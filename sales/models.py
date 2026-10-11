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


class SalesHeader(models.Model):
    """QuickBooks-style sales header: who it is emailed to, where it ships and how."""

    email_to = models.CharField(_("Customer email"), max_length=300, blank=True,
                                help_text=_("Separate several addresses with commas."))
    email_cc = models.CharField(_("Cc"), max_length=300, blank=True)
    email_bcc = models.CharField(_("Bcc"), max_length=300, blank=True)
    bill_to = models.TextField(_("Bill to"), blank=True)
    ship_to = models.TextField(_("Ship to"), blank=True)
    ship_via = models.CharField(_("Ship via"), max_length=80, blank=True)
    ship_date = models.DateField(_("Shipping date"), null=True, blank=True)
    tracking_no = models.CharField(_("Tracking no."), max_length=80, blank=True)
    customer_po = models.CharField(_("Customer PO no."), max_length=60, blank=True)

    class Meta:
        abstract = True


class Quotation(TradeDocument, SalesHeader):
    STATUSES = [("draft", _("Draft")), ("sent", _("Sent")), ("accepted", _("Accepted")),
                ("declined", _("Declined")), ("converted", _("Converted"))]
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="quotations", verbose_name=_("Customer"))
    valid_until = models.DateField(_("Valid until"), null=True, blank=True)
    status = models.CharField(_("Status"), max_length=10, choices=STATUSES, default="draft")


class QuotationLine(TradeLine):
    document = models.ForeignKey(Quotation, on_delete=models.CASCADE, related_name="lines")


class SalesOrder(TradeDocument, SalesHeader):
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


class Invoice(TradeDocument, SalesHeader):
    STATUSES = [("draft", _("Draft")), ("posted", _("Posted")), ("void", _("Void"))]
    TERMS = [("receipt", _("Due on receipt")), ("net15", _("Net 15")), ("net30", _("Net 30")), ("net45", _("Net 45")),
             ("net60", _("Net 60")), ("net90", _("Net 90")), ("custom", _("Custom"))]
    TERM_DAYS = {"receipt": 0, "net15": 15, "net30": 30, "net45": 45, "net60": 60, "net90": 90}
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="invoices", verbose_name=_("Customer"))
    due_date = models.DateField(_("Due date"))
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, null=True, blank=True, verbose_name=_("Ship from warehouse"))
    sales_order = models.ForeignKey(SalesOrder, on_delete=models.SET_NULL, null=True, blank=True, related_name="invoices")
    status = models.CharField(_("Status"), max_length=10, choices=STATUSES, default="draft")
    terms = models.CharField(_("Terms"), max_length=8, choices=TERMS, default="custom")
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


class CreditNote(TradeDocument):
    """Goods returned or an allowance given to a customer: reverses the sale and its VAT. The credit is set against
    invoices or paid back with a refund."""

    STATUSES = [("draft", _("Draft")), ("posted", _("Posted")), ("void", _("Void"))]
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="credit_notes", verbose_name=_("Customer"))
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, null=True, blank=True, related_name="credit_notes",
                                verbose_name=_("Original invoice"))
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, null=True, blank=True,
                                  verbose_name=_("Return goods to warehouse"))
    reason = models.CharField(_("Reason"), max_length=200, blank=True)
    status = models.CharField(_("Status"), max_length=10, choices=STATUSES, default="draft")
    amount_applied = models.DecimalField(default=0, **MONEY)
    amount_refunded = models.DecimalField(default=0, **MONEY)
    journal_entry = models.OneToOneField(JournalEntry, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    posted_at = models.DateTimeField(null=True, blank=True)

    @property
    def available(self):
        return self.total - self.amount_applied - self.amount_refunded if self.status == "posted" else Decimal("0")

    @property
    def payment_state(self):
        if self.status != "posted":
            return self.status
        return "paid" if self.available <= 0 else ("partial" if self.amount_applied or self.amount_refunded else "open")


class CreditNoteLine(TradeLine):
    document = models.ForeignKey(CreditNote, on_delete=models.CASCADE, related_name="lines")
    return_to_stock = models.BooleanField(_("Back to stock"), default=True)
    serials = models.TextField(_("Serial numbers"), blank=True)
    batch_no = models.CharField(_("Batch"), max_length=60, blank=True)
    expiry_date = models.DateField(_("Expiry date"), null=True, blank=True)
    cost = models.DecimalField(default=0, **MONEY)  # stock value returned, base currency


class CreditAllocation(models.Model):
    credit_note = models.ForeignKey(CreditNote, on_delete=models.CASCADE, related_name="allocations")
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="credit_allocations")
    amount = models.DecimalField(**MONEY)
    date = models.DateField()


class CustomerRefund(models.Model):
    """Money paid back to a customer who has a credit (from a credit note or an overpayment)."""

    METHODS = [("cash", _("Cash")), ("bank", _("Bank transfer")), ("cheque", _("Cheque"))]
    STATUSES = [("posted", _("Posted")), ("void", _("Void"))]
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="+")
    number = models.CharField(_("Number"), max_length=30, blank=True)
    date = models.DateField(_("Refund date"))
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="refunds", verbose_name=_("Customer"))
    credit_note = models.ForeignKey(CreditNote, on_delete=models.PROTECT, null=True, blank=True, related_name="refunds",
                                    verbose_name=_("For credit note"))
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, verbose_name=_("Currency"))
    rate = models.DecimalField(_("Exchange rate"), max_digits=18, decimal_places=6, default=1)
    amount = models.DecimalField(_("Amount refunded"), **MONEY)
    method = models.CharField(_("Paid by"), max_length=6, choices=METHODS, default="bank")
    bank_account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, verbose_name=_("Paid from"))
    cheque_number = models.CharField(_("Cheque number"), max_length=40, blank=True)
    reference = models.CharField(_("Reference"), max_length=60, blank=True)
    notes = models.CharField(_("Notes"), max_length=300, blank=True)
    status = models.CharField(_("Status"), max_length=6, choices=STATUSES, default="posted")
    journal_entry = models.OneToOneField(JournalEntry, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return self.number
