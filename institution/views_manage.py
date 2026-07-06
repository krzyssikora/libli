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
from integrations.delivery import send_test_event
from integrations.forms import IntegrationsForm
from integrations.models import WebhookDelivery
from integrations.models import WebhookEndpoint

TABS = ("branding", "access", "uploads", "sso", "notifications", "integrations")


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
    integrations=None,
):
    """Assemble the six-form context. Any bound (errored) form passed in is used as-is;
    the rest are unbound — the four institution forms seeded from `inst`, the SSO form
    seeded from the service. The SSO sub-context is built on EVERY render because
    settings.html renders all six panels (inactive ones just hidden).

    The integrations form is likewise built on every render (the panel is always
    included, just hidden) but from a READ-ONLY fetch, not `WebhookEndpoint.load()` —
    `.load()`'s get_or_create would write a row on a plain GET of any other tab.
    `recent_deliveries` IS gated to the integrations tab since it's only rendered
    there."""
    app = load_sso_app()
    site = get_current_site(request)
    endpoint_ro = WebhookEndpoint.objects.filter(pk=1).first() or WebhookEndpoint()
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
        "integrations": integrations or IntegrationsForm(instance=endpoint_ro),
        "webhook_configured": bool(endpoint_ro.url and endpoint_ro.secret),
        "recent_deliveries": (
            WebhookDelivery.objects.all()[:20] if active_tab == "integrations" else []
        ),
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


@login_required
@permission_required("institution.change_institution", raise_exception=True)
def settings_integrations(request):
    if request.method == "GET":
        return redirect(_index_url("integrations"))  # actions are POST targets
    endpoint = WebhookEndpoint.load()
    form = IntegrationsForm(request.POST, instance=endpoint)
    if form.is_valid():
        obj = form.save()
        if obj.url.startswith("http://"):
            messages.warning(
                request,
                _("Endpoint uses http — grades transit in cleartext. Prefer https."),
            )
        messages.success(request, _("Integration settings saved."))
        return redirect(_index_url("integrations"))
    ctx = _settings_context(
        request, Institution.load(), "integrations", integrations=form
    )
    return render(request, "institution/manage/settings.html", ctx)


@login_required
@permission_required("institution.change_institution", raise_exception=True)
def settings_integrations_test(request):
    if request.method == "GET":
        return redirect(_index_url("integrations"))  # actions are POST targets
    endpoint = WebhookEndpoint.load()
    if not (endpoint.url and endpoint.secret):
        messages.error(
            request,
            _("Set an endpoint URL and signing secret before sending a test event."),
        )
        return redirect(_index_url("integrations"))
    ok, status, detail = send_test_event(endpoint)
    if ok:
        messages.success(
            request,
            _("Test event delivered — endpoint returned %(code)s.") % {"code": status},
        )
    else:
        messages.error(request, _("Test event failed: %(reason)s") % {"reason": detail})
    return redirect(_index_url("integrations"))
