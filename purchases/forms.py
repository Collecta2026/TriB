from django import forms
from django.utils.translation import gettext_lazy as _

from core.forms_util import DATE, CompanyModelForm, LineForm, line_formsets

from .models import Bill, BillLine, GoodsReceipt, GoodsReceiptLine, PurchaseOrder, PurchaseOrderLine, SupplierPayment

LINE_FIELDS = ["item", "description", "qty", "unit_price", "discount_pct", "tax_rate", "project"]


class PurchaseOrderForm(CompanyModelForm):
    class Meta:
        model = PurchaseOrder
        fields = ["supplier", "date", "expected_date", "warehouse", "currency", "rate", "reference", "branch", "notes"]
        widgets = {"date": DATE, "expected_date": DATE, "notes": forms.Textarea(attrs={"rows": 2})}


class BillForm(CompanyModelForm):
    class Meta:
        model = Bill
        fields = ["supplier", "supplier_invoice_no", "date", "due_date", "currency", "rate", "warehouse", "reference",
                  "branch", "notes"]
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
