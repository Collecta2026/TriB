"""The start-up access recovery in config/wsgi.py (for hosts without a shell). Runs on the test database only."""
from users.models import Membership, User

NEW = "N3w-live-pass-2026!"


def run(monkeypatch, email, password):
    from config.wsgi import reset_password_from_env
    monkeypatch.setenv("TRIB_RESET_EMAIL", email)
    monkeypatch.setenv("TRIB_RESET_PASSWORD", password)
    reset_password_from_env()


def test_creates_a_new_owner(monkeypatch, company, owner, client, capsys):
    run(monkeypatch, "Zak@iCloud.test", NEW)
    assert "New owner created: zak@icloud.test" in capsys.readouterr().out
    m = Membership.objects.get(user__email="zak@icloud.test", company=company)
    assert m.is_owner and m.roles.filter(name_en="Administrator").exists()
    assert client.login(username="zak@icloud.test", password=NEW)
    assert client.get("/").status_code == 200  # straight into the dashboard
    assert client.login(username="owner@scigate.test", password="Str0ng-test-pass!")  # old owner untouched


def test_resets_an_existing_user(monkeypatch, company, owner, client, capsys):
    run(monkeypatch, "owner@scigate.test", NEW)
    assert "Password reset: owner@scigate.test" in capsys.readouterr().out
    assert User.objects.count() == 1
    assert client.login(username="owner@scigate.test", password=NEW)


def test_weak_password_creates_nothing(monkeypatch, company, owner, capsys):
    run(monkeypatch, "zak@icloud.test", "123")
    assert "skipped" in capsys.readouterr().out
    assert not User.objects.filter(email="zak@icloud.test").exists()


def test_does_nothing_without_variables(monkeypatch, company, owner, capsys):
    from config.wsgi import reset_password_from_env
    monkeypatch.delenv("TRIB_RESET_EMAIL", raising=False)
    monkeypatch.delenv("TRIB_RESET_PASSWORD", raising=False)
    reset_password_from_env()
    assert capsys.readouterr().out == ""
