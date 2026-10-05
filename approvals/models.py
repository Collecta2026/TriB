from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import Company
from users.models import DOC_TYPES, Role


class ApprovalRule(models.Model):
    """Documents of `doc_type` worth at least `min_amount` (base currency) need the rule's steps.

    When several rules match, the one with the highest minimum applies.
    """

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="approval_rules")
    doc_type = models.CharField(_("Document type"), max_length=20, choices=DOC_TYPES)
    min_amount = models.DecimalField(_("From amount"), max_digits=19, decimal_places=2, default=0)
    is_active = models.BooleanField(_("Active"), default=True)

    class Meta:
        ordering = ["doc_type", "min_amount"]


class ApprovalStep(models.Model):
    rule = models.ForeignKey(ApprovalRule, on_delete=models.CASCADE, related_name="steps")
    order = models.PositiveSmallIntegerField(_("Level"))
    role = models.ForeignKey(Role, on_delete=models.PROTECT, verbose_name=_("Approver role"))

    class Meta:
        ordering = ["order"]
        constraints = [models.UniqueConstraint(fields=["rule", "order"], name="uniq_step_order")]


class ApprovalRequest(models.Model):
    STATUSES = [("pending", _("Pending")), ("approved", _("Approved")), ("rejected", _("Rejected"))]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="+")
    voucher = models.ForeignKey("vouchers.Voucher", on_delete=models.CASCADE, related_name="approval_requests")
    rule = models.ForeignKey(ApprovalRule, on_delete=models.PROTECT)
    current_order = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=10, choices=STATUSES, default="pending", db_index=True)
    amount_base = models.DecimalField(max_digits=19, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def current_step(self):
        return self.rule.steps.filter(order=self.current_order).select_related("role").first()

    @property
    def total_steps(self):
        return self.rule.steps.count()


class ApprovalAction(models.Model):
    DECISIONS = [("approve", _("Approved")), ("reject", _("Rejected"))]

    request = models.ForeignKey(ApprovalRequest, on_delete=models.CASCADE, related_name="actions")
    order = models.PositiveSmallIntegerField()
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    decision = models.CharField(max_length=10, choices=DECISIONS)
    comment = models.CharField(_("Comment"), max_length=300, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    signed_at = models.DateTimeField()
    signature = models.CharField(max_length=64)

    class Meta:
        ordering = ["order", "signed_at"]
