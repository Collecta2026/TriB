from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _

from core.models import AuditLog, client_ip
from ledger.services import Line, PostingError, post_journal, system_account
from users.permissions import require_perm

from . import importer
from .forms import (AttendanceImportForm, BenefitPlanForm, DepartmentForm, EmployeeForm, ImportForm, LeaveForm,
                    LoanForm)
from .models import Attendance, BenefitPlan, Department, Employee, Leave, Loan

ZERO = Decimal("0")
SESSION_KEY = "team.import"


# ---------- Employees ----------
@require_perm("team.view")
def employees(request):
    qs = Employee.objects.filter(company=request.company).select_related("department")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(code__icontains=q) | Q(name_en__icontains=q) | Q(name_ar__icontains=q) |
                       Q(job_title_en__icontains=q) | Q(national_id=q))
    status = request.GET.get("status", "current")
    if status == "current":
        qs = qs.exclude(status="left")
    elif status:
        qs = qs.filter(status=status)
    dept = request.GET.get("department", "")
    if dept.isdigit():
        qs = qs.filter(department_id=dept)
    people = list(qs)
    page = Paginator(people, 60).get_page(request.GET.get("page"))
    show_pay = request.membership.has_perm("payroll.view")
    return render(request, "team/employees.html", {
        "page": page, "q": q, "status": status, "statuses": Employee.STATUSES, "show_pay": show_pay,
        "departments": Department.objects.filter(company=request.company),
        "headcount": len(people), "payroll": sum((e.total_monthly for e in people), ZERO) if show_pay else None})


def _employee_form(request, employee):
    form = EmployeeForm(request.POST or None, instance=employee, company=request.company)
    if not request.membership.has_perm("payroll.view"):
        # Salary details are for payroll staff only.
        for name in ("basic_salary", "allowances", "insurable_wage", "medical_employee_share", "bank_account"):
            form.fields.pop(name, None)
    if request.method == "POST" and form.is_valid():
        employee = form.save(commit=False)
        employee.company = request.company
        employee.save()
        AuditLog.record(request.company, request.user, "employee.saved", employee, employee.code, ip=client_ip(request))
        messages.success(request, _("Saved."))
        return redirect("team:employee", pk=employee.pk)
    return render(request, "team/employee_form.html", {"form": form, "employee": employee})


@require_perm("team.create")
def employee_new(request):
    return _employee_form(request, Employee(company=request.company, hire_date=timezone.localdate()))


@require_perm("team.edit")
def employee_edit(request, pk):
    return _employee_form(request, get_object_or_404(Employee, pk=pk, company=request.company))


@require_perm("team.view")
def employee(request, pk):
    e = get_object_or_404(Employee, pk=pk, company=request.company)
    show_pay = request.membership.has_perm("payroll.view")
    since = timezone.localdate() - timedelta(days=31)
    return render(request, "team/employee_detail.html", {
        "e": e, "show_pay": show_pay,
        "payslips": e.payslips.select_related("run").order_by("-run__year", "-run__month")[:12] if show_pay else [],
        "loans": e.loans.all() if show_pay else [], "leaves": e.leaves.all()[:20],
        "attendance": e.attendance.filter(work_date__gte=since)[:31]})


# ---------- Import from the payroll workbook ----------
def _to_session(people):
    out = []
    for p in people:
        out.append({k: (v.isoformat() if isinstance(v, date) else str(v) if isinstance(v, Decimal) else v)
                    for k, v in p.items()})
    return out


def _from_session(rows):
    people = []
    for r in rows:
        p = dict(r)
        p["joined"] = date.fromisoformat(r["joined"]) if r.get("joined") else None
        for k in ("basic", "medical", "social", "allowance"):
            p[k] = Decimal(r[k]) if r.get(k) not in (None, "", "None") else None
        people.append(p)
    return people


@require_perm("team.create")
def employee_import(request):
    company = request.company
    form = ImportForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and "confirm" in request.POST:
        rows = request.session.pop(SESSION_KEY, None)
        if not rows:
            messages.error(request, _("The preview has expired. Upload the workbook again."))
            return redirect("team:import")
        created, updated = importer.import_people(company, _from_session(rows))
        AuditLog.record(company, request.user, "employee.import", None, f"{created} new, {updated} updated",
                        ip=client_ip(request))
        messages.success(request, _("%(c)s employees added and %(u)s updated.") % {"c": created, "u": updated})
        return redirect("team:employees")
    if request.method == "POST" and "cancel" in request.POST:
        request.session.pop(SESSION_KEY, None)
        return redirect("team:import")
    people = None
    if request.method == "POST" and form.is_valid():
        try:
            people = importer.read_workbook(form.cleaned_data["workbook"])
        except Exception:  # openpyxl raises many types for damaged or protected files
            messages.error(request, _("TriB could not read this workbook. Save it again as .xlsx and retry."))
            people = None
        if people is not None and not people:
            messages.error(request, _("No employee rows were found. The first sheet needs a heading row with Name and SN or Department."))
        elif people:
            request.session[SESSION_KEY] = _to_session(people)
            existing = set(Employee.objects.filter(company=company, code__in=[p["code"] for p in people])
                           .values_list("code", flat=True))
            for p in people:
                p["exists"] = p["code"] in existing
    return render(request, "team/import.html", {
        "form": form, "people": people, "show_pay": request.membership.has_perm("payroll.view"),
        "summary": {"new": sum(1 for p in people or [] if not p["exists"]),
                    "update": sum(1 for p in people or [] if p["exists"]),
                    "hold": sum(1 for p in people or [] if p["status"] == "hold"),
                    "left": sum(1 for p in people or [] if p["status"] == "left")}})


# ---------- Departments & benefits ----------
def _simple(request, model, form_class, template, redirect_name, extra=None):
    obj = None
    pk = request.GET.get("edit") or request.POST.get("pk")
    if pk and str(pk).isdigit():
        obj = get_object_or_404(model, pk=pk, company=request.company)
    form = None
    if request.membership.has_perm("team.edit" if obj else "team.create"):
        form = form_class(request.POST or None, instance=obj or model(company=request.company), company=request.company)
        if request.method == "POST" and form.is_valid():
            saved = form.save(commit=False)
            saved.company = request.company
            saved.save()
            messages.success(request, _("Saved."))
            return redirect(redirect_name)
    ctx = {"rows": model.objects.filter(company=request.company), "form": form, "obj": obj}
    ctx.update(extra or {})
    return render(request, template, ctx)


@require_perm("team.view")
def departments(request):
    rows = Department.objects.filter(company=request.company).annotate(
        n=Count("employees", filter=~Q(employees__status="left"))).select_related("cost_center")
    return _simple(request, Department, DepartmentForm, "team/departments.html", "team:departments",
                   {"rows": rows})


@require_perm("team.view")
def benefits(request):
    rows = BenefitPlan.objects.filter(company=request.company).annotate(n=Count("members"))
    return _simple(request, BenefitPlan, BenefitPlanForm, "team/benefits.html", "team:benefits", {"rows": rows})


# ---------- Loans & advances ----------
@require_perm("payroll.view")
def loans(request):
    form = LoanForm(request.POST or None, company=request.company,
                    initial={"issue_date": timezone.localdate()}, instance=Loan(company=request.company))
    if request.method == "POST":
        if not request.membership.has_perm("payroll.create"):
            messages.error(request, _("You do not have permission to do that."))
        elif form.is_valid():
            try:
                with transaction.atomic():
                    loan = form.save(commit=False)
                    loan.company, loan.outstanding = request.company, loan.principal
                    loan.save()
                    paid_from = form.cleaned_data.get("paid_from")
                    if paid_from:
                        label = _("Advance to %(e)s") % {"e": loan.employee}
                        loan.journal_entry = post_journal(request.company, loan.issue_date, [
                            Line(system_account(request.company, "custody"), debit=loan.principal, description=label),
                            Line(paid_from.gl_account, credit=loan.principal, description=label),
                        ], memo=label, source="payroll", source_ref=f"LOAN-{loan.pk}", user=request.user)
                        loan.save(update_fields=["journal_entry"])
                    AuditLog.record(request.company, request.user, "loan.issued", loan, str(loan.principal))
                messages.success(request, _("Loan recorded. It is deducted from payroll each month until repaid."))
                return redirect("team:loans")
            except PostingError as exc:
                messages.error(request, str(exc))
    rows = Loan.objects.filter(company=request.company).select_related("employee", "journal_entry")
    status = request.GET.get("status", "active")
    if status:
        rows = rows.filter(status=status)
    return render(request, "team/loans.html", {"form": form, "rows": rows, "status": status,
                                               "outstanding": rows.aggregate(s=Sum("outstanding"))["s"] or ZERO})


# ---------- Attendance ----------
@require_perm("team.view")
def attendance(request):
    from payroll.services import import_attendance
    today = timezone.localdate()
    try:
        year, month = int(request.GET.get("year", today.year)), int(request.GET.get("month", today.month))
        start = date(year, month, 1)
    except ValueError:
        start = today.replace(day=1)
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    form = AttendanceImportForm(request.POST or None, request.FILES or None)
    if request.method == "POST":
        if not request.membership.has_perm("team.edit"):
            messages.error(request, _("You do not have permission to do that."))
        elif form.is_valid():
            raw = form.cleaned_data["file"].read()
            text = raw.decode("utf-8-sig", errors="replace")
            added, updated, skipped = import_attendance(request.company, text)
            messages.success(request, _("Attendance imported: %(a)s added, %(u)s updated, %(s)s skipped.") % {
                "a": added, "u": updated, "s": skipped})
            return redirect(f"{request.path}?year={start.year}&month={start.month}")
    rows = (Attendance.objects.filter(company=request.company, work_date__gte=start, work_date__lte=end)
            .values("employee__code", "employee__name_en", "employee_id")
            .annotate(days=Count("id", filter=Q(status="present")), absent=Count("id", filter=Q(status="absent")),
                      worked=Sum("hours_worked"), expected=Sum("expected_hours"), ot=Sum("ot_day_hours"),
                      night=Sum("ot_night_hours"))
            .order_by("employee__code"))
    return render(request, "team/attendance.html", {"form": form, "rows": rows, "start": start, "end": end,
                                                    "prev": start - timedelta(days=1), "next": end + timedelta(days=1)})


# ---------- Leave ----------
@require_perm("team.view")
def leave(request):
    form = LeaveForm(request.POST or None, company=request.company, instance=Leave(company=request.company))
    form.fields["employee"].queryset = Employee.objects.filter(company=request.company).exclude(status="left")
    if request.method == "POST":
        if not request.membership.has_perm("team.edit"):
            messages.error(request, _("You do not have permission to do that."))
        elif form.is_valid():
            item = form.save(commit=False)
            item.company = request.company
            item.days = form.cleaned_data["days"]
            item.save()
            messages.success(request, _("Leave recorded."))
            return redirect("team:leave")
    year = timezone.localdate().year
    rows = Leave.objects.filter(company=request.company, start_date__year=year).select_related("employee")
    return render(request, "team/leave.html", {"form": form, "rows": rows, "year": year})
