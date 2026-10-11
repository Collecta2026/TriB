from django import forms
from django.utils.translation import gettext_lazy as _

from core import access
from core.forms_util import DATE, CompanyModelForm

from .models import Appointment, Contract, Conversation, Lead, Opportunity, Proposal, Task

DATETIME = forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")


class CrmForm(CompanyModelForm):
    """Company-scoped form; people pickers list this company's active users."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from users.models import User

        team = User.objects.filter(memberships__company=self.company, memberships__is_active=True).distinct()
        for name in ("owner", "assignee", "attendees"):
            if name in self.fields:
                self.fields[name].queryset = team
        for name in ("notes", "cover_letter", "scope", "terms", "summary"):
            if name in self.fields:
                self.fields[name].widget = forms.Textarea(attrs={"rows": 4})


class LeadForm(CrmForm):
    class Meta:
        model = Lead
        fields = ["name", "contact_person", "email", "phone", "city", "source", "status", "owner", "notes"]


class OpportunityForm(CrmForm):
    class Meta:
        model = Opportunity
        fields = ["title", "customer", "lead", "stage", "value", "currency", "probability", "expected_close", "owner",
                  "quotation", "lost_reason", "notes"]
        widgets = {"expected_close": DATE}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from sales.models import Quotation
        self.fields["quotation"].queryset = access.scope(Quotation.objects.filter(company=self.company).exclude(number=""))
        self.fields["probability"].widget.attrs.update({"min": 0, "max": 100})

    def clean(self):
        data = super().clean()
        if not data.get("customer") and not data.get("lead"):
            self.add_error("customer", _("Choose a customer or a lead."))
        return data


class ProposalForm(CrmForm):
    class Meta:
        model = Proposal
        fields = ["title", "customer", "opportunity", "quotation", "date", "valid_until", "cover_letter", "scope", "terms"]
        widgets = {"date": DATE, "valid_until": DATE}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from sales.models import Quotation
        self.fields["quotation"].queryset = access.scope(Quotation.objects.filter(company=self.company).exclude(number=""))
        self.fields["opportunity"].queryset = access.scope(Opportunity.objects.filter(company=self.company))


class ContractForm(CrmForm):
    class Meta:
        model = Contract
        fields = ["title", "customer", "start_date", "end_date", "value", "currency", "renewal_reminder_days", "status", "terms"]
        widgets = {"start_date": DATE, "end_date": DATE}

    def clean(self):
        data = super().clean()
        if data.get("end_date") and data.get("start_date") and data["end_date"] < data["start_date"]:
            self.add_error("end_date", _("The end date is before the start date."))
        return data


class AppointmentForm(CrmForm):
    class Meta:
        model = Appointment
        fields = ["title", "customer", "lead", "opportunity", "starts_at", "duration", "location", "attendees", "notes"]
        widgets = {"starts_at": DATETIME, "attendees": forms.CheckboxSelectMultiple}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["starts_at"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["opportunity"].queryset = access.scope(Opportunity.objects.filter(company=self.company,
                                                                                 stage__in=Opportunity.OPEN))


class TaskForm(CrmForm):
    class Meta:
        model = Task
        fields = ["title", "due_date", "assignee", "customer", "supplier", "lead", "opportunity", "notes"]
        widgets = {"due_date": DATE}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["opportunity"].queryset = access.scope(Opportunity.objects.filter(company=self.company))


class ConversationForm(CrmForm):
    class Meta:
        model = Conversation
        fields = ["customer", "lead", "kind", "happened_at", "summary", "follow_up"]
        widgets = {"happened_at": DATETIME, "follow_up": DATE}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["happened_at"].input_formats = ["%Y-%m-%dT%H:%M"]

    def clean(self):
        data = super().clean()
        if not data.get("customer") and not data.get("lead"):
            self.add_error("customer", _("Choose a customer or a lead."))
        return data


class AcceptForm(forms.Form):
    name = forms.CharField(label=_("Your full name"), max_length=120)
    agree = forms.BooleanField(label=_("I accept on behalf of my company"))


class ReviewForm(forms.Form):
    rating = forms.TypedChoiceField(label=_("Your rating"), coerce=int, choices=[(i, "★" * i) for i in range(5, 0, -1)],
                                    widget=forms.RadioSelect)
    comment = forms.CharField(label=_("Comment"), required=False, widget=forms.Textarea(attrs={"rows": 4}), max_length=2000)
    reviewer = forms.CharField(label=_("Your name"), required=False, max_length=120)
