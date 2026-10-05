from datetime import timedelta
from decimal import Decimal

from ledger.models import Account, JournalLine
from ledger.services import balances

ZERO = Decimal("0")


def trial_balance(company, date_from, date_to):
    accounts = Account.objects.filter(company=company, is_group=False).order_by("code")
    opening = balances(company, date_to=date_from - timedelta(days=1))
    period = balances(company, date_from=date_from, date_to=date_to)
    rows, totals = [], dict(od=ZERO, oc=ZERO, pd=ZERO, pc=ZERO, cd=ZERO, cc=ZERO)
    for a in accounts:
        o_d, o_c = opening.get(a.id, (ZERO, ZERO))
        p_d, p_c = period.get(a.id, (ZERO, ZERO))
        if not any((o_d, o_c, p_d, p_c)):
            continue
        o_net, c_net = o_d - o_c, o_d - o_c + p_d - p_c
        row = {
            "account": a,
            "od": max(o_net, ZERO), "oc": max(-o_net, ZERO),
            "pd": p_d, "pc": p_c,
            "cd": max(c_net, ZERO), "cc": max(-c_net, ZERO),
        }
        for k in totals:
            totals[k] += row[k]
        rows.append(row)
    return rows, totals


def statement(account, date_from, date_to):
    before = balances(account.company, date_to=date_from - timedelta(days=1), accounts=[account]).get(account.id, (ZERO, ZERO))
    sign = 1 if account.debit_nature else -1
    running = (before[0] - before[1]) * sign
    opening = running
    rows = []
    lines = (
        JournalLine.objects.filter(account=account, entry__date__gte=date_from, entry__date__lte=date_to)
        .select_related("entry", "currency").order_by("entry__date", "entry_id", "id")
    )
    for line in lines:
        running += (line.debit - line.credit) * sign
        rows.append({"line": line, "balance": running})
    return opening, rows, running


def profit_and_loss(company, date_from, date_to):
    period = balances(company, date_from=date_from, date_to=date_to)
    income, expense = [], []
    for a in Account.objects.filter(company=company, is_group=False, type__in=("income", "expense")).order_by("code"):
        d, c = period.get(a.id, (ZERO, ZERO))
        if not d and not c:
            continue
        if a.type == "income":
            income.append((a, c - d))
        else:
            expense.append((a, d - c))
    total_income = sum((v for _a, v in income), ZERO)
    total_expense = sum((v for _a, v in expense), ZERO)
    return {"income": income, "expense": expense, "total_income": total_income, "total_expense": total_expense,
            "net": total_income - total_expense}


def balance_sheet(company, as_of):
    totals = balances(company, date_to=as_of)
    sections = {"asset": [], "liability": [], "equity": []}
    earnings = ZERO
    for a in Account.objects.filter(company=company, is_group=False).order_by("code"):
        d, c = totals.get(a.id, (ZERO, ZERO))
        if a.type == "income":
            earnings += c - d
        elif a.type == "expense":
            earnings -= d - c
        elif d or c:
            sections[a.type].append((a, d - c if a.type == "asset" else c - d))
    total_assets = sum((v for _a, v in sections["asset"]), ZERO)
    total_liabilities = sum((v for _a, v in sections["liability"]), ZERO)
    total_equity = sum((v for _a, v in sections["equity"]), ZERO) + earnings
    return {**sections, "earnings": earnings, "total_assets": total_assets, "total_liabilities": total_liabilities,
            "total_equity": total_equity, "total_liabilities_equity": total_liabilities + total_equity,
            "check": total_assets - total_liabilities - total_equity}
