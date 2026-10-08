"""Release 2 demo data: products with SKUs, stock with serials and expiry dates, customers, suppliers, purchase
orders, invoices, orders, staff and fixed assets. Every name and figure here is invented."""
from datetime import timedelta
from decimal import Decimal as D

from django.utils import timezone

from assets.models import Asset, AssetCategory
from assets.services import next_asset_number
from contacts.models import Customer, Supplier
from core.models import NumberSeries
from inventory import services as stock
from inventory.models import Category, Item, StockAdjustment, Warehouse
from ledger.models import TaxRate
from ledger.services import system_account
from purchases import services as purchasing
from purchases.models import PurchaseOrder, PurchaseOrderLine
from sales import services as sales
from sales.models import CustomerPayment, Invoice, InvoiceLine, SalesOrder, SalesOrderLine
from team.models import Department, Employee
from users.models import Membership

CLINICS = [("Cairo Dental Center", "مركز القاهرة لطب الأسنان"), ("Nile Smile Clinics", "عيادات ابتسامة النيل"),
           ("Alex Ortho Center", "مركز الإسكندرية لتقويم الأسنان"), ("Smile Clinic, Heliopolis", "عيادة سمايل مصر الجديدة"),
           ("Giza Dental Hospital", "مستشفى الجيزة للأسنان"), ("Delta Dental Care", "دلتا لرعاية الأسنان")]


def build(company, owner, cib, fm=None):
    today = timezone.localdate()
    vat = TaxRate.objects.get(company=company, is_default=True)
    main = Warehouse.objects.get(company=company, code="MAIN")
    alex = Warehouse.objects.create(company=company, code="ALX", name_en="Alexandria showroom", name_ar="معرض الإسكندرية")

    machines = Category.objects.create(company=company, name_en="Machines", name_ar="أجهزة", prefix="MCH")
    supplies = Category.objects.create(company=company, name_en="Supplies", name_ar="مستلزمات", prefix="SUP")
    services_cat = Category.objects.create(company=company, name_en="Services", name_ar="خدمات", prefix="SRV")

    def item(cat, name_en, name_ar, tracking, price, cost, reorder=0, type_="inventory", unit="pcs"):
        return Item.objects.create(company=company, sku=stock.next_sku(company, cat), category=cat, name_en=name_en,
                                   name_ar=name_ar, tracking=tracking, type=type_, unit=unit, sales_price=D(price),
                                   purchase_cost=D(cost), sales_tax=vat, purchase_tax=vat, reorder_level=D(reorder))

    chair = item(machines, "Dental chair unit A6", "وحدة كرسي أسنان A6", "serial", 285000, 172000, 2)
    xray = item(machines, "Intraoral X-ray unit", "جهاز أشعة داخل الفم", "serial", 96000, 58000, 1)
    autoclave = item(machines, "Autoclave 23 L class B", "جهاز تعقيم 23 لتر", "serial", 64000, 39000, 1)
    composite = item(supplies, "Composite kit A2", "طقم حشو كومبوزيت A2", "batch", 1450, 820, 40, unit="kit")
    alginate = item(supplies, "Alginate impression 500 g", "ألجينات طبعة 500 جم", "batch", 380, 190, 60, unit="bag")
    gloves = item(supplies, "Nitrile gloves (box 100)", "قفازات نيتريل (علبة 100)", "batch", 260, 140, 100, unit="box")
    install = item(services_cat, "Installation & training", "تركيب وتدريب", "none", 4500, 0, type_="service")

    medent = Supplier.objects.create(company=company, code="SUP-00001", name_en="Medent Italia S.r.l.", currency_id="EGP",
                                     payment_terms_days=60)
    alpha = Supplier.objects.create(company=company, code="SUP-00002", name_en="Alpha Dental GmbH", currency_id="EGP",
                                    payment_terms_days=30)
    customers = [Customer.objects.create(company=company, code=f"CUS-{i + 1:05d}", name_en=en, name_ar=ar,
                                         currency_id="EGP", payment_terms_days=30, credit_limit=D(2500000))
                 for i, (en, ar) in enumerate(CLINICS)]

    # Opening stock of consumables, with batches and expiry dates. Sales use the soonest expiry first, so some of
    # ALG-2309 is left over after it expired, and part of CMP-2311 is close to expiry.
    adj = StockAdjustment.objects.create(company=company, warehouse=main, date=today - timedelta(days=200),
                                         reason="opening", created_by=owner, notes="Opening stock")
    for it, batch, qty, days in ((composite, "CMP-2405", 120, 420), (composite, "CMP-2311", 90, 60),
                                 (alginate, "ALG-2402", 200, 300), (alginate, "ALG-2309", 140, -12),
                                 (gloves, "GLV-2406", 400, 700)):
        adj.lines.create(item=it, qty_change=D(qty), unit_cost=it.purchase_cost, batch_no=batch,
                         expiry_date=today + timedelta(days=days))
    stock.post_adjustment(adj, owner)

    # Machines: purchase order → partly received with serial numbers → billed. The rest is still on order.
    po = PurchaseOrder.objects.create(company=company, date=today - timedelta(days=75), supplier=medent, currency_id="EGP",
                                      warehouse=main, expected_date=today - timedelta(days=5), created_by=owner)
    for it, qty in ((chair, 8), (xray, 4), (autoclave, 4)):
        PurchaseOrderLine.objects.create(document=po, item=it, qty=D(qty), unit_price=it.purchase_cost, tax_rate=vat)
    purchasing.submit_order(po, owner)
    purchasing.approve_order(po, owner, Membership.objects.get(user=owner, company=company))
    grn = purchasing.receipt_from_order(po, owner)
    grn.date = today - timedelta(days=60)
    grn.save(update_fields=["date"])
    serial_no = iter(range(1001, 2000))
    for line in grn.lines.select_related("item"):
        line.qty = {chair.pk: 6, xray.pk: 4, autoclave.pk: 3}[line.item_id]
        line.serials = "\n".join(f"{line.item.sku[-5:]}-SN{next(serial_no)}" for _ in range(int(line.qty)))
        line.save()
    purchasing.post_receipt(grn, owner)
    bill = purchasing.bill_from_order(po, owner)
    bill.date, bill.due_date, bill.supplier_invoice_no = today - timedelta(days=58), today + timedelta(days=2), "MI-26-0815"
    bill.save()
    purchasing.post_bill(bill, owner)

    # A local supplies order not yet received.
    po2 = PurchaseOrder.objects.create(company=company, date=today - timedelta(days=4), supplier=alpha, currency_id="EGP",
                                       warehouse=main, expected_date=today + timedelta(days=10), created_by=owner)
    PurchaseOrderLine.objects.create(document=po2, item=gloves, qty=D(300), unit_price=gloves.purchase_cost, tax_rate=vat)
    PurchaseOrderLine.objects.create(document=po2, item=composite, qty=D(100), unit_price=composite.purchase_cost, tax_rate=vat)
    purchasing.submit_order(po2, owner)

    # Sales over the last 90 days.
    def invoice(days_ago, customer, lines, paid=False):
        inv = Invoice.objects.create(company=company, customer=customer, date=today - timedelta(days=days_ago),
                                     due_date=today - timedelta(days=days_ago) + timedelta(days=30), currency_id="EGP",
                                     warehouse=main, created_by=owner)
        for it, qty in lines:
            InvoiceLine.objects.create(document=inv, item=it, qty=D(qty), unit_price=it.sales_price, tax_rate=vat,
                                       description=it.name_en)
        sales.post_invoice(inv, owner, allow_over_limit=True)
        if paid:
            pay = CustomerPayment(company=company, date=inv.date + timedelta(days=20), customer=customer, currency_id="EGP",
                                  amount=inv.total, method="bank", bank_account=cib, created_by=owner)
            sales.post_payment(pay, [(inv, inv.total)], owner)
        return inv

    invoice(55, customers[0], [(chair, 1), (install, 1), (composite, 10)], paid=True)
    invoice(48, customers[1], [(xray, 2), (gloves, 40)], paid=True)
    invoice(41, customers[2], [(chair, 1), (autoclave, 1), (install, 2)])          # overdue
    invoice(33, customers[3], [(composite, 30), (alginate, 50), (gloves, 120)])     # overdue
    invoice(20, customers[4], [(chair, 2), (install, 2)], paid=True)
    invoice(12, customers[5], [(xray, 1), (alginate, 40)])
    invoice(5, customers[0], [(composite, 25), (gloves, 100)])

    # Open customer orders.
    for days_ago, customer, lines in ((6, customers[1], [(chair, 2), (install, 2)]),
                                      (3, customers[4], [(autoclave, 1), (composite, 20)])):
        so = SalesOrder.objects.create(company=company, date=today - timedelta(days=days_ago), customer=customer,
                                       number=NumberSeries.next(company, "SO", today - timedelta(days=days_ago)),
                                       currency_id="EGP", warehouse=main, status="open", created_by=owner,
                                       expected_date=today + timedelta(days=14))
        for it, qty in lines:
            SalesOrderLine.objects.create(document=so, item=it, qty=D(qty), unit_price=it.sales_price, tax_rate=vat,
                                          description=it.name_en)

    # Staff (invented people) for the payroll demo.
    depts = {n: Department.objects.create(company=company, name_en=n, name_ar=a) for n, a in
             (("Sales", "المبيعات"), ("Technical service", "الدعم الفني"), ("Warehouse", "المخازن"),
              ("Finance", "المالية"))}
    for code, name, dept, title, basic, allowance, channel in (
            ("101", "Ahmed Demo", "Sales", "Sales engineer", 18000, 2500, "bank"),
            ("102", "Sara Demo", "Sales", "Sales coordinator", 11000, 1000, "instapay"),
            ("103", "Omar Demo", "Technical service", "Service engineer", 16000, 2000, "bank"),
            ("104", "Hany Demo", "Warehouse", "Storekeeper", 8500, 500, "cash"),
            ("105", "Mona Demo", "Finance", "Accountant", 14000, 1500, "bank")):
        Employee.objects.create(company=company, code=code, name_en=name, department=depts[dept], job_title_en=title,
                                basic_salary=D(basic), allowances=D(allowance), payment_method=channel,
                                hire_date=today - timedelta(days=500), medical_employee_share=D(250))

    # Fixed assets with numbers for barcode labels.
    cat = AssetCategory.objects.create(company=company, name_en="Office & IT equipment", name_ar="معدات مكتبية وحاسبات",
                                       useful_life_months=36, asset_account=system_account(company, "fixed_assets"),
                                       depreciation_account=system_account(company, "accum_depreciation"),
                                       expense_account=system_account(company, "depreciation"))
    vehicles = AssetCategory.objects.create(company=company, name_en="Vehicles", name_ar="سيارات", useful_life_months=60,
                                            asset_account=system_account(company, "fixed_assets"),
                                            depreciation_account=system_account(company, "accum_depreciation"),
                                            expense_account=system_account(company, "depreciation"))
    for name, category, cost, wh in (("Service van", vehicles, 1450000, main), ("Laptop · Finance", cat, 42000, main),
                                     ("Demo chair (showroom)", cat, 172000, alex)):
        Asset.objects.create(company=company, number=next_asset_number(company), name_en=name, category=category,
                             purchase_date=today - timedelta(days=150), in_service_date=today - timedelta(days=150),
                             cost=D(cost), useful_life_months=category.useful_life_months, warehouse=wh)
