"""Price rules: which rule applies to a customer, a product and a date, and the price it gives.

When several rules match, the most specific wins: a rule for chosen customers beats one for all customers, and a rule
for chosen products beats one for a category, which beats one for all products. Between equally specific rules, the
newest wins. The same order is sent to the line-item script (static/js/docs.js), which applies rules as products are
added to invoices, quotes and sales orders.
"""
from decimal import ROUND_HALF_UP, Decimal

from .models import PriceRule

ZERO = Decimal("0")


def _score(rule, customers, items, categories):
    return (2 if customers else 0) + (2 if items else 1 if categories else 0)


def rule_data(company):
    """Active rules as plain data, most specific first: customer ids / item ids are None for "all"."""
    out = []
    rules = (PriceRule.objects.filter(company=company, is_active=True)
             .prefetch_related("customers", "categories", "items"))
    for r in rules:
        customers = [c.pk for c in r.customers.all()]
        items = {i.pk for i in r.items.all()}
        categories = [c.pk for c in r.categories.all()]
        if categories:
            from .models import Item
            items |= set(Item.objects.filter(company=company, category_id__in=categories).values_list("pk", flat=True))
        out.append({"id": r.pk, "name": r.name, "customers": customers or None,
                    "items": sorted(items) if (items or categories) else None,
                    "start": r.start_date.isoformat() if r.start_date else "",
                    "end": r.end_date.isoformat() if r.end_date else "",
                    "dir": r.direction, "method": r.method, "amount": str(r.amount), "rounding": r.rounding,
                    "score": _score(r, customers, r.items.exists(), categories), "created": r.pk})
    out.sort(key=lambda d: (-d["score"], -d["created"]))
    return out


def adjust(price, rule):
    """The price after a rule (rule as from rule_data). Never below zero."""
    price = Decimal(price or 0)
    amount = Decimal(rule["amount"] or 0)
    change = price * amount / 100 if rule["method"] == "percent" else amount
    new = price + change if rule["dir"] == "up" else price - change
    new = max(new, ZERO)
    r = rule["rounding"]
    if r == "whole":
        new = new.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    elif r == "half":
        new = (new * 2).quantize(Decimal("1"), rounding=ROUND_HALF_UP) / 2
    elif r == "nickel":
        new = (new * 20).quantize(Decimal("1"), rounding=ROUND_HALF_UP) / 20
    elif r == "end99":
        new = max(new.quantize(Decimal("1"), rounding=ROUND_HALF_UP) - Decimal("0.01"), ZERO)
    return new.quantize(Decimal("0.0001"))


def matching(rules, customer_id, item_id, day):
    """The first (most specific) rule for this customer, product and date, or None."""
    iso = day.isoformat() if day else ""
    for r in rules:
        if r["customers"] is not None and customer_id not in r["customers"]:
            continue
        if r["items"] is not None and item_id not in r["items"]:
            continue
        if iso and ((r["start"] and iso < r["start"]) or (r["end"] and iso > r["end"])):
            continue
        return r
    return None


def price_for(company, item, customer=None, day=None, rules=None):
    """(price, rule name or "") for a product sold to a customer on a day."""
    rules = rule_data(company) if rules is None else rules
    rule = matching(rules, customer.pk if customer else None, item.pk, day)
    if rule is None:
        return item.sales_price, ""
    return adjust(item.sales_price, rule), rule["name"]
