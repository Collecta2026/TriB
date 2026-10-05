"""Voucher workflow: draft → submitted → approved → posted (or rejected / cancelled)."""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from approvals import services as approvals
from banking.models import Cheque
from core.models import AuditLog, NumberSeries
from ledger.services import Line, PostingError, post_journal, q2, system_account


class VoucherError(Exception):
    pass


def validate(voucher):
    lines = list(voucher.lines.select_related("account"))
    if not lines:
        raise VoucherError(_("Add at least one line."))
    for line in lines:
        if line.account.is_group or not line.account.is_active or line.account.company_id != voucher.company_id:
            raise VoucherError(_("Account %(code)s cannot take postings.") % {"code": line.account.code})
    if voucher.rate <= 0:
        raise VoucherError(_("The exchange rate must be greater than zero."))
    if voucher.currency_id == voucher.company.base_currency_id and voucher.rate != 1:
        raise VoucherError(_("Base-currency vouchers use an exchange rate of 1."))
    if voucher.kind == "journal":
        debit = sum((l.debit for l in lines), Decimal("0"))
        credit = sum((l.credit for l in lines), Decimal("0"))
        if any(l.debit and l.credit for l in lines) or any(l.debit < 0 or l.credit < 0 for l in lines):
            raise VoucherError(_("Each line must be either a debit or a credit, and not negative."))
        if debit <= 0 or debit != credit:
            raise VoucherError(_("Total debits and total credits must be equal."))
        return
    if any(l.amount <= 0 for l in lines):
        raise VoucherError(_("Every line needs an amount greater than zero."))
    if not voucher.party_name:
        raise VoucherError(_("Enter who the money was received from or paid to."))
    if voucher.method in ("cash", "bank") and voucher.bank_account is None:
        raise VoucherError(_("Choose the cash box or bank account."))
    if voucher.method == "cheque":
        if not voucher.cheque_number or not voucher.cheque_due_date:
            raise VoucherError(_("Enter the cheque number and due date."))
        if voucher.kind == "payment" and voucher.bank_account is None:
            raise VoucherError(_("Choose the bank account the cheque is drawn on."))
    if voucher.bank_account and voucher.bank_account.currency_id != voucher.currency_id:
        raise VoucherError(_("The voucher currency must match the cash box or bank account currency."))


@transaction.atomic
def submit(voucher, user):
    if not voucher.editable:
        raise VoucherError(_("Only draft or rejected vouchers can be submitted."))
    validate(voucher)
    if not voucher.number:
        voucher.number = NumberSeries.next(voucher.company, voucher.prefix, voucher.date)
    voucher.status = "submitted"
    voucher.save(update_fields=["number", "status"])
    AuditLog.record(voucher.company, user, "voucher.submitted", voucher, voucher.number)
    request = approvals.start(voucher, user)
    if request is None:
        voucher.status = "approved"
        voucher.save(update_fields=["status"])
        if voucher.company.auto_post_on_approval:
            post_voucher(voucher, user)
    return voucher


def _base(amount, rate):
    return q2(amount * rate)


def build_lines(voucher):
    company, cur, rate = voucher.company, voucher.currency_id, voucher.rate
    memo = voucher.description or voucher.party_name
    lines = []
    if voucher.kind == "journal":
        items = list(voucher.lines.select_related("account", "cost_center"))
        for l in items:
            fc = l.debit or l.credit
            lines.append(Line(account=l.account, debit=_base(l.debit, rate), credit=_base(l.credit, rate),
                              description=l.description or memo, cost_center=l.cost_center, currency=cur,
                              amount_fc=fc, rate=rate))
        # Absorb rounding from currency conversion on the largest line so the entry balances.
        diff = sum(x.debit for x in lines) - sum(x.credit for x in lines)
        if diff:
            biggest = max(lines, key=lambda x: x.debit or x.credit)
            if biggest.debit:
                biggest.debit -= diff
            else:
                biggest.credit += diff
        return lines

    counter = []
    for l in voucher.lines.select_related("account", "cost_center"):
        counter.append(Line(account=l.account, description=l.description or memo, cost_center=l.cost_center,
                            currency=cur, amount_fc=l.amount, rate=rate,
                            **({"credit": _base(l.amount, rate)} if voucher.kind == "receipt" else {"debit": _base(l.amount, rate)})))
    total_base = sum((x.credit or x.debit for x in counter), Decimal("0"))
    total_fc = voucher.total
    if voucher.method == "cheque":
        money_account = system_account(company, "notes_receivable" if voucher.kind == "receipt" else "notes_payable")
    else:
        money_account = voucher.bank_account.gl_account
    side = {"debit": total_base} if voucher.kind == "receipt" else {"credit": total_base}
    money = Line(account=money_account, description=memo, currency=cur, amount_fc=total_fc, rate=rate, **side)
    return [money] + counter if voucher.kind == "receipt" else counter + [money]


@transaction.atomic
def post_voucher(voucher, user):
    if voucher.status != "approved":
        raise VoucherError(_("Only approved vouchers can be posted."))
    validate(voucher)
    try:
        entry = post_journal(
            voucher.company, voucher.date, build_lines(voucher), memo=f"{voucher.number} {voucher.description or voucher.party_name}",
            source=voucher.kind, source_ref=voucher.number, user=user, branch=voucher.branch,
        )
    except PostingError as exc:
        raise VoucherError(str(exc)) from exc
    if voucher.method == "cheque":
        first_line = voucher.lines.select_related("account").first()
        voucher.cheque = Cheque.objects.create(
            company=voucher.company, direction="in" if voucher.kind == "receipt" else "out",
            number=voucher.cheque_number, drawee_bank=voucher.cheque_bank, party_name=voucher.party_name,
            amount=voucher.total, currency_id=voucher.currency_id, rate=voucher.rate, issue_date=voucher.date,
            due_date=voucher.cheque_due_date, status="in_safe" if voucher.kind == "receipt" else "issued",
            bank_account=voucher.bank_account if voucher.kind == "payment" else None,
            counter_account=first_line.account, source_ref=voucher.number, created_by=user,
        )
    voucher.journal_entry = entry
    voucher.status = "posted"
    voucher.posted_at = timezone.now()
    voucher.save(update_fields=["journal_entry", "status", "posted_at", "cheque"])
    AuditLog.record(voucher.company, user, "voucher.posted", voucher, f"{voucher.number} → {entry.number}")
    return entry


@transaction.atomic
def cancel(voucher, user):
    if not voucher.editable:
        raise VoucherError(_("Only draft or rejected vouchers can be cancelled."))
    voucher.status = "cancelled"
    voucher.save(update_fields=["status"])
    AuditLog.record(voucher.company, user, "voucher.cancelled", voucher, voucher.number or str(voucher.pk))
