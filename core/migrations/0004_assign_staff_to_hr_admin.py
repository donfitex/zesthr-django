from django.db import migrations

HR_ADMIN = "HR Administrator"


def staff_to_hr_admin(apps, schema_editor):
    """Before roles existed, `is_staff` meant "HR administrator" in this app.

    Keep those accounts working: put every non-superuser staff user in the HR
    Administrator group. Superusers already have every permission.
    """
    User = apps.get_model("auth", "User")
    Group = apps.get_model("auth", "Group")
    staff = User.objects.filter(is_staff=True, is_superuser=False)
    if not staff.exists():
        return
    group, _ = Group.objects.get_or_create(name=HR_ADMIN)
    for user in staff:
        user.groups.add(group)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_role_permissions"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]
    operations = [migrations.RunPython(staff_to_hr_admin, migrations.RunPython.noop)]
