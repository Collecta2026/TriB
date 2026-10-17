"""Products & services, laid out like QuickBooks: the "needs your attention" banner, search / type / stock status /
filters, sortable columns with pictures and OUT / LOW badges, edit mode for prices, row actions (Edit, Run report,
Duplicate, Make inactive, Adjust quantity, Print label), batch actions, More ▾ (categories, price rules, reports,
starting value, labels, import) and New ▾ (stock item, non-stock item, service)."""
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import DecimalField, Exists, F, OuterRef, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from core import access
from core.models import AuditLog, client_ip
from users.permissions import require_perm

from . import services
from .forms import PriceRuleForm, StartingValueForm
from .models import Category, Item, PriceRule, StockAdjustment, StockAdjustmentLine, StockMove, Warehouse

ZERO = Decimal("0")
STATUSES = [("", gettext_lazy("Any")), ("in", gettext_lazy("In stock")), ("low", gettext_lazy("Low stock")),
            ("out", gettext_lazy("Out of stock")), ("nocost", gettext_lazy("No initial cost"))]
ACTIVE = [("active", gettext_lazy("Active")), ("inactive", gettext_lazy("Inactive")), ("all", gettext_lazy("All"))]
SORTS = {"name": "name_en", "sku": "sku", "type": "type", "category": "category__name_en", "price": "sales_price",
         "cost": "purchase_cost", "qty": "on_hand", "desc": "description"}


def stock_on(company):
    """Stock columns and actions: always in TriB; in TriB International only with the Inventory module."""
    try:
        from core.modules import enabled
    except ImportError:
        return True
    return enabled(company, "inventory")


def _safe_next(request, fallback):
    nxt = request.POST.get("next") or request.GET.get("next") or ""
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return nxt
    return fallback


def annotated(request):
    """Products with stock on hand (in the warehouses this user may see) and whether they have any stock history."""
    ids = access.warehouse_ids(request.membership)
    in_mine = Q(layers__warehouse_id__in=ids) if ids is not None else Q()
    return (Item.objects.filter(company=request.company).defer("image").select_related("category")
            .annotate(on_hand=Coalesce(Sum("layers__qty_remaining", filter=in_mine), Value(ZERO),
                                       output_field=DecimalField(max_digits=19, decimal_places=3)),
                      has_history=Exists(StockMove.objects.filter(item=OuterRef("pk")))))


def _status_q(status):
    stock = Q(type="inventory")
    return {"in": stock & Q(on_hand__gt=0),
            "low": stock & Q(reorder_level__gt=0, on_hand__gt=0, on_hand__lte=F("reorder_level")),
            "out": stock & Q(on_hand__lte=0),
            "nocost": stock & Q(purchase_cost=0, has_history=False)}.get(status)


def attention(request):
    """The banner: stock items without an initial cost, out of stock, and at or below their reorder level."""
    qs = annotated(request).filter(is_active=True, type="inventory")
    return {"nocost": qs.filter(_status_q("nocost")).count(), "out": qs.filter(_status_q("out")).count(),
            "low": qs.filter(_status_q("low")).count()}


@require_perm("inventory.view")
def items(request):
    company = request.company
    g = request.GET
    stock = stock_on(company)
    qs = annotated(request)
    q = g.get("q", "").strip()
    if q:
        qs = qs.filter(Q(sku__icontains=q) | Q(name_en__icontains=q) | Q(name_ar__icontains=q) | Q(barcode=q)
                       | Q(description__icontains=q))
    kind = g.get("type", "")
    if kind in dict(Item.TYPES):
        qs = qs.filter(type=kind)
    status = g.get("status", "") if stock else ""
    if _status_q(status) is not None:
        qs = qs.filter(_status_q(status))
    cat = g.get("category", "")
    if cat == "none":
        qs = qs.filter(category__isnull=True)
    elif cat.isdigit():
        qs = qs.filter(category_id=cat)
    tracking = g.get("tracking", "")
    if tracking in dict(Item.TRACKING):
        qs = qs.filter(tracking=tracking)
    active = g.get("active") or ("all" if g.get("inactive") == "1" else "active")
    if active == "active":
        qs = qs.filter(is_active=True)
    elif active == "inactive":
        qs = qs.filter(is_active=False)
    sort = g.get("sort", "name")
    key = SORTS.get(sort.lstrip("-"), "name_en")
    qs = qs.order_by(f"-{key}" if sort.startswith("-") else key, "sku")
    page = Paginator(qs, 50).get_page(g.get("page"))
    edit = g.get("edit") == "1" and request.membership.has_perm("inventory.edit")
    keep = {k: v for k, v in g.items() if k not in ("page", "sort", "edit") and v}
    cols = {k: {"url": "?" + urlencode({**keep, "sort": f"-{k}" if sort == k else k}),
                "arrow": "↑" if sort == k else "↓" if sort == f"-{k}" else ""} for k in SORTS}
    filters_on = sum(1 for k in ("category", "tracking") if g.get(k)) + (1 if active != "active" else 0)
    return render(request, "inventory/items.html", {
        "rows": page, "page": page, "q": q, "types": Item.TYPES, "statuses": STATUSES, "status": status,
        "trackings": Item.TRACKING, "actives": ACTIVE, "active": active, "sort": sort, "edit": edit,
        "categories": Category.objects.filter(company=company), "attention": attention(request) if stock else None,
        "stock": stock, "keep": urlencode({**keep, "sort": sort}), "cols": cols, "filters_on": filters_on, "now": timezone.now(),
        "list_key": "inventory-items", "sees_costs": access.sees_costs(request.membership),
        "here": request.get_full_path()})


@require_perm("inventory.view")
def item_image(request, pk):
    item = get_object_or_404(Item, pk=pk, company=request.company)
    if not item.image_type or item.image is None:
        return HttpResponse(status=404)
    response = HttpResponse(bytes(item.image), content_type=item.image_type)
    response["Cache-Control"] = "private, max-age=300"
    return response


@require_POST
@require_perm("inventory.view")
@transaction.atomic
def item_action(request, pk):
    """Row ▾: Duplicate, Make inactive, Make active."""
    item = get_object_or_404(Item, pk=pk, company=request.company)
    action = request.POST.get("action")
    back = _safe_next(request, reverse("inventory:items"))
    can = request.membership.has_perm
    if action == "duplicate" and can("inventory.create"):
        copy = Item.objects.get(pk=item.pk)
        copy.pk = None
        copy.sku = services.next_sku(request.company, item.category)
        copy.name_en = f"{item.name_en} (copy)"[:200]
        copy.name_ar = f"{item.name_ar} (نسخة)"[:200] if item.name_ar else ""
        copy.barcode = ""
        copy.is_active = True
        copy.save()
        AuditLog.record(request.company, request.user, "item.duplicated", copy, f"{copy.sku} from {item.sku}",
                        ip=client_ip(request))
        messages.success(request, _("Copied to %(sku)s. Check it and save.") % {"sku": copy.sku})
        return redirect("inventory:item_edit", pk=copy.pk)
    if action in ("inactive", "active") and can("inventory.edit"):
        item.is_active = action == "active"
        item.save(update_fields=["is_active"])
        AuditLog.record(request.company, request.user, f"item.{action}", item, item.sku, ip=client_ip(request))
        messages.success(request, (_("%(sku)s is active again.") if item.is_active else
                                   _("%(sku)s is inactive. It no longer appears on new transactions.")) % {"sku": item.sku})
    return redirect(back)


@require_POST
@require_perm("inventory.view")
def items_batch(request):
    """Batch actions on the ticked rows."""
    company, can = request.company, request.membership.has_perm
    ids = [i for i in request.POST.getlist("ids") if i.isdigit()][:200]
    chosen = Item.objects.filter(company=company, pk__in=ids)
    back = _safe_next(request, reverse("inventory:items"))
    action = request.POST.get("action")
    if not ids:
        messages.error(request, _("Tick one or more products first."))
        return redirect(back)
    if action in ("inactive", "active") and can("inventory.edit"):
        n = chosen.update(is_active=action == "active")
        AuditLog.record(company, request.user, f"items.{action}", None, f"{n} products", ip=client_ip(request))
        messages.success(request, _("%(n)s products updated.") % {"n": n})
    elif action == "category" and can("inventory.edit"):
        raw = request.POST.get("category", "")
        cat = Category.objects.filter(company=company, pk=raw).first() if raw.isdigit() else None
        if raw and cat is None:
            messages.error(request, _("Choose a category."))
            return redirect(back)
        n = chosen.update(category=cat)
        AuditLog.record(company, request.user, "items.category", None, f"{n} products → {cat or '-'}", ip=client_ip(request))
        messages.success(request, _("%(n)s products updated.") % {"n": n})
    elif action == "adjust" and can("inventory.create"):
        stocked = [str(i.pk) for i in chosen.filter(type="inventory")]
        if not stocked:
            messages.error(request, _("Only stock items have a quantity to adjust."))
            return redirect(back)
        return redirect(f"{reverse('inventory:adjustment_new')}?items={','.join(stocked)}")
    elif action == "labels":
        return redirect(f"{reverse('inventory:labels')}?{urlencode([('item', i) for i in ids] + [('copies', 1)])}")
    else:
        messages.error(request, _("You do not have permission to do that."))
    return redirect(back)


def _dec(raw):
    raw = (raw or "").replace(",", "").strip()
    if raw == "":
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise ValueError(raw)
    if value < 0:
        raise ValueError(raw)
    return value


@require_POST
@require_perm("inventory.edit")
@transaction.atomic
def items_bulk_save(request):
    """Edit mode (pencil): price, cost, reorder level and category typed straight into the list."""
    company = request.company
    back = _safe_next(request, reverse("inventory:items"))
    costs = access.sees_costs(request.membership)
    cats = {str(c.pk): c for c in Category.objects.filter(company=company)}
    changed, bad = 0, []
    for item in Item.objects.filter(company=company, pk__in=[i for i in request.POST.getlist("ids") if i.isdigit()]):
        fields = []
        try:
            for name, attr in (("price", "sales_price"), ("cost", "purchase_cost"), ("reorder", "reorder_level")):
                if name == "cost" and not costs:
                    continue
                key = f"{name}_{item.pk}"
                if key in request.POST:
                    value = _dec(request.POST[key])
                    if value is not None and value != getattr(item, attr):
                        setattr(item, attr, value)
                        fields.append(attr)
        except ValueError:
            bad.append(item.sku)
            continue
        key = f"category_{item.pk}"
        if key in request.POST:
            cat = cats.get(request.POST[key])
            if (cat.pk if cat else None) != item.category_id:
                item.category = cat
                fields.append("category")
        if fields:
            item.save(update_fields=fields)
            changed += 1
    if changed:
        AuditLog.record(company, request.user, "items.bulk_edit", None, f"{changed} products", ip=client_ip(request))
    messages.success(request, _("%(n)s products updated.") % {"n": changed})
    if bad:
        messages.error(request, _("Not saved (check the numbers): %(skus)s") % {"skus": ", ".join(bad)})
    return redirect(back)


# ---------- QuickReport for one product ----------
@require_perm("inventory.view")
def item_report(request, pk):
    from datetime import date as date_cls, timedelta

    from purchases.models import BillLine, SupplierCreditLine
    from sales.models import CreditNoteLine, InvoiceLine

    item = get_object_or_404(Item.objects.defer("image"), pk=pk, company=request.company)
    today = timezone.localdate()

    def day(name, default):
        try:
            return date_cls.fromisoformat(request.GET.get(name, ""))
        except ValueError:
            return default
    date_from, date_to = day("from", today - timedelta(days=365)), day("to", today)
    can = request.membership.has_perm
    rows = []
    period = {"document__date__gte": date_from, "document__date__lte": date_to, "document__status": "posted",
              "item": item}
    if can("sales.view"):
        for line in access.scope(InvoiceLine.objects.filter(**period).select_related("document__customer")):
            d = line.document
            rows.append({"date": d.date, "type": _("Invoice"), "number": d.number, "party": d.customer.name,
                         "qty": line.qty, "rate": line.unit_price, "amount": line.net * d.rate, "side": "sales",
                         "url": reverse("sales:invoice", args=[d.pk])})
        for line in CreditNoteLine.objects.filter(**period).select_related("document__customer"):
            d = line.document
            rows.append({"date": d.date, "type": _("Credit note"), "number": d.number, "party": d.customer.name,
                         "qty": -line.qty, "rate": line.unit_price, "amount": -line.net * d.rate, "side": "sales",
                         "url": reverse("sales:credit", args=[d.pk])})
    if can("purchases.view") and access.sees_costs(request.membership):
        for line in BillLine.objects.filter(**period).select_related("document__supplier"):
            d = line.document
            rows.append({"date": d.date, "type": _("Bill"), "number": d.number, "party": d.supplier.name,
                         "qty": line.qty, "rate": line.unit_price, "amount": line.net * d.rate, "side": "purchases",
                         "url": reverse("purchases:bill", args=[d.pk])})
        for line in SupplierCreditLine.objects.filter(**period).select_related("document__supplier"):
            d = line.document
            rows.append({"date": d.date, "type": _("Supplier credit"), "number": d.number, "party": d.supplier.name,
                         "qty": -line.qty, "rate": line.unit_price, "amount": -line.net * d.rate, "side": "purchases",
                         "url": reverse("purchases:supplier_credit", args=[d.pk])})
    moves = []
    if item.is_stocked and stock_on(request.company):
        moves = list(access.scope(item.moves.filter(date__gte=date_from, date__lte=date_to,
                                                    kind__in=("transfer_in", "transfer_out", "adjust_in", "adjust_out",
                                                              "opening"))).select_related("warehouse").order_by("date", "id"))
    rows.sort(key=lambda r: (r["date"], r["number"] or ""))
    sold = [r for r in rows if r["side"] == "sales"]
    bought = [r for r in rows if r["side"] == "purchases"]
    return render(request, "inventory/item_report.html", {
        "item": item, "rows": rows, "moves": moves, "date_from": date_from, "date_to": date_to,
        "qty_sold": sum((r["qty"] for r in sold), ZERO), "sales": sum((r["amount"] for r in sold), ZERO),
        "qty_bought": sum((r["qty"] for r in bought), ZERO), "purchases": sum((r["amount"] for r in bought), ZERO)})


# ---------- Price rules ----------
@require_perm("inventory.view")
def price_rules(request):
    from . import pricing

    company = request.company
    obj = None
    pk = request.GET.get("edit") or request.POST.get("pk")
    if pk and str(pk).isdigit():
        obj = get_object_or_404(PriceRule, pk=pk, company=company)
    form = None
    can_edit = request.membership.has_perm("inventory.edit")
    if can_edit and (obj is not None or request.GET.get("new") == "1" or request.method == "POST"):
        if request.method == "POST" and request.POST.get("delete") == "1" and obj is not None:
            AuditLog.record(company, request.user, "price_rule.deleted", None, obj.name, ip=client_ip(request))
            obj.delete()
            messages.success(request, _("Price rule deleted."))
            return redirect("inventory:price_rules")
        form = PriceRuleForm(request.POST or None, instance=obj or PriceRule(company=company), company=company)
        if request.method == "POST" and form.is_valid():
            rule = form.save(commit=False)
            rule.company = company
            rule.save()
            form.save_m2m()
            AuditLog.record(company, request.user, "price_rule.saved", rule, rule.name, ip=client_ip(request))
            messages.success(request, _("Price rule saved."))
            return redirect("inventory:price_rules")
    rules = PriceRule.objects.filter(company=company).prefetch_related("customers", "categories", "items")
    sample = []
    data = pricing.rule_data(company)
    for r in rules:
        item = r.items.first() or Item.objects.filter(company=company, category__in=r.categories.all()).first() \
            or Item.objects.filter(company=company, is_active=True, sales_price__gt=0).first()
        if item is not None:
            rd = next((d for d in data if d["id"] == r.pk), None)
            sample.append((r.pk, item, pricing.adjust(item.sales_price, rd) if rd else None))
    examples = {pk: (item, price) for pk, item, price in sample}
    return render(request, "inventory/price_rules.html", {
        "rules": [{"r": r, "example": examples.get(r.pk)} for r in rules], "form": form, "obj": obj,
        "can_edit": can_edit, "today": timezone.localdate()})


# ---------- Starting value ----------
@require_perm("inventory.create")
@transaction.atomic
def starting_value(request):
    """Opening stock for a product with no history (QuickBooks' Starting value): posted as an opening adjustment."""
    company = request.company
    warehouses = access.scope(Warehouse.objects.filter(company=company, is_active=True))
    initial = {"as_of": timezone.localdate(), "warehouse": warehouses.first()}
    raw = request.GET.get("item", "")
    item = Item.objects.filter(company=company, pk=raw).first() if raw.isdigit() else None
    if item is not None:
        initial.update(item=item, unit_cost=item.purchase_cost)
    form = StartingValueForm(request.POST or None, company=company, warehouses=warehouses, initial=initial)
    if request.method == "POST" and form.is_valid():
        if not request.membership.has_perm("inventory.post"):
            messages.error(request, _("You do not have permission to do that."))
            return redirect(request.get_full_path())
        d = form.cleaned_data
        item = d["item"]
        adj = StockAdjustment.objects.create(company=company, warehouse=d["warehouse"], date=d["as_of"], reason="opening",
                                             created_by=request.user, notes=_("Starting value"))
        StockAdjustmentLine.objects.create(adjustment=adj, item=item, qty_change=d["qty"], unit_cost=d["unit_cost"],
                                           serials=d.get("serials") or "", batch_no=d.get("batch_no") or "",
                                           expiry_date=d.get("expiry_date"))
        try:
            services.post_adjustment(adj, request.user)
        except services.StockError as exc:
            transaction.set_rollback(True)
            messages.error(request, str(exc))
            return render(request, "inventory/starting_value.html", {"form": form, "missing": _missing(request),
                                                                     "tracking": _tracking_map(form)})
        if not item.purchase_cost:
            item.purchase_cost = d["unit_cost"]
            item.save(update_fields=["purchase_cost"])
        messages.success(request, _("Starting value saved for %(sku)s (%(n)s).") % {"sku": item.sku, "n": adj.number})
        return redirect(_safe_next(request, reverse("inventory:item", args=[item.pk])))
    return render(request, "inventory/starting_value.html", {"form": form, "missing": _missing(request),
                                                             "tracking": _tracking_map(form)})


def _tracking_map(form):
    import json
    return json.dumps({str(i.pk): i.tracking for i in form.fields["item"].queryset})


def _missing(request):
    return annotated(request).filter(is_active=True).filter(_status_q("nocost")).order_by("name_en")[:50]


# ---------- Import from Excel ----------
@require_perm("inventory.create")
def import_items(request):
    from . import import_items as imp

    if request.GET.get("template") == "1":
        response = HttpResponse(imp.template_workbook(),
                                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = 'attachment; filename="trib-products-template.xlsx"'
        return response
    preview = request.session.get("items.import")
    if request.method == "POST" and "confirm" in request.POST and preview:
        created, updated = imp.save(request.company, preview["rows"])
        request.session.pop("items.import", None)
        AuditLog.record(request.company, request.user, "items.imported", None, f"{created} new, {updated} updated",
                        ip=client_ip(request))
        messages.success(request, _("%(c)s products added and %(u)s updated.") % {"c": created, "u": updated})
        return redirect("inventory:items")
    if request.method == "POST" and request.FILES.get("file"):
        upload = request.FILES["file"]
        if upload.size > 5 * 1024 * 1024 or not upload.name.lower().endswith((".xlsx", ".csv")):
            messages.error(request, _("Upload an Excel (.xlsx) or CSV file up to 5 MB."))
            return redirect("inventory:import_items")
        try:
            rows, problems = imp.parse(request.company, upload)
        except Exception as exc:  # unreadable files come back as a message
            rows, problems = [], [_("The file could not be read: %(e)s") % {"e": exc}]
        request.session["items.import"] = {"rows": rows, "problems": problems}
        return redirect("inventory:import_items")
    if request.GET.get("reset") == "1":
        request.session.pop("items.import", None)
        return redirect("inventory:import_items")
    return render(request, "inventory/import_items.html", {"preview": preview, "columns": imp.COLUMNS})
