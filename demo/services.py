"""Demo-kit services. The commands and (later) PR 3's tab both call these, so
every rule lives here rather than in a caller."""

import contextlib
import logging
import random
import secrets

# (no `contextvars` here — the ContextVar lives in notifications/services.py,
#  where notify() can read it; see Step 3b.)
from dataclasses import dataclass
from dataclasses import field
from datetime import timedelta

from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.debug import sensitive_variables

from accounts.emails import ensure_verified_primary_email
from accounts.services import set_user_role
from courses.models import QuizSubmission
from courses.models import UnitProgress

# `is_obligatory_lesson` IS used here — by the up-front "no obligatory lesson"
# check in provision_kit. (It was briefly dropped as unused when that check lived
# only in the generator; restore it, or the check is an F821.)
from courses.rollups import is_obligatory_lesson
from demo import errors
from demo.constants import DEFAULT_DAYS
from demo.constants import DEFAULT_PUPILS
from demo.constants import EMAIL_DOMAIN
from demo.constants import LABEL_MAX
from demo.constants import LONG_LIVED_DAYS
from demo.constants import MAX_DAYS
from demo.constants import MAX_DISAMBIGUATOR
from demo.constants import MAX_PUPILS
from demo.constants import MIN_DAYS
from demo.constants import MIN_PUPILS
from demo.constants import PASSWORD_ALPHABET
from demo.constants import PASSWORD_LENGTH
from demo.constants import SLUG_FALLBACK
from demo.constants import SLUG_MAX
from demo.content import build_course_plan
from demo.generator import frontier_index  # NOT just `generate` — the up-front
from demo.generator import generate  # frontier_part check below calls it
from demo.models import DemoKit
from demo.names import draw_names
from demo.warnings import DemoWarning
from grouping.models import Group
from grouping.services import add_students_to_group
from grouping.services import delete_group
from institution.roles import STUDENT
from institution.roles import TEACHER
from institution.roles import seed_roles

User = get_user_model()

logger = logging.getLogger(__name__)


def require_vendor():
    """Refuse on a box that is not the vendor instance.

    Guards the CREATING half only: provision_kit and extend_kit. purge_kit,
    revoke_kit and list are deliberately EXEMPT (spec R8) — guarding a cleanup
    path is the one way this guard could leave stranger-known logins alive on
    prod, since the flag is an env var a compose change can lose.
    """
    if not settings.VENDOR_INSTANCE:
        raise ImproperlyConfigured(
            "Demo kits can only be provisioned on the vendor instance. Set "
            "LIBLI_VENDOR_INSTANCE=true in .env.production if this box is it."
        )


@dataclass
class ProvisionResult:
    kit: DemoKit
    # repr=False is the MECHANISM behind "never logged": a plain dataclass repr
    # lists every field, and Django's error reporter dumps locals into
    # tracebacks (and into ADMINS mail once SMTP lands).
    teacher_password: str = field(repr=False)
    student_password: str = field(repr=False)
    warnings: list = field(default_factory=list)


def _password():
    return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(PASSWORD_LENGTH))


def _usernames(base, pupils):
    width = len(str(pupils))
    return (
        f"{base}-nauczyciel",
        f"{base}-uczen",
        [f"{base}-p{i + 1:0{width}d}" for i in range(pupils)],
    )


def _taken(names):
    """Exact-match, across User.username, User.email AND allauth's EmailAddress.

    All three tables, because an address lives in two of them and
    ensure_verified_primary_email raises a bare ValueError mid-transaction on a
    verified row bound elsewhere.

    EXACT, not case-insensitive: `__in` is case-sensitive on Postgres, and
    lowercasing the candidates does nothing about a stored
    `SP-12-Nauczyciel@demo.invalid`. That is acceptable here because every name
    we generate is already lowercase (slugify + the `-pNN` suffix), so a
    differently-cased squatter is a pre-existing hand-made row, not a kit we
    issued. If that ever stops being true, switch to `__iexact` in a loop or
    `annotate(Lower(...))` — do NOT just lowercase harder on this side.
    """
    lowered = [n.lower() for n in names]
    emails = [f"{n}@{EMAIL_DOMAIN}" for n in lowered]
    return (
        User.objects.filter(username__in=lowered).exists()
        or User.objects.filter(email__in=emails).exists()
        or EmailAddress.objects.filter(email__in=emails).exists()
    )


def _free_base(slug, pupils):
    """The lowest disambiguator making EVERY username in the kit free. A taken
    name bumps the search whoever holds it; it is never adopted."""
    for n in range(1, MAX_DISAMBIGUATOR + 1):
        base = slug if n == 1 else f"{slug}-{n}"
        teacher, student, pupil_names = _usernames(base, pupils)
        if not _taken([teacher, student, *pupil_names]):
            return base
    raise errors.UsernameCollision(
        f"no free username set for {slug!r} within {MAX_DISAMBIGUATOR} tries"
    )


def _make_user(
    username, *, display_name, password=None, role=None, first_name="", last_name=""
):
    """NO `staff` PARAMETER. `set_user_role` below does
    `user.is_staff = role_is_staff(role) or user.is_superuser` and saves
    (accounts/services.py:36-37), so it is the LAST writer of the flag — an
    `is_staff=` passed at creation is overwritten, not honoured. Keeping the
    parameter would be dead weight whose stated rationale is false, and a future
    caller passing `staff=True, role=STUDENT` would be silently demoted.

    The role is therefore the single authority: `role_is_staff(TEACHER)` is True,
    which IS the course-access widening documented above.
    """
    user = User.objects.create_user(
        username=username,
        email=f"{username}@{EMAIL_DOMAIN}",
        password=password,
    )
    user.display_name = display_name
    user.first_name = first_name
    user.last_name = last_name
    user.language = "pl"
    if password is None:
        user.set_unusable_password()
    user.save()
    ensure_verified_primary_email(user, user.email)
    if role is not None:
        set_user_role(user, role)
    return user


@sensitive_variables()
@transaction.atomic
def provision_kit(
    label,
    *,
    course,
    days=DEFAULT_DAYS,
    pupils=DEFAULT_PUPILS,
    frontier_part=None,
    seed=None,
    created_by=None,
):
    require_vendor()

    label = (label or "").strip()
    if not label or len(label) > LABEL_MAX:
        # The CONSTANT, not a literal 200: a hard-coded number in the message is
        # one that lies the day LABEL_MAX changes — the exact failure the
        # constants module's own docstring argues against.
        raise errors.InvalidLabel(
            f"label must be non-blank and at most {LABEL_MAX} characters"
        )
    if not MIN_PUPILS <= pupils <= MAX_PUPILS:
        raise errors.InvalidBounds(
            "pupils", f"pupils must be {MIN_PUPILS}-{MAX_PUPILS}"
        )
    if not MIN_DAYS <= days <= MAX_DAYS:
        raise errors.InvalidBounds("days", f"days must be {MIN_DAYS}-{MAX_DAYS}")

    # Matches seed_demo_course.py:80's precedent. accounts/services.py:34 uses
    # Group.objects.get_or_create(name=role), so on a box where setup_roles never
    # ran, set_user_role would silently create a PERMISSION-LESS "Teacher" group:
    # is_staff and the review queue still work (groups_visible_to reaches the
    # demo Teacher via Group.teachers), so no test here would notice, but any
    # demo surface gated on a courses.*/grouping.* perm would be dead for the rep.
    seed_roles()

    plan = build_course_plan(course)
    if not plan.units:
        raise errors.EmptyCourse(f"{course.slug} has no published unit")
    # frontier_part is validated HERE, alongside days/pupils — not deep inside
    # frontier_index, which generate() only reaches after the kit, the group, the
    # teacher, the student and every pupil have been written. `--frontier-part 99`
    # would otherwise do a full provisioning's worth of work before rolling back,
    # and PR 3's form could not attach the message to a field.
    frontier_index(plan, frontier_part, course)  # raises InvalidFrontierPart

    # The other two whole-course defects, checked HERE for the same reason.
    # generate()'s reach-forward is a no-op when either of these is missing, so
    # the per-pupil EmptyKit loop at the bottom would be the first to notice —
    # after a kit, a group, a teacher, a student, up to 40 pupils and the whole
    # generation pass have been written and are about to roll back. And its
    # message names a PUPIL ("produced no usable activity for sp-12-p01") when
    # the defect is the COURSE.
    if not any(is_obligatory_lesson(u) for u in plan.units):
        raise errors.EmptyCourse(f"{course.slug} has no obligatory published lesson")
    if not plan.answerable_quizzes:
        raise errors.EmptyCourse(
            f"{course.slug} has no quiz the demo can answer "
            f"({len(plan.skipped_quiz_ids)} skipped)"
        )

    slug = slugify(label, allow_unicode=False)[:SLUG_MAX] or SLUG_FALLBACK
    base = _free_base(slug, pupils)
    teacher_name, student_name, pupil_names = _usernames(base, pupils)

    seed = secrets.randbelow(2**31) if seed is None else seed
    kit = DemoKit.objects.create(
        label=label,
        slug=slug,
        course=course,
        course_slug=course.slug,
        seed=seed,
        pupil_count=pupils,
        frontier_part=frontier_part,
        created_by=created_by,
        expires_at=timezone.now() + timedelta(days=days),
    )

    group = Group.objects.create(
        name=f"Klasa demo — {label[:150]} (#{kit.pk})", course=course
    )
    kit.group = group

    teacher_password, student_password = _password(), _password()
    teacher = _make_user(
        teacher_name,
        display_name=f"Nauczyciel demo — {label} (#{kit.pk})"[:150],
        password=teacher_password,
        role=TEACHER,  # role_is_staff(TEACHER) -> is_staff
    )
    group.teachers.add(teacher)
    student = _make_user(
        student_name,
        display_name=f"Uczeń demo — {label} (#{kit.pk})"[:150],
        password=student_password,
        role=STUDENT,
    )
    kit.teacher, kit.student = teacher, student
    kit.save(update_fields=["group", "teacher", "student"])
    kit.users.add(teacher, student)

    rng = random.Random(seed)  # imported at module level; there is no cycle here
    names = draw_names(rng, pupils)
    pupil_users = []
    for username, (first, last) in zip(pupil_names, names, strict=True):
        pupil = _make_user(
            username,
            display_name=f"{first} {last}",
            first_name=first,
            last_name=last,
            role=STUDENT,
        )
        kit.users.add(pupil)
        pupil_users.append(pupil)

    # The SERVICE, never a direct Enrollment.objects.create.
    # ⚠️ R6 ("provisioning is silent") LIVES OR DIES HERE. The chain is:
    #   add_students_to_group -> recompute_enrollment -> (on a NEW Enrollment)
    #   notify_enrolled -> notify() -> Notification.objects.create(...)
    #                                + transaction.on_commit(deliver_..._email)
    # So without suppression this writes one Notification row per pupil and
    # queues one email per pupil to an @demo.invalid address, fired when the
    # outer atomic block commits.
    with suppress_enrolment_notifications():
        add_students_to_group(group, [student, *pupil_users], added_by=teacher)

    warnings, _bands, _depths = generate(
        rng, plan, pupil_users, course=course, frontier_part=frontier_part
    )
    warnings.extend(plan.warnings)
    warnings.extend(_webhook_warnings())

    for pupil in pupil_users:
        has_lesson = (
            UnitProgress.objects.filter(student=pupil, completed=True)
            .filter(unit__unit_type="lesson")
            .exists()
        )
        has_score = (
            QuizSubmission.objects.filter(
                student=pupil, status=QuizSubmission.Status.SUBMITTED
            )
            .exclude(score=None)
            .exists()
        )
        if not (has_lesson and has_score):
            raise errors.EmptyKit(
                f"{course.slug} produced no usable activity for {pupil.username}"
            )

    return ProvisionResult(kit, teacher_password, student_password, warnings)


@contextlib.contextmanager
def suppress_enrolment_notifications():
    """Keep provisioning silent (spec R6) across add_students_to_group.

    A kit enrols 6-41 users in one go. Each NEW Enrollment row makes
    recompute_enrollment call notify_enrolled, which writes a Notification AND
    registers an on_commit email to an @demo.invalid address. Nobody wants 20
    bounce reports per demo, and the rows would show up in the Teacher's own bell
    menu the first time they log in.

    Patching the notifications entry point is deliberate: the alternative —
    creating Enrollment rows directly — would bypass the grouping service, which
    is exactly what the spec's T16 forbids.

    ⚠️ A CONTEXTVAR, NOT A BARE MODULE-ATTRIBUTE SWAP. Rebinding
    `notification_services.notify` for the duration is process-global: PR 3 calls
    provision_kit synchronously from an admin form, and Task 10 Step 6 budgets
    that at up to 60 s — during which EVERY OTHER REQUEST in that worker would
    silently lose its notifications. A ContextVar is per-thread and per-async-task,
    so only the provisioning call is affected, and it cannot leak if an exception
    unwinds between the set and the reset.

    The ContextVar itself lives in `notifications/services.py` (Step 3b), not
    here: `notify()` is what must read it, and notifications must not import from
    demo.
    """
    from notifications.services import muted

    with muted():
        yield


def _webhook_warnings():
    """Warn, never refuse: a refusal would let a data-protection nicety block
    provisioning, and a human-only check is what Risk 5 says stops happening."""
    from integrations.models import WebhookEndpoint

    endpoint = WebhookEndpoint.load()
    if endpoint.enabled and endpoint.url:
        return [DemoWarning("active_webhook_endpoint", None, endpoint.url)]
    return []


@dataclass
class ExtendResult:
    kit: DemoKit
    new_expires_at: object
    long_lived: bool


def _require_open(kit):
    if kit.closed_at is not None:
        raise errors.KitAlreadyClosed(
            f"kit #{kit.pk} was closed on {kit.closed_at:%Y-%m-%d}"
        )


@transaction.atomic
def purge_kit(kit, *, reason):
    """Atomic PER KIT. A partial failure that deleted the users, left the group
    and never set closed_at would be re-purged nightly for ever.

    NOT vendor-guarded (R8). Deliberately tolerant of a half-dismantled kit.
    """
    # Materialise the pks BEFORE deleting: a lazy kit.users.all() shrinks
    # underneath the loop as each deleted user cascades away its through-row,
    # which is how a Teacher gets missed and left live under a closed kit.
    user_ids = list(kit.users.values_list("pk", flat=True))
    User.objects.filter(pk__in=user_ids).delete()
    if kit.group_id is not None:
        group = Group.objects.filter(pk=kit.group_id).first()
        if group is not None:
            delete_group(group)  # the service: it recomputes enrolment after
    kit.group = None
    kit.teacher = None
    kit.student = None
    kit.closed_at = timezone.now()
    kit.closed_reason = reason
    kit.save(
        update_fields=["group", "teacher", "student", "closed_at", "closed_reason"]
    )


def revoke_kit(kit):
    _require_open(kit)
    purge_kit(kit, reason=DemoKit.ClosedReason.REVOKED)


def extend_kit(kit, *, days):
    require_vendor()
    _require_open(kit)
    if not MIN_DAYS <= days <= MAX_DAYS:
        raise errors.InvalidBounds("days", f"days must be {MIN_DAYS}-{MAX_DAYS}")
    base = max(kit.expires_at, timezone.now())
    kit.expires_at = base + timedelta(days=days)
    kit.save(update_fields=["expires_at"])
    long_lived = kit.expires_at - kit.created_at > timedelta(days=LONG_LIVED_DAYS)
    return ExtendResult(kit, kit.expires_at, long_lived)


def purge_expired(*, dry_run=False):
    """`expires_at <= now AND closed_at IS NULL`. The second conjunct is what
    makes purge IDEMPOTENT: without it every historical kit is re-processed
    nightly for ever.

    ⚠️ EVERY KIT IS ATTEMPTED, even after one raises. `purge_kit` being
    @transaction.atomic only guarantees that an ALREADY-PURGED kit stays purged;
    without the try/except below, an exception on the first kit propagates out of
    the loop and every later due kit is never attempted — their logins stay live
    on prod, which is precisely the failure the runbook's cron warning is about.
    Failures are re-raised at the END so the cron run still exits non-zero and
    the operator hears about it.
    """
    due = list(
        DemoKit.objects.filter(expires_at__lte=timezone.now(), closed_at__isnull=True)
    )
    if dry_run:
        return due
    purged, failures = [], []
    for kit in due:
        try:
            purge_kit(kit, reason=DemoKit.ClosedReason.EXPIRED)
        # A broad catch on purpose: one bad kit must not strand the rest. (No
        # `noqa` — `BLE` is not in this repo's ruff `select`, and bugbear does
        # not flag `except Exception`; a suppression here would imply a gate
        # that does not exist.)
        except Exception as exc:
            logger.exception("demo kit #%s failed to purge", kit.pk)
            failures.append((kit.pk, exc))
        else:
            purged.append(kit)
    if failures:
        ids = ", ".join(f"#{pk}" for pk, _ in failures)
        # `errors.PurgeFailed`, NOT a bare `PurgeFailed`. This module imports
        # `from demo import errors` and spells every raise `errors.X`; the bare
        # name is an F821 at the lint gate and a NameError at runtime — which
        # would make test_one_failing_kit_does_not_strand_the_others fail on the
        # CORRECT build, indistinguishable from Step 5's third mutant.
        raise errors.PurgeFailed(
            f"{len(failures)} kit(s) failed to purge: {ids}", purged
        )
    return purged
