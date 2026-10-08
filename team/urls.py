from django.urls import path

from . import views

app_name = "team"

urlpatterns = [
    path("", views.employees, name="employees"),
    path("new/", views.employee_new, name="employee_new"),
    path("import/", views.employee_import, name="import"),
    path("<int:pk>/", views.employee, name="employee"),
    path("<int:pk>/edit/", views.employee_edit, name="employee_edit"),
    path("departments/", views.departments, name="departments"),
    path("benefits/", views.benefits, name="benefits"),
    path("loans/", views.loans, name="loans"),
    path("attendance/", views.attendance, name="attendance"),
    path("leave/", views.leave, name="leave"),
]
