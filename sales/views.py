from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from contacts.models import Customer
from core.docviews import DocSpec, doc_detail, doc_form, doc_list, doc_print, get_doc
from core.models import client_ip
from inventory.models import Warehouse
from users.permissions import require_perm

from . import services
from .forms import (INVOICE_LINES, ORDER_LINES, QUOTE_LINES, ConfirmationForm, InvoiceForm, PaymentForm,
                    QuotationForm, SalesOrderForm, StatementForm)
from .models import CustomerPayment, Invoice, Quotation, SalesOrder


def _defaults(request, due=False, warehouse=False):
    today = timezone.localdate()
    out = {"date": today}
    cid = request.GET.get("customer")
    if cid and cid.isdigit():
        customer = Customer.objects.filter(company=request.company, pk=cid).first()
        if customer:
            out["customer"] = customer
            out["currency"] = customer.currency
            if due:
                out["due_date"] = today + timedelta(days=customer.payment_terms_days)
    if due and "due_date" not in out:
        out["due_date"] = today + timedelta(days=30)
    if warehouse:
        out["warehouse"] = Warehouse.objects.filter(company=request.company, is_active=True).first()
    return out


COLUMNS = [
    (gettext_lazy("Number"), lambda d: d.number, "text"),
    (gettext_lazy("Date"), lambda d: d.date, "date"),
    (gettext_lazy("Customer"), lambda d: d.customer.name, "text"),
    (gettext_lazy("Reference"), lambda d: d.reference, "text"),
    (gettext_lazy("Total"), lambda d: d.total, "money"),
    (gettext_lazy("Currency"), lambda d: d.currency_id, "text"),
    (gettext_lazy("Status"), lambda d: (d.status, d.get_status_display()), "pill"),
]

QUOTE = DocSpec(key="quote", ns="sales", perm="sales", model=Quotation, header_form=QuotationForm, formsets=QUOTE_LINES,
                title=gettext_lazy("Quotation"), plural=gettext_lazy("Quotations"), print_en="Quotation",
                print_ar="عرض سعر", party="customer", columns=COLUMNS, statuses=Quotation.STATUSES,
                actions_template="sales/_quote_actions.html", editable_statuses=("draft", "sent"),
                defaults=lambda r: _defaults(r) | {"valid_until": timezone.localdate() + timedelta(days=30)})
ORDER = DocSpec(key="order", ns="sales", perm="sales", model=SalesOrder, header_form=SalesOrderForm, formsets=ORDER_LINES,
                title=gettext_lazy("Sales order"), plural=gettext_lazy("Sales orders"), print_en="Sales Order",
                print_ar="أمر بيع", party="customer", columns=COLUMNS, statuses=SalesOrder.STATUSES,
                actions_template="sales/_order_actions.html", related_template="sales/_order_related.html",
                editable_statuses=("draft", "open"), defaults=lambda r: _defaults(r, warehouse=True))
INVOICE = DocSpec(key="invoice", ns="sales", perm="sales", model=Invoice, header_form=InvoiceForm, formsets=INVOICE_LINES,
                  title=gettext_lazy("Invoice"), plural=gettext_lazy("Invoices"), print_en="Tax Invoice",
                  print_ar="فاتورة ضريبية", party="customer", statuses=Invoice.STATUSES,
                  columns=COLUMNS[:4] + [(gettext_lazy("Due date"), lambda d: d.due_date, "date"),
                                         (gettext_lazy("Total"), lambda d: d.total, "money"),
                                         (gettext_lazy("Balance due"), lambda d: d.balance_due, "money"),
                                         (gettext_lazy("Status"), lambda d: (d.payment_state, _state(d)), "pill")],
                  actions_template="sales/_invoice_actions.html", related_template="sales/_invoice_related.html",
                  defaults=lambda r: _defaults(r, due=True, warehouse=True))


def _state(doc):
    from core.templatetags.trib import state_label
    return state_label(doc.payment_state)


def _info(doc):
    rows = [(_("Customer"), doc.customer), (_("Reference"), doc.reference), (_("Branch"), doc.branch)]
    for attr, label in (("due_date", _("Due date")), ("valid_until", _("Valid until")), ("expected_date", _("Delivery date"))):
        if getattr(doc, attr, None):
            rows.append((label, getattr(doc, attr).strftime("%d/%m/%Y")))
    if getattr(doc, "warehouse", None):
        rows.append((_("Warehouse"), doc.warehouse))
    return rows


def _detail(request, spec, pk, extra=None):
    doc = get_doc(request, spec, pk)
    from django.urls import reverse
    ctx = {"info": _info(doc), "party": doc.customer, "party_url": reverse("contacts:customer", args=[doc.customer_id])}
    ctx.update(extra or {})
    return doc_detail(request, spec, doc, ctx)


# ---------- Quotations ----------
@require_perm("sales.view")
def quotes(request):
    return doc_list(request, QUOTE)


@require_perm("sales.create")
def quote_new(request):
    return doc_form(request, QUOTE)


@require_perm("sales.edit")
def quote_edit(request, pk):
    return doc_form(request, QUOTE, get_doc(request, QUOTE, pk))


@require_perm("sales.view")
def quote(request, pk):
    return _detail(request, QUOTE, pk)


@require_perm("sales.view")
def quote_print(request, pk):
    return doc_print(request, QUOTE, get_doc(request, QUOTE, pk))


@require_POST
@require_perm("sales.edit")
@transaction.atomic
def quote_action(request, pk):
    doc = get_doc(request, QUOTE, pk)
    action = request.POST.get("action")
    from core.models import NumberSeries
    if action in ("sent", "accepted", "declined"):
        if not doc.number:
            doc.number = NumberSeries.next(request.company, "QT", doc.date)
        doc.status = action
        doc.save(update_fields=["number", "status"])
        messages.success(request, _("Saved."))
    elif action == "to_order":
        order = services.quote_to_order(doc, request.user)
        return redirect("sales:order_edit", pk=order.pk)
    elif action == "to_invoice":
        invoice = services.quote_to_invoice(doc, request.user)
        return redirect("sales:invoice_edit", pk=invoice.pk)
    return redirect("sales:quote", pk=pk)


# ---------- Sales orders ----------
@require_perm("sales.view")
def orders(request):
    return doc_list(request, ORDER)


@require_perm("sales.create")
def order_new(request):
    return doc_form(request, ORDER)


@require_perm("sales.edit")
def order_edit(request, pk):
    return doc_form(request, ORDER, get_doc(request, ORDER, pk))


@require_perm("sales.view")
def order(request, pk):
    return _detail(request, ORDER, pk)


@require_perm("sales.view")
def order_print(request, pk):
    return doc_print(request, ORDER, get_doc(request, ORDER, pk))


@require_POST
@require_perm("sales.edit")
@transaction.atomic
def order_action(request, pk):
    doc = get_doc(request, ORDER, pk)
    action = request.POST.get("action")
    from core.models import NumberSeries
    if action == "confirm" and doc.status == "draft":
        doc.number = doc.number or NumberSeries.next(request.company, "SO", doc.date)
        doc.status = "open"
        doc.save(update_fields=["number", "status"])
        messages.success(request, _("Sales order confirmed."))
    elif action == "invoice" and doc.status in ("open", "partial"):
        invoice = services.order_to_invoice(doc, request.user)
        return redirect("sales:invoice_edit", pk=invoice.pk)
    elif action == "cancel" and doc.status in ("draft", "open"):
        doc.status = "cancelled"
        doc.save(update_fields=["status"])
        messages.success(request, _("Sales order cancelled."))
    return redirect("sales:order", pk=pk)


# ---------- Invoices ----------
def _post_after_save(request, doc):
    if not request.membership.has_perm("sales.post"):
        return None
    try:
        services.post_invoice(doc, request.user, allow_over_limit=bool(request.POST.get("over_limit")))
    except services.SalesError as exc:
        messages.error(request, str(exc))
        return redirect("sales:invoice", pk=doc.pk)
    messages.success(request, _("Invoice %(n)s posted.") % {"n": doc.number})
    return redirect("sales:invoice", pk=doc.pk)


@require_perm("sales.view")
def invoices(request):
    return doc_list(request, INVOICE)


@require_perm("sales.create")
def invoice_new(request):
    return doc_form(request, INVOICE, after_save=_post_after_save, post_label=_("Save and post"))


@require_perm("sales.edit")
def invoice_edit(request, pk):
    return doc_form(request, INVOICE, get_doc(request, INVOICE, pk), after_save=_post_after_save,
                    post_label=_("Save and post"))


@require_perm("sales.view")
def invoice(request, pk):
    return _detail(request, INVOICE, pk)


@require_perm("sales.view")
def invoice_print(request, pk):
    doc = get_doc(request, INVOICE, pk)
    bank = request.company.bank_accounts.filter(kind="bank", currency=doc.currency, is_active=True).first()
    details = f"{bank.name_en} · {bank.account_number}" + (f" · IBAN {bank.iban}" if bank.iban else "") if bank else ""
    return doc_print(request, INVOICE, doc, {"bank_details": details})


@require_POST
@require_perm("sales.post")
def invoice_action(request, pk):
    doc = get_doc(request, INVOICE, pk)
    action = request.POST.get("action")
    if action == "post":
        return _post_after_save(request, doc)
    if action == "void" and request.membership.has_perm("sales.void"):
        try:
            services.void_invoice(doc, request.user)
            messages.success(request, _("Invoice voided."))
        except services.SalesError as exc:
            messages.error(request, str(exc))
    return redirect("sales:invoice", pk=pk)


# ---------- Customer payments ----------
@require_perm("sales.view")
def payments(request):
    qs = CustomerPayment.objects.filter(company=request.company).select_related("customer", "currency", "bank_account")
    page = Paginator(qs, 40).get_page(request.GET.get("page"))
    return render(request, "sales/payments.html", {"page": page})


@require_perm("sales.create")
def payment_new(request):
    company = request.company
    initial = {"date": timezone.localdate(), "currency": company.base_currency, "method": "bank"}
    cid = request.GET.get("customer") or request.POST.get("customer")
    customer = Customer.objects.filter(company=company, pk=cid).first() if cid and str(cid).isdigit() else None
    if customer:
        initial.update(customer=customer, currency=customer.currency)
    form = PaymentForm(request.POST or None, company=company, initial=initial,
                       instance=CustomerPayment(company=company, created_by=request.user))
    open_invoices = []
    if customer:
        open_invoices = [i for i in Invoice.objects.filter(customer=customer, status="posted").order_by("due_date")
                         if i.balance_due > 0]
    if request.method == "POST" and form.is_valid() and "save" in request.POST:
        payment = form.save(commit=False)
        payment.company, payment.created_by = company, request.user
        allocations = []
        for inv in open_invoices:
            raw = request.POST.get(f"alloc_{inv.pk}", "").replace(",", "").strip()
            if raw:
                try:
                    allocations.append((inv, Decimal(raw)))
                except InvalidOperation:
                    pass
        try:
            services.post_payment(payment, allocations, request.user)
        except services.SalesError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, _("Payment %(n)s recorded.") % {"n": payment.number})
            return redirect("sales:payment", pk=payment.pk)
    return render(request, "sales/payment_form.html", {"form": form, "customer": customer, "open_invoices": open_invoices})


@require_perm("sales.view")
def payment(request, pk):
    p = get_object_or_404(CustomerPayment, pk=pk, company=request.company)
    return render(request, "sales/payment_detail.html", {"p": p, "allocs": p.allocations.select_related("invoice")})


@require_perm("sales.view")
def payment_print(request, pk):
    from core.amount_words import amount_in_words
    p = get_object_or_404(CustomerPayment, pk=pk, company=request.company)
    return render(request, "sales/payment_print.html", {
        "p": p, "allocs": p.allocations.select_related("invoice"),
        "words_en": amount_in_words(p.amount, p.currency_id, "en"), "words_ar": amount_in_words(p.amount, p.currency_id, "ar"),
        "balance": services.customer_balance(p.customer)})


@require_POST
@require_perm("sales.void")
def payment_void(request, pk):
    p = get_object_or_404(CustomerPayment, pk=pk, company=request.company)
    try:
        services.void_payment(p, request.user)
        messages.success(request, _("Payment voided."))
    except services.SalesError as exc:
        messages.error(request, str(exc))
    return redirect("sales:payment", pk=pk)


# ---------- Statements & confirmations ----------
@require_perm("sales.view")
def statements(request):
    today = timezone.localdate()
    initial = {"date_from": today.replace(month=1, day=1), "date_to": today, "customer": request.GET.get("customer")}
    form = StatementForm(request.GET if "date_to" in request.GET else None, company=request.company, initial=initial)
    data = None
    if form.is_valid():
        d = form.cleaned_data
        data = services.statement(d["customer"], d["date_from"], d["date_to"])
        data.update(contact=d["customer"], date_from=d["date_from"], date_to=d["date_to"])
    return render(request, "sales/statement.html", {"form": form, "data": data, "kind": "customer",
                                                    "buckets": services.AGING_BUCKETS})


@require_perm("sales.view")
def confirmations(request):
    today = timezone.localdate()
    year_end = today.replace(month=12, day=31) if today.month == 12 else today.replace(year=today.year - 1, month=12, day=31)
    form = ConfirmationForm(request.GET if "as_of" in request.GET else None,
                            initial={"as_of": year_end, "reply_by": today + timedelta(days=21)})
    letters = []
    if form.is_valid():
        as_of = form.cleaned_data["as_of"]
        for c in Customer.objects.filter(company=request.company, is_active=True).order_by("name_en"):
            bal = services.customer_balance(c, as_of=as_of)
            if bal or form.cleaned_data["include_zero"]:
                letters.append({"contact": c, "balance": bal})
        return render(request, "sales/confirmations_print.html", {"letters": letters, "as_of": as_of,
                                                                  "reply_by": form.cleaned_data["reply_by"]})
    return render(request, "sales/confirmations.html", {"form": form})
