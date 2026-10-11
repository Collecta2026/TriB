"""The TriB user manual: topics in English (help_en) and Arabic (help_ar), a tiny markup renderer, and "Help for
this page" (the topic whose page prefix best matches the current URL)."""
import re

from django.utils.html import escape
from django.utils.safestring import mark_safe

from . import help_ar, help_en
from .models import is_arabic

BOLD = re.compile(r"\*\*(.+?)\*\*")


def _inline(text):
    return BOLD.sub(r"<b>\1</b>", escape(text))


def render(body):
    """Paragraphs, "- " bullets, "1. " steps, "Tip:" / "Note:" boxes (and their Arabic forms)."""
    out, block = [], []
    kind = None

    def flush():
        nonlocal block, kind
        if block:
            tag = "ul" if kind == "ul" else "ol"
            out.append(f"<{tag}>" + "".join(f"<li>{_inline(x)}</li>" for x in block) + f"</{tag}>")
        block, kind = [], None

    for raw in body.strip().splitlines():
        line = raw.strip()
        if not line:
            flush()
            continue
        m = re.match(r"^(\d+)\.\s+(.*)$", line)
        if line.startswith("- "):
            if kind != "ul":
                flush()
                kind = "ul"
            block.append(line[2:])
        elif m:
            if kind != "ol":
                flush()
                kind = "ol"
            block.append(m.group(2))
        else:
            flush()
            for prefix, cls in (("Tip:", "tip"), ("نصيحة:", "tip"), ("Note:", "note"), ("ملاحظة:", "note")):
                if line.startswith(prefix):
                    out.append(f'<p class="hbox {cls}"><b>{escape(prefix)}</b>{_inline(line[len(prefix):])}</p>')
                    break
            else:
                out.append(f"<p>{_inline(line)}</p>")
    flush()
    return mark_safe("".join(out))


def topics(arabic=None):
    """[{key, section, section_title, title, pages, html, text}] in manual order, in the current language."""
    arabic = is_arabic() if arabic is None else arabic
    sections = dict(help_en.SECTIONS)
    out = []
    for key, section, title, pages, body in help_en.TOPICS:
        if arabic and key in help_ar.TOPICS:
            title, body = help_ar.TOPICS[key]
        out.append({"key": key, "section": section, "pages": pages, "title": title, "html": render(body),
                    "section_title": help_ar.SECTIONS.get(section) if arabic else sections[section],
                    "text": re.sub(r"\s+", " ", BOLD.sub(r"\1", body)).strip().lower()})
    return out


def sections(arabic=None):
    grouped = {}
    for t in topics(arabic):
        grouped.setdefault((t["section"], t["section_title"]), []).append(t)
    return [{"key": k, "title": title, "topics": items} for (k, title), items in grouped.items()]


def for_path(path):
    """The topic that explains the page at `path` (longest matching prefix), or None."""
    best, length = None, 0
    for key, _section, title, pages, _body in help_en.TOPICS:
        for prefix in pages:
            if (path == prefix or (prefix != "/" and path.startswith(prefix))) and len(prefix) > length:
                best, length = key, len(prefix)
    if best is None:
        return None
    t = next(t for t in topics() if t["key"] == best)
    return {"key": best, "title": t["title"]}
