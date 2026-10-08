from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from banking.models import BankAccount, Cheque
from contacts.models import Customer
from core.documents import MONEY, PRICE, QTY, TradeDocument, TradeLine, r2
from core.models import Company, Currency
from inventory.models import Warehouse
from ledger.models import JournalEntry


class Quotation(TradeDocument):
    STATUSES = [("draft", _("Draft")), ("sent", _("Sent")), ("accepted", _("Accepted")),
                ("declined", _("Declined")), ("converted", _("Converted"))]
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="quotations", verbose_name=_("Customer"))
    valid_until = models.DateField(_("Valid until"), null=True, blank=True)
    status = models.CharField(_("Status"), max_length=10, choices=STATUSES, default="draft")


class QuotationLine(TradeLine):
    document = models.ForeignKey(Quotation, on_delete=models.CASCADE, related_name="lines")


class SalesOrder(TradeDocument):
    STATUSES = [("draft", _("Draft")), ("open", _("Open")), ("partial", _("Partly invoiced")),
                ("invoiced", _("Invoiced")), ("cancelled", _("Cancelled"))]
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="sales_orders", verbose_name=_("Customer"))
    expected_date = models.DateField(_("Delivery date"), null=True, blank=True)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, null=True, blank=True, verbose_name=_("Warehouse"))
    quotation = models.ForeignKey(Quotation, on_delete=models.SET_NULL, null=True, blank=True, related_name="orders")
    status = models.CharField(_("Status"), max_length=10, choices=STATUSES, default="draft")

    def refresh_status(self):
        if self.status in ("draft", "cancelled"):
            return
        lines = list(self.lines.all())
        invoiced = [l.qty_invoiced for l in lines]
        if lines and all(l.qty_invoiced >= l.qty for l in lines):
            self.status = "invoiced"
        elif any(invoiced):
            self.status = "partial"
        else:
            self.status = "open"
        self.save(update_fields=["status"])


class SalesOrderLine(TradeLine):
    document = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name="lines")

    @property
    def qty_invoiced(self):
        return self.invoice_lines.filter(document__status="posted").aggregate(q=Sum("qty"))["q"] or Decimal("0")

    @property
    def qty_open(self):
        return max(self.qty - self.qty_invoiced, Decimal("0"))


class Invoice(TradeDocument):
    STATUSES = [("draft", _("Draft")), ("posted", _("Posted")), ("void", _("Void"))]
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="invoices", verbose_name=_("Customer"))
    due_date = models.DateField(_("Due date"))
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, null=True, blank=True, verbose_name=_("Ship from warehouse"))
    sales_order = models.ForeignKey(SalesOrder, on_delete=models.SET_NULL, null=True, blank=True, related_name="invoices")
    status = models.CharField(_("Status"), max_length=10, choices=STATUSES, default="draft")
    amount_paid = models.DecimalField(default=0, **MONEY)
    journal_entry = models.OneToOneField(JournalEntry, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    posted_at = models.DateTimeField(null=True, blank=True)

    @property
    def balance_due(self):
        return self.total - self.amount_paid if self.status == "posted" else Decimal("0")

    @property
    def payment_state(self):
        if self.status != "posted":
            return self.status
        if self.balance_due <= 0:
            return "paid"
        if self.due_date < timezone.localdate():
            return "overdue"
        return "partial" if self.amount_paid else "unpaid"


class InvoiceLine(TradeLine):
    document = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    order_line = models.ForeignKey(SalesOrderLine, on_delete=models.SET_NULL, null=True, blank=True, related_name="invoice_lines")
    serials = models.TextField(_("Serial numbers"), blank=True, help_text=_("Optional: which machines are sold."))
    cost = models.DecimalField(default=0, **MONEY)  # FIFO cost of goods sold, base currency


class CustomerPayment(models.Model):
    METHODS = [("cash", _("Cash")), ("bank", _("Bank transfer")), ("cheque", _("Cheque"))]
    STATUSES = [("posted", _("Posted")), ("void", _("Void"))]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="+")
    number = models.CharField(_("Number"), max_length=30, blank=True)
    date = models.DateField(_("Payment date"))
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="payments", verbose_name=_("Customer"))
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, verbose_name=_("Currency"))
    rate = models.DecimalField(_("Exchange rate"), max_digits=18, decimal_places=6, default=1)
    amount = models.DecimalField(_("Amount received"), **MONEY)
    method = models.CharField(_("Payment method"), max_length=6, choices=METHODS, default="bank")
    bank_account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, null=True, blank=True, verbose_name=_("Deposit to"))
    cheque_number = models.CharField(_("Cheque number"), max_length=40, blank=True)
    cheque_bank = models.CharField(_("Drawn on bank"), max_length=120, blank=True)
    cheque_due_date = models.DateField(_("Cheque due date"), null=True, blank=True)
    reference = models.CharField(_("Reference"), max_length=60, blank=True)
    notes = models.CharField(_("Notes"), max_length=300, blank=True)
    status = models.CharField(_("Status"), max_length=6, choices=STATUSES, default="posted")
    journal_entry = models.OneToOneField(JournalEntry, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    cheque = models.OneToOneField(Cheque, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return self.number

    @property
    def allocated(self):
        return self.allocations.aggregate(a=Sum("amount"))["a"] or Decimal("0")

    @property
    def unallocated(self):
        return self.amount - self.allocated if self.status == "posted" else Decimal("0")


class PaymentAllocation(models.Model):
    payment = models.ForeignKey(CustomerPayment, on_delete=models.CASCADE, related_name="allocations")
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="allocations")
    amount = models.DecimalField(**MONEY)
