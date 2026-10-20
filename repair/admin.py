from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    fieldsets = BaseUserAdmin.fieldsets + (
        ('角色与联系信息', {'fields': ('role', 'real_name', 'phone')}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ('角色与联系信息', {'fields': ('role', 'real_name', 'phone')}),
    )
    list_display = ('username', 'real_name', 'role', 'is_staff', 'is_active')
    list_filter = BaseUserAdmin.list_filter + ('role',)
    search_fields = ('username', 'real_name', 'phone')
