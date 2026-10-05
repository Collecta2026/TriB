"""Electronic authorisation: approval routing, authority checks and tamper-evident e-signatures."""
import hashlib
import hmac

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from core.models import AuditLog
from users.models import Membership

from .models import ApprovalAction, ApprovalRequest, ApprovalRule


class ApprovalError(Exception):
    pass


def find_rule(company, doc_type, amount_base):
    return (
        ApprovalRule.objects.filter(company=company, doc_type=doc_type, is_active=True, min_amount__lte=amount_base)
        .filter(steps__isnull=False).distinct().order_by("-min_amount").first()
    )


def document_fingerprint(voucher):
    """Everything an approver signs. Any later change to these values breaks the signature."""
    lines = ";".join(
        f"{l.account.code}:{l.amount}:{l.debit}:{l.credit}" for l in voucher.lines.select_related("account").order_by("id")
    )
    return "|".join([
        str(voucher.company_id), voucher.kind, voucher.number, voucher.date.isoformat(), voucher.currency_id,
        str(voucher.rate), voucher.party_name, str(voucher.total), lines,
    ])


def sign(voucher, user_id, decision, signed_at):
    payload = f"{document_fingerprint(voucher)}|{user_id}|{decision}|{signed_at.isoformat()}"
    return hmac.new(settings.SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()


def verify(action):
    expected = sign(action.request.voucher, action.user_id, action.decision, action.signed_at)
    return hmac.compare_digest(expected, action.signature)


def start(voucher, user):
    """Route a submitted voucher. Returns the ApprovalRequest, or None when no approval is needed."""
    rule = find_rule(voucher.company, voucher.kind, voucher.amount_base)
    if rule is None:
        return None
    first = rule.steps.order_by("order").first()
    request = ApprovalRequest.objects.create(
        company=voucher.company, voucher=voucher, rule=rule, current_order=first.order, amount_base=voucher.amount_base,
    )
    AuditLog.record(voucher.company, user, "approval.requested", voucher, voucher.number)
    return request


def check_authority(request, user):
    """Return None if `user` may act on the current step, otherwise the reason they may not."""
    voucher = request.voucher
    if request.status != "pending":
        return _("This document is no longer waiting for approval.")
    membership = Membership.objects.filter(user=user, company=request.company, is_active=True).first()
    if membership is None or not membership.has_perm("vouchers.approve"):
        return _("You do not have permission to approve documents.")
    step = request.current_step
    if not membership.is_owner and not membership.roles.filter(pk=step.role_id).exists():
        return _("This step must be approved by: %(role)s") % {"role": step.role.name}
    if request.company.enforce_sod and voucher.created_by_id == user.id:
        return _("You created this document, so someone else must approve it.")
    if request.actions.filter(user=user, decision="approve").exists():
        return _("You have already approved an earlier step of this document.")
    limit = membership.approval_limit(voucher.kind)
    if limit is not None and request.amount_base > limit:
        return _("This amount is above your approval limit.")
    return None


@transaction.atomic
def decide(request, user, decision, comment="", ip=None):
    request = ApprovalRequest.objects.select_for_update().get(pk=request.pk)
    reason = check_authority(request, user)
    if reason:
        raise ApprovalError(reason)
    voucher = request.voucher
    now = timezone.now()
    ApprovalAction.objects.create(
        request=request, order=request.current_order, user=user, decision=decision, comment=comment[:300], ip=ip,
        signed_at=now, signature=sign(voucher, user.id, decision, now),
    )
    if decision == "reject":
        request.status = "rejected"
        request.save(update_fields=["status"])
        voucher.status = "rejected"
        voucher.save(update_fields=["status"])
        AuditLog.record(voucher.company, user, "approval.rejected", voucher, f"{voucher.number}: {comment}", ip=ip)
        return request

    next_step = request.rule.steps.filter(order__gt=request.current_order).order_by("order").first()
    if next_step:
        request.current_order = next_step.order
        request.save(update_fields=["current_order"])
        AuditLog.record(voucher.company, user, "approval.step_approved", voucher, voucher.number, ip=ip)
        return request

    request.status = "approved"
    request.save(update_fields=["status"])
    voucher.status = "approved"
    voucher.save(update_fields=["status"])
    AuditLog.record(voucher.company, user, "approval.approved", voucher, voucher.number, ip=ip)
    if voucher.company.auto_post_on_approval:
        from vouchers.services import post_voucher

        post_voucher(voucher, user)
    return request


def pending_for(user, company):
    """Requests in `company` that `user` can act on right now."""
    candidates = ApprovalRequest.objects.filter(company=company, status="pending").select_related(
        "voucher", "voucher__currency", "voucher__created_by", "rule"
    )
    return [r for r in candidates if check_authority(r, user) is None]
