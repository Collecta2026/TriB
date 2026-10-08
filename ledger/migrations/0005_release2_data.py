"""Give companies created before Release 2 the new accounts, VAT rates and starter-role permissions."""
from django.db import migrations


def forwards(apps, schema_editor):
    from ledger.coa import ensure_release_2
    from users.defaults import DEFAULT_ROLES, RELEASE_2_CODES, RELEASE_2_MODULES

    Company = apps.get_model("core", "Company")
    Account = apps.get_model("ledger", "Account")
    TaxRate = apps.get_model("ledger", "TaxRate")
    Role = apps.get_model("users", "Role")
    for company in Company.objects.all():
        ensure_release_2(company, Account=Account, TaxRate=TaxRate)
        existing = {r.name_en: r for r in Role.objects.filter(company=company, is_system=True)}
        for spec in DEFAULT_ROLES:
            role = existing.get(spec["name_en"])
            if role is None:
                Role.objects.create(company=company, name_en=spec["name_en"], name_ar=spec["name_ar"],
                                    permissions=list(spec["perms"]), is_system=True)
                continue
            new = {c for c in spec["perms"] if c.split(".")[0] in RELEASE_2_MODULES or c in RELEASE_2_CODES}
            merged = sorted(set(role.permissions or []) | new)
            if merged != sorted(role.permissions or []):
                role.permissions = merged
                role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [
        ("ledger", "0004_journalline_reconciliation_alter_account_subtype_and_more"),
        ("users", "0001_initial"),
        ("core", "0003_bookmark_recurringtemplate_attachment_userpreference"),
    ]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
