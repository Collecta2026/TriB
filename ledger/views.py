from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from core.models import AuditLog, client_ip
from users.permissions import require_perm

from .forms import AccountForm, CostCenterForm, ReverseForm
from .models import Account, CostCenter, JournalEntry
from .services import PostingError, balances, reverse_journal


@require_perm("ledger.view")
def account_list(request):
    company = request.company
    accounts = list(Account.objects.filter(company=company).select_related("parent"))
    totals = balances(company)
    by_id = {a.id: a for a in accounts}
    # Roll balances up to header accounts.
    signed = {}
    for a in accounts:
        d, c = totals.get(a.id, (0, 0))
        signed[a.id] = d - c
    rolled = dict(signed)
    for a in accounts:
        node = a.parent_id
        while node:
            rolled[node] = rolled.get(node, 0) + signed[a.id]
            node = by_id[node].parent_id
    rows = []
    for a in accounts:
        value = rolled.get(a.id, 0)
        rows.append({"a": a, "balance": value if a.debit_nature else -value})
    return render(request, "ledger/accounts.html", {"rows": rows})


@require_perm("ledger.create")
def account_new(request):
    form = AccountForm(request.POST or None, company=request.company)
    if request.method == "POST" and form.is_valid():
        account = form.save(commit=False)
        account.company = request.company
        account.save()
        AuditLog.record(request.company, request.user, "account.created", account, str(account), ip=client_ip(request))
        messages.success(request, _("Account %(code)s created.") % {"code": account.code})
        return redirect("ledger:accounts")
    return render(request, "ledger/account_form.html", {"form": form, "title": _("New account")})


@require_perm("ledger.edit")
def account_edit(request, pk):
    account = get_object_or_404(Account, pk=pk, company=request.company)
    form = AccountForm(request.POST or None, instance=account, company=request.company)
    if request.method == "POST" and form.is_valid():
        form.save()
        AuditLog.record(request.company, request.user, "account.changed", account, str(account), ip=client_ip(request))
        messages.success(request, _("Saved."))
        return redirect("ledger:accounts")
    return render(request, "ledger/account_form.html", {"form": form, "title": str(account)})


@require_perm("ledger.view")
def cost_centers(request):
    form = CostCenterForm(request.POST or None)
    if request.method == "POST":
        if not request.membership.has_perm("ledger.edit"):
            messages.error(request, _("You do not have permission to do that."))
            return redirect("ledger:cost_centers")
        if form.is_valid():
            cc = form.save(commit=False)
            cc.company = request.company
            cc.save()
            messages.success(request, _("Cost centre added."))
            return redirect("ledger:cost_centers")
    return render(request, "ledger/cost_centers.html", {"form": form, "rows": CostCenter.objects.filter(company=request.company)})


@require_perm("ledger.view")
def journal_list(request):
    entries = JournalEntry.objects.filter(company=request.company).prefetch_related("lines")
    source = request.GET.get("source")
    if source:
        entries = entries.filter(source=source)
    page = Paginator(entries, 50).get_page(request.GET.get("page"))
    return render(request, "ledger/journals.html", {"page": page, "sources": JournalEntry.SOURCES, "source": source})


@require_perm("ledger.view")
def journal_detail(request, pk):
    entry = get_object_or_404(JournalEntry.objects.select_related("created_by", "reversal_of"), pk=pk, company=request.company)
    lines = entry.lines.select_related("account", "cost_center", "currency")
    form = ReverseForm(initial={"date": timezone.localdate()})
    return render(request, "ledger/journal_detail.html", {"entry": entry, "lines": lines, "form": form})


@require_POST
@require_perm("ledger.void")
def journal_reverse(request, pk):
    entry = get_object_or_404(JournalEntry, pk=pk, company=request.company)
    form = ReverseForm(request.POST)
    if form.is_valid():
        try:
            reversal = reverse_journal(entry, form.cleaned_data["date"], request.user)
            messages.success(request, _("Reversed by %(n)s.") % {"n": reversal.number})
            return redirect("ledger:journal", pk=reversal.pk)
        except PostingError as exc:
            messages.error(request, str(exc))
    return redirect("ledger:journal", pk=pk)
