from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("setup/", views.first_run, name="setup"),
    path("no-company/", views.no_company, name="no_company"),
    path("language/", views.switch_language, name="language"),
    path("company/switch/", views.switch_company, name="switch_company"),
    path("apps/", views.apps, name="apps"),
    path("search/", views.search, name="search"),
    path("settings/", views.company_settings, name="settings"),
    path("audit/", views.audit_log, name="audit"),
]
