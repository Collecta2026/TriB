from django.urls import path

from . import views

app_name = "contacts"

urlpatterns = [
    path("customers/", views.customers, name="customers"),
    path("customers/new/", views.customer_new, name="customer_new"),
    path("customers/<int:pk>/", views.customer, name="customer"),
    path("customers/<int:pk>/edit/", views.customer_edit, name="customer_edit"),
    path("suppliers/", views.suppliers, name="suppliers"),
    path("suppliers/new/", views.supplier_new, name="supplier_new"),
    path("suppliers/<int:pk>/", views.supplier, name="supplier"),
    path("suppliers/<int:pk>/edit/", views.supplier_edit, name="supplier_edit"),
]
