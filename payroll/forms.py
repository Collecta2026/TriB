from django import forms
from django.forms import modelformset_factory
from django.utils.translation import gettext_lazy as _

from banking.models import BankAccount
from core.forms_util import DATE

from .models import DelegationBand, PayrollSettings, Remittance

MONTHS = [(i, _(m)) for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August",
                                           "September", "October", "November", "December"], start=1)]


class NewRunForm(forms.Form):
    year = forms.IntegerField(label=_("Year"), min_value=2000, max_value=2100)
    month = forms.TypedChoiceField(label=_("Month"), choices=MONTHS, coerce=int)


class PayForm(forms.Form):
    pay_date = forms.DateField(label=_("Payment date"), widget=DATE)
    bank_account = forms.ModelChoiceField(BankAccount.objects.none(), label=_("Bank & InstaPay salaries paid from"))
    cash_account = forms.ModelChoiceField(BankAccount.objects.none(), label=_("Cash salaries paid from"), required=False)

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        accounts = BankAccount.objects.filter(company=company, is_active=True)
        self.fields["bank_account"].queryset = accounts.exclude(kind="cash")
        self.fields["cash_account"].queryset = accounts.filter(kind="cash")


class RemitForm(forms.Form):
    kind = forms.ChoiceField(choices=Remittance.KINDS, widget=forms.HiddenInput)
    pay_date = forms.DateField(label=_("Payment date"), widget=DATE)
    bank_account = forms.ModelChoiceField(BankAccount.objects.none(), label=_("Paid from"))
    reference = forms.CharField(label=_("Reference"), max_length=80, required=False)

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["bank_account"].queryset = BankAccount.objects.filter(company=company, is_active=True)


class SettingsForm(forms.ModelForm):
    class Meta:
        model = PayrollSettings
        exclude = ["company"]

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        accounts = BankAccount.objects.filter(company=company, is_active=True)
        self.fields["pay_bank_account"].queryset = accounts.exclude(kind="cash")
        self.fields["pay_cash_account"].queryset = accounts.filter(kind="cash")


BandFormSet = modelformset_factory(DelegationBand, fields=["name", "min_amount", "max_amount", "requires_fm",
                                                          "requires_md", "order"], extra=1, can_delete=True)
