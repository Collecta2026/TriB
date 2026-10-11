from django import forms
from django.utils.translation import gettext_lazy as _

from core.forms_util import DATE, CompanyModelForm, LineForm, line_formsets

from .models import (Bill, BillLine, GoodsReceipt, GoodsReceiptLine, PurchaseOrder, PurchaseOrderLine, SupplierCredit,
                     SupplierCreditLine, SupplierPayment)

LINE_FIELDS = ["item", "description", "qty", "unit_price", "discount_pct", "tax_rate", "project"]


class PurchaseOrderForm(CompanyModelForm):
    class Meta:
        model = PurchaseOrder
        fields = ["supplier", "date", "expected_date", "warehouse", "currency", "rate", "reference", "branch",
                  "prices_include_tax", "tags", "notes"]
        widgets = {"date": DATE, "expected_date": DATE, "notes": forms.Textarea(attrs={"rows": 2})}


class BillForm(CompanyModelForm):
    class Meta:
        model = Bill
        fields = ["supplier", "supplier_invoice_no", "date", "due_date", "currency", "rate", "warehouse", "reference",
                  "branch", "prices_include_tax", "tags", "notes"]
        widgets = {"date": DATE, "due_date": DATE, "notes": forms.Textarea(attrs={"rows": 2})}


class GoodsReceiptForm(CompanyModelForm):
    class Meta:
        model = GoodsReceipt
        fields = ["supplier", "date", "warehouse", "reference", "notes"]
        widgets = {"date": DATE, "notes": forms.Textarea(attrs={"rows": 2})}


ORDER_LINES = line_formsets(PurchaseOrder, PurchaseOrderLine, LINE_FIELDS + ["account"])
BILL_LINES = line_formsets(Bill, BillLine, LINE_FIELDS + ["account", "serials", "batch_no", "expiry_date"])
RECEIPT_LINES = line_formsets(GoodsReceipt, GoodsReceiptLine,
                              ["item", "description", "qty", "unit_cost", "serials", "batch_no", "expiry_date"])
for formsets in (BILL_LINES, RECEIPT_LINES):
    base = formsets[0].form.base_fields
    base["serials"].widget = forms.TextInput(attrs={"placeholder": _("S/N, comma separated")})
    base["expiry_date"].widget = DATE


class SupplierPaymentForm(CompanyModelForm):
    class Meta:
        model = SupplierPayment
        fields = ["supplier", "date", "currency", "rate", "amount", "method", "bank_account", "cheque_number",
                  "cheque_due_date", "reference", "notes"]
        widgets = {"date": DATE, "cheque_due_date": DATE}

class SupplierCreditForm(CompanyModelForm):
    class Meta:
        model = SupplierCredit
        fields = ["supplier", "bill", "supplier_credit_no", "date", "warehouse", "currency", "rate", "reason", "reference",
                  "branch", "prices_include_tax", "tags", "notes"]
        widgets = {"date": DATE, "notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["bill"].queryset = Bill.objects.filter(company=self.company, status="posted").select_related("supplier")
        self.fields["bill"].label_from_instance = lambda b: f"{b.number} · {b.supplier.name} · {b.total:,.2f}"

    def clean(self):
        data = super().clean()
        bill, supplier = data.get("bill"), data.get("supplier")
        if bill and supplier and bill.supplier_id != supplier.pk:
            self.add_error("bill", _("This bill belongs to another supplier."))
        return data


SUPPLIER_CREDIT_LINES = line_formsets(SupplierCredit, SupplierCreditLine, LINE_FIELDS + ["account", "return_stock", "serials"])
for _fs in SUPPLIER_CREDIT_LINES:
    _fs.form.base_fields["serials"].widget = forms.TextInput(attrs={"placeholder": _("S/N, comma separated")})


class ApplySupplierCreditForm(forms.Form):
    bill = forms.ModelChoiceField(queryset=None, label=_("Bill"))
    amount = forms.DecimalField(label=_("Amount"), min_value=0, decimal_places=2)

    def __init__(self, *args, credit, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["bill"].queryset = Bill.objects.filter(company=credit.company, supplier=credit.supplier,
                                                           currency=credit.currency, status="posted")
        self.fields["bill"].label_from_instance = lambda b: f"{b.number} · {b.supplier_invoice_no} · {b.balance_due:,.2f}"
