"""Payroll runs: compute (Time's engine), approve (Time's scheme of delegation), post to the ledger, pay, remit.

Posting on authorisation (accrual), per department cost centre:
    Dr Salaries & wages            basic + allowances − absence deductions
    Dr Overtime                    overtime
    Dr Employer social insurance   employer 18.75% + emergency fund 1%
        Cr Social insurance payable          employee 11% + employer 18.75% + emergency 1%
        Cr Salary income tax payable         income tax
        Cr Employee custody & advances       loan recoveries
        Cr Employee deductions payable       medical & other deductions
        Cr Salaries payable                  net pay
Payment:     Dr Salaries payable   Cr Bank (bank & InstaPay staff) / Cash box (cash staff)
Remittance:  Dr Social insurance payable / Salary tax payable / Employee deductions payable   Cr Bank
"""
import calendar
import csv
import io
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from core.models import AuditLog
from ledger.services import Line, PostingError, post_journal, system_account
from team.models import Attendance, Employee, Leave, LoanPayment

from . import engine
from .models import DelegationBand, PayrollRun, PayrollSettings, Payslip, Remittance

ZERO = Decimal("0")


class PayrollError(Exception):
    pass


def month_bounds(year, month):
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def required_signoffs(company, net_total):
    band = (DelegationBand.objects.filter(company=company, min_amount__lte=net_total)
            .filter(Q(max_amount__isnull=True) | Q(max_amount__gte=net_total)).order_by("order").first())
    if not band:
        return {"fm": True, "md": True, "band": None}
    return {"fm": band.requires_fm, "md": band.requires_md, "band": band}


@transaction.atomic
def compute_run(run):
    """Build a payslip for every employee active during the period (Time's _compute_run)."""
    if run.locked:
        raise PayrollError(_("Only a draft run can be recomputed."))
    company = run.company
    s = PayrollSettings.for_company(company)
    start, end = month_bounds(run.year, run.month)
    prior = {p.employee_id: p.comment for p in run.payslips.all() if p.comment}
    run.payslips.all().delete()
    employees = (Employee.objects.filter(company=company).exclude(status="hold")
                 .filter(Q(hire_date__isnull=True) | Q(hire_date__lte=end))
                 .filter(Q(end_date__isnull=True) | Q(end_date__gte=start)))
    for e in employees.select_related("benefit"):
        att = list(Attendance.objects.filter(employee=e, work_date__gte=start, work_date__lte=end))
        worked = sum((a.hours_worked for a in att), ZERO)
        expected = sum((a.expected_hours for a in att), ZERO)
        ot_day = sum((max(ZERO, a.hours_worked - a.expected_hours) for a in att), ZERO)
        ot_night = sum((a.ot_night_hours for a in att), ZERO)
        shortfall = sum((max(ZERO, a.expected_hours - a.hours_worked) for a in att), ZERO)
        loan_ded = sum((min(l.monthly_deduction, l.outstanding) for l in e.active_loans()), ZERO)
        r = engine.compute_payslip(
            basic=e.basic_salary, allowances=e.allowances, ot_day_hours=ot_day, ot_night_hours=ot_night,
            hours_short=shortfall, loan_deduction=loan_ded, other_deductions=e.medical_deduction,
            insurable_override=e.insurable_wage, s=s, insured=e.insured, taxable=e.taxable)
        Payslip.objects.create(run=run, employee=e, hours_worked=worked, hours_expected=expected,
                               comment=prior.get(e.id, ""), **r)
    return run


@transaction.atomic
def submit(run, user):
    if run.status != "draft":
        raise PayrollError(_("This run has already been submitted."))
    if not run.payslips.exists():
        raise PayrollError(_("There are no payslips in this run."))
    run.status, run.prepared_by, run.prepared_at, run.reject_reason = "prepared", user, timezone.now(), ""
    run.save(update_fields=["status", "prepared_by", "prepared_at", "reject_reason"])
    AuditLog.record(run.company, user, "payroll.submit", run, run.period_label)


def _same_person(a, b):
    return a is not None and b is not None and a.pk == b.pk


@transaction.atomic
def approve(run, user, membership):
    if run.status != "prepared":
        raise PayrollError(_("This run is not waiting for approval."))
    if _same_person(run.prepared_by, user) and not membership.is_owner:
        raise PayrollError(_("Segregation of duties: the person who prepared the run cannot approve it."))
    run.approved_by, run.approved_at = user, timezone.now()
    signoffs = required_signoffs(run.company, run.totals()["net_pay"])
    if signoffs["md"]:
        run.status = "approved"
        run.save(update_fields=["status", "approved_by", "approved_at"])
    else:
        run.save(update_fields=["approved_by", "approved_at"])
        _authorise(run, user)
    AuditLog.record(run.company, user, "payroll.approve", run, run.period_label)


@transaction.atomic
def authorise(run, user, membership):
    if run.status != "approved":
        raise PayrollError(_("This run is not waiting for authorisation."))
    if (_same_person(run.prepared_by, user) or _same_person(run.approved_by, user)) and not membership.is_owner:
        raise PayrollError(_("Joint release: authorisation must come from a different person."))
    _authorise(run, user)
    AuditLog.record(run.company, user, "payroll.authorise", run, run.period_label)


def _authorise(run, user):
    run.authorised_by, run.authorised_at, run.status = user, timezone.now(), "authorised"
    run.journal_entry = post_run(run, user)
    run.save(update_fields=["authorised_by", "authorised_at", "status", "journal_entry"])
    apply_loan_deductions(run)


@transaction.atomic
def reject(run, user, reason):
    if run.status not in ("prepared", "approved"):
        raise PayrollError(_("Only a submitted or approved run can be returned."))
    run.reject_reason = (reason or "").strip()[:300] or _("Returned for review")
    run.status = "draft"
    run.prepared_by = run.prepared_at = run.approved_by = run.approved_at = None
    run.save()
    AuditLog.record(run.company, user, "payroll.reject", run, run.reject_reason)


def journal_lines(run):
    """The accrual entry for a run, grouped by department cost centre."""
    company = run.company
    salaries = system_account(company, "salaries")
    overtime = system_account(company, "overtime")
    employer_si = system_account(company, "employer_si")
    by_cc = defaultdict(lambda: {"salary": ZERO, "overtime": ZERO, "employer": ZERO})
    totals = defaultdict(Decimal)
    for p in run.payslips.select_related("employee__department__cost_center"):
        dept = p.employee.department
        cc = dept.cost_center if dept and dept.cost_center_id else None
        bucket = by_cc[cc]
        bucket["salary"] += p.basic + p.allowances - p.absence_deduction
        bucket["overtime"] += p.overtime
        bucket["employer"] += p.si_employer + p.emergency_fund
        totals["si"] += p.si_employee + p.si_employer + p.emergency_fund
        totals["tax"] += p.income_tax
        totals["loan"] += p.loan_deduction
        totals["other"] += p.other_deductions
        totals["net"] += p.net_pay
    label = _("Payroll %(p)s") % {"p": run.period_label}
    lines = []
    for cc, b in by_cc.items():
        lines += [Line(salaries, debit=b["salary"], description=label, cost_center=cc),
                  Line(overtime, debit=b["overtime"], description=label, cost_center=cc),
                  Line(employer_si, debit=b["employer"], description=label, cost_center=cc)]
    lines += [
        Line(system_account(company, "social_insurance"), credit=totals["si"], description=_("Social insurance %(p)s") % {"p": run.period_label}),
        Line(system_account(company, "payroll_tax"), credit=totals["tax"], description=_("Salary tax %(p)s") % {"p": run.period_label}),
        Line(system_account(company, "custody"), credit=totals["loan"], description=_("Loan recoveries %(p)s") % {"p": run.period_label}),
        Line(system_account(company, "employee_deductions"), credit=totals["other"], description=_("Medical & other %(p)s") % {"p": run.period_label}),
        Line(system_account(company, "salaries_payable"), credit=totals["net"], description=_("Net salaries %(p)s") % {"p": run.period_label}),
    ]
    return lines


def post_run(run, user):
    _start, end = month_bounds(run.year, run.month)
    try:
        return post_journal(run.company, end, journal_lines(run), memo=_("Payroll %(p)s") % {"p": run.period_label},
                            source="payroll", source_ref=f"PAY-{run.period_label}", user=user)
    except PostingError as exc:
        raise PayrollError(str(exc)) from exc


def apply_loan_deductions(run):
    """On authorisation, reduce loan balances by this run's deductions (once) — Time's rule."""
    _start, end = month_bounds(run.year, run.month)
    for p in run.payslips.select_related("employee"):
        remaining = p.loan_deduction
        for loan in p.employee.active_loans():
            if remaining <= 0:
                break
            take = min(remaining, loan.monthly_deduction, loan.outstanding)
            if take > 0:
                loan.outstanding = max(ZERO, loan.outstanding - take)
                if loan.outstanding <= 0:
                    loan.status = "settled"
                loan.save(update_fields=["outstanding", "status"])
                LoanPayment.objects.create(loan=loan, pay_date=end, amount=take, payroll_run=run,
                                           note=_("Payroll %(p)s") % {"p": run.period_label})
                remaining -= take


@transaction.atomic
def mark_paid(run, user, pay_date, bank_account, cash_account=None):
    """Pay net salaries: bank & InstaPay staff from the bank account, cash staff from the cash box."""
    if run.status != "authorised":
        raise PayrollError(_("Only an authorised run can be paid."))
    if bank_account is None:
        raise PayrollError(_("Choose the bank account salaries are paid from."))
    by_channel = defaultdict(Decimal)
    for p in run.payslips.select_related("employee"):
        by_channel["cash" if p.employee.payment_method == "cash" else "bank"] += p.net_pay
    if by_channel["cash"] and cash_account is None:
        raise PayrollError(_("Some staff are paid in cash: choose the cash box."))
    payable = system_account(run.company, "salaries_payable")
    label = _("Salaries paid %(p)s") % {"p": run.period_label}
    lines = [Line(payable, debit=by_channel["bank"] + by_channel["cash"], description=label)]
    if by_channel["bank"]:
        lines.append(Line(bank_account.gl_account, credit=by_channel["bank"], description=label))
    if by_channel["cash"]:
        lines.append(Line(cash_account.gl_account, credit=by_channel["cash"], description=label))
    try:
        run.payment_entry = post_journal(run.company, pay_date, lines, memo=label, source="payroll",
                                         source_ref=f"PAY-{run.period_label}", user=user)
    except PostingError as exc:
        raise PayrollError(str(exc)) from exc
    run.status, run.paid_by, run.paid_at = "paid", user, timezone.now()
    run.save(update_fields=["status", "paid_by", "paid_at", "payment_entry"])
    AuditLog.record(run.company, user, "payroll.paid", run, run.period_label)


def remittance_amounts(run):
    t = run.totals()
    return {"si": t["si_employee"] + t["si_employer"] + t["emergency_fund"], "tax": t["income_tax"],
            "medical": t["other_deductions"]}


@transaction.atomic
def remit(run, kind, user, pay_date, bank_account, reference=""):
    if run.status not in ("authorised", "paid"):
        raise PayrollError(_("Deductions can be paid over once the run is authorised."))
    if run.remittances.filter(kind=kind).exists():
        raise PayrollError(_("This deduction has already been paid over."))
    amount = remittance_amounts(run)[kind]
    if amount <= 0:
        raise PayrollError(_("There is nothing to pay over."))
    account = {"si": "social_insurance", "tax": "payroll_tax", "medical": "employee_deductions"}[kind]
    label = f"{dict(Remittance.KINDS)[kind]} {run.period_label}"
    try:
        entry = post_journal(run.company, pay_date, [
            Line(system_account(run.company, account), debit=amount, description=label),
            Line(bank_account.gl_account, credit=amount, description=label),
        ], memo=label, source="payroll", source_ref=reference or f"PAY-{run.period_label}", user=user)
    except PostingError as exc:
        raise PayrollError(str(exc)) from exc
    Remittance.objects.create(run=run, kind=kind, date=pay_date, amount=amount, bank_account=bank_account,
                              reference=reference, journal_entry=entry, created_by=user)
    AuditLog.record(run.company, user, "payroll.remit", run, label)


@transaction.atomic
def delete_run(run, user):
    if run.locked:
        raise PayrollError(_("Only a draft run can be deleted."))
    AuditLog.record(run.company, user, "payroll.delete", run, run.period_label)
    run.delete()


# ---------- Leave provision (Time's rules) ----------
def leave_entitlement(employee, s, as_of=None):
    as_of = as_of or date.today()
    yrs = employee.years_service or 0
    age = (as_of - employee.dob).days / 365.25 if employee.dob else None
    if yrs >= 10 or (age is not None and age >= 50):
        return s.annual_leave_senior
    if yrs < 1:
        return s.annual_leave_y1
    return s.annual_leave_std


def leave_provision(company, year, month):
    s = PayrollSettings.for_company(company)
    start, period_end = date(year, 1, 1), month_bounds(year, month)[1]
    rows = []
    for e in Employee.objects.filter(company=company, status="active").order_by("code"):
        if e.hire_date and e.hire_date > period_end:
            continue
        entitlement = Decimal(leave_entitlement(e, s, period_end))
        first_month = e.hire_date.month if (e.hire_date and e.hire_date.year == year) else 1
        months_earned = max(0, month - first_month + 1)
        accrued = (entitlement * months_earned / 12).quantize(Decimal("0.01"))
        taken = Leave.objects.filter(employee=e, leave_type="annual", start_date__gte=start,
                                     start_date__lte=period_end).aggregate(d=Sum("days"))["d"] or ZERO
        balance = accrued - taken
        daily = (e.total_monthly / (s.days_per_month or 30)).quantize(Decimal("0.01"))
        rows.append({"emp": e, "entitlement": entitlement, "accrued": accrued, "taken": taken, "balance": balance,
                     "daily": daily, "provision": (max(ZERO, balance) * daily).quantize(Decimal("0.01")),
                     "monthly_accrual": (entitlement / 12 * daily).quantize(Decimal("0.01"))})
    totals = {k: sum((r[k] for r in rows), ZERO) for k in ("provision", "monthly_accrual", "balance")}
    return rows, totals


# ---------- Attendance import (Time's CSV format) ----------
def _hours_between(t_in, t_out):
    try:
        a, b = datetime.strptime(t_in.strip(), "%H:%M"), datetime.strptime(t_out.strip(), "%H:%M")
        return Decimal(str(round((b - a).seconds / 3600, 2)))
    except (ValueError, AttributeError):
        return ZERO


@transaction.atomic
def import_attendance(company, text):
    """CSV: employee_code,date,hours_worked,time_in,time_out (hours or in/out times)."""
    s = PayrollSettings.for_company(company)
    reader = csv.DictReader(io.StringIO(text))
    emap = {e.code: e for e in Employee.objects.filter(company=company)}
    added = updated = skipped = 0
    for row in reader:
        emp = emap.get((row.get("employee_code") or row.get("code") or "").strip())
        try:
            day = date.fromisoformat((row.get("date") or "").strip())
        except ValueError:
            day = None
        if not emp or not day:
            skipped += 1
            continue
        try:
            hours = Decimal((row.get("hours_worked") or "").strip() or "0")
        except InvalidOperation:
            hours = ZERO
        if not hours and row.get("time_in") and row.get("time_out"):
            hours = _hours_between(row["time_in"], row["time_out"])
        expected = s.standard_daily_hours
        rec, created = Attendance.objects.get_or_create(company=company, employee=emp, work_date=day)
        added += created
        updated += not created
        rec.hours_worked, rec.expected_hours = hours, expected
        rec.ot_day_hours = max(ZERO, hours - expected)
        rec.status = "present" if hours > 0 else "absent"
        rec.save()
    return added, updated, skipped
