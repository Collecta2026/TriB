from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import Bilingual, Company, Currency


class Contact(Bilingual):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="+")
    code = models.CharField(_("Code"), max_length=20, blank=True)
    contact_person = models.CharField(_("Contact person"), max_length=120, blank=True)
    email = models.EmailField(_("Email"), blank=True)
    phone = models.CharField(_("Phone"), max_length=40, blank=True)
    tax_id = models.CharField(_("Tax registration number"), max_length=30, blank=True)
    commercial_register = models.CharField(_("Commercial register"), max_length=30, blank=True)
    address = models.TextField(_("Address"), blank=True)
    city = models.CharField(_("City"), max_length=80, blank=True)
    country = models.CharField(_("Country"), max_length=80, blank=True, default="Egypt")
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, verbose_name=_("Currency"))
    payment_terms_days = models.PositiveIntegerField(_("Payment terms (days)"), default=30)
    notes = models.TextField(_("Notes"), blank=True)
    is_active = models.BooleanField(_("Active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        ordering = ["name_en"]

    def __str__(self):
        return f"{self.name} ({self.code})" if self.code else self.name


class Customer(Contact):
    credit_limit = models.DecimalField(_("Credit limit"), max_digits=19, decimal_places=2, default=0,
                                       help_text=_("0 means no limit."))

    class Meta(Contact.Meta):
        constraints = [models.UniqueConstraint(fields=["company", "code"], name="uniq_customer_code")]


class Supplier(Contact):
    bank_details = models.TextField(_("Bank details"), blank=True)

    class Meta(Contact.Meta):
        constraints = [models.UniqueConstraint(fields=["company", "code"], name="uniq_supplier_code")]
