import dataclasses
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
from core import access
from core.docviews import DocSpec, doc_detail, doc_form, doc_list, doc_print, get_doc
from core.models import client_ip
from inventory.models import Warehouse
from users.permissions import require_perm

from . import services
from .forms import (CREDIT_LINES, INVOICE_LINES, ORDER_LINES, QUOTE_LINES, ApplyCreditForm, ConfirmationForm, CreditNoteForm,
                    InvoiceForm, PaymentForm, QuotationForm, RefundForm, SalesOrderForm, SalesReceiptForm, StatementForm)
from .models import CreditNote, CustomerPayment, CustomerRefund, Invoice, Quotation, SalesOrder


def terms_for(days):
    return {v: k for k, v in Invoice.TERM_DAYS.items()}.get(days, "custom")


def party_header(customer):
    """Email, bill-to and ship-to filled from the customer card."""
    address = "\n".join(x for x in (customer.name, customer.address, customer.city) if x)
    return {"email_to": customer.email, "bill_to": address,
            "ship_to": customer.shipping_address or ""}


def _defaults(request, due=False, warehouse=False):
    today = timezone.localdate()
    out = {"date": today}
    cid = request.GET.get("customer")
    if cid and cid.isdigit():
        customer = access.scope(Customer.objects.filter(company=request.company, pk=cid)).first()
        if customer:
            out["customer"] = customer
            out["currency"] = customer.currency
            out.update(party_header(customer))
            if due:
                out["due_date"] = today + timedelta(days=customer.payment_terms_days)
                out["terms"] = terms_for(customer.payment_terms_days)
    if due and "due_date" not in out:
        out["due_date"] = today + timedelta(days=30)
    if warehouse:
        out["warehouse"] = access.scope(Warehouse.objects.filter(company=request.company, is_active=True)).first()
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
INVOICE = DocSpec(key="invoice", voidable=True, recurring_kind="invoice", ns="sales", perm="sales", model=Invoice, header_form=InvoiceForm, formsets=INVOICE_LINES,
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
    from core.filters import apply as drill_filter
    qs = access.scope(CustomerPayment.objects.filter(company=request.company)).select_related("customer", "currency", "bank_account")
    qs, drill = drill_filter(request, qs, "customer")
    page = Paginator(qs, 40).get_page(request.GET.get("page"))
    from contacts.models import Customer
    from core.filters import DATES
    return render(request, "sales/payments.html", {
        "page": page, "drill": drill, "filter_dates": DATES, "list_key": "sales-payments", "filter_party_label": _("Customer"),
        "filter_party": list(access.scope(Customer.objects.filter(company=request.company, is_active=True))
                             .values_list("pk", "name_en"))})


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
    p = get_object_or_404(access.scope(CustomerPayment.objects.filter(company=request.company)), pk=pk)
    return render(request, "sales/payment_detail.html", {"p": p, "allocs": p.allocations.select_related("invoice")})


@require_perm("sales.view")
def payment_print(request, pk):
    from core.amount_words import amount_in_words
    p = get_object_or_404(access.scope(CustomerPayment.objects.filter(company=request.company)), pk=pk)
    return render(request, "sales/payment_print.html", {
        "p": p, "allocs": p.allocations.select_related("invoice"),
        "words_en": amount_in_words(p.amount, p.currency_id, "en"), "words_ar": amount_in_words(p.amount, p.currency_id, "ar"),
        "balance": services.customer_balance(p.customer)})


@require_POST
@require_perm("sales.void")
def payment_void(request, pk):
    p = get_object_or_404(access.scope(CustomerPayment.objects.filter(company=request.company)), pk=pk)
    try:
        services.void_payment(p, request.user)
        messages.success(request, _("Payment voided."))
    except services.SalesError as exc:
        messages.error(request, str(exc))
    return redirect("sales:payment", pk=pk)


# ---------- Statements & confirmations ----------
@require_perm("sales.view")
def statements(request):
    from . import statements as st
    form, data = st.from_request(request)
    return render(request, "sales/statement.html", {"form": form, "data": data, "kind": "customer",
                                                    "query": request.GET.urlencode()})


@require_perm("sales.create")
def statement_email(request):
    """Email a customer their statement (the statement itself is in the email)."""
    from django.urls import reverse

    from core.mailer import review_and_send

    from . import statements as st
    _form, data = st.from_request(request)
    if data is None:
        messages.error(request, _("Choose the customer and dates first."))
        return redirect("sales:statements")
    company, customer = request.company, data["contact"]
    subject = st.default_subject(company)
    return review_and_send(
        request, initial={"to": customer.email, "subject": subject, "message": st.default_message(company, data)},
        build=lambda text: st.email_parts(company, data, text, subject),
        title=f"{_('Statement')} · {customer.name}", back_url=f"{reverse('sales:statements')}?{request.GET.urlencode()}",
        crumbs=[(_("Customer statements"), reverse("sales:statements")),
                (customer.name, reverse("contacts:customer", args=[customer.pk]))],
        audit_action="customer.statement_sent", audit_obj=customer, summary=_("Statement"),
        note=_("The email contains the statement itself, so your customer can read it without signing in."))


@require_perm("sales.view")
def statements_batch(request):
    """Statements for every customer with a balance (or only overdue ones): print them all, or email each customer."""
    from django.conf import settings
    from django.core.mail import EmailMultiAlternatives

    from core.doc_actions import email_ready
    from core.models import AuditLog, client_ip

    from . import statements as st
    today = timezone.localdate()
    form = st.BatchForm(request.GET or None, initial={"date_from": today.replace(month=1, day=1), "date_to": today})
    rows = st.batch_customers(request, form.cleaned_data) if form.is_valid() else []
    if form.is_valid() and request.GET.get("print") == "1":
        d = form.cleaned_data
        items = [st.build(r["c"], d["date_from"], d["date_to"], d["style"], request.company) for r in rows]
        return render(request, "sales/statements_print.html", {"items": items, "back": f"?{request.GET.urlencode().replace('&print=1', '')}"})
    ready = email_ready()
    if request.method == "POST" and form.is_valid():
        if not request.membership.has_perm("sales.create") or not ready:
            messages.error(request, _("Email isn't set up yet, so TriB can't send statements. Print them instead."))
            return redirect(request.get_full_path())
        d, company = form.cleaned_data, request.company
        sent, skipped, failed = [], [], []
        subject = st.default_subject(company)
        for r in rows:
            c = r["c"]
            if not c.email:
                skipped.append(c.name)
                continue
            data = st.build(c, d["date_from"], d["date_to"], d["style"], company)
            html, text = st.email_parts(company, data, st.default_message(company, data), subject)
            mail = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, [c.email],
                                          reply_to=[company.email] if company.email else None)
            mail.attach_alternative(html, "text/html")
            try:
                mail.send()
            except Exception:  # one bad address does not stop the others
                failed.append(c.name)
                continue
            AuditLog.record(company, request.user, "customer.statement_sent", c, f"Statement → {c.email}",
                            ip=client_ip(request))
            sent.append(c.name)
        if sent:
            messages.success(request, _("%(n)s statements sent.") % {"n": len(sent)})
        if skipped:
            messages.warning(request, _("No email address, so not sent: %(names)s") % {"names": ", ".join(skipped)})
        if failed:
            messages.error(request, _("Could not be sent: %(names)s") % {"names": ", ".join(failed)})
        return redirect(request.get_full_path())
    return render(request, "sales/statements_batch.html", {
        "form": form, "rows": rows, "ready": ready, "query": request.GET.urlencode(),
        "with_email": sum(1 for r in rows if r["c"].email)})


@require_perm("sales.view")
def confirmations(request):
    today = timezone.localdate()
    year_end = today.replace(month=12, day=31) if today.month == 12 else today.replace(year=today.year - 1, month=12, day=31)
    form = ConfirmationForm(request.GET if "as_of" in request.GET else None,
                            initial={"as_of": year_end, "reply_by": today + timedelta(days=21)})
    letters = []
    if form.is_valid():
        as_of = form.cleaned_data["as_of"]
        for c in access.scope(Customer.objects.filter(company=request.company, is_active=True)).order_by("name_en"):
            bal = services.customer_balance(c, as_of=as_of)
            if bal or form.cleaned_data["include_zero"]:
                letters.append({"contact": c, "balance": bal})
        return render(request, "sales/confirmations_print.html", {"letters": letters, "as_of": as_of,
                                                                  "reply_by": form.cleaned_data["reply_by"]})
    return render(request, "sales/confirmations.html", {"form": form})

# ---------- Sales receipts (cash sales) ----------
SALES_RECEIPT = dataclasses.replace(INVOICE, header_form=SalesReceiptForm, title=gettext_lazy("Sales receipt"),
                                    plural=gettext_lazy("Invoices"), defaults=lambda r: _defaults(r, warehouse=True))


def _receipt_after_save(request, doc):
    from banking.models import BankAccount
    if not request.membership.has_perm("sales.post"):
        return None
    deposit_to = BankAccount.objects.filter(company=request.company, pk=request.POST.get("deposit_to") or 0).first()
    try:
        payment = services.post_sales_receipt(doc, deposit_to, request.user)
    except services.SalesError as exc:
        messages.error(request, str(exc))
        return redirect("sales:invoice", pk=doc.pk)
    messages.success(request, _("Sales receipt %(n)s posted and paid (%(p)s).") % {"n": doc.number, "p": payment.number})
    return redirect("sales:invoice", pk=doc.pk)


@require_perm("sales.create")
def sales_receipt_new(request):
    return doc_form(request, SALES_RECEIPT, after_save=_receipt_after_save, post_label=_("Save and receive payment"))


# ---------- Credit notes ----------
CREDIT = DocSpec(key="credit", voidable=True, ns="sales", perm="sales", model=CreditNote, header_form=CreditNoteForm,
                 formsets=CREDIT_LINES, title=gettext_lazy("Credit note"), plural=gettext_lazy("Credit notes"),
                 print_en="Credit Note", print_ar="إشعار دائن", party="customer", statuses=CreditNote.STATUSES,
                 columns=COLUMNS[:3] + [(gettext_lazy("Original invoice"), lambda d: d.invoice.number if d.invoice_id else "", "text"),
                                        (gettext_lazy("Total"), lambda d: d.total, "money"),
                                        (gettext_lazy("Unused credit"), lambda d: d.available, "money"),
                                        (gettext_lazy("Status"), lambda d: (d.status, d.get_status_display()), "pill")],
                 actions_template="sales/_credit_actions.html", related_template="sales/_credit_related.html",
                 defaults=lambda r: _credit_defaults(r))


def _credit_defaults(request):
    out = _defaults(request, warehouse=True)
    iid = request.GET.get("invoice", "")
    inv = access.scope(Invoice.objects.filter(company=request.company, pk=iid, status="posted")).first() if iid.isdigit() else None
    if inv:
        out.update(invoice=inv, customer=inv.customer, currency=inv.currency, rate=inv.rate, warehouse=inv.warehouse,
                   prices_include_tax=inv.prices_include_tax)
    return out


def _credit_after_save(request, doc):
    if not request.membership.has_perm("sales.post"):
        return None
    try:
        services.post_credit_note(doc, request.user)
    except services.SalesError as exc:
        messages.error(request, str(exc))
        return redirect("sales:credit", pk=doc.pk)
    messages.success(request, _("Credit note %(n)s posted.") % {"n": doc.number})
    return redirect("sales:credit", pk=doc.pk)


@require_perm("sales.view")
def credits(request):
    return doc_list(request, CREDIT)


@require_perm("sales.create")
def credit_new(request):
    return doc_form(request, CREDIT, after_save=_credit_after_save, post_label=_("Save and post"))


@require_perm("sales.edit")
def credit_edit(request, pk):
    return doc_form(request, CREDIT, get_doc(request, CREDIT, pk), after_save=_credit_after_save, post_label=_("Save and post"))


@require_perm("sales.view")
def credit(request, pk):
    doc = get_doc(request, CREDIT, pk)
    return _detail(request, CREDIT, pk, {"apply_form": ApplyCreditForm(note=doc, initial={"amount": doc.available}),
                                         "allocs": doc.allocations.select_related("invoice"),
                                         "refunds": doc.refunds.filter(status="posted")})


@require_perm("sales.view")
def credit_print(request, pk):
    return doc_print(request, CREDIT, get_doc(request, CREDIT, pk))


@require_POST
@require_perm("sales.post")
def credit_action(request, pk):
    doc = get_doc(request, CREDIT, pk)
    action = request.POST.get("action")
    try:
        if action == "post":
            return _credit_after_save(request, doc)
        if action == "apply":
            form = ApplyCreditForm(request.POST, note=doc)
            if form.is_valid():
                services.apply_credit(doc, form.cleaned_data["invoice"], form.cleaned_data["amount"], request.user)
                messages.success(request, _("Credit applied to %(n)s.") % {"n": form.cleaned_data["invoice"].number})
            else:
                messages.error(request, " ".join(e for errs in form.errors.values() for e in errs))
        elif action == "void" and request.membership.has_perm("sales.void"):
            services.void_credit_note(doc, request.user)
            messages.success(request, _("Credit note voided."))
    except services.SalesError as exc:
        messages.error(request, str(exc))
    return redirect("sales:credit", pk=pk)


# ---------- Refunds ----------
@require_perm("sales.view")
def refunds(request):
    qs = access.scope(CustomerRefund.objects.filter(company=request.company)).select_related("customer", "currency", "bank_account", "credit_note")
    return render(request, "sales/refunds.html", {"page": Paginator(qs, 40).get_page(request.GET.get("page"))})


@require_perm("sales.create")
def refund_new(request):
    company = request.company
    initial = {"date": timezone.localdate(), "currency": company.base_currency, "method": "bank"}
    nid = request.GET.get("credit_note", "")
    note = CreditNote.objects.filter(company=company, pk=nid, status="posted").first() if nid.isdigit() else None
    if note:
        initial.update(credit_note=note, customer=note.customer, currency=note.currency, rate=note.rate, amount=note.available)
    cid = request.GET.get("customer", "")
    if not note and cid.isdigit():
        customer = Customer.objects.filter(company=company, pk=cid).first()
        if customer:
            initial.update(customer=customer, currency=customer.currency)
    form = RefundForm(request.POST or None, company=company, initial=initial,
                      instance=CustomerRefund(company=company, created_by=request.user))
    if request.method == "POST" and form.is_valid():
        refund = form.save(commit=False)
        refund.company, refund.created_by = company, request.user
        try:
            with transaction.atomic():
                services.post_refund(refund, request.user)
        except services.SalesError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, _("Refund %(n)s recorded.") % {"n": refund.number})
            return redirect("sales:refund", pk=refund.pk)
    customer = form.instance.customer if form.instance.customer_id else initial.get("customer")
    return render(request, "sales/refund_form.html", {
        "form": form, "available": services.available_credit(customer) if customer else None, "customer": customer})


@require_perm("sales.view")
def refund(request, pk):
    r = get_object_or_404(access.scope(CustomerRefund.objects.filter(company=request.company)), pk=pk)
    return render(request, "sales/refund_detail.html", {"r": r})


@require_perm("sales.view")
def refund_print(request, pk):
    from core.amount_words import amount_in_words
    r = get_object_or_404(access.scope(CustomerRefund.objects.filter(company=request.company)), pk=pk)
    return render(request, "sales/refund_print.html", {
        "r": r, "words_en": amount_in_words(r.amount, r.currency_id, "en"), "words_ar": amount_in_words(r.amount, r.currency_id, "ar")})


@require_POST
@require_perm("sales.void")
def refund_void(request, pk):
    r = get_object_or_404(access.scope(CustomerRefund.objects.filter(company=request.company)), pk=pk)
    try:
        services.void_refund(r, request.user)
        messages.success(request, _("Refund voided."))
    except services.SalesError as exc:
        messages.error(request, str(exc))
    return redirect("sales:refund", pk=pk)
