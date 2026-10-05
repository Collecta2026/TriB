from django.conf import settings
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from core.models import AuditLog, Company, client_ip

from .forms import LoginForm, MemberForm, RoleForm
from .models import DOC_TYPES, ApprovalLimit, Membership, Role, User
from .permissions import ALL_CODES, ACTIONS, matrix_rows, require_perm


class LoginView(auth_views.LoginView):
    template_name = "users/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def dispatch(self, request, *args, **kwargs):
        if not Company.objects.exists():
            return redirect("core:setup")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        user = form.get_user()
        response.set_cookie(settings.LANGUAGE_COOKIE_NAME, user.preferred_language, max_age=365 * 24 * 3600, samesite="Lax")
        AuditLog.record(None, user, "user.login", user, user.email, ip=client_ip(self.request))
        return response


@login_required
def change_password(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        messages.success(request, _("Your password was changed."))
        return redirect("dashboard:home")
    return render(request, "users/password.html", {"form": form})


@require_perm("users.view")
def user_list(request):
    members = Membership.objects.filter(company=request.company).select_related("user").prefetch_related("roles", "branches")
    roles = request.company.roles.prefetch_related("limits")
    return render(request, "users/users.html", {"members": members, "roles": roles})


@require_perm("users.create")
@transaction.atomic
def user_new(request):
    form = MemberForm(request.POST or None, company=request.company)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        user = User.objects.filter(email__iexact=d["email"]).first()
        if user is None:
            user = User.objects.create_user(d["email"], d["password"], full_name=d["full_name"], phone=d["phone"],
                                            preferred_language=d["preferred_language"])
        membership = Membership.objects.create(user=user, company=request.company, is_active=d["is_active"])
        membership.roles.set(d["roles"])
        membership.branches.set(d["branches"])
        AuditLog.record(request.company, request.user, "user.added", membership,
                        f"{user.email}: {', '.join(r.name_en for r in d['roles'])}", ip=client_ip(request))
        messages.success(request, _("%(name)s can now sign in.") % {"name": user})
        return redirect("users:users")
    return render(request, "users/user_form.html", {"form": form, "title": _("Add user")})


@require_perm("users.edit")
@transaction.atomic
def user_edit(request, pk):
    membership = get_object_or_404(Membership, pk=pk, company=request.company)
    user = membership.user
    initial = {"full_name": user.full_name, "phone": user.phone, "preferred_language": user.preferred_language,
               "roles": membership.roles.all(), "branches": membership.branches.all(), "is_active": membership.is_active}
    form = MemberForm(request.POST or None, company=request.company, editing=membership, initial=initial)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        if membership.is_owner and not d["is_active"]:
            messages.error(request, _("The company owner cannot be deactivated."))
            return redirect("users:user_edit", pk=pk)
        user.full_name, user.phone, user.preferred_language = d["full_name"], d["phone"], d["preferred_language"]
        user.save(update_fields=["full_name", "phone", "preferred_language"])
        membership.is_active = d["is_active"]
        membership.save(update_fields=["is_active"])
        membership.roles.set(d["roles"])
        membership.branches.set(d["branches"])
        AuditLog.record(request.company, request.user, "user.changed", membership,
                        f"{user.email}: {', '.join(r.name_en for r in d['roles'])}; active={d['is_active']}", ip=client_ip(request))
        messages.success(request, _("Saved."))
        return redirect("users:users")
    return render(request, "users/user_form.html", {"form": form, "title": str(user), "membership": membership})


@require_perm("users.edit")
@transaction.atomic
def role_edit(request, pk=None):
    role = get_object_or_404(Role, pk=pk, company=request.company) if pk else None
    limits = {l.doc_type: l.max_amount for l in role.limits.all()} if role else {}
    initial = {f"limit_{k}": v for k, v in limits.items()}
    form = RoleForm(request.POST or None, instance=role, initial=initial)
    selected = request.POST.getlist("perm") if request.method == "POST" else (role.permissions if role else [])
    if request.method == "POST" and form.is_valid():
        role = form.save(commit=False)
        role.company = request.company
        role.permissions = [code for code in selected if code in ALL_CODES]
        role.save()
        for doc_type, _label in DOC_TYPES:
            amount = form.cleaned_data.get(f"limit_{doc_type}")
            if amount is None:
                ApprovalLimit.objects.filter(role=role, doc_type=doc_type).delete()
            else:
                ApprovalLimit.objects.update_or_create(role=role, doc_type=doc_type, defaults={"max_amount": amount})
        AuditLog.record(request.company, request.user, "role.saved", role, f"{role.name_en}: {len(role.permissions)} permissions",
                        {"permissions": role.permissions}, ip=client_ip(request))
        messages.success(request, _("Role saved."))
        return redirect("users:users")
    return render(request, "users/role_form.html", {
        "form": form, "role": role, "rows": matrix_rows(selected), "actions": ACTIONS,
    })
