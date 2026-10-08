"""Starter chart of accounts for an Egyptian trading company, in English and Arabic.

Rows: code, parent code, English name, Arabic name, type, subtype, is_group.
"""
from .models import Account

EGYPT_TRADING = [
    ("1", None, "Assets", "الأصول", "asset", "", True),
    ("11", "1", "Current assets", "الأصول المتداولة", "asset", "", True),
    ("1110", "11", "Cash on hand", "النقدية بالصندوق", "asset", "cash", True),
    ("1120", "11", "Banks", "البنوك", "asset", "bank", True),
    ("1130", "11", "Customers", "العملاء", "asset", "receivable", False),
    ("1140", "11", "Cheques in the safe (notes receivable)", "أوراق القبض (شيكات بالخزينة)", "asset", "notes_receivable", False),
    ("1145", "11", "Cheques under collection", "شيكات تحت التحصيل", "asset", "cheques_collection", False),
    ("1150", "11", "Inventory", "المخزون", "asset", "inventory", False),
    ("1160", "11", "Goods in transit", "بضاعة بالطريق", "asset", "goods_in_transit", False),
    ("1170", "11", "Employee custody & advances", "العهد والسلف", "asset", "custody", False),
    ("1180", "11", "VAT input", "ضريبة القيمة المضافة - مدخلات", "asset", "vat_input", False),
    ("1185", "11", "Withholding tax receivable", "ضرائب الخصم من المنبع - مدينة", "asset", "wht_receivable", False),
    ("1190", "11", "Prepaid expenses", "مصروفات مدفوعة مقدمًا", "asset", "", False),
    ("12", "1", "Non-current assets", "الأصول غير المتداولة", "asset", "", True),
    ("1210", "12", "Property, plant & equipment", "الأصول الثابتة", "asset", "", False),
    ("1290", "12", "Accumulated depreciation", "مجمع الإهلاك", "asset", "", False),
    ("2", None, "Liabilities", "الخصوم", "liability", "", True),
    ("21", "2", "Current liabilities", "الخصوم المتداولة", "liability", "", True),
    ("2110", "21", "Suppliers", "الموردون", "liability", "payable", False),
    ("2120", "21", "Cheques issued (notes payable)", "أوراق الدفع (شيكات صادرة)", "liability", "notes_payable", False),
    ("2130", "21", "VAT output", "ضريبة القيمة المضافة - مخرجات", "liability", "vat_output", False),
    ("2140", "21", "Withholding tax payable", "ضرائب الخصم والإضافة - دائنة", "liability", "wht_payable", False),
    ("2150", "21", "Accrued expenses", "مصروفات مستحقة", "liability", "", False),
    ("2160", "21", "Social insurance payable", "التأمينات الاجتماعية المستحقة", "liability", "", False),
    ("2170", "21", "Customer advances", "دفعات مقدمة من العملاء", "liability", "", False),
    ("22", "2", "Long-term liabilities", "الخصوم طويلة الأجل", "liability", "", True),
    ("2210", "22", "Long-term loans", "قروض طويلة الأجل", "liability", "", False),
    ("3", None, "Equity", "حقوق الملكية", "equity", "", True),
    ("3100", "3", "Paid-up capital", "رأس المال المدفوع", "equity", "", False),
    ("3200", "3", "Legal reserve", "الاحتياطي القانوني", "equity", "", False),
    ("3300", "3", "Retained earnings", "الأرباح المحتجزة", "equity", "retained_earnings", False),
    ("3400", "3", "Partners' current accounts", "جاري الشركاء", "equity", "", False),
    ("4", None, "Revenue", "الإيرادات", "income", "", True),
    ("4100", "4", "Sales revenue", "إيرادات المبيعات", "income", "", False),
    ("4150", "4", "Sales returns & discounts", "مردودات ومسموحات المبيعات", "income", "", False),
    ("4200", "4", "Service revenue", "إيرادات الخدمات", "income", "", False),
    ("4800", "4", "Exchange gains", "أرباح فروق العملة", "income", "fx_gain", False),
    ("4900", "4", "Other income", "إيرادات أخرى", "income", "", False),
    ("5", None, "Expenses", "المصروفات", "expense", "", True),
    ("5100", "5", "Cost of goods sold", "تكلفة البضاعة المباعة", "expense", "", False),
    ("5200", "5", "Salaries & wages", "الرواتب والأجور", "expense", "", False),
    ("5210", "5", "Social insurance (company share)", "حصة الشركة في التأمينات الاجتماعية", "expense", "", False),
    ("5300", "5", "Rent", "الإيجار", "expense", "", False),
    ("5310", "5", "Utilities", "المرافق", "expense", "", False),
    ("5400", "5", "Freight & customs clearing", "الشحن والتخليص الجمركي", "expense", "", False),
    ("5500", "5", "Marketing & exhibitions", "التسويق والمعارض", "expense", "", False),
    ("5600", "5", "Vehicles & travel", "السيارات والانتقالات", "expense", "", False),
    ("5700", "5", "Bank charges", "المصروفات البنكية", "expense", "", False),
    ("5710", "5", "Exchange losses", "خسائر فروق العملة", "expense", "fx_loss", False),
    ("5800", "5", "Depreciation", "الإهلاك", "expense", "", False),
    ("5900", "5", "General & administrative", "مصروفات عمومية وإدارية", "expense", "", False),
]


# Added in Release 2 (inventory, purchasing, assets, payroll). Also applied to companies created earlier.
RELEASE_2_ACCOUNTS = [
    ("2115", "21", "Goods received not invoiced", "بضاعة مستلمة لم تصل فواتيرها", "liability", "grni", False),
    ("2155", "21", "Salaries payable", "رواتب مستحقة", "liability", "salaries_payable", False),
    ("2165", "21", "Salary income tax payable", "ضريبة كسب العمل المستحقة", "liability", "payroll_tax", False),
    ("2168", "21", "Employee deductions payable (medical & other)", "استقطاعات العاملين المستحقة (طبي وأخرى)",
     "liability", "employee_deductions", False),
    ("5220", "5", "Overtime", "الأجر الإضافي", "expense", "overtime", False),
    ("3900", "3", "Opening balance equity", "حقوق ملكية افتتاحية", "equity", "opening_equity", False),
    ("4850", "4", "Gain on disposal of assets", "أرباح بيع أصول", "income", "disposal_gain", False),
    ("5110", "5", "Stock adjustments & write-offs", "تسويات وإعدام المخزون", "expense", "stock_adjustment", False),
    ("5120", "5", "Purchase price variance", "فروق أسعار الشراء", "expense", "price_variance", False),
    ("5850", "5", "Loss on disposal of assets", "خسائر بيع أصول", "expense", "disposal_loss", False),
]
# Existing accounts that gain a system role in Release 2.
RELEASE_2_ROLES = {"4100": "sales", "5100": "cogs", "1210": "fixed_assets", "1290": "accum_depreciation",
                   "5800": "depreciation", "2160": "social_insurance", "5200": "salaries", "5210": "employer_si"}

DEFAULT_TAX_RATES = [
    ("VAT 14%", "ضريبة القيمة المضافة 14%", "14", "standard", True),
    ("Zero rated 0%", "خاضع بنسبة صفر", "0", "zero", False),
    ("Exempt", "معفى", "0", "exempt", False),
    ("Out of scope", "خارج نطاق الضريبة", "0", "out_of_scope", False),
]


def install_chart(company, rows=EGYPT_TRADING):
    created = {}
    for code, parent, en, ar, typ, subtype, is_group in rows:
        created[code] = Account.objects.create(
            company=company, code=code, parent=created.get(parent), name_en=en, name_ar=ar,
            type=typ, subtype=subtype, is_group=is_group, is_system=True,
        )
    ensure_release_2(company)
    return created


def ensure_release_2(company, Account=Account, TaxRate=None):
    """Add the Release 2 accounts, roles and VAT rates to a company if they are missing. Safe to repeat."""
    if TaxRate is None:
        from .models import TaxRate
    by_code = {a.code: a for a in Account.objects.filter(company=company)}
    for code, parent, en, ar, typ, subtype, is_group in RELEASE_2_ACCOUNTS:
        if code not in by_code and parent in by_code:
            by_code[code] = Account.objects.create(
                company=company, code=code, parent=by_code[parent], name_en=en, name_ar=ar, type=typ,
                subtype=subtype, is_group=is_group, is_system=True,
            )
    for code, subtype in RELEASE_2_ROLES.items():
        account = by_code.get(code)
        if account is not None and not account.subtype:
            account.subtype = subtype
            account.save(update_fields=["subtype"])
    if not TaxRate.objects.filter(company=company).exists():
        for en, ar, rate, kind, default in DEFAULT_TAX_RATES:
            TaxRate.objects.create(company=company, name_en=en, name_ar=ar, rate=rate, kind=kind, is_default=default)
