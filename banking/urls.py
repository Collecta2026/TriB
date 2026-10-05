from django.urls import path

from . import views

app_name = "banking"

urlpatterns = [
    path("", views.account_list, name="accounts"),
    path("accounts/new/", views.account_new, name="account_new"),
    path("banks/", views.bank_list, name="banks"),
    path("cheques/", views.cheque_list, name="cheques"),
    path("cheques/<int:pk>/action/", views.cheque_action, name="cheque_action"),
]
