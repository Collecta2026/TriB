from decimal import Decimal, InvalidOperation

from django import template
from django.utils.html import format_html

from core.models import Currency, is_arabic

register = template.Library()


@register.filter
def num(value, decimals=2):
    """1234.5 → 1,234.50 (Western digits in both languages, as Egyptian accounts are kept)."""
    try:
        value = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return value
    return f"{value:,.{int(decimals)}f}"


@register.filter
def money(value, currency=None):
    """Amount with its currency label, isolated so it reads correctly inside Arabic text."""
    if value is None or value == "":
        return ""
    code = getattr(currency, "code", currency)
    label = ""
    if code:
        cur = currency if isinstance(currency, Currency) else Currency.objects.filter(code=code).first()
        label = cur.label if cur else code
    amount = num(value)
    text = f"{amount} {label}" if is_arabic() else f"{label} {amount}"
    return format_html('<bdi class="m">{}</bdi>', text.strip())


@register.filter
def get(mapping, key):
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.simple_tag(takes_context=True)
def active(context, prefix):
    path = context["request"].path
    return "active" if path.startswith(prefix) else ""
