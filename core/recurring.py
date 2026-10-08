"""Recurring transactions: copy a template document as a new draft each period."""
import calendar
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from .models import AuditLog, RecurringTemplate


def add_period(day, frequency):
    if frequency == "weekly":
        return day + timedelta(days=7)
    months = {"monthly": 1, "quarterly": 3, "yearly": 12}[frequency]
    month = day.month - 1 + months
    year, month = day.year + month // 12, month % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def source_document(template):
    if template.kind == "voucher":
        from vouchers.models import Voucher
        return Voucher.objects.filter(company=template.company, pk=template.source_id).first()
    if template.kind == "invoice":
        from sales.models import Invoice
        return Invoice.objects.filter(company=template.company, pk=template.source_id).first()
    from purchases.models import Bill
    return Bill.objects.filter(company=template.company, pk=template.source_id).first()


def _clone(doc, on, user, extra):
    lines = list(doc.lines.all())
    doc.pk = None
    doc.id = None
    doc.number = ""
    doc.date = on
    doc.status = "draft"
    for key, value in extra.items():
        setattr(doc, key, value)
    if hasattr(doc, "created_by_id"):
        doc.created_by = user
    doc.save()
    for line in lines:
        line.pk = None
        line.id = None
        if hasattr(line, "voucher_id"):
            line.voucher = doc
        else:
            line.document = doc
        for attr in ("order_line_id", "receipt_line_id"):
            if hasattr(line, attr):
                setattr(line, attr, None)
        line.save()
    return doc


@transaction.atomic
def create_one(template, user):
    doc = source_document(template)
    if doc is None:
        template.is_active = False
        template.save(update_fields=["is_active"])
        return None
    on = template.next_date
    extra = {}
    if template.kind == "voucher":
        extra = {"journal_entry": None, "cheque": None, "posted_at": None}
    elif template.kind == "invoice":
        extra = {"journal_entry": None, "amount_paid": 0, "posted_at": None, "sales_order": None,
                 "due_date": on + (doc.due_date - doc.date)}
    else:
        extra = {"journal_entry": None, "amount_paid": 0, "purchase_order": None, "supplier_invoice_no": "",
                 "due_date": on + (doc.due_date - doc.date)}
    copy = _clone(doc, on, user, extra)
    template.next_date = add_period(template.next_date, template.frequency)
    template.last_created = f"{template.kind}:{copy.pk}"
    if template.end_date and template.next_date > template.end_date:
        template.is_active = False
    template.save(update_fields=["next_date", "last_created", "is_active"])
    AuditLog.record(template.company, user, "recurring.created", template, template.name)
    return copy


def run_due(company, user, today=None):
    """Create every draft that is due. Called from the dashboard and the Recurring page."""
    today = today or timezone.localdate()
    created = []
    for template in RecurringTemplate.objects.filter(company=company, is_active=True, next_date__lte=today):
        while template.is_active and template.next_date <= today:
            doc = create_one(template, user)
            if doc is None:
                break
            created.append(doc)
    return created
