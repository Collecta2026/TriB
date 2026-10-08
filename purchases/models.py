from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from banking.models import BankAccount, Cheque
from contacts.models import Supplier
from core.documents import MONEY, PRICE, QTY, TradeDocument, TradeLine
from core.models import Company, Currency
from inventory.models import Item, Warehouse
from ledger.models import JournalEntry


class PurchaseOrder(TradeDocument):
    STATUSES = [("draft", _("Draft")), ("submitted", _("Waiting for approval")), ("open", _("Approved")),
                ("partial", _("Partly received")), ("received", _("Received")), ("closed", _("Closed")),
                ("cancelled", _("Cancelled"))]
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="purchase_orders", verbose_name=_("Supplier"))
    expected_date = models.DateField(_("Expected delivery"), null=True, blank=True)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, null=True, blank=True, verbose_name=_("Deliver to warehouse"))
    status = models.CharField(_("Status"), max_length=10, choices=STATUSES, default="draft")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)

    def refresh_status(self):
        if self.status not in ("open", "partial", "received"):
            return
        lines = [l for l in self.lines.all() if l.qty > 0]
        received = [l.qty_received for l in lines]
        if lines and all(l.qty_received >= l.qty for l in lines):
            self.status = "received"
        elif any(received):
            self.status = "partial"
        else:
            self.status = "open"
        self.save(update_fields=["status"])


class PurchaseOrderLine(TradeLine):
    document = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="lines")

    @property
    def qty_received(self):
        return self.receipt_lines.filter(document__status="posted").aggregate(q=Sum("qty"))["q"] or Decimal("0")

    @property
    def qty_billed(self):
        return self.bill_lines.filter(document__status="posted").aggregate(q=Sum("qty"))["q"] or Decimal("0")

    @property
    def qty_outstanding(self):
        return max(self.qty - self.qty_received, Decimal("0"))


class GoodsReceipt(models.Model):
    """Item receipt / goods received note: what physically arrived in the warehouse."""

    STATUSES = [("draft", _("Draft")), ("posted", _("Posted")), ("void", _("Void"))]
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="+")
    number = models.CharField(_("Number"), max_length=30, blank=True)
    date = models.DateField(_("Date received"))
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="receipts", verbose_name=_("Supplier"))
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, null=True, blank=True,
                                       related_name="receipts", verbose_name=_("Purchase order"))
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, verbose_name=_("Warehouse"))
    reference = models.CharField(_("Supplier delivery note"), max_length=60, blank=True)
    notes = models.TextField(_("Notes"), blank=True)
    status = models.CharField(_("Status"), max_length=6, choices=STATUSES, default="draft")
    journal_entry = models.OneToOneField(JournalEntry, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return self.number or str(_("Draft"))

    @property
    def total_value(self):
        return sum((l.value for l in self.lines.all()), Decimal("0"))


class GoodsReceiptLine(models.Model):
    document = models.ForeignKey(GoodsReceipt, on_delete=models.CASCADE, related_name="lines")
    order_line = models.ForeignKey(PurchaseOrderLine, on_delete=models.PROTECT, null=True, blank=True, related_name="receipt_lines")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, verbose_name=_("Product"))
    description = models.CharField(_("Description"), max_length=300, blank=True)
    qty = models.DecimalField(_("Qty received"), **QTY)
    unit_cost = models.DecimalField(_("Unit cost"), default=0, **PRICE)  # document currency
    unit_cost_base = models.DecimalField(default=0, **PRICE)
    serials = models.TextField(_("Serial numbers"), blank=True)
    batch_no = models.CharField(_("Batch"), max_length=60, blank=True)
    expiry_date = models.DateField(_("Expiry date"), null=True, blank=True)

    class Meta:
        ordering = ["id"]

    @property
    def value(self):
        return (self.qty * self.unit_cost_base).quantize(Decimal("0.01"))

    @property
    def qty_billed(self):
        return self.bill_lines.filter(document__status="posted").aggregate(q=Sum("qty"))["q"] or Decimal("0")


class Bill(TradeDocument):
    STATUSES = [("draft", _("Draft")), ("posted", _("Posted")), ("void", _("Void"))]
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="bills", verbose_name=_("Supplier"))
    supplier_invoice_no = models.CharField(_("Supplier invoice number"), max_length=60, blank=True)
    due_date = models.DateField(_("Due date"))
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.SET_NULL, null=True, blank=True, related_name="bills")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, null=True, blank=True,
                                  verbose_name=_("Receive stock into"),
                                  help_text=_("Only for stock items billed without an item receipt."))
    status = models.CharField(_("Status"), max_length=6, choices=STATUSES, default="draft")
    amount_paid = models.DecimalField(default=0, **MONEY)
    journal_entry = models.OneToOneField(JournalEntry, on_delete=models.PROTECT, null=True, blank=True, related_name="+")

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


class BillLine(TradeLine):
    document = models.ForeignKey(Bill, on_delete=models.CASCADE, related_name="lines")
    order_line = models.ForeignKey(PurchaseOrderLine, on_delete=models.SET_NULL, null=True, blank=True, related_name="bill_lines")
    receipt_line = models.ForeignKey(GoodsReceiptLine, on_delete=models.SET_NULL, null=True, blank=True, related_name="bill_lines")
    serials = models.TextField(_("Serial numbers"), blank=True)
    batch_no = models.CharField(_("Batch"), max_length=60, blank=True)
    expiry_date = models.DateField(_("Expiry date"), null=True, blank=True)


class SupplierPayment(models.Model):
    METHODS = [("cash", _("Cash")), ("bank", _("Bank transfer")), ("cheque", _("Cheque"))]
    STATUSES = [("posted", _("Posted")), ("void", _("Void"))]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="+")
    number = models.CharField(_("Number"), max_length=30, blank=True)
    date = models.DateField(_("Payment date"))
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="payments", verbose_name=_("Supplier"))
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, verbose_name=_("Currency"))
    rate = models.DecimalField(_("Exchange rate"), max_digits=18, decimal_places=6, default=1)
    amount = models.DecimalField(_("Amount paid"), **MONEY)
    method = models.CharField(_("Payment method"), max_length=6, choices=METHODS, default="bank")
    bank_account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, null=True, blank=True, verbose_name=_("Pay from"))
    cheque_number = models.CharField(_("Cheque number"), max_length=40, blank=True)
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


class BillAllocation(models.Model):
    payment = models.ForeignKey(SupplierPayment, on_delete=models.CASCADE, related_name="allocations")
    bill = models.ForeignKey(Bill, on_delete=models.PROTECT, related_name="allocations")
    amount = models.DecimalField(**MONEY)
