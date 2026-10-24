"""Verify order-number and pending-order concurrency against MySQL."""

import logging
import os
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

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
from django.db import close_old_connections, connections  # noqa: E402
from django.test import Client  # noqa: E402
from django.urls import reverse  # noqa: E402
from django.utils import timezone  # noqa: E402

from repair.models import (  # noqa: E402
    Building,
    RepairCategory,
    StatusLog,
    User,
    WorkOrder,
    WorkOrderSequence,
)


def run_concurrent(actions):
    barrier = threading.Barrier(len(actions))

    def worker(action):
        close_old_connections()
        client = Client()
        user = User.objects.get(pk=action['user_id'])
        client.force_login(user)
        session_key = client.session.session_key
        barrier.wait(timeout=10)
        response = client.post(
            reverse(action['url_name'], args=[action['order_id']])
            if action.get('order_id')
            else reverse(action['url_name']),
            action['payload'],
        )
        close_old_connections()
        return {
            'status_code': response.status_code,
            'session_key': session_key,
        }

    with ThreadPoolExecutor(max_workers=len(actions)) as executor:
        return list(executor.map(worker, actions))


def run():
    unique = uuid.uuid4().hex[:8]
    marker = f'IT6-{unique}'
    service_date = timezone.localdate() + timedelta(days=3650)
    date_prefix = f'BX{service_date:%Y%m%d}'
    while WorkOrder.objects.filter(
        order_no__startswith=date_prefix
    ).exists():
        service_date += timedelta(days=1)
        date_prefix = f'BX{service_date:%Y%m%d}'

    WorkOrderSequence.objects.filter(service_date=service_date).delete()
    user_ids = []
    building_id = None
    category_id = None
    order_ids = []
    session_keys = []

    try:
        student = User.objects.create_user(
            username=f'it6s{unique}',
            password='test-pass-123',
            role=User.Role.STUDENT,
            real_name='迭代6学生',
            phone='13800000000',
        )
        manager = User.objects.create_user(
            username=f'it6m{unique}',
            password='test-pass-123',
            role=User.Role.MANAGER,
            real_name='迭代6宿管',
        )
        repairer = User.objects.create_user(
            username=f'it6r{unique}',
            password='test-pass-123',
            role=User.Role.REPAIRER,
            real_name='迭代6维修员',
        )
        user_ids = [student.pk, manager.pk, repairer.pk]
        building = Building.objects.create(name=f'迭代6楼{unique}')
        category = RepairCategory.objects.create(name=f'迭代6分类{unique}')
        building_id = building.pk
        category_id = category.pk

        submission_actions = [
            {
                'user_id': student.pk,
                'url_name': 'repair:submit_repair',
                'payload': {
                    'building': building.pk,
                    'room_no': f'70{index}',
                    'contact_phone': '13800000000',
                    'category': category.pk,
                    'description': f'{marker}-submit-{index}',
                },
            }
            for index in range(1, 5)
        ]
        with patch(
            'repair.models.timezone.localdate',
            return_value=service_date,
        ):
            submission_results = run_concurrent(submission_actions)
        session_keys.extend(
            result['session_key'] for result in submission_results
        )
        submitted_orders = WorkOrder.objects.filter(
            description__startswith=f'{marker}-submit-'
        )
        order_ids.extend(submitted_orders.values_list('pk', flat=True))
        submitted_numbers = list(
            submitted_orders.values_list('order_no', flat=True)
        )
        sequence = WorkOrderSequence.objects.get(service_date=service_date)

        assert all(
            result['status_code'] == 302 for result in submission_results
        )
        assert submitted_orders.count() == 4
        assert len(set(submitted_numbers)) == 4
        assert all(number.startswith(date_prefix) for number in submitted_numbers)
        assert sequence.last_value == 4

        accept_cancel_order = WorkOrder.objects.create(
            order_no=f'IT{unique}AC',
            student=student,
            building=building,
            room_no='801',
            contact_phone='13800000000',
            category=category,
            description=f'{marker}-accept-cancel',
            status=WorkOrder.Status.PENDING,
        )
        order_ids.append(accept_cancel_order.pk)
        accept_cancel_results = run_concurrent(
            [
                {
                    'user_id': manager.pk,
                    'url_name': 'repair:accept_order',
                    'order_id': accept_cancel_order.pk,
                    'payload': {'repairer': repairer.pk},
                },
                {
                    'user_id': student.pk,
                    'url_name': 'repair:cancel_order',
                    'order_id': accept_cancel_order.pk,
                    'payload': {'reason': '并发撤销。'},
                },
            ]
        )
        session_keys.extend(
            result['session_key'] for result in accept_cancel_results
        )
        accept_cancel_order.refresh_from_db()
        accept_cancel_logs = StatusLog.objects.filter(
            work_order=accept_cancel_order
        ).count()

        accept_reject_order = WorkOrder.objects.create(
            order_no=f'IT{unique}AR',
            student=student,
            building=building,
            room_no='802',
            contact_phone='13800000000',
            category=category,
            description=f'{marker}-accept-reject',
            status=WorkOrder.Status.PENDING,
        )
        order_ids.append(accept_reject_order.pk)
        accept_reject_results = run_concurrent(
            [
                {
                    'user_id': manager.pk,
                    'url_name': 'repair:accept_order',
                    'order_id': accept_reject_order.pk,
                    'payload': {'repairer': repairer.pk},
                },
                {
                    'user_id': manager.pk,
                    'url_name': 'repair:reject_order',
                    'order_id': accept_reject_order.pk,
                    'payload': {'reason': '并发驳回。'},
                },
            ]
        )
        session_keys.extend(
            result['session_key'] for result in accept_reject_results
        )
        accept_reject_order.refresh_from_db()
        accept_reject_logs = StatusLog.objects.filter(
            work_order=accept_reject_order
        ).count()

        assert all(
            result['status_code'] == 302 for result in accept_cancel_results
        )
        assert accept_cancel_order.status in (
            WorkOrder.Status.ASSIGNED,
            WorkOrder.Status.CANCELLED,
        )
        assert accept_cancel_logs == 1
        if accept_cancel_order.status == WorkOrder.Status.ASSIGNED:
            assert accept_cancel_order.repairer_id == repairer.pk
            assert accept_cancel_order.accepted_at is not None
            assert accept_cancel_order.cancel_reason == ''
        else:
            assert accept_cancel_order.repairer_id is None
            assert accept_cancel_order.accepted_at is None
            assert accept_cancel_order.cancel_reason == '并发撤销。'

        assert all(
            result['status_code'] == 302 for result in accept_reject_results
        )
        assert accept_reject_order.status in (
            WorkOrder.Status.ASSIGNED,
            WorkOrder.Status.REJECTED,
        )
        assert accept_reject_logs == 1
        if accept_reject_order.status == WorkOrder.Status.ASSIGNED:
            assert accept_reject_order.repairer_id == repairer.pk
            assert accept_reject_order.reject_reason == ''
        else:
            assert accept_reject_order.repairer_id is None
            assert accept_reject_order.reject_reason == '并发驳回。'

        print(
            '并发提交：请求={} | 工单=4 | 唯一工单号=4 | 序号={}'.format(
                [result['status_code'] for result in submission_results],
                sequence.last_value,
            )
        )
        print(
            '受理/撤销竞争：最终状态={} | 状态日志=1'.format(
                accept_cancel_order.get_status_display()
            )
        )
        print(
            '受理/驳回竞争：最终状态={} | 状态日志=1'.format(
                accept_reject_order.get_status_display()
            )
        )
    finally:
        connections.close_all()
        WorkOrder.objects.filter(description__startswith=marker).delete()
        if order_ids:
            WorkOrder.objects.filter(pk__in=order_ids).delete()
        WorkOrderSequence.objects.filter(service_date=service_date).delete()
        if user_ids:
            User.objects.filter(pk__in=user_ids).delete()
        if building_id:
            Building.objects.filter(pk=building_id).delete()
        if category_id:
            RepairCategory.objects.filter(pk=category_id).delete()
        if session_keys:
            Session.objects.filter(session_key__in=session_keys).delete()

    print('MySQL 迭代6一致性与并发验证通过，临时数据已清理。')


if __name__ == '__main__':
    run()
