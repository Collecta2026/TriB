from decimal import Decimal

from django.conf import settings
from django.db import models, transaction
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _


def is_arabic():
    return (get_language() or "en").startswith("ar")


class Bilingual(models.Model):
    """Every name a user sees is stored in English and Arabic."""

    name_en = models.CharField(_("Name (English)"), max_length=200)
    name_ar = models.CharField(_("Name (Arabic)"), max_length=200, blank=True)

    class Meta:
        abstract = True

    @property
    def name(self):
        if is_arabic() and self.name_ar:
            return self.name_ar
        return self.name_en

    def __str__(self):
        return self.name


class Currency(Bilingual):
    code = models.CharField(max_length=3, primary_key=True)
    decimals = models.PositiveSmallIntegerField(default=2)
    symbol_ar = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ["code"]
        verbose_name_plural = "currencies"

    def __str__(self):
        return f"{self.code} · {self.name}"

    @property
    def label(self):
        """Short label for amounts: EGP in English, ج.م in Arabic."""
        if is_arabic() and self.symbol_ar:
            return self.symbol_ar
        return self.code


class Company(Bilingual):
    """A customer of TriB. Every business record belongs to exactly one company."""

    ADDONS = [
        ("egypt", _("Egypt tax & ETA e-invoicing")),
        ("trading", _("Trading & imports")),
        ("gcc", _("GCC pack")),
        ("payroll", _("Payroll")),
        ("planning", _("Planning suite")),
    ]
    DEFAULT_ADDONS = {"egypt": True, "trading": True, "gcc": False, "payroll": False, "planning": False}

    base_currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name="+", verbose_name=_("Base currency"))
    currencies = models.ManyToManyField(Currency, related_name="+", blank=True, verbose_name=_("Currencies in use"))
    tax_id = models.CharField(_("Tax registration number"), max_length=30, blank=True)
    commercial_register = models.CharField(_("Commercial register"), max_length=30, blank=True)
    address = models.TextField(_("Address"), blank=True)
    phone = models.CharField(_("Phone"), max_length=40, blank=True)
    email = models.EmailField(_("Email"), blank=True)
    fiscal_year_start_month = models.PositiveSmallIntegerField(_("Financial year starts in month"), default=1)
    lock_date = models.DateField(
        _("Lock date"), null=True, blank=True,
        help_text=_("No entries can be posted on or before this date."),
    )
    auto_post_on_approval = models.BooleanField(_("Post documents automatically when fully approved"), default=True)
    enforce_sod = models.BooleanField(_("The person who creates a document cannot approve it"), default=True)
    addons = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "companies"

    def addon_enabled(self, key):
        return bool({**self.DEFAULT_ADDONS, **(self.addons or {})}.get(key))


class Branch(Bilingual):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="branches")
    code = models.CharField(_("Code"), max_length=10)
    is_active = models.BooleanField(_("Active"), default=True)

    class Meta:
        ordering = ["code"]
        constraints = [models.UniqueConstraint(fields=["company", "code"], name="uniq_branch_code")]


class ExchangeRate(models.Model):
    """How many units of the company's base currency one unit of `currency` buys on `date`."""

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="rates")
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, verbose_name=_("Currency"))
    date = models.DateField(_("Date"))
    rate = models.DecimalField(_("Rate"), max_digits=18, decimal_places=6)

    class Meta:
        ordering = ["-date", "currency_id"]
        constraints = [models.UniqueConstraint(fields=["company", "currency", "date"], name="uniq_rate_per_day")]

    @classmethod
    def rate_for(cls, company, currency, date):
        code = getattr(currency, "code", currency)
        if code == company.base_currency_id:
            return Decimal("1")
        row = cls.objects.filter(company=company, currency_id=code, date__lte=date).order_by("-date").first()
        return row.rate if row else None


class NumberSeries(models.Model):
    """Gap-free sequential numbers per company, document prefix and year (e.g. PV-2026-00042)."""

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="+")
    key = models.CharField(max_length=20)
    next_number = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["company", "key"], name="uniq_series_key")]

    @classmethod
    def next(cls, company, prefix, date):
        key = f"{prefix}-{date.year}"
        with transaction.atomic():
            cls.objects.get_or_create(company=company, key=key)
            row = cls.objects.select_for_update().get(company=company, key=key)
            number = row.next_number
            row.next_number = number + 1
            row.save(update_fields=["next_number"])
        return f"{key}-{number:05d}"


class AuditLog(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, null=True, related_name="+")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    action = models.CharField(max_length=40)
    object_type = models.CharField(max_length=60, blank=True)
    object_id = models.CharField(max_length=40, blank=True)
    summary = models.CharField(max_length=300, blank=True)
    data = models.JSONField(default=dict, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    @classmethod
    def record(cls, company, user, action, obj=None, summary="", data=None, ip=None):
        return cls.objects.create(
            company=company,
            user=user if getattr(user, "is_authenticated", False) else None,
            action=action,
            object_type=obj._meta.label if obj is not None else "",
            object_id=str(obj.pk) if obj is not None else "",
            summary=summary[:300],
            data=data or {},
            ip=ip,
        )


def client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")
