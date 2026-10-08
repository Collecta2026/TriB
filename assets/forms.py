from django import forms
from django.utils.translation import gettext_lazy as _

from banking.models import BankAccount
from core.forms_util import DATE, CompanyModelForm
from core.models import Branch
from inventory.models import Warehouse

from .models import Asset, AssetCategory


class AssetCategoryForm(CompanyModelForm):
    class Meta:
        model = AssetCategory
        fields = ["name_en", "name_ar", "useful_life_months", "asset_account", "depreciation_account", "expense_account"]


class AssetForm(CompanyModelForm):
    class Meta:
        model = Asset
        fields = ["name_en", "name_ar", "number", "category", "serial_no", "supplier", "purchase_date", "in_service_date",
                  "cost", "salvage_value", "useful_life_months", "opening_depreciation", "branch", "warehouse",
                  "location_detail", "custodian", "cost_center", "status", "notes"]
        widgets = {"purchase_date": DATE, "in_service_date": DATE, "notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["number"].required = False
        self.fields["number"].help_text = _("Leave empty to number it automatically (FA-00001).")
        self.fields["useful_life_months"].required = False
        self.fields["useful_life_months"].help_text = _("Leave empty to use the category's useful life.")
        self.fields["status"].choices = [c for c in Asset.STATUSES if c[0] != "disposed"]
        if self.instance.pk and self.instance.depreciation_lines.exists():
            for name in ("cost", "salvage_value", "useful_life_months", "in_service_date", "opening_depreciation",
                         "category"):
                self.fields[name].disabled = True
                self.fields[name].help_text = _("Fixed once depreciation has been posted.")

    def clean_number(self):
        number = (self.cleaned_data.get("number") or "").strip().upper()
        if number and Asset.objects.filter(company=self.company, number=number).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_("This asset number is already used."))
        return number

    def clean(self):
        data = super().clean()
        if data.get("category") and not data.get("useful_life_months"):
            data["useful_life_months"] = data["category"].useful_life_months
        cost, salvage, opening = data.get("cost"), data.get("salvage_value") or 0, data.get("opening_depreciation") or 0
        if cost is not None and salvage + opening > cost:
            self.add_error("opening_depreciation", _("Residual value plus earlier depreciation cannot exceed the cost."))
        return data


class DisposeForm(forms.Form):
    date = forms.DateField(label=_("Disposal date"), widget=DATE)
    proceeds = forms.DecimalField(label=_("Sale proceeds"), min_value=0, decimal_places=2, initial=0)
    bank_account = forms.ModelChoiceField(BankAccount.objects.none(), label=_("Received into"), required=False)

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["bank_account"].queryset = BankAccount.objects.filter(company=company, is_active=True)


class DepreciationForm(forms.Form):
    month = forms.DateField(label=_("Month"), widget=forms.DateInput(attrs={"type": "month"}, format="%Y-%m"),
                            input_formats=["%Y-%m", "%Y-%m-%d"])


class AssetCountForm(forms.Form):
    date = forms.DateField(label=_("Date"), widget=DATE)
    branch = forms.ModelChoiceField(Branch.objects.none(), label=_("Branch"), required=False)
    warehouse = forms.ModelChoiceField(Warehouse.objects.none(), label=_("Location"), required=False,
                                       help_text=_("Leave both empty to count every asset."))

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["branch"].queryset = Branch.objects.filter(company=company)
        self.fields["warehouse"].queryset = Warehouse.objects.filter(company=company, is_active=True)
