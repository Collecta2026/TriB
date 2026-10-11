from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
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
    from django.db.models import Q

    from core.attachments import for_object
    from core.docviews import REGISTRY
    from core.models import Attachment, AuditLog, RecurringTemplate

    from . import hub

    cfg = KINDS[kind]
    obj = get_object_or_404(cfg["model"], pk=pk, company=request.company)
    can = request.membership.has_perm
    all_rows = hub.customer_rows(obj, can) if kind == "customer" else hub.supplier_rows(obj, can)
    rows, filters = hub.filtered(all_rows, request)
    overdue = sum((r.get("doc_due", 0) for r in all_rows if r["status"] == "overdue"), 0)
    ids = hub.related_ids(all_rows)
    # Documents & files: the contact's own files and everything attached to its documents.
    files_q = Q(target=obj._meta.label_lower, target_id=obj.pk)
    for (ns, key), pks in ids.items():
        spec = REGISTRY.get((ns, key))
        if spec:
            files_q |= Q(target=spec.model._meta.label_lower, target_id__in=pks)
    files = Attachment.objects.filter(files_q, company=request.company).defer("data").order_by("-uploaded_at")[:100]
    activity_q = Q(object_type=obj._meta.label, object_id=str(obj.pk))
    for (ns, key), pks in ids.items():
        spec = REGISTRY.get((ns, key))
        if spec:
            activity_q |= Q(object_type=spec.model._meta.label, object_id__in=[str(x) for x in pks])
    activity = AuditLog.objects.filter(activity_q, company=request.company).select_related("user")[:60] \
        if can("audit.view") else []
    recurring_kind = "invoice" if kind == "customer" else "bill"
    recurring_ids = ids.get(("sales", "invoice") if kind == "customer" else ("purchases", "bill"), [])
    recurring = RecurringTemplate.objects.filter(company=request.company, kind=recurring_kind, source_id__in=recurring_ids)
    projects = obj.projects.all() if kind == "customer" else []
    return render(request, "contacts/detail.html", {
        "kind": kind, "cfg": cfg, "obj": obj, "rows": rows, "filters": filters, "total_rows": len(all_rows),
        "types": hub.TYPES[kind], "statuses": hub.STATUSES, "periods": hub.PERIODS,
        "balance": hub.summary(kind, obj, [])["balance"], "overdue": overdue,
        "files": files, "activity": activity, "recurring": recurring, "projects": projects,
        "tab": request.GET.get("tab", "transactions"), "contact_files": for_object(obj),
    })


@require_perm("contacts.edit")
def contact_notes(request, kind, pk):
    from django.views.decorators.http import require_POST  # noqa: F401 (POST only, checked below)

    cfg = KINDS[kind]
    obj = get_object_or_404(cfg["model"], pk=pk, company=request.company)
    if request.method == "POST":
        obj.notes = request.POST.get("notes", "")[:5000]
        obj.save(update_fields=["notes"])
        AuditLog.record(request.company, request.user, f"{kind}.notes", obj, obj.name_en, ip=client_ip(request))
        messages.success(request, _("Notes saved."))
    return redirect(f"{reverse(f'contacts:{kind}', args=[obj.pk])}?tab=notes")


customers = require_perm("contacts.view")(lambda r: contact_list(r, "customer"))
customer_new = require_perm("contacts.create")(lambda r: contact_form(r, "customer"))
customer_edit = require_perm("contacts.edit")(lambda r, pk: contact_form(r, "customer", pk))
customer = require_perm("contacts.view")(lambda r, pk: contact_detail(r, "customer", pk))
suppliers = require_perm("contacts.view")(lambda r: contact_list(r, "supplier"))
supplier_new = require_perm("contacts.create")(lambda r: contact_form(r, "supplier"))
supplier_edit = require_perm("contacts.edit")(lambda r, pk: contact_form(r, "supplier", pk))
supplier = require_perm("contacts.view")(lambda r, pk: contact_detail(r, "supplier", pk))
customer_notes = lambda r, pk: contact_notes(r, "customer", pk)  # noqa: E731
supplier_notes = lambda r, pk: contact_notes(r, "supplier", pk)  # noqa: E731
