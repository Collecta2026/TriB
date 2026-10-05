from django import forms
from django.utils.translation import gettext_lazy as _

from users.models import DOC_TYPES


class RuleForm(forms.Form):
    doc_type = forms.ChoiceField(label=_("Document type"), choices=DOC_TYPES)
    min_amount = forms.DecimalField(label=_("From amount (base currency)"), min_value=0, max_digits=19, decimal_places=2, initial=0)
    level1 = forms.ModelChoiceField(label=_("Level 1 approver"), queryset=None)
    level2 = forms.ModelChoiceField(label=_("Level 2 approver"), queryset=None, required=False)
    level3 = forms.ModelChoiceField(label=_("Level 3 approver"), queryset=None, required=False)

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("level1", "level2", "level3"):
            self.fields[name].queryset = company.roles.all()
