from django.db import transaction

from .models import AuditLog, Branch, Company, Currency
from .reference import CURRENCIES


def seed_currencies():
    for code, en, ar, decimals, symbol in CURRENCIES:
        Currency.objects.update_or_create(
            code=code, defaults={"name_en": en, "name_ar": ar, "decimals": decimals, "symbol_ar": symbol}
        )


def seed_banks():
    from banking.models import Bank
    from banking.reference import BANKS

    for country, short, en, ar in BANKS:
        Bank.objects.update_or_create(
            company=None, country=country, short_name=short, defaults={"name_en": en, "name_ar": ar}
        )


@transaction.atomic
def bootstrap_company(*, name_en, name_ar, base_currency="EGP", owner, extra_currencies=("USD",)):
    """Create a ready-to-use company: branch, currencies, roles, chart of accounts, cash box, approval rules."""
    from approvals.defaults import install_default_rules
    from banking.services import create_bank_account
    from ledger.coa import install_chart
    from users.defaults import install_default_roles
    from users.models import Membership

    if not Currency.objects.exists():
        seed_currencies()
    company = Company.objects.create(name_en=name_en, name_ar=name_ar or name_en, base_currency_id=base_currency,
                                     addons=dict(Company.DEFAULT_ADDONS))
    company.currencies.set([base_currency, *[c for c in extra_currencies if c != base_currency]])
    Branch.objects.create(company=company, code="HQ", name_en="Head office", name_ar="المقر الرئيسي")
    roles = install_default_roles(company)
    install_chart(company)
    create_bank_account(company, kind="cash", currency=base_currency, name_en="Main cash box",
                        name_ar="الخزينة الرئيسية", user=owner)
    install_default_rules(company, roles)
    from inventory.models import Warehouse
    Warehouse.objects.create(company=company, code="MAIN", name_en="Main warehouse", name_ar="المخزن الرئيسي")
    membership = Membership.objects.create(user=owner, company=company, is_owner=True)
    membership.roles.add(roles["admin"])
    AuditLog.record(company, owner, "company.created", company, name_en)
    return company
