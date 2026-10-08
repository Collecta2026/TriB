from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.utils.translation import gettext_lazy as _

from banking.models import BankAccount
from core.models import Company
from ledger.models import JournalEntry
from team.models import Employee

MONEY = {"max_digits": 19, "decimal_places": 2}
PCT = {"max_digits": 6, "decimal_places": 2}
HOURS = {"max_digits": 9, "decimal_places": 2}


class PayrollSettings(models.Model):
    """Statutory parameters (Time's CompanySettings), one row per company. Defaults reflect 2026."""

    company = models.OneToOneField(Company, on_delete=models.CASCADE, related_name="payroll_settings")
    insurance_no = models.CharField(_("Employer insurance number"), max_length=60, blank=True)
    standard_daily_hours = models.DecimalField(_("Standard hours per day"), default=8, **PCT)
    standard_weekly_hours = models.DecimalField(_("Standard hours per week"), default=48, **PCT)
    working_days = models.CharField(_("Working days"), max_length=40, default="SU,MO,TU,WE,TH")
    days_per_month = models.PositiveSmallIntegerField(_("Days per month (for daily rate)"), default=30)
    si_employee_pct = models.DecimalField(_("Social insurance — employee %"), default=Decimal("11.00"), **PCT)
    si_employer_pct = models.DecimalField(_("Social insurance — employer %"), default=Decimal("18.75"), **PCT)
    emergency_fund_pct = models.DecimalField(_("Emergency fund — employer %"), default=Decimal("1.00"), **PCT)
    si_floor = models.DecimalField(_("Insurable wage floor / month"), default=Decimal("2700"), **MONEY)
    si_ceiling = models.DecimalField(_("Insurable wage ceiling / month"), default=Decimal("16700"), **MONEY)
    tax_annual_exemption = models.DecimalField(_("Annual salary tax exemption"), default=Decimal("20000"), **MONEY)
    overtime_day_pct = models.DecimalField(_("Overtime premium — day %"), default=Decimal("35"), **PCT)
    overtime_night_pct = models.DecimalField(_("Overtime premium — night / rest day %"), default=Decimal("70"), **PCT)
    annual_leave_y1 = models.PositiveSmallIntegerField(_("Annual leave — first year (days)"), default=15)
    annual_leave_std = models.PositiveSmallIntegerField(_("Annual leave — standard (days)"), default=21)
    annual_leave_senior = models.PositiveSmallIntegerField(_("Annual leave — senior (days)"), default=30)
    casual_leave = models.PositiveSmallIntegerField(_("Casual leave (days)"), default=7)
    probation_months = models.PositiveSmallIntegerField(_("Probation (months)"), default=3)
    pay_bank_account = models.ForeignKey(BankAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                                         verbose_name=_("Salaries paid from"))
    pay_cash_account = models.ForeignKey(BankAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                                         verbose_name=_("Cash salaries paid from"))

    @classmethod
    def for_company(cls, company):
        obj, _created = cls.objects.get_or_create(company=company)
        return obj


class DelegationBand(models.Model):
    """Scheme of delegation by run net total: Finance Manager approval, with a joint MD release where required."""

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="+")
    name = models.CharField(_("Band"), max_length=60)
    min_amount = models.DecimalField(_("From net total"), default=0, **MONEY)
    max_amount = models.DecimalField(_("Up to net total"), null=True, blank=True, **MONEY)
    requires_fm = models.BooleanField(_("Finance Manager approval"), default=True)
    requires_md = models.BooleanField(_("Managing Director authorisation"), default=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "min_amount"]


class PayrollRun(models.Model):
    STATUSES = [("draft", _("Draft")), ("prepared", _("Waiting for Finance Manager")),
                ("approved", _("Waiting for Managing Director")), ("authorised", _("Authorised")), ("paid", _("Paid"))]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="payroll_runs")
    year = models.PositiveIntegerField(_("Year"))
    month = models.PositiveSmallIntegerField(_("Month"))
    status = models.CharField(_("Status"), max_length=10, choices=STATUSES, default="draft")
    created_at = models.DateTimeField(auto_now_add=True)
    prepared_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    prepared_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    authorised_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    authorised_at = models.DateTimeField(null=True, blank=True)
    paid_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    paid_at = models.DateTimeField(null=True, blank=True)
    reject_reason = models.CharField(max_length=300, blank=True)
    journal_entry = models.OneToOneField(JournalEntry, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    payment_entry = models.OneToOneField(JournalEntry, on_delete=models.PROTECT, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["-year", "-month"]
        constraints = [models.UniqueConstraint(fields=["company", "year", "month"], name="uniq_payroll_period")]

    def __str__(self):
        return self.period_label

    @property
    def period_label(self):
        return f"{self.year}-{self.month:02d}"

    @property
    def locked(self):
        return self.status != "draft"

    def totals(self):
        fields = ["basic", "allowances", "overtime", "gross", "insurable_wage", "si_employee", "si_employer",
                  "emergency_fund", "income_tax", "absence_deduction", "loan_deduction", "other_deductions",
                  "total_deductions", "net_pay", "employer_cost"]
        agg = self.payslips.aggregate(**{f: Sum(f) for f in fields})
        return {k: v or Decimal("0") for k, v in agg.items()}


class Payslip(models.Model):
    run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name="payslips")
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="payslips")
    basic = models.DecimalField(default=0, **MONEY)
    allowances = models.DecimalField(default=0, **MONEY)
    overtime = models.DecimalField(default=0, **MONEY)
    gross = models.DecimalField(default=0, **MONEY)
    insurable_wage = models.DecimalField(default=0, **MONEY)
    si_employee = models.DecimalField(default=0, **MONEY)
    si_employer = models.DecimalField(default=0, **MONEY)
    emergency_fund = models.DecimalField(default=0, **MONEY)
    income_tax = models.DecimalField(default=0, **MONEY)
    absence_deduction = models.DecimalField(default=0, **MONEY)
    loan_deduction = models.DecimalField(default=0, **MONEY)
    other_deductions = models.DecimalField(default=0, **MONEY)
    total_deductions = models.DecimalField(default=0, **MONEY)
    net_pay = models.DecimalField(default=0, **MONEY)
    employer_cost = models.DecimalField(default=0, **MONEY)
    hours_worked = models.DecimalField(default=0, **HOURS)
    hours_expected = models.DecimalField(default=0, **HOURS)
    comment = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["employee__code"]


class Remittance(models.Model):
    """Paying a run's deductions over: social insurance to NOSI, salary tax to the Tax Authority, medical to the insurer."""

    KINDS = [("si", _("Social insurance (NOSI)")), ("tax", _("Salary tax")), ("medical", _("Medical & other deductions"))]
    run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name="remittances")
    kind = models.CharField(max_length=8, choices=KINDS)
    date = models.DateField()
    amount = models.DecimalField(**MONEY)
    bank_account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, related_name="+")
    reference = models.CharField(max_length=80, blank=True)
    journal_entry = models.OneToOneField(JournalEntry, on_delete=models.PROTECT, related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["run", "kind"], name="uniq_remittance_kind")]
