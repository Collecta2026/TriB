"""Database-level guarantee that every journal entry balances (PostgreSQL only).

The check runs at commit time (DEFERRABLE INITIALLY DEFERRED), so an entry can be written line by line
inside one transaction, but can never be committed with debits different from credits.

The SQL deliberately contains no percent signs, so no database driver can mistake part of it for a
query placeholder.
"""
from django.db import migrations

CREATE_FUNCTION = """
CREATE OR REPLACE FUNCTION ledger_check_entry_balanced() RETURNS trigger AS $$
DECLARE
    v_entry bigint;
    v_diff numeric;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_entry := OLD.entry_id;
    ELSE
        v_entry := NEW.entry_id;
    END IF;
    SELECT COALESCE(SUM(l.debit), 0) - COALESCE(SUM(l.credit), 0) INTO v_diff
    FROM ledger_journalline l WHERE l.entry_id = v_entry;
    IF v_diff <> 0 THEN
        RAISE EXCEPTION USING MESSAGE =
            'Journal entry ' || v_entry::text || ' does not balance (difference ' || v_diff::text || ')';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql
"""

DROP_TRIGGER = "DROP TRIGGER IF EXISTS ledger_entry_balanced ON ledger_journalline"

CREATE_TRIGGER = """
CREATE CONSTRAINT TRIGGER ledger_entry_balanced
    AFTER INSERT OR UPDATE OR DELETE ON ledger_journalline
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION ledger_check_entry_balanced()
"""

DROP_FUNCTION = "DROP FUNCTION IF EXISTS ledger_check_entry_balanced()"


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for sql in (CREATE_FUNCTION, DROP_TRIGGER, CREATE_TRIGGER):
        schema_editor.execute(sql, params=None)


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for sql in (DROP_TRIGGER, DROP_FUNCTION):
        schema_editor.execute(sql, params=None)


class Migration(migrations.Migration):
    dependencies = [("ledger", "0002_initial")]
    operations = [migrations.RunPython(forwards, backwards)]
