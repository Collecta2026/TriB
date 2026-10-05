from django.urls import path

from . import views

app_name = "vouchers"

urlpatterns = [
    path("", views.voucher_list, name="list"),
    path("new/<str:kind>/", views.voucher_new, name="new"),
    path("<int:pk>/", views.voucher_detail, name="detail"),
    path("<int:pk>/edit/", views.voucher_edit, name="edit"),
    path("<int:pk>/action/", views.voucher_action, name="action"),
    path("<int:pk>/print/", views.voucher_print, name="print"),
]
