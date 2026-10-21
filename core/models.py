from datetime import date, datetime

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.db import models
from django.utils import timezone


class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=10, unique=True, help_text="Short code, e.g. FIN")
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


class WorkLocation(models.Model):
    name = models.CharField(max_length=100, unique=True)
    city = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, blank=True)
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
    break_minutes = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(600)])
    grace_minutes = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(240)])
    working_days = models.JSONField(default=default_working_days, validators=[validate_working_days],
                                    help_text="Weekday numbers, 0=Monday ... 6=Sunday")
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "work_schedule"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.start_time:%H:%M}-{self.end_time:%H:%M})"

    def clean(self):
        if self.start_time and self.end_time and self.start_time == self.end_time:
            raise ValidationError("Start and end time cannot be the same.")


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
        ]

    def clean(self):
        """Rules for a single attendance row. Used by forms and the admin; services build valid rows themselves."""
        errors = {}
        if self.date and self.date > timezone.localdate():
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
        elif self.check_in and self.check_out and self.check_out <= self.check_in:
            errors["check_out"] = "Check-out must be after check-in."
        if errors:
            raise ValidationError(errors)

    @property
    def hours(self):
        if self.check_in and self.check_out:
            a = datetime.combine(self.date, self.check_in)
            b = datetime.combine(self.date, self.check_out)
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


class SecurityEvent(models.Model):
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

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Security events cannot be modified.")
        super().save(*args, **kwargs)


class EmploymentHistory(models.Model):
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

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Employment history cannot be modified.")
        super().save(*args, **kwargs)


class AttendanceAudit(models.Model):
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
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "attendance_audit"
        ordering = ["-created_at", "-id"]
        permissions = [("view_attendance_audit", "Can view the attendance change history")]
        indexes = [models.Index(fields=["emp", "date"], name="attaudit_emp_date_idx")]

    def __str__(self):
        return f"{self.get_action_display()}: {self.emp_id} {self.date}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Attendance history cannot be modified.")
        super().save(*args, **kwargs)
