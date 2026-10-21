"""Attendance rules: punching in/out, status changes by HR, and the audit trail.

Allowed transitions for ONE employee on ONE day (the row is locked while it changes, so
two simultaneous requests can never both succeed):

    no row        --check_in-->   Present, check_in set
    Present(no in)--check_in-->   Present, check_in set      (HR created an empty Present entry)
    Present(in)   --check_out-->  Present, check_out set     (must be later than check_in)
    anything else on check_in / check_out is refused:
        already punched in/out, not punched in, absent/leave/half-day set by HR, inactive employee

    HR status changes (Absent / Half day / Leave):
    no row or Present(no punches) --> A / H / L              allowed
    A <-> L <-> H without punches                            allowed
    row with punches --> A / L   would erase real punch times: refused unless a reason is given
    same status again                                        no-op

Every change writes an AttendanceAudit row in the same transaction.
Corrections of any other kind go through the edit form, which requires a reason.
"""
from django.db import transaction
from django.utils import timezone

from ..models import Attendance, AttendanceAudit

MARKABLE_STATUSES = ("A", "H", "L")  # statuses HR may set explicitly


class AttendanceError(Exception):
    """A rule was broken. `code` is stable for tests/UI; str() is a message fit for the user."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _now_time():
    return timezone.localtime().time().replace(microsecond=0)


def snapshot(rec):
    """The fields that matter, as plain JSON-safe values."""
    if rec is None:
        return None
    return {"status": rec.status,
            "check_in": rec.check_in.isoformat() if rec.check_in else None,
            "check_out": rec.check_out.isoformat() if rec.check_out else None}


def record_audit(action, rec, before, *, by=None, reason="", day=None, emp=None, deleted=False):
    return AttendanceAudit.objects.create(
        emp=emp or rec.emp, date=day or rec.date, attendance=None if deleted else rec, record_id=rec.pk,
        action=action, old_values=before, new_values=None if deleted else snapshot(rec),
        reason=(reason or "").strip()[:255], changed_by=by if getattr(by, "pk", None) else None)


def _require_active(emp):
    if not emp.is_active:
        raise AttendanceError("inactive_employee", f"{emp.name} is not an active employee, so attendance cannot be recorded.")


@transaction.atomic
def check_in(emp, *, now=None, today=None, by=None):
    _require_active(emp)
    day, moment = today or timezone.localdate(), now or _now_time()
    rec, created = Attendance.objects.select_for_update().get_or_create(
        emp=emp, date=day, defaults={"status": "P", "check_in": moment})
    if created:
        record_audit(AttendanceAudit.CHECK_IN, rec, None, by=by)
        return rec
    if rec.check_in:
        raise AttendanceError("already_checked_in", f"Already punched in today at {rec.check_in:%H:%M}.")
    if rec.status == "L":
        raise AttendanceError("status_locked", "Today is recorded as approved leave, so punching in is not possible.")
    if rec.status in ("A", "H"):
        raise AttendanceError("status_locked", f"HR has marked today as {rec.get_status_display().lower()}. "
                                               "Ask HR to correct it if that is wrong.")
    before = snapshot(rec)  # an empty Present entry that HR created
    rec.check_in, rec.status = moment, "P"
    rec.save()
    record_audit(AttendanceAudit.CHECK_IN, rec, before, by=by)
    return rec


@transaction.atomic
def check_out(emp, *, now=None, today=None, by=None):
    _require_active(emp)
    day, moment = today or timezone.localdate(), now or _now_time()
    rec = Attendance.objects.select_for_update().filter(emp=emp, date=day).first()
    if rec is None or not rec.check_in:
        hint = ""
        if Attendance.objects.filter(emp=emp, date__lt=day, check_in__isnull=False, check_out__isnull=True,
                                     status__in=["P", "H"]).order_by("-date").exists():
            hint = " You also have an earlier day without a check-out; ask HR to correct it."
        raise AttendanceError("not_checked_in", "You have not punched in today, so there is nothing to punch out of." + hint)
    if rec.check_out:
        raise AttendanceError("already_checked_out", f"Already punched out today at {rec.check_out:%H:%M}.")
    if moment <= rec.check_in:
        raise AttendanceError("invalid_time", "The check-out time must be later than the check-in time "
                                              f"({rec.check_in:%H:%M}). Check the device clock.")
    before = snapshot(rec)
    rec.check_out = moment
    rec.save()
    record_audit(AttendanceAudit.CHECK_OUT, rec, before, by=by)
    return rec


@transaction.atomic
def mark_status(emp, status, *, today=None, by=None, reason=""):
    """HR sets today's status to Absent / Half day / Leave."""
    if status not in MARKABLE_STATUSES:
        raise ValueError(f"Unsupported attendance status: {status!r}")
    day = today or timezone.localdate()
    rec, created = Attendance.objects.select_for_update().get_or_create(emp=emp, date=day, defaults={"status": status})
    if created:
        record_audit(AttendanceAudit.SET_STATUS, rec, None, by=by, reason=reason)
        return rec
    if rec.status == status:
        return rec  # nothing to change: repeating the click is harmless
    erases_punches = status in ("A", "L") and (rec.check_in or rec.check_out)
    if erases_punches and not (reason or "").strip():
        raise AttendanceError(
            "correction_required",
            f"{emp.name} already has punch times today. Use Edit attendance and give a reason to override them.")
    before = snapshot(rec)
    rec.status = status
    if status in ("A", "L"):
        rec.check_in = rec.check_out = None
    rec.save()
    record_audit(AttendanceAudit.SET_STATUS, rec, before, by=by, reason=reason)
    return rec


def record_manual_change(action, rec, before, *, by, reason, deleted=False, day=None, emp=None):
    """For edits made through the correction form (the form validates; this keeps the history)."""
    if action == AttendanceAudit.MANUAL_EDIT and before == snapshot(rec) and not deleted:
        return None  # saved without changing anything: nothing to record
    return record_audit(action, rec, before, by=by, reason=reason, deleted=deleted, day=day, emp=emp)
