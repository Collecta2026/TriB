"""The user manual switches between English and Arabic, and the publisher is AWS Pro."""
from django.urls import reverse

from users.models import User


def test_manual_switches_language_without_changing_the_users_setting(company, owner, client):
    client.force_login(owner)
    url = reverse("core:manual")
    en = client.get(url + "?lang=en").content.decode()
    assert 'dir="ltr"' in en and "Accounting &amp; ERP · by AWS Pro" in en and "Heliolink" not in en
    ar = client.get(url + "?lang=ar").content.decode()
    assert 'dir="rtl"' in ar and "من AWS Pro" in ar and 'aria-current="true">العربية' in ar
    assert User.objects.get(pk=owner.pk).preferred_language == owner.preferred_language
    assert "Back to TriB" in en and "location.replace" in en
    help_page = client.get(reverse("core:help")).content.decode()
    assert f'href="{url}" target="_blank"' in help_page          # opens in its own tab
    # Without ?lang the manual follows the reader's own language.
    assert client.get(url).status_code == 200
