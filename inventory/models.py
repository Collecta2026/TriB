from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.utils.translation import gettext_lazy as _

from core.models import Bilingual, Branch, Company
from ledger.models import Account, JournalEntry, TaxRate

QTY = {"max_digits": 19, "decimal_places": 3}
COST = {"max_digits": 19, "decimal_places": 4}
MONEY = {"max_digits": 19, "decimal_places": 2}


class Category(Bilingual):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="item_categories")
    prefix = models.CharField(_("SKU prefix"), max_length=6, help_text=_("Used to build SKUs, e.g. MCH → MCH-00001"))

    class Meta:
        ordering = ["name_en"]
        verbose_name_plural = "categories"
        constraints = [models.UniqueConstraint(fields=["company", "prefix"], name="uniq_category_prefix")]


class Warehouse(Bilingual):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="warehouses")
    code = models.CharField(_("Code"), max_length=10)
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, null=True, blank=True, verbose_name=_("Branch"))
    address = models.CharField(_("Address"), max_length=300, blank=True)
    is_active = models.BooleanField(_("Active"), default=True)

    class Meta:
        ordering = ["code"]
        constraints = [models.UniqueConstraint(fields=["company", "code"], name="uniq_warehouse_code")]

    def __str__(self):
        return f"{self.code} · {self.name}"


class Item(Bilingual):
    TYPES = [("inventory", _("Stock item")), ("non_inventory", _("Non-stock item")), ("service", _("Service"))]
    TRACKING = [("none", _("No tracking")), ("serial", _("Serial numbers")), ("batch", _("Batch & expiry date"))]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="items")
    sku = models.CharField(_("SKU"), max_length=40, blank=True, help_text=_("Leave empty to number it automatically."))
    barcode = models.CharField(_("Barcode"), max_length=60, blank=True,
                               help_text=_("Manufacturer barcode if it has one; otherwise the SKU is used."))
    type = models.CharField(_("Type"), max_length=14, choices=TYPES, default="inventory")
    category = models.ForeignKey(Category, on_delete=models.PROTECT, null=True, blank=True, verbose_name=_("Category"))
    tracking = models.CharField(_("Tracking"), max_length=6, choices=TRACKING, default="none")
    unit = models.CharField(_("Unit"), max_length=20, default="pcs")
    description = models.TextField(_("Sales description"), blank=True,
                                   help_text=_("Filled in on invoices, quotes and sales orders."))
    purchase_description = models.TextField(_("Purchase description"), blank=True,
                                            help_text=_("Filled in on purchase orders and bills."))
    # The product picture, kept in the database (like attachments) so it survives redeploys.
    image = models.BinaryField(null=True, blank=True, editable=False)
    image_type = models.CharField(max_length=40, blank=True, editable=False)
    sales_price = models.DecimalField(_("Sales price"), default=0, **COST)
    purchase_cost = models.DecimalField(_("Purchase cost"), default=0, **COST)
    sales_tax = models.ForeignKey(TaxRate, on_delete=models.PROTECT, null=True, blank=True, related_name="+",
                                  verbose_name=_("Sales VAT"))
    purchase_tax = models.ForeignKey(TaxRate, on_delete=models.PROTECT, null=True, blank=True, related_name="+",
                                     verbose_name=_("Purchase VAT"))
    income_account = models.ForeignKey(Account, on_delete=models.PROTECT, null=True, blank=True, related_name="+",
                                       verbose_name=_("Income account"))
    expense_account = models.ForeignKey(Account, on_delete=models.PROTECT, null=True, blank=True, related_name="+",
                                        verbose_name=_("Cost / expense account"))
    inventory_account = models.ForeignKey(Account, on_delete=models.PROTECT, null=True, blank=True, related_name="+",
                                          verbose_name=_("Inventory account"))
    reorder_level = models.DecimalField(_("Reorder level"), default=0, **QTY)
    is_active = models.BooleanField(_("Active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sku"]
        constraints = [models.UniqueConstraint(fields=["company", "sku"], name="uniq_item_sku")]

    def __str__(self):
        return f"{self.sku} · {self.name}"

    @property
    def is_stocked(self):
        return self.type == "inventory"

    @property
    def scan_code(self):
        return self.barcode or self.sku

    @property
    def has_image(self):
        return bool(self.image_type)

    def on_hand(self, warehouse=None):
        qs = self.layers.all()
        if warehouse is not None:
            qs = qs.filter(warehouse=warehouse)
        return qs.aggregate(q=Sum("qty_remaining"))["q"] or Decimal("0")


class StockLayer(models.Model):
    """One FIFO cost layer: a quantity that arrived together at one unit cost (base currency)."""

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="+")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="layers")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="layers")
    date = models.DateField()
    ref = models.CharField(max_length=40, blank=True)
    qty_in = models.DecimalField(**QTY)
    qty_remaining = models.DecimalField(**QTY)
    unit_cost = models.DecimalField(**COST)
    serial_no = models.CharField(_("Serial number"), max_length=80, blank=True, db_index=True)
    batch_no = models.CharField(_("Batch"), max_length=60, blank=True)
    expiry_date = models.DateField(_("Expiry date"), null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "id"]
        indexes = [models.Index(fields=["item", "warehouse", "qty_remaining"])]


class StockMove(models.Model):
    KINDS = [
        ("receipt", _("Receipt")), ("issue", _("Issue")), ("transfer_in", _("Transfer in")),
        ("transfer_out", _("Transfer out")), ("adjust_in", _("Adjustment in")), ("adjust_out", _("Adjustment out")),
        ("opening", _("Opening stock")), ("return", _("Return")),
    ]
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="+")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="moves")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="moves")
    date = models.DateField(db_index=True)
    kind = models.CharField(max_length=14, choices=KINDS)
    qty = models.DecimalField(**QTY)  # positive in, negative out
    unit_cost = models.DecimalField(**COST)
    value = models.DecimalField(**MONEY)  # signed, base currency
    ref = models.CharField(max_length=40, blank=True)
    layer = models.ForeignKey(StockLayer, on_delete=models.PROTECT, null=True, blank=True, related_name="moves")
    serial_no = models.CharField(max_length=80, blank=True)
    batch_no = models.CharField(max_length=60, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "id"]


class StockDocument(models.Model):
    STATUSES = [("draft", _("Draft")), ("posted", _("Posted"))]
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="+")
    number = models.CharField(_("Number"), max_length=30, blank=True)
    date = models.DateField(_("Date"))
    status = models.CharField(_("Status"), max_length=10, choices=STATUSES, default="draft")
    notes = models.CharField(_("Notes"), max_length=300, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        ordering = ["-date", "-id"]

    def __str__(self):
        return self.number or str(self.pk)


class StockTransfer(StockDocument):
    from_warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="+", verbose_name=_("From"))
    to_warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="+", verbose_name=_("To"))


class StockTransferLine(models.Model):
    transfer = models.ForeignKey(StockTransfer, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, verbose_name=_("Item"))
    qty = models.DecimalField(_("Quantity"), **QTY)
    serials = models.TextField(_("Serial numbers"), blank=True, help_text=_("One per line, for serial-tracked items."))
    position = models.PositiveIntegerField(default=0)  # order on the document (drag to reorder)

    class Meta:
        ordering = ["position", "id"]


class StockAdjustment(StockDocument):
    REASONS = [("count", _("Stock take difference")), ("damaged", _("Damaged")), ("expired", _("Expired")),
               ("lost", _("Lost or stolen")), ("found", _("Found")), ("opening", _("Opening stock")),
               ("other", _("Other"))]
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="+", verbose_name=_("Warehouse"))
    reason = models.CharField(_("Reason"), max_length=10, choices=REASONS, default="other")
    journal_entry = models.OneToOneField(JournalEntry, on_delete=models.PROTECT, null=True, blank=True, related_name="+")


class StockAdjustmentLine(models.Model):
    adjustment = models.ForeignKey(StockAdjustment, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, verbose_name=_("Item"))
    qty_change = models.DecimalField(_("Quantity + / −"), **QTY)
    unit_cost = models.DecimalField(_("Unit cost (for increases)"), default=0, **COST)
    serials = models.TextField(_("Serial numbers"), blank=True)
    batch_no = models.CharField(_("Batch"), max_length=60, blank=True)
    expiry_date = models.DateField(_("Expiry date"), null=True, blank=True)
    position = models.PositiveIntegerField(default=0)  # order on the document (drag to reorder)

    class Meta:
        ordering = ["position", "id"]


class StockCount(StockDocument):
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="+", verbose_name=_("Warehouse"))
    adjustment = models.OneToOneField(StockAdjustment, on_delete=models.PROTECT, null=True, blank=True, related_name="+")


class StockCountLine(models.Model):
    count = models.ForeignKey(StockCount, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    expected_qty = models.DecimalField(**QTY)
    counted_qty = models.DecimalField(null=True, blank=True, **QTY)

    class Meta:
        ordering = ["item__sku"]

    @property
    def difference(self):
        return (self.counted_qty or 0) - self.expected_qty if self.counted_qty is not None else None


class PriceRule(models.Model):
    """A price rule (QuickBooks' Price rules): raise or lower the sales price, by a percentage or a fixed amount, for
    some or all customers and some or all products, between two dates. Invoices, quotes and sales orders apply it when
    a product is added to a line; the price can still be changed on the line."""

    DIRECTIONS = [("down", _("Decrease")), ("up", _("Increase"))]
    METHODS = [("percent", _("By a percentage")), ("fixed", _("By a fixed amount"))]
    ROUNDING = [("none", _("No rounding")), ("whole", _("To the nearest whole number")),
                ("half", _("To the nearest 0.50")), ("nickel", _("To the nearest 0.05")),
                ("end99", _("Ending in .99"))]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="price_rules")
    name = models.CharField(_("Rule name"), max_length=80)
    customers = models.ManyToManyField("contacts.Customer", blank=True, related_name="price_rules",
                                       verbose_name=_("Customers"), help_text=_("Leave empty for all customers."))
    categories = models.ManyToManyField(Category, blank=True, related_name="price_rules", verbose_name=_("Categories"))
    items = models.ManyToManyField(Item, blank=True, related_name="price_rules", verbose_name=_("Products"),
                                   help_text=_("Leave products and categories empty for all products."))
    direction = models.CharField(_("Price"), max_length=4, choices=DIRECTIONS, default="down")
    method = models.CharField(_("Adjust"), max_length=7, choices=METHODS, default="percent")
    amount = models.DecimalField(_("Amount"), max_digits=12, decimal_places=4, default=0)
    rounding = models.CharField(_("Rounding"), max_length=6, choices=ROUNDING, default="none")
    start_date = models.DateField(_("Start date"), null=True, blank=True)
    end_date = models.DateField(_("End date"), null=True, blank=True)
    is_active = models.BooleanField(_("Active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

