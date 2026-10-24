from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Case, Count, F, IntegerField, Q, Value, When
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .filters import STUDENT_PROCESSING_STATUSES, filter_work_orders
from .forms import (
    AcceptanceEvaluationForm,
    AcceptanceReturnForm,
    AcceptOrderForm,
    CancelOrderForm,
    RepairCompletionForm,
    RejectOrderForm,
    StudentRegistrationForm,
    WorkOrderSubmitForm,
)
from .models import (
    Evaluation,
    OPEN_WORK_ORDER_STATUSES,
    RepairRecord,
    StatusLog,
    User,
    WorkOrder,
    WorkOrderImage,
)
from .permissions import (
    is_assigned_repairer,
    is_manager_user,
    is_student_owner,
    require_assigned_repairer,
    require_student_owner,
    require_work_order_access,
    role_required,
)


def paginate_work_orders(queryset, params):
    """分页并把当前筛选条件保留到翻页链接中。"""
    page_obj = Paginator(queryset, 20).get_page(params.get('page'))
    query_params = params.copy()
    query_params.pop('page', None)
    return page_obj, query_params.urlencode()


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
    if request.user.role not in User.Role.values:
        logout(request)
        messages.error(request, '账号角色配置异常，请联系宿管或系统管理员。')
        return redirect('repair:login')

    student_summary = None
    if request.user.role == User.Role.STUDENT:
        student_summary = WorkOrder.objects.filter(
            student=request.user
        ).aggregate(
            pending_acceptance=Count(
                'id',
                filter=Q(status=WorkOrder.Status.PENDING_ACCEPTANCE),
            ),
            pending_processing=Count(
                'id',
                filter=Q(status__in=STUDENT_PROCESSING_STATUSES),
            ),
            returned=Count(
                'id',
                filter=Q(
                    status=WorkOrder.Status.REPAIRING,
                    return_count__gt=0,
                ),
            ),
        )
    return render(
        request,
        'repair/home.html',
        {'student_summary': student_summary},
    )


@role_required(User.Role.STUDENT)
def my_orders(request):
    """学生查看自己的报修列表。"""
    queryset = WorkOrder.objects.filter(student=request.user).select_related(
        'building',
        'category',
        'repairer',
    )
    params = request.GET.copy()
    work_orders, filter_form = filter_work_orders(
        queryset,
        params,
        include_active=True,
        active_label='处理中',
        active_statuses=STUDENT_PROCESSING_STATUSES,
    )
    page_obj, filter_query = paginate_work_orders(work_orders, params)
    return render(
        request,
        'repair/my_orders.html',
        {
            'work_orders': page_obj,
            'page_obj': page_obj,
            'filter_query': filter_query,
            'filter_form': filter_form,
        },
    )


@role_required(User.Role.REPAIRER)
def repairer_orders(request):
    """维修人员查看派给自己的任务。"""
    params = request.GET.copy()
    if 'status' not in params:
        params['status'] = 'active'

    queryset = (
        WorkOrder.objects.filter(repairer=request.user)
        .select_related(
            'student',
            'building',
            'category',
            'repairer',
        )
        .annotate(
            task_priority=Case(
                When(status=WorkOrder.Status.ASSIGNED, then=Value(0)),
                When(status=WorkOrder.Status.REPAIRING, then=Value(1)),
                When(
                    status=WorkOrder.Status.PENDING_ACCEPTANCE,
                    then=Value(2),
                ),
                default=Value(3),
                output_field=IntegerField(),
            )
        )
        .order_by(
            'task_priority',
            F('appointment_at').asc(nulls_last=True),
            '-assigned_at',
        )
    )
    work_orders, filter_form = filter_work_orders(
        queryset,
        params,
        include_active=True,
    )
    page_obj, filter_query = paginate_work_orders(work_orders, params)
    summary = WorkOrder.objects.filter(repairer=request.user).aggregate(
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
            'work_orders': page_obj,
            'page_obj': page_obj,
            'filter_query': filter_query,
            'filter_form': filter_form,
            'summary': summary,
        },
    )


@role_required(User.Role.MANAGER, allow_superuser=True)
def manager_orders(request):
    """宿管工单池，默认显示待受理工单。"""
    params = request.GET.copy()
    if 'status' not in params:
        params['status'] = WorkOrder.Status.PENDING

    queryset = WorkOrder.objects.select_related(
        'student',
        'building',
        'category',
        'repairer',
    )
    work_orders, filter_form = filter_work_orders(queryset, params)
    page_obj, filter_query = paginate_work_orders(work_orders, params)
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
            'work_orders': page_obj,
            'page_obj': page_obj,
            'filter_query': filter_query,
            'filter_form': filter_form,
            'summary': summary,
        },
    )


@role_required(User.Role.STUDENT)
def submit_repair(request):
    """学生提交报修，并保存现场照片。"""
    if request.method == 'POST':
        form = WorkOrderSubmitForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            building = form.cleaned_data['building']
            room_no = form.cleaned_data['room_no']
            category = form.cleaned_data['category']
            duplicate_orders = WorkOrder.objects.filter(
                building=building,
                room_no=room_no,
                category=category,
                status__in=OPEN_WORK_ORDER_STATUSES,
            )
            duplicate_count = duplicate_orders.count()
            if (
                duplicate_count
                and request.POST.get('confirm_duplicate') != '1'
            ):
                return render(
                    request,
                    'repair/submit_repair.html',
                    {
                        'form': form,
                        'duplicate_count': duplicate_count,
                    },
                )

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
            'evaluation__student',
        ).prefetch_related(
            'repair_records__repairer',
            'status_logs__operator',
        ),
        pk=pk,
    )

    require_work_order_access(request.user, work_order)

    student_owner = is_student_owner(request.user, work_order)
    manager = is_manager_user(request.user)
    repairer_assigned = is_assigned_repairer(request.user, work_order)
    status_logs = work_order.status_logs.select_related('operator')
    repair_records = work_order.repair_records.all()
    evaluation = getattr(work_order, 'evaluation', None)

    return render(
        request,
        'repair/work_order_detail.html',
        {
            'work_order': work_order,
            'status_logs': status_logs,
            'repair_records': repair_records,
            'evaluation': evaluation,
            'can_cancel': (
                student_owner
                and work_order.status == WorkOrder.Status.PENDING
            ),
            'can_manage': (
                manager
                and work_order.status == WorkOrder.Status.PENDING
            ),
            'can_start_repair': (
                repairer_assigned
                and work_order.status == WorkOrder.Status.ASSIGNED
            ),
            'can_complete_repair': (
                repairer_assigned
                and work_order.status == WorkOrder.Status.REPAIRING
            ),
            'can_accept_result': (
                student_owner
                and work_order.status == WorkOrder.Status.PENDING_ACCEPTANCE
            ),
        },
    )


@role_required(User.Role.REPAIRER)
@require_POST
def start_repair(request, pk):
    """维修人员接单，将工单从已派单转为维修中。"""
    work_order = get_object_or_404(WorkOrder, pk=pk)
    require_assigned_repairer(request.user, work_order, '不能接未派给自己的工单。')
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


@role_required(User.Role.REPAIRER)
def complete_repair(request, pk):
    """维修人员填写维修记录并提交完工。"""
    work_order = get_object_or_404(WorkOrder, pk=pk)
    require_assigned_repairer(
        request.user,
        work_order,
        '不能提交未派给自己的工单。',
    )
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

                locked_order.status = WorkOrder.Status.PENDING_ACCEPTANCE
                locked_order.completed_at = now
                locked_order.save()

                RepairRecord.objects.create(
                    work_order=locked_order,
                    repairer=request.user,
                    fault_cause=fault_cause,
                    repair_action=repair_action,
                    materials_used=materials_used,
                    completed_at=now,
                )
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
        form = RepairCompletionForm()

    return render(
        request,
        'repair/complete_repair.html',
        {
            'work_order': work_order,
            'form': form,
        },
    )


@role_required(User.Role.STUDENT)
def acceptance_result(request, pk):
    """学生验收通过，并对已完工工单提交一次性评价。"""
    work_order = get_object_or_404(
        WorkOrder.objects.select_related(
            'student',
            'building',
            'category',
            'repairer',
        ).prefetch_related('repair_records__repairer'),
        pk=pk,
    )
    require_student_owner(request.user, work_order, '只能验收自己的报修。')
    if work_order.status != WorkOrder.Status.PENDING_ACCEPTANCE:
        messages.error(request, '只有待验收工单可以确认修复。')
        return redirect('repair:work_order_detail', pk=work_order.pk)

    if request.method == 'POST':
        form = AcceptanceEvaluationForm(request.POST)
        if form.is_valid():
            rating = form.cleaned_data['rating']
            comment = form.cleaned_data['comment'].strip()
            now = timezone.now()

            with transaction.atomic():
                locked_order = WorkOrder.objects.select_for_update().get(
                    pk=work_order.pk
                )
                if locked_order.status != WorkOrder.Status.PENDING_ACCEPTANCE:
                    messages.error(request, '工单状态已变化，请刷新后重试。')
                    return redirect(
                        'repair:work_order_detail',
                        pk=locked_order.pk,
                    )
                if Evaluation.objects.filter(work_order_id=locked_order.pk).exists():
                    messages.error(request, '该工单已经提交过评价。')
                    return redirect(
                        'repair:work_order_detail',
                        pk=locked_order.pk,
                    )

                locked_order.status = WorkOrder.Status.COMPLETED
                locked_order.verified_at = now
                locked_order.save()
                Evaluation.objects.create(
                    work_order=locked_order,
                    student=request.user,
                    rating=rating,
                    comment=comment,
                )
                StatusLog.objects.create(
                    work_order=locked_order,
                    from_status=WorkOrder.Status.PENDING_ACCEPTANCE,
                    to_status=WorkOrder.Status.COMPLETED,
                    operator=request.user,
                    remark=f'学生验收通过；评分 {rating} 星',
                )

            messages.success(request, '验收完成，感谢你的评价。')
            return redirect('repair:work_order_detail', pk=work_order.pk)
    else:
        form = AcceptanceEvaluationForm()

    latest_record = work_order.repair_records.last()
    return render(
        request,
        'repair/acceptance_result.html',
        {
            'work_order': work_order,
            'form': form,
            'latest_record': latest_record,
        },
    )


@role_required(User.Role.STUDENT)
def return_repair(request, pk):
    """学生退回未修复的工单，由原维修人员继续处理。"""
    work_order = get_object_or_404(
        WorkOrder.objects.select_related(
            'student',
            'building',
            'category',
            'repairer',
        ).prefetch_related('repair_records__repairer'),
        pk=pk,
    )
    require_student_owner(request.user, work_order, '只能退回自己的报修。')
    if work_order.status != WorkOrder.Status.PENDING_ACCEPTANCE:
        messages.error(request, '只有待验收工单可以退回返修。')
        return redirect('repair:work_order_detail', pk=work_order.pk)

    if request.method == 'POST':
        form = AcceptanceReturnForm(request.POST)
        if form.is_valid():
            reason = form.cleaned_data['reason'].strip()

            with transaction.atomic():
                locked_order = WorkOrder.objects.select_for_update().get(
                    pk=work_order.pk
                )
                if locked_order.status != WorkOrder.Status.PENDING_ACCEPTANCE:
                    messages.error(request, '工单状态已变化，请刷新后重试。')
                    return redirect(
                        'repair:work_order_detail',
                        pk=locked_order.pk,
                    )

                locked_order.status = WorkOrder.Status.REPAIRING
                locked_order.return_count += 1
                locked_order.save()
                StatusLog.objects.create(
                    work_order=locked_order,
                    from_status=WorkOrder.Status.PENDING_ACCEPTANCE,
                    to_status=WorkOrder.Status.REPAIRING,
                    operator=request.user,
                    remark=f'验收未通过，退回返修：{reason}',
                )

            messages.warning(
                request,
                '工单已退回维修，维修人员会继续处理。',
            )
            return redirect('repair:work_order_detail', pk=work_order.pk)
    else:
        form = AcceptanceReturnForm()

    latest_record = work_order.repair_records.last()
    return render(
        request,
        'repair/return_repair.html',
        {
            'work_order': work_order,
            'form': form,
            'latest_record': latest_record,
        },
    )


@role_required(User.Role.MANAGER, allow_superuser=True)
def accept_order(request, pk):
    """宿管受理待受理工单并派给维修人员。"""
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


@role_required(User.Role.MANAGER, allow_superuser=True)
def reject_order(request, pk):
    """宿管驳回待受理工单。"""
    work_order = get_object_or_404(WorkOrder, pk=pk)
    if work_order.status != WorkOrder.Status.PENDING:
        messages.error(request, '只有待受理工单可以驳回。')
        return redirect('repair:work_order_detail', pk=work_order.pk)

    if request.method == 'POST':
        form = RejectOrderForm(request.POST)
        if form.is_valid():
            reason = form.cleaned_data['reason']
            with transaction.atomic():
                locked_order = WorkOrder.objects.select_for_update().get(
                    pk=work_order.pk
                )
                if locked_order.status != WorkOrder.Status.PENDING:
                    messages.error(
                        request,
                        '工单状态已变化，无法驳回。',
                    )
                    return redirect(
                        'repair:work_order_detail',
                        pk=locked_order.pk,
                    )
                locked_order.status = WorkOrder.Status.REJECTED
                locked_order.reject_reason = reason
                locked_order.save()
                StatusLog.objects.create(
                    work_order=locked_order,
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


@role_required(User.Role.STUDENT)
def cancel_order(request, pk):
    """学生撤销自己的待受理工单。"""
    work_order = get_object_or_404(WorkOrder, pk=pk)
    require_student_owner(request.user, work_order, '只能撤销自己的报修。')
    if work_order.status != WorkOrder.Status.PENDING:
        messages.error(request, '只有待受理工单可以撤销。')
        return redirect('repair:work_order_detail', pk=work_order.pk)

    if request.method == 'POST':
        form = CancelOrderForm(request.POST)
        if form.is_valid():
            reason = form.cleaned_data.get('reason', '')
            with transaction.atomic():
                locked_order = WorkOrder.objects.select_for_update().get(
                    pk=work_order.pk
                )
                if locked_order.status != WorkOrder.Status.PENDING:
                    messages.error(
                        request,
                        '工单状态已变化，无法撤销。',
                    )
                    return redirect(
                        'repair:work_order_detail',
                        pk=locked_order.pk,
                    )
                locked_order.status = WorkOrder.Status.CANCELLED
                locked_order.cancel_reason = reason
                locked_order.save()
                StatusLog.objects.create(
                    work_order=locked_order,
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
