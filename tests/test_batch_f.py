"""Batch F: line grid (positions, subtotals), draft printing, expenses list and reclassification, import bills, filter
chips, contact pages, Customer Hub (CRM) and the Help centre."""
import io
import json
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from openpyxl import Workbook

from contacts.models import Customer, Supplier
from crm.models import Contract, Lead, Opportunity, Proposal, Review, Task
from inventory.models import Item, Warehouse
from ledger.models import Account, JournalEntry, TaxRate
from purchases import services as purchasing
from purchases.models import Bill, BillLine, PurchaseOrder, PurchaseOrderLine
from sales.models import Invoice, Quotation, QuotationLine

from .conftest import D


@pytest.fixture
def base(company, owner):
    today = timezone.localdate()
    customer = Customer.objects.create(company=company, code="CUS-1", name_en="Nile Smile", currency_id="EGP",
                                       phone="01001234567", email="ap@nilesmile.example")
    supplier = Supplier.objects.create(company=company, code="SUP-1", name_en="Medent", currency_id="EGP")
    vat = TaxRate.objects.get(company=company, rate=14)
    service = Item.objects.create(company=company, sku="SRV-1", name_en="Installation", type="service", sales_price=D(1000))
    expenses = list(Account.objects.filter(company=company, type="expense", is_group=False, is_active=True)[:2])
    return {"today": today, "customer": customer, "supplier": supplier, "vat": vat, "service": service, "exp": expenses}


def _invoice_post_data(s, rows, subtotals):
    data = {"customer": s["customer"].pk, "terms": "net30", "date": s["today"].isoformat(), "due_date": "", "currency": "EGP",
            "rate": "1", "prices_include_tax": "False", "save": "", "subtotals": json.dumps(subtotals),
            "lines-TOTAL_FORMS": str(len(rows) + 1), "lines-INITIAL_FORMS": "0", "lines-MIN_NUM_FORMS": "0",
            "lines-MAX_NUM_FORMS": "1000"}
    for i, (desc, price, pos) in enumerate(rows):
        data.update({f"lines-{i}-item": s["service"].pk, f"lines-{i}-description": desc, f"lines-{i}-qty": "1",
                     f"lines-{i}-unit_price": price, f"lines-{i}-discount_pct": "0", f"lines-{i}-tax_rate": s["vat"].pk,
                     f"lines-{i}-position": str(pos)})
    blank = len(rows)  # an untouched blank row that only got a position: must not become a line
    data.update({f"lines-{blank}-qty": "1", f"lines-{blank}-unit_price": "0", f"lines-{blank}-discount_pct": "0",
                 f"lines-{blank}-position": "9"})
    return data


def test_line_order_and_subtotals(client, company, owner, base):
    client.force_login(owner)
    # Sent in this order on screen: B (pos 1), A (pos 2), subtotal (pos 3), C (pos 4)
    data = _invoice_post_data(base, [("A", "200", 2), ("B", "100", 1), ("C", "50", 4)], [{"pos": 3, "label": "Equipment"}])
    r = client.post(reverse("sales:invoice_new"), data)
    assert r.status_code == 302
    inv = Invoice.objects.get()
    assert [l.description for l in inv.lines_list] == ["B", "A", "C"]
    rows = inv.display_lines
    assert [("sub" if "subtotal" in x else x["line"].description) for x in rows] == ["B", "A", "sub", "C"]
    assert rows[2]["amount"] == D(300) and rows[2]["subtotal"] == "Equipment"
    assert inv.total == D("399.00")  # subtotals never change the totals
    detail = client.get(reverse("sales:invoice", args=[inv.pk])).content.decode()
    assert "Equipment" in detail
    form = client.get(reverse("sales:invoice_edit", args=[inv.pk])).content.decode()
    assert "data-subtotals-field" in form and "&quot;pos&quot;: 3" in form and "Add subtotal" in form
    # In Arabic a subtotal line reads المجموع الفرعي, not the document's "total before VAT"
    inv.subtotals = [{"pos": 3, "label": ""}]
    inv.save(update_fields=["subtotals"])
    owner.preferred_language = "ar"
    owner.save(update_fields=["preferred_language"])
    client.cookies["django_language"] = "ar"
    ar = client.get(reverse("sales:invoice_edit", args=[inv.pk])).content.decode()
    assert 'data-l-subtotal="المجموع الفرعي"' in ar
    assert "المجموع الفرعي" in client.get(reverse("sales:invoice", args=[inv.pk])).content.decode()


def test_draft_purchase_order_prints(client, company, owner, base):
    wh = Warehouse.objects.get(company=company, code="MAIN")
    po = PurchaseOrder.objects.create(company=company, supplier=base["supplier"], date=base["today"], currency_id="EGP",
                                      warehouse=wh, created_by=owner)
    PurchaseOrderLine.objects.create(document=po, item=base["service"], qty=D(2), unit_price=D(50))
    client.force_login(owner)
    detail = client.get(reverse("purchases:order", args=[po.pk])).content.decode()
    assert reverse("purchases:order_print", args=[po.pk]) in detail
    printed = client.get(reverse("purchases:order_print", args=[po.pk])).content.decode()
    assert "DRAFT" in printed


def test_expenses_list_and_reclassify(client, company, owner, base):
    old, new = base["exp"]
    bill = Bill.objects.create(company=company, supplier=base["supplier"], supplier_invoice_no="X1", date=base["today"],
                               due_date=base["today"], currency_id="EGP", created_by=owner)
    BillLine.objects.create(document=bill, account=old, description="Rent", qty=D(1), unit_price=D(1000))
    purchasing.post_bill(bill, owner)
    client.force_login(owner)
    page = client.get(reverse("purchases:expenses"))
    assert page.status_code == 200 and f'data-key="bill:{bill.pk}"' in page.content.decode()
    r = client.post(reverse("purchases:expense_category"), {"key": f"bill:{bill.pk}", "account": new.pk})
    assert r.json()["ok"] and r.json()["entry"]
    entry = JournalEntry.objects.get(source="reclass")
    lines = {l.account_id: (l.debit, l.credit) for l in entry.lines.all()}
    assert lines[new.pk] == (D(1000), D(0)) and lines[old.pk] == (D(0), D(1000))
    assert bill.lines.get().account_id == new.pk
    assert client.post(reverse("purchases:expense_category"), {"key": "bill:999999", "account": new.pk}).status_code == 400


def test_import_bills(client, company, owner, base):
    acc = base["exp"][0]
    wb = Workbook()
    ws = wb.active
    ws.append(["Supplier", "Supplier invoice no", "Date", "Due date", "Product SKU", "Account code", "Description", "Qty",
               "Rate", "VAT %"])
    ws.append(["SUP-1", "INV-9", "01/10/2026", "", "", acc.code, "Rent", 1, 1000, 14])
    ws.append(["SUP-1", "INV-9", "01/10/2026", "", "", acc.code, "Service charge", 1, 200, 14])
    ws.append(["NOPE", "INV-1", "bad", "", "", "", "", 0, "", 3])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    buf.name = "bills.xlsx"
    client.force_login(owner)
    assert client.get(reverse("purchases:import_bills"), {"template": "1"}).status_code == 200
    client.post(reverse("purchases:import_bills"), {"file": buf})
    preview = client.get(reverse("purchases:import_bills")).context["preview"]
    assert len(preview["bills"]) == 1 and len(preview["bills"][0]["lines"]) == 2 and len(preview["problems"]) == 1
    client.post(reverse("purchases:import_bills"), {"confirm": "1"})
    bill = Bill.objects.get(supplier_invoice_no="INV-9")
    assert bill.status == "draft" and bill.total == D("1368.00")


def test_filter_chips(client, company, owner, base):
    client.force_login(owner)
    html = client.get(reverse("sales:invoices"), {"dates": "365", "status": "draft"}).content.decode()
    assert "Last 12 months" in html and 'class="fchip"' in html and "Filter" in html
    assert "?status=draft" in html  # removing the date chip keeps the status


def test_delivery_method_filter(client, company, owner, base):
    from core.models import AuditLog, ShareLink

    docs = []
    for n in range(3):
        inv = Invoice.objects.create(company=company, customer=base["customer"], number=f"INV-T{n}", date=base["today"],
                                     due_date=base["today"], currency_id="EGP", created_by=owner)
        docs.append(inv)
    AuditLog.record(company, owner, "invoice.sent", docs[0], "INV-T0")
    ShareLink.for_object(docs[1], owner)
    client.force_login(owner)

    def numbers(method):
        page = client.get(reverse("sales:invoices"), {"delivery": method})
        return sorted(r["obj"].number for r in page.context["rows"])

    assert numbers("emailed") == ["INV-T0"]
    assert numbers("shared") == ["INV-T1"]
    assert numbers("unsent") == ["INV-T2"]
    html = client.get(reverse("sales:invoices"), {"delivery": "emailed"}).content.decode()
    assert "Delivery method" in html and "Emailed" in html


def test_contact_page_menus_and_inactive(client, company, owner, base):
    client.force_login(owner)
    url = reverse("contacts:supplier", args=[base["supplier"].pk])
    html = client.get(url).content.decode()
    for text in ("New transaction", "Import bills", "Item receipt", "hub-side", "Bill payment info", "Make inactive"):
        assert text in html, text
    client.post(reverse("contacts:supplier_active", args=[base["supplier"].pk]))
    base["supplier"].refresh_from_db()
    assert not base["supplier"].is_active
    cust = client.get(reverse("contacts:customer", args=[base["customer"].pk])).content.decode()
    assert 'data-tab="tasks"' in cust and 'data-tab="opportunities"' in cust and "Request feedback" in cust


def test_crm_flow(client, company, owner, base):
    client.force_login(owner)
    for kind in ("lead", "opportunity", "proposal", "contract", "appointment", "task", "conversation"):
        assert client.get(reverse("crm:list", args=[kind])).status_code == 200
        assert client.get(reverse("crm:new", args=[kind])).status_code == 200
    for name in ("crm:overview", "crm:board", "crm:calendar", "crm:reviews", "crm:review_request"):
        assert client.get(reverse(name)).status_code == 200
    client.post(reverse("crm:new", args=["lead"]), {"name": "Delta Clinic", "phone": "0100", "source": "referral",
                                                    "status": "new", "owner": owner.pk})
    lead = Lead.objects.get()
    client.post(reverse("crm:new", args=["task"]), {"title": "Call back", "lead": lead.pk, "assignee": owner.pk,
                                                    "due_date": base["today"].isoformat()})
    client.post(reverse("crm:lead_convert", args=[lead.pk]))
    lead.refresh_from_db()
    assert lead.status == "converted" and lead.customer and Task.objects.get().customer == lead.customer
    home = client.get(reverse("dashboard:home")).content.decode()
    assert "of your tasks are due today" in home
    opp = Opportunity.objects.create(company=company, title="Chairs", customer=base["customer"], value=D(50000),
                                     currency_id="EGP")
    assert client.post(reverse("crm:opportunity_stage", args=[opp.pk]), {"stage": "won"}).json() == {"ok": True}
    opp.refresh_from_db()
    assert opp.stage == "won" and opp.probability == 100 and opp.closed_at
    # proposal priced from an estimate, accepted online, turned into a sales order
    q = Quotation.objects.create(company=company, customer=base["customer"], date=base["today"], number="QT-1",
                                 currency_id="EGP", created_by=owner, status="sent")
    QuotationLine.objects.create(document=q, item=base["service"], qty=D(2), unit_price=D(1000), tax_rate=base["vat"])
    client.post(reverse("crm:new", args=["proposal"]), {"title": "Clinic fit-out", "customer": base["customer"].pk,
                                                        "quotation": q.pk, "date": base["today"].isoformat()})
    prop = Proposal.objects.get()
    assert prop.number.startswith("PRP-")
    link = client.post(reverse("crm:share", args=["proposal", prop.pk])).json()
    assert "wa.me/201001234567" in link["whatsapp"]
    public_url = link["url"].split("testserver")[-1]
    client.logout()
    page = client.get(public_url)
    assert page.status_code == 200 and "Clinic fit-out" in page.content.decode() and "2,000.00" in page.content.decode()
    client.post(public_url, {"name": "Dr Hany", "agree": "on"})
    prop.refresh_from_db()
    assert prop.status == "accepted" and prop.accepted_name == "Dr Hany"
    client.force_login(owner)
    r = client.post(reverse("crm:proposal_action", args=[prop.pk]), {"action": "order"})
    assert r.status_code == 302 and "/sales/orders/" in r["Location"]
    # contract accepted online
    client.post(reverse("crm:new", args=["contract"]), {"title": "Maintenance", "customer": base["customer"].pk,
                                                        "start_date": base["today"].isoformat(), "value": "12000",
                                                        "currency": "EGP", "renewal_reminder_days": "30", "status": "draft"})
    con = Contract.objects.get()
    curl = client.post(reverse("crm:share", args=["contract", con.pk])).json()["url"].split("testserver")[-1]
    client.post(curl, {"name": "Dr Hany", "agree": "on"})
    con.refresh_from_db()
    assert con.status == "active"
    # feedback request
    r = client.post(reverse("crm:review_request"), {"customer": base["customer"].pk})
    review = Review.objects.get()
    client.logout()
    client.post(reverse("crm:review_public", args=[review.token]), {"rating": "5", "comment": "Great service"})
    review.refresh_from_db()
    assert review.rating == 5 and review.submitted_at


def test_crm_needs_permission(client, company, make_user):
    clerk = make_user("store@scigate.test", "Storekeeper")
    client.force_login(clerk)
    assert client.get(reverse("crm:overview")).status_code == 403


@pytest.mark.parametrize("lang", ["en", "ar"])
def test_help_centre(client, company, owner, lang):
    client.force_login(owner)
    client.cookies["django_language"] = lang
    index = client.get(reverse("core:help"))
    assert index.status_code == 200 and len(index.context["sections"]) == 12
    for key in ("invoices", "action-bar", "returned-cheques", "lines", "proposals"):
        assert client.get(reverse("core:help_topic", args=[key])).status_code == 200
    assert client.get(reverse("core:help_topic", args=["nope"])).status_code == 404
    manual = client.get(reverse("core:manual")).content.decode()
    assert ("Add subtotal" in manual) if lang == "en" else ("مجموع فرعي" in manual)
    page = client.get(reverse("sales:invoices")).content.decode()
    assert reverse("core:help_topic", args=["invoices"]) in page


def test_role_sync_gives_new_modules(company):
    from users.defaults import sync_system_roles
    from users.models import Role

    role = Role.objects.get(company=company, name_en="Sales officer")
    role.permissions = [p for p in role.permissions if not p.startswith("crm.")]
    role.save()
    sync_system_roles(company)
    role.refresh_from_db()
    assert "crm.create" in role.permissions
