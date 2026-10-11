"""Customer Hub (CRM): leads, opportunities, proposals, contracts, appointments, reviews, tasks and conversations."""
import secrets

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import Company, Currency

MONEY = {"max_digits": 19, "decimal_places": 2}
USER = settings.AUTH_USER_MODEL


class Lead(models.Model):
    SOURCES = [("website", _("Website")), ("referral", _("Referral")), ("exhibition", _("Exhibition or event")),
               ("call", _("Cold call")), ("social", _("Social media")), ("existing", _("Existing customer")),
               ("other", _("Other"))]
    STATUSES = [("new", _("New")), ("contacted", _("Contacted")), ("qualified", _("Qualified")),
                ("unqualified", _("Not a fit")), ("converted", _("Converted"))]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="+")
    name = models.CharField(_("Business or person"), max_length=200)
    contact_person = models.CharField(_("Contact person"), max_length=120, blank=True)
    email = models.EmailField(_("Email"), blank=True)
    phone = models.CharField(_("Phone"), max_length=40, blank=True)
    city = models.CharField(_("City"), max_length=80, blank=True)
    source = models.CharField(_("Source"), max_length=12, choices=SOURCES, default="other")
    status = models.CharField(_("Status"), max_length=12, choices=STATUSES, default="new")
    owner = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name=_("Owner"))
    notes = models.TextField(_("Notes"), blank=True)
    customer = models.ForeignKey("contacts.Customer", on_delete=models.SET_NULL, null=True, blank=True, related_name="leads",
                                 verbose_name=_("Customer"))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class Opportunity(models.Model):
    STAGES = [("new", _("New")), ("qualified", _("Qualified")), ("proposal", _("Proposal")),
              ("negotiation", _("Negotiation")), ("won", _("Won")), ("lost", _("Lost"))]
    OPEN = ("new", "qualified", "proposal", "negotiation")

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="+")
    title = models.CharField(_("Opportunity"), max_length=200)
    customer = models.ForeignKey("contacts.Customer", on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="opportunities", verbose_name=_("Customer"))
    lead = models.ForeignKey(Lead, on_delete=models.SET_NULL, null=True, blank=True, related_name="opportunities",
                             verbose_name=_("Lead"))
    stage = models.CharField(_("Stage"), max_length=12, choices=STAGES, default="new")
    value = models.DecimalField(_("Value"), default=0, **MONEY)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, verbose_name=_("Currency"))
    probability = models.PositiveSmallIntegerField(_("Probability %"), default=20)
    expected_close = models.DateField(_("Expected close"), null=True, blank=True)
    owner = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name=_("Owner"))
    quotation = models.ForeignKey("sales.Quotation", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                                  verbose_name=_("Estimate"))
    lost_reason = models.CharField(_("Reason lost"), max_length=200, blank=True)
    notes = models.TextField(_("Notes"), blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["expected_close", "-created_at"]

    def __str__(self):
        return self.title

    @property
    def party(self):
        return self.customer or self.lead

    @property
    def weighted(self):
        return self.value * self.probability / 100


class Proposal(models.Model):
    STATUSES = [("draft", _("Draft")), ("sent", _("Sent")), ("accepted", _("Accepted")), ("declined", _("Declined"))]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="+")
    number = models.CharField(_("Number"), max_length=30, blank=True)
    title = models.CharField(_("Title"), max_length=200)
    customer = models.ForeignKey("contacts.Customer", on_delete=models.PROTECT, related_name="proposals",
                                 verbose_name=_("Customer"))
    opportunity = models.ForeignKey(Opportunity, on_delete=models.SET_NULL, null=True, blank=True, related_name="proposals",
                                    verbose_name=_("Opportunity"))
    quotation = models.ForeignKey("sales.Quotation", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                                  verbose_name=_("Pricing from estimate"))
    date = models.DateField(_("Date"))
    valid_until = models.DateField(_("Valid until"), null=True, blank=True)
    cover_letter = models.TextField(_("Cover letter"), blank=True)
    scope = models.TextField(_("Scope and deliverables"), blank=True)
    terms = models.TextField(_("Terms and conditions"), blank=True)
    status = models.CharField(_("Status"), max_length=10, choices=STATUSES, default="draft")
    accepted_name = models.CharField(_("Accepted by"), max_length=120, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return self.number or self.title


class Contract(models.Model):
    STATUSES = [("draft", _("Draft")), ("sent", _("Sent")), ("active", _("Active")), ("expired", _("Expired")),
                ("cancelled", _("Cancelled"))]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="+")
    number = models.CharField(_("Number"), max_length=30, blank=True)
    title = models.CharField(_("Title"), max_length=200)
    customer = models.ForeignKey("contacts.Customer", on_delete=models.PROTECT, related_name="contracts",
                                 verbose_name=_("Customer"))
    start_date = models.DateField(_("Start date"))
    end_date = models.DateField(_("End date"), null=True, blank=True)
    value = models.DecimalField(_("Contract value"), default=0, **MONEY)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, verbose_name=_("Currency"))
    renewal_reminder_days = models.PositiveSmallIntegerField(_("Remind me before the end (days)"), default=30)
    terms = models.TextField(_("Terms"), blank=True)
    status = models.CharField(_("Status"), max_length=10, choices=STATUSES, default="draft")
    accepted_name = models.CharField(_("Accepted by"), max_length=120, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date", "-id"]

    def __str__(self):
        return self.number or self.title


class Appointment(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="+")
    title = models.CharField(_("Title"), max_length=200)
    customer = models.ForeignKey("contacts.Customer", on_delete=models.CASCADE, null=True, blank=True,
                                 related_name="appointments", verbose_name=_("Customer"))
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, null=True, blank=True, related_name="appointments",
                             verbose_name=_("Lead"))
    opportunity = models.ForeignKey(Opportunity, on_delete=models.SET_NULL, null=True, blank=True, related_name="appointments",
                                    verbose_name=_("Opportunity"))
    starts_at = models.DateTimeField(_("Starts"))
    duration = models.PositiveSmallIntegerField(_("Duration (minutes)"), default=60)
    location = models.CharField(_("Location"), max_length=200, blank=True)
    attendees = models.ManyToManyField(USER, blank=True, related_name="+", verbose_name=_("From your team"))
    notes = models.TextField(_("Notes"), blank=True)
    created_by = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["starts_at"]

    def __str__(self):
        return self.title


class Review(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="+")
    customer = models.ForeignKey("contacts.Customer", on_delete=models.CASCADE, related_name="reviews",
                                 verbose_name=_("Customer"))
    token = models.CharField(max_length=64, unique=True)
    rating = models.PositiveSmallIntegerField(_("Rating"), null=True, blank=True)
    comment = models.TextField(_("Comment"), blank=True)
    reviewer = models.CharField(_("Name"), max_length=120, blank=True)
    requested_by = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, related_name="+")
    requested_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-requested_at"]

    @classmethod
    def request(cls, customer, user):
        return cls.objects.create(company_id=customer.company_id, customer=customer, token=secrets.token_urlsafe(24),
                                  requested_by=user)


class Task(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="+")
    title = models.CharField(_("Task"), max_length=200)
    due_date = models.DateField(_("Due date"), null=True, blank=True)
    assignee = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                                 verbose_name=_("Assigned to"))
    customer = models.ForeignKey("contacts.Customer", on_delete=models.CASCADE, null=True, blank=True, related_name="tasks",
                                 verbose_name=_("Customer"))
    supplier = models.ForeignKey("contacts.Supplier", on_delete=models.CASCADE, null=True, blank=True, related_name="tasks",
                                 verbose_name=_("Supplier"))
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, null=True, blank=True, related_name="tasks", verbose_name=_("Lead"))
    opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE, null=True, blank=True, related_name="tasks",
                                    verbose_name=_("Opportunity"))
    notes = models.TextField(_("Notes"), blank=True)
    done = models.BooleanField(_("Done"), default=False)
    done_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["done", "due_date", "-created_at"]

    def __str__(self):
        return self.title


class Conversation(models.Model):
    KINDS = [("call", _("Phone call")), ("meeting", _("Meeting")), ("email", _("Email")), ("whatsapp", _("WhatsApp")),
             ("note", _("Note"))]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="+")
    customer = models.ForeignKey("contacts.Customer", on_delete=models.CASCADE, null=True, blank=True,
                                 related_name="conversations", verbose_name=_("Customer"))
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, null=True, blank=True, related_name="conversations",
                             verbose_name=_("Lead"))
    kind = models.CharField(_("Type"), max_length=10, choices=KINDS, default="call")
    happened_at = models.DateTimeField(_("When"))
    summary = models.TextField(_("What was said"))
    follow_up = models.DateField(_("Follow up on"), null=True, blank=True)
    by = models.ForeignKey(USER, on_delete=models.SET_NULL, null=True, related_name="+", verbose_name=_("By"))

    class Meta:
        ordering = ["-happened_at"]
