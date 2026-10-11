"""Bank accounts, the post-dated cheque lifecycle, transfers between own accounts and bank deposits."""
from decimal import Decimal

from django.db import transaction
from django.utils.translation import gettext as _

from core.models import AuditLog, ExchangeRate, NumberSeries
from ledger.models import Account
from ledger.services import Line, PostingError, next_child_code, post_journal, q2, system_account

from .models import BankAccount, BankDeposit, BankTransfer, Cheque, ChequeEvent


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


def _event(cheque, action, date, user, entry=None, bank_account=None, statement_line=None, reference="", note=""):
    return ChequeEvent.objects.create(company=cheque.company, cheque=cheque, action=action, date=date,
                                      amount=cheque.amount, bank_account=bank_account, journal_entry=entry,
                                      statement_line=statement_line, reference=reference[:80], note=note[:300],
                                      created_by=user)


def _owed_by(cheque):
    """The account a returned cheque is owed on again: the customer's receivable, or the voucher's account."""
    return cheque.counter_account or system_account(cheque.company, "receivable")


@transaction.atomic
def deposit_for_collection(cheque, bank_account, date, user=None, reference=""):
    if cheque.direction != "in" or cheque.status != "in_safe":
        raise PostingError(_("Only received cheques in the safe can be deposited."))
    memo = _("Cheque %(n)s deposited for collection") % {"n": cheque.number}
    entry = _post(cheque, date, system_account(cheque.company, "cheques_collection"),
                  system_account(cheque.company, "notes_receivable"), memo, user)
    cheque.status, cheque.bank_account = "under_collection", bank_account
    cheque.save(update_fields=["status", "bank_account"])
    _event(cheque, "deposited", date, user, entry, bank_account, reference=reference)
    AuditLog.record(cheque.company, user, "cheque.deposited", cheque, memo)


@transaction.atomic
def clear_cheque(cheque, date, user=None, bank_account=None, statement_line=None):
    """The bank paid the cheque. Issued: Dr Cheques payable / Cr Bank. Received: Dr Bank / Cr Cheques under
    collection (or notes receivable when it was never deposited). Returns the journal entry."""
    company = cheque.company
    bank_account = bank_account or cheque.bank_account
    if bank_account is None:
        raise PostingError(_("Choose the bank account the cheque cleared through."))
    memo = _("Cheque %(n)s cleared") % {"n": cheque.number}
    if cheque.direction == "in":
        if cheque.status not in ("in_safe", "under_collection"):
            raise PostingError(_("This cheque cannot be cleared from its current status."))
        source = "cheques_collection" if cheque.status == "under_collection" else "notes_receivable"
        entry = _post(cheque, date, bank_account.gl_account, system_account(company, source), memo, user)
    else:
        if cheque.status != "issued":
            raise PostingError(_("This cheque cannot be cleared from its current status."))
        entry = _post(cheque, date, system_account(company, "notes_payable"), bank_account.gl_account, memo, user)
    cheque.status, cheque.bank_account, cheque.cleared_on = "cleared", bank_account, date
    cheque.save(update_fields=["status", "bank_account", "cleared_on"])
    _event(cheque, "cleared", date, user, entry, bank_account, statement_line,
           reference=statement_line.reference if statement_line else "")
    AuditLog.record(company, user, "cheque.cleared", cheque, memo)
    return entry


@transaction.atomic
def bounce_cheque(cheque, date, user=None, reason="", reference=""):
    """The bank returned a received cheque unpaid: the amount is owed again by the customer."""
    company = cheque.company
    if cheque.direction != "in" or cheque.status not in ("in_safe", "under_collection"):
        raise PostingError(_("Only received cheques that have not cleared can bounce."))
    memo = _("Cheque %(n)s bounced") % {"n": cheque.number}
    source = "cheques_collection" if cheque.status == "under_collection" else "notes_receivable"
    entry = _post(cheque, date, _owed_by(cheque), system_account(company, source), memo, user)
    cheque.status, cheque.bounced_on, cheque.bounce_reason = "bounced", date, (reason or "")[:200]
    cheque.bounce_count += 1
    cheque.save(update_fields=["status", "bounced_on", "bounce_reason", "bounce_count"])
    _event(cheque, "bounced", date, user, entry, cheque.bank_account, reference=reference, note=reason)
    AuditLog.record(company, user, "cheque.bounced", cheque, f"{memo} {reason}".strip())
    return entry


@transaction.atomic
def resubmit_cheque(cheque, bank_account, date, user=None, reference=""):
    """After talking to the customer, the returned cheque goes back to the bank for collection."""
    if cheque.direction != "in" or cheque.status != "bounced":
        raise PostingError(_("Only returned cheques can be resubmitted."))
    if bank_account is None:
        raise PostingError(_("Choose the bank account the cheque is deposited into."))
    memo = _("Cheque %(n)s resubmitted for collection") % {"n": cheque.number}
    entry = _post(cheque, date, system_account(cheque.company, "cheques_collection"), _owed_by(cheque), memo, user)
    cheque.status, cheque.bank_account = "under_collection", bank_account
    cheque.save(update_fields=["status", "bank_account"])
    _event(cheque, "resubmitted", date, user, entry, bank_account, reference=reference)
    AuditLog.record(cheque.company, user, "cheque.resubmitted", cheque, memo)
    return entry


@transaction.atomic
def settle_returned_cheque(cheque, bank_account, date, user=None, reference=""):
    """The customer paid a returned cheque in cash or by transfer instead: Dr cash box or bank / Cr customer."""
    if cheque.direction != "in" or cheque.status != "bounced":
        raise PostingError(_("Only returned cheques can be settled."))
    if bank_account is None:
        raise PostingError(_("Choose the cash box or bank account that received the money."))
    if bank_account.currency_id != cheque.currency_id:
        raise PostingError(_("Choose a cash box or bank account in %(c)s.") % {"c": cheque.currency_id})
    memo = _("Returned cheque %(n)s settled") % {"n": cheque.number}
    entry = _post(cheque, date, bank_account.gl_account, _owed_by(cheque), memo, user)
    cheque.status = "settled"
    cheque.save(update_fields=["status"])
    _event(cheque, "settled", date, user, entry, bank_account, reference=reference)
    AuditLog.record(cheque.company, user, "cheque.settled", cheque, memo)
    return entry


@transaction.atomic
def cancel_issued_cheque(cheque, date, user=None):
    """An issued cheque was cancelled before it was cashed: the amount is owed to the payee again."""
    company = cheque.company
    if cheque.direction != "out" or cheque.status != "issued":
        raise PostingError(_("Only issued cheques that have not cleared can be cancelled."))
    memo = _("Cheque %(n)s cancelled") % {"n": cheque.number}
    back_to = cheque.counter_account or system_account(company, "payable")
    entry = _post(cheque, date, system_account(company, "notes_payable"), back_to, memo, user)
    cheque.status = "cancelled"
    cheque.save(update_fields=["status"])
    _event(cheque, "cancelled", date, user, entry)
    AuditLog.record(company, user, "cheque.cancelled", cheque, memo)


def returned_cheques_balance(customer, as_of=None):
    """What a customer owes on cheques the bank returned and that are not yet resubmitted or settled."""
    from decimal import Decimal
    events = ChequeEvent.objects.filter(cheque__customer=customer, action__in=("bounced", "resubmitted", "settled"))
    if as_of:
        events = events.filter(date__lte=as_of)
    total = Decimal("0")
    for e in events:
        total += e.amount if e.action == "bounced" else -e.amount
    return total

# ---------- Transfers between own accounts ----------
def _base_rate(company, currency_id, date):
    if currency_id == company.base_currency_id:
        return Decimal("1")
    rate = ExchangeRate.rate_for(company, currency_id, date)
    if rate is None:
        raise PostingError(_("Save an exchange rate for %(c)s first.") % {"c": currency_id})
    return rate


@transaction.atomic
def post_transfer(transfer, user):
    """Dr receiving account / Cr sending account, each in its own currency; any rate difference to FX gain or loss."""
    company = transfer.company
    src, dst = transfer.from_account, transfer.to_account
    if src.pk == dst.pk:
        raise PostingError(_("Choose two different accounts."))
    if transfer.amount <= 0:
        raise PostingError(_("The amount must be greater than zero."))
    if src.currency_id == dst.currency_id:
        transfer.amount_to = transfer.amount
    elif not transfer.amount_to or transfer.amount_to <= 0:
        raise PostingError(_("Enter the amount received in %(c)s.") % {"c": dst.currency_id})
    rate_from = _base_rate(company, src.currency_id, transfer.date)
    rate_to = _base_rate(company, dst.currency_id, transfer.date)
    base_from, base_to = q2(transfer.amount * rate_from), q2(transfer.amount_to * rate_to)
    transfer.number = transfer.number or NumberSeries.next(company, "TR", transfer.date)
    memo = transfer.memo or _("Transfer %(a)s → %(b)s") % {"a": src.name_en, "b": dst.name_en}
    lines = [Line(dst.gl_account, debit=base_to, description=memo, currency=dst.currency_id, amount_fc=transfer.amount_to, rate=rate_to),
             Line(src.gl_account, credit=base_from, description=memo, currency=src.currency_id, amount_fc=transfer.amount, rate=rate_from)]
    diff = base_from - base_to
    if diff > 0:
        lines.append(Line(system_account(company, "fx_loss"), debit=diff, description=_("Exchange difference")))
    elif diff < 0:
        lines.append(Line(system_account(company, "fx_gain"), credit=-diff, description=_("Exchange difference")))
    transfer.journal_entry = post_journal(company, transfer.date, lines, memo=memo, source="bank",
                                          source_ref=transfer.number, user=user)
    transfer.save()
    AuditLog.record(company, user, "bank.transfer", transfer, f"{transfer.number} {transfer.amount}")
    return transfer


@transaction.atomic
def void_transfer(transfer, user, date=None):
    from django.utils import timezone
    from ledger.services import reverse_journal
    if transfer.status != "posted":
        raise PostingError(_("This transfer is already void."))
    reverse_journal(transfer.journal_entry, date or timezone.localdate(), user, _("Void %(n)s") % {"n": transfer.number})
    transfer.status = "void"
    transfer.save(update_fields=["status"])
    AuditLog.record(transfer.company, user, "bank.transfer_void", transfer, transfer.number)


# ---------- Bank deposits ----------
@transaction.atomic
def post_deposit(deposit, cheques, user):
    """Pay received cheques (deposited for collection) and cash from a cash box into the bank on one slip."""
    company = deposit.company
    bank = deposit.bank_account
    if bank.kind != "bank":
        raise PostingError(_("Deposits go into a bank account."))
    if not cheques and not deposit.cash_amount:
        raise PostingError(_("Tick at least one cheque or enter a cash amount."))
    if deposit.cash_amount and (deposit.cash_from is None or deposit.cash_from.currency_id != bank.currency_id):
        raise PostingError(_("Choose the cash box the cash comes from, in %(c)s.") % {"c": bank.currency_id})
    deposit.number = deposit.number or NumberSeries.next(company, "DEP", deposit.date)
    deposit.save()
    total = Decimal("0")
    for cheque in cheques:
        if cheque.currency_id != bank.currency_id:
            raise PostingError(_("Cheque %(n)s is in %(c)s; deposit it into an account in that currency.") % {
                "n": cheque.number, "c": cheque.currency_id})
        deposit_for_collection(cheque, bank, deposit.date, user, reference=deposit.number)
        total += cheque.amount
    deposit.cheques.set(cheques)
    deposit.cheque_total = total
    if deposit.cash_amount:
        rate = _base_rate(company, bank.currency_id, deposit.date)
        base = q2(deposit.cash_amount * rate)
        memo = _("Cash deposited %(n)s") % {"n": deposit.number}
        deposit.journal_entry = post_journal(company, deposit.date, [
            Line(bank.gl_account, debit=base, description=memo, currency=bank.currency_id, amount_fc=deposit.cash_amount, rate=rate),
            Line(deposit.cash_from.gl_account, credit=base, description=memo, currency=bank.currency_id,
                 amount_fc=deposit.cash_amount, rate=rate),
        ], memo=memo, source="bank", source_ref=deposit.number, user=user)
    deposit.save()
    AuditLog.record(company, user, "bank.deposit", deposit, f"{deposit.number} {deposit.total}")
    return deposit
