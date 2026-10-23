"""Verify concurrent acceptance and return requests against MySQL."""

import logging
import os
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
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

from django.contrib.sessions.models import Session  # noqa: E402
from django.db import close_old_connections, connections, transaction  # noqa: E402
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


def submit_concurrently(url_name, order_id, user_id, payload):
    barrier = threading.Barrier(2)

    def worker(index):
        close_old_connections()
        client = Client()
        user = User.objects.get(pk=user_id)
        client.force_login(user)
        session_key = client.session.session_key
        barrier.wait(timeout=10)
        started_at = time.monotonic()
        response = client.post(
            reverse(f'repair:{url_name}', args=[order_id]),
            payload,
        )
        elapsed = time.monotonic() - started_at
        close_old_connections()
        return {
            'index': index,
            'status_code': response.status_code,
            'session_key': session_key,
            'elapsed': elapsed,
        }

    with ThreadPoolExecutor(max_workers=2) as executor:
        return list(executor.map(worker, (1, 2)))


def run():
    stamp = timezone.now().strftime('%m%d%H%M')
    unique = uuid.uuid4().hex[:8]
    order_ids = []
    user_ids = []
    building_id = None
    category_id = None
    session_keys = []

    try:
        with transaction.atomic():
            student = User.objects.create_user(
                username=f'conc4s{unique}',
                password='test-pass-123',
                role=User.Role.STUDENT,
                real_name='并发验收学生',
            )
            repairer = User.objects.create_user(
                username=f'conc4r{unique}',
                password='test-pass-123',
                role=User.Role.REPAIRER,
                real_name='并发验收维修员',
            )
            building = Building.objects.create(name=f'并发楼{stamp}{unique}')
            category = RepairCategory.objects.create(
                name=f'并发分类{stamp}{unique}'
            )
            user_ids = [student.pk, repairer.pk]
            building_id = building.pk
            category_id = category.pk
            now = timezone.now()

            def make_order(suffix):
                order = WorkOrder.objects.create(
                    order_no=f'C4{stamp}{unique}{suffix}',
                    student=student,
                    building=building,
                    room_no='601',
                    contact_phone='13600000000',
                    category=category,
                    description='真实 MySQL 并发验证工单。',
                    status=WorkOrder.Status.PENDING_ACCEPTANCE,
                    repairer=repairer,
                    accepted_at=now,
                    assigned_at=now,
                    started_at=now,
                    completed_at=now,
                )
                RepairRecord.objects.create(
                    work_order=order,
                    repairer=repairer,
                    repair_action='并发验证用维修记录。',
                    completed_at=now,
                )
                order_ids.append(order.pk)
                return order

            acceptance_order = make_order('A')
            return_order = make_order('R')

        acceptance_results = submit_concurrently(
            'acceptance_result',
            acceptance_order.pk,
            student.pk,
            {'rating': '5', 'comment': '并发验收只允许写入一条评价。'},
        )
        session_keys.extend(
            result['session_key'] for result in acceptance_results
        )
        acceptance_order.refresh_from_db()
        acceptance_evaluation_count = Evaluation.objects.filter(
            work_order_id=acceptance_order.pk
        ).count()
        acceptance_log_count = StatusLog.objects.filter(
            work_order_id=acceptance_order.pk
        ).count()

        return_results = submit_concurrently(
            'return_repair',
            return_order.pk,
            student.pk,
            {'reason': '并发退回只允许记录一次。'},
        )
        session_keys.extend(result['session_key'] for result in return_results)
        return_order.refresh_from_db()
        return_evaluation_count = Evaluation.objects.filter(
            work_order_id=return_order.pk
        ).count()
        return_log_count = StatusLog.objects.filter(
            work_order_id=return_order.pk
        ).count()

        assert all(
            result['status_code'] == 302 for result in acceptance_results
        )
        assert acceptance_order.status == WorkOrder.Status.COMPLETED
        assert acceptance_order.verified_at is not None
        assert acceptance_evaluation_count == 1
        assert acceptance_log_count == 1

        assert all(result['status_code'] == 302 for result in return_results)
        assert return_order.status == WorkOrder.Status.REPAIRING
        assert return_order.return_count == 1
        assert return_evaluation_count == 0
        assert return_log_count == 1

        print(
            '并发验收：请求={} | 最终状态=已完成 | 评价=1 | 状态日志=1'.format(
                [result['status_code'] for result in acceptance_results]
            )
        )
        print(
            '并发退回：请求={} | 最终状态=维修中 | 返修次数=1 | 状态日志=1'.format(
                [result['status_code'] for result in return_results]
            )
        )
        print(
            '请求耗时：验收={} | 退回={}'.format(
                [
                    f"{result['elapsed']:.3f}s"
                    for result in acceptance_results
                ],
                [f"{result['elapsed']:.3f}s" for result in return_results],
            )
        )
    finally:
        connections.close_all()
        if order_ids:
            WorkOrder.objects.filter(pk__in=order_ids).delete()
        if user_ids:
            User.objects.filter(pk__in=user_ids).delete()
        if building_id:
            Building.objects.filter(pk=building_id).delete()
        if category_id:
            RepairCategory.objects.filter(pk=category_id).delete()
        if session_keys:
            Session.objects.filter(session_key__in=session_keys).delete()

    print('MySQL 并发验证通过，临时工单、账号、分类和会话已清理。')


if __name__ == '__main__':
    run()
