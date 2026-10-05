from django import forms
from django.contrib.auth.password_validation import validate_password
from django.utils.translation import gettext_lazy as _

from users.models import User

from .models import Branch, Company, Currency, ExchangeRate
from .reference import CURRENCIES


class SetupForm(forms.Form):
    company_name_en = forms.CharField(label=_("Company name (English)"), max_length=200)
    company_name_ar = forms.CharField(label=_("Company name (Arabic)"), max_length=200, required=False)
    base_currency = forms.ChoiceField(
        label=_("Base currency"), initial="EGP",
        choices=[(c[0], f"{c[0]} · {c[1]}") for c in CURRENCIES],
        help_text=_("The currency your books are kept in. It cannot be changed later."),
    )
    full_name = forms.CharField(label=_("Your full name"), max_length=150)
    email = forms.EmailField(label=_("Your email"))
    password1 = forms.CharField(label=_("Password"), widget=forms.PasswordInput, min_length=10)
    password2 = forms.CharField(label=_("Repeat password"), widget=forms.PasswordInput)

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(_("This email is already registered."))
        return email

    def clean(self):
        data = super().clean()
        if data.get("password1") and data.get("password1") != data.get("password2"):
            self.add_error("password2", _("The passwords do not match."))
        elif data.get("password1"):
            try:
                validate_password(data["password1"])
            except forms.ValidationError as exc:
                self.add_error("password1", exc)
        return data


class CompanyForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = ["name_en", "name_ar", "tax_id", "commercial_register", "phone", "email", "address",
                  "fiscal_year_start_month", "lock_date", "auto_post_on_approval", "enforce_sod"]
        widgets = {"lock_date": forms.DateInput(attrs={"type": "date"}), "address": forms.Textarea(attrs={"rows": 2})}


class CurrenciesForm(forms.Form):
    currencies = forms.ModelMultipleChoiceField(
        queryset=Currency.objects.all(), widget=forms.CheckboxSelectMultiple, required=False, label=_("Currencies in use")
    )


class AddonsForm(forms.Form):
    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        for key, label in Company.ADDONS:
            self.fields[key] = forms.BooleanField(label=label, required=False, initial=company.addon_enabled(key))


class BranchForm(forms.ModelForm):
    class Meta:
        model = Branch
        fields = ["code", "name_en", "name_ar"]


class RateForm(forms.ModelForm):
    class Meta:
        model = ExchangeRate
        fields = ["currency", "date", "rate"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        self.fields["currency"].queryset = company.currencies.exclude(code=company.base_currency_id)
        self.fields["rate"].help_text = _("Units of base currency for one unit of this currency.")

    def clean_rate(self):
        rate = self.cleaned_data["rate"]
        if rate <= 0:
            raise forms.ValidationError(_("The rate must be greater than zero."))
        return rate
