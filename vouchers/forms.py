from decimal import Decimal

from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory
from django.utils.translation import gettext_lazy as _

from core.models import ExchangeRate
from ledger.models import Account, CostCenter

from .models import Voucher, VoucherLine

DATE = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class VoucherForm(forms.ModelForm):
    class Meta:
        model = Voucher
        fields = ["date", "branch", "party_name", "method", "bank_account", "currency", "rate", "description",
                  "cheque_number", "cheque_bank", "cheque_due_date"]
        widgets = {"date": DATE, "cheque_due_date": DATE}

    def __init__(self, *args, company, kind, **kwargs):
        super().__init__(*args, **kwargs)
        self.company, self.kind = company, kind
        self.fields["branch"].queryset = company.branches.filter(is_active=True)
        self.fields["currency"].queryset = company.currencies.all()
        self.fields["bank_account"].queryset = company.bank_accounts.filter(is_active=True).select_related("currency")
        self.fields["rate"].required = False
        self.fields["rate"].help_text = _("Leave as 1 for the base currency. For other currencies, the latest saved rate is used if you leave it at 1.")
        if kind == "journal":
            for name in ("party_name", "method", "bank_account", "cheque_number", "cheque_bank", "cheque_due_date"):
                self.fields.pop(name)
        else:
            self.fields["method"].required = True
            self.fields["party_name"].label = _("Received from") if kind == "receipt" else _("Paid to")
            if kind == "receipt":
                self.fields["bank_account"].help_text = _("Not needed for cheques: they go to the safe first.")

    def clean(self):
        data = super().clean()
        currency, date = data.get("currency"), data.get("date")
        rate = data.get("rate") or Decimal("1")
        if currency and date:
            if currency.code == self.company.base_currency_id:
                rate = Decimal("1")
            elif rate == 1:
                saved = ExchangeRate.rate_for(self.company, currency, date)
                if saved is None:
                    self.add_error("rate", _("Enter the exchange rate, or save one in Settings."))
                else:
                    rate = saved
        data["rate"] = rate
        return data


class LineForm(forms.ModelForm):
    class Meta:
        model = VoucherLine
        fields = ["account", "cost_center", "description", "amount", "debit", "credit"]

    def __init__(self, *args, company, kind, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = Account.objects.filter(company=company, is_group=False, is_active=True)
        self.fields["cost_center"].queryset = CostCenter.objects.filter(company=company, is_active=True)
        for name in ("amount", "debit", "credit"):
            self.fields[name].required = False
            self.fields[name].widget.attrs.update({"step": "0.01", "min": "0"})
        if kind == "journal":
            self.fields.pop("amount")
        else:
            self.fields.pop("debit")
            self.fields.pop("credit")

    def clean(self):
        data = super().clean()
        for name in ("amount", "debit", "credit"):
            if name in self.fields and data.get(name) is None:
                data[name] = Decimal("0")
        return data


class BaseLineFormSet(BaseInlineFormSet):
    def __init__(self, *args, company, kind, **kwargs):
        self.company, self.kind = company, kind
        super().__init__(*args, **kwargs)

    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        kwargs.update(company=self.company, kind=self.kind)
        return kwargs

    @property
    def empty_form(self):
        form = self.form(auto_id=self.auto_id, prefix=self.add_prefix("__prefix__"), empty_permitted=True,
                         use_required_attribute=False, company=self.company, kind=self.kind)
        self.add_fields(form, None)
        return form

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        lines = [f for f in self.forms if f.cleaned_data and not f.cleaned_data.get("DELETE") and f.cleaned_data.get("account")]
        if not lines:
            raise forms.ValidationError(_("Add at least one line."))


LineFormSet = inlineformset_factory(Voucher, VoucherLine, form=LineForm, formset=BaseLineFormSet, extra=0, can_delete=True)
NewLineFormSet = inlineformset_factory(Voucher, VoucherLine, form=LineForm, formset=BaseLineFormSet, extra=2, can_delete=True)


class DecisionForm(forms.Form):
    comment = forms.CharField(label=_("Comment"), max_length=300, required=False)
