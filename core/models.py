from datetime import date, datetime

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class Employee(models.Model):
    user = models.OneToOneField(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="employee_profile")
    name = models.CharField(max_length=100)
    designation = models.CharField(max_length=100)
    basic_salary = models.DecimalField(max_digits=10, decimal_places=2)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    joined_on = models.DateField(default=date.today)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "employee"
        ordering = ["name"]

    def __str__(self):
        return self.name

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
    emp = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="attendance")
    date = models.DateField(default=date.today)
    check_in = models.TimeField(null=True, blank=True)
    check_out = models.TimeField(null=True, blank=True)
    status = models.CharField(max_length=1, choices=STATUS, default="P")

    class Meta:
        db_table = "attendance"
        unique_together = ("emp", "date")
        ordering = ["-date", "emp__name"]

    @property
    def hours(self):
        if self.check_in and self.check_out:
            a = datetime.combine(self.date, self.check_in)
            b = datetime.combine(self.date, self.check_out)
            return round((b - a).total_seconds() / 3600, 2)
        return None


class Salary(models.Model):
    emp = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="salaries")
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
    emp = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="leaves")
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

    @property
    def days_count(self):
        if self.start_date and self.end_date:
            return (self.end_date - self.start_date).days + 1
        return 1

    def __str__(self):
        return f"{self.emp.name} - {self.get_leave_type_display()} ({self.start_date})"

