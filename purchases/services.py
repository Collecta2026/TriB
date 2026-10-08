"""Purchasing posting rules.

Item receipt (GRN):  Dr Inventory               qty × PO cost (base)
                         Cr Goods received not invoiced (GRNI)
Bill:                Dr GRNI                    for received lines, at the receipt value
                     Dr/Cr Purchase price variance   bill price − receipt price
                     Dr Inventory               stock billed without a receipt (received on the bill)
                     Dr Expense                 services and non-stock items
                     Dr VAT input
                         Cr Suppliers (AP)      total
Supplier payment:    Dr Suppliers (AP)          allocated × bill rate, rest × payment rate
                         Cr Bank / cash / cheques issued   amount × payment rate
                     ± Exchange gain / loss
"""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from banking.models import Cheque
from core.documents import r2
from core.models import AuditLog, ExchangeRate, NumberSeries
from inventory.services import StockError, inventory_account, parse_serials, receive
from ledger.services import Line, PostingError, post_journal, reverse_journal, system_account

from .models import (Bill, BillAllocation, BillLine, GoodsReceipt, GoodsReceiptLine, PurchaseOrder,
                     PurchaseOrderLine, SupplierPayment)

ZERO = Decimal("0")


class PurchaseError(Exception):
    pass


# ---------- Purchase orders ----------
@transaction.atomic
def submit_order(order, user):
    if order.status != "draft":
        raise PurchaseError(_("Only draft purchase orders can be submitted."))
    if not order.lines.exists():
        raise PurchaseError(_("Add at least one line."))
    order.number = order.number or NumberSeries.next(order.company, "PO", order.date)
    order.status = "submitted"
    order.save(update_fields=["number", "status"])
    AuditLog.record(order.company, user, "po.submitted", order, order.number)


@transaction.atomic
def approve_order(order, user, membership):
    if order.status != "submitted":
        raise PurchaseError(_("This purchase order is not waiting for approval."))
    if order.company.enforce_sod and order.created_by_id == user.id and not membership.is_owner:
        raise PurchaseError(_("You created this document, so someone else must approve it."))
    order.status = "open"
    order.approved_by, order.approved_at = user, timezone.now()
    order.save(update_fields=["status", "approved_by", "approved_at"])
    AuditLog.record(order.company, user, "po.approved", order, order.number)


@transaction.atomic
def reject_order(order, user, reason):
    if order.status != "submitted":
        raise PurchaseError(_("This purchase order is not waiting for approval."))
    order.status = "draft"
    order.notes = (order.notes + "\n" if order.notes else "") + _("Returned: %(r)s") % {"r": reason}
    order.save(update_fields=["status", "notes"])
    AuditLog.record(order.company, user, "po.rejected", order, reason)


def outstanding_lines(company, supplier=None):
    """Purchase-order lines ordered but not yet fully received into the warehouse."""
    lines = PurchaseOrderLine.objects.filter(document__company=company, document__status__in=("open", "partial"))
    if supplier is not None:
        lines = lines.filter(document__supplier=supplier)
    return [l for l in lines.select_related("document", "document__supplier", "item") if l.qty_outstanding > 0]


def billed_not_received(company):
    """Stock lines billed against a purchase order where the goods have not all arrived."""
    out = []
    for line in PurchaseOrderLine.objects.filter(document__company=company, item__type="inventory").select_related(
            "document", "item"):
        billed_direct = sum((b.qty for b in line.bill_lines.filter(document__status="posted", receipt_line__isnull=True)),
                            ZERO)
        if line.qty_billed > line.qty_received and not billed_direct:
            out.append(line)
    return out


@transaction.atomic
def receipt_from_order(order, user, date=None):
    if order.status not in ("open", "partial"):
        raise PurchaseError(_("Only approved purchase orders can be received."))
    if not order.warehouse_id:
        raise PurchaseError(_("Set the delivery warehouse on the purchase order first."))
    grn = GoodsReceipt.objects.create(company=order.company, date=date or timezone.localdate(), supplier=order.supplier,
                                      purchase_order=order, warehouse=order.warehouse, created_by=user)
    for line in order.lines.select_related("item"):
        if line.item_id and line.qty_outstanding > 0:
            GoodsReceiptLine.objects.create(document=grn, order_line=line, item=line.item, description=line.label,
                                            qty=line.qty_outstanding, unit_cost=line.unit_price)
    return grn


# ---------- Item receipts ----------
def _rate(company, currency, date, fallback):
    rate = ExchangeRate.rate_for(company, currency, date)
    return rate if rate is not None else fallback


@transaction.atomic
def post_receipt(grn, user):
    if grn.status != "draft":
        raise PurchaseError(_("This item receipt is already posted."))
    company = grn.company
    lines = list(grn.lines.select_related("item", "order_line", "order_line__document"))
    if not lines:
        raise PurchaseError(_("Add at least one line."))
    order = grn.purchase_order
    currency = order.currency_id if order else company.base_currency_id
    rate = order.rate if order else Decimal("1")
    for line in lines:
        if line.qty <= 0:
            raise PurchaseError(_("Every line needs a quantity greater than zero."))
        if line.order_line_id and line.qty > line.order_line.qty_outstanding:
            raise PurchaseError(_("%(sku)s: you are receiving more than is still outstanding on the order (%(q)s).") % {
                "sku": line.item.sku, "q": line.order_line.qty_outstanding.normalize()})
    grn.number = grn.number or NumberSeries.next(company, "GRN", grn.date)
    journal = []
    grni = system_account(company, "grni")
    for line in lines:
        line.unit_cost_base = (Decimal(line.unit_cost) * rate).quantize(Decimal("0.0001"))
        line.save(update_fields=["unit_cost_base"])
        if not line.item.is_stocked:
            continue
        try:
            value = receive(line.item, grn.warehouse, line.qty, line.unit_cost_base, grn.date, grn.number,
                            serials=parse_serials(line.serials), batch_no=line.batch_no, expiry_date=line.expiry_date)
        except StockError as exc:
            raise PurchaseError(str(exc)) from exc
        if value:
            journal += [Line(inventory_account(line.item), debit=value, description=f"{line.item.sku} {grn.number}"),
                        Line(grni, credit=value, description=f"{line.item.sku} {grn.number}")]
    if journal:
        try:
            grn.journal_entry = post_journal(company, grn.date, journal, memo=f"{grn.number} {grn.supplier.name}",
                                             source="receipt_goods", source_ref=grn.number, user=user)
        except PostingError as exc:
            raise PurchaseError(str(exc)) from exc
    grn.status = "posted"
    grn.save(update_fields=["number", "status", "journal_entry"])
    if order:
        order.refresh_status()
    AuditLog.record(company, user, "grn.posted", grn, grn.number)
    return grn


# ---------- Bills ----------
def expense_account(line, company):
    if line.account_id:
        return line.account
    if line.item_id and line.item.expense_account_id:
        return line.item.expense_account
    return system_account(company, "cogs") if line.item_id and line.item.is_stocked else \
        company.accounts.get(code="5900")


@transaction.atomic
def post_bill(bill, user):
    if bill.status != "draft":
        raise PurchaseError(_("Only draft bills can be posted."))
    company = bill.company
    lines = list(bill.lines.select_related("item", "tax_rate", "account", "project", "receipt_line"))
    if not lines:
        raise PurchaseError(_("Add at least one line."))
    if Bill.objects.filter(company=company, supplier=bill.supplier, supplier_invoice_no=bill.supplier_invoice_no,
                           status="posted").exclude(pk=bill.pk).exists() and bill.supplier_invoice_no:
        raise PurchaseError(_("Supplier invoice %(n)s is already entered for this supplier.") % {"n": bill.supplier_invoice_no})
    bill.number = bill.number or NumberSeries.next(company, "BILL", bill.date)
    rate, cur = bill.rate, bill.currency_id
    memo = f"{bill.number} {bill.supplier.name} {bill.supplier_invoice_no}".strip()
    journal, vat = [], defaultdict(Decimal)
    grni = system_account(company, "grni")
    for line in lines:
        if line.qty <= 0:
            raise PurchaseError(_("Every line needs a quantity greater than zero."))
        base = r2(line.net * rate)
        if line.receipt_line_id:
            rl = line.receipt_line
            if line.qty > rl.qty - rl.qty_billed:
                raise PurchaseError(_("%(sku)s: billing more than was received.") % {"sku": rl.item.sku})
            received_value = r2(line.qty * rl.unit_cost_base)
            if rl.item.is_stocked:
                journal.append(Line(grni, debit=received_value, description=line.label, project=line.project))
                if base != received_value:
                    variance = base - received_value
                    journal.append(Line(system_account(company, "price_variance"), debit=max(variance, ZERO),
                                        credit=max(-variance, ZERO), description=_("Price difference %(sku)s") % {"sku": rl.item.sku}))
            else:
                journal.append(Line(expense_account(line, company), debit=base, description=line.label, project=line.project))
        elif line.item_id and line.item.is_stocked:
            if not bill.warehouse_id:
                raise PurchaseError(_("Choose the warehouse that receives the stock on this bill."))
            unit_base = (Decimal(line.net) / line.qty * rate).quantize(Decimal("0.0001"))
            try:
                receive(line.item, bill.warehouse, line.qty, unit_base, bill.date, bill.number,
                        serials=parse_serials(line.serials), batch_no=line.batch_no, expiry_date=line.expiry_date)
            except StockError as exc:
                raise PurchaseError(str(exc)) from exc
            journal.append(Line(inventory_account(line.item), debit=base, description=line.label, project=line.project,
                                currency=cur, amount_fc=line.net, rate=rate))
        else:
            journal.append(Line(expense_account(line, company), debit=base, description=line.label, project=line.project,
                                currency=cur, amount_fc=line.net, rate=rate))
        if line.tax:
            vat[line.tax_rate_id] += line.tax
    vat_account = system_account(company, "vat_input")
    for _tax, amount in vat.items():
        journal.append(Line(vat_account, debit=r2(amount * rate), description=_("VAT"), currency=cur, amount_fc=amount, rate=rate))
    ap_base = sum((l.debit for l in journal), ZERO) - sum((l.credit for l in journal), ZERO)
    journal.append(Line(system_account(company, "payable"), credit=ap_base, description=memo, currency=cur,
                        amount_fc=bill.total, rate=rate))
    try:
        bill.journal_entry = post_journal(company, bill.date, journal, memo=memo, source="bill", source_ref=bill.number,
                                          user=user, branch=bill.branch)
    except PostingError as exc:
        raise PurchaseError(str(exc)) from exc
    bill.status = "posted"
    bill.save(update_fields=["number", "status", "journal_entry"])
    AuditLog.record(company, user, "bill.posted", bill, f"{bill.number} {bill.total}")
    return bill


@transaction.atomic
def void_bill(bill, user, date=None):
    if bill.status != "posted":
        raise PurchaseError(_("Only posted bills can be voided."))
    if bill.amount_paid:
        raise PurchaseError(_("Remove the payments allocated to this bill first."))
    if any(l.item_id and l.item.is_stocked and not l.receipt_line_id for l in bill.lines.select_related("item")):
        raise PurchaseError(_("This bill received stock directly; reverse it with a stock adjustment instead."))
    reverse_journal(bill.journal_entry, date or timezone.localdate(), user, _("Void %(n)s") % {"n": bill.number})
    bill.status = "void"
    bill.save(update_fields=["status"])
    AuditLog.record(bill.company, user, "bill.void", bill, bill.number)


@transaction.atomic
def bill_from_order(order, user):
    """A draft bill for everything received but not yet billed (or ordered services)."""
    today = timezone.localdate()
    bill = Bill.objects.create(company=order.company, branch=order.branch, date=today,
                               due_date=today + timedelta(days=order.supplier.payment_terms_days), supplier=order.supplier,
                               currency=order.currency, rate=order.rate, purchase_order=order, created_by=user)
    for line in order.lines.select_related("item"):
        common = {"item_id": line.item_id, "description": line.description, "unit_price": line.unit_price,
                  "discount_pct": line.discount_pct, "tax_rate_id": line.tax_rate_id, "project_id": line.project_id,
                  "account_id": line.account_id, "order_line": line}
        if line.item_id and line.item.is_stocked:
            for rl in line.receipt_lines.filter(document__status="posted"):
                open_qty = rl.qty - rl.qty_billed
                if open_qty > 0:
                    BillLine.objects.create(document=bill, qty=open_qty, receipt_line=rl, **common)
        elif line.qty - line.qty_billed > 0:
            BillLine.objects.create(document=bill, qty=line.qty - line.qty_billed, **common)
    return bill


# ---------- Supplier payments ----------
@transaction.atomic
def post_payment(payment, allocations, user):
    company = payment.company
    if payment.amount <= 0:
        raise PurchaseError(_("The amount must be greater than zero."))
    total_alloc = sum((a for _b, a in allocations), ZERO)
    if total_alloc > payment.amount:
        raise PurchaseError(_("You allocated more than the amount paid."))
    for bill, amount in allocations:
        if bill.supplier_id != payment.supplier_id or bill.currency_id != payment.currency_id:
            raise PurchaseError(_("Bill %(n)s belongs to another supplier or currency.") % {"n": bill.number})
        if amount > bill.balance_due:
            raise PurchaseError(_("%(n)s only has %(b)s left to pay.") % {"n": bill.number, "b": f"{bill.balance_due:,.2f}"})
    if not payment.bank_account_id and payment.method in ("cash", "bank", "cheque"):
        raise PurchaseError(_("Choose the cash box or bank account."))
    if payment.method == "cheque" and not (payment.cheque_number and payment.cheque_due_date):
        raise PurchaseError(_("Enter the cheque number and due date."))

    payment.number = payment.number or NumberSeries.next(company, "SP", payment.date)
    payment.save()
    cur, rate = payment.currency_id, payment.rate
    memo = f"{payment.number} {payment.supplier.name}"
    money_base = r2(payment.amount * rate)
    money_account = system_account(company, "notes_payable") if payment.method == "cheque" else payment.bank_account.gl_account
    ap = system_account(company, "payable")
    lines, ap_base = [], ZERO
    for bill, amount in allocations:
        if amount <= 0:
            continue
        BillAllocation.objects.create(payment=payment, bill=bill, amount=amount)
        bill.amount_paid += amount
        bill.save(update_fields=["amount_paid"])
        base = r2(amount * bill.rate)
        ap_base += base
        lines.append(Line(ap, debit=base, description=bill.number, currency=cur, amount_fc=amount, rate=bill.rate))
    rest = payment.amount - total_alloc
    if rest > 0:
        base = r2(rest * rate)
        ap_base += base
        lines.append(Line(ap, debit=base, description=_("Advance / unallocated"), currency=cur, amount_fc=rest, rate=rate))
    lines.append(Line(money_account, credit=money_base, description=memo, currency=cur, amount_fc=payment.amount, rate=rate))
    diff = ap_base - money_base
    if diff > 0:
        lines.append(Line(system_account(company, "fx_gain"), credit=diff, description=_("Exchange difference")))
    elif diff < 0:
        lines.append(Line(system_account(company, "fx_loss"), debit=-diff, description=_("Exchange difference")))
    try:
        payment.journal_entry = post_journal(company, payment.date, lines, memo=memo, source="supplier_payment",
                                             source_ref=payment.number, user=user)
    except PostingError as exc:
        raise PurchaseError(str(exc)) from exc
    if payment.method == "cheque":
        payment.cheque = Cheque.objects.create(
            company=company, direction="out", number=payment.cheque_number, party_name=payment.supplier.name,
            amount=payment.amount, currency_id=cur, rate=rate, issue_date=payment.date, due_date=payment.cheque_due_date,
            status="issued", bank_account=payment.bank_account, counter_account=ap, source_ref=payment.number,
            created_by=user)
    payment.save(update_fields=["journal_entry", "cheque", "number"])
    AuditLog.record(company, user, "supplier_payment.posted", payment, f"{payment.number} {payment.amount}")
    return payment


@transaction.atomic
def void_payment(payment, user, date=None):
    if payment.status != "posted":
        raise PurchaseError(_("This payment is already void."))
    if payment.cheque_id and payment.cheque.status != "issued":
        raise PurchaseError(_("The cheque has already cleared; it cannot be voided here."))
    reverse_journal(payment.journal_entry, date or timezone.localdate(), user, _("Void %(n)s") % {"n": payment.number})
    for alloc in payment.allocations.select_related("bill"):
        alloc.bill.amount_paid -= alloc.amount
        alloc.bill.save(update_fields=["amount_paid"])
    payment.allocations.all().delete()
    if payment.cheque_id:
        payment.cheque.status = "cancelled"
        payment.cheque.save(update_fields=["status"])
    payment.status = "void"
    payment.save(update_fields=["status"])
    AuditLog.record(payment.company, user, "supplier_payment.void", payment, payment.number)


def supplier_balance(supplier, as_of=None):
    bills = Bill.objects.filter(supplier=supplier, status="posted")
    pays = SupplierPayment.objects.filter(supplier=supplier, status="posted")
    if as_of:
        bills, pays = bills.filter(date__lte=as_of), pays.filter(date__lte=as_of)
    return sum((b.total for b in bills), ZERO) - sum((p.amount for p in pays), ZERO)


def ap_aging(company, as_of=None):
    from sales.services import bucket_for
    as_of = as_of or timezone.localdate()
    rows = {}
    for bill in Bill.objects.filter(company=company, status="posted", date__lte=as_of).select_related("supplier"):
        due = bill.balance_due
        if due <= 0:
            continue
        row = rows.setdefault(bill.supplier_id, {"contact": bill.supplier, "buckets": [ZERO] * 5, "total": ZERO})
        base = r2(due * bill.rate)
        row["buckets"][bucket_for((as_of - bill.due_date).days)] += base
        row["total"] += base
    for pay in SupplierPayment.objects.filter(company=company, status="posted", date__lte=as_of).select_related("supplier"):
        if pay.unallocated > 0:
            row = rows.setdefault(pay.supplier_id, {"contact": pay.supplier, "buckets": [ZERO] * 5, "total": ZERO})
            base = r2(pay.unallocated * pay.rate)
            row["buckets"][0] -= base
            row["total"] -= base
    return sorted(rows.values(), key=lambda r: -r["total"])


def statement(supplier, date_from, date_to):
    from sales.services import bucket_for
    opening = supplier_balance(supplier, as_of=date_from - timedelta(days=1))
    events = []
    for bill in Bill.objects.filter(supplier=supplier, status="posted", date__gte=date_from, date__lte=date_to):
        events.append((bill.date, 0, bill.number, bill.supplier_invoice_no, _("Bill"), bill.total, ZERO, bill.due_date))
    for pay in SupplierPayment.objects.filter(supplier=supplier, status="posted", date__gte=date_from, date__lte=date_to):
        events.append((pay.date, 1, pay.number, pay.reference, _("Payment"), ZERO, pay.amount, None))
    events.sort(key=lambda e: (e[0], e[1]))
    running, rows = opening, []
    for date, _o, number, ref, kind, debit, credit, due in events:
        running += debit - credit
        rows.append({"date": date, "number": number, "ref": ref, "kind": kind, "debit": debit, "credit": credit,
                     "balance": running, "due": due})
    aging = [ZERO] * 5
    for bill in Bill.objects.filter(supplier=supplier, status="posted", date__lte=date_to):
        if bill.balance_due > 0:
            aging[bucket_for((date_to - bill.due_date).days)] += bill.balance_due
    return {"opening": opening, "rows": rows, "closing": running, "aging": aging}
