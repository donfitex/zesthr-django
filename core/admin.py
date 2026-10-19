from django.contrib import admin

from . import roles
from .models import (Attendance, Department, Employee, EmploymentType, JobPosition, Salary, WorkLocation,
                     WorkSchedule)


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    """The admin site must not be a back door around the role rules."""

    list_display = ("employee_number", "name", "department", "position", "employment_status")
    list_filter = ("employment_status", "department")
    search_fields = ("name", "designation", "employee_number")

    # Lifecycle changes go through the app's Deactivate/Reactivate actions, which also
    # revoke or restore the login; the admin must not bypass them.
    LIFECYCLE_FIELDS = ["employment_status", "separation_date", "separation_reason"]

    def get_fields(self, request, obj=None):
        fields = ["user", "employee_number", "name", "designation", "basic_salary", "email", "phone",
                  "joined_on", "department", "position", "employment_type", "work_location",
                  "work_schedule", "manager", "confirmation_date", *self.LIFECYCLE_FIELDS]
        u = request.user
        if not (u.has_perm(roles.VIEW_EMPLOYEE_PAY) or u.has_perm(roles.CHANGE_EMPLOYEE_PAY)):
            fields.remove("basic_salary")
        return fields

    def get_readonly_fields(self, request, obj=None):
        readonly = list(self.LIFECYCLE_FIELDS)
        u = request.user
        # Visible-but-locked for users who may see pay but not change it. (Users who
        # may not even see it never get the field: see get_fields.)
        if u.has_perm(roles.VIEW_EMPLOYEE_PAY) and not u.has_perm(roles.CHANGE_EMPLOYEE_PAY):
            readonly.append("basic_salary")
        if not request.user.has_perm(roles.LINK_EMPLOYEE_ACCOUNT):
            readonly.append("user")
        return readonly

    def has_add_permission(self, request):
        # A new employee needs a salary, so it also needs pay-edit rights.
        return (super().has_add_permission(request)
                and request.user.has_perm(roles.CHANGE_EMPLOYEE_PAY))


for model in (Department, JobPosition, EmploymentType, WorkLocation, WorkSchedule):
    admin.site.register(model)
admin.site.register(Attendance)
admin.site.register(Salary)
