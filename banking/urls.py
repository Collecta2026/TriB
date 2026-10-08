from django.urls import path

from . import cheque_views, feed_views, views

app_name = "banking"

urlpatterns = [
    path("", views.account_list, name="accounts"),
    path("accounts/new/", views.account_new, name="account_new"),
    path("banks/", views.bank_list, name="banks"),
    path("cheques/", views.cheque_list, name="cheques"),
    path("cheques/<int:pk>/action/", views.cheque_action, name="cheque_action"),
    path("cheques/returned/", cheque_views.bounced, name="bounced"),
    path("cheques/returned/<int:pk>/", cheque_views.returned_action, name="returned_action"),
    path("cheques/reconciliation/", cheque_views.cheque_reconciliation, name="cheque_reconciliation"),
    path("transactions/", feed_views.transactions, name="transactions"),
    path("transactions/upload/", feed_views.transactions_import, name="transactions_import"),
    path("transactions/columns/", feed_views.transactions_map, name="transactions_map"),
    path("transactions/<int:pk>/", feed_views.transaction_action, name="transaction_action"),
    path("rules/", feed_views.rules, name="rules"),
    path("reconcile/", feed_views.reconcile, name="reconcile"),
    path("reconcile/<int:pk>/", feed_views.reconciliation, name="reconciliation"),
]
