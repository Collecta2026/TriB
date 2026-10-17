"""Sales posting rules.

Invoice:   Dr Customers (AR)          total
               Cr Sales / income      per line, net
               Cr VAT output          VAT
           Dr Cost of goods sold      FIFO cost   (stock items)
               Cr Inventory           FIFO cost
Credit note: the invoice in reverse (Dr income, Dr VAT output, Cr AR); returned goods Dr Inventory / Cr COGS.
Refund:    Dr Customers (AR) / Cr Bank or cash.
Payment:   Dr Bank / cash / cheques in the safe   amount × payment rate
               Cr Customers (AR)       allocated × invoice rate, rest × payment rate
           ± Exchange gain / loss      the difference
"""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from banking.models import Cheque
from core.documents import r2
from core.models import AuditLog, NumberSeries
from inventory.services import StockError, cogs_account, inventory_account, issue, parse_serials, receive
from ledger.services import Line, PostingError, post_journal, reverse_journal, system_account

from .models import (CreditAllocation, CreditNote, CustomerPayment, CustomerRefund, Invoice, InvoiceLine, PaymentAllocation,
                     SalesOrder, SalesOrderLine)

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
    notes = CreditNote.objects.filter(customer=customer, status="posted")
    refunds = CustomerRefund.objects.filter(customer=customer, status="posted")
    if as_of:
        notes, refunds = notes.filter(date__lte=as_of), refunds.filter(date__lte=as_of)
    return (sum((i.total for i in inv), ZERO) - sum((p.amount for p in pay), ZERO)
            - sum((n.total for n in notes), ZERO) + sum((r.amount for r in refunds), ZERO)
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
    order = SalesOrder.objects.create(company=quote.company, prices_include_tax=quote.prices_include_tax, branch=quote.branch, date=timezone.localdate(),
                                      customer=quote.customer, currency=quote.currency, rate=quote.rate,
                                      reference=quote.reference, notes=quote.notes, quotation=quote, created_by=user)
    copy_lines(quote, order, SalesOrderLine)
    quote.status = "converted"
    quote.save(update_fields=["status"])
    return order


@transaction.atomic
def order_to_invoice(order, user):
    today = timezone.localdate()
    invoice = Invoice.objects.create(company=order.company, prices_include_tax=order.prices_include_tax, branch=order.branch, date=today,
                                     due_date=today + timedelta(days=order.customer.payment_terms_days),
                                     customer=order.customer, currency=order.currency, rate=order.rate,
                                     reference=order.reference, warehouse=order.warehouse, sales_order=order,
                                     created_by=user)
    copy_lines(order, invoice, InvoiceLine, link_field="order_line", qty_attr="qty_open")
    return invoice


@transaction.atomic
def quote_to_invoice(quote, user):
    today = timezone.localdate()
    invoice = Invoice.objects.create(company=quote.company, prices_include_tax=quote.prices_include_tax, branch=quote.branch, date=today,
                                     due_date=today + timedelta(days=quote.customer.payment_terms_days),
                                     customer=quote.customer, currency=quote.currency, rate=quote.rate,
                                     reference=quote.reference, created_by=user)
    copy_lines(quote, invoice, InvoiceLine)
    quote.status = "converted"
    quote.save(update_fields=["status"])
    return invoice


# Ageing columns: days past the due date. (upper limit of the column, label)
AGING_BUCKETS = [(0, gettext_lazy("Current")), (30, gettext_lazy("1–30 days")), (60, gettext_lazy("31–60 days")),
                 (90, gettext_lazy("61–90 days")), (120, gettext_lazy("91–120 days")),
                 (None, gettext_lazy("Over 120 days"))]


def bucket_for(days_overdue):
    """The ageing column for an amount this many days past its due date."""
    for i, (limit, _label) in enumerate(AGING_BUCKETS):
        if limit is None or days_overdue <= limit:
            return i
    return len(AGING_BUCKETS) - 1


def no_buckets():
    return [ZERO] * len(AGING_BUCKETS)


def ar_aging(company, as_of=None):
    """Per customer: open balance split into ageing buckets, in base currency."""
    as_of = as_of or timezone.localdate()
    rows = {}
    for inv in Invoice.objects.filter(company=company, status="posted", date__lte=as_of).select_related("customer"):
        due = inv.balance_due
        if due <= 0:
            continue
        row = rows.setdefault(inv.customer_id, {"contact": inv.customer, "buckets": no_buckets(), "total": ZERO})
        base = r2(due * inv.rate)
        row["buckets"][bucket_for((as_of - inv.due_date).days)] += base
        row["total"] += base
    for pay in CustomerPayment.objects.filter(company=company, status="posted", date__lte=as_of).select_related("customer"):
        if pay.unallocated > 0:
            row = rows.setdefault(pay.customer_id, {"contact": pay.customer, "buckets": no_buckets(), "total": ZERO})
            base = r2(pay.unallocated * pay.rate)
            row["buckets"][0] -= base
            row["total"] -= base
    # Credit not yet used against an invoice or refunded reduces what the customer owes.
    for note in CreditNote.objects.filter(company=company, status="posted", date__lte=as_of).select_related("customer"):
        if note.available > 0:
            row = rows.setdefault(note.customer_id, {"contact": note.customer, "buckets": no_buckets(), "total": ZERO})
            base = r2(note.available * note.rate)
            row["buckets"][0] -= base
            row["total"] -= base
    # Refunds of overpayments (not tied to a credit note) cancel out the unallocated payment above.
    for ref in CustomerRefund.objects.filter(company=company, status="posted", credit_note__isnull=True,
                                             date__lte=as_of).select_related("customer"):
        row = rows.setdefault(ref.customer_id, {"contact": ref.customer, "buckets": no_buckets(), "total": ZERO})
        base = r2(ref.amount * ref.rate)
        row["buckets"][0] += base
        row["total"] += base
    # Cheques the bank returned are owed again from the day they came back.
    from banking.models import Cheque
    for chq in Cheque.objects.filter(company=company, status="bounced", customer__isnull=False,
                                     bounced_on__lte=as_of).select_related("customer"):
        row = rows.setdefault(chq.customer_id, {"contact": chq.customer, "buckets": no_buckets(), "total": ZERO})
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
    for note in CreditNote.objects.filter(customer=customer, status="posted", date__gte=date_from, date__lte=date_to):
        events.append((note.date, 1, note.number, _("Credit note"), ZERO, note.total, None))
    for ref in CustomerRefund.objects.filter(customer=customer, status="posted", date__gte=date_from, date__lte=date_to):
        events.append((ref.date, 2, ref.number, _("Refund"), ref.amount, ZERO, None))
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
    return {"opening": opening, "rows": rows, "closing": running, "aging": open_items(customer, date_to)["aging"]}


def open_items(customer, as_of):
    """Open-item statement: every unpaid invoice with its age, then payments and credits not yet used and returned
    cheques, in the customer's currency. The ageing line adds them up by column (days past the due date)."""
    rows = []
    for inv in (Invoice.objects.filter(customer=customer, status="posted", date__lte=as_of)
                .prefetch_related("lines__tax_rate").order_by("due_date", "id")):
        open_ = inv.balance_due
        if open_ > 0:
            days = (as_of - inv.due_date).days
            rows.append({"date": inv.date, "number": inv.number, "ref": inv.reference, "kind": _("Invoice"),
                         "due": inv.due_date, "days": max(days, 0), "amount": inv.total, "settled": inv.total - open_,
                         "open": open_, "bucket": bucket_for(days)})
    from banking.models import Cheque
    for chq in Cheque.objects.filter(customer=customer, status="bounced", bounced_on__lte=as_of).order_by("bounced_on"):
        days = (as_of - chq.bounced_on).days
        rows.append({"date": chq.bounced_on, "number": f"#{chq.number}", "ref": chq.bounce_reason,
                     "kind": _("Returned cheque"), "due": chq.bounced_on, "days": max(days, 0), "amount": chq.amount,
                     "settled": ZERO, "open": chq.amount, "bucket": bucket_for(days)})
    on_account = sum((p.unallocated for p in CustomerPayment.objects.filter(customer=customer, status="posted",
                                                                             date__lte=as_of)), ZERO)
    on_account -= CustomerRefund.objects.filter(customer=customer, status="posted", credit_note__isnull=True,
                                                date__lte=as_of).aggregate(s=Sum("amount"))["s"] or ZERO
    if on_account > 0:
        rows.append({"date": as_of, "number": "", "ref": "", "kind": _("Payments not yet applied to an invoice"),
                     "due": None, "days": None, "amount": None, "settled": None, "open": -on_account, "bucket": 0})
    for note in CreditNote.objects.filter(customer=customer, status="posted", date__lte=as_of).order_by("date", "id"):
        if note.available > 0:
            rows.append({"date": note.date, "number": note.number, "ref": note.reference,
                         "kind": _("Credit note not yet used"), "due": None, "days": None, "amount": None,
                         "settled": None, "open": -note.available, "bucket": 0})
    aging = no_buckets()
    for r in rows:
        aging[r["bucket"]] += r["open"]
    return {"rows": rows, "aging": aging, "total": sum(aging, ZERO), "as_of": as_of}

# ---------- Credit notes ----------
def _return_cost(note, line):
    """Unit cost (base currency) for returned goods: what they cost when sold on the original invoice, else the
    product's purchase cost."""
    if note.invoice_id:
        sold = note.invoice.lines.filter(item=line.item, qty__gt=0).first()
        if sold and sold.cost:
            return (sold.cost / sold.qty).quantize(Decimal("0.0001"))
    return line.item.purchase_cost


@transaction.atomic
def post_credit_note(note, user):
    if note.status != "draft":
        raise SalesError(_("Only draft credit notes can be posted."))
    company = note.company
    lines = list(note.lines.select_related("item", "tax_rate", "account", "project"))
    if not lines:
        raise SalesError(_("Add at least one line."))
    if any(l.qty <= 0 for l in lines):
        raise SalesError(_("Every line needs a quantity greater than zero."))
    if note.invoice_id and (note.invoice.customer_id != note.customer_id or note.invoice.currency_id != note.currency_id):
        raise SalesError(_("The original invoice belongs to another customer or currency."))
    returning = [l for l in lines if l.item_id and l.item.is_stocked and l.return_to_stock]
    if returning and not note.warehouse_id:
        raise SalesError(_("Choose the warehouse the goods come back to."))
    note.number = note.number or NumberSeries.next(company, "CN", note.date)
    rate, cur = note.rate, note.currency_id
    memo = f"{note.number} {note.customer.name}"
    journal, vat = [], defaultdict(Decimal)
    for line in lines:
        journal.append(Line(income_account(line), debit=r2(line.net * rate), description=line.label[:300] or memo,
                            project=line.project, currency=cur, amount_fc=line.net, rate=rate))
        if line.tax:
            vat[line.tax_rate_id] += line.tax
        if line in returning:
            try:
                value = receive(line.item, note.warehouse, line.qty, _return_cost(note, line), note.date, note.number,
                                kind="return", serials=parse_serials(line.serials), batch_no=line.batch_no,
                                expiry_date=line.expiry_date)
            except StockError as exc:
                raise SalesError(str(exc)) from exc
            line.cost = value
            line.save(update_fields=["cost"])
            if value:
                journal += [Line(inventory_account(line.item), debit=value, description=line.item.sku),
                            Line(cogs_account(line.item), credit=value, description=line.item.sku, project=line.project)]
    vat_account = system_account(company, "vat_output")
    for _tax, amount in vat.items():
        journal.append(Line(vat_account, debit=r2(amount * rate), description=_("VAT"), currency=cur, amount_fc=amount, rate=rate))
    ar_base = sum((l.debit for l in journal), ZERO) - sum((l.credit for l in journal), ZERO)
    journal.append(Line(system_account(company, "receivable"), credit=ar_base, description=memo, currency=cur,
                        amount_fc=note.total, rate=rate))
    try:
        note.journal_entry = post_journal(company, note.date, journal, memo=memo, source="invoice",
                                          source_ref=note.number, user=user, branch=note.branch)
    except PostingError as exc:
        raise SalesError(str(exc)) from exc
    note.status, note.posted_at = "posted", timezone.now()
    note.save(update_fields=["number", "status", "journal_entry", "posted_at"])
    if note.invoice_id and note.invoice.status == "posted" and note.invoice.balance_due > 0:
        apply_credit(note, note.invoice, min(note.available, note.invoice.balance_due), user)
    AuditLog.record(company, user, "credit_note.posted", note, f"{note.number} {note.total}")
    return note


@transaction.atomic
def apply_credit(note, invoice, amount, user=None, date=None):
    """Set part of a credit note against an invoice of the same customer (no journal: both sit in AR)."""
    amount = Decimal(amount)
    if amount <= 0:
        raise SalesError(_("The amount must be greater than zero."))
    if invoice.customer_id != note.customer_id or invoice.currency_id != note.currency_id:
        raise SalesError(_("Invoice %(n)s belongs to another customer or currency.") % {"n": invoice.number})
    if amount > note.available:
        raise SalesError(_("Only %(a)s of this credit is still available.") % {"a": f"{note.available:,.2f}"})
    if amount > invoice.balance_due:
        raise SalesError(_("%(n)s only has %(b)s left to pay.") % {"n": invoice.number, "b": f"{invoice.balance_due:,.2f}"})
    CreditAllocation.objects.create(credit_note=note, invoice=invoice, amount=amount, date=date or timezone.localdate())
    invoice.amount_paid += amount
    invoice.save(update_fields=["amount_paid"])
    note.amount_applied += amount
    note.save(update_fields=["amount_applied"])
    AuditLog.record(note.company, user, "credit_note.applied", note, f"{invoice.number} {amount}")


@transaction.atomic
def void_credit_note(note, user, date=None):
    if note.status != "posted":
        raise SalesError(_("Only posted credit notes can be voided."))
    if note.amount_applied or note.amount_refunded:
        raise SalesError(_("Remove what this credit was used for first."))
    date = date or timezone.localdate()
    from inventory.models import StockMove
    for move in StockMove.objects.filter(company=note.company, ref=note.number, kind="return", qty__gt=0).select_related("item"):
        try:
            issue(move.item, move.warehouse, move.qty, date, note.number, kind="return",
                  serials=[move.serial_no] if move.serial_no else None)
        except StockError as exc:
            raise SalesError(str(exc)) from exc
    reverse_journal(note.journal_entry, date, user, _("Void %(n)s") % {"n": note.number})
    note.status = "void"
    note.save(update_fields=["status"])
    AuditLog.record(note.company, user, "credit_note.void", note, note.number)


def available_credit(customer):
    """Credit a customer can be refunded: unused credit notes plus unallocated payments, less earlier refunds of them."""
    notes = sum((n.available for n in CreditNote.objects.filter(customer=customer, status="posted")), ZERO)
    payments = sum((p.unallocated for p in CustomerPayment.objects.filter(customer=customer, status="posted")), ZERO)
    refunded = sum((r.amount for r in CustomerRefund.objects.filter(customer=customer, status="posted",
                                                                       credit_note__isnull=True)), ZERO)
    return notes + payments - refunded


@transaction.atomic
def post_refund(refund, user):
    company = refund.company
    if refund.amount <= 0:
        raise SalesError(_("The amount must be greater than zero."))
    if refund.bank_account.currency_id != refund.currency_id:
        raise SalesError(_("Pay the refund from an account in %(c)s.") % {"c": refund.currency_id})
    if refund.credit_note_id:
        note = refund.credit_note
        if note.customer_id != refund.customer_id:
            raise SalesError(_("This credit note belongs to another customer."))
        if refund.amount > note.available:
            raise SalesError(_("Only %(a)s of this credit is still available.") % {"a": f"{note.available:,.2f}"})
    elif refund.amount > available_credit(refund.customer):
        raise SalesError(_("The customer only has %(a)s of credit to refund.") % {"a": f"{available_credit(refund.customer):,.2f}"})
    refund.number = refund.number or NumberSeries.next(company, "RF", refund.date)
    refund.save()
    base = r2(refund.amount * refund.rate)
    memo = f"{refund.number} {refund.customer.name}"
    try:
        refund.journal_entry = post_journal(company, refund.date, [
            Line(system_account(company, "receivable"), debit=base, description=memo, currency=refund.currency_id,
                 amount_fc=refund.amount, rate=refund.rate),
            Line(refund.bank_account.gl_account, credit=base, description=memo, currency=refund.currency_id,
                 amount_fc=refund.amount, rate=refund.rate),
        ], memo=memo, source="customer_payment", source_ref=refund.number, user=user)
    except PostingError as exc:
        raise SalesError(str(exc)) from exc
    refund.save(update_fields=["journal_entry", "number"])
    if refund.credit_note_id:
        refund.credit_note.amount_refunded += refund.amount
        refund.credit_note.save(update_fields=["amount_refunded"])
    AuditLog.record(company, user, "customer_refund.posted", refund, f"{refund.number} {refund.amount}")
    return refund


@transaction.atomic
def void_refund(refund, user, date=None):
    if refund.status != "posted":
        raise SalesError(_("This refund is already void."))
    reverse_journal(refund.journal_entry, date or timezone.localdate(), user, _("Void %(n)s") % {"n": refund.number})
    if refund.credit_note_id:
        refund.credit_note.amount_refunded -= refund.amount
        refund.credit_note.save(update_fields=["amount_refunded"])
    refund.status = "void"
    refund.save(update_fields=["status"])
    AuditLog.record(refund.company, user, "customer_refund.void", refund, refund.number)


@transaction.atomic
def post_sales_receipt(invoice, deposit_to, user):
    """A cash sale: post the invoice and record its full payment into the cash box or bank in one step."""
    post_invoice(invoice, user, allow_over_limit=True)
    payment = CustomerPayment(company=invoice.company, date=invoice.date, customer=invoice.customer,
                              currency=invoice.currency, rate=invoice.rate, amount=invoice.total,
                              method="cash" if deposit_to.kind == "cash" else "bank", bank_account=deposit_to,
                              reference=invoice.number, created_by=user)
    post_payment(payment, [(invoice, invoice.total)], user)
    return payment
