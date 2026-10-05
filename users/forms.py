from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password
from django.utils.translation import gettext_lazy as _

from .models import DOC_TYPES, Role, User


class LoginForm(AuthenticationForm):
    username = forms.EmailField(label=_("Email"), widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "email"}))


class MemberForm(forms.Form):
    full_name = forms.CharField(label=_("Full name"), max_length=150)
    email = forms.EmailField(label=_("Email"))
    phone = forms.CharField(label=_("Mobile"), max_length=40, required=False)
    preferred_language = forms.ChoiceField(label=_("Language"), choices=[("en", "English"), ("ar", "العربية")])
    password = forms.CharField(
        label=_("Temporary password"), widget=forms.PasswordInput, required=False,
        help_text=_("Give this to the person; they can change it after signing in. Not needed for existing users."),
    )
    roles = forms.ModelMultipleChoiceField(queryset=Role.objects.none(), widget=forms.CheckboxSelectMultiple, label=_("Roles"))
    branches = forms.ModelMultipleChoiceField(
        queryset=None, widget=forms.CheckboxSelectMultiple, required=False, label=_("Branches"),
        help_text=_("Leave empty to allow every branch."),
    )
    is_active = forms.BooleanField(label=_("Active"), required=False, initial=True)

    def __init__(self, *args, company, editing=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company, self.editing = company, editing
        self.fields["roles"].queryset = company.roles.all()
        self.fields["branches"].queryset = company.branches.filter(is_active=True)
        if editing is not None:
            for name in ("email", "password"):
                self.fields.pop(name)

    def clean(self):
        data = super().clean()
        if self.editing is None:
            email = (data.get("email") or "").lower()
            existing = User.objects.filter(email__iexact=email).first()
            if existing and existing.memberships.filter(company=self.company).exists():
                self.add_error("email", _("This person is already a user of this company."))
            if not existing:
                if not data.get("password"):
                    self.add_error("password", _("Set a temporary password for the new user."))
                else:
                    try:
                        validate_password(data["password"])
                    except forms.ValidationError as exc:
                        self.add_error("password", exc)
        return data


class RoleForm(forms.ModelForm):
    class Meta:
        model = Role
        fields = ["name_en", "name_ar"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for doc_type, label in DOC_TYPES:
            self.fields[f"limit_{doc_type}"] = forms.DecimalField(
                label=_("Approval limit: %(doc)s") % {"doc": label}, required=False, min_value=0,
                max_digits=19, decimal_places=2, help_text=_("Largest amount in base currency. Empty means cannot approve."),
            )
