from django.urls import path

from . import views

app_name = "sales"

urlpatterns = [
    path("quotes/", views.quotes, name="quotes"),
    path("quotes/new/", views.quote_new, name="quote_new"),
    path("quotes/<int:pk>/", views.quote, name="quote"),
    path("quotes/<int:pk>/edit/", views.quote_edit, name="quote_edit"),
    path("quotes/<int:pk>/print/", views.quote_print, name="quote_print"),
    path("quotes/<int:pk>/action/", views.quote_action, name="quote_action"),
    path("orders/", views.orders, name="orders"),
    path("orders/new/", views.order_new, name="order_new"),
    path("orders/<int:pk>/", views.order, name="order"),
    path("orders/<int:pk>/edit/", views.order_edit, name="order_edit"),
    path("orders/<int:pk>/print/", views.order_print, name="order_print"),
    path("orders/<int:pk>/action/", views.order_action, name="order_action"),
    path("invoices/", views.invoices, name="invoices"),
    path("invoices/new/", views.invoice_new, name="invoice_new"),
    path("invoices/<int:pk>/", views.invoice, name="invoice"),
    path("invoices/<int:pk>/edit/", views.invoice_edit, name="invoice_edit"),
    path("invoices/<int:pk>/print/", views.invoice_print, name="invoice_print"),
    path("invoices/<int:pk>/action/", views.invoice_action, name="invoice_action"),
    path("payments/", views.payments, name="payments"),
    path("payments/new/", views.payment_new, name="payment_new"),
    path("payments/<int:pk>/", views.payment, name="payment"),
    path("payments/<int:pk>/print/", views.payment_print, name="payment_print"),
    path("payments/<int:pk>/void/", views.payment_void, name="payment_void"),
    path("statements/", views.statements, name="statements"),
    path("confirmations/", views.confirmations, name="confirmations"),
]
