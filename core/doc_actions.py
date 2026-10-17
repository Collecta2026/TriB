"""The QuickBooks action bar on every document: Print or download, Make recurring, More actions (copy, delete, void,
journal, audit history), Save ▾ (new / close), Share link, WhatsApp and Review and send."""
import re
from urllib.parse import quote, urlencode

from django import forms
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from .docviews import REGISTRY, get_doc, require
from .models import AuditLog, ShareLink, client_ip


def _spec(ns, key):
    spec = REGISTRY.get((ns, key))
    if spec is None:
        raise Http404
    return spec


def _url(name, *args):
    try:
        return reverse(name, args=args)
    except NoReverseMatch:
        return None


def email_ready():
    return bool(settings.EMAIL_HOST) or "locmem" in settings.EMAIL_BACKEND


# ---------- Where Save sends you ----------
def saved_redirect(request, detail_url, new_url, list_url):
    """Save → the document; Save and new → a blank form; Save and close → the list."""
    choice = request.POST.get("save", "")
    if choice == "new":
        return redirect(new_url)
    if choice == "close":
        return redirect(list_url)
    then = request.POST.get("then", "")
    if then in ("share", "whatsapp", "send"):
        return redirect(f"{detail_url}?{then}=1")
    return redirect(detail_url)


# ---------- The bar itself ----------
def bar_for(request, spec, doc, mode):
    """Everything the action bar template needs for a DocSpec document. mode: "form" or "detail"."""
    can = request.membership.has_perm
    has_number = bool(doc.pk and doc.number)
    detail = spec.url("detail", doc.pk) if doc.pk else None
    bar = {"mode": mode, "cancel": detail or spec.url_list, "left": [], "more": []}
    if doc.pk:  # drafts print too, marked DRAFT
        printing = spec.url("print", doc.pk)
        bar["print"] = {"print": printing, "pdf": printing + "#pdf",
                        "delivery": printing + "?delivery=1" if spec.party == "customer" else None}
    if spec.recurring_kind and has_number and can("vouchers.create"):
        bar["recurring"] = f"{reverse('core:recurring')}?{urlencode({'kind': spec.recurring_kind, 'number': doc.number})}"
    if doc.pk:
        if can(f"{spec.perm}.create"):
            bar["more"].append({"label": _("Make a copy"), "post": reverse("core:doc_copy", args=[spec.ns, spec.key, doc.pk])})
        if doc.status == "draft" and can(f"{spec.perm}.delete"):
            bar["more"].append({"label": _("Delete"), "post": reverse("core:doc_delete", args=[spec.ns, spec.key, doc.pk]),
                                "confirm": _("Delete this draft? This cannot be undone."), "danger": True})
        if spec.voidable and doc.status == "posted" and can(f"{spec.perm}.void") and not getattr(doc, "amount_paid", 0):
            bar["more"].append({"label": _("Void"), "post": _url(f"{spec.ns}:{spec.key}_action", doc.pk), "action": "void",
                                "confirm": _("Void this document? Its ledger entry is reversed."), "danger": True})
        if getattr(doc, "journal_entry_id", None) and can("ledger.view"):
            bar["more"].append({"label": _("Transaction journal"), "url": reverse("ledger:journal", args=[doc.journal_entry_id])})
        if can("audit.view"):
            bar["more"].append({"label": _("Audit history"), "url": audit_url(doc)})
    bar["share"] = spec.shareable and spec.party and doc.pk is not None
    bar["share_url"] = reverse("core:doc_share", args=[spec.ns, spec.key, doc.pk]) if doc.pk else ""
    bar["send"] = spec.ns == "sales" and spec.key in ("invoice", "quote") and doc.pk and has_number
    bar["send_url"] = reverse("core:doc_send", args=[spec.ns, spec.key, doc.pk]) if bar["send"] else ""
    bar["can_send_on_save"] = spec.ns == "sales" and spec.key in ("invoice", "quote")
    return bar


def audit_url(obj):
    return f"{reverse('core:audit')}?{urlencode({'type': obj._meta.label, 'id': obj.pk, 'q': getattr(obj, 'number', '') or ''})}"


# ---------- More actions ----------
COPY_SKIP = {"id", "number", "status", "created_at", "posted_at", "journal_entry", "amount_paid", "amount_applied",
             "amount_refunded", "qty_invoiced", "qty_received", "qty_delivered", "approved_by", "approved_at"}

COPY_FKS = {"company", "branch", "currency", "customer", "supplier", "warehouse"}  # links to source documents are not copied
LINE_FKS = {"item", "tax_rate", "project", "account"}


@login_required
@require_POST
@transaction.atomic
def doc_copy(request, ns, key, pk):
    spec = _spec(ns, key)
    require(request, spec, "create")
    src = get_doc(request, spec, pk)
    copy = spec.model()
    for f in spec.model._meta.concrete_fields:
        if f.name in COPY_SKIP or f.primary_key or f.one_to_one or (f.is_relation and f.name not in COPY_FKS):
            continue
        setattr(copy, f.attname, getattr(src, f.attname))
    copy.number, copy.status, copy.created_by = "", "draft", request.user
    copy.date = timezone.localdate()
    if hasattr(copy, "due_date") and hasattr(src, "due_date") and src.due_date and src.date:
        copy.due_date = copy.date + (src.due_date - src.date)
    copy.save()
    line_model = src.lines.model
    for line in src.lines.all():
        new = line_model()
        for f in line_model._meta.concrete_fields:
            if f.primary_key or f.name in COPY_SKIP or f.name in ("cost", "serials") or (
                    f.is_relation and f.name not in LINE_FKS):
                continue
            setattr(new, f.attname, getattr(line, f.attname))
        new.document = copy
        new.save()
    AuditLog.record(request.company, request.user, f"{key}.copied", copy, f"Copy of {src.number or src.pk}", ip=client_ip(request))
    messages.success(request, _("Copied to a new draft. Check it and save."))
    return redirect(spec.url("edit", copy.pk))


@login_required
@require_POST
@transaction.atomic
def doc_delete(request, ns, key, pk):
    spec = _spec(ns, key)
    require(request, spec, "delete")
    doc = get_doc(request, spec, pk)
    if doc.status != "draft":
        messages.error(request, _("Only drafts can be deleted. Void a posted document instead."))
        return redirect(spec.url("detail", doc.pk))
    AuditLog.record(request.company, request.user, f"{key}.deleted", doc, f"Draft {doc.pk} deleted", ip=client_ip(request))
    doc.lines.all().delete()
    doc.delete()
    messages.success(request, _("Draft deleted."))
    return redirect(spec.url_list)


# ---------- Share link and WhatsApp ----------
def whatsapp_number(phone):
    """Egyptian mobiles written 01xxxxxxxxx become 201xxxxxxxxx; other numbers keep their country code."""
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0") and len(digits) == 11:
        digits = "20" + digits[1:]
    return digits


def share_message(spec, doc, link):
    party = getattr(doc, spec.party, None)
    return _("Hello %(name)s, here is %(doc)s %(number)s for %(amount)s %(cur)s from %(company)s: %(link)s") % {
        "name": party.name if party else "", "doc": spec.title, "number": doc.number, "amount": f"{doc.total:,.2f}",
        "cur": doc.currency_id, "company": doc.company.name, "link": link}


@login_required
@require_POST
def doc_share(request, ns, key, pk):
    spec = _spec(ns, key)
    require(request, spec, "view")
    doc = get_doc(request, spec, pk)
    if not doc.number:
        return JsonResponse({"error": _("Save or post the document first so it has a number.")}, status=400)
    if request.POST.get("revoke") == "1":
        ShareLink.objects.filter(company=request.company, target=doc._meta.label_lower, target_id=doc.pk,
                                 revoked_at__isnull=True).update(revoked_at=timezone.now())
        AuditLog.record(request.company, request.user, f"{key}.share_revoked", doc, doc.number, ip=client_ip(request))
        return JsonResponse({"revoked": True})
    link = ShareLink.for_object(doc, request.user)
    url = request.build_absolute_uri(reverse("core:shared", args=[link.token]))
    party = getattr(doc, spec.party, None)
    text = share_message(spec, doc, url)
    phone = whatsapp_number(getattr(party, "phone", ""))
    AuditLog.record(request.company, request.user, f"{key}.shared", doc, doc.number, ip=client_ip(request))
    return JsonResponse({"url": url, "views": link.views,
                         "whatsapp": f"https://wa.me/{phone}?text={quote(text)}" if phone else f"https://wa.me/?text={quote(text)}"})


def shared(request, token):
    """The page a customer or supplier opens from a share link: the printable document, nothing else."""
    link = ShareLink.objects.filter(token=token, revoked_at__isnull=True).select_related("company").first()
    if link is None:
        return render(request, "docs/shared_gone.html", status=404)
    spec = next((s for s in REGISTRY.values() if s.model._meta.label_lower == link.target), None)
    if spec is None:
        raise Http404
    doc = spec.model.objects.filter(pk=link.target_id, company=link.company).first()
    if doc is None or doc.status in ("draft", "void"):
        return render(request, "docs/shared_gone.html", status=404)
    ShareLink.objects.filter(pk=link.pk).update(views=link.views + 1, last_viewed_at=timezone.now())
    return render(request, "docs/shared.html", print_context(spec, doc, delivery=False, company=link.company))


def print_context(spec, doc, delivery=False, company=None):
    party = getattr(doc, spec.party, None) if spec.party else None
    return {"spec": spec, "doc": doc, "lines": doc.lines.select_related("item", "tax_rate"), "party": party,
            "words_en": doc.words("en"), "words_ar": doc.words("ar"), "delivery": delivery,
            "company": company or doc.company}


# ---------- Review and send (email) ----------
class SendForm(forms.Form):
    to = forms.CharField(label=gettext_lazy("To"), max_length=300)
    cc = forms.CharField(label=gettext_lazy("Cc"), max_length=300, required=False)
    bcc = forms.CharField(label=gettext_lazy("Bcc"), max_length=300, required=False)
    subject = forms.CharField(label=gettext_lazy("Subject"), max_length=200)
    message = forms.CharField(label=gettext_lazy("Message"), widget=forms.Textarea(attrs={"rows": 7}))

    def _emails(self, name):
        raw = [e.strip() for e in re.split(r"[,;\s]+", self.cleaned_data.get(name) or "") if e.strip()]
        from django.core.validators import validate_email
        for e in raw:
            try:
                validate_email(e)
            except forms.ValidationError:
                raise forms.ValidationError(_("%(e)s is not a valid email address.") % {"e": e})
        return raw

    def clean_to(self):
        return self._emails("to")

    def clean_cc(self):
        return self._emails("cc")

    def clean_bcc(self):
        return self._emails("bcc")


@login_required
def doc_send(request, ns, key, pk):
    spec = _spec(ns, key)
    require(request, spec, "view")
    doc = get_doc(request, spec, pk)
    if not doc.number:
        messages.error(request, _("Post the document first so it has a number."))
        return redirect(spec.url("detail", doc.pk))
    party = getattr(doc, spec.party)
    company = request.company
    initial = {
        "to": getattr(doc, "email_to", "") or party.email, "cc": getattr(doc, "email_cc", ""),
        "bcc": getattr(doc, "email_bcc", ""),
        "subject": _("%(doc)s %(number)s from %(company)s") % {"doc": spec.title, "number": doc.number, "company": company.name},
        "message": _("Dear %(name)s,\n\nPlease find %(doc)s %(number)s for %(amount)s %(cur)s. You can view and print it using the link "
                     "below.\n\nThank you for your business.\n%(company)s") % {
            "name": party.name, "doc": spec.title, "number": doc.number, "amount": f"{doc.total:,.2f}", "cur": doc.currency_id,
            "company": company.name},
    }
    form = SendForm(request.POST or None, initial=initial)
    ready = email_ready()
    if request.method == "POST" and ready and form.is_valid():
        require(request, spec, "create")
        d = form.cleaned_data
        link = ShareLink.for_object(doc, request.user)
        url = request.build_absolute_uri(reverse("core:shared", args=[link.token]))
        ctx = {"doc": doc, "spec": spec, "company": company, "message": d["message"], "url": url}
        mail = EmailMultiAlternatives(d["subject"], render_to_string("docs/email.txt", ctx), settings.DEFAULT_FROM_EMAIL,
                                      d["to"], cc=d["cc"], bcc=d["bcc"], reply_to=[company.email] if company.email else None)
        mail.attach_alternative(render_to_string("docs/email.html", ctx), "text/html")
        try:
            mail.send()
        except Exception as exc:  # SMTP problems are shown, not raised
            messages.error(request, _("The email could not be sent: %(e)s") % {"e": exc})
            return redirect(request.path)
        AuditLog.record(company, request.user, f"{key}.sent", doc, f"{doc.number} → {', '.join(d['to'])}",
                        {"cc": d["cc"], "bcc": d["bcc"]}, ip=client_ip(request))
        messages.success(request, _("%(number)s sent to %(to)s.") % {"number": doc.number, "to": ", ".join(d["to"])})
        return redirect(spec.url("detail", doc.pk))
    return render(request, "docs/send.html", {"spec": spec, "doc": doc, "form": form, "ready": ready,
                                              "preview": spec.url("print", doc.pk) + "?embed=1"})


@login_required
def batch_print(request):
    """Customer / supplier page → Batch actions → Print selected: several documents, one per page."""
    docs, payments = [], []
    for item in (request.GET.get("items", "") or "").split(",")[:50]:
        try:
            ns, key, pk = item.split(":")
        except ValueError:
            continue
        if (ns, key) == ("purchases", "payment"):  # supplier payments print as remittance advices
            if pk.isdigit() and request.membership.has_perm("purchases.view"):
                payments.append(pk)
            continue
        spec = REGISTRY.get((ns, key))
        if spec is None or not pk.isdigit():
            continue
        require(request, spec, "view")
        doc = spec.model.objects.filter(pk=pk, company=request.company).first()
        if doc is not None and doc.number:
            docs.append(print_context(spec, doc, company=request.company))
    remits = []
    if payments:
        from purchases.remittance import payments_from, remittance
        remits = [remittance(p) for p in payments_from(request.company, payments)]
    return render(request, "docs/batch_print.html", {"docs": docs, "remits": remits, "count": len(docs) + len(remits)})
