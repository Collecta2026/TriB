"""Build locale/ar/LC_MESSAGES/django.po and .mo from core/translations_ar.py.

Django's own compilemessages needs GNU gettext, which Windows and Render do not always have.
This command only needs polib, so it runs the same everywhere.
"""
from pathlib import Path

import polib
from django.conf import settings
from django.core.management.base import BaseCommand

from core.translations_ar import AR


class Command(BaseCommand):
    help = "Write the Arabic translation catalogue (.po and .mo)."

    def handle(self, *args, **options):
        out = Path(settings.BASE_DIR) / "locale" / "ar" / "LC_MESSAGES"
        out.mkdir(parents=True, exist_ok=True)
        po = polib.POFile()
        po.metadata = {
            "Project-Id-Version": "TriB",
            "Language": "ar",
            "MIME-Version": "1.0",
            "Content-Type": "text/plain; charset=utf-8",
            "Content-Transfer-Encoding": "8bit",
            "Plural-Forms": "nplurals=6; plural=n==0 ? 0 : n==1 ? 1 : n==2 ? 2 : n%100>=3 && n%100<=10 ? 3 : n%100>=11 && n%100<=99 ? 4 : 5;",
        }
        for msgid, msgstr in AR.items():
            if "{% plural %}" in msgid:
                # {% blocktranslate count %}: one Arabic text serves every plural form (it reads "n items").
                singular, plural = msgid.split("{% plural %}")
                po.append(polib.POEntry(msgid=singular, msgid_plural=plural,
                                        msgstr_plural={i: msgstr for i in range(6)}))
            else:
                po.append(polib.POEntry(msgid=msgid, msgstr=msgstr))
        po.save(str(out / "django.po"))
        po.save_as_mofile(str(out / "django.mo"))
        self.stdout.write(self.style.SUCCESS(f"Wrote {len(AR)} Arabic strings to {out}"))
