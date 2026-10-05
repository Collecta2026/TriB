from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from core.models import Bilingual, Branch, Company, Currency

ACCOUNT_TYPES = [
    ("asset", _("Asset")),
    ("liability", _("Liability")),
    ("equity", _("Equity")),
    ("income", _("Income")),
    ("expense", _("Expense")),
]

# Accounts the system needs to find automatically (cash, banks, cheques, taxes...).
SUBTYPES = [
    ("", _("General")),
    ("cash", _("Cash")),
    ("bank", _("Bank")),
    ("receivable", _("Customers (receivable)")),
    ("payable", _("Suppliers (payable)")),
    ("notes_receivable", _("Cheques in the safe (notes receivable)")),
    ("cheques_collection", _("Cheques under collection")),
    ("notes_payable", _("Cheques issued (notes payable)")),
    ("inventory", _("Inventory")),
    ("goods_in_transit", _("Goods in transit")),
    ("custody", _("Custody & advances")),
    ("vat_input", _("VAT input")),
    ("vat_output", _("VAT output")),
    ("wht_receivable", _("Withholding tax receivable")),
    ("wht_payable", _("Withholding tax payable")),
    ("retained_earnings", _("Retained earnings")),
    ("fx_gain", _("Exchange gains")),
    ("fx_loss", _("Exchange losses")),
]

DEBIT_NATURE = {"asset", "expense"}


class Account(Bilingual):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="accounts")
    code = models.CharField(_("Code"), max_length=20)
    parent = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="children",
                               verbose_name=_("Parent account"))
    type = models.CharField(_("Type"), max_length=12, choices=ACCOUNT_TYPES)
    subtype = models.CharField(_("System role"), max_length=24, choices=SUBTYPES, blank=True)
    is_group = models.BooleanField(_("Header account (no postings)"), default=False)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, null=True, blank=True,
                                 verbose_name=_("Currency (foreign-currency accounts only)"))
    is_active = models.BooleanField(_("Active"), default=True)
    is_system = models.BooleanField(default=False)

    class Meta:
        ordering = ["code"]
        constraints = [models.UniqueConstraint(fields=["company", "code"], name="uniq_account_code")]

    def __str__(self):
        return f"{self.code} · {self.name}"

    @property
    def debit_nature(self):
        return self.type in DEBIT_NATURE

    @property
    def depth(self):
        depth, node = 0, self.parent
        while node is not None:
            depth, node = depth + 1, node.parent
        return depth


class CostCenter(Bilingual):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="cost_centers")
    code = models.CharField(_("Code"), max_length=20)
    is_active = models.BooleanField(_("Active"), default=True)

    class Meta:
        ordering = ["code"]
        constraints = [models.UniqueConstraint(fields=["company", "code"], name="uniq_cost_center_code")]

    def __str__(self):
        return f"{self.code} · {self.name}"


class JournalEntry(models.Model):
    SOURCES = [
        ("manual", _("Manual journal")),
        ("receipt", _("Receipt voucher")),
        ("payment", _("Payment voucher")),
        ("journal", _("Journal voucher")),
        ("cheque", _("Cheque")),
        ("opening", _("Opening balance")),
        ("reversal", _("Reversal")),
    ]
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="entries")
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, null=True, blank=True)
    number = models.CharField(max_length=30)
    date = models.DateField(db_index=True)
    memo = models.CharField(max_length=300, blank=True)
    source = models.CharField(max_length=12, choices=SOURCES, default="manual")
    source_ref = models.CharField(max_length=40, blank=True)
    reversal_of = models.OneToOneField("self", on_delete=models.PROTECT, null=True, blank=True, related_name="reversed_by")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]
        constraints = [models.UniqueConstraint(fields=["company", "number"], name="uniq_entry_number")]

    def __str__(self):
        return self.number

    @property
    def total(self):
        return sum((line.debit for line in self.lines.all()), 0)


class JournalLine(models.Model):
    entry = models.ForeignKey(JournalEntry, on_delete=models.CASCADE, related_name="lines")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="lines")
    cost_center = models.ForeignKey(CostCenter, on_delete=models.PROTECT, null=True, blank=True)
    description = models.CharField(max_length=300, blank=True)
    # Base-currency amounts. These are what the ledger balances on.
    debit = models.DecimalField(max_digits=19, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=19, decimal_places=2, default=0)
    # The original transaction currency and amount, kept for foreign-currency statements.
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    amount_fc = models.DecimalField(max_digits=19, decimal_places=2, default=0)
    rate = models.DecimalField(max_digits=18, decimal_places=6, default=1)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(condition=Q(debit__gte=0) & Q(credit__gte=0), name="line_amounts_not_negative"),
            models.CheckConstraint(condition=~(Q(debit__gt=0) & Q(credit__gt=0)), name="line_one_side_only"),
        ]
