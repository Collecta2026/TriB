from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from core.models import AuditLog, client_ip
from users.permissions import require_perm

from . import services
from .forms import RuleForm
from .models import ApprovalAction, ApprovalRule, ApprovalStep


@require_perm("vouchers.approve")
def inbox(request):
    waiting = services.pending_for(request.user, request.company)
    recent = ApprovalAction.objects.filter(user=request.user, request__company=request.company).select_related(
        "request__voucher", "request__voucher__currency")[:20]
    return render(request, "approvals/inbox.html", {"waiting": waiting, "recent": recent})


@require_perm("setup.view")
def rules(request):
    form = RuleForm(request.POST or None, company=request.company)
    if request.method == "POST":
        if not request.membership.has_perm("setup.edit"):
            messages.error(request, _("You do not have permission to do that."))
            return redirect("approvals:rules")
        if form.is_valid():
            d = form.cleaned_data
            with transaction.atomic():
                rule = ApprovalRule.objects.create(company=request.company, doc_type=d["doc_type"], min_amount=d["min_amount"])
                order = 1
                for name in ("level1", "level2", "level3"):
                    if d.get(name):
                        ApprovalStep.objects.create(rule=rule, order=order, role=d[name])
                        order += 1
            AuditLog.record(request.company, request.user, "approval_rule.created", rule,
                            f"{rule.doc_type} ≥ {rule.min_amount}", ip=client_ip(request))
            messages.success(request, _("Approval rule added."))
            return redirect("approvals:rules")
    rows = ApprovalRule.objects.filter(company=request.company).prefetch_related("steps__role")
    return render(request, "approvals/rules.html", {"form": form, "rows": rows})


@require_POST
@require_perm("setup.edit")
def rule_toggle(request, pk):
    rule = get_object_or_404(ApprovalRule, pk=pk, company=request.company)
    rule.is_active = not rule.is_active
    rule.save(update_fields=["is_active"])
    AuditLog.record(request.company, request.user, "approval_rule.toggled", rule, f"active={rule.is_active}", ip=client_ip(request))
    messages.success(request, _("Rule switched on.") if rule.is_active else _("Rule switched off."))
    return redirect("approvals:rules")
