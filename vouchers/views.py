from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from approvals import services as approvals
from core.models import client_ip
from users.models import DOC_TYPES
from users.permissions import require_perm

from . import services
from .forms import DecisionForm, LineFormSet, NewLineFormSet, VoucherForm
from .models import Voucher

KINDS = dict(DOC_TYPES)


def _voucher(request, pk):
    voucher = get_object_or_404(Voucher.objects.select_related("currency", "bank_account", "created_by", "company"),
                                pk=pk, company=request.company)
    allowed = request.membership.allowed_branch_ids()
    if allowed and voucher.branch_id and voucher.branch_id not in allowed:
        raise Http404
    return voucher


@require_perm("vouchers.view")
def voucher_list(request):
    vouchers = Voucher.objects.filter(company=request.company).select_related("currency", "created_by")
    allowed = request.membership.allowed_branch_ids()
    if allowed:
        vouchers = vouchers.filter(branch_id__in=allowed)
    kind, status = request.GET.get("kind", ""), request.GET.get("status", "")
    if kind in KINDS:
        vouchers = vouchers.filter(kind=kind)
    if status:
        vouchers = vouchers.filter(status=status)
    page = Paginator(vouchers.prefetch_related("lines"), 40).get_page(request.GET.get("page"))
    return render(request, "vouchers/list.html", {
        "page": page, "kind": kind, "status": status, "kinds": DOC_TYPES, "statuses": Voucher.STATUSES,
    })


@transaction.atomic
def _edit(request, voucher, kind):
    company = request.company
    form = VoucherForm(request.POST or None, instance=voucher, company=company, kind=kind)
    formset_class = LineFormSet if voucher.pk else NewLineFormSet
    formset = formset_class(request.POST or None, instance=voucher, company=company, kind=kind, prefix="lines")
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        voucher = form.save(commit=False)
        voucher.company, voucher.kind = company, kind
        voucher.rate = form.cleaned_data["rate"]
        if not voucher.pk:
            voucher.created_by = request.user
        voucher.save()
        formset.instance = voucher
        formset.save()
        if "submit" in request.POST:
            try:
                services.submit(voucher, request.user)
            except services.VoucherError as exc:
                messages.error(request, str(exc))
                return redirect("vouchers:edit", pk=voucher.pk)
            messages.success(request, _("%(n)s submitted.") % {"n": voucher.number})
        else:
            messages.success(request, _("Draft saved."))
        return redirect("vouchers:detail", pk=voucher.pk)
    return render(request, "vouchers/form.html", {
        "form": form, "formset": formset, "kind": kind, "kind_label": KINDS[kind], "voucher": voucher,
    })


@require_perm("vouchers.create")
def voucher_new(request, kind):
    if kind not in KINDS:
        raise Http404
    voucher = Voucher(company=request.company, kind=kind, date=timezone.localdate(), currency=request.company.base_currency)
    if request.method != "POST":
        cash = request.company.bank_accounts.filter(kind="cash", is_active=True).first()
        voucher.method = "cash" if kind != "journal" else ""
        voucher.bank_account = cash if kind != "journal" else None
    return _edit(request, voucher, kind)


@require_perm("vouchers.edit")
def voucher_edit(request, pk):
    voucher = _voucher(request, pk)
    if not voucher.editable:
        messages.error(request, _("This voucher can no longer be changed."))
        return redirect("vouchers:detail", pk=pk)
    return _edit(request, voucher, voucher.kind)


@require_perm("vouchers.view")
def voucher_detail(request, pk):
    voucher = _voucher(request, pk)
    req = voucher.current_request
    trail = []
    if req:
        for action in req.actions.select_related("user"):
            trail.append({"a": action, "valid": approvals.verify(action)})
    can_decide = req is not None and approvals.check_authority(req, request.user) is None
    return render(request, "vouchers/detail.html", {
        "v": voucher, "lines": voucher.lines.select_related("account", "cost_center"), "req": req, "trail": trail,
        "can_decide": can_decide, "decision_form": DecisionForm(),
        "step": req.current_step if req and req.status == "pending" else None,
    })


@require_POST
@require_perm("vouchers.view")
def voucher_action(request, pk):
    voucher = _voucher(request, pk)
    action = request.POST.get("action")
    perms = {"submit": "vouchers.create", "cancel": "vouchers.edit", "post": "vouchers.post",
             "approve": "vouchers.approve", "reject": "vouchers.approve"}
    if action not in perms or not request.membership.has_perm(perms[action]):
        messages.error(request, _("You do not have permission to do that."))
        return redirect("vouchers:detail", pk=pk)
    try:
        if action == "submit":
            services.submit(voucher, request.user)
            messages.success(request, _("%(n)s submitted.") % {"n": voucher.number})
        elif action == "cancel":
            services.cancel(voucher, request.user)
            messages.success(request, _("Voucher cancelled."))
        elif action == "post":
            entry = services.post_voucher(voucher, request.user)
            messages.success(request, _("Posted as %(n)s.") % {"n": entry.number})
        else:
            form = DecisionForm(request.POST)
            comment = form.cleaned_data["comment"] if form.is_valid() else ""
            if action == "reject" and not comment:
                messages.error(request, _("Write a comment so the creator knows what to fix."))
                return redirect("vouchers:detail", pk=pk)
            req = voucher.current_request
            if req is None:
                raise services.VoucherError(_("This document is not waiting for approval."))
            approvals.decide(req, request.user, action, comment, ip=client_ip(request))
            messages.success(request, _("Approved and e-signed.") if action == "approve" else _("Rejected and returned to the creator."))
    except (services.VoucherError, approvals.ApprovalError) as exc:
        messages.error(request, str(exc))
    return redirect("vouchers:detail", pk=pk)


@require_perm("vouchers.view")
def voucher_print(request, pk):
    voucher = _voucher(request, pk)
    if not voucher.number:
        messages.error(request, _("Submit the voucher before printing it."))
        return redirect("vouchers:detail", pk=pk)
    req = voucher.current_request
    signatures = list(req.actions.select_related("user").filter(decision="approve")) if req else []
    return render(request, "vouchers/print.html", {
        "v": voucher, "lines": voucher.lines.select_related("account", "cost_center"),
        "words_ar": voucher.words("ar"), "words_en": voucher.words("en"), "signatures": signatures,
    })
