"""Run iteration 5 permission and basic-data checks against MySQL."""

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
    StatusLog,
    User,
    WorkOrder,
)


def run():
    with transaction.atomic():
        stamp = timezone.now().strftime('%m%d%H%M%S')
        student = User.objects.create_user(
            username=f'it5s{stamp}',
            password='test-pass-123',
            role=User.Role.STUDENT,
            real_name='迭代5学生',
            phone='13800000000',
        )
        other_student = User.objects.create_user(
            username=f'it5o{stamp}',
            password='test-pass-123',
            role=User.Role.STUDENT,
            real_name='其他学生',
        )
        repairer = User.objects.create_user(
            username=f'it5r{stamp}',
            password='test-pass-123',
            role=User.Role.REPAIRER,
            real_name='迭代5维修员',
        )
        other_repairer = User.objects.create_user(
            username=f'it5x{stamp}',
            password='test-pass-123',
            role=User.Role.REPAIRER,
            real_name='其他维修员',
        )
        manager = User.objects.create_user(
            username=f'it5m{stamp}',
            password='test-pass-123',
            role=User.Role.MANAGER,
            real_name='迭代5宿管',
        )
        superuser = User.objects.create_superuser(
            username=f'it5a{stamp}',
            password='test-pass-123',
            role=User.Role.MANAGER,
            real_name='迭代5管理员',
        )
        building = Building.objects.create(name=f'迭代5楼{stamp}')
        inactive_building = Building.objects.create(
            name=f'停用楼{stamp}',
            is_active=False,
        )
        category = RepairCategory.objects.create(name=f'迭代5分类{stamp}')
        inactive_category = RepairCategory.objects.create(
            name=f'停用分类{stamp}',
            is_active=False,
        )
        now = timezone.now()
        assigned_order = WorkOrder.objects.create(
            order_no=f'IT5{stamp}A',
            student=student,
            building=building,
            room_no='601',
            contact_phone='13800000000',
            category=category,
            description='MySQL迭代5权限验证工单。',
            status=WorkOrder.Status.ASSIGNED,
            repairer=repairer,
            assigned_at=now,
        )
        other_order = WorkOrder.objects.create(
            order_no=f'IT5{stamp}B',
            student=other_student,
            building=building,
            room_no='602',
            contact_phone='13900000000',
            category=category,
            description='MySQL迭代5他人权限验证工单。',
            status=WorkOrder.Status.ASSIGNED,
            repairer=other_repairer,
            assigned_at=now,
        )
        detail_url = reverse(
            'repair:work_order_detail',
            args=[assigned_order.pk],
        )
        other_detail_url = reverse(
            'repair:work_order_detail',
            args=[other_order.pk],
        )

        client = Client()
        anonymous_redirect = client.get(reverse('repair:my_orders'))

        client.force_login(student)
        student_home = client.get(reverse('repair:home'))
        own_detail = client.get(detail_url)
        other_detail = client.get(other_detail_url)
        manager_denied = client.get(reverse('repair:manager_orders'))
        forged_inactive = client.post(
            reverse('repair:submit_repair'),
            {
                'building': inactive_building.pk,
                'room_no': '603',
                'contact_phone': '13800000000',
                'category': category.pk,
                'description': '不应创建。',
            },
        )
        forged_category = client.post(
            reverse('repair:submit_repair'),
            {
                'building': building.pk,
                'room_no': '604',
                'contact_phone': '13800000000',
                'category': inactive_category.pk,
                'description': '不应创建。',
            },
        )
        submitted = client.post(
            reverse('repair:submit_repair'),
            {
                'building': building.pk,
                'room_no': '605',
                'contact_phone': '13800000000',
                'category': category.pk,
                'description': 'MySQL迭代5基础数据提交验证。',
            },
        )

        client.force_login(repairer)
        assigned_detail = client.get(detail_url)
        other_assigned_detail = client.get(other_detail_url)
        other_assigned_action = client.post(
            reverse('repair:start_repair', args=[other_order.pk])
        )

        client.force_login(manager)
        manager_pool = client.get(reverse('repair:manager_orders'))
        manager_any_detail = client.get(other_detail_url)
        manager_student_page = client.get(reverse('repair:my_orders'))
        manager_cancel = client.post(
            reverse('repair:cancel_order', args=[assigned_order.pk]),
            {'reason': '越权撤销'},
        )

        client.force_login(superuser)
        superuser_pool = client.get(reverse('repair:manager_orders'))
        admin_building_list = client.get(
            reverse('admin:repair_building_changelist')
        )
        protected_delete = client.get(
            reverse('admin:repair_building_delete', args=[building.pk])
        )

        assigned_order.refresh_from_db()
        other_order.refresh_from_db()
        assert anonymous_redirect.status_code == 302
        assert student_home.status_code == 200
        assert own_detail.status_code == 200
        assert other_detail.status_code == 403
        assert manager_denied.status_code == 403
        assert forged_inactive.status_code == 200
        assert forged_category.status_code == 200
        assert submitted.status_code == 302
        assert WorkOrder.objects.filter(
            student=student,
            room_no='605',
            building=building,
            category=category,
        ).count() == 1
        assert not WorkOrder.objects.filter(room_no__in=('603', '604')).exists()
        assert assigned_detail.status_code == 200
        assert other_assigned_detail.status_code == 403
        assert other_assigned_action.status_code == 403
        assert other_order.status == WorkOrder.Status.ASSIGNED
        assert manager_pool.status_code == 200
        assert manager_any_detail.status_code == 200
        assert manager_student_page.status_code == 403
        assert manager_cancel.status_code == 403
        assert assigned_order.status == WorkOrder.Status.ASSIGNED
        assert not StatusLog.objects.filter(work_order=assigned_order).exists()
        assert superuser_pool.status_code == 200
        assert admin_building_list.status_code == 200
        assert protected_delete.status_code == 403
        assert Building.objects.filter(pk=building.pk).exists()

        print('匿名访问=302 | 学生本人详情=200 | 学生访问他人=403')
        print('维修员本人详情=200 | 他人任务=403 | 越权接单=403')
        print('宿管工单池=200 | 学生页面=403 | 越权撤销=403')
        print('停用楼栋/分类提交被拒 | 启用数据提交=302')
        print('超级管理员工单池=200 | Admin列表=200 | 引用删除=403')
        transaction.set_rollback(True)

    print('MySQL 迭代5权限与基础数据验证通过，临时数据已回滚。')


if __name__ == '__main__':
    run()
