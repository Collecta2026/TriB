"""Form helpers: limit every drop-down to the current company, and standard widgets."""
from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory
from django.utils.translation import gettext_lazy as _

DATE = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


def scope_fields(form, company):
    """Restrict choice fields to records of `company` (and to sensible subsets for shared models)."""
    from core.models import Currency
    from ledger.models import Account, Project, TaxRate

    for name, field in form.fields.items():
        if not isinstance(field, forms.ModelChoiceField):
            if isinstance(field.widget, forms.DateInput):
                field.widget = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
            continue
        model = field.queryset.model
        if model is Currency:
            field.queryset = company.currencies.all()
        elif model is Account:
            field.queryset = Account.objects.filter(company=company, is_group=False, is_active=True)
        elif model is TaxRate:
            field.queryset = TaxRate.objects.filter(company=company, is_active=True)
        elif model is Project:
            field.queryset = Project.objects.filter(company=company, status="active")
        elif hasattr(model, "company"):
            qs = model.objects.filter(company=company)
            if hasattr(model, "is_active"):
                qs = qs.filter(is_active=True)
            field.queryset = qs


class CompanyModelForm(forms.ModelForm):
    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        scope_fields(self, company)
        if "rate" in self.fields:
            self.fields["rate"].required = False
            self.fields["rate"].help_text = _("Leave at 1 to use the latest saved rate for foreign currencies.")

    def clean(self):
        data = super().clean()
        currency, day = data.get("currency"), data.get("date")
        if "rate" in self.fields and currency and day:
            from core.models import ExchangeRate
            from decimal import Decimal
            rate = data.get("rate") or Decimal("1")
            if currency.code == self.company.base_currency_id:
                rate = Decimal("1")
            elif rate == 1:
                saved = ExchangeRate.rate_for(self.company, currency, day)
                if saved is None:
                    self.add_error("rate", _("Enter the exchange rate, or save one in Settings."))
                else:
                    rate = saved
            data["rate"] = rate
        return data


class LineForm(CompanyModelForm):
    """Line items: amounts optional on blank rows, small inputs."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("qty", "unit_price", "discount_pct", "unit_cost"):
            if name in self.fields:
                self.fields[name].widget.attrs.update({"step": "any", "min": "0"})
        if "description" in self.fields:
            self.fields["description"].required = False

    def clean(self):
        data = super().clean()
        item = data.get("item")
        # Consumables must arrive with their batch and expiry date so the warehouse knows what expires when.
        # Bill lines for goods already received on an item receipt carry them on the receipt instead.
        if ("expiry_date" in self.fields and item is not None and item.is_stocked and item.tracking == "batch"
                and not getattr(self.instance, "receipt_line_id", None) and not data.get("DELETE")
                and (data.get("qty_change") is None or data["qty_change"] > 0)):
            if not data.get("batch_no"):
                self.add_error("batch_no", _("Enter the batch number."))
            if not data.get("expiry_date"):
                self.add_error("expiry_date", _("Enter the expiry date."))
        return data


class CompanyLineFormSet(BaseInlineFormSet):
    def __init__(self, *args, company, **kwargs):
        self.company = company
        super().__init__(*args, **kwargs)

    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        kwargs["company"] = self.company
        return kwargs

    @property
    def empty_form(self):
        form = self.form(auto_id=self.auto_id, prefix=self.add_prefix("__prefix__"), empty_permitted=True,
                         use_required_attribute=False, company=self.company)
        self.add_fields(form, None)
        return form

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        live = [f for f in self.forms if f.cleaned_data and not f.cleaned_data.get("DELETE")
                and (f.cleaned_data.get("item") or f.cleaned_data.get("description") or f.cleaned_data.get("account"))]
        if not live:
            raise forms.ValidationError(_("Add at least one line."))


def line_formsets(parent, line_model, fields, form=LineForm, fk_name="document"):
    """(existing-document formset, new-document formset with two blank rows)."""
    meta = type("Meta", (), {"model": line_model, "fields": fields})
    form_class = type(f"{line_model.__name__}Form", (form,), {"Meta": meta})
    kwargs = {"form": form_class, "formset": CompanyLineFormSet, "fields": fields, "can_delete": True, "fk_name": fk_name}
    return (inlineformset_factory(parent, line_model, extra=0, **kwargs),
            inlineformset_factory(parent, line_model, extra=2, **kwargs))
