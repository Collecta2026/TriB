"""Every existing company gets a main warehouse."""
from django.db import migrations


def forwards(apps, schema_editor):
    Company = apps.get_model("core", "Company")
    Warehouse = apps.get_model("inventory", "Warehouse")
    for company in Company.objects.all():
        if not Warehouse.objects.filter(company=company).exists():
            Warehouse.objects.create(company=company, code="MAIN", name_en="Main warehouse", name_ar="المخزن الرئيسي")


class Migration(migrations.Migration):
    dependencies = [("inventory", "0001_initial")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
