"""Bank accounts and the post-dated cheque lifecycle."""
from django.db import transaction
from django.utils.translation import gettext as _

from core.models import AuditLog, ExchangeRate
from ledger.models import Account
from ledger.services import Line, PostingError, next_child_code, post_journal, q2, system_account

from .models import BankAccount, Cheque


@transaction.atomic
def create_bank_account(company, *, kind, currency, name_en, name_ar="", bank=None, account_number="", iban="",
                        branch=None, user=None):
    """Create a bank account or cash box and its own account in the chart, under Banks or Cash on hand."""
    parent_subtype = "bank" if kind == "bank" else "cash"
    parent = Account.objects.filter(company=company, subtype=parent_subtype, is_group=True).order_by("code").first()
    if parent is None:
        raise PostingError(_("The chart of accounts has no header account for banks or cash."))
    currency_code = getattr(currency, "code", currency)
    gl = Account.objects.create(
        company=company, code=next_child_code(parent), parent=parent, type="asset", subtype=parent_subtype,
        name_en=name_en, name_ar=name_ar or name_en, is_group=False,
        currency_id=None if currency_code == company.base_currency_id else currency_code,
    )
    account = BankAccount.objects.create(
        company=company, kind=kind, bank=bank, branch=branch, account_number=account_number, iban=iban,
        currency_id=currency_code, gl_account=gl, name_en=name_en, name_ar=name_ar or name_en,
    )
    AuditLog.record(company, user, "bank_account.created", account, f"{gl.code} {name_en}")
    return account


def _rate(cheque, date):
    rate = ExchangeRate.rate_for(cheque.company, cheque.currency_id, date)
    return rate if rate is not None else cheque.rate


def _post(cheque, date, debit_account, credit_account, memo, user):
    rate = _rate(cheque, date)
    base = q2(cheque.amount * rate)
    lines = [
        Line(account=debit_account, debit=base, currency=cheque.currency_id, amount_fc=cheque.amount, rate=rate,
             description=memo),
        Line(account=credit_account, credit=base, currency=cheque.currency_id, amount_fc=cheque.amount, rate=rate,
             description=memo),
    ]
    return post_journal(cheque.company, date, lines, memo=memo, source="cheque", source_ref=f"CHQ {cheque.number}",
                        user=user)


@transaction.atomic
def deposit_for_collection(cheque, bank_account, date, user=None):
    if cheque.direction != "in" or cheque.status != "in_safe":
        raise PostingError(_("Only received cheques in the safe can be deposited."))
    memo = _("Cheque %(n)s deposited for collection") % {"n": cheque.number}
    _post(cheque, date, system_account(cheque.company, "cheques_collection"),
          system_account(cheque.company, "notes_receivable"), memo, user)
    cheque.status, cheque.bank_account = "under_collection", bank_account
    cheque.save(update_fields=["status", "bank_account"])
    AuditLog.record(cheque.company, user, "cheque.deposited", cheque, memo)


@transaction.atomic
def clear_cheque(cheque, date, user=None, bank_account=None):
    company = cheque.company
    bank_account = bank_account or cheque.bank_account
    if bank_account is None:
        raise PostingError(_("Choose the bank account the cheque cleared through."))
    memo = _("Cheque %(n)s cleared") % {"n": cheque.number}
    if cheque.direction == "in":
        if cheque.status not in ("in_safe", "under_collection"):
            raise PostingError(_("This cheque cannot be cleared from its current status."))
        source = "cheques_collection" if cheque.status == "under_collection" else "notes_receivable"
        _post(cheque, date, bank_account.gl_account, system_account(company, source), memo, user)
    else:
        if cheque.status != "issued":
            raise PostingError(_("This cheque cannot be cleared from its current status."))
        _post(cheque, date, system_account(company, "notes_payable"), bank_account.gl_account, memo, user)
    cheque.status, cheque.bank_account = "cleared", bank_account
    cheque.save(update_fields=["status", "bank_account"])
    AuditLog.record(company, user, "cheque.cleared", cheque, memo)


@transaction.atomic
def bounce_cheque(cheque, date, user=None):
    """A received cheque came back unpaid: the amount is owed again by the customer."""
    company = cheque.company
    if cheque.direction != "in" or cheque.status not in ("in_safe", "under_collection"):
        raise PostingError(_("Only received cheques that have not cleared can bounce."))
    memo = _("Cheque %(n)s bounced") % {"n": cheque.number}
    source = "cheques_collection" if cheque.status == "under_collection" else "notes_receivable"
    back_to = cheque.counter_account or system_account(company, "receivable")
    _post(cheque, date, back_to, system_account(company, source), memo, user)
    cheque.status = "bounced"
    cheque.save(update_fields=["status"])
    AuditLog.record(company, user, "cheque.bounced", cheque, memo)


@transaction.atomic
def cancel_issued_cheque(cheque, date, user=None):
    """An issued cheque was cancelled before it was cashed: the amount is owed to the payee again."""
    company = cheque.company
    if cheque.direction != "out" or cheque.status != "issued":
        raise PostingError(_("Only issued cheques that have not cleared can be cancelled."))
    memo = _("Cheque %(n)s cancelled") % {"n": cheque.number}
    back_to = cheque.counter_account or system_account(company, "payable")
    _post(cheque, date, system_account(company, "notes_payable"), back_to, memo, user)
    cheque.status = "cancelled"
    cheque.save(update_fields=["status"])
    AuditLog.record(company, user, "cheque.cancelled", cheque, memo)
