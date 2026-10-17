"""Remittance advice: what a supplier needs to match our payment against their invoices. For each bill the payment
covers: the invoice amount, credits already taken off it, what we paid before, what this payment pays and what is
still open; then the supplier credits used and any amount paid in advance."""
from decimal import Decimal

from django.db.models import Q, Sum

from core.amount_words import amount_in_words

from .models import BillAllocation, SupplierPayment

ZERO = Decimal("0")


def remittance(payment):
    rows, credits = [], []
    for a in payment.allocations.select_related("bill").order_by("bill__date", "bill_id"):
        bill = a.bill
        used = [c for c in bill.credit_allocations.select_related("credit").order_by("date", "id") if c.date <= payment.date]
        credited = sum((c.amount for c in used), ZERO)
        before = (BillAllocation.objects.filter(bill=bill, payment__status="posted").exclude(payment=payment)
                  .filter(Q(payment__date__lt=payment.date) | Q(payment__date=payment.date, payment_id__lt=payment.pk))
                  .aggregate(s=Sum("amount"))["s"] or ZERO)
        rows.append({"bill": bill, "your_ref": bill.supplier_invoice_no, "our_ref": bill.number, "date": bill.date,
                     "due": bill.due_date, "amount": bill.total, "credited": credited, "before": before,
                     "deducted": credited + before,
                     "now": a.amount, "open": bill.total - credited - before - a.amount})
        credits += [{"your_ref": c.credit.supplier_credit_no, "our_ref": c.credit.number, "date": c.date,
                     "against": bill.supplier_invoice_no or bill.number, "amount": c.amount} for c in used]
    return {"p": payment, "rows": rows, "credits": credits, "advance": payment.unallocated,
            "total_bills": sum((r["amount"] for r in rows), ZERO), "total_now": sum((r["now"] for r in rows), ZERO),
            "words_en": amount_in_words(payment.amount, payment.currency_id, "en"),
            "words_ar": amount_in_words(payment.amount, payment.currency_id, "ar")}


def payments_from(company, ids):
    """Posted payments of this company from "1,2,3" (or a list), in date order."""
    raw = ids.split(",") if isinstance(ids, str) else ids
    pks = [int(x) for x in raw if str(x).strip().isdigit()][:50]
    return list(SupplierPayment.objects.filter(company=company, pk__in=pks).exclude(status="void")
                .select_related("supplier", "currency", "bank_account", "created_by").order_by("date", "id"))
