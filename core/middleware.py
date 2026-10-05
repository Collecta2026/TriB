from users.models import Membership


class CompanyMiddleware:
    """Attach the signed-in user's current company and membership to every request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.company = None
        request.membership = None
        if request.user.is_authenticated:
            memberships = (
                Membership.objects.filter(user=request.user, is_active=True, company__is_active=True)
                .select_related("company", "company__base_currency")
                .order_by("created_at")
            )
            wanted = request.session.get("company_id")
            membership = memberships.filter(company_id=wanted).first() if wanted else None
            membership = membership or memberships.first()
            if membership:
                request.company = membership.company
                request.membership = membership
                request.session["company_id"] = membership.company_id
        return self.get_response(request)
