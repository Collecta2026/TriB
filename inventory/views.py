from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from core.models import AuditLog, client_ip
from users.permissions import require_perm

from . import services
from .forms import (ADJUSTMENT_LINES, TRANSFER_LINES, AdjustmentForm, CategoryForm, CountStartForm, ItemForm,
                    LabelForm, TransferForm, WarehouseForm)
from .models import (Category, Item, StockAdjustment, StockCount, StockCountLine, StockLayer, StockMove,
                     StockTransfer, Warehouse)

ZERO = Decimal("0")


def _warehouse_filter(request):
    wid = request.GET.get("warehouse", "")
    return Warehouse.objects.filter(company=request.company, pk=wid).first() if wid.isdigit() else None


# ---------- Overview ----------
@require_perm("inventory.view")
def overview(request):
    from purchases.models import PurchaseOrder
    from purchases.services import outstanding_lines
    from sales.models import SalesOrder

    company = request.company
    summary = services.stock_summary(company)
    on_hand = {item.id: qty for item, qty, _v in summary}
    low = [i for i in Item.objects.filter(company=company, type="inventory", is_active=True, reorder_level__gt=0)
           if on_hand.get(i.id, ZERO) <= i.reorder_level]
    expiring = services.batches_on_hand(company, expiring_within=90)
    return render(request, "inventory/overview.html", {
        "value": sum((v for _i, _q, v in summary), ZERO), "lines": len(summary),
        "items": Item.objects.filter(company=company, is_active=True).count(),
        "low": [(i, on_hand.get(i.id, ZERO)) for i in low][:15], "low_count": len(low),
        "expiring": expiring[:15], "expired_count": sum(1 for r in expiring if r["state"] == "expired"),
        "soon_count": sum(1 for r in expiring if r["state"] == "soon"),
        "not_received": len(outstanding_lines(company)),
        "open_pos": PurchaseOrder.objects.filter(company=company, status__in=("open", "partial")).count(),
        "open_sos": SalesOrder.objects.filter(company=company, status__in=("open", "partial")).count(),
        "moves": StockMove.objects.filter(company=company).select_related("item", "warehouse").order_by("-date", "-id")[:12],
        "warehouses": Warehouse.objects.filter(company=company, is_active=True),
    })


# ---------- Products & services ----------
@require_perm("inventory.view")
def items(request):
    qs = Item.objects.filter(company=request.company).select_related("category")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(sku__icontains=q) | Q(name_en__icontains=q) | Q(name_ar__icontains=q) | Q(barcode=q))
    kind = request.GET.get("type", "")
    if kind:
        qs = qs.filter(type=kind)
    cat = request.GET.get("category", "")
    if cat.isdigit():
        qs = qs.filter(category_id=cat)
    if request.GET.get("inactive") != "1":
        qs = qs.filter(is_active=True)
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    qty = dict(StockLayer.objects.filter(item__in=list(page), qty_remaining__gt=0).values("item_id")
               .annotate(q=Sum("qty_remaining")).values_list("item_id", "q"))
    rows = [{"i": i, "qty": qty.get(i.id, ZERO)} for i in page]
    return render(request, "inventory/items.html", {"rows": rows, "page": page, "q": q, "types": Item.TYPES,
                                                    "categories": Category.objects.filter(company=request.company)})


def _item_form(request, item):
    form = ItemForm(request.POST or None, instance=item, company=request.company)
    if request.method == "POST" and form.is_valid():
        item = form.save(commit=False)
        item.company = request.company
        if not item.sku:
            item.sku = services.next_sku(request.company, item.category)
        item.save()
        AuditLog.record(request.company, request.user, "item.saved", item, item.sku, ip=client_ip(request))
        messages.success(request, _("Saved."))
        return redirect("inventory:item", pk=item.pk)
    return render(request, "inventory/item_form.html", {"form": form, "item": item})


@require_perm("inventory.create")
def item_new(request):
    from ledger.models import TaxRate
    company = request.company
    default_tax = TaxRate.objects.filter(company=company, is_default=True, is_active=True).first()
    return _item_form(request, Item(company=company, sales_tax=default_tax, purchase_tax=default_tax))


@require_perm("inventory.edit")
def item_edit(request, pk):
    return _item_form(request, get_object_or_404(Item, pk=pk, company=request.company))


@require_perm("inventory.view")
def item(request, pk):
    item = get_object_or_404(Item, pk=pk, company=request.company)
    layers = item.layers.filter(qty_remaining__gt=0).select_related("warehouse").order_by("expiry_date", "date", "id")
    by_wh = item.layers.filter(qty_remaining__gt=0).values("warehouse__code", "warehouse__name_en") \
        .annotate(q=Sum("qty_remaining")).order_by("warehouse__code")
    value = sum((l.qty_remaining * l.unit_cost for l in layers), ZERO)
    return render(request, "inventory/item_detail.html", {
        "item": item, "layers": layers, "by_wh": by_wh, "on_hand": sum((l.qty_remaining for l in layers), ZERO),
        "value": services.money(value), "today": timezone.localdate(),
        "moves": item.moves.select_related("warehouse").order_by("-date", "-id")[:30]})


# ---------- Categories & warehouses ----------
def _simple_list(request, model, form_class, template, redirect_name, perm_edit):
    obj = None
    pk = request.GET.get("edit") or request.POST.get("pk")
    if pk and str(pk).isdigit():
        obj = get_object_or_404(model, pk=pk, company=request.company)
    form = None
    if request.membership.has_perm(perm_edit if obj else perm_edit.replace(".edit", ".create")):
        form = form_class(request.POST or None, instance=obj or model(company=request.company), company=request.company)
        if request.method == "POST" and form.is_valid():
            saved = form.save(commit=False)
            saved.company = request.company
            saved.save()
            messages.success(request, _("Saved."))
            return redirect(redirect_name)
    return render(request, template, {"rows": model.objects.filter(company=request.company), "form": form, "obj": obj})


@require_perm("inventory.view")
def categories(request):
    return _simple_list(request, Category, CategoryForm, "inventory/categories.html", "inventory:categories",
                        "inventory.edit")


@require_perm("inventory.view")
def warehouses(request):
    return _simple_list(request, Warehouse, WarehouseForm, "inventory/warehouses.html", "inventory:warehouses",
                        "inventory.edit")


# ---------- Stock on hand & expiry ----------
@require_perm("inventory.view")
def stock(request):
    wh = _warehouse_filter(request)
    rows = services.stock_summary(request.company, wh)
    q = request.GET.get("q", "").strip().lower()
    if q:
        rows = [r for r in rows if q in r[0].sku.lower() or q in r[0].name_en.lower() or q in (r[0].name_ar or "")]
    return render(request, "inventory/stock.html", {
        "rows": rows, "total": sum((v for _i, _q, v in rows), ZERO), "warehouse": wh, "q": q,
        "warehouses": Warehouse.objects.filter(company=request.company)})


@require_perm("inventory.view")
def expiry(request):
    wh = _warehouse_filter(request)
    window = request.GET.get("within", "")
    rows = services.batches_on_hand(request.company, wh, expiring_within=int(window) if window.isdigit() else None)
    if window == "expired":
        rows = [r for r in rows if r["state"] == "expired"]
    return render(request, "inventory/expiry.html", {
        "rows": rows, "warehouse": wh, "within": window, "total": sum((r["value"] for r in rows), ZERO),
        "warehouses": Warehouse.objects.filter(company=request.company)})


# ---------- Transfers and adjustments ----------
STOCK_DOCS = {
    "transfer": {"model": StockTransfer, "form": TransferForm, "lines": TRANSFER_LINES, "post": services.post_transfer,
                 "list": "inventory:transfers", "detail": "inventory:transfer"},
    "adjustment": {"model": StockAdjustment, "form": AdjustmentForm, "lines": ADJUSTMENT_LINES,
                   "post": services.post_adjustment, "list": "inventory:adjustments", "detail": "inventory:adjustment"},
}


def _doc_list(request, kind):
    cfg = STOCK_DOCS[kind]
    qs = cfg["model"].objects.filter(company=request.company)
    page = Paginator(qs, 40).get_page(request.GET.get("page"))
    return render(request, f"inventory/{kind}s.html", {"page": page})


@transaction.atomic
def _doc_form(request, kind, doc):
    cfg = STOCK_DOCS[kind]
    form = cfg["form"](request.POST or None, instance=doc, company=request.company)
    formset = (cfg["lines"][0] if doc.pk else cfg["lines"][1])(request.POST or None, instance=doc,
                                                                company=request.company, prefix="lines")
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        doc = form.save(commit=False)
        doc.company = request.company
        doc.save()
        formset.instance = doc
        formset.save()
        if "post" in request.POST and request.membership.has_perm("inventory.post"):
            try:
                with transaction.atomic():
                    cfg["post"](doc, request.user)
                messages.success(request, _("%(n)s posted.") % {"n": doc.number})
            except services.StockError as exc:
                messages.error(request, str(exc))
        else:
            messages.success(request, _("Saved."))
        return redirect(cfg["detail"], pk=doc.pk)
    return render(request, "inventory/doc_form.html", {"form": form, "formset": formset, "doc": doc, "kind": kind,
                                                       "list_url": cfg["list"]})


def _doc_new(request, kind):
    cfg = STOCK_DOCS[kind]
    first = Warehouse.objects.filter(company=request.company, is_active=True).first()
    doc = cfg["model"](company=request.company, created_by=request.user, date=timezone.localdate())
    if kind == "adjustment":
        doc.warehouse = first
        if request.GET.get("reason") in dict(StockAdjustment.REASONS):
            doc.reason = request.GET["reason"]
    else:
        doc.from_warehouse = first
    return _doc_form(request, kind, doc)


def _doc_edit(request, kind, pk):
    cfg = STOCK_DOCS[kind]
    doc = get_object_or_404(cfg["model"], pk=pk, company=request.company)
    if doc.status != "draft":
        messages.error(request, _("This document can no longer be changed."))
        return redirect(cfg["detail"], pk=pk)
    return _doc_form(request, kind, doc)


def _doc_detail(request, kind, pk):
    cfg = STOCK_DOCS[kind]
    doc = get_object_or_404(cfg["model"], pk=pk, company=request.company)
    return render(request, f"inventory/{kind}_detail.html", {
        "doc": doc, "lines": doc.lines.select_related("item"),
        "moves": StockMove.objects.filter(company=request.company, ref=doc.number).select_related("item", "warehouse")
        if doc.number else []})


def _doc_post(request, kind, pk):
    cfg = STOCK_DOCS[kind]
    doc = get_object_or_404(cfg["model"], pk=pk, company=request.company)
    try:
        with transaction.atomic():
            cfg["post"](doc, request.user)
        messages.success(request, _("%(n)s posted.") % {"n": doc.number})
    except services.StockError as exc:
        messages.error(request, str(exc))
    return redirect(cfg["detail"], pk=pk)


transfers = require_perm("inventory.view")(lambda r: _doc_list(r, "transfer"))
transfer_new = require_perm("inventory.create")(lambda r: _doc_new(r, "transfer"))
transfer_edit = require_perm("inventory.edit")(lambda r, pk: _doc_edit(r, "transfer", pk))
transfer = require_perm("inventory.view")(lambda r, pk: _doc_detail(r, "transfer", pk))
transfer_post = require_POST(require_perm("inventory.post")(lambda r, pk: _doc_post(r, "transfer", pk)))
adjustments = require_perm("inventory.view")(lambda r: _doc_list(r, "adjustment"))
adjustment_new = require_perm("inventory.create")(lambda r: _doc_new(r, "adjustment"))
adjustment_edit = require_perm("inventory.edit")(lambda r, pk: _doc_edit(r, "adjustment", pk))
adjustment = require_perm("inventory.view")(lambda r, pk: _doc_detail(r, "adjustment", pk))
adjustment_post = require_POST(require_perm("inventory.post")(lambda r, pk: _doc_post(r, "adjustment", pk)))


# ---------- Stock take ----------
@require_perm("inventory.view")
def counts(request):
    form = CountStartForm(request.POST or None, company=request.company,
                          initial={"date": timezone.localdate(),
                                   "warehouse": Warehouse.objects.filter(company=request.company, is_active=True).first()})
    if request.method == "POST":
        if not request.membership.has_perm("inventory.create"):
            messages.error(request, _("You do not have permission to do that."))
        elif form.is_valid():
            d = form.cleaned_data
            items = Item.objects.filter(company=request.company, type="inventory", is_active=True)
            if d["category"]:
                items = items.filter(category=d["category"])
            count = services.start_count(request.company, d["warehouse"], d["date"], request.user, items)
            return redirect("inventory:count", pk=count.pk)
    page = Paginator(StockCount.objects.filter(company=request.company).select_related("warehouse"), 30) \
        .get_page(request.GET.get("page"))
    return render(request, "inventory/counts.html", {"page": page, "form": form})


@require_perm("inventory.view")
def count(request, pk):
    count = get_object_or_404(StockCount, pk=pk, company=request.company)
    if request.method == "POST" and count.status == "draft" and request.membership.has_perm("inventory.edit"):
        if "code" in request.POST:
            _scan(request, count)
            return redirect(f"{request.path}#scan")
        for line in count.lines.all():
            raw = request.POST.get(f"counted_{line.pk}")
            if raw is None:
                continue
            raw = raw.replace(",", "").strip()
            try:
                line.counted_qty = Decimal(raw) if raw else None
            except InvalidOperation:
                continue
            line.save(update_fields=["counted_qty"])
        messages.success(request, _("Counts saved."))
        return redirect("inventory:count", pk=pk)
    lines = list(count.lines.select_related("item"))
    return render(request, "inventory/count_detail.html", {
        "count": count, "lines": lines, "counted": sum(1 for l in lines if l.counted_qty is not None),
        "differences": [l for l in lines if l.difference]})


def _scan(request, count):
    item = services.find_by_code(request.company, request.POST.get("code"))
    if item is None or not item.is_stocked:
        messages.error(request, _("No stock item has the code %(c)s.") % {"c": request.POST.get("code", "")})
        return
    try:
        qty = Decimal(request.POST.get("qty") or "1")
    except InvalidOperation:
        qty = Decimal("1")
    line = count.lines.filter(item=item).first()
    if line is None:
        line = StockCountLine.objects.create(count=count, item=item, expected_qty=item.on_hand(count.warehouse))
    line.counted_qty = (line.counted_qty or ZERO) + qty
    line.save(update_fields=["counted_qty"])
    messages.success(request, _("%(sku)s counted: %(q)s") % {"sku": item.sku, "q": line.counted_qty.normalize()})


@require_POST
@require_perm("inventory.post")
def count_post(request, pk):
    count = get_object_or_404(StockCount, pk=pk, company=request.company)
    try:
        with transaction.atomic():
            adj = services.post_count(count, request.user)
        messages.success(request, _("Stock take posted as adjustment %(n)s.") % {"n": adj.number})
    except services.StockError as exc:
        messages.error(request, str(exc))
    return redirect("inventory:count", pk=pk)


@require_perm("inventory.view")
def count_sheet(request, pk):
    count = get_object_or_404(StockCount, pk=pk, company=request.company)
    return render(request, "inventory/count_sheet.html", {"count": count, "lines": count.lines.select_related("item")})


# ---------- Barcode labels ----------
@require_perm("inventory.view")
def labels(request):
    form = LabelForm(request.GET or None, company=request.company)
    chosen = []
    if request.GET.getlist("item"):
        ids = [i for i in request.GET.getlist("item") if i.isdigit()]
        copies = int(request.GET.get("copies") or 1) if (request.GET.get("copies") or "1").isdigit() else 1
        for item in Item.objects.filter(company=request.company, pk__in=ids):
            chosen += [item] * min(max(copies, 1), 50)
        return render(request, "inventory/labels_print.html", {"labels": chosen})
    qs = Item.objects.filter(company=request.company, is_active=True, type="inventory")
    if form.is_valid():
        if form.cleaned_data["category"]:
            qs = qs.filter(category=form.cleaned_data["category"])
        if form.cleaned_data["q"]:
            q = form.cleaned_data["q"]
            qs = qs.filter(Q(sku__icontains=q) | Q(name_en__icontains=q) | Q(name_ar__icontains=q))
    return render(request, "inventory/labels.html", {"form": form, "items": qs[:300]})
