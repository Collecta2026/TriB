"""Filters the dashboard and reports drill into: ?pay=overdue, ?from=&to=, ?party=<id>. Each list shows what is
applied ("Showing: Overdue · From 01/10/2026") with a link to clear it."""
from datetime import timedelta

from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.translation import gettext as _

PAY = {"open", "overdue", "notdue", "due7"}


def pay_labels():
    return {"open": _("Unpaid"), "overdue": _("Overdue"), "notdue": _("Not due yet"), "due7": _("Due within 7 days")}


def apply(request, qs, party=None):
    """Narrow a queryset of documents or payments. Returns (queryset or list, labels of the filters applied)."""
    labels = []
    date_from = parse_date(request.GET.get("from", "") or "")
    date_to = parse_date(request.GET.get("to", "") or "")
    if date_from:
        qs = qs.filter(date__gte=date_from)
        labels.append(_("From %(d)s") % {"d": f"{date_from:%d/%m/%Y}"})
    if date_to:
        qs = qs.filter(date__lte=date_to)
        labels.append(_("To %(d)s") % {"d": f"{date_to:%d/%m/%Y}"})
    pid = request.GET.get("party", "")
    if party and pid.isdigit():
        qs = qs.filter(**{f"{party}_id": int(pid)})
        obj = qs.model._meta.get_field(party).related_model.objects.filter(pk=pid).first()
        if obj:
            labels.append(str(obj))
    tag = request.GET.get("tag", "").strip()
    if tag and any(f.name == "tags" for f in qs.model._meta.fields):
        ids = [pk for pk, tags in qs.values_list("pk", "tags") if any(t.lower() == tag.lower() for t in (tags or []))]
        qs = qs.filter(pk__in=ids)
        labels.append(_("Tag: %(t)s") % {"t": tag})
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
        labels.append(pay_labels()[pay])
    return qs, labels
