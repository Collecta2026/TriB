import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
application = get_wsgi_application()

# Password reset from the server environment (TRIB_RESET_EMAIL / TRIB_RESET_PASSWORD) also runs when the app starts,
# so a plain restart is enough and the result shows in the live logs. Remove both variables after signing in.
if os.environ.get("TRIB_RESET_EMAIL") and os.environ.get("TRIB_RESET_PASSWORD"):
    try:
        from django.core.management import call_command

        call_command("reset_password_from_env")
    except Exception as exc:  # never stop the site from starting because of the reset
        print(f"Password reset failed: {exc}", flush=True)
