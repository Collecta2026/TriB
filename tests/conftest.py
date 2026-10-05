import datetime
from decimal import Decimal

import pytest

from core.services import bootstrap_company, seed_banks, seed_currencies
from users.models import Membership, Role, User

TODAY = datetime.date(2026, 10, 5)
PASSWORD = "Str0ng-test-pass!"


@pytest.fixture
def owner(db):
    return User.objects.create_user("owner@scigate.test", PASSWORD, full_name="Sara Owner")


@pytest.fixture
def company(owner):
    seed_currencies()
    seed_banks()
    return bootstrap_company(name_en="Scientific Gate", name_ar="البوابة العلمية", owner=owner)


@pytest.fixture
def make_user(company):
    def make(email, role_name, **membership):
        user = User.objects.create_user(email, PASSWORD, full_name=email.split("@")[0].title())
        m = Membership.objects.create(user=user, company=company, **membership)
        m.roles.add(Role.objects.get(company=company, name_en=role_name))
        return user
    return make


@pytest.fixture
def cash(company):
    return company.bank_accounts.get(kind="cash")


def acct(company, code):
    from ledger.models import Account
    return Account.objects.get(company=company, code=code)


def D(value):
    return Decimal(str(value))
