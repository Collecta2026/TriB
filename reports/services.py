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


def vat_return(company, date_from, date_to):
    """VAT for a period: documents by rate, and the ledger movement that is actually payable or refundable."""
    from ledger.services import system_account
    from purchases.models import BillLine
    from sales.models import InvoiceLine

    def by_rate(lines, doc):
        rows = {}
        for l in lines:
            parent = getattr(l, doc)
            key = l.tax_rate_id
            row = rows.setdefault(key, {"rate": l.tax_rate, "net": ZERO, "tax": ZERO, "docs": set()})
            row["net"] += (l.net * parent.rate).quantize(Decimal("0.01"))
            row["tax"] += (l.tax * parent.rate).quantize(Decimal("0.01"))
            row["docs"].add(parent.pk)
        out = sorted(rows.values(), key=lambda r: -(r["rate"].rate if r["rate"] else Decimal("-1")))
        for r in out:
            r["docs"] = len(r["docs"])
        return out

    period = dict(date__gte=date_from, date__lte=date_to, status="posted", company=company)
    sales = by_rate(InvoiceLine.objects.filter(**{f"document__{k}": v for k, v in period.items()})
                    .select_related("document", "tax_rate"), "document")
    purchases = by_rate(BillLine.objects.filter(**{f"document__{k}": v for k, v in period.items()})
                        .select_related("document", "tax_rate"), "document")
    out_acc, in_acc = system_account(company, "vat_output"), system_account(company, "vat_input")
    moves = balances(company, date_from=date_from, date_to=date_to, accounts=[out_acc, in_acc])
    od, oc = moves.get(out_acc.id, (ZERO, ZERO))
    idr, icr = moves.get(in_acc.id, (ZERO, ZERO))
    output_vat, input_vat = oc - od, idr - icr
    return {"sales": sales, "purchases": purchases, "output_vat": output_vat, "input_vat": input_vat,
            "net": output_vat - input_vat, "out_account": out_acc, "in_account": in_acc,
            "sales_tax": sum((r["tax"] for r in sales), ZERO), "purchase_tax": sum((r["tax"] for r in purchases), ZERO)}


def sales_by_item(company, date_from, date_to):
    """Posted sales grouped by category then product: quantity, revenue, cost and margin in base currency."""
    from sales.models import InvoiceLine

    groups = {}
    lines = InvoiceLine.objects.filter(document__company=company, document__status="posted",
                                       document__date__gte=date_from, document__date__lte=date_to) \
        .select_related("document", "item", "item__category")
    for l in lines:
        item = l.item
        cat = item.category if item and item.category_id else None
        group = groups.setdefault(cat.pk if cat else 0, {"category": cat, "items": {}, "qty": ZERO, "revenue": ZERO,
                                                          "cost": ZERO})
        key = item.pk if item else f"d:{l.description[:60]}"
        row = group["items"].setdefault(key, {"item": item, "label": l.label, "qty": ZERO, "revenue": ZERO, "cost": ZERO})
        revenue = (l.net * l.document.rate).quantize(Decimal("0.01"))
        for target in (row, group):
            target["qty"] += l.qty
            target["revenue"] += revenue
            target["cost"] += l.cost or ZERO
    out = []
    for g in sorted(groups.values(), key=lambda g: -g["revenue"]):
        g["items"] = sorted(g["items"].values(), key=lambda r: -r["revenue"])
        for r in g["items"] + [g]:
            r["margin"] = r["revenue"] - r["cost"]
        out.append(g)
    return out
