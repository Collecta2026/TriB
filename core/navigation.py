"""The app menu, laid out like QuickBooks: All apps → app → pages. Pinned apps sit on the rail.

Each page: (label, url name, permission code). A url name of None means "coming soon".
"""
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

APPS = [
    {"key": "accounting", "label": _("Accounting"), "icon": "book", "items": [
        (_("Bank transactions"), "banking:transactions", "banking.view"),
        (_("Reconcile"), "banking:reconcile", "banking.post"),
        (_("Rules"), "banking:rules", "banking.edit"),
        (_("Receipts"), "core:receipts", "vouchers.create"),
        (_("Chart of accounts"), "ledger:accounts", "ledger.view"),
        (_("Journal entries"), "ledger:journals", "ledger.view"),
        (_("Vouchers"), "vouchers:list", "vouchers.view"),
        (_("Recurring transactions"), "core:recurring", "vouchers.create"),
        (_("Cost centres"), "ledger:cost_centers", "ledger.view"),
    ]},
    {"key": "expenses", "label": _("Expenses & Bills"), "icon": "wallet", "items": [
        (_("Expense transactions"), "purchases:expenses", "purchases.view"),
        (_("Bills"), "purchases:bills", "purchases.view"),
        (_("Pay bills"), "purchases:payments", "purchases.view"),
        (_("Purchase orders"), "purchases:orders", "purchases.view"),
        (_("Suppliers"), "contacts:suppliers", "contacts.view"),
        (_("Supplier statements"), "purchases:statements", "purchases.view"),
    ]},
    {"key": "sales", "label": _("Sales & Get Paid"), "icon": "sales", "items": [
        (_("Invoices"), "sales:invoices", "sales.view"),
        (_("Receive payments"), "sales:payments", "sales.view"),
        (_("Sales orders"), "sales:orders", "sales.view"),
        (_("Quotations"), "sales:quotes", "sales.view"),
        (_("Products & services"), "inventory:items", "inventory.view"),
        (_("Customers"), "contacts:customers", "contacts.view"),
    ]},
    {"key": "customers", "label": _("Customer Hub"), "icon": "hub", "items": [
        (_("Customers"), "contacts:customers", "contacts.view"),
        (_("Quotations"), "sales:quotes", "sales.view"),
        (_("Customer statements"), "sales:statements", "sales.view"),
        (_("Balance confirmations"), "sales:confirmations", "sales.view"),
        (_("Leads"), None, "contacts.view"),
    ]},
    {"key": "payroll", "label": _("Payroll"), "icon": "payroll", "items": [
        (_("Payroll runs"), "payroll:runs", "payroll.view"),
        (_("Loans & advances"), "team:loans", "payroll.view"),
        (_("Leave provision"), "payroll:leave_provision", "payroll.view"),
        (_("Payroll settings"), "payroll:settings", "payroll.edit"),
    ]},
    {"key": "team", "label": _("Team"), "icon": "people", "items": [
        (_("Employees"), "team:employees", "team.view"),
        (_("Import from payroll sheet"), "team:import", "team.create"),
        (_("Departments"), "team:departments", "team.view"),
        (_("Attendance"), "team:attendance", "team.view"),
        (_("Leave"), "team:leave", "team.view"),
        (_("Medical plans"), "team:benefits", "team.view"),
    ]},
    {"key": "projects", "label": _("Projects"), "icon": "projects", "items": [
        (_("Projects"), "projects:list", "projects.view"),
    ]},
    {"key": "inventory", "label": _("Inventory"), "icon": "box", "items": [
        (_("Overview"), "inventory:overview", "inventory.view"),
        (_("Inventory"), "inventory:stock", "inventory.view"),
        (_("Batches & expiry"), "inventory:expiry", "inventory.view"),
        (_("Purchase orders"), "purchases:orders", "purchases.view"),
        (_("Item receipts"), "purchases:receipts", "purchases.view"),
        (_("Sales orders"), "sales:orders", "sales.view"),
        (_("Stock transfers"), "inventory:transfers", "inventory.view"),
        (_("Stock adjustments"), "inventory:adjustments", "inventory.view"),
        (_("Stock take"), "inventory:counts", "inventory.view"),
        (_("Warehouses"), "inventory:warehouses", "inventory.view"),
        (_("Barcode labels"), "inventory:labels", "inventory.view"),
    ]},
    {"key": "assets", "label": _("Fixed assets"), "icon": "asset", "items": [
        (_("Asset register"), "assets:list", "assets.view"),
        (_("Asset categories"), "assets:categories", "assets.view"),
        (_("Depreciation"), "assets:depreciation", "assets.post"),
        (_("Asset count"), "assets:counts", "assets.view"),
        (_("Asset labels"), "assets:labels", "assets.view"),
    ]},
    {"key": "banking", "label": _("Banking & cheques"), "icon": "bank", "items": [
        (_("Bank accounts"), "banking:accounts", "banking.view"),
        (_("Cheques"), "banking:cheques", "cheques.view"),
        (_("Returned cheques"), "banking:bounced", "cheques.view"),
        (_("Cheque reconciliation"), "banking:cheque_reconciliation", "cheques.view"),
        (_("Bank transactions"), "banking:transactions", "banking.view"),
        (_("Reconcile"), "banking:reconcile", "banking.post"),
        (_("Banks"), "banking:banks", "banking.view"),
    ]},
    {"key": "vat", "label": _("VAT"), "icon": "percent", "items": [
        (_("VAT return"), "reports:vat_return", "reports.view"),
        (_("VAT rates"), "ledger:tax_rates", "setup.view"),
    ]},
    {"key": "approvals", "label": _("Approvals"), "icon": "shield", "items": [
        (_("Waiting for me"), "approvals:inbox", "vouchers.approve"),
        (_("Approval rules"), "approvals:rules", "setup.view"),
    ]},
    {"key": "capital", "label": _("Capital"), "icon": "capital", "items": [
        (_("Loans & financing"), None, "ledger.view"),
    ]},
    {"key": "marketing", "label": _("Marketing"), "icon": "megaphone", "items": [
        (_("Email campaigns"), None, "contacts.view"),
    ]},
]

APP_KEYS = [a["key"] for a in APPS]
DEFAULT_PINNED = ["accounting", "expenses", "sales"]

# What a new user sees under Bookmarks, like QuickBooks.
DEFAULT_BOOKMARKS = [
    (_("VAT"), "reports:vat_return"),
    (_("Bank transactions"), "banking:transactions"),
    (_("Invoices"), "sales:invoices"),
    (_("Bills"), "purchases:bills"),
    (_("Products & services"), "inventory:items"),
    (_("Rules"), "banking:rules"),
    (_("Receipts"), "core:receipts"),
    (_("Expense transactions"), "purchases:expenses"),
    (_("Chart of accounts"), "ledger:accounts"),
]


PERMS = {url_name: perm for app in APPS for _label, url_name, perm in app["items"] if url_name}


def visible_apps(membership, path=""):
    """Apps and pages this person may open. Pages they can't open are left out; apps with nothing to open
    disappear. The app holding the current page is marked active."""
    apps = []
    for app in APPS:
        items, active = [], False
        for label, url_name, perm in app["items"]:
            if url_name is None:
                items.append({"label": label, "url": None})
            elif membership and membership.has_perm(perm):
                url = reverse(url_name)
                items.append({"label": label, "url": url})
                active = active or (url != "/" and path.startswith(url))
        first = next((i["url"] for i in items if i["url"]), None)
        if first:
            apps.append({"key": app["key"], "label": app["label"], "icon": app["icon"], "items": items, "url": first,
                         "active": active})
    return apps


def seed_bookmarks(user, company, membership):
    """Give a new user QuickBooks' starter bookmarks (only pages they may open)."""
    from core.models import Bookmark

    rows = []
    for position, (title, url_name) in enumerate(DEFAULT_BOOKMARKS):
        perm = PERMS.get(url_name)
        if perm and membership.has_perm(perm):
            rows.append(Bookmark(user=user, company=company, title=str(title), url=reverse(url_name), position=position))
    Bookmark.objects.bulk_create(rows)


def menu_for(user, company, membership, path=""):
    """Everything the rail needs: all apps, pinned apps in the user's order, and bookmarks."""
    from core.models import Bookmark, UserPreference

    pref = UserPreference.for_user(user, company)
    if not pref.bookmarks_seeded:
        seed_bookmarks(user, company, membership)
        pref.bookmarks_seeded = True
        pref.save(update_fields=["bookmarks_seeded"])
    apps = visible_apps(membership, path)
    by_key = {a["key"]: a for a in apps}
    pinned = [by_key[k] for k in (pref.pinned_apps or []) if k in by_key]
    return {"apps": apps, "pinned": pinned, "pinned_keys": [a["key"] for a in pinned],
            "bookmarks": list(Bookmark.objects.filter(user=user, company=company)[:30])}
