"""8-week cash forecast: today's cash plus what is due in and out each week. Used by the business feed's
"Cash falls below your minimum" warning and the Cash flow forecast page.

Counted: received cheques due (in the safe or under collection), unpaid invoices by due date, cheques you issued,
unpaid bills by due date (overdue bills fall in week 1) and payroll at each month end (last run's net pay).
Not counted: overdue customer invoices, because when they will be paid is unknown; they are shown separately."""
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum

ZERO = Decimal("0")


def _week_index(day, today, weeks):
    i = max((day - today).days, 0) // 7
    return i if i < weeks else None


def cash_forecast(company, today, weeks=8):
    from banking.models import Cheque
    from ledger.models import Account
    from ledger.services import balances
    from payroll.models import PayrollRun
    from purchases.models import Bill
    from sales.models import Invoice

    cash_accounts = list(Account.objects.filter(company=company, subtype__in=("bank", "cash"), is_group=False))
    opening = sum((d - c for d, c in balances(company, date_to=today, accounts=cash_accounts).values()), ZERO)
    rows = [{"start": today + timedelta(days=7 * i), "end": today + timedelta(days=7 * i + 6), "cheques_in": ZERO,
             "invoices": ZERO, "cheques_out": ZERO, "bills": ZERO, "payroll": ZERO} for i in range(weeks)]
    horizon = today + timedelta(days=7 * weeks - 1)

    for chq in Cheque.objects.filter(company=company, direction="in", status__in=("in_safe", "under_collection"),
                                     due_date__lte=horizon):
        rows[_week_index(chq.due_date, today, weeks)]["cheques_in"] += chq.base_amount
    for chq in Cheque.objects.filter(company=company, direction="out", status="issued", due_date__lte=horizon):
        rows[_week_index(chq.due_date, today, weeks)]["cheques_out"] += chq.base_amount
    overdue_in = ZERO
    for inv in Invoice.objects.filter(company=company, status="posted", due_date__lte=horizon).prefetch_related("lines__tax_rate"):
        due = inv.balance_due * inv.rate
        if due <= 0:
            continue
        if inv.due_date < today:
            overdue_in += due
        else:
            rows[_week_index(inv.due_date, today, weeks)]["invoices"] += due
    for bill in Bill.objects.filter(company=company, status="posted", due_date__lte=horizon).prefetch_related("lines__tax_rate"):
        due = bill.balance_due * bill.rate
        if due > 0:
            rows[_week_index(bill.due_date, today, weeks)]["bills"] += due

    last_run = PayrollRun.objects.filter(company=company).exclude(status="draft").first()
    net_pay = last_run.payslips.aggregate(n=Sum("net_pay"))["n"] or ZERO if last_run else ZERO
    if net_pay:
        paid = set(PayrollRun.objects.filter(company=company, status="paid").values_list("year", "month"))
        d = date(today.year, today.month, 1)
        while d <= horizon:
            end = date(d.year, d.month, monthrange(d.year, d.month)[1])
            if today <= end <= horizon and (d.year, d.month) not in paid:
                rows[_week_index(end, today, weeks)]["payroll"] += net_pay
            d = end + timedelta(days=1)

    minimum = company.minimum_cash
    balance, first_below = opening, None
    for r in rows:
        r["opening"] = balance
        r["money_in"] = r["cheques_in"] + r["invoices"]
        r["money_out"] = r["cheques_out"] + r["bills"] + r["payroll"]
        balance = balance + r["money_in"] - r["money_out"]
        r["closing"] = balance
        r["below"] = minimum is not None and balance < minimum
        if r["below"] and first_below is None:
            first_below = r
    return {"rows": rows, "opening": opening, "closing": balance, "minimum": minimum, "first_below": first_below,
            "overdue_in": overdue_in, "net_pay": net_pay,
            "chart": {"labels": [r["start"].isoformat() for r in rows], "balance": [float(r["closing"]) for r in rows],
                      "minimum": float(minimum) if minimum is not None else None}}
