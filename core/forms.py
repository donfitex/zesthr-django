from datetime import date

from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q

from .models import Attendance, Employee, LeaveApplication
from .services.leave import validate_leave_request

D = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
T = forms.TimeInput(attrs={"type": "time"}, format="%H:%M")


class EmployeeForm(forms.ModelForm):
    class Meta:
        model = Employee
        fields = ["user", "employee_number", "name", "designation", "basic_salary", "email", "phone", "joined_on",
                  "department", "position", "employment_type", "work_location", "work_schedule", "manager",
                  "employment_status", "confirmation_date",
                  "address", "emergency_contact_name", "emergency_contact_phone"]
        widgets = {"joined_on": D, "confirmation_date": D, "address": forms.Textarea(attrs={"rows": 2})}
        labels = {"user": "Login account", "employment_status": "Status", "employee_number": "Employee ID"}

    def __init__(self, *args, can_edit_pay=False, can_link_account=False, can_edit_personal=True, **kwargs):
        super().__init__(*args, **kwargs)
        # Restricted fields are removed entirely, so a crafted POST cannot set them either.
        if not can_edit_pay:
            del self.fields["basic_salary"]
        if not can_edit_personal:
            for name in ("address", "emergency_contact_name", "emergency_contact_phone"):
                del self.fields[name]
        if not can_link_account:
            del self.fields["user"]
        else:
            # Only active, not-yet-linked accounts (plus this employee's current one).
            current = self.instance.user_id
            self.fields["user"].queryset = (
                get_user_model().objects.filter(is_active=True)
                .filter(Q(employee_profile__isnull=True) | Q(pk=current)).order_by("username")
            )
            self.fields["user"].required = False

        # Separation (resigned, terminated...) goes through the Deactivate action so the
        # login is revoked too; this form only toggles probation <-> active.
        if self.instance.pk and self.instance.employment_status not in Employee.ACTIVE_STATUSES:
            del self.fields["employment_status"]
        else:
            self.fields["employment_status"].choices = [
                c for c in Employee.STATUS if c[0] in Employee.ACTIVE_STATUSES]

        managers = Employee.objects.filter(is_active=True)
        if self.instance.pk:
            managers = managers.exclude(pk=self.instance.pk)
        self.fields["manager"].queryset = managers
        for name in ("department", "position", "employment_type", "work_location", "work_schedule"):
            self.fields[name].queryset = self.fields[name].queryset.filter(
                **({"is_active": True} if hasattr(self.fields[name].queryset.model, "is_active") else {}))


class EmployeeSelfForm(forms.ModelForm):
    """The only fields an employee may change on their own record."""

    class Meta:
        model = Employee
        fields = ["email", "phone", "address", "emergency_contact_name", "emergency_contact_phone"]
        widgets = {"address": forms.Textarea(attrs={"rows": 3})}


class DeactivateEmployeeForm(forms.Form):
    status = forms.ChoiceField(choices=[c for c in Employee.STATUS if c[0] not in Employee.ACTIVE_STATUSES])
    separation_date = forms.DateField(required=False, widget=D, initial=date.today,
                                      help_text="Required for resigned, terminated or retired")
    reason = forms.CharField(required=False, max_length=255)


class AttendanceForm(forms.ModelForm):
    """Manual entry / correction by HR. A reason is mandatory and goes into the audit history."""

    reason = forms.CharField(max_length=255, help_text="Why is this entry being added or corrected? (kept in the history)")

    class Meta:
        model = Attendance
        fields = ["emp", "date", "status", "check_in", "check_out", "ends_next_day"]
        widgets = {"date": D, "check_in": T, "check_out": T}
        labels = {"ends_next_day": "Check-out is on the next day (overnight shift)"}
        labels = {"emp": "Employee"}


class LeaveApplicationForm(forms.ModelForm):
    class Meta:
        model = LeaveApplication
        fields = ["leave_type", "start_date", "end_date", "reason"]
        widgets = {
            "start_date": D,
            "end_date": D,
            "reason": forms.Textarea(attrs={"rows": 3, "placeholder": "Please provide a clear reason for your leave request..."}),
        }

    def __init__(self, *args, **kwargs):
        self.employee = kwargs.pop("employee", None)
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        # The rules live in services.leave so they are shared and testable on their own.
        validate_leave_request(self.employee, cleaned.get("leave_type"),
                               cleaned.get("start_date"), cleaned.get("end_date"))
        return cleaned

