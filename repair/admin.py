from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Building, RepairCategory, User, WorkOrder, WorkOrderImage


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


@admin.register(Building)
class BuildingAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name',)


@admin.register(RepairCategory)
class RepairCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name',)


class WorkOrderImageInline(admin.TabularInline):
    model = WorkOrderImage
    extra = 0
    readonly_fields = ('uploaded_at',)


@admin.register(WorkOrder)
class WorkOrderAdmin(admin.ModelAdmin):
    list_display = (
        'order_no',
        'student',
        'building',
        'room_no',
        'contact_phone',
        'allow_entry_without_student',
        'category',
        'status',
        'created_at',
    )
    list_filter = ('status', 'building', 'category', 'allow_entry_without_student')
    search_fields = (
        'order_no',
        'student__username',
        'student__real_name',
        'room_no',
        'contact_phone',
        'repair_address',
        'remark',
    )
    readonly_fields = ('order_no', 'created_at', 'updated_at')
    date_hierarchy = 'created_at'
    inlines = [WorkOrderImageInline]
