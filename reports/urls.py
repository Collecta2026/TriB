from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("", views.index, name="index"),
    path("trial-balance/", views.trial_balance, name="trial_balance"),
    path("statement/", views.statement, name="statement"),
    path("profit-and-loss/", views.profit_loss, name="profit_loss"),
    path("balance-sheet/", views.balance_sheet, name="balance_sheet"),
]
