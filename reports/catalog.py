"""The Reports page, laid out like QuickBooks' standard reports: sections of reports, each with a star (favourite)
and a ⋮ menu. Each report: (key, label, url name, permission, short description)."""
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

R = "reports.view"

SECTIONS = [
    ("overview", _("Business overview"), [
        ("profit_loss", _("Profit and loss"), "reports:profit_loss", R, _("Income and expenses for a period.")),
        ("pl_compare", _("Profit and loss comparison"), "reports:pl_compare", R,
         _("This period next to the previous period or last year.")),
        ("pl_month", _("Profit and loss by month"), "reports:pl_month", R, _("Income and expenses month by month.")),
        ("pl_customer", _("Profit and loss by customer"), "reports:pl_customer", R,
         _("Sales, cost of sales and gross profit for each customer.")),
        ("pl_detail", _("Profit and loss detail"), "reports:pl_detail", R,
         _("Every posting behind the profit and loss figures.")),
        ("balance_sheet", _("Balance sheet"), "reports:balance_sheet", R, _("Assets, liabilities and equity on a date.")),
        ("bs_compare", _("Balance sheet comparison"), "reports:bs_compare", R,
         _("The balance sheet on two dates, side by side.")),
        ("cash_flows", _("Statement of cash flows"), "reports:cash_flows", R,
         _("Where cash came from and went: operating, investing and financing.")),
        ("projects_pl", _("Project profitability"), "projects:list", "projects.view",
         _("Income, costs and profit for each project.")),
    ]),
    ("receivables", _("Who owes you"), [
        ("ar_aging", _("Accounts receivable ageing"), "reports:ar_aging", R, _("What customers owe, by how late it is.")),
        ("customer_summary", _("Customer balance summary"), "reports:customer_summary", R,
         _("What each customer owes today.")),
        ("customer_detail", _("Customer balance detail"), "reports:customer_detail", R,
         _("Every open invoice, credit and payment by customer.")),
        ("invoice_list", _("Invoice list"), "reports:invoice_list", R, _("Invoices in a period with what is still open.")),
        ("statements", _("Customer statements"), "sales:statements", "sales.view",
         _("Statements of account to send to customers.")),
        ("confirmations", _("Balance confirmations"), "sales:confirmations", "sales.view",
         _("Letters asking customers to confirm their balance.")),
    ]),
    ("sales", _("Sales and customers"), [
        ("sales_customer", _("Sales by customer"), "reports:sales_customer", R, _("Net sales and VAT for each customer.")),
        ("sales_by_item", _("Sales by product"), "reports:sales_by_item", R,
         _("Quantities, sales and margin by category and product.")),
        ("customer_contacts", _("Customer contact list"), "contacts:customers", "contacts.view",
         _("Names, phones and emails of your customers.")),
        ("open_orders", _("Open sales orders"), "sales:orders", "sales.view", _("Orders not yet fully delivered.")),
    ]),
    ("payables", _("What you owe"), [
        ("ap_aging", _("Accounts payable ageing"), "reports:ap_aging", R, _("What you owe suppliers, by how late it is.")),
        ("supplier_summary", _("Supplier balance summary"), "reports:supplier_summary", R,
         _("What you owe each supplier today.")),
        ("supplier_detail", _("Supplier balance detail"), "reports:supplier_detail", R,
         _("Every open bill, credit and payment by supplier.")),
        ("bill_list", _("Bill list"), "reports:bill_list", R, _("Bills in a period with what is still open.")),
        ("supplier_statements", _("Supplier statements"), "purchases:statements", "purchases.view",
         _("Your account with each supplier.")),
    ]),
    ("expenses", _("Expenses and suppliers"), [
        ("expenses_supplier", _("Expenses by supplier"), "reports:expenses_supplier", R,
         _("Bills less supplier credits, for each supplier.")),
        ("not_received", _("Purchases not yet received"), "purchases:not_received", "purchases.view",
         _("Ordered goods still to arrive.")),
        ("supplier_contacts", _("Supplier contact list"), "contacts:suppliers", "contacts.view",
         _("Names, phones and emails of your suppliers.")),
    ]),
    ("vat", _("VAT"), [
        ("vat_return", _("VAT return"), "reports:vat_return", R,
         _("Output and input VAT for the month, checked against the ledger.")),
    ]),
    ("payroll", _("Employees and payroll"), [
        ("payroll_summary", _("Payroll summary by employee"), "reports:payroll_summary", "payroll.view",
         _("Gross pay, deductions and net pay for each employee.")),
        ("payroll_runs", _("Payroll runs and deductions"), "payroll:runs", "payroll.view",
         _("Each month's run with its deductions workbook.")),
        ("leave_provision", _("Leave provision"), "payroll:leave_provision", "payroll.view",
         _("Leave owed to employees, valued at their pay.")),
        ("employees", _("Employee list"), "team:employees", "team.view", _("Everyone on the team.")),
    ]),
    ("inventory", _("Inventory"), [
        ("stock_valuation", _("Stock valuation summary"), "inventory:stock", "inventory.costs",
         _("Stock on hand at FIFO cost, by warehouse.")),
        ("stock_detail", _("Inventory valuation detail"), "reports:stock_detail", "inventory.costs",
         _("Each FIFO cost layer: batch, expiry, quantity and value.")),
        ("expiry", _("Batches & expiry"), "inventory:expiry", "inventory.view", _("Consumables by expiry date.")),
    ]),
    ("assets", _("Fixed assets"), [
        ("asset_register", _("Fixed asset register"), "reports:asset_register", "assets.view",
         _("Cost, accumulated depreciation and book value of every asset.")),
    ]),
    ("banking", _("Banking and cheques"), [
        ("cheque_reconciliation", _("Cheque reconciliation"), "banking:cheque_reconciliation", "cheques.view",
         _("Cleared and outstanding cheques against the bank statement.")),
        ("returned_cheques", _("Returned cheques"), "banking:bounced", "cheques.view",
         _("Cheques the bank sent back and what happened to them.")),
        ("deposits", _("Bank deposits"), "banking:deposits", "banking.view", _("Deposit slips paid into the bank.")),
    ]),
    ("accountant", _("For my accountant"), [
        ("account_list", _("Account list"), "reports:account_list", R, _("The chart of accounts with balances.")),
        ("trial_balance", _("Trial balance"), "reports:trial_balance", R,
         _("Opening, movement and closing balance of every account.")),
        ("general_ledger", _("General ledger"), "reports:general_ledger", R,
         _("Every posting by account, with running balances.")),
        ("journal", _("Journal"), "reports:journal", R, _("Journal entries with their debit and credit lines.")),
        ("statement", _("Account statement"), "reports:statement", R,
         _("Every posting to one account, with a running balance.")),
        ("recent", _("Recent transactions"), "reports:recent", R, _("Everything posted in the last 30 days.")),
        ("audit", _("Audit log"), "core:audit", "audit.view", _("Who did what, and when.")),
        ("access", _("Who can do what"), "users:access_report", "users.view",
         _("Every user's roles, warehouses, approval limits and permissions, for review and sign-off.")),
    ]),
]

KEYS = {key for _s, _t, reports in SECTIONS for key, *_rest in reports}


def visible_sections(membership, favourites=()):
    """Sections with only the reports this person may open; favourites are listed first in their own section."""
    out, by_key = [], {}
    for skey, title, reports in SECTIONS:
        items = []
        for key, label, url_name, perm, desc in reports:
            if membership and membership.has_perm(perm):
                item = {"key": key, "label": label, "url": reverse(url_name), "desc": desc, "fav": key in favourites}
                items.append(item)
                by_key[key] = item
        if items:
            out.append({"key": skey, "title": title, "items": items})
    favs = [by_key[k] for k in favourites if k in by_key]
    return out, favs
