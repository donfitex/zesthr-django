"""Read-only queries that feed dashboards and lists (no side effects)."""
import calendar
from datetime import date, timedelta

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


def punch_state(emp, record):
    """What the punch card should offer: 'inactive', 'marked' (leave/absent set by HR),
    'not_in', 'in' or 'done'."""
    if not emp.is_active:
        return "inactive"
    if record and record.check_in and record.check_out:
        return "done"
    if record and record.check_in:
        return "in"
    if record and record.status in ("A", "L", "H"):
        return "marked"
    return "not_in"


def month_summary(emp, today):
    """This month's attendance totals, computed from the same records the log shows."""
    records = list(Attendance.objects.filter(emp=emp, date__year=today.year, date__month=today.month))
    counts = {code: 0 for code in "PHAL"}
    hours = 0.0
    for r in records:
        counts[r.status] = counts.get(r.status, 0) + 1
        hours += r.hours or 0
    return {"present": counts["P"], "half": counts["H"], "absent": counts["A"], "leave": counts["L"],
            "hours": round(hours, 2), "marked_days": len(records)}


def leave_taken_this_year(emp, today):
    """[(leave type label, approved days falling inside this year)], skipping zero rows."""
    first, last = date(today.year, 1, 1), date(today.year, 12, 31)
    # short names: drop the rule note in brackets, e.g. "Sick Leave (1 day/month max)"
    labels = {code: label.split(" (")[0] for code, label in LeaveApplication.LEAVE_TYPES}
    days = {}
    approved = LeaveApplication.objects.filter(emp=emp, status="APPROVED", start_date__lte=last, end_date__gte=first)
    for leave in approved:
        inside = (min(leave.end_date, last) - max(leave.start_date, first)).days + 1
        days[leave.leave_type] = days.get(leave.leave_type, 0) + max(inside, 0)
    return [(labels[code], n) for code, n in days.items() if n]


def employee_notifications(emp, today, limit=6):
    """Things worth the employee's attention, worked out from live data (not stored)."""
    notes = []

    def add(level, text, url=None):
        notes.append({"level": level, "text": text, "url": url})

    if not emp.is_active:
        add("warn", "Your employee record is inactive, so punching and leave requests are switched off. Contact HR.")
    for rec in Attendance.objects.filter(emp=emp, date__lt=today, date__gte=today - timedelta(days=7),
                                         check_in__isnull=False, check_out__isnull=True, status__in=["P", "H"]):
        add("warn", f"You did not punch out on {rec.date:%a %d %b}. Ask HR to correct it.")
    pending = LeaveApplication.objects.filter(emp=emp, status="PENDING").count()
    if pending:
        add("info", f"{pending} leave request{'s' if pending != 1 else ''} awaiting a decision.", "leaves_list")
    decided = LeaveApplication.objects.filter(emp=emp, status__in=["APPROVED", "REJECTED"],
                                              applied_on__date__gte=today - timedelta(days=30)).order_by("-applied_on")[:3]
    for leave in decided:
        verdict = "approved" if leave.status == "APPROVED" else "not approved"
        note = f" Note: {leave.admin_note}" if leave.admin_note else ""
        add("success" if leave.status == "APPROVED" else "warn",
            f"Your {leave.get_leave_type_display()} request for {leave.start_date:%d %b} was {verdict}.{note}", "leaves_list")
    for slip in Salary.objects.filter(emp=emp, generated_on__date__gte=today - timedelta(days=30)).order_by("-year", "-month")[:2]:
        add("success", f"Your payslip for {calendar.month_name[slip.month]} {slip.year} is available.", ("slip", slip.pk))
    holiday = Holiday.objects.filter(date__in=[today, today + timedelta(days=1)]).order_by("date").first()
    if holiday:
        when = "Today" if holiday.date == today else "Tomorrow"
        add("info", f"{when} is a holiday: {holiday.name}.", "holidays")
    if emp.employment_status == "PROBATION" and emp.confirmation_date \
            and today <= emp.confirmation_date <= today + timedelta(days=14):
        add("info", f"Your probation is due to end on {emp.confirmation_date:%d %b %Y}.")
    if not emp.phone or not emp.emergency_contact_name:
        add("info", "Complete your contact details (phone and emergency contact).", "my_profile_edit")
    order = {"warn": 0, "success": 1, "info": 2}
    return sorted(notes, key=lambda n: order[n["level"]])[:limit]


def employee_snapshot(emp, today):
    """Everything an employee's own dashboard shows. Only ever reads this employee's rows."""
    record = Attendance.objects.filter(emp=emp, date=today).first()
    return {
        "emp": emp,
        "today": today,
        "today_rec": record,
        "punch_state": punch_state(emp, record),
        "today_holiday": Holiday.objects.filter(date=today).first(),
        "month": month_summary(emp, today),
        "recent": Attendance.objects.filter(emp=emp).order_by("-date")[:10],
        "leaves": LeaveApplication.objects.filter(emp=emp).order_by("-applied_on")[:5],
        "pending_leaves": LeaveApplication.objects.filter(emp=emp, status="PENDING").count(),
        "leave_taken": leave_taken_this_year(emp, today),
        "sick_used": emp.sick_leaves_used_this_month(today.month, today.year),
        "sick_rem": emp.sick_leaves_remaining(today.month, today.year),
        "holidays": [{"holiday": h, "days_away": (h.date - today).days}
                     for h in Holiday.objects.filter(date__gte=today).order_by("date")[:3]],
        "payslips": Salary.objects.filter(emp=emp).order_by("-year", "-month")[:6],
        "notifications": employee_notifications(emp, today),
    }


def attendance_register(today):
    """(employee, today's record or None) for every active employee."""
    records = {a.emp_id: a for a in Attendance.objects.filter(date=today)}
    return [(e, records.get(e.id)) for e in Employee.objects.filter(is_active=True)]
