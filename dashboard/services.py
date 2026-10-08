"""Numbers for the home page blocks, all read live from the ledger."""
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone
from django.utils.translation import gettext as _

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
    items = sorted(current["expense"], key=lambda x: x[1], reverse=True)
    top = [(a.name, v) for a, v in items[:4]]
    rest = sum((v for _a, v in items[4:]), ZERO)
    if rest:
        top.append((_("Other"), rest))
    total = current["total_expense"]
    change = float((total - prior["total_expense"]) / prior["total_expense"] * 100) if prior["total_expense"] else None
    return {"total": total, "items": top, "change": change}


def bank_block(company):
    rows, total = [], ZERO
    for acc in company.bank_accounts.filter(is_active=True).select_related("bank", "currency", "gl_account"):
        base = account_balance(acc.gl_account)
        own = base if acc.currency_id == company.base_currency_id else foreign_balance(acc.gl_account, acc.currency_id)
        total += base
        rows.append({"acc": acc, "own": own})
    return {"rows": rows, "total": total}


def cash_trend(company, today, weeks=12):
    cash_accounts = list(Account.objects.filter(company=company, subtype__in=("bank", "cash"), is_group=False))
    labels, values = [], []
    for i in range(weeks, -1, -1):
        day = today - timedelta(weeks=i)
        totals = balances(company, date_to=day, accounts=cash_accounts)
        values.append(float(sum((d - c for d, c in totals.values()), ZERO)))
        labels.append(day.isoformat())
    return {"labels": labels, "values": values, "today": values[-1] if values else 0}


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
    return {
        "tiles": [{"key": k, "label": label, "n": agg["n"] or 0, "a": agg["a"] or ZERO, "cls": cls} for k, label, agg, cls in tiles],
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
            "margin": sum((g["margin"] for g in groups), ZERO), "days": days}


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


def feed(company, user, today, approvals, cheques, extra=None):
    items = list(extra or [])
    if approvals:
        items.append(("var(--crit)", _("%(n)s documents are waiting for your approval") % {"n": len(approvals)}, "approvals:inbox", _("Review")))
    if cheques["due_week"]:
        items.append(("var(--warn)", _("%(n)s received cheques are due within 7 days") % {"n": cheques["due_week"]}, "banking:cheques", _("View")))
    if cheques["bounced"]:
        items.append(("var(--crit)", _("%(n)s cheques bounced this month") % {"n": cheques["bounced"]}, "banking:cheques", _("View")))
    rejected = Voucher.objects.filter(company=company, created_by=user, status="rejected").count()
    if rejected:
        items.append(("var(--crit)", _("%(n)s of your vouchers were rejected and need changes") % {"n": rejected}, "vouchers:list", _("Fix")))
    drafts = Voucher.objects.filter(company=company, created_by=user, status="draft").count()
    if drafts:
        items.append(("var(--brand)", _("You have %(n)s draft vouchers") % {"n": drafts}, "vouchers:list", _("Open")))
    missing = [c.code for c in company.currencies.exclude(code=company.base_currency_id)
               if not ExchangeRate.objects.filter(company=company, currency=c, date=today).exists()]
    if missing:
        items.append(("var(--warn)", _("No exchange rate saved for today: %(codes)s") % {"codes": ", ".join(missing)}, "core:settings", _("Add")))
    return items


def build(company, user, membership):
    from core.models import RecurringTemplate

    today = timezone.localdate()
    can = membership.has_perm
    approvals = pending_for(user, company) if can("vouchers.approve") else []
    cheques = cheques_block(company, today)
    hour = timezone.localtime().hour
    data = {
        "greeting": _("Good morning") if hour < 12 else _("Good afternoon") if hour < 17 else _("Good evening"),
        "pl": profit_block(company, today),
        "exp": expenses_block(company, today),
        "bank": bank_block(company),
        "trend": cash_trend(company, today),
        "approvals": approvals[:5],
        "approvals_count": len(approvals),
        "cheques": cheques,
        "year": today.year,
    }
    extra = []
    if can("sales.view"):
        data.update(sales=sales_block(company, today), invoices=invoices_block(company, today),
                    ar=receivables_block(company, today), orders=orders_block(company))
        if data["invoices"]["n_overdue"]:
            extra.append(("var(--crit)", _("%(n)s invoices are overdue") % {"n": data["invoices"]["n_overdue"]},
                          "reports:ar_aging", _("Chase")))
    if can("purchases.view"):
        data["ap"] = payables_block(company, today)
    if can("inventory.view"):
        data["stock"] = stock_block(company, today)
        if data["stock"]["expired"]:
            extra.append(("var(--crit)", _("%(n)s batches in stock have expired") % {"n": len(data["stock"]["expired"])},
                          "inventory:expiry", _("Write off")))
        if data["stock"]["low_count"]:
            extra.append(("var(--warn)", _("%(n)s products are at or below their reorder level") % {
                "n": data["stock"]["low_count"]}, "inventory:overview", _("Reorder")))
    if can("payroll.approve") or can("payroll.authorise"):
        from payroll.models import PayrollRun
        waiting = PayrollRun.objects.filter(company=company, status__in=(
            ["prepared"] if can("payroll.approve") else []) + (["approved"] if can("payroll.authorise") else [])).count()
        if waiting:
            extra.append(("var(--crit)", _("A payroll run is waiting for your sign-off"), "payroll:runs", _("Review")))
    if can("vouchers.create"):
        due = RecurringTemplate.objects.filter(company=company, is_active=True, next_date__lte=today).count()
        if due:
            extra.append(("var(--brand)", _("%(n)s recurring transactions are due") % {"n": due}, "core:recurring", _("Create")))
    data["feed"] = feed(company, user, today, approvals, cheques, extra)
    return data
