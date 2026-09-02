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
from institution.forms import PublicPagesForm
from institution.forms import RetentionForm
from institution.forms import UploadsForm
from institution.models import Institution
from integrations.delivery import send_test_event
from integrations.forms import IntegrationsForm
from integrations.models import WebhookDelivery
from integrations.models import WebhookEndpoint
from support.forms import SupportSettingsForm
from support.models import SupportSettings

TABS = (
    "branding",
    "access",
    "uploads",
    "sso",
    "notifications",
    "integrations",
    "support",
    "public-pages",
)


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
    support=None,
    public_pages=None,
    page_overrides=None,
):
    """Assemble the seven-form context. Any bound (errored) form passed in is used
    as-is; the rest are unbound — the four institution forms seeded from `inst`,
    the SSO form seeded from the service. The SSO sub-context is built on EVERY
    render because settings.html renders all seven panels (inactive ones just
    hidden).

    The integrations form is likewise built on every render (the panel is always
    included, just hidden) but from a READ-ONLY fetch, not `WebhookEndpoint.load()` —
    `.load()`'s get_or_create would write a row on a plain GET of any other tab.
    `recent_deliveries` IS gated to the integrations tab since it's only rendered
    there."""
    app = load_sso_app()
    site = get_current_site(request)
    endpoint_ro = WebhookEndpoint.objects.filter(pk=1).first() or WebhookEndpoint()
    support_row = SupportSettings.objects.filter(pk=1).first() or SupportSettings()
    # Count through the JOIN TABLE, never support_row.extra_reporters.count():
    # before the first save support_row is unsaved, and an M2M access on an
    # unsaved instance raises ValueError — 500ing every settings tab on a fresh
    # install.
    extra_reporter_count = SupportSettings.extra_reporters.through.objects.filter(
        supportsettings_id=1
    ).count()
    # Named, not merely counted: the panel must show WHICH addresses receive
    # reports automatically. Reuses the one resolver so the panel and the mailer
    # can never disagree about who "the Platform Admins" are.
    from support.emails import resolve_pa_recipients

    auto_recipients = resolve_pa_recipients()
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
        "support": support or SupportSettingsForm(instance=support_row),
        "extra_reporter_count": extra_reporter_count,
        "auto_recipients": auto_recipients,
        "page_overrides": (
            page_overrides if page_overrides is not None else _page_overrides()
        ),
        "public_pages": public_pages or PublicPagesForm(instance=inst),
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
    response = _action(
        request, AccessForm, "access", "access", _("Access settings saved.")
    )
    # Advisory only, and deliberately AFTER _action: sso_only with no working IdP
    # is not a lockout (accept_invite ignores the policy, and existing password
    # accounts can still log in), so refusing the save would be wrong. A hard
    # guard is also impossible -- the first-run wizard's Access step runs BEFORE
    # its SSO step, so it would make the policy unselectable where it is offered.
    # Not added to the wizard for that same reason: there it would fire for every
    # school, two steps before they could act on it.
    if Institution.load().signup_policy == "sso_only" and not is_enabled(
        load_sso_app(), get_current_site(request)
    ):
        messages.warning(
            request,
            _(
                "Signup is set to SSO only, but SSO is not enabled — new users "
                "cannot sign in until you configure it on the SSO tab. Existing "
                "accounts and invitations are unaffected."
            ),
        )
    return response


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


@login_required
@permission_required("support.change_supportsettings", raise_exception=True)
def settings_support(request):
    # GET guard first, matching settings_integrations: without it a GET binds an
    # empty QueryDict and re-renders the settings page covered in validation
    # errors.
    if request.method == "GET":
        return redirect(_index_url("support"))
    # Bind to a READ-ONLY instance, not load(). load() is get_or_create, which
    # writes pk=1 before is_valid() is ever called — so an invalid POST would
    # materialise the singleton, and the two rejection tests below (which assert
    # count() == 0) would fail against this very view. SupportSettingsForm holds
    # no M2M, so an unsaved instance is safe here, and save() forces pk=1.
    row = SupportSettings.objects.filter(pk=1).first() or SupportSettings()
    form = SupportSettingsForm(request.POST, instance=row)
    if form.is_valid():
        form.save()
        messages.success(request, _("Support settings saved."))
        return redirect(_index_url("support"))
    return render(
        request,
        "institution/manage/settings.html",
        _settings_context(request, Institution.load(), "support", support=form),
    )


def _page_overrides():
    """One dict per registered slug, in PAGES order. Built on the DISPLAY path,
    because the settings view renders every panel on GET. Takes no argument:
    everything comes from get_site_config() and PublicPage.objects.

    Languages come from get_site_config() (the COALESCED bundle), not from inst:
    _build() coalesces an empty stored list to the default, so reading inst
    directly would render zero language rows on a deployment whose stored list
    is empty while the public pages still resolved ["en", "pl"].
    """
    from core.public_pages import PAGES
    from core.public_pages import normalize_lang
    from core.services import get_site_config
    from institution.models import PublicPage

    config = get_site_config()
    enabled = []
    for code in config["enabled_languages"]:
        code = normalize_lang(code)
        if code not in enabled:
            enabled.append(code)

    rows_by_key = {(r.slug, r.language): r for r in PublicPage.objects.all()}
    demo = config["demo_instance"]
    out = []
    for slug, page in PAGES.items():
        stale = sorted(
            lang for (s, lang) in rows_by_key if s == slug and lang not in enabled
        )
        rows = []
        for lang in enabled + stale:
            row = rows_by_key.get((slug, lang))
            value = row.body_markdown if row else ""
            rows.append(
                {
                    "language": lang,
                    "value": value,
                    "enabled": lang in enabled,
                    # Per-ROW, not per-page: with en and pl overrides where only one
                    # carries the token, a page-level flag cannot say which language
                    # lost the warning.
                    "missing_demo_notice": bool(
                        demo and value.strip() and "{libli:demo_notice}" not in value
                    ),
                }
            )
        filled = [r for r in rows if r["enabled"] and r["value"].strip()]
        out.append(
            {
                "slug": slug,
                "title": page.title,
                "rows": rows,
                "partial": 0 < len(filled) < len(enabled),
                "any_missing_demo_notice": any(r["missing_demo_notice"] for r in rows),
            }
        )
    return out


@login_required
@permission_required("institution.change_institution", raise_exception=True)
def settings_public_pages(request):
    # ctx_key "public_pages" MUST differ from the tab slug "public-pages":
    # _action splats **{ctx_key: form}, and "public-pages" is not a valid Python
    # identifier. This is the first tab where the two diverge.
    return _action(
        request,
        PublicPagesForm,
        "public_pages",
        "public-pages",
        _("Public page settings saved."),
    )


@login_required
@permission_required("institution.change_institution", raise_exception=True)
def settings_page_overrides(request):
    from institution.models import PublicPage

    # NOT `== "GET"`: every other non-POST method (HEAD, OPTIONS, PUT, DELETE)
    # carries an empty request.POST, so falling through would run the
    # delete-when-blank rule over every registered slug x language and wipe the
    # published legal text -- and CsrfViewMiddleware exempts HEAD and OPTIONS,
    # so two of those need no token at all.
    if request.method != "POST":
        return redirect(_index_url("public-pages"))

    # The iteration set is the SAME union the panel builds -- and it is
    # qualified to slugs still in PAGES. Without that qualification, a row for a
    # retired slug (for which the panel rendered no textarea) would read as ""
    # and the delete-when-blank rule would silently destroy live legal text.
    for page in _page_overrides():
        for row in page["rows"]:
            key = f"override-{page['slug']}-{row['language']}"
            # Never parse submitted key names: "getting-started" contains
            # hyphens, so override-getting-started-pl cannot be split safely.
            value = request.POST.get(key, "")
            if value.strip():
                obj, _created = PublicPage.objects.get_or_create(
                    slug=page["slug"], language=row["language"]
                )
                obj.body_markdown = value
                obj.save()
            else:
                PublicPage.objects.filter(
                    slug=page["slug"], language=row["language"]
                ).delete()
    # _action owns messages.success, and this view cannot reuse it -- so it must
    # emit its own, or the one action that publishes live legal text is the only
    # panel that confirms nothing.
    messages.success(request, _("Public page content saved."))
    return redirect(_index_url("public-pages"))
