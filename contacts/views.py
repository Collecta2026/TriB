from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from core.models import AuditLog, NumberSeries, client_ip
from users.permissions import require_perm

from .forms import CustomerForm, SupplierForm
from .models import Customer, Supplier

KINDS = {
    "customer": {"model": Customer, "form": CustomerForm, "prefix": "CUS", "title": gettext_lazy("Customer"),
                 "plural": gettext_lazy("Customers")},
    "supplier": {"model": Supplier, "form": SupplierForm, "prefix": "SUP", "title": gettext_lazy("Supplier"),
                 "plural": gettext_lazy("Suppliers")},
}


def _balances(kind, contacts):
    if kind == "customer":
        from sales.services import customer_balance as balance
    else:
        from purchases.services import supplier_balance as balance
    return {c.id: balance(c) for c in contacts}


def contact_list(request, kind):
    cfg = KINDS[kind]
    qs = cfg["model"].objects.filter(company=request.company).select_related("currency")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(name_en__icontains=q) | Q(name_ar__icontains=q) | Q(code__icontains=q) | Q(phone__icontains=q))
    if request.GET.get("inactive") != "1":
        qs = qs.filter(is_active=True)
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    balances = _balances(kind, page)
    rows = [{"c": c, "balance": balances[c.id]} for c in page]
    return render(request, "contacts/list.html", {"kind": kind, "cfg": cfg, "rows": rows, "page": page, "q": q})


def contact_form(request, kind, pk=None):
    cfg = KINDS[kind]
    obj = get_object_or_404(cfg["model"], pk=pk, company=request.company) if pk else \
        cfg["model"](company=request.company, currency=request.company.base_currency)
    form = cfg["form"](request.POST or None, instance=obj, company=request.company)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.company = request.company
        if not obj.code:
            obj.code = NumberSeries.next_plain(request.company, cfg["prefix"])
        obj.save()
        AuditLog.record(request.company, request.user, f"{kind}.saved", obj, obj.name_en, ip=client_ip(request))
        messages.success(request, _("Saved."))
        return redirect(f"contacts:{kind}", pk=obj.pk)
    return render(request, "contacts/form.html", {"kind": kind, "cfg": cfg, "form": form, "obj": obj})


def contact_detail(request, kind, pk):
    cfg = KINDS[kind]
    obj = get_object_or_404(cfg["model"], pk=pk, company=request.company)
    ctx = {"kind": kind, "cfg": cfg, "obj": obj}
    if kind == "customer":
        from sales.models import CustomerPayment, Invoice, Quotation, SalesOrder
        from sales.services import customer_balance
        ctx.update(balance=customer_balance(obj),
                   open_docs=[i for i in Invoice.objects.filter(customer=obj, status="posted") if i.balance_due > 0],
                   invoices=Invoice.objects.filter(customer=obj).order_by("-date")[:10],
                   orders=SalesOrder.objects.filter(customer=obj).order_by("-date")[:10],
                   quotes=Quotation.objects.filter(customer=obj).order_by("-date")[:5],
                   payments=CustomerPayment.objects.filter(customer=obj).order_by("-date")[:10])
    else:
        from purchases.models import Bill, PurchaseOrder, SupplierPayment
        from purchases.services import supplier_balance
        ctx.update(balance=supplier_balance(obj),
                   open_docs=[b for b in Bill.objects.filter(supplier=obj, status="posted") if b.balance_due > 0],
                   bills=Bill.objects.filter(supplier=obj).order_by("-date")[:10],
                   orders=PurchaseOrder.objects.filter(supplier=obj).order_by("-date")[:10],
                   payments=SupplierPayment.objects.filter(supplier=obj).order_by("-date")[:10])
    return render(request, "contacts/detail.html", ctx)


customers = require_perm("contacts.view")(lambda r: contact_list(r, "customer"))
customer_new = require_perm("contacts.create")(lambda r: contact_form(r, "customer"))
customer_edit = require_perm("contacts.edit")(lambda r, pk: contact_form(r, "customer", pk))
customer = require_perm("contacts.view")(lambda r, pk: contact_detail(r, "customer", pk))
suppliers = require_perm("contacts.view")(lambda r: contact_list(r, "supplier"))
supplier_new = require_perm("contacts.create")(lambda r: contact_form(r, "supplier"))
supplier_edit = require_perm("contacts.edit")(lambda r, pk: contact_form(r, "supplier", pk))
supplier = require_perm("contacts.view")(lambda r, pk: contact_detail(r, "supplier", pk))
