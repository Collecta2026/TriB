from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.utils.translation import gettext_lazy as _

from contacts.models import Supplier
from core.models import Bilingual, Branch, Company
from inventory.models import Warehouse
from ledger.models import Account, CostCenter, JournalEntry

MONEY = {"max_digits": 19, "decimal_places": 2}


class AssetCategory(Bilingual):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="asset_categories")
    useful_life_months = models.PositiveIntegerField(_("Useful life (months)"), default=60)
    asset_account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="+", verbose_name=_("Asset account"))
    depreciation_account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="+",
                                             verbose_name=_("Accumulated depreciation account"))
    expense_account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="+",
                                        verbose_name=_("Depreciation expense account"))

    class Meta:
        ordering = ["name_en"]
        verbose_name_plural = "asset categories"


class Asset(Bilingual):
    STATUSES = [("active", _("In use")), ("idle", _("Not in use")), ("disposed", _("Disposed")), ("missing", _("Missing"))]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="assets")
    number = models.CharField(_("Asset number"), max_length=30, blank=True)
    category = models.ForeignKey(AssetCategory, on_delete=models.PROTECT, verbose_name=_("Category"))
    serial_no = models.CharField(_("Serial number"), max_length=80, blank=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, null=True, blank=True, verbose_name=_("Supplier"))
    purchase_date = models.DateField(_("Purchase date"))
    in_service_date = models.DateField(_("Depreciation starts"))
    cost = models.DecimalField(_("Cost"), **MONEY)
    salvage_value = models.DecimalField(_("Residual value"), default=0, **MONEY)
    useful_life_months = models.PositiveIntegerField(_("Useful life (months)"))
    opening_depreciation = models.DecimalField(_("Depreciation before TriB"), default=0, **MONEY,
                                               help_text=_("For assets bought before you started using TriB."))
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, null=True, blank=True, verbose_name=_("Branch"))
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, null=True, blank=True, verbose_name=_("Location"))
    location_detail = models.CharField(_("Room / area"), max_length=120, blank=True)
    custodian = models.CharField(_("Custodian"), max_length=120, blank=True)
    cost_center = models.ForeignKey(CostCenter, on_delete=models.PROTECT, null=True, blank=True, verbose_name=_("Cost centre"))
    status = models.CharField(_("Status"), max_length=10, choices=STATUSES, default="active")
    disposed_on = models.DateField(_("Disposal date"), null=True, blank=True)
    disposal_proceeds = models.DecimalField(_("Sale proceeds"), default=0, **MONEY)
    disposal_entry = models.OneToOneField(JournalEntry, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    notes = models.TextField(_("Notes"), blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["number"]
        constraints = [models.UniqueConstraint(fields=["company", "number"], name="uniq_asset_number")]

    def __str__(self):
        return f"{self.number} · {self.name}"

    @property
    def depreciable(self):
        return max(self.cost - self.salvage_value, Decimal("0"))

    @property
    def monthly_charge(self):
        if not self.useful_life_months:
            return Decimal("0")
        return (self.depreciable / self.useful_life_months).quantize(Decimal("0.01"))

    @property
    def accumulated(self):
        posted = self.depreciation_lines.aggregate(a=Sum("amount"))["a"] or Decimal("0")
        return self.opening_depreciation + posted

    @property
    def book_value(self):
        return self.cost - self.accumulated


class DepreciationRun(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="+")
    period = models.DateField(_("Month"))  # first day of the month
    journal_entry = models.OneToOneField(JournalEntry, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-period"]
        constraints = [models.UniqueConstraint(fields=["company", "period"], name="uniq_depreciation_month")]


class DepreciationLine(models.Model):
    run = models.ForeignKey(DepreciationRun, on_delete=models.CASCADE, related_name="lines")
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="depreciation_lines")
    amount = models.DecimalField(**MONEY)


class AssetCount(models.Model):
    STATUSES = [("open", _("Counting")), ("closed", _("Closed"))]
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="+")
    number = models.CharField(_("Number"), max_length=30)
    date = models.DateField(_("Date"))
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, null=True, blank=True, verbose_name=_("Branch"))
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, null=True, blank=True, verbose_name=_("Location"))
    status = models.CharField(_("Status"), max_length=6, choices=STATUSES, default="open")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]


class AssetCountLine(models.Model):
    count = models.ForeignKey(AssetCount, on_delete=models.CASCADE, related_name="lines")
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT)
    found = models.BooleanField(default=False)
    scanned_at = models.DateTimeField(null=True, blank=True)
    condition = models.CharField(_("Condition"), max_length=120, blank=True)

    class Meta:
        ordering = ["asset__number"]
