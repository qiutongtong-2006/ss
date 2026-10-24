from datetime import datetime, time, timedelta

from django.db.models import Count, Q
from django.utils import timezone

from .deadlines import unaccepted_overdue_cutoff
from .models import OPEN_WORK_ORDER_STATUSES, WorkOrder


REPORT_RANGE_CHOICES = (
    ('today', '今天'),
    ('7d', '最近 7 天'),
    ('30d', '最近 30 天'),
    ('all', '全部'),
)
VALID_REPORT_RANGES = {value for value, _ in REPORT_RANGE_CHOICES}
PIE_COLORS = (
    '#2563eb',
    '#0ea5e9',
    '#14b8a6',
    '#f59e0b',
    '#8b5cf6',
    '#ef4444',
    '#ec4899',
    '#84cc16',
)


def _range_bounds(range_key):
    today = timezone.localdate()
    if range_key == 'all':
        return None, None, '全部历史工单'
    if range_key == 'today':
        start_date = today
        label = f'{today:%Y-%m-%d}'
    elif range_key == '30d':
        start_date = today - timedelta(days=29)
        label = f'{start_date:%Y-%m-%d} 至 {today:%Y-%m-%d}'
    else:
        start_date = today - timedelta(days=6)
        label = f'{start_date:%Y-%m-%d} 至 {today:%Y-%m-%d}'

    current_timezone = timezone.get_current_timezone()
    start_at = timezone.make_aware(
        datetime.combine(start_date, time.min),
        current_timezone,
    )
    end_at = timezone.make_aware(
        datetime.combine(today + timedelta(days=1), time.min),
        current_timezone,
    )
    return start_at, end_at, label


def build_report(range_key='7d'):
    """汇总指定时间范围内的报修量、完成率和分类占比。"""
    if range_key not in VALID_REPORT_RANGES:
        range_key = '7d'

    start_at, end_at, range_label = _range_bounds(range_key)
    queryset = WorkOrder.objects.all()
    if start_at is not None:
        queryset = queryset.filter(
            created_at__gte=start_at,
            created_at__lt=end_at,
        )

    summary = queryset.aggregate(
        total=Count('id'),
        completed=Count(
            'id',
            filter=Q(status=WorkOrder.Status.COMPLETED),
        ),
        processing=Count(
            'id',
            filter=Q(status__in=OPEN_WORK_ORDER_STATUSES),
        ),
        overdue=Count(
            'id',
            filter=Q(
                status=WorkOrder.Status.PENDING,
                created_at__lt=unaccepted_overdue_cutoff(),
            ),
        ),
    )
    total = summary['total']
    completed = summary['completed']
    processing = summary['processing']
    overdue = summary['overdue']
    completion_rate = round(completed * 100 / total, 1) if total else 0.0

    category_rows = []
    category_counts = (
        queryset.values('category_id', 'category__name')
        .annotate(total=Count('id'))
        .order_by('-total', 'category__name')
    )
    category_counts = list(category_counts)
    start_percentage = 0.0
    for index, row in enumerate(category_counts):
        category_total = row['total']
        if index == len(category_counts) - 1:
            end_percentage = 100.0
        else:
            end_percentage = (
                start_percentage + category_total * 100 / total
                if total
                else 100.0
            )
        category_rows.append(
            {
                'id': row['category_id'],
                'name': row['category__name'],
                'total': category_total,
                'percentage': (
                    round(category_total * 100 / total, 1) if total else 0.0
                ),
                'color': PIE_COLORS[index % len(PIE_COLORS)],
                'start_percentage': round(start_percentage, 4),
                'end_percentage': round(end_percentage, 4),
            }
        )
        start_percentage = end_percentage

    return {
        'range_key': range_key,
        'range_label': range_label,
        'range_choices': REPORT_RANGE_CHOICES,
        'total': total,
        'completed': completed,
        'processing': processing,
        'overdue': overdue,
        'completion_rate': completion_rate,
        'category_rows': category_rows,
        'generated_at': timezone.now(),
    }
