"""Load a demo company (Scientific Gate, sample figures) for local testing and sales demos.

The password for the three demo users comes from the TRIB_DEMO_PASSWORD environment variable
(put it in your local .env). Refuses to run when DEBUG is off, so it never touches production data.
"""
import os
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from approvals import services as approvals
from banking.models import Bank
from banking.services import create_bank_account
from core.models import Company, ExchangeRate
from core.services import bootstrap_company, seed_banks, seed_currencies
from ledger.models import Account
from ledger.services import Line, post_journal
from users.models import ApprovalLimit, Membership, Role, User
from vouchers.models import Voucher, VoucherLine
from vouchers.services import submit

DEMO_NAME = "Scientific Gate (demo)"


class Command(BaseCommand):
    help = "Create a demo company with sample users, bank accounts, vouchers and cheques."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo only runs with DEBUG=1 (local development).")
        password = os.environ.get("TRIB_DEMO_PASSWORD", "")
        if len(password) < 10:
            raise CommandError("Set TRIB_DEMO_PASSWORD (10+ characters) in your local .env first.")
        existing = Company.objects.filter(name_en=DEMO_NAME).first()
        if existing:
            from inventory.models import Item
            if Item.objects.filter(company=existing).exists():
                self.stdout.write("The demo company already exists.")
                return
            from . import _demo_r2
            owner = existing.memberships.filter(is_owner=True).first().user
            with transaction.atomic():
                _demo_r2.build(existing, owner, existing.bank_accounts.filter(currency_id="EGP", kind="bank").first())
            self.stdout.write(self.style.SUCCESS("Release 2 demo data added (products, stock, sales, staff, assets)."))
            return
        seed_currencies()
        seed_banks()
        with transaction.atomic():
            self._build(password)
        self.stdout.write(self.style.SUCCESS(
            "Demo ready. Sign in as demo-owner@trib.local, demo-finance@trib.local or demo-cashier@trib.local "
            "with the password from TRIB_DEMO_PASSWORD."
        ))

    def _user(self, email, name, password):
        return User.objects.create_user(email, password, full_name=name)

    def _build(self, password):
        today = timezone.localdate()
        owner = self._user("demo-owner@trib.local", "Zak Saleh", password)
        company = bootstrap_company(name_en=DEMO_NAME, name_ar="البوابة العلمية (تجريبي)", owner=owner)
        company.address = "Nasr City, Cairo"
        company.tax_id = "000-000-000"
        company.save()
        for email, name, role in (("demo-finance@trib.local", "Mona Adel", "Finance manager"),
                                  ("demo-cashier@trib.local", "Karim Hassan", "Cashier")):
            m = Membership.objects.create(user=self._user(email, name, password), company=company)
            m.roles.add(Role.objects.get(company=company, name_en=role))
        # Demo supplier payments run into millions, so the finance manager gets a higher payment limit.
        ApprovalLimit.objects.filter(role__company=company, role__name_en="Finance manager", doc_type="payment").update(
            max_amount=Decimal("10000000"))
        fm = User.objects.get(email="demo-finance@trib.local")
        cashier = User.objects.get(email="demo-cashier@trib.local")

        bank = lambda short: Bank.objects.get(company=None, country="EG", short_name=short)  # noqa: E731
        cib = create_bank_account(company, kind="bank", currency="EGP", name_en="CIB · Current account",
                                  name_ar="البنك التجاري الدولي · جاري", bank=bank("CIB"), account_number="100004417", user=owner)
        cib_usd = create_bank_account(company, kind="bank", currency="USD", name_en="CIB · USD account",
                                      name_ar="البنك التجاري الدولي · دولار", bank=bank("CIB"), account_number="100009203", user=owner)
        nbe = create_bank_account(company, kind="bank", currency="EGP", name_en="National Bank of Egypt · Current",
                                  name_ar="البنك الأهلي المصري · جاري", bank=bank("NBE"), account_number="200000581", user=owner)
        create_bank_account(company, kind="bank", currency="USD", name_en="FABMISR · USD account",
                            name_ar="بنك أبوظبي الأول مصر · دولار", bank=bank("FAB"), account_number="300007730", user=owner)
        cash = company.bank_accounts.get(kind="cash")
        rate = Decimal("48.65")
        for back in range(0, 120, 7):
            ExchangeRate.objects.get_or_create(company=company, currency_id="USD", date=today - timedelta(days=back),
                                               defaults={"rate": rate})

        acc = lambda code: Account.objects.get(company=company, code=code)  # noqa: E731
        start = today.replace(month=1, day=1)
        post_journal(company, start, [Line(cib.gl_account, debit=Decimal("15000000")), Line(acc("3100"), credit=Decimal("15000000"))],
                     memo="Opening balance", source="opening", user=owner)
        post_journal(company, start, [
            Line(cib_usd.gl_account, debit=Decimal("9730000"), currency="USD", amount_fc=Decimal("200000"), rate=rate),
            Line(acc("3100"), credit=Decimal("9730000"), currency="USD", amount_fc=Decimal("200000"), rate=rate),
        ], memo="Opening balance", source="opening", user=owner)

        def voucher(kind, creator, date, lines, **fields):
            v = Voucher.objects.create(company=company, kind=kind, created_by=creator, date=date,
                                       currency_id=fields.pop("currency", "EGP"), **fields)
            for line in lines:
                VoucherLine.objects.create(voucher=v, **line)
            submit(v, creator)
            return v

        clinics = ["Cairo Dental Center", "Nile Smile Clinics", "Alex Ortho Center", "Smile Clinic, Heliopolis",
                   "Giza Dental Hospital", "Delta Dental Care"]
        months = max(today.month, 1)
        for i in range(months):
            day = start.replace(month=i + 1, day=12)
            if day > today:
                break
            amount = Decimal(6800000 + 450000 * i)
            voucher("receipt", owner, day, [{"account": acc("4100"), "amount": amount, "description": "Dental equipment sales"}],
                    party_name=clinics[i % len(clinics)], method="bank", bank_account=cib if i % 2 == 0 else nbe,
                    description="Monthly sales collection")

        def pay(date, account, amount, party, desc, approve=True, bank_account=cib):
            v = voucher("payment", cashier, date, [{"account": acc(account), "amount": Decimal(amount), "description": desc}],
                        party_name=party, method="bank", bank_account=bank_account, description=desc)
            req = v.current_request
            while approve and req and req.status == "pending":
                approver = fm if approvals.check_authority(req, fm) is None else owner
                approvals.decide(req, approver, "approve", "OK")
                req.refresh_from_db()
            return v

        for i in range(months):
            day = start.replace(month=i + 1, day=20)
            if day > today:
                break
            pay(day, "5100", 4600000 + 300000 * i, "Medent Italia S.r.l.", "Cost of dental chairs sold",
                bank_account=cib if i % 2 == 0 else nbe)
            pay(day, "5200", 640000, "Payroll", "Salaries")
            pay(day, "5300", 160000, "Nasr City Properties", "Office and warehouse rent")
        pay(today - timedelta(days=6), "5400", 310000, "Damietta Clearing Co.", "Freight & clearing SHP-0409")
        pay(today - timedelta(days=4), "5500", 120000, "AEEDC exhibition stand", "Marketing & exhibitions")
        pay(today - timedelta(days=3), "5700", 18500, "CIB", "Bank charges")
        # Waiting for approval.
        pay(today - timedelta(days=1), "5400", 62000, "Cairo Airport Cargo", "Clearing SHP-0415", approve=False)
        pay(today, "2110", 300000, "Alpha Dental GmbH", "Supplier settlement", approve=False)
        voucher("journal", cashier, today, [
            {"account": acc("5710"), "debit": Decimal("31248"), "description": "FX revaluation, September"},
            {"account": acc("2150"), "credit": Decimal("31248"), "description": "FX revaluation, September"},
        ], description="FX revaluation, September")
        # Post-dated cheques received.
        for number, party, days, amount in (("10048832", "Cairo Dental Center", 2, "125000"),
                                            ("55120917", "Nile Smile Clinics", 3, "112000"),
                                            ("30077145", "Alex Ortho Center", 5, "75000"),
                                            ("40011290", "Giza Dental Hospital", 40, "260000")):
            voucher("receipt", owner, today - timedelta(days=10), [{"account": acc("1130"), "amount": Decimal(amount)}],
                    party_name=party, method="cheque", cheque_number=number, cheque_bank="Banque Misr",
                    cheque_due_date=today + timedelta(days=days), description="Post-dated cheque")
        # A small cash sale to the cash box.
        voucher("receipt", owner, today, [{"account": acc("4200"), "amount": Decimal("38500"), "description": "Service visit"}],
                party_name="Walk-in clinic", method="cash", bank_account=cash, description="Maintenance service")
        from . import _demo_r2
        _demo_r2.build(company, owner, cib)
