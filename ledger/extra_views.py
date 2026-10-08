"""VAT rates and projects (QuickBooks' Projects app: income and costs tracked per job)."""
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from core.forms_util import DATE, CompanyModelForm
from users.permissions import require_perm

from .models import JournalLine, Project, TaxRate

ZERO = Decimal("0")


class TaxRateForm(CompanyModelForm):
    class Meta:
        model = TaxRate
        fields = ["name_en", "name_ar", "rate", "kind", "is_default", "is_active"]


class ProjectForm(CompanyModelForm):
    class Meta:
        model = Project
        fields = ["code", "name_en", "name_ar", "customer", "status", "start_date", "end_date", "budget", "notes"]
        widgets = {"start_date": DATE, "end_date": DATE, "notes": forms.Textarea(attrs={"rows": 2})}

    def clean_code(self):
        code = self.cleaned_data["code"].strip().upper()
        if Project.objects.filter(company=self.company, code=code).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_("This code is already used."))
        return code


@require_perm("setup.view")
def tax_rates(request):
    obj = None
    pk = request.GET.get("edit") or request.POST.get("pk")
    if pk and str(pk).isdigit():
        obj = get_object_or_404(TaxRate, pk=pk, company=request.company)
    form = None
    if request.membership.has_perm("setup.edit"):
        form = TaxRateForm(request.POST or None, instance=obj or TaxRate(company=request.company), company=request.company)
        if request.method == "POST" and form.is_valid():
            rate = form.save(commit=False)
            rate.company = request.company
            rate.save()
            if rate.is_default:
                TaxRate.objects.filter(company=request.company).exclude(pk=rate.pk).update(is_default=False)
            messages.success(request, _("Saved."))
            return redirect("ledger:tax_rates")
    return render(request, "ledger/tax_rates.html", {
        "rows": TaxRate.objects.filter(company=request.company), "form": form, "obj": obj})


def _pl(project):
    rows = (JournalLine.objects.filter(project=project, account__type__in=("income", "expense"))
            .values("account__code", "account__name_en", "account__name_ar", "account__type")
            .annotate(d=Sum("debit"), c=Sum("credit")).order_by("account__code"))
    income, expense = [], []
    for r in rows:
        if r["account__type"] == "income":
            income.append((r, (r["c"] or ZERO) - (r["d"] or ZERO)))
        else:
            expense.append((r, (r["d"] or ZERO) - (r["c"] or ZERO)))
    ti, te = sum((v for _r, v in income), ZERO), sum((v for _r, v in expense), ZERO)
    return {"income": income, "expense": expense, "total_income": ti, "total_expense": te, "profit": ti - te}


@require_perm("projects.view")
def project_list(request):
    status = request.GET.get("status", "active")
    qs = Project.objects.filter(company=request.company).select_related("customer")
    if status:
        qs = qs.filter(status=status)
    rows = [(p, _pl(p)) for p in qs]
    return render(request, "ledger/projects.html", {"rows": rows, "status": status, "statuses": Project.STATUSES})


def _project_form(request, project):
    form = ProjectForm(request.POST or None, instance=project, company=request.company)
    if request.method == "POST" and form.is_valid():
        project = form.save(commit=False)
        project.company = request.company
        project.save()
        messages.success(request, _("Saved."))
        return redirect("projects:detail", pk=project.pk)
    return render(request, "ledger/project_form.html", {"form": form, "project": project})


@require_perm("projects.create")
def project_new(request):
    return _project_form(request, Project(company=request.company))


@require_perm("projects.edit")
def project_edit(request, pk):
    return _project_form(request, get_object_or_404(Project, pk=pk, company=request.company))


@require_perm("projects.view")
def project_detail(request, pk):
    project = get_object_or_404(Project, pk=pk, company=request.company)
    lines = (JournalLine.objects.filter(project=project).select_related("entry", "account")
             .order_by("-entry__date", "-id")[:100])
    return render(request, "ledger/project_detail.html", {"p": project, "pl": _pl(project), "lines": lines})
