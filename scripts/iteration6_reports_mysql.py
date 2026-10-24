"""Verify the report dashboard against real MySQL and roll data back."""

import logging
import os
import sys
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
        client.force_login(student)
        student_denied = client.get(reverse('repair:report_dashboard'))

        assert after['total'] == before['total'] + 2
        assert after['completed'] == before['completed'] + 1
        assert after['processing'] == before['processing'] + 1
        assert category_totals[category_completed.name] >= 1
        assert category_totals[category_pending.name] >= 1
        assert report_page.status_code == 200
        assert report_page.content.count(b'RPT') == 0
        assert student_denied.status_code == 403
        assert WorkOrder.objects.filter(
            pk=completed_order.pk
        ).exists()
        assert WorkOrder.objects.filter(pk=pending_order.pk).exists()

        print(
            '报修总量 +2 | 已完成 +1 | 处理中 +1 | 停用分类保留'
        )
        print('宿管报表页=200 | 学生访问=403 | 页面不暴露工单号')
        transaction.set_rollback(True)

    print('MySQL 统计报表验证通过，临时数据已回滚。')


if __name__ == '__main__':
    run()
