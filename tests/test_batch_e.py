"""Batch E: action bar (Save ▾, More actions, share link, WhatsApp, Review and send), QuickBooks invoice header
(terms, shipping, VAT-inclusive amounts, tags), the customer page, feed tiles and the cash forecast."""
from datetime import timedelta

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from banking.models import Cheque
from banking.services import create_bank_account
from contacts.models import Customer
from core.doc_actions import whatsapp_number
from core.models import AuditLog, ShareLink
from inventory.models import Item, Warehouse
from ledger.models import JournalLine, TaxRate
from ledger.services import Line, post_journal, system_account
from sales import services as sales
from sales.models import Invoice, InvoiceLine

from .conftest import D, acct


@pytest.fixture
def setup(company, owner):
    today = timezone.localdate()
    bank = create_bank_account(company, kind="bank", currency="EGP", name_en="CIB", user=owner)
    post_journal(company, today - timedelta(days=30), [Line(bank.gl_account, debit=D(100000)),
                                                       Line(acct(company, "3100"), credit=D(100000))],
                 memo="Opening", source="opening", user=owner)
    customer = Customer.objects.create(company=company, code="CUS-1", name_en="Nile Smile", currency_id="EGP",
                                       email="ap@nilesmile.example", phone="01001234567", address="12 Tahrir St",
                                       shipping_address="Clinic 3, Maadi", payment_terms_days=30)
    vat = TaxRate.objects.get(company=company, rate=14)
    service = Item.objects.create(company=company, sku="SRV-1", name_en="Installation", type="service", sales_price=D(1140))
    return {"today": today, "bank": bank, "customer": customer, "vat": vat, "service": service}


def _invoice(company, owner, s, inclusive=False, due_days=30, post=True, **extra):
    inv = Invoice.objects.create(company=company, customer=s["customer"], date=s["today"],
                                 due_date=s["today"] + timedelta(days=due_days), currency_id="EGP", created_by=owner,
                                 prices_include_tax=inclusive, **extra)
    InvoiceLine.objects.create(document=inv, item=s["service"], qty=D(1), unit_price=D(1140), tax_rate=s["vat"])
    if post:
        sales.post_invoice(inv, owner)
    return inv


def test_vat_inclusive_amounts_post_correctly(company, owner, setup):
    inv = _invoice(company, owner, setup, inclusive=True)
    assert (inv.subtotal, inv.tax_total, inv.total) == (D(1000), D(140), D(1140))
    lines = JournalLine.objects.filter(entry=inv.journal_entry)
    assert sum(l.debit for l in lines) == D(1140)
    assert lines.get(account=system_account(company, "vat_output")).credit == D(140)
    exclusive = _invoice(company, owner, setup)
    assert (exclusive.subtotal, exclusive.total) == (D(1140), D("1299.60"))


def test_invoice_form_header_terms_and_new_fields(client, company, owner, setup):
    client.force_login(owner)
    page = client.get(reverse("sales:invoice_new") + f"?customer={setup['customer'].pk}")
    html = page.content.decode()
    for name in ("email_to", "email_cc", "bill_to", "ship_to", "ship_via", "tracking_no", "customer_po", "terms",
                 "prices_include_tax", "tags"):
        assert f'name="{name}"' in html, name
    form = page.context["form"]
    assert form.initial["terms"] == "net30" and form.initial["email_to"] == "ap@nilesmile.example"
    assert "Clinic 3, Maadi" in form.initial["ship_to"]
    assert 'class="abar' in html and "Save and new" in html and "Make a copy" not in html
    data = {"customer": setup["customer"].pk, "terms": "net15", "date": setup["today"].isoformat(), "due_date": "",
            "currency": "EGP", "rate": "1", "prices_include_tax": "True", "tags": "Haulage: Same day, urgent",
            "email_to": "a@x.example", "ship_via": "Aramex", "save": "new",
            "lines-TOTAL_FORMS": "1", "lines-INITIAL_FORMS": "0", "lines-MIN_NUM_FORMS": "0", "lines-MAX_NUM_FORMS": "1000",
            "lines-0-item": setup["service"].pk, "lines-0-description": "Install", "lines-0-qty": "1",
            "lines-0-unit_price": "1140", "lines-0-discount_pct": "0", "lines-0-tax_rate": setup["vat"].pk}
    r = client.post(reverse("sales:invoice_new"), data)
    assert r.status_code == 302 and r["Location"] == reverse("sales:invoice_new")  # Save and new
    inv = Invoice.objects.get(ship_via="Aramex")
    assert inv.due_date == setup["today"] + timedelta(days=15)
    assert inv.tags == ["Haulage: Same day", "urgent"] and inv.prices_include_tax and inv.total == D(1140)
    listing = client.get(reverse("sales:invoices"), {"tag": "urgent"}).content.decode()
    assert "Tag: urgent" in listing


def test_more_actions_copy_delete_void(client, company, owner, setup):
    client.force_login(owner)
    inv = _invoice(company, owner, setup, tags=["x"])
    detail = client.get(reverse("sales:invoice", args=[inv.pk])).content.decode()
    for label in ("Print or download", "Make recurring", "Make a copy", "Void", "Transaction journal", "Audit history",
                  "Review and send", "Share link"):
        assert label in detail, label
    r = client.post(reverse("core:doc_copy", args=["sales", "invoice", inv.pk]))
    copy = Invoice.objects.exclude(pk=inv.pk).get()
    assert r["Location"] == reverse("sales:invoice_edit", args=[copy.pk])
    assert copy.status == "draft" and not copy.number and copy.lines.count() == 1 and copy.tags == ["x"]
    client.post(reverse("core:doc_delete", args=["sales", "invoice", inv.pk]))
    assert Invoice.objects.filter(pk=inv.pk).exists()  # posted documents are not deleted
    client.post(reverse("core:doc_delete", args=["sales", "invoice", copy.pk]))
    assert not Invoice.objects.filter(pk=copy.pk).exists()
    client.post(reverse("sales:invoice_action", args=[inv.pk]), {"action": "void"})
    inv.refresh_from_db()
    assert inv.status == "void"
    audit = client.get(reverse("core:audit"), {"type": "sales.Invoice", "id": inv.pk, "q": inv.number})
    assert audit.status_code == 200


def test_share_link_whatsapp_and_public_page(client, company, owner, setup):
    client.force_login(owner)
    inv = _invoice(company, owner, setup)
    draft = _invoice(company, owner, setup, post=False)
    assert client.post(reverse("core:doc_share", args=["sales", "invoice", draft.pk])).status_code == 400
    data = client.post(reverse("core:doc_share", args=["sales", "invoice", inv.pk])).json()
    assert data["whatsapp"].startswith("https://wa.me/201001234567?text=") and inv.number in data["whatsapp"]
    token = ShareLink.objects.get().token
    assert data["url"].endswith(reverse("core:shared", args=[token]))
    client.logout()
    page = client.get(reverse("core:shared", args=[token]))
    assert page.status_code == 200 and inv.number in page.content.decode() and "noindex" in page.content.decode()
    client.force_login(owner)
    client.post(reverse("core:doc_share", args=["sales", "invoice", inv.pk]), {"revoke": "1"})
    client.logout()
    assert client.get(reverse("core:shared", args=[token])).status_code == 404
    assert client.get(reverse("core:shared", args=["nope"])).status_code == 404
    assert whatsapp_number("+20 100 123 4567") == "201001234567" and whatsapp_number("00971501234567") == "971501234567"


def test_review_and_send_email(client, company, owner, setup):
    client.force_login(owner)
    inv = _invoice(company, owner, setup, email_cc="boss@nilesmile.example")
    page = client.get(reverse("core:doc_send", args=["sales", "invoice", inv.pk]))
    assert page.context["form"].initial["to"] == "ap@nilesmile.example"
    r = client.post(reverse("core:doc_send", args=["sales", "invoice", inv.pk]),
                    {"to": "ap@nilesmile.example", "cc": "boss@nilesmile.example", "bcc": "", "subject": "Invoice",
                     "message": "Please pay"})
    assert r.status_code == 302 and len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert msg.to == ["ap@nilesmile.example"] and msg.cc == ["boss@nilesmile.example"]
    assert "/s/" in msg.body and AuditLog.objects.filter(action="invoice.sent").exists()
    bad = client.post(reverse("core:doc_send", args=["sales", "invoice", inv.pk]),
                      {"to": "not-an-email", "subject": "x", "message": "y"})
    assert bad.status_code == 200 and len(mail.outbox) == 1
    embed = client.get(reverse("sales:invoice_print", args=[inv.pk]) + "?embed=1")
    assert embed["X-Frame-Options"] == "SAMEORIGIN"
    delivery = client.get(reverse("sales:invoice_print", args=[inv.pk]) + "?delivery=1").content.decode()
    assert "Delivery Note" in delivery and "1,140.00" not in delivery


@pytest.mark.parametrize("lang", ["en", "ar"])
def test_customer_page_tabs_filters_and_batch_print(client, company, owner, setup, lang):
    client.force_login(owner)
    client.cookies["django_language"] = lang
    late = _invoice(company, owner, setup, due_days=-5)
    current = _invoice(company, owner, setup)
    url = reverse("contacts:customer", args=[setup["customer"].pk])
    page = client.get(url)
    html = page.content.decode()
    assert page.status_code == 200 and 'data-panel="transactions"' in html and 'data-panel="notes"' in html
    assert page.context["overdue"] == D("1299.60")
    overdue = client.get(url, {"tab": "transactions", "status": "overdue"}).context["rows"]
    assert [r["number"] for r in overdue] == [late.number]
    assert len(client.get(url, {"type": "invoice"}).context["rows"]) == 2
    batch = client.get(reverse("core:batch_print"), {"items": f"sales:invoice:{late.pk},sales:invoice:{current.pk},x:y:1"})
    assert batch.status_code == 200 and len(batch.context["docs"]) == 2
    client.post(reverse("contacts:customer_notes", args=[setup["customer"].pk]), {"notes": "Prefers WhatsApp"})
    setup["customer"].refresh_from_db()
    assert setup["customer"].notes == "Prefers WhatsApp"


def test_cash_forecast_and_minimum_alert(client, company, owner, setup):
    from reports.forecast import cash_forecast

    today = setup["today"]
    Cheque.objects.create(company=company, direction="out", number="900", amount=D(80000), currency_id="EGP",
                          due_date=today + timedelta(days=9), issue_date=today, status="issued", party_name="Landlord")
    company.minimum_cash = D(50000)
    company.save()
    fc = cash_forecast(company, today)
    assert fc["opening"] == D(100000) and fc["rows"][1]["cheques_out"] == D(80000)
    assert fc["first_below"] is fc["rows"][1]
    client.force_login(owner)
    home = client.get(reverse("dashboard:home")).content.decode()
    assert "Cash falls below your EGP 50,000 minimum" in home and reverse("reports:cash_forecast") in home
    assert reverse("core:alerts") in home and "ftile" in home
    assert client.get(reverse("reports:cash_forecast")).status_code == 200


def test_other_entry_screens_have_the_action_bar(client, company, owner):
    client.force_login(owner)
    for url in (reverse("vouchers:new", args=["payment"]), reverse("purchases:receipt_new"),
                reverse("inventory:adjustment_new"), reverse("purchases:bill_new"), reverse("sales:quote_new")):
        html = client.get(url).content.decode()
        assert 'class="abar' in html and "Save and close" in html, url
