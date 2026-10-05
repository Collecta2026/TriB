"""Every string marked for translation has an Arabic version."""
import re
from pathlib import Path

from core.translations_ar import AR

ROOT = Path(__file__).resolve().parent.parent
APPS = ["core", "users", "ledger", "banking", "approvals", "vouchers", "reports", "dashboard", "templates", "config"]

TRANSLATE = re.compile(r"""{%\s*translate\s+(["'])(.+?)\1""")
UNDERSCORE = re.compile(r"""(?<![\w.])_\(\s*(["'])((?:\\.|(?!\1).)+)\1\s*[,)%]""")
BLOCK = re.compile(r"{%\s*blocktranslate[^%]*%}(.*?){%\s*endblocktranslate\s*%}", re.S)


def collect():
    found = set()
    for app in APPS:
        for path in (ROOT / app).rglob("*"):
            if path.suffix not in (".py", ".html") or "migrations" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            if path.suffix == ".html":
                found.update(m.group(2) for m in TRANSLATE.finditer(text))
                for m in BLOCK.finditer(text):
                    found.add(re.sub(r"{{\s*(\w+)\s*}}", r"%(\1)s", m.group(1)))
            found.update(m.group(2).replace("\\'", "'").replace('\\"', '"') for m in UNDERSCORE.finditer(text))
    return found


def test_every_string_has_arabic():
    missing = sorted(s for s in collect() if s not in AR)
    assert not missing, "Missing Arabic for:\n" + "\n".join(missing)
