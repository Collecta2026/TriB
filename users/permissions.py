"""The authority matrix: which modules exist and which actions each one supports.

A permission code is "<module>.<action>", e.g. "vouchers.approve". Roles hold a list of codes.
"""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _

ACTIONS = [
    ("view", _("View")),
    ("create", _("Create")),
    ("edit", _("Edit")),
    ("approve", _("Approve")),
    ("post", _("Post")),
    ("void", _("Void")),
    ("export", _("Export")),
]

MODULES = [
    ("dashboard", _("Dashboard"), ["view"]),
    ("ledger", _("Chart of accounts & journals"), ["view", "create", "edit", "post", "void", "export"]),
    ("banking", _("Banks & cash"), ["view", "create", "edit"]),
    ("cheques", _("Cheques"), ["view", "create", "edit", "post", "void"]),
    ("vouchers", _("Vouchers"), ["view", "create", "edit", "approve", "post", "void", "export"]),
    ("reports", _("Reports"), ["view", "export"]),
    ("setup", _("Company setup"), ["view", "edit"]),
    ("users", _("Users & roles"), ["view", "create", "edit"]),
    ("audit", _("Audit log"), ["view"]),
]

ALL_CODES = [f"{m}.{a}" for m, _label, actions in MODULES for a in actions]


def matrix_rows(selected=()):
    """Rows for the matrix editor: one per module, one cell per action (None where not applicable)."""
    selected = set(selected)
    rows = []
    for module, label, actions in MODULES:
        cells = []
        for action, _alabel in ACTIONS:
            code = f"{module}.{action}"
            cells.append({"code": code, "checked": code in selected} if action in actions else None)
        rows.append({"module": module, "label": label, "cells": cells})
    return rows


def require_perm(code):
    """View decorator: signed in, belongs to a company, and holds the permission."""

    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(request, *args, **kwargs):
            if request.membership is None:
                return redirect("core:no_company")
            if not request.membership.has_perm(code):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapped

    return decorator
