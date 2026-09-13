"""Platform-admin settings: Branding / Access / Uploads / SSO / Notifications tabs."""

import time
from datetime import datetime
from importlib import import_module

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import permission_required
from django.contrib.sessions.backends.base import UpdateError
from django.contrib.sites.shortcuts import get_current_site
from django.http import Http404
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.cache import add_never_cache_headers
from django.utils.formats import date_format
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.decorators.debug import sensitive_variables

from accounts.forms import SsoForm
from accounts.sso_config import is_enabled
from accounts.sso_config import load_sso_app
from accounts.sso_config import redirect_uri
from accounts.sso_config import save_sso_config
from courses.models import ContentNode
from demo import errors as demo_errors
from demo.constants import DEFAULT_DAYS
from demo.constants import LONG_LIVED_DAYS
from demo.models import STATUS_DISPLAY
from demo.models import DemoKit
from demo.services import extend_kit
from demo.services import revoke_kit
from demo.warnings import DISPLAY as DEMO_WARNING_DISPLAY
from institution.forms import AccessForm
from institution.forms import BrandingForm
from institution.forms import PricingForm
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

# NOTE for anyone tempted to "simplify" this alias away: this module defines
# `def settings(request)` below (routed as `institution:settings`), so a bare
# `from django.conf import settings` would be bound at import time and then
# REBOUND by that def -- every `settings.VENDOR_INSTANCE` reference here would
# raise `AttributeError: 'function' object has no attribute 'VENDOR_INSTANCE'`.

_BASE_TABS = (
    "branding",
    "access",
    "uploads",
    "sso",
    "notifications",
    "integrations",
    "support",
    "public-pages",
)


def _tabs():
    """Per REQUEST, not at import. A module-level conditional tuple is evaluated
    once, so override_settings(VENDOR_INSTANCE=True) would never reach it and the
    gate would half-work: the tab link renders, ?tab=pricing falls back to
    branding, and the panel never opens. Demo access (PR 3) is vendor-only for the
    same reason Pricing is."""
    vendor_tabs = ("pricing", "demo") if django_settings.VENDOR_INSTANCE else ()
    return _BASE_TABS + vendor_tabs


def _active_tab(request):
    tab = request.GET.get("tab", "branding")
    return tab if tab in _tabs() else "branding"


def _demo_context(active_tab, form, show_all):
    """PR 3 spec §4.1/§4.6. Built ONLY for the Demo tab: the settings view builds
    every panel on each GET, so without this gate every tab would pay for the kit
    list. It never touches pending credentials — the settings view owns those
    (spec §4.4)."""
    if active_tab != "demo":
        return {
            "demo_form": None,
            "demo_kits": None,
            "demo_show_all": False,
            "demo_extend_label": None,
        }
    kits = DemoKit.objects.select_related("teacher")
    if not show_all:
        kits = kits.filter(closed_at__isnull=True)
    kits = list(kits)  # the model's ordering: ("-created_at", "-pk")
    for kit in kits:
        kit.status_label = STATUS_DISPLAY[kit.status_key]
    return {
        "demo_form": form,
        "demo_kits": kits,
        "demo_show_all": show_all,
        "demo_extend_label": ngettext(
            "Extend by %(days)d day", "Extend by %(days)d days", DEFAULT_DAYS
        )
        % {"days": DEFAULT_DAYS},
    }


DEMO_RESULTS_KEY = "demo_kit_results"
# PR 3 spec §4.4: how long an undisplayed entry may still become a card. A
# property of the tab, not of the demo machinery, so it lives here.
DEMO_RESULT_TTL = 15 * 60


def _session_store(request):
    """A SEPARATE store on the request's session row (spec §4.3).

    request.session was loaded when the request began — ~40 s before a create
    finishes. Anything that marks it modified makes SessionMiddleware save that
    whole start-of-request snapshot over keys other tabs wrote meanwhile (a staged
    course import, element_clip, _language). Reading and writing the pending list
    through this store keeps each read-modify-save to milliseconds.

    ⚠️ Read it with .get(), never .load(): SessionBase.load() returns the data
    WITHOUT filling _session_cache (django/contrib/sessions/backends/base.py,
    _get_session), so the next item access loads again — and a row deleted between
    the two loads nulls the key after the `session_key is None` guard has passed.
    """
    engine = import_module(django_settings.SESSION_ENGINE)
    return engine.SessionStore(session_key=request.session.session_key)


def _mirror_demo_results(request, saved):
    """Spec §4.3 step 4. Called immediately before a view returns, and only with
    the list a fresh store actually holds (None when the store's guard stopped or
    its save raised UpdateError — then nothing is mirrored).

    The view never modifies request.session on its own account, but middleware
    may already have: LanguageSeederMiddleware writes _language (core/middleware.py
    :28-36), and get_user cycles the key after a SECRET_KEY fallback rotation. A
    modified request.session is saved whole at the end of the request, so giving it
    the same list is what stops that save undoing the fresh store's write.
    """
    if saved is None or not request.session.modified:
        return
    if saved:
        request.session[DEMO_RESULTS_KEY] = saved
    else:
        request.session.pop(DEMO_RESULTS_KEY, None)


def _is_speculative(request):
    """A prefetch or prerender whose body the operator may never see."""
    purpose = " ".join(
        (request.headers.get("Sec-Purpose", ""), request.headers.get("Purpose", ""))
    )
    return "prefetch" in purpose or "prerender" in purpose


def _attach_warning_lines(cards):
    """Spec §4.4 step 4 / §4.5. The template can neither index DISPLAY by a
    variable nor sort by its declaration order, so the lines are built here, with
    ONE title query over every card's unit ids. No raw `reason` is ever stored or
    shown — it is an English diagnostic — except the webhook's `detail`, a URL."""
    unit_ids = {
        unit_id
        for card in cards
        for summary in card["warnings"].values()
        for unit_id in summary["unit_ids"]
    }
    titles = dict(
        ContentNode.objects.filter(pk__in=unit_ids).values_list("pk", "title")
    )
    webhook = "active_webhook_endpoint"
    order = [webhook, *(kind for kind in DEMO_WARNING_DISPLAY if kind != webhook)]
    for card in cards:
        lines = []
        for kind in order:
            summary = card["warnings"].get(kind)
            if summary is None:
                continue
            lines.append(
                {
                    "text": DEMO_WARNING_DISPLAY[kind],
                    "count": summary["count"],
                    "detail": summary["detail"],
                    "titles": [
                        titles[unit_id]
                        for unit_id in summary["unit_ids"]
                        if unit_id in titles
                    ],
                }
            )
        card["warning_lines"] = lines


@sensitive_variables()
def _pending_demo_results(request):
    """Spec §4.4 steps 1-5. READS ONLY — the discard runs after a successful render,
    so a render exception leaves every entry for the next GET (P20)."""
    fresh = _session_store(request)
    entries = fresh.get(DEMO_RESULTS_KEY) or []
    if fresh.session_key is None or not entries:
        return [], []
    open_ids = set(
        DemoKit.objects.filter(
            pk__in=[entry["kit_id"] for entry in entries], closed_at__isnull=True
        ).values_list("pk", flat=True)
    )
    now = time.time()
    cards, notices = [], []
    for entry in entries:
        if entry["kit_id"] not in open_ids:
            # Whatever its age: a password for deleted users is never shown, and a
            # closed kit is never called revocable.
            notices.append({"kit_id": entry["kit_id"], "kind": "closed"})
        elif now - entry["stored_at"] > DEMO_RESULT_TTL:
            notices.append({"kit_id": entry["kit_id"], "kind": "expired"})
        else:
            cards.append(
                {**entry, "expires_at": datetime.fromisoformat(entry["expires_at"])}
            )
    _attach_warning_lines(cards)
    return cards, notices


@sensitive_variables()
def _discard_shown_results(request, kit_ids):
    """Spec §4.4: remove exactly what this page showed, through a second fresh
    store. An entry a create saved while the page rendered is not in kit_ids, so it
    survives (P18). Returns the list the store now holds, or None when the session
    row is gone or the save raised UpdateError (nothing to mirror then)."""
    fresh = _session_store(request)
    current = fresh.get(DEMO_RESULTS_KEY, [])
    if fresh.session_key is None:
        return None
    remaining = [entry for entry in current if entry["kit_id"] not in kit_ids]
    if remaining == current:
        return remaining  # the store already agrees; the mirror still applies
    if remaining:
        fresh[DEMO_RESULTS_KEY] = remaining
    else:
        fresh.pop(DEMO_RESULTS_KEY, None)
    try:
        fresh.save()
    except UpdateError:
        return None
    return remaining


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
    pricing=None,
    demo_form=None,
    demo_show_all=False,
):
    """Assemble the nine-form context. Any bound (errored) form passed in is used
    as-is; the rest are unbound — the six institution forms seeded from `inst`,
    the SSO form seeded from the service. The SSO sub-context is built on EVERY
    render because settings.html renders all nine panels (inactive ones just
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
        # Gated like the tab itself (_tabs()): the panel div is gated too, so
        # there is no leak on a school box, but building the one form for a tab
        # that cannot exist there still costs a PricingPlan query on every GET.
        "pricing": (
            pricing
            or (PricingForm(instance=inst) if django_settings.VENDOR_INSTANCE else None)
        ),
        **_demo_context(active_tab, demo_form, demo_show_all),
    }


@sensitive_variables()
@login_required
@permission_required("institution.change_institution", raise_exception=True)
def settings(request):
    inst = Institution.load()
    active_tab = _active_tab(request)
    cards, notices, waiting = [], [], False
    # Spec §4.4: pending credentials are taken in exactly one place — here, on a
    # real GET of the Demo tab. Never on HEAD/OPTIONS (this view has no method
    # guard) and never on a speculative load, whose body may never be seen.
    if active_tab == "demo" and request.method == "GET":
        if _is_speculative(request):
            waiting = bool(request.session.get(DEMO_RESULTS_KEY))
        else:
            cards, notices = _pending_demo_results(request)
    ctx = _settings_context(
        request,
        inst,
        active_tab,
        demo_show_all=request.GET.get("all") == "1",
    )
    ctx.update(
        demo_results=cards,
        demo_notices=notices,
        demo_waiting=waiting,
        demo_login_url=(
            request.build_absolute_uri(reverse("account_login")) if cards else None
        ),
    )
    response = render(request, "institution/manage/settings.html", ctx)
    if cards or notices:
        add_never_cache_headers(response)
        shown = {card["kit_id"] for card in cards} | {n["kit_id"] for n in notices}
        _mirror_demo_results(request, _discard_shown_results(request, shown))
    return response


def _index_url(tab):
    return f"{reverse('institution:settings')}?tab={tab}"


def _action(request, form_cls, ctx_key, tab, success_msg):
    # NOT `== "GET"`: every other non-POST method (HEAD, OPTIONS, PUT, DELETE)
    # carries an EMPTY request.POST, and an empty QueryDict makes several of
    # these forms VALID -- `enabled`/checkbox fields fall to False, so the
    # clean() rules that would have objected never fire. The fall-through then
    # reaches form.save() and writes the blanks over the stored row. And
    # CsrfViewMiddleware skips the safe methods, so HEAD and OPTIONS carry no
    # token at all. Same fix as settings_page_overrides (#279); the whole family
    # behaves one way now.
    if request.method != "POST":
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
    if request.method != "POST":
        return redirect(_index_url("notifications"))  # non-POST: see _action
    # Function-local import: keeps notifications out of this module's import graph.
    from notifications.retention import format_purge_result
    from notifications.retention import purge_notifications

    counts = purge_notifications()  # no days ⇒ uses the saved Institution window
    messages.success(request, format_purge_result(counts, dry_run=False))
    return redirect(_index_url("notifications"))


@login_required
@permission_required("institution.change_institution", raise_exception=True)
def settings_sso(request):
    if request.method != "POST":
        return redirect(_index_url("sso"))  # non-POST: see _action
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
    if request.method != "POST":
        return redirect(_index_url("integrations"))  # non-POST: see _action
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
    if request.method != "POST":
        return redirect(_index_url("integrations"))  # non-POST: see _action
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
    # Non-POST guard first, matching settings_integrations: without it the empty
    # QueryDict binds and the settings page re-renders covered in validation
    # errors. `!= "POST"`, not `== "GET"` -- see _action.
    if request.method != "POST":
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
    """One dict per registered slug, in PAGES order (excluding vendor-only slugs
    off the vendor box). Built on the DISPLAY path, because the settings view
    renders every panel on GET, using the module-level `django_settings` alias
    (not a local import — see the note by that import): everything comes from
    get_site_config(), django_settings.VENDOR_INSTANCE, and PublicPage.objects.

    Languages come from get_site_config() (the COALESCED bundle), not from inst:
    _build() coalesces an empty stored list to the default, so reading inst
    directly would render zero language rows on a deployment whose stored list
    is empty while the public pages still resolved ["en", "pl"].
    """
    from core.public_pages import DEMO_NOTICE_SLUGS
    from core.public_pages import PAGES
    from core.public_pages import VENDOR_ONLY_SLUGS
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
        # A school's box 404s /for-schools/, so an editable box for it would be a
        # dead control. This gates the WRITE path too: settings_page_overrides
        # reuses this function as its iteration loop, so a slug missing here is
        # silently not saved AND an existing row is never deleted.
        if slug in VENDOR_ONLY_SLUGS and not django_settings.VENDOR_INSTANCE:
            continue
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
                    # lost the warning. `slug in DEMO_NOTICE_SLUGS`: /for-schools/
                    # deliberately carries no demo notice, so without this it would
                    # be flagged "no demonstration warning" on any box where the
                    # vendor flag AND demo_instance are both on.
                    "missing_demo_notice": bool(
                        demo
                        and value.strip()
                        and slug in DEMO_NOTICE_SLUGS
                        and "{libli:demo_notice}" not in value
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


@login_required
@permission_required("institution.change_institution", raise_exception=True)
def settings_pricing(request):
    if not django_settings.VENDOR_INSTANCE:  # aliased -- `settings` is a VIEW here
        raise Http404
    return _action(request, PricingForm, "pricing", "pricing", _("Pricing saved."))


def _demo_list_url(request):
    """PR 3 spec §4.7: back to the list the operator was looking at. Only the
    literal "1" is honoured, and nothing posted is ever echoed into the URL."""
    url = _index_url("demo")
    return f"{url}&all=1" if request.POST.get("all") == "1" else url


def _demo_kit_or_404(kit_id):
    kit = DemoKit.objects.filter(pk=kit_id).first()
    if kit is None:
        raise Http404
    return kit


@login_required
@permission_required("institution.change_institution", raise_exception=True)
def settings_demo_extend(request, kit_id):
    if not django_settings.VENDOR_INSTANCE:  # aliased -- `settings` is a VIEW here
        raise Http404
    if request.method != "POST":
        return redirect(_index_url("demo"))  # non-POST: see _action
    kit = _demo_kit_or_404(kit_id)
    try:
        # ⚠️ Accepted race (spec §4.7): if the nightly purge closes a pending-purge
        # kit between the lookup above and this call, _require_open checks the
        # stale row and the new expiry lands on a closed kit. Locking belongs in
        # extend_kit, not here.
        result = extend_kit(kit, days=DEFAULT_DAYS)
    except demo_errors.KitAlreadyClosed:
        messages.error(request, _("Kit #%(id)s is already closed.") % {"id": kit.pk})
    else:
        messages.success(
            request,
            _("Kit #%(id)s now expires on %(date)s.")
            % {
                "id": kit.pk,
                "date": date_format(timezone.localtime(result.new_expires_at)),
            },
        )
        if result.long_lived:
            # Worded to the computation: long_lived is the kit's LIFESPAN up to the
            # new expiry (demo/services.py extend_kit), not its age.
            messages.warning(
                request,
                ngettext(
                    "After this extension the kit will have been open for more "
                    "than %(days)d day.",
                    "After this extension the kit will have been open for more "
                    "than %(days)d days.",
                    LONG_LIVED_DAYS,
                )
                % {"days": LONG_LIVED_DAYS},
            )
    return redirect(_demo_list_url(request))


@login_required
@permission_required("institution.change_institution", raise_exception=True)
def settings_demo_revoke(request, kit_id):
    # The tab is vendor-only like the rest of it. Parent R8's exemption for revoke
    # lives in the service and in `demo_access revoke`, which stay unguarded.
    if not django_settings.VENDOR_INSTANCE:  # aliased -- `settings` is a VIEW here
        raise Http404
    if request.method != "POST":
        return redirect(_index_url("demo"))  # non-POST: see _action
    kit = _demo_kit_or_404(kit_id)
    try:
        revoke_kit(kit)
    except demo_errors.KitAlreadyClosed:
        # A stale page. Two truly simultaneous revokes both pass _require_open and
        # both purge; the second only rewrites closed_at. Harmless, not guarded.
        messages.error(request, _("Kit #%(id)s is already closed.") % {"id": kit.pk})
    else:
        messages.success(
            request, _("Kit #%(id)s revoked; its logins were deleted.") % {"id": kit.pk}
        )
    return redirect(_demo_list_url(request))
