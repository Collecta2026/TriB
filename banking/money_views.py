"""Transfers between the company's own accounts, and bank deposits (QuickBooks: Transfer, Bank deposit)."""
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from core.forms_util import DATE, CompanyModelForm
from ledger.services import PostingError
from users.permissions import require_perm

from . import services
from .models import BankAccount, BankDeposit, BankTransfer, Cheque


class TransferForm(CompanyModelForm):
    class Meta:
        model = BankTransfer
        fields = ["date", "from_account", "to_account", "amount", "amount_to", "reference", "memo"]
        widgets = {"date": DATE}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["amount_to"].required = False


class DepositForm(CompanyModelForm):
    class Meta:
        model = BankDeposit
        fields = ["date", "bank_account", "reference", "cash_from", "cash_amount", "notes"]
        widgets = {"date": DATE}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        accounts = BankAccount.objects.filter(company=self.company, is_active=True)
        self.fields["bank_account"].queryset = accounts.filter(kind="bank")
        self.fields["cash_from"].queryset = accounts.filter(kind="cash")
        self.fields["cash_from"].required = False
        self.fields["cash_amount"].required = False


# ---------- Transfers ----------
@require_perm("banking.view")
def transfers(request):
    company = request.company
    form = TransferForm(request.POST or None, company=company, initial={"date": timezone.localdate()},
                        instance=BankTransfer(company=company))
    if request.method == "POST":
        if not request.membership.has_perm("banking.post"):
            messages.error(request, _("You do not have permission to do that."))
        elif form.is_valid():
            transfer = form.save(commit=False)
            transfer.company, transfer.created_by = company, request.user
            transfer.amount_to = transfer.amount_to or 0
            try:
                with transaction.atomic():
                    services.post_transfer(transfer, request.user)
            except PostingError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, _("Transfer %(n)s posted.") % {"n": transfer.number})
                return redirect("banking:transfers")
    qs = BankTransfer.objects.filter(company=company).select_related("from_account", "to_account", "journal_entry")
    return render(request, "banking/transfers.html", {"form": form, "page": Paginator(qs, 40).get_page(request.GET.get("page"))})


@require_POST
@require_perm("banking.post")
def transfer_void(request, pk):
    transfer = get_object_or_404(BankTransfer, pk=pk, company=request.company)
    try:
        services.void_transfer(transfer, request.user)
        messages.success(request, _("Transfer voided."))
    except PostingError as exc:
        messages.error(request, str(exc))
    return redirect("banking:transfers")


# ---------- Bank deposits ----------
@require_perm("banking.view")
def deposits(request):
    qs = BankDeposit.objects.filter(company=request.company).select_related("bank_account", "cash_from")
    return render(request, "banking/deposits.html", {"page": Paginator(qs, 40).get_page(request.GET.get("page"))})


@require_perm("banking.post")
def deposit_new(request):
    company = request.company
    form = DepositForm(request.POST or None, company=company, initial={"date": timezone.localdate()},
                       instance=BankDeposit(company=company))
    waiting = Cheque.objects.filter(company=company, direction="in", status="in_safe").select_related("currency").order_by("due_date")
    if request.method == "POST" and form.is_valid():
        deposit = form.save(commit=False)
        deposit.company, deposit.created_by = company, request.user
        deposit.cash_amount = deposit.cash_amount or 0
        ids = [int(i) for i in request.POST.getlist("cheque") if i.isdigit()]
        cheques = list(waiting.filter(pk__in=ids))
        try:
            with transaction.atomic():
                services.post_deposit(deposit, cheques, request.user)
        except PostingError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, _("Deposit %(n)s recorded.") % {"n": deposit.number})
            return redirect("banking:deposit", pk=deposit.pk)
    return render(request, "banking/deposit_form.html", {"form": form, "waiting": waiting, "today": timezone.localdate(),
                                                         "chosen": set(request.POST.getlist("cheque"))})


@require_perm("banking.view")
def deposit(request, pk):
    dep = get_object_or_404(BankDeposit, pk=pk, company=request.company)
    return render(request, "banking/deposit_slip.html", {"d": dep, "cheques": dep.cheques.select_related("currency")})
