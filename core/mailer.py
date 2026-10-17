"""Emailing pages TriB prints that are not stored documents: remittance advices and statements. The email carries
the document itself, laid out for email programs, so the reader needs no link or login."""
from django.conf import settings
from django.contrib import messages
from django.core.mail import EmailMultiAlternatives
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from .doc_actions import SendForm, email_ready
from .models import AuditLog, client_ip


def bilingual(company):
    """Documents print in Arabic and English, except in countries whose pack prints in English only (the UK)."""
    pack = getattr(company, "pack", None)
    return pack is None or getattr(pack, "bilingual_print", True)


def amount_in_words_on(company):
    pack = getattr(company, "pack", None)
    return pack is None or getattr(pack, "amount_in_words", True)


def review_and_send(request, *, initial, build, title, back_url, crumbs, audit_action, audit_obj, summary, note):
    """The Review and send screen: To / Cc / Bcc / Subject / Message on the left, the email itself on the right.

    build(message) → (html, text): the email for that message. On a successful send, back to back_url."""
    form = SendForm(request.POST or None, initial=initial)
    ready = email_ready()
    if request.method == "POST" and ready and form.is_valid():
        d = form.cleaned_data
        html, text = build(d["message"])
        company = request.company
        mail = EmailMultiAlternatives(d["subject"], text, settings.DEFAULT_FROM_EMAIL, d["to"], cc=d["cc"], bcc=d["bcc"],
                                      reply_to=[company.email] if company.email else None)
        mail.attach_alternative(html, "text/html")
        try:
            mail.send()
        except Exception as exc:  # SMTP problems are shown, not raised
            messages.error(request, _("The email could not be sent: %(e)s") % {"e": exc})
            return redirect(request.get_full_path())
        AuditLog.record(company, request.user, audit_action, audit_obj, f"{summary} → {', '.join(d['to'])}",
                        {"cc": d["cc"], "bcc": d["bcc"]}, ip=client_ip(request))
        messages.success(request, _("Sent to %(to)s.") % {"to": ", ".join(d["to"])})
        return redirect(back_url)
    message = form["message"].value() or initial.get("message", "")
    preview, _text = build(message)
    return render(request, "docs/send_page.html", {"form": form, "ready": ready, "title": title, "back_url": back_url,
                                                   "crumbs": crumbs, "preview": preview, "note": note})
