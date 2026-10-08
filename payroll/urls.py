from django.urls import path

from . import views

app_name = "payroll"

urlpatterns = [
    path("", views.runs, name="runs"),
    path("runs/<int:pk>/", views.run, name="run"),
    path("runs/<int:pk>/action/", views.run_action, name="run_action"),
    path("runs/<int:pk>/deductions/", views.deductions, name="deductions"),
    path("runs/<int:pk>/payslips/", views.payslips_print, name="payslips_print"),
    path("payslips/<int:pk>/", views.payslip, name="payslip"),
    path("settings/", views.settings_view, name="settings"),
    path("leave-provision/", views.leave_provision, name="leave_provision"),
]
