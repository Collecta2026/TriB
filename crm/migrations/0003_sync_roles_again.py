"""Run the starter-role update from 0002 once more. On the live site 0002 ran before users/defaults.py with the
Customer Hub permissions had been uploaded, so non-owner roles could be missing them. Adding only, never removing,
so running it twice is harmless."""
import importlib

from django.db import migrations


def sync(apps, schema_editor):
    importlib.import_module("crm.migrations.0002_sync_roles").sync(apps, schema_editor)


class Migration(migrations.Migration):
    dependencies = [("crm", "0002_sync_roles")]
    operations = [migrations.RunPython(sync, migrations.RunPython.noop)]
