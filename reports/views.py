import csv
from datetime import date

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
