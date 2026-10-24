from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from .models import User, WorkOrder


def role_required(*allowed_roles, allow_superuser=False):
    """限制视图角色；匿名用户仍跳转登录，已登录越权用户返回 403。"""
    allowed_roles = frozenset(allowed_roles)

    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapped(request, *args, **kwargs):
            user = request.user
            if user.is_superuser:
                if allow_superuser:
                    return view_func(request, *args, **kwargs)
                raise PermissionDenied('超级管理员不能代替业务角色执行此操作。')
            if user.role not in allowed_roles:
                raise PermissionDenied('当前角色无权访问此功能。')
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator


def is_manager_user(user):
    return bool(
        getattr(user, 'is_authenticated', False)
        and (
            user.is_superuser
            or getattr(user, 'role', None) == User.Role.MANAGER
        )
    )


def is_student_owner(user, work_order):
    return bool(
        getattr(user, 'is_authenticated', False)
        and not user.is_superuser
        and getattr(user, 'role', None) == User.Role.STUDENT
        and work_order.student_id == user.id
    )


def is_assigned_repairer(user, work_order):
    return bool(
        getattr(user, 'is_authenticated', False)
        and not user.is_superuser
        and getattr(user, 'role', None) == User.Role.REPAIRER
        and work_order.repairer_id == user.id
    )


def user_can_view_work_order(user, work_order):
    if not getattr(user, 'is_authenticated', False):
        return False
    if user.is_superuser or is_manager_user(user):
        return True
    if getattr(user, 'role', None) == User.Role.STUDENT:
        return work_order.student_id == user.id
    if getattr(user, 'role', None) == User.Role.REPAIRER:
        return work_order.repairer_id == user.id
    return False


def require_work_order_access(user, work_order):
    if not user_can_view_work_order(user, work_order):
        raise PermissionDenied('无权查看该工单。')


def require_student_owner(user, work_order, message='只能操作自己的报修。'):
    if not is_student_owner(user, work_order):
        raise PermissionDenied(message)


def require_assigned_repairer(
    user,
    work_order,
    message='不能操作未派给自己的工单。',
):
    if not is_assigned_repairer(user, work_order):
        raise PermissionDenied(message)
