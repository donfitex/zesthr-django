"""Employee lifecycle: safe deactivation and reactivation.

An employee is never deleted to "remove" them: attendance, leave and payroll
history must survive. Deactivation keeps every record, marks the employee as
no longer active, and revokes the linked login in the same transaction.
"""
from django.core.exceptions import ValidationError
from django.db import transaction

from ..models import Employee
from . import accounts, history

DEACTIVATION_STATUSES = ("SUSPENDED", "INACTIVE", "RESIGNED", "TERMINATED", "RETIRED")


@transaction.atomic
def deactivate_employee(employee, *, status, separation_date=None, reason="", by=None):
    if status not in DEACTIVATION_STATUSES:
        raise ValidationError("Choose a valid deactivation status.")
    if status in Employee.SEPARATED_STATUSES and not separation_date:
        raise ValidationError("A separation date is required for this status.")
    before = history.refresh_and_snapshot(employee.pk)
    employee.employment_status = status
    employee.separation_date = separation_date if status in Employee.SEPARATED_STATUSES else None
    employee.separation_reason = reason.strip()
    employee.full_clean()
    employee.save()
    history.record_changes(before, employee, by)
    if employee.user_id:  # revoke access immediately
        accounts.set_account_active(employee.user, False, by=by)
    return employee


@transaction.atomic
def reactivate_employee(employee, *, status="ACTIVE", by=None):
    if status not in Employee.ACTIVE_STATUSES:
        raise ValidationError("Reactivate as Active or On probation.")
    before = history.refresh_and_snapshot(employee.pk)
    employee.employment_status = status
    employee.separation_date = None
    employee.separation_reason = ""
    employee.save()
    history.record_changes(before, employee, by)
    if employee.user_id:
        accounts.set_account_active(employee.user, True, by=by)
    return employee
