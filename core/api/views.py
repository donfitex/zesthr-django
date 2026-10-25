from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from ..models import (
    Attendance,
    Employee,
    LeaveApplication,
    Salary,
)

from .permissions import (
    CanViewAttendance,
    CanViewEmployees,
    CanViewPayroll,
)

from .serializers import (
    AttendanceSerializer,
    EmployeeSerializer,
    LeaveApplicationSerializer,
    SalarySerializer,
)


class EmployeeViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = EmployeeSerializer
    permission_classes = [
        IsAuthenticated,
        CanViewEmployees,
    ]

    def get_queryset(self):
        return (
            Employee.objects
            .filter(is_active=True)
            .select_related(
                "department",
                "position",
            )
            .order_by("name")
        )


class AttendanceViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AttendanceSerializer
    permission_classes = [
        IsAuthenticated,
        CanViewAttendance,
    ]

    def get_queryset(self):
        return (
            Attendance.objects
            .select_related("emp")
            .order_by("-date")
        )


class LeaveApplicationViewSet(
    viewsets.ReadOnlyModelViewSet
):
    serializer_class = LeaveApplicationSerializer
    permission_classes = [
        IsAuthenticated,
    ]

    def get_queryset(self):
        employee = getattr(
            self.request.user,
            "employee_profile",
            None,
        )

        if self.request.user.has_perm(
            "core.view_all_leaves"
        ):
            return LeaveApplication.objects.select_related(
                "emp"
            )

        if not employee:
            return LeaveApplication.objects.none()

        return LeaveApplication.objects.filter(
            emp=employee
        ).select_related("emp")


class SalaryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = SalarySerializer
    permission_classes = [
        IsAuthenticated,
    ]

    def get_queryset(self):
        employee = getattr(
            self.request.user,
            "employee_profile",
            None,
        )

        if self.request.user.has_perm(
            "core.view_all_payslips"
        ):
            return Salary.objects.select_related(
                "emp"
            )

        if not employee:
            return Salary.objects.none()

        return Salary.objects.filter(
            emp=employee
        ).select_related("emp")