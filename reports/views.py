import csv
from datetime import date

from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from ledger.models import Account
from users.permissions import require_perm

from . import catalog, extra, periods, services


def _period(request, default=None):
    date_from, date_to, request.report_period = periods.resolve(request, timezone.localdate(), default)
    return date_from, date_to


@require_perm("reports.view")
def index(request):
    from core.models import UserPreference

    pref = UserPreference.for_user(request.user, request.company)
    sections, favourites = catalog.visible_sections(request.membership, pref.report_favourites or [])
    return render(request, "reports/index.html", {"sections": sections, "favourites": favourites,
                                                  "can_export": request.membership.has_perm("reports.export")})


@require_POST
@require_perm("reports.view")
def favourite(request):
    from core.models import UserPreference

    key = request.POST.get("key", "")
    if key not in catalog.KEYS:
        return JsonResponse({"error": "unknown report"}, status=400)
    pref = UserPreference.for_user(request.user, request.company)
    favs = list(pref.report_favourites or [])
    on = key not in favs
    favs = favs + [key] if on else [k for k in favs if k != key]
    pref.report_favourites = favs
    pref.save(update_fields=["report_favourites"])
    return JsonResponse({"on": on})


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
    chosen = request.GET.get("account", "")
    ctx = {"accounts": accounts, "from": date_from, "to": date_to,
           "controls": [{"name": "account", "label": _("Account"), "value": chosen,
                         "options": [("", _("Choose an account"))] + [(str(a.pk), str(a)) for a in accounts]}]}
    if chosen.isdigit():
        account = get_object_or_404(Account, pk=chosen, company=request.company)
        opening, rows, closing = services.statement(account, date_from, date_to)
        ctx.update(account=account, opening=opening, rows=rows, closing=closing)
    return render(request, "reports/statement.html", ctx)


@require_perm("reports.view")
def profit_loss(request):
    date_from, date_to = _period(request)
    return render(request, "reports/profit_loss.html", {
        "r": services.profit_and_loss(request.company, date_from, date_to), "from": date_from, "to": date_to,
    })


def _as_of(request):
    return parse_date(request.GET.get("to", "") or "") or timezone.localdate()


@require_perm("reports.view")
def balance_sheet(request):
    as_of = _as_of(request)
    return render(request, "reports/balance_sheet.html", {"r": services.balance_sheet(request.company, as_of), "to": as_of})


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
    # Default: last complete month, as filed with the ETA.
    date_from, date_to = _period(request, default="last_month")
    return render(request, "reports/vat_return.html", {
        "r": services.vat_return(request.company, date_from, date_to), "from": date_from, "to": date_to})


@require_perm("reports.view")
def sales_by_item(request):
    date_from, date_to = _period(request)
    groups = services.sales_by_item(request.company, date_from, date_to)
    return render(request, "reports/sales_by_item.html", {
        "groups": groups, "from": date_from, "to": date_to,
        "total": {k: sum((g[k] for g in groups), services.ZERO) for k in ("revenue", "cost", "margin")}})


# ---------- Standard reports sharing one table layout (reports/table.html) ----------
def _cols(*specs):
    """("Label", True) → a numeric column."""
    return [{"label": label, "num": num} for label, num in specs]


def _cell(v, column):
    if isinstance(v, date):
        v = f"{v:%d/%m/%Y}"
    elif isinstance(v, int) and not isinstance(v, bool):
        v = f"{v:,}"
    return {"v": v, "num": column["num"]}


def _table(request, title, columns, rows, foot=None, mode="period", date_from=None, date_to=None, note="", controls=None):
    for r in rows:
        r["cells"] = [_cell(v, c) for v, c in zip(r["cells"], columns)]
    foot_cells = [_cell(v, c) for v, c in zip(foot, columns)] if foot else None
    return render(request, "reports/table.html", {
        "title": title, "columns": columns, "rows": rows, "foot": foot_cells, "mode": mode, "from": date_from,
        "to": date_to, "note": note, "controls": controls or []})


def _compare_control(request):
    how = request.GET.get("compare") or periods.user_defaults(request)["compare"]
    how = how if how in dict(periods.COMPARE) else "previous_period"
    return how, [{"name": "compare", "label": _("Compare with"), "value": how, "options": periods.COMPARE}]


@require_perm("reports.view")
def account_list(request):
    as_of = _as_of(request)
    return _table(request, _("Account list"), _cols((_("Account"), False), (_("Type"), False), (_("System role"), False),
                                                    (_("Balance"), True)),
                  extra.account_list(request.company, as_of), mode="asof", date_to=as_of)


@require_perm("reports.view")
def pl_compare(request):
    date_from, date_to = _period(request)
    how, controls = _compare_control(request)
    rows, foot, (c_from, c_to) = extra.pl_compare(request.company, date_from, date_to, how)
    columns = _cols((_("Account"), False), (f"{date_from:%d/%m/%Y} – {date_to:%d/%m/%Y}", True),
                    (f"{c_from:%d/%m/%Y} – {c_to:%d/%m/%Y}", True), (_("Change"), True), (_("% change"), True))
    return _table(request, _("Profit and loss comparison"), columns, rows, foot, date_from=date_from, date_to=date_to,
                  controls=controls)


@require_perm("reports.view")
def pl_month(request):
    date_from, date_to = _period(request)
    months, rows, foot = extra.pl_by_month(request.company, date_from, date_to)
    columns = _cols((_("Account"), False), *[(f"{m:%m/%Y}", True) for m in months], (_("Total"), True))
    return _table(request, _("Profit and loss by month"), columns, rows, foot, date_from=date_from, date_to=date_to,
                  note=_("Up to 24 months are shown.") if len(months) == 24 else "")


@require_perm("reports.view")
def pl_customer(request):
    date_from, date_to = _period(request)
    rows, foot = extra.pl_by_customer(request.company, date_from, date_to)
    return _table(request, _("Profit and loss by customer"),
                  _cols((_("Customer"), False), (_("Income"), True), (_("Cost of sales"), True), (_("Gross profit"), True),
                        (_("Margin %"), True)), rows, foot, date_from=date_from, date_to=date_to,
                  note=_("From posted invoices less credit notes, at FIFO cost."))


LEDGER_COLS = ((gettext_lazy("Date"), False), (gettext_lazy("Type"), False), (gettext_lazy("Number"), False),
               (gettext_lazy("Description"), False), (gettext_lazy("Debit"), True), (gettext_lazy("Credit"), True),
               (gettext_lazy("Balance"), True))


@require_perm("reports.view")
def pl_detail(request):
    date_from, date_to = _period(request)
    return _table(request, _("Profit and loss detail"), _cols(*LEDGER_COLS),
                  extra.pl_detail(request.company, date_from, date_to), date_from=date_from, date_to=date_to)


@require_perm("reports.view")
def bs_compare(request):
    as_of = _as_of(request)
    compare_to = parse_date(request.GET.get("compare_to", "") or "") or date(as_of.year - 1, 12, 31)
    rows, foot = extra.bs_compare(request.company, as_of, compare_to)
    columns = _cols((_("Account"), False), (f"{as_of:%d/%m/%Y}", True), (f"{compare_to:%d/%m/%Y}", True), (_("Change"), True))
    controls = [{"name": "compare_to", "label": _("Compare with"), "value": f"{compare_to:%Y-%m-%d}", "date": True}]
    return _table(request, _("Balance sheet comparison"), columns, rows, foot, mode="asof", date_to=as_of, controls=controls)


@require_perm("reports.view")
def cash_flows(request):
    date_from, date_to = _period(request)
    rows, foot, _info = extra.cash_flows(request.company, date_from, date_to)
    return _table(request, _("Statement of cash flows"), _cols((_("Line"), False), (_("Amount"), True)), rows, foot,
                  date_from=date_from, date_to=date_to,
                  note=_("Indirect method. Inflows are positive, outflows negative."))


@require_perm("reports.view")
def recent(request):
    date_from, date_to = _period(request, default="last_30")
    return _table(request, _("Recent transactions"),
                  _cols((_("Date"), False), (_("Type"), False), (_("Number"), False), (_("Memo"), False), (_("Amount"), True)),
                  extra.recent_transactions(request.company, date_from, date_to), date_from=date_from, date_to=date_to)


@require_perm("reports.view")
def general_ledger(request):
    date_from, date_to = _period(request, default="this_month")
    all_accounts = Account.objects.filter(company=request.company, is_group=False).order_by("code")
    chosen = request.GET.get("account", "")
    accounts = all_accounts.filter(pk=chosen) if chosen.isdigit() else all_accounts
    controls = [{"name": "account", "label": _("Account"), "value": chosen,
                 "options": [("", _("All accounts"))] + [(str(a.pk), str(a)) for a in all_accounts]}]
    return _table(request, _("General ledger"), _cols(*LEDGER_COLS),
                  extra.ledger_detail(request.company, date_from, date_to, list(accounts)), date_from=date_from,
                  date_to=date_to, controls=controls)


@require_perm("reports.view")
def journal(request):
    date_from, date_to = _period(request, default="this_month")
    rows, foot = extra.journal(request.company, date_from, date_to)
    return _table(request, _("Journal"), _cols((_("Date"), False), (_("Number"), False), (_("Type / account"), False),
                                               (_("Description"), False), (_("Debit"), True), (_("Credit"), True)),
                  rows, foot, date_from=date_from, date_to=date_to,
                  note=_("Up to 300 entries are shown; narrow the dates for more."))


DOC_COLS = ((gettext_lazy("Date"), False), (gettext_lazy("Number"), False), (gettext_lazy("Name"), False),
            (gettext_lazy("Due date"), False), (gettext_lazy("Status"), False), (gettext_lazy("Currency"), False),
            (gettext_lazy("Amount"), True), (gettext_lazy("Amount (base)"), True), (gettext_lazy("Open balance (base)"), True))


@require_perm("reports.view")
def invoice_list(request):
    from sales.models import Invoice
    date_from, date_to = _period(request)
    rows, foot = extra.document_list(Invoice, request.company, date_from, date_to, "customer", "sales:invoice")
    return _table(request, _("Invoice list"), _cols(*DOC_COLS), rows, foot, date_from=date_from, date_to=date_to)


@require_perm("reports.view")
def bill_list(request):
    from purchases.models import Bill
    date_from, date_to = _period(request)
    rows, foot = extra.document_list(Bill, request.company, date_from, date_to, "supplier", "purchases:bill")
    return _table(request, _("Bill list"), _cols(*DOC_COLS), rows, foot, date_from=date_from, date_to=date_to)


@require_perm("reports.view")
def sales_customer(request):
    date_from, date_to = _period(request)
    rows, foot = extra.sales_by_customer(request.company, date_from, date_to)
    return _table(request, _("Sales by customer"), _cols((_("Customer"), False), (_("Invoices"), True), (_("Net sales"), True),
                                                         (_("VAT"), True), (_("Total"), True)),
                  rows, foot, date_from=date_from, date_to=date_to,
                  note=_("Posted invoices less credit notes, in base currency."))


@require_perm("reports.view")
def expenses_supplier(request):
    date_from, date_to = _period(request)
    rows, foot = extra.expenses_by_supplier(request.company, date_from, date_to)
    return _table(request, _("Expenses by supplier"), _cols((_("Supplier"), False), (_("Bills"), True), (_("Net"), True),
                                                            (_("VAT"), True), (_("Total"), True)),
                  rows, foot, date_from=date_from, date_to=date_to,
                  note=_("Posted bills less supplier credits, in base currency."))


BAL_DETAIL_COLS = ((gettext_lazy("Date"), False), (gettext_lazy("Type"), False), (gettext_lazy("Number"), False),
                   (gettext_lazy("Due date"), False), (gettext_lazy("Open amount"), True), (gettext_lazy("Balance"), True))


@require_perm("reports.view")
def customer_summary(request):
    as_of = _as_of(request)
    rows, foot = extra.balance_summary(extra.customer_open_items(request.company, as_of), "contacts:customer")
    return _table(request, _("Customer balance summary"), _cols((_("Customer"), False), (_("Open items"), True),
                                                                (_("Balance"), True)),
                  rows, foot, mode="asof", date_to=as_of)


@require_perm("reports.view")
def customer_detail(request):
    as_of = _as_of(request)
    rows, foot = extra.balance_detail(extra.customer_open_items(request.company, as_of), as_of)
    return _table(request, _("Customer balance detail"), _cols(*BAL_DETAIL_COLS), rows, foot, mode="asof", date_to=as_of)


@require_perm("reports.view")
def supplier_summary(request):
    as_of = _as_of(request)
    rows, foot = extra.balance_summary(extra.supplier_open_items(request.company, as_of), "contacts:supplier")
    return _table(request, _("Supplier balance summary"), _cols((_("Supplier"), False), (_("Open items"), True),
                                                                (_("Balance"), True)),
                  rows, foot, mode="asof", date_to=as_of)


@require_perm("reports.view")
def supplier_detail(request):
    as_of = _as_of(request)
    rows, foot = extra.balance_detail(extra.supplier_open_items(request.company, as_of), as_of)
    return _table(request, _("Supplier balance detail"), _cols(*BAL_DETAIL_COLS), rows, foot, mode="asof", date_to=as_of)


@require_perm("inventory.view")
def stock_detail(request):
    rows, foot = extra.inventory_valuation_detail(request.company)
    return _table(request, _("Inventory valuation detail"),
                  _cols((_("Warehouse"), False), (_("Received"), False), (_("Reference"), False), (_("Serial / batch"), False),
                        (_("Expiry date"), False), (_("Quantity"), True), (_("Unit cost"), True), (_("Value"), True)),
                  rows, foot, mode="none", note=_("Stock on hand today at FIFO cost."))


@require_perm("assets.view")
def asset_register(request):
    rows, foot = extra.fixed_asset_register(request.company)
    return _table(request, _("Fixed asset register"),
                  _cols((_("Asset number"), False), (_("Name"), False), (_("Category"), False), (_("Purchase date"), False),
                        (_("Status"), False), (_("Cost"), True), (_("Accumulated depreciation"), True), (_("Book value"), True)),
                  rows, foot, mode="none")


@require_perm("payroll.view")
def payroll_summary(request):
    date_from, date_to = _period(request)
    rows, foot = extra.payroll_summary(request.company, date_from, date_to)
    return _table(request, _("Payroll summary by employee"),
                  _cols((_("Code"), False), (_("Employee"), False), (_("Payslips"), True), (_("Gross pay"), True),
                        (_("Deductions"), True), (_("Net pay"), True)),
                  rows, foot, date_from=date_from, date_to=date_to, note=_("Payroll months that fall within the dates."))


@require_perm("reports.view")
def cash_forecast(request):
    from .forecast import cash_forecast as forecast

    return render(request, "reports/cash_forecast.html", {"fc": forecast(request.company, timezone.localdate())})


@require_perm("reports.view")
def cash_overview(request):
    from dashboard.services import cash_flow_block

    return render(request, "reports/cash_overview.html", {"flow": cash_flow_block(request.company, timezone.localdate())})


# ---------- Export any report page to Excel ----------
@require_perm("reports.export")
def export(request):
    """Runs the page at ?url= as this user (its own permission checks apply) and saves its tables as a workbook."""
    from urllib.parse import urlsplit

    from django.http import Http404, QueryDict
    from django.urls import Resolver404, resolve
    from django.utils.http import content_disposition_header

    from .xlsx import tables_to_workbook

    target = request.GET.get("url", "")
    parts = urlsplit(target)
    if not target.startswith("/") or target.startswith("//") or parts.netloc or parts.scheme:
        raise Http404
    try:
        match = resolve(parts.path)
    except Resolver404:
        raise Http404
    if match.func is export:
        raise Http404
    request.GET = QueryDict(parts.query)
    response = match.func(request, *match.args, **match.kwargs)
    if getattr(response, "status_code", 500) != 200 or "text/html" not in response.get("Content-Type", ""):
        return response
    if hasattr(response, "render"):
        response.render()
    data, title = tables_to_workbook(response.content.decode("utf-8"))
    out = HttpResponse(data, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    out["Content-Disposition"] = content_disposition_header(True, f"{title or 'report'}.xlsx")
    return out
