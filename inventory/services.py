"""FIFO stock engine. Every receipt creates cost layers; every issue consumes the oldest layers first.

Serial-tracked items (machines) are one layer per serial number. Batch-tracked items (consumables) are
issued soonest-expiry first, which is still FIFO by receipt within the same expiry date.
"""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import F, Q, Sum
from django.utils.translation import gettext as _

from core.models import AuditLog, NumberSeries
from ledger.services import Line, PostingError, post_journal, system_account

from .models import (Item, StockAdjustment, StockCount, StockCountLine, StockLayer, StockMove, StockTransfer,
                     Warehouse)

ZERO = Decimal("0")
CENT = Decimal("0.01")


class StockError(Exception):
    pass


def money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def parse_serials(text):
    return [s.strip() for s in (text or "").replace(",", "\n").splitlines() if s.strip()]


def next_sku(company, category=None):
    prefix = (category.prefix if category else "ITM").upper()
    while True:
        sku = NumberSeries.next_plain(company, prefix)
        if not Item.objects.filter(company=company, sku=sku).exists():
            return sku


def inventory_account(item):
    return item.inventory_account or system_account(item.company, "inventory")


def cogs_account(item):
    return item.expense_account or system_account(item.company, "cogs")


@dataclass
class Issued:
    layer: StockLayer
    qty: Decimal
    cost: Decimal  # base currency, 2 dp


def receive(item, warehouse, qty, unit_cost, date, ref, kind="receipt", serials=None, batch_no="", expiry_date=None):
    """Add stock at `unit_cost` (base currency). Returns the total value received."""
    if not item.is_stocked:
        return ZERO
    qty = Decimal(qty)
    if qty <= 0:
        raise StockError(_("Quantity must be greater than zero."))
    unit_cost = Decimal(unit_cost)
    serials = serials or []
    if item.tracking == "serial":
        if len(serials) != qty or qty != int(qty):
            raise StockError(_("%(sku)s needs exactly %(n)s serial numbers.") % {"sku": item.sku, "n": qty.normalize()})
        if len(set(serials)) != len(serials):
            raise StockError(_("The same serial number is entered twice for %(sku)s.") % {"sku": item.sku})
        clash = StockLayer.objects.filter(item=item, serial_no__in=serials, qty_remaining__gt=0).values_list("serial_no", flat=True)
        if clash:
            raise StockError(_("Serial number already in stock: %(s)s") % {"s": ", ".join(clash)})
        chunks = [(Decimal("1"), s) for s in serials]
    else:
        if item.tracking == "batch" and not batch_no:
            raise StockError(_("Enter the batch number for %(sku)s.") % {"sku": item.sku})
        if item.tracking == "batch" and not expiry_date:
            raise StockError(_("Enter the expiry date for %(sku)s.") % {"sku": item.sku})
        if item.tracking == "batch" and kind in ("receipt", "opening") and expiry_date <= date:
            raise StockError(_("%(sku)s batch %(b)s is already expired. Do not receive it into stock.") % {
                "sku": item.sku, "b": batch_no})
        chunks = [(qty, "")]
    total = ZERO
    for chunk_qty, serial in chunks:
        layer = StockLayer.objects.create(
            company=item.company, item=item, warehouse=warehouse, date=date, ref=ref, qty_in=chunk_qty,
            qty_remaining=chunk_qty, unit_cost=unit_cost, serial_no=serial, batch_no=batch_no or "",
            expiry_date=expiry_date,
        )
        value = money(chunk_qty * unit_cost)
        StockMove.objects.create(company=item.company, item=item, warehouse=warehouse, date=date, kind=kind,
                                 qty=chunk_qty, unit_cost=unit_cost, value=value, ref=ref, layer=layer,
                                 serial_no=serial, batch_no=batch_no or "", expiry_date=expiry_date)
        total += value
    return total


def issue(item, warehouse, qty, date, ref, kind="issue", serials=None):
    """Take stock out, oldest layers first. Returns (total cost, [Issued])."""
    if not item.is_stocked:
        return ZERO, []
    qty = Decimal(qty)
    if qty <= 0:
        raise StockError(_("Quantity must be greater than zero."))
    layers = StockLayer.objects.select_for_update().filter(item=item, warehouse=warehouse, qty_remaining__gt=0)
    serials = serials or []
    if item.tracking == "serial" and serials:
        if len(serials) != qty:
            raise StockError(_("%(sku)s needs exactly %(n)s serial numbers.") % {"sku": item.sku, "n": qty.normalize()})
        layers = list(layers.filter(serial_no__in=serials))
        missing = set(serials) - {l.serial_no for l in layers}
        if missing:
            raise StockError(_("Serial number not in this warehouse: %(s)s") % {"s": ", ".join(sorted(missing))})
    elif item.tracking == "batch":
        if kind == "issue":
            # Never sell expired consumables; write them off with an "Expired" stock adjustment instead.
            layers = layers.filter(Q(expiry_date__isnull=True) | Q(expiry_date__gte=date))
        layers = list(layers.order_by(F("expiry_date").asc(nulls_last=True), "date", "id"))
    else:
        layers = list(layers.order_by("date", "id"))

    available = sum((l.qty_remaining for l in layers), ZERO)
    if available < qty and kind == "issue" and item.tracking == "batch":
        expired = StockLayer.objects.filter(item=item, warehouse=warehouse, qty_remaining__gt=0,
                                            expiry_date__lt=date).aggregate(q=Sum("qty_remaining"))["q"]
        if expired:
            raise StockError(_("Not enough stock of %(sku)s in %(wh)s: %(have)s in date, %(need)s needed "
                               "(%(exp)s more is expired and cannot be sold).") % {
                "sku": item.sku, "wh": warehouse.code, "have": available.normalize(), "need": qty.normalize(),
                "exp": expired.normalize()})
    if available < qty:
        raise StockError(_("Not enough stock of %(sku)s in %(wh)s: %(have)s available, %(need)s needed.") % {
            "sku": item.sku, "wh": warehouse.code, "have": available.normalize(), "need": qty.normalize()})

    remaining, out, total = qty, [], ZERO
    for layer in layers:
        if remaining <= 0:
            break
        take = min(layer.qty_remaining, remaining)
        layer.qty_remaining -= take
        layer.save(update_fields=["qty_remaining"])
        cost = money(take * layer.unit_cost)
        StockMove.objects.create(company=item.company, item=item, warehouse=warehouse, date=date, kind=kind,
                                 qty=-take, unit_cost=layer.unit_cost, value=-cost, ref=ref, layer=layer,
                                 serial_no=layer.serial_no, batch_no=layer.batch_no, expiry_date=layer.expiry_date)
        out.append(Issued(layer, take, cost))
        total += cost
        remaining -= take
    return total, out


@transaction.atomic
def post_transfer(transfer, user):
    if transfer.status != "draft":
        raise StockError(_("This transfer is already posted."))
    if transfer.from_warehouse_id == transfer.to_warehouse_id:
        raise StockError(_("Choose two different warehouses."))
    if not transfer.number:
        transfer.number = NumberSeries.next(transfer.company, "TRF", transfer.date)
    for line in transfer.lines.select_related("item"):
        _cost, issued = issue(line.item, transfer.from_warehouse, line.qty, transfer.date, transfer.number,
                              kind="transfer_out", serials=parse_serials(line.serials))
        for part in issued:
            receive(line.item, transfer.to_warehouse, part.qty, part.layer.unit_cost, transfer.date, transfer.number,
                    kind="transfer_in", serials=[part.layer.serial_no] if part.layer.serial_no else None,
                    batch_no=part.layer.batch_no, expiry_date=part.layer.expiry_date)
    transfer.status = "posted"
    transfer.save(update_fields=["number", "status"])
    AuditLog.record(transfer.company, user, "stock.transfer", transfer, transfer.number)


@transaction.atomic
def post_adjustment(adjustment, user):
    if adjustment.status != "draft":
        raise StockError(_("This adjustment is already posted."))
    company = adjustment.company
    if not adjustment.number:
        adjustment.number = NumberSeries.next(company, "ADJ", adjustment.date)
    offset = system_account(company, "opening_equity" if adjustment.reason == "opening" else "stock_adjustment")
    lines = []
    for line in adjustment.lines.select_related("item"):
        item = line.item
        if not item.is_stocked or not line.qty_change:
            continue
        if line.qty_change > 0:
            cost = line.unit_cost if line.unit_cost else item.purchase_cost
            value = receive(item, adjustment.warehouse, line.qty_change, cost, adjustment.date, adjustment.number,
                            kind="opening" if adjustment.reason == "opening" else "adjust_in",
                            serials=parse_serials(line.serials), batch_no=line.batch_no, expiry_date=line.expiry_date)
            lines += [Line(inventory_account(item), debit=value, description=f"{item.sku} +{line.qty_change.normalize()}"),
                      Line(offset, credit=value, description=f"{item.sku} +{line.qty_change.normalize()}")]
        else:
            value, _issued = issue(item, adjustment.warehouse, -line.qty_change, adjustment.date, adjustment.number,
                                   kind="adjust_out", serials=parse_serials(line.serials))
            lines += [Line(offset, debit=value, description=f"{item.sku} {line.qty_change.normalize()}"),
                      Line(inventory_account(item), credit=value, description=f"{item.sku} {line.qty_change.normalize()}")]
    lines = [l for l in lines if l.debit or l.credit]
    if lines:
        try:
            adjustment.journal_entry = post_journal(
                company, adjustment.date, lines, memo=f"{adjustment.number} {adjustment.get_reason_display()}",
                source="stock", source_ref=adjustment.number, user=user)
        except PostingError as exc:
            raise StockError(str(exc)) from exc
    adjustment.status = "posted"
    adjustment.save(update_fields=["number", "status", "journal_entry"])
    AuditLog.record(company, user, "stock.adjustment", adjustment, adjustment.number)


def start_count(company, warehouse, date, user, items=None):
    """Freeze the expected quantity of every stocked item in a warehouse, ready for counting."""
    count = StockCount.objects.create(company=company, warehouse=warehouse, date=date, created_by=user,
                                      number=NumberSeries.next(company, "CNT", date))
    on_hand = dict(
        StockLayer.objects.filter(warehouse=warehouse, qty_remaining__gt=0).values("item_id")
        .annotate(q=Sum("qty_remaining")).values_list("item_id", "q")
    )
    qs = items if items is not None else Item.objects.filter(company=company, type="inventory", is_active=True)
    StockCountLine.objects.bulk_create(
        [StockCountLine(count=count, item=i, expected_qty=on_hand.get(i.id, ZERO)) for i in qs]
    )
    return count


@transaction.atomic
def post_count(count, user):
    """Turn the differences of a stock take into one stock adjustment."""
    if count.status != "draft":
        raise StockError(_("This stock take is already posted."))
    adjustment = StockAdjustment.objects.create(
        company=count.company, warehouse=count.warehouse, date=count.date, reason="count", created_by=user,
        notes=_("Stock take %(n)s") % {"n": count.number},
    )
    for line in count.lines.select_related("item"):
        diff = line.difference
        if not diff:
            continue
        batch_no, expiry = "", None
        if diff > 0 and line.item.tracking == "batch":
            # Extra consumables found: book them to the most recent batch seen in this warehouse.
            last = StockLayer.objects.filter(item=line.item, warehouse=count.warehouse).exclude(expiry_date=None) \
                .order_by("-date", "-id").first()
            if last is None:
                raise StockError(_("%(sku)s: extra stock was counted but no batch is known. Enter it with a stock "
                                   "adjustment showing its batch and expiry date.") % {"sku": line.item.sku})
            batch_no, expiry = last.batch_no, last.expiry_date
        adjustment.lines.create(item=line.item, qty_change=diff, unit_cost=line.item.purchase_cost,
                                batch_no=batch_no, expiry_date=expiry)
    post_adjustment(adjustment, user)
    count.adjustment = adjustment
    count.status = "posted"
    count.save(update_fields=["adjustment", "status"])
    return adjustment


def stock_summary(company, warehouse=None):
    """[(item, qty, value)] of stock on hand at FIFO cost."""
    qs = StockLayer.objects.filter(company=company, qty_remaining__gt=0)
    if warehouse is not None:
        qs = qs.filter(warehouse=warehouse)
    rows = {}
    for layer in qs.select_related("item"):
        qty, value = rows.get(layer.item_id, (ZERO, ZERO))
        rows[layer.item_id] = (qty + layer.qty_remaining, value + layer.qty_remaining * layer.unit_cost)
    items = {i.id: i for i in Item.objects.filter(id__in=rows)}
    return sorted(((items[k], q, money(v)) for k, (q, v) in rows.items()), key=lambda r: r[0].sku)


def batches_on_hand(company, warehouse=None, expiring_within=None, today=None):
    """Batch / expiry stock still in the warehouse, soonest expiry first.

    Rows: dict(item, warehouse, batch_no, expiry_date, qty, value, days_left, state) where state is
    "expired", "soon" (within 90 days) or "ok".
    """
    from datetime import timedelta
    from django.utils import timezone
    today = today or timezone.localdate()
    qs = StockLayer.objects.filter(company=company, qty_remaining__gt=0).exclude(expiry_date=None)
    if warehouse is not None:
        qs = qs.filter(warehouse=warehouse)
    if expiring_within is not None:
        qs = qs.filter(expiry_date__lte=today + timedelta(days=expiring_within))
    rows = {}
    for layer in qs.select_related("item", "warehouse").order_by("expiry_date", "item__sku"):
        key = (layer.item_id, layer.warehouse_id, layer.batch_no, layer.expiry_date)
        row = rows.setdefault(key, {"item": layer.item, "warehouse": layer.warehouse, "batch_no": layer.batch_no,
                                    "expiry_date": layer.expiry_date, "qty": ZERO, "value": ZERO})
        row["qty"] += layer.qty_remaining
        row["value"] += layer.qty_remaining * layer.unit_cost
    out = []
    for row in rows.values():
        row["value"] = money(row["value"])
        row["days_left"] = (row["expiry_date"] - today).days
        row["state"] = "expired" if row["days_left"] < 0 else "soon" if row["days_left"] <= 90 else "ok"
        out.append(row)
    return out


def find_by_code(company, code):
    code = (code or "").strip()
    if not code:
        return None
    return Item.objects.filter(company=company).filter(Q(sku__iexact=code) | Q(barcode=code)).first()
