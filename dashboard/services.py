"""Numbers for the home page blocks, all read live from the ledger."""
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from approvals.services import pending_for
from banking.models import Cheque
from core.models import ExchangeRate
from ledger.models import Account
from ledger.services import account_balance, balances, foreign_balance
from reports.services import profit_and_loss
from vouchers.models import Voucher

ZERO = Decimal("0")


def _pending_vouchers(company, kind):
    rows = Voucher.objects.filter(company=company, kind=kind, status__in=("draft", "submitted", "approved")).prefetch_related("lines")
    return len(rows), sum((v.amount_base for v in rows), ZERO)


def profit_block(company, today):
    start = date(today.year, 1, 1)
    pl = profit_and_loss(company, start, today)
    rec_n, rec_amt = _pending_vouchers(company, "receipt")
    pay_n, pay_amt = _pending_vouchers(company, "payment")
    inc, exp = pl["total_income"], pl["total_expense"]
    scale = max(inc + rec_amt, exp + pay_amt, Decimal("1"))

    def bar(posted, pending):
        width = (posted + pending) / scale * 100
        total = posted + pending or Decimal("1")
        return {"width": float(width), "solid": float(posted / total * 100), "hatch": float(pending / total * 100)}

    return {
        "income": inc, "expense": exp, "net": pl["net"],
        "margin": float(pl["net"] / inc * 100) if inc else None,
        "income_bar": bar(inc, rec_amt), "expense_bar": bar(exp, pay_amt),
        "income_review": rec_n, "expense_review": pay_n,
    }


def expenses_block(company, today):
    start, prior_start = today - timedelta(days=29), today - timedelta(days=59)
    current = profit_and_loss(company, start, today)
    prior = profit_and_loss(company, prior_start, start - timedelta(days=1))
    from django.urls import reverse

    period = f"from={start:%Y-%m-%d}&to={today:%Y-%m-%d}"
    items = sorted(current["expense"], key=lambda x: x[1], reverse=True)
    top = [(a.name, v, f"{reverse('reports:statement')}?account={a.pk}&{period}") for a, v in items[:4]]
    rest = sum((v for _a, v in items[4:]), ZERO)
    detail = f"{reverse('reports:pl_detail')}?{period}"
    if rest:
        top.append((_("Other"), rest, detail))
    total = current["total_expense"]
    change = float((total - prior["total_expense"]) / prior["total_expense"] * 100) if prior["total_expense"] else None
    return {"total": total, "items": top, "change": change, "url": detail}


def bank_block(company):
    rows, total = [], ZERO
    for acc in company.bank_accounts.filter(is_active=True).select_related("bank", "currency", "gl_account"):
        base = account_balance(acc.gl_account)
        own = base if acc.currency_id == company.base_currency_id else foreign_balance(acc.gl_account, acc.currency_id)
        total += base
        rows.append({"acc": acc, "own": own})
    return {"rows": rows, "total": total}


def cash_flow_block(company, today, months=12):
    """Cash and bank over the last 12 months: month-end balance, money in and money out. Moves between your own
    accounts (transfers, deposits) cancel out within one entry, so they count as neither in nor out."""
    from django.urls import reverse

    from ledger.models import JournalLine
    from reports.extra import month_end

    cash_accounts = list(Account.objects.filter(company=company, subtype__in=("bank", "cash"), is_group=False))
    start = date(today.year, today.month, 1)
    for _i in range(months - 1):
        start = date(start.year - (start.month == 1), (start.month - 2) % 12 + 1, 1)
    opening = balances(company, date_to=start - timedelta(days=1), accounts=cash_accounts)
    balance = sum((d - c for d, c in opening.values()), ZERO)
    per_entry = (JournalLine.objects.filter(account__in=cash_accounts, entry__date__gte=start, entry__date__lte=today)
                 .values("entry_id", "entry__date").annotate(d=Sum("debit"), c=Sum("credit")))
    flows = {}
    for e in per_entry:
        key = e["entry__date"].replace(day=1)
        net = e["d"] - e["c"]
        f = flows.setdefault(key, [ZERO, ZERO])
        if net > 0:
            f[0] += net
        else:
            f[1] -= net
    rows, m = [], start
    for _i in range(months):
        money_in, money_out = flows.get(m, [ZERO, ZERO])
        balance += money_in - money_out
        end = min(month_end(m), today)
        rows.append({"month": m, "in": money_in, "out": money_out, "balance": balance,
                     "url": f"{reverse('reports:cash_flows')}?from={m:%Y-%m-%d}&to={end:%Y-%m-%d}"})
        m = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
    return {
        "rows": rows, "today": balance,
        "money_in": sum((r["in"] for r in rows), ZERO), "money_out": sum((r["out"] for r in rows), ZERO),
        "chart": {"labels": [r["month"].isoformat() for r in rows], "balance": [float(r["balance"]) for r in rows],
                  "in": [float(r["in"]) for r in rows], "out": [float(r["out"]) for r in rows],
                  "urls": [r["url"] for r in rows]},
    }


def cheques_block(company, today):
    received = Cheque.objects.filter(company=company, direction="in")
    open_ = received.filter(status__in=("in_safe", "under_collection"))
    month_start = today.replace(day=1)
    tiles = [
        ("in_safe", _("In the safe"), open_.filter(status="in_safe").aggregate(n=Count("id"), a=Sum("amount")), ""),
        ("under_collection", _("Under collection"), open_.filter(status="under_collection").aggregate(n=Count("id"), a=Sum("amount")), ""),
        ("week", _("Due this week"), open_.filter(due_date__lte=today + timedelta(days=7)).aggregate(n=Count("id"), a=Sum("amount")), "warn"),
        ("bounced", _("Bounced this month"), received.filter(status="bounced", bounced_on__gte=month_start).aggregate(n=Count("id"), a=Sum("amount")), "crit"),
    ]
    from django.urls import reverse

    base = reverse("banking:cheques")
    urls = {"in_safe": f"{base}?status=in_safe", "under_collection": f"{base}?status=under_collection",
            "week": f"{base}?due=7", "bounced": f"{base}?status=bounced&bounced=month"}
    return {
        "tiles": [{"key": k, "label": label, "n": agg["n"] or 0, "a": agg["a"] or ZERO, "cls": cls, "url": urls[k]}
                  for k, label, agg, cls in tiles],
        "next": open_.order_by("due_date").select_related("currency")[:3],
        "due_week": tiles[2][2]["n"] or 0, "due_week_amount": tiles[2][2]["a"] or ZERO,
        "bounced": tiles[3][2]["n"] or 0,
    }


def sales_block(company, today, days=90):
    """Sales of the last 90 days by category (machines, supplies…) and the best-selling products — a list, not a graph."""
    from reports.services import sales_by_item

    groups = sales_by_item(company, today - timedelta(days=days), today)
    items = sorted((r for g in groups for r in g["items"]), key=lambda r: -r["revenue"])[:6]
    total = sum((g["revenue"] for g in groups), ZERO)
    return {"groups": groups[:6], "top": items, "total": total,
            "margin": sum((g["margin"] for g in groups), ZERO), "days": days, "from": today - timedelta(days=days)}


def invoices_block(company, today):
    from sales.models import Invoice

    unpaid = overdue = paid30 = ZERO
    n_overdue = 0
    for inv in Invoice.objects.filter(company=company, status="posted", date__gte=today - timedelta(days=365)):
        due = inv.balance_due * inv.rate
        unpaid += due
        if due > 0 and inv.due_date < today:
            overdue += due
            n_overdue += 1
    from sales.models import CustomerPayment
    for p in CustomerPayment.objects.filter(company=company, status="posted", date__gte=today - timedelta(days=29)):
        paid30 += p.amount * p.rate
    return {"unpaid": unpaid, "overdue": overdue, "not_due": unpaid - overdue, "n_overdue": n_overdue, "paid30": paid30,
            "paid_from": today - timedelta(days=29),
            "overdue_pct": float(overdue / unpaid * 100) if unpaid else 0}


def receivables_block(company, today):
    from sales.services import AGING_BUCKETS, ar_aging

    rows = ar_aging(company, today)
    buckets = [sum((r["buckets"][i] for r in rows), ZERO) for i in range(5)]
    total = sum(buckets, ZERO)
    colors = ["var(--good)", "var(--c2)", "var(--warn)", "var(--c4)", "var(--crit)"]
    return {"total": total, "customers": len(rows), "top": rows[:4],
            "buckets": [{"label": label, "amount": amt, "color": colors[i],
                         "pct": float(amt / total * 100) if total > 0 and amt > 0 else 0}
                        for i, ((_d, label), amt) in enumerate(zip(AGING_BUCKETS, buckets))]}


def payables_block(company, today):
    from purchases.services import ap_aging

    rows = ap_aging(company, today)
    total = sum((r["total"] for r in rows), ZERO)
    overdue = sum((sum(r["buckets"][1:], ZERO) for r in rows), ZERO)
    return {"total": total, "overdue": overdue, "top": rows[:4]}


def orders_block(company):
    from sales.models import SalesOrder

    orders = list(SalesOrder.objects.filter(company=company, status__in=("open", "partial"))
                  .select_related("customer").order_by("date")[:6])
    total = SalesOrder.objects.filter(company=company, status__in=("open", "partial")).count()
    return {"rows": [{"o": o, "open": sum((l.qty_open * l.unit_price * (1 - l.discount_pct / 100) for l in o.lines.all()),
                                          ZERO)} for o in orders], "count": total}


def stock_block(company, today):
    from inventory.models import Item
    from inventory.services import batches_on_hand, stock_summary

    summary = stock_summary(company)
    on_hand = {i.id: q for i, q, _v in summary}
    low = [(i, on_hand.get(i.id, ZERO)) for i in Item.objects.filter(company=company, type="inventory", is_active=True,
                                                                         reorder_level__gt=0)
           if on_hand.get(i.id, ZERO) <= i.reorder_level]
    batches = batches_on_hand(company, expiring_within=90, today=today)
    return {"value": sum((v for _i, _q, v in summary), ZERO), "low": low[:4], "low_count": len(low),
            "expired": [b for b in batches if b["state"] == "expired"], "soon": [b for b in batches if b["state"] == "soon"]}


def _money(amount, company):
    return f"{company.base_currency_id} {amount:,.0f}"


def _card(tone, icon, title, text, url, action, rows=None):
    return {"tone": tone, "icon": icon, "title": title, "text": text, "url": url, "action": action, "rows": rows or []}


def alerts(company, user, membership, today=None, approvals=None):
    """Business feed cards (also the bell's alerts): approvals first, then what needs attention, then good news.
    Each card links to the exact filtered list behind it."""
    from django.urls import reverse

    from core.models import RecurringTemplate

    today = today or timezone.localdate()
    can = membership.has_perm
    cards = []
    if approvals is None:
        approvals = pending_for(user, company) if can("vouchers.approve") else []
    if approvals:
        rows = [{"label": f"{r.voucher.get_kind_display()} · {r.voucher.number}",
                 "sub": r.voucher.party_name or r.voucher.description, "amount": r.voucher.total,
                 "currency": r.voucher.currency, "url": reverse("vouchers:detail", args=[r.voucher.pk]),
                 "approve": reverse("vouchers:action", args=[r.voucher.pk])} for r in approvals[:3]]
        cards.append(_card("crit", "shield", _("Approvals"),
                           _("%(n)s documents are waiting for your approval") % {"n": len(approvals)},
                           reverse("approvals:inbox"), _("Review all"), rows))
    if can("payroll.approve") or can("payroll.authorise"):
        from payroll.models import PayrollRun
        waiting = PayrollRun.objects.filter(company=company, status__in=(
            ["prepared"] if can("payroll.approve") else []) + (["approved"] if can("payroll.authorise") else [])).count()
        if waiting:
            cards.append(_card("crit", "payroll", _("Payroll"), _("A payroll run is waiting for your sign-off"),
                               reverse("payroll:runs"), _("Review")))
    if can("sales.view"):
        from sales.models import CustomerPayment, Invoice
        overdue = [i for i in Invoice.objects.filter(company=company, status="posted", due_date__lt=today)
                   .prefetch_related("lines__tax_rate") if i.balance_due > 0]
        if overdue:
            amount = sum((i.balance_due * i.rate for i in overdue), ZERO)
            cards.append(_card("crit", "sales", _("Overdue invoices"), _("%(n)s invoices are overdue · %(a)s") % {
                "n": len(overdue), "a": _money(amount, company)}, f"{reverse('sales:invoices')}?pay=overdue", _("Chase")))
        week = CustomerPayment.objects.filter(company=company, status="posted", date__gte=today - timedelta(days=6))
        agg = week.aggregate(n=Count("id"))
        if agg["n"]:
            total = sum((p.amount * p.rate for p in week), ZERO)
            cards.append(_card("good", "wallet", _("Customer payments"),
                               _("%(n)s payments received in the last 7 days, %(a)s in total") % {
                                   "n": agg["n"], "a": f"{total:,.0f} {company.base_currency_id}"},
                               f"{reverse('sales:payments')}?from={today - timedelta(days=6):%Y-%m-%d}", _("View")))
    if can("purchases.view"):
        from purchases.models import Bill
        due = [b for b in Bill.objects.filter(company=company, status="posted", due_date__lte=today + timedelta(days=7))
               .prefetch_related("lines__tax_rate") if b.balance_due > 0]
        if due:
            amount = sum((b.balance_due * b.rate for b in due), ZERO)
            cards.append(_card("warn", "wallet", _("Bills to pay"), _("%(n)s bills due within 7 days or overdue · %(a)s") % {
                "n": len(due), "a": _money(amount, company)}, f"{reverse('purchases:bills')}?pay=due7", _("Pay bills")))
    if can("cheques.view"):
        received = Cheque.objects.filter(company=company, direction="in")
        week = list(received.filter(status__in=("in_safe", "under_collection"), due_date__lte=today + timedelta(days=7)))
        if week:
            cards.append(_card("warn", "cheque", _("Cheques due"), _("%(n)s cheques due this week · %(a)s") % {
                "n": len(week), "a": _money(sum((c.base_amount for c in week), ZERO), company)},
                f"{reverse('banking:cheques')}?due=7", _("View")))
        bounced = received.filter(status="bounced", bounced_on__gte=today.replace(day=1)).count()
        if bounced:
            cards.append(_card("crit", "cheque", _("Returned cheques"), _("%(n)s cheques bounced this month") % {"n": bounced},
                               f"{reverse('banking:cheques')}?status=bounced&bounced=month", _("View")))
    if can("inventory.view"):
        from inventory.services import batches_on_hand
        batches = batches_on_hand(company, expiring_within=60, today=today)
        expired = sum(1 for b in batches if b["state"] == "expired")
        soon = len(batches) - expired
        if batches:
            cards.append(_card("crit" if expired else "warn", "box", _("Stock expiry"),
                               _("%(soon)s batches expire within 60 days, %(n)s expired") % {"soon": soon, "n": expired},
                               f"{reverse('inventory:expiry')}?within={'expired' if expired and not soon else '60'}", _("View")))
    if company.minimum_cash is not None and can("reports.view"):
        from reports.forecast import cash_forecast
        fc = cash_forecast(company, today)
        if fc["first_below"]:
            cards.insert(1 if cards and cards[0]["icon"] == "shield" else 0, _card(
                "warn", "trend", _("Cash forecast"), _("Cash falls below your %(m)s minimum in the week of %(d)s") % {
                    "m": _money(company.minimum_cash, company), "d": f"{fc['first_below']['start']:%d/%m}"},
                reverse("reports:cash_forecast"), _("See forecast")))
    rejected = Voucher.objects.filter(company=company, created_by=user, status="rejected").count()
    if rejected:
        cards.append(_card("crit", "alert", _("Rejected vouchers"),
                           _("%(n)s of your vouchers were rejected and need changes") % {"n": rejected},
                           f"{reverse('vouchers:list')}?status=rejected", _("Fix")))
    drafts = Voucher.objects.filter(company=company, created_by=user, status="draft").count()
    if drafts:
        cards.append(_card("brand", "file", _("Drafts"), _("You have %(n)s draft vouchers") % {"n": drafts},
                           f"{reverse('vouchers:list')}?status=draft", _("Open")))
    if can("vouchers.create"):
        due = RecurringTemplate.objects.filter(company=company, is_active=True, next_date__lte=today).count()
        if due:
            cards.append(_card("brand", "list", _("Recurring transactions"),
                               _("%(n)s recurring transactions are due") % {"n": due}, reverse("core:recurring"), _("Create")))
    missing = [c.code for c in company.currencies.exclude(code=company.base_currency_id)
               if not ExchangeRate.objects.filter(company=company, currency=c, date=today).exists()]
    if missing:
        cards.append(_card("warn", "percent", _("Exchange rates"),
                           _("No exchange rate saved for today: %(codes)s") % {"codes": ", ".join(missing)},
                           reverse("core:settings"), _("Add")))
    return cards


# Home page widgets: key, title, default width (of 4 columns), permission needed (None = everyone).
WIDGETS = [
    ("cashflow", gettext_lazy("Cash flow"), 2, None),
    ("pl", gettext_lazy("Profit & loss"), 1, None),
    ("bank", gettext_lazy("Bank accounts"), 1, None),
    ("invoices", gettext_lazy("Invoices"), 1, "sales.view"),
    ("expenses", gettext_lazy("Expenses"), 1, None),
    ("ar", gettext_lazy("Accounts receivable"), 1, "sales.view"),
    ("ap", gettext_lazy("Accounts payable"), 1, "purchases.view"),
    ("sales", gettext_lazy("Sales"), 2, "sales.view"),
    ("orders", gettext_lazy("Customer orders"), 1, "sales.view"),
    ("stock", gettext_lazy("Stock alerts"), 1, "inventory.view"),
    ("cheques", gettext_lazy("Post-dated cheques"), 1, None),
]
WIDGET_KEYS = [w[0] for w in WIDGETS]


def layout_for(saved, membership):
    """The user's saved order, widths and hidden widgets, plus any widget added since (shown at the end)."""
    available = {key: (title, width) for key, title, width, perm in WIDGETS if perm is None or membership.has_perm(perm)}
    out, seen = [], set()
    for w in saved or []:
        key = w.get("key") if isinstance(w, dict) else None
        if key in available and key not in seen:
            seen.add(key)
            width = w.get("w") if isinstance(w.get("w"), int) else available[key][1]
            out.append({"key": key, "title": available[key][0], "w": max(1, min(4, width)), "hidden": bool(w.get("hidden"))})
    for key, (title, width) in available.items():
        if key not in seen:
            out.append({"key": key, "title": title, "w": width, "hidden": False})
    return out


def clean_layout(posted):
    """Validate a layout sent from the Customise screen."""
    out, seen = [], set()
    for w in posted if isinstance(posted, list) else []:
        if not isinstance(w, dict) or w.get("key") not in WIDGET_KEYS or w["key"] in seen:
            continue
        seen.add(w["key"])
        width = w.get("w")
        out.append({"key": w["key"], "w": max(1, min(4, width)) if isinstance(width, int) else 1,
                    "hidden": bool(w.get("hidden"))})
    return out


def build(company, user, membership):
    from core.models import UserPreference

    today = timezone.localdate()
    can = membership.has_perm
    pref = UserPreference.for_user(user, company)
    widgets = layout_for(pref.dashboard_layout, membership)
    keys = {w["key"] for w in widgets}
    approvals = pending_for(user, company) if can("vouchers.approve") else []
    hour = timezone.localtime().hour
    data = {
        "greeting": _("Good morning") if hour < 12 else _("Good afternoon") if hour < 17 else _("Good evening"),
        "widgets": widgets, "year": today.year, "today": today,
        "feed_all": alerts(company, user, membership, today, approvals),
    }
    data["feed"] = data["feed_all"][:6]
    if "pl" in keys:
        data["pl"] = profit_block(company, today)
    if "expenses" in keys:
        data["exp"] = expenses_block(company, today)
    if "bank" in keys or "cashflow" in keys:
        data["bank"] = bank_block(company)
    if "cashflow" in keys:
        data["flow"] = cash_flow_block(company, today)
    if "cheques" in keys:
        data["cheques"] = cheques_block(company, today)
    if "sales" in keys:
        data["sales"] = sales_block(company, today)
    if "invoices" in keys:
        data["invoices"] = invoices_block(company, today)
    if "ar" in keys:
        data["ar"] = receivables_block(company, today)
    if "orders" in keys:
        data["orders"] = orders_block(company)
    if "ap" in keys:
        data["ap"] = payables_block(company, today)
    if "stock" in keys:
        data["stock"] = stock_block(company, today)
    return data
