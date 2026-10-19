"""Roles and the permissions each role grants.

A role is a Django Group. This file is the single source of truth: running
`sync_roles` (also done automatically after every `migrate`) makes each group
hold exactly the permissions listed here, so editing this file and migrating
is how role changes are rolled out.

Codenames are "app_label.codename" strings, as used by user.has_perm().
"""
from django.contrib.auth.models import Group, Permission

SYSTEM_ADMIN = "System Administrator"
HR_ADMIN = "HR Administrator"
HR_OFFICER = "HR Officer"
DEPARTMENT_MANAGER = "Department Manager"
PAYROLL_OFFICER = "Payroll Officer"
EMPLOYEE = "Employee"

# Permission names used by views (kept as constants to avoid typos).
VIEW_EMPLOYEE = "core.view_employee"
ADD_EMPLOYEE = "core.add_employee"
CHANGE_EMPLOYEE = "core.change_employee"
DELETE_EMPLOYEE = "core.delete_employee"
VIEW_EMPLOYEE_PAY = "core.view_employee_pay"
CHANGE_EMPLOYEE_PAY = "core.change_employee_pay"
LINK_EMPLOYEE_ACCOUNT = "core.link_employee_account"
DEACTIVATE_EMPLOYEE = "core.deactivate_employee"
ADD_ATTENDANCE = "core.add_attendance"
CHANGE_ATTENDANCE = "core.change_attendance"
DELETE_ATTENDANCE = "core.delete_attendance"
VIEW_ALL_ATTENDANCE = "core.view_all_attendance"
MARK_ATTENDANCE = "core.mark_attendance"
VIEW_ALL_LEAVES = "core.view_all_leaves"
APPROVE_LEAVE = "core.approve_leave"
GENERATE_PAYROLL = "core.generate_payroll"
VIEW_ALL_PAYSLIPS = "core.view_all_payslips"
VIEW_PAYROLL_REPORT = "core.view_payroll_report"

# Organization reference data (departments, positions, ...), managed in the admin site.
REFERENCE_DATA_PERMISSIONS = [
    f"core.{action}_{model}"
    for model in ("department", "jobposition", "employmenttype", "worklocation", "workschedule")
    for action in ("view", "add", "change", "delete")
]

ROLE_PERMISSIONS = {
    # Manages accounts and groups. Deliberately has NO access to salary data.
    SYSTEM_ADMIN: [
        "auth.view_user", "auth.add_user", "auth.change_user", "auth.delete_user",
        "auth.view_group",
    ],
    # Full HR access, including payroll.
    HR_ADMIN: [
        VIEW_EMPLOYEE, ADD_EMPLOYEE, CHANGE_EMPLOYEE, DELETE_EMPLOYEE,
        VIEW_EMPLOYEE_PAY, CHANGE_EMPLOYEE_PAY, LINK_EMPLOYEE_ACCOUNT, DEACTIVATE_EMPLOYEE,
        *REFERENCE_DATA_PERMISSIONS,
        ADD_ATTENDANCE, CHANGE_ATTENDANCE, DELETE_ATTENDANCE,
        VIEW_ALL_ATTENDANCE, MARK_ATTENDANCE,
        VIEW_ALL_LEAVES, APPROVE_LEAVE,
        GENERATE_PAYROLL, VIEW_ALL_PAYSLIPS, VIEW_PAYROLL_REPORT,
    ],
    # Day-to-day HR work. No salary data, no payroll, cannot add/delete employees.
    HR_OFFICER: [
        VIEW_EMPLOYEE, CHANGE_EMPLOYEE,
        ADD_ATTENDANCE, CHANGE_ATTENDANCE, VIEW_ALL_ATTENDANCE, MARK_ATTENDANCE,
        VIEW_ALL_LEAVES, APPROVE_LEAVE,
    ],
    # Payroll only: reads pay data and attendance, runs payroll. Cannot edit people.
    PAYROLL_OFFICER: [
        VIEW_EMPLOYEE, VIEW_EMPLOYEE_PAY, VIEW_ALL_ATTENDANCE,
        GENERATE_PAYROLL, VIEW_ALL_PAYSLIPS, VIEW_PAYROLL_REPORT,
    ],
    # Self-service only for now. Team-scoped powers need the manager/department
    # relationships added in Commit 2.2, so no org-wide permission is granted.
    DEPARTMENT_MANAGER: [],
    # Self-service (own attendance, leave, payslips) needs no extra permission:
    # it is tied to the user's own employee profile.
    EMPLOYEE: [],
}


def _split(codename):
    app_label, _, code = codename.partition(".")
    return app_label, code


def sync_roles():
    """Create every role group and make it hold exactly its listed permissions."""
    for role, codenames in ROLE_PERMISSIONS.items():
        group, _ = Group.objects.get_or_create(name=role)
        permissions = []
        for full in codenames:
            app_label, code = _split(full)
            permissions.append(
                Permission.objects.get(content_type__app_label=app_label, codename=code)
            )
        group.permissions.set(permissions)
