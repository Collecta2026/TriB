from django.urls import path

from . import views

app_name = "assets"

urlpatterns = [
    path("", views.asset_list, name="list"),
    path("new/", views.asset_new, name="new"),
    path("<int:pk>/", views.asset_detail, name="detail"),
    path("<int:pk>/edit/", views.asset_edit, name="edit"),
    path("<int:pk>/dispose/", views.asset_dispose, name="dispose"),
    path("categories/", views.categories, name="categories"),
    path("depreciation/", views.depreciation, name="depreciation"),
    path("counts/", views.counts, name="counts"),
    path("counts/<int:pk>/", views.count, name="count"),
    path("counts/<int:pk>/close/", views.count_close, name="count_close"),
    path("labels/", views.labels, name="labels"),
]
