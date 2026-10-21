from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

from . import roles
from .services import accounts
from .models import (AttendanceAudit, SecurityEvent, Attendance, Department, Employee, EmploymentType, JobPosition, Salary, WorkLocation,
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
        if u.has_perm(roles.VIEW_EMPLOYEE_PERSONAL):
            fields += ["address", "emergency_contact_name", "emergency_contact_phone"]
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


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    """Read-only here: every change must go through the app, which demands a reason and keeps history."""

    list_display = ("emp", "date", "status", "check_in", "check_out")
    list_filter = ("status",)
    date_hierarchy = "date"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AttendanceAudit)
class AttendanceAuditAdmin(admin.ModelAdmin):
    list_display = ("created_at", "emp", "date", "action", "reason", "changed_by")
    list_filter = ("action",)
    search_fields = ("emp__name", "reason")
    date_hierarchy = "created_at"

    def has_view_permission(self, request, obj=None):
        return request.user.has_perm(roles.VIEW_ATTENDANCE_AUDIT)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

admin.site.register(Salary)


admin.site.unregister(User)


@admin.register(User)
class HROSUserAdmin(UserAdmin):
    """Users created here are 'provisioned': they must choose their own password at first sign-in."""

    actions = ["require_password_change", "deactivate_accounts", "activate_accounts"]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change:
            accounts.require_password_change(obj, by=request.user)

    @admin.action(description="Require a password change at next sign-in")
    def require_password_change(self, request, queryset):
        for user in queryset:
            accounts.require_password_change(user, by=request.user)
        self.message_user(request, f"{queryset.count()} account(s) must change their password.")

    @admin.action(description="Deactivate selected accounts (revokes access immediately)")
    def deactivate_accounts(self, request, queryset):
        done = 0
        for user in queryset.exclude(pk=request.user.pk):  # never lock yourself out
            accounts.set_account_active(user, False, by=request.user)
            done += 1
        if queryset.filter(pk=request.user.pk).exists():
            self.message_user(request, "You cannot deactivate your own account.", messages.WARNING)
        self.message_user(request, f"{done} account(s) deactivated.")

    @admin.action(description="Activate selected accounts")
    def activate_accounts(self, request, queryset):
        for user in queryset:
            accounts.set_account_active(user, True, by=request.user)
        self.message_user(request, f"{queryset.count()} account(s) activated.")


@admin.register(SecurityEvent)
class SecurityEventAdmin(admin.ModelAdmin):
    """Read-only audit trail: nobody can add, edit or delete entries from here."""

    list_display = ("created_at", "event_type", "username", "ip_address", "detail")
    list_filter = ("event_type",)
    search_fields = ("username", "ip_address")
    date_hierarchy = "created_at"

    def has_view_permission(self, request, obj=None):
        return request.user.has_perm(roles.VIEW_SECURITY_LOG)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
