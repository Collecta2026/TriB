"""List filters (the Filter panel, and what the dashboard and reports drill into): ?status=, ?dates=last_365 or
?from=&to=, ?party=<id>, ?tag=, ?pay=overdue. Each list shows what is applied as chips that can be removed one by one."""
from datetime import date, timedelta

from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

PAY = {"open", "overdue", "notdue", "due7"}
DATES = [("30", gettext_lazy("Last 30 days")), ("90", gettext_lazy("Last 90 days")), ("365", gettext_lazy("Last 12 months")),
         ("this_year", gettext_lazy("This year")), ("last_year", gettext_lazy("Last year")), ("custom", gettext_lazy("Custom dates"))]


class Chip(str):
    """A filter label that knows which URL parameters remove it."""

    def __new__(cls, text, *params):
        chip = super().__new__(cls, text)
        chip.params = params
        return chip


def pay_labels():
    return {"open": _("Unpaid"), "overdue": _("Overdue"), "notdue": _("Not due yet"), "due7": _("Due within 7 days")}


def date_range(request, today=None):
    """(from, to, label) from ?dates= or ?from=&to=."""
    today = today or timezone.localdate()
    preset = request.GET.get("dates", "")
    if preset in ("30", "90", "365"):
        return today - timedelta(days=int(preset)), today, dict(DATES)[preset]
    if preset == "this_year":
        return date(today.year, 1, 1), today, dict(DATES)[preset]
    if preset == "last_year":
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31), dict(DATES)[preset]
    return parse_date(request.GET.get("from", "") or ""), parse_date(request.GET.get("to", "") or ""), None


def apply(request, qs, party=None):
    """Narrow a queryset of documents or payments. Returns (queryset, chips of the filters applied)."""
    labels = []
    date_from, date_to, preset = date_range(request)
    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)
    if preset:
        labels.append(Chip(str(preset), "dates"))
    else:
        if date_from:
            labels.append(Chip(_("From %(d)s") % {"d": f"{date_from:%d/%m/%Y}"}, "from"))
        if date_to:
            labels.append(Chip(_("To %(d)s") % {"d": f"{date_to:%d/%m/%Y}"}, "to"))
    pid = request.GET.get("party", "")
    if party and pid.isdigit():
        qs = qs.filter(**{f"{party}_id": int(pid)})
        obj = qs.model._meta.get_field(party).related_model.objects.filter(pk=pid).first()
        if obj:
            labels.append(Chip(str(obj), "party"))
    tag = request.GET.get("tag", "").strip()
    if tag and any(f.name == "tags" for f in qs.model._meta.fields):
        ids = [pk for pk, tags in qs.values_list("pk", "tags") if any(t.lower() == tag.lower() for t in (tags or []))]
        qs = qs.filter(pk__in=ids)
        labels.append(Chip(_("Tag: %(t)s") % {"t": tag}, "tag"))
    project = request.GET.get("project", "")
    if project.isdigit() and hasattr(qs.model, "lines"):
        qs = qs.filter(lines__project_id=int(project)).distinct()
        from ledger.models import Project
        p = Project.objects.filter(pk=project).first()
        if p:
            labels.append(Chip(str(p), "project"))
    pay = request.GET.get("pay", "")
    if pay in PAY and hasattr(qs.model, "balance_due"):
        today = timezone.localdate()
        posted = qs.filter(status="posted")
        if pay == "overdue":
            posted = posted.filter(due_date__lt=today)
        elif pay == "notdue":
            posted = posted.filter(due_date__gte=today)
        elif pay == "due7":
            posted = posted.filter(due_date__lte=today + timedelta(days=7))
        ids = [d.pk for d in posted.prefetch_related("lines__tax_rate") if d.balance_due > 0]
        qs = qs.filter(pk__in=ids)
        labels.append(Chip(pay_labels()[pay], "pay"))
    return qs, labels
