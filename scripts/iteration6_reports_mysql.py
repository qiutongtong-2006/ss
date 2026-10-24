"""Verify the report dashboard against real MySQL and roll data back."""

import logging
import os
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ss.settings')

import django

django.setup()

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')
logging.disable(logging.CRITICAL)

from django.db import transaction  # noqa: E402
from django.test import Client  # noqa: E402
from django.urls import reverse  # noqa: E402
from django.utils import timezone  # noqa: E402

from repair.models import (  # noqa: E402
    Building,
    RepairCategory,
    User,
    WorkOrder,
)
from repair.reports import build_report  # noqa: E402


def run():
    with transaction.atomic():
        stamp = timezone.now().strftime('%m%d%H%M%S')
        manager = User.objects.create_user(
            username=f'report6m{stamp}',
            password='test-pass-123',
            role=User.Role.MANAGER,
            real_name='报表验证宿管',
        )
        student = User.objects.create_user(
            username=f'report6s{stamp}',
            password='test-pass-123',
            role=User.Role.STUDENT,
            real_name='报表验证学生',
        )
        building = Building.objects.create(name=f'报表楼{stamp}')
        category_completed = RepairCategory.objects.create(
            name=f'报表完成分类{stamp}'
        )
        category_pending = RepairCategory.objects.create(
            name=f'报表处理中分类{stamp}',
            is_active=False,
        )

        before = build_report('all')
        completed_order = WorkOrder.objects.create(
            order_no=f'RPT{stamp}A',
            student=student,
            building=building,
            room_no='901',
            contact_phone='13800000000',
            category=category_completed,
            description='MySQL统计报表已完成工单。',
            status=WorkOrder.Status.COMPLETED,
        )
        pending_order = WorkOrder.objects.create(
            order_no=f'RPT{stamp}B',
            student=student,
            building=building,
            room_no='902',
            contact_phone='13800000000',
            category=category_pending,
            description='MySQL统计报表处理中工单。',
            status=WorkOrder.Status.PENDING,
        )
        overdue_order = WorkOrder.objects.create(
            order_no=f'RPT{stamp}C',
            student=student,
            building=building,
            room_no='903',
            contact_phone='13800000000',
            category=category_pending,
            description='MySQL统计报表超时未受理工单。',
            status=WorkOrder.Status.PENDING,
        )
        WorkOrder.objects.filter(pk=overdue_order.pk).update(
            created_at=timezone.now() - timedelta(hours=25)
        )
        after = build_report('all')
        category_totals = {
            row['name']: row['total'] for row in after['category_rows']
        }

        client = Client()
        client.force_login(manager)
        report_page = client.get(
            reverse('repair:report_dashboard'),
            {'range': 'all'},
        )
        manager_pool = client.get(reverse('repair:manager_orders'))
        overdue_filter = client.get(
            reverse('repair:manager_orders'),
            {
                'status': 'overdue',
                'building': building.pk,
                'category': category_pending.pk,
                'q': overdue_order.order_no,
            },
        )
        client.force_login(student)
        student_denied = client.get(reverse('repair:report_dashboard'))

        assert after['total'] == before['total'] + 3
        assert after['completed'] == before['completed'] + 1
        assert after['processing'] == before['processing'] + 2
        assert after['overdue'] == before['overdue'] + 1
        assert category_totals[category_completed.name] >= 1
        assert category_totals[category_pending.name] >= 1
        assert report_page.status_code == 200
        assert report_page.content.count(b'RPT') == 0
        assert '超时未受理'.encode() in report_page.content
        assert manager_pool.status_code == 200
        assert '超过 24 小时仍未受理'.encode() in manager_pool.content
        assert overdue_filter.status_code == 200
        assert overdue_order.order_no.encode() in overdue_filter.content
        assert student_denied.status_code == 403
        assert WorkOrder.objects.filter(
            pk=completed_order.pk
        ).exists()
        assert WorkOrder.objects.filter(pk=pending_order.pk).exists()

        print(
            '报修总量 +3 | 已完成 +1 | 处理中 +2 | 超时未受理 +1'
        )
        print('宿管报表页=200 | 红色提醒可见 | 超时筛选命中 | 学生访问=403')
        transaction.set_rollback(True)

    print('MySQL 统计报表验证通过，临时数据已回滚。')


if __name__ == '__main__':
    run()
