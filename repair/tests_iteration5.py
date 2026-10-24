from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .filters import WorkOrderFilterForm
from .forms import WorkOrderSubmitForm
from .models import (
    Building,
    RepairCategory,
    StatusLog,
    User,
    WorkOrder,
)


class PermissionMatrixTests(TestCase):
    def setUp(self):
        self.student = self.create_user(
            '20261001',
            User.Role.STUDENT,
            '权限学生',
        )
        self.other_student = self.create_user(
            '20261002',
            User.Role.STUDENT,
            '其他学生',
        )
        self.repairer = self.create_user(
            'WX101',
            User.Role.REPAIRER,
            '维修员一',
        )
        self.other_repairer = self.create_user(
            'WX102',
            User.Role.REPAIRER,
            '维修员二',
        )
        self.manager = self.create_user(
            'GL101',
            User.Role.MANAGER,
            '宿管',
        )
        self.superuser = User.objects.create_superuser(
            username='root101',
            password='admin-pass-123',
            role=User.Role.MANAGER,
            real_name='超级管理员',
        )
        self.building = Building.objects.create(name='10号楼')
        self.category = RepairCategory.objects.create(name='门窗')
        self.pending_order = self.create_order(
            'BX202610240101',
            WorkOrder.Status.PENDING,
        )
        self.other_pending_order = self.create_order(
            'BX202610240102',
            WorkOrder.Status.PENDING,
            student=self.other_student,
        )
        self.assigned_order = self.create_order(
            'BX202610240103',
            WorkOrder.Status.ASSIGNED,
            repairer=self.repairer,
        )
        self.other_assigned_order = self.create_order(
            'BX202610240104',
            WorkOrder.Status.ASSIGNED,
            repairer=self.other_repairer,
        )
        self.acceptance_order = self.create_order(
            'BX202610240105',
            WorkOrder.Status.PENDING_ACCEPTANCE,
            repairer=self.repairer,
        )

    def create_user(self, username, role, real_name):
        return User.objects.create_user(
            username=username,
            password='user-pass-123',
            role=role,
            real_name=real_name,
        )

    def create_order(
        self,
        order_no,
        status,
        student=None,
        repairer=None,
    ):
        now = timezone.now()
        return WorkOrder.objects.create(
            order_no=order_no,
            student=student or self.student,
            building=self.building,
            room_no='101',
            contact_phone='13800000000',
            category=self.category,
            description='权限矩阵测试工单。',
            status=status,
            repairer=repairer,
            assigned_at=now if repairer else None,
        )

    def detail_url(self, order=None):
        return reverse(
            'repair:work_order_detail',
            args=[(order or self.pending_order).pk],
        )

    def test_student_page_permissions(self):
        self.client.force_login(self.student)

        for url in (
            reverse('repair:home'),
            reverse('repair:my_orders'),
            reverse('repair:submit_repair'),
            self.detail_url(),
            reverse('repair:cancel_order', args=[self.pending_order.pk]),
            reverse(
                'repair:acceptance_result',
                args=[self.acceptance_order.pk],
            ),
            reverse('repair:return_repair', args=[self.acceptance_order.pk]),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

        for url in (
            reverse('repair:repairer_orders'),
            reverse('repair:manager_orders'),
            self.detail_url(self.other_pending_order),
            reverse('repair:accept_order', args=[self.pending_order.pk]),
            reverse('repair:reject_order', args=[self.pending_order.pk]),
            reverse('repair:start_repair', args=[self.assigned_order.pk]),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_repairer_page_permissions(self):
        self.client.force_login(self.repairer)

        for url in (
            reverse('repair:home'),
            reverse('repair:repairer_orders'),
            self.detail_url(self.assigned_order),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

        for url in (
            reverse('repair:my_orders'),
            reverse('repair:submit_repair'),
            reverse('repair:manager_orders'),
            self.detail_url(self.other_assigned_order),
            reverse('repair:cancel_order', args=[self.assigned_order.pk]),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_manager_page_permissions(self):
        self.client.force_login(self.manager)

        for url in (
            reverse('repair:home'),
            reverse('repair:manager_orders'),
            self.detail_url(self.other_pending_order),
            reverse('repair:accept_order', args=[self.pending_order.pk]),
            reverse('repair:reject_order', args=[self.pending_order.pk]),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

        for url in (
            reverse('repair:my_orders'),
            reverse('repair:submit_repair'),
            reverse('repair:repairer_orders'),
            reverse('repair:cancel_order', args=[self.pending_order.pk]),
            reverse('repair:start_repair', args=[self.assigned_order.pk]),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_superuser_has_manager_scope_without_business_role_impersonation(self):
        self.client.force_login(self.superuser)

        for url in (
            reverse('repair:manager_orders'),
            self.detail_url(self.other_pending_order),
            reverse('repair:accept_order', args=[self.pending_order.pk]),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

        for url in (
            reverse('repair:my_orders'),
            reverse('repair:submit_repair'),
            reverse('repair:repairer_orders'),
            reverse('repair:cancel_order', args=[self.pending_order.pk]),
            reverse('repair:start_repair', args=[self.assigned_order.pk]),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_unknown_role_cannot_view_work_order(self):
        unknown = self.create_user(
            'UNKNOWN',
            'unknown',
            '未知角色',
        )
        self.client.force_login(unknown)

        response = self.client.get(self.detail_url())

        self.assertEqual(response.status_code, 403)

    def test_anonymous_users_are_redirected_to_login(self):
        urls = (
            reverse('repair:home'),
            reverse('repair:my_orders'),
            reverse('repair:repairer_orders'),
            reverse('repair:manager_orders'),
            reverse('repair:submit_repair'),
            self.detail_url(),
            reverse('repair:start_repair', args=[self.assigned_order.pk]),
            reverse('repair:complete_repair', args=[self.assigned_order.pk]),
            reverse('repair:acceptance_result', args=[self.pending_order.pk]),
            reverse('repair:return_repair', args=[self.pending_order.pk]),
            reverse('repair:accept_order', args=[self.pending_order.pk]),
            reverse('repair:reject_order', args=[self.pending_order.pk]),
            reverse('repair:cancel_order', args=[self.pending_order.pk]),
        )

        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse('repair:login'), response.url)

    def test_registration_cannot_assign_privileged_role(self):
        response = self.client.post(
            reverse('repair:register'),
            {
                'username': '20261099',
                'real_name': '自助注册学生',
                'phone': '13700000000',
                'password1': 'student-pass-123',
                'password2': 'student-pass-123',
                'role': User.Role.MANAGER,
                'is_staff': 'on',
                'is_superuser': 'on',
            },
        )

        self.assertRedirects(response, reverse('repair:home'))
        user = User.objects.get(username='20261099')
        self.assertEqual(user.role, User.Role.STUDENT)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_unauthorized_manager_and_repairer_actions_have_no_side_effects(self):
        payload = {
            'fault_cause': '',
            'repair_action': '越权维修',
            'materials_used': '',
        }
        for user in (self.student, self.repairer):
            self.client.force_login(user)
            for url_name in ('accept_order', 'reject_order'):
                with self.subTest(user=user.username, url_name=url_name):
                    response = self.client.post(
                        reverse(
                            f'repair:{url_name}',
                            args=[self.pending_order.pk],
                        ),
                        {'reason': '越权操作'},
                    )
                    self.assertEqual(response.status_code, 403)

        self.pending_order.status = WorkOrder.Status.REPAIRING
        self.pending_order.repairer = self.repairer
        self.pending_order.save()
        for user in (self.student, self.manager):
            self.client.force_login(user)
            response = self.client.post(
                reverse('repair:complete_repair', args=[self.pending_order.pk]),
                payload,
            )
            self.assertEqual(response.status_code, 403)

        for user in (self.repairer, self.manager):
            self.client.force_login(user)
            response = self.client.post(
                reverse('repair:cancel_order', args=[self.pending_order.pk]),
                {'reason': '越权撤销'},
            )
            self.assertEqual(response.status_code, 403)

        self.pending_order.refresh_from_db()
        self.assertEqual(self.pending_order.status, WorkOrder.Status.REPAIRING)
        self.assertFalse(
            StatusLog.objects.filter(work_order=self.pending_order).exists()
        )
        self.assertFalse(self.pending_order.repair_records.exists())


class BasicDataAdminTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username='root-basic-data',
            password='admin-pass-123',
            role=User.Role.MANAGER,
            real_name='基础数据管理员',
        )
        self.manager = User.objects.create_user(
            username='manager-basic-data',
            password='manager-pass-123',
            role=User.Role.MANAGER,
            real_name='非后台宿管',
        )
        self.student = User.objects.create_user(
            username='20261101',
            password='student-pass-123',
            role=User.Role.STUDENT,
            real_name='提交学生',
            phone='13900000000',
        )
        self.repairer = User.objects.create_user(
            username='WX201',
            password='repairer-pass-123',
            role=User.Role.REPAIRER,
            real_name='维修员',
        )
        self.active_building = Building.objects.create(name='11号楼')
        self.inactive_building = Building.objects.create(
            name='12号楼',
            is_active=False,
        )
        self.active_category = RepairCategory.objects.create(name='水电')
        self.inactive_category = RepairCategory.objects.create(
            name='网络',
            is_active=False,
        )
        self.used_order = WorkOrder.objects.create(
            order_no='BX202610240201',
            student=self.student,
            building=self.active_building,
            room_no='201',
            contact_phone='13900000000',
            category=self.active_category,
            description='用于验证基础数据引用保护。',
            status=WorkOrder.Status.ASSIGNED,
            repairer=self.repairer,
            assigned_at=timezone.now(),
        )

    def test_new_repair_only_offers_active_basic_data(self):
        form = WorkOrderSubmitForm(user=self.student)
        building_ids = set(
            form.fields['building'].queryset.values_list('id', flat=True)
        )
        category_ids = set(
            form.fields['category'].queryset.values_list('id', flat=True)
        )

        self.assertIn(self.active_building.pk, building_ids)
        self.assertNotIn(self.inactive_building.pk, building_ids)
        self.assertIn(self.active_category.pk, category_ids)
        self.assertNotIn(self.inactive_category.pk, category_ids)

    def test_historical_filters_keep_inactive_basic_data(self):
        form = WorkOrderFilterForm()
        building_ids = set(
            form.fields['building'].queryset.values_list('id', flat=True)
        )
        category_ids = set(
            form.fields['category'].queryset.values_list('id', flat=True)
        )

        self.assertIn(self.active_building.pk, building_ids)
        self.assertIn(self.inactive_building.pk, building_ids)
        self.assertIn(self.active_category.pk, category_ids)
        self.assertIn(self.inactive_category.pk, category_ids)

    def test_student_submits_with_admin_managed_basic_data(self):
        initial_building_count = Building.objects.count()
        self.client.force_login(self.student)

        response = self.client.post(
            reverse('repair:submit_repair'),
            {
                'building': self.active_building.pk,
                'room_no': '202',
                'repair_address': '洗手台',
                'contact_phone': '13900000000',
                'category': self.active_category.pk,
                'description': '水龙头持续漏水。',
                'remark': '',
            },
        )

        work_order = WorkOrder.objects.get(room_no='202')
        self.assertRedirects(
            response,
            reverse('repair:work_order_detail', args=[work_order.pk]),
        )
        self.assertEqual(work_order.building, self.active_building)
        self.assertEqual(work_order.category, self.active_category)
        self.assertEqual(Building.objects.count(), initial_building_count)

    def test_student_cannot_forge_inactive_or_new_basic_data(self):
        self.client.force_login(self.student)
        invalid_payloads = (
            {
                'building': self.inactive_building.pk,
                'category': self.active_category.pk,
            },
            {
                'building': self.active_building.pk,
                'category': self.inactive_category.pk,
            },
            {
                'building': '999号楼',
                'category': self.active_category.pk,
            },
        )

        for values in invalid_payloads:
            with self.subTest(values=values):
                response = self.client.post(
                    reverse('repair:submit_repair'),
                    {
                        **values,
                        'room_no': '203',
                        'contact_phone': '13900000000',
                        'description': '不应创建的工单。',
                    },
                )
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['form'].errors)

        self.assertFalse(WorkOrder.objects.filter(room_no='203').exists())
        self.assertFalse(Building.objects.filter(name='999号楼').exists())

    def test_superuser_can_add_and_edit_building_in_admin(self):
        self.client.force_login(self.superuser)

        response = self.client.post(
            reverse('admin:repair_building_add'),
            {
                'name': '二号楼',
                'is_active': 'on',
                '_save': '保存',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Building.objects.filter(name='2号楼').exists())

        response = self.client.post(
            reverse(
                'admin:repair_building_change',
                args=[self.active_building.pk],
            ),
            {
                'name': '十一号楼',
                '_save': '保存',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.active_building.refresh_from_db()
        self.assertEqual(self.active_building.name, '11号楼')
        self.assertFalse(self.active_building.is_active)

    def test_superuser_can_add_and_edit_category_in_admin(self):
        self.client.force_login(self.superuser)

        response = self.client.post(
            reverse('admin:repair_repaircategory_add'),
            {
                'name': '照明',
                'description': '灯具与开关',
                'is_active': 'on',
                '_save': '保存',
            },
        )
        self.assertEqual(response.status_code, 302)
        category = RepairCategory.objects.get(name='照明')

        response = self.client.post(
            reverse(
                'admin:repair_repaircategory_change',
                args=[category.pk],
            ),
            {
                'name': '照明与开关',
                'description': '灯具、开关和插座',
                '_save': '保存',
            },
        )
        self.assertEqual(response.status_code, 302)
        category.refresh_from_db()
        self.assertEqual(category.name, '照明与开关')
        self.assertFalse(category.is_active)

    def test_referenced_basic_data_cannot_be_deleted(self):
        self.client.force_login(self.superuser)
        urls = (
            reverse(
                'admin:repair_building_delete',
                args=[self.active_building.pk],
            ),
            reverse(
                'admin:repair_repaircategory_delete',
                args=[self.active_category.pk],
            ),
        )

        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

        self.assertTrue(
            Building.objects.filter(pk=self.active_building.pk).exists()
        )
        self.assertTrue(
            RepairCategory.objects.filter(pk=self.active_category.pk).exists()
        )

    def test_unreferenced_basic_data_can_be_deleted(self):
        self.client.force_login(self.superuser)

        response = self.client.post(
            reverse(
                'admin:repair_building_delete',
                args=[self.inactive_building.pk],
            ),
            {'post': 'yes'},
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            Building.objects.filter(pk=self.inactive_building.pk).exists()
        )

    def test_admin_lists_related_work_order_counts(self):
        self.client.force_login(self.superuser)

        response = self.client.get(
            reverse('admin:repair_building_changelist')
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '关联工单')
        building = next(
            obj
            for obj in response.context['cl'].result_list
            if obj.pk == self.active_building.pk
        )
        self.assertEqual(building.work_order_count, 1)

    def test_non_staff_manager_cannot_enter_django_admin(self):
        self.client.force_login(self.manager)

        response = self.client.get(reverse('admin:index'))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('admin:login'), response.url)
