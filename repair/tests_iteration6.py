from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    Building,
    RepairCategory,
    StatusLog,
    User,
    WorkOrder,
    WorkOrderSequence,
    generate_order_no,
)


class OrderNumberSequenceTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            username='20262001',
            password='student-pass-123',
            role=User.Role.STUDENT,
            real_name='序号测试学生',
        )
        self.building = Building.objects.create(name='20号楼')
        self.category = RepairCategory.objects.create(name='序号测试分类')

    def create_order(self, order_no=None, room_no='101'):
        return WorkOrder.objects.create(
            order_no=order_no or '',
            student=self.student,
            building=self.building,
            room_no=room_no,
            contact_phone='13800000000',
            category=self.category,
            description='工单序号测试。',
        )

    def test_generated_order_numbers_are_sequential(self):
        first = self.create_order(room_no='101')
        second = self.create_order(room_no='102')
        date_part = timezone.localdate().strftime('%Y%m%d')

        self.assertEqual(first.order_no, f'BX{date_part}0001')
        self.assertEqual(second.order_no, f'BX{date_part}0002')
        self.assertEqual(
            WorkOrderSequence.objects.get(
                service_date=timezone.localdate()
            ).last_value,
            2,
        )

    def test_sequence_continues_after_existing_order_numbers(self):
        date_part = timezone.localdate().strftime('%Y%m%d')
        self.create_order(
            order_no=f'BX{date_part}0042',
            room_no='201',
        )

        generated = generate_order_no()

        self.assertEqual(generated, f'BX{date_part}0043')


class DuplicateWorkOrderWarningTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            username='20262101',
            password='student-pass-123',
            role=User.Role.STUDENT,
            real_name='重复报修测试学生',
        )
        self.building = Building.objects.create(name='21号楼')
        self.category = RepairCategory.objects.create(name='重复测试分类')
        self.other_category = RepairCategory.objects.create(name='其他分类')
        self.existing_order = WorkOrder.objects.create(
            student=self.student,
            building=self.building,
            room_no='301',
            contact_phone='13800000000',
            category=self.category,
            description='已有未完成报修。',
            status=WorkOrder.Status.PENDING,
        )
        self.client.force_login(self.student)

    def submit_payload(self, **overrides):
        payload = {
            'building': self.building.pk,
            'room_no': '301',
            'contact_phone': '13800000000',
            'category': self.category.pk,
            'description': '疑似重复的报修。',
            'remark': '',
        }
        payload.update(overrides)
        return payload

    def test_duplicate_warning_requires_explicit_confirmation(self):
        response = self.client.post(
            reverse('repair:submit_repair'),
            self.submit_payload(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '可能重复报修')
        self.assertContains(response, '确认仍要提交')
        self.assertContains(response, 'name="confirm_duplicate"')
        self.assertEqual(
            WorkOrder.objects.filter(room_no='301').count(),
            1,
        )

        response = self.client.post(
            reverse('repair:submit_repair'),
            self.submit_payload(confirm_duplicate='1'),
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            WorkOrder.objects.filter(room_no='301').count(),
            2,
        )

    def test_closed_or_different_repairs_do_not_trigger_warning(self):
        self.existing_order.status = WorkOrder.Status.COMPLETED
        self.existing_order.save()

        completed_response = self.client.post(
            reverse('repair:submit_repair'),
            self.submit_payload(description='已完成后的新报修。'),
        )
        different_category_response = self.client.post(
            reverse('repair:submit_repair'),
            self.submit_payload(
                category=self.other_category.pk,
                description='不同分类的新报修。',
            ),
        )
        different_room_response = self.client.post(
            reverse('repair:submit_repair'),
            self.submit_payload(
                room_no='302',
                description='不同房间的新报修。',
            ),
        )

        for response in (
            completed_response,
            different_category_response,
            different_room_response,
        ):
            with self.subTest(response=response):
                self.assertEqual(response.status_code, 302)
        self.assertEqual(WorkOrder.objects.count(), 4)

    def test_closed_statuses_are_not_treated_as_duplicates(self):
        for status in (
            WorkOrder.Status.REJECTED,
            WorkOrder.Status.CANCELLED,
        ):
            with self.subTest(status=status):
                order = self.existing_order
                order.status = status
                order.save()
                WorkOrder.objects.exclude(pk=order.pk).filter(
                    room_no='301'
                ).delete()

                response = self.client.post(
                    reverse('repair:submit_repair'),
                    self.submit_payload(
                        description=f'{status} 后的新报修。',
                    ),
                )
                self.assertEqual(response.status_code, 302)


class PendingOrderTransitionTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            username='20262201',
            password='student-pass-123',
            role=User.Role.STUDENT,
            real_name='待受理学生',
        )
        self.manager = User.objects.create_user(
            username='GL2201',
            password='manager-pass-123',
            role=User.Role.MANAGER,
            real_name='待受理宿管',
        )
        self.building = Building.objects.create(name='22号楼')
        self.category = RepairCategory.objects.create(name='状态测试分类')

    def create_order(self):
        return WorkOrder.objects.create(
            student=self.student,
            building=self.building,
            room_no='401',
            contact_phone='13800000000',
            category=self.category,
            description='待受理状态测试。',
            status=WorkOrder.Status.PENDING,
        )

    def test_manager_rejects_pending_order_with_one_log(self):
        order = self.create_order()
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse('repair:reject_order', args=[order.pk]),
            {'reason': '重复报修。'},
        )

        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, WorkOrder.Status.REJECTED)
        self.assertEqual(order.reject_reason, '重复报修。')
        self.assertEqual(StatusLog.objects.filter(work_order=order).count(), 1)

    def test_student_cancels_pending_order_with_one_log(self):
        order = self.create_order()
        self.client.force_login(self.student)

        response = self.client.post(
            reverse('repair:cancel_order', args=[order.pk]),
            {'reason': '问题自行解决。'},
        )

        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, WorkOrder.Status.CANCELLED)
        self.assertEqual(order.cancel_reason, '问题自行解决。')
        self.assertEqual(StatusLog.objects.filter(work_order=order).count(), 1)


class InvalidRoleAuthenticationTests(TestCase):
    def setUp(self):
        self.invalid_user = User.objects.create_user(
            username='INVALID-ROLE',
            password='invalid-pass-123',
            role='invalid',
            real_name='异常角色',
        )
        self.valid_user = User.objects.create_user(
            username='20262301',
            password='student-pass-123',
            role=User.Role.STUDENT,
            real_name='正常角色',
        )

    def test_valid_role_can_still_log_in(self):
        response = self.client.post(
            reverse('repair:login'),
            {
                'username': self.valid_user.username,
                'password': 'student-pass-123',
            },
        )

        self.assertRedirects(response, reverse('repair:home'))
        self.assertEqual(
            int(self.client.session['_auth_user_id']),
            self.valid_user.pk,
        )

    def test_invalid_role_cannot_log_in(self):
        response = self.client.post(
            reverse('repair:login'),
            {
                'username': self.invalid_user.username,
                'password': 'invalid-pass-123',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '账号角色配置异常')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_invalid_role_existing_session_is_logged_out_from_home(self):
        self.client.force_login(self.invalid_user)

        response = self.client.get(reverse('repair:home'))

        self.assertRedirects(response, reverse('repair:login'))
        self.assertNotIn('_auth_user_id', self.client.session)
