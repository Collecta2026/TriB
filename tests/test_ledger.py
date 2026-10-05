import datetime

import pytest

from ledger.models import JournalEntry
from ledger.services import Line, PostingError, account_balance, post_journal, reverse_journal
from reports.services import balance_sheet, trial_balance

from .conftest import TODAY, D, acct


def test_new_company_has_chart_cash_box_and_roles(company):
    assert company.accounts.filter(code="1140", subtype="notes_receivable").exists()
    cash = company.bank_accounts.get(kind="cash")
    assert cash.gl_account.parent.code == "1110"
    assert cash.gl_account.code == "1111"
    assert set(company.roles.values_list("name_en", flat=True)) >= {"Administrator", "Finance manager", "Accountant", "Cashier"}


def test_balanced_entry_posts_and_numbers_sequentially(company, owner):
    rent, cash = acct(company, "5300"), company.bank_accounts.get(kind="cash").gl_account
    e1 = post_journal(company, TODAY, [Line(rent, debit=D(1000)), Line(cash, credit=D(1000))], user=owner)
    e2 = post_journal(company, TODAY, [Line(rent, debit=D(5)), Line(cash, credit=D(5))], user=owner)
    assert e1.number == "JE-2026-00001" and e2.number == "JE-2026-00002"
    assert account_balance(rent) == D(1005)
    assert account_balance(cash) == D(-1005)


def test_unbalanced_entry_is_refused(company):
    rent, cash = acct(company, "5300"), company.bank_accounts.get(kind="cash").gl_account
    with pytest.raises(PostingError):
        post_journal(company, TODAY, [Line(rent, debit=D(100)), Line(cash, credit=D(99.99))])
    assert not JournalEntry.objects.exists()


def test_header_accounts_and_locked_periods_are_refused(company):
    cash = company.bank_accounts.get(kind="cash").gl_account
    with pytest.raises(PostingError):
        post_journal(company, TODAY, [Line(acct(company, "5"), debit=D(1)), Line(cash, credit=D(1))])
    company.lock_date = datetime.date(2026, 9, 30)
    company.save()
    with pytest.raises(PostingError):
        post_journal(company, datetime.date(2026, 9, 30), [Line(acct(company, "5300"), debit=D(1)), Line(cash, credit=D(1))])


def test_reversal_cancels_entry_and_cannot_repeat(company, owner):
    rent, cash = acct(company, "5300"), company.bank_accounts.get(kind="cash").gl_account
    entry = post_journal(company, TODAY, [Line(rent, debit=D(250)), Line(cash, credit=D(250))], user=owner)
    reverse_journal(entry, TODAY, owner)
    assert account_balance(rent) == 0
    with pytest.raises(PostingError):
        reverse_journal(entry, TODAY, owner)


def test_trial_balance_and_balance_sheet_balance(company, owner):
    cash = company.bank_accounts.get(kind="cash").gl_account
    post_journal(company, TODAY, [Line(cash, debit=D(50000)), Line(acct(company, "3100"), credit=D(50000))])
    post_journal(company, TODAY, [Line(acct(company, "5300"), debit=D(7000)), Line(cash, credit=D(7000))])
    post_journal(company, TODAY, [Line(cash, debit=D(12500.5)), Line(acct(company, "4100"), credit=D(12500.5))])
    rows, t = trial_balance(company, datetime.date(2026, 1, 1), TODAY)
    assert t["pd"] == t["pc"] and t["cd"] == t["cc"]
    bs = balance_sheet(company, TODAY)
    assert bs["check"] == 0
    assert bs["earnings"] == D(5500.5)
