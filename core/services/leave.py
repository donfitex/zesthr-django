"""Leave rules: validation, submission, approval and rejection."""
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction

from ..models import Attendance, LeaveApplication

SICK_LEAVE_MAX_DAYS = 1
SICK_LEAVE_MONTHLY_QUOTA = 1


def validate_leave_request(employee, leave_type, start, end):
    """Raise ValidationError if the request breaks a leave rule. Safe to call from forms."""
    if not (start and end):
        return
    if end < start:
        raise ValidationError("End date cannot be earlier than start date.")
    days = (end - start).days + 1
    if leave_type == "SL":
        if days > SICK_LEAVE_MAX_DAYS:
            raise ValidationError(
                f"Sick leave allowance is strictly 1 day per month. You requested {days} days.")
        if employee is not None:
            used = employee.sick_leaves_used_this_month(month=start.month, year=start.year)
            if used >= SICK_LEAVE_MONTHLY_QUOTA:
                raise ValidationError(
                    f"You have already exhausted your 1 Sick Leave allocation for {start.strftime('%B %Y')}.")


@transaction.atomic
def submit_leave(employee, *, leave_type, start_date, end_date, reason):
    """Create a PENDING application for `employee` (always the caller-supplied employee)."""
    validate_leave_request(employee, leave_type, start_date, end_date)
    return LeaveApplication.objects.create(
        emp=employee, leave_type=leave_type, start_date=start_date, end_date=end_date,
        reason=reason, status="PENDING")


@transaction.atomic
def approve_leave(leave, note=""):
    """Approve and record every day of the leave as 'L' in attendance, atomically."""
    leave.status = "APPROVED"
    leave.admin_note = note
    leave.save()
    day = leave.start_date
    while day <= leave.end_date:
        Attendance.objects.update_or_create(
            emp=leave.emp, date=day,
            defaults={"status": "L", "check_in": None, "check_out": None})
        day += timedelta(days=1)
    return leave


@transaction.atomic
def reject_leave(leave, note=""):
    leave.status = "REJECTED"
    leave.admin_note = note
    leave.save()
    return leave
