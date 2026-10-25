"""Read models for organization-scoped screens.

Department remains in `core.models` during the incremental migration. This
module is its new owning query boundary; callers outside the legacy facade
should import selectors from here rather than query the model directly.
"""
from django.db.models import Count, Q

from core.models import Department


def department_attendance_summary(day):
    """Return active departments annotated with their attendance for `day`."""
    return (
        Department.objects
        .filter(is_active=True)
        .annotate(
            employee_count=Count(
                "employees",
                filter=Q(employees__is_active=True),
            ),
            present_count=Count(
                "employees__attendance",
                filter=Q(
                    employees__attendance__date=day,
                    employees__attendance__status="P",
                ),
            ),
            absent_count=Count(
                "employees__attendance",
                filter=Q(
                    employees__attendance__date=day,
                    employees__attendance__status="A",
                ),
            ),
        )
        .order_by("name")
    )
