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
import calendar
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Q

from ..models import Attendance, Employee, Salary
from . import schedules

CENT = Decimal("0.01")


def _overtime_by_employee(month, year, per_day_by_emp):
    """{employee id: (overtime minutes, overtime pay)} for employees who earned any."""
    resolver = schedules.ScheduleResolver()
    records = (Attendance.objects
               .filter(date__year=year, date__month=month, status="P", check_out__isnull=False, emp__is_active=True)
               .select_related("emp__work_schedule", "emp__department__work_schedule"))
    minutes, schedule_of = {}, {}
    for rec in records:
        schedule = resolver.for_employee(rec.emp)
        if schedule is None or not schedule.overtime_eligible:
            continue
        result = schedules.evaluate(rec, schedule)
        if result and result.overtime_minutes:
            minutes[rec.emp_id] = minutes.get(rec.emp_id, 0) + result.overtime_minutes
            schedule_of[rec.emp_id] = schedule
    out = {}
    for emp_id, total in minutes.items():
        schedule = schedule_of[emp_id]
        shift = schedules.scheduled_minutes(schedule)
        if not shift or emp_id not in per_day_by_emp:
            continue
        pay = (Decimal(total) * per_day_by_emp[emp_id] * schedule.overtime_multiplier / Decimal(shift)).quantize(CENT)
        out[emp_id] = (total, pay)
    return out


def calculate_payroll_rows(month, year):
    """Per-employee attendance totals and salary figures for active employees."""
    f = Q(attendance__date__month=month, attendance__date__year=year)
    emps = Employee.objects.filter(is_active=True).annotate(
        present=Count("attendance", filter=f & Q(attendance__status="P")),
        half=Count("attendance", filter=f & Q(attendance__status="H")),
        absent=Count("attendance", filter=f & Q(attendance__status="A")),
        leave=Count("attendance", filter=f & Q(attendance__status="L")),
    )
    days = calendar.monthrange(year, month)[1]
    emps = list(emps)
    per_day_by_emp = {e.pk: (e.basic_salary / days).quantize(CENT) for e in emps}
    overtime = _overtime_by_employee(month, year, per_day_by_emp)
    rows = []
    for e in emps:
        per_day = per_day_by_emp[e.pk]
        absent_days = Decimal(e.absent) + Decimal(e.half) / 2
        deduction = min((absent_days * per_day).quantize(CENT), e.basic_salary)
        net = e.basic_salary - deduction
        ot_minutes, ot_pay = overtime.get(e.pk, (0, Decimal("0.00")))
        if ot_pay:
            net += ot_pay  # untouched when there is no overtime
        rows.append({"emp": e, "present": e.present, "half": e.half, "absent": e.absent,
                     "leave": e.leave, "absent_days": absent_days, "per_day": per_day,
                     "deduction": deduction, "overtime_minutes": ot_minutes, "overtime_pay": ot_pay,
                     "net": net})
    return rows


@transaction.atomic
def generate_payroll(month, year):
    """Create or refresh one Salary row per active employee, all-or-nothing."""
    rows = calculate_payroll_rows(month, year)
    for r in rows:
        Salary.objects.update_or_create(
            emp=r["emp"], month=month, year=year,
            defaults={"absent_days": r["absent_days"], "per_day_pay": r["per_day"],
                      # gross = basic pay + overtime, so that net = gross - deduction still holds
                      "gross": r["emp"].basic_salary + r["overtime_pay"], "deduction": r["deduction"],
                      "overtime_minutes": r["overtime_minutes"], "overtime_pay": r["overtime_pay"], "net": r["net"]})
    return len(rows)


def attendance_totals(salary):
    """Attendance counts for the month a salary slip covers."""
    f = Q(date__month=salary.month, date__year=salary.year)
    return salary.emp.attendance.aggregate(
        present=Count("id", filter=f & Q(status="P")), half=Count("id", filter=f & Q(status="H")),
        absent=Count("id", filter=f & Q(status="A")), leave=Count("id", filter=f & Q(status="L")))
