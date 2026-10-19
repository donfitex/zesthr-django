import calendar

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Q, ProtectedError, Sum
from django.http import Http404
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from . import roles, selectors
from .forms import AttendanceForm, DeactivateEmployeeForm, EmployeeForm, LeaveApplicationForm
from .models import Attendance, Employee, Holiday, LeaveApplication, Salary
from .permissions import (PermissionRequiredMixin, get_employee_profile, permission_required,
                          require_employee_profile, require_perm)
from .services import attendance as attendance_service
from .services import employees as employee_service
from .services import leave as leave_service
from .services import payroll as payroll_service

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


def home(request):
    """Public landing page. Live company data is shown only to authorized users;
    everyone else sees the template's sample figures."""
    today = timezone.localdate()
    ctx = {"today": today, "month_name": calendar.month_name[today.month], "year": today.year}
    if request.user.has_perm(roles.VIEW_ALL_ATTENDANCE):
        snap = selectors.company_snapshot(today, recent_limit=5)
        ctx.update(total_employees=snap["total"], present_count=snap["present"],
                   absent_count=snap["absent"], leave_count=snap["leave"],
                   unmarked_count=snap["unmarked"], recent_checkins=snap["recent"])
    if request.user.has_perm(roles.VIEW_PAYROLL_REPORT):
        ctx["payroll_total"] = selectors.net_payroll_total(today.month, today.year)
    return render(request, "home.html", ctx)


@login_required
def dashboard(request):
    today = timezone.localdate()
    emp_profile = get_employee_profile(request.user)
    can_see_company = request.user.has_perm(roles.VIEW_ALL_ATTENDANCE)

    # Employee portal
    if not can_see_company and emp_profile:
        return render(request, "employee_dashboard.html", selectors.employee_snapshot(emp_profile, today))

    # Administrator / HR / payroll portal
    if not can_see_company:
        raise PermissionDenied
    ctx = selectors.company_snapshot(today)
    ctx["today"] = today
    # None means "not permitted": the template hides the tile.
    ctx["pending_leaves"] = (selectors.pending_leave_count()
                             if request.user.has_perm(roles.VIEW_ALL_LEAVES) else None)
    ctx["payroll"] = (selectors.net_payroll_total(today.month, today.year)
                      if request.user.has_perm(roles.VIEW_PAYROLL_REPORT) else None)
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
        kwargs["can_link_account"] = self.request.user.has_perm(roles.LINK_EMPLOYEE_ACCOUNT)
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

    def form_valid(self, form):
        try:
            return super().form_valid(form)
        except ProtectedError:
            messages.error(self.request, "This employee has attendance, leave or payroll history and cannot "
                                         "be deleted. Deactivate the employee instead.")
            return redirect("employee_list")
    model, title, template_name = Employee, "Delete employee", "confirm_delete.html"
    success_url, success_message = reverse_lazy("employee_list"), "Employee deleted."


# ---------- Attendance ----------
@permission_required(roles.DEACTIVATE_EMPLOYEE)
def employee_deactivate(request, pk):
    emp = get_object_or_404(Employee, pk=pk)
    if not emp.is_active:
        messages.info(request, f"{emp.name} is already inactive.")
        return redirect("employee_list")
    form = DeactivateEmployeeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            employee_service.deactivate_employee(emp, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"{emp.name} deactivated. Their records are kept and their login is disabled.")
            return redirect("employee_list")
    return render(request, "form.html", {"form": form, "title": f"Deactivate {emp.name}"})


@permission_required(roles.DEACTIVATE_EMPLOYEE)
def employee_reactivate(request, pk):
    emp = get_object_or_404(Employee, pk=pk)
    if request.method == "POST":
        employee_service.reactivate_employee(emp)
        messages.success(request, f"{emp.name} reactivated.")
    return redirect("employee_list")


@login_required
def attendance_today(request):
    today = timezone.localdate()
    emp_profile = get_employee_profile(request.user)
    can_mark_others = request.user.has_perm(roles.MARK_ATTENDANCE)

    if request.method == "POST":
        raw_id = request.POST.get("emp_id")
        try:
            emp_id = int(raw_id) if raw_id else None
        except ValueError:
            raise Http404("Unknown employee.")

        if can_mark_others and emp_id is not None:
            emp = get_object_or_404(Employee, pk=emp_id)
        else:
            # Self-service: the employee always comes from the logged-in account.
            emp = require_employee_profile(request.user)
            # A submitted id that points at someone else is tampering, not a typo.
            if emp_id is not None and emp_id != emp.pk:
                raise PermissionDenied

        action = request.POST.get("action")
        # Employees may only punch in/out. Setting a status (absent, half day,
        # leave) changes pay, so it is reserved for attendance managers.
        if action in attendance_service.MARKABLE_STATUSES and not can_mark_others:
            raise PermissionDenied

        if action == "check_in":
            rec = attendance_service.check_in(emp)
            messages.success(request, f"Punched IN at {rec.check_in.strftime('%I:%M %p')}.")
        elif action == "check_out":
            rec = attendance_service.check_out(emp)
            messages.success(request, f"Punched OUT at {rec.check_out.strftime('%I:%M %p')}.")
        elif action in attendance_service.MARKABLE_STATUSES:
            rec = attendance_service.mark_status(emp, action)
            messages.success(request, f"{emp.name}: status marked as {rec.get_status_display()}.")
        else:
            # Unknown action: change nothing (it used to create a "Present" record).
            messages.error(request, "Unknown attendance action.")

        if not can_mark_others:
            return redirect("dashboard")
        return redirect("attendance_today")

    if not can_mark_others:
        if emp_profile:
            return redirect("dashboard")
        raise PermissionDenied

    return render(request, "attendance_today.html",
                  {"rows": selectors.attendance_register(today), "today": today})


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
    rows = payroll_service.calculate_payroll_rows(p["month"], p["year"])
    p.update(rows=rows, total_net=sum(r["net"] for r in rows), total_ded=sum(r["deduction"] for r in rows),
             month_name=calendar.month_name[p["month"]])
    return render(request, "report.html", p)


@permission_required(roles.VIEW_PAYROLL_REPORT)
def payroll(request):
    p = period(request)
    if request.method == "POST":
        require_perm(request.user, roles.GENERATE_PAYROLL)
        payroll_service.generate_payroll(p["month"], p["year"])
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
    counts = payroll_service.attendance_totals(s)
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
    # The applicant is always the logged-in user's own (active) employee profile.
    emp_profile = require_employee_profile(request.user)

    sick_used = emp_profile.sick_leaves_used_this_month(today.month, today.year)
    sick_rem = emp_profile.sick_leaves_remaining(today.month, today.year)

    if request.method == "POST":
        form = LeaveApplicationForm(request.POST, employee=emp_profile)
        if form.is_valid():
            leave = leave_service.submit_leave(emp_profile, **form.cleaned_data)
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
            leave_service.approve_leave(leave, note)
            messages.success(request, f"Leave for {leave.emp.name} approved. Dates recorded as Paid Leave.")
        elif action == "reject":
            leave_service.reject_leave(leave, note)
            messages.info(request, f"Leave application for {leave.emp.name} rejected.")

    return redirect("leaves_list")
