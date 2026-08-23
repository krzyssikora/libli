"""Who may report, the cached config bundle, the throttle, and role labelling."""

from django.core.cache import cache
from django.utils import timezone

from institution.roles import COURSE_ADMIN
from institution.roles import PLATFORM_ADMIN
from institution.roles import ROLE_LABELS
from institution.roles import ROLE_NAMES
from institution.roles import TEACHER
from support.constants import SUPPORT_CONFIG_CACHE_KEY
from support.constants import SUPPORT_CONFIG_TTL
from support.constants import THROTTLE_MAX_REPORTS
from support.constants import THROTTLE_WINDOW

# The ladder's semantics, named so the matrix test parametrises off the constant
# instead of restating it. `all` is never consulted at runtime (rule 3
# short-circuits above it) but must exist so the test covers four rungs.
AUDIENCE_GROUPS = {
    "admins": frozenset(),
    "course_admins": frozenset({COURSE_ADMIN}),
    "teachers": frozenset({TEACHER, COURSE_ADMIN}),
    "all": frozenset(ROLE_NAMES),
}

_ALL = "all"


def get_support_config():
    """{"audience": str, "extra_reporter_ids": frozenset[int]}, cached.

    Immediate in the worker that saved; bounded by SUPPORT_CONFIG_TTL elsewhere,
    because the default LocMemCache is per-process — the same property
    core.services.get_site_config has. This bounds REVOCATION latency too.
    """
    bundle = cache.get(SUPPORT_CONFIG_CACHE_KEY)
    if bundle is None:
        bundle = _build_config()
        cache.set(SUPPORT_CONFIG_CACHE_KEY, bundle, SUPPORT_CONFIG_TTL)
    return bundle


def _build_config():
    from support.models import SupportSettings

    row = SupportSettings.objects.filter(pk=1).first()
    if row is None:
        # MUST NOT fall back to an unsaved SupportSettings(): any M2M access on an
        # unsaved instance raises ValueError, and can_report runs from a context
        # processor on every authenticated render — that would 500 the whole site
        # on a fresh install.
        return {
            "audience": SupportSettings.Audience.ADMINS,
            "extra_reporter_ids": frozenset(),
        }
    return {
        "audience": row.audience,
        "extra_reporter_ids": frozenset(
            row.extra_reporters.values_list("id", flat=True)
        ),
    }


def invalidate_support_config(*args, **kwargs):
    """Signal receiver: drop the bundle so the next read rebuilds it."""
    cache.delete(SUPPORT_CONFIG_CACHE_KEY)


def can_report(user, role_names=None):
    """Rules are ordered so 1-3 settle without touching Groups."""
    if user is None or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True
    config = get_support_config()
    if config["audience"] == _ALL:
        return True
    if role_names is None:
        role_names = frozenset(user.groups.values_list("name", flat=True))
    if PLATFORM_ADMIN in role_names:
        return True
    if role_names & AUDIENCE_GROUPS.get(config["audience"], frozenset()):
        return True
    return user.id in config["extra_reporter_ids"]


def throttle_exceeded(user):
    """Rolling window, not a clock hour. Nobody is exempt: the limit is high
    enough not to obstruct honest use, and an exemption is a branch nobody tests."""
    from support.models import IssueReport

    since = timezone.now() - THROTTLE_WINDOW
    count = IssueReport.objects.filter(reporter=user, created_at__gte=since).count()
    return count >= THROTTLE_MAX_REPORTS


def role_snapshot(role_names):
    """Comma-joined Group names in CANONICAL order.

    role_names is a frozenset, and joining a set yields a hash-seed-dependent
    order: the same user would store "Teacher,Course Admin" in one process and the
    reverse in another, making assertions flaky, making the comma-boundary
    truncation drop a different role run to run, and making the triage role column
    unstable between two reports from the same person.
    """
    ordered = [n for n in ROLE_NAMES if n in role_names]
    ordered += sorted(n for n in role_names if n not in ROLE_NAMES)
    return ",".join(ordered)


def role_labels(reporter_roles):
    """Stored Group names -> display labels, falling back to the raw name.

    One home, consumed by the triage templates AND both email templates. Django
    templates cannot index a dict by a variable key, so this cannot live in a
    template. Note accounts/views_manage.py:_role_labels_for DROPS unknown names —
    the opposite of what a historical snapshot needs — so it must not be reused.
    """
    if not reporter_roles:
        return []
    return [
        ROLE_LABELS.get(name, name)
        for name in (part.strip() for part in reporter_roles.split(","))
        if name
    ]
