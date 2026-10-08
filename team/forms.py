from django import forms
from django.utils.translation import gettext_lazy as _

from banking.models import BankAccount
from core.forms_util import DATE, CompanyModelForm

from .models import BenefitPlan, Department, Employee, Leave, Loan


class EmployeeForm(CompanyModelForm):
    class Meta:
        model = Employee
        fields = ["code", "name_en", "name_ar", "national_id", "insurance_no", "gender", "dob", "phone", "email",
                  "address", "department", "branch", "job_title_en", "job_title_ar", "grade", "hire_date", "end_date",
                  "status", "contract_type", "basic_salary", "allowances", "insurable_wage", "insured", "taxable",
                  "payment_method", "bank_name", "bank_account", "benefit", "medical_employee_share", "notes"]
        widgets = {"dob": DATE, "hire_date": DATE, "end_date": DATE, "notes": forms.Textarea(attrs={"rows": 2})}

    def clean_code(self):
        code = self.cleaned_data["code"].strip()
        if Employee.objects.filter(company=self.company, code=code).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_("Another employee already has this code."))
        return code


class DepartmentForm(CompanyModelForm):
    class Meta:
        model = Department
        fields = ["name_en", "name_ar", "cost_center"]


class BenefitPlanForm(CompanyModelForm):
    class Meta:
        model = BenefitPlan
        fields = ["name_en", "name_ar", "provider", "employer_cost", "employee_cost", "coverage", "is_active"]


class LoanForm(CompanyModelForm):
    paid_from = forms.ModelChoiceField(BankAccount.objects.none(), label=_("Paid out from"), required=False,
                                       help_text=_("Choose to post the advance to the ledger now (Dr employee advances, Cr bank or cash)."))

    class Meta:
        model = Loan
        fields = ["employee", "issue_date", "principal", "monthly_deduction", "reason"]
        widgets = {"issue_date": DATE}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["paid_from"].queryset = BankAccount.objects.filter(company=self.company, is_active=True)
        self.fields["employee"].queryset = Employee.objects.filter(company=self.company).exclude(status="left")

    def clean(self):
        data = super().clean()
        if data.get("principal") and data.get("monthly_deduction") and data["monthly_deduction"] > data["principal"]:
            self.add_error("monthly_deduction", _("The monthly deduction cannot be more than the loan."))
        return data


class LeaveForm(CompanyModelForm):
    class Meta:
        model = Leave
        fields = ["employee", "leave_type", "start_date", "end_date", "days", "paid_pct", "note"]
        widgets = {"start_date": DATE, "end_date": DATE}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["days"].required = False
        self.fields["days"].help_text = _("Leave empty to count calendar days from the dates.")

    def clean(self):
        data = super().clean()
        if data.get("start_date") and data.get("end_date") and data["end_date"] < data["start_date"]:
            self.add_error("end_date", _("The end date is before the start date."))
        if data.get("start_date") and data.get("end_date") and not data.get("days"):
            data["days"] = (data["end_date"] - data["start_date"]).days + 1
        return data


class ImportForm(forms.Form):
    workbook = forms.FileField(label=_("Payroll workbook (.xlsx)"),
                               help_text=_("Only the first sheet is read. Other sheets are ignored."))

    def clean_workbook(self):
        f = self.cleaned_data["workbook"]
        if not f.name.lower().endswith((".xlsx", ".xlsm")):
            raise forms.ValidationError(_("Choose an Excel .xlsx file."))
        if f.size > 10 * 1024 * 1024:
            raise forms.ValidationError(_("The file is larger than 10 MB."))
        return f


class AttendanceImportForm(forms.Form):
    file = forms.FileField(label=_("Attendance CSV"),
                           help_text=_("Columns: employee_code, date (YYYY-MM-DD), hours_worked — or time_in and time_out."))
