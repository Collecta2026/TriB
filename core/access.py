"""Record-level access, on top of the authority matrix:

- Own records only: a role can be limited to the user's own customers, leads, opportunities and the sales documents
  for them. A user sees everything as soon as one of their roles is not limited.
- Warehouses: a user can be limited to some warehouses, like branches. Stock and documents for other warehouses
  are hidden and cannot be chosen.

`scope(qs)` applies both to any queryset. The signed-in user's membership is kept for the current request
(CompanyMiddleware), so forms restrict their drop-downs without extra arguments.
"""
from contextvars import ContextVar

from django.db.models import Q

_current = ContextVar("trib_membership", default=None)


def set_current(membership):
    return _current.set(membership)


def reset_current(token):
    _current.reset(token)


def current():
    return _current.get()


def own_only(membership):
    """True when every role the user holds is limited to their own records (owners never are)."""
    if membership is None or membership.is_owner:
        return False
    if not hasattr(membership, "_own_only"):
        roles = list(membership.roles.all())
        membership._own_only = bool(roles) and all(r.own_records_only for r in roles)
    return membership._own_only


def warehouse_ids(membership):
    """The warehouses this user may use, or None for all of them."""
    if membership is None or membership.is_owner:
        return None
    if not hasattr(membership, "_warehouse_ids"):
        membership._warehouse_ids = list(membership.warehouses.values_list("id", flat=True)) or None
    return membership._warehouse_ids


def _own_q(label, user):
    """Which rows of a model count as the user's own."""
    mine_customer = Q(customer__account_manager=user)
    rules = {
        "contacts.customer": Q(account_manager=user),
        "crm.lead": Q(owner=user),
        "crm.opportunity": Q(owner=user) | mine_customer,
        "crm.proposal": Q(created_by=user) | mine_customer,
        "crm.contract": Q(created_by=user) | mine_customer,
        "crm.appointment": Q(created_by=user) | Q(attendees=user) | mine_customer | Q(lead__owner=user),
        "crm.task": Q(assignee=user) | Q(created_by=user),
        "crm.conversation": Q(by=user) | mine_customer | Q(lead__owner=user),
        "crm.review": mine_customer,
    }
    return rules.get(label)


def _has_field(model, name):
    return any(f.name == name for f in model._meta.get_fields())


def scope(qs, membership=None):
    """Limit `qs` to what the user may see. Without a signed-in user (services, commands) nothing is limited."""
    m = membership if membership is not None else current()
    if m is None or m.is_owner:
        return qs
    model = qs.model
    label = model._meta.label_lower
    if own_only(m):
        q = _own_q(label, m.user)
        if q is None and _has_field(model, "customer") and model._meta.app_label in ("sales", "crm"):
            q = Q(customer__account_manager=m.user)
            if _has_field(model, "created_by"):
                q |= Q(created_by=m.user)
        if q is not None:
            qs = qs.filter(q).distinct()
    ids = warehouse_ids(m)
    if ids is not None:
        if label == "inventory.warehouse":
            qs = qs.filter(pk__in=ids)
        elif label == "inventory.stocktransfer":
            qs = qs.filter(Q(from_warehouse_id__in=ids) | Q(to_warehouse_id__in=ids))
        elif _has_field(model, "warehouse"):
            qs = qs.filter(Q(warehouse_id__in=ids) | Q(warehouse__isnull=True))
    return qs


def sees_costs(membership):
    """Cost prices, stock values and margins. Without a signed-in user (services, commands) costs are not hidden."""
    return membership is None or membership.has_perm("inventory.costs")


def can_see(obj, membership=None):
    """Whether one record is visible to the user (for detail pages and actions)."""
    return scope(type(obj)._default_manager.filter(pk=obj.pk), membership).exists()


def stock_warehouses(request):
    """Warehouses to total stock over: the user's own, or None for every warehouse."""
    return warehouse_ids(getattr(request, "membership", None))
