from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    Building,
    Evaluation,
    RepairCategory,
    RepairRecord,
    StatusLog,
    User,
    WorkOrder,
)


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
        self.admin_user = User.objects.create_superuser(
            username='admin-test',
            password='admin-pass-123',
            role=User.Role.MANAGER,
            real_name='测试管理员',
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

    def test_task_list_defaults_to_current_work_and_sorts_actionable_first(self):
        repairing_order = self.create_order(
            order_no='BX202610230004',
            repairer=self.repairer,
            status=WorkOrder.Status.REPAIRING,
        )
        historical_order = self.create_order(
            order_no='BX202610230005',
            repairer=self.repairer,
            status=WorkOrder.Status.PENDING_ACCEPTANCE,
        )
        self.client.force_login(self.repairer)

        response = self.client.get(reverse('repair:repairer_orders'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [order.pk for order in response.context['page_obj'].object_list],
            [self.order.pk, repairing_order.pk],
        )
        self.assertNotContains(response, historical_order.order_no)
        self.assertContains(response, '接单')
        self.assertContains(response, '填写完工')

        response = self.client.get(
            reverse('repair:repairer_orders'),
            {'status': WorkOrder.Status.PENDING_ACCEPTANCE},
        )
        self.assertContains(response, historical_order.order_no)

    def test_task_list_is_paginated_and_keeps_default_filter(self):
        for index in range(20):
            self.create_order(
                order_no=f'BX20261024{index:04d}',
                repairer=self.repairer,
                status=WorkOrder.Status.ASSIGNED,
            )
        self.client.force_login(self.repairer)

        response = self.client.get(reverse('repair:repairer_orders'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['page_obj'].object_list), 20)
        self.assertEqual(response.context['page_obj'].paginator.count, 21)
        self.assertContains(response, 'status=active')
        self.assertContains(response, '下一页')

        response = self.client.get(
            reverse('repair:repairer_orders'),
            {'status': 'active', 'page': 2},
        )
        self.assertEqual(response.context['page_obj'].number, 2)
        self.assertEqual(len(response.context['page_obj'].object_list), 1)

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

    def test_start_repair_requires_post(self):
        self.client.force_login(self.repairer)

        response = self.client.get(
            reverse('repair:start_repair', args=[self.order.pk])
        )

        self.assertEqual(response.status_code, 405)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, WorkOrder.Status.ASSIGNED)

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
        self.assertIsNotNone(self.order.completed_at)
        record = RepairRecord.objects.get(work_order=self.order)
        self.assertEqual(record.repairer, self.repairer)
        self.assertEqual(record.fault_cause, '水龙头阀芯老化')
        self.assertEqual(record.repair_action, '更换阀芯并测试，漏水问题已解决。')
        self.assertEqual(record.materials_used, '阀芯 1 个')
        self.assertEqual(record.completed_at, self.order.completed_at)
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
        self.assertFalse(RepairRecord.objects.filter(work_order=self.order).exists())
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
        self.assertFalse(RepairRecord.objects.filter(work_order=self.order).exists())
        self.assertFalse(StatusLog.objects.filter(work_order=self.order).exists())

    def test_manager_cannot_start_or_complete_repair(self):
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse('repair:start_repair', args=[self.order.pk])
        )
        self.assertEqual(response.status_code, 403)

        self.order.status = WorkOrder.Status.REPAIRING
        self.order.save()
        response = self.client.post(
            reverse('repair:complete_repair', args=[self.order.pk]),
            {
                'fault_cause': '',
                'repair_action': '管理员不应提交',
                'materials_used': '',
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(RepairRecord.objects.filter(work_order=self.order).exists())

    def test_duplicate_completion_submit_creates_one_record(self):
        self.order.status = WorkOrder.Status.REPAIRING
        self.order.started_at = timezone.now()
        self.order.save()
        self.client.force_login(self.repairer)
        payload = {
            'fault_cause': '线路松动',
            'repair_action': '重新接线并测试',
            'materials_used': '',
        }
        url = reverse('repair:complete_repair', args=[self.order.pk])

        first_response = self.client.post(url, payload)
        second_response = self.client.post(url, payload)

        self.assertEqual(first_response.status_code, 302)
        self.assertEqual(second_response.status_code, 302)
        self.assertEqual(
            RepairRecord.objects.filter(work_order=self.order).count(),
            1,
        )
        self.assertEqual(
            StatusLog.objects.filter(work_order=self.order).count(),
            1,
        )

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

    def test_repeated_repair_keeps_previous_records(self):
        self.order.status = WorkOrder.Status.REPAIRING
        self.order.started_at = timezone.now()
        self.order.save()
        self.client.force_login(self.repairer)

        self.client.post(
            reverse('repair:complete_repair', args=[self.order.pk]),
            {
                'fault_cause': '第一次故障',
                'repair_action': '第一次维修',
                'materials_used': '材料一',
            },
        )
        self.order.status = WorkOrder.Status.REPAIRING
        self.order.save()
        self.client.post(
            reverse('repair:complete_repair', args=[self.order.pk]),
            {
                'fault_cause': '第二次故障',
                'repair_action': '第二次维修',
                'materials_used': '材料二',
            },
        )

        records = RepairRecord.objects.filter(work_order=self.order)
        self.assertEqual(records.count(), 2)
        self.assertEqual(records[0].repair_action, '第一次维修')
        self.assertEqual(records[1].repair_action, '第二次维修')

    def test_admin_cannot_edit_workflow_fields(self):
        self.client.force_login(self.admin_user)

        response = self.client.get(
            reverse('admin:repair_workorder_change', args=[self.order.pk])
        )

        self.assertEqual(response.status_code, 200)
        admin_form = response.context['adminform'].form
        for field_name in (
            'status',
            'repairer',
            'accepted_at',
            'assigned_at',
            'started_at',
            'completed_at',
            'verified_at',
        ):
            self.assertNotIn(field_name, admin_form.fields)


class AcceptanceWorkflowTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            username='20260011',
            password='student-pass-123',
            role=User.Role.STUDENT,
            real_name='验收学生',
        )
        self.other_student = User.objects.create_user(
            username='20260012',
            password='student-pass-123',
            role=User.Role.STUDENT,
            real_name='其他学生',
        )
        self.repairer = User.objects.create_user(
            username='WX011',
            password='repairer-pass-123',
            role=User.Role.REPAIRER,
            real_name='返修人员',
        )
        self.manager = User.objects.create_user(
            username='manager11',
            password='manager-pass-123',
            role=User.Role.MANAGER,
            real_name='验收宿管',
        )
        self.admin_user = User.objects.create_superuser(
            username='admin-acceptance',
            password='admin-pass-123',
            role=User.Role.MANAGER,
            real_name='验收管理员',
        )
        self.building = Building.objects.create(name='8号楼')
        self.category = RepairCategory.objects.create(name='家具')
        self.order = self.create_order()
        self.record = RepairRecord.objects.create(
            work_order=self.order,
            repairer=self.repairer,
            fault_cause='抽屉滑轨损坏',
            repair_action='更换抽屉滑轨并调试。',
            materials_used='滑轨 1 组',
            completed_at=self.order.completed_at,
        )

    def create_order(
        self,
        order_no='BX202610230011',
        status=WorkOrder.Status.PENDING_ACCEPTANCE,
        student=None,
    ):
        now = timezone.now()
        return WorkOrder.objects.create(
            order_no=order_no,
            student=student or self.student,
            building=self.building,
            room_no='402',
            contact_phone='13900000000',
            category=self.category,
            description='书桌抽屉无法正常拉出。',
            status=status,
            repairer=self.repairer,
            assigned_at=now,
            started_at=now,
            completed_at=now,
        )

    def test_student_home_shows_actionable_order_counts(self):
        self.create_order(
            order_no='BX202610230012',
            status=WorkOrder.Status.PENDING,
        )
        self.create_order(
            order_no='BX202610230013',
            status=WorkOrder.Status.ASSIGNED,
        )
        returned_order = self.create_order(
            order_no='BX202610230014',
            status=WorkOrder.Status.REPAIRING,
        )
        returned_order.return_count = 2
        returned_order.save()
        self.create_order(
            order_no='BX202610230015',
            status=WorkOrder.Status.PENDING,
            student=self.other_student,
        )
        self.client.force_login(self.student)

        response = self.client.get(reverse('repair:home'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context['student_summary'],
            {
                'pending_acceptance': 1,
                'pending_processing': 3,
                'returned': 1,
            },
        )
        self.assertContains(response, '去验收')
        self.assertContains(response, '其中 1 单正在返修。')

    def test_my_orders_links_pending_acceptance_directly_to_review(self):
        self.client.force_login(self.student)

        response = self.client.get(reverse('repair:my_orders'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '去验收')
        self.assertContains(
            response,
            reverse('repair:acceptance_result', args=[self.order.pk]),
        )

    def test_my_orders_highlights_returned_repair(self):
        self.order.status = WorkOrder.Status.REPAIRING
        self.order.return_count = 2
        self.order.save()
        self.client.force_login(self.student)

        response = self.client.get(reverse('repair:my_orders'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '返修中 · 第 2 次')
        self.assertContains(response, '上次验收未通过')
        self.assertContains(response, '查看返修进度')
        self.assertContains(response, 'order-returned-row')

    def accept(self, rating='5', comment='维修及时，抽屉已经恢复正常。'):
        return self.client.post(
            reverse('repair:acceptance_result', args=[self.order.pk]),
            {'rating': rating, 'comment': comment},
        )

    def return_order(self, reason='抽屉仍然卡住，无法完全拉出。'):
        return self.client.post(
            reverse('repair:return_repair', args=[self.order.pk]),
            {'reason': reason},
        )

    def test_student_owner_can_open_acceptance_page(self):
        self.client.force_login(self.student)

        response = self.client.get(
            reverse('repair:acceptance_result', args=[self.order.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '验收并评价')
        self.assertContains(response, self.record.repair_action)
        self.assertContains(response, '5 星 · 非常满意')

    def test_other_student_cannot_open_acceptance_or_return_page(self):
        self.client.force_login(self.other_student)

        for url_name in ('acceptance_result', 'return_repair'):
            with self.subTest(url_name=url_name):
                response = self.client.get(
                    reverse(f'repair:{url_name}', args=[self.order.pk])
                )
                self.assertEqual(response.status_code, 403)

    def test_manager_and_repairer_cannot_accept_or_return(self):
        payload = {'rating': '5', 'comment': '越权评价'}
        for user in (self.manager, self.repairer):
            self.client.force_login(user)
            for url_name in ('acceptance_result', 'return_repair'):
                with self.subTest(user=user.username, url_name=url_name):
                    response = self.client.post(
                        reverse(f'repair:{url_name}', args=[self.order.pk]),
                        payload,
                    )
                    self.assertEqual(response.status_code, 403)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, WorkOrder.Status.PENDING_ACCEPTANCE)
        self.assertFalse(Evaluation.objects.filter(work_order=self.order).exists())
        self.assertFalse(StatusLog.objects.filter(work_order=self.order).exists())

    def test_owner_accepts_and_creates_evaluation(self):
        self.client.force_login(self.student)

        response = self.accept()

        self.assertRedirects(
            response,
            reverse('repair:work_order_detail', args=[self.order.pk]),
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, WorkOrder.Status.COMPLETED)
        self.assertIsNotNone(self.order.verified_at)
        evaluation = Evaluation.objects.get(work_order=self.order)
        self.assertEqual(evaluation.student, self.student)
        self.assertEqual(evaluation.rating, 5)
        self.assertEqual(evaluation.comment, '维修及时，抽屉已经恢复正常。')
        log = StatusLog.objects.get(work_order=self.order)
        self.assertEqual(log.from_status, WorkOrder.Status.PENDING_ACCEPTANCE)
        self.assertEqual(log.to_status, WorkOrder.Status.COMPLETED)
        self.assertEqual(log.operator, self.student)
        self.assertIn('评分 5 星', log.remark)

    def test_acceptance_requires_valid_rating_and_comment(self):
        self.client.force_login(self.student)

        response = self.accept(rating='', comment='')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, WorkOrder.Status.PENDING_ACCEPTANCE)
        self.assertFalse(Evaluation.objects.filter(work_order=self.order).exists())
        self.assertFalse(StatusLog.objects.filter(work_order=self.order).exists())

    def test_rating_outside_one_to_five_is_rejected(self):
        self.client.force_login(self.student)

        for rating in ('0', '6', 'abc'):
            with self.subTest(rating=rating):
                response = self.accept(rating=rating)
                self.assertEqual(response.status_code, 200)
                self.assertIn('rating', response.context['form'].errors)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, WorkOrder.Status.PENDING_ACCEPTANCE)
        self.assertFalse(Evaluation.objects.filter(work_order=self.order).exists())

    def test_acceptance_is_blocked_outside_pending_acceptance(self):
        self.order.status = WorkOrder.Status.REPAIRING
        self.order.save()
        self.client.force_login(self.student)

        response = self.accept()

        self.assertRedirects(
            response,
            reverse('repair:work_order_detail', args=[self.order.pk]),
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, WorkOrder.Status.REPAIRING)
        self.assertFalse(Evaluation.objects.filter(work_order=self.order).exists())

    def test_repeated_acceptance_keeps_one_evaluation_and_log(self):
        self.client.force_login(self.student)

        first_response = self.accept()
        second_response = self.accept(comment='重复提交')

        self.assertEqual(first_response.status_code, 302)
        self.assertEqual(second_response.status_code, 302)
        self.assertEqual(
            Evaluation.objects.filter(work_order=self.order).count(),
            1,
        )
        self.assertEqual(
            StatusLog.objects.filter(work_order=self.order).count(),
            1,
        )

    def test_owner_can_return_for_repair(self):
        self.client.force_login(self.student)

        response = self.return_order()

        self.assertRedirects(
            response,
            reverse('repair:work_order_detail', args=[self.order.pk]),
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, WorkOrder.Status.REPAIRING)
        self.assertEqual(self.order.return_count, 1)
        self.assertIsNone(self.order.verified_at)
        self.assertFalse(Evaluation.objects.filter(work_order=self.order).exists())
        self.assertEqual(
            RepairRecord.objects.filter(work_order=self.order).count(),
            1,
        )
        log = StatusLog.objects.get(work_order=self.order)
        self.assertEqual(log.from_status, WorkOrder.Status.PENDING_ACCEPTANCE)
        self.assertEqual(log.to_status, WorkOrder.Status.REPAIRING)
        self.assertEqual(log.operator, self.student)
        self.assertIn('抽屉仍然卡住', log.remark)

    def test_return_requires_reason(self):
        self.client.force_login(self.student)

        response = self.return_order(reason='')

        self.assertEqual(response.status_code, 200)
        self.assertIn('reason', response.context['form'].errors)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, WorkOrder.Status.PENDING_ACCEPTANCE)
        self.assertEqual(self.order.return_count, 0)
        self.assertFalse(StatusLog.objects.filter(work_order=self.order).exists())

    def test_other_student_cannot_return_order(self):
        self.client.force_login(self.other_student)

        response = self.return_order()

        self.assertEqual(response.status_code, 403)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, WorkOrder.Status.PENDING_ACCEPTANCE)
        self.assertEqual(self.order.return_count, 0)

    def test_full_return_recomplete_and_reacceptance_workflow(self):
        self.client.force_login(self.student)
        self.return_order()

        self.client.force_login(self.repairer)
        response = self.client.post(
            reverse('repair:complete_repair', args=[self.order.pk]),
            {
                'fault_cause': '滑轨安装位置仍有偏差',
                'repair_action': '重新调整滑轨位置并反复测试。',
                'materials_used': '',
            },
        )
        self.assertEqual(response.status_code, 302)

        self.client.force_login(self.student)
        response = self.accept(
            rating='4',
            comment='第二次处理正常了。',
        )
        self.assertEqual(response.status_code, 302)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, WorkOrder.Status.COMPLETED)
        self.assertEqual(self.order.return_count, 1)
        self.assertEqual(
            RepairRecord.objects.filter(work_order=self.order).count(),
            2,
        )
        evaluation = Evaluation.objects.get(work_order=self.order)
        self.assertEqual(evaluation.rating, 4)
        self.assertEqual(evaluation.comment, '第二次处理正常了。')
        self.assertEqual(
            StatusLog.objects.filter(work_order=self.order).count(),
            3,
        )

    def test_detail_shows_acceptance_actions_only_to_owner(self):
        detail_url = reverse('repair:work_order_detail', args=[self.order.pk])

        self.client.force_login(self.student)
        response = self.client.get(detail_url)
        self.assertContains(response, '验收并评价')
        self.assertContains(response, '退回返修')

        self.client.force_login(self.repairer)
        response = self.client.get(detail_url)
        self.assertNotContains(response, '验收并评价')
        self.assertNotContains(response, '退回返修')

    def test_completed_detail_shows_evaluation_and_timeline(self):
        self.client.force_login(self.student)
        self.accept(rating='5', comment='响应很快，问题已彻底解决。')

        response = self.client.get(
            reverse('repair:work_order_detail', args=[self.order.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '学生验收评价')
        self.assertContains(response, '★★★★★')
        self.assertContains(response, '响应很快，问题已彻底解决。')
        self.assertContains(response, '待验收 → 已完成')
        self.assertContains(response, '工单已完成验收，学生评价已归档。')

    def test_returned_detail_shows_reason_and_return_count(self):
        self.client.force_login(self.student)
        self.return_order(reason='柜门仍然发出异响。')

        response = self.client.get(
            reverse('repair:work_order_detail', args=[self.order.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '退回返修次数')
        self.assertContains(response, '1 次')
        self.assertContains(response, '柜门仍然发出异响。')
        self.assertContains(response, '待验收 → 维修中')

    def test_evaluation_is_unique_per_work_order(self):
        self.client.force_login(self.student)
        self.accept()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Evaluation.objects.create(
                    work_order=self.order,
                    student=self.student,
                    rating=4,
                    comment='不应创建的第二条评价',
                )

    def test_acceptance_and_return_require_login(self):
        for url_name in ('acceptance_result', 'return_repair'):
            with self.subTest(url_name=url_name):
                response = self.client.get(
                    reverse(f'repair:{url_name}', args=[self.order.pk])
                )
                self.assertEqual(response.status_code, 302)
                self.assertIn('/login/', response.url)

    def test_admin_exposes_workflow_fields_as_read_only(self):
        self.client.force_login(self.admin_user)

        response = self.client.get(
            reverse('admin:repair_workorder_change', args=[self.order.pk])
        )

        self.assertEqual(response.status_code, 200)
        admin_form = response.context['adminform'].form
        for field_name in (
            'status',
            'repairer',
            'completed_at',
            'verified_at',
            'return_count',
        ):
            self.assertNotIn(field_name, admin_form.fields)
