"""Phase 5e — first-run setup wizard. Sequences the existing config surfaces
(Branding / Access / SSO + invites) into a guided stepped flow for a fresh
install. STEPS drives navigation + the progress indicator only; each config step
has its own bespoke form-construction + save wiring (added in later tasks)."""

from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import permission_required
from django.shortcuts import redirect
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _

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
