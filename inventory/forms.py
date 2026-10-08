from django import forms
from django.utils.translation import gettext_lazy as _

from core.forms_util import DATE, CompanyModelForm, line_formsets

from .models import (Category, Item, StockAdjustment, StockAdjustmentLine, StockTransfer, StockTransferLine,
                     Warehouse)


class CategoryForm(CompanyModelForm):
    class Meta:
        model = Category
        fields = ["name_en", "name_ar", "prefix"]

    def clean_prefix(self):
        return self.cleaned_data["prefix"].strip().upper()


class WarehouseForm(CompanyModelForm):
    class Meta:
        model = Warehouse
        fields = ["code", "name_en", "name_ar", "branch", "address", "is_active"]

    def clean_code(self):
        return self.cleaned_data["code"].strip().upper()


class ItemForm(CompanyModelForm):
    class Meta:
        model = Item
        fields = ["name_en", "name_ar", "sku", "type", "category", "tracking", "unit", "barcode", "sales_price",
                  "purchase_cost", "sales_tax", "purchase_tax", "income_account", "expense_account",
                  "inventory_account", "reorder_level", "description", "is_active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sku"].required = False
        for name in ("sales_price", "purchase_cost", "reorder_level"):
            self.fields[name].widget.attrs.update({"step": "any", "min": "0"})
        if self.instance.pk and self.instance.layers.exists():
            # Tracking decides how stock layers are kept; it can't change once stock has moved.
            self.fields["tracking"].disabled = True
            self.fields["tracking"].help_text = _("Fixed once stock has been received.")

    def clean_sku(self):
        sku = (self.cleaned_data.get("sku") or "").strip().upper()
        if sku and Item.objects.filter(company=self.company, sku=sku).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_("This SKU is already used by another item."))
        return sku

    def clean(self):
        data = super().clean()
        if data.get("type") != "inventory" and data.get("tracking") not in (None, "none"):
            self.add_error("tracking", _("Only stock items can track serial numbers or batches."))
        return data


class TransferForm(CompanyModelForm):
    class Meta:
        model = StockTransfer
        fields = ["date", "from_warehouse", "to_warehouse", "notes"]
        widgets = {"date": DATE}

    def clean(self):
        data = super().clean()
        if data.get("from_warehouse") and data.get("from_warehouse") == data.get("to_warehouse"):
            self.add_error("to_warehouse", _("Choose two different warehouses."))
        return data


class AdjustmentForm(CompanyModelForm):
    class Meta:
        model = StockAdjustment
        fields = ["date", "warehouse", "reason", "notes"]
        widgets = {"date": DATE}


class CountStartForm(forms.Form):
    warehouse = forms.ModelChoiceField(Warehouse.objects.none(), label=_("Warehouse"))
    date = forms.DateField(label=_("Date"), widget=DATE)
    category = forms.ModelChoiceField(Category.objects.none(), label=_("Category"), required=False,
                                      help_text=_("Leave empty to count every stock item."))

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["warehouse"].queryset = Warehouse.objects.filter(company=company, is_active=True)
        self.fields["category"].queryset = Category.objects.filter(company=company)


class LabelForm(forms.Form):
    category = forms.ModelChoiceField(Category.objects.none(), label=_("Category"), required=False)
    q = forms.CharField(label=_("SKU or name contains"), required=False,
                        widget=forms.TextInput(attrs={"placeholder": _("SKU or name contains")}))

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.filter(company=company)


TRANSFER_LINES = line_formsets(StockTransfer, StockTransferLine, ["item", "qty", "serials"], fk_name="transfer")
ADJUSTMENT_LINES = line_formsets(StockAdjustment, StockAdjustmentLine,
                                 ["item", "qty_change", "unit_cost", "serials", "batch_no", "expiry_date"],
                                 fk_name="adjustment")
for formsets in (TRANSFER_LINES, ADJUSTMENT_LINES):
    base = formsets[0].form.base_fields
    base["serials"].widget = forms.TextInput(attrs={"placeholder": _("S/N, comma separated")})
ADJUSTMENT_LINES[0].form.base_fields["expiry_date"].widget = DATE
ADJUSTMENT_LINES[0].form.base_fields["qty_change"].widget.attrs.update({"step": "any"})
