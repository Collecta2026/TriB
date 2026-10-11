"""Expenses list (QuickBooks "Expense transactions"): expenses, cheques, bills, bill payments and supplier credits in
one list, with the category shown and changeable on the row. Changing the category of a posted transaction posts a
reclassification entry (old account → new account) and keeps an audit trail."""
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from core.models import AuditLog
from ledger.services import Line, PostingError, post_journal

ZERO = Decimal("0")
TYPES = [("expense", gettext_lazy("Expenses")), ("cheque", gettext_lazy("Cheques")), ("bill", gettext_lazy("Bills")),
         ("payment", gettext_lazy("Bill payments")), ("credit", gettext_lazy("Supplier credits"))]


def _category(accounts):
    """One account name, or --Split-- when the lines use several."""
    ids = {a.pk for a in accounts if a is not None}
    if not ids:
        return "", None
    if len(ids) > 1:
        return _("--Split--"), None
    a = next(a for a in accounts if a is not None)
    return a.name, a


def rows(company, request):
    from purchases.models import Bill, SupplierCredit, SupplierPayment
    from purchases.services import expense_account
    from vouchers.models import Voucher

    today = timezone.localdate()
    kind = request.GET.get("type", "")
    period = request.GET.get("period", "365")
    since = None if period == "all" else today - timedelta(days=int(period) if period.isdigit() else 365)
    out = []

    def keep(k, d):
        return (not kind or kind == k) and (since is None or d >= since)

    for v in (Voucher.objects.filter(company=company, kind="payment").exclude(status="cancelled")
              .select_related("currency").prefetch_related("lines__account")):
        k = "cheque" if v.method == "cheque" else "expense"
        if not keep(k, v.date):
            continue
        lines = list(v.lines.all())
        name, acc = _category([l.account for l in lines])
        out.append({"date": v.date, "kind": k, "type": _("Cheque") if k == "cheque" else _("Expense"), "number": v.number,
                    "payee": v.party_name, "category": name, "account": acc, "before_tax": v.total, "tax": ZERO,
                    "total": v.total, "currency": v.currency_id, "status": v.status, "status_label": v.get_status_display(),
                    "url": reverse("vouchers:detail", args=[v.pk]),
                    "edit_key": f"voucher:{v.pk}" if len(lines) == 1 and v.status != "cancelled" else ""})
    for b in (Bill.objects.filter(company=company).exclude(status="void").select_related("supplier", "currency")
              .prefetch_related("lines__item", "lines__account", "lines__tax_rate")):
        if not keep("bill", b.date):
            continue
        lines = list(b.lines.all())
        accounts = [None if (l.item_id and l.item.is_stocked) else expense_account(l, company) for l in lines]
        stocked = any(l.item_id and l.item.is_stocked for l in lines)
        name, acc = (_("Inventory"), None) if stocked and len(lines) == 1 else _category(accounts)
        if stocked and len(lines) > 1:
            name, acc = _("--Split--"), None
        out.append({"date": b.date, "kind": "bill", "type": _("Bill"), "number": b.number or _("Draft"),
                    "payee": b.supplier.name, "category": name, "account": acc, "before_tax": b.subtotal, "tax": b.tax_total,
                    "total": b.total, "currency": b.currency_id, "status": b.payment_state, "status_label": b.get_status_display(),
                    "url": reverse("purchases:bill", args=[b.pk]),
                    "edit_key": f"bill:{b.pk}" if len(lines) == 1 and not stocked and not lines[0].receipt_line_id else ""})
    for p in SupplierPayment.objects.filter(company=company, status="posted").select_related("supplier", "currency"):
        if keep("payment", p.date):
            out.append({"date": p.date, "kind": "payment", "type": _("Bill payment"), "number": p.number,
                        "payee": p.supplier.name, "category": _("Accounts payable"), "account": None, "before_tax": p.amount,
                        "tax": ZERO, "total": p.amount, "currency": p.currency_id, "status": p.status,
                        "status_label": p.get_status_display(), "url": reverse("purchases:payment", args=[p.pk]), "edit_key": ""})
    for c in (SupplierCredit.objects.filter(company=company).exclude(status="void").select_related("supplier", "currency")
              .prefetch_related("lines__tax_rate")):
        if keep("credit", c.date):
            out.append({"date": c.date, "kind": "credit", "type": _("Supplier credit"), "number": c.number or _("Draft"),
                        "payee": c.supplier.name, "category": "", "account": None, "before_tax": -c.subtotal,
                        "tax": -c.tax_total, "total": -c.total, "currency": c.currency_id, "status": c.status,
                        "status_label": c.get_status_display(), "url": reverse("purchases:supplier_credit", args=[c.pk]),
                        "edit_key": ""})
    payee = request.GET.get("payee", "").strip().lower()
    category = request.GET.get("category", "")
    status = request.GET.get("status", "")
    if payee:
        out = [r for r in out if payee in (r["payee"] or "").lower()]
    if category.isdigit():
        out = [r for r in out if r["account"] is not None and r["account"].pk == int(category)]
    if status:
        out = [r for r in out if r["status"] == status]
    out.sort(key=lambda r: r["date"], reverse=True)
    return out[:300], {"type": kind, "period": period, "payee": request.GET.get("payee", ""), "category": category,
                       "status": status}


@transaction.atomic
def reclassify(company, key, new_account, user):
    """Change the category of a one-line expense or bill. Posted ones get a reclassification entry."""
    from purchases.models import Bill
    from purchases.services import expense_account
    from vouchers.models import Voucher

    kind, _sep, pk = key.partition(":")
    if kind == "voucher":
        doc = Voucher.objects.select_for_update().get(pk=pk, company=company, kind="payment")
        line = doc.lines.get()
        old, base, number, posted = line.account, (line.amount * doc.rate).quantize(Decimal("0.01")), doc.number, \
            doc.status == "posted"
    elif kind == "bill":
        doc = Bill.objects.select_for_update().get(pk=pk, company=company)
        line = doc.lines.select_related("item").get()
        if (line.item_id and line.item.is_stocked) or line.receipt_line_id:
            raise PostingError(_("Stock lines keep their inventory account."))
        old = expense_account(line, company)
        base, number, posted = (line.net * doc.rate).quantize(Decimal("0.01")), doc.number, doc.status == "posted"
    else:
        raise PostingError(_("This transaction's category can't be changed here."))
    if new_account.company_id != company.id or new_account.is_group:
        raise PostingError(_("Choose a posting account."))
    if old is not None and old.pk == new_account.pk:
        return None
    entry = None
    if posted and old is not None and base:
        entry = post_journal(company, timezone.localdate(), [
            Line(new_account, debit=base if base > 0 else ZERO, credit=-base if base < 0 else ZERO,
                 description=_("Reclassified from %(a)s") % {"a": old.name}),
            Line(old, credit=base if base > 0 else ZERO, debit=-base if base < 0 else ZERO,
                 description=_("Reclassified to %(a)s") % {"a": new_account.name}),
        ], memo=_("Reclassification %(n)s") % {"n": number}, source="reclass", source_ref=number, user=user)
    line.account = new_account
    line.save(update_fields=["account"])
    AuditLog.record(company, user, "expense.reclassified", doc,
                    f"{number or doc.pk}: {old.code if old else '—'} → {new_account.code}",
                    {"entry": entry.number if entry else None})
    return entry
