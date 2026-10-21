from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .filters import filter_work_orders
from .forms import StudentRegistrationForm, WorkOrderSubmitForm
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
    work_order = get_object_or_404(WorkOrder, pk=pk)

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

    return render(
        request,
        'repair/work_order_detail.html',
        {'work_order': work_order},
    )


@require_POST
def logout_view(request):
    logout(request)
    messages.info(request, '你已退出登录。')
    return redirect('repair:login')
