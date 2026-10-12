from django import forms

from .models import Attendance, Employee, LeaveApplication

D = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
T = forms.TimeInput(attrs={"type": "time"}, format="%H:%M")


class EmployeeForm(forms.ModelForm):
    class Meta:
        model = Employee
        fields = ["name", "designation", "basic_salary", "email", "phone", "joined_on", "is_active"]
        widgets = {"joined_on": D}


class AttendanceForm(forms.ModelForm):
    class Meta:
        model = Attendance
        fields = ["emp", "date", "status", "check_in", "check_out"]
        widgets = {"date": D, "check_in": T, "check_out": T}
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
        start = cleaned.get("start_date")
        end = cleaned.get("end_date")
        ltype = cleaned.get("leave_type")

        if start and end:
            if end < start:
                raise forms.ValidationError("End date cannot be earlier than start date.")
            
            days = (end - start).days + 1
            if ltype == "SL":
                if days > 1:
                    raise forms.ValidationError(f"Sick leave allowance is strictly 1 day per month. You requested {days} days.")
                
                if self.employee:
                    used = self.employee.sick_leaves_used_this_month(month=start.month, year=start.year)
                    if used >= 1:
                        raise forms.ValidationError(f"You have already exhausted your 1 Sick Leave allocation for {start.strftime('%B %Y')}.")
        return cleaned

