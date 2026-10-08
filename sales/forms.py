from django import forms
from django.utils.translation import gettext_lazy as _

from core.forms_util import DATE, CompanyModelForm, line_formsets

from .models import (CustomerPayment, Invoice, InvoiceLine, Quotation, QuotationLine, SalesOrder,
                     SalesOrderLine)

LINE_FIELDS = ["item", "description", "qty", "unit_price", "discount_pct", "tax_rate", "project"]


class QuotationForm(CompanyModelForm):
    class Meta:
        model = Quotation
        fields = ["customer", "date", "valid_until", "currency", "rate", "reference", "branch", "notes"]
        widgets = {"date": DATE, "valid_until": DATE, "notes": forms.Textarea(attrs={"rows": 2})}


class SalesOrderForm(CompanyModelForm):
    class Meta:
        model = SalesOrder
        fields = ["customer", "date", "expected_date", "warehouse", "currency", "rate", "reference", "branch", "notes"]
        widgets = {"date": DATE, "expected_date": DATE, "notes": forms.Textarea(attrs={"rows": 2})}


class InvoiceForm(CompanyModelForm):
    class Meta:
        model = Invoice
        fields = ["customer", "date", "due_date", "warehouse", "currency", "rate", "reference", "branch", "notes"]
        widgets = {"date": DATE, "due_date": DATE, "notes": forms.Textarea(attrs={"rows": 2})}


QUOTE_LINES = line_formsets(Quotation, QuotationLine, LINE_FIELDS)
ORDER_LINES = line_formsets(SalesOrder, SalesOrderLine, LINE_FIELDS)
INVOICE_LINES = line_formsets(Invoice, InvoiceLine, LINE_FIELDS + ["serials"])
for _fs in INVOICE_LINES:
    _fs.form.base_fields["serials"].widget = forms.TextInput(attrs={"placeholder": _("S/N, comma separated")})


class PaymentForm(CompanyModelForm):
    class Meta:
        model = CustomerPayment
        fields = ["customer", "date", "currency", "rate", "amount", "method", "bank_account", "cheque_number",
                  "cheque_bank", "cheque_due_date", "reference", "notes"]
        widgets = {"date": DATE, "cheque_due_date": DATE}


class StatementForm(forms.Form):
    customer = forms.ModelChoiceField(queryset=None, label=_("Customer"))
    date_from = forms.DateField(label=_("From"), widget=DATE)
    date_to = forms.DateField(label=_("To"), widget=DATE)

    def __init__(self, *args, company, model=None, label=None, **kwargs):
        super().__init__(*args, **kwargs)
        from contacts.models import Customer
        model = model or Customer
        self.fields["customer"].queryset = model.objects.filter(company=company, is_active=True)
        if label:
            self.fields["customer"].label = label


class ConfirmationForm(forms.Form):
    as_of = forms.DateField(label=_("Balance as of"), widget=DATE)
    reply_by = forms.DateField(label=_("Please reply by"), widget=DATE)
    include_zero = forms.BooleanField(label=_("Include customers with a zero balance"), required=False)
