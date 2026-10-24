from datetime import timedelta

from django.utils import timezone


UNACCEPTED_OVERDUE_HOURS = 24


def unaccepted_overdue_cutoff(now=None):
    """返回“仍未受理”工单的超时截止时间。"""
    current_time = now or timezone.now()
    return current_time - timedelta(hours=UNACCEPTED_OVERDUE_HOURS)
