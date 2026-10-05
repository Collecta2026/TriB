from django.core.management.base import BaseCommand

from core.services import seed_banks, seed_currencies


class Command(BaseCommand):
    help = "Load or refresh reference currencies and the shared bank list. Safe to run on every deploy."

    def handle(self, *args, **options):
        seed_currencies()
        seed_banks()
        self.stdout.write(self.style.SUCCESS("Currencies and banks are up to date."))
