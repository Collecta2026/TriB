from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from core.models import Company
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
