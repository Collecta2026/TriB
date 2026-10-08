"""Release 2 screens render in both languages, and the key forms work end to end."""
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from contacts.models import Supplier
from inventory import services as stock
from inventory.models import Category, Item, StockCount, Warehouse
from purchases.models import GoodsReceipt

from .conftest import TODAY, D

PAGES = [
    "contacts:customers", "contacts:customer_new", "contacts:suppliers", "contacts:supplier_new",
    "sales:invoices", "sales:invoice_new", "sales:orders", "sales:order_new", "sales:quotes", "sales:quote_new",
    "sales:payments", "sales:payment_new", "sales:statements", "sales:confirmations",
    "purchases:orders", "purchases:order_new", "purchases:bills", "purchases:bill_new", "purchases:receipts",
    "purchases:receipt_new", "purchases:payments", "purchases:payment_new", "purchases:expenses",
    "purchases:statements", "purchases:not_received",
    "inventory:overview", "inventory:items", "inventory:item_new", "inventory:categories", "inventory:warehouses",
    "inventory:stock", "inventory:expiry", "inventory:transfers", "inventory:transfer_new", "inventory:adjustments",
    "inventory:adjustment_new", "inventory:counts", "inventory:labels",
    "reports:ar_aging", "reports:ap_aging", "reports:vat_return", "reports:sales_by_item",
    "assets:list", "assets:new", "assets:categories", "assets:depreciation", "assets:counts", "assets:labels",
    "banking:transactions", "banking:transactions_import", "banking:rules", "banking:reconcile",
    "ledger:tax_rates", "projects:list", "projects:new", "core:bookmarks", "core:customise", "core:receipts",
    "core:recurring", "core:apps",
]


@pytest.fixture
def wh(company):
    return Warehouse.objects.get(company=company, code="MAIN")


@pytest.fixture
def composite(company):
    cat = Category.objects.create(company=company, name_en="Supplies", prefix="SUP")
    return Item.objects.create(company=company, sku=stock.next_sku(company, cat), name_en="Composite A2", category=cat,
                               tracking="batch", sales_price=D(400), purchase_cost=D(250))


@pytest.mark.parametrize("lang", ["en", "ar"])
def test_release2_pages_render(client, company, owner, composite, wh, lang):
    stock.receive(composite, wh, 5, D(250), TODAY, "R1", batch_no="B1", expiry_date=TODAY + timedelta(days=20))
    client.force_login(owner)
    client.cookies["django_language"] = lang
    for name in PAGES:
        assert client.get(reverse(name)).status_code == 200, name
    assert client.get(reverse("inventory:item", args=[composite.pk])).status_code == 200
    page = client.get(reverse("inventory:expiry")).content.decode()
    assert "B1" in page and composite.sku in page
    assert client.get(reverse("inventory:labels") + f"?item={composite.pk}&copies=2").status_code == 200


def _grn_post(supplier, wh, item, **line):
    data = {"supplier": supplier.pk, "date": TODAY.isoformat(), "warehouse": wh.pk, "reference": "DN-1", "notes": "",
            "lines-TOTAL_FORMS": "1", "lines-INITIAL_FORMS": "0", "lines-MIN_NUM_FORMS": "0",
            "lines-MAX_NUM_FORMS": "1000", "lines-0-item": item.pk, "lines-0-description": "", "lines-0-qty": "10",
            "lines-0-unit_cost": "250", "lines-0-serials": "", "post": "1"}
    data.update({f"lines-0-{k}": v for k, v in line.items()})
    return data


def test_goods_receipt_needs_and_records_expiry(client, company, owner, composite, wh):
    supplier = Supplier.objects.create(company=company, code="SUP-1", name_en="Alpha Dental", currency_id="EGP")
    client.force_login(owner)
    response = client.post(reverse("purchases:receipt_new"), _grn_post(supplier, wh, composite, batch_no="LOT-1"))
    assert response.status_code == 200 and "Enter the expiry date." in response.content.decode()
    assert not GoodsReceipt.objects.exists()
    expiry = TODAY + timedelta(days=365)
    response = client.post(reverse("purchases:receipt_new"),
                           _grn_post(supplier, wh, composite, batch_no="LOT-1", expiry_date=expiry.isoformat()))
    assert response.status_code == 302
    grn = GoodsReceipt.objects.get()
    assert grn.status == "posted"
    layer = composite.layers.get()
    assert (layer.batch_no, layer.expiry_date, layer.qty_remaining) == ("LOT-1", expiry, 10)
    assert composite.moves.get().expiry_date == expiry


def test_stock_take_scanning(client, company, owner, composite, wh):
    stock.receive(composite, wh, 5, D(250), TODAY, "R1", batch_no="B1", expiry_date=TODAY + timedelta(days=200))
    client.force_login(owner)
    client.post(reverse("inventory:counts"), {"warehouse": wh.pk, "date": TODAY.isoformat()})
    count = StockCount.objects.get()
    for _ in range(3):
        client.post(reverse("inventory:count", args=[count.pk]), {"code": composite.sku, "qty": "2"})
    line = count.lines.get(item=composite)
    assert line.counted_qty == 6 and line.difference == 1
    client.post(reverse("inventory:count_post", args=[count.pk]))
    assert composite.on_hand(wh) == 6
    assert composite.layers.filter(qty_in=1).get().batch_no == "B1"


def test_asset_register_depreciation_and_count(client, company, owner):
    from assets.models import Asset, AssetCategory, AssetCount
    client.force_login(owner)
    client.post(reverse("assets:categories"), {
        "name_en": "Office equipment", "name_ar": "", "useful_life_months": "36",
        "asset_account": company.accounts.get(subtype="fixed_assets").pk,
        "depreciation_account": company.accounts.get(subtype="accum_depreciation").pk,
        "expense_account": company.accounts.get(subtype="depreciation").pk})
    cat = AssetCategory.objects.get()
    response = client.post(reverse("assets:new"), {
        "name_en": "Laptop", "category": cat.pk, "purchase_date": "2026-08-10", "in_service_date": "2026-08-10",
        "cost": "36000", "salvage_value": "0", "opening_depreciation": "0", "status": "active"})
    assert response.status_code == 302, response.content.decode()[:2000]
    asset = Asset.objects.get()
    assert asset.number == "FA-00001" and asset.useful_life_months == 36
    page = client.get(reverse("assets:depreciation") + "?month=2026-09").content.decode()
    assert "1,000.00" in page
    client.post(reverse("assets:depreciation"), {"month": "2026-08"})
    client.post(reverse("assets:depreciation"), {"month": "2026-09"})
    asset.refresh_from_db()
    assert asset.accumulated == D(2000)
    assert client.get(reverse("assets:detail", args=[asset.pk])).status_code == 200
    client.post(reverse("assets:counts"), {"date": TODAY.isoformat()})
    count = AssetCount.objects.get()
    client.post(reverse("assets:count", args=[count.pk]), {"code": "fa-00001"})
    assert count.lines.get().found
    assert client.get(reverse("assets:labels") + f"?asset={asset.pk}").status_code == 200


def test_menu_bookmarks_and_statement_import(client, company, owner, cash):
    from banking.models import StatementLine
    from core.models import Bookmark
    client.force_login(owner)
    html = client.get(reverse("dashboard:home")).content.decode()
    assert reverse("sales:invoices") in html and reverse("purchases:bills") in html  # pinned apps' submenus
    assert Bookmark.objects.filter(user=owner).count() == 9  # QuickBooks' starter bookmarks
    client.post(reverse("core:bookmark_add"), {"url": "//evil.example/x", "title": "x"})
    assert not Bookmark.objects.filter(url__contains="evil").exists()
    client.post(reverse("core:bookmark_add"), {"url": reverse("inventory:expiry"), "title": "Expiry"})
    assert Bookmark.objects.filter(user=owner, url=reverse("inventory:expiry")).exists()
    client.post(reverse("core:customise"), {"pinned": ["inventory", "payroll"]})
    html = client.get(reverse("dashboard:home")).content.decode()
    assert reverse("payroll:runs") in html
    csv_file = SimpleUploadedFile("statement.csv", b"Date,Details,Debit,Credit\n01/10/2026,Bank charges,25.00,\n"
                                                  b"02/10/2026,Transfer in,,1000.00\n")
    client.post(reverse("banking:transactions_import"), {"bank_account": cash.pk, "file": csv_file})
    client.post(reverse("banking:transactions_map"), {"date": "0", "description": "1", "debit": "2", "credit": "3",
                                                      "header": "1"})
    assert sorted(StatementLine.objects.values_list("amount", flat=True)) == [D("-25.00"), D("1000.00")]
    assert client.get(reverse("banking:transactions") + f"?account={cash.pk}").status_code == 200


def test_demo_data_builds_and_dashboard_shows_it(client, company, owner):
    from banking.services import create_bank_account
    from core.management.commands import _demo_r2
    cib = create_bank_account(company, kind="bank", currency="EGP", name_en="CIB", user=owner)
    from ledger.services import Line, post_journal
    post_journal(company, TODAY.replace(month=1, day=1), [Line(cib.gl_account, debit=D(5000000)),
                                                           Line(company.accounts.get(code="3100"), credit=D(5000000))],
                 memo="Opening", source="opening", user=owner)
    _demo_r2.build(company, owner, cib)
    client.force_login(owner)
    html = client.get(reverse("dashboard:home")).content.decode()
    for text in ("Machines", "Supplies", "Nile Smile Clinics", "SO-"):
        assert text in html, text
    rows = stock.batches_on_hand(company)
    assert {"expired", "soon"} <= {r["state"] for r in rows}


def test_attachment_type_comes_from_extension(client, company, owner, composite):
    client.force_login(owner)
    upload = SimpleUploadedFile("photo.png", b"<svg onload=alert(1)>", content_type="image/svg+xml")
    client.post(reverse("core:attachment_upload"), {"target": "inventory.item", "target_id": composite.pk,
                                                    "files": upload, "next": "/"})
    from core.models import Attachment
    a = Attachment.objects.get()
    assert a.content_type == "image/png"
    response = client.get(reverse("core:attachment", args=[a.pk]))
    assert response["Content-Type"] == "image/png" and response["X-Content-Type-Options"] == "nosniff"
