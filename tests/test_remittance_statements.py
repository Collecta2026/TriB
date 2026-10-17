"""Remittance advice after paying suppliers (print, email, several at once) and customer statements (open items,
ageing up to over 120 days, email and batch statements)."""
from datetime import timedelta

from django.core import mail
from django.urls import reverse

from contacts.models import Customer, Supplier
from purchases import services as purchasing
from purchases.models import Bill, BillLine, SupplierCredit, SupplierCreditLine, SupplierPayment
from purchases.remittance import remittance
from sales import services as sales
from sales.models import CustomerPayment, Invoice, InvoiceLine

from .conftest import TODAY, D, acct


# ---------- ageing columns ----------
def test_six_ageing_columns():
    assert [str(label) for _l, label in sales.AGING_BUCKETS][-2:] == ["91–120 days", "Over 120 days"]
    assert [sales.bucket_for(d) for d in (-5, 0, 1, 30, 31, 60, 61, 90, 91, 120, 121, 400)] == [0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5]


def _invoice(company, owner, customer, days_ago, amount):
    day = TODAY - timedelta(days=days_ago)
    inv = Invoice.objects.create(company=company, customer=customer, date=day, due_date=day + timedelta(days=30),
                                 currency_id="EGP", created_by=owner)
    InvoiceLine.objects.create(document=inv, description="Service", qty=D(1), unit_price=D(amount), account=acct(company, "4100"))
    sales.post_invoice(inv, owner, allow_over_limit=True)
    return inv


def _customers(company, owner, cash):
    clinic = Customer.objects.create(company=company, code="C1", name_en="Delta Clinic", currency_id="EGP",
                                     email="accounts@delta.test")
    lab = Customer.objects.create(company=company, code="C2", name_en="Nile Lab", currency_id="EGP")  # no email
    _invoice(company, owner, clinic, 10, 1000)      # not yet due
    _invoice(company, owner, clinic, 80, 2000)      # 50 days overdue → 31–60
    old = _invoice(company, owner, clinic, 160, 3000)  # 130 days overdue → over 120
    pay = CustomerPayment(company=company, date=TODAY, customer=clinic, currency_id="EGP", amount=D(1200),
                          method="cash", bank_account=cash, created_by=owner)
    sales.post_payment(pay, [(old, D(1000))], owner)   # 200 left on account
    _invoice(company, owner, lab, 140, 500)         # 110 days overdue → 91–120
    return clinic, lab


def test_open_item_statement_ages_every_invoice(company, owner, cash):
    clinic, _lab = _customers(company, owner, cash)
    data = sales.open_items(clinic, TODAY)
    assert data["aging"] == [D(800), 0, D(2000), 0, 0, D(2000)]   # 1,000 not yet due less 200 paid on account
    assert data["total"] == D(4800) == sales.customer_balance(clinic)
    old = next(r for r in data["rows"] if r["bucket"] == 5)
    assert old["days"] == 130 and old["settled"] == D(1000) and old["open"] == D(2000)
    # The balance-forward statement shows the same ageing.
    assert sales.statement(clinic, TODAY - timedelta(days=200), TODAY)["aging"] == data["aging"]


def test_statement_opens_straight_from_the_customer_page(company, owner, cash, client):
    clinic, _lab = _customers(company, owner, cash)
    client.force_login(owner)
    html = client.get(reverse("sales:statements") + f"?customer={clinic.pk}").content.decode()
    assert "Statement of Account" in html and "Over 120 days" in html and "91–120 days" in html
    html = client.get(reverse("sales:statements") + f"?customer={clinic.pk}&style=open").content.decode()
    assert "Days overdue" in html and "4,800.00" in html


def test_statement_is_emailed_with_the_statement_inside(company, owner, cash, client):
    clinic, _lab = _customers(company, owner, cash)
    client.force_login(owner)
    url = reverse("sales:statement_email") + f"?customer={clinic.pk}&style=open"
    page = client.get(url)
    assert page.status_code == 200 and "accounts@delta.test" in page.content.decode()
    client.post(url, {"to": "accounts@delta.test", "subject": "Statement", "message": "Dear Delta Clinic"})
    assert len(mail.outbox) == 1
    html = mail.outbox[0].alternatives[0][0]
    assert "Over 120 days" in html and "4,800.00" in html and "Delta Clinic" in html


def test_batch_statements_print_and_email(company, owner, cash, client):
    _customers(company, owner, cash)
    client.force_login(owner)
    query = f"which=balance&style=open&date_from={TODAY.replace(month=1, day=1)}&date_to={TODAY}"
    page = client.get(reverse("sales:statements_batch") + "?" + query).content.decode()
    assert "Delta Clinic" in page and "Nile Lab" in page
    printed = client.get(reverse("sales:statements_batch") + "?" + query + "&print=1").content.decode()
    assert printed.count("Statement of Account") == 2
    client.post(reverse("sales:statements_batch") + "?" + query)
    assert [m.to for m in mail.outbox] == [["accounts@delta.test"]]       # Nile Lab has no email address


# ---------- remittance advice ----------
def _bill(company, owner, supplier, ref, amount, days_ago):
    day = TODAY - timedelta(days=days_ago)
    bill = Bill.objects.create(company=company, supplier=supplier, date=day, due_date=day + timedelta(days=30),
                               currency_id="EGP", supplier_invoice_no=ref, created_by=owner)
    BillLine.objects.create(document=bill, description="Supplies", qty=D(1), unit_price=D(amount), account=acct(company, "5300"))
    purchasing.post_bill(bill, owner)
    return bill


def _pay(company, owner, supplier, cash, amount, allocations, days_ago=0, reference=""):
    p = SupplierPayment(company=company, date=TODAY - timedelta(days=days_ago), supplier=supplier, currency_id="EGP",
                        amount=D(amount), method="cash", bank_account=cash, reference=reference, created_by=owner)
    purchasing.post_payment(p, [(b, D(a)) for b, a in allocations], owner)
    return p


def _supplier_case(company, owner, cash):
    medent = Supplier.objects.create(company=company, code="S1", name_en="Medent Italia", currency_id="EGP",
                                     email="ar@medent.test")
    b1 = _bill(company, owner, medent, "MI-100", 10000, 40)
    b2 = _bill(company, owner, medent, "MI-101", 6000, 20)
    credit = SupplierCredit.objects.create(company=company, supplier=medent, date=TODAY - timedelta(days=5),
                                           currency_id="EGP", supplier_credit_no="CN-7", created_by=owner)
    SupplierCreditLine.objects.create(document=credit, description="Allowance", qty=D(1), unit_price=D(1500),
                                      account=acct(company, "5300"), return_stock=False)
    purchasing.post_supplier_credit(credit, owner)
    purchasing.apply_supplier_credit(credit, b1, D(1500), owner, date=TODAY - timedelta(days=5))
    _pay(company, owner, medent, cash, 2000, [(b2, 2000)], days_ago=3)
    pay = _pay(company, owner, medent, cash, 13000, [(b1, 8500), (b2, 3000)], reference="FT-2210")
    return medent, b1, b2, pay


def test_remittance_shows_credits_earlier_payments_and_what_is_left(company, owner, cash):
    _medent, _b1, _b2, pay = _supplier_case(company, owner, cash)
    r = remittance(pay)
    first, second = r["rows"]
    assert (first["your_ref"], first["amount"], first["credited"], first["before"], first["now"], first["open"]) == (
        "MI-100", D(10000), D(1500), 0, D(8500), 0)
    assert (second["your_ref"], second["before"], second["now"], second["open"]) == ("MI-101", D(2000), D(3000), D(1000))
    assert r["advance"] == D(1500) and r["credits"][0]["your_ref"] == "CN-7"


def test_paying_a_supplier_goes_to_the_remittance_advice(company, owner, cash, client):
    medent = Supplier.objects.create(company=company, code="S1", name_en="Medent Italia", currency_id="EGP")
    bill = _bill(company, owner, medent, "MI-200", 5000, 10)
    client.force_login(owner)
    r = client.post(reverse("purchases:payment_new"), {
        "supplier": medent.pk, "date": TODAY.isoformat(), "currency": "EGP", "rate": "1", "amount": "5000",
        "method": "cash", "bank_account": cash.pk, f"alloc_{bill.pk}": "5000", "save": "1"})
    pay = SupplierPayment.objects.get(supplier=medent)
    assert r.status_code == 302 and r["Location"] == reverse("purchases:payment_print", args=[pay.pk]) + "?paid=1"
    html = client.get(r["Location"]).content.decode()
    assert "Remittance Advice" in html and "MI-200" in html and reverse("purchases:remittance_email") in html


def test_remittance_email_and_several_at_once(company, owner, cash, client):
    medent, _b1, _b2, pay = _supplier_case(company, owner, cash)
    earlier = SupplierPayment.objects.exclude(pk=pay.pk).get(supplier=medent)
    client.force_login(owner)
    url = reverse("purchases:remittance_email") + f"?ids={earlier.pk},{pay.pk}"
    assert "ar@medent.test" in client.get(url).content.decode()
    client.post(url, {"to": "ar@medent.test", "subject": "Remittance", "message": "Dear Medent"})
    html = mail.outbox[0].alternatives[0][0]
    assert mail.outbox[0].to == ["ar@medent.test"] and "MI-100" in html and "FT-2210" in html and html.count("Remittance advice") >= 2
    # Supplier page → select payments → Print selected.
    page = client.get(reverse("core:batch_print") + f"?items=purchases:payment:{earlier.pk},purchases:payment:{pay.pk}")
    assert page.content.decode().count("Remittance Advice") == 2
    hub = client.get(reverse("contacts:supplier", args=[medent.pk])).content.decode()
    assert f'data-sel="purchases:payment:{pay.pk}"' in hub and 'data-batch="remittance-email"' in hub
