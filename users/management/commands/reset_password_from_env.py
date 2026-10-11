"""Reset a user's password on a server without a shell (e.g. Render's free plan).

In Render → Environment, add TRIB_RESET_EMAIL and TRIB_RESET_PASSWORD, then deploy. The deploy log says whether it
worked (or lists the owner sign-in emails if that email isn't found). Remove both variables after signing in.
Runs at the end of `seed_reference`, so the build command doesn't change. Does nothing when the variables are unset.
"""
import os

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand

from core.models import AuditLog
from users.models import Membership, User


class Command(BaseCommand):
    help = "Set a user's password from TRIB_RESET_EMAIL / TRIB_RESET_PASSWORD (only when both are set)."

    def handle(self, *args, **options):
        email = os.environ.get("TRIB_RESET_EMAIL", "").strip()
        password = os.environ.get("TRIB_RESET_PASSWORD", "")
        if not email and not password:
            return
        if not email or not password:
            self.stdout.write(self.style.WARNING("Password reset skipped: set both TRIB_RESET_EMAIL and TRIB_RESET_PASSWORD."))
            return
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            owners = sorted({m.user.email for m in Membership.objects.filter(is_owner=True).select_related("user")})
            self.stdout.write(self.style.WARNING(
                f"Password reset skipped: no user with the email {email}. "
                f"Owner sign-in email(s) in this database: {', '.join(owners) or 'none (open the site to set up)'}"))
            return
        try:
            validate_password(password, user)
        except ValidationError as exc:
            self.stdout.write(self.style.WARNING("Password reset skipped: " + " ".join(exc.messages)))
            return
        user.set_password(password)
        user.is_active = True
        user.save(update_fields=["password", "is_active"])
        Membership.objects.filter(user=user).update(is_active=True)
        for m in Membership.objects.filter(user=user).select_related("company"):
            AuditLog.record(m.company, None, "user.password_reset", user, "Reset from server environment")
        self.stdout.write(self.style.SUCCESS(
            f"Password reset for {user.email}. Sign in, then remove TRIB_RESET_EMAIL and TRIB_RESET_PASSWORD."))
