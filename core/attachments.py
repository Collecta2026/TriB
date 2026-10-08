"""Attach files (PDF, images, Excel, Word…) to any document."""
import mimetypes

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils.http import content_disposition_header, url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from .models import Attachment, AuditLog

# Which permission module guards attachments of each app.
MODULES = {"sales": "sales", "purchases": "purchases", "vouchers": "vouchers", "team": "team", "assets": "assets",
           "contacts": "contacts", "inventory": "inventory", "payroll": "payroll", "ledger": "ledger",
           "banking": "banking", "core": "vouchers"}
ALLOWED = (".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".xlsx", ".xls", ".csv", ".docx", ".doc", ".txt",
           ".msg", ".eml", ".zip")
# Only these open in the browser; everything else downloads.
INLINE_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp"}


def module_for(target):
    return MODULES.get(target.split(".")[0], "ledger")


def check(request, target, action):
    if request.membership is None or not request.membership.has_perm(f"{module_for(target)}.{action}"):
        raise PermissionDenied


def _back(request, fallback="/"):
    nxt = request.POST.get("next") or request.GET.get("next") or fallback
    return nxt if url_has_allowed_host_and_scheme(nxt, {request.get_host()}) else fallback


@login_required
@require_POST
def upload(request):
    target, target_id = request.POST.get("target", ""), request.POST.get("target_id", "0")
    check(request, target, "view")
    files = request.FILES.getlist("files")
    added = 0
    for f in files:
        if f.size > Attachment.MAX_BYTES:
            messages.error(request, _("%(f)s is larger than 10 MB.") % {"f": f.name})
            continue
        if not f.name.lower().endswith(ALLOWED):
            messages.error(request, _("%(f)s is not a supported file type.") % {"f": f.name})
            continue
        # Decide the type from the extension, never from the browser, so nothing uploaded can render as HTML/SVG.
        content_type = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        Attachment.objects.create(company=request.company, target=target, target_id=int(target_id or 0),
                                  filename=f.name[:200], content_type=content_type,
                                  size=f.size, data=f.read(), uploaded_by=request.user)
        added += 1
    if added:
        AuditLog.record(request.company, request.user, "attachment.added", None, f"{target}#{target_id}: {added} file(s)")
        messages.success(request, _("File attached.") if added == 1 else _("Files attached."))
    return redirect(_back(request))


@login_required
def download(request, pk):
    a = get_object_or_404(Attachment, pk=pk, company=request.company)
    check(request, a.target, "view")
    inline = a.content_type in INLINE_TYPES
    response = HttpResponse(bytes(a.data), content_type=a.content_type if inline else "application/octet-stream")
    response["Content-Disposition"] = content_disposition_header(not inline, a.filename)
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
@require_POST
def delete(request, pk):
    a = get_object_or_404(Attachment, pk=pk, company=request.company)
    check(request, a.target, "edit")
    AuditLog.record(request.company, request.user, "attachment.deleted", None, f"{a.target}#{a.target_id}: {a.filename}")
    a.delete()
    messages.success(request, _("Attachment removed."))
    return redirect(_back(request))


def for_object(obj):
    return Attachment.objects.filter(company_id=obj.company_id, target=obj._meta.label_lower, target_id=obj.pk).defer("data")
