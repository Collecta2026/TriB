import csv
from datetime import date, timedelta

from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.dateparse import parse_date

from ledger.models import Account
from users.permissions import require_perm

from . import services


def _period(request):
    today = timezone.localdate()
    date_from = parse_date(request.GET.get("from", "") or "") or date(today.year, 1, 1)
    date_to = parse_date(request.GET.get("to", "") or "") or today
    return date_from, date_to


@require_perm("reports.view")
def index(request):
    return render(request, "reports/index.html")


@require_perm("reports.view")
def trial_balance(request):
    date_from, date_to = _period(request)
    rows, totals = services.trial_balance(request.company, date_from, date_to)
    if request.GET.get("format") == "csv" and request.membership.has_perm("reports.export"):
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="trial-balance-{date_to}.csv"'
        response.write("﻿")  # so Excel opens Arabic correctly
        writer = csv.writer(response)
        writer.writerow(["Code", "Account (EN)", "Account (AR)", "Opening Dr", "Opening Cr", "Period Dr", "Period Cr", "Closing Dr", "Closing Cr"])
        for r in rows:
            a = r["account"]
            writer.writerow([a.code, a.name_en, a.name_ar, r["od"], r["oc"], r["pd"], r["pc"], r["cd"], r["cc"]])
        writer.writerow(["", "Total", "", totals["od"], totals["oc"], totals["pd"], totals["pc"], totals["cd"], totals["cc"]])
        return response
    return render(request, "reports/trial_balance.html", {"rows": rows, "t": totals, "from": date_from, "to": date_to})


@require_perm("reports.view")
def statement(request):
    date_from, date_to = _period(request)
    accounts = Account.objects.filter(company=request.company, is_group=False)
    account = None
    ctx = {"accounts": accounts, "from": date_from, "to": date_to}
    if request.GET.get("account", "").isdigit():
        account = get_object_or_404(Account, pk=request.GET["account"], company=request.company)
        opening, rows, closing = services.statement(account, date_from, date_to)
        ctx.update(account=account, opening=opening, rows=rows, closing=closing)
    return render(request, "reports/statement.html", ctx)


@require_perm("reports.view")
def profit_loss(request):
    date_from, date_to = _period(request)
    return render(request, "reports/profit_loss.html", {
        "r": services.profit_and_loss(request.company, date_from, date_to), "from": date_from, "to": date_to,
    })


@require_perm("reports.view")
def balance_sheet(request):
    _from, as_of = _period(request)
    return render(request, "reports/balance_sheet.html", {"r": services.balance_sheet(request.company, as_of), "to": as_of})


def _as_of(request):
    return parse_date(request.GET.get("to", "") or "") or timezone.localdate()


@require_perm("reports.view")
def ar_aging(request):
    from sales.services import AGING_BUCKETS, ar_aging as aging
    as_of = _as_of(request)
    rows = aging(request.company, as_of)
    return render(request, "reports/aging.html", {
        "rows": rows, "to": as_of, "kind": "customer", "buckets": AGING_BUCKETS,
        "totals": [sum(r["buckets"][i] for r in rows) for i in range(5)], "total": sum(r["total"] for r in rows)})


@require_perm("reports.view")
def ap_aging(request):
    from purchases.services import ap_aging as aging
    from sales.services import AGING_BUCKETS
    as_of = _as_of(request)
    rows = aging(request.company, as_of)
    return render(request, "reports/aging.html", {
        "rows": rows, "to": as_of, "kind": "supplier", "buckets": AGING_BUCKETS,
        "totals": [sum(r["buckets"][i] for r in rows) for i in range(5)], "total": sum(r["total"] for r in rows)})


@require_perm("reports.view")
def vat_return(request):
    today = timezone.localdate()
    first = today.replace(day=1)
    if "from" not in request.GET:  # default: last complete month, as filed with the ETA
        last_month_end = first - timedelta(days=1)
        date_from, date_to = last_month_end.replace(day=1), last_month_end
    else:
        date_from, date_to = _period(request)
    return render(request, "reports/vat_return.html", {
        "r": services.vat_return(request.company, date_from, date_to), "from": date_from, "to": date_to})


@require_perm("reports.view")
def sales_by_item(request):
    today = timezone.localdate()
    if "from" not in request.GET:
        date_from, date_to = today - timedelta(days=90), today
    else:
        date_from, date_to = _period(request)
    groups = services.sales_by_item(request.company, date_from, date_to)
    return render(request, "reports/sales_by_item.html", {
        "groups": groups, "from": date_from, "to": date_to,
        "total": {k: sum((g[k] for g in groups), services.ZERO) for k in ("revenue", "cost", "margin")}})
