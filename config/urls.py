from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path


def healthz(request):
    return HttpResponse("ok", content_type="text/plain")


urlpatterns = [
    path("healthz", healthz),
    path("admin/", admin.site.urls),
    path("", include("dashboard.urls")),
    path("", include("core.urls")),
    path("accounts/", include("users.urls")),
    path("ledger/", include("ledger.urls")),
    path("banking/", include("banking.urls")),
    path("vouchers/", include("vouchers.urls")),
    path("approvals/", include("approvals.urls")),
    path("reports/", include("reports.urls")),
]
