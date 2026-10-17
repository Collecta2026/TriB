from django import forms
from django.utils.translation import gettext_lazy as _

from core import access
from core.forms_util import DATE, CompanyModelForm, line_formsets

from .models import (Category, Item, PriceRule, StockAdjustment, StockAdjustmentLine, StockTransfer, StockTransferLine,
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


IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp", "image/gif")
IMAGE_MAX = 2 * 1024 * 1024


class ItemForm(CompanyModelForm):
    picture = forms.FileField(label=_("Picture"), required=False,
                              help_text=_("JPG, PNG, WebP or GIF, up to 2 MB. Shown in the product list and on the product page."),
                              widget=forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png,image/webp,image/gif"}))
    remove_picture = forms.BooleanField(label=_("Remove the picture"), required=False)

    class Meta:
        model = Item
        fields = ["name_en", "name_ar", "sku", "type", "category", "tracking", "unit", "barcode", "sales_price",
                  "purchase_cost", "sales_tax", "purchase_tax", "income_account", "expense_account",
                  "inventory_account", "reorder_level", "description", "purchase_description", "is_active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 2}), "purchase_description": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sku"].required = False
        if not self.instance.has_image:
            self.fields.pop("remove_picture")
        for name in ("sales_price", "purchase_cost", "reorder_level"):
            self.fields[name].widget.attrs.update({"step": "any", "min": "0"})
        if not access.sees_costs(access.current()):
            self.fields.pop("purchase_cost")  # kept as it is; only people who may see costs can change it
        if self.instance.pk and self.instance.layers.exists():
            # Tracking decides how stock layers are kept; it can't change once stock has moved.
            self.fields["tracking"].disabled = True
            self.fields["tracking"].help_text = _("Fixed once stock has been received.")

    def clean_sku(self):
        sku = (self.cleaned_data.get("sku") or "").strip().upper()
        if sku and Item.objects.filter(company=self.company, sku=sku).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_("This SKU is already used by another item."))
        return sku

    def clean_picture(self):
        f = self.cleaned_data.get("picture")
        if f:
            if getattr(f, "content_type", "") not in IMAGE_TYPES:
                raise forms.ValidationError(_("Choose a JPG, PNG, WebP or GIF picture."))
            if f.size > IMAGE_MAX:
                raise forms.ValidationError(_("The picture is larger than 2 MB."))
        return f

    def clean(self):
        data = super().clean()
        if data.get("type") != "inventory" and data.get("tracking") not in (None, "none"):
            self.add_error("tracking", _("Only stock items can track serial numbers or batches."))
        return data

    def save_picture(self, item):
        """Store an uploaded picture on the item (or remove it), after the item itself is saved."""
        f = self.cleaned_data.get("picture")
        if f:
            item.image, item.image_type = f.read(), f.content_type
        elif self.cleaned_data.get("remove_picture"):
            item.image, item.image_type = None, ""
        else:
            return
        item.save(update_fields=["image", "image_type"])


class PriceRuleForm(CompanyModelForm):
    class Meta:
        model = PriceRule
        fields = ["name", "direction", "method", "amount", "rounding", "customers", "categories", "items", "start_date",
                  "end_date", "is_active"]
        widgets = {"start_date": DATE, "end_date": DATE,
                   "customers": forms.SelectMultiple(attrs={"size": 6, "data-multi": ""}),
                   "categories": forms.SelectMultiple(attrs={"size": 5, "data-multi": ""}),
                   "items": forms.SelectMultiple(attrs={"size": 8, "data-multi": ""})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from contacts.models import Customer
        self.fields["customers"].queryset = access.scope(Customer.objects.filter(company=self.company, is_active=True))
        self.fields["categories"].queryset = Category.objects.filter(company=self.company)
        self.fields["items"].queryset = Item.objects.filter(company=self.company, is_active=True)
        self.fields["amount"].widget.attrs.update({"step": "any", "min": "0"})

    def clean(self):
        data = super().clean()
        start, end = data.get("start_date"), data.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", _("The end date is before the start date."))
        if data.get("method") == "percent" and data.get("direction") == "down" and (data.get("amount") or 0) > 100:
            self.add_error("amount", _("A price can't go down by more than 100%."))
        return data


class StartingValueForm(forms.Form):
    """Opening stock for a product with no history: quantity, cost and date, posted as an opening adjustment."""
    item = forms.ModelChoiceField(queryset=None, label=_("Product"))
    warehouse = forms.ModelChoiceField(queryset=None, label=_("Warehouse"))
    as_of = forms.DateField(label=_("As of date"), widget=DATE)
    qty = forms.DecimalField(label=_("Initial quantity on hand"), min_value=0, max_digits=19, decimal_places=3)
    unit_cost = forms.DecimalField(label=_("Initial cost per unit"), min_value=0, max_digits=19, decimal_places=4)
    batch_no = forms.CharField(label=_("Batch"), max_length=60, required=False)
    expiry_date = forms.DateField(label=_("Expiry date"), required=False, widget=DATE)
    serials = forms.CharField(label=_("Serial numbers"), required=False, widget=forms.Textarea(attrs={"rows": 3}),
                              help_text=_("Serial-tracked products: one serial number per line, one per unit."))

    def __init__(self, *args, company, warehouses, **kwargs):
        super().__init__(*args, **kwargs)
        from django.db.models import Exists, OuterRef

        from .models import StockMove
        # Only products with no stock history yet; the rest are adjusted with a stock adjustment.
        self.fields["item"].queryset = (Item.objects.filter(company=company, type="inventory", is_active=True)
                                        .exclude(Exists(StockMove.objects.filter(item=OuterRef("pk")))).order_by("name_en"))
        self.fields["item"].widget.attrs["data-tracking-map"] = ""
        self.fields["warehouse"].queryset = warehouses
        for name in ("qty", "unit_cost"):
            self.fields[name].widget.attrs.update({"step": "any", "min": "0"})

    def clean(self):
        data = super().clean()
        item, qty = data.get("item"), data.get("qty")
        if item is None or qty is None:
            return data
        if qty <= 0:
            self.add_error("qty", _("Enter a quantity above zero."))
        if item.layers.exists() or item.moves.exists():
            self.add_error("item", _("This product already has stock history. Use a stock adjustment instead."))
        if item.tracking == "batch":
            if not data.get("batch_no"):
                self.add_error("batch_no", _("Enter the batch."))
            if not data.get("expiry_date"):
                self.add_error("expiry_date", _("Enter the expiry date."))
        if item.tracking == "serial":
            serials = [x.strip() for x in (data.get("serials") or "").replace(",", "\n").splitlines() if x.strip()]
            if qty is not None and len(serials) != qty:
                self.add_error("serials", _("Enter one serial number for each unit (%(n)s).") % {"n": qty.normalize()})
        return data


class TransferForm(CompanyModelForm):
    class Meta:
        model = StockTransfer
        fields = ["date", "from_warehouse", "to_warehouse", "notes"]
        widgets = {"date": DATE}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Stock leaves one of your own warehouses but may go to any of the company's warehouses.
        self.fields["to_warehouse"].queryset = Warehouse.objects.filter(company=self.company, is_active=True)

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
        self.fields["warehouse"].queryset = access.scope(Warehouse.objects.filter(company=company, is_active=True))
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
