"""The customer / supplier page (QuickBooks "customer hub"): financial summary, one transaction list across
every document type, and the tabs behind it."""
from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

ZERO = Decimal("0")

TYPES = {
    "customer": [("invoice", gettext_lazy("Invoices")), ("payment", gettext_lazy("Payments")),
                 ("credit", gettext_lazy("Credit notes")), ("refund", gettext_lazy("Refunds")),
                 ("quote", gettext_lazy("Quotations")), ("order", gettext_lazy("Sales orders")),
                 ("cheque", gettext_lazy("Returned cheques"))],
    "supplier": [("bill", gettext_lazy("Bills")), ("payment", gettext_lazy("Payments")),
                 ("supplier_credit", gettext_lazy("Supplier credits")), ("order", gettext_lazy("Purchase orders")),
                 ("receipt", gettext_lazy("Item receipts"))],
}
STATUSES = [("open", gettext_lazy("Open")), ("overdue", gettext_lazy("Overdue")), ("paid", gettext_lazy("Paid")),
            ("closed", gettext_lazy("Closed")), ("draft", gettext_lazy("Draft")), ("void", gettext_lazy("Void"))]
PERIODS = [("30", gettext_lazy("Last 30 days")), ("90", gettext_lazy("Last 90 days")), ("365", gettext_lazy("Last 12 months")),
           ("year", gettext_lazy("This year")), ("all", gettext_lazy("All dates"))]


def _status(state, due=None, today=None):
    """(status key for filtering, icon class, label)."""
    if state == "overdue":
        days = (today - due).days if due and today else 0
        return "overdue", "warn", _("Overdue %(n)s days") % {"n": days} if days != 1 else _("Overdue 1 day")
    return {
        "paid": ("paid", "ok", _("Paid")), "closed": ("closed", "ok", _("Closed")),
        "partial": ("open", "part", _("Partly paid")), "unpaid": ("open", "open", _("Open")),
        "open": ("open", "open", _("Open")), "draft": ("draft", "draft", _("Draft")), "void": ("void", "void", _("Void")),
        "posted": ("closed", "ok", _("Posted")), "accepted": ("closed", "ok", _("Accepted")), "sent": ("open", "open", _("Sent")),
        "invoiced": ("closed", "ok", _("Invoiced")), "received": ("closed", "ok", _("Received")),
        "declined": ("void", "void", _("Declined")), "cancelled": ("void", "void", _("Cancelled")),
        "bounced": ("open", "warn", _("Returned")), "settled": ("closed", "ok", _("Settled")),
    }.get(state, ("open", "open", str(state).replace("_", " ").capitalize()))


def _order_status(order):
    """Orders keep their own wording ("Partly received", "Waiting for approval"), with the usual icon."""
    key, icon, _label = _status(order.status)
    return key, icon, order.get_status_display()


def _row(kind, label, doc, number, amount, currency, status, url, actions=(), memo="", select="", can=None):
    key, icon, text = status
    return {"menu": doc_menu(select, doc, can) if can else [],"kind": kind, "type": label, "date": doc.date if hasattr(doc, "date") else None, "number": number,
            "memo": memo, "amount": amount, "currency": currency, "status": key, "icon": icon, "status_label": text,
            "url": url, "actions": list(actions), "select": select, "sort": (getattr(doc, "date", None), getattr(doc, "pk", 0))}


def customer_rows(c, can):
    from banking.models import Cheque
    from sales.models import CreditNote, CustomerPayment, CustomerRefund, Invoice, Quotation, SalesOrder

    today = timezone.localdate()
    rows = []
    for inv in Invoice.objects.filter(customer=c).prefetch_related("lines__tax_rate"):
        state = inv.payment_state
        actions = [(_("View/Edit"), reverse("sales:invoice", args=[inv.pk]))]
        if inv.status == "posted" and inv.balance_due > 0 and can("sales.create"):
            actions.append((_("Receive payment"), f"{reverse('sales:payment_new')}?customer={c.pk}"))
        elif inv.number:
            actions.append((_("Print"), reverse("sales:invoice_print", args=[inv.pk]) + "#print"))
        row = _row("invoice", _("Invoice"), inv, inv.number, inv.total, inv.currency_id,
                   _status(state, inv.due_date, today), reverse("sales:invoice", args=[inv.pk]), actions,
                   inv.reference or inv.customer_po, f"sales:invoice:{inv.pk}" if inv.number else "", can=can)
        row["doc_due"] = inv.balance_due
        rows.append(row)
    for p in CustomerPayment.objects.filter(customer=c):
        rows.append(_row("payment", _("Payment"), p, p.number, p.amount, p.currency_id,
                         _status("void" if p.status == "void" else "closed"), reverse("sales:payment", args=[p.pk]),
                         [(_("View"), reverse("sales:payment", args=[p.pk])),
                          (_("Print"), reverse("sales:payment_print", args=[p.pk]) + "#print")], p.reference))
    for n in CreditNote.objects.filter(customer=c).prefetch_related("lines__tax_rate"):
        state = n.status if n.status != "posted" else ("closed" if n.available <= 0 else "open")
        rows.append(_row("credit", _("Credit note"), n, n.number, -n.total, n.currency_id, _status(state),
                         reverse("sales:credit", args=[n.pk]), [(_("View/Edit"), reverse("sales:credit", args=[n.pk]))],
                         n.reference, f"sales:credit:{n.pk}" if n.number else "", can=can))
    for r in CustomerRefund.objects.filter(customer=c):
        rows.append(_row("refund", _("Refund"), r, r.number, r.amount, r.currency_id,
                         _status("void" if r.status == "void" else "closed"), reverse("sales:refund", args=[r.pk]),
                         [(_("View"), reverse("sales:refund", args=[r.pk]))], r.reference))
    for q in Quotation.objects.filter(customer=c).prefetch_related("lines__tax_rate"):
        rows.append(_row("quote", _("Quotation"), q, q.number, q.total, q.currency_id, _status(q.status),
                         reverse("sales:quote", args=[q.pk]), [(_("View/Edit"), reverse("sales:quote", args=[q.pk]))],
                         q.reference, f"sales:quote:{q.pk}" if q.number else "", can=can))
    for o in SalesOrder.objects.filter(customer=c).prefetch_related("lines__tax_rate"):
        rows.append(_row("order", _("Sales order"), o, o.number, o.total, o.currency_id, _order_status(o),
                         reverse("sales:order", args=[o.pk]), [(_("View/Edit"), reverse("sales:order", args=[o.pk]))],
                         o.reference or o.customer_po, f"sales:order:{o.pk}" if o.number else "", can=can))
    for chq in Cheque.objects.filter(customer=c, status__in=("bounced", "settled")).exclude(bounced_on=None):
        chq.date = chq.bounced_on
        rows.append(_row("cheque", _("Returned cheque"), chq, chq.number, chq.amount, chq.currency_id, _status(chq.status),
                         f"{reverse('banking:cheques')}?status={chq.status}&q={chq.number}",
                         [(_("View"), f"{reverse('banking:bounced')}")], chq.bounce_reason))
    return rows


def supplier_rows(s, can):
    from purchases.models import Bill, GoodsReceipt, PurchaseOrder, SupplierCredit, SupplierPayment

    today = timezone.localdate()
    rows = []
    for b in Bill.objects.filter(supplier=s).prefetch_related("lines__tax_rate"):
        actions = [(_("View/Edit"), reverse("purchases:bill", args=[b.pk]))]
        if b.status == "posted" and b.balance_due > 0 and can("purchases.create"):
            actions.append((_("Pay bill"), f"{reverse('purchases:payment_new')}?supplier={s.pk}"))
        row = _row("bill", _("Bill"), b, b.number, b.total, b.currency_id, _status(b.payment_state, b.due_date, today),
                   reverse("purchases:bill", args=[b.pk]), actions, b.supplier_invoice_no or b.reference,
                   f"purchases:bill:{b.pk}" if b.number else "", can=can)
        row["doc_due"] = b.balance_due
        rows.append(row)
    for p in SupplierPayment.objects.filter(supplier=s):
        rows.append(_row("payment", _("Payment"), p, p.number, p.amount, p.currency_id,
                         _status("void" if p.status == "void" else "closed"), reverse("purchases:payment", args=[p.pk]),
                         [(_("View"), reverse("purchases:payment", args=[p.pk])),
                          (_("Remittance advice"), reverse("purchases:payment_print", args=[p.pk]))], p.reference,
                         f"purchases:payment:{p.pk}" if p.status == "posted" else ""))
    for n in SupplierCredit.objects.filter(supplier=s).prefetch_related("lines__tax_rate"):
        state = n.status if n.status != "posted" else ("closed" if n.available <= 0 else "open")
        rows.append(_row("supplier_credit", _("Supplier credit"), n, n.number, -n.total, n.currency_id, _status(state),
                         reverse("purchases:supplier_credit", args=[n.pk]),
                         [(_("View/Edit"), reverse("purchases:supplier_credit", args=[n.pk]))], n.reference,
                         f"purchases:supplier_credit:{n.pk}" if n.number else "", can=can))
    for o in PurchaseOrder.objects.filter(supplier=s).prefetch_related("lines__tax_rate"):
        rows.append(_row("order", _("Purchase order"), o, o.number, o.total, o.currency_id, _order_status(o),
                         reverse("purchases:order", args=[o.pk]), [(_("View/Edit"), reverse("purchases:order", args=[o.pk]))],
                         o.reference, f"purchases:order:{o.pk}" if o.number else "", can=can))
    for g in GoodsReceipt.objects.filter(supplier=s):
        rows.append(_row("receipt", _("Item receipt"), g, g.number, None, "", _status(g.status),
                         reverse("purchases:receipt", args=[g.pk]), [(_("View"), reverse("purchases:receipt", args=[g.pk]))],
                         g.reference))
    return rows


def doc_menu(select, doc, can):
    """The ▾ beside a row's action: Print, Send, Make a copy, Void."""
    from core.docviews import REGISTRY

    if not select:
        return []
    ns, key, pk = select.split(":")
    spec = REGISTRY.get((ns, key))
    if spec is None:
        return []
    out = [{"label": _("Print"), "url": spec.url("print", doc.pk) + "#print"}]
    if ns == "sales" and key in ("invoice", "quote") and doc.number:
        out.append({"label": _("Send"), "url": reverse("core:doc_send", args=[ns, key, doc.pk])})
    if can(f"{spec.perm}.create"):
        out.append({"label": _("Make a copy"), "post": reverse("core:doc_copy", args=[ns, key, doc.pk])})
    if spec.voidable and doc.status == "posted" and can(f"{spec.perm}.void") and not getattr(doc, "amount_paid", 0):
        out.append({"label": _("Void"), "post": reverse(f"{ns}:{key}_action", args=[doc.pk]), "action": "void",
                    "confirm": _("Void this document? Its ledger entry is reversed.")})
    return out


def filtered(rows, request):
    kind, status, period = request.GET.get("type", ""), request.GET.get("status", ""), request.GET.get("period", "365")
    today = timezone.localdate()
    since = None
    if period == "all":
        since = None
    elif period in ("30", "90", "365"):
        since = today - timedelta(days=int(period))
    elif period == "year":
        since = today.replace(month=1, day=1)
    out = [r for r in rows if (not kind or r["kind"] == kind) and (not status or r["status"] == status)
           and (since is None or (r["date"] and r["date"] >= since))]
    out.sort(key=lambda r: (r["sort"][0] or today, r["sort"][1]), reverse=True)
    return out, {"type": kind, "status": status, "period": period}


def summary(kind, obj, rows):
    """Open balance and overdue amount, in the contact's currency (like QuickBooks' Financial summary)."""
    if kind == "customer":
        from sales.services import customer_balance as balance
    else:
        from purchases.services import supplier_balance as balance
    overdue = ZERO
    for r in rows:
        if r["status"] == "overdue" and r["kind"] in ("invoice", "bill"):
            overdue += r["doc_due"] if "doc_due" in r else ZERO
    return {"balance": balance(obj), "overdue": overdue}


def related_ids(rows):
    out = {}
    for r in rows:
        if r["select"]:
            ns, key, pk = r["select"].split(":")
            out.setdefault((ns, key), []).append(int(pk))
    return out
