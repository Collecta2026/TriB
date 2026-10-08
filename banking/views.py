from django.contrib import messages
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from core.models import AuditLog, client_ip
from ledger.services import PostingError, account_balance, foreign_balance
from users.permissions import require_perm

from . import services
from .forms import BankAccountForm, BankForm, ChequeActionForm
from .models import Bank, Cheque


@require_perm("banking.view")
def account_list(request):
    company = request.company
    rows = []
    for acc in company.bank_accounts.select_related("bank", "currency", "gl_account", "branch"):
        base = account_balance(acc.gl_account)
        own = base if acc.currency_id == company.base_currency_id else foreign_balance(acc.gl_account, acc.currency_id)
        rows.append({"acc": acc, "base": base, "own": own})
    total = sum((r["base"] for r in rows), 0)
    return render(request, "banking/accounts.html", {"rows": rows, "total": total})


@require_perm("banking.create")
def account_new(request):
    form = BankAccountForm(request.POST or None, company=request.company)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            acc = services.create_bank_account(
                request.company, kind=d["kind"], currency=d["currency"], name_en=d["name_en"], name_ar=d["name_ar"],
                bank=d["bank"], account_number=d["account_number"], iban=d["iban"], branch=d["branch"], user=request.user,
            )
        except PostingError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, _("%(name)s created with chart account %(code)s.") % {"name": acc.name, "code": acc.gl_account.code})
            return redirect("banking:accounts")
    return render(request, "banking/account_form.html", {"form": form})


@require_perm("banking.view")
def bank_list(request):
    form = BankForm(request.POST or None)
    if request.method == "POST":
        if not request.membership.has_perm("banking.create"):
            messages.error(request, _("You do not have permission to do that."))
            return redirect("banking:banks")
        if form.is_valid():
            bank = form.save(commit=False)
            bank.company = request.company
            bank.save()
            AuditLog.record(request.company, request.user, "bank.added", bank, bank.name_en, ip=client_ip(request))
            messages.success(request, _("Bank added."))
            return redirect("banking:banks")
    banks = Bank.objects.filter(Q(company__isnull=True) | Q(company=request.company)).order_by("country", "name_en")
    return render(request, "banking/banks.html", {"form": form, "banks": banks})


@require_perm("cheques.view")
def cheque_list(request):
    company = request.company
    direction = request.GET.get("direction", "in")
    status = request.GET.get("status", "")
    cheques = Cheque.objects.filter(company=company, direction=direction).select_related("currency", "bank_account")
    if status:
        cheques = cheques.filter(status=status)
    summary = (
        Cheque.objects.filter(company=company, direction=direction).values("status")
        .annotate(n=Count("id"), total=Sum("amount")).order_by("status")
    )
    form = ChequeActionForm(company=company, initial={"date": timezone.localdate()})
    return render(request, "banking/cheques.html", {
        "cheques": cheques, "direction": direction, "status": status, "summary": summary, "form": form,
        "statuses": [s for s in Cheque.STATUSES if (s[0] in ("in_safe", "under_collection", "cleared", "bounced", "settled")) == (direction == "in")],
    })


@require_POST
@require_perm("cheques.post")
def cheque_action(request, pk):
    cheque = get_object_or_404(Cheque, pk=pk, company=request.company)
    form = ChequeActionForm(request.POST, company=request.company)
    back = redirect(f"/banking/cheques/?direction={cheque.direction}")
    if not form.is_valid():
        messages.error(request, _("Check the date and bank account."))
        return back
    d = form.cleaned_data
    try:
        if d["action"] == "deposit":
            if not d["bank_account"]:
                raise PostingError(_("Choose the bank account the cheque is deposited into."))
            services.deposit_for_collection(cheque, d["bank_account"], d["date"], request.user)
        elif d["action"] == "clear":
            services.clear_cheque(cheque, d["date"], request.user, bank_account=d["bank_account"])
        elif d["action"] == "bounce":
            services.bounce_cheque(cheque, d["date"], request.user)
        elif d["action"] == "cancel":
            services.cancel_issued_cheque(cheque, d["date"], request.user)
        messages.success(request, _("Cheque %(n)s updated.") % {"n": cheque.number})
    except PostingError as exc:
        messages.error(request, str(exc))
    return back
