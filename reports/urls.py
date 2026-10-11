from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("", views.index, name="index"),
    path("favourite/", views.favourite, name="favourite"),
    path("export/", views.export, name="export"),
    path("trial-balance/", views.trial_balance, name="trial_balance"),
    path("statement/", views.statement, name="statement"),
    path("profit-and-loss/", views.profit_loss, name="profit_loss"),
    path("profit-and-loss/comparison/", views.pl_compare, name="pl_compare"),
    path("profit-and-loss/by-month/", views.pl_month, name="pl_month"),
    path("profit-and-loss/by-customer/", views.pl_customer, name="pl_customer"),
    path("profit-and-loss/detail/", views.pl_detail, name="pl_detail"),
    path("balance-sheet/", views.balance_sheet, name="balance_sheet"),
    path("balance-sheet/comparison/", views.bs_compare, name="bs_compare"),
    path("cash-flows/", views.cash_flows, name="cash_flows"),
    path("cash-flow-overview/", views.cash_overview, name="cash_overview"),
    path("cash-flow-forecast/", views.cash_forecast, name="cash_forecast"),
    path("ar-ageing/", views.ar_aging, name="ar_aging"),
    path("ap-ageing/", views.ap_aging, name="ap_aging"),
    path("customer-balances/", views.customer_summary, name="customer_summary"),
    path("customer-balances/detail/", views.customer_detail, name="customer_detail"),
    path("supplier-balances/", views.supplier_summary, name="supplier_summary"),
    path("supplier-balances/detail/", views.supplier_detail, name="supplier_detail"),
    path("invoice-list/", views.invoice_list, name="invoice_list"),
    path("bill-list/", views.bill_list, name="bill_list"),
    path("sales-by-customer/", views.sales_customer, name="sales_customer"),
    path("expenses-by-supplier/", views.expenses_supplier, name="expenses_supplier"),
    path("vat-return/", views.vat_return, name="vat_return"),
    path("sales-by-product/", views.sales_by_item, name="sales_by_item"),
    path("account-list/", views.account_list, name="account_list"),
    path("general-ledger/", views.general_ledger, name="general_ledger"),
    path("journal/", views.journal, name="journal"),
    path("recent-transactions/", views.recent, name="recent"),
    path("inventory-valuation-detail/", views.stock_detail, name="stock_detail"),
    path("fixed-asset-register/", views.asset_register, name="asset_register"),
    path("payroll-summary/", views.payroll_summary, name="payroll_summary"),
]
