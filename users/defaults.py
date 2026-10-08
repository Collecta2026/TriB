"""Starter roles every new company gets. Admins can edit them or add their own."""
from decimal import Decimal

from .models import ApprovalLimit, Role
from .permissions import ALL_CODES

VIEW_ALL = [c for c in ALL_CODES if c.endswith(".view")]


def _codes(*modules_actions):
    out = []
    for item in modules_actions:
        module, actions = item.split(".", 1)
        out += [f"{module}.{a}" for a in actions.split(",")]
    return out


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
        "perms": VIEW_ALL + _codes("vouchers.approve,post,export", "ledger.post,export", "reports.export", "cheques.post",
                                   "purchases.approve,post,export", "sales.post,void,export", "banking.post",
                                   "assets.post,export", "inventory.export", "payroll.approve,post,export",
                                   "team.view"),
        "limits": {"receipt": "5000000", "payment": "1000000", "journal": "5000000"},
    },
    {
        "key": "accountant",
        "name_en": "Accountant", "name_ar": "محاسب",
        "perms": _codes("dashboard.view", "ledger.view,create,edit,post,export", "banking.view,create,edit,post",
                        "cheques.view,create,edit,post", "vouchers.view,create,edit,post,export", "reports.view,export",
                        "contacts.view,create,edit,export", "sales.view,create,edit,post,export",
                        "purchases.view,create,edit,post,export", "inventory.view,export", "assets.view,create,edit,post",
                        "projects.view,create,edit", "team.view", "payroll.view,create,edit"),
        "limits": {},
    },
    {
        "key": "cashier",
        "name_en": "Cashier", "name_ar": "أمين الخزينة",
        "perms": _codes("dashboard.view", "banking.view", "cheques.view,create", "vouchers.view,create,edit",
                        "contacts.view", "sales.view", "purchases.view"),
        "limits": {},
    },
    {
        "key": "sales",
        "name_en": "Sales officer", "name_ar": "مسؤول مبيعات",
        "perms": _codes("dashboard.view", "contacts.view,create,edit", "sales.view,create,edit,post",
                        "inventory.view", "projects.view"),
        "limits": {},
    },
    {
        "key": "purchasing",
        "name_en": "Purchasing officer", "name_ar": "مسؤول مشتريات",
        "perms": _codes("dashboard.view", "contacts.view,create,edit", "purchases.view,create,edit",
                        "inventory.view", "projects.view"),
        "limits": {},
    },
    {
        "key": "storekeeper",
        "name_en": "Storekeeper", "name_ar": "أمين المخزن",
        "perms": _codes("dashboard.view", "inventory.view,create,edit,post", "purchases.view", "sales.view",
                        "assets.view"),
        "limits": {},
    },
    {
        "key": "hr",
        "name_en": "HR officer", "name_ar": "مسؤول الموارد البشرية",
        "perms": _codes("dashboard.view", "team.view,create,edit", "payroll.view,create,edit,export"),
        "limits": {},
    },
    {
        "key": "md",
        "name_en": "Managing director", "name_ar": "العضو المنتدب",
        "perms": VIEW_ALL + _codes("payroll.authorise,export", "purchases.approve", "vouchers.approve", "reports.export"),
        "limits": {"receipt": "999999999999", "payment": "999999999999", "journal": "999999999999"},
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


RELEASE_2_MODULES = {"contacts", "sales", "purchases", "inventory", "assets", "projects", "team", "payroll"}
RELEASE_2_CODES = {"banking.post"}


def sync_system_roles(company):
    """Give the starter roles of an existing company the permissions for modules added in Release 2.

    Only codes for the new modules are added, so anything an admin removed from an older module stays removed.
    Missing starter roles are created.
    """
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
