from decimal import Decimal

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import Bilingual, Branch, Company

DOC_TYPES = [
    ("receipt", _("Receipt voucher")),
    ("payment", _("Payment voucher")),
    ("journal", _("Journal voucher")),
]


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email).lower()
        extra.setdefault("username", email)
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        return self.create_user(email, password, **extra)


class User(AbstractUser):
    """People sign in with their email address."""

    email = models.EmailField(_("Email"), unique=True)
    full_name = models.CharField(_("Full name"), max_length=150, blank=True)
    phone = models.CharField(_("Mobile"), max_length=40, blank=True)
    preferred_language = models.CharField(
        _("Language"), max_length=5, choices=[("en", "English"), ("ar", "العربية")], default="en"
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []
    objects = UserManager()

    def __str__(self):
        return self.full_name or self.email

    @property
    def initials(self):
        source = self.full_name or self.email
        parts = [p for p in source.replace("@", " ").split() if p]
        return "".join(p[0] for p in parts[:2]).upper()


class Role(Bilingual):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="roles")
    permissions = models.JSONField(default=list, blank=True)
    is_system = models.BooleanField(default=False)

    class Meta:
        ordering = ["name_en"]


class ApprovalLimit(models.Model):
    """The largest document (in base currency) a role may approve."""

    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="limits")
    doc_type = models.CharField(max_length=20, choices=DOC_TYPES)
    max_amount = models.DecimalField(max_digits=19, decimal_places=2)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["role", "doc_type"], name="uniq_limit_per_doc")]


class Membership(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="memberships")
    roles = models.ManyToManyField(Role, blank=True, related_name="members")
    branches = models.ManyToManyField(
        Branch, blank=True, related_name="+",
        help_text=_("Leave empty to allow every branch."),
    )
    is_owner = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "company"], name="uniq_membership")]

    def __str__(self):
        return f"{self.user} @ {self.company}"

    def permission_set(self):
        if not hasattr(self, "_perm_cache"):
            codes = set()
            for role in self.roles.all():
                codes.update(role.permissions or [])
            self._perm_cache = codes
        return self._perm_cache

    def has_perm(self, code):
        return self.is_active and (self.is_owner or code in self.permission_set())

    def approval_limit(self, doc_type):
        """None means no limit (owners); Decimal('0') means this person cannot approve."""
        if self.is_owner:
            return None
        limits = ApprovalLimit.objects.filter(role__in=self.roles.all(), doc_type=doc_type)
        return max((lim.max_amount for lim in limits), default=Decimal("0"))

    def allowed_branch_ids(self):
        ids = list(self.branches.values_list("id", flat=True))
        return ids or None
