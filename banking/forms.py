from django import forms
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from core.models import Branch

from .models import Bank, BankAccount


class BankAccountForm(forms.Form):
    kind = forms.ChoiceField(label=_("Type"), choices=BankAccount.KINDS)
    bank = forms.ModelChoiceField(label=_("Bank"), queryset=Bank.objects.none(), required=False,
                                  help_text=_("Missing a bank? Add it on the Banks page."))
    name_en = forms.CharField(label=_("Name (English)"), max_length=200, help_text=_("For example: CIB · USD current account"))
    name_ar = forms.CharField(label=_("Name (Arabic)"), max_length=200, required=False)
    currency = forms.ModelChoiceField(label=_("Currency"), queryset=None)
    account_number = forms.CharField(label=_("Account number"), max_length=40, required=False)
    iban = forms.CharField(label=_("IBAN"), max_length=40, required=False)
    branch = forms.ModelChoiceField(label=_("Branch"), queryset=Branch.objects.none(), required=False)

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["bank"].queryset = Bank.objects.filter(Q(company__isnull=True) | Q(company=company), is_active=True)
        self.fields["currency"].queryset = company.currencies.all()
        self.fields["currency"].initial = company.base_currency_id
        self.fields["branch"].queryset = company.branches.filter(is_active=True)

    def clean(self):
        data = super().clean()
        if data.get("kind") == "bank" and not data.get("bank"):
            self.add_error("bank", _("Choose the bank."))
        return data


class BankForm(forms.ModelForm):
    class Meta:
        model = Bank
        fields = ["name_en", "name_ar", "short_name", "country", "swift"]


class ChequeActionForm(forms.Form):
    action = forms.ChoiceField(choices=[("deposit", ""), ("clear", ""), ("bounce", ""), ("cancel", "")])
    date = forms.DateField(label=_("Date"), widget=forms.DateInput(attrs={"type": "date"}))
    bank_account = forms.ModelChoiceField(label=_("Bank account"), queryset=BankAccount.objects.none(), required=False)

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["bank_account"].queryset = company.bank_accounts.filter(kind="bank", is_active=True)
