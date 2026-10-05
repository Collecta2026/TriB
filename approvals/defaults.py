from decimal import Decimal

from .models import ApprovalRule, ApprovalStep


def install_default_rules(company, roles):
    """Payment vouchers: finance manager; from 250,000 also the administrator. Journal vouchers: finance manager."""
    fm, admin = roles["finance_manager"], roles["admin"]
    specs = [
        ("payment", Decimal("0"), [fm]),
        ("payment", Decimal("250000"), [fm, admin]),
        ("journal", Decimal("0"), [fm]),
    ]
    for doc_type, minimum, approvers in specs:
        rule = ApprovalRule.objects.create(company=company, doc_type=doc_type, min_amount=minimum)
        for order, role in enumerate(approvers, start=1):
            ApprovalStep.objects.create(rule=rule, order=order, role=role)
