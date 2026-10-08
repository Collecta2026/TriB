from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("", views.index, name="index"),
    path("trial-balance/", views.trial_balance, name="trial_balance"),
    path("statement/", views.statement, name="statement"),
    path("profit-and-loss/", views.profit_loss, name="profit_loss"),
    path("balance-sheet/", views.balance_sheet, name="balance_sheet"),
    path("ar-ageing/", views.ar_aging, name="ar_aging"),
    path("ap-ageing/", views.ap_aging, name="ap_aging"),
    path("vat-return/", views.vat_return, name="vat_return"),
    path("sales-by-product/", views.sales_by_item, name="sales_by_item"),
]
