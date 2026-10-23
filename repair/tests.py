from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Building, RepairCategory, StatusLog, User, WorkOrder


class RepairerWorkflowTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            username='20260001',
            password='student-pass-123',
            role=User.Role.STUDENT,
            real_name='测试学生',
        )
        self.repairer = User.objects.create_user(
            username='WX001',
            password='repairer-pass-123',
            role=User.Role.REPAIRER,
            real_name='维修员一',
        )
        self.other_repairer = User.objects.create_user(
            username='WX002',
            password='repairer-pass-123',
            role=User.Role.REPAIRER,
            real_name='维修员二',
        )
        self.manager = User.objects.create_user(
            username='manager01',
            password='manager-pass-123',
            role=User.Role.MANAGER,
            real_name='测试宿管',
        )
        self.building = Building.objects.create(name='7号楼')
        self.category = RepairCategory.objects.create(name='水电')
        self.order = self.create_order(
            order_no='BX202610230001',
            repairer=self.repairer,
            status=WorkOrder.Status.ASSIGNED,
        )

    def create_order(self, order_no, repairer=None, status=WorkOrder.Status.PENDING):
        return WorkOrder.objects.create(
            order_no=order_no,
            student=self.student,
            building=self.building,
            room_no='301',
            contact_phone='13800000000',
            category=self.category,
            description='洗手台水龙头持续漏水。',
            status=status,
            repairer=repairer,
            assigned_at=timezone.now() if repairer else None,
        )

    def test_only_assigned_orders_appear_in_repairer_task_list(self):
        other_order = self.create_order(
            order_no='BX202610230002',
            repairer=self.other_repairer,
            status=WorkOrder.Status.ASSIGNED,
        )
        self.client.force_login(self.repairer)

        response = self.client.get(reverse('repair:repairer_orders'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.order.order_no)
        self.assertNotContains(response, other_order.order_no)

    def test_non_repairer_cannot_open_task_list(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse('repair:repairer_orders'))
        self.assertEqual(response.status_code, 403)

    def test_assigned_repairer_can_start_repair(self):
        self.client.force_login(self.repairer)

        response = self.client.post(
            reverse('repair:start_repair', args=[self.order.pk])
        )

        self.assertRedirects(
            response,
            reverse('repair:work_order_detail', args=[self.order.pk]),
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, WorkOrder.Status.REPAIRING)
        self.assertIsNotNone(self.order.started_at)
        log = StatusLog.objects.get(work_order=self.order)
        self.assertEqual(log.from_status, WorkOrder.Status.ASSIGNED)
        self.assertEqual(log.to_status, WorkOrder.Status.REPAIRING)
        self.assertEqual(log.operator, self.repairer)
        self.assertIn('接单', log.remark)

    def test_other_repairer_cannot_start_order(self):
        self.client.force_login(self.other_repairer)

        response = self.client.post(
            reverse('repair:start_repair', args=[self.order.pk])
        )

        self.assertEqual(response.status_code, 403)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, WorkOrder.Status.ASSIGNED)
        self.assertIsNone(self.order.started_at)
        self.assertFalse(StatusLog.objects.filter(work_order=self.order).exists())

    def test_order_must_be_assigned_before_repairer_can_start(self):
        pending_order = self.create_order(order_no='BX202610230003')
        pending_order.repairer = self.repairer
        pending_order.save()
        self.client.force_login(self.repairer)

        response = self.client.post(
            reverse('repair:start_repair', args=[pending_order.pk])
        )

        self.assertRedirects(
            response,
            reverse('repair:work_order_detail', args=[pending_order.pk]),
        )
        pending_order.refresh_from_db()
        self.assertEqual(pending_order.status, WorkOrder.Status.PENDING)
        self.assertIsNone(pending_order.started_at)

    def test_repairer_can_submit_completion_with_record(self):
        self.order.status = WorkOrder.Status.REPAIRING
        self.order.started_at = timezone.now()
        self.order.save()
        self.client.force_login(self.repairer)

        response = self.client.post(
            reverse('repair:complete_repair', args=[self.order.pk]),
            {
                'fault_cause': '水龙头阀芯老化',
                'repair_action': '更换阀芯并测试，漏水问题已解决。',
                'materials_used': '阀芯 1 个',
            },
        )

        self.assertRedirects(
            response,
            reverse('repair:work_order_detail', args=[self.order.pk]),
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, WorkOrder.Status.PENDING_ACCEPTANCE)
        self.assertEqual(self.order.fault_cause, '水龙头阀芯老化')
        self.assertEqual(
            self.order.repair_action,
            '更换阀芯并测试，漏水问题已解决。',
        )
        self.assertEqual(self.order.materials_used, '阀芯 1 个')
        self.assertIsNotNone(self.order.completed_at)
        log = StatusLog.objects.get(work_order=self.order)
        self.assertEqual(log.from_status, WorkOrder.Status.REPAIRING)
        self.assertEqual(log.to_status, WorkOrder.Status.PENDING_ACCEPTANCE)
        self.assertEqual(log.operator, self.repairer)
        self.assertIn('维修内容', log.remark)

    def test_completion_requires_repair_content(self):
        self.order.status = WorkOrder.Status.REPAIRING
        self.order.started_at = timezone.now()
        self.order.save()
        self.client.force_login(self.repairer)

        response = self.client.post(
            reverse('repair:complete_repair', args=[self.order.pk]),
            {
                'fault_cause': '线路松动',
                'repair_action': '',
                'materials_used': '',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, WorkOrder.Status.REPAIRING)
        self.assertIsNone(self.order.completed_at)
        self.assertFalse(StatusLog.objects.filter(work_order=self.order).exists())

    def test_repairer_cannot_complete_before_starting(self):
        self.client.force_login(self.repairer)

        response = self.client.post(
            reverse('repair:complete_repair', args=[self.order.pk]),
            {
                'fault_cause': '线路松动',
                'repair_action': '重新接线',
                'materials_used': '',
            },
        )

        self.assertRedirects(
            response,
            reverse('repair:work_order_detail', args=[self.order.pk]),
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, WorkOrder.Status.ASSIGNED)
        self.assertIsNone(self.order.completed_at)

    def test_other_repairer_cannot_submit_completion(self):
        self.order.status = WorkOrder.Status.REPAIRING
        self.order.started_at = timezone.now()
        self.order.save()
        self.client.force_login(self.other_repairer)

        response = self.client.post(
            reverse('repair:complete_repair', args=[self.order.pk]),
            {
                'fault_cause': '',
                'repair_action': '未经授权提交',
                'materials_used': '',
            },
        )

        self.assertEqual(response.status_code, 403)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, WorkOrder.Status.REPAIRING)
        self.assertFalse(StatusLog.objects.filter(work_order=self.order).exists())

    def test_detail_shows_next_step_for_assigned_repairer(self):
        self.client.force_login(self.repairer)

        response = self.client.get(
            reverse('repair:work_order_detail', args=[self.order.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '接单并开始维修')

    def test_detail_shows_completion_entry_while_repairing(self):
        self.order.status = WorkOrder.Status.REPAIRING
        self.order.started_at = timezone.now()
        self.order.save()
        self.client.force_login(self.repairer)

        response = self.client.get(
            reverse('repair:work_order_detail', args=[self.order.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '填写维修记录并提交完工')
