"""Payroll calculation.

    net = basic - deduction + overtime_pay

Per-day pay is the basic salary divided by the calendar days of the month; a half
day counts as 0.5 absent day; the deduction never exceeds the basic salary.

Overtime pay (employees whose schedule is overtime-eligible only):

    hourly rate  = per-day pay / paid hours of a normal shift
    overtime pay = overtime hours x hourly rate x the schedule's multiplier

An employee with no overtime gets no overtime term at all, so their figures are exactly
what they were before overtime existed.
"""

"""Payroll calculation and payroll business rules."""

import calendar
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from apps.organizations.tenancy import scope_queryset

from ..models import Attendance, Employee, Salary
from . import schedules

from django.utils import timezone

from ..models import (
    PayrollAdjustment,
    PayrollRun,
)

CENT = Decimal("0.01")


def money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class PayrollCalculation:
    employee: Employee
    month: int
    year: int
    calendar_days: int
    present_days: int
    half_days: int
    absent_days_count: int
    leave_days: int
    absent_equivalent_days: Decimal
    basic_salary: Decimal
    per_day_pay: Decimal
    absence_deduction: Decimal
    overtime_minutes: int
    overtime_pay: Decimal
    gross_pay: Decimal
    net_pay: Decimal

    def __getitem__(self, key):
        """Compatibility with the report's established dictionary-style row API."""
        fields = {
            "emp": self.employee,
            "present": self.present_days,
            "half": self.half_days,
            "absent": self.absent_days_count,
            "leave": self.leave_days,
            "absent_days": self.absent_equivalent_days,
            "per_day": self.per_day_pay,
            "deduction": self.absence_deduction,
            "overtime_minutes": self.overtime_minutes,
            "overtime_pay": self.overtime_pay,
            "gross": self.gross_pay,
            "net": self.net_pay,
        }
        try:
            return fields[key]
        except KeyError:
            raise KeyError(key) from None


def validate_period(month, year):
    if not 1 <= int(month) <= 12:
        raise ValidationError("Month must be between 1 and 12.")

    if int(year) < 2000 or int(year) > 2100:
        raise ValidationError("Invalid payroll year.")


def get_attendance_totals(employee, month, year):
    result = employee.attendance.filter(
        date__month=month,
        date__year=year,
    ).aggregate(
        present=Count(
            "id",
            filter=Q(status="P"),
        ),
        half=Count(
            "id",
            filter=Q(status="H"),
        ),
        absent=Count(
            "id",
            filter=Q(status="A"),
        ),
        leave=Count(
            "id",
            filter=Q(status="L"),
        ),
    )

    return {
        "present": result["present"] or 0,
        "half": result["half"] or 0,
        "absent": result["absent"] or 0,
        "leave": result["leave"] or 0,
    }


def calculate_overtime(employee, month, year, per_day_pay):
    resolver = schedules.ScheduleResolver()

    records = (
        Attendance.objects
        .filter(
            emp=employee,
            date__month=month,
            date__year=year,
            status="P",
            check_out__isnull=False,
        )
        .select_related(
            "emp__work_schedule",
            "emp__department__work_schedule",
        )
    )

    total_minutes = 0
    multiplier = Decimal("1.00")
    scheduled_minutes = 0

    for record in records:
        schedule = resolver.for_employee(employee)

        if not schedule or not schedule.overtime_eligible:
            continue

        evaluation = schedules.evaluate(record, schedule)

        if not evaluation:
            continue

        if evaluation.overtime_minutes <= 0:
            continue

        total_minutes += evaluation.overtime_minutes
        multiplier = schedule.overtime_multiplier
        scheduled_minutes = schedules.scheduled_minutes(schedule)

    if not total_minutes or not scheduled_minutes:
        return 0, Decimal("0.00")

    overtime_pay = (
        Decimal(total_minutes)
        * per_day_pay
        * multiplier
        / Decimal(scheduled_minutes)
    )

    return total_minutes, money(overtime_pay)


def calculate_employee_payroll(employee, month, year):
    validate_period(month, year)

    calendar_days = calendar.monthrange(year, month)[1]

    totals = get_attendance_totals(
        employee,
        month,
        year,
    )

    basic_salary = money(employee.basic_salary)

    per_day_pay = money(
        basic_salary / Decimal(calendar_days)
    )

    absent_equivalent_days = (
        Decimal(totals["absent"])
        + Decimal(totals["half"]) / Decimal("2")
    )

    absence_deduction = money(
        min(
            absent_equivalent_days * per_day_pay,
            basic_salary,
        )
    )

    overtime_minutes, overtime_pay = calculate_overtime(
        employee,
        month,
        year,
        per_day_pay,
    )

    gross_pay = money(
        basic_salary + overtime_pay
    )

    net_pay = money(
        max(
            Decimal("0.00"),
            gross_pay - absence_deduction,
        )
    )

    return PayrollCalculation(
        employee=employee,
        month=month,
        year=year,
        calendar_days=calendar_days,
        present_days=totals["present"],
        half_days=totals["half"],
        absent_days_count=totals["absent"],
        leave_days=totals["leave"],
        absent_equivalent_days=absent_equivalent_days,
        basic_salary=basic_salary,
        per_day_pay=per_day_pay,
        absence_deduction=absence_deduction,
        overtime_minutes=overtime_minutes,
        overtime_pay=overtime_pay,
        gross_pay=gross_pay,
        net_pay=net_pay,
    )


def calculate_payroll_rows(month, year, *, user=None):
    validate_period(month, year)

    employees = (
        Employee.objects
        .filter(is_active=True)
        .select_related(
            "department",
            "position",
            "work_schedule",
        )
        .order_by("name")
    )

    if user is not None:
        employees = scope_queryset(employees, user)
    return [
        calculate_employee_payroll(
            employee,
            month,
            year,
        )
        for employee in employees
    ]


@transaction.atomic
def generate_payroll(month, year, *, user=None):
    """
    Backward-compatible payroll generation.

    This keeps the existing Salary model working while
    the PayrollRun lifecycle is introduced.
    """

    rows = calculate_payroll_rows(
        month, year, user=user,
    )

    for row in rows:
        Salary.objects.update_or_create(
            emp=row.employee,
            month=row.month,
            year=row.year,
            defaults={
                "absent_days": row.absent_equivalent_days,
                "per_day_pay": row.per_day_pay,
                "gross": row.gross_pay,
                "deduction": row.absence_deduction,
                "overtime_minutes": row.overtime_minutes,
                "overtime_pay": row.overtime_pay,
                "net": row.net_pay,
            },
        )

    return len(rows)


def attendance_totals(salary):
    result = salary.emp.attendance.filter(
        date__month=salary.month,
        date__year=salary.year,
    ).aggregate(
        present=Count(
            "id",
            filter=Q(status="P"),
        ),
        half=Count(
            "id",
            filter=Q(status="H"),
        ),
        absent=Count(
            "id",
            filter=Q(status="A"),
        ),
        leave=Count(
            "id",
            filter=Q(status="L"),
        ),
    )

    return result

@transaction.atomic
def create_payroll_run(month, year, user):
    validate_period(month, year)

    run, created = PayrollRun.objects.select_for_update().get_or_create(
        month=month,
        year=year,
        defaults={
            "created_by": user,
            "policy_version": "1.0",
        },
    )

    if run.status in {
        PayrollRun.FINALIZED,
        PayrollRun.REVERSED,
    }:
        raise ValidationError(
            "A finalized or reversed payroll cannot be regenerated."
        )

    return run


@transaction.atomic
def submit_payroll_for_approval(run):
    run = PayrollRun.objects.select_for_update().get(
        pk=run.pk
    )

    if run.status != PayrollRun.DRAFT:
        raise ValidationError(
            "Only draft payroll runs can be submitted."
        )

    rows = calculate_payroll_rows(
        run.month,
        run.year,
    )

    if not rows:
        raise ValidationError(
            "There are no active employees to process."
        )

    run.status = PayrollRun.PENDING_APPROVAL
    run.save(
        update_fields=["status"]
    )

    return run


@transaction.atomic
def approve_payroll(run, user):
    run = PayrollRun.objects.select_for_update().get(
        pk=run.pk
    )

    if run.status != PayrollRun.PENDING_APPROVAL:
        raise ValidationError(
            "Only payroll awaiting approval can be approved."
        )

    run.status = PayrollRun.APPROVED
    run.approved_by = user
    run.approved_at = timezone.now()

    run.save(
        update_fields=[
            "status",
            "approved_by",
            "approved_at",
        ]
    )

    return run


@transaction.atomic
def finalize_payroll(run, user):
    run = PayrollRun.objects.select_for_update().get(
        pk=run.pk
    )

    if run.status != PayrollRun.APPROVED:
        raise ValidationError(
            "Only approved payroll can be finalized."
        )

    generate_payroll(
        run.month,
        run.year,
    )

    run.status = PayrollRun.FINALIZED
    run.finalized_by = user
    run.finalized_at = timezone.now()

    run.save(
        update_fields=[
            "status",
            "finalized_by",
            "finalized_at",
        ]
    )

    return run


@transaction.atomic
def reverse_payroll(run):
    run = PayrollRun.objects.select_for_update().get(
        pk=run.pk
    )

    if run.status != PayrollRun.FINALIZED:
        raise ValidationError(
            "Only finalized payroll can be reversed."
        )

    run.status = PayrollRun.REVERSED

    run.save(
        update_fields=["status"]
    )

    return run
