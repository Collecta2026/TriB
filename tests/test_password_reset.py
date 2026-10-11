"""Password reset from the server environment (for hosts without a shell)."""
from io import StringIO

from django.core.management import call_command

NEW = "N3w-live-pass-2026!"


def run(monkeypatch, email, password):
    monkeypatch.setenv("TRIB_RESET_EMAIL", email)
    monkeypatch.setenv("TRIB_RESET_PASSWORD", password)
    out = StringIO()
    call_command("seed_reference", stdout=out)
    return out.getvalue()


def test_resets_owner_password(monkeypatch, company, owner, client):
    output = run(monkeypatch, "OWNER@scigate.test", NEW)
    assert "Password reset for owner@scigate.test" in output
    assert client.login(username="owner@scigate.test", password=NEW)


def test_unknown_email_lists_owner_emails(monkeypatch, company, owner):
    output = run(monkeypatch, "someone@else.test", NEW)
    assert "no user with the email" in output and "owner@scigate.test" in output


def test_weak_password_is_refused(monkeypatch, company, owner, client):
    output = run(monkeypatch, "owner@scigate.test", "123")
    assert "skipped" in output
    assert not client.login(username="owner@scigate.test", password="123")


def test_nothing_happens_without_variables(monkeypatch, company, owner):
    monkeypatch.delenv("TRIB_RESET_EMAIL", raising=False)
    monkeypatch.delenv("TRIB_RESET_PASSWORD", raising=False)
    out = StringIO()
    call_command("seed_reference", stdout=out)
    assert "Password reset" not in out.getvalue()
