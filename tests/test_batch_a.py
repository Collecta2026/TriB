"""Batch A of the QuickBooks Create menu: credit notes, refunds, sales receipts, supplier credits, transfers, deposits."""
from datetime import timedelta

import pytest
from django.urls import reverse

from banking import services as banking
from banking.models import BankTransfer, Cheque
from banking.services import create_bank_account
from contacts.models import Customer, Supplier
from core.models import ExchangeRate
from inventory import services as stock
from inventory.models import Item, Warehouse
from ledger.models import TaxRate
from ledger.services import Line, account_balance, post_journal, system_account
from purchases import services as purchasing
from purchases.models import Bill, BillLine, SupplierCredit, SupplierCreditLine
from sales import services as sales
from sales.models import CreditNote, CreditNoteLine, CustomerPayment, CustomerRefund, Invoice, InvoiceLine

from .conftest import TODAY, D, acct


@pytest.fixture
def wh(company):
    return Warehouse.objects.get(company=company, code="MAIN")


@pytest.fixture
def vat14(company):
    return TaxRate.objects.get(company=company, rate=14)


@pytest.fixture
def bur(company, wh):
    item = Item.objects.create(company=company, sku="SUP-00001", name_en="Diamond bur set", sales_price=D(1000),
                               purchase_cost=D(600))
    stock.receive(item, wh, 20, D(600), TODAY - timedelta(days=30), "OPEN")
    return item


@pytest.fixture
def customer(company):
    return Customer.objects.create(company=company, code="CUS-1", name_en="Nile Smile Clinics", currency_id="EGP")


@pytest.fixture
def bank(company, owner):
    account = create_bank_account(company, kind="bank", currency="EGP", name_en="CIB", user=owner)
    post_journal(company, TODAY - timedelta(days=40), [Line(account.gl_account, debit=D(1000000)),
                                                       Line(acct(company, "3100"), credit=D(1000000))],
                 memo="Opening", source="opening", user=owner)
    return account


def _invoice(company, owner, customer, wh, item, qty, vat):
    inv = Invoice.objects.create(company=company, customer=customer, date=TODAY - timedelta(days=5),
                                 due_date=TODAY + timedelta(days=25), currency_id="EGP", warehouse=wh, created_by=owner)
    InvoiceLine.objects.create(document=inv, item=item, qty=D(qty), unit_price=item.sales_price, tax_rate=vat)
    sales.post_invoice(inv, owner)
    return inv


def test_credit_note_returns_goods_and_reduces_the_invoice(company, owner, customer, wh, bur, vat14):
    inv = _invoice(company, owner, customer, wh, bur, 5, vat14)  # 5 × 1,000 + 14% = 5,700
    note = CreditNote.objects.create(company=company, customer=customer, invoice=inv, date=TODAY, currency_id="EGP",
                                     warehouse=wh, created_by=owner)
    CreditNoteLine.objects.create(document=note, item=bur, qty=D(2), unit_price=D(1000), tax_rate=vat14)
    sales.post_credit_note(note, owner)
    inv.refresh_from_db(); note.refresh_from_db()
    assert note.total == D(2280) and note.amount_applied == D(2280)
    assert inv.balance_due == D(3420)
    assert sales.customer_balance(customer) == D(3420)
    assert bur.on_hand(wh) == 17                                     # 20 − 5 sold + 2 back
    assert account_balance(acct(company, "1130")) == D(3420)         # receivables
    assert note.lines.get().cost == D(1200)                          # back at the cost it was sold at
    page = sales.statement(customer, TODAY - timedelta(days=30), TODAY)
    assert page["closing"] == D(3420)


def test_unused_credit_is_refunded(company, owner, customer, wh, bur, vat14, bank):
    note = CreditNote.objects.create(company=company, customer=customer, date=TODAY, currency_id="EGP", created_by=owner)
    CreditNoteLine.objects.create(document=note, description="Goodwill allowance", qty=D(1), unit_price=D(500))
    sales.post_credit_note(note, owner)
    assert sales.customer_balance(customer) == D(-500)
    refund = CustomerRefund(company=company, customer=customer, credit_note=note, date=TODAY, currency_id="EGP",
                            amount=D(500), method="bank", bank_account=bank, created_by=owner)
    sales.post_refund(refund, owner)
    note.refresh_from_db()
    assert note.available == 0 and sales.customer_balance(customer) == 0
    assert account_balance(bank.gl_account) == D(999500)
    with pytest.raises(sales.SalesError):
        sales.post_refund(CustomerRefund(company=company, customer=customer, date=TODAY, currency_id="EGP", amount=D(1),
                                         method="bank", bank_account=bank, created_by=owner), owner)


def test_sales_receipt_is_paid_on_the_spot(client, company, owner, customer, wh, bur, vat14):
    cash = company.bank_accounts.get(kind="cash")
    client.force_login(owner)
    data = {"customer": customer.pk, "date": TODAY.isoformat(), "deposit_to": cash.pk, "warehouse": wh.pk,
            "currency": "EGP", "rate": "1", "reference": "", "notes": "",
            "lines-TOTAL_FORMS": "1", "lines-INITIAL_FORMS": "0", "lines-MIN_NUM_FORMS": "0", "lines-MAX_NUM_FORMS": "1000",
            "lines-0-item": bur.pk, "lines-0-description": "Diamond bur set", "lines-0-qty": "1", "lines-0-unit_price": "1000",
            "lines-0-discount_pct": "0", "lines-0-tax_rate": vat14.pk, "post": "1"}
    response = client.post(reverse("sales:sales_receipt_new"), data)
    assert response.status_code == 302
    inv = Invoice.objects.get()
    assert inv.status == "posted" and inv.payment_state == "paid"
    assert account_balance(cash.gl_account) == D(1140)
    assert CustomerPayment.objects.get().allocations.get().invoice == inv


def test_supplier_credit_returns_goods_and_reduces_the_bill(company, owner, wh, bur, vat14):
    supplier = Supplier.objects.create(company=company, code="SUP-1", name_en="Alpha Dental", currency_id="EGP")
    bill = Bill.objects.create(company=company, supplier=supplier, date=TODAY - timedelta(days=3), due_date=TODAY + timedelta(days=27),
                               currency_id="EGP", warehouse=wh, supplier_invoice_no="AD-1", created_by=owner)
    BillLine.objects.create(document=bill, item=bur, qty=D(10), unit_price=D(600), tax_rate=vat14)
    purchasing.post_bill(bill, owner)                                # 6,000 + 840
    credit = SupplierCredit.objects.create(company=company, supplier=supplier, bill=bill, date=TODAY, currency_id="EGP",
                                           warehouse=wh, supplier_credit_no="AD-CN-1", created_by=owner)
    SupplierCreditLine.objects.create(document=credit, item=bur, qty=D(3), unit_price=D(600), tax_rate=vat14)
    purchasing.post_supplier_credit(credit, owner)
    bill.refresh_from_db()
    assert bill.balance_due == D(6840) - D(2052)
    assert purchasing.supplier_balance(supplier) == D(4788)
    assert bur.on_hand(wh) == 27                                     # 20 + 10 − 3
    assert account_balance(acct(company, "2110")) == D(4788)         # payables


def test_transfer_between_currencies_books_the_difference(company, owner, bank):
    usd = create_bank_account(company, kind="bank", currency="USD", name_en="CIB USD", user=owner)
    ExchangeRate.objects.create(company=company, currency_id="USD", date=TODAY, rate=D("48.50"))
    transfer = BankTransfer(company=company, date=TODAY, from_account=bank, to_account=usd, amount=D(49000),
                            amount_to=D(1000), created_by=owner)
    banking.post_transfer(transfer, owner)
    assert account_balance(bank.gl_account) == D(951000)
    assert account_balance(usd.gl_account) == D(48500)
    assert account_balance(system_account(company, "fx_loss")) == D(500)


def test_deposit_slip_pays_in_cheques_and_cash(company, owner, bank):
    cash = company.bank_accounts.get(kind="cash")
    post_journal(company, TODAY, [Line(cash.gl_account, debit=D(3000)), Line(acct(company, "3100"), credit=D(3000))],
                 memo="Float", source="opening", user=owner)
    customer = Customer.objects.create(company=company, code="CUS-9", name_en="Delta Dental", currency_id="EGP")
    pays = []
    for n, amount in (("111222", "7000"), ("333444", "5000")):
        p = CustomerPayment(company=company, date=TODAY, customer=customer, currency_id="EGP", amount=D(amount),
                            method="cheque", cheque_number=n, cheque_due_date=TODAY, created_by=owner)
        sales.post_payment(p, [], owner)
        pays.append(p.cheque)
    from banking.models import BankDeposit
    dep = BankDeposit(company=company, date=TODAY, bank_account=bank, reference="SLIP-77", cash_from=cash,
                      cash_amount=D(2500), created_by=owner)
    banking.post_deposit(dep, pays, owner)
    assert dep.total == D(14500)
    assert set(Cheque.objects.values_list("status", flat=True)) == {"under_collection"}
    assert account_balance(cash.gl_account) == D(500)
    assert account_balance(bank.gl_account) == D(1002500)


@pytest.mark.parametrize("lang", ["en", "ar"])
def test_new_screens_and_create_menu(client, company, owner, lang):
    client.force_login(owner)
    client.cookies["django_language"] = lang
    for name in ("sales:credits", "sales:credit_new", "sales:refunds", "sales:refund_new", "sales:sales_receipt_new",
                 "purchases:supplier_credits", "purchases:supplier_credit_new", "banking:transfers", "banking:deposits",
                 "banking:deposit_new"):
        assert client.get(reverse(name)).status_code == 200, name
    home = client.get(reverse("dashboard:home")).content.decode()
    for name in ("sales:credit_new", "sales:sales_receipt_new", "sales:refund_new", "purchases:supplier_credit_new",
                 "banking:deposit_new", "banking:transfers", "projects:new"):
        assert reverse(name) in home, name
    assert client.get(reverse("vouchers:new", args=["payment"]) + "?method=cheque").status_code == 200
