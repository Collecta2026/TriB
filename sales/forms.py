from django import forms

from core import access
from django.utils.translation import gettext_lazy as _

from banking.models import BankAccount
from core.forms_util import DATE, CompanyModelForm, line_formsets

from .models import (CreditNote, CreditNoteLine, CustomerPayment, CustomerRefund, Invoice, InvoiceLine, Quotation,
                     QuotationLine, SalesOrder, SalesOrderLine)

LINE_FIELDS = ["item", "description", "qty", "unit_price", "discount_pct", "tax_rate", "project"]


class QuotationForm(CompanyModelForm):
    class Meta:
        model = Quotation
        fields = ["customer", "email_to", "email_cc", "email_bcc", "bill_to", "ship_to", "date", "valid_until",
                  "ship_via", "ship_date", "tracking_no", "customer_po", "currency", "rate", "reference", "branch",
                  "prices_include_tax", "tags", "notes"]
        widgets = {"date": DATE, "valid_until": DATE, "ship_date": DATE, "notes": forms.Textarea(attrs={"rows": 2})}


class SalesOrderForm(CompanyModelForm):
    class Meta:
        model = SalesOrder
        fields = ["customer", "email_to", "email_cc", "email_bcc", "bill_to", "ship_to", "date", "expected_date",
                  "ship_via", "ship_date", "tracking_no", "customer_po", "warehouse", "currency", "rate", "reference",
                  "branch", "prices_include_tax", "tags", "notes"]
        widgets = {"date": DATE, "expected_date": DATE, "ship_date": DATE, "notes": forms.Textarea(attrs={"rows": 2})}


class InvoiceForm(CompanyModelForm):
    class Meta:
        model = Invoice
        fields = ["customer", "email_to", "email_cc", "email_bcc", "bill_to", "ship_to", "terms", "date", "due_date",
                  "ship_via", "ship_date", "tracking_no", "customer_po", "warehouse", "currency", "rate", "reference",
                  "branch", "prices_include_tax", "tags", "notes"]
        widgets = {"date": DATE, "due_date": DATE, "ship_date": DATE, "notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "terms" in self.fields:
            self.fields["due_date"].required = False

    def clean(self):
        from datetime import timedelta

        data = super().clean()
        terms, day = data.get("terms"), data.get("date")
        if terms in Invoice.TERM_DAYS and day:
            data["due_date"] = day + timedelta(days=Invoice.TERM_DAYS[terms])
        elif "terms" in self.fields and not data.get("due_date"):
            self.add_error("due_date", _("Enter the due date, or choose terms."))
        return data


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
    STYLES = [("balance", _("Balance forward: every transaction in the period")),
              ("open", _("Open items: unpaid invoices with their age"))]
    style = forms.ChoiceField(label=_("Statement type"), choices=STYLES, initial="balance", required=False)

    def __init__(self, *args, company, model=None, label=None, **kwargs):
        super().__init__(*args, **kwargs)
        from contacts.models import Customer
        if model is not None:
            self.fields.pop("style")  # supplier statements: balance forward only
        model = model or Customer
        self.fields["customer"].queryset = access.scope(model.objects.filter(company=company, is_active=True))
        if label:
            self.fields["customer"].label = label

    def clean_style(self):
        return self.cleaned_data.get("style") or "balance"


class ConfirmationForm(forms.Form):
    as_of = forms.DateField(label=_("Balance as of"), widget=DATE)
    reply_by = forms.DateField(label=_("Please reply by"), widget=DATE)
    include_zero = forms.BooleanField(label=_("Include customers with a zero balance"), required=False)

class SalesReceiptForm(InvoiceForm):
    """A cash sale: an invoice paid in full on the spot."""
    deposit_to = forms.ModelChoiceField(queryset=BankAccount.objects.none(), label=_("Deposit to"),
                                        help_text=_("The cash box or bank account the money goes into."))

    class Meta(InvoiceForm.Meta):
        fields = ["customer", "email_to", "bill_to", "date", "deposit_to", "warehouse", "currency", "rate", "reference", "branch",
                  "prices_include_tax", "tags", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["deposit_to"].queryset = BankAccount.objects.filter(company=self.company, is_active=True)

    def clean(self):
        data = super().clean()
        if data.get("deposit_to") and data.get("currency") and data["deposit_to"].currency_id != data["currency"].code:
            self.add_error("deposit_to", _("Choose a cash box or bank account in %(c)s.") % {"c": data["currency"].code})
        return data

    def save(self, commit=True):
        doc = super().save(commit=False)
        doc.due_date = doc.date
        if commit:
            doc.save()
        return doc


class CreditNoteForm(CompanyModelForm):
    class Meta:
        model = CreditNote
        fields = ["customer", "invoice", "date", "warehouse", "currency", "rate", "reason", "reference", "branch",
                  "prices_include_tax", "tags", "notes"]
        widgets = {"date": DATE, "notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["invoice"].queryset = Invoice.objects.filter(company=self.company, status="posted").select_related("customer")
        self.fields["invoice"].label_from_instance = lambda i: f"{i.number} · {i.customer.name} · {i.total:,.2f}"

    def clean(self):
        data = super().clean()
        inv, customer = data.get("invoice"), data.get("customer")
        if inv and customer and inv.customer_id != customer.pk:
            self.add_error("invoice", _("This invoice belongs to another customer."))
        return data


CREDIT_LINES = line_formsets(CreditNote, CreditNoteLine, LINE_FIELDS + ["return_to_stock", "serials", "batch_no", "expiry_date"])
for _fs in CREDIT_LINES:
    _fs.form.base_fields["serials"].widget = forms.TextInput(attrs={"placeholder": _("S/N, comma separated")})
    _fs.form.base_fields["expiry_date"].widget = DATE


class RefundForm(CompanyModelForm):
    class Meta:
        model = CustomerRefund
        fields = ["customer", "credit_note", "date", "currency", "rate", "amount", "method", "bank_account",
                  "cheque_number", "reference", "notes"]
        widgets = {"date": DATE}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["credit_note"].queryset = CreditNote.objects.filter(company=self.company, status="posted")
        self.fields["credit_note"].required = False


class ApplyCreditForm(forms.Form):
    invoice = forms.ModelChoiceField(queryset=None, label=_("Invoice"))
    amount = forms.DecimalField(label=_("Amount"), min_value=0, decimal_places=2)

    def __init__(self, *args, note, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["invoice"].queryset = Invoice.objects.filter(company=note.company, customer=note.customer,
                                                                 currency=note.currency, status="posted")
        self.fields["invoice"].label_from_instance = lambda i: f"{i.number} · {i.date:%d/%m/%Y} · {i.balance_due:,.2f}"
