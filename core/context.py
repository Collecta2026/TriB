from django.conf import settings


class _Module:
    def __init__(self, membership, module):
        self.membership, self.module = membership, module

    def __getitem__(self, action):
        return bool(self.membership and self.membership.has_perm(f"{self.module}.{action}"))


class Can:
    """Template helper: {% if can.vouchers.create %} (resolved through item lookup)."""

    def __init__(self, membership):
        self.membership = membership

    def __getitem__(self, module):
        return _Module(self.membership, module)


def trib(request):
    membership = getattr(request, "membership", None)
    ctx = {
        "product": settings.TRIB_PRODUCT,
        "company": getattr(request, "company", None),
        "membership": membership,
        "can": Can(membership),
        "pending_approvals": 0,
        "my_companies": [],
    }
    if membership is not None:
        from approvals.services import pending_for

        ctx["pending_approvals"] = len(pending_for(request.user, request.company))
        ctx["my_companies"] = [m.company for m in request.user.memberships.filter(is_active=True).select_related("company")]
    return ctx
