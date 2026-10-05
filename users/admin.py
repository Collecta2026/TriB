from django.contrib import admin

from .models import Membership, Role, User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email", "full_name", "is_active", "is_staff", "last_login")
    search_fields = ("email", "full_name")
    exclude = ("password",)


admin.site.register(Role)
admin.site.register(Membership)
