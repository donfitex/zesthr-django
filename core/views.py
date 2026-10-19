import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from .forms import AttendanceForm, EmployeeForm, LeaveApplicationForm
from . import roles
from .models import Attendance, Employee, Holiday, LeaveApplication, Salary
from .permissions import PermissionRequiredMixin, get_employee_profile, permission_required, require_perm

CENT = Decimal("0.01")


def period(request):
    """Month/year filter shared by report, attendance log and payroll."""
    today = timezone.localdate()
    try:
        month, year = int(request.GET.get("month", today.month)), int(request.GET.get("year", today.year))
        if not 1 <= month <= 12:
            raise ValueError
    except ValueError:
        month, year = today.month, today.year
    return {
        "month": month, "year": year,
        "months": [(i, calendar.month_name[i]) for i in range(1, 13)],
        "years": range(today.year - 3, today.year + 2),
    }


def summary(month, year):
    """Per-employee attendance totals + salary: net = basic - (absent_days x per_day_pay)."""
    f = Q(attendance__date__month=month, attendance__date__year=year)
    emps = Employee.objects.filter(is_active=True).annotate(
        present=Count("attendance", filter=f & Q(attendance__status="P")),
        half=Count("attendance", filter=f & Q(attendance__status="H")),
        absent=Count("attendance", filter=f & Q(attendance__status="A")),
        leave=Count("attendance", filter=f & Q(attendance__status="L")),
    )
    days = calendar.monthrange(year, month)[1]
    rows = []
    for e in emps:
        per_day = (e.basic_salary / days).quantize(CENT)
        absent_days = Decimal(e.absent) + Decimal(e.half) / 2
        deduction = min((absent_days * per_day).quantize(CENT), e.basic_salary)
        rows.append({"emp": e, "present": e.present, "half": e.half, "absent": e.absent,
                     "leave": e.leave, "absent_days": absent_days, "per_day": per_day,
                     "deduction": deduction, "net": e.basic_salary - deduction})
    return rows


def home(request):
    """Public landing page. Live company data is shown only to authorized users;
    everyone else sees the template's sample figures."""
    today = timezone.localdate()
    ctx = {"today": today, "month_name": calendar.month_name[today.month], "year": today.year}
    if request.user.has_perm(roles.VIEW_ALL_ATTENDANCE):
        total = Employee.objects.filter(is_active=True).count()
        recs = Attendance.objects.filter(date=today, emp__is_active=True)
        ctx.update(
            total_employees=total,
            present_count=recs.filter(status__in=["P", "H"]).count(),
            absent_count=recs.filter(status="A").count(),
            leave_count=recs.filter(status="L").count(),
            unmarked_count=max(0, total - recs.count()),
            recent_checkins=recs.select_related("emp")[:5],
        )
    if request.user.has_perm(roles.VIEW_PAYROLL_REPORT):
        ctx["payroll_total"] = Salary.objects.filter(month=today.month, year=today.year).aggregate(t=Sum("net"))["t"] or 0
    return render(request, "home.html", ctx)


@login_required
def dashboard(request):
    today = timezone.localdate()
    emp_profile = get_employee_profile(request.user)
    can_see_company = request.user.has_perm(roles.VIEW_ALL_ATTENDANCE)

    # Employee Portal
    if not can_see_company and emp_profile:
        rec = Attendance.objects.filter(emp=emp_profile, date=today).first()
        recent = Attendance.objects.filter(emp=emp_profile).order_by("-date")[:10]
        leaves = LeaveApplication.objects.filter(emp=emp_profile).order_by("-applied_on")[:5]
        sick_used = emp_profile.sick_leaves_used_this_month(today.month, today.year)
        sick_rem = emp_profile.sick_leaves_remaining(today.month, today.year)
        upcoming_holiday = Holiday.objects.filter(date__gte=today).order_by("date").first()
        my_salary = Salary.objects.filter(emp=emp_profile, month=today.month, year=today.year).first()

        ctx = {
            "emp": emp_profile,
            "today": today,
            "today_rec": rec,
            "recent": recent,
            "leaves": leaves,
            "sick_used": sick_used,
            "sick_rem": sick_rem,
            "upcoming_holiday": upcoming_holiday,
            "my_salary": my_salary,
        }
        return render(request, "employee_dashboard.html", ctx)

    # Administrator / HR / payroll portal
    if not can_see_company:
        raise PermissionDenied
    total = Employee.objects.filter(is_active=True).count()
    recs = Attendance.objects.filter(date=today, emp__is_active=True)
    ctx = {
        "total": total,
        "present": recs.filter(status__in=["P", "H"]).count(),
        "absent": recs.filter(status="A").count(),
        "leave": recs.filter(status="L").count(),
        "unmarked": max(0, total - recs.count()),
        "recent": recs.select_related("emp")[:8],
        "today": today,
        # None means "not permitted": the template hides the tile.
        "pending_leaves": (LeaveApplication.objects.filter(status="PENDING").count()
                           if request.user.has_perm(roles.VIEW_ALL_LEAVES) else None),
        "payroll": (Salary.objects.filter(month=today.month, year=today.year).aggregate(t=Sum("net"))["t"] or 0
                    if request.user.has_perm(roles.VIEW_PAYROLL_REPORT) else None),
    }
    return render(request, "dashboard.html", ctx)


# ---------- Employees ----------
class Base(LoginRequiredMixin, SuccessMessageMixin):
    template_name = "form.html"
    title = ""

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx["title"] = self.title
        return ctx


class EmployeeList(PermissionRequiredMixin, ListView):
    permission_required = roles.VIEW_EMPLOYEE
    template_name = "employee_list.html"
    context_object_name = "employees"

    def get_queryset(self):
        qs = Employee.objects.all()
        q, status = self.request.GET.get("q", ""), self.request.GET.get("status", "")
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(designation__icontains=q))
        if status in ("active", "inactive"):
            qs = qs.filter(is_active=status == "active")
        return qs

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx.update(q=self.request.GET.get("q", ""), status=self.request.GET.get("status", ""))
        return ctx


class EmployeeFormMixin:
    """Users without pay-edit permission never see or change the salary field."""

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["can_edit_pay"] = self.request.user.has_perm(roles.CHANGE_EMPLOYEE_PAY)
        return kwargs


class EmployeeCreate(PermissionRequiredMixin, EmployeeFormMixin, Base, CreateView):
    # Creating an employee requires a salary, so it also needs pay-edit rights.
    permission_required = (roles.ADD_EMPLOYEE, roles.CHANGE_EMPLOYEE_PAY)
    model, form_class, title = Employee, EmployeeForm, "Add employee"
    success_url, success_message = reverse_lazy("employee_list"), "Employee added."


class EmployeeUpdate(PermissionRequiredMixin, EmployeeFormMixin, Base, UpdateView):
    permission_required = roles.CHANGE_EMPLOYEE
    model, form_class, title = Employee, EmployeeForm, "Edit employee"
    success_url, success_message = reverse_lazy("employee_list"), "Employee updated."


class EmployeeDelete(PermissionRequiredMixin, Base, DeleteView):
    permission_required = roles.DELETE_EMPLOYEE
    model, title, template_name = Employee, "Delete employee", "confirm_delete.html"
    success_url, success_message = reverse_lazy("employee_list"), "Employee deleted."


# ---------- Attendance ----------
@login_required
def attendance_today(request):
    today = timezone.localdate()
    emp_profile = get_employee_profile(request.user)
    can_mark_others = request.user.has_perm(roles.MARK_ATTENDANCE)

    if request.method == "POST":
        emp_id = request.POST.get("emp_id")
        emp = get_object_or_404(Employee, pk=emp_id) if emp_id else emp_profile

        if not emp:
            messages.error(request, "Employee profile not found.")
            return redirect("attendance_today")

        # Acting on someone else's attendance needs the explicit permission.
        if not can_mark_others and (emp_profile is None or emp.pk != emp_profile.pk):
            raise PermissionDenied

        action = request.POST.get("action")
        # Employees may only punch in/out. Setting a status (absent, half day,
        # leave) changes pay, so it is reserved for attendance managers.
        if action in ("A", "H", "L") and not can_mark_others:
            raise PermissionDenied
        now = timezone.localtime().time().replace(microsecond=0)
        rec, _ = Attendance.objects.get_or_create(emp=emp, date=today)
        if action == "check_in":
            rec.check_in, rec.status = now, "P"
            messages.success(request, f"Punched IN at {now.strftime('%I:%M %p')}.")
        elif action == "check_out":
            rec.check_out = now
            messages.success(request, f"Punched OUT at {now.strftime('%I:%M %p')}.")
        elif action in ("A", "H", "L"):
            rec.status = action
            if action in ("A", "L"):
                rec.check_in = rec.check_out = None
            messages.success(request, f"{emp.name}: status marked as {rec.get_status_display()}.")
        rec.save()

        if not can_mark_others:
            return redirect("dashboard")
        return redirect("attendance_today")

    if not can_mark_others:
        if emp_profile:
            return redirect("dashboard")
        raise PermissionDenied

    records = {a.emp_id: a for a in Attendance.objects.filter(date=today)}
    rows = [(e, records.get(e.id)) for e in Employee.objects.filter(is_active=True)]
    return render(request, "attendance_today.html", {"rows": rows, "today": today})


class AttendanceList(LoginRequiredMixin, ListView):
    """Everyone sees their own log; only users with view_all_attendance see others."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not (
            request.user.has_perm(roles.VIEW_ALL_ATTENDANCE) or get_employee_profile(request.user)
        ):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    template_name = "attendance_list.html"
    context_object_name = "records"

    def get_queryset(self):
        p = period(self.request)
        qs = Attendance.objects.select_related("emp").filter(date__month=p["month"], date__year=p["year"])
        if not self.request.user.has_perm(roles.VIEW_ALL_ATTENDANCE):
            return qs.filter(emp=get_employee_profile(self.request.user))
        emp = self.request.GET.get("emp")
        return qs.filter(emp_id=emp) if emp else qs

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx.update(period(self.request))
        can_see_all = self.request.user.has_perm(roles.VIEW_ALL_ATTENDANCE)
        ctx.update(is_staff=can_see_all, emp=self.request.GET.get("emp", ""),
                   employees=Employee.objects.all() if can_see_all else Employee.objects.none())
        return ctx


class AttendanceCreate(PermissionRequiredMixin, Base, CreateView):
    permission_required = roles.ADD_ATTENDANCE
    model, form_class, title = Attendance, AttendanceForm, "Add attendance entry"
    success_url, success_message = reverse_lazy("attendance_list"), "Attendance saved."


class AttendanceUpdate(PermissionRequiredMixin, Base, UpdateView):
    permission_required = roles.CHANGE_ATTENDANCE
    model, form_class, title = Attendance, AttendanceForm, "Edit attendance entry"
    success_url, success_message = reverse_lazy("attendance_list"), "Attendance updated."


class AttendanceDelete(PermissionRequiredMixin, Base, DeleteView):
    permission_required = roles.DELETE_ATTENDANCE
    model, title, template_name = Attendance, "Delete attendance entry", "confirm_delete.html"
    success_url, success_message = reverse_lazy("attendance_list"), "Entry deleted."


# ---------- Reports & payroll ----------
@permission_required(roles.VIEW_PAYROLL_REPORT)
def monthly_report(request):
    p = period(request)
    rows = summary(p["month"], p["year"])
    p.update(rows=rows, total_net=sum(r["net"] for r in rows), total_ded=sum(r["deduction"] for r in rows),
             month_name=calendar.month_name[p["month"]])
    return render(request, "report.html", p)


@permission_required(roles.VIEW_PAYROLL_REPORT)
def payroll(request):
    p = period(request)
    if request.method == "POST":
        require_perm(request.user, roles.GENERATE_PAYROLL)
        for r in summary(p["month"], p["year"]):
            Salary.objects.update_or_create(
                emp=r["emp"], month=p["month"], year=p["year"],
                defaults={"absent_days": r["absent_days"], "per_day_pay": r["per_day"],
                          "gross": r["emp"].basic_salary, "deduction": r["deduction"], "net": r["net"]})
        messages.success(request, "Payroll generated.")
        return redirect(f"{request.path}?month={p['month']}&year={p['year']}")
    slips = Salary.objects.select_related("emp").filter(month=p["month"], year=p["year"])
    p.update(slips=slips, total=slips.aggregate(t=Sum("net"))["t"] or 0,
             month_name=calendar.month_name[p["month"]])
    return render(request, "payroll.html", p)


@login_required
def slip(request, pk):
    emp_profile = get_employee_profile(request.user)
    slips = Salary.objects.select_related("emp")
    if not request.user.has_perm(roles.VIEW_ALL_PAYSLIPS):
        if not emp_profile:
            raise PermissionDenied
        slips = slips.filter(emp=emp_profile)  # someone else's slip is a 404, not a hint it exists
    s = get_object_or_404(slips, pk=pk)
    f = Q(date__month=s.month, date__year=s.year)
    counts = s.emp.attendance.aggregate(
        present=Count("id", filter=f & Q(status="P")), half=Count("id", filter=f & Q(status="H")),
        absent=Count("id", filter=f & Q(status="A")), leave=Count("id", filter=f & Q(status="L")))
    return render(request, "slip.html", {"s": s, "c": counts, "month_name": calendar.month_name[s.month]})


# ---------- Holidays & Leaves ----------
@login_required
def holidays_list(request):
    today = timezone.localdate()
    holidays = Holiday.objects.all().order_by("date")
    h_type = request.GET.get("type")
    if h_type in ("gazetted", "restricted"):
        holidays = holidays.filter(holiday_type=h_type)
    return render(request, "holidays.html", {
        "holidays": holidays,
        "today": today,
        "selected_type": h_type or "all",
    })


@login_required
def leaves_list(request):
    today = timezone.localdate()
    can_manage = request.user.has_perm(roles.VIEW_ALL_LEAVES)
    emp_profile = get_employee_profile(request.user)

    if not can_manage and not emp_profile:
        raise PermissionDenied

    if not can_manage:
        leaves = LeaveApplication.objects.filter(emp=emp_profile).order_by("-applied_on")
        sick_used = emp_profile.sick_leaves_used_this_month(today.month, today.year)
        sick_rem = emp_profile.sick_leaves_remaining(today.month, today.year)
        return render(request, "leaves_list.html", {
            "leaves": leaves,
            "is_staff": False,
            "sick_used": sick_used,
            "sick_rem": sick_rem,
            "emp": emp_profile,
            "today": today,
        })

    status_filter = request.GET.get("status")
    qs = LeaveApplication.objects.select_related("emp").all().order_by("-applied_on")
    if status_filter in ("PENDING", "APPROVED", "REJECTED"):
        qs = qs.filter(status=status_filter)
    pending_count = LeaveApplication.objects.filter(status="PENDING").count()
    return render(request, "leaves_list.html", {
        "leaves": qs,
        "is_staff": True,
        "pending_count": pending_count,
        "selected_status": status_filter or "ALL",
        "today": today,
    })


@login_required
def leave_apply(request):
    today = timezone.localdate()
    emp_profile = getattr(request.user, "employee_profile", None)

    if not emp_profile:
        emp_profile = Employee.objects.filter(is_active=True).first()
        if not emp_profile:
            messages.error(request, "No employee record found to apply for leave.")
            return redirect("leaves_list")

    sick_used = emp_profile.sick_leaves_used_this_month(today.month, today.year)
    sick_rem = emp_profile.sick_leaves_remaining(today.month, today.year)

    if request.method == "POST":
        form = LeaveApplicationForm(request.POST, employee=emp_profile)
        if form.is_valid():
            leave = form.save(commit=False)
            leave.emp = emp_profile
            leave.status = "PENDING"
            leave.save()
            messages.success(request, f"Leave application for {leave.days_count} day(s) submitted. Awaiting HR review.")
            return redirect("leaves_list")
    else:
        form = LeaveApplicationForm(employee=emp_profile, initial={"start_date": today, "end_date": today})

    return render(request, "leave_apply.html", {
        "form": form,
        "emp": emp_profile,
        "sick_used": sick_used,
        "sick_rem": sick_rem,
        "today": today,
    })


@permission_required(roles.APPROVE_LEAVE)
def leave_action(request, pk):

    leave = get_object_or_404(LeaveApplication.objects.select_related("emp"), pk=pk)
    if request.method == "POST":
        action = request.POST.get("action")
        note = request.POST.get("admin_note", "").strip()
        if action == "approve":
            leave.status = "APPROVED"
            leave.admin_note = note
            leave.save()
            curr = leave.start_date
            while curr <= leave.end_date:
                Attendance.objects.update_or_create(
                    emp=leave.emp, date=curr,
                    defaults={"status": "L", "check_in": None, "check_out": None}
                )
                curr += timedelta(days=1)
            messages.success(request, f"Leave for {leave.emp.name} approved. Dates recorded as Paid Leave.")
        elif action == "reject":
            leave.status = "REJECTED"
            leave.admin_note = note
            leave.save()
            messages.info(request, f"Leave application for {leave.emp.name} rejected.")

    return redirect("leaves_list")

