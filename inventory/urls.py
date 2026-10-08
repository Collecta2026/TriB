from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("items/", views.items, name="items"),
    path("items/new/", views.item_new, name="item_new"),
    path("items/<int:pk>/", views.item, name="item"),
    path("items/<int:pk>/edit/", views.item_edit, name="item_edit"),
    path("categories/", views.categories, name="categories"),
    path("warehouses/", views.warehouses, name="warehouses"),
    path("stock/", views.stock, name="stock"),
    path("expiry/", views.expiry, name="expiry"),
    path("transfers/", views.transfers, name="transfers"),
    path("transfers/new/", views.transfer_new, name="transfer_new"),
    path("transfers/<int:pk>/", views.transfer, name="transfer"),
    path("transfers/<int:pk>/edit/", views.transfer_edit, name="transfer_edit"),
    path("transfers/<int:pk>/post/", views.transfer_post, name="transfer_post"),
    path("adjustments/", views.adjustments, name="adjustments"),
    path("adjustments/new/", views.adjustment_new, name="adjustment_new"),
    path("adjustments/<int:pk>/", views.adjustment, name="adjustment"),
    path("adjustments/<int:pk>/edit/", views.adjustment_edit, name="adjustment_edit"),
    path("adjustments/<int:pk>/post/", views.adjustment_post, name="adjustment_post"),
    path("counts/", views.counts, name="counts"),
    path("counts/<int:pk>/", views.count, name="count"),
    path("counts/<int:pk>/post/", views.count_post, name="count_post"),
    path("counts/<int:pk>/sheet/", views.count_sheet, name="count_sheet"),
    path("labels/", views.labels, name="labels"),
]
