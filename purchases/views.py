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
from core import access
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
        out["warehouse"] = access.scope(Warehouse.objects.filter(company=request.company, is_active=True)).first()
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
    from django.utils.dateparse import parse_datetime

    for n, a in enumerate(getattr(doc, "approvals", None) or [], start=1):
        at = parse_datetime(a.get("at") or "")
        limit = _("no limit") if a.get("limit") is None else f"{Decimal(a['limit']):,.0f}"
        rows.append((_("Approval %(n)s") % {"n": n},
                     f"{a.get('name')} · {timezone.localtime(at):%d/%m/%Y %H:%M} · {_('limit')} {limit}" if at else a.get("name")))
    if getattr(doc, "approved_by_id", None):
        rows.append((_("Approved by"), f"{doc.approved_by} · {doc.approved_at:%d/%m/%Y %H:%M}"))
    if getattr(doc, "approval_requested_at", None) and doc.status == "draft":
        rows.append((_("Waiting for approval"), f"{doc.approval_requested_by} · "
                                                f"{timezone.localtime(doc.approval_requested_at):%d/%m/%Y %H:%M}"))
    return rows


def _detail(request, spec, pk):
    doc = get_doc(request, spec, pk)
    extra = {"info": _info(doc), "party": doc.supplier, "party_url": reverse("contacts:supplier", args=[doc.supplier_id]),
             "amount_base": doc.amount_base if hasattr(doc, "amount_base") else None}
    if spec is ORDER and doc.status == "submitted":
        extra["approve_block"] = services.order_approval_block(doc, request.user, request.membership)
        extra["approve_limit"] = request.membership.approval_limit("purchase_order")
    if spec is BILL and doc.status == "draft":
        extra["bill_limit"] = services.bill_over_limit(doc, request.membership)
    return doc_detail(request, spec, doc, extra)


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
            if services.approve_order(doc, request.user, m) == "approved":
                messages.success(request, _("Purchase order approved."))
            else:
                messages.warning(request, _("Approved at your level. The amount is above your limit, so it now goes to "
                                            "someone whose purchase order limit covers %(a)s.") % {
                    "a": f"{doc.amount_base:,.2f} {request.company.base_currency_id}"})
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
    qs = access.scope(GoodsReceipt.objects.filter(company=request.company)).select_related("supplier", "warehouse", "purchase_order")
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
                       warehouse=access.scope(Warehouse.objects.filter(company=request.company, is_active=True)).first())
    return _receipt_form(request, grn)


@require_perm("purchases.edit")
def receipt_edit(request, pk):
    grn = get_object_or_404(access.scope(GoodsReceipt.objects.filter(company=request.company)), pk=pk)
    if grn.status != "draft":
        messages.error(request, _("This document can no longer be changed."))
        return redirect("purchases:receipt", pk=pk)
    return _receipt_form(request, grn)


@require_perm("purchases.view")
def receipt(request, pk):
    grn = get_object_or_404(access.scope(GoodsReceipt.objects.filter(company=request.company)), pk=pk)
    return render(request, "purchases/receipt_detail.html", {"grn": grn, "lines": grn.lines.select_related("item", "order_line")})


@require_POST
@require_perm("inventory.post")
def receipt_post(request, pk):
    grn = get_object_or_404(access.scope(GoodsReceipt.objects.filter(company=request.company)), pk=pk)
    try:
        services.post_receipt(grn, request.user)
        messages.success(request, _("Item receipt %(n)s posted. Stock is in the warehouse.") % {"n": grn.number})
    except services.PurchaseError as exc:
        messages.error(request, str(exc))
    return redirect("purchases:receipt", pk=pk)


@require_perm("purchases.view")
def receipt_print(request, pk):
    grn = get_object_or_404(access.scope(GoodsReceipt.objects.filter(company=request.company)), pk=pk)
    return render(request, "purchases/receipt_print.html", {"grn": grn, "lines": grn.lines.select_related("item")})


# ---------- Bills ----------
def _post_after_save(request, doc):
    if not request.membership.has_perm("purchases.post"):
        return None
    limit = services.bill_over_limit(doc, request.membership)
    if limit is not None:
        # Above this person's limit: it waits, as a draft, for someone whose bill limit covers it.
        services.request_bill_approval(doc, request.user)
        messages.warning(request, _("This bill (%(a)s) is above your posting limit of %(l)s. It has been sent for approval "
                                    "and will be posted by someone whose limit covers it.") % {
            "a": f"{doc.amount_base:,.2f} {request.company.base_currency_id}", "l": f"{limit:,.2f}"})
        return redirect("purchases:bill", pk=doc.pk)
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
    from contacts.models import Supplier
    from core.filters import DATES
    return render(request, "purchases/payments.html", {
        "page": page, "drill": drill, "filter_dates": DATES, "list_key": "purchases-payments", "filter_party_label": _("Supplier"),
        "filter_party": list(Supplier.objects.filter(company=request.company, is_active=True).values_list("pk", "name_en"))})


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
            # Straight on to the remittance advice, ready to print or email to the supplier.
            return redirect(reverse("purchases:payment_print", args=[payment.pk]) + "?paid=1")
    return render(request, "purchases/payment_form.html", {"form": form, "supplier": supplier, "open_bills": open_bills})


@require_perm("purchases.view")
def payment(request, pk):
    p = get_object_or_404(SupplierPayment, pk=pk, company=request.company)
    return render(request, "purchases/payment_detail.html", {"p": p, "allocs": p.allocations.select_related("bill")})


@require_perm("purchases.view")
def payment_print(request, pk):
    p = get_object_or_404(SupplierPayment, pk=pk, company=request.company)
    return _remittance_page(request, [p], back_url=reverse("purchases:payment", args=[p.pk]),
                            just_paid=request.GET.get("paid") == "1")


@require_perm("purchases.view")
def remittance_print(request):
    """Several remittance advices, one per page (supplier page → select payments → Print selected)."""
    from .remittance import payments_from
    payments = payments_from(request.company, request.GET.get("ids", ""))
    back = (reverse("contacts:supplier", args=[payments[0].supplier_id]) if payments
            else reverse("purchases:payments"))
    return _remittance_page(request, payments, back_url=back)


def _remittance_page(request, payments, back_url, just_paid=False):
    from .remittance import remittance
    return render(request, "purchases/remittance.html", {
        "items": [remittance(p) for p in payments], "ids": ",".join(str(p.pk) for p in payments),
        "back_url": back_url, "just_paid": just_paid})


@require_perm("purchases.create")
def remittance_email(request):
    """Email one or more remittance advices (all to the same supplier) in one email."""
    from django.template.loader import render_to_string
    from django.utils.formats import date_format

    from core.mailer import bilingual, review_and_send

    from .remittance import payments_from, remittance
    payments = payments_from(request.company, request.GET.get("ids", ""))
    if not payments:
        messages.error(request, _("Choose at least one payment."))
        return redirect("purchases:payments")
    supplier = payments[0].supplier
    if any(p.supplier_id != supplier.pk for p in payments):
        messages.error(request, _("Choose payments to one supplier at a time."))
        return redirect("purchases:payments")
    company = request.company
    items = [remittance(p) for p in payments]
    numbers = ", ".join(p.number for p in payments)
    total = sum((p.amount for p in payments), Decimal("0"))
    if len(payments) == 1:
        p = payments[0]
        subject = _("Remittance advice %(number)s from %(company)s") % {"number": p.number, "company": company.name}
        message = _("Dear %(name)s,\n\nWe have paid %(amount)s %(cur)s on %(date)s. The details of the invoices this "
                    "payment covers are below.\n\nKind regards,\n%(company)s") % {
            "name": supplier.name, "amount": f"{p.amount:,.2f}", "cur": p.currency_id,
            "date": date_format(p.date, "d/m/Y"), "company": company.name}
    else:
        subject = _("Remittance advice for %(n)s payments from %(company)s") % {"n": len(payments), "company": company.name}
        message = _("Dear %(name)s,\n\nPlease find below our remittance advice for payments %(numbers)s, %(amount)s "
                    "in total. Each shows the invoices it covers.\n\nKind regards,\n%(company)s") % {
            "name": supplier.name, "numbers": numbers, "amount": f"{total:,.2f}", "company": company.name}

    def build(text):
        ctx = {"items": items, "company": company, "message": text, "subject": subject, "bi": bilingual(company)}
        return (render_to_string("purchases/email_remittance.html", ctx),
                render_to_string("purchases/email_remittance.txt", ctx))

    back = (reverse("purchases:payment", args=[payments[0].pk]) if len(payments) == 1
            else reverse("contacts:supplier", args=[supplier.pk]))
    return review_and_send(
        request, initial={"to": supplier.email, "subject": subject, "message": message}, build=build,
        title=f"{_('Remittance advice')} · {supplier.name} · {numbers}", back_url=back,
        crumbs=[(_("Bill payments"), reverse("purchases:payments")), (supplier.name, reverse("contacts:supplier", args=[supplier.pk]))],
        audit_action="payment.remittance_sent", audit_obj=payments[0], summary=numbers,
        note=_("The email contains the remittance advice itself, so your supplier can read it without signing in."))


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
    from core.filters import DATES
    from ledger.models import Account

    from . import expenses as exp
    rows, filters = exp.rows(request.company, request)
    categories = Account.objects.filter(company=request.company, is_group=False, is_active=True,
                                        type__in=("expense", "asset", "liability")).order_by("code")
    return render(request, "purchases/expenses.html", {
        "rows": rows, "filters": filters, "types": exp.TYPES, "categories": categories, "list_key": "expenses",
        "filter_dates": DATES, "can_reclass": request.membership.has_perm("ledger.post"),
        "filter_statuses": [("draft", _("Draft")), ("posted", _("Posted")), ("unpaid", _("Unpaid")), ("paid", _("Paid")),
                            ("overdue", _("Overdue"))],
        "totals": {"before_tax": sum(r["before_tax"] for r in rows), "tax": sum(r["tax"] for r in rows),
                   "total": sum(r["total"] for r in rows)}})


@require_POST
@require_perm("ledger.post")
def expense_category(request):
    from django.core.exceptions import MultipleObjectsReturned, ObjectDoesNotExist
    from django.http import JsonResponse

    from ledger.models import Account
    from ledger.services import PostingError

    from . import expenses as exp
    account = Account.objects.filter(company=request.company, pk=request.POST.get("account") or 0).first()
    if account is None:
        return JsonResponse({"error": _("Choose an account.")}, status=400)
    try:
        entry = exp.reclassify(request.company, request.POST.get("key", ""), account, request.user)
    except (PostingError, ObjectDoesNotExist, MultipleObjectsReturned) as exc:  # e.g. a locked period
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"ok": True, "entry": entry.number if entry else None, "name": account.name})


@require_perm("purchases.create")
def import_bills(request):
    """Import bills from Excel: upload → preview with problems → create drafts."""
    from django.http import HttpResponse

    from core.models import AuditLog

    from . import import_bills as imp
    if request.GET.get("template") == "1":
        response = HttpResponse(imp.template_workbook(),
                                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = 'attachment; filename="trib-bills-template.xlsx"'
        return response
    preview = request.session.get("bills.import")
    if request.method == "POST" and "confirm" in request.POST and preview:
        made = imp.create(request.company, preview["bills"], request.user)
        request.session.pop("bills.import", None)
        AuditLog.record(request.company, request.user, "bills.imported", None, f"{len(made)} draft bills")
        messages.success(request, _("%(n)s draft bills created. Review and post them.") % {"n": len(made)})
        return redirect(f"{reverse('purchases:bills')}?status=draft")
    if request.method == "POST" and request.FILES.get("file"):
        upload = request.FILES["file"]
        if upload.size > 5 * 1024 * 1024 or not upload.name.lower().endswith((".xlsx", ".csv")):
            messages.error(request, _("Upload an Excel (.xlsx) or CSV file up to 5 MB."))
            return redirect("purchases:import_bills")
        try:
            bills, problems = imp.parse(request.company, upload)
        except Exception as exc:  # unreadable files come back as a message
            bills, problems = [], [_("The file could not be read: %(e)s") % {"e": exc}]
        request.session["bills.import"] = {"bills": bills, "problems": problems}
        return redirect("purchases:import_bills")
    if request.GET.get("reset") == "1":
        request.session.pop("bills.import", None)
        return redirect("purchases:import_bills")
    return render(request, "purchases/import_bills.html", {"preview": preview, "columns": imp.COLUMNS})


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
        data.update(contact=d["customer"], date_from=d["date_from"], date_to=d["date_to"], style="balance")
        from sales.statements import finish
        finish(data, request.company)
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
