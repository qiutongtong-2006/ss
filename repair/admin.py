from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import (
    Building,
    Evaluation,
    RepairCategory,
    RepairRecord,
    StatusLog,
    User,
    WorkOrder,
    WorkOrderImage,
)


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


class RepairRecordInline(admin.TabularInline):
    model = RepairRecord
    extra = 0
    can_delete = False
    readonly_fields = (
        'repairer',
        'fault_cause',
        'repair_action',
        'materials_used',
        'completed_at',
        'created_at',
    )
    ordering = ('completed_at',)

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class StatusLogInline(admin.TabularInline):
    model = StatusLog
    extra = 0
    can_delete = False
    readonly_fields = ('from_status', 'to_status', 'operator', 'remark', 'created_at')
    ordering = ('created_at',)

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class EvaluationInline(admin.StackedInline):
    model = Evaluation
    extra = 0
    can_delete = False
    readonly_fields = (
        'student',
        'rating',
        'comment',
        'created_at',
    )
    max_num = 1

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


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
        'repairer',
        'started_at',
        'completed_at',
        'created_at',
    )
    list_filter = (
        'status',
        'building',
        'category',
        'repairer',
        'allow_entry_without_student',
    )
    search_fields = (
        'order_no',
        'student__username',
        'student__real_name',
        'room_no',
        'contact_phone',
        'repair_address',
        'remark',
        'repairer__username',
        'repairer__real_name',
        'repair_records__repair_action',
    )
    readonly_fields = (
        'order_no',
        'status',
        'repairer',
        'accepted_at',
        'assigned_at',
        'started_at',
        'completed_at',
        'verified_at',
        'return_count',
        'reject_reason',
        'cancel_reason',
        'created_at',
        'updated_at',
    )
    date_hierarchy = 'created_at'
    inlines = [
        WorkOrderImageInline,
        RepairRecordInline,
        EvaluationInline,
        StatusLogInline,
    ]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Evaluation)
class EvaluationAdmin(admin.ModelAdmin):
    list_display = ('work_order', 'student', 'rating', 'created_at')
    list_filter = ('rating', 'created_at')
    search_fields = (
        'work_order__order_no',
        'student__username',
        'student__real_name',
        'comment',
    )
    readonly_fields = (
        'work_order',
        'student',
        'rating',
        'comment',
        'created_at',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
