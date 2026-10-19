"""Read-only queries that feed dashboards and lists (no side effects)."""
from django.db.models import Sum

from .models import Attendance, Employee, Holiday, LeaveApplication, Salary


def company_snapshot(today, recent_limit=8):
    """Today's headcount and attendance totals for the whole company."""
    total = Employee.objects.filter(is_active=True).count()
    recs = Attendance.objects.filter(date=today, emp__is_active=True)
    return {
        "total": total,
        "present": recs.filter(status__in=["P", "H"]).count(),
        "absent": recs.filter(status="A").count(),
        "leave": recs.filter(status="L").count(),
        "unmarked": max(0, total - recs.count()),
        "recent": recs.select_related("emp")[:recent_limit],
    }


def employees_managed_by(user):
    """Direct reports of the employee linked to `user` (none if the account has no profile).

    Building block for manager-scoped views (approval queues, team attendance).
    """
    profile = getattr(user, "employee_profile", None)
    if profile is None:
        return Employee.objects.none()
    return Employee.objects.filter(manager=profile, is_active=True)


def pending_leave_count():
    return LeaveApplication.objects.filter(status="PENDING").count()


def net_payroll_total(month, year):
    return Salary.objects.filter(month=month, year=year).aggregate(t=Sum("net"))["t"] or 0


def employee_snapshot(emp, today):
    """Everything an employee's own dashboard shows."""
    return {
        "emp": emp,
        "today": today,
        "today_rec": Attendance.objects.filter(emp=emp, date=today).first(),
        "recent": Attendance.objects.filter(emp=emp).order_by("-date")[:10],
        "leaves": LeaveApplication.objects.filter(emp=emp).order_by("-applied_on")[:5],
        "sick_used": emp.sick_leaves_used_this_month(today.month, today.year),
        "sick_rem": emp.sick_leaves_remaining(today.month, today.year),
        "upcoming_holiday": Holiday.objects.filter(date__gte=today).order_by("date").first(),
        "my_salary": Salary.objects.filter(emp=emp, month=today.month, year=today.year).first(),
    }


def attendance_register(today):
    """(employee, today's record or None) for every active employee."""
    records = {a.emp_id: a for a in Attendance.objects.filter(date=today)}
    return [(e, records.get(e.id)) for e in Employee.objects.filter(is_active=True)]
