"""The Settings (gear) menu pages added in Batch C, the bell's alerts and Help."""
from django import forms
from django.contrib import messages
from django.db.models import Count, Sum
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import NoReverseMatch, reverse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from reports.periods import COMPARE, PERIODS
from users.permissions import require_perm

from .models import Attachment, Bookmark, Company, Feedback, UserPreference
from .nav_views import _safe_path


# ---------- Bookmark icon in the menus ----------
@require_POST
@require_perm("dashboard.view")
def bookmark_toggle(request):
    url = _safe_path(request, request.POST.get("url"))
    if url is None:
        return JsonResponse({"error": "bad url"}, status=400)
    existing = Bookmark.objects.filter(user=request.user, company=request.company, url=url).first()
    if existing:
        existing.delete()
        return JsonResponse({"on": False})
    last = Bookmark.objects.filter(user=request.user, company=request.company).order_by("-position").first()
    Bookmark.objects.create(user=request.user, company=request.company, url=url,
                            title=(request.POST.get("title") or url).strip()[:120], position=(last.position + 1) if last else 0)
    return JsonResponse({"on": True})


# ---------- Bell: alerts ----------
@require_perm("dashboard.view")
def alerts(request):
    from dashboard.services import alerts as build_alerts

    cards = build_alerts(request.company, request.user, request.membership)
    template = "core/_alerts.html" if request.GET.get("partial") == "1" else "core/alerts.html"
    return render(request, template, {"cards": cards})


# ---------- Help ----------
SHORTCUTS = [
    ("Tab", gettext_lazy("Move to the next field or cell")),
    ("Enter", gettext_lazy("In a line grid: go to the next line, or add one")),
    ("Ctrl + Delete", gettext_lazy("In a line grid: remove the line")),
    ("↓ / ↑", gettext_lazy("In a product or account picker: move through the list")),
    ("Esc", gettext_lazy("Close a menu or picker")),
    ("/", gettext_lazy("Jump to the search box")),
]


@require_perm("dashboard.view")
def help_page(request):
    return render(request, "core/help.html", {"shortcuts": SHORTCUTS})


# ---------- Your company ----------
class ReportDefaultsForm(forms.Form):
    period = forms.ChoiceField(label=gettext_lazy("Default report period"),
                               choices=[p for p in PERIODS if p[0] != "custom"])
    compare = forms.ChoiceField(label=gettext_lazy("Compare with"), choices=COMPARE)


@require_perm("reports.view")
def report_settings(request):
    from reports.periods import DEFAULTS

    pref = UserPreference.for_user(request.user, request.company)
    form = ReportDefaultsForm(request.POST or None, initial={**DEFAULTS, **(pref.report_defaults or {})})
    if request.method == "POST" and form.is_valid():
        pref.report_defaults = {**(pref.report_defaults or {}), **form.cleaned_data}
        pref.save(update_fields=["report_defaults"])
        messages.success(request, _("Report settings saved. Reports now open with these choices."))
        return redirect("core:report_settings")
    return render(request, "core/simple_form.html", {
        "form": form, "title": _("Default report settings"),
        "intro": _("Choose the period every report opens with. You can still change it on each report."),
        "back": ("reports:index", _("Reports"))})


class AdditionalInfoForm(forms.Form):
    INDUSTRIES = [("", "—"), ("medical", gettext_lazy("Medical and dental supplies")), ("trading", gettext_lazy("Trading and distribution")),
                  ("manufacturing", gettext_lazy("Manufacturing")), ("services", gettext_lazy("Professional services")),
                  ("construction", gettext_lazy("Construction and contracting")), ("retail", gettext_lazy("Retail")),
                  ("logistics", gettext_lazy("Logistics and shipping")), ("technology", gettext_lazy("Technology")),
                  ("other", gettext_lazy("Other"))]
    TYPES = [("", "—"), ("sole", gettext_lazy("Sole proprietorship")), ("partnership", gettext_lazy("Partnership")),
             ("llc", gettext_lazy("Limited liability company (LLC)")), ("jsc", gettext_lazy("Joint stock company")),
             ("branch", gettext_lazy("Branch of a foreign company")), ("other", gettext_lazy("Other"))]
    SIZES = [("", "—"), ("1-10", "1–10"), ("11-50", "11–50"), ("51-200", "51–200"), ("201+", "201+")]
    CUSTOMERS = [("", "—"), ("b2b", gettext_lazy("Businesses")), ("b2c", gettext_lazy("Consumers")),
                 ("both", gettext_lazy("Businesses and consumers")), ("government", gettext_lazy("Government"))]

    legal_name = forms.CharField(label=gettext_lazy("Legal name (if different)"), max_length=200, required=False)
    industry = forms.ChoiceField(label=gettext_lazy("Industry"), choices=INDUSTRIES, required=False)
    business_type = forms.ChoiceField(label=gettext_lazy("Legal form"), choices=TYPES, required=False)
    employees = forms.ChoiceField(label=gettext_lazy("Number of employees"), choices=SIZES, required=False)
    customers = forms.ChoiceField(label=gettext_lazy("Who you sell to"), choices=CUSTOMERS, required=False)
    founded = forms.IntegerField(label=gettext_lazy("Year established"), min_value=1900, max_value=2100, required=False)
    website = forms.URLField(label=gettext_lazy("Website"), required=False, assume_scheme="https")
    activity = forms.CharField(label=gettext_lazy("Main activity"), max_length=300, required=False,
                               widget=forms.Textarea(attrs={"rows": 3}),
                               help_text=gettext_lazy("As written in your commercial register."))


@require_perm("setup.view")
def additional_info(request):
    company = request.company
    can_edit = request.membership.has_perm("setup.edit")
    form = AdditionalInfoForm(request.POST or None, initial=company.profile or {})
    if request.method == "POST" and can_edit and form.is_valid():
        company.profile = {k: v for k, v in form.cleaned_data.items() if v not in ("", None)}
        company.save(update_fields=["profile"])
        messages.success(request, _("Company information saved."))
        return redirect("core:additional_info")
    if not can_edit:
        for f in form.fields.values():
            f.disabled = True
    return render(request, "core/simple_form.html", {
        "form": form, "title": _("Additional info"), "can_save": can_edit,
        "intro": _("More about your business. It helps your accountant and fills in reports and letters."),
        "back": ("core:settings", _("Account and settings"))})


@require_perm("users.view")
def accountant(request):
    from users.models import Membership, Role

    role = Role.objects.filter(company=request.company, name_en__iexact="Accountant").first()
    members = (Membership.objects.filter(company=request.company, roles=role).select_related("user") if role else [])
    return render(request, "core/accountant.html", {"role": role, "members": members})


# ---------- Lists ----------
LISTS = [
    (gettext_lazy("Customers and sales"), [
        (gettext_lazy("Customers"), "contacts:customers", "contacts.view"),
        (gettext_lazy("Products & services"), "inventory:items", "inventory.view"),
        (gettext_lazy("Product categories"), "inventory:categories", "inventory.view"),
        (gettext_lazy("VAT rates"), "ledger:tax_rates", "setup.view"),
    ]),
    (gettext_lazy("Suppliers and purchases"), [
        (gettext_lazy("Suppliers"), "contacts:suppliers", "contacts.view"),
        (gettext_lazy("Warehouses"), "inventory:warehouses", "inventory.view"),
    ]),
    (gettext_lazy("Accounting"), [
        (gettext_lazy("Chart of accounts"), "ledger:accounts", "ledger.view"),
        (gettext_lazy("Cost centres"), "ledger:cost_centers", "ledger.view"),
        (gettext_lazy("Projects"), "projects:list", "projects.view"),
        (gettext_lazy("Recurring transactions"), "core:recurring", "vouchers.create"),
        (gettext_lazy("Bank rules"), "banking:rules", "banking.edit"),
    ]),
    (gettext_lazy("Banking"), [
        (gettext_lazy("Bank accounts"), "banking:accounts", "banking.view"),
        (gettext_lazy("Banks"), "banking:banks", "banking.view"),
    ]),
    (gettext_lazy("Team and assets"), [
        (gettext_lazy("Employees"), "team:employees", "team.view"),
        (gettext_lazy("Departments"), "team:departments", "team.view"),
        (gettext_lazy("Medical plans"), "team:benefits", "team.view"),
        (gettext_lazy("Asset categories"), "assets:categories", "assets.view"),
    ]),
    (gettext_lazy("Company"), [
        (gettext_lazy("Users & roles"), "users:users", "users.view"),
        (gettext_lazy("Approval rules"), "approvals:rules", "setup.view"),
        (gettext_lazy("Attachments"), "core:attachments", "vouchers.view"),
    ]),
]


@require_perm("dashboard.view")
def all_lists(request):
    groups = []
    for title, items in LISTS:
        rows = [(label, reverse(name)) for label, name, perm in items if request.membership.has_perm(perm)]
        if rows:
            groups.append((title, rows))
    return render(request, "core/lists.html", {"groups": groups})


def _target_url(target, target_id):
    if target == "core.receipt":
        return reverse("core:receipts")
    app, _sep, model = target.partition(".")
    for name in (f"{app}:{model}", f"{app}:detail"):
        try:
            return reverse(name, args=[target_id])
        except NoReverseMatch:
            continue
    return None


@require_perm("dashboard.view")
def attachments_list(request):
    from .attachments import MODULES

    allowed = [app for app, module in MODULES.items() if request.membership.has_perm(f"{module}.view")]
    qs = Attachment.objects.filter(company=request.company).defer("data").select_related("uploaded_by").order_by("-uploaded_at")
    qs = qs.filter(target__regex=r"^(%s)\." % "|".join(allowed)) if allowed else qs.none()
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(filename__icontains=q)
    totals = qs.aggregate(n=Count("id"), size=Sum("size"))
    from django.core.paginator import Paginator
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    rows = [(a, _target_url(a.target, a.target_id)) for a in page]
    return render(request, "core/attachments.html", {"page": page, "rows": rows, "q": q, "totals": totals})


# ---------- Profile ----------
@require_perm("dashboard.view")
def subscription(request):
    from django.conf import settings

    from users.models import Membership

    company = request.company
    addons = [(label, company.addon_enabled(key)) for key, label in Company.ADDONS]
    storage = Attachment.objects.filter(company=company).aggregate(n=Count("id"), size=Sum("size"))
    return render(request, "core/subscription.html", {
        "addons": addons, "users": Membership.objects.filter(company=company, is_active=True).count(),
        "storage": storage, "product": settings.TRIB_PRODUCT})


class FeedbackForm(forms.ModelForm):
    class Meta:
        model = Feedback
        fields = ["kind", "message"]
        widgets = {"kind": forms.RadioSelect, "message": forms.Textarea(attrs={"rows": 5})}


@require_perm("dashboard.view")
def feedback(request):
    form = FeedbackForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        fb = form.save(commit=False)
        fb.company, fb.user = request.company, request.user
        ref = _safe_path(request, (request.META.get("HTTP_REFERER") or "").split(request.get_host(), 1)[-1])
        fb.page = (ref or "")[:300]
        fb.save()
        messages.success(request, _("Thank you. Your feedback has been sent to the TriB team."))
        return redirect("core:feedback")
    mine = Feedback.objects.filter(company=request.company, user=request.user)[:10]
    everyone = Feedback.objects.filter(company=request.company).select_related("user")[:50] \
        if request.membership.has_perm("users.view") else None
    return render(request, "core/feedback.html", {"form": form, "mine": mine, "everyone": everyone})


@require_perm("dashboard.view")
def privacy(request):
    pref = UserPreference.for_user(request.user, request.company)
    if request.method == "POST":
        pref.privacy_choices = {**(pref.privacy_choices or {}), "blur": request.POST.get("blur") == "on"}
        pref.save(update_fields=["privacy_choices"])
        messages.success(request, _("Your privacy choices are saved."))
        return redirect("core:privacy")
    return render(request, "core/privacy.html", {"choices": pref.privacy_choices or {}})


@require_perm("dashboard.view")
def cookies(request):
    from django.conf import settings

    return render(request, "core/cookies.html", {"session_hours": settings.SESSION_COOKIE_AGE // 3600})
