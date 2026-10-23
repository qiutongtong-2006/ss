"""Run an iteration 4 workflow against MySQL and roll the data back."""

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
    Evaluation,
    RepairCategory,
    RepairRecord,
    StatusLog,
    User,
    WorkOrder,
)


def run():
    with transaction.atomic():
        stamp = timezone.now().strftime('%m%d%H%M%S')
        student = User.objects.create_user(
            username=f'e2e4s{stamp}',
            password='test-pass-123',
            role=User.Role.STUDENT,
            real_name='迭代4验收学生',
        )
        other_student = User.objects.create_user(
            username=f'e2e4o{stamp}',
            password='test-pass-123',
            role=User.Role.STUDENT,
            real_name='其他学生',
        )
        repairer = User.objects.create_user(
            username=f'e2e4r{stamp}',
            password='test-pass-123',
            role=User.Role.REPAIRER,
            real_name='迭代4维修员',
        )
        building = Building.objects.create(name=f'E2E4楼{stamp}')
        category = RepairCategory.objects.create(name=f'E2E4分类{stamp}')
        now = timezone.now()

        def make_order(suffix):
            return WorkOrder.objects.create(
                order_no=f'E2E4{stamp}{suffix}',
                student=student,
                building=building,
                room_no='501',
                contact_phone='13700000000',
                category=category,
                description='MySQL迭代4端到端验证工单。',
                status=WorkOrder.Status.PENDING_ACCEPTANCE,
                repairer=repairer,
                accepted_at=now,
                assigned_at=now,
                started_at=now,
                completed_at=now,
            )

        direct_order = make_order('A')
        RepairRecord.objects.create(
            work_order=direct_order,
            repairer=repairer,
            repair_action='完成首次维修。',
            completed_at=now,
        )

        client = Client()
        client.force_login(student)
        acceptance_page = client.get(
            reverse('repair:acceptance_result', args=[direct_order.pk])
        )
        accepted = client.post(
            reverse('repair:acceptance_result', args=[direct_order.pk]),
            {'rating': '5', 'comment': 'MySQL验收直接通过测试。'},
        )
        direct_order.refresh_from_db()

        return_order = make_order('B')
        RepairRecord.objects.create(
            work_order=return_order,
            repairer=repairer,
            repair_action='完成首次维修。',
            completed_at=now,
        )
        returned = client.post(
            reverse('repair:return_repair', args=[return_order.pk]),
            {'reason': 'MySQL 端到端退回测试。'},
        )
        return_order.refresh_from_db()

        client.force_login(repairer)
        recompleted = client.post(
            reverse('repair:complete_repair', args=[return_order.pk]),
            {
                'fault_cause': '端到端复测',
                'repair_action': '返修后再次测试通过。',
                'materials_used': '',
            },
        )
        client.force_login(student)
        reaccepted = client.post(
            reverse('repair:acceptance_result', args=[return_order.pk]),
            {'rating': '4', 'comment': 'MySQL返修后最终验收测试。'},
        )
        return_order.refresh_from_db()

        client.force_login(other_student)
        denied = client.post(
            reverse('repair:acceptance_result', args=[return_order.pk]),
            {'rating': '5', 'comment': '越权测试'},
        )

        assert acceptance_page.status_code == 200
        assert accepted.status_code == 302
        assert direct_order.status == WorkOrder.Status.COMPLETED
        assert direct_order.verified_at is not None
        assert Evaluation.objects.filter(
            work_order=direct_order,
            rating=5,
        ).count() == 1
        assert returned.status_code == 302
        assert return_order.return_count == 1
        assert recompleted.status_code == 302
        assert reaccepted.status_code == 302
        assert return_order.status == WorkOrder.Status.COMPLETED
        assert RepairRecord.objects.filter(
            work_order=return_order
        ).count() == 2
        assert Evaluation.objects.filter(
            work_order=return_order,
            rating=4,
        ).count() == 1
        assert StatusLog.objects.filter(
            work_order=return_order
        ).count() == 3
        assert denied.status_code == 403

        print('验收页=200 | 直接验收=302 | 状态=已完成 | 评价=1')
        print('退回=302 | 返修完工=302 | 再次验收=302 | 最终状态=已完成')
        print('返修次数=1 | 维修记录=2 | 状态日志=3 | 他人访问=403')
        transaction.set_rollback(True)

    print('MySQL 迭代4端到端验证通过，临时数据已回滚。')


if __name__ == '__main__':
    run()
