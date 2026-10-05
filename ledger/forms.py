from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Account, CostCenter


class AccountForm(forms.ModelForm):
    class Meta:
        model = Account
        fields = ["code", "name_en", "name_ar", "parent", "type", "is_group", "currency", "is_active"]

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        self.fields["parent"].queryset = Account.objects.filter(company=company, is_group=True)
        self.fields["currency"].queryset = company.currencies.exclude(code=company.base_currency_id)
        if self.instance.pk and self.instance.is_system:
            for name in ("code", "type", "is_group", "parent"):
                self.fields[name].disabled = True

    def clean_code(self):
        code = self.cleaned_data["code"].strip()
        clash = Account.objects.filter(company=self.company, code=code).exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError(_("This code is already used."))
        return code

    def clean(self):
        data = super().clean()
        parent = data.get("parent")
        if parent and data.get("type") and parent.type != data["type"]:
            self.add_error("type", _("An account must have the same type as its parent."))
        if self.instance.pk and data.get("is_group") and self.instance.lines.exists():
            self.add_error("is_group", _("An account with postings cannot become a header account."))
        return data


class CostCenterForm(forms.ModelForm):
    class Meta:
        model = CostCenter
        fields = ["code", "name_en", "name_ar"]


class ReverseForm(forms.Form):
    date = forms.DateField(label=_("Reversal date"), widget=forms.DateInput(attrs={"type": "date"}))
