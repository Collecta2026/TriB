"""Sales posting rules.

Invoice:   Dr Customers (AR)          total
               Cr Sales / income      per line, net
               Cr VAT output          VAT
           Dr Cost of goods sold      FIFO cost   (stock items)
               Cr Inventory           FIFO cost
Payment:   Dr Bank / cash / cheques in the safe   amount × payment rate
               Cr Customers (AR)       allocated × invoice rate, rest × payment rate
           ± Exchange gain / loss      the difference
"""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from banking.models import Cheque
from core.documents import r2
from core.models import AuditLog, NumberSeries
from inventory.services import StockError, cogs_account, inventory_account, issue, parse_serials, receive
from ledger.services import Line, PostingError, post_journal, reverse_journal, system_account

from .models import CustomerPayment, Invoice, InvoiceLine, PaymentAllocation, SalesOrder, SalesOrderLine

ZERO = Decimal("0")


class SalesError(Exception):
    pass


def income_account(line):
    if line.account_id:
        return line.account
    if line.item_id and line.item.income_account_id:
        return line.item.income_account
    return system_account(line.document.company, "sales")


def customer_balance(customer, as_of=None):
    """What the customer owes, in the customer's currency (posted invoices less payments)."""
    inv = Invoice.objects.filter(customer=customer, status="posted")
    pay = CustomerPayment.objects.filter(customer=customer, status="posted")
    if as_of:
        inv, pay = inv.filter(date__lte=as_of), pay.filter(date__lte=as_of)
    from banking.services import returned_cheques_balance
    return (sum((i.total for i in inv), ZERO) - sum((p.amount for p in pay), ZERO)
            + returned_cheques_balance(customer, as_of))


@transaction.atomic
def post_invoice(invoice, user, allow_over_limit=False):
    if invoice.status != "draft":
        raise SalesError(_("Only draft invoices can be posted."))
    company = invoice.company
    lines = list(invoice.lines.select_related("item", "tax_rate", "account", "project"))
    if not lines:
        raise SalesError(_("Add at least one line."))
    if any(l.qty <= 0 for l in lines):
        raise SalesError(_("Every line needs a quantity greater than zero."))
    if any(l.item_id and l.item.is_stocked for l in lines) and not invoice.warehouse_id:
        raise SalesError(_("Choose the warehouse the goods are shipped from."))
    customer = invoice.customer
    if customer.credit_limit and not allow_over_limit:
        owed = customer_balance(customer) + invoice.total
        if owed > customer.credit_limit:
            raise SalesError(_("This invoice takes %(c)s over the credit limit of %(l)s.") % {
                "c": customer.name, "l": f"{customer.credit_limit:,.2f}"})

    if not invoice.number:
        invoice.number = NumberSeries.next(company, "INV", invoice.date)
    rate, cur = invoice.rate, invoice.currency_id
    memo = f"{invoice.number} {customer.name}"
    journal, vat = [], defaultdict(Decimal)
    for line in lines:
        base = r2(line.net * rate)
        journal.append(Line(income_account(line), credit=base, description=line.label[:300] or memo, project=line.project,
                            currency=cur, amount_fc=line.net, rate=rate))
        if line.tax:
            vat[line.tax_rate_id] += line.tax
        if line.item_id and line.item.is_stocked:
            try:
                cost, _parts = issue(line.item, invoice.warehouse, line.qty, invoice.date, invoice.number,
                                     serials=parse_serials(line.serials))
            except StockError as exc:
                raise SalesError(str(exc)) from exc
            line.cost = cost
            line.save(update_fields=["cost"])
            if cost:
                journal += [Line(cogs_account(line.item), debit=cost, description=line.item.sku, project=line.project),
                            Line(inventory_account(line.item), credit=cost, description=line.item.sku)]
    vat_account = system_account(company, "vat_output")
    for tax_id, amount in vat.items():
        journal.append(Line(vat_account, credit=r2(amount * rate), description=_("VAT"), currency=cur, amount_fc=amount, rate=rate))
    ar_base = sum((l.credit for l in journal), ZERO) - sum((l.debit for l in journal), ZERO)
    journal.insert(0, Line(system_account(company, "receivable"), debit=ar_base, description=memo, currency=cur,
                           amount_fc=invoice.total, rate=rate))
    try:
        invoice.journal_entry = post_journal(company, invoice.date, journal, memo=memo, source="invoice",
                                             source_ref=invoice.number, user=user, branch=invoice.branch)
    except PostingError as exc:
        raise SalesError(str(exc)) from exc
    invoice.status = "posted"
    invoice.posted_at = timezone.now()
    invoice.save(update_fields=["number", "status", "journal_entry", "posted_at"])
    if invoice.sales_order_id:
        invoice.sales_order.refresh_status()
    AuditLog.record(company, user, "invoice.posted", invoice, f"{invoice.number} {invoice.total}")
    return invoice


@transaction.atomic
def void_invoice(invoice, user, date=None):
    if invoice.status != "posted":
        raise SalesError(_("Only posted invoices can be voided."))
    if invoice.amount_paid:
        raise SalesError(_("Remove the payments allocated to this invoice first."))
    date = date or timezone.localdate()
    reverse_journal(invoice.journal_entry, date, user, _("Void %(n)s") % {"n": invoice.number})
    # Put the goods back at the cost they left at.
    from inventory.models import StockMove
    for move in StockMove.objects.filter(company=invoice.company, ref=invoice.number, kind="issue").select_related("item", "layer"):
        receive(move.item, move.warehouse, -move.qty, move.unit_cost, date, invoice.number, kind="return",
                serials=[move.serial_no] if move.serial_no else None, batch_no=move.batch_no,
                expiry_date=move.layer.expiry_date if move.layer else None)
    invoice.status = "void"
    invoice.save(update_fields=["status"])
    if invoice.sales_order_id:
        invoice.sales_order.refresh_status()
    AuditLog.record(invoice.company, user, "invoice.void", invoice, invoice.number)


@transaction.atomic
def post_payment(payment, allocations, user):
    """allocations: [(invoice, amount)] in the payment currency."""
    company = payment.company
    if payment.amount <= 0:
        raise SalesError(_("The amount must be greater than zero."))
    total_alloc = sum((a for _i, a in allocations), ZERO)
    if total_alloc > payment.amount:
        raise SalesError(_("You allocated more than the amount received."))
    for invoice, amount in allocations:
        if invoice.customer_id != payment.customer_id or invoice.currency_id != payment.currency_id:
            raise SalesError(_("Invoice %(n)s belongs to another customer or currency.") % {"n": invoice.number})
        if amount > invoice.balance_due:
            raise SalesError(_("%(n)s only has %(b)s left to pay.") % {"n": invoice.number, "b": f"{invoice.balance_due:,.2f}"})
    if payment.method in ("cash", "bank") and not payment.bank_account_id:
        raise SalesError(_("Choose the cash box or bank account."))
    if payment.method == "cheque" and not (payment.cheque_number and payment.cheque_due_date):
        raise SalesError(_("Enter the cheque number and due date."))

    payment.number = payment.number or NumberSeries.next(company, "RC", payment.date)
    payment.save()
    cur, rate = payment.currency_id, payment.rate
    memo = f"{payment.number} {payment.customer.name}"
    money_base = r2(payment.amount * rate)
    money_account = (system_account(company, "notes_receivable") if payment.method == "cheque"
                     else payment.bank_account.gl_account)
    ar = system_account(company, "receivable")
    lines = [Line(money_account, debit=money_base, description=memo, currency=cur, amount_fc=payment.amount, rate=rate)]
    ar_base = ZERO
    for invoice, amount in allocations:
        if amount <= 0:
            continue
        PaymentAllocation.objects.create(payment=payment, invoice=invoice, amount=amount)
        invoice.amount_paid += amount
        invoice.save(update_fields=["amount_paid"])
        base = r2(amount * invoice.rate)
        ar_base += base
        lines.append(Line(ar, credit=base, description=invoice.number, currency=cur, amount_fc=amount, rate=invoice.rate))
    rest = payment.amount - total_alloc
    if rest > 0:
        base = money_base - ar_base if not ar_base else r2(rest * rate)
        ar_base += base
        lines.append(Line(ar, credit=base, description=_("Unallocated"), currency=cur, amount_fc=rest, rate=rate))
    diff = money_base - ar_base
    if diff > 0:
        lines.append(Line(system_account(company, "fx_gain"), credit=diff, description=_("Exchange difference")))
    elif diff < 0:
        lines.append(Line(system_account(company, "fx_loss"), debit=-diff, description=_("Exchange difference")))
    try:
        payment.journal_entry = post_journal(company, payment.date, lines, memo=memo, source="customer_payment",
                                             source_ref=payment.number, user=user)
    except PostingError as exc:
        raise SalesError(str(exc)) from exc
    if payment.method == "cheque":
        payment.cheque = Cheque.objects.create(
            company=company, direction="in", number=payment.cheque_number, drawee_bank=payment.cheque_bank,
            party_name=payment.customer.name, amount=payment.amount, currency_id=cur, rate=rate,
            issue_date=payment.date, due_date=payment.cheque_due_date, status="in_safe", counter_account=ar,
            source_ref=payment.number, created_by=user, customer=payment.customer)
    payment.save(update_fields=["journal_entry", "cheque", "number"])
    AuditLog.record(company, user, "customer_payment.posted", payment, f"{payment.number} {payment.amount}")
    return payment


@transaction.atomic
def void_payment(payment, user, date=None):
    if payment.status != "posted":
        raise SalesError(_("This payment is already void."))
    if payment.cheque_id and payment.cheque.status != "in_safe":
        raise SalesError(_("The cheque has already moved on; bounce or reverse it from Cheques."))
    date = date or timezone.localdate()
    reverse_journal(payment.journal_entry, date, user, _("Void %(n)s") % {"n": payment.number})
    for alloc in payment.allocations.select_related("invoice"):
        alloc.invoice.amount_paid -= alloc.amount
        alloc.invoice.save(update_fields=["amount_paid"])
    payment.allocations.all().delete()
    if payment.cheque_id:
        payment.cheque.status = "cancelled"
        payment.cheque.save(update_fields=["status"])
    payment.status = "void"
    payment.save(update_fields=["status"])
    AuditLog.record(payment.company, user, "customer_payment.void", payment, payment.number)


def copy_lines(source, target, line_model, link_field=None, qty_attr="qty"):
    for line in source.lines.all():
        qty = getattr(line, qty_attr)
        if qty <= 0:
            continue
        data = {f: getattr(line, f) for f in ("item_id", "description", "unit_price", "discount_pct", "tax_rate_id",
                                               "project_id", "account_id")}
        if link_field:
            data[link_field] = line
        line_model.objects.create(document=target, qty=qty, **data)


@transaction.atomic
def quote_to_order(quote, user):
    order = SalesOrder.objects.create(company=quote.company, branch=quote.branch, date=timezone.localdate(),
                                      customer=quote.customer, currency=quote.currency, rate=quote.rate,
                                      reference=quote.reference, notes=quote.notes, quotation=quote, created_by=user)
    copy_lines(quote, order, SalesOrderLine)
    quote.status = "converted"
    quote.save(update_fields=["status"])
    return order


@transaction.atomic
def order_to_invoice(order, user):
    today = timezone.localdate()
    invoice = Invoice.objects.create(company=order.company, branch=order.branch, date=today,
                                     due_date=today + timedelta(days=order.customer.payment_terms_days),
                                     customer=order.customer, currency=order.currency, rate=order.rate,
                                     reference=order.reference, warehouse=order.warehouse, sales_order=order,
                                     created_by=user)
    copy_lines(order, invoice, InvoiceLine, link_field="order_line", qty_attr="qty_open")
    return invoice


@transaction.atomic
def quote_to_invoice(quote, user):
    today = timezone.localdate()
    invoice = Invoice.objects.create(company=quote.company, branch=quote.branch, date=today,
                                     due_date=today + timedelta(days=quote.customer.payment_terms_days),
                                     customer=quote.customer, currency=quote.currency, rate=quote.rate,
                                     reference=quote.reference, created_by=user)
    copy_lines(quote, invoice, InvoiceLine)
    quote.status = "converted"
    quote.save(update_fields=["status"])
    return invoice


AGING_BUCKETS = [(0, gettext_lazy("Current")), (30, gettext_lazy("1–30 days")), (60, gettext_lazy("31–60 days")),
                 (90, gettext_lazy("61–90 days")),
                 (None, gettext_lazy("Over 90 days"))]


def bucket_for(days_overdue):
    if days_overdue <= 0:
        return 0
    if days_overdue <= 30:
        return 1
    if days_overdue <= 60:
        return 2
    if days_overdue <= 90:
        return 3
    return 4


def ar_aging(company, as_of=None):
    """Per customer: open balance split into ageing buckets, in base currency."""
    as_of = as_of or timezone.localdate()
    rows = {}
    for inv in Invoice.objects.filter(company=company, status="posted", date__lte=as_of).select_related("customer"):
        due = inv.balance_due
        if due <= 0:
            continue
        row = rows.setdefault(inv.customer_id, {"contact": inv.customer, "buckets": [ZERO] * 5, "total": ZERO})
        base = r2(due * inv.rate)
        row["buckets"][bucket_for((as_of - inv.due_date).days)] += base
        row["total"] += base
    for pay in CustomerPayment.objects.filter(company=company, status="posted", date__lte=as_of).select_related("customer"):
        if pay.unallocated > 0:
            row = rows.setdefault(pay.customer_id, {"contact": pay.customer, "buckets": [ZERO] * 5, "total": ZERO})
            base = r2(pay.unallocated * pay.rate)
            row["buckets"][0] -= base
            row["total"] -= base
    # Cheques the bank returned are owed again from the day they came back.
    from banking.models import Cheque
    for chq in Cheque.objects.filter(company=company, status="bounced", customer__isnull=False,
                                     bounced_on__lte=as_of).select_related("customer"):
        row = rows.setdefault(chq.customer_id, {"contact": chq.customer, "buckets": [ZERO] * 5, "total": ZERO})
        base = chq.base_amount
        row["buckets"][bucket_for((as_of - chq.bounced_on).days)] += base
        row["total"] += base
    return sorted(rows.values(), key=lambda r: -r["total"])


def statement(customer, date_from, date_to):
    """Opening balance, transactions and closing balance for a customer statement (customer currency)."""
    opening = customer_balance(customer, as_of=date_from - timedelta(days=1))
    events = []
    for inv in Invoice.objects.filter(customer=customer, status="posted", date__gte=date_from, date__lte=date_to):
        events.append((inv.date, 0, inv.number, _("Invoice"), inv.total, ZERO, inv.due_date))
    for pay in CustomerPayment.objects.filter(customer=customer, status="posted", date__gte=date_from, date__lte=date_to):
        events.append((pay.date, 1, pay.number, _("Payment received"), ZERO, pay.amount, None))
    from banking.models import ChequeEvent
    labels = {"bounced": _("Cheque %(n)s returned unpaid"), "resubmitted": _("Cheque %(n)s resubmitted"),
              "settled": _("Returned cheque %(n)s settled")}
    for ev in ChequeEvent.objects.filter(cheque__customer=customer, action__in=labels, date__gte=date_from,
                                         date__lte=date_to).select_related("cheque"):
        debit, credit = (ev.amount, ZERO) if ev.action == "bounced" else (ZERO, ev.amount)
        events.append((ev.date, 2, f"#{ev.cheque.number}", labels[ev.action] % {"n": ev.cheque.number}, debit, credit,
                       None))
    events.sort(key=lambda e: (e[0], e[1]))
    running, rows = opening, []
    for date, _o, number, kind, debit, credit, due in events:
        running += debit - credit
        rows.append({"date": date, "number": number, "kind": kind, "debit": debit, "credit": credit, "balance": running,
                     "due": due})
    aging = [ZERO] * 5
    for inv in Invoice.objects.filter(customer=customer, status="posted", date__lte=date_to):
        if inv.balance_due > 0:
            aging[bucket_for((date_to - inv.due_date).days)] += inv.balance_due
    return {"opening": opening, "rows": rows, "closing": running, "aging": aging}
