from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from contacts.models import Supplier
from core.docviews import DocSpec, doc_detail, doc_form, doc_list, doc_print, get_doc
from inventory.models import Warehouse
from sales.forms import StatementForm
from sales.services import AGING_BUCKETS
from users.permissions import require_perm

from . import services
from .forms import (BILL_LINES, ORDER_LINES, RECEIPT_LINES, SUPPLIER_CREDIT_LINES, ApplySupplierCreditForm, BillForm,
                    GoodsReceiptForm, PurchaseOrderForm, SupplierCreditForm, SupplierPaymentForm)
from .models import Bill, GoodsReceipt, PurchaseOrder, SupplierCredit, SupplierPayment


def _defaults(request, due=False, warehouse=False):
    today = timezone.localdate()
    out = {"date": today}
    sid = request.GET.get("supplier")
    if sid and sid.isdigit():
        supplier = Supplier.objects.filter(company=request.company, pk=sid).first()
        if supplier:
            out.update(supplier=supplier, currency=supplier.currency)
            if due:
                out["due_date"] = today + timedelta(days=supplier.payment_terms_days)
    if due and "due_date" not in out:
        out["due_date"] = today + timedelta(days=30)
    if warehouse:
        out["warehouse"] = Warehouse.objects.filter(company=request.company, is_active=True).first()
    return out


def _state(doc):
    from core.templatetags.trib import state_label
    return state_label(doc.payment_state)


ORDER = DocSpec(
    key="order", ns="purchases", perm="purchases", model=PurchaseOrder, header_form=PurchaseOrderForm,
    formsets=ORDER_LINES, title=gettext_lazy("Purchase order"), plural=gettext_lazy("Purchase orders"),
    print_en="Purchase Order", print_ar="أمر شراء", party="supplier", price_source="purchase",
    statuses=PurchaseOrder.STATUSES, actions_template="purchases/_order_actions.html",
    related_template="purchases/_order_related.html", editable_statuses=("draft",),
    defaults=lambda r: _defaults(r, warehouse=True),
    columns=[(gettext_lazy("Number"), lambda d: d.number, "text"), (gettext_lazy("Date"), lambda d: d.date, "date"),
             (gettext_lazy("Supplier"), lambda d: d.supplier.name, "text"),
             (gettext_lazy("Expected delivery"), lambda d: d.expected_date, "date"),
             (gettext_lazy("Total"), lambda d: d.total, "money"), (gettext_lazy("Currency"), lambda d: d.currency_id, "text"),
             (gettext_lazy("Status"), lambda d: (d.status, d.get_status_display()), "pill")])
BILL = DocSpec(
    key="bill", voidable=True, recurring_kind="bill", ns="purchases", perm="purchases", model=Bill, header_form=BillForm, formsets=BILL_LINES,
    title=gettext_lazy("Bill"), plural=gettext_lazy("Bills"), print_en="Supplier Bill", print_ar="فاتورة مورد",
    party="supplier", price_source="purchase", statuses=Bill.STATUSES, actions_template="purchases/_bill_actions.html",
    related_template="purchases/_bill_related.html", defaults=lambda r: _defaults(r, due=True),
    columns=[(gettext_lazy("Number"), lambda d: d.number, "text"), (gettext_lazy("Date"), lambda d: d.date, "date"),
             (gettext_lazy("Supplier"), lambda d: d.supplier.name, "text"),
             (gettext_lazy("Supplier invoice number"), lambda d: d.supplier_invoice_no, "text"),
             (gettext_lazy("Due date"), lambda d: d.due_date, "date"), (gettext_lazy("Total"), lambda d: d.total, "money"),
             (gettext_lazy("Balance due"), lambda d: d.balance_due, "money"),
             (gettext_lazy("Status"), lambda d: (d.payment_state, _state(d)), "pill")])


def _info(doc):
    rows = [(_("Supplier"), doc.supplier), (_("Reference"), doc.reference), (_("Branch"), doc.branch)]
    if getattr(doc, "supplier_invoice_no", ""):
        rows.insert(1, (_("Supplier invoice number"), doc.supplier_invoice_no))
    for attr, label in (("due_date", _("Due date")), ("expected_date", _("Expected delivery"))):
        if getattr(doc, attr, None):
            rows.append((label, getattr(doc, attr).strftime("%d/%m/%Y")))
    if doc.warehouse_id:
        rows.append((_("Warehouse"), doc.warehouse))
    if getattr(doc, "approved_by_id", None):
        rows.append((_("Approved by"), f"{doc.approved_by} · {doc.approved_at:%d/%m/%Y %H:%M}"))
    return rows


def _detail(request, spec, pk):
    doc = get_doc(request, spec, pk)
    return doc_detail(request, spec, doc, {"info": _info(doc), "party": doc.supplier,
                                           "party_url": reverse("contacts:supplier", args=[doc.supplier_id])})


# ---------- Purchase orders ----------
@require_perm("purchases.view")
def orders(request):
    return doc_list(request, ORDER)


@require_perm("purchases.create")
def order_new(request):
    return doc_form(request, ORDER)


@require_perm("purchases.edit")
def order_edit(request, pk):
    return doc_form(request, ORDER, get_doc(request, ORDER, pk))


@require_perm("purchases.view")
def order(request, pk):
    return _detail(request, ORDER, pk)


@require_perm("purchases.view")
def order_print(request, pk):
    return doc_print(request, ORDER, get_doc(request, ORDER, pk))


@require_POST
@require_perm("purchases.view")
def order_action(request, pk):
    doc = get_doc(request, ORDER, pk)
    action, m = request.POST.get("action"), request.membership
    needs = {"submit": "purchases.create", "approve": "purchases.approve", "reject": "purchases.approve",
             "receive": "inventory.post", "bill": "purchases.create", "close": "purchases.edit", "cancel": "purchases.edit"}
    if action not in needs or not m.has_perm(needs[action]):
        messages.error(request, _("You do not have permission to do that."))
        return redirect("purchases:order", pk=pk)
    try:
        if action == "submit":
            services.submit_order(doc, request.user)
            messages.success(request, _("Sent for approval."))
        elif action == "approve":
            services.approve_order(doc, request.user, m)
            messages.success(request, _("Purchase order approved."))
        elif action == "reject":
            services.reject_order(doc, request.user, request.POST.get("reason", ""))
            messages.success(request, _("Returned to the creator."))
        elif action == "receive":
            grn = services.receipt_from_order(doc, request.user)
            return redirect("purchases:receipt_edit", pk=grn.pk)
        elif action == "bill":
            bill = services.bill_from_order(doc, request.user)
            return redirect("purchases:bill_edit", pk=bill.pk)
        elif action == "close" and doc.status in ("open", "partial", "received"):
            doc.status = "closed"
            doc.save(update_fields=["status"])
            messages.success(request, _("Purchase order closed. Anything not received is no longer expected."))
        elif action == "cancel" and doc.status in ("draft", "submitted", "open"):
            doc.status = "cancelled"
            doc.save(update_fields=["status"])
            messages.success(request, _("Purchase order cancelled."))
    except services.PurchaseError as exc:
        messages.error(request, str(exc))
    return redirect("purchases:order", pk=pk)


# ---------- Item receipts (GRN) ----------
@require_perm("purchases.view")
def receipts(request):
    qs = GoodsReceipt.objects.filter(company=request.company).select_related("supplier", "warehouse", "purchase_order")
    page = Paginator(qs, 40).get_page(request.GET.get("page"))
    return render(request, "purchases/receipts.html", {"page": page})


@transaction.atomic
def _receipt_form(request, grn):
    form = GoodsReceiptForm(request.POST or None, instance=grn, company=request.company)
    formset = (RECEIPT_LINES[0] if grn.pk else RECEIPT_LINES[1])(request.POST or None, instance=grn,
                                                                    company=request.company, prefix="lines")
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        grn = form.save(commit=False)
        grn.company = request.company
        grn.save()
        formset.instance = grn
        formset.save()
        if "post" in request.POST and request.membership.has_perm("inventory.post"):
            try:
                services.post_receipt(grn, request.user)
                messages.success(request, _("Item receipt %(n)s posted. Stock is in the warehouse.") % {"n": grn.number})
            except services.PurchaseError as exc:
                messages.error(request, str(exc))
        else:
            messages.success(request, _("Saved."))
        from core.doc_actions import saved_redirect
        return saved_redirect(request, reverse("purchases:receipt", args=[grn.pk]), reverse("purchases:receipt_new"),
                              reverse("purchases:receipts"))
    from core.docviews import picker_data
    from core.doc_actions import audit_url
    bar = {"mode": "form", "save_label": _("Save draft"), "more": [],
           "cancel": reverse("purchases:receipt", args=[grn.pk]) if grn.pk else reverse("purchases:receipts"),
           "primary": _("Save and receive into stock") if request.membership.has_perm("inventory.post") else ""}
    if grn.pk and request.membership.has_perm("audit.view"):
        bar["more"].append({"label": _("Audit history"), "url": audit_url(grn)})
    return render(request, "purchases/receipt_form.html", {"form": form, "formset": formset, "grn": grn, "bar": bar,
                                                           "picker": picker_data(request.company, "purchase")})


@require_perm("purchases.create")
def receipt_new(request):
    grn = GoodsReceipt(company=request.company, created_by=request.user, date=timezone.localdate(),
                       warehouse=Warehouse.objects.filter(company=request.company, is_active=True).first())
    return _receipt_form(request, grn)


@require_perm("purchases.edit")
def receipt_edit(request, pk):
    grn = get_object_or_404(GoodsReceipt, pk=pk, company=request.company)
    if grn.status != "draft":
        messages.error(request, _("This document can no longer be changed."))
        return redirect("purchases:receipt", pk=pk)
    return _receipt_form(request, grn)


@require_perm("purchases.view")
def receipt(request, pk):
    grn = get_object_or_404(GoodsReceipt, pk=pk, company=request.company)
    return render(request, "purchases/receipt_detail.html", {"grn": grn, "lines": grn.lines.select_related("item", "order_line")})


@require_POST
@require_perm("inventory.post")
def receipt_post(request, pk):
    grn = get_object_or_404(GoodsReceipt, pk=pk, company=request.company)
    try:
        services.post_receipt(grn, request.user)
        messages.success(request, _("Item receipt %(n)s posted. Stock is in the warehouse.") % {"n": grn.number})
    except services.PurchaseError as exc:
        messages.error(request, str(exc))
    return redirect("purchases:receipt", pk=pk)


@require_perm("purchases.view")
def receipt_print(request, pk):
    grn = get_object_or_404(GoodsReceipt, pk=pk, company=request.company)
    return render(request, "purchases/receipt_print.html", {"grn": grn, "lines": grn.lines.select_related("item")})


# ---------- Bills ----------
def _post_after_save(request, doc):
    if not request.membership.has_perm("purchases.post"):
        return None
    try:
        services.post_bill(doc, request.user)
    except services.PurchaseError as exc:
        messages.error(request, str(exc))
        return redirect("purchases:bill", pk=doc.pk)
    messages.success(request, _("Bill %(n)s posted.") % {"n": doc.number})
    return redirect("purchases:bill", pk=doc.pk)


@require_perm("purchases.view")
def bills(request):
    return doc_list(request, BILL)


@require_perm("purchases.create")
def bill_new(request):
    return doc_form(request, BILL, after_save=_post_after_save, post_label=_("Save and post"))


@require_perm("purchases.edit")
def bill_edit(request, pk):
    return doc_form(request, BILL, get_doc(request, BILL, pk), after_save=_post_after_save, post_label=_("Save and post"))


@require_perm("purchases.view")
def bill(request, pk):
    return _detail(request, BILL, pk)


@require_perm("purchases.view")
def bill_print(request, pk):
    return doc_print(request, BILL, get_doc(request, BILL, pk))


@require_POST
@require_perm("purchases.post")
def bill_action(request, pk):
    doc = get_doc(request, BILL, pk)
    action = request.POST.get("action")
    if action == "post":
        return _post_after_save(request, doc)
    if action == "void" and request.membership.has_perm("purchases.void"):
        try:
            services.void_bill(doc, request.user)
            messages.success(request, _("Bill voided."))
        except services.PurchaseError as exc:
            messages.error(request, str(exc))
    return redirect("purchases:bill", pk=pk)


# ---------- Supplier payments ----------
@require_perm("purchases.view")
def payments(request):
    from core.filters import apply as drill_filter
    qs = SupplierPayment.objects.filter(company=request.company).select_related("supplier", "currency", "bank_account")
    qs, drill = drill_filter(request, qs, "supplier")
    page = Paginator(qs, 40).get_page(request.GET.get("page"))
    return render(request, "purchases/payments.html", {"page": page, "drill": drill})


@require_perm("purchases.create")
def payment_new(request):
    company = request.company
    initial = {"date": timezone.localdate(), "currency": company.base_currency, "method": "bank"}
    sid = request.GET.get("supplier") or request.POST.get("supplier")
    supplier = Supplier.objects.filter(company=company, pk=sid).first() if sid and str(sid).isdigit() else None
    if supplier:
        initial.update(supplier=supplier, currency=supplier.currency)
    form = SupplierPaymentForm(request.POST or None, company=company, initial=initial,
                               instance=SupplierPayment(company=company, created_by=request.user))
    open_bills = []
    if supplier:
        open_bills = [b for b in Bill.objects.filter(supplier=supplier, status="posted").order_by("due_date") if b.balance_due > 0]
    if request.method == "POST" and form.is_valid() and "save" in request.POST:
        payment = form.save(commit=False)
        payment.company, payment.created_by = company, request.user
        allocations = []
        for b in open_bills:
            raw = request.POST.get(f"alloc_{b.pk}", "").replace(",", "").strip()
            if raw:
                try:
                    allocations.append((b, Decimal(raw)))
                except InvalidOperation:
                    pass
        try:
            services.post_payment(payment, allocations, request.user)
        except services.PurchaseError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, _("Payment %(n)s recorded.") % {"n": payment.number})
            return redirect("purchases:payment", pk=payment.pk)
    return render(request, "purchases/payment_form.html", {"form": form, "supplier": supplier, "open_bills": open_bills})


@require_perm("purchases.view")
def payment(request, pk):
    p = get_object_or_404(SupplierPayment, pk=pk, company=request.company)
    return render(request, "purchases/payment_detail.html", {"p": p, "allocs": p.allocations.select_related("bill")})


@require_perm("purchases.view")
def payment_print(request, pk):
    from core.amount_words import amount_in_words
    p = get_object_or_404(SupplierPayment, pk=pk, company=request.company)
    return render(request, "purchases/remittance.html", {
        "p": p, "allocs": p.allocations.select_related("bill"),
        "words_en": amount_in_words(p.amount, p.currency_id, "en"), "words_ar": amount_in_words(p.amount, p.currency_id, "ar")})


@require_POST
@require_perm("purchases.void")
def payment_void(request, pk):
    p = get_object_or_404(SupplierPayment, pk=pk, company=request.company)
    try:
        services.void_payment(p, request.user)
        messages.success(request, _("Payment voided."))
    except services.PurchaseError as exc:
        messages.error(request, str(exc))
    return redirect("purchases:payment", pk=pk)


# ---------- Expenses, statements, not-received ----------
@require_perm("purchases.view")
def expenses(request):
    from vouchers.models import Voucher
    company = request.company
    rows = []
    for v in Voucher.objects.filter(company=company, kind="payment").exclude(status="cancelled").select_related("currency")[:100]:
        rows.append({"date": v.date, "type": _("Payment voucher"), "number": v.number or _("Draft"), "party": v.party_name,
                     "amount": v.total, "currency": v.currency_id, "status": v.get_status_display(), "state": v.status,
                     "url": reverse("vouchers:detail", args=[v.pk])})
    for b in Bill.objects.filter(company=company).exclude(status="void").select_related("supplier")[:100]:
        rows.append({"date": b.date, "type": _("Bill"), "number": b.number or _("Draft"), "party": b.supplier.name,
                     "amount": b.total, "currency": b.currency_id, "status": _state(b), "state": b.payment_state,
                     "url": reverse("purchases:bill", args=[b.pk])})
    for p in SupplierPayment.objects.filter(company=company, status="posted").select_related("supplier")[:100]:
        rows.append({"date": p.date, "type": _("Bill payment"), "number": p.number, "party": p.supplier.name,
                     "amount": p.amount, "currency": p.currency_id, "status": p.get_status_display(), "state": p.status,
                     "url": reverse("purchases:payment", args=[p.pk])})
    rows.sort(key=lambda r: r["date"], reverse=True)
    return render(request, "purchases/expenses.html", {"rows": rows[:150]})


@require_perm("purchases.view")
def statements(request):
    today = timezone.localdate()
    initial = {"date_from": today.replace(month=1, day=1), "date_to": today, "customer": request.GET.get("supplier")}
    form = StatementForm(request.GET if "date_to" in request.GET else None, company=request.company, initial=initial,
                         model=Supplier, label=_("Supplier"))
    data = None
    if form.is_valid():
        d = form.cleaned_data
        data = services.statement(d["customer"], d["date_from"], d["date_to"])
        data.update(contact=d["customer"], date_from=d["date_from"], date_to=d["date_to"])
    return render(request, "sales/statement.html", {"form": form, "data": data, "kind": "supplier", "buckets": AGING_BUCKETS})


@require_perm("purchases.view")
def not_received(request):
    return render(request, "purchases/not_received.html", {
        "outstanding": services.outstanding_lines(request.company),
        "billed": services.billed_not_received(request.company)})

# ---------- Supplier credits (debit notes) ----------
def _credit_defaults(request):
    out = _defaults(request, warehouse=True)
    bid = request.GET.get("bill", "")
    bill = Bill.objects.filter(company=request.company, pk=bid, status="posted").first() if bid.isdigit() else None
    if bill:
        out.update(bill=bill, supplier=bill.supplier, currency=bill.currency, rate=bill.rate,
                   warehouse=bill.warehouse or out.get("warehouse"))
    return out


SUPPLIER_CREDIT = DocSpec(
    key="supplier_credit", voidable=True, ns="purchases", perm="purchases", model=SupplierCredit, header_form=SupplierCreditForm,
    formsets=SUPPLIER_CREDIT_LINES, title=gettext_lazy("Supplier credit"), plural=gettext_lazy("Supplier credits"),
    print_en="Debit Note", print_ar="إشعار مدين", party="supplier", price_source="purchase", statuses=SupplierCredit.STATUSES,
    actions_template="purchases/_supplier_credit_actions.html", related_template="purchases/_supplier_credit_related.html",
    defaults=_credit_defaults,
    columns=[(gettext_lazy("Number"), lambda d: d.number, "text"), (gettext_lazy("Date"), lambda d: d.date, "date"),
             (gettext_lazy("Supplier"), lambda d: d.supplier.name, "text"),
             (gettext_lazy("Supplier's credit note number"), lambda d: d.supplier_credit_no, "text"),
             (gettext_lazy("Total"), lambda d: d.total, "money"), (gettext_lazy("Unused credit"), lambda d: d.available, "money"),
             (gettext_lazy("Status"), lambda d: (d.status, d.get_status_display()), "pill")])


def _supplier_credit_after_save(request, doc):
    if not request.membership.has_perm("purchases.post"):
        return None
    try:
        services.post_supplier_credit(doc, request.user)
    except services.PurchaseError as exc:
        messages.error(request, str(exc))
        return redirect("purchases:supplier_credit", pk=doc.pk)
    messages.success(request, _("Supplier credit %(n)s posted.") % {"n": doc.number})
    return redirect("purchases:supplier_credit", pk=doc.pk)


@require_perm("purchases.view")
def supplier_credits(request):
    return doc_list(request, SUPPLIER_CREDIT)


@require_perm("purchases.create")
def supplier_credit_new(request):
    return doc_form(request, SUPPLIER_CREDIT, after_save=_supplier_credit_after_save, post_label=_("Save and post"))


@require_perm("purchases.edit")
def supplier_credit_edit(request, pk):
    return doc_form(request, SUPPLIER_CREDIT, get_doc(request, SUPPLIER_CREDIT, pk), after_save=_supplier_credit_after_save,
                    post_label=_("Save and post"))


@require_perm("purchases.view")
def supplier_credit(request, pk):
    doc = get_doc(request, SUPPLIER_CREDIT, pk)
    return doc_detail(request, SUPPLIER_CREDIT, doc, {
        "info": _info(doc), "party": doc.supplier, "party_url": reverse("contacts:supplier", args=[doc.supplier_id]),
        "apply_form": ApplySupplierCreditForm(credit=doc), "allocs": doc.allocations.select_related("bill")})


@require_perm("purchases.view")
def supplier_credit_print(request, pk):
    return doc_print(request, SUPPLIER_CREDIT, get_doc(request, SUPPLIER_CREDIT, pk))


@require_POST
@require_perm("purchases.post")
def supplier_credit_action(request, pk):
    doc = get_doc(request, SUPPLIER_CREDIT, pk)
    action = request.POST.get("action")
    try:
        if action == "post":
            return _supplier_credit_after_save(request, doc)
        if action == "apply":
            form = ApplySupplierCreditForm(request.POST, credit=doc)
            if form.is_valid():
                services.apply_supplier_credit(doc, form.cleaned_data["bill"], form.cleaned_data["amount"], request.user)
                messages.success(request, _("Credit applied to %(n)s.") % {"n": form.cleaned_data["bill"].number})
            else:
                messages.error(request, " ".join(e for errs in form.errors.values() for e in errs))
        elif action == "void" and request.membership.has_perm("purchases.void"):
            services.void_supplier_credit(doc, request.user)
            messages.success(request, _("Supplier credit voided."))
    except services.PurchaseError as exc:
        messages.error(request, str(exc))
    return redirect("purchases:supplier_credit", pk=pk)
