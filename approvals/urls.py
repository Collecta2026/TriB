from django.urls import path

from . import views

app_name = "approvals"

urlpatterns = [
    path("", views.inbox, name="inbox"),
    path("rules/", views.rules, name="rules"),
    path("rules/<int:pk>/toggle/", views.rule_toggle, name="rule_toggle"),
]
