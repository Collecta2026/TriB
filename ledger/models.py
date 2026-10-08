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
    ("grni", _("Goods received not invoiced")),
    ("sales", _("Sales revenue")),
    ("cogs", _("Cost of goods sold")),
    ("stock_adjustment", _("Stock adjustments")),
    ("price_variance", _("Purchase price variance")),
    ("fixed_assets", _("Fixed assets")),
    ("accum_depreciation", _("Accumulated depreciation")),
    ("depreciation", _("Depreciation expense")),
    ("disposal_gain", _("Gain on disposal")),
    ("disposal_loss", _("Loss on disposal")),
    ("salaries_payable", _("Salaries payable")),
    ("social_insurance", _("Social insurance payable")),
    ("payroll_tax", _("Salary tax payable")),
    ("employee_deductions", _("Employee deductions payable")),
    ("overtime", _("Overtime")),
    ("salaries", _("Salaries & wages")),
    ("employer_si", _("Employer social insurance")),
    ("opening_equity", _("Opening balance equity")),
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


class TaxRate(Bilingual):
    KINDS = [("standard", _("Standard rated")), ("zero", _("Zero rated")), ("exempt", _("Exempt")),
             ("out_of_scope", _("Out of scope"))]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="tax_rates")
    rate = models.DecimalField(_("Rate %"), max_digits=6, decimal_places=2, default=0)
    kind = models.CharField(_("Type"), max_length=14, choices=KINDS, default="standard")
    is_default = models.BooleanField(_("Default"), default=False)
    is_active = models.BooleanField(_("Active"), default=True)

    class Meta:
        ordering = ["-is_default", "-rate", "name_en"]

    def __str__(self):
        return self.name


class Project(Bilingual):
    STATUSES = [("active", _("Active")), ("completed", _("Completed")), ("on_hold", _("On hold"))]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="projects")
    code = models.CharField(_("Code"), max_length=20)
    customer = models.ForeignKey("contacts.Customer", on_delete=models.PROTECT, null=True, blank=True,
                                 related_name="projects", verbose_name=_("Customer"))
    status = models.CharField(_("Status"), max_length=10, choices=STATUSES, default="active")
    start_date = models.DateField(_("Start date"), null=True, blank=True)
    end_date = models.DateField(_("End date"), null=True, blank=True)
    budget = models.DecimalField(_("Budget"), max_digits=19, decimal_places=2, default=0)
    notes = models.TextField(_("Notes"), blank=True)

    class Meta:
        ordering = ["code"]
        constraints = [models.UniqueConstraint(fields=["company", "code"], name="uniq_project_code")]

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
        ("invoice", _("Sales invoice")),
        ("customer_payment", _("Customer payment")),
        ("bill", _("Supplier bill")),
        ("supplier_payment", _("Supplier payment")),
        ("receipt_goods", _("Item receipt")),
        ("stock", _("Stock adjustment")),
        ("depreciation", _("Depreciation")),
        ("asset", _("Asset disposal")),
        ("bank", _("Bank transaction")),
        ("payroll", _("Payroll")),
    ]
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="entries")
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, null=True, blank=True)
    number = models.CharField(max_length=30)
    date = models.DateField(db_index=True)
    memo = models.CharField(max_length=300, blank=True)
    source = models.CharField(max_length=20, choices=SOURCES, default="manual")
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
    project = models.ForeignKey(Project, on_delete=models.PROTECT, null=True, blank=True, related_name="lines")
    reconciliation = models.ForeignKey("banking.Reconciliation", on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name="lines")
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
