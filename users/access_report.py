"""Who can do what: every user's roles, branches, warehouses, record scope, approval limits and effective permissions,
plus each role's matrix. For the auditor and for signing off access (printable page and Excel)."""
import io

from django.utils.translation import gettext as _

from .models import LIMIT_TYPES, NO_LIMIT, ApprovalLimit, Membership
from .permissions import ACTIONS, MODULES

# One letter per action for the compact grid; the legend is printed with the report.
LETTERS = {"view": "V", "create": "C", "edit": "E", "delete": "D", "approve": "A", "authorise": "Au", "post": "P",
           "void": "Vo", "export": "X", "costs": "$"}


def _limit_text(amount):
    if amount is None:
        return "—"
    return _("No limit") if amount >= NO_LIMIT else f"{amount:,.0f}"


def build(company):
    members = (Membership.objects.filter(company=company).select_related("user")
               .prefetch_related("roles", "branches", "warehouses").order_by("-is_active", "user__full_name", "user__email"))
    roles = list(company.roles.prefetch_related("limits").order_by("name_en"))
    limits = {}
    for lim in ApprovalLimit.objects.filter(role__company=company):
        limits.setdefault(lim.role_id, {})[lim.doc_type] = lim.max_amount
    people = []
    for m in members:
        mine = list(m.roles.all())
        codes = set()
        for r in mine:
            codes.update(r.permissions or [])
        own = bool(mine) and all(r.own_records_only for r in mine) and not m.is_owner
        person_limits = []
        for doc_type, label in LIMIT_TYPES:
            if m.is_owner:
                person_limits.append((label, _("No limit")))
                continue
            amounts = [limits.get(r.id, {}).get(doc_type) for r in mine]
            amounts = [a for a in amounts if a is not None]
            person_limits.append((label, _limit_text(max(amounts)) if amounts else "—"))
        grid = []
        for module, label, actions in MODULES:
            allowed = [a for a in actions if m.is_owner or f"{module}.{a}" in codes]
            grid.append({"module": label, "letters": " ".join(LETTERS[a] for a in allowed)})
        people.append({
            "m": m, "name": str(m.user), "email": m.user.email, "active": m.is_active, "owner": m.is_owner,
            "roles": ", ".join(r.name for r in mine) or "—",
            "branches": ", ".join(b.code for b in m.branches.all()) or _("All"),
            "warehouses": ", ".join(w.code for w in m.warehouses.all()) or _("All"),
            "scope": _("Own records only") if own else _("All records"),
            "limits": person_limits, "grid": grid,
        })
    role_rows = []
    for r in roles:
        codes = set(r.permissions or [])
        role_limits = [(label, _limit_text(limits.get(r.id, {}).get(dt))) for dt, label in LIMIT_TYPES]
        role_rows.append({
            "role": r, "own": r.own_records_only, "limits": role_limits,
            "limits_set": [(label, v) for label, v in role_limits if v != "—"],
            "matrix": [{"module": label, "cells": [(a in actions, f"{module}.{a}" in codes) for a, _l in ACTIONS]}
                       for module, label, actions in MODULES],
        })
    return {"people": people, "roles": role_rows, "actions": ACTIONS, "modules": [label for _m, label, _a in MODULES],
            "legend": [(LETTERS[a], label) for a, label in ACTIONS], "limit_types": [label for _d, label in LIMIT_TYPES]}


def workbook(company, data):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    head = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor="0E6470")
    wb = Workbook()

    def sheet(ws, header, rows, widths):
        ws.append(header)
        for c in ws[1]:
            c.font, c.fill, c.alignment = head, fill, Alignment(wrap_text=True, vertical="top")
        for row in rows:
            ws.append(row)
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w
        ws.freeze_panes = "B2"

    ws = wb.active
    ws.title = _("People")[:31]
    sheet(ws, [_("Name"), _("Email"), _("Status"), _("Roles"), _("Branches"), _("Warehouses"), _("Records")]
          + [str(t) for t in data["limit_types"]],
          [[p["name"] + (f" ({_('Owner')})" if p["owner"] else ""), p["email"], _("Active") if p["active"] else _("Inactive"),
            p["roles"], p["branches"], p["warehouses"], str(p["scope"])] + [str(v) for _l, v in p["limits"]]
           for p in data["people"]],
          [26, 30, 10, 34, 14, 14, 18] + [16] * len(data["limit_types"]))
    ws = wb.create_sheet(_("Permissions")[:31])
    sheet(ws, [_("Name")] + [str(m) for m in data["modules"]],
          [[p["name"]] + [g["letters"] for g in p["grid"]] for p in data["people"]],
          [26] + [14] * len(data["modules"]))
    ws.append([])
    ws.append([_("Key")] + [f"{k} = {v}" for k, v in data["legend"]])
    ws = wb.create_sheet(_("Roles")[:31])
    sheet(ws, [_("Role"), _("Records")] + [str(t) for t in data["limit_types"]],
          [[r["role"].name, str(_("Own records only") if r["own"] else _("All records"))] + [str(v) for _l, v in r["limits"]]
           for r in data["roles"]], [26, 18] + [16] * len(data["limit_types"]))
    ws = wb.create_sheet(_("Role permissions")[:31])
    rows = []
    for r in data["roles"]:
        for row in r["matrix"]:
            ticks = [("✓" if on else "") if applies else "—" for applies, on in row["cells"]]
            rows.append([r["role"].name, str(row["module"])] + ticks)
    sheet(ws, [_("Role"), _("Module")] + [str(label) for _a, label in data["actions"]],
          rows, [24, 30] + [12] * len(data["actions"]))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
