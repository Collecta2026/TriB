"""Bank statement import, matching, categorising and reconciliation.

Egyptian banks don't offer QuickBooks-style live feeds, so statements are imported as CSV or Excel
(any bank: you tell TriB which column is which).
"""
import csv
import io
import re
import uuid
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from core.models import AuditLog
from ledger.models import JournalLine
from ledger.services import Line, PostingError, post_journal

from .models import BankRule, Reconciliation, StatementLine

ZERO = Decimal("0")
DATE_FORMATS = ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%m/%d/%Y", "%d/%m/%y", "%d-%b-%Y", "%d %b %Y"]


class FeedError(Exception):
    pass


def read_table(uploaded):
    """Rows (lists of strings) from a CSV or XLSX upload."""
    name = (uploaded.name or "").lower()
    if name.endswith(".xlsx"):
        import openpyxl

        wb = openpyxl.load_workbook(uploaded, data_only=True, read_only=True)
        ws = wb.worksheets[0]
        return [["" if c is None else (c.strftime("%Y-%m-%d") if hasattr(c, "strftime") else str(c)) for c in row]
                for row in ws.iter_rows(values_only=True)]
    raw = uploaded.read()
    for encoding in ("utf-8-sig", "cp1256", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    dialect = csv.Sniffer().sniff(text[:2048], delimiters=",;\t") if text.strip() else csv.excel
    return [row for row in csv.reader(io.StringIO(text), dialect)]


def parse_date(value):
    value = (value or "").strip()
    candidates = [value, value.split(" ")[0], value[:10], value[:11]]
    for fmt in DATE_FORMATS:
        for candidate in candidates:
            try:
                return datetime.strptime(candidate, fmt).date()
            except ValueError:
                continue
    try:
        return datetime.fromisoformat(value[:10]).date()
    except ValueError:
        return None


def parse_amount(value):
    value = (value or "").replace(",", "").replace(" ", "").strip()
    if not value:
        return ZERO
    negative = value.startswith("(") and value.endswith(")")
    value = value.strip("()")
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    return -number if negative else number


@transaction.atomic
def import_statement(company, bank_account, rows, mapping, user, skip_header=True):
    """mapping: column indexes for date, description, reference and either amount or debit/credit."""
    batch = uuid.uuid4().hex[:12]
    created, skipped = [], 0
    for row in rows[1:] if skip_header else rows:
        cell = lambda key: row[mapping[key]] if mapping.get(key) is not None and mapping[key] < len(row) else ""  # noqa: E731
        when = parse_date(cell("date"))
        if not when:
            skipped += 1
            continue
        if mapping.get("amount") is not None:
            amount = parse_amount(cell("amount"))
        else:
            money_in, money_out = parse_amount(cell("credit")), parse_amount(cell("debit"))
            amount = None if money_in is None or money_out is None else (money_in or ZERO) - abs(money_out or ZERO)
        if amount is None or amount == 0:
            skipped += 1
            continue
        description = cell("description").strip()[:300] or "-"
        reference = cell("reference").strip()[:80]
        duplicate = StatementLine.objects.filter(bank_account=bank_account, date=when, amount=amount,
                                                 description=description).exists()
        if duplicate:
            skipped += 1
            continue
        created.append(StatementLine.objects.create(company=company, bank_account=bank_account, date=when,
                                                    description=description, reference=reference, amount=amount,
                                                    import_batch=batch))
    auto_clear_cheques(created, user)  # before the rules, so a cheque is never categorised as something else
    apply_rules(company, [l for l in created if l.status == "new"], user)
    AuditLog.record(company, user, "bank.import", bank_account, f"{len(created)} lines, {skipped} skipped")
    return created, skipped


# ---------- Cheques on the statement ----------
CHEQUE_NO = re.compile(r"\d{3,}")


def _numbers(text):
    return {n.lstrip("0") for n in CHEQUE_NO.findall(text or "") if n.lstrip("0")}


def cheque_candidates(line):
    """Cheques this statement line may be paying: [(cheque, how)], best first.

    how = "exact"  (cheque number in the reference or description, and the same amount)
          "number" (number matches, amount differs: check before clearing)
          "amount" (same amount, no number on the line: check before clearing)
    Money out pairs with issued cheques; money in with received cheques in the safe or under collection.
    """
    from .models import Cheque

    account = line.bank_account
    direction = "out" if line.amount < 0 else "in"
    statuses = ("issued",) if direction == "out" else ("under_collection", "in_safe")
    open_cheques = (Cheque.objects.filter(company=line.company, direction=direction, status__in=statuses,
                                          currency_id=account.currency_id)
                    .filter(Q(bank_account=account) | Q(bank_account__isnull=True)))
    numbers = _numbers(f"{line.reference} {line.description}")
    amount = abs(line.amount)
    found = []
    for chq in open_cheques:
        number_hit = chq.number.strip().lstrip("0") in numbers
        if number_hit and chq.amount == amount:
            found.append((chq, "exact"))
        elif number_hit:
            found.append((chq, "number"))
        elif chq.amount == amount and chq.due_date <= line.date + timedelta(days=7):
            found.append((chq, "amount"))
    order = {"exact": 0, "number": 1, "amount": 2}
    return sorted(found, key=lambda f: (order[f[1]], f[0].due_date))[:5]


@transaction.atomic
def clear_from_statement(line, cheque, user):
    """Clear a cheque on the date the bank paid it and tie it to this statement line."""
    from .services import clear_cheque

    if line.status != "new":
        raise FeedError(_("This line has already been dealt with."))
    if (line.amount < 0) != (cheque.direction == "out"):
        raise FeedError(_("This cheque goes the other way."))
    try:
        entry = clear_cheque(cheque, line.date, user, bank_account=line.bank_account, statement_line=line)
    except PostingError as exc:
        raise FeedError(str(exc)) from exc
    line.journal_line = entry.lines.get(account=line.bank_account.gl_account)
    line.status = "matched"
    line.save(update_fields=["journal_line", "status"])
    return entry


def auto_clear_cheques(lines, user):
    """Clear every cheque that matches a statement line exactly (number and amount, one candidate only)."""
    cleared = 0
    for line in lines:
        if line.status != "new":
            continue
        exact = [c for c, how in cheque_candidates(line) if how == "exact"]
        if len(exact) == 1:
            try:
                with transaction.atomic():
                    clear_from_statement(line, exact[0], user)
                cleared += 1
            except FeedError:
                continue  # left for review on the Bank transactions page
    return cleared


def apply_rules(company, lines, user):
    rules = list(BankRule.objects.filter(company=company, is_active=True))
    for line in lines:
        for rule in rules:
            if rule.matches(line):
                line.rule = rule
                line.save(update_fields=["rule"])
                if rule.auto_post:
                    categorise(line, rule.account, rule.memo or line.description, user)
                break


def suggestions(line, days=10):
    """Posted ledger lines on this bank account with the same amount, near the same date, not yet matched."""
    gl = line.bank_account.gl_account
    field = "debit" if line.amount > 0 else "credit"
    taken = StatementLine.objects.filter(journal_line__isnull=False).values_list("journal_line_id", flat=True)
    return (JournalLine.objects.filter(account=gl, **{field: abs(line.amount)},
                                       entry__date__gte=line.date - timedelta(days=days),
                                       entry__date__lte=line.date + timedelta(days=days))
            .exclude(id__in=taken).select_related("entry")[:5])


@transaction.atomic
def match(line, journal_line, user):
    if line.status != "new":
        raise FeedError(_("This line has already been dealt with."))
    if journal_line.account_id != line.bank_account.gl_account_id:
        raise FeedError(_("That entry is on a different account."))
    line.journal_line, line.status = journal_line, "matched"
    line.save(update_fields=["journal_line", "status"])
    AuditLog.record(line.company, user, "bank.match", line.bank_account, f"{line.date} {line.amount} → {journal_line.entry.number}")


@transaction.atomic
def categorise(line, account, memo, user, cost_center=None, project=None):
    """Post a new entry for a bank line that has no matching transaction (bank charges, interest, transfers…)."""
    if line.status != "new":
        raise FeedError(_("This line has already been dealt with."))
    bank_gl = line.bank_account.gl_account
    amount = abs(line.amount)
    cur = line.bank_account.currency_id
    rate = Decimal("1")
    if cur != line.company.base_currency_id:
        from core.models import ExchangeRate
        rate = ExchangeRate.rate_for(line.company, cur, line.date)
        if rate is None:
            raise FeedError(_("Save an exchange rate for %(c)s first.") % {"c": cur})
    base = (amount * rate).quantize(Decimal("0.01"))
    bank_side = Line(bank_gl, debit=base if line.amount > 0 else ZERO, credit=base if line.amount < 0 else ZERO,
                     description=memo, currency=cur, amount_fc=amount, rate=rate)
    other = Line(account, debit=base if line.amount < 0 else ZERO, credit=base if line.amount > 0 else ZERO,
                 description=memo, cost_center=cost_center, project=project, currency=cur, amount_fc=amount, rate=rate)
    try:
        entry = post_journal(line.company, line.date, [bank_side, other], memo=memo, source="bank",
                             source_ref=line.reference or line.bank_account.name_en, user=user)
    except PostingError as exc:
        raise FeedError(str(exc)) from exc
    line.journal_line = entry.lines.get(account=bank_gl)
    line.status = "posted"
    line.save(update_fields=["journal_line", "status"])
    return entry


@transaction.atomic
def exclude(line, user):
    line.status = "excluded"
    line.save(update_fields=["status"])
    AuditLog.record(line.company, user, "bank.exclude", line.bank_account, f"{line.date} {line.amount} {line.description}")


# ---------- Reconciliation ----------
def last_reconciled_balance(bank_account):
    last = bank_account.reconciliations.filter(status="done").order_by("-statement_date", "-id").first()
    return last.statement_balance if last else ZERO


def _signed(line, foreign):
    if foreign:
        return line.amount_fc if line.debit > 0 else -line.amount_fc
    return line.debit - line.credit


def uncleared(rec):
    gl = rec.bank_account.gl_account
    return (JournalLine.objects.filter(account=gl, entry__date__lte=rec.statement_date)
            .filter(Q(reconciliation__isnull=True) | Q(reconciliation=rec))
            .select_related("entry").order_by("entry__date", "id"))


def cleared_total(rec):
    foreign = rec.bank_account.currency_id != rec.company.base_currency_id
    return sum((_signed(l, foreign) for l in rec.lines.all()), ZERO)


def difference(rec):
    return rec.statement_balance - (rec.opening_balance + cleared_total(rec))


@transaction.atomic
def set_cleared(rec, line_ids):
    if rec.status != "open":
        raise FeedError(_("This reconciliation is finished."))
    candidates = uncleared(rec)
    JournalLine.objects.filter(reconciliation=rec).update(reconciliation=None)
    candidates.filter(id__in=line_ids).update(reconciliation=rec)


@transaction.atomic
def finish(rec, user):
    if difference(rec) != 0:
        raise FeedError(_("The difference must be zero before you finish."))
    rec.status, rec.finished_at = "done", timezone.now()
    rec.save(update_fields=["status", "finished_at"])
    AuditLog.record(rec.company, user, "bank.reconciled", rec.bank_account, f"{rec.statement_date} {rec.statement_balance}")
