"""Every screen renders, in English and Arabic, and the authority matrix is enforced."""
import pytest
from django.urls import reverse

from core.models import Company
from users.models import User
from vouchers.models import Voucher

from .conftest import PASSWORD, TODAY, D, acct

PAGES = [
    "dashboard:home", "core:apps", "core:settings", "core:audit", "users:users", "users:user_new", "users:role_new",
    "users:password", "ledger:accounts", "ledger:account_new", "ledger:cost_centers", "ledger:journals",
    "banking:accounts", "banking:account_new", "banking:banks", "banking:cheques", "vouchers:list", "approvals:inbox",
    "approvals:rules", "reports:index", "reports:trial_balance", "reports:statement", "reports:profit_loss",
    "reports:balance_sheet",
]


def test_first_run_setup_creates_company_and_signs_in(client, db):
    assert client.get("/").status_code == 302
    response = client.post(reverse("core:setup"), {
        "company_name_en": "Scientific Gate", "company_name_ar": "البوابة العلمية", "base_currency": "EGP",
        "full_name": "Zak Saleh", "email": "zak@scigate.test", "password1": PASSWORD, "password2": PASSWORD,
    })
    assert response.status_code == 302
    assert Company.objects.count() == 1
    assert client.get(reverse("dashboard:home")).status_code == 200
    # Setup is closed once a company exists.
    assert client.get(reverse("core:setup")).status_code == 302


@pytest.mark.parametrize("lang", ["en", "ar"])
def test_all_pages_render_for_owner(client, company, owner, lang):
    client.force_login(owner)
    client.cookies["django_language"] = lang
    for name in PAGES:
        response = client.get(reverse(name))
        assert response.status_code == 200, name
    for kind in ("receipt", "payment", "journal"):
        assert client.get(reverse("vouchers:new", args=[kind])).status_code == 200


def test_arabic_layout_is_right_to_left(client, company, owner):
    client.force_login(owner)
    client.cookies["django_language"] = "ar"
    html = client.get(reverse("dashboard:home")).content.decode()
    assert 'dir="rtl"' in html
    assert "نظرة سريعة على الأعمال" in html  # "Business at a glance"
    assert "سند قبض" in html  # "Receipt voucher"


def test_cashier_cannot_edit_roles_or_settings(client, company, make_user):
    cashier = make_user("cash@scigate.test", "Cashier")
    client.force_login(cashier)
    assert client.get(reverse("users:role_new")).status_code == 403
    assert client.get(reverse("core:settings")).status_code == 403
    assert client.get(reverse("vouchers:new", args=["payment"])).status_code == 200


def test_create_and_submit_voucher_through_the_form(client, company, owner, cash):
    company.enforce_sod = False
    company.save()
    client.force_login(owner)
    data = {
        "date": TODAY.isoformat(), "party_name": "Smile Clinic", "method": "cash", "bank_account": cash.pk,
        "currency": "EGP", "rate": "1", "description": "Clinic payment",
        "lines-TOTAL_FORMS": "1", "lines-INITIAL_FORMS": "0", "lines-MIN_NUM_FORMS": "0", "lines-MAX_NUM_FORMS": "1000",
        "lines-0-account": acct(company, "4100").pk, "lines-0-amount": "3500", "lines-0-description": "Chair service",
        "submit": "1",
    }
    response = client.post(reverse("vouchers:new", args=["receipt"]), data)
    assert response.status_code == 302
    voucher = Voucher.objects.get()
    assert voucher.status == "posted" and voucher.total == D(3500)
    page = client.get(reverse("vouchers:print", args=[voucher.pk])).content.decode()
    assert "سند قبض" in page and "Three thousand five hundred Egyptian pounds only" in page


def test_users_of_other_companies_are_invisible(client, company, owner):
    from core.services import bootstrap_company
    other_owner = User.objects.create_user("other@else.test", PASSWORD)
    other = bootstrap_company(name_en="Other Co", name_ar="", owner=other_owner)
    other_account = other.accounts.get(code="5300")
    client.force_login(owner)
    assert client.get(reverse("ledger:account_edit", args=[other_account.pk])).status_code == 404
