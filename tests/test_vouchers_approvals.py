from decimal import Decimal

import pytest

from approvals import services as approvals
from approvals.models import ApprovalAction
from banking.models import Cheque
from banking.services import create_bank_account
from core.models import ExchangeRate
from ledger.services import account_balance
from vouchers.models import Voucher, VoucherLine
from vouchers.services import VoucherError, submit

from .conftest import TODAY, D, acct


def make_voucher(company, user, kind, lines, **fields):
    defaults = {"date": TODAY, "currency_id": company.base_currency_id, "party_name": "Medent Italia", "method": "cash"}
    defaults.update(fields)
    if kind == "journal":
        defaults.pop("party_name")
        defaults.pop("method")
    v = Voucher.objects.create(company=company, kind=kind, created_by=user, **defaults)
    for line in lines:
        VoucherLine.objects.create(voucher=v, **line)
    return v


def test_receipt_without_rule_posts_immediately(company, owner, cash):
    v = make_voucher(company, owner, "receipt", [{"account": acct(company, "4100"), "amount": D(1250.5)}], bank_account=cash)
    submit(v, owner)
    v.refresh_from_db()
    assert v.status == "posted" and v.number == "RV-2026-00001"
    assert account_balance(cash.gl_account) == D(1250.5)
    assert account_balance(acct(company, "4100")) == D(1250.5)


def test_payment_needs_finance_manager_and_creator_cannot_approve(company, owner, cash, make_user):
    clerk = make_user("clerk@scigate.test", "Cashier")
    fm = make_user("fm@scigate.test", "Finance manager")
    v = make_voucher(company, clerk, "payment", [{"account": acct(company, "5300"), "amount": D(20000)}], bank_account=cash)
    submit(v, clerk)
    v.refresh_from_db()
    assert v.status == "submitted"
    req = v.current_request
    assert approvals.check_authority(req, clerk) is not None  # no approve permission
    assert approvals.pending_for(fm, company) == [req]
    approvals.decide(req, fm, "approve", "OK")
    v.refresh_from_db()
    assert v.status == "posted"
    assert account_balance(acct(company, "5300")) == D(20000)


def test_owner_cannot_approve_own_document_when_sod_is_on(company, owner, cash):
    v = make_voucher(company, owner, "payment", [{"account": acct(company, "5300"), "amount": D(100)}], bank_account=cash)
    submit(v, owner)
    with pytest.raises(approvals.ApprovalError):
        approvals.decide(v.current_request, owner, "approve")
    company.enforce_sod = False
    company.save()
    approvals.decide(v.current_request, owner, "approve")
    v.refresh_from_db()
    assert v.status == "posted"


def test_large_payment_needs_two_levels_and_limits_apply(company, owner, cash, make_user):
    clerk = make_user("clerk@scigate.test", "Cashier")
    fm = make_user("fm@scigate.test", "Finance manager")
    v = make_voucher(company, clerk, "payment", [{"account": acct(company, "5400"), "amount": D(300000)}], bank_account=cash)
    submit(v, clerk)
    req = v.current_request
    assert req.total_steps == 2
    approvals.decide(req, fm, "approve")
    req.refresh_from_db()
    assert req.current_order == 2 and req.status == "pending"
    with pytest.raises(approvals.ApprovalError):  # finance manager may not also approve level 2
        approvals.decide(req, fm, "approve")
    approvals.decide(req, owner, "approve")  # owner holds the administrator role
    v.refresh_from_db()
    assert v.status == "posted"

    big = make_voucher(company, clerk, "payment", [{"account": acct(company, "5400"), "amount": D(2000000)}], bank_account=cash)
    submit(big, clerk)
    assert "limit" in approvals.check_authority(big.current_request, fm)


def test_rejection_returns_voucher_for_editing(company, cash, make_user):
    clerk = make_user("clerk@scigate.test", "Cashier")
    fm = make_user("fm@scigate.test", "Finance manager")
    v = make_voucher(company, clerk, "payment", [{"account": acct(company, "5300"), "amount": D(500)}], bank_account=cash)
    submit(v, clerk)
    approvals.decide(v.current_request, fm, "reject", "Wrong account")
    v.refresh_from_db()
    assert v.status == "rejected" and v.editable
    submit(v, clerk)
    v.refresh_from_db()
    assert v.status == "submitted" and v.approval_requests.count() == 2


def test_signature_detects_tampering(company, cash, make_user):
    clerk = make_user("clerk@scigate.test", "Cashier")
    fm = make_user("fm@scigate.test", "Finance manager")
    v = make_voucher(company, clerk, "payment", [{"account": acct(company, "5300"), "amount": D(900)}], bank_account=cash)
    submit(v, clerk)
    approvals.decide(v.current_request, fm, "approve")
    action = ApprovalAction.objects.get()
    assert approvals.verify(action)
    VoucherLine.objects.filter(voucher=v).update(amount=D(9000))
    action = ApprovalAction.objects.get()
    assert not approvals.verify(action)


def test_cheque_receipt_goes_to_safe(company, owner):
    v = make_voucher(company, owner, "receipt", [{"account": acct(company, "1130"), "amount": D(75000)}], method="cheque",
                     cheque_number="30077145", cheque_bank="Banque Misr", cheque_due_date=TODAY)
    submit(v, owner)
    v.refresh_from_db()
    assert v.status == "posted"
    cheque = Cheque.objects.get()
    assert cheque.status == "in_safe" and cheque.direction == "in" and v.cheque == cheque
    assert account_balance(acct(company, "1140")) == D(75000)


def test_foreign_currency_payment_converts_at_rate(company, owner, make_user):
    usd = create_bank_account(company, kind="bank", currency="USD", name_en="CIB USD", user=owner)
    ExchangeRate.objects.create(company=company, currency_id="USD", date=TODAY, rate=D("48.65"))
    clerk = make_user("clerk@scigate.test", "Cashier")
    fm = make_user("fm@scigate.test", "Finance manager")
    v = make_voucher(company, clerk, "payment", [{"account": acct(company, "5400"), "amount": D(1000)}],
                     currency_id="USD", rate=D("48.65"), method="bank", bank_account=usd)
    submit(v, clerk)
    approvals.decide(v.current_request, fm, "approve")
    assert account_balance(acct(company, "5400")) == D("48650.00")
    from ledger.services import foreign_balance
    assert foreign_balance(usd.gl_account, "USD") == D(-1000)


def test_unbalanced_journal_voucher_cannot_be_submitted(company, owner):
    v = make_voucher(company, owner, "journal", [
        {"account": acct(company, "5300"), "debit": D(100)},
        {"account": acct(company, "2150"), "credit": D(90)},
    ])
    with pytest.raises(VoucherError):
        submit(v, owner)
