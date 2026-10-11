"""Starter roles every new company gets. Admins can edit them or add their own."""
from decimal import Decimal

from .models import ApprovalLimit, Role
from .permissions import ALL_CODES

NO_LIMIT = "999999999999"
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
        "limits": {"receipt": NO_LIMIT, "payment": NO_LIMIT, "journal": NO_LIMIT, "purchase_order": NO_LIMIT,
                   "bill": NO_LIMIT},
    },
    {
        "key": "finance_manager",
        "name_en": "Finance manager", "name_ar": "المدير المالي",
        "perms": VIEW_ALL + _codes("vouchers.approve,post,export", "ledger.post,export", "reports.export", "cheques.post",
                                   "purchases.approve,post,export,delete", "sales.post,void,export,delete", "banking.post",
                                   "assets.post,export", "inventory.export,costs", "payroll.approve,post,export",
                                   "team.view"),
        "limits": {"receipt": "5000000", "payment": "1000000", "journal": "5000000", "purchase_order": "1000000",
                   "bill": "1000000"},
    },
    {
        "key": "accountant",
        "name_en": "Accountant", "name_ar": "محاسب",
        "perms": _codes("dashboard.view", "ledger.view,create,edit,post,export", "banking.view,create,edit,post",
                        "cheques.view,create,edit,post", "vouchers.view,create,edit,post,export", "reports.view,export",
                        "contacts.view,create,edit,export", "sales.view,create,edit,post,export,delete",
                        "purchases.view,create,edit,post,export,delete", "inventory.view,export,costs",
                        "assets.view,create,edit,post", "projects.view,create,edit", "team.view", "payroll.view,create,edit",
                        "crm.view"),
        "limits": {"bill": "500000"},
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
                        "inventory.view", "projects.view", "crm.view,create,edit"),
        "limits": {},
    },
    {
        "key": "purchasing",
        "name_en": "Purchasing officer", "name_ar": "مسؤول مشتريات",
        "perms": _codes("dashboard.view", "contacts.view,create,edit", "purchases.view,create,edit",
                        "inventory.view,costs", "projects.view"),
        "limits": {},
    },
    {
        "key": "storekeeper",
        "name_en": "Storekeeper", "name_ar": "أمين المخزن",
        "perms": _codes("dashboard.view", "inventory.view,create,edit,post,costs", "purchases.view", "sales.view",
                        "assets.view"),
        "limits": {},
    },
    {
        "key": "hr",
        "name_en": "HR officer", "name_ar": "مسؤول الموارد البشرية",
        "perms": _codes("dashboard.view", "team.view,create,edit", "payroll.view,create,edit,export,delete"),
        "limits": {},
    },
    {
        "key": "md",
        "name_en": "Managing director", "name_ar": "العضو المنتدب",
        "perms": VIEW_ALL + _codes("payroll.authorise,export", "purchases.approve", "vouchers.approve", "reports.export",
                                   "inventory.costs"),
        "limits": {"receipt": NO_LIMIT, "payment": NO_LIMIT, "journal": NO_LIMIT, "purchase_order": NO_LIMIT,
                   "bill": NO_LIMIT},
    },
    {
        "key": "auditor",
        "name_en": "Auditor (read only)", "name_ar": "مراجع (عرض فقط)",
        "perms": VIEW_ALL + ["reports.export", "ledger.export", "inventory.costs"],
        "limits": {},
    },
]

# Batch G: codes added to existing roles on deploy. Starter roles get exactly what DEFAULT_ROLES gives them; roles a
# company made itself keep working as before (whoever could create could delete; anyone could see costs; anyone who
# could approve or post purchases had no limit).
BATCH_G_CODES = {"sales.delete", "purchases.delete", "payroll.delete", "inventory.costs"}


def upgrade_roles_batch_g(company, Role=Role, ApprovalLimit=ApprovalLimit):
    specs = {s["name_en"]: s for s in DEFAULT_ROLES}
    for role in Role.objects.filter(company=company):
        perms = set(role.permissions or [])
        spec = specs.get(role.name_en) if role.is_system else None
        if spec is not None:
            add = {c for c in spec["perms"] if c in BATCH_G_CODES}
            limits = {k: v for k, v in spec["limits"].items() if k in ("purchase_order", "bill")}
        else:
            add = set()
            for module in ("sales", "purchases"):
                if f"{module}.create" in perms:
                    add.add(f"{module}.delete")
            if "payroll.edit" in perms:
                add.add("payroll.delete")
            if "inventory.view" in perms:
                add.add("inventory.costs")
            limits = {}
            if "purchases.approve" in perms:
                limits["purchase_order"] = NO_LIMIT
            if "purchases.post" in perms:
                limits["bill"] = NO_LIMIT
        if add - perms:
            role.permissions = sorted(perms | add)
            role.save(update_fields=["permissions"])
        for doc_type, amount in limits.items():
            ApprovalLimit.objects.get_or_create(role=role, doc_type=doc_type, defaults={"max_amount": Decimal(amount)})


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


# Modules added after a company was created; their codes are merged into the starter roles on deploy (crm migration).
RELEASE_2_MODULES = {"contacts", "sales", "purchases", "inventory", "assets", "projects", "team", "payroll", "crm"}
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
