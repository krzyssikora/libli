"""Platform-admin settings: Branding / Access / Uploads / SSO / Notifications tabs."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import permission_required
from django.contrib.sites.shortcuts import get_current_site
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext as _

from accounts.forms import SsoForm
from accounts.sso_config import is_enabled
from accounts.sso_config import load_sso_app
from accounts.sso_config import redirect_uri
from accounts.sso_config import save_sso_config
from institution.forms import AccessForm
from institution.forms import BrandingForm
from institution.forms import RetentionForm
from institution.forms import UploadsForm
from institution.models import Institution

TABS = ("branding", "access", "uploads", "sso", "notifications")


def _active_tab(request):
    tab = request.GET.get("tab", "branding")
    return tab if tab in TABS else "branding"


def _settings_context(
    request,
    inst,
    active_tab,
    *,
    branding=None,
    access=None,
    uploads=None,
    sso=None,
    notifications=None,
):
    """Assemble the five-form context. Any bound (errored) form passed in is used as-is;
    the rest are unbound — the institution forms seeded from `inst`, the SSO form
    seeded from the service. The SSO sub-context is built on EVERY render because
    settings.html renders all five panels (inactive ones just hidden)."""
    app = load_sso_app()
    site = get_current_site(request)
    return {
        "active_tab": active_tab,
        "branding": branding or BrandingForm(instance=inst),
        "access": access or AccessForm(instance=inst),
        "uploads": uploads or UploadsForm(instance=inst),
        "sso": sso
        or SsoForm(
            app=app,
            initial={
                "enabled": is_enabled(app, site),
                "name": app.name if app else "",
                "server_url": (app.settings or {}).get("server_url", "") if app else "",
                "client_id": app.client_id if app else "",
            },
        ),
        "sso_secret_saved": bool(app and app.secret),
        "sso_redirect_uri": redirect_uri(request, app),
        "notifications": notifications or RetentionForm(instance=inst),
    }


@login_required
@permission_required("institution.change_institution", raise_exception=True)
def settings(request):
    inst = Institution.load()
    ctx = _settings_context(request, inst, _active_tab(request))
    return render(request, "institution/manage/settings.html", ctx)


def _index_url(tab):
    return f"{reverse('institution:settings')}?tab={tab}"


def _action(request, form_cls, ctx_key, tab, success_msg):
    if request.method == "GET":
        return redirect(_index_url(tab))  # method contract: actions are POST targets
    inst = Institution.load()
    form = form_cls(request.POST, request.FILES, instance=inst)
    if form.is_valid():
        form.save()  # fires post_save -> invalidate_site_config
        messages.success(request, success_msg)
        return redirect(_index_url(tab))
    ctx = _settings_context(request, inst, tab, **{ctx_key: form})
    return render(request, "institution/manage/settings.html", ctx)


@login_required
@permission_required("institution.change_institution", raise_exception=True)
def settings_branding(request):
    return _action(request, BrandingForm, "branding", "branding", _("Branding saved."))


@login_required
@permission_required("institution.change_institution", raise_exception=True)
def settings_access(request):
    return _action(request, AccessForm, "access", "access", _("Access settings saved."))


@login_required
@permission_required("institution.change_institution", raise_exception=True)
def settings_uploads(request):
    return _action(
        request, UploadsForm, "uploads", "uploads", _("Upload settings saved.")
    )


@login_required
@permission_required("institution.change_institution", raise_exception=True)
def settings_notifications(request):
    return _action(
        request,
        RetentionForm,
        "notifications",
        "notifications",
        _("Retention settings saved."),
    )


@login_required
@permission_required("institution.change_institution", raise_exception=True)
def settings_notifications_purge(request):
    if request.method == "GET":
        return redirect(_index_url("notifications"))  # actions are POST targets
    # Function-local import: keeps notifications out of this module's import graph.
    from notifications.retention import format_purge_result
    from notifications.retention import purge_notifications

    counts = purge_notifications()  # no days ⇒ uses the saved Institution window
    messages.success(request, format_purge_result(counts, dry_run=False))
    return redirect(_index_url("notifications"))


@login_required
@permission_required("institution.change_institution", raise_exception=True)
def settings_sso(request):
    if request.method == "GET":
        return redirect(_index_url("sso"))  # method contract: actions are POST targets
    form = SsoForm(request.POST, app=load_sso_app())
    if form.is_valid():
        cd = form.cleaned_data
        # Payload MUST come from cleaned_data (rescheme + rstrip live only there).
        saved = save_sso_config(
            name=cd["name"],
            server_url=cd["server_url"],
            client_id=cd["client_id"],
            client_secret=cd["client_secret"],
            enabled=cd["enabled"],
            site=get_current_site(request),
        )
        if saved is not None:
            messages.success(request, _("SSO settings saved."))
        else:
            messages.info(request, _("Nothing to save."))
        return redirect(_index_url("sso"))
    inst = Institution.load()
    return render(
        request,
        "institution/manage/settings.html",
        _settings_context(request, inst, "sso", sso=form),
    )
