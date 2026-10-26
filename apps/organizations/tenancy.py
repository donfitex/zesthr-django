"""Tenant-scope primitives used by domain selectors and services."""
from .models import Organization, OrganizationMembership


def organization_ids_for(user):
    if not getattr(user, "is_authenticated", False):
        return Organization.objects.none().values_list("id", flat=True)
    if user.is_superuser:
        return Organization.objects.values_list("id", flat=True)
    cached = getattr(user, "_hros_organization_ids", None)
    if cached is not None:
        return cached
    memberships = list(OrganizationMembership.objects.filter(
        user=user, is_active=True
    ).values_list("organization_id", flat=True))
    if memberships:
        user._hros_organization_ids = memberships
        return memberships
    # Preserve access for deployments that have not yet created a second tenant.
    # Once multi-tenant data exists, an administrator must assign a membership.
    organization_ids = list(Organization.objects.values_list("id", flat=True)[:2])
    user._hros_organization_ids = organization_ids if len(organization_ids) == 1 else []
    return user._hros_organization_ids


def scope_queryset(queryset, user, organization_field="organization"):
    """Restrict an organization-owned queryset to the request user's tenant scope."""
    if getattr(user, "is_superuser", False):
        return queryset
    return queryset.filter(**{f"{organization_field}__in": organization_ids_for(user)})


def scope_model_queryset(queryset, user):
    """Explicit ownership paths for models presented in forms and administration."""
    paths = {
        "organization": "pk", "organizationmembership": "organization",
        "company": "organization", "branch": "company__organization",
        "division": "company__organization", "team": "division__company__organization",
        "jobgrade": "company__organization", "costcenter": "company__organization",
        "employee": "organization", "department": "organization",
        "jobposition": "department__organization",
        "attendance": "emp__organization", "attendanceaudit": "emp__organization",
        "salary": "emp__organization", "leaveapplication": "emp__organization",
    }
    path = paths.get(queryset.model._meta.model_name)
    if path is None:
        return queryset  # shared schedule and employment-type reference data
    if queryset.model._meta.model_name == "jobposition":
        from django.db.models import Q
        return queryset.filter(Q(department__isnull=True) | Q(
            department__organization__in=organization_ids_for(user)))
    return scope_queryset(queryset, user, path)
