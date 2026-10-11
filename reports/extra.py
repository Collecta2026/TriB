"""The QuickBooks standard reports TriB did not have yet. Each returns plain rows for reports/table.html:
{"cells": [...], "cls": "grp" | "sub" | "tot" | "", "url": optional link for the first cell, "indent": 0-3}."""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from ledger.models import Account, JournalEntry, JournalLine
from ledger.services import balances

from .services import ZERO, balance_sheet, profit_and_loss

CENT = Decimal("0.01")


def r2(v):
    return Decimal(v).quantize(CENT)


def row(cells, cls="", url=None, indent=0):
    return {"cells": list(cells), "cls": cls, "url": url, "indent": indent}


def month_starts(date_from, date_to, limit=24):
    out, d = [], date(date_from.year, date_from.month, 1)
    while d <= date_to and len(out) < limit:
        out.append(d)
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return out


def month_end(d):
    return date(d.year + (d.month == 12), d.month % 12 + 1, 1) - timedelta(days=1)


def statement_url(account, date_from, date_to):
    return f"{reverse('reports:statement')}?account={account.pk}&from={date_from:%Y-%m-%d}&to={date_to:%Y-%m-%d}"


def compare_period(date_from, date_to, how):
    """The period to compare with: the one just before, or the same dates last year."""
    if how == "previous_year":
        def back(d):
            try:
                return d.replace(year=d.year - 1)
            except ValueError:  # 29 February
                return d.replace(year=d.year - 1, day=28)
        return back(date_from), back(date_to)
    length = (date_to - date_from).days
    end = date_from - timedelta(days=1)
    return end - timedelta(days=length), end


# ---------- Business overview ----------
def account_list(company, as_of):
    totals = balances(company, date_to=as_of)
    rows = []
    for a in Account.objects.filter(company=company).order_by("code"):
        d, c = totals.get(a.id, (ZERO, ZERO))
        bal = (d - c) if a.debit_nature else (c - d)
        rows.append(row([f"{a.code} · {a.name}", a.get_type_display(), a.get_subtype_display() if a.subtype else "",
                         None if a.is_group else bal],
                        cls="grp" if a.is_group else "", indent=min(a.depth, 3),
                        url=None if a.is_group else statement_url(a, date(as_of.year, 1, 1), as_of)))
    return rows


def pl_compare(company, date_from, date_to, how):
    c_from, c_to = compare_period(date_from, date_to, how)
    now, then = profit_and_loss(company, date_from, date_to), profit_and_loss(company, c_from, c_to)
    rows = []

    def change(a, b):
        return [a, b, a - b, (r2((a - b) / abs(b) * 100) if b else None)]

    for key, title, total_key, total_label in (("income", _("Income"), "total_income", _("Total income")),
                                               ("expense", _("Expenses"), "total_expense", _("Total expenses"))):
        rows.append(row([title, None, None, None, None], cls="grp"))
        before = {a.id: v for a, v in then[key]}
        accounts = {a.id: a for a, _v in now[key] + then[key]}
        current = {a.id: v for a, v in now[key]}
        for aid in sorted(accounts, key=lambda i: accounts[i].code):
            a = accounts[aid]
            rows.append(row([f"{a.code} · {a.name}"] + change(current.get(aid, ZERO), before.get(aid, ZERO)),
                            indent=1, url=statement_url(a, date_from, date_to)))
        rows.append(row([total_label] + change(now[total_key], then[total_key]), cls="sub"))
    foot = [_("Net profit")] + change(now["net"], then["net"])
    return rows, foot, (c_from, c_to)


def pl_by_month(company, date_from, date_to):
    months = month_starts(date_from, date_to)
    per = [profit_and_loss(company, max(m, date_from), min(month_end(m), date_to)) for m in months]
    rows = []
    for key, title, total_label in (("income", _("Income"), _("Total income")), ("expense", _("Expenses"), _("Total expenses"))):
        rows.append(row([title] + [None] * (len(months) + 1), cls="grp"))
        accounts = {}
        for p in per:
            for a, _v in p[key]:
                accounts[a.id] = a
        for aid in sorted(accounts, key=lambda i: accounts[i].code):
            vals = [dict((a.id, v) for a, v in p[key]).get(aid, ZERO) for p in per]
            rows.append(row([f"{accounts[aid].code} · {accounts[aid].name}"] + vals + [sum(vals, ZERO)], indent=1,
                            url=statement_url(accounts[aid], date_from, date_to)))
        totals = [p["total_" + key] for p in per]
        rows.append(row([total_label] + totals + [sum(totals, ZERO)], cls="sub"))
    nets = [p["net"] for p in per]
    return months, rows, [_("Net profit")] + nets + [sum(nets, ZERO)]


def pl_by_customer(company, date_from, date_to):
    from sales.models import CreditNoteLine, InvoiceLine

    data = defaultdict(lambda: {"income": ZERO, "cost": ZERO})
    period = dict(document__company=company, document__status="posted", document__date__gte=date_from,
                  document__date__lte=date_to)
    for l in InvoiceLine.objects.filter(**period).select_related("document__customer"):
        d = data[l.document.customer]
        d["income"] += r2(l.net * l.document.rate)
        d["cost"] += l.cost or ZERO
    for l in CreditNoteLine.objects.filter(**period).select_related("document__customer"):
        d = data[l.document.customer]
        d["income"] -= r2(l.net * l.document.rate)
        d["cost"] -= (l.cost or ZERO) if l.return_to_stock else ZERO
    rows, tot = [], {"income": ZERO, "cost": ZERO}
    for cust, d in sorted(data.items(), key=lambda kv: -kv[1]["income"]):
        gp = d["income"] - d["cost"]
        rows.append(row([cust.name, d["income"], d["cost"], gp, r2(gp / d["income"] * 100) if d["income"] else None],
                        url=reverse("contacts:customer", args=[cust.pk])))
        tot["income"] += d["income"]
        tot["cost"] += d["cost"]
    gp = tot["income"] - tot["cost"]
    return rows, [_("Total"), tot["income"], tot["cost"], gp, r2(gp / tot["income"] * 100) if tot["income"] else None]


def _source_label(entry):
    return entry.get_source_display()


def ledger_detail(company, date_from, date_to, accounts, running=True):
    """General ledger style: per account an opening line, every posting and the closing balance."""
    opening = balances(company, date_to=date_from - timedelta(days=1), accounts=accounts)
    lines = (JournalLine.objects.filter(account__in=accounts, entry__date__gte=date_from, entry__date__lte=date_to)
             .select_related("entry", "account").order_by("account__code", "entry__date", "entry_id", "id"))
    by_account = defaultdict(list)
    for l in lines:
        by_account[l.account_id].append(l)
    rows = []
    for a in accounts:
        od, oc = opening.get(a.id, (ZERO, ZERO))
        if not by_account.get(a.id) and not (od - oc):
            continue
        sign = 1 if a.debit_nature else -1
        bal = (od - oc) * sign
        rows.append(row([f"{a.code} · {a.name}", "", "", "", None, None, None], cls="grp",
                        url=statement_url(a, date_from, date_to)))
        rows.append(row([date_from - timedelta(days=1), _("Opening balance"), "", "", None, None, bal], indent=1))
        dr = cr = ZERO
        for l in by_account.get(a.id, []):
            bal += (l.debit - l.credit) * sign
            dr += l.debit
            cr += l.credit
            rows.append(row([l.entry.date, _source_label(l.entry), l.entry.number, l.description or l.entry.memo,
                             l.debit or None, l.credit or None, bal], indent=1,
                            url=reverse("ledger:journal", args=[l.entry_id])))
        rows.append(row([_("Total for %(a)s") % {"a": a.name}, "", "", "", dr, cr, bal], cls="sub"))
    return rows


def pl_detail(company, date_from, date_to):
    rows = []
    for t, title in (("income", _("Income")), ("expense", _("Expenses"))):
        accounts = list(Account.objects.filter(company=company, type=t, is_group=False).order_by("code"))
        part = ledger_detail(company, date_from, date_to, accounts)
        # A P&L account starts each period from its movement only.
        part = [r for r in part if r["cells"][1] != _("Opening balance")]
        if part:
            rows.append(row([title, "", "", "", None, None, None], cls="grp", indent=0))
            rows.extend(part)
    return rows


def bs_compare(company, as_of, compare_to):
    now, then = balance_sheet(company, as_of), balance_sheet(company, compare_to)
    rows = []
    for key, title, total_key, total_label in (
            ("asset", _("Assets"), "total_assets", _("Total assets")),
            ("liability", _("Liabilities"), "total_liabilities", _("Total liabilities")),
            ("equity", _("Equity"), None, None)):
        rows.append(row([title, None, None, None], cls="grp"))
        accounts = {a.id: a for a, _v in now[key] + then[key]}
        a_now, a_then = dict((a.id, v) for a, v in now[key]), dict((a.id, v) for a, v in then[key])
        for aid in sorted(accounts, key=lambda i: accounts[i].code):
            x, y = a_now.get(aid, ZERO), a_then.get(aid, ZERO)
            rows.append(row([f"{accounts[aid].code} · {accounts[aid].name}", x, y, x - y], indent=1,
                            url=statement_url(accounts[aid], date(as_of.year, 1, 1), as_of)))
        if key == "equity":
            rows.append(row([_("Profit for the period (not yet closed)"), now["earnings"], then["earnings"],
                             now["earnings"] - then["earnings"]], indent=1))
            rows.append(row([_("Total equity"), now["total_equity"], then["total_equity"],
                             now["total_equity"] - then["total_equity"]], cls="sub"))
        else:
            rows.append(row([total_label, now[total_key], then[total_key], now[total_key] - then[total_key]], cls="sub"))
    foot = [_("Total liabilities and equity"), now["total_liabilities_equity"], then["total_liabilities_equity"],
            now["total_liabilities_equity"] - then["total_liabilities_equity"]]
    return rows, foot


INVESTING = {"fixed_assets"}
OPERATING_EQUITY = {"retained_earnings"}


def cash_flows(company, date_from, date_to):
    """Statement of cash flows (indirect method). It reconciles exactly to the movement on cash and bank accounts:
    cash change = net profit − the change in every other balance-sheet account."""
    accounts = list(Account.objects.filter(company=company, is_group=False))
    moves = balances(company, date_from=date_from, date_to=date_to)
    net = profit_and_loss(company, date_from, date_to)["net"]
    sections = {"operating": [], "investing": [], "financing": []}
    cash_ids = []
    for a in accounts:
        if a.type in ("income", "expense"):
            continue
        if a.subtype in ("cash", "bank"):
            cash_ids.append(a.id)
            continue
        d, c = moves.get(a.id, (ZERO, ZERO))
        effect = c - d
        if not effect:
            continue
        if a.subtype in INVESTING:
            key = "investing"
        elif a.type == "equity" and a.subtype not in OPERATING_EQUITY:
            key = "financing"
        else:
            key = "operating"
        sections[key].append((a, effect))
    opening = balances(company, date_to=date_from - timedelta(days=1), accounts=[a for a in accounts if a.id in cash_ids])
    start = sum((d - c for d, c in opening.values()), ZERO)
    rows = [row([_("Operating activities"), None], cls="grp"), row([_("Net profit"), net], indent=1,
                                                                  url=f"{reverse('reports:profit_loss')}?from={date_from:%Y-%m-%d}&to={date_to:%Y-%m-%d}")]
    totals = {}
    for key, title, total_label in (("operating", None, _("Net cash from operating activities")),
                                    ("investing", _("Investing activities"), _("Net cash from investing activities")),
                                    ("financing", _("Financing activities"), _("Net cash from financing activities"))):
        if title:
            rows.append(row([title, None], cls="grp"))
        elif sections[key]:
            rows.append(row([_("Adjustments for changes in balances"), None], indent=1))
        for a, effect in sorted(sections[key], key=lambda x: x[0].code):
            rows.append(row([f"{a.code} · {a.name}", effect], indent=2 if key == "operating" else 1,
                            url=statement_url(a, date_from, date_to)))
        totals[key] = sum((e for _a, e in sections[key]), ZERO) + (net if key == "operating" else ZERO)
        rows.append(row([total_label, totals[key]], cls="sub"))
    change = sum(totals.values(), ZERO)
    rows.append(row([_("Net change in cash"), change], cls="grp"))
    rows.append(row([_("Cash at the beginning of the period"), start], indent=1))
    return rows, [_("Cash at the end of the period"), start + change], {"change": change, "start": start}


def recent_transactions(company, date_from, date_to):
    entries = (JournalEntry.objects.filter(company=company, date__gte=date_from, date__lte=date_to)
               .annotate(amount=Sum("lines__debit")).order_by("-date", "-id")[:500])
    return [row([e.date, e.get_source_display(), e.number, e.memo, e.amount], url=reverse("ledger:journal", args=[e.pk]))
            for e in entries]


def journal(company, date_from, date_to):
    entries = (JournalEntry.objects.filter(company=company, date__gte=date_from, date__lte=date_to)
               .prefetch_related("lines__account").order_by("date", "id")[:300])
    rows, dr, cr = [], ZERO, ZERO
    for e in entries:
        rows.append(row([e.date, e.number, e.get_source_display(), e.memo, None, None], cls="grp",
                        url=reverse("ledger:journal", args=[e.pk])))
        for l in e.lines.all():
            rows.append(row(["", "", f"{l.account.code} · {l.account.name}", l.description, l.debit or None,
                             l.credit or None], indent=1))
            dr += l.debit
            cr += l.credit
    return rows, [_("Total"), "", "", "", dr, cr]


# ---------- Customers and suppliers ----------
PAY_STATES = {"paid": gettext_lazy("Paid"), "overdue": gettext_lazy("Overdue"), "partial": gettext_lazy("Partly paid"),
              "unpaid": gettext_lazy("Unpaid")}


def document_list(model, company, date_from, date_to, party, detail):
    rows, total, open_ = [], ZERO, ZERO
    qs = (model.objects.filter(company=company, date__gte=date_from, date__lte=date_to).exclude(status="void")
          .select_related(party, "currency").prefetch_related("lines__tax_rate").order_by("date", "id"))
    for d in qs:
        base_total, base_open = r2(d.total * d.rate), r2(d.balance_due * d.rate)
        total += base_total
        open_ += base_open
        state = d.get_status_display() if d.status != "posted" else PAY_STATES.get(d.payment_state, d.payment_state)
        rows.append(row([d.date, d.number or _("Draft"), getattr(d, party).name, d.due_date, state, d.currency_id,
                         d.total, base_total, base_open], url=reverse(detail, args=[d.pk])))
    return rows, [_("Total"), "", "", "", "", "", None, total, open_]


def sales_by_customer(company, date_from, date_to):
    from sales.models import CreditNote, Invoice

    data = defaultdict(lambda: {"n": 0, "net": ZERO, "tax": ZERO})
    for inv in (Invoice.objects.filter(company=company, status="posted", date__gte=date_from, date__lte=date_to)
                .select_related("customer").prefetch_related("lines__tax_rate")):
        d = data[inv.customer]
        d["n"] += 1
        d["net"] += r2(inv.subtotal * inv.rate)
        d["tax"] += r2(inv.tax_total * inv.rate)
    for note in (CreditNote.objects.filter(company=company, status="posted", date__gte=date_from, date__lte=date_to)
                 .select_related("customer").prefetch_related("lines__tax_rate")):
        d = data[note.customer]
        d["net"] -= r2(note.subtotal * note.rate)
        d["tax"] -= r2(note.tax_total * note.rate)
    rows, tn, tt = [], ZERO, ZERO
    for cust, d in sorted(data.items(), key=lambda kv: -kv[1]["net"]):
        rows.append(row([cust.name, d["n"], d["net"], d["tax"], d["net"] + d["tax"]],
                        url=f"{reverse('sales:invoices')}?party={cust.pk}&from={date_from:%Y-%m-%d}&to={date_to:%Y-%m-%d}"))
        tn += d["net"]
        tt += d["tax"]
    return rows, [_("Total"), sum(d["n"] for d in data.values()), tn, tt, tn + tt]


def expenses_by_supplier(company, date_from, date_to):
    from purchases.models import Bill, SupplierCredit

    data = defaultdict(lambda: {"n": 0, "net": ZERO, "tax": ZERO})
    for bill in (Bill.objects.filter(company=company, status="posted", date__gte=date_from, date__lte=date_to)
                 .select_related("supplier").prefetch_related("lines__tax_rate")):
        d = data[bill.supplier]
        d["n"] += 1
        d["net"] += r2(bill.subtotal * bill.rate)
        d["tax"] += r2(bill.tax_total * bill.rate)
    for credit in (SupplierCredit.objects.filter(company=company, status="posted", date__gte=date_from, date__lte=date_to)
                   .select_related("supplier").prefetch_related("lines__tax_rate")):
        d = data[credit.supplier]
        d["net"] -= r2(credit.subtotal * credit.rate)
        d["tax"] -= r2(credit.tax_total * credit.rate)
    rows, tn, tt = [], ZERO, ZERO
    for sup, d in sorted(data.items(), key=lambda kv: -kv[1]["net"]):
        rows.append(row([sup.name, d["n"], d["net"], d["tax"], d["net"] + d["tax"]],
                        url=f"{reverse('purchases:bills')}?party={sup.pk}&from={date_from:%Y-%m-%d}&to={date_to:%Y-%m-%d}"))
        tn += d["net"]
        tt += d["tax"]
    return rows, [_("Total"), sum(d["n"] for d in data.values()), tn, tt, tn + tt]


def customer_open_items(company, as_of):
    """What each customer owes, document by document (the same items the ageing report adds up)."""
    from banking.models import Cheque
    from sales.models import CreditNote, CustomerPayment, CustomerRefund, Invoice

    items = defaultdict(list)
    for inv in Invoice.objects.filter(company=company, status="posted", date__lte=as_of).select_related("customer"):
        if inv.balance_due > 0:
            items[inv.customer].append((inv.date, _("Invoice"), inv.number, inv.due_date, r2(inv.balance_due * inv.rate),
                                        reverse("sales:invoice", args=[inv.pk])))
    for pay in CustomerPayment.objects.filter(company=company, status="posted", date__lte=as_of).select_related("customer"):
        if pay.unallocated > 0:
            items[pay.customer].append((pay.date, _("Payment on account"), pay.number, None, -r2(pay.unallocated * pay.rate),
                                        reverse("sales:payment", args=[pay.pk])))
    for note in CreditNote.objects.filter(company=company, status="posted", date__lte=as_of).select_related("customer"):
        if note.available > 0:
            items[note.customer].append((note.date, _("Credit note"), note.number, None, -r2(note.available * note.rate),
                                         reverse("sales:credit", args=[note.pk])))
    for ref in CustomerRefund.objects.filter(company=company, status="posted", credit_note__isnull=True,
                                             date__lte=as_of).select_related("customer"):
        items[ref.customer].append((ref.date, _("Refund"), ref.number, None, r2(ref.amount * ref.rate),
                                    reverse("sales:refund", args=[ref.pk])))
    for chq in Cheque.objects.filter(company=company, status="bounced", customer__isnull=False,
                                     bounced_on__lte=as_of).select_related("customer"):
        items[chq.customer].append((chq.bounced_on, _("Returned cheque"), chq.number, chq.bounced_on, chq.base_amount,
                                    f"{reverse('banking:cheques')}?status=bounced&q={chq.number}"))
    return items


def supplier_open_items(company, as_of):
    from purchases.models import Bill, SupplierCredit, SupplierPayment

    items = defaultdict(list)
    for bill in Bill.objects.filter(company=company, status="posted", date__lte=as_of).select_related("supplier"):
        if bill.balance_due > 0:
            items[bill.supplier].append((bill.date, _("Bill"), bill.number, bill.due_date, r2(bill.balance_due * bill.rate),
                                         reverse("purchases:bill", args=[bill.pk])))
    for pay in SupplierPayment.objects.filter(company=company, status="posted", date__lte=as_of).select_related("supplier"):
        if pay.unallocated > 0:
            items[pay.supplier].append((pay.date, _("Payment on account"), pay.number, None, -r2(pay.unallocated * pay.rate),
                                        reverse("purchases:payment", args=[pay.pk])))
    for credit in SupplierCredit.objects.filter(company=company, status="posted", date__lte=as_of).select_related("supplier"):
        if credit.available > 0:
            items[credit.supplier].append((credit.date, _("Supplier credit"), credit.number, None,
                                           -r2(credit.available * credit.rate),
                                           reverse("purchases:supplier_credit", args=[credit.pk])))
    return items


def balance_summary(items, contact_url):
    rows, total = [], ZERO
    for contact, docs in sorted(items.items(), key=lambda kv: -sum(d[4] for d in kv[1])):
        bal = sum((d[4] for d in docs), ZERO)
        if not bal:
            continue
        total += bal
        rows.append(row([contact.name, len(docs), bal], url=reverse(contact_url, args=[contact.pk])))
    return rows, [_("Total"), sum(r["cells"][1] for r in rows), total]


def balance_detail(items, as_of):
    rows, total = [], ZERO
    for contact, docs in sorted(items.items(), key=lambda kv: kv[0].name):
        bal = sum((d[4] for d in docs), ZERO)
        if not bal:
            continue
        rows.append(row([contact.name, "", "", "", None, None], cls="grp"))
        running = ZERO
        for d, kind, number, due, amount, url in sorted(docs, key=lambda x: x[0]):
            running += amount
            rows.append(row([d, kind, number, due, amount, running], indent=1, url=url))
        rows.append(row([_("Total for %(a)s") % {"a": contact.name}, "", "", "", bal, None], cls="sub"))
        total += bal
    return rows, [_("Total"), "", "", "", total, None]


# ---------- Inventory, assets, payroll ----------
def inventory_valuation_detail(company):
    from inventory.models import StockLayer

    rows, total = [], ZERO
    layers = (StockLayer.objects.filter(company=company, qty_remaining__gt=0)
              .select_related("item", "warehouse").order_by("item__sku", "warehouse__code", "date", "id"))
    current, sub = None, ZERO
    for l in layers:
        if current != l.item_id:
            if current is not None:
                rows.append(row([_("Total"), "", "", "", "", None, None, sub], cls="sub"))
            rows.append(row([f"{l.item.sku} · {l.item.name}", "", "", "", "", None, None, None], cls="grp",
                            url=reverse("inventory:item", args=[l.item_id])))
            current, sub = l.item_id, ZERO
        value = r2(l.qty_remaining * l.unit_cost)
        sub += value
        total += value
        rows.append(row([l.warehouse.name, l.date, l.ref, l.serial_no or l.batch_no, l.expiry_date, l.qty_remaining,
                         l.unit_cost, value], indent=1))
    if current is not None:
        rows.append(row([_("Total"), "", "", "", "", None, None, sub], cls="sub"))
    return rows, [_("Stock value"), "", "", "", "", None, None, total]


def fixed_asset_register(company):
    from assets.models import Asset

    rows, tc, ta, tb = [], ZERO, ZERO, ZERO
    for a in Asset.objects.filter(company=company).select_related("category").order_by("category__name_en", "number"):
        acc = a.accumulated
        rows.append(row([a.number, a.name, a.category.name, a.purchase_date, a.get_status_display(), a.cost, acc,
                         a.cost - acc], url=reverse("assets:detail", args=[a.pk])))
        tc += a.cost
        ta += acc
        tb += a.cost - acc
    return rows, [_("Total"), "", "", "", "", tc, ta, tb]


def payroll_summary(company, date_from, date_to):
    from payroll.models import Payslip

    first, last = (date_from.year, date_from.month), (date_to.year, date_to.month)
    data = defaultdict(lambda: {"n": 0, "gross": ZERO, "ded": ZERO, "net": ZERO})
    for p in Payslip.objects.filter(run__company=company).select_related("employee", "run"):
        if not first <= (p.run.year, p.run.month) <= last:
            continue
        d = data[p.employee]
        d["n"] += 1
        d["gross"] += p.gross
        d["ded"] += p.total_deductions
        d["net"] += p.net_pay
    rows, t = [], {"gross": ZERO, "ded": ZERO, "net": ZERO}
    for emp, d in sorted(data.items(), key=lambda kv: kv[0].code):
        rows.append(row([emp.code, emp.name, d["n"], d["gross"], d["ded"], d["net"]],
                        url=reverse("team:employee", args=[emp.pk])))
        for k in t:
            t[k] += d[k]
    return rows, [_("Total"), "", sum(d["n"] for d in data.values()), t["gross"], t["ded"], t["net"]]
