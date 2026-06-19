from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import permission_required
from django.http import HttpResponse
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from core.context_processors import COOKIE_THEME
from core.context_processors import THEME_VALUES
from core.forms import UserSettingsForm
from core.middleware import LANGUAGE_SESSION_KEY as SESSION_KEY
from core.services import get_site_config
from institution.forms import InstitutionSettingsForm
from institution.models import Institution


@login_required
def home(request):
    """Post-login dashboard: lists the user's enrolled courses (linking into each
    outline) and, for course owners / Platform Admins, a way into management."""
    from courses.models import Course

    enrolled_courses = Course.objects.filter(
        enrollments__student=request.user
    ).order_by("title")
    can_manage_courses = (
        request.user.has_perm("courses.change_course")
        or Course.objects.filter(owner=request.user).exists()
    )
    return render(
        request,
        "core/home.html",
        {
            "enrolled_courses": enrolled_courses,
            "can_manage_courses": can_manage_courses,
        },
    )


def landing(request):
    """Public marketing entry. Authenticated users are bounced to the dashboard."""
    if request.user.is_authenticated:
        return redirect("home")
    from allauth.socialaccount.models import SocialApp

    app = SocialApp.objects.filter(provider="openid_connect").order_by("pk").first()
    sso_enabled = app is not None
    # URL confirmed in Step 4a to equal /accounts/oidc/<provider_id>/login/.
    sso_login_url = (
        reverse("openid_connect_login", kwargs={"provider_id": app.provider_id})
        if app
        else None
    )
    return render(
        request,
        "core/landing.html",
        {
            "sso_enabled": sso_enabled,
            "sso_login_url": sso_login_url,
            "signup_open": get_site_config()["signup_policy"] == "open",
        },
    )


@login_required
def user_settings(request):
    """Edit theme/language/display_name/email; re-sync session language + theme
    cookie; keep allauth's primary EmailAddress in step with User.email."""
    from allauth.socialaccount.models import SocialApp

    # SSO badge context — computed on every render path (GET + invalid-POST re-render).
    # order_by("pk") for determinism if more than one OIDC app exists (matches landing).
    app = SocialApp.objects.filter(provider="openid_connect").order_by("pk").first()
    sso_account = None
    sso_provider_label = None
    if app is not None:
        from allauth.socialaccount.models import SocialAccount

        # SocialAccount.provider stores app.provider_id (falling back to app.provider
        # when provider_id is blank), NOT the literal "openid_connect" — mirror
        # allauth's own SocialApp.sub_id resolution so a blank provider_id still
        # matches.
        effective_provider = app.provider_id or app.provider
        sso_account = SocialAccount.objects.filter(
            user=request.user, provider=effective_provider
        ).first()
        sso_provider_label = app.name or effective_provider

    if request.method == "POST":
        form = UserSettingsForm(request.POST, instance=request.user)
        if form.is_valid():
            from django.db import transaction

            from accounts.emails import reconcile_primary_email

            with transaction.atomic():
                user = form.save()
                if "email" in form.changed_data:
                    reconcile_primary_email(user)
            request.session[SESSION_KEY] = user.language
            messages.success(request, _("Your settings have been saved."))
            response = redirect("core:user_settings")
            response.set_cookie(
                COOKIE_THEME,
                user.theme,
                max_age=31_536_000,  # ~1 year
                path="/",
                samesite="Lax",
                secure=request.is_secure(),
            )
            return response
    else:
        form = UserSettingsForm(instance=request.user)
    return render(
        request,
        "core/user_settings.html",
        {
            "form": form,
            "sso_account": sso_account,
            "sso_provider_label": sso_provider_label,
        },
    )


@require_POST
def set_ui_language(request):
    """Switch UI language (session + User.language if authed); safe-redirect back."""
    lang = request.POST.get("language", "")
    if lang in get_site_config()["enabled_languages"]:
        request.session[SESSION_KEY] = lang
        if request.user.is_authenticated:
            request.user.language = lang
            request.user.save(update_fields=["language"])
    nxt = request.POST.get("next") or request.headers.get("referer", "")
    if not url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        nxt = reverse("home")
    return redirect(nxt)


@login_required
@require_POST
def set_theme(request):
    """Persist User.theme (fetch endpoint: 204 on success, 400 on bad value)."""
    theme = request.POST.get("theme", "")
    if theme not in THEME_VALUES:
        return HttpResponseBadRequest("invalid theme")
    request.user.theme = theme
    request.user.save(update_fields=["theme"])
    return HttpResponse(status=204)


@login_required
@permission_required("institution.change_institution", raise_exception=True)
def institution_settings(request):
    """Platform-Admin-only operational settings. login_required runs first so an
    anonymous request redirects to login; an authed user lacking the perm gets 403."""
    inst = Institution.load()  # bootstrap/admin write path (get_or_create) — OK here
    if request.method == "POST":
        form = InstitutionSettingsForm(request.POST, request.FILES, instance=inst)
        if form.is_valid():
            form.save()  # fires post_save -> invalidate_site_config
            messages.success(request, _("Institution settings saved."))
            return redirect("core:institution_settings")
    else:
        form = InstitutionSettingsForm(instance=inst)
    return render(request, "core/institution_settings.html", {"form": form})
