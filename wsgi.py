import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
application = get_wsgi_application()


def reset_password_from_env():
    """Set a user's password from TRIB_RESET_EMAIL / TRIB_RESET_PASSWORD when the app starts (for hosts without a
    shell). Self-contained so it works from this one file; the result is printed to the live logs.
    Remove both variables after signing in."""
    email = os.environ.get("TRIB_RESET_EMAIL", "").strip()
    password = os.environ.get("TRIB_RESET_PASSWORD", "")
    if not email or not password:
        return
    from django.contrib.auth import get_user_model
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError

    from users.models import Membership

    user = get_user_model().objects.filter(email__iexact=email).first()
    if user is None:
        owners = sorted({m.user.email for m in Membership.objects.filter(is_owner=True).select_related("user")})
        print(f"Password reset skipped: no user with the email {email}. Owner sign-in email(s) in this database: "
              f"{', '.join(owners) or 'none (open the site to set up)'}", flush=True)
        return
    try:
        validate_password(password, user)
    except ValidationError as exc:
        print("Password reset skipped: " + " ".join(exc.messages), flush=True)
        return
    user.set_password(password)
    user.is_active = True
    user.save(update_fields=["password", "is_active"])
    Membership.objects.filter(user=user).update(is_active=True)
    print(f"Password reset for {user.email}. Sign in, then remove TRIB_RESET_EMAIL and TRIB_RESET_PASSWORD.", flush=True)


try:
    reset_password_from_env()
except Exception as exc:  # never stop the site from starting because of the reset
    print(f"Password reset failed: {exc}", flush=True)
