"""Link cheques received through customer payments to their customer, so returned cheques go back on the
right customer's account."""
from django.db import migrations


def link(apps, schema_editor):
    CustomerPayment = apps.get_model("sales", "CustomerPayment")
    Cheque = apps.get_model("banking", "Cheque")
    for payment in CustomerPayment.objects.exclude(cheque=None).only("cheque_id", "customer_id"):
        Cheque.objects.filter(pk=payment.cheque_id, customer=None).update(customer_id=payment.customer_id)


class Migration(migrations.Migration):
    dependencies = [
        ("banking", "0006_cheque_events"),
        ("sales", "0001_initial"),
    ]

    operations = [migrations.RunPython(link, migrations.RunPython.noop)]
