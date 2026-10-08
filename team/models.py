"""Team (HR) records, ported from the "Time" HR & payroll system and made multi-company."""
from datetime import date
from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import Bilingual, Branch, Company, is_arabic
from ledger.models import CostCenter, JournalEntry

MONEY = {"max_digits": 19, "decimal_places": 2}
HOURS = {"max_digits": 7, "decimal_places": 2}


class Department(Bilingual):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="departments")
    cost_center = models.ForeignKey(CostCenter, on_delete=models.PROTECT, null=True, blank=True,
                                    verbose_name=_("Cost centre"), help_text=_("Payroll costs of this department post here."))

    class Meta:
        ordering = ["name_en"]


class Grade(Bilingual):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="grades")
    code = models.CharField(_("Code"), max_length=20)
    order = models.PositiveIntegerField(_("Order"), default=0)

    class Meta:
        ordering = ["order", "code"]

    def __str__(self):
        return f"{self.code} · {self.name}"


class SpinePoint(models.Model):
    grade = models.ForeignKey(Grade, on_delete=models.CASCADE, related_name="points")
    point_no = models.PositiveIntegerField(_("Spine point"))
    monthly_salary = models.DecimalField(_("Monthly salary"), **MONEY)

    class Meta:
        ordering = ["point_no"]


class BenefitPlan(Bilingual):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="benefit_plans")
    provider = models.CharField(_("Provider"), max_length=160, blank=True)
    employer_cost = models.DecimalField(_("Company share / month"), default=0, **MONEY)
    employee_cost = models.DecimalField(_("Employee share / month"), default=0, **MONEY)
    coverage = models.CharField(_("Coverage"), max_length=300, blank=True)
    is_active = models.BooleanField(_("Active"), default=True)

    class Meta:
        ordering = ["name_en"]


class Employee(Bilingual):
    STATUSES = [("active", _("Active")), ("hold", _("On hold")), ("left", _("Left"))]
    CONTRACTS = [("indefinite", _("Indefinite")), ("fixed", _("Fixed term")), ("probation", _("Probation")),
                 ("part_time", _("Part time")), ("contractor", _("Contractor"))]
    GENDERS = [("", "—"), ("male", _("Male")), ("female", _("Female"))]
    PAYMENT = [("bank", _("Bank transfer")), ("instapay", _("InstaPay")), ("cash", _("Cash"))]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="employees")
    code = models.CharField(_("Employee code"), max_length=30, help_text=_("Use the fingerprint ID so attendance imports match."))
    national_id = models.CharField(_("National ID"), max_length=20, blank=True)
    insurance_no = models.CharField(_("Insurance number"), max_length=30, blank=True)
    gender = models.CharField(_("Gender"), max_length=6, choices=GENDERS, blank=True)
    dob = models.DateField(_("Date of birth"), null=True, blank=True)
    phone = models.CharField(_("Mobile"), max_length=40, blank=True)
    email = models.EmailField(_("Email"), blank=True)
    address = models.CharField(_("Address"), max_length=300, blank=True)
    department = models.ForeignKey(Department, on_delete=models.PROTECT, null=True, blank=True, related_name="employees",
                                   verbose_name=_("Department"))
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, null=True, blank=True, verbose_name=_("Branch"))
    job_title_en = models.CharField(_("Job title (English)"), max_length=160, blank=True)
    job_title_ar = models.CharField(_("Job title (Arabic)"), max_length=160, blank=True)
    grade = models.ForeignKey(Grade, on_delete=models.PROTECT, null=True, blank=True, verbose_name=_("Grade"))
    spine_point = models.PositiveIntegerField(_("Spine point"), null=True, blank=True)
    hire_date = models.DateField(_("Joining date"), null=True, blank=True)
    end_date = models.DateField(_("Leaving date"), null=True, blank=True)
    status = models.CharField(_("Status"), max_length=6, choices=STATUSES, default="active")
    contract_type = models.CharField(_("Contract"), max_length=12, choices=CONTRACTS, default="indefinite")
    basic_salary = models.DecimalField(_("Basic salary / month"), default=0, **MONEY)
    allowances = models.DecimalField(_("Allowances / month"), default=0, **MONEY)
    insurable_wage = models.DecimalField(_("Insurable wage"), null=True, blank=True, **MONEY,
                                         help_text=_("Leave empty to use basic + allowances within the legal floor and ceiling."))
    insured = models.BooleanField(_("Covered by social insurance"), default=True)
    taxable = models.BooleanField(_("Subject to salary tax"), default=True)
    payment_method = models.CharField(_("Paid by"), max_length=8, choices=PAYMENT, default="bank")
    bank_name = models.CharField(_("Bank"), max_length=120, blank=True)
    bank_account = models.CharField(_("Account / IBAN / InstaPay"), max_length=60, blank=True)
    benefit = models.ForeignKey(BenefitPlan, on_delete=models.SET_NULL, null=True, blank=True, related_name="members",
                                verbose_name=_("Medical plan"))
    medical_employee_share = models.DecimalField(_("Medical deduction / month"), null=True, blank=True, **MONEY,
                                                 help_text=_("Overrides the plan's employee share for this person."))
    notes = models.TextField(_("Notes"), blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["code"]
        constraints = [models.UniqueConstraint(fields=["company", "code"], name="uniq_employee_code")]

    def __str__(self):
        return f"{self.code} · {self.name}"

    @property
    def job_title(self):
        return (self.job_title_ar if is_arabic() and self.job_title_ar else self.job_title_en) or ""

    @property
    def total_monthly(self):
        return (self.basic_salary or 0) + (self.allowances or 0)

    @property
    def medical_deduction(self):
        if self.medical_employee_share is not None:
            return self.medical_employee_share
        return self.benefit.employee_cost if self.benefit_id and self.benefit.is_active else Decimal("0")

    @property
    def years_service(self):
        if not self.hire_date:
            return 0
        end = self.end_date or date.today()
        return round((end - self.hire_date).days / 365.25, 1)

    def active_loans(self):
        return list(self.loans.filter(status="active").order_by("issue_date", "id"))


class Loan(models.Model):
    STATUSES = [("active", _("Active")), ("settled", _("Settled"))]
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="+")
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="loans", verbose_name=_("Employee"))
    issue_date = models.DateField(_("Issue date"))
    principal = models.DecimalField(_("Amount"), **MONEY)
    monthly_deduction = models.DecimalField(_("Monthly deduction"), **MONEY)
    outstanding = models.DecimalField(_("Outstanding"), **MONEY)
    reason = models.CharField(_("Reason"), max_length=200, blank=True)
    status = models.CharField(_("Status"), max_length=8, choices=STATUSES, default="active")
    journal_entry = models.OneToOneField(JournalEntry, on_delete=models.PROTECT, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["-issue_date", "-id"]


class LoanPayment(models.Model):
    loan = models.ForeignKey(Loan, on_delete=models.CASCADE, related_name="payments")
    pay_date = models.DateField()
    amount = models.DecimalField(**MONEY)
    note = models.CharField(max_length=120, blank=True)
    payroll_run = models.ForeignKey("payroll.PayrollRun", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["pay_date", "id"]


class Attendance(models.Model):
    STATUSES = [("present", _("Present")), ("absent", _("Absent")), ("leave", _("Leave")), ("holiday", _("Holiday"))]
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="+")
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="attendance")
    work_date = models.DateField(_("Date"))
    hours_worked = models.DecimalField(_("Hours worked"), default=0, **HOURS)
    expected_hours = models.DecimalField(_("Expected hours"), default=0, **HOURS)
    ot_day_hours = models.DecimalField(default=0, **HOURS)
    ot_night_hours = models.DecimalField(_("Night / rest-day overtime"), default=0, **HOURS)
    status = models.CharField(_("Status"), max_length=8, choices=STATUSES, default="present")
    source = models.CharField(max_length=10, default="import")

    class Meta:
        ordering = ["-work_date", "employee__code"]
        constraints = [models.UniqueConstraint(fields=["employee", "work_date"], name="uniq_attendance_day")]


class Leave(models.Model):
    TYPES = [("annual", _("Annual")), ("sick", _("Sick")), ("casual", _("Casual")), ("maternity", _("Maternity")),
             ("unpaid", _("Unpaid"))]
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="+")
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="leaves", verbose_name=_("Employee"))
    leave_type = models.CharField(_("Type"), max_length=10, choices=TYPES)
    start_date = models.DateField(_("From"))
    end_date = models.DateField(_("To"))
    days = models.DecimalField(_("Days"), default=0, **HOURS)
    paid_pct = models.DecimalField(_("Paid %"), default=100, **HOURS)
    note = models.CharField(_("Note"), max_length=200, blank=True)

    class Meta:
        ordering = ["-start_date"]


class LeaveProvision(models.Model):
    """Monthly snapshot of accrued-but-untaken annual leave and its value (the leave liability)."""

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="+")
    year = models.PositiveIntegerField()
    month = models.PositiveSmallIntegerField()
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="+")
    entitlement_days = models.DecimalField(default=0, **HOURS)
    accrued_days = models.DecimalField(default=0, **HOURS)
    taken_days = models.DecimalField(default=0, **HOURS)
    balance_days = models.DecimalField(default=0, **HOURS)
    daily_rate = models.DecimalField(default=0, **MONEY)
    provision_value = models.DecimalField(default=0, **MONEY)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["company", "year", "month", "employee"], name="uniq_leave_provision")]
