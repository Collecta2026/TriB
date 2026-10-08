"""Bookmarks, pinned apps (Customise), the Receipts inbox and recurring transactions."""
from django import forms
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from users.permissions import require_perm

from .attachments import ALLOWED
from .forms_util import DATE
from .models import Attachment, AuditLog, Bookmark, RecurringTemplate, UserPreference
from .navigation import APP_KEYS, DEFAULT_PINNED, visible_apps

RECEIPT_TARGET = "core.receipt"


# ---------- Bookmarks ----------
def _safe_path(request, url):
    """Only paths inside TriB can be bookmarked."""
    url = (url or "").strip()
    if not url.startswith("/") or url.startswith("//"):
        return None
    return url if url_has_allowed_host_and_scheme(url, {request.get_host()}) else None


@require_perm("dashboard.view")
def bookmarks(request):
    rows = Bookmark.objects.filter(user=request.user, company=request.company)
    if request.method == "POST":
        for b in rows:
            title = request.POST.get(f"title_{b.pk}")
            pos = request.POST.get(f"pos_{b.pk}", "")
            if title is not None:
                b.title = title.strip()[:120] or b.title
                b.position = int(pos) if pos.isdigit() else b.position
                b.save(update_fields=["title", "position"])
        messages.success(request, _("Bookmarks saved."))
        return redirect("core:bookmarks")
    return render(request, "core/bookmarks.html", {"rows": rows})


@require_POST
@require_perm("dashboard.view")
def bookmark_add(request):
    url = _safe_path(request, request.POST.get("url"))
    if url is None:
        messages.error(request, _("This page cannot be bookmarked."))
        return redirect("dashboard:home")
    existing = Bookmark.objects.filter(user=request.user, company=request.company, url=url).first()
    if existing:
        existing.delete()
        messages.success(request, _("Removed from bookmarks."))
    else:
        last = Bookmark.objects.filter(user=request.user, company=request.company).order_by("-position").first()
        Bookmark.objects.create(user=request.user, company=request.company, url=url,
                                title=(request.POST.get("title") or url).strip()[:120],
                                position=(last.position + 1) if last else 0)
        messages.success(request, _("Added to bookmarks."))
    return redirect(url)


@require_POST
@require_perm("dashboard.view")
def bookmark_delete(request, pk):
    get_object_or_404(Bookmark, pk=pk, user=request.user, company=request.company).delete()
    messages.success(request, _("Removed from bookmarks."))
    return redirect("core:bookmarks")


# ---------- Customise (pinned apps) ----------
@require_perm("dashboard.view")
def customise(request):
    pref = UserPreference.for_user(request.user, request.company)
    apps = visible_apps(request.membership)
    if request.method == "POST":
        keys = [k for k in request.POST.getlist("pinned") if k in APP_KEYS]
        order = {k: i for i, k in enumerate(pref.pinned_apps or [])}
        pref.pinned_apps = sorted(keys, key=lambda k: order.get(k, 99))
        pref.save(update_fields=["pinned_apps"])
        messages.success(request, _("Your menu is updated."))
        return redirect("core:customise")
    if request.GET.get("reset") == "1":
        pref.pinned_apps = list(DEFAULT_PINNED)
        pref.save(update_fields=["pinned_apps"])
        return redirect("core:customise")
    return render(request, "core/customise.html", {"apps": apps, "pinned": set(pref.pinned_apps or [])})


# ---------- Receipts inbox ----------
class AttachToForm(forms.Form):
    KINDS = [("vouchers.voucher", gettext_lazy("Voucher")), ("purchases.bill", gettext_lazy("Supplier bill"))]
    kind = forms.ChoiceField(choices=KINDS)
    number = forms.CharField(max_length=30)


@require_perm("vouchers.create")
def receipts(request):
    company = request.company
    if request.method == "POST" and request.FILES.getlist("files"):
        added = 0
        for f in request.FILES.getlist("files"):
            if f.size > Attachment.MAX_BYTES or not f.name.lower().endswith(ALLOWED):
                messages.error(request, _("%(f)s is not a supported file type.") % {"f": f.name})
                continue
            import mimetypes
            Attachment.objects.create(company=company, target=RECEIPT_TARGET, target_id=0, filename=f.name[:200],
                                      content_type=mimetypes.guess_type(f.name)[0] or "application/octet-stream",
                                      size=f.size, data=f.read(), uploaded_by=request.user)
            added += 1
        if added:
            messages.success(request, _("%(n)s receipts uploaded. Record each one, then attach it.") % {"n": added})
        return redirect("core:receipts")
    rows = Attachment.objects.filter(company=company, target=RECEIPT_TARGET, target_id=0).defer("data") \
        .select_related("uploaded_by").order_by("-uploaded_at")
    return render(request, "core/receipts.html", {"rows": rows, "form": AttachToForm()})


@require_POST
@require_perm("vouchers.create")
def receipt_attach(request, pk):
    a = get_object_or_404(Attachment, pk=pk, company=request.company, target=RECEIPT_TARGET)
    if "discard" in request.POST:
        AuditLog.record(request.company, request.user, "receipt.discarded", None, a.filename)
        a.delete()
        messages.success(request, _("Receipt removed."))
        return redirect("core:receipts")
    form = AttachToForm(request.POST)
    if form.is_valid():
        kind, number = form.cleaned_data["kind"], form.cleaned_data["number"].strip()
        if kind == "vouchers.voucher":
            from vouchers.models import Voucher
            doc = Voucher.objects.filter(company=request.company, number__iexact=number).first()
        else:
            from purchases.models import Bill
            doc = Bill.objects.filter(company=request.company, number__iexact=number).first()
        if doc is None:
            messages.error(request, _("No document numbered %(n)s.") % {"n": number})
        else:
            a.target, a.target_id = kind, doc.pk
            a.save(update_fields=["target", "target_id"])
            messages.success(request, _("Receipt attached to %(n)s.") % {"n": number})
    return redirect("core:receipts")


# ---------- Recurring transactions ----------
class RecurringForm(forms.ModelForm):
    number = forms.CharField(label=gettext_lazy("Copy this document (number)"), max_length=30)

    class Meta:
        model = RecurringTemplate
        fields = ["name", "kind", "frequency", "next_date", "end_date"]
        widgets = {"next_date": DATE, "end_date": DATE}


def _source_id(company, kind, number):
    if kind == "voucher":
        from vouchers.models import Voucher as M
    elif kind == "invoice":
        from sales.models import Invoice as M
    else:
        from purchases.models import Bill as M
    doc = M.objects.filter(company=company, number__iexact=number.strip()).first()
    return doc.pk if doc else None


@require_perm("vouchers.create")
def recurring(request):
    from .recurring import run_due, source_document
    company = request.company
    form = RecurringForm(request.POST or None, initial={"next_date": timezone.localdate()})
    if request.method == "POST" and "run" in request.POST:
        created = run_due(company, request.user)
        messages.success(request, _("%(n)s draft documents created.") % {"n": len(created)} if created
                         else _("Nothing is due today."))
        return redirect("core:recurring")
    if request.method == "POST" and "stop" in request.POST:
        t = get_object_or_404(RecurringTemplate, pk=request.POST.get("stop"), company=company)
        t.is_active = not t.is_active
        t.save(update_fields=["is_active"])
        return redirect("core:recurring")
    if request.method == "POST" and form.is_valid():
        source = _source_id(company, form.cleaned_data["kind"], form.cleaned_data["number"])
        if source is None:
            form.add_error("number", _("No document of this type has that number."))
        else:
            t = form.save(commit=False)
            t.company, t.source_id, t.created_by = company, source, request.user
            t.save()
            messages.success(request, _("Saved. A draft is created on each date for you to review and post."))
            return redirect("core:recurring")
    rows = [(t, source_document(t)) for t in RecurringTemplate.objects.filter(company=company)]
    return render(request, "core/recurring.html", {"form": form, "rows": rows, "today": timezone.localdate(),
                                                   "due": sum(1 for t, _s in rows if t.is_active and t.next_date <= timezone.localdate())})
