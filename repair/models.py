from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from .utils import normalize_building_name


class User(AbstractUser):
    """系统用户：学生用学号作为用户名，维修人员和宿管用工号或拼音作为用户名。"""

    class Role(models.TextChoices):
        STUDENT = 'student', '学生'
        REPAIRER = 'repairer', '维修人员'
        MANAGER = 'manager', '宿管'

    role = models.CharField(
        '角色',
        max_length=20,
        choices=Role.choices,
        default=Role.STUDENT,
    )
    real_name = models.CharField('姓名', max_length=30, blank=True)
    phone = models.CharField('联系电话', max_length=20, blank=True)

    class Meta:
        verbose_name = '用户'
        verbose_name_plural = '用户'

    def __str__(self):
        return f'{self.real_name or self.username}（{self.get_role_display()}）'


class Building(models.Model):
    name = models.CharField('楼栋名称', max_length=50, unique=True)
    is_active = models.BooleanField('启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name = '楼栋'
        verbose_name_plural = '楼栋'

    def clean(self):
        super().clean()
        self.name = normalize_building_name(self.name)
        if (
            self.name
            and Building.objects.filter(name__iexact=self.name)
            .exclude(pk=self.pk)
            .exists()
        ):
            raise ValidationError({'name': '该楼栋已存在（已按统一写法匹配）。'})

    def save(self, *args, **kwargs):
        self.name = normalize_building_name(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class RepairCategory(models.Model):
    name = models.CharField('分类名称', max_length=50, unique=True)
    description = models.CharField('说明', max_length=200, blank=True)
    is_active = models.BooleanField('启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name = '报修分类'
        verbose_name_plural = '报修分类'

    def __str__(self):
        return self.name


def generate_order_no():
    """生成 BX + 日期 + 四位序号 的工单号。"""
    date_part = timezone.localdate().strftime('%Y%m%d')
    prefix = f'BX{date_part}'
    last_order = (
        WorkOrder.objects.filter(order_no__startswith=prefix)
        .order_by('-order_no')
        .first()
    )
    sequence = int(last_order.order_no[-4:]) + 1 if last_order else 1
    return f'{prefix}{sequence:04d}'


class WorkOrder(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', '待受理'
        ASSIGNED = 'assigned', '已派单'
        REPAIRING = 'repairing', '维修中'
        PENDING_ACCEPTANCE = 'pending_acceptance', '待验收'
        COMPLETED = 'completed', '已完成'
        REJECTED = 'rejected', '已驳回'
        CANCELLED = 'cancelled', '已撤销'

    order_no = models.CharField('工单号', max_length=20, unique=True, editable=False)
    student = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='work_orders',
        verbose_name='报修学生',
        limit_choices_to={'role': 'student'},
    )
    building = models.ForeignKey(
        Building,
        on_delete=models.PROTECT,
        verbose_name='楼栋',
    )
    room_no = models.CharField('房间号', max_length=20)
    repair_address = models.CharField('维修地址', max_length=200, blank=True)
    contact_phone = models.CharField('联系电话', max_length=20, default='')
    category = models.ForeignKey(
        RepairCategory,
        on_delete=models.PROTECT,
        verbose_name='报修分类',
    )
    description = models.TextField('故障描述')
    remark = models.TextField('备注', max_length=500, blank=True, default='')
    allow_entry_without_student = models.BooleanField(
        '宿舍无人时同意在宿管陪同下进入',
        default=False,
    )
    contact_note = models.TextField('联系备注', blank=True, default='')
    appointment_at = models.DateTimeField('约定上门时间', null=True, blank=True)
    status = models.CharField(
        '状态',
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    repairer = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_work_orders',
        verbose_name='维修人员',
        limit_choices_to={'role': 'repairer'},
    )
    accepted_at = models.DateTimeField('受理时间', null=True, blank=True)
    assigned_at = models.DateTimeField('派单时间', null=True, blank=True)
    started_at = models.DateTimeField('开始维修时间', null=True, blank=True)
    completed_at = models.DateTimeField('完工时间', null=True, blank=True)
    verified_at = models.DateTimeField('验收时间', null=True, blank=True)
    return_count = models.PositiveSmallIntegerField('退回返修次数', default=0)
    reject_reason = models.TextField('驳回原因', blank=True)
    cancel_reason = models.TextField('撤销原因', blank=True)
    created_at = models.DateTimeField('提交时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(
                fields=['repairer', 'status'],
                name='wo_repairer_status_idx',
            ),
            models.Index(
                fields=['student', 'status'],
                name='wo_student_status_idx',
            ),
            models.Index(
                fields=['status', 'created_at'],
                name='wo_status_created_idx',
            ),
        ]
        verbose_name = '报修工单'
        verbose_name_plural = '报修工单'

    def __str__(self):
        return f'{self.order_no} - {self.get_status_display()}'

    def save(self, *args, **kwargs):
        if not self.order_no:
            self.order_no = generate_order_no()
        super().save(*args, **kwargs)

    @property
    def status_color(self):
        return {
            self.Status.PENDING: 'warning',
            self.Status.ASSIGNED: 'info',
            self.Status.REPAIRING: 'primary',
            self.Status.PENDING_ACCEPTANCE: 'dark',
            self.Status.COMPLETED: 'success',
            self.Status.REJECTED: 'danger',
            self.Status.CANCELLED: 'secondary',
        }.get(self.status, 'secondary')

    @property
    def status_index(self):
        flow = [
            self.Status.PENDING,
            self.Status.ASSIGNED,
            self.Status.REPAIRING,
            self.Status.PENDING_ACCEPTANCE,
            self.Status.COMPLETED,
        ]
        try:
            return flow.index(self.status)
        except ValueError:
            return -1


class WorkOrderImage(models.Model):
    work_order = models.ForeignKey(
        WorkOrder,
        on_delete=models.CASCADE,
        related_name='images',
        verbose_name='工单',
    )
    image = models.ImageField('照片', upload_to='repair_images/%Y/%m/')
    uploaded_at = models.DateTimeField('上传时间', auto_now_add=True)

    class Meta:
        verbose_name = '工单照片'
        verbose_name_plural = '工单照片'

    def __str__(self):
        return f'{self.work_order.order_no} 的照片'


class RepairRecord(models.Model):
    work_order = models.ForeignKey(
        WorkOrder,
        on_delete=models.CASCADE,
        related_name='repair_records',
        verbose_name='工单',
    )
    repairer = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='repair_records',
        verbose_name='维修人员',
        limit_choices_to={'role': 'repairer'},
    )
    fault_cause = models.TextField('故障原因', blank=True, default='')
    repair_action = models.TextField('维修内容')
    materials_used = models.CharField(
        '更换材料',
        max_length=500,
        blank=True,
        default='',
    )
    completed_at = models.DateTimeField('完工时间')
    created_at = models.DateTimeField('记录时间', auto_now_add=True)

    class Meta:
        ordering = ['completed_at', 'created_at']
        verbose_name = '维修记录'
        verbose_name_plural = '维修记录'

    def __str__(self):
        return f'{self.work_order.order_no} 的维修记录'


class Evaluation(models.Model):
    work_order = models.OneToOneField(
        WorkOrder,
        on_delete=models.CASCADE,
        related_name='evaluation',
        verbose_name='工单',
    )
    student = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='evaluations',
        verbose_name='评价学生',
        limit_choices_to={'role': 'student'},
    )
    rating = models.PositiveSmallIntegerField(
        '评分',
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    comment = models.TextField('评价内容', max_length=1000)
    created_at = models.DateTimeField('评价时间', auto_now_add=True)

    class Meta:
        verbose_name = '验收评价'
        verbose_name_plural = '验收评价'

    @property
    def star_display(self):
        return f'{"★" * self.rating}{"☆" * (5 - self.rating)}'

    def __str__(self):
        return f'{self.work_order.order_no} - {self.rating} 星'


class StatusLog(models.Model):
    work_order = models.ForeignKey(
        WorkOrder,
        on_delete=models.CASCADE,
        related_name='status_logs',
        verbose_name='工单',
    )
    from_status = models.CharField(
        '原状态',
        max_length=20,
        choices=WorkOrder.Status.choices,
        blank=True,
    )
    to_status = models.CharField(
        '新状态',
        max_length=20,
        choices=WorkOrder.Status.choices,
    )
    operator = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='status_logs',
        verbose_name='操作人',
    )
    remark = models.TextField('备注', blank=True, default='')
    created_at = models.DateTimeField('操作时间', auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = '状态日志'
        verbose_name_plural = '状态日志'

    def __str__(self):
        from_display = self.get_from_status_display() if self.from_status else '新建'
        return f'{self.work_order.order_no}: {from_display} → {self.get_to_status_display()}'
