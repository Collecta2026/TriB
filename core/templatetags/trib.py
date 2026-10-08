from decimal import Decimal, InvalidOperation

from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

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
def div(value, by):
    """value ÷ by, or empty when dividing by zero."""
    try:
        by = Decimal(by)
        return Decimal(value) / by if by else ""
    except (InvalidOperation, TypeError, ValueError):
        return ""


@register.filter
def absval(value):
    try:
        return abs(Decimal(value))
    except (InvalidOperation, TypeError, ValueError):
        return value


@register.filter
def index(sequence, i):
    try:
        return sequence[int(i)]
    except (IndexError, TypeError, ValueError, KeyError):
        return ""


@register.filter
def get_attr(obj, name):
    """Attribute by name, for tables whose columns are listed in the view (public fields only)."""
    return getattr(obj, name, "") if not str(name).startswith("_") else ""


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


@register.simple_tag(takes_context=True)
def page_url(context, number):
    """The current URL with ?page= swapped, keeping every filter."""
    query = context["request"].GET.copy()
    query["page"] = number
    return "?" + query.urlencode()


@register.inclusion_tag("partials/attachments.html", takes_context=True)
def attachments(context, obj):
    from core.attachments import for_object

    request = context["request"]
    return {"files": for_object(obj) if obj.pk else [], "target": obj._meta.label_lower, "target_id": obj.pk,
            "request": request, "csrf_token": context.get("csrf_token"), "can": context.get("can"), "saved": bool(obj.pk)}


@register.simple_tag
def barcode(text, module=2, height=50):
    from core.barcode import svg

    return mark_safe(svg(str(text), module=int(module), height=int(height)))


@register.filter
def pill_class(status):
    return {"posted": "good", "paid": "good", "approved": "good", "received": "good", "invoiced": "good",
            "accepted": "good", "authorised": "good", "done": "good", "closed": "good", "active": "good",
            "matched": "good", "found": "good",
            "draft": "info", "open": "info", "sent": "info", "new": "info",
            "submitted": "warn", "prepared": "warn", "partial": "warn", "unpaid": "warn", "hold": "warn",
            "overdue": "crit", "void": "crit", "cancelled": "crit", "declined": "crit", "rejected": "crit",
            "missing": "crit", "left": "crit", "disposed": "crit", "excluded": "",
            "expired": "crit", "soon": "warn", "ok": "good"}.get(str(status), "")


@register.filter
def state_label(state):
    from django.utils.translation import gettext as _

    return {"paid": _("Paid"), "unpaid": _("Unpaid"), "overdue": _("Overdue"), "partial": _("Partly paid"),
            "draft": _("Draft"), "void": _("Void"), "posted": _("Posted")}.get(str(state), state)


@register.filter
def filesize(n):
    n = int(n or 0)
    return f"{n / 1048576:.1f} MB" if n >= 1048576 else f"{max(1, n // 1024)} KB"
