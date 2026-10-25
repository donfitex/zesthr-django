from django.contrib import admin

from .models import Branch, Company, CostCenter, Division, JobGrade, Organization, Team


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "default_time_zone", "default_currency", "is_active")
    search_fields = ("name", "code")
    list_filter = ("is_active",)


@admin.register(Company, Branch, Division, Team, JobGrade, CostCenter)
class OrganizationReferenceAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_active")
    search_fields = ("name", "code")
    list_filter = ("is_active",)
