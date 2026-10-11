"""Batch G: add the new Delete and See costs permissions and the purchase order / bill approval limits to every
company's existing roles (see users.defaults.upgrade_roles_batch_g)."""
from django.db import migrations


def upgrade(apps, schema_editor):
    from users.defaults import upgrade_roles_batch_g

    Company = apps.get_model("core", "Company")
    Role = apps.get_model("users", "Role")
    ApprovalLimit = apps.get_model("users", "ApprovalLimit")
    for company in Company.objects.all():
        upgrade_roles_batch_g(company, Role=Role, ApprovalLimit=ApprovalLimit)


class Migration(migrations.Migration):
    dependencies = [("users", "0002_batch_g"), ("crm", "0003_sync_roles_again")]
    operations = [migrations.RunPython(upgrade, migrations.RunPython.noop)]
