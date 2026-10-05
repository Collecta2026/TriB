"""Starter roles every new company gets. Admins can edit them or add their own."""
from decimal import Decimal

from .models import ApprovalLimit, Role
from .permissions import ALL_CODES

VIEW_ALL = [c for c in ALL_CODES if c.endswith(".view")]

DEFAULT_ROLES = [
    {
        "key": "admin",
        "name_en": "Administrator", "name_ar": "مدير النظام",
        "perms": ALL_CODES,
        "limits": {"receipt": "999999999999", "payment": "999999999999", "journal": "999999999999"},
    },
    {
        "key": "finance_manager",
        "name_en": "Finance manager", "name_ar": "المدير المالي",
        "perms": VIEW_ALL + ["vouchers.approve", "vouchers.post", "vouchers.export", "ledger.post", "ledger.export",
                             "reports.export", "cheques.post"],
        "limits": {"receipt": "5000000", "payment": "1000000", "journal": "5000000"},
    },
    {
        "key": "accountant",
        "name_en": "Accountant", "name_ar": "محاسب",
        "perms": ["dashboard.view", "ledger.view", "ledger.create", "ledger.edit", "ledger.post", "ledger.export",
                  "banking.view", "cheques.view", "cheques.create", "cheques.edit", "cheques.post",
                  "vouchers.view", "vouchers.create", "vouchers.edit", "vouchers.post", "vouchers.export",
                  "reports.view", "reports.export"],
        "limits": {},
    },
    {
        "key": "cashier",
        "name_en": "Cashier", "name_ar": "أمين الخزينة",
        "perms": ["dashboard.view", "banking.view", "cheques.view", "cheques.create",
                  "vouchers.view", "vouchers.create", "vouchers.edit"],
        "limits": {},
    },
    {
        "key": "auditor",
        "name_en": "Auditor (read only)", "name_ar": "مراجع (عرض فقط)",
        "perms": VIEW_ALL + ["reports.export", "ledger.export"],
        "limits": {},
    },
]


def install_default_roles(company):
    roles = {}
    for spec in DEFAULT_ROLES:
        role = Role.objects.create(
            company=company, name_en=spec["name_en"], name_ar=spec["name_ar"],
            permissions=list(spec["perms"]), is_system=True,
        )
        for doc_type, amount in spec["limits"].items():
            ApprovalLimit.objects.create(role=role, doc_type=doc_type, max_amount=Decimal(amount))
        roles[spec["key"]] = role
    return roles
