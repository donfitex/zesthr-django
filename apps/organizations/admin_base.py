from django.contrib import admin
from .tenancy import scope_model_queryset


class TenantAdmin(admin.ModelAdmin):
    def get_queryset(self, request):
        return scope_model_queryset(super().get_queryset(request), request.user)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        kwargs["queryset"] = scope_model_queryset(db_field.remote_field.model.objects.all(), request.user)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


