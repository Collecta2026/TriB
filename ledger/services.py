"""Posting to the general ledger. Every journal entry in TriB goes through post_journal()."""
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.utils.translation import gettext as _

from core.models import AuditLog, NumberSeries

from .models import Account, CostCenter, JournalEntry, JournalLine

CENT = Decimal("0.01")
ZERO = Decimal("0")


def q2(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


class PostingError(Exception):
    pass


@dataclass
class Line:
    account: Account
    debit: Decimal = ZERO
    credit: Decimal = ZERO
    description: str = ""
    cost_center: CostCenter = None
    project: object = None
    currency: object = None  # Currency or code; defaults to base currency
    amount_fc: Decimal = None  # original-currency amount; defaults to debit/credit
    rate: Decimal = field(default_factory=lambda: Decimal("1"))


def system_account(company, subtype):
    """The posting account that plays a system role, e.g. 'notes_receivable'."""
    account = Account.objects.filter(company=company, subtype=subtype, is_group=False, is_active=True).order_by("code").first()
    if account is None:
        raise PostingError(_("No active account is set up for: %(role)s") % {"role": subtype})
    return account


@transaction.atomic
def post_journal(company, date, lines, memo="", source="manual", source_ref="", user=None, branch=None, reversal_of=None):
    if len(lines) < 2:
        raise PostingError(_("A journal entry needs at least two lines."))
    if company.lock_date and date <= company.lock_date:
        raise PostingError(_("The period up to %(date)s is locked.") % {"date": company.lock_date.isoformat()})

    total_debit = total_credit = ZERO
    clean = []
    for line in lines:
        account = line.account
        if account.company_id != company.id:
            raise PostingError(_("Account %(code)s belongs to another company.") % {"code": account.code})
        if account.is_group or not account.is_active:
            raise PostingError(_("Account %(code)s cannot take postings.") % {"code": account.code})
        debit, credit = q2(line.debit or 0), q2(line.credit or 0)
        if debit < 0 or credit < 0 or (debit and credit):
            raise PostingError(_("Each line must be either a debit or a credit, and not negative."))
        if not debit and not credit:
            continue
        currency = getattr(line.currency, "code", line.currency) or company.base_currency_id
        amount_fc = q2(line.amount_fc if line.amount_fc is not None else (debit or credit))
        total_debit += debit
        total_credit += credit
        clean.append(JournalLine(
            account=account, cost_center=line.cost_center, project=line.project, description=(line.description or "")[:300],
            debit=debit, credit=credit, currency_id=currency, amount_fc=amount_fc, rate=line.rate or Decimal("1"),
        ))

    if len(clean) < 2:
        raise PostingError(_("A journal entry needs at least two lines."))
    if total_debit != total_credit:
        raise PostingError(_("Debits (%(d)s) and credits (%(c)s) must be equal.") % {"d": total_debit, "c": total_credit})

    entry = JournalEntry.objects.create(
        company=company, branch=branch, date=date, memo=memo[:300], source=source, source_ref=source_ref,
        number=NumberSeries.next(company, "JE", date), created_by=user, reversal_of=reversal_of,
    )
    for line in clean:
        line.entry = entry
    JournalLine.objects.bulk_create(clean)
    AuditLog.record(company, user, "journal.posted", entry, f"{entry.number} {memo}", {"total": str(total_debit)})
    return entry


@transaction.atomic
def reverse_journal(entry, date, user=None, memo=""):
    if hasattr(entry, "reversed_by"):
        raise PostingError(_("This entry has already been reversed."))
    lines = [
        Line(account=l.account, debit=l.credit, credit=l.debit, description=l.description, cost_center=l.cost_center,
             project=l.project, currency=l.currency_id, amount_fc=l.amount_fc, rate=l.rate)
        for l in entry.lines.select_related("account")
    ]
    return post_journal(
        entry.company, date, lines, memo=memo or _("Reversal of %(n)s") % {"n": entry.number},
        source="reversal", source_ref=entry.number, user=user, branch=entry.branch, reversal_of=entry,
    )


def balances(company, date_from=None, date_to=None, accounts=None):
    """{account_id: (debit, credit)} for posted lines in the date range."""
    qs = JournalLine.objects.filter(entry__company=company)
    if date_from:
        qs = qs.filter(entry__date__gte=date_from)
    if date_to:
        qs = qs.filter(entry__date__lte=date_to)
    if accounts is not None:
        qs = qs.filter(account__in=accounts)
    rows = qs.values("account_id").annotate(d=Sum("debit"), c=Sum("credit"))
    return {r["account_id"]: (r["d"] or ZERO, r["c"] or ZERO) for r in rows}


def account_balance(account, date_to=None):
    """Signed balance in the account's natural direction (debit-nature accounts positive when in debit)."""
    d, c = balances(account.company, date_to=date_to, accounts=[account]).get(account.id, (ZERO, ZERO))
    return d - c if account.debit_nature else c - d


def foreign_balance(account, currency_code, date_to=None):
    """Balance of a foreign-currency account in its own currency."""
    qs = JournalLine.objects.filter(account=account, currency_id=currency_code)
    if date_to:
        qs = qs.filter(entry__date__lte=date_to)
    agg = qs.aggregate(
        d=Sum("amount_fc", filter=Q(debit__gt=0)), c=Sum("amount_fc", filter=Q(credit__gt=0))
    )
    return (agg["d"] or ZERO) - (agg["c"] or ZERO)


def next_child_code(parent):
    existing = set(parent.children.values_list("code", flat=True))
    stem = parent.code[:-1] if parent.code.endswith("0") else parent.code
    for digit in range(1, 10):
        candidate = f"{stem}{digit}"
        if candidate not in existing and not Account.objects.filter(company=parent.company, code=candidate).exists():
            return candidate
    n = 1
    while True:
        candidate = f"{parent.code}{n:02d}"
        if not Account.objects.filter(company=parent.company, code=candidate).exists():
            return candidate
        n += 1
