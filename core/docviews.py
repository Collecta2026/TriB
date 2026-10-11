"""Generic list / form / detail / print views for trade documents, configured per document type."""
import json
from dataclasses import dataclass, field

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from . import access

REGISTRY = {}  # (ns, key) -> DocSpec, for the shared More actions (copy, delete, share)


@dataclass
class DocSpec:
    key: str                      # e.g. "invoice"
    ns: str                       # url namespace, e.g. "sales"
    perm: str                     # permission module, e.g. "sales"
    model: type
    header_form: type
    formsets: tuple               # (existing, new) from forms_util.line_formsets
    title: object                 # lazy singular label
    plural: object
    print_en: str = ""
    print_ar: str = ""
    party: str = ""               # "customer" / "supplier"
    price_source: str = "sales"   # "sales" uses sales price & VAT, "purchase" uses cost & purchase VAT
    columns: list = field(default_factory=list)   # [(label, callable, kind)]
    statuses: list = field(default_factory=list)
    actions_template: str = ""
    related_template: str = ""
    editable_statuses: tuple = ("draft",)
    defaults: object = None       # callable(request) -> dict for a new document
    list_filter: object = None    # callable(request, qs) -> qs

    voidable: bool = False        # posted documents have a "void" action on <key>_action
    recurring_kind: str = ""      # "invoice" / "bill" when Make recurring applies
    shareable: bool = True        # Share link / WhatsApp for the customer or supplier

    def __post_init__(self):
        REGISTRY.setdefault((self.ns, self.key), self)  # copies made with dataclasses.replace keep the original

    def url(self, kind, pk=None):
        names = {"list": f"{self.ns}:{self.key}s", "new": f"{self.ns}:{self.key}_new", "detail": f"{self.ns}:{self.key}",
                 "edit": f"{self.ns}:{self.key}_edit", "print": f"{self.ns}:{self.key}_print"}
        return reverse(names[kind], args=[pk] if pk else [])

    @property
    def target(self):
        return self.model._meta.label_lower

    @property
    def url_new(self):
        return self.url("new")

    @property
    def url_list(self):
        return self.url("list")


def require(request, spec, action):
    if request.membership is None or not request.membership.has_perm(f"{spec.perm}.{action}"):
        raise PermissionDenied


def get_doc(request, spec, pk):
    """The document, if this user may see it (own records only, warehouses)."""
    return get_object_or_404(access.scope(spec.model.objects.filter(company=request.company)), pk=pk)


def picker_data(company, source, party=""):
    """Product and VAT data for the line-item autofill script, and the customer card for the header."""
    from inventory.models import Item
    from ledger.models import TaxRate

    items = {}
    for i in Item.objects.filter(company=company, is_active=True).select_related("sales_tax", "purchase_tax"):
        items[i.id] = {
            "sku": i.sku, "name": i.name, "desc": i.name, "barcode": i.barcode,
            "search": f"{i.sku} {i.barcode} {i.name_en} {i.name_ar}".lower(),
            "price": str(i.sales_price if source == "sales" else i.purchase_cost),
            "tax": (i.sales_tax_id if source == "sales" else i.purchase_tax_id) or "",
            "tracking": i.tracking, "stocked": i.is_stocked,
        }
    taxes = {t.id: str(t.rate) for t in TaxRate.objects.filter(company=company)}
    default_tax = TaxRate.objects.filter(company=company, is_default=True).values_list("id", flat=True).first()
    parties = {}
    if party == "customer":
        from contacts.models import Customer
        for c in access.scope(Customer.objects.filter(company=company, is_active=True)):
            parties[c.id] = {"email": c.email, "bill": "\n".join(x for x in (c.name, c.address, c.city) if x),
                             "ship": c.shipping_address, "days": c.payment_terms_days,
                             "edit": reverse("contacts:customer_edit", args=[c.id])}
    elif party == "supplier":
        from contacts.models import Supplier
        for s in Supplier.objects.filter(company=company, is_active=True):
            parties[s.id] = {"days": s.payment_terms_days, "edit": reverse("contacts:supplier_edit", args=[s.id])}
    return json.dumps({"items": items, "taxes": taxes, "defaultTax": default_tax or "", "parties": parties})


def clean_subtotals(raw):
    """Subtotal markers from the line grid: [{"pos": int, "label": str}], at most 50."""
    try:
        data = json.loads(raw or "[]")
    except ValueError:
        return []
    out = []
    for s in data if isinstance(data, list) else []:
        if isinstance(s, dict) and isinstance(s.get("pos"), int) and 0 < s["pos"] < 10000:
            out.append({"pos": s["pos"], "label": str(s.get("label") or "")[:60]})
    return out[:50]


DELIVERY = [("unsent", gettext_lazy("Not sent yet")), ("emailed", gettext_lazy("Emailed")),
            ("shared", gettext_lazy("Shared by link or WhatsApp"))]


def filter_delivery(company, qs, method):
    """Documents emailed with Review and send, shared by link, or neither."""
    from .models import AuditLog, ShareLink

    model = qs.model
    emailed = {int(i) for i in AuditLog.objects.filter(company=company, object_type=model._meta.label,
                                                       action__endswith=".sent").values_list("object_id", flat=True)
               if str(i).isdigit()}
    shared = set(ShareLink.objects.filter(company=company, target=model._meta.label_lower)
                 .values_list("target_id", flat=True))
    if method == "emailed":
        return qs.filter(pk__in=emailed)
    if method == "shared":
        return qs.filter(pk__in=shared)
    return qs.exclude(pk__in=emailed | shared)


def doc_list(request, spec, template="docs/list.html", extra=None):
    require(request, spec, "view")
    qs = access.scope(spec.model.objects.filter(company=request.company))
    party = spec.party
    if party:
        qs = qs.select_related(party, "currency")
    status = request.GET.get("status", "")
    if status:
        qs = qs.filter(status=status)
    q = request.GET.get("q", "").strip()
    if q:
        cond = Q(number__icontains=q) | Q(reference__icontains=q)
        if party:
            cond |= Q(**{f"{party}__name_en__icontains": q}) | Q(**{f"{party}__name_ar__icontains": q})
        qs = qs.filter(cond)
    if spec.list_filter:
        qs = spec.list_filter(request, qs)
    from ledger.models import Project

    from .filters import DATES, Chip
    from .filters import apply as drill_filter
    qs, drill = drill_filter(request, qs, party)
    if status:
        drill.insert(0, Chip(str(dict(spec.statuses).get(status, status)), "status"))
    delivery_methods = DELIVERY if spec.shareable and party == "customer" else []
    delivery = request.GET.get("delivery", "")
    if delivery in dict(delivery_methods):
        qs = filter_delivery(request.company, qs, delivery)
        drill.append(Chip(str(dict(delivery_methods)[delivery]), "delivery"))
    page = Paginator(qs.prefetch_related("lines__tax_rate"), 40).get_page(request.GET.get("page"))
    rows = [{"obj": o, "url": spec.url("detail", o.pk), "cells": [(fn(o), kind) for _label, fn, kind in spec.columns]}
            for o in page]
    party_model = spec.model._meta.get_field(party).related_model if party else None
    ctx = {"spec": spec, "page": page, "rows": rows, "status": status, "q": q, "drill": drill,
           "filter_statuses": spec.statuses, "filter_dates": DATES, "list_key": f"{spec.ns}-{spec.key}",
           "filter_party": list(access.scope(party_model.objects.filter(company=request.company, is_active=True))
                                .values_list("pk", "name_en")) if party_model else [],
           "filter_party_label": party_model._meta.verbose_name.capitalize() if party_model else "",
           "projects": Project.objects.filter(company=request.company), "delivery_methods": delivery_methods,
           "can_create": request.membership.has_perm(f"{spec.perm}.create")}
    ctx.update(extra or {})
    return render(request, template, ctx)


@transaction.atomic
def doc_form(request, spec, doc=None, after_save=None, post_label=None):
    """Create or edit a document with its lines. `after_save(request, doc)` may post it and return a redirect."""
    company = request.company
    if doc is None:
        require(request, spec, "create")
        names = {f.name for f in spec.model._meta.get_fields()}
        defaults = {k: v for k, v in (spec.defaults(request) if spec.defaults else {}).items() if k in names}
        doc = spec.model(company=company, created_by=request.user, **{"currency": company.base_currency, **defaults})
    else:
        require(request, spec, "edit")
        if doc.status not in spec.editable_statuses:
            messages.error(request, _("This document can no longer be changed."))
            return redirect(spec.url("detail", doc.pk))
    form = spec.header_form(request.POST or None, instance=doc, company=company)
    formset_class = spec.formsets[0] if doc.pk else spec.formsets[1]
    formset = formset_class(request.POST or None, instance=doc, company=company, prefix="lines")
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        doc = form.save(commit=False)
        doc.company = company
        if hasattr(doc, "subtotals") and "subtotals" in request.POST:
            doc.subtotals = clean_subtotals(request.POST.get("subtotals"))
        if not doc.pk:
            doc.created_by = request.user
        if doc.currency_id == company.base_currency_id:
            doc.rate = 1
        doc.save()
        formset.instance = doc
        formset.save()
        from .doc_actions import saved_redirect

        if after_save and "post" in request.POST:
            response = after_save(request, doc)
            if response is not None:
                then = request.POST.get("then", "")
                if then in ("share", "whatsapp", "send") and doc.number:
                    return redirect(f"{spec.url('detail', doc.pk)}?{then}=1")
                return response
        messages.success(request, _("Saved."))
        return saved_redirect(request, spec.url("detail", doc.pk), spec.url_new, spec.url_list)
    from .doc_actions import bar_for

    can_post = request.membership.has_perm(f"{spec.perm}.post") and after_save is not None
    return render(request, "docs/form.html", {
        "spec": spec, "doc": doc, "form": form, "formset": formset,
        "picker": picker_data(company, spec.price_source, spec.party),
        "can_post": can_post, "post_label": post_label, "subtotals_json": json.dumps(getattr(doc, "subtotals", None) or []),
        "bar": {**bar_for(request, spec, doc, "form"), "primary": post_label if can_post else "", "primary_name": "post"},
    })


def doc_detail(request, spec, doc, extra=None):
    from .doc_actions import bar_for

    require(request, spec, "view")
    editable = doc.status in spec.editable_statuses and request.membership.has_perm(f"{spec.perm}.edit")
    ctx = {"spec": spec, "doc": doc, "lines": doc.lines.select_related("item", "tax_rate", "project", "account"),
           "editable": editable, "bar": {**bar_for(request, spec, doc, "detail"),
                                         "edit": spec.url("edit", doc.pk) if editable else ""}}
    ctx.update(extra or {})
    return render(request, "docs/detail.html", ctx)


def doc_print(request, spec, doc, extra=None):
    """Print / PDF. ?delivery=1 prints a delivery note (no prices); ?embed=1 is the bare page for previews."""
    from .doc_actions import print_context

    require(request, spec, "view")
    ctx = print_context(spec, doc, delivery=request.GET.get("delivery") == "1" and spec.party == "customer",
                        company=request.company)
    ctx.update(extra or {})
    embed = request.GET.get("embed") == "1"
    response = render(request, "docs/shared.html" if embed else "docs/print.html", {**ctx, "embed": embed})
    if embed:
        response["X-Frame-Options"] = "SAMEORIGIN"  # shown inside Review and send
    return response


def action_redirect(request, spec, doc, fn, success, *args):
    """Run a service call, turning its domain error into a message."""
    try:
        result = fn(*args)
    except Exception as exc:  # services raise their own *Error classes
        if exc.__class__.__name__.endswith("Error"):
            messages.error(request, str(exc))
            return redirect(spec.url("detail", doc.pk))
        raise
    messages.success(request, success)
    return result
