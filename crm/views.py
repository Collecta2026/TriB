"""Customer Hub pages. Lists and forms share two templates (crm/list.html, crm/form.html); leads, opportunities,
proposals and contracts have their own detail pages. Proposals, contracts and review requests can be opened by the
customer from a private link (no sign-in)."""
from datetime import timedelta
from urllib.parse import quote
from decimal import Decimal

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Sum
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from core.doc_actions import whatsapp_number
from core.models import AuditLog, NumberSeries, ShareLink, client_ip
from users.permissions import require_perm

from . import forms
from .models import Appointment, Contract, Conversation, Lead, Opportunity, Proposal, Review, Task

# One place that says how each record type is listed and edited.
KINDS = {
    "lead": {"model": Lead, "form": forms.LeadForm, "title": gettext_lazy("Lead"), "plural": gettext_lazy("Customers & leads"),
             "columns": [(gettext_lazy("Name"), "name"), (gettext_lazy("Contact person"), "contact_person"),
                         (gettext_lazy("Phone"), "phone"), (gettext_lazy("Source"), "get_source_display"),
                         (gettext_lazy("Status"), "get_status_display"), (gettext_lazy("Owner"), "owner")]},
    "opportunity": {"model": Opportunity, "form": forms.OpportunityForm, "title": gettext_lazy("Opportunity"),
                    "plural": gettext_lazy("Opportunities"),
                    "columns": [(gettext_lazy("Opportunity"), "title"), (gettext_lazy("Customer / lead"), "party"),
                                (gettext_lazy("Stage"), "get_stage_display"), (gettext_lazy("Value"), "value"),
                                (gettext_lazy("Probability %"), "probability"), (gettext_lazy("Expected close"), "expected_close"),
                                (gettext_lazy("Owner"), "owner")]},
    "proposal": {"model": Proposal, "form": forms.ProposalForm, "title": gettext_lazy("Proposal"),
                 "plural": gettext_lazy("Proposals"),
                 "columns": [(gettext_lazy("Number"), "number"), (gettext_lazy("Title"), "title"),
                             (gettext_lazy("Customer"), "customer"), (gettext_lazy("Date"), "date"),
                             (gettext_lazy("Status"), "get_status_display")]},
    "contract": {"model": Contract, "form": forms.ContractForm, "title": gettext_lazy("Contract"),
                 "plural": gettext_lazy("Contracts"),
                 "columns": [(gettext_lazy("Number"), "number"), (gettext_lazy("Title"), "title"),
                             (gettext_lazy("Customer"), "customer"), (gettext_lazy("Start date"), "start_date"),
                             (gettext_lazy("End date"), "end_date"), (gettext_lazy("Contract value"), "value"),
                             (gettext_lazy("Status"), "get_status_display")]},
    "appointment": {"model": Appointment, "form": forms.AppointmentForm, "title": gettext_lazy("Appointment"),
                    "plural": gettext_lazy("Appointments"),
                    "columns": [(gettext_lazy("When"), "starts_at"), (gettext_lazy("Title"), "title"),
                                (gettext_lazy("Customer"), "customer"), (gettext_lazy("Lead"), "lead"),
                                (gettext_lazy("Location"), "location")]},
    "task": {"model": Task, "form": forms.TaskForm, "title": gettext_lazy("Task"), "plural": gettext_lazy("Tasks"),
             "columns": [(gettext_lazy("Task"), "title"), (gettext_lazy("Due date"), "due_date"),
                         (gettext_lazy("Assigned to"), "assignee"), (gettext_lazy("Customer"), "customer"),
                         (gettext_lazy("Lead"), "lead")]},
    "conversation": {"model": Conversation, "form": forms.ConversationForm, "title": gettext_lazy("Conversation"),
                     "plural": gettext_lazy("Conversations"),
                     "columns": [(gettext_lazy("When"), "happened_at"), (gettext_lazy("Type"), "get_kind_display"),
                                 (gettext_lazy("Customer"), "customer"), (gettext_lazy("Lead"), "lead"),
                                 (gettext_lazy("What was said"), "summary"), (gettext_lazy("By"), "by")]},
}
DETAIL = {"lead", "opportunity", "proposal", "contract"}
NUMBERS = {"proposal": "PRP", "contract": "CON"}


def _cell(obj, attr):
    value = getattr(obj, attr, "")
    return value() if callable(value) else value


def _initial(request):
    """New records opened from a customer, lead or opportunity page start linked to it."""
    out = {}
    for key in ("customer", "lead", "opportunity", "supplier"):
        if request.GET.get(key, "").isdigit():
            out[key] = request.GET[key]
    if request.GET.get("date"):
        out["starts_at"] = f"{request.GET['date']}T09:00"
    return out


@require_perm("crm.view")
def crm_list(request, kind):
    cfg = KINDS.get(kind)
    if cfg is None:
        raise Http404
    qs = cfg["model"].objects.filter(company=request.company)
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    if kind == "task":
        mine = request.GET.get("show", "open")
        if mine == "open":
            qs = qs.filter(done=False)
        elif mine == "mine":
            qs = qs.filter(done=False, assignee=request.user)
    if kind == "appointment" and request.GET.get("show") != "past":
        qs = qs.filter(starts_at__gte=timezone.now() - timedelta(hours=12))
    if status and kind in ("lead", "proposal", "contract"):
        qs = qs.filter(status=status)
    if status and kind == "opportunity":
        qs = qs.filter(stage=status)
    if q:
        fields = {"lead": "name", "opportunity": "title", "proposal": "title", "contract": "title", "appointment": "title",
                  "task": "title", "conversation": "summary"}
        qs = qs.filter(**{f"{fields[kind]}__icontains": q})
    rows = [{"obj": o, "cells": [_cell(o, attr) for _l, attr in cfg["columns"]],
             "url": reverse(f"crm:{kind}", args=[o.pk]) if kind in DETAIL else reverse("crm:edit", args=[kind, o.pk])}
            for o in qs[:300]]
    statuses = {"lead": Lead.STATUSES, "opportunity": Opportunity.STAGES, "proposal": Proposal.STATUSES,
                "contract": Contract.STATUSES}.get(kind, [])
    return render(request, "crm/list.html", {"kind": kind, "cfg": cfg, "rows": rows, "q": q, "status": status,
                                             "statuses": statuses, "show": request.GET.get("show", "open")})


@require_perm("crm.create")
def crm_new(request, kind):
    return _form(request, kind, None)


@require_perm("crm.edit")
def crm_edit(request, kind, pk):
    cfg = KINDS.get(kind)
    if cfg is None:
        raise Http404
    return _form(request, kind, get_object_or_404(cfg["model"], pk=pk, company=request.company))


@transaction.atomic
def _form(request, kind, obj):
    cfg = KINDS.get(kind)
    if cfg is None:
        raise Http404
    company = request.company
    if obj is None:
        obj = cfg["model"](company=company)
        if hasattr(obj, "currency_id"):
            obj.currency = company.base_currency
    initial = _initial(request) if obj.pk is None else {}
    if obj.pk is None and kind == "proposal":
        initial.setdefault("date", timezone.localdate())
    if obj.pk is None and kind == "contract":
        initial.setdefault("start_date", timezone.localdate())
    if obj.pk is None and kind == "conversation":
        initial.setdefault("happened_at", timezone.localtime().strftime("%Y-%m-%dT%H:%M"))
    if obj.pk is None and kind in ("lead", "opportunity"):
        initial.setdefault("owner", request.user.pk)
    if obj.pk is None and kind == "task":
        initial.setdefault("assignee", request.user.pk)
    form = cfg["form"](request.POST or None, instance=obj, company=company, initial=initial)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.company = company
        for field in ("created_by", "by"):
            if hasattr(obj, f"{field}_id") and not getattr(obj, f"{field}_id"):
                setattr(obj, field, request.user)
        if kind in NUMBERS and not obj.number:
            obj.number = NumberSeries.next(company, NUMBERS[kind], getattr(obj, "date", None) or obj.start_date)
        if kind == "opportunity" and obj.stage in ("won", "lost") and not obj.closed_at:
            obj.closed_at = timezone.localdate()
        obj.save()
        form.save_m2m()
        AuditLog.record(company, request.user, f"crm.{kind}.saved", obj, str(obj)[:200], ip=client_ip(request))
        messages.success(request, _("Saved."))
        nxt = request.POST.get("next") or request.GET.get("next")
        if nxt and nxt.startswith("/") and not nxt.startswith("//"):
            return redirect(nxt)
        if request.POST.get("save") == "new":
            return redirect("crm:new", kind)
        return redirect(reverse(f"crm:{kind}", args=[obj.pk]) if kind in DETAIL else reverse("crm:list", args=[kind]))
    return render(request, "crm/form.html", {"form": form, "kind": kind, "cfg": cfg, "obj": obj,
                                             "next": request.GET.get("next", "")})


# ---------- Overview ----------
@require_perm("crm.view")
def overview(request):
    company, today = request.company, timezone.localdate()
    opps = Opportunity.objects.filter(company=company)
    open_ = opps.filter(stage__in=Opportunity.OPEN)
    stages = []
    for key, label in Opportunity.STAGES:
        agg = opps.filter(stage=key).aggregate(n=Count("id"), v=Sum("value"))
        stages.append({"key": key, "label": label, "n": agg["n"], "value": agg["v"] or Decimal("0")})
    year_closed = opps.filter(stage__in=("won", "lost"), closed_at__year=today.year)
    won = year_closed.filter(stage="won").count()
    win_rate = round(won * 100 / year_closed.count()) if year_closed.count() else None
    pipeline = sum((o.value for o in open_), Decimal("0"))
    weighted = sum((o.weighted for o in open_), Decimal("0"))
    return render(request, "crm/overview.html", {
        "stages": stages, "pipeline": pipeline, "weighted": weighted, "win_rate": win_rate,
        "leads_month": Lead.objects.filter(company=company, created_at__date__gte=today.replace(day=1)).count(),
        "appointments": Appointment.objects.filter(company=company, starts_at__date__gte=today,
                                                   starts_at__date__lte=today + timedelta(days=7))
        .select_related("customer", "lead")[:8],
        "tasks": Task.objects.filter(company=company, done=False, due_date__lte=today + timedelta(days=7))
        .select_related("customer", "lead", "assignee")[:8],
        "closing": open_.filter(expected_close__lte=today + timedelta(days=30)).select_related("customer", "lead")[:8],
        "reviews": Review.objects.filter(company=company, submitted_at__isnull=False).aggregate(n=Count("id"), avg=Sum("rating")),
        "today": today})


# ---------- Leads ----------
@require_perm("crm.view")
def lead(request, pk):
    obj = get_object_or_404(Lead, pk=pk, company=request.company)
    return render(request, "crm/lead.html", {"obj": obj, "tasks": obj.tasks.all(), "conversations": obj.conversations.all(),
                                             "appointments": obj.appointments.all(), "opportunities": obj.opportunities.all()})


@require_POST
@require_perm("crm.edit")
@transaction.atomic
def lead_convert(request, pk):
    """Make the lead a customer; its opportunities, tasks and conversations move to the customer."""
    from contacts.models import Customer

    obj = get_object_or_404(Lead, pk=pk, company=request.company)
    if obj.customer_id:
        return redirect("contacts:customer", pk=obj.customer_id)
    if not request.membership.has_perm("contacts.create"):
        messages.error(request, _("You do not have permission to do that."))
        return redirect("crm:lead", pk=pk)
    customer = Customer.objects.create(company=request.company, code=NumberSeries.next_plain(request.company, "CUS"),
                                       name_en=obj.name, contact_person=obj.contact_person, email=obj.email,
                                       phone=obj.phone, city=obj.city, currency=request.company.base_currency,
                                       notes=obj.notes)
    obj.customer, obj.status = customer, "converted"
    obj.save(update_fields=["customer", "status"])
    for model in (Opportunity, Task, Conversation, Appointment):
        model.objects.filter(lead=obj).update(customer=customer)
    AuditLog.record(request.company, request.user, "crm.lead.converted", obj, f"{obj.name} → {customer.code}",
                    ip=client_ip(request))
    messages.success(request, _("%(n)s is now a customer.") % {"n": obj.name})
    return redirect("contacts:customer", pk=customer.pk)


# ---------- Opportunities ----------
@require_perm("crm.view")
def opportunity(request, pk):
    obj = get_object_or_404(Opportunity, pk=pk, company=request.company)
    return render(request, "crm/opportunity.html", {"obj": obj, "tasks": obj.tasks.all(), "proposals": obj.proposals.all(),
                                                    "appointments": obj.appointments.all()})


@require_perm("crm.view")
def board(request):
    opps = Opportunity.objects.filter(company=request.company).select_related("customer", "lead", "owner", "currency")
    cols = [{"key": k, "label": label, "items": [o for o in opps if o.stage == k]} for k, label in Opportunity.STAGES]
    for c in cols:
        c["value"] = sum((o.value for o in c["items"]), Decimal("0"))
    return render(request, "crm/board.html", {"cols": cols})


@require_POST
@require_perm("crm.edit")
def opportunity_stage(request, pk):
    obj = get_object_or_404(Opportunity, pk=pk, company=request.company)
    stage = request.POST.get("stage", "")
    if stage not in dict(Opportunity.STAGES):
        return JsonResponse({"error": "bad stage"}, status=400)
    obj.stage = stage
    obj.probability = {"won": 100, "lost": 0}.get(stage, obj.probability)
    obj.closed_at = timezone.localdate() if stage in ("won", "lost") else None
    obj.save(update_fields=["stage", "probability", "closed_at"])
    AuditLog.record(request.company, request.user, "crm.opportunity.stage", obj, f"{obj.title}: {stage}", ip=client_ip(request))
    return JsonResponse({"ok": True})


# ---------- Proposals and contracts ----------
def _quote_lines(quote):
    return quote.lines.select_related("item", "tax_rate") if quote else []


@require_perm("crm.view")
def proposal(request, pk):
    obj = get_object_or_404(Proposal, pk=pk, company=request.company)
    return render(request, "crm/proposal.html", {"obj": obj, "lines": _quote_lines(obj.quotation), "kind": "proposal",
                                                 "share_url": reverse("crm:share", args=["proposal", obj.pk])})


@require_perm("crm.view")
def contract(request, pk):
    obj = get_object_or_404(Contract, pk=pk, company=request.company)
    return render(request, "crm/contract.html", {"obj": obj, "kind": "contract",
                                                 "share_url": reverse("crm:share", args=["contract", obj.pk])})


@require_POST
@require_perm("crm.edit")
def proposal_action(request, pk):
    from sales import services as sales

    obj = get_object_or_404(Proposal, pk=pk, company=request.company)
    action = request.POST.get("action")
    if action in ("sent", "declined", "draft"):
        obj.status = action
        obj.save(update_fields=["status"])
    elif action == "order" and obj.status == "accepted" and obj.quotation_id and request.membership.has_perm("sales.create"):
        try:
            order = sales.quote_to_order(obj.quotation, request.user)
        except sales.SalesError as exc:
            messages.error(request, str(exc))
            return redirect("crm:proposal", pk=pk)
        if obj.opportunity_id:
            Opportunity.objects.filter(pk=obj.opportunity_id).update(stage="won", probability=100,
                                                                    closed_at=timezone.localdate())
        messages.success(request, _("Sales order created from the accepted proposal."))
        return redirect("sales:order", pk=order.pk)
    AuditLog.record(request.company, request.user, f"crm.proposal.{action}", obj, str(obj), ip=client_ip(request))
    return redirect("crm:proposal", pk=pk)


@require_POST
@require_perm("crm.view")
def share(request, kind, pk):
    """Private link for the customer to read and accept a proposal or contract."""
    model = {"proposal": Proposal, "contract": Contract}.get(kind)
    if model is None:
        raise Http404
    obj = get_object_or_404(model, pk=pk, company=request.company)
    if request.POST.get("revoke") == "1":
        ShareLink.objects.filter(company=request.company, target=obj._meta.label_lower, target_id=obj.pk,
                                 revoked_at__isnull=True).update(revoked_at=timezone.now())
        return JsonResponse({"revoked": True})
    link = ShareLink.for_object(obj, request.user)
    if obj.status == "draft":
        obj.status = "sent"
        obj.save(update_fields=["status"])
    url = request.build_absolute_uri(reverse("crm:public", args=[link.token]))
    phone = whatsapp_number(obj.customer.phone)
    text = _("Hello %(name)s, please review our %(doc)s \"%(title)s\": %(link)s") % {
        "name": obj.customer.name, "doc": KINDS[kind]["title"], "title": obj.title, "link": url}
    return JsonResponse({"url": url, "whatsapp": f"https://wa.me/{phone}?text={quote(text)}"})


def public(request, token):
    """What the customer sees from the link: the proposal or contract, and an Accept form."""
    link = ShareLink.objects.filter(token=token, revoked_at__isnull=True,
                                    target__in=("crm.proposal", "crm.contract")).select_related("company").first()
    if link is None:
        return render(request, "docs/shared_gone.html", status=404)
    model = Proposal if link.target == "crm.proposal" else Contract
    obj = model.objects.filter(pk=link.target_id, company=link.company).first()
    if obj is None or obj.status in ("draft", "cancelled"):
        return render(request, "docs/shared_gone.html", status=404)
    form = forms.AcceptForm(request.POST or None)
    accepted_states = ("accepted", "active")
    if request.method == "POST" and obj.status not in accepted_states and form.is_valid():
        obj.accepted_name, obj.accepted_at = form.cleaned_data["name"], timezone.now()
        obj.status = "accepted" if model is Proposal else "active"
        obj.save(update_fields=["accepted_name", "accepted_at", "status"])
        AuditLog.record(link.company, None, f"crm.{model.__name__.lower()}.accepted", obj,
                        f"{obj} accepted by {obj.accepted_name}", ip=client_ip(request))
        return redirect(request.path)
    ShareLink.objects.filter(pk=link.pk).update(views=link.views + 1, last_viewed_at=timezone.now())
    lines = _quote_lines(obj.quotation) if model is Proposal else []
    return render(request, "crm/public.html", {"obj": obj, "company": link.company, "form": form, "lines": lines,
                                               "is_proposal": model is Proposal,
                                               "accepted": obj.status in accepted_states})


# ---------- Reviews ----------
@require_perm("crm.view")
def reviews(request):
    rows = Review.objects.filter(company=request.company).select_related("customer")
    done = rows.filter(submitted_at__isnull=False)
    avg = done.aggregate(n=Count("id"), total=Sum("rating"))
    return render(request, "crm/reviews.html", {"rows": rows[:200], "count": avg["n"],
                                                "average": round(avg["total"] / avg["n"], 1) if avg["n"] else None})


@require_perm("crm.create")
def review_request(request):
    """Request feedback: a private link for the customer to rate you."""
    from contacts.models import Customer

    cid = request.GET.get("customer") or request.POST.get("customer")
    customer = get_object_or_404(Customer, pk=cid, company=request.company) if str(cid or "").isdigit() else None
    if request.method == "POST" and customer:
        r = Review.request(customer, request.user)
        url = request.build_absolute_uri(reverse("crm:review_public", args=[r.token]))
        text = _("Hello %(name)s, how did we do? Please rate us here: %(link)s") % {"name": customer.name, "link": url}
        return render(request, "crm/review_link.html", {"customer": customer, "url": url,
                                                        "whatsapp": f"https://wa.me/{whatsapp_number(customer.phone)}?text={quote(text)}",
                                                        "mailto": f"mailto:{customer.email}?body={quote(text)}"})
    customers = Customer.objects.filter(company=request.company, is_active=True)
    return render(request, "crm/review_request.html", {"customer": customer, "customers": customers})


def review_public(request, token):
    r = Review.objects.filter(token=token).select_related("company", "customer").first()
    if r is None:
        return render(request, "docs/shared_gone.html", status=404)
    form = forms.ReviewForm(request.POST or None, initial={"reviewer": r.customer.contact_person})
    if request.method == "POST" and r.submitted_at is None and form.is_valid():
        r.rating, r.comment, r.reviewer = form.cleaned_data["rating"], form.cleaned_data["comment"], form.cleaned_data["reviewer"]
        r.submitted_at = timezone.now()
        r.save(update_fields=["rating", "comment", "reviewer", "submitted_at"])
        return redirect(request.path)
    return render(request, "crm/review_public.html", {"r": r, "form": form, "company": r.company})


# ---------- Tasks and appointments ----------
@require_POST
@require_perm("crm.edit")
def task_done(request, pk):
    t = get_object_or_404(Task, pk=pk, company=request.company)
    t.done = not t.done
    t.done_at = timezone.now() if t.done else None
    t.save(update_fields=["done", "done_at"])
    nxt = request.POST.get("next", "")
    return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else reverse("crm:list", args=["task"]))


@require_perm("crm.view")
def calendar(request):
    from django.utils.dateparse import parse_date

    today = timezone.localdate()
    start = parse_date(request.GET.get("week", "") or "") or today
    start = start - timedelta(days=(start.weekday() + 1) % 7)  # weeks start on Sunday
    days = [start + timedelta(days=i) for i in range(7)]
    appts = (Appointment.objects.filter(company=request.company, starts_at__date__gte=days[0], starts_at__date__lte=days[-1])
             .select_related("customer", "lead"))
    by_day = [{"day": d, "items": [a for a in appts if timezone.localtime(a.starts_at).date() == d]} for d in days]
    return render(request, "crm/calendar.html", {"days": by_day, "prev": days[0] - timedelta(days=7),
                                                 "next": days[0] + timedelta(days=7), "today": today})
