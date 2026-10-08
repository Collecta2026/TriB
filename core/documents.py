"""Shared building blocks for trade documents (quotations, orders, invoices, purchase orders, bills)."""
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from .models import Branch, Company, Currency, is_arabic
from .amount_words import amount_in_words

CENT = Decimal("0.01")
QTY = {"max_digits": 19, "decimal_places": 3}
PRICE = {"max_digits": 19, "decimal_places": 4}
MONEY = {"max_digits": 19, "decimal_places": 2}


def r2(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


class TradeDocument(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="+")
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, null=True, blank=True, verbose_name=_("Branch"))
    number = models.CharField(_("Number"), max_length=30, blank=True)
    date = models.DateField(_("Date"))
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, verbose_name=_("Currency"))
    rate = models.DecimalField(_("Exchange rate"), max_digits=18, decimal_places=6, default=1)
    reference = models.CharField(_("Reference"), max_length=60, blank=True)
    notes = models.TextField(_("Notes"), blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        ordering = ["-date", "-id"]

    def __str__(self):
        return self.number or str(_("Draft"))

    @property
    def lines_list(self):
        if not hasattr(self, "_lines_cache"):
            self._lines_cache = list(self.lines.select_related("item", "tax_rate"))
        return self._lines_cache

    @property
    def subtotal(self):
        return sum((l.net for l in self.lines_list), Decimal("0"))

    @property
    def tax_total(self):
        return sum((l.tax for l in self.lines_list), Decimal("0"))

    @property
    def total(self):
        return self.subtotal + self.tax_total

    @property
    def total_base(self):
        return r2(self.total * self.rate)

    def tax_breakdown(self):
        out = {}
        for l in self.lines_list:
            if l.tax_rate_id:
                out.setdefault(l.tax_rate, Decimal("0"))
                out[l.tax_rate] += l.tax
        return out.items()

    def words(self, lang):
        return amount_in_words(self.total, self.currency_id, lang, self.currency.decimals)

    @property
    def words_current(self):
        return self.words("ar" if is_arabic() else "en")


class TradeLine(models.Model):
    item = models.ForeignKey("inventory.Item", on_delete=models.PROTECT, null=True, blank=True, verbose_name=_("Product / service"))
    description = models.CharField(_("Description"), max_length=300, blank=True)
    qty = models.DecimalField(_("Qty"), default=1, **QTY)
    unit_price = models.DecimalField(_("Rate"), default=0, **PRICE)
    discount_pct = models.DecimalField(_("Disc. %"), max_digits=5, decimal_places=2, default=0)
    tax_rate = models.ForeignKey("ledger.TaxRate", on_delete=models.PROTECT, null=True, blank=True, verbose_name=_("VAT"))
    project = models.ForeignKey("ledger.Project", on_delete=models.PROTECT, null=True, blank=True, verbose_name=_("Project"))
    account = models.ForeignKey("ledger.Account", on_delete=models.PROTECT, null=True, blank=True, verbose_name=_("Account"))

    class Meta:
        abstract = True
        ordering = ["id"]

    @property
    def net(self):
        gross = Decimal(self.qty or 0) * Decimal(self.unit_price or 0)
        return r2(gross * (1 - Decimal(self.discount_pct or 0) / 100))

    @property
    def tax(self):
        if not self.tax_rate_id:
            return Decimal("0")
        return r2(self.net * self.tax_rate.rate / 100)

    @property
    def total(self):
        return self.net + self.tax

    @property
    def label(self):
        return self.description or (self.item.name if self.item_id else "")
