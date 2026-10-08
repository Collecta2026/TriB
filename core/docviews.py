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
    return get_object_or_404(spec.model, pk=pk, company=request.company)


def picker_data(company, source):
    """Product and VAT data for the line-item autofill script."""
    from inventory.models import Item
    from ledger.models import TaxRate

    items = {}
    for i in Item.objects.filter(company=company, is_active=True).select_related("sales_tax", "purchase_tax"):
        items[i.id] = {
            "sku": i.sku, "name": i.name, "desc": i.name,
            "price": str(i.sales_price if source == "sales" else i.purchase_cost),
            "tax": (i.sales_tax_id if source == "sales" else i.purchase_tax_id) or "",
            "tracking": i.tracking, "stocked": i.is_stocked,
        }
    taxes = {t.id: str(t.rate) for t in TaxRate.objects.filter(company=company)}
    default_tax = TaxRate.objects.filter(company=company, is_default=True).values_list("id", flat=True).first()
    return json.dumps({"items": items, "taxes": taxes, "defaultTax": default_tax or ""})


def doc_list(request, spec, template="docs/list.html", extra=None):
    require(request, spec, "view")
    qs = spec.model.objects.filter(company=request.company)
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
    page = Paginator(qs.prefetch_related("lines__tax_rate"), 40).get_page(request.GET.get("page"))
    rows = [{"obj": o, "url": spec.url("detail", o.pk), "cells": [(fn(o), kind) for _label, fn, kind in spec.columns]}
            for o in page]
    ctx = {"spec": spec, "page": page, "rows": rows, "status": status, "q": q,
           "can_create": request.membership.has_perm(f"{spec.perm}.create")}
    ctx.update(extra or {})
    return render(request, template, ctx)


@transaction.atomic
def doc_form(request, spec, doc=None, after_save=None, post_label=None):
    """Create or edit a document with its lines. `after_save(request, doc)` may post it and return a redirect."""
    company = request.company
    if doc is None:
        require(request, spec, "create")
        doc = spec.model(company=company, created_by=request.user, currency=company.base_currency,
                         **(spec.defaults(request) if spec.defaults else {}))
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
        if not doc.pk:
            doc.created_by = request.user
        if doc.currency_id == company.base_currency_id:
            doc.rate = 1
        doc.save()
        formset.instance = doc
        formset.save()
        if after_save and "post" in request.POST:
            response = after_save(request, doc)
            if response is not None:
                return response
        messages.success(request, _("Saved."))
        return redirect(spec.url("detail", doc.pk))
    return render(request, "docs/form.html", {
        "spec": spec, "doc": doc, "form": form, "formset": formset,
        "picker": picker_data(company, spec.price_source),
        "can_post": request.membership.has_perm(f"{spec.perm}.post") and after_save is not None,
        "post_label": post_label,
    })


def doc_detail(request, spec, doc, extra=None):
    require(request, spec, "view")
    ctx = {"spec": spec, "doc": doc, "lines": doc.lines.select_related("item", "tax_rate", "project", "account"),
           "editable": doc.status in spec.editable_statuses and request.membership.has_perm(f"{spec.perm}.edit")}
    ctx.update(extra or {})
    return render(request, "docs/detail.html", ctx)


def doc_print(request, spec, doc, extra=None):
    require(request, spec, "view")
    ctx = {"spec": spec, "doc": doc, "lines": doc.lines.select_related("item", "tax_rate"),
           "party": getattr(doc, spec.party, None) if spec.party else None,
           "words_en": doc.words("en"), "words_ar": doc.words("ar")}
    ctx.update(extra or {})
    return render(request, "docs/print.html", ctx)


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
