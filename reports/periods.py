"""Report periods (This month, Last quarter…) and each user's default report settings."""
from datetime import date, timedelta

from django.utils.dateparse import parse_date
from django.utils.translation import gettext_lazy as _

PERIODS = [
    ("this_month", _("This month")),
    ("this_quarter", _("This quarter")),
    ("this_year", _("This year to date")),
    ("last_month", _("Last month")),
    ("last_quarter", _("Last quarter")),
    ("last_year", _("Last year")),
    ("last_30", _("Last 30 days")),
    ("last_365", _("Last 12 months")),
    ("custom", _("Custom dates")),
]
COMPARE = [("previous_period", _("Previous period")), ("previous_year", _("Same period last year"))]
DEFAULTS = {"period": "this_year", "compare": "previous_period", "zero_rows": False}


def period_dates(key, today):
    q_start = date(today.year, (today.month - 1) // 3 * 3 + 1, 1)
    if key == "this_month":
        return today.replace(day=1), today
    if key == "this_quarter":
        return q_start, today
    if key == "last_month":
        end = today.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end
    if key == "last_quarter":
        end = q_start - timedelta(days=1)
        return date(end.year, (end.month - 1) // 3 * 3 + 1, 1), end
    if key == "last_year":
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    if key == "last_30":
        return today - timedelta(days=29), today
    if key == "last_365":
        return today - timedelta(days=364), today
    return date(today.year, 1, 1), today


def user_defaults(request):
    from core.models import UserPreference

    if getattr(request, "_report_defaults", None) is None:
        saved = {}
        if request.user.is_authenticated and getattr(request, "company", None):
            saved = UserPreference.for_user(request.user, request.company).report_defaults or {}
        request._report_defaults = {**DEFAULTS, **saved}
    return request._report_defaults


def resolve(request, today, default=None):
    """(from, to, period key) from ?period=…, else ?from=&to=, else the user's default period."""
    key = request.GET.get("period", "")
    if key and key != "custom" and key in dict(PERIODS):
        return (*period_dates(key, today), key)
    date_from = parse_date(request.GET.get("from", "") or "")
    date_to = parse_date(request.GET.get("to", "") or "")
    if date_from or date_to:
        return date_from or date(today.year, 1, 1), date_to or today, "custom"
    key = default or user_defaults(request)["period"]
    return (*period_dates(key, today), key)
