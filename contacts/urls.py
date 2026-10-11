from django.urls import path

from . import views

app_name = "contacts"

urlpatterns = [
    path("customers/", views.customers, name="customers"),
    path("customers/new/", views.customer_new, name="customer_new"),
    path("customers/<int:pk>/", views.customer, name="customer"),
    path("customers/<int:pk>/edit/", views.customer_edit, name="customer_edit"),
    path("customers/<int:pk>/notes/", views.customer_notes, name="customer_notes"),
    path("customers/<int:pk>/active/", views.customer_active, name="customer_active"),
    path("suppliers/", views.suppliers, name="suppliers"),
    path("suppliers/new/", views.supplier_new, name="supplier_new"),
    path("suppliers/<int:pk>/", views.supplier, name="supplier"),
    path("suppliers/<int:pk>/edit/", views.supplier_edit, name="supplier_edit"),
    path("suppliers/<int:pk>/notes/", views.supplier_notes, name="supplier_notes"),
    path("suppliers/<int:pk>/active/", views.supplier_active, name="supplier_active"),
]
