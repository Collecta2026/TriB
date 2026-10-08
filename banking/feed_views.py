"""Bank transactions (statement import and review), bank rules and reconciliation — QuickBooks' Banking screens."""
from django import forms
from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from core.forms_util import DATE, CompanyModelForm
from ledger.models import Account, JournalLine
from users.permissions import require_perm

from . import feeds
from .models import BankAccount, BankRule, Reconciliation, StatementLine

SESSION_KEY = "bank.import"
MAX_ROWS = 3000
FIELDS = [("date", gettext_lazy("Date")), ("description", gettext_lazy("Description")),
          ("reference", gettext_lazy("Reference")), ("amount", gettext_lazy("Amount (+ in, − out)")),
          ("credit", gettext_lazy("Money in")), ("debit", gettext_lazy("Money out"))]


class RuleForm(CompanyModelForm):
    class Meta:
        model = BankRule
        fields = ["name", "contains", "direction", "account", "memo", "auto_post", "priority", "is_active"]


class ReconcileStartForm(forms.Form):
    bank_account = forms.ModelChoiceField(BankAccount.objects.none(), label=gettext_lazy("Account"))
    statement_date = forms.DateField(label=gettext_lazy("Statement end date"), widget=DATE)
    statement_balance = forms.DecimalField(label=gettext_lazy("Statement ending balance"), decimal_places=2)

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["bank_account"].queryset = BankAccount.objects.filter(company=company, is_active=True)


def _accounts(request):
    return BankAccount.objects.filter(company=request.company, is_active=True).select_related("gl_account")


# ---------- Bank transactions ----------
@require_perm("banking.view")
def transactions(request):
    accounts = list(_accounts(request))
    account = None
    aid = request.GET.get("account", "")
    if aid.isdigit():
        account = next((a for a in accounts if a.pk == int(aid)), None)
    account = account or (accounts[0] if accounts else None)
    tab = request.GET.get("tab", "new")
    rows, counts = [], {}
    if account:
        base = StatementLine.objects.filter(bank_account=account)
        counts = {s: base.filter(status=s).count() for s, _l in StatementLine.STATUSES}
        qs = base.filter(status__in=("matched", "posted")) if tab == "done" else base.filter(status=tab if tab in ("new", "excluded") else "new")
        page = Paginator(qs.select_related("rule", "rule__account", "journal_line__entry"), 50).get_page(request.GET.get("page"))
        rows = [{"line": l, "suggestions": feeds.suggestions(l) if l.status == "new" else [],
                 "cheques": feeds.cheque_candidates(l) if l.status == "new" else []} for l in page]
    else:
        page = None
    return render(request, "banking/transactions.html", {
        "accounts": accounts, "account": account, "tab": tab, "rows": rows, "page": page, "counts": counts,
        "post_accounts": Account.objects.filter(company=request.company, is_group=False, is_active=True)})


@require_perm("banking.post")
def transactions_import(request):
    accounts = _accounts(request)
    if request.method == "POST" and "file" in request.FILES:
        account = get_object_or_404(BankAccount, pk=request.POST.get("bank_account"), company=request.company)
        upload = request.FILES["file"]
        if upload.size > 5 * 1024 * 1024 or not upload.name.lower().endswith((".csv", ".xlsx", ".txt")):
            messages.error(request, _("Upload a CSV or Excel (.xlsx) statement under 5 MB."))
            return redirect("banking:transactions_import")
        try:
            table = feeds.read_table(upload)
        except Exception:  # damaged files raise many different errors
            messages.error(request, _("TriB could not read this file. Export the statement again as CSV or .xlsx."))
            return redirect("banking:transactions_import")
        table = [r for r in table if any(str(c).strip() for c in r)][:MAX_ROWS]
        if len(table) < 2:
            messages.error(request, _("The file has no transactions."))
            return redirect("banking:transactions_import")
        request.session[SESSION_KEY] = {"account": account.pk, "rows": table}
        return redirect("banking:transactions_map")
    return render(request, "banking/import.html", {"accounts": accounts})


def _guess(header):
    guesses = {}
    words = {"date": ("date", "تاريخ"), "description": ("desc", "detail", "narr", "بيان", "وصف"),
             "reference": ("ref", "cheque", "مرجع"), "credit": ("credit", "deposit", "دائن", "إيداع"),
             "debit": ("debit", "withdraw", "مدين", "سحب"), "amount": ("amount", "مبلغ")}
    for i, h in enumerate(header):
        h = str(h).lower()
        for key, keys in words.items():
            if key not in guesses and any(k in h for k in keys):
                guesses[key] = i
    if "credit" in guesses and "debit" in guesses:
        guesses.pop("amount", None)
    return guesses


@require_perm("banking.post")
def transactions_map(request):
    data = request.session.get(SESSION_KEY)
    if not data:
        return redirect("banking:transactions_import")
    account = get_object_or_404(BankAccount, pk=data["account"], company=request.company)
    rows = data["rows"]
    width = max(len(r) for r in rows)
    if request.method == "POST":
        mapping = {}
        for key, _label in FIELDS:
            raw = request.POST.get(key, "")
            mapping[key] = int(raw) if raw.isdigit() and int(raw) < width else None
        if mapping["date"] is None or (mapping["amount"] is None and (mapping["credit"] is None or mapping["debit"] is None)):
            messages.error(request, _("Choose the date column, and either the amount column or both money in and money out."))
        else:
            if mapping["amount"] is not None:
                mapping.pop("credit"), mapping.pop("debit")
            else:
                mapping.pop("amount")
            created, skipped = feeds.import_statement(request.company, account, rows, mapping, request.user,
                                                      skip_header=request.POST.get("header") == "1")
            request.session.pop(SESSION_KEY, None)
            messages.success(request, _("%(n)s transactions imported, %(s)s skipped (duplicates or blank).") % {
                "n": len(created), "s": skipped})
            cleared = sum(1 for l in created if l.status == "matched")
            if cleared:
                messages.success(request, _("%(n)s cheques were found on the statement and cleared.") % {"n": cleared})
            return redirect(f"{_url('banking:transactions')}?account={account.pk}")
    return render(request, "banking/import_map.html", {
        "account": account, "preview": rows[:6], "columns": range(width), "fields": FIELDS, "guess": _guess(rows[0]),
        "total": len(rows)})


def _url(name):
    from django.urls import reverse
    return reverse(name)


@require_POST
@require_perm("banking.post")
def transaction_action(request, pk):
    line = get_object_or_404(StatementLine, pk=pk, company=request.company)
    action = request.POST.get("action")
    try:
        if action == "match":
            jl = get_object_or_404(JournalLine, pk=request.POST.get("journal_line"), entry__company=request.company)
            feeds.match(line, jl, request.user)
            messages.success(request, _("Matched."))
        elif action == "add":
            account = get_object_or_404(Account, pk=request.POST.get("account"), company=request.company, is_group=False)
            entry = feeds.categorise(line, account, request.POST.get("memo") or line.description, request.user)
            messages.success(request, _("Added to the books as %(n)s.") % {"n": entry.number})
        elif action == "cheque":
            from .models import Cheque
            cheque = get_object_or_404(Cheque, pk=request.POST.get("cheque"), company=request.company)
            feeds.clear_from_statement(line, cheque, request.user)
            messages.success(request, _("Cheque %(n)s cleared.") % {"n": cheque.number})
        elif action == "exclude":
            feeds.exclude(line, request.user)
            messages.success(request, _("Excluded."))
        elif action == "restore" and line.status == "excluded":
            line.status = "new"
            line.save(update_fields=["status"])
    except feeds.FeedError as exc:
        messages.error(request, str(exc))
    return redirect(f"{_url('banking:transactions')}?account={line.bank_account_id}")


# ---------- Rules ----------
@require_perm("banking.view")
def rules(request):
    obj = None
    pk = request.GET.get("edit") or request.POST.get("pk")
    if pk and str(pk).isdigit():
        obj = get_object_or_404(BankRule, pk=pk, company=request.company)
    form = None
    if request.membership.has_perm("banking.edit"):
        form = RuleForm(request.POST or None, instance=obj or BankRule(company=request.company), company=request.company)
        if request.method == "POST" and form.is_valid():
            rule = form.save(commit=False)
            rule.company = request.company
            rule.save()
            messages.success(request, _("Saved."))
            return redirect("banking:rules")
    return render(request, "banking/rules.html", {
        "rows": BankRule.objects.filter(company=request.company).select_related("account"), "form": form, "obj": obj})


# ---------- Reconcile ----------
@require_perm("banking.view")
def reconcile(request):
    form = ReconcileStartForm(request.POST or None, company=request.company,
                              initial={"statement_date": timezone.localdate()})
    if request.method == "POST":
        if not request.membership.has_perm("banking.post"):
            messages.error(request, _("You do not have permission to do that."))
        elif form.is_valid():
            d = form.cleaned_data
            account = d["bank_account"]
            if account.reconciliations.filter(status="open").exists():
                rec = account.reconciliations.filter(status="open").first()
                messages.info(request, _("Carry on with the reconciliation already in progress."))
            else:
                rec = Reconciliation.objects.create(
                    company=request.company, bank_account=account, statement_date=d["statement_date"],
                    statement_balance=d["statement_balance"], opening_balance=feeds.last_reconciled_balance(account),
                    created_by=request.user)
            return redirect("banking:reconciliation", pk=rec.pk)
    return render(request, "banking/reconcile.html", {
        "form": form, "rows": Reconciliation.objects.filter(company=request.company).select_related("bank_account")[:40]})


@require_perm("banking.view")
def reconciliation(request, pk):
    rec = get_object_or_404(Reconciliation, pk=pk, company=request.company)
    if request.method == "POST" and rec.status == "open" and request.membership.has_perm("banking.post"):
        ids = [int(i) for i in request.POST.getlist("cleared") if i.isdigit()]
        try:
            feeds.set_cleared(rec, ids)
            if "finish" in request.POST:
                feeds.finish(rec, request.user)
                messages.success(request, _("Reconciled."))
            else:
                messages.success(request, _("Progress saved."))
        except feeds.FeedError as exc:
            messages.error(request, str(exc))
        return redirect("banking:reconciliation", pk=pk)
    foreign = rec.bank_account.currency_id != rec.company.base_currency_id
    lines = [{"l": l, "amount": feeds._signed(l, foreign), "cleared": l.reconciliation_id == rec.pk}
             for l in feeds.uncleared(rec)]
    return render(request, "banking/reconciliation.html", {
        "rec": rec, "lines": lines, "cleared": feeds.cleared_total(rec), "difference": feeds.difference(rec)})
