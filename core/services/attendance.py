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
from datetime import timedelta

from django.db import transaction

from .. import timeutil
from ..models import Attendance, AttendanceAudit, AttendanceCorrectionRequest, Employee
from .schedules import resolve_schedule

MARKABLE_STATUSES = ("A", "H", "L")  # statuses HR may set explicitly


class AttendanceError(Exception):
    """A rule was broken. `code` is stable for tests/UI; str() is a message fit for the user."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def snapshot(rec):
    """The fields that matter, as plain JSON-safe values."""
    if rec is None:
        return None
    return {"status": rec.status,
            "check_in": rec.check_in.isoformat() if rec.check_in else None,
            "check_out": rec.check_out.isoformat() if rec.check_out else None,
            "ends_next_day": rec.ends_next_day}


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
    day, moment = today or timeutil.today_for(emp), now or timeutil.time_for(emp)
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


def current_record(emp, today):
    """The record a punch card should show: today's, or the open shift that started yesterday
    when the employee works overnight shifts."""
    rec = Attendance.objects.filter(emp=emp, date=today).first()
    if rec and rec.check_in and not rec.check_out:
        return rec
    schedule = resolve_schedule(emp)
    if schedule and schedule.is_overnight:
        prev = Attendance.objects.filter(emp=emp, date=today - timedelta(days=1), check_in__isnull=False,
                                         check_out__isnull=True, status__in=["P", "H"]).first()
        if prev:
            return prev
    return rec


@transaction.atomic
def check_out(emp, *, now=None, today=None, by=None):
    _require_active(emp)
    day, moment = today or timeutil.today_for(emp), now or timeutil.time_for(emp)
    rec = Attendance.objects.select_for_update().filter(emp=emp, date=day).first()
    open_today = rec is not None and rec.check_in is not None and rec.check_out is None

    if not open_today:
        # Overnight shift: the employee clocked in yesterday evening and leaves this morning.
        schedule = resolve_schedule(emp)
        if schedule and schedule.is_overnight:
            prev = Attendance.objects.select_for_update().filter(
                emp=emp, date=day - timedelta(days=1), check_in__isnull=False, check_out__isnull=True,
                status__in=["P", "H"]).first()
            if prev:
                if moment >= prev.check_in:
                    raise AttendanceError("invalid_time", "That shift would be 24 hours or longer. Ask HR to correct it.")
                before = snapshot(prev)
                prev.check_out, prev.ends_next_day = moment, True
                prev.save()
                record_audit(AttendanceAudit.CHECK_OUT, prev, before, by=by)
                return prev
        if rec is not None and rec.check_out:
            raise AttendanceError("already_checked_out", f"Already punched out today at {rec.check_out:%H:%M}.")
        hint = ""
        if Attendance.objects.filter(emp=emp, date__lt=day, check_in__isnull=False, check_out__isnull=True,
                                     status__in=["P", "H"]).exists():
            hint = " You also have an earlier day without a check-out; ask HR to correct it."
        raise AttendanceError("not_checked_in", "You have not punched in today, so there is nothing to punch out of." + hint)

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
    day = today or timeutil.today_for(emp)
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
        rec.ends_next_day = False
    rec.save()
    record_audit(AttendanceAudit.SET_STATUS, rec, before, by=by, reason=reason)
    return rec


def record_manual_change(action, rec, before, *, by, reason, deleted=False, day=None, emp=None):
    """For edits made through the correction form (the form validates; this keeps the history)."""
    if action == AttendanceAudit.MANUAL_EDIT and before == snapshot(rec) and not deleted:
        return None  # saved without changing anything: nothing to record
    return record_audit(action, rec, before, by=by, reason=reason, deleted=deleted, day=day, emp=emp)

@transaction.atomic
def submit_bulk_attendance(employee_ids, date, check_in_time=None, check_out_time=None, author_user=None, reason="Bulk Entry"):
    """
    Creates or updates basic attendance sheets for an entire list of employees at once.
    """
    records_updated = 0
    for emp_id in employee_ids:
        try:
            employee = Employee.objects.get(id=emp_id)
            # Create or update standard daily attendance placeholder
            attendance, created = Attendance.objects.get_or_create(
                employee=employee,
                date=date,
                defaults={'check_in': check_in_time, 'check_out': check_out_time, 'notes': reason}
            )
            if not created:
                if check_in_time: attendance.check_in = check_in_time
                if check_out_time: attendance.check_out = check_out_time
                attendance.notes = f"{attendance.notes} | Updated via bulk: {reason}"
                attendance.save()
            records_updated += 1
        except Employee.DoesNotExist:
            continue
    return records_updated

@transaction.atomic
def process_correction_request(request_id, status, manager_user, review_notes=""):
    """
    Handles transition rules for correction requests. If approved, applies directly
    to the target employee's core attendance card.
    """
    correction = AttendanceCorrectionRequest.objects.select_for_update().get(id=request_id)
    
    if correction.status != 'PENDING':
        raise ValueError("This request has already been processed.")
        
    correction.status = status
    correction.reviewed_by = manager_user
    correction.review_notes = review_notes
    correction.save()
    
    if status == 'APPROVED':
        # Apply edits downstream directly onto core Attendance logging
        attendance, created = Attendance.objects.get_or_create(
            employee=correction.employee,
            date=correction.attendance_date
        )
        if correction.requested_check_in:
            attendance.check_in = correction.requested_check_in
        if correction.requested_check_out:
            attendance.check_out = correction.requested_check_out
            
        audit_trail_text = f"Corrected by Manager Review. Reason: {correction.reason}"
        attendance.notes = f"{attendance.notes} | {audit_trail_text}" if attendance.notes else audit_trail_text
        attendance.save()
        
    return correction
