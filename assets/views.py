from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from core.models import AuditLog, client_ip
from ledger.services import PostingError, system_account
from users.permissions import require_perm

from . import services
from .forms import AssetCategoryForm, AssetCountForm, AssetForm, DepreciationForm, DisposeForm
from .models import Asset, AssetCategory, AssetCount, DepreciationRun

ZERO = Decimal("0")


# ---------- Register ----------
@require_perm("assets.view")
def asset_list(request):
    qs = Asset.objects.filter(company=request.company).select_related("category", "warehouse", "branch")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(number__icontains=q) | Q(name_en__icontains=q) | Q(name_ar__icontains=q) |
                       Q(serial_no__icontains=q) | Q(custodian__icontains=q))
    status = request.GET.get("status", "")
    qs = qs.filter(status=status) if status else qs.exclude(status="disposed")
    cat = request.GET.get("category", "")
    if cat.isdigit():
        qs = qs.filter(category_id=cat)
    assets = list(qs)
    page = Paginator(assets, 50).get_page(request.GET.get("page"))
    return render(request, "assets/list.html", {
        "page": page, "q": q, "status": status, "statuses": Asset.STATUSES,
        "categories": AssetCategory.objects.filter(company=request.company),
        "totals": {"cost": sum((a.cost for a in assets), ZERO), "book": sum((a.book_value for a in assets), ZERO)}})


def _asset_form(request, asset):
    form = AssetForm(request.POST or None, instance=asset, company=request.company)
    if request.method == "POST" and form.is_valid():
        asset = form.save(commit=False)
        asset.company = request.company
        if not asset.number:
            asset.number = services.next_asset_number(request.company)
        asset.save()
        AuditLog.record(request.company, request.user, "asset.saved", asset, asset.number, ip=client_ip(request))
        messages.success(request, _("Saved."))
        return redirect("assets:detail", pk=asset.pk)
    return render(request, "assets/form.html", {"form": form, "asset": asset,
                                                "has_categories": AssetCategory.objects.filter(company=request.company).exists()})


@require_perm("assets.create")
def asset_new(request):
    today = timezone.localdate()
    return _asset_form(request, Asset(company=request.company, purchase_date=today, in_service_date=today))


@require_perm("assets.edit")
def asset_edit(request, pk):
    asset = get_object_or_404(Asset, pk=pk, company=request.company)
    if asset.status == "disposed":
        messages.error(request, _("This asset is disposed and can no longer be changed."))
        return redirect("assets:detail", pk=pk)
    return _asset_form(request, asset)


@require_perm("assets.view")
def asset_detail(request, pk):
    asset = get_object_or_404(Asset, pk=pk, company=request.company)
    dispose_form = DisposeForm(company=request.company, initial={"date": timezone.localdate(), "proceeds": 0})
    return render(request, "assets/detail.html", {
        "asset": asset, "dispose_form": dispose_form,
        "lines": asset.depreciation_lines.select_related("run", "run__journal_entry").order_by("-run__period")})


@require_POST
@require_perm("assets.post")
def asset_dispose(request, pk):
    asset = get_object_or_404(Asset, pk=pk, company=request.company)
    form = DisposeForm(request.POST, company=request.company)
    if form.is_valid():
        d = form.cleaned_data
        try:
            services.dispose(asset, d["date"], d["proceeds"], d["bank_account"], request.user)
            messages.success(request, _("Asset disposed and posted to the ledger."))
        except services.AssetError as exc:
            messages.error(request, str(exc))
    else:
        messages.error(request, " ".join(e for errs in form.errors.values() for e in errs))
    return redirect("assets:detail", pk=pk)


# ---------- Categories ----------
@require_perm("assets.view")
def categories(request):
    company = request.company
    obj = None
    pk = request.GET.get("edit") or request.POST.get("pk")
    if pk and str(pk).isdigit():
        obj = get_object_or_404(AssetCategory, pk=pk, company=company)
    form = None
    if request.membership.has_perm("assets.edit" if obj else "assets.create"):
        if obj is None:
            obj_new = AssetCategory(company=company)
            try:
                obj_new.asset_account = system_account(company, "fixed_assets")
                obj_new.depreciation_account = system_account(company, "accum_depreciation")
                obj_new.expense_account = system_account(company, "depreciation")
            except PostingError:  # chart without the Release 2 roles: let the user pick
                pass
        form = AssetCategoryForm(request.POST or None, instance=obj or obj_new, company=company)
        if request.method == "POST" and form.is_valid():
            saved = form.save(commit=False)
            saved.company = company
            saved.save()
            messages.success(request, _("Saved."))
            return redirect("assets:categories")
    return render(request, "assets/categories.html", {
        "rows": AssetCategory.objects.filter(company=company).select_related(
            "asset_account", "depreciation_account", "expense_account"), "form": form, "obj": obj})


# ---------- Depreciation ----------
@require_perm("assets.view")
def depreciation(request):
    company = request.company
    today = timezone.localdate()
    last = DepreciationRun.objects.filter(company=company).first()
    if last:
        nxt = services.month_end(last.period)
        suggested = (nxt.replace(day=28) + timedelta(days=4)).replace(day=1)
    else:
        suggested = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    form = DepreciationForm(request.POST or (request.GET if "month" in request.GET else None), initial={"month": suggested})
    if request.method == "POST":
        if not request.membership.has_perm("assets.post"):
            messages.error(request, _("You do not have permission to do that."))
        elif form.is_valid():
            try:
                run = services.run_depreciation(company, form.cleaned_data["month"], request.user)
                messages.success(request, _("Depreciation for %(m)s posted.") % {"m": run.period.strftime("%m/%Y")})
                return redirect("assets:depreciation")
            except services.AssetError as exc:
                messages.error(request, str(exc))
    month = form.cleaned_data["month"].replace(day=1) if form.is_bound and form.is_valid() else suggested
    preview = [(a, services.charge_for(a, month)) for a in
               Asset.objects.filter(company=company).exclude(status="disposed").select_related("category")]
    preview = [(a, c) for a, c in preview if c > 0]
    runs = DepreciationRun.objects.filter(company=company).select_related("journal_entry")[:24]
    return render(request, "assets/depreciation.html", {
        "form": form, "month": month, "preview": preview, "preview_total": sum((c for _a, c in preview), ZERO),
        "runs": [(r, sum((l.amount for l in r.lines.all()), ZERO)) for r in runs]})


# ---------- Asset count ----------
@require_perm("assets.view")
def counts(request):
    form = AssetCountForm(request.POST or None, company=request.company, initial={"date": timezone.localdate()})
    if request.method == "POST":
        if not request.membership.has_perm("assets.create"):
            messages.error(request, _("You do not have permission to do that."))
        elif form.is_valid():
            d = form.cleaned_data
            count = services.start_count(request.company, d["date"], request.user, d["branch"], d["warehouse"])
            return redirect("assets:count", pk=count.pk)
    return render(request, "assets/counts.html", {
        "form": form, "rows": AssetCount.objects.filter(company=request.company).select_related("warehouse", "branch")[:50]})


@require_perm("assets.view")
def count(request, pk):
    count = get_object_or_404(AssetCount, pk=pk, company=request.company)
    if request.method == "POST" and count.status == "open" and request.membership.has_perm("assets.edit"):
        _line, message = services.scan(count, request.POST.get("code"))
        (messages.success if _line else messages.error)(request, message)
        return redirect(f"{request.path}#scan")
    lines = list(count.lines.select_related("asset", "asset__warehouse"))
    return render(request, "assets/count_detail.html", {
        "count": count, "found": [l for l in lines if l.found], "missing": [l for l in lines if not l.found]})


@require_POST
@require_perm("assets.post")
def count_close(request, pk):
    count = get_object_or_404(AssetCount, pk=pk, company=request.company)
    try:
        services.close_count(count, request.user, mark_missing=request.POST.get("mark_missing") == "1")
        messages.success(request, _("Asset count closed."))
    except services.AssetError as exc:
        messages.error(request, str(exc))
    return redirect("assets:count", pk=pk)


# ---------- Labels ----------
@require_perm("assets.view")
def labels(request):
    ids = [i for i in request.GET.getlist("asset") if i.isdigit()]
    if ids:
        return render(request, "assets/labels_print.html", {
            "assets": Asset.objects.filter(company=request.company, pk__in=ids)})
    qs = Asset.objects.filter(company=request.company).exclude(status="disposed").select_related("category", "warehouse")
    cat = request.GET.get("category", "")
    if cat.isdigit():
        qs = qs.filter(category_id=cat)
    return render(request, "assets/labels.html", {
        "assets": qs, "categories": AssetCategory.objects.filter(company=request.company)})
