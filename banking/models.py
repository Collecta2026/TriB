from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import Bilingual, Branch, Company, Currency
from ledger.models import Account
from ledger.services import q2

COUNTRIES = [
    ("EG", _("Egypt")), ("AE", _("United Arab Emirates")), ("SA", _("Saudi Arabia")), ("KW", _("Kuwait")),
    ("QA", _("Qatar")), ("BH", _("Bahrain")), ("OM", _("Oman")), ("JO", _("Jordan")), ("GB", _("United Kingdom")),
    ("XX", _("Other")),
]


class Bank(Bilingual):
    """A bank in the shared list (company empty) or one a company added for itself."""

    company = models.ForeignKey(Company, on_delete=models.CASCADE, null=True, blank=True, related_name="custom_banks")
    short_name = models.CharField(_("Short name"), max_length=20)
    country = models.CharField(_("Country"), max_length=2, choices=COUNTRIES, default="EG")
    swift = models.CharField(_("SWIFT / BIC"), max_length=11, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["country", "name_en"]


class BankAccount(Bilingual):
    KINDS = [("bank", _("Bank account")), ("cash", _("Cash box"))]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="bank_accounts")
    kind = models.CharField(_("Type"), max_length=4, choices=KINDS, default="bank")
    bank = models.ForeignKey(Bank, on_delete=models.PROTECT, null=True, blank=True, verbose_name=_("Bank"))
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, null=True, blank=True, verbose_name=_("Branch"))
    account_number = models.CharField(_("Account number"), max_length=40, blank=True)
    iban = models.CharField(_("IBAN"), max_length=40, blank=True)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, verbose_name=_("Currency"))
    gl_account = models.OneToOneField(Account, on_delete=models.PROTECT, related_name="bank_account")
    is_active = models.BooleanField(_("Active"), default=True)

    class Meta:
        ordering = ["kind", "gl_account__code"]

    @property
    def masked_number(self):
        return f"•••• {self.account_number[-4:]}" if self.account_number else ""


class Cheque(models.Model):
    DIRECTIONS = [("in", _("Received")), ("out", _("Issued"))]
    STATUSES = [
        ("in_safe", _("In the safe")),
        ("under_collection", _("Under collection")),
        ("cleared", _("Cleared")),
        ("bounced", _("Bounced")),
        ("issued", _("Issued")),
        ("cancelled", _("Cancelled")),
    ]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="cheques")
    direction = models.CharField(_("Direction"), max_length=3, choices=DIRECTIONS)
    number = models.CharField(_("Cheque number"), max_length=40)
    drawee_bank = models.CharField(_("Drawn on bank"), max_length=120, blank=True)
    party_name = models.CharField(_("Customer / supplier"), max_length=200)
    amount = models.DecimalField(_("Amount"), max_digits=19, decimal_places=2)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    rate = models.DecimalField(max_digits=18, decimal_places=6, default=1)
    issue_date = models.DateField(_("Cheque date"))
    due_date = models.DateField(_("Due date"), db_index=True)
    status = models.CharField(_("Status"), max_length=20, choices=STATUSES)
    bank_account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, null=True, blank=True,
                                     verbose_name=_("Our bank account"))
    # Where the money came from / went to, so a bounced cheque can be put back.
    counter_account = models.ForeignKey(Account, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    source_ref = models.CharField(max_length=40, blank=True)
    notes = models.CharField(_("Notes"), max_length=300, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["due_date", "id"]

    def __str__(self):
        return f"#{self.number}"

    @property
    def base_amount(self):
        return q2(self.amount * self.rate)
