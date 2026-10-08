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
        ("settled", _("Settled by cash or transfer")),
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
    # The customer whose account a bounced cheque goes back to (set for customer payments by cheque).
    customer = models.ForeignKey("contacts.Customer", on_delete=models.PROTECT, null=True, blank=True,
                                 related_name="cheques", verbose_name=_("Customer"))
    cleared_on = models.DateField(_("Cleared on"), null=True, blank=True)
    bounced_on = models.DateField(_("Bounced on"), null=True, blank=True)
    bounce_reason = models.CharField(_("Reason returned"), max_length=200, blank=True)
    bounce_count = models.PositiveSmallIntegerField(_("Times returned"), default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["due_date", "id"]

    def __str__(self):
        return f"#{self.number}"

    @property
    def base_amount(self):
        return q2(self.amount * self.rate)


class ChequeEvent(models.Model):
    """The life of a cheque: deposited, cleared (from the bank statement or by hand), returned by the bank,
    resubmitted, settled in cash or by transfer, cancelled. Each event that moves money carries its journal."""

    ACTIONS = [("deposited", _("Deposited for collection")), ("cleared", _("Cleared")), ("bounced", _("Returned unpaid")),
               ("resubmitted", _("Resubmitted to the bank")), ("settled", _("Settled by cash or transfer")),
               ("cancelled", _("Cancelled"))]
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="+")
    cheque = models.ForeignKey(Cheque, on_delete=models.CASCADE, related_name="events")
    action = models.CharField(_("Action"), max_length=12, choices=ACTIONS)
    date = models.DateField(_("Date"))
    amount = models.DecimalField(_("Amount"), max_digits=19, decimal_places=2)
    bank_account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    journal_entry = models.ForeignKey("ledger.JournalEntry", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    statement_line = models.ForeignKey("banking.StatementLine", on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name="+")
    reference = models.CharField(_("Reference"), max_length=80, blank=True)
    note = models.CharField(_("Note"), max_length=300, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "id"]


class BankRule(models.Model):
    """If a statement line's description contains `contains`, suggest (or apply) this account."""

    DIRECTIONS = [("any", _("Money in or out")), ("in", _("Money in")), ("out", _("Money out"))]
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="bank_rules")
    name = models.CharField(_("Rule name"), max_length=120)
    contains = models.CharField(_("Description contains"), max_length=120)
    direction = models.CharField(_("Applies to"), max_length=3, choices=DIRECTIONS, default="any")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="+", verbose_name=_("Categorise as"))
    memo = models.CharField(_("Memo"), max_length=200, blank=True)
    auto_post = models.BooleanField(_("Post automatically when imported"), default=False)
    priority = models.PositiveSmallIntegerField(_("Priority"), default=10)
    is_active = models.BooleanField(_("Active"), default=True)

    class Meta:
        ordering = ["priority", "id"]

    def matches(self, line):
        if not self.is_active or self.contains.lower() not in (line.description or "").lower():
            return False
        return self.direction == "any" or (self.direction == "in") == (line.amount > 0)


class StatementLine(models.Model):
    STATUSES = [("new", _("For review")), ("matched", _("Matched")), ("posted", _("Categorised")),
                ("excluded", _("Excluded"))]
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="+")
    bank_account = models.ForeignKey(BankAccount, on_delete=models.CASCADE, related_name="statement_lines")
    date = models.DateField(_("Date"), db_index=True)
    description = models.CharField(_("Description"), max_length=300)
    reference = models.CharField(_("Reference"), max_length=80, blank=True)
    amount = models.DecimalField(_("Amount"), max_digits=19, decimal_places=2)  # + money in, − money out
    status = models.CharField(_("Status"), max_length=8, choices=STATUSES, default="new", db_index=True)
    journal_line = models.ForeignKey("ledger.JournalLine", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    rule = models.ForeignKey(BankRule, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    import_batch = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]


class Reconciliation(models.Model):
    STATUSES = [("open", _("In progress")), ("done", _("Reconciled"))]
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="+")
    bank_account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, related_name="reconciliations")
    statement_date = models.DateField(_("Statement end date"))
    statement_balance = models.DecimalField(_("Statement ending balance"), max_digits=19, decimal_places=2)
    opening_balance = models.DecimalField(max_digits=19, decimal_places=2, default=0)
    status = models.CharField(_("Status"), max_length=4, choices=STATUSES, default="open")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-statement_date", "-id"]
