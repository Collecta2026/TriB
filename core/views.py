from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from users.models import Membership, User
from users.permissions import require_perm

from .forms import AddonsForm, BranchForm, CompanyForm, CurrenciesForm, RateForm, SetupForm
from .models import AuditLog, Company, ExchangeRate, client_ip
from .services import bootstrap_company


def first_run(request):
    """Create the first company and its owner. Only available while no company exists."""
    if Company.objects.exists():
        return redirect("dashboard:home")
    form = SetupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        user = User.objects.create_user(
            d["email"], d["password1"], full_name=d["full_name"],
            preferred_language="ar" if request.LANGUAGE_CODE == "ar" else "en",
        )
        bootstrap_company(name_en=d["company_name_en"], name_ar=d["company_name_ar"],
                          base_currency=d["base_currency"], owner=user)
        login(request, user, backend="users.backends.EmailBackend")
        messages.success(request, _(
            "Your company is ready. Approval rules are switched on, so documents you create need a second person "
            "to approve them. Add a Finance manager in Users & roles, or switch the rule off in Settings while you test."
        ))
        return redirect("dashboard:home")
    return render(request, "core/setup.html", {"form": form})


@login_required
def no_company(request):
    if request.membership is not None:
        return redirect("dashboard:home")
    return render(request, "core/no_company.html")


@require_POST
def switch_language(request):
    lang = request.POST.get("language", "en")
    if lang not in dict(settings.LANGUAGES):
        lang = "en"
    target = request.POST.get("next") or "/"
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        target = "/"
    response = HttpResponseRedirect(target)
    response.set_cookie(settings.LANGUAGE_COOKIE_NAME, lang, max_age=365 * 24 * 3600, samesite="Lax")
    if request.user.is_authenticated and request.user.preferred_language != lang:
        request.user.preferred_language = lang
        request.user.save(update_fields=["preferred_language"])
    return response


@login_required
@require_POST
def switch_company(request):
    company_id = request.POST.get("company")
    if Membership.objects.filter(user=request.user, company_id=company_id, is_active=True).exists():
        request.session["company_id"] = int(company_id)
    return redirect("dashboard:home")


@require_perm("dashboard.view")
def apps(request):
    return render(request, "core/apps.html")


@require_perm("dashboard.view")
def search(request):
    from banking.models import Cheque
    from ledger.models import Account
    from vouchers.models import Voucher

    q = request.GET.get("q", "").strip()
    results = {"vouchers": [], "accounts": [], "cheques": []}
    if q:
        company = request.company
        if request.membership.has_perm("vouchers.view"):
            results["vouchers"] = Voucher.objects.filter(company=company).filter(
                Q(number__icontains=q) | Q(party_name__icontains=q) | Q(description__icontains=q)
            ).select_related("currency")[:25]
        if request.membership.has_perm("ledger.view"):
            results["accounts"] = Account.objects.filter(company=company).filter(
                Q(code__startswith=q) | Q(name_en__icontains=q) | Q(name_ar__icontains=q)
            )[:25]
        if request.membership.has_perm("cheques.view"):
            results["cheques"] = Cheque.objects.filter(company=company).filter(
                Q(number__icontains=q) | Q(party_name__icontains=q)
            ).select_related("currency")[:25]
    return render(request, "core/search.html", {"q": q, "results": results})


@require_perm("setup.view")
def company_settings(request):
    company = request.company
    can_edit = request.membership.has_perm("setup.edit")
    action = request.POST.get("action") if request.method == "POST" else None
    if action and not can_edit:
        messages.error(request, _("You do not have permission to change settings."))
        return redirect("core:settings")

    company_form = CompanyForm(request.POST if action == "company" else None, instance=company, prefix="co")
    currencies_form = CurrenciesForm(request.POST if action == "currencies" else None, prefix="cur",
                                     initial={"currencies": company.currencies.all()})
    addons_form = AddonsForm(request.POST if action == "addons" else None, company=company, prefix="add")
    branch_form = BranchForm(request.POST if action == "branch" else None, prefix="br")
    rate_form = RateForm(request.POST if action == "rate" else None, company=company, prefix="rate")

    if action == "company" and company_form.is_valid():
        company_form.save()
        AuditLog.record(company, request.user, "settings.company", company, _("Company details updated"), ip=client_ip(request))
        messages.success(request, _("Company details saved."))
        return redirect("core:settings")
    if action == "currencies" and currencies_form.is_valid():
        chosen = set(currencies_form.cleaned_data["currencies"].values_list("code", flat=True)) | {company.base_currency_id}
        company.currencies.set(chosen)
        AuditLog.record(company, request.user, "settings.currencies", company, ", ".join(sorted(chosen)), ip=client_ip(request))
        messages.success(request, _("Currencies saved."))
        return redirect("core:settings")
    if action == "addons" and addons_form.is_valid():
        company.addons = {key: bool(addons_form.cleaned_data.get(key)) for key, _label in Company.ADDONS}
        company.save(update_fields=["addons"])
        AuditLog.record(company, request.user, "settings.addons", company, str(company.addons), ip=client_ip(request))
        messages.success(request, _("Add-ons saved."))
        return redirect("core:settings")
    if action == "branch" and branch_form.is_valid():
        branch = branch_form.save(commit=False)
        branch.company = company
        branch.save()
        messages.success(request, _("Branch added."))
        return redirect("core:settings")
    if action == "rate" and rate_form.is_valid():
        ExchangeRate.objects.update_or_create(
            company=company, currency=rate_form.cleaned_data["currency"], date=rate_form.cleaned_data["date"],
            defaults={"rate": rate_form.cleaned_data["rate"]},
        )
        AuditLog.record(company, request.user, "settings.rate", company,
                        f"{rate_form.cleaned_data['currency'].code} {rate_form.cleaned_data['rate']}", ip=client_ip(request))
        messages.success(request, _("Exchange rate saved."))
        return redirect("core:settings")

    return render(request, "core/settings.html", {
        "company_form": company_form, "currencies_form": currencies_form, "addons_form": addons_form,
        "branch_form": branch_form, "rate_form": rate_form, "can_edit": can_edit,
        "branches": company.branches.all(), "rates": ExchangeRate.objects.filter(company=company).select_related("currency")[:30],
    })


@require_perm("audit.view")
def audit_log(request):
    rows = AuditLog.objects.filter(company=request.company).select_related("user")
    q = request.GET.get("q", "").strip()
    if q:
        rows = rows.filter(Q(summary__icontains=q) | Q(action__icontains=q) | Q(user__email__icontains=q))
    return render(request, "core/audit.html", {"rows": rows[:300], "q": q})
