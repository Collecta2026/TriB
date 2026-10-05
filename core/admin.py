from django.contrib import admin

from .models import AuditLog, Branch, Company, Currency, ExchangeRate


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name_en", "name_ar", "base_currency", "is_active", "created_at")
    list_filter = ("is_active",)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "company", "user", "action", "summary")
    list_filter = ("action",)

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(Currency)
admin.site.register(Branch)
admin.site.register(ExchangeRate)
admin.site.site_header = "TriB platform administration"
