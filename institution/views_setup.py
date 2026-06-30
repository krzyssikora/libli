"""Phase 5e — first-run setup wizard. Sequences the existing config surfaces
(Branding / Access / SSO + invites) into a guided stepped flow for a fresh
install. STEPS drives navigation + the progress indicator only; each config step
has its own bespoke form-construction + save wiring (added in later tasks)."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from accounts.forms import SendInvitationForm
from accounts.provisioning import email_domain
from accounts.provisioning import normalized_allowlist
from accounts.services import InvitationError
from accounts.services import create_or_refresh_invitation
from institution.forms import AccessForm
from institution.forms import BrandingForm
from institution.models import Institution

# slug -> label. Order defines the wizard sequence and the progress indicator.
# Labels are lazy so they localize per-request (eager gettext would freeze them).
STEPS = [
    ("welcome", _("Welcome")),
    ("identity", _("Identity")),
    ("access", _("Access")),
    ("team", _("Team")),
    ("sso", _("SSO")),
]
STEP_SLUGS = [slug for slug, _label in STEPS]

# slug -> handler(request). Populated by the per-step tasks (5/6/7).
_HANDLERS = {}


def _step_index(slug):
    return STEP_SLUGS.index(slug)


def _next_slug(slug):
    i = _step_index(slug)
    return STEP_SLUGS[i + 1] if i + 1 < len(STEP_SLUGS) else None


def _prev_slug(slug):
    i = _step_index(slug)
    return STEP_SLUGS[i - 1] if i > 0 else None


def _wizard_context(current_slug, **extra):
    """Frame context: the progress steps, current/total, and prev/next slugs."""
    idx = _step_index(current_slug)
    steps = [
        {
            "slug": slug,
            "label": label,
            "number": i + 1,
            "is_current": slug == current_slug,
            "is_done": i < idx,
        }
        for i, (slug, label) in enumerate(STEPS)
    ]
    ctx = {
        "steps": steps,
        "current_slug": current_slug,
        "step_number": idx + 1,
        "step_total": len(STEPS),
        "prev_slug": _prev_slug(current_slug),
        "next_slug": _next_slug(current_slug),
    }
    ctx.update(extra)
    return ctx


@login_required
@permission_required("institution.change_institution", raise_exception=True)
def setup(request):
    """Welcome step. This is the kwargless `institution:setup` that the home gate
    and the unknown-slug fallback both redirect to."""
    return render(request, "institution/setup/welcome.html", _wizard_context("welcome"))


@login_required
@permission_required("institution.change_institution", raise_exception=True)
def setup_skip(request):
    """'Skip setup for now' — suppress the home gate for THIS session only."""
    request.session["setup_skipped"] = True
    return redirect("home")


@login_required
@permission_required("institution.change_institution", raise_exception=True)
def setup_step(request, step):
    """Dispatch to the per-step handler. Unknown or not-yet-implemented slugs
    (and 'welcome', which is the kwargless route) fall back to the welcome step."""
    handler = _HANDLERS.get(step)
    if handler is None:
        return redirect("institution:setup")
    return handler(request)


def _modelform_step(request, *, slug, form_cls, template):
    """Shared GET/POST handler for the Identity (BrandingForm) and Access
    (AccessForm) steps: GET seeds from the singleton; POST action=next validates
    + saves the real model and advances; action=skip advances without saving;
    a validation error re-renders the same step."""
    inst = Institution.load()
    if request.method == "GET":
        return render(
            request, template, _wizard_context(slug, form=form_cls(instance=inst))
        )
    if request.POST.get("action") == "skip":
        return redirect("institution:setup_step", step=_next_slug(slug))
    form = form_cls(request.POST, request.FILES, instance=inst)
    if form.is_valid():
        form.save()  # fires post_save -> invalidate_site_config
        return redirect("institution:setup_step", step=_next_slug(slug))
    return render(request, template, _wizard_context(slug, form=form))


def _identity_step(request):
    return _modelform_step(
        request,
        slug="identity",
        form_cls=BrandingForm,
        template="institution/setup/identity.html",
    )


def _access_step(request):
    return _modelform_step(
        request,
        slug="access",
        form_cls=AccessForm,
        template="institution/setup/access.html",
    )


_HANDLERS["identity"] = _identity_step
_HANDLERS["access"] = _access_step


def _pending_invitations():
    """Outstanding invites: unaccepted AND unexpired, newest first.

    `status` is a @property (not a DB field), so filter on accepted_at/expires_at
    — the same predicate as Invitation.find_pending.
    """
    from accounts.models import Invitation

    return Invitation.objects.filter(
        accepted_at__isnull=True, expires_at__gt=timezone.now()
    ).order_by("-created_at")


def _team_step(request):
    slug = "team"
    template = "institution/setup/team.html"
    if request.method == "POST" and request.POST.get("action") == "next":
        # Next advances WITHOUT validating/sending — an empty email must not block.
        return redirect("institution:setup_step", step=_next_slug(slug))

    if request.method == "POST":  # action == "invite"
        if not request.user.has_perm("accounts.add_user"):
            raise PermissionDenied
        form = SendInvitationForm(request.POST)
        if form.is_valid():
            try:
                create_or_refresh_invitation(
                    email=form.cleaned_data["email"],
                    role=form.cleaned_data["role"],
                    invited_by=request.user,
                )
                messages.success(request, _("Invitation sent."))
                allowed = normalized_allowlist(Institution.load().allowed_email_domains)
                domain = email_domain(form.cleaned_data["email"])
                if allowed and domain not in allowed:
                    messages.warning(
                        request,
                        _("Note: %(domain)s is not in your allowed email domains.")
                        % {"domain": domain},
                    )
                # PRG: re-render the step (fresh form + refreshed pending list).
                return redirect("institution:setup_step", step="team")
            except InvitationError as exc:
                form.add_error("email", str(exc))
        return render(
            request,
            template,
            _wizard_context(slug, form=form, pending=_pending_invitations()),
        )

    return render(
        request,
        template,
        _wizard_context(
            slug, form=SendInvitationForm(), pending=_pending_invitations()
        ),
    )


_HANDLERS["team"] = _team_step
