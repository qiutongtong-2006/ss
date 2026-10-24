from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Building, RepairCategory, User, WorkOrder


class OverdueUnacceptedTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            username='20264001',
            password='student-pass-123',
            role=User.Role.STUDENT,
            real_name='超时测试学生',
        )
        self.manager = User.objects.create_user(
            username='GL4001',
            password='manager-pass-123',
            role=User.Role.MANAGER,
            real_name='超时测试宿管',
        )
        self.building = Building.objects.create(name='40号楼')
        self.category = RepairCategory.objects.create(name='超时测试分类')
        self.order_counter = 0

    def create_order(self, status, hours_ago):
        self.order_counter += 1
        order = WorkOrder.objects.create(
            order_no=f'OVERDUE{self.order_counter:04d}',
            student=self.student,
            building=self.building,
            room_no=f'{self.order_counter:03d}',
            contact_phone='13800000000',
            category=self.category,
            description=f'超时测试工单 {self.order_counter}',
            status=status,
        )
        WorkOrder.objects.filter(pk=order.pk).update(
            created_at=timezone.now() - timedelta(hours=hours_ago)
        )
        order.refresh_from_db()
        return order

    def test_manager_pool_shows_overdue_alert_and_badges(self):
        overdue_order = self.create_order(
            WorkOrder.Status.PENDING,
            hours_ago=25,
        )
        self.create_order(WorkOrder.Status.PENDING, hours_ago=23)
        self.create_order(WorkOrder.Status.ASSIGNED, hours_ago=48)
        self.create_order(WorkOrder.Status.COMPLETED, hours_ago=48)
        self.client.force_login(self.manager)

        response = self.client.get(reverse('repair:manager_orders'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['summary']['overdue'], 1)
        self.assertContains(
            response,
            '有 1 条报修超过 24 小时仍未受理',
        )
        self.assertContains(
            response,
            f"{reverse('repair:manager_orders')}?status=overdue",
        )
        self.assertContains(response, '超时未受理')
        listed_orders = {
            order.pk: order
            for order in response.context['page_obj'].object_list
        }
        self.assertEqual(len(listed_orders), 2)
        self.assertTrue(listed_orders[overdue_order.pk].is_overdue)
        self.assertEqual(
            sum(order.is_overdue for order in listed_orders.values()),
            1,
        )

    def test_overdue_filter_only_returns_unaccepted_orders(self):
        overdue_order = self.create_order(
            WorkOrder.Status.PENDING,
            hours_ago=30,
        )
        self.create_order(WorkOrder.Status.PENDING, hours_ago=10)
        self.create_order(WorkOrder.Status.ASSIGNED, hours_ago=30)
        self.client.force_login(self.manager)

        response = self.client.get(
            reverse('repair:manager_orders'),
            {'status': 'overdue'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [order.pk for order in response.context['page_obj'].object_list],
            [overdue_order.pk],
        )
        self.assertIn(
            ('overdue', '超时未受理'),
            response.context['filter_form'].fields['status'].choices,
        )

    def test_report_counts_overdue_orders_in_selected_range(self):
        self.create_order(WorkOrder.Status.PENDING, hours_ago=25)
        self.create_order(WorkOrder.Status.PENDING, hours_ago=23)
        self.create_order(WorkOrder.Status.ASSIGNED, hours_ago=48)
        self.client.force_login(self.manager)

        response = self.client.get(
            reverse('repair:report_dashboard'),
            {'range': 'all'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['overdue'], 1)
        self.assertContains(response, '超时未受理')
        self.assertContains(response, '提交超过 24 小时仍未受理')

    def test_report_overdue_count_respects_selected_range(self):
        self.create_order(WorkOrder.Status.PENDING, hours_ago=48)
        self.client.force_login(self.manager)

        today_response = self.client.get(
            reverse('repair:report_dashboard'),
            {'range': 'today'},
        )
        all_response = self.client.get(
            reverse('repair:report_dashboard'),
            {'range': 'all'},
        )

        self.assertEqual(today_response.context['overdue'], 0)
        self.assertEqual(all_response.context['overdue'], 1)

    def test_pool_has_no_alert_when_no_order_is_overdue(self):
        self.create_order(WorkOrder.Status.PENDING, hours_ago=2)
        self.create_order(WorkOrder.Status.ASSIGNED, hours_ago=48)
        self.client.force_login(self.manager)

        response = self.client.get(reverse('repair:manager_orders'))

        self.assertEqual(response.context['summary']['overdue'], 0)
        self.assertNotContains(
            response,
            '条报修超过 24 小时仍未受理',
        )
