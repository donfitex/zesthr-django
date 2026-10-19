"""Attendance operations (punching in/out and marking a status)."""
from django.db import transaction
from django.utils import timezone

from ..models import Attendance

# Statuses that may be set explicitly (anything else is not a valid status action).
MARKABLE_STATUSES = ("A", "H", "L")


def _now_time():
    return timezone.localtime().time().replace(microsecond=0)


def _record_for_today(emp, today=None):
    rec, _ = Attendance.objects.select_for_update().get_or_create(
        emp=emp, date=today or timezone.localdate())
    return rec


@transaction.atomic
def check_in(emp, *, now=None, today=None):
    rec = _record_for_today(emp, today)
    rec.check_in, rec.status = now or _now_time(), "P"
    rec.save()
    return rec


@transaction.atomic
def check_out(emp, *, now=None, today=None):
    rec = _record_for_today(emp, today)
    rec.check_out = now or _now_time()
    rec.save()
    return rec


@transaction.atomic
def mark_status(emp, status, *, today=None):
    """Set today's status (Absent / Half day / Leave). Absent and Leave clear punch times."""
    if status not in MARKABLE_STATUSES:
        raise ValueError(f"Unsupported attendance status: {status!r}")
    rec = _record_for_today(emp, today)
    rec.status = status
    if status in ("A", "L"):
        rec.check_in = rec.check_out = None
    rec.save()
    return rec
