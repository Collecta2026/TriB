"""Customer statements: balance forward (every transaction in the period) or open items (unpaid invoices with their
age), each with the ageing line (Current, 1–30 … Over 120 days). Shown on screen, printed one per page, or emailed with
the statement itself in the email; batch statements do the same for every customer with a balance."""
from decimal import Decimal

from django import forms
from django.template.loader import render_to_string
from django.utils import timezone, translation
from django.utils.formats import date_format
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from core.forms_util import DATE
from core.mailer import bilingual

from . import services

ZERO = Decimal("0")


def aging_labels(company):
    """The ageing column headings as (English, Arabic); Arabic is "" where documents print in English only."""
    out = []
    for _limit, label in services.AGING_BUCKETS:
        with translation.override("en"):
            en = str(label)
        with translation.override("ar"):
            ar = str(label)
        out.append((en, ar if bilingual(company) else ""))
    return out


def finish(data, company):
    """What every statement layout needs on top of the figures."""
    data["aging_total"] = sum(data["aging"], ZERO)
    data["aging_cols"] = [(en, ar, v) for (en, ar), v in zip(aging_labels(company), data["aging"])]
    data["balance"] = data["total"] if data.get("style") == "open" else data["closing"]
    return data


def build(customer, date_from, date_to, style, company):
    if style == "open":
        data = services.open_items(customer, date_to)
    else:
        data = services.statement(customer, date_from, date_to)
    data.update(contact=customer, date_from=date_from, date_to=date_to, style=style)
    return finish(data, company)


def from_request(request, params=None):
    """(form, statement or None) from ?customer=…&date_from=…&date_to=…&style=…. With just ?customer= (the customer
    page's Statement button) the statement shows straight away: this year to today, balance forward."""
    from .forms import StatementForm

    params = request.GET if params is None else params
    today = timezone.localdate()
    defaults = {"date_from": today.replace(month=1, day=1).isoformat(), "date_to": today.isoformat(), "style": "balance"}
    bound = None
    if params.get("customer") or "date_to" in params:
        bound = params.copy()
        for key, value in defaults.items():
            if not bound.get(key):
                bound[key] = value
    form = StatementForm(bound, company=request.company,
                         initial={"date_from": today.replace(month=1, day=1), "date_to": today, "style": "balance"})
    if bound is None or not form.is_valid():
        return form, None
    d = form.cleaned_data
    return form, build(d["customer"], d["date_from"], d["date_to"], d["style"], request.company)


# ---------- email ----------
def default_subject(company):
    return _("Statement of account from %(company)s") % {"company": company.name}


def default_message(company, data):
    return _("Dear %(name)s,\n\nPlease find below your statement of account to %(date)s. The balance is %(amount)s "
             "%(cur)s.\n\nPlease let us know within 15 days if it does not agree with your records.\n\nKind regards,\n"
             "%(company)s") % {"name": data["contact"].name, "date": date_format(data["date_to"], "d/m/Y"),
                               "amount": f"{data['balance']:,.2f}", "cur": data["contact"].currency_id,
                               "company": company.name}


def email_parts(company, data, message, subject=""):
    ctx = {"data": data, "company": company, "message": message, "subject": subject, "bi": bilingual(company)}
    return (render_to_string("sales/email_statement.html", ctx), render_to_string("sales/email_statement.txt", ctx))


# ---------- batch statements ----------
class BatchForm(forms.Form):
    WHICH = [("balance", gettext_lazy("Every customer with a balance")),
             ("overdue", gettext_lazy("Only customers with overdue invoices"))]
    which = forms.ChoiceField(label=gettext_lazy("Customers"), choices=WHICH, initial="balance")
    style = forms.ChoiceField(label=gettext_lazy("Statement type"), initial="open", choices=[
        ("open", gettext_lazy("Open items: unpaid invoices with their age")),
        ("balance", gettext_lazy("Balance forward: every transaction in the period"))])
    date_from = forms.DateField(label=gettext_lazy("From"), widget=DATE,
                                help_text=gettext_lazy("Balance forward only: the start of the period."))
    date_to = forms.DateField(label=gettext_lazy("Statement date"), widget=DATE)


def batch_customers(request, d):
    """Customers the batch covers, with their balance and overdue amount (base currency) as of the statement date."""
    from contacts.models import Customer
    from core import access

    owed = {r["contact"].pk: r for r in services.ar_aging(request.company, d["date_to"])}
    rows = []
    for c in access.scope(Customer.objects.filter(company=request.company, is_active=True)).order_by("name_en"):
        r = owed.get(c.pk)
        if not r or r["total"] <= 0:
            continue
        overdue = sum(r["buckets"][1:], ZERO)
        if d["which"] == "overdue" and overdue <= 0:
            continue
        rows.append({"c": c, "total": r["total"], "overdue": overdue})
    return rows
