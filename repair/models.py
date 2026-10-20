from django.contrib.auth.models import AbstractUser
from django.db import models


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

# Create your models here.
