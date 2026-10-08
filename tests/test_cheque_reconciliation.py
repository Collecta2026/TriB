"""Cheques against the bank statement, returned cheques from the bank's list, and the reconciliation report."""
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from banking import services as banking
from banking.models import Cheque, StatementLine
from banking.services import create_bank_account
from contacts.models import Customer, Supplier
from ledger.services import account_balance, system_account
from purchases import services as purchasing
from purchases.models import SupplierPayment
from sales import services as sales
from sales.models import CustomerPayment

from .conftest import TODAY, D, acct


@pytest.fixture
def bank(company, owner):
    from ledger.services import Line, post_journal
    account = create_bank_account(company, kind="bank", currency="EGP", name_en="CIB", user=owner)
    post_journal(company, TODAY - timedelta(days=40), [Line(account.gl_account, debit=D(500000)),
                                                       Line(acct(company, "3100"), credit=D(500000))],
                 memo="Opening", source="opening", user=owner)
    return account


@pytest.fixture
def customer(company):
    return Customer.objects.create(company=company, code="CUS-1", name_en="Nile Smile Clinics", currency_id="EGP")


def _issued(company, owner, bank, number, amount):
    supplier = Supplier.objects.get_or_create(company=company, code="SUP-1",
                                              defaults={"name_en": "Alpha Dental", "currency_id": "EGP"})[0]
    pay = SupplierPayment(company=company, date=TODAY - timedelta(days=20), supplier=supplier, currency_id="EGP",
                          amount=D(amount), method="cheque", bank_account=bank, cheque_number=number,
                          cheque_due_date=TODAY - timedelta(days=5), created_by=owner)
    purchasing.post_payment(pay, [], owner)
    return pay.cheque


def _received(company, owner, customer, number, amount, bank=None):
    pay = CustomerPayment(company=company, date=TODAY - timedelta(days=20), customer=customer, currency_id="EGP",
                          amount=D(amount), method="cheque", cheque_number=number, cheque_bank="Banque Misr",
                          cheque_due_date=TODAY - timedelta(days=6), created_by=owner)
    sales.post_payment(pay, [], owner)
    cheque = pay.cheque
    if bank:
        banking.deposit_for_collection(cheque, bank, TODAY - timedelta(days=6), owner)
        cheque.refresh_from_db()
    return cheque


def _upload(client, bank, csv_text):
    client.post(reverse("banking:transactions_import"),
                {"bank_account": bank.pk, "file": SimpleUploadedFile("st.csv", csv_text.encode())})
    return client.post(reverse("banking:transactions_map"),
                       {"date": "0", "description": "1", "reference": "2", "debit": "3", "credit": "4", "header": "1"})


def test_statement_clears_cheques_and_updates_cheques_payable(client, company, owner, bank, customer):
    out = _issued(company, owner, bank, "000123", "45000")
    inn = _received(company, owner, customer, "551209", "30000", bank)
    payable = system_account(company, "notes_payable")
    assert account_balance(payable) == D(45000)
    client.force_login(owner)
    day = (TODAY - timedelta(days=2)).strftime("%d/%m/%Y")
    _upload(client, bank, "Date,Details,Ref,Debit,Credit\n"
                          f"{day},Cheque paid,CHQ 123,45000.00,\n"
                          f"{day},Cheque deposit cleared,551209,,30000.00\n"
                          f"{day},Bank charges,,25.00,\n")
    out.refresh_from_db(); inn.refresh_from_db()
    assert (out.status, out.cleared_on) == ("cleared", TODAY - timedelta(days=2))
    assert inn.status == "cleared"
    assert account_balance(payable) == 0                       # the payable ledger is updated
    assert account_balance(bank.gl_account) == D(500000 - 45000 + 30000)
    assert StatementLine.objects.filter(status="matched").count() == 2
    assert StatementLine.objects.get(status="new").description == "Bank charges"
    page = client.get(reverse("banking:cheque_reconciliation") + f"?account={bank.pk}&from={(TODAY - timedelta(days=30)).isoformat()}"
                      f"&to={TODAY.isoformat()}&statement_balance=484975").content.decode()
    assert "#000123" in page and "#551209" in page
    report = client.get(reverse("banking:cheque_reconciliation") + f"?account={bank.pk}&statement_balance=484975&format=xlsx")
    assert report["Content-Type"].startswith("application/vnd.openxml")


def test_amount_mismatch_is_only_suggested(client, company, owner, bank):
    _issued(company, owner, bank, "000777", "10000")
    client.force_login(owner)
    _upload(client, bank, f"Date,Details,Ref,Debit,Credit\n{TODAY:%d/%m/%Y},Cheque 777,,10500.00,\n")
    line = StatementLine.objects.get()
    assert line.status == "new"
    from banking.feeds import cheque_candidates
    assert [how for _c, how in cheque_candidates(line)] == ["number"]


def test_bank_list_of_returned_cheques_then_resubmit_and_settle(client, company, owner, bank, customer):
    cheque = _received(company, owner, customer, "777001", "20000", bank)
    assert sales.customer_balance(customer) == D(-20000)
    client.force_login(owner)
    page = client.post(reverse("banking:bounced"), {"date": TODAY.isoformat(), "reference": "CIB-RET-55",
                                                    "numbers": "777001, insufficient funds\n999999", "preview": "1"})
    html = page.content.decode()
    assert "#777001" in html and "Not found in TriB" in html
    client.post(reverse("banking:bounced"), {"confirm": "1", "cheque": [cheque.pk]})
    cheque.refresh_from_db()
    assert (cheque.status, cheque.bounce_reason, cheque.bounce_count) == ("bounced", "insufficient funds", 1)
    assert sales.customer_balance(customer) == 0                # owed again
    assert any(r["contact"] == customer for r in sales.ar_aging(company, TODAY))
    statement = sales.statement(customer, TODAY - timedelta(days=30), TODAY)
    assert any("returned" in str(r["kind"]) for r in statement["rows"])

    client.post(reverse("banking:returned_action", args=[cheque.pk]),
                {"action": "resubmit", "bank_account": bank.pk, "date": TODAY.isoformat()})
    cheque.refresh_from_db()
    assert cheque.status == "under_collection" and sales.customer_balance(customer) == D(-20000)

    banking.bounce_cheque(cheque, TODAY, owner, reason="signature differs")
    cash = company.bank_accounts.get(kind="cash")
    client.post(reverse("banking:returned_action", args=[cheque.pk]),
                {"action": "settle", "bank_account": cash.pk, "date": TODAY.isoformat(), "reference": "RC cash"})
    cheque.refresh_from_db()
    assert cheque.status == "settled" and cheque.bounce_count == 2
    assert sales.customer_balance(customer) == D(-20000)        # paid in cash instead
    assert account_balance(cash.gl_account) == D(20000)
    assert client.get(reverse("banking:bounced")).status_code == 200


@pytest.mark.parametrize("lang", ["en", "ar"])
def test_cheque_pages_render(client, company, owner, bank, lang):
    client.force_login(owner)
    client.cookies["django_language"] = lang
    for name in ("banking:bounced", "banking:cheque_reconciliation", "banking:cheques"):
        assert client.get(reverse(name)).status_code == 200, name
