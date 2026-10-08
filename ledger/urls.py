from django.urls import path

from . import extra_views, views

app_name = "ledger"

urlpatterns = [
    path("accounts/", views.account_list, name="accounts"),
    path("accounts/new/", views.account_new, name="account_new"),
    path("accounts/<int:pk>/", views.account_edit, name="account_edit"),
    path("cost-centres/", views.cost_centers, name="cost_centers"),
    path("vat-rates/", extra_views.tax_rates, name="tax_rates"),
    path("journals/", views.journal_list, name="journals"),
    path("journals/<int:pk>/", views.journal_detail, name="journal"),
    path("journals/<int:pk>/reverse/", views.journal_reverse, name="journal_reverse"),
]
