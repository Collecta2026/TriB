"""Release 2 business rules: FIFO, sales, purchasing, assets and payroll postings."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from assets import services as asset_services
from assets.models import Asset, AssetCategory
from banking.services import create_bank_account
from contacts.models import Customer, Supplier
from core.barcode import PATTERNS, code128_values, svg
from inventory import services as stock
from inventory.models import Category, Item, StockAdjustment, Warehouse
from ledger.models import TaxRate
from ledger.services import account_balance
from payroll import engine
from payroll import services as payroll
from payroll.models import PayrollRun, PayrollSettings
from purchases import services as purchasing
from purchases.models import Bill, PurchaseOrder, PurchaseOrderLine
from sales import services as sales
from sales.models import CustomerPayment, Invoice, InvoiceLine, SalesOrder, SalesOrderLine
from team.models import Department, Employee, Loan

from .conftest import TODAY, D, acct


@pytest.fixture
def wh(company):
    return Warehouse.objects.get(company=company, code="MAIN")


@pytest.fixture
def vat14(company):
    return TaxRate.objects.get(company=company, rate=14)


@pytest.fixture
def machine(company):
    cat = Category.objects.create(company=company, name_en="Machines", prefix="MCH")
    return Item.objects.create(company=company, sku=stock.next_sku(company, cat), name_en="Dental chair", category=cat,
                               tracking="serial", sales_price=D(150000), purchase_cost=D(90000))


@pytest.fixture
def composite(company):
    cat = Category.objects.create(company=company, name_en="Supplies", prefix="SUP")
    return Item.objects.create(company=company, sku=stock.next_sku(company, cat), name_en="Composite A2", category=cat,
                               tracking="batch", sales_price=D(400), purchase_cost=D(250))


@pytest.fixture
def customer(company):
    return Customer.objects.create(company=company, code="CUS-00001", name_en="Cairo Dental Center",
                                   currency_id="EGP", payment_terms_days=30)


@pytest.fixture
def supplier(company):
    return Supplier.objects.create(company=company, code="SUP-00001", name_en="Alpha Dental GmbH", currency_id="EGP")


def test_barcode_table_and_svg():
    assert len(PATTERNS) == 107 and all(sum(map(int, p)) == 11 for p in PATTERNS[:106])
    assert len(set(PATTERNS)) == 107
    values = code128_values("FA-00001")
    assert values[0] == 104 and values[-1] == 106
    assert svg("MCH-00001").startswith("<svg")


def test_skus_are_unique_and_prefixed(company, machine):
    assert machine.sku == "MCH-00001"
    assert stock.next_sku(company, machine.category) == "MCH-00002"


def test_fifo_costs_oldest_first_and_fefo_for_batches(company, wh, composite):
    stock.receive(composite, wh, 10, D(200), TODAY - timedelta(days=20), "R1", batch_no="B1", expiry_date=TODAY + timedelta(days=300))
    stock.receive(composite, wh, 10, D(300), TODAY - timedelta(days=10), "R2", batch_no="B2", expiry_date=TODAY + timedelta(days=100))
    cost, parts = stock.issue(composite, wh, 12, TODAY, "I1")
    # B2 expires first, so it goes first (FEFO), then 2 from B1.
    assert [p.layer.batch_no for p in parts] == ["B2", "B1"]
    assert cost == D(10 * 300 + 2 * 200)
    assert composite.on_hand(wh) == 8


def test_serial_items_need_serials_and_cannot_oversell(company, wh, machine):
    with pytest.raises(stock.StockError):
        stock.receive(machine, wh, 2, D(90000), TODAY, "R1", serials=["SN1"])
    stock.receive(machine, wh, 2, D(90000), TODAY, "R1", serials=["SN1", "SN2"])
    with pytest.raises(stock.StockError):
        stock.issue(machine, wh, 3, TODAY, "I1")
    cost, parts = stock.issue(machine, wh, 1, TODAY, "I1", serials=["SN2"])
    assert parts[0].layer.serial_no == "SN2" and cost == D(90000)


def test_invoice_posts_revenue_vat_cogs_and_payment_clears_it(company, owner, wh, machine, customer, vat14, cash):
    stock.receive(machine, wh, 1, D(90000), TODAY, "R1", serials=["SN9"])
    inv = Invoice.objects.create(company=company, date=TODAY, due_date=TODAY + timedelta(days=30), customer=customer,
                                 currency_id="EGP", warehouse=wh, created_by=owner)
    InvoiceLine.objects.create(document=inv, item=machine, qty=1, unit_price=D(150000), tax_rate=vat14)
    sales.post_invoice(inv, owner)
    inv.refresh_from_db()
    assert inv.number == "INV-2026-00001" and inv.total == D(171000)
    assert account_balance(acct(company, "1130")) == D(171000)
    assert account_balance(acct(company, "4100")) == D(150000)
    assert account_balance(acct(company, "2130")) == D(21000)
    assert account_balance(acct(company, "5100")) == D(90000)
    assert machine.on_hand(wh) == 0

    pay = CustomerPayment(company=company, date=TODAY, customer=customer, currency_id="EGP", amount=D(171000),
                          method="bank", bank_account=cash, created_by=owner)
    sales.post_payment(pay, [(inv, D(171000))], owner)
    inv.refresh_from_db()
    assert inv.payment_state == "paid"
    assert account_balance(acct(company, "1130")) == 0
    st = sales.statement(customer, TODAY - timedelta(days=5), TODAY)
    assert st["closing"] == 0 and len(st["rows"]) == 2


def test_order_to_invoice_tracks_open_quantity(company, owner, wh, composite, customer):
    stock.receive(composite, wh, 50, D(250), TODAY, "R", batch_no="B1", expiry_date=TODAY + timedelta(days=400))
    so = SalesOrder.objects.create(company=company, date=TODAY, customer=customer, currency_id="EGP", warehouse=wh,
                                   status="open", created_by=owner)
    SalesOrderLine.objects.create(document=so, item=composite, qty=20, unit_price=D(400))
    inv = sales.order_to_invoice(so, owner)
    line = inv.lines.get()
    line.qty = 5
    line.save()
    sales.post_invoice(inv, owner)
    so.refresh_from_db()
    assert so.status == "partial" and so.lines.get().qty_open == 15


def test_po_receipt_bill_and_unreceived_tracking(company, owner, make_user, wh, composite, supplier, vat14, cash):
    po = PurchaseOrder.objects.create(company=company, date=TODAY, supplier=supplier, currency_id="EGP", warehouse=wh,
                                      created_by=owner)
    PurchaseOrderLine.objects.create(document=po, item=composite, qty=100, unit_price=D(250), tax_rate=vat14)
    purchasing.submit_order(po, owner)
    approver = make_user("fm@scigate.test", "Finance manager")
    from users.models import Membership
    purchasing.approve_order(po, approver, Membership.objects.get(user=approver))
    grn = purchasing.receipt_from_order(po, owner)
    line = grn.lines.get()
    line.qty, line.batch_no, line.expiry_date = 60, "LOT-7", TODAY + timedelta(days=500)
    line.save()
    purchasing.post_receipt(grn, owner)
    po.refresh_from_db()
    assert po.status == "partial"
    assert [l.qty_outstanding for l in purchasing.outstanding_lines(company)] == [D(40)]
    assert account_balance(acct(company, "1150")) == D(15000)
    assert account_balance(acct(company, "2115")) == D(15000)

    bill = purchasing.bill_from_order(po, owner)
    bl = bill.lines.get()
    assert bl.qty == 60
    bl.unit_price = D(260)  # supplier charged 10 more per unit
    bl.save()
    bill.supplier_invoice_no = "AD-991"
    bill.save()
    purchasing.post_bill(bill, owner)
    assert account_balance(acct(company, "2115")) == 0
    assert account_balance(acct(company, "5120")) == D(600)
    assert account_balance(acct(company, "1180")) == D("2184.00")
    assert account_balance(acct(company, "2110")) == D("17784.00")

    from purchases.models import SupplierPayment
    pay = SupplierPayment(company=company, date=TODAY, supplier=supplier, currency_id="EGP", amount=D("17784.00"),
                          method="bank", bank_account=cash, created_by=owner)
    purchasing.post_payment(pay, [(bill, D("17784.00"))], owner)
    assert account_balance(acct(company, "2110")) == 0


def test_expiry_date_is_recorded_and_enforced(company, wh, composite):
    with pytest.raises(stock.StockError):  # consumables need an expiry date
        stock.receive(composite, wh, 5, D(250), TODAY, "R0", batch_no="B0")
    with pytest.raises(stock.StockError):  # already expired goods are refused
        stock.receive(composite, wh, 5, D(250), TODAY, "R0", batch_no="B0", expiry_date=TODAY - timedelta(days=1))
    stock.receive(composite, wh, 4, D(250), TODAY - timedelta(days=60), "R1", batch_no="OLD",
                  expiry_date=TODAY - timedelta(days=30), kind="adjust_in")
    stock.receive(composite, wh, 6, D(250), TODAY, "R2", batch_no="NEW", expiry_date=TODAY + timedelta(days=45))
    rows = stock.batches_on_hand(company, wh)
    assert [(r["batch_no"], r["state"]) for r in rows] == [("OLD", "expired"), ("NEW", "soon")]
    with pytest.raises(stock.StockError):  # only 6 in date
        stock.issue(composite, wh, 7, TODAY, "INV-X")
    _cost, parts = stock.issue(composite, wh, 2, TODAY, "INV-Y")
    assert [p.layer.batch_no for p in parts] == ["NEW"]
    assert composite.moves.filter(ref="INV-Y").get().expiry_date == TODAY + timedelta(days=45)


def test_stock_count_posts_difference(company, owner, wh, composite):
    stock.receive(composite, wh, 10, D(250), TODAY, "R", batch_no="B", expiry_date=TODAY + timedelta(days=400))
    count = stock.start_count(company, wh, TODAY, owner)
    line = count.lines.get(item=composite)
    line.counted_qty = 8
    line.save()
    stock.post_count(count, owner)
    assert composite.on_hand(wh) == 8
    assert account_balance(acct(company, "5110")) == D(500)


def test_depreciation_and_disposal(company, owner, cash):
    cat = AssetCategory.objects.create(company=company, name_en="Vehicles", useful_life_months=60,
                                       asset_account=acct(company, "1210"), depreciation_account=acct(company, "1290"),
                                       expense_account=acct(company, "5800"))
    asset = Asset.objects.create(company=company, number=asset_services.next_asset_number(company), name_en="Van",
                                 category=cat, purchase_date=date(2026, 1, 1), in_service_date=date(2026, 1, 1),
                                 cost=D(600000), useful_life_months=60)
    assert asset.number == "FA-00001" and asset.monthly_charge == D(10000)
    asset_services.run_depreciation(company, date(2026, 1, 1), owner)
    with pytest.raises(asset_services.AssetError):
        asset_services.run_depreciation(company, date(2026, 1, 1), owner)
    assert account_balance(acct(company, "5800")) == D(10000)
    asset_services.dispose(asset, date(2026, 2, 1), D(595000), cash, owner)
    assert account_balance(acct(company, "4850")) == D(5000)  # sold 5,000 above book value
    count = asset_services.start_count(company, TODAY, owner)
    assert count.lines.count() == 0  # disposed assets are not counted


def test_time_engine_matches_published_example():
    s = PayrollSettings()
    r = engine.compute_payslip(basic=D(10000), allowances=D(2000), ot_day_hours=0, ot_night_hours=0, hours_short=0,
                               loan_deduction=D(500), other_deductions=D(0), insurable_override=None, s=s)
    assert r["si_employee"] == D("1320.00")  # 11% of 12,000
    assert r["gross"] == D("12000.00")
    assert r["net_pay"] == r["gross"] - r["total_deductions"]


def test_payroll_run_posts_every_deduction_to_its_account(company, owner, make_user, cash):
    dept = Department.objects.create(company=company, name_en="Sales")
    e1 = Employee.objects.create(company=company, code="1", name_en="A", department=dept, basic_salary=D(12000),
                                 hire_date=date(2025, 1, 1), insurable_wage=D(2700), medical_employee_share=D("424.50"))
    Employee.objects.create(company=company, code="2", name_en="B", basic_salary=D(6000), hire_date=date(2025, 1, 1),
                            insured=False, taxable=False, payment_method="cash", contract_type="contractor")
    Loan.objects.create(company=company, employee=e1, issue_date=date(2026, 1, 1), principal=D(5000),
                        monthly_deduction=D(1000), outstanding=D(5000))
    run = PayrollRun.objects.create(company=company, year=2026, month=9)
    payroll.compute_run(run)
    t = run.totals()
    assert t["si_employee"] == D("297.00") and t["loan_deduction"] == D(1000) and t["other_deductions"] == D("424.50")

    hr = make_user("hr@scigate.test", "HR officer")
    fm = make_user("fm@scigate.test", "Finance manager")
    md = make_user("md@scigate.test", "Managing director")
    from users.models import Membership
    payroll.submit(run, hr)
    with pytest.raises(payroll.PayrollError):
        payroll.approve(run, hr, Membership.objects.get(user=hr))
    payroll.approve(run, fm, Membership.objects.get(user=fm))
    run.refresh_from_db()
    assert run.status == "approved"
    payroll.authorise(run, md, Membership.objects.get(user=md))
    run.refresh_from_db()
    assert run.status == "authorised" and run.journal_entry_id
    si = t["si_employee"] + t["si_employer"] + t["emergency_fund"]
    assert account_balance(acct(company, "2160")) == si
    assert account_balance(acct(company, "2165")) == t["income_tax"]
    assert account_balance(acct(company, "2168")) == t["other_deductions"]
    assert account_balance(acct(company, "2155")) == t["net_pay"]
    assert account_balance(acct(company, "1170")) == D(-1000)  # loan recovered
    assert Loan.objects.get().outstanding == D(4000)

    bank = create_bank_account(company, kind="bank", currency="EGP", name_en="CIB", user=owner)
    payroll.mark_paid(run, fm, date(2026, 9, 30), bank, cash)
    assert account_balance(acct(company, "2155")) == 0
    payroll.remit(run, "si", fm, date(2026, 10, 10), bank)
    payroll.remit(run, "tax", fm, date(2026, 10, 10), bank)
    assert account_balance(acct(company, "2160")) == 0 and account_balance(acct(company, "2165")) == 0
