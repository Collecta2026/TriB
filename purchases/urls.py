from django.urls import path

from . import views

app_name = "purchases"

urlpatterns = [
    path("orders/", views.orders, name="orders"),
    path("orders/new/", views.order_new, name="order_new"),
    path("orders/<int:pk>/", views.order, name="order"),
    path("orders/<int:pk>/edit/", views.order_edit, name="order_edit"),
    path("orders/<int:pk>/print/", views.order_print, name="order_print"),
    path("orders/<int:pk>/action/", views.order_action, name="order_action"),
    path("receipts/", views.receipts, name="receipts"),
    path("receipts/new/", views.receipt_new, name="receipt_new"),
    path("receipts/<int:pk>/", views.receipt, name="receipt"),
    path("receipts/<int:pk>/edit/", views.receipt_edit, name="receipt_edit"),
    path("receipts/<int:pk>/post/", views.receipt_post, name="receipt_post"),
    path("receipts/<int:pk>/print/", views.receipt_print, name="receipt_print"),
    path("bills/", views.bills, name="bills"),
    path("bills/new/", views.bill_new, name="bill_new"),
    path("bills/<int:pk>/", views.bill, name="bill"),
    path("bills/<int:pk>/edit/", views.bill_edit, name="bill_edit"),
    path("bills/<int:pk>/print/", views.bill_print, name="bill_print"),
    path("bills/<int:pk>/action/", views.bill_action, name="bill_action"),
    path("payments/", views.payments, name="payments"),
    path("payments/new/", views.payment_new, name="payment_new"),
    path("payments/<int:pk>/", views.payment, name="payment"),
    path("payments/<int:pk>/remittance/", views.payment_print, name="payment_print"),
    path("payments/<int:pk>/void/", views.payment_void, name="payment_void"),
    path("expenses/", views.expenses, name="expenses"),
    path("statements/", views.statements, name="statements"),
    path("not-received/", views.not_received, name="not_received"),
]
