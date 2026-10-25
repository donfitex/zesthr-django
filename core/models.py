from datetime import date, datetime, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=10, unique=True, help_text="Short code, e.g. FIN")
    work_schedule = models.ForeignKey("WorkSchedule", on_delete=models.PROTECT, null=True, blank=True,
                                      related_name="departments", help_text="Default schedule for this department")
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "department"
        ordering = ["name"]

    def __str__(self):
        return self.name


class JobPosition(models.Model):
    title = models.CharField(max_length=100, unique=True)
    department = models.ForeignKey(Department, on_delete=models.PROTECT, null=True, blank=True,
                                   related_name="positions", help_text="Optional: where this position usually sits")
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "job_position"
        ordering = ["title"]

    def __str__(self):
        return self.title


class EmploymentType(models.Model):
    name = models.CharField(max_length=50, unique=True)

    class Meta:
        db_table = "employment_type"
        ordering = ["name"]

    def __str__(self):
        return self.name


class AppendOnlyQuerySet(models.QuerySet):
    """Audit rows can be added, never changed or removed through the ORM."""

    def update(self, **kwargs):
        raise ValidationError("Audit history cannot be modified.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Audit history cannot be modified.")

    def delete(self):
        raise ValidationError("Audit history cannot be deleted.")


class AppendOnlyModel(models.Model):
    """Base for history tables: insert-only. (Attendance history is additionally protected by database
    triggers, see migration 0014.)"""

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Audit history cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Audit history cannot be deleted.")


def validate_time_zone(value):
    from .timeutil import is_valid_zone

    if value and not is_valid_zone(value):
        raise ValidationError(f"'{value}' is not a valid time zone name (examples: Africa/Lagos, Asia/Kolkata).")


class WorkLocation(models.Model):
    name = models.CharField(max_length=100, unique=True)
    city = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, blank=True)
    time_zone = models.CharField(max_length=64, blank=True, validators=[validate_time_zone],
                                 help_text="Leave blank to use the company time zone")
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "work_location"
        ordering = ["name"]

    def __str__(self):
        return self.name


def default_working_days():
    return [0, 1, 2, 3, 4]  # Monday..Friday


def validate_working_days(value):
    if (not isinstance(value, list) or not value
            or any(not isinstance(d, int) or isinstance(d, bool) or d not in range(7) for d in value)
            or len(set(value)) != len(value)):
        raise ValidationError("Working days must be a non-empty list of unique weekday numbers 0 (Mon) to 6 (Sun).")


class WorkSchedule(models.Model):
    """A reusable shift pattern. Lateness and overtime rules are built on it in Phase 4.

    end_time earlier than start_time means an overnight shift.
    """

    name = models.CharField(max_length=100, unique=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    break_minutes = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(600)],
                                                     help_text="Unpaid break inside the shift; taken off worked time")
    grace_minutes = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(240)],
                                                     help_text="Minutes after the start time before an arrival counts as late")
    early_leave_grace_minutes = models.PositiveSmallIntegerField(
        default=0, validators=[MaxValueValidator(240)],
        help_text="Minutes before the end time that still do not count as leaving early")
    overtime_eligible = models.BooleanField(default=False, help_text="Employees on this schedule are paid for overtime")
    overtime_after_minutes = models.PositiveSmallIntegerField(
        default=30, validators=[MaxValueValidator(480)],
        help_text="Overtime only counts once the employee stays at least this long after the end time")
    overtime_max_minutes = models.PositiveSmallIntegerField(
        default=240, validators=[MaxValueValidator(960)],
        help_text="Most overtime paid for one day after the shift (0 = no limit). Guards against a forgotten punch-out")
    overtime_multiplier = models.DecimalField(max_digits=3, decimal_places=2, default=Decimal("1.50"),
                                              validators=[MinValueValidator(Decimal("1.00"))],
                                              help_text="Overtime pay rate as a multiple of the normal hourly rate")
    is_default = models.BooleanField(default=False, help_text="Used for employees whose department has no schedule")
    working_days = models.JSONField(default=default_working_days, validators=[validate_working_days],
                                    help_text="Weekday numbers, 0=Monday ... 6=Sunday")
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "work_schedule"
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["is_default"], condition=models.Q(is_default=True),
                                               name="work_schedule_single_default")]

    def __str__(self):
        return f"{self.name} ({self.start_time:%H:%M}-{self.end_time:%H:%M})"

    @property
    def is_overnight(self):
        return bool(self.start_time and self.end_time and self.end_time < self.start_time)

    def clean(self):
        if self.start_time and self.end_time and self.start_time == self.end_time:
            raise ValidationError("Start and end time cannot be the same.")
        if self.overtime_max_minutes and self.overtime_max_minutes < self.overtime_after_minutes:
            raise ValidationError({"overtime_max_minutes": "The daily limit cannot be smaller than the minimum overtime."})


class Employee(models.Model):
    ACTIVE_STATUSES = ("ACTIVE", "PROBATION")
    SEPARATED_STATUSES = ("RESIGNED", "TERMINATED", "RETIRED")
    STATUS = [
        ("PROBATION", "On probation"), ("ACTIVE", "Active"), ("SUSPENDED", "Suspended"),
        ("INACTIVE", "Inactive"), ("RESIGNED", "Resigned"), ("TERMINATED", "Terminated"), ("RETIRED", "Retired"),
    ]

    user = models.OneToOneField(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="employee_profile")
    name = models.CharField(max_length=100)
    designation = models.CharField(max_length=100)
    basic_salary = models.DecimalField(max_digits=10, decimal_places=2)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    joined_on = models.DateField(default=date.today)
    # Derived from employment_status on every save (never edit it directly).
    is_active = models.BooleanField(default=True, editable=False)

    employee_number = models.CharField(max_length=20, unique=True, null=True, blank=True,
                                       help_text="Leave blank to generate automatically (EMP-00001)")
    department = models.ForeignKey(Department, on_delete=models.PROTECT, null=True, blank=True, related_name="employees")
    position = models.ForeignKey(JobPosition, on_delete=models.PROTECT, null=True, blank=True, related_name="employees")
    employment_type = models.ForeignKey(EmploymentType, on_delete=models.PROTECT, null=True, blank=True, related_name="employees")
    work_location = models.ForeignKey(WorkLocation, on_delete=models.PROTECT, null=True, blank=True, related_name="employees")
    work_schedule = models.ForeignKey(WorkSchedule, on_delete=models.PROTECT, null=True, blank=True, related_name="employees")
    manager = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="direct_reports")
    employment_status = models.CharField(max_length=10, choices=STATUS, default="ACTIVE")
    confirmation_date = models.DateField(null=True, blank=True, help_text="End of probation")
    separation_date = models.DateField(null=True, blank=True)
    separation_reason = models.CharField(max_length=255, blank=True)
    # Personal details: visible to the employee and to HR only.
    address = models.TextField(blank=True)
    emergency_contact_name = models.CharField(max_length=100, blank=True)
    emergency_contact_phone = models.CharField(max_length=20, blank=True)

    class Meta:
        db_table = "employee"
        ordering = ["name"]
        permissions = [
            ("view_employee_pay", "Can view employee pay details"),
            ("change_employee_pay", "Can change employee pay details"),
            ("link_employee_account", "Can link or unlink an employee's login account"),
            ("deactivate_employee", "Can deactivate and reactivate employees"),
            ("view_employee_personal", "Can view employees' address and emergency contacts"),
        ]
        indexes = [models.Index(fields=["is_active", "department"], name="emp_active_dept_idx")]
        constraints = [
            models.CheckConstraint(condition=models.Q(basic_salary__gte=0), name="emp_basic_salary_non_negative"),
            models.CheckConstraint(
                name="emp_active_flag_matches_status",
                condition=(models.Q(is_active=True, employment_status__in=["ACTIVE", "PROBATION"])
                           | models.Q(is_active=False) & ~models.Q(employment_status__in=["ACTIVE", "PROBATION"]))),
            models.CheckConstraint(
                name="emp_separated_requires_date",
                condition=~models.Q(employment_status__in=["RESIGNED", "TERMINATED", "RETIRED"])
                | models.Q(separation_date__isnull=False)),
            models.CheckConstraint(
                name="emp_separation_not_before_joining",
                condition=models.Q(separation_date__isnull=True) | models.Q(separation_date__gte=models.F("joined_on"))),
            models.CheckConstraint(condition=~models.Q(manager=models.F("id")), name="emp_not_own_manager"),
        ]

    def __str__(self):
        return self.name

    @property
    def is_separated(self):
        return self.employment_status in self.SEPARATED_STATUSES

    def clean(self):
        # is_active is derived; set it before Django validates the DB constraints.
        self.is_active = self.employment_status in self.ACTIVE_STATUSES
        errors = {}
        if self.manager_id:
            if self.pk and self.manager_id == self.pk:
                errors["manager"] = "An employee cannot be their own manager."
            elif self.pk:
                boss = self.manager
                while boss is not None:  # walk up the chain looking for a cycle
                    if boss.pk == self.pk:
                        errors["manager"] = "This would create a reporting loop."
                        break
                    boss = boss.manager
        if self.employment_status in self.SEPARATED_STATUSES and not self.separation_date:
            errors["separation_date"] = "A separation date is required for this status."
        if self.separation_date and self.joined_on and self.separation_date < self.joined_on:
            errors["separation_date"] = "Separation date cannot be before the joining date."
        if self.confirmation_date and self.joined_on and self.confirmation_date < self.joined_on:
            errors["confirmation_date"] = "Confirmation date cannot be before the joining date."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.is_active = self.employment_status in self.ACTIVE_STATUSES
        self.employee_number = (self.employee_number or "").strip() or None
        super().save(*args, **kwargs)
        if self.employee_number is None:
            self.employee_number = f"EMP-{self.pk:05d}"
            type(self).objects.filter(pk=self.pk).update(employee_number=self.employee_number)

    def sick_leaves_used_this_month(self, month=None, year=None):
        today = timezone.localdate()
        m = month or today.month
        y = year or today.year
        return self.leaves.filter(
            leave_type="SL",
            status="APPROVED",
            start_date__month=m,
            start_date__year=y
        ).count()

    def sick_leaves_remaining(self, month=None, year=None):
        return max(0, 1 - self.sick_leaves_used_this_month(month, year))


class Attendance(models.Model):
    STATUS = [("P", "Present"), ("A", "Absent"), ("H", "Half day"), ("L", "Leave")]
    emp = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="attendance")
    date = models.DateField(default=date.today)
    check_in = models.TimeField(null=True, blank=True)
    check_out = models.TimeField(null=True, blank=True)
    ends_next_day = models.BooleanField(default=False, help_text="Overnight shift: the check-out is on the day after the date")
    status = models.CharField(max_length=1, choices=STATUS, default="P")

    class Meta:
        db_table = "attendance"
        unique_together = ("emp", "date")
        ordering = ["-date", "emp__name"]
        permissions = [
            ("view_all_attendance", "Can view attendance of all employees"),
            ("mark_attendance", "Can mark attendance on behalf of employees"),
        ]
        # (emp, date) is already indexed by the unique constraint; this serves the
        # "everyone on a given day" queries (registers, dashboards).
        indexes = [models.Index(fields=["date", "status"], name="att_date_status_idx")]
        constraints = [
            models.CheckConstraint(condition=models.Q(check_out__isnull=True) | models.Q(check_in__isnull=False),
                                   name="att_checkout_needs_checkin"),
            models.CheckConstraint(
                condition=~models.Q(status__in=["A", "L"])
                | (models.Q(check_in__isnull=True) & models.Q(check_out__isnull=True)),
                name="att_absent_leave_has_no_punches"),
            # An overnight shift ends the next day, so its check-out TIME is earlier than the
            # check-in time (otherwise it would be 24 hours or more).
            models.CheckConstraint(
                condition=models.Q(ends_next_day=False)
                | (models.Q(check_out__isnull=False) & models.Q(check_out__lt=models.F("check_in"))),
                name="att_overnight_checkout_is_earlier_time"),
        ]

    def clean(self):
        """Rules for a single attendance row. Used by forms and the admin; services build valid rows themselves."""
        errors = {}
        from .timeutil import today_for

        if self.date and self.date > (today_for(self.emp) if self.emp_id else timezone.localdate()):
            errors["date"] = "Attendance cannot be recorded for a future date."
        if self.emp_id and self.date:
            if self.date < self.emp.joined_on:
                errors["date"] = f"{self.emp.name} joined on {self.emp.joined_on}; earlier dates are not valid."
            elif self.emp.separation_date and self.date > self.emp.separation_date:
                errors["date"] = f"{self.emp.name} left on {self.emp.separation_date}; later dates are not valid."
        if self.status in ("A", "L") and (self.check_in or self.check_out):
            errors["status"] = "Absent and Leave records cannot have check-in or check-out times."
        if self.check_out and not self.check_in:
            errors["check_out"] = "A check-out needs a check-in time."
        elif self.ends_next_day:
            if not (self.check_in and self.check_out) or self.check_out >= self.check_in:
                errors["ends_next_day"] = ("An overnight shift needs both times, with the check-out earlier on the "
                                           "clock than the check-in (e.g. in 22:00, out 06:00 the next day).")
        elif self.check_in and self.check_out and self.check_out <= self.check_in:
            errors["check_out"] = ("Check-out must be after check-in. For an overnight shift tick "
                                   "'check-out is on the next day'.")
        if errors:
            raise ValidationError(errors)

    @property
    def hours(self):
        if self.check_in and self.check_out:
            a = datetime.combine(self.date, self.check_in)
            b = datetime.combine(self.date + timedelta(days=1 if self.ends_next_day else 0), self.check_out)
            return round((b - a).total_seconds() / 3600, 2)
        return None


class Salary(models.Model):
    emp = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="salaries")
    month = models.PositiveSmallIntegerField()
    year = models.PositiveSmallIntegerField()
    absent_days = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    per_day_pay = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    gross = models.DecimalField(max_digits=10, decimal_places=2)
    deduction = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    overtime_minutes = models.PositiveIntegerField(default=0)
    overtime_pay = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    net = models.DecimalField(max_digits=10, decimal_places=2)
    generated_on = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "salary"
        unique_together = ("emp", "month", "year")
        ordering = ["-year", "-month", "emp__name"]
        permissions = [
            ("generate_payroll", "Can generate payroll"),
            ("view_all_payslips", "Can view payslips of all employees"),
            ("view_payroll_report", "Can view payroll and salary reports"),
        ]
        indexes = [models.Index(fields=["year", "month"], name="salary_period_idx")]
        constraints = [
            models.CheckConstraint(condition=models.Q(gross__gte=0), name="salary_gross_non_negative"),
            models.CheckConstraint(condition=models.Q(deduction__gte=0), name="salary_deduction_non_negative"),
            models.CheckConstraint(condition=models.Q(net__gte=0), name="salary_net_non_negative"),
            models.CheckConstraint(condition=models.Q(overtime_pay__gte=0), name="salary_overtime_non_negative"),
        ]


class Holiday(models.Model):
    HOLIDAY_TYPES = [("gazetted", "Gazetted Holiday"), ("restricted", "Restricted Holiday")]
    name = models.CharField(max_length=150)
    date = models.DateField()
    day = models.CharField(max_length=20, blank=True)
    holiday_type = models.CharField(max_length=20, choices=HOLIDAY_TYPES, default="gazetted")
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "holiday"
        ordering = ["date"]

    def __str__(self):
        return f"{self.name} ({self.date})"


class LeaveApplication(models.Model):
    LEAVE_TYPES = [
        ("SL", "Sick Leave (1 day/month max)"),
        ("CL", "Casual Leave"),
        ("PL", "Privilege / Paid Leave"),
    ]
    STATUS = [
        ("PENDING", "Pending"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
    ]
    emp = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="leaves")
    leave_type = models.CharField(max_length=5, choices=LEAVE_TYPES, default="SL")
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.TextField()
    status = models.CharField(max_length=10, choices=STATUS, default="PENDING")
    admin_note = models.CharField(max_length=255, blank=True)
    applied_on = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "leave_application"
        ordering = ["-applied_on"]
        permissions = [
            ("view_all_leaves", "Can view leave applications of all employees"),
            ("approve_leave", "Can approve or reject leave applications"),
        ]
        indexes = [
            models.Index(fields=["status", "applied_on"], name="leave_status_applied_idx"),
            models.Index(fields=["emp", "start_date"], name="leave_emp_start_idx"),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(end_date__gte=models.F("start_date")),
                                   name="leave_end_not_before_start"),
        ]

    @property
    def days_count(self):
        if self.start_date and self.end_date:
            return (self.end_date - self.start_date).days + 1
        return 1

    def __str__(self):
        return f"{self.emp.name} - {self.get_leave_type_display()} ({self.start_date})"



class AccountSecurity(models.Model):
    """Per-login security state that Django's User model does not carry."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="security")
    must_change_password = models.BooleanField(default=False)
    password_changed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "account_security"

    def __str__(self):
        return f"Security state of {self.user}"


class SecurityEvent(AppendOnlyModel):
    """Append-only audit trail of sign-ins and account changes. Never stores passwords."""

    LOGIN_SUCCESS, LOGIN_FAILED, LOGIN_BLOCKED, LOGOUT = "LOGIN_SUCCESS", "LOGIN_FAILED", "LOGIN_BLOCKED", "LOGOUT"
    PASSWORD_CHANGED, PASSWORD_RESET_REQUESTED = "PASSWORD_CHANGED", "PASSWORD_RESET_REQUESTED"
    PASSWORD_RESET_COMPLETED, PASSWORD_CHANGE_REQUIRED = "PASSWORD_RESET_COMPLETED", "PASSWORD_CHANGE_REQUIRED"
    ACCOUNT_DEACTIVATED, ACCOUNT_ACTIVATED = "ACCOUNT_DEACTIVATED", "ACCOUNT_ACTIVATED"
    TYPES = [
        (LOGIN_SUCCESS, "Signed in"), (LOGIN_FAILED, "Failed sign-in"), (LOGIN_BLOCKED, "Sign-in blocked (too many failures)"),
        (LOGOUT, "Signed out"), (PASSWORD_CHANGED, "Password changed"),
        (PASSWORD_RESET_REQUESTED, "Password reset requested"), (PASSWORD_RESET_COMPLETED, "Password reset completed"),
        (PASSWORD_CHANGE_REQUIRED, "Password change required"),
        (ACCOUNT_DEACTIVATED, "Account deactivated"), (ACCOUNT_ACTIVATED, "Account activated"),
    ]

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="security_events")
    username = models.CharField(max_length=150, blank=True, help_text="Name typed or account concerned")
    event_type = models.CharField(max_length=30, choices=TYPES)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    detail = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "security_event"
        ordering = ["-created_at", "-id"]
        permissions = [("view_security_log", "Can view the sign-in and account security log")]
        indexes = [models.Index(fields=["username", "event_type", "created_at"], name="secevent_lookup_idx")]

    def __str__(self):
        return f"{self.get_event_type_display()}: {self.username or self.user_id}"



class EmploymentHistory(AppendOnlyModel):
    """Append-only record of changes to an employee's job details (who, when, from what to what).

    Values are stored as text so the history stays readable after a department or position
    is renamed. Pay changes are flagged `sensitive` and shown only to those who may see pay.
    """

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="history")
    field = models.CharField(max_length=30)
    old_value = models.CharField(max_length=255, blank=True)
    new_value = models.CharField(max_length=255, blank=True)
    sensitive = models.BooleanField(default=False)
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "employment_history"
        ordering = ["-changed_at", "-id"]
        indexes = [models.Index(fields=["employee", "changed_at"], name="emphist_emp_when_idx")]

    def __str__(self):
        return f"{self.employee_id}: {self.field} {self.old_value!r} -> {self.new_value!r}"



class AttendanceAudit(AppendOnlyModel):
    """Append-only trail of every attendance change: what it was, what it became, who and why.

    Survives deletion of the attendance row (record_id and date are copied), and the
    employee cannot be deleted while any audit rows exist.
    """

    CHECK_IN, CHECK_OUT, SET_STATUS = "CHECK_IN", "CHECK_OUT", "SET_STATUS"
    MANUAL_CREATE, MANUAL_EDIT, MANUAL_DELETE = "MANUAL_CREATE", "MANUAL_EDIT", "MANUAL_DELETE"
    ACTIONS = [(CHECK_IN, "Checked in"), (CHECK_OUT, "Checked out"), (SET_STATUS, "Status set"),
               (MANUAL_CREATE, "Entry added"), (MANUAL_EDIT, "Entry corrected"), (MANUAL_DELETE, "Entry deleted")]

    emp = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="attendance_audit")
    date = models.DateField()
    attendance = models.ForeignKey(Attendance, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit")
    record_id = models.PositiveIntegerField(null=True, blank=True)
    action = models.CharField(max_length=15, choices=ACTIONS)
    old_values = models.JSONField(null=True, blank=True)
    new_values = models.JSONField(null=True, blank=True)
    reason = models.CharField(max_length=255, blank=True)
    correction_request = models.ForeignKey("AttendanceCorrectionRequest", on_delete=models.SET_NULL, null=True,
                                           blank=True, related_name="audit_entries")
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "attendance_audit"
        ordering = ["-created_at", "-id"]
        permissions = [("view_attendance_audit", "Can view the attendance change history")]
        indexes = [models.Index(fields=["emp", "date"], name="attaudit_emp_date_idx")]

    def __str__(self):
        return f"{self.get_action_display()}: {self.emp_id} {self.date}"



class AttendanceCorrectionRequest(models.Model):
    """An employee asks for a day's attendance to be corrected; a manager or HR approves or rejects it.

    Approving applies the change (with a full audit entry linked back here); rejecting changes nothing.
    """

    PENDING, APPROVED, REJECTED, CANCELLED = "PENDING", "APPROVED", "REJECTED", "CANCELLED"
    STATUSES = [(PENDING, "Pending"), (APPROVED, "Approved"), (REJECTED, "Rejected"), (CANCELLED, "Cancelled")]

    emp = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="correction_requests")
    date = models.DateField()
    requested_status = models.CharField(max_length=1, choices=Attendance.STATUS, default="P")
    requested_check_in = models.TimeField(null=True, blank=True)
    requested_check_out = models.TimeField(null=True, blank=True)
    requested_ends_next_day = models.BooleanField(default=False)
    reason = models.CharField(max_length=255)
    original_values = models.JSONField(null=True, blank=True, help_text="The record as it was when requested")
    status = models.CharField(max_length=10, choices=STATUSES, default=PENDING)
    requested_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    decided_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "attendance_correction_request"
        ordering = ["-created_at", "-id"]
        permissions = [("review_attendance_corrections", "Can review attendance correction requests for all employees")]
        indexes = [models.Index(fields=["status", "created_at"], name="attcorr_status_idx"),
                   models.Index(fields=["emp", "date"], name="attcorr_emp_date_idx")]
        constraints = [models.UniqueConstraint(fields=["emp", "date"], condition=models.Q(status="PENDING"),
                                               name="attcorr_one_pending_per_day")]

    def __str__(self):
        return f"Correction #{self.pk}: {self.emp_id} {self.date} ({self.status})"

    @property
    def requested_summary(self):
        label = dict(Attendance.STATUS)[self.requested_status]
        times = ""
        if self.requested_check_in or self.requested_check_out:
            times = f" {self.requested_check_in:%H:%M}" if self.requested_check_in else " --"
            times += f" - {self.requested_check_out:%H:%M}" if self.requested_check_out else " - --"
            times += " (+1 day)" if self.requested_ends_next_day else ""
        return f"{label}{times}"


class PayrollComponent(models.Model):
    """
    Reusable earning/deduction definition.

    Examples:
    - Housing Allowance
    - Transport Allowance
    - Medical Allowance
    - Pension
    - Loan Deduction
    """

    EARNING = "EARNING"
    DEDUCTION = "DEDUCTION"

    COMPONENT_TYPES = [
        (EARNING, "Earning"),
        (DEDUCTION, "Deduction"),
    ]

    name = models.CharField(
        max_length=100,
        unique=True,
    )

    code = models.CharField(
        max_length=30,
        unique=True,
    )

    component_type = models.CharField(
        max_length=20,
        choices=COMPONENT_TYPES,
    )

    taxable = models.BooleanField(
        default=False,
    )

    active = models.BooleanField(
        default=True,
    )

    description = models.CharField(
        max_length=255,
        blank=True,
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})"


class EmployeePayrollComponent(models.Model):
    """
    Recurring payroll component assigned to an employee.
    """

    employee = models.ForeignKey(
        Employee,
        on_delete=models.PROTECT,
        related_name="payroll_components",
    )

    component = models.ForeignKey(
        PayrollComponent,
        on_delete=models.PROTECT,
        related_name="employee_assignments",
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    effective_from = models.DateField()

    effective_to = models.DateField(
        null=True,
        blank=True,
    )

    active = models.BooleanField(
        default=True,
    )

    class Meta:
        ordering = [
            "employee",
            "component",
            "-effective_from",
        ]

        indexes = [
            models.Index(
                fields=[
                    "employee",
                    "active",
                ],
                name="emp_pay_component_idx",
            ),
        ]

    def clean(self):
        errors = {}

        if self.amount < 0:
            errors["amount"] = "Amount cannot be negative."

        if (
            self.effective_to
            and self.effective_to < self.effective_from
        ):
            errors["effective_to"] = (
                "End date cannot be earlier than start date."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"{self.employee} - "
            f"{self.component} - "
            f"{self.amount}"
        )


class PayrollAdjustment(models.Model):
    """
    One-time payroll earning or deduction.
    """

    employee = models.ForeignKey(
        Employee,
        on_delete=models.PROTECT,
        related_name="payroll_adjustments",
    )

    month = models.PositiveSmallIntegerField()

    year = models.PositiveSmallIntegerField()

    description = models.CharField(
        max_length=255,
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    component_type = models.CharField(
        max_length=20,
        choices=PayrollComponent.COMPONENT_TYPES,
    )

    approved = models.BooleanField(
        default=False,
    )

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        indexes = [
            models.Index(
                fields=[
                    "employee",
                    "year",
                    "month",
                ],
                name="pay_adjust_period_idx",
            ),
        ]

    def clean(self):
        if self.amount < 0:
            raise ValidationError(
                {"amount": "Adjustment cannot be negative."}
            )

        if not 1 <= self.month <= 12:
            raise ValidationError(
                {"month": "Invalid payroll month."}
            )

    def __str__(self):
        return (
            f"{self.employee} - "
            f"{self.description} - "
            f"{self.amount}"
        )
        
        
class PayrollRun(models.Model):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    FINALIZED = "FINALIZED"
    REVERSED = "REVERSED"

    STATUS_CHOICES = [
        (DRAFT, "Draft"),
        (PENDING_APPROVAL, "Pending approval"),
        (APPROVED, "Approved"),
        (FINALIZED, "Finalized"),
        (REVERSED, "Reversed"),
    ]

    month = models.PositiveSmallIntegerField()
    year = models.PositiveSmallIntegerField()

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=DRAFT,
    )

    policy_version = models.CharField(
        max_length=50,
        default="1.0",
    )

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_payroll_runs",
    )

    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_payroll_runs",
    )

    finalized_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="finalized_payroll_runs",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    approved_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    finalized_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["month", "year"],
                name="unique_payroll_period",
            ),
        ]

        ordering = [
            "-year",
            "-month",
        ]

    def __str__(self):
        return (
            f"Payroll {self.month:02d}/{self.year}"
            f" - {self.get_status_display()}"
        )

    @property
    def is_locked(self):
        return self.status in {
            self.FINALIZED,
            self.REVERSED,
        }
        
        
class HolidayCalendar(models.Model):
    name = models.CharField(
        max_length=100,
        unique=True,
    )

    code = models.CharField(
        max_length=30,
        unique=True,
    )

    country = models.CharField(
        max_length=100,
        blank=True,
    )

    active = models.BooleanField(
        default=True,
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class CalendarHoliday(models.Model):
    calendar = models.ForeignKey(
        HolidayCalendar,
        on_delete=models.CASCADE,
        related_name="holidays",
    )

    name = models.CharField(
        max_length=150,
    )

    date = models.DateField()

    is_working_day = models.BooleanField(
        default=False,
    )

    description = models.CharField(
        max_length=255,
        blank=True,
    )

    class Meta:
        ordering = ["date"]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "calendar",
                    "date",
                ],
                name="unique_calendar_holiday",
            ),
        ]

    def __str__(self):
        return (
            f"{self.calendar.name}: "
            f"{self.name} ({self.date})"
        )
        
        
class Notification(models.Model):
    LEAVE_DECISION = "LEAVE_DECISION"
    LEAVE_PENDING = "LEAVE_PENDING"
    ATTENDANCE_EXCEPTION = "ATTENDANCE_EXCEPTION"

    TYPES = [
        (LEAVE_DECISION, "Leave decision"),
        (LEAVE_PENDING, "Pending leave"),
        (
            ATTENDANCE_EXCEPTION,
            "Attendance exception",
        ),
    ]

    recipient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="notifications",
    )

    notification_type = models.CharField(
        max_length=40,
        choices=TYPES,
    )

    title = models.CharField(
        max_length=150,
    )

    message = models.TextField()

    url = models.CharField(
        max_length=255,
        blank=True,
    )

    unique_key = models.CharField(
        max_length=255,
        blank=True,
    )

    read = models.BooleanField(
        default=False,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["-created_at"]

        indexes = [
            models.Index(
                fields=[
                    "recipient",
                    "read",
                    "created_at",
                ],
                name="notification_user_idx",
            ),
        ]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "recipient",
                    "unique_key",
                ],
                condition=~models.Q(
                    unique_key=""
                ),
                name="unique_user_notification",
            ),
        ]

    def __str__(self):
        return self.title
    