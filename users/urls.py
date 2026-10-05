from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "users"

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("password/", views.change_password, name="password"),
    path("users/", views.user_list, name="users"),
    path("users/new/", views.user_new, name="user_new"),
    path("users/<int:pk>/", views.user_edit, name="user_edit"),
    path("roles/new/", views.role_edit, name="role_new"),
    path("roles/<int:pk>/", views.role_edit, name="role_edit"),
]
