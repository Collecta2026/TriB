from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from banking.models import BankAccount, Cheque
from core.amount_words import amount_in_words
from core.models import Branch, Company, Currency, is_arabic
from ledger.models import Account, CostCenter, JournalEntry
from ledger.services import q2
from users.models import DOC_TYPES

PREFIXES = {"receipt": "RV", "payment": "PV", "journal": "JV"}


class Voucher(models.Model):
    """Receipt voucher (سند قبض), payment voucher (سند صرف) or journal voucher (قيد يومية)."""

    STATUSES = [
        ("draft", _("Draft")),
        ("submitted", _("Waiting for approval")),
        ("approved", _("Approved")),
        ("posted", _("Posted")),
        ("rejected", _("Rejected")),
        ("cancelled", _("Cancelled")),
    ]
    METHODS = [("cash", _("Cash")), ("bank", _("Bank transfer")), ("cheque", _("Cheque"))]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="vouchers")
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, null=True, blank=True, verbose_name=_("Branch"))
    kind = models.CharField(max_length=10, choices=DOC_TYPES)
    number = models.CharField(_("Number"), max_length=30, blank=True)
    date = models.DateField(_("Date"))
    status = models.CharField(_("Status"), max_length=10, choices=STATUSES, default="draft", db_index=True)
    party_name = models.CharField(_("Received from / paid to"), max_length=200, blank=True)
    method = models.CharField(_("Payment method"), max_length=6, choices=METHODS, blank=True)
    bank_account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, null=True, blank=True,
                                     verbose_name=_("Cash box / bank account"))
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, verbose_name=_("Currency"))
    rate = models.DecimalField(_("Exchange rate"), max_digits=18, decimal_places=6, default=1)
    description = models.CharField(_("Description"), max_length=300, blank=True)
    cheque_number = models.CharField(_("Cheque number"), max_length=40, blank=True)
    cheque_bank = models.CharField(_("Drawn on bank"), max_length=120, blank=True)
    cheque_due_date = models.DateField(_("Cheque due date"), null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    posted_at = models.DateTimeField(null=True, blank=True)
    journal_entry = models.OneToOneField(JournalEntry, on_delete=models.PROTECT, null=True, blank=True, related_name="voucher")
    cheque = models.OneToOneField(Cheque, on_delete=models.PROTECT, null=True, blank=True, related_name="voucher")

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return self.number or f"{self.get_kind_display()} ({self.get_status_display()})"

    @property
    def prefix(self):
        return PREFIXES[self.kind]

    @property
    def total(self):
        if self.kind == "journal":
            return sum((l.debit for l in self.lines.all()), Decimal("0"))
        return sum((l.amount for l in self.lines.all()), Decimal("0"))

    @property
    def amount_base(self):
        return q2(self.total * self.rate)

    @property
    def editable(self):
        return self.status in ("draft", "rejected")

    def words(self, lang):
        return amount_in_words(self.total, self.currency_id, lang, self.currency.decimals)

    @property
    def words_current(self):
        return self.words("ar" if is_arabic() else "en")

    @property
    def current_request(self):
        return self.approval_requests.order_by("-created_at").first()


class VoucherLine(models.Model):
    voucher = models.ForeignKey(Voucher, on_delete=models.CASCADE, related_name="lines")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, verbose_name=_("Account"))
    cost_center = models.ForeignKey(CostCenter, on_delete=models.PROTECT, null=True, blank=True, verbose_name=_("Cost centre"))
    description = models.CharField(_("Description"), max_length=300, blank=True)
    # Receipt and payment vouchers use `amount`; journal vouchers use debit/credit.
    amount = models.DecimalField(_("Amount"), max_digits=19, decimal_places=2, default=0)
    debit = models.DecimalField(_("Debit"), max_digits=19, decimal_places=2, default=0)
    credit = models.DecimalField(_("Credit"), max_digits=19, decimal_places=2, default=0)

    class Meta:
        ordering = ["id"]
