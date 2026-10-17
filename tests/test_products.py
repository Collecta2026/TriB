"""Products & services (QuickBooks layout): stock status and attention counts, sorting, edit mode, row and batch
actions, pictures, price rules, starting value, import from Excel and the product QuickReport."""
import io
import json
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from contacts.models import Customer
from core.docviews import picker_data
from inventory import pricing, services
from inventory.models import Category, Item, PriceRule, StockAdjustment, Warehouse
from ledger.services import account_balance, system_account
from sales import services as sales
from sales.models import Invoice, InvoiceLine

from .conftest import TODAY, D, acct

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


@pytest.fixture
def p(company):
    machines = Category.objects.create(company=company, name_en="Machines", name_ar="أجهزة", prefix="MCH")
    supplies = Category.objects.create(company=company, name_en="Supplies", name_ar="مستلزمات", prefix="SUP")
    wh = Warehouse.objects.get(company=company, code="MAIN")
    chair = Item.objects.create(company=company, sku="MCH-1", name_en="Dental chair", category=machines, type="inventory",
                                sales_price=D(1000), purchase_cost=D(600), reorder_level=D(5), description="Chair unit")
    gloves = Item.objects.create(company=company, sku="SUP-1", name_en="Gloves", category=supplies, type="inventory",
                                 sales_price=D(20), purchase_cost=D(0))
    autoclave = Item.objects.create(company=company, sku="MCH-2", name_en="Autoclave", category=machines,
                                    type="inventory", sales_price=D(500), purchase_cost=D(300))
    install = Item.objects.create(company=company, sku="SRV-1", name_en="Installation", type="service",
                                  sales_price=D(150), purchase_description="Engineer visit")
    services.receive(chair, wh, D(3), D(600), TODAY, "OPEN")          # 3 ≤ reorder level 5 → low
    services.receive(autoclave, wh, D(1), D(300), TODAY, "OPEN")
    services.issue(autoclave, wh, D(1), TODAY, "SOLD")                # → out of stock
    return {"chair": chair, "gloves": gloves, "autoclave": autoclave, "install": install, "wh": wh,
            "machines": machines, "supplies": supplies}


def _names(response):
    return [i.name_en for i in response.context["rows"]]


# ---------- list ----------
def test_stock_status_filters_and_attention_banner(client, owner, p):
    client.force_login(owner)
    r = client.get(reverse("inventory:items"))
    assert r.context["attention"] == {"nocost": 1, "out": 2, "low": 1}   # gloves: no cost and none on hand
    html = r.content.decode()
    assert "Some items need your attention" in html and "OUT" in html and "LOW" in html
    assert _names(client.get(reverse("inventory:items") + "?status=out")) == ["Autoclave", "Gloves"]
    assert _names(client.get(reverse("inventory:items") + "?status=low")) == ["Dental chair"]
    assert _names(client.get(reverse("inventory:items") + "?status=nocost")) == ["Gloves"]
    assert _names(client.get(reverse("inventory:items") + "?status=in")) == ["Dental chair"]
    assert _names(client.get(reverse("inventory:items") + "?type=service")) == ["Installation"]
    assert _names(client.get(reverse("inventory:items") + f"?category={p['machines'].pk}")) == ["Autoclave", "Dental chair"]
    assert _names(client.get(reverse("inventory:items") + "?q=chair unit")) == ["Dental chair"]  # sales description


def test_sorting(client, owner, p):
    client.force_login(owner)
    assert _names(client.get(reverse("inventory:items")))[0] == "Autoclave"                 # name ↑ by default
    assert _names(client.get(reverse("inventory:items") + "?sort=-price"))[0] == "Dental chair"
    assert _names(client.get(reverse("inventory:items") + "?sort=-qty"))[0] == "Dental chair"


def test_edit_mode_saves_prices_and_categories(client, owner, p):
    client.force_login(owner)
    assert 'name="price_' in client.get(reverse("inventory:items") + "?edit=1").content.decode()
    chair, gloves = p["chair"], p["gloves"]
    client.post(reverse("inventory:items_bulk_save"), {
        "ids": [chair.pk, gloves.pk], f"price_{chair.pk}": "1,100", f"cost_{chair.pk}": "650",
        f"reorder_{chair.pk}": "2", f"category_{chair.pk}": p["machines"].pk,
        f"price_{gloves.pk}": "-5", f"category_{gloves.pk}": p["machines"].pk, "next": "/inventory/items/"})
    chair.refresh_from_db()
    gloves.refresh_from_db()
    assert (chair.sales_price, chair.purchase_cost, chair.reorder_level) == (D(1100), D(650), D(2))
    assert gloves.sales_price == D(20) and gloves.category == p["supplies"]     # a bad number skips the whole row


def test_row_actions_duplicate_and_inactive(client, owner, p):
    client.force_login(owner)
    r = client.post(reverse("inventory:item_action", args=[p["chair"].pk]), {"action": "duplicate"})
    copy = Item.objects.get(name_en="Dental chair (copy)")
    assert r["Location"] == reverse("inventory:item_edit", args=[copy.pk])
    assert copy.sku.startswith("MCH-") and copy.sku != "MCH-1" and copy.on_hand() == 0
    client.post(reverse("inventory:item_action", args=[p["gloves"].pk]), {"action": "inactive"})
    p["gloves"].refresh_from_db()
    assert not p["gloves"].is_active
    assert "Gloves" not in _names(client.get(reverse("inventory:items")))
    assert "Gloves" in _names(client.get(reverse("inventory:items") + "?active=inactive"))


def test_batch_actions(client, owner, p):
    client.force_login(owner)
    ids = [p["gloves"].pk, p["install"].pk]
    client.post(reverse("inventory:items_batch"), {"ids": ids, "action": "category", "category": p["supplies"].pk})
    assert set(Item.objects.filter(pk__in=ids).values_list("category_id", flat=True)) == {p["supplies"].pk}
    r = client.post(reverse("inventory:items_batch"), {"ids": ids, "action": "adjust"})
    assert r["Location"] == f"{reverse('inventory:adjustment_new')}?items={p['gloves'].pk}"   # stock items only
    page = client.get(r["Location"]).content.decode()
    assert f'value="{p["gloves"].pk}" selected' in page
    r = client.post(reverse("inventory:items_batch"), {"ids": ids, "action": "labels"})
    assert r["Location"].startswith(reverse("inventory:labels")) and "copies=1" in r["Location"]
    client.post(reverse("inventory:items_batch"), {"ids": ids, "action": "inactive"})
    assert not Item.objects.filter(pk__in=ids, is_active=True).exists()


def test_picture_upload_and_check(client, owner, p):
    client.force_login(owner)
    item = p["install"]
    data = {"name_en": item.name_en, "name_ar": "", "sku": item.sku, "type": "service", "tracking": "none",
            "unit": "job", "sales_price": "150", "purchase_cost": "0", "reorder_level": "0", "is_active": "on"}
    bad = client.post(reverse("inventory:item_edit", args=[item.pk]),
                      {**data, "picture": SimpleUploadedFile("x.txt", b"hello", content_type="text/plain")})
    assert bad.status_code == 200 and "Choose a JPG" in bad.content.decode()
    client.post(reverse("inventory:item_edit", args=[item.pk]),
                {**data, "picture": SimpleUploadedFile("p.png", PNG, content_type="image/png")})
    item.refresh_from_db()
    assert item.has_image
    img = client.get(reverse("inventory:item_image", args=[item.pk]))
    assert img["Content-Type"] == "image/png" and img.content == PNG
    assert reverse("inventory:item_image", args=[item.pk]) in client.get(reverse("inventory:items")).content.decode()


# ---------- price rules ----------
def test_price_rules_most_specific_wins(company, p):
    clinic = Customer.objects.create(company=company, code="C1", name_en="Clinic", currency_id="EGP")
    other = Customer.objects.create(company=company, code="C2", name_en="Other", currency_id="EGP")
    everyone = PriceRule.objects.create(company=company, name="Autumn 10% off", direction="down", method="percent",
                                        amount=D(10))
    vip = PriceRule.objects.create(company=company, name="Clinic machines +50", direction="up", method="fixed",
                                   amount=D(50), rounding="whole")
    vip.customers.add(clinic)
    vip.categories.add(p["machines"])
    ended = PriceRule.objects.create(company=company, name="Old promo", direction="down", method="percent", amount=D(90),
                                     end_date=TODAY - timedelta(days=1))
    ended.items.add(p["chair"])
    assert pricing.price_for(company, p["chair"], clinic, TODAY) == (D(1050), "Clinic machines +50")
    assert pricing.price_for(company, p["chair"], other, TODAY) == (D(900), "Autumn 10% off")
    assert pricing.price_for(company, p["install"], clinic, TODAY) == (D(135), "Autumn 10% off")
    assert pricing.price_for(company, p["chair"], other, TODAY - timedelta(days=5))[1] == "Old promo"
    rule = {"amount": "7.5", "method": "percent", "dir": "down", "rounding": "end99"}
    assert pricing.adjust(D(100), rule) == D("92.99")                                       # 92.50 → 92.99
    data = json.loads(picker_data(company, "sales", "customer"))
    assert data["rules"][0]["name"] == "Clinic machines +50"                                # most specific first
    assert data["items"][str(p["chair"].pk)]["desc"] == "Chair unit"
    assert json.loads(picker_data(company, "purchase"))["items"][str(p["install"].pk)]["desc"] == "Engineer visit"


def test_price_rules_page(client, owner, company, p):
    client.force_login(owner)
    r = client.post(reverse("inventory:price_rules"), {
        "name": "Machines 5% up", "direction": "up", "method": "percent", "amount": "5", "rounding": "none",
        "categories": [p["machines"].pk], "is_active": "on"})
    assert r.status_code == 302
    rule = PriceRule.objects.get(company=company)
    assert list(rule.categories.all()) == [p["machines"]]
    assert "1,050.00" in client.get(reverse("inventory:price_rules")).content.decode()        # example: 1,000 → 1,050


# ---------- starting value ----------
def test_starting_value_posts_opening_stock(client, owner, company, p):
    client.force_login(owner)
    gloves = p["gloves"]
    r = client.post(reverse("inventory:starting_value"), {
        "item": gloves.pk, "warehouse": p["wh"].pk, "as_of": TODAY.isoformat(), "qty": "40", "unit_cost": "12.5"})
    assert r.status_code == 302
    gloves.refresh_from_db()
    assert gloves.on_hand() == 40 and gloves.purchase_cost == D("12.5")
    adj = StockAdjustment.objects.get(reason="opening")
    assert adj.status == "posted" and adj.journal_entry_id
    assert account_balance(system_account(company, "opening_equity")) == D(500)               # 40 × 12.50, credit
    again = client.post(reverse("inventory:starting_value"), {
        "item": gloves.pk, "warehouse": p["wh"].pk, "as_of": TODAY.isoformat(), "qty": "1", "unit_cost": "1"})
    assert again.status_code == 200 and StockAdjustment.objects.filter(reason="opening").count() == 1


# ---------- import ----------
def test_import_products_from_excel(client, owner, company, p):
    from openpyxl import Workbook

    from inventory import import_items as imp

    wb = Workbook()
    ws = wb.active
    ws.append(imp.COLUMNS)
    ws.append(["MCH-1", "Dental chair A6", "", "Stock", "Machines", "pcs", "New description", "", 1200, "", "", ""])
    ws.append(["", "Pallet wrap", "", "Stock", "Packaging", "roll", "", "Stretch film", 12.5, 7.8, 20, ""])
    ws.append(["", "Delivery", "", "Service", "", "", "", "", "abc", "", "", ""])
    buf = io.BytesIO()
    wb.save(buf)
    client.force_login(owner)
    client.post(reverse("inventory:import_items"),
                {"file": SimpleUploadedFile("products.xlsx", buf.getvalue(),
                                            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    preview = client.get(reverse("inventory:import_items")).content.decode()
    assert "Row 4: Sales price is not a number." in preview and "Pallet wrap" in preview
    client.post(reverse("inventory:import_items"), {"confirm": "1"})
    chair = Item.objects.get(sku="MCH-1")
    assert chair.name_en == "Dental chair A6" and chair.sales_price == D(1200) and chair.description == "New description"
    wrap = Item.objects.get(name_en="Pallet wrap")
    assert wrap.category.name_en == "Packaging" and wrap.sku.startswith(wrap.category.prefix)
    assert (wrap.sales_price, wrap.purchase_cost, wrap.purchase_description) == (D("12.5"), D("7.8"), "Stretch film")
    assert not Item.objects.filter(name_en="Delivery").exists()


# ---------- QuickReport ----------
def test_product_quickreport(client, owner, company, p):
    customer = Customer.objects.create(company=company, code="C1", name_en="Clinic", currency_id="EGP")
    inv = Invoice.objects.create(company=company, customer=customer, date=TODAY, due_date=TODAY, currency_id="EGP",
                                 warehouse=p["wh"], created_by=owner)
    InvoiceLine.objects.create(document=inv, item=p["chair"], qty=D(2), unit_price=D(1000))
    sales.post_invoice(inv, owner, allow_over_limit=True)
    client.force_login(owner)
    r = client.get(reverse("inventory:item_report", args=[p["chair"].pk]))
    assert r.context["qty_sold"] == D(2) and r.context["sales"] == D(2000)
    assert inv.number in r.content.decode()
