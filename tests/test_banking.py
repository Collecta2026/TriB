import datetime

import pytest

from banking.models import Bank, Cheque
from banking.services import bounce_cheque, clear_cheque, create_bank_account, deposit_for_collection
from ledger.services import PostingError, account_balance, foreign_balance

from .conftest import TODAY, D, acct


def test_bank_account_gets_its_own_chart_account(company, owner):
    cib = Bank.objects.get(company=None, country="EG", short_name="CIB")
    egp = create_bank_account(company, kind="bank", currency="EGP", name_en="CIB current", bank=cib, user=owner)
    usd = create_bank_account(company, kind="bank", currency="USD", name_en="CIB USD", bank=cib, user=owner)
    assert (egp.gl_account.code, usd.gl_account.code) == ("1121", "1122")
    assert egp.gl_account.parent.code == "1120"
    assert egp.gl_account.currency_id is None
    assert usd.gl_account.currency_id == "USD"


def test_uae_banks_are_in_the_list(company):
    assert Bank.objects.filter(company=None, country="AE", short_name="FAB").exists()
    assert Bank.objects.filter(company=None, country="EG", short_name="FAB").exists()


def _received_cheque(company, owner, amount=D(125000)):
    return Cheque.objects.create(
        company=company, direction="in", number="10048832", party_name="Cairo Dental Center", amount=amount,
        currency_id="EGP", issue_date=TODAY, due_date=TODAY + datetime.timedelta(days=2), status="in_safe",
        counter_account=acct(company, "1130"), created_by=owner,
    )


def test_received_cheque_deposit_and_clear(company, owner):
    bank = create_bank_account(company, kind="bank", currency="EGP", name_en="NBE", user=owner)
    cheque = _received_cheque(company, owner)
    # Simulate the receipt voucher that put the cheque in the safe.
    from ledger.services import Line, post_journal
    post_journal(company, TODAY, [Line(acct(company, "1140"), debit=D(125000)), Line(acct(company, "1130"), credit=D(125000))])

    deposit_for_collection(cheque, bank, TODAY, owner)
    assert account_balance(acct(company, "1140")) == 0
    assert account_balance(acct(company, "1145")) == D(125000)
    clear_cheque(cheque, TODAY, owner)
    assert account_balance(acct(company, "1145")) == 0
    assert account_balance(bank.gl_account) == D(125000)
    assert Cheque.objects.get(pk=cheque.pk).status == "cleared"
    with pytest.raises(PostingError):
        bounce_cheque(cheque, TODAY, owner)


def test_bounced_cheque_goes_back_to_customer(company, owner):
    from ledger.services import Line, post_journal
    cheque = _received_cheque(company, owner, D(46000))
    post_journal(company, TODAY, [Line(acct(company, "1140"), debit=D(46000)), Line(acct(company, "1130"), credit=D(46000))])
    bounce_cheque(cheque, TODAY, owner)
    assert account_balance(acct(company, "1140")) == 0
    assert account_balance(acct(company, "1130")) == 0  # the customer owes the money again


def test_foreign_balance_tracks_original_currency(company, owner):
    from ledger.services import Line, post_journal
    usd = create_bank_account(company, kind="bank", currency="USD", name_en="CIB USD", user=owner)
    rate = D("48.65")
    post_journal(company, TODAY, [
        Line(usd.gl_account, debit=D("486500.00"), currency="USD", amount_fc=D(10000), rate=rate),
        Line(acct(company, "3100"), credit=D("486500.00"), currency="USD", amount_fc=D(10000), rate=rate),
    ])
    assert foreign_balance(usd.gl_account, "USD") == D(10000)
    assert account_balance(usd.gl_account) == D("486500.00")
