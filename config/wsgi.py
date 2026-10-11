import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
application = get_wsgi_application()


def reset_password_from_env():
    """Regain access on a host without a shell, from TRIB_RESET_EMAIL and TRIB_RESET_PASSWORD, when the app starts.

    - The email belongs to a user: their password is set and the account re-enabled.
    - No user has that email and the database has one company: a new owner (Administrator role) is created.
    The result is printed to the live logs. Remove both variables after signing in.
    """
    email = os.environ.get("TRIB_RESET_EMAIL", "").strip().lower()
    password = os.environ.get("TRIB_RESET_PASSWORD", "")
    if not email and not password:
        return
    if not email or not password:
        print("Password reset skipped: set both TRIB_RESET_EMAIL and TRIB_RESET_PASSWORD.", flush=True)
        return
    from django.contrib.auth import get_user_model
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError
    from django.db import transaction

    from core.models import AuditLog, Company
    from users.models import Membership, Role

    User = get_user_model()
    user = User.objects.filter(email__iexact=email).first()
    companies = list(Company.objects.all()[:2])
    if user is None and len(companies) != 1:
        print("Password reset skipped: no user has this email, and a new owner can only be added when the database "
              f"has exactly one company (it has {Company.objects.count()}).", flush=True)
        return
    try:
        validate_password(password, user or User(email=email))
    except ValidationError as exc:
        print("Password reset skipped: " + " ".join(exc.messages), flush=True)
        return

    with transaction.atomic():
        created = user is None
        if created:
            user = User.objects.create_user(email, password)
        else:
            user.set_password(password)
            user.is_active = True
            user.save(update_fields=["password", "is_active"])
            Membership.objects.filter(user=user).update(is_active=True)
        for company in companies if len(companies) == 1 else []:
            membership, new = Membership.objects.get_or_create(user=user, company=company,
                                                               defaults={"is_owner": True})
            if new:
                admin = Role.objects.filter(company=company, name_en="Administrator").first()
                if admin:
                    membership.roles.add(admin)
            AuditLog.record(company, None, "user.created" if created else "user.password_reset", user,
                            "Set from the server environment")
    action = "New owner created" if created else "Password reset"
    print(f"{action}: {user.email}. Sign in with this email, then remove TRIB_RESET_EMAIL and TRIB_RESET_PASSWORD.",
          flush=True)


try:
    reset_password_from_env()
except Exception as exc:  # never stop the site from starting because of the reset
    print(f"Password reset failed: {exc}", flush=True)
