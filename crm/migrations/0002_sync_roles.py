"""Give existing companies' starter roles the permissions for modules added since they were created
(Release 2 modules and the Customer Hub). Anything an admin removed from an older module stays removed."""
from django.db import migrations


def sync(apps, schema_editor):
    from users.defaults import DEFAULT_ROLES, RELEASE_2_CODES, RELEASE_2_MODULES

    Company = apps.get_model("core", "Company")
    Role = apps.get_model("users", "Role")
    for company in Company.objects.all():
        existing = {r.name_en: r for r in Role.objects.filter(company=company, is_system=True)}
        for spec in DEFAULT_ROLES:
            role = existing.get(spec["name_en"])
            if role is None:
                continue
            new = {c for c in spec["perms"] if c.split(".")[0] in RELEASE_2_MODULES or c in RELEASE_2_CODES}
            merged = sorted(set(role.permissions or []) | new)
            if merged != sorted(role.permissions or []):
                role.permissions = merged
                role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [("crm", "0001_initial"), ("users", "0001_initial"), ("core", "0005_batch_e")]
    operations = [migrations.RunPython(sync, migrations.RunPython.noop)]
