"""Straight-line depreciation, disposals and asset counts."""
from collections import defaultdict
from datetime import date as date_cls
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from core.models import AuditLog, NumberSeries
from ledger.services import Line, PostingError, post_journal, system_account

from .models import Asset, AssetCount, AssetCountLine, DepreciationLine, DepreciationRun

ZERO = Decimal("0")


class AssetError(Exception):
    pass


def next_asset_number(company):
    while True:
        number = NumberSeries.next_plain(company, "FA")
        if not Asset.objects.filter(company=company, number=number).exists():
            return number


def month_end(period):
    nxt = date_cls(period.year + (period.month == 12), period.month % 12 + 1, 1)
    return nxt.fromordinal(nxt.toordinal() - 1)


def charge_for(asset, period):
    """This month's depreciation for one asset (never below residual value)."""
    if asset.status == "disposed" or asset.in_service_date > month_end(period):
        return ZERO
    remaining = asset.book_value - asset.salvage_value
    if remaining <= 0:
        return ZERO
    return min(asset.monthly_charge, remaining)


@transaction.atomic
def run_depreciation(company, period, user):
    period = period.replace(day=1)
    if DepreciationRun.objects.filter(company=company, period=period).exists():
        raise AssetError(_("Depreciation for this month has already been posted."))
    later = DepreciationRun.objects.filter(company=company, period__gt=period).exists()
    if later:
        raise AssetError(_("A later month is already posted; post months in order."))
    run = DepreciationRun.objects.create(company=company, period=period, created_by=user)
    by_category = defaultdict(Decimal)
    for asset in Asset.objects.filter(company=company).exclude(status="disposed").select_related("category"):
        amount = charge_for(asset, period)
        if amount > 0:
            DepreciationLine.objects.create(run=run, asset=asset, amount=amount)
            by_category[asset.category] += amount
    if not by_category:
        run.delete()
        raise AssetError(_("Nothing to depreciate for this month."))
    lines, label = [], period.strftime("%Y-%m")
    for category, amount in by_category.items():
        lines += [Line(category.expense_account, debit=amount, description=f"{category.name_en} {label}"),
                  Line(category.depreciation_account, credit=amount, description=f"{category.name_en} {label}")]
    try:
        run.journal_entry = post_journal(company, month_end(period), lines, memo=_("Depreciation %(m)s") % {"m": label},
                                         source="depreciation", source_ref=f"DEP-{label}", user=user)
    except PostingError as exc:
        raise AssetError(str(exc)) from exc
    run.save(update_fields=["journal_entry"])
    AuditLog.record(company, user, "assets.depreciation", run, label)
    return run


@transaction.atomic
def dispose(asset, date, proceeds, bank_account, user):
    if asset.status == "disposed":
        raise AssetError(_("This asset is already disposed."))
    company = asset.company
    proceeds = Decimal(proceeds or 0)
    accumulated, cost = asset.accumulated, asset.cost
    gain = proceeds - (cost - accumulated)
    lines = [Line(asset.category.depreciation_account, debit=accumulated, description=asset.number),
             Line(asset.category.asset_account, credit=cost, description=asset.number)]
    if proceeds:
        if bank_account is None:
            raise AssetError(_("Choose the account that received the sale proceeds."))
        lines.append(Line(bank_account.gl_account, debit=proceeds, description=asset.number))
    if gain > 0:
        lines.append(Line(system_account(company, "disposal_gain"), credit=gain, description=asset.number))
    elif gain < 0:
        lines.append(Line(system_account(company, "disposal_loss"), debit=-gain, description=asset.number))
    try:
        entry = post_journal(company, date, lines, memo=_("Disposal of %(n)s") % {"n": asset.number}, source="asset",
                             source_ref=asset.number, user=user)
    except PostingError as exc:
        raise AssetError(str(exc)) from exc
    asset.status, asset.disposed_on, asset.disposal_proceeds, asset.disposal_entry = "disposed", date, proceeds, entry
    asset.save(update_fields=["status", "disposed_on", "disposal_proceeds", "disposal_entry"])
    AuditLog.record(company, user, "asset.disposed", asset, f"{asset.number} {proceeds}")


@transaction.atomic
def start_count(company, date, user, branch=None, warehouse=None):
    count = AssetCount.objects.create(company=company, number=NumberSeries.next(company, "AC", date), date=date,
                                      branch=branch, warehouse=warehouse, created_by=user)
    assets = Asset.objects.filter(company=company).exclude(status="disposed")
    if branch:
        assets = assets.filter(branch=branch)
    if warehouse:
        assets = assets.filter(warehouse=warehouse)
    AssetCountLine.objects.bulk_create([AssetCountLine(count=count, asset=a) for a in assets])
    return count


def scan(count, code):
    """Mark an asset found by its barcode (asset number). Returns (line, message)."""
    code = (code or "").strip()
    line = count.lines.select_related("asset").filter(asset__number__iexact=code).first()
    if line is None:
        asset = Asset.objects.filter(company=count.company, number__iexact=code).first()
        if asset is None:
            return None, _("Unknown asset number: %(c)s") % {"c": code}
        return None, _("%(n)s is not on this count list (it belongs to another location).") % {"n": asset.number}
    if not line.found:
        line.found, line.scanned_at = True, timezone.now()
        line.save(update_fields=["found", "scanned_at"])
    return line, _("Found: %(n)s") % {"n": line.asset}


@transaction.atomic
def close_count(count, user, mark_missing=True):
    if count.status != "open":
        raise AssetError(_("This count is already closed."))
    if mark_missing:
        for line in count.lines.filter(found=False).select_related("asset"):
            line.asset.status = "missing"
            line.asset.save(update_fields=["status"])
    for line in count.lines.filter(found=True).select_related("asset"):
        if line.asset.status == "missing":
            line.asset.status = "active"
            line.asset.save(update_fields=["status"])
    count.status = "closed"
    count.save(update_fields=["status"])
    AuditLog.record(count.company, user, "assets.count_closed", count, count.number)
