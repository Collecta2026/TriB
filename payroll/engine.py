"""
Egyptian statutory payroll engine, taken from the "Time" HR & payroll system (payroll.py).

The calculations are Time's, unchanged. TriB adds two switches per employee: `insured` (contractors and
others outside social insurance) and `taxable` (people outside salary tax).

All rates and thresholds come from PayrollSettings so an administrator keeps the product compliant
without a code change (the law revises the insurance ceilings every January). Defaults for 2026:

  Social Insurance & Pensions Law No. 148 of 2019
    - Employee 11.00%, employer 18.75%, emergency fund 1.00% (employer) of the insurable wage
    - Insurable wage floor EGP 2,700 / month, ceiling EGP 16,700 / month (2026); both rise 15% each January
  Income Tax Law No. 91 of 2005 (as amended by Law No. 7 of 2024)
    - Seven progressive bands 0% .. 27.5%, EGP 20,000 annual exemption, employee SI deductible,
      lower bands withdrawn for higher incomes (bracket integration)
  Labour Law No. 14 of 2025
    - 8 hours/day or 48 hours/week; overtime 35% day / 70% night or rest-day
"""
from decimal import ROUND_HALF_UP, Decimal

TWOPLACES = Decimal("0.01")


def _d(x):
    return Decimal(str(x or 0))


def _round(x):
    return _d(x).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def insurable_wage(total_monthly_wage, floor, ceiling):
    w = _d(total_monthly_wage)
    lo, hi = _d(floor), _d(ceiling)
    if w < lo:
        w = lo
    if w > hi:
        w = hi
    return _round(w)


def social_insurance(insurable, s):
    base = _d(insurable)
    emp = _round(base * _d(s.si_employee_pct) / 100)
    er = _round(base * _d(s.si_employer_pct) / 100)
    fund = _round(base * _d(s.emergency_fund_pct) / 100)
    return {"insurable_wage": _round(base), "employee": emp, "employer": er, "emergency_fund": fund,
            "employer_total": _round(er + fund)}


def _bands_for_total(total):
    t = _d(total)
    if t <= 600000:
        return [(40000, 0), (55000, 10), (70000, 15), (200000, 20), (400000, 22.5), (None, 25)]
    if t <= 700000:
        return [(55000, 10), (70000, 15), (200000, 20), (400000, 22.5), (None, 25)]
    if t <= 800000:
        return [(70000, 15), (200000, 20), (400000, 22.5), (None, 25)]
    if t <= 900000:
        return [(200000, 20), (400000, 22.5), (None, 25)]
    if t <= 1200000:
        return [(400000, 22.5), (None, 25)]
    return [(1200000, 25), (None, 27.5)]


def annual_income_tax(taxable_annual):
    taxable = _d(taxable_annual)
    if taxable <= 0:
        return Decimal("0.00")
    tax, lower = Decimal("0"), Decimal("0")
    for upper, rate in _bands_for_total(taxable):
        cap = taxable if upper is None else min(taxable, _d(upper))
        if cap > lower:
            tax += (cap - lower) * _d(rate) / 100
        lower = _d(upper) if upper is not None else taxable
        if upper is not None and taxable <= _d(upper):
            break
    return _round(tax)


def monthly_income_tax(monthly_taxable_gross, monthly_employee_si, s):
    annual_gross = _d(monthly_taxable_gross) * 12
    annual_si = _d(monthly_employee_si) * 12
    taxable = annual_gross - annual_si - _d(s.tax_annual_exemption)
    if taxable < 0:
        taxable = Decimal("0")
    return _round(annual_income_tax(taxable) / 12)


def hourly_rate(monthly_salary, s):
    daily = _d(monthly_salary) / _d(s.days_per_month or 30)
    return daily / _d(s.standard_daily_hours or 8)


def overtime_pay(monthly_salary, ot_day_hours, ot_night_hours, s):
    hr = hourly_rate(monthly_salary, s)
    day = hr * _d(ot_day_hours) * (1 + _d(s.overtime_day_pct) / 100)
    night = hr * _d(ot_night_hours) * (1 + _d(s.overtime_night_pct) / 100)
    return _round(day + night)


def absence_deduction(monthly_salary, hours_short, s):
    return _round(hourly_rate(monthly_salary, s) * _d(hours_short))


def compute_payslip(*, basic, allowances, ot_day_hours, ot_night_hours, hours_short, loan_deduction,
                    other_deductions, insurable_override, s, insured=True, taxable=True):
    basic, allowances = _d(basic), _d(allowances)
    ot = overtime_pay(basic + allowances, ot_day_hours, ot_night_hours, s)
    gross = _round(basic + allowances + ot)

    if insured:
        iw = _d(insurable_override) if insurable_override else insurable_wage(basic + allowances, s.si_floor, s.si_ceiling)
        si = social_insurance(iw, s)
    else:
        si = {"insurable_wage": Decimal("0.00"), "employee": Decimal("0.00"), "employer": Decimal("0.00"),
              "emergency_fund": Decimal("0.00"), "employer_total": Decimal("0.00")}

    tax = monthly_income_tax(gross, si["employee"], s) if taxable else Decimal("0.00")
    absence = absence_deduction(basic + allowances, hours_short, s)
    loan = _round(loan_deduction)
    other = _round(other_deductions)
    total_deductions = _round(si["employee"] + tax + absence + loan + other)
    net = _round(gross - total_deductions)
    return {
        "basic": _round(basic), "allowances": _round(allowances), "overtime": ot, "gross": gross,
        "insurable_wage": si["insurable_wage"], "si_employee": si["employee"], "si_employer": si["employer"],
        "emergency_fund": si["emergency_fund"], "employer_cost": _round(gross + si["employer_total"]),
        "income_tax": tax, "absence_deduction": absence, "loan_deduction": loan, "other_deductions": other,
        "total_deductions": total_deductions, "net_pay": net,
    }
