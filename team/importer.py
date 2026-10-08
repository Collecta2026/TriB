"""Import employees from a monthly payroll workbook (the layout Scientific Gate uses).

Columns are found by their headings, so moving a column does not break the import. Recognised headings
(English, case-insensitive): Department, SN, Name, Title, Full Time, Bank / Instapay, Joining Date,
Net Basic Salary, Monthly Employee Medical Due, Monthly Employee Social Due, Allowance.
Row colours follow the sheet's legend: yellow = on hold, red = resigned.
"""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction

from payroll.models import PayrollSettings

from .models import Department, Employee

HEADINGS = {
    "department": ["department"],
    "code": ["sn", "code", "employee code"],
    "name": ["name"],
    "title": ["title", "job title"],
    "full_time": ["full time", "fulltime", "part /contractor", "part/contractor"],
    "channel": ["bank / instapay", "bank/instapay", "payment"],
    "joined": ["joining date", "joining\ndate", "hire date"],
    "basic": ["net basic salary", "net\nbasic \nsalary", "basic salary", "net basic"],
    "medical": ["monthly employee medical due", "medical"],
    "social": ["monthly employee social due", "social"],
    "allowance": ["allowance"],
}
HOLD_RGB, RESIGNED_RGB = "FFFFFF00", "FFFF0000"


def _norm(text):
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _money(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def _date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date()
        except (ValueError, TypeError):
            continue
    return None


def _fill(cell):
    f = cell.fill
    if not f or not f.fill_type:
        return None
    rgb = f.fgColor.rgb
    return rgb if isinstance(rgb, str) else None


def _header_map(row):
    out = {}
    for idx, cell in enumerate(row):
        label = _norm(cell.value)
        for key, names in HEADINGS.items():
            if key not in out and any(label == _norm(n) for n in names):
                out[key] = idx
    return out


def read_workbook(uploaded):
    """[{field: value}] for every employee row of the first worksheet."""
    import openpyxl

    ws = openpyxl.load_workbook(uploaded, data_only=True).worksheets[0]
    columns, people = None, []
    for row in ws.iter_rows():
        header = _header_map(row)
        if "name" in header and ("department" in header or "code" in header):
            columns = {**(columns or {}), **header} if columns else header
            continue
        if not columns:
            continue
        cell = lambda key: row[columns[key]] if key in columns and columns[key] < len(row) else None  # noqa: E731
        name = cell("name").value if cell("name") is not None else None
        code = cell("code").value if cell("code") is not None else None
        if not name or str(name).strip().lower() == "name" or code in (None, ""):
            continue
        colours = {_fill(c) for c in row[:12]}
        people.append({
            "department": (cell("department").value if cell("department") is not None else "") or "",
            "code": str(int(code)) if isinstance(code, (int, float)) else str(code).strip(),
            "name": str(name).strip(),
            "title": (cell("title").value if cell("title") is not None else "") or "",
            "full_time": _norm(cell("full_time").value if cell("full_time") is not None else ""),
            "channel": _norm(cell("channel").value if cell("channel") is not None else ""),
            "joined": _date(cell("joined").value) if cell("joined") is not None else None,
            "basic": _money(cell("basic").value) if cell("basic") is not None else None,
            "medical": _money(cell("medical").value) if cell("medical") is not None else None,
            "social": _money(cell("social").value) if cell("social") is not None else None,
            "allowance": _money(cell("allowance").value) if cell("allowance") is not None else None,
            "status": "left" if RESIGNED_RGB in colours else "hold" if HOLD_RGB in colours else "active",
        })
    return people


def _contract(flag):
    if flag.startswith("contract"):
        return "contractor"
    if flag in ("p", "part", "part time", "part-time"):
        return "part_time"
    return "indefinite"


def _channel(text):
    if "insta" in text:
        return "instapay"
    if "cash" in text:
        return "cash"
    return "bank"


@transaction.atomic
def import_people(company, people):
    """Create or update employees by code. Returns (created, updated)."""
    s = PayrollSettings.for_company(company)
    departments = {d.name_en.lower(): d for d in Department.objects.filter(company=company)}
    created = updated = 0
    for p in people:
        dept = None
        if p["department"]:
            key = str(p["department"]).strip().lower()
            dept = departments.get(key)
            if dept is None:
                dept = Department.objects.create(company=company, name_en=str(p["department"]).strip())
                departments[key] = dept
        social = p["social"] or Decimal("0")
        insurable = (social * 100 / s.si_employee_pct).quantize(Decimal("0.01")) if social and s.si_employee_pct else None
        values = {
            "name_en": p["name"], "job_title_en": str(p["title"]).strip(), "department": dept,
            "contract_type": _contract(p["full_time"]), "payment_method": _channel(p["channel"]),
            "hire_date": p["joined"], "basic_salary": p["basic"] or Decimal("0"),
            "allowances": p["allowance"] or Decimal("0"), "medical_employee_share": p["medical"],
            "insured": bool(social), "insurable_wage": insurable, "status": p["status"],
        }
        employee = Employee.objects.filter(company=company, code=p["code"]).first()
        if employee is None:
            Employee.objects.create(company=company, code=p["code"], **values)
            created += 1
        else:
            for k, v in values.items():
                setattr(employee, k, v)
            employee.save()
            updated += 1
    return created, updated
