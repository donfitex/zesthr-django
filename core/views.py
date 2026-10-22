import calendar

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.db import transaction
from django.core.exceptions import PermissionDenied
from django.db.models import Q, ProtectedError, Sum
from django.http import Http404
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from . import roles, selectors, timeutil
from .forms import AttendanceForm, DeactivateEmployeeForm, EmployeeForm, EmployeeSelfForm, LeaveApplicationForm
from .models import Attendance, AttendanceAudit, Department, Employee, Holiday, LeaveApplication, Salary
from .permissions import (PermissionRequiredMixin, employee_access, get_employee_profile, permission_required,
                          require_employee_profile, require_perm)
from .services import attendance as attendance_service
from .services import employees as employee_service
from .services import history as history_service
from .services import leave as leave_service
from .services import payroll as payroll_service
from .services import schedules as schedules_service

<<<<<<< HEAD

from core.selectors import get_filtered_attendance, get_missing_punch_report, get_attendance_exceptions_report
from core.services.attendance import submit_bulk_attendance, process_correction_request

from datetime import datetime
from core.forms import BulkAttendanceForm

=======
>>>>>>> parent of ab78984 ( feat: improve attendance administration)
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
        return _employee_portal(request, emp_profile, today)

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
    paginate_by = 20

    def filters(self):
        g = self.request.GET
        status = g.get("status", "")
        valid = {"active", "inactive", *(code for code, _ in Employee.STATUS)}
        department = g.get("department", "")
        return {"q": g.get("q", "").strip(), "status": status if status in valid else "",
                "department": department if department.isdigit() else ""}

    def get_queryset(self):
        f = self.filters()
        qs = Employee.objects.select_related("department", "position")
        if f["q"]:
            qs = qs.filter(Q(name__icontains=f["q"]) | Q(designation__icontains=f["q"])
                           | Q(employee_number__icontains=f["q"]) | Q(email__icontains=f["q"])
                           | Q(department__name__icontains=f["q"]) | Q(position__title__icontains=f["q"]))
        if f["status"] in ("active", "inactive"):
            qs = qs.filter(is_active=f["status"] == "active")
        elif f["status"]:
            qs = qs.filter(employment_status=f["status"])
        if f["department"]:
            qs = qs.filter(department_id=int(f["department"]))
        return qs.order_by("name", "pk")

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx.update(self.filters(), departments=Department.objects.all(), statuses=Employee.STATUS,
                   total_matches=ctx["paginator"].count)
        return ctx


@login_required
def employee_detail(request, pk):
    emp = get_object_or_404(Employee.objects.select_related(
        "department", "position", "employment_type", "work_location", "work_schedule", "manager", "user"), pk=pk)
    access = employee_access(request.user, emp)
    if not access.can_view:
        raise Http404  # not "forbidden": do not even confirm that this employee exists
    return render(request, "employee_detail.html", _profile_context(emp, access))


def _profile_context(emp, access):
    ctx = {"emp": emp, "access": access, "history": [], "reports": []}
    if access.employment:
        events = emp.history.select_related("changed_by")
        ctx["history"] = [h for h in events if access.pay or not h.sensitive]
        ctx["reports"] = emp.direct_reports.filter(is_active=True).select_related("position")
    return ctx


@login_required
def my_profile(request):
    emp = require_employee_profile(request.user, active=False)
    return render(request, "employee_detail.html", _profile_context(emp, employee_access(request.user, emp)))


@login_required
def my_profile_edit(request):
    emp = require_employee_profile(request.user)
    form = EmployeeSelfForm(request.POST or None, instance=emp)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Your details were updated.")
        return redirect("my_profile")
    return render(request, "form.html", {"form": form, "title": "Edit my details"})


class EmployeeFormMixin:
    """Users without pay-edit permission never see or change the salary field."""

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["can_edit_pay"] = self.request.user.has_perm(roles.CHANGE_EMPLOYEE_PAY)
        kwargs["can_link_account"] = self.request.user.has_perm(roles.LINK_EMPLOYEE_ACCOUNT)
        kwargs["can_edit_personal"] = self.request.user.has_perm(roles.VIEW_EMPLOYEE_PERSONAL)
        return kwargs


class EmployeeCreate(PermissionRequiredMixin, EmployeeFormMixin, Base, CreateView):
    # Creating an employee requires a salary, so it also needs pay-edit rights.
    permission_required = (roles.ADD_EMPLOYEE, roles.CHANGE_EMPLOYEE_PAY)

    def form_valid(self, form):
        with transaction.atomic():
            response = super().form_valid(form)
            history_service.record_created(self.object, self.request.user)
        return response
    model, form_class, title = Employee, EmployeeForm, "Add employee"
    success_url, success_message = reverse_lazy("employee_list"), "Employee added."


class EmployeeUpdate(PermissionRequiredMixin, EmployeeFormMixin, Base, UpdateView):
    permission_required = roles.CHANGE_EMPLOYEE

    def form_valid(self, form):
        before = history_service.refresh_and_snapshot(self.object.pk)  # DB values, before the save
        with transaction.atomic():
            response = super().form_valid(form)
            history_service.record_changes(before, self.object, self.request.user)
        return response
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
def _employee_portal(request, emp, today):
    ctx = selectors.employee_snapshot(emp, timeutil.today_for(emp))  # the employee's own local day
    # Notifications may link to a named route or to (route, id); resolve here so templates stay simple.
    from django.urls import reverse
    for note in ctx["notifications"]:
        target = note["url"]
        note["href"] = (reverse(target[0], args=[target[1]]) if isinstance(target, tuple)
                        else reverse(target) if target else "")
    return render(request, "employee_dashboard.html", ctx)


@login_required
def my_portal(request):
    """The employee view of the dashboard. HR staff who are also employees reach it from here."""
    emp = require_employee_profile(request.user, active=False)
    return _employee_portal(request, emp, timezone.localdate())


@permission_required(roles.DEACTIVATE_EMPLOYEE)
def employee_deactivate(request, pk):
    emp = get_object_or_404(Employee, pk=pk)
    if not emp.is_active:
        messages.info(request, f"{emp.name} is already inactive.")
        return redirect("employee_list")
    form = DeactivateEmployeeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            employee_service.deactivate_employee(emp, by=request.user, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"{emp.name} deactivated. Their records are kept and their login is disabled.")
            return redirect("employee_list")
    return render(request, "employee_deactivate.html", {"form": form, "emp": emp})


@permission_required(roles.DEACTIVATE_EMPLOYEE)
def employee_reactivate(request, pk):
    emp = get_object_or_404(Employee, pk=pk)
    if request.method == "POST":
        employee_service.reactivate_employee(emp, by=request.user)
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

        reason = request.POST.get("reason", "")
        try:
            if action == "check_in":
                rec = attendance_service.check_in(emp, by=request.user)
                messages.success(request, f"Punched IN at {rec.check_in.strftime('%I:%M %p')}.")
            elif action == "check_out":
                rec = attendance_service.check_out(emp, by=request.user)
                messages.success(request, f"Punched OUT at {rec.check_out.strftime('%I:%M %p')}.")
            elif action in attendance_service.MARKABLE_STATUSES:
                rec = attendance_service.mark_status(emp, action, by=request.user, reason=reason)
                messages.success(request, f"{emp.name}: status marked as {rec.get_status_display()}.")
            else:
                # Unknown action: change nothing (it used to create a "Present" record).
                messages.error(request, "Unknown attendance action.")
        except attendance_service.AttendanceError as exc:
            messages.error(request, str(exc))

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
        qs = Attendance.objects.select_related("emp", "emp__work_schedule", "emp__department__work_schedule") \
            .filter(date__month=p["month"], date__year=p["year"])
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
        resolver = schedules_service.ScheduleResolver()
        for rec in ctx["records"]:  # what each day's punches mean under the employee's schedule
            rec.day = schedules_service.evaluate(rec, resolver.for_employee(rec.emp))
        return ctx


class AttendanceCreate(PermissionRequiredMixin, Base, CreateView):
    permission_required = roles.ADD_ATTENDANCE
    model, form_class, title = Attendance, AttendanceForm, "Add attendance entry"
    success_url, success_message = reverse_lazy("attendance_list"), "Attendance saved."

    def form_valid(self, form):
        with transaction.atomic():
            response = super().form_valid(form)
            attendance_service.record_manual_change(AttendanceAudit.MANUAL_CREATE, self.object, None,
                                                    by=self.request.user, reason=form.cleaned_data["reason"])
        return response


class AttendanceUpdate(PermissionRequiredMixin, Base, UpdateView):
    permission_required = roles.CHANGE_ATTENDANCE
    model, form_class, title = Attendance, AttendanceForm, "Edit attendance entry"
    success_url, success_message = reverse_lazy("attendance_list"), "Attendance updated."

    def form_valid(self, form):
        # The in-memory object already carries the form's values; the original is what the database holds.
        before = attendance_service.snapshot(Attendance.objects.get(pk=self.object.pk))
        with transaction.atomic():
            response = super().form_valid(form)
            attendance_service.record_manual_change(AttendanceAudit.MANUAL_EDIT, self.object, before,
                                                    by=self.request.user, reason=form.cleaned_data["reason"])
        return response


class AttendanceDelete(PermissionRequiredMixin, Base, DeleteView):
    permission_required = roles.DELETE_ATTENDANCE
    model, title, template_name = Attendance, "Delete attendance entry", "attendance_confirm_delete.html"
    success_url, success_message = reverse_lazy("attendance_list"), "Entry deleted."

    def form_valid(self, form):
        reason = self.request.POST.get("reason", "").strip()
        if not reason:
            return self.render_to_response(self.get_context_data(form=form, reason_error=True))
        rec = self.object
        with transaction.atomic():
            attendance_service.record_manual_change(
                AttendanceAudit.MANUAL_DELETE, rec, attendance_service.snapshot(rec), by=self.request.user,
                reason=reason, deleted=True, day=rec.date, emp=rec.emp)
            return super().form_valid(form)


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
             month_name=calendar.month_name[p["month"]],
             any_overtime=slips.filter(overtime_pay__gt=0).exists())
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
    return render(request, "slip.html", {"s": s, "c": counts, "month_name": calendar.month_name[s.month],
                                         "basic": s.gross - s.overtime_pay,
                                         "overtime_text": schedules_service.minutes_text(s.overtime_minutes)})


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
<<<<<<< HEAD

@login_required
@permission_required('core.view_attendance') # Removed raise_exception
def admin_attendance_dashboard(request):
    """
    Master registry grid with interactive search combinations.
    """
    # Alternative: if you strictly want a 403 instead of a login redirect:
    # if not request.user.has_perm('core.view_attendance'):
    #     raise PermissionDenied
        
    filters = {
        'employee_id': request.GET.get('employee'),
        'department_id': request.GET.get('department'),
        'start_date': request.GET.get('start_date'),
        'end_date': request.GET.get('end_date'),
    }
    
    context = {
        'attendance_records': get_filtered_attendance(filters),
        'departments': Department.objects.all(),
        'employees': Employee.objects.filter(is_active=True),
        'selected_filters': filters
    }
    return render(request, 'core/admin_attendance_list.html', context)

@login_required
@permission_required('core.can_review_corrections') # Removed raise_exception
def review_corrections_queue(request):
    """
    Unified manager hub for confirming or rejecting historical changes.
    """
    if request.method == 'POST':
        req_id = request.POST.get('request_id')
        action = request.POST.get('action') # 'APPROVED' or 'REJECTED'
        notes = request.POST.get('review_notes', '')
        
        try:
            process_correction_request(req_id, action, request.user, notes)
        except ValueError as e:
            # Handle cleanly if already edited concurrently
            pass
        return redirect('review_corrections_queue')

    context = {
        'pending_requests': AttendanceCorrectionRequest.objects.filter(status='PENDING').select_related('employee')
    }
    return render(request, 'core/admin_corrections_queue.html', context)

@login_required
@permission_required('core.change_attendance')
def bulk_attendance_entry(request):
    """
    Process bulk record injection using safe multi-record database transactions.
    """
    if request.method == 'POST':
        form = BulkAttendanceForm(request.POST)
        if form.is_valid():
            employee_ids = [emp.id for emp in form.cleaned_data['employees']]
            date_target = form.cleaned_data['date']
            
            # Combine current date with input times to construct absolute datetimes
            check_in_dt = None
            check_out_dt = None
            if form.cleaned_data['check_in']:
                check_in_dt = timezone.make_aware(datetime.combine(date_target, form.cleaned_data['check_in']))
            if form.cleaned_data['check_out']:
                check_out_dt = timezone.make_aware(datetime.combine(date_target, form.cleaned_data['check_out']))
                
            submit_bulk_attendance(
                employee_ids=employee_ids,
                date=date_target,
                check_in_time=check_in_dt,
                check_out_time=check_out_dt,
                author_user=request.user,
                reason=form.cleaned_data['reason']
            )
            return redirect('admin_attendance_dashboard')
    else:
        form = BulkAttendanceForm(initial={'date': timezone.now().date()})
        
    return render(request, 'core/admin_bulk_entry.html', {'form': form})

@login_required
@permission_required('core.view_attendance')
def attendance_anomaly_reports(request):
    """
    Central operations workspace for Missing-Punch registers and Exception metrics.
    """
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    
    # Establish dynamic fallbacks if dates are omitted
    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else timezone.now().date()
    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else timezone.now().date()
    
    context = {
        'missing_punches': get_missing_punch_report(start_date, end_date),
        'exceptions': get_attendance_exceptions_report(start_date, end_date),
        'start_date': start_date,
        'end_date': end_date
    }
    return render(request, 'core/admin_anomaly_reports.html', context)
=======
>>>>>>> parent of ab78984 ( feat: improve attendance administration)
