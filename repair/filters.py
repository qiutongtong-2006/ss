from django import forms
from django.db.models import Q

from .models import Building, RepairCategory, WorkOrder


class WorkOrderFilterForm(forms.Form):
    status = forms.ChoiceField(
        label='状态',
        required=False,
        choices=[('', '全部状态')] + list(WorkOrder.Status.choices),
    )
    building = forms.ModelChoiceField(
        label='楼栋',
        required=False,
        queryset=Building.objects.none(),
        empty_label='全部楼栋',
    )
    category = forms.ModelChoiceField(
        label='报修类别',
        required=False,
        queryset=RepairCategory.objects.none(),
        empty_label='全部类别',
    )
    q = forms.CharField(
        label='关键词',
        required=False,
        widget=forms.TextInput(
            attrs={'placeholder': '工单号 / 房间号 / 学生姓名'}
        ),
    )

    def __init__(self, *args, include_active=False, **kwargs):
        super().__init__(*args, **kwargs)
        if include_active:
            self.fields['status'].choices = [
                ('', '全部状态'),
                ('active', '当前任务'),
                *WorkOrder.Status.choices,
            ]
        self.fields['building'].queryset = Building.objects.all().order_by('name')
        self.fields['category'].queryset = RepairCategory.objects.all().order_by('name')

        for name, field in self.fields.items():
            css_class = 'form-control' if name == 'q' else 'form-select'
            field.widget.attrs.setdefault('class', css_class)


def filter_work_orders(queryset, data=None, include_active=False):
    """按 GET 参数过滤工单，返回过滤后的查询集和绑定后的表单。"""
    form = WorkOrderFilterForm(data or None, include_active=include_active)
    if form.is_valid():
        status = form.cleaned_data.get('status')
        building = form.cleaned_data.get('building')
        category = form.cleaned_data.get('category')
        keyword = form.cleaned_data.get('q', '').strip()

        if status == 'active':
            queryset = queryset.filter(
                status__in=[
                    WorkOrder.Status.ASSIGNED,
                    WorkOrder.Status.REPAIRING,
                ]
            )
        elif status:
            queryset = queryset.filter(status=status)
        if building:
            queryset = queryset.filter(building=building)
        if category:
            queryset = queryset.filter(category=category)
        if keyword:
            queryset = queryset.filter(
                Q(order_no__icontains=keyword)
                | Q(room_no__icontains=keyword)
                | Q(contact_phone__icontains=keyword)
                | Q(student__username__icontains=keyword)
                | Q(student__real_name__icontains=keyword)
            )

    return queryset, form
