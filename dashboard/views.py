import json

from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from core.models import Company, UserPreference
from users.permissions import require_perm

from . import services


def home(request):
    if not Company.objects.exists():
        return redirect("core:setup")
    return _home(request)


@require_perm("dashboard.view")
def _home(request):
    data = services.build(request.company, request.user, request.membership)
    name = (request.user.full_name or request.user.email).split()[0]
    return render(request, "dashboard/home.html", {**data, "first_name": name})


@require_POST
@require_perm("dashboard.view")
def save_layout(request):
    """Customise dashboard → Save: order, width and visibility of each widget, for this user only."""
    pref = UserPreference.for_user(request.user, request.company)
    if request.POST.get("reset") == "1":
        pref.dashboard_layout = []
    else:
        try:
            posted = json.loads(request.POST.get("layout") or "[]")
        except ValueError:
            return JsonResponse({"error": "bad layout"}, status=400)
        pref.dashboard_layout = services.clean_layout(posted)
    pref.save(update_fields=["dashboard_layout"])
    return JsonResponse({"ok": True})
