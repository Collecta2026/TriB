from django.urls import path

from . import attachments, nav_views, views

app_name = "core"

urlpatterns = [
    path("attachments/upload/", attachments.upload, name="attachment_upload"),
    path("attachments/<int:pk>/", attachments.download, name="attachment"),
    path("attachments/<int:pk>/delete/", attachments.delete, name="attachment_delete"),
    path("setup/", views.first_run, name="setup"),
    path("no-company/", views.no_company, name="no_company"),
    path("language/", views.switch_language, name="language"),
    path("company/switch/", views.switch_company, name="switch_company"),
    path("apps/", views.apps, name="apps"),
    path("search/", views.search, name="search"),
    path("settings/", views.company_settings, name="settings"),
    path("audit/", views.audit_log, name="audit"),
    path("bookmarks/", nav_views.bookmarks, name="bookmarks"),
    path("bookmarks/add/", nav_views.bookmark_add, name="bookmark_add"),
    path("bookmarks/<int:pk>/delete/", nav_views.bookmark_delete, name="bookmark_delete"),
    path("customise/", nav_views.customise, name="customise"),
    path("receipts/", nav_views.receipts, name="receipts"),
    path("receipts/<int:pk>/", nav_views.receipt_attach, name="receipt_attach"),
    path("recurring/", nav_views.recurring, name="recurring"),
]
