from datetime import datetime, time, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Building, RepairCategory, User, WorkOrder


class ReportDashboardTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            username='20263001',
            password='student-pass-123',
            role=User.Role.STUDENT,
            real_name='报表学生',
        )
        self.repairer = User.objects.create_user(
            username='WX3001',
            password='repairer-pass-123',
            role=User.Role.REPAIRER,
            real_name='报表维修员',
        )
        self.manager = User.objects.create_user(
            username='GL3001',
            password='manager-pass-123',
            role=User.Role.MANAGER,
            real_name='报表宿管',
        )
        self.superuser = User.objects.create_superuser(
            username='root-report',
            password='admin-pass-123',
            role=User.Role.MANAGER,
            real_name='报表管理员',
        )
        self.building = Building.objects.create(name='30号楼')
        self.category_a = RepairCategory.objects.create(name='水电报表')
        self.category_b = RepairCategory.objects.create(name='家具报表')
        self.inactive_category = RepairCategory.objects.create(
            name='历史停用分类',
            is_active=False,
        )
        self.order_counter = 0

    def create_order(self, category, status, days_ago=0):
        self.order_counter += 1
        order = WorkOrder.objects.create(
            order_no=f'REPORT{self.order_counter:04d}',
            student=self.student,
            building=self.building,
            room_no=f'{self.order_counter:03d}',
            contact_phone='13800000000',
            category=category,
            description=f'报表测试工单 {self.order_counter}',
            status=status,
        )
        created_at = timezone.make_aware(
            datetime.combine(
                timezone.localdate() - timedelta(days=days_ago),
                time(hour=10),
            ),
            timezone.get_current_timezone(),
        )
        WorkOrder.objects.filter(pk=order.pk).update(created_at=created_at)
        return order

    def get_report(self, range_key='7d'):
        self.client.force_login(self.manager)
        return self.client.get(
            reverse('repair:report_dashboard'),
            {'range': range_key},
        )

    def create_report_orders(self):
        self.create_order(
            self.category_a,
            WorkOrder.Status.COMPLETED,
        )
        self.create_order(
            self.category_a,
            WorkOrder.Status.REPAIRING,
        )
        self.create_order(
            self.category_b,
            WorkOrder.Status.PENDING,
        )
        self.create_order(
            self.category_b,
            WorkOrder.Status.REJECTED,
        )
        self.create_order(
            self.inactive_category,
            WorkOrder.Status.COMPLETED,
            days_ago=1,
        )
        self.create_order(
            self.category_a,
            WorkOrder.Status.COMPLETED,
            days_ago=40,
        )

    def test_report_permissions(self):
        anonymous_response = self.client.get(
            reverse('repair:report_dashboard')
        )
        self.assertEqual(anonymous_response.status_code, 302)
        self.assertIn(reverse('repair:login'), anonymous_response.url)

        for user in (self.student, self.repairer):
            self.client.force_login(user)
            with self.subTest(user=user.username):
                self.assertEqual(
                    self.client.get(
                        reverse('repair:report_dashboard')
                    ).status_code,
                    403,
                )

        for user in (self.manager, self.superuser):
            self.client.force_login(user)
            with self.subTest(user=user.username):
                self.assertEqual(
                    self.client.get(
                        reverse('repair:report_dashboard')
                    ).status_code,
                    200,
                )

    def test_last_seven_days_metrics_and_category_shares(self):
        self.create_report_orders()

        response = self.get_report('7d')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total'], 5)
        self.assertEqual(response.context['completed'], 2)
        self.assertEqual(response.context['processing'], 2)
        self.assertEqual(response.context['completion_rate'], 40.0)
        self.assertEqual(
            [
                (row['name'], row['total'], row['percentage'])
                for row in response.context['category_rows']
            ],
            [
                ('家具报表', 2, 40.0),
                ('水电报表', 2, 40.0),
                ('历史停用分类', 1, 20.0),
            ],
        )
        self.assertContains(response, '报修总量')
        self.assertContains(response, '完成率')
        self.assertContains(response, '历史停用分类')
        self.assertContains(response, '报修分类占比饼图')
        self.assertContains(response, 'conic-gradient(')
        self.assertContains(response, 'report-pie-legend')
        self.assertNotContains(response, 'echarts.min.js')
        self.assertEqual(
            response.context['category_rows'][0]['start_percentage'],
            0.0,
        )
        self.assertEqual(
            response.context['category_rows'][-1]['end_percentage'],
            100.0,
        )

    def test_all_range_includes_historical_orders(self):
        self.create_report_orders()

        response = self.get_report('all')

        self.assertEqual(response.context['total'], 6)
        self.assertEqual(response.context['completed'], 3)
        self.assertEqual(response.context['completion_rate'], 50.0)
        self.assertEqual(response.context['range_label'], '全部历史工单')

    def test_invalid_range_falls_back_to_seven_days(self):
        self.create_report_orders()

        response = self.get_report('invalid')

        self.assertEqual(response.context['range_key'], '7d')
        self.assertEqual(response.context['total'], 5)

    def test_empty_report_has_zero_metrics_and_empty_state(self):
        response = self.get_report('30d')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total'], 0)
        self.assertEqual(response.context['completed'], 0)
        self.assertEqual(response.context['processing'], 0)
        self.assertEqual(response.context['completion_rate'], 0.0)
        self.assertEqual(response.context['category_rows'], [])
        self.assertContains(response, '当前范围暂无报修数据')
        self.assertContains(response, '暂无分类数据')
        self.assertNotContains(response, 'report-pie')

    def test_manager_home_and_navigation_link_to_report(self):
        self.client.force_login(self.manager)

        response = self.client.get(reverse('repair:home'))

        self.assertEqual(response.status_code, 200)
        report_url = reverse('repair:report_dashboard')
        self.assertContains(response, report_url, count=2)
        self.assertNotContains(response, '迭代 6 视工期实现')

    def test_student_home_does_not_link_to_report(self):
        self.client.force_login(self.student)

        response = self.client.get(reverse('repair:home'))

        self.assertNotContains(response, reverse('repair:report_dashboard'))
