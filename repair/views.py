from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .filters import filter_work_orders
from .forms import (
    AcceptOrderForm,
    CancelOrderForm,
    RepairCompletionForm,
    RejectOrderForm,
    StudentRegistrationForm,
    WorkOrderSubmitForm,
)
from .models import Building, StatusLog, User, WorkOrder, WorkOrderImage


def register(request):
    """学生自助注册，角色固定为学生。"""
    if request.user.is_authenticated:
        return redirect('repair:home')

    if request.method == 'POST':
        form = StudentRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.role = User.Role.STUDENT
            user.save()
            login(request, user)
            messages.success(request, '注册成功，欢迎使用学生宿舍报修系统。')
            return redirect('repair:home')
    else:
        form = StudentRegistrationForm()

    return render(request, 'repair/register.html', {'form': form})


@login_required
def home(request):
    """登录后的首页，按角色显示不同入口。"""
    return render(request, 'repair/home.html')


@login_required
def my_orders(request):
    """学生查看自己的报修列表。"""
    if request.user.role != User.Role.STUDENT:
        raise PermissionDenied('只有学生可以查看“我的报修”。')

    queryset = WorkOrder.objects.filter(student=request.user).select_related(
        'building',
        'category',
        'repairer',
    )
    work_orders, filter_form = filter_work_orders(queryset, request.GET)
    return render(
        request,
        'repair/my_orders.html',
        {
            'work_orders': work_orders,
            'filter_form': filter_form,
        },
    )


@login_required
def repairer_orders(request):
    """维修人员查看派给自己的任务。"""
    if request.user.role != User.Role.REPAIRER:
        raise PermissionDenied('只有维修人员可以查看“我的维修任务”。')

    queryset = WorkOrder.objects.filter(repairer=request.user).select_related(
        'student',
        'building',
        'category',
        'repairer',
    )
    work_orders, filter_form = filter_work_orders(queryset, request.GET)
    summary = queryset.aggregate(
        total=Count('id'),
        assigned=Count('id', filter=Q(status=WorkOrder.Status.ASSIGNED)),
        repairing=Count('id', filter=Q(status=WorkOrder.Status.REPAIRING)),
        pending_acceptance=Count(
            'id',
            filter=Q(status=WorkOrder.Status.PENDING_ACCEPTANCE),
        ),
        completed=Count('id', filter=Q(status=WorkOrder.Status.COMPLETED)),
    )
    return render(
        request,
        'repair/repairer_orders.html',
        {
            'work_orders': work_orders,
            'filter_form': filter_form,
            'summary': summary,
        },
    )


@login_required
def manager_orders(request):
    """宿管工单池，默认显示待受理工单。"""
    if not (
        request.user.role == User.Role.MANAGER
        or request.user.is_superuser
    ):
        raise PermissionDenied('只有宿管可以查看工单池。')

    params = request.GET.copy()
    if not params:
        params['status'] = WorkOrder.Status.PENDING

    queryset = WorkOrder.objects.select_related(
        'student',
        'building',
        'category',
        'repairer',
    )
    work_orders, filter_form = filter_work_orders(queryset, params)
    summary = WorkOrder.objects.aggregate(
        total=Count('id'),
        pending=Count('id', filter=Q(status=WorkOrder.Status.PENDING)),
        assigned=Count('id', filter=Q(status=WorkOrder.Status.ASSIGNED)),
        repairing=Count('id', filter=Q(status=WorkOrder.Status.REPAIRING)),
        pending_acceptance=Count(
            'id',
            filter=Q(status=WorkOrder.Status.PENDING_ACCEPTANCE),
        ),
    )

    return render(
        request,
        'repair/manager_orders.html',
        {
            'work_orders': work_orders,
            'filter_form': filter_form,
            'summary': summary,
        },
    )


@login_required
def submit_repair(request):
    """学生提交报修，并保存现场照片。"""
    if request.user.role != User.Role.STUDENT:
        messages.error(request, '只有学生可以提交报修。')
        return redirect('repair:home')

    if request.method == 'POST':
        form = WorkOrderSubmitForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            building_name = form.cleaned_data['building_name']
            building = Building.objects.filter(name__iexact=building_name).first()
            if building is None:
                building = Building.objects.create(name=building_name)

            work_order = form.save(commit=False)
            work_order.student = request.user
            work_order.building = building
            with transaction.atomic():
                work_order.save()
                for image in form.cleaned_data['images']:
                    WorkOrderImage.objects.create(work_order=work_order, image=image)
                StatusLog.objects.create(
                    work_order=work_order,
                    from_status='',
                    to_status=WorkOrder.Status.PENDING,
                    operator=request.user,
                    remark='学生提交报修',
                )
            messages.success(request, f'报修提交成功，工单号：{work_order.order_no}')
            return redirect('repair:work_order_detail', pk=work_order.pk)
    else:
        form = WorkOrderSubmitForm(user=request.user)

    return render(
        request,
        'repair/submit_repair.html',
        {
            'form': form,
            'building_options': Building.objects.filter(is_active=True),
        },
    )


@login_required
def work_order_detail(request, pk):
    """查看工单详情，按角色限制数据范围。"""
    work_order = get_object_or_404(
        WorkOrder.objects.select_related(
            'student',
            'building',
            'category',
            'repairer',
        ),
        pk=pk,
    )

    if (
        request.user.role == User.Role.STUDENT
        and work_order.student_id != request.user.id
    ):
        raise PermissionDenied('不能查看其他学生的报修。')
    if (
        request.user.role == User.Role.REPAIRER
        and work_order.repairer_id != request.user.id
    ):
        raise PermissionDenied('不能查看未派给自己的工单。')

    is_student_owner = (
        request.user.role == User.Role.STUDENT
        and work_order.student_id == request.user.id
    )
    is_manager = (
        request.user.role == User.Role.MANAGER
        or request.user.is_superuser
    )
    is_repairer_assigned = (
        request.user.role == User.Role.REPAIRER
        and work_order.repairer_id == request.user.id
    )
    status_logs = work_order.status_logs.select_related('operator')

    return render(
        request,
        'repair/work_order_detail.html',
        {
            'work_order': work_order,
            'status_logs': status_logs,
            'can_cancel': (
                is_student_owner
                and work_order.status == WorkOrder.Status.PENDING
            ),
            'can_manage': (
                is_manager
                and work_order.status == WorkOrder.Status.PENDING
            ),
            'can_start_repair': (
                is_repairer_assigned
                and work_order.status == WorkOrder.Status.ASSIGNED
            ),
            'can_complete_repair': (
                is_repairer_assigned
                and work_order.status == WorkOrder.Status.REPAIRING
            ),
        },
    )


@login_required
@require_POST
def start_repair(request, pk):
    """维修人员接单，将工单从已派单转为维修中。"""
    if request.user.role != User.Role.REPAIRER:
        raise PermissionDenied('只有维修人员可以接单。')

    work_order = get_object_or_404(WorkOrder, pk=pk)
    if work_order.repairer_id != request.user.id:
        raise PermissionDenied('不能接未派给自己的工单。')
    if work_order.status != WorkOrder.Status.ASSIGNED:
        messages.error(request, '只有已派单工单可以接单。')
        return redirect('repair:work_order_detail', pk=work_order.pk)

    with transaction.atomic():
        locked_order = WorkOrder.objects.select_for_update().get(pk=work_order.pk)
        if locked_order.status != WorkOrder.Status.ASSIGNED:
            messages.error(request, '工单状态已变化，请刷新后重试。')
            return redirect('repair:work_order_detail', pk=locked_order.pk)

        locked_order.status = WorkOrder.Status.REPAIRING
        locked_order.started_at = timezone.now()
        locked_order.save()
        StatusLog.objects.create(
            work_order=locked_order,
            from_status=WorkOrder.Status.ASSIGNED,
            to_status=WorkOrder.Status.REPAIRING,
            operator=request.user,
            remark='维修人员接单，开始维修',
        )

    messages.success(request, '接单成功，请完成维修后填写维修记录。')
    return redirect('repair:work_order_detail', pk=work_order.pk)


@login_required
def complete_repair(request, pk):
    """维修人员填写维修记录并提交完工。"""
    if request.user.role != User.Role.REPAIRER:
        raise PermissionDenied('只有维修人员可以提交完工。')

    work_order = get_object_or_404(WorkOrder, pk=pk)
    if work_order.repairer_id != request.user.id:
        raise PermissionDenied('不能提交未派给自己的工单。')
    if work_order.status != WorkOrder.Status.REPAIRING:
        messages.error(request, '只有维修中的工单可以填写维修记录并提交完工。')
        return redirect('repair:work_order_detail', pk=work_order.pk)

    if request.method == 'POST':
        form = RepairCompletionForm(request.POST)
        if form.is_valid():
            fault_cause = form.cleaned_data['fault_cause'].strip()
            repair_action = form.cleaned_data['repair_action'].strip()
            materials_used = form.cleaned_data['materials_used'].strip()
            now = timezone.now()

            with transaction.atomic():
                locked_order = WorkOrder.objects.select_for_update().get(
                    pk=work_order.pk
                )
                if locked_order.status != WorkOrder.Status.REPAIRING:
                    messages.error(request, '工单状态已变化，请刷新后重试。')
                    return redirect(
                        'repair:work_order_detail',
                        pk=locked_order.pk,
                    )

                locked_order.fault_cause = fault_cause
                locked_order.repair_action = repair_action
                locked_order.materials_used = materials_used
                locked_order.status = WorkOrder.Status.PENDING_ACCEPTANCE
                locked_order.completed_at = now
                locked_order.save()

                remark_parts = [f'维修内容：{repair_action}']
                if fault_cause:
                    remark_parts.insert(0, f'故障原因：{fault_cause}')
                if materials_used:
                    remark_parts.append(f'更换材料：{materials_used}')
                StatusLog.objects.create(
                    work_order=locked_order,
                    from_status=WorkOrder.Status.REPAIRING,
                    to_status=WorkOrder.Status.PENDING_ACCEPTANCE,
                    operator=request.user,
                    remark='；'.join(remark_parts),
                )

            messages.success(request, '维修记录已保存，工单已提交完工并等待学生验收。')
            return redirect('repair:work_order_detail', pk=work_order.pk)
    else:
        form = RepairCompletionForm(
            initial={
                'fault_cause': work_order.fault_cause,
                'repair_action': work_order.repair_action,
                'materials_used': work_order.materials_used,
            }
        )

    return render(
        request,
        'repair/complete_repair.html',
        {
            'work_order': work_order,
            'form': form,
        },
    )


@login_required
def accept_order(request, pk):
    """宿管受理待受理工单并派给维修人员。"""
    if not (
        request.user.role == User.Role.MANAGER
        or request.user.is_superuser
    ):
        raise PermissionDenied('只有宿管可以受理并派单。')

    work_order = get_object_or_404(WorkOrder, pk=pk)
    if work_order.status != WorkOrder.Status.PENDING:
        messages.error(request, '只有待受理工单可以受理并派单。')
        return redirect('repair:work_order_detail', pk=work_order.pk)

    if request.method == 'POST':
        form = AcceptOrderForm(request.POST)
        if form.is_valid():
            repairer = form.cleaned_data['repairer']
            contact_note = form.cleaned_data.get('contact_note', '')
            appointment_at = form.cleaned_data.get('appointment_at')
            now = timezone.now()

            with transaction.atomic():
                locked_order = WorkOrder.objects.select_for_update().get(
                    pk=work_order.pk
                )
                if locked_order.status != WorkOrder.Status.PENDING:
                    messages.error(request, '工单状态已变化，请刷新后重试。')
                    return redirect(
                        'repair:work_order_detail',
                        pk=locked_order.pk,
                    )

                locked_order.repairer = repairer
                locked_order.status = WorkOrder.Status.ASSIGNED
                locked_order.accepted_at = now
                locked_order.assigned_at = now
                locked_order.contact_note = contact_note
                locked_order.appointment_at = appointment_at
                locked_order.save()

                remark_parts = [
                    f'受理并派给{repairer.real_name or repairer.username}'
                ]
                if contact_note:
                    remark_parts.append(f'联系备注：{contact_note}')
                if appointment_at:
                    local_appointment = (
                        timezone.localtime(appointment_at)
                        if timezone.is_aware(appointment_at)
                        else appointment_at
                    )
                    remark_parts.append(
                        f'约定上门：{local_appointment:%Y-%m-%d %H:%M}'
                    )

                StatusLog.objects.create(
                    work_order=locked_order,
                    from_status=WorkOrder.Status.PENDING,
                    to_status=WorkOrder.Status.ASSIGNED,
                    operator=request.user,
                    remark='；'.join(remark_parts),
                )

            messages.success(
                request,
                f'工单已派给 {repairer.real_name or repairer.username}。',
            )
            return redirect(
                'repair:work_order_detail',
                pk=work_order.pk,
            )
    else:
        form = AcceptOrderForm(
            initial={
                'contact_note': work_order.contact_note,
                'appointment_at': work_order.appointment_at,
            }
        )

    has_repairers = User.objects.filter(
        role=User.Role.REPAIRER,
        is_active=True,
    ).exists()
    return render(
        request,
        'repair/accept_order.html',
        {
            'work_order': work_order,
            'form': form,
            'has_repairers': has_repairers,
        },
    )


@login_required
def reject_order(request, pk):
    """宿管驳回待受理工单。"""
    if not (
        request.user.role == User.Role.MANAGER
        or request.user.is_superuser
    ):
        raise PermissionDenied('只有宿管可以驳回工单。')

    work_order = get_object_or_404(WorkOrder, pk=pk)
    if work_order.status != WorkOrder.Status.PENDING:
        messages.error(request, '只有待受理工单可以驳回。')
        return redirect('repair:work_order_detail', pk=work_order.pk)

    if request.method == 'POST':
        form = RejectOrderForm(request.POST)
        if form.is_valid():
            reason = form.cleaned_data['reason']
            with transaction.atomic():
                work_order.status = WorkOrder.Status.REJECTED
                work_order.reject_reason = reason
                work_order.save()
                StatusLog.objects.create(
                    work_order=work_order,
                    from_status=WorkOrder.Status.PENDING,
                    to_status=WorkOrder.Status.REJECTED,
                    operator=request.user,
                    remark=reason,
                )
            messages.success(request, '工单已驳回，学生可以在详情页看到原因。')
            return redirect('repair:work_order_detail', pk=work_order.pk)
    else:
        form = RejectOrderForm()

    return render(
        request,
        'repair/reject_order.html',
        {'work_order': work_order, 'form': form},
    )


@login_required
def cancel_order(request, pk):
    """学生撤销自己的待受理工单。"""
    work_order = get_object_or_404(WorkOrder, pk=pk)
    if (
        request.user.role != User.Role.STUDENT
        or work_order.student_id != request.user.id
    ):
        raise PermissionDenied('只能撤销自己的报修。')
    if work_order.status != WorkOrder.Status.PENDING:
        messages.error(request, '只有待受理工单可以撤销。')
        return redirect('repair:work_order_detail', pk=work_order.pk)

    if request.method == 'POST':
        form = CancelOrderForm(request.POST)
        if form.is_valid():
            reason = form.cleaned_data.get('reason', '')
            with transaction.atomic():
                work_order.status = WorkOrder.Status.CANCELLED
                work_order.cancel_reason = reason
                work_order.save()
                StatusLog.objects.create(
                    work_order=work_order,
                    from_status=WorkOrder.Status.PENDING,
                    to_status=WorkOrder.Status.CANCELLED,
                    operator=request.user,
                    remark=reason or '学生撤销报修',
                )
            messages.success(request, '报修已撤销。')
            return redirect('repair:work_order_detail', pk=work_order.pk)
    else:
        form = CancelOrderForm()

    return render(
        request,
        'repair/cancel_order.html',
        {'work_order': work_order, 'form': form},
    )


@require_POST
def logout_view(request):
    logout(request)
    messages.info(request, '你已退出登录。')
    return redirect('repair:login')
