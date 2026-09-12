# Demo access for schools — core implementation plan (PR 1 + PR 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the `seed_demo_course` production guard, then a `demo` app that provisions a
time-limited demo kit — a Teacher login, a Student login and ~20 fake pupils with believable
activity on `mat-pp` — and purges it on expiry.

**Architecture:** One new Django app, `demo`, holding a `DemoKit` model, a service layer
(`provision_kit` / `purge_kit` / `extend_kit` / `revoke_kit`), a deterministic activity
generator, and a `demo_access` management command. All randomness comes from one
`random.Random(kit.seed)` consumed in a fixed documented order. Every answer is computed and
validated **once per question, kit-wide**, before any pupil is touched.

**Tech Stack:** Django 5, pytest + pytest-django, Postgres. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-12-demo-access-for-schools-design.md` — 344 review
catches applied over 14 rounds. **The plan argues from the spec; read both.** Section
references below (§4.5, R1b, T7…) are spec sections and are where the *why* lives.

## Global Constraints

- **Vendor gate:** `provision_kit` and `extend_kit` refuse when `settings.VENDOR_INSTANCE` is
  False (raise `ImproperlyConfigured`). `purge_kit`, `revoke_kit` and `list` are **exempt on
  purpose** — spec R8. Never "fix" that asymmetry.
- **Determinism (R5):** all *content* randomness from one `random.Random(kit.seed)`, consumed
  in §4.5's fixed order. `secrets` is used for exactly two things: the seed itself and the
  passwords. Bernoulli draws are `rng.random() < p`; list picks are
  `rng.randrange(len(x))` — never `rng.choice`, which consumes differently.
- **Course order** means `courses.rollups.units_in_order(course, drafts="hide")` — the outline
  pre-order. `ContentNode.order` is `for_fields=["course", "parent"]` and is only *locally*
  monotonic; a flat `order_by("order")` is not pre-order.
- **Published only (R2):** the generator writes progress/submissions only for units with
  `published=True`.
- **Top-level questions only (R9):** enumerate
  `unit.elements.filter(parent__isnull=True).order_by("order", "pk")` and keep only those
  whose `content_object` is a `QuestionElement`.
- **Quiz units only (R3):** R3/R1b/the content pass never touch lesson self-checks.
- **No timestamp rewriting:** there is no back-dating (spec Q1, resolved). Rows keep what
  `save()` stamps.
- **Tests:** every test that provisions runs under
  `override_settings(VENDOR_INSTANCE=True)` and passes an **explicit `seed`**.
  `config/settings/test.py:37` pins the flag False.
- ⚠️ **Never pass `-q` to pytest** — `addopts` in `pyproject.toml` already has it, and a
  doubled `-q` suppresses the summary line.
- **Polish copy** in this PR is limited to display names and the checked-in name lists. No new
  msgids beyond the model/field labels and `ClosedReason`.

---

## File Structure

| File | Responsibility |
|---|---|
| `demo/__init__.py`, `demo/apps.py` | app registration (label `demo`, verified free) |
| `demo/constants.py` | every tunable: bounds, defaults, bands, `WRONG_VARIANTS`, password alphabet |
| `demo/errors.py` | the `DemoKitError` hierarchy |
| `demo/models.py` | `DemoKit` + `ClosedReason` + the `status_key` property |
| `demo/migrations/0001_initial.py` | add-table migration |
| `demo/names.py` | the four gendered name lists + the distinct-pair drawer |
| `demo/builders.py` | per-type answer builders, `NO_WRONG_ANSWER`, the registry, `UNANSWERABLE_QUESTION_TYPES`, the de-dup wrapper |
| `demo/content.py` | the kit-wide content pass (spec step 5.5): validate once, cache answers **and fractions**, compute the skip set and the two candidate sets |
| `demo/generator.py` | bands, depths, slices, the writes, the IN_PROGRESS pass |
| `demo/services.py` | `provision_kit`, `purge_kit`, `extend_kit`, `revoke_kit`, `require_vendor`, `ProvisionResult`, `ExtendResult` |
| `demo/warnings.py` | the closed `kind` set + the translated display map |
| `demo/management/commands/demo_access.py` | the operator surface |
| `tests/demo/` | one test module per unit above |

Split by responsibility: `content.py` (what is answerable) and `generator.py` (who did what)
change for different reasons, and `builders.py` is pure data-shaping that the other two
consume.

---

### Task 1: PR 1 — `seed_demo_course` refuses to run in production

The command creates `demo_admin` as a **Platform Admin with the password `demo-pass-123`
hardcoded in this repo**, and `docs/deployment.md` §7 has told the operator to run it on the
live box since the first deployment. Prod was measured clean on 2026-09-12 (spec §5.0), so
this is prevention, not cleanup.

**Files:**
- Modify: `courses/management/commands/seed_demo_course.py` (imports + top of `handle`)
- Modify: `docs/deployment.md:440-448`
- Test: `tests/test_seed_demo_course.py`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing other tasks use.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_seed_demo_course.py`:

```python
@pytest.mark.django_db
def test_seed_demo_course_refuses_when_debug_is_false(settings):
    """It creates a Platform Admin whose password is published in this repo."""
    from django.core.management.base import CommandError

    settings.DEBUG = False
    with pytest.raises(CommandError) as exc:
        call_command("seed_demo_course")
    assert "DEBUG=False" in str(exc.value)
```

- [ ] **Step 2: Run it and watch it fail**

```bash
uv run pytest tests/test_seed_demo_course.py::test_seed_demo_course_refuses_when_debug_is_false -v
```

Expected: FAIL — the command runs happily and seeds the course.

- [ ] **Step 3: Add the guard**

In `courses/management/commands/seed_demo_course.py`, add `from django.conf import settings`
and `from django.core.management.base import CommandError` to the imports, then make the first
statements of `handle()`:

```python
    @transaction.atomic
    def handle(self, *args, **options):
        # This command is a SCREENSHOT FIXTURE, not a demo seeder: it creates
        # demo_admin as a Platform Admin with the password below, which is
        # published in this repository. docs/deployment.md used to tell the
        # operator to run it on the live box; that instruction is gone, and this
        # guard is what makes it stay gone.
        if not settings.DEBUG:
            raise CommandError(
                "seed_demo_course refuses to run with DEBUG=False: it creates a "
                "Platform Admin whose password is hardcoded in this repository. "
                "It is a local screenshot fixture. For a school demo use "
                "`manage.py demo_access create` instead."
            )
```

- [ ] **Step 4: Run the test and the rest of the file**

```bash
uv run pytest tests/test_seed_demo_course.py -v
```

Expected: PASS — the new test passes and the pre-existing ones still do (they run under the
test settings, where `DEBUG` is False by default… **if they now fail, that is the point**: add
`settings.DEBUG = True` to the existing tests' arrange, since they exercise the fixture
deliberately).

- [ ] **Step 5: Fix the runbook**

In `docs/deployment.md`, replace the §7 `seed_demo_course` block (the prose, the fenced
command, and the sentence introducing it) with:

```markdown
`seed_demo_course` is a LOCAL screenshot fixture and refuses to run with `DEBUG=False`.
Do not run it here: it creates a Platform Admin whose password is hardcoded in the
repository. For a school demo, use `manage.py demo_access create` (see the demo-access
spec). Verified 2026-09-12: it has never been run on libli.pl — no `demo_*` users, one
user in total, `mat-pp` the only course, no groups, institution name unchanged, webhook
disabled. Re-verify only if someone runs an older copy of this runbook.
```

- [ ] **Step 6: Commit**

```bash
git add courses/management/commands/seed_demo_course.py docs/deployment.md tests/test_seed_demo_course.py
git commit -m "fix(demo): seed_demo_course refuses to run with DEBUG=False

It creates demo_admin as a Platform Admin with a password hardcoded in
this repo, and the deployment runbook told the operator to run it on the
live box. Prod measured clean 2026-09-12; this is prevention."
```

---

### Task 2: The `demo` app, the `DemoKit` model and its migration

**Files:**
- Create: `demo/__init__.py`, `demo/apps.py`, `demo/models.py`, `demo/constants.py`,
  `demo/errors.py`, `demo/migrations/__init__.py`
- Modify: `config/settings/base.py` (INSTALLED_APPS)
- Test: `tests/demo/__init__.py`, `tests/demo/test_model.py`

**Interfaces:**
- Produces:
  - `demo.models.DemoKit` with fields `label, slug, course, group, teacher, student, users,
    seed, pupil_count, frontier_part, created_at, expires_at, created_by, closed_at,
    closed_reason` and property `status_key -> str`.
  - `demo.models.DemoKit.ClosedReason` (`EXPIRED`, `REVOKED`).
  - `demo.constants` — every name in the block below.
  - `demo.errors.DemoKitError` and its nine subclasses.

- [ ] **Step 1: Write the failing test**

Create `tests/demo/__init__.py` (empty) and `tests/demo/test_model.py`:

```python
import pytest
from django.utils import timezone
from datetime import timedelta


@pytest.mark.django_db
def test_status_key_moves_active_to_pending_to_closed():
    from demo.models import DemoKit
    from tests.factories import make_course

    course = make_course(slug="c1")
    kit = DemoKit.objects.create(
        label="SP 12", slug="sp-12", course=course, seed=1, pupil_count=20,
        expires_at=timezone.now() + timedelta(days=14),
    )
    assert kit.status_key == "active"

    kit.expires_at = timezone.now() - timedelta(days=1)
    assert kit.status_key == "pending_purge"

    kit.closed_at = timezone.now()
    kit.closed_reason = DemoKit.ClosedReason.EXPIRED
    assert kit.status_key == "closed_expired"

    kit.closed_reason = DemoKit.ClosedReason.REVOKED
    assert kit.status_key == "closed_revoked"


@pytest.mark.django_db
def test_slug_is_not_unique_so_a_school_can_get_a_second_kit():
    """A closed kit's row is retained, so a unique slug would block for ever."""
    from demo.models import DemoKit
    from tests.factories import make_course

    course = make_course(slug="c1")
    for _ in range(2):
        DemoKit.objects.create(
            label="SP 12", slug="sp-12", course=course, seed=1, pupil_count=20,
            expires_at=timezone.now() + timedelta(days=14),
        )
    assert DemoKit.objects.filter(slug="sp-12").count() == 2
```

- [ ] **Step 2: Run it and watch it fail**

```bash
uv run pytest tests/demo/test_model.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'demo'`.

- [ ] **Step 3: Create the app package**

`demo/__init__.py` — empty. `demo/migrations/__init__.py` — empty. `demo/apps.py`:

```python
from django.apps import AppConfig


class DemoConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "demo"
```

- [ ] **Step 4: Write the constants**

`demo/constants.py`:

```python
"""Every tunable the demo generator has. Named, not inlined: the spec's
determinism rule (R5) is a claim about an exact draw sequence, and a literal
buried in a loop is a number nobody can change safely."""

import string

# --- operator bounds (spec §4.4). The service enforces these, not just the
# command, so PR 3's form inherits them by calling the service. ---
DEFAULT_DAYS = 14
DEFAULT_PUPILS = 20
MIN_DAYS = 1
MAX_DAYS = 90
# MIN_PUPILS is 5, not 2: the band partition is `pupils * 20 // 100`, which is
# ZERO for 2-4 pupils, making the whole class one band.
MIN_PUPILS = 5
MAX_PUPILS = 40
LABEL_MAX = 200
LONG_LIVED_DAYS = 60  # extend_kit flags a kit alive longer than this

# --- identifiers (spec §4.2) ---
SLUG_MAX = 100  # leaves room for "-NNN-nauczyciel" inside username's 150
SLUG_FALLBACK = "demo"  # a label that slugifies to "" (pure punctuation, CJK)
MAX_DISAMBIGUATOR = 999
EMAIL_DOMAIN = "demo.invalid"

# --- credentials (spec §4.6) ---
PASSWORD_LENGTH = 14
# 56 symbols: letters+digits minus the visually ambiguous ones. ~81 bits.
PASSWORD_ALPHABET = "".join(
    c for c in (string.ascii_letters + string.digits) if c not in "Oo0Il1"
)

# --- the class (spec §4.5) ---
FRONTIER_FRACTION = 0.75
STRONG_PCT = 20
STRUGGLING_PCT = 20
JITTER = 0.08
IN_PROGRESS_PUPILS = 2
P_PARTIAL_GIVEN_WRONG = 0.4
WRONG_VARIANTS = 3
NAME_RETRY_LIMIT = 50
MIN_NAMES_PER_LIST = 40

# band -> (share_pct, p_correct, depth_multiplier, p_lesson, p_optional)
STRONG = "strong"
AVERAGE = "average"
STRUGGLING = "struggling"
BANDS = {
    STRONG: {"p_correct": 0.90, "depth": 1.15, "p_lesson": 1.00, "p_optional": 0.50},
    AVERAGE: {"p_correct": 0.65, "depth": 1.00, "p_lesson": 0.95, "p_optional": 0.30},
    STRUGGLING: {"p_correct": 0.35, "depth": 0.70, "p_lesson": 0.80, "p_optional": 0.15},
}

# Fixed nonsense strings for text-shaped wrong answers. Three, so a question can
# offer three distinct wrong variants (spec §3.1).
WRONG_TEXTS = ("nieprawidlowa-1", "nieprawidlowa-2", "nieprawidlowa-3")
```

- [ ] **Step 5: Write the errors**

`demo/errors.py`:

```python
"""One hierarchy, referenced by all three consumers: the command maps each to a
CommandError, PR 3's form maps InvalidBounds to a FIELD error, and the tests
assert on these classes rather than on ValueError.

The vendor guard's ImproperlyConfigured deliberately sits OUTSIDE this
hierarchy: it signals misconfiguration, not bad input, so a caller catching
DemoKitError does not swallow it."""


class DemoKitError(Exception):
    """Base for every demo-provisioning failure."""


class InvalidLabel(DemoKitError):
    pass


class InvalidBounds(DemoKitError):
    """Carries the offending field so a form can attach the message to it."""

    def __init__(self, field, message):
        self.field = field
        super().__init__(message)


class InvalidFrontierPart(DemoKitError):
    pass


class UsernameCollision(DemoKitError):
    pass


class EmptyCourse(DemoKitError):
    pass


class EmptyKit(DemoKitError):
    pass


class KitNotFound(DemoKitError):
    pass


class KitAlreadyClosed(DemoKitError):
    pass


class NamePoolExhausted(DemoKitError):
    pass
```

- [ ] **Step 6: Write the model**

`demo/models.py`:

```python
from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class DemoKit(models.Model):
    """One school representative's demo access.

    `users` is the authority for purging, so nothing depends on a username
    convention at delete time. The row is RETAINED after purge (closed_at set,
    FKs nulled) as a record of who was given a demo and when; it holds no
    credentials.
    """

    class ClosedReason(models.TextChoices):
        EXPIRED = "expired", _("Expired")
        REVOKED = "revoked", _("Revoked")

    label = models.CharField(max_length=200)
    # NOT unique: a closed kit's row is retained, so a unique slug would
    # permanently block a second demo for the same school. Uniqueness lives on
    # the usernames instead (services._free_disambiguator).
    slug = models.SlugField(max_length=200)
    course = models.ForeignKey("courses.Course", on_delete=models.PROTECT)
    group = models.ForeignKey(
        "grouping.Group", on_delete=models.SET_NULL, null=True, blank=True
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        blank=True, related_name="+",
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        blank=True, related_name="+",
    )
    users = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="demo_kits"
    )
    seed = models.PositiveIntegerField()
    pupil_count = models.PositiveSmallIntegerField()
    frontier_part = models.PositiveSmallIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        blank=True, related_name="+",
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_reason = models.CharField(
        max_length=16, choices=ClosedReason.choices, blank=True
    )

    class Meta:
        # "Newest first" pinned so the command and PR 3's list cannot drift, and
        # so it never resolves to pk order by accident.
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"{self.label} (#{self.pk})"

    @property
    def status_key(self):
        """Machine-readable status. The TRANSLATED label lives in a display map
        used only by PR 3's tab: a lazily translated property would make
        `demo_access list` follow the process locale."""
        if self.closed_at is not None:
            return f"closed_{self.closed_reason or 'expired'}"
        if self.expires_at <= timezone.now():
            return "pending_purge"
        return "active"
```

- [ ] **Step 7: Register the app**

In `config/settings/base.py`, add `"demo",` to `INSTALLED_APPS` after `"support",`.

⚠️ It goes in `base.py`, **not** a vendor-only settings module: a conditionally installed app
makes its migration conditional too. The guard is in the code (Task 3), not the install.

- [ ] **Step 8: Make the migration**

```bash
uv run python manage.py makemigrations demo
```

Expected: creates `demo/migrations/0001_initial.py` with one `CreateModel`. Read the file —
confirm it is add-table only and touches no other app's tables.

- [ ] **Step 9: Run the tests**

```bash
uv run pytest tests/demo/test_model.py -v
```

Expected: PASS (both tests).

- [ ] **Step 10: Check for missing migrations**

```bash
uv run python manage.py makemigrations --check --dry-run
```

Expected: "No changes detected" — CI runs this and fails the build otherwise.

- [ ] **Step 11: Commit**

```bash
git add demo/ config/settings/base.py tests/demo/
git commit -m "feat(demo): add the demo app, DemoKit model and error hierarchy"
```

---

### Task 3: The vendor guard

**Files:**
- Create: `demo/services.py` (first slice — the guard only)
- Test: `tests/demo/test_vendor_guard.py`

**Interfaces:**
- Produces: `demo.services.require_vendor() -> None`, raising
  `django.core.exceptions.ImproperlyConfigured`.

- [ ] **Step 1: Write the failing test**

`tests/demo/test_vendor_guard.py`:

```python
import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings


@override_settings(VENDOR_INSTANCE=False)
def test_require_vendor_refuses_on_a_school_box():
    from demo.services import require_vendor

    with pytest.raises(ImproperlyConfigured) as exc:
        require_vendor()
    assert "LIBLI_VENDOR_INSTANCE" in str(exc.value)


@override_settings(VENDOR_INSTANCE=True)
def test_require_vendor_passes_on_the_vendor_box():
    from demo.services import require_vendor

    require_vendor()  # must not raise
```

- [ ] **Step 2: Run it and watch it fail**

```bash
uv run pytest tests/demo/test_vendor_guard.py -v
```

Expected: FAIL — `ImportError: cannot import name 'require_vendor'`.

- [ ] **Step 3: Write the guard**

`demo/services.py`:

```python
"""Demo-kit services. The commands and (later) PR 3's tab both call these, so
every rule lives here rather than in a caller."""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


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
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/demo/test_vendor_guard.py -v
```

Expected: PASS (both).

- [ ] **Step 5: Commit**

```bash
git add demo/services.py tests/demo/test_vendor_guard.py
git commit -m "feat(demo): vendor guard for the creating half of the services"
```

---

### Task 4: Polish names — gendered lists and the distinct-pair drawer

**Files:**
- Create: `demo/names.py`
- Test: `tests/demo/test_names.py`

**Interfaces:**
- Produces:
  - `demo.names.FEMININE_GIVEN`, `MASCULINE_GIVEN`, `FEMININE_SURNAMES`,
    `MASCULINE_SURNAMES` — tuples of ≥ 40 strings each.
  - `demo.names.draw_names(rng, count) -> list[tuple[str, str]]` — `count` distinct
    `(first_name, last_name)` pairs, gender-consistent, raising
    `demo.errors.NamePoolExhausted`.

- [ ] **Step 1: Write the failing test**

`tests/demo/test_names.py`:

```python
import random

import pytest


def test_lists_meet_the_minimum_length():
    """The assertion is on the LIST LENGTHS, not their product: 40 given names x
    1 surname satisfies a product bound while making the 40th distinct pair a
    1-in-40 draw, so the retry limit would fire during ordinary provisioning."""
    from demo import names
    from demo.constants import MIN_NAMES_PER_LIST

    for lst in (
        names.FEMININE_GIVEN,
        names.MASCULINE_GIVEN,
        names.FEMININE_SURNAMES,
        names.MASCULINE_SURNAMES,
    ):
        assert len(lst) >= MIN_NAMES_PER_LIST
        assert len(set(lst)) == len(lst)


def test_draw_names_returns_distinct_gender_consistent_pairs():
    from demo import names

    drawn = names.draw_names(random.Random(7), 40)
    assert len(drawn) == 40
    assert len(set(drawn)) == 40
    for first, last in drawn:
        if first in names.FEMININE_GIVEN:
            assert last in names.FEMININE_SURNAMES
        else:
            assert first in names.MASCULINE_GIVEN
            assert last in names.MASCULINE_SURNAMES


def test_draw_names_is_deterministic_for_a_seed():
    from demo import names

    assert names.draw_names(random.Random(3), 20) == names.draw_names(
        random.Random(3), 20
    )


def test_draw_names_raises_rather_than_spinning_on_a_short_pool(monkeypatch):
    from demo import errors, names

    monkeypatch.setattr(names, "FEMININE_SURNAMES", ("Kowalska",))
    monkeypatch.setattr(names, "MASCULINE_SURNAMES", ("Kowalski",))
    monkeypatch.setattr(names, "FEMININE_GIVEN", ("Anna",))
    monkeypatch.setattr(names, "MASCULINE_GIVEN", ("Jan",))
    with pytest.raises(errors.NamePoolExhausted):
        names.draw_names(random.Random(1), 10)
```

- [ ] **Step 2: Run it and watch it fail**

```bash
uv run pytest tests/demo/test_names.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'demo.names'`.

- [ ] **Step 3: Write the lists and the drawer**

`demo/names.py`:

```python
"""Polish class-list names for the fake pupils.

GENDERED ON PURPOSE: Polish surnames inflect (Kowalski/Kowalska; Nowak is
invariant), so drawing independently from one flat pair of lists produces
"Anna Kowalski" — obviously fake to any Polish reader, on the screen the spec
calls the demo's best moment. A library or generator is rejected for a
different reason: it would make the determinism test depend on a package
upgrade.
"""

import random  # noqa: F401 - the type of the `rng` argument, for readers

from demo.constants import NAME_RETRY_LIMIT
from demo.errors import NamePoolExhausted

FEMININE_GIVEN = (
    "Anna", "Maria", "Katarzyna", "Małgorzata", "Agnieszka", "Barbara",
    "Ewa", "Krystyna", "Magdalena", "Elżbieta", "Joanna", "Aleksandra",
    "Zofia", "Monika", "Teresa", "Danuta", "Natalia", "Julia",
    "Karolina", "Marta", "Beata", "Halina", "Irena", "Jadwiga",
    "Dorota", "Janina", "Iwona", "Justyna", "Renata", "Sylwia",
    "Paulina", "Emilia", "Weronika", "Klaudia", "Patrycja", "Wiktoria",
    "Oliwia", "Zuzanna", "Amelia", "Lena",
)

MASCULINE_GIVEN = (
    "Jan", "Andrzej", "Piotr", "Krzysztof", "Stanisław", "Tomasz",
    "Paweł", "Marcin", "Michał", "Marek", "Grzegorz", "Jerzy",
    "Tadeusz", "Adam", "Łukasz", "Zbigniew", "Ryszard", "Dariusz",
    "Henryk", "Mariusz", "Kazimierz", "Wojciech", "Robert", "Mateusz",
    "Marian", "Rafał", "Jacek", "Jakub", "Antoni", "Franciszek",
    "Filip", "Szymon", "Wiktor", "Oskar", "Igor", "Alan",
    "Nikodem", "Leon", "Borys", "Fabian",
)

# Paired by index with MASCULINE_SURNAMES: same surname, the form that agrees
# with the given name's gender. Invariant surnames (Nowak, Wójcik, Mazur...)
# repeat unchanged, which is correct Polish.
FEMININE_SURNAMES = (
    "Nowak", "Kowalska", "Wiśniewska", "Wójcik", "Kowalczyk", "Kamińska",
    "Lewandowska", "Zielińska", "Szymańska", "Woźniak", "Dąbrowska",
    "Kozłowska", "Jankowska", "Mazur", "Kwiatkowska", "Krawczyk",
    "Piotrowska", "Grabowska", "Nowakowska", "Pawłowska", "Michalska",
    "Nowicka", "Adamczyk", "Dudek", "Zając", "Wieczorek", "Jabłońska",
    "Król", "Majewska", "Olszewska", "Jaworska", "Wróbel", "Malinowska",
    "Pawlak", "Witkowska", "Walczak", "Stępień", "Górska", "Rutkowska",
    "Michalak",
)

MASCULINE_SURNAMES = (
    "Nowak", "Kowalski", "Wiśniewski", "Wójcik", "Kowalczyk", "Kamiński",
    "Lewandowski", "Zieliński", "Szymański", "Woźniak", "Dąbrowski",
    "Kozłowski", "Jankowski", "Mazur", "Kwiatkowski", "Krawczyk",
    "Piotrowski", "Grabowski", "Nowakowski", "Pawłowski", "Michalski",
    "Nowicki", "Adamczyk", "Dudek", "Zając", "Wieczorek", "Jabłoński",
    "Król", "Majewski", "Olszewski", "Jaworski", "Wróbel", "Malinowski",
    "Pawlak", "Witkowski", "Walczak", "Stępień", "Górski", "Rutkowski",
    "Michalak",
)


def draw_names(rng, count):
    """`count` distinct, gender-consistent (first, last) pairs.

    RNG contract (spec §4.5, order item 1) — per pupil in creation order:
    gender, then given name, then surname; a duplicate pair redraws THE SURNAME
    ONLY, costing exactly one further draw. Methods are pinned (`random()` for
    the Bernoulli, `randrange` for the indexes) because different methods
    consume the Mersenne stream differently and R5 is a claim about the stream.
    """
    if min(
        len(FEMININE_GIVEN), len(MASCULINE_GIVEN),
        len(FEMININE_SURNAMES), len(MASCULINE_SURNAMES),
    ) < count:
        # A runtime check, not only the test above: a service must not depend on
        # a test having run.
        raise NamePoolExhausted(
            f"the name lists are too short to draw {count} distinct pairs"
        )

    seen = set()
    drawn = []
    for _ in range(count):
        feminine = rng.random() < 0.5
        given_pool = FEMININE_GIVEN if feminine else MASCULINE_GIVEN
        surname_pool = FEMININE_SURNAMES if feminine else MASCULINE_SURNAMES
        first = given_pool[rng.randrange(len(given_pool))]
        last = surname_pool[rng.randrange(len(surname_pool))]
        tries = 0
        while (first, last) in seen:
            tries += 1
            if tries > NAME_RETRY_LIMIT:
                raise NamePoolExhausted(
                    "could not draw a distinct name pair within "
                    f"{NAME_RETRY_LIMIT} retries"
                )
            last = surname_pool[rng.randrange(len(surname_pool))]
        seen.add((first, last))
        drawn.append((first, last))
    return drawn
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/demo/test_names.py -v
```

Expected: PASS (four tests).

- [ ] **Step 5: Falsify the distinctness rule**

Temporarily change `draw_names` to skip the `while` loop (accept duplicates) and re-run.

Expected: `test_draw_names_returns_distinct_gender_consistent_pairs` FAILS. **Revert by
hand** — do not `git checkout`, which would take the whole file with it.

- [ ] **Step 6: Commit**

```bash
git add demo/names.py tests/demo/test_names.py
git commit -m "feat(demo): gendered Polish name lists and the distinct-pair drawer"
```

---

### Task 5: The builders registry

Each builder is a **pure function of the question row** and consumes **no RNG draw** — §4.5's
fixed order lists no builder draws, so a builder that took one would silently invalidate the
whole order, and neither determinism test could see it.

⚠️ Verified while writing this plan (read the code, don't trust the prose):
`ShortNumericQuestionElement.mark` is `abs(got - want) <= tol` — the tolerance is **absolute**,
so "band upper bound + 1" is a genuinely wrong answer.
`ChoiceQuestionElement.mark` is `set(answer) == correct_set` with **no** `n > 0` guard, so a
question with **no** correct choice marks an empty pick 1.0 — such a row is *unanswerable*, not
a validation failure.

**Files:**
- Create: `demo/builders.py`
- Test: `tests/demo/test_builders.py`

**Interfaces:**
- Produces:
  - `demo.builders.NO_WRONG_ANSWER` — a module-level sentinel object.
  - `demo.builders.Answers` — `NamedTuple(correct, wrong, partial)` where `wrong` is either a
    non-empty `list` (1..`WRONG_VARIANTS`) **or** the bare sentinel, and `partial` is an answer
    or `None`.
  - `demo.builders.REGISTRY` — `dict[type[QuestionElement], Callable[[obj], Answers | None]]`;
    a builder returns `None` when the row itself is unanswerable.
  - `demo.builders.UNANSWERABLE_QUESTION_TYPES` — `frozenset` of three model classes.
  - `demo.builders.build(question) -> Answers | None` — the wrapper that serialises,
    de-duplicates and caps the variant list.

- [ ] **Step 1: Write the failing test**

`tests/demo/test_builders.py`:

```python
import pytest

from courses.quiz import answer_to_json


def _fixtures():
    """One row of every registry type. Kept here (not in tests/factories.py) so
    the builder contract and its fixtures move together."""
    from decimal import Decimal

    from courses.models import (
        Blank, Choice, ChoiceGridQuestionElement, ChoiceQuestionElement,
        FillBlankQuestionElement, GridColumn, GridRow, MatchPair,
        MatchPairQuestionElement, MultiGridColumn, MultiGridQuestionElement,
        MultiGridRow, QuestionElement, ShortNumericQuestionElement,
        ShortTextQuestionElement,
    )

    made = []

    choice = ChoiceQuestionElement.objects.create(
        stem="Which are prime?", multiple=True,
        marking_mode=QuestionElement.MarkingMode.AUTO, max_marks=Decimal("1"),
    )
    for text, ok in (("2", True), ("3", True), ("4", False), ("6", False)):
        Choice.objects.create(question=choice, text=text, is_correct=ok)
    made.append(choice)

    made.append(ShortNumericQuestionElement.objects.create(
        stem="2+2?", value="4", tolerance="0",
        marking_mode=QuestionElement.MarkingMode.AUTO, max_marks=Decimal("1"),
    ))
    made.append(ShortTextQuestionElement.objects.create(
        stem="Capital of Poland?", accepted="Warszawa\nWarsaw",
        marking_mode=QuestionElement.MarkingMode.AUTO, max_marks=Decimal("1"),
    ))

    fb = FillBlankQuestionElement.objects.create(
        stem="2 + {{2}} = {{4}}",
        marking_mode=QuestionElement.MarkingMode.AUTO, max_marks=Decimal("1"),
    )
    Blank.objects.create(question=fb, accepted="2")
    Blank.objects.create(question=fb, accepted="4")
    made.append(fb)

    mp = MatchPairQuestionElement.objects.create(
        stem="Match", marking_mode=QuestionElement.MarkingMode.AUTO,
        max_marks=Decimal("1"),
    )
    for left, right in (("a", "1"), ("b", "2"), ("c", "3")):
        MatchPair.objects.create(question=mp, left=left, right=right)
    made.append(mp)

    cg = ChoiceGridQuestionElement.objects.create(
        stem="Grid", marking_mode=QuestionElement.MarkingMode.AUTO,
        max_marks=Decimal("1"),
    )
    cols = [GridColumn.objects.create(question=cg, label=lbl) for lbl in ("yes", "no")]
    for label in ("r1", "r2"):
        GridRow.objects.create(question=cg, label=label, correct_column=cols[0])
    made.append(cg)

    mg = MultiGridQuestionElement.objects.create(
        stem="MultiGrid", marking_mode=QuestionElement.MarkingMode.AUTO,
        max_marks=Decimal("1"),
    )
    mcols = [MultiGridColumn.objects.create(question=mg, label=l) for l in ("a", "b", "c")]
    for label in ("r1", "r2"):
        row = MultiGridRow.objects.create(question=mg, label=label)
        row.correct_columns.set(mcols[:2])
    made.append(mg)

    return made


@pytest.mark.django_db
def test_every_registry_type_has_a_fixture_and_an_honest_builder():
    """T1b — the highest-value test here. Without it the derived-score rule is
    tautological: it defines `fraction` as mark()'s own output, so a builder
    returning a WRONG 'correct' answer is invisible."""
    from demo import builders

    by_type = {type(q): q for q in _fixtures()}
    assert set(by_type) == set(builders.REGISTRY), "every registry type needs a fixture"

    for model, question in by_type.items():
        answers = builders.build(question)
        assert answers is not None, model
        assert question.mark(answers.correct).fraction == 1.0, model

        assert answers.wrong is not builders.NO_WRONG_ANSWER, model
        assert 1 <= len(answers.wrong) <= builders.WRONG_VARIANTS, model
        serialised = [answer_to_json(v) for v in answers.wrong]
        assert len(serialised) == len({repr(s) for s in serialised}), model
        for variant in answers.wrong:
            # == 0.0, not < 1.0: the wrong slot must SCORE ZERO, or the
            # wrong-vs-partly-right split means nothing.
            assert question.mark(variant).fraction == 0.0, (model, variant)

        if answers.partial is not None:
            f = question.mark(answers.partial).fraction
            assert 0 < f < 1, (model, f)


@pytest.mark.django_db
def test_every_question_type_is_classified():
    """T6 — derived, never a len(...) == N pin. A new question type fails until
    someone puts it in the registry or in UNANSWERABLE_QUESTION_TYPES."""
    from courses.models import QuestionElement
    from demo import builders

    def concrete_subclasses(cls):
        for sub in cls.__subclasses__():
            if not sub._meta.abstract:
                yield sub
            yield from concrete_subclasses(sub)

    every = set(concrete_subclasses(QuestionElement))
    classified = set(builders.REGISTRY) | set(builders.UNANSWERABLE_QUESTION_TYPES)
    assert every - classified == set(), "unclassified question types"
    assert classified - every == set(), "classified a type that no longer exists"


@pytest.mark.django_db
def test_a_choice_with_no_correct_option_is_unanswerable():
    """mark() is `set(answer) == correct_set` with no n>0 guard, so an empty pick
    would mark 1.0 — the row is excluded here rather than 'failing validation'."""
    from decimal import Decimal

    from courses.models import Choice, ChoiceQuestionElement, QuestionElement
    from demo import builders

    q = ChoiceQuestionElement.objects.create(
        stem="broken", marking_mode=QuestionElement.MarkingMode.AUTO,
        max_marks=Decimal("1"),
    )
    Choice.objects.create(question=q, text="a", is_correct=False)
    assert builders.build(q) is None
```

- [ ] **Step 2: Run it and watch it fail**

```bash
uv run pytest tests/demo/test_builders.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'demo.builders'`.

- [ ] **Step 3: Write the builders**

`demo/builders.py`:

```python
"""Per-type answer builders.

Contract: a builder takes the concrete question object and returns `Answers`,
or None when the ROW is unanswerable (so R3 skips its unit). Builders are PURE
functions of the row and consume NO RNG draw — the fixed draw order in the spec
lists none, so a builder that took one would invalidate it silently.

The wrong slot is a LIST of up to WRONG_VARIANTS deterministic answers, because
PR 5's per-question view renders each pupil's stored answer: one wrong answer
per question shows twenty pupils who all chose option C.
"""

from fractions import Fraction
from typing import NamedTuple

from courses.models import (
    ChoiceGridQuestionElement, ChoiceQuestionElement,
    DragFillBlankQuestionElement, DragToImageQuestionElement,
    ExtendedResponseQuestionElement, FillBlankQuestionElement,
    MatchPairQuestionElement, MultiGridQuestionElement,
    ShortNumericQuestionElement, ShortTextQuestionElement,
)
from courses.models import _accepted_lines
from courses.numeric import parse_numeric_value
from courses.quiz import answer_to_json
from demo.constants import WRONG_TEXTS, WRONG_VARIANTS


class _NoWrongAnswer:
    """Distinct from None, which already means 'no partial' in slot 3."""

    def __repr__(self):
        return "NO_WRONG_ANSWER"


NO_WRONG_ANSWER = _NoWrongAnswer()


class Answers(NamedTuple):
    correct: object
    wrong: object  # list[answer] (non-empty) OR NO_WRONG_ANSWER — never []
    partial: object  # an answer, or None


def _choice(q):
    choices = sorted(q.choices.all(), key=lambda c: (c.order, c.pk))
    correct = {c.pk for c in choices if c.is_correct}
    if not correct:
        return None  # an empty pick would mark 1.0; the row is unanswerable
    wrong = [{c.pk} for c in choices if c.pk not in correct][:WRONG_VARIANTS]
    if not wrong:
        return Answers(correct, NO_WRONG_ANSWER, None)
    # All-or-nothing for both `multiple` values (fraction = 1.0 or 0.0), so
    # there is no partial band to aim at. Permanent, not "unverified".
    return Answers(correct, wrong, None)


def _shortnumeric(q):
    want = parse_numeric_value(q.value)
    if want is None:
        return None  # a hand-edited row: every answer marks 0.0
    tol = parse_numeric_value(q.tolerance) or Fraction(0)
    upper = want + tol  # mark() is abs(got - want) <= tol — ABSOLUTE tolerance
    wrong = [str(upper + n) for n in (1, 2, 3)][:WRONG_VARIANTS]
    return Answers(str(want), wrong, None)


def _shorttext(q):
    lines = _accepted_lines(q.accepted)
    if not lines:
        return None
    wrong = [t for t in WRONG_TEXTS if q.mark(t).fraction == 0.0][:WRONG_VARIANTS]
    if not wrong:
        return Answers(lines[0], NO_WRONG_ANSWER, None)  # a row accepting everything
    return Answers(lines[0], wrong, None)


def _fillblank(q):
    blanks = list(q.blanks.all())
    if not blanks:
        return None
    correct = []
    for blank in blanks:
        lines = _accepted_lines(blank.accepted)
        if not lines:
            return None  # an unfillable blank: no correct answer exists
        correct.append(lines[0])
    # WRONG scores ZERO: every blank spoiled. Spoiling only the first would earn
    # partial credit and collapse the wrong/partial distinction.
    wrong = [[text] * len(blanks) for text in WRONG_TEXTS][:WRONG_VARIANTS]
    partial = None
    if len(blanks) >= 2:
        partial = [WRONG_TEXTS[0]] + correct[1:]
    return Answers(correct, wrong, partial)


def _matchpair(q):
    expected = [p.right for p in q.pairs.all()]
    n = len(expected)
    if n == 0:
        return None
    wrong = []
    for shift in (1, 2, 3):
        if shift % n == 0:
            continue  # the identity
        rotated = expected[shift % n:] + expected[: shift % n]
        # A repeated right-hand token leaves positions matching under rotation,
        # which scores a strict PARTIAL. Keep only rotations that score zero.
        if q.mark(rotated).fraction == 0.0:
            wrong.append(rotated)
    partial = None
    if n >= 3:
        partial = [expected[1], expected[0]] + expected[2:]
    if not wrong:
        return Answers(expected, NO_WRONG_ANSWER, partial)
    return Answers(expected, wrong[:WRONG_VARIANTS], partial)


def _choicegrid(q):
    rows = list(q.rows.all())
    columns = sorted(q.columns.all(), key=lambda c: (c.order, c.pk))
    if not rows or len(columns) < 2:
        return None if not rows else Answers(
            [r.correct_column_id for r in rows], NO_WRONG_ANSWER, None
        )
    correct = [r.correct_column_id for r in rows]
    wrong = []
    for nth in range(WRONG_VARIANTS):
        variant = []
        for row in rows:
            others = [c.pk for c in columns if c.pk != row.correct_column_id]
            variant.append(others[min(nth, len(others) - 1)])
        wrong.append(variant)
    partial = None
    if len(rows) >= 2:
        first_others = [c.pk for c in columns if c.pk != rows[0].correct_column_id]
        partial = [first_others[0]] + correct[1:]
    return Answers(correct, wrong, partial)


def _multigrid(q):
    rows = list(q.rows.all())
    columns = sorted(q.columns.all(), key=lambda c: (c.order, c.pk))
    if not rows or len(columns) < 2:
        return None
    correct = [sorted(c.pk for c in r.correct_columns.all()) for r in rows]
    if any(not sets for sets in correct):
        return None
    wrong = []
    for nth in range(WRONG_VARIANTS):
        variant = []
        for row_correct in correct:
            others = [c.pk for c in columns if c.pk not in row_correct]
            if not others:
                return Answers(correct, NO_WRONG_ANSWER, None)
            variant.append([others[min(nth, len(others) - 1)]])
        wrong.append(variant)
    partial = None
    if len(rows) >= 2 and len(correct[0]) >= 1:
        partial = [correct[0][1:]] + correct[1:]
        if not correct[0][1:]:
            others = [c.pk for c in columns if c.pk not in correct[0]]
            partial = [[others[0]]] + correct[1:] if others else None
    return Answers(correct, wrong, partial)


REGISTRY = {
    ChoiceQuestionElement: _choice,
    ShortNumericQuestionElement: _shortnumeric,
    ShortTextQuestionElement: _shorttext,
    FillBlankQuestionElement: _fillblank,
    MatchPairQuestionElement: _matchpair,
    ChoiceGridQuestionElement: _choicegrid,
    MultiGridQuestionElement: _multigrid,
}

# Keyed on the model CLASS, never a string, so a key cannot drift from a name.
# extendedresponse cannot be answered meaningfully; the two drag types look easy
# on paper but have never been exercised against a real row and appear in no
# published mat-pp quiz, so the safe default is to skip rather than guess.
UNANSWERABLE_QUESTION_TYPES = frozenset(
    {
        ExtendedResponseQuestionElement,
        DragFillBlankQuestionElement,
        DragToImageQuestionElement,
    }
)


def build(question):
    """Registry lookup + the shared post-processing every builder shares.

    De-duplication lives HERE, not in each builder: builders stay pure functions
    of the row and never touch serialisation, while a duplicate variant would
    consume a pick draw to store an identical answer.
    """
    builder = REGISTRY.get(type(question))
    if builder is None:
        return None
    answers = builder(question)
    if answers is None:
        return None
    if answers.wrong is NO_WRONG_ANSWER:
        # A sentinel forces the partial slot empty: the question is answered
        # correctly and consumes no draw, so a partial beside it would tempt an
        # implementer into the always-two-draws rule.
        return Answers(answers.correct, NO_WRONG_ANSWER, None)
    seen, unique = set(), []
    for variant in answers.wrong:
        key = repr(answer_to_json(variant))
        if key not in seen:
            seen.add(key)
            unique.append(variant)
    if not unique:
        return Answers(answers.correct, NO_WRONG_ANSWER, None)
    return Answers(answers.correct, unique[:WRONG_VARIANTS], answers.partial)
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/demo/test_builders.py -v
```

Expected: PASS (three tests). ⚠️ If `test_every_question_type_is_classified` fails, a question
type was added to the codebase — classify it, do not weaken the test. If an import fails, fix
the import path against `courses/models.py` rather than the test.

- [ ] **Step 5: Falsify T1b**

Swap `_choice`'s correct and wrong slots (`return Answers(wrong[0], [correct], None)`) and
re-run.

Expected: `test_every_registry_type_has_a_fixture_and_an_honest_builder` FAILS on the
`mark(correct).fraction == 1.0` assertion. **Revert by hand.**

- [ ] **Step 6: Commit**

```bash
git add demo/builders.py tests/demo/test_builders.py
git commit -m "feat(demo): per-type answer builders with wrong-answer variants"
```

---

### Task 6: The kit-wide content pass

Computed **once**, before any pupil is touched. Validating per pupil would cost `pupils ×
questions × (1 + k)` `mark()` calls — the 20× multiplier on exactly the path PR 3's request
timeout turns on — and would make "passes R3 for this kit" a per-pupil notion, which the
IN_PROGRESS rule cannot use.

**Files:**
- Create: `demo/warnings.py`, `demo/content.py`
- Test: `tests/demo/test_content.py`

**Interfaces:**
- Produces:
  - `demo.warnings.Warning` — `NamedTuple(kind, unit_id, reason)`; `unit_id` may be `None`.
  - `demo.warnings.KINDS` — the closed `frozenset`; `demo.warnings.DISPLAY` — `dict[kind,
    lazy str]`.
  - `demo.content.QuestionPlan` — `NamedTuple(element_id, answers, fractions, partial_ok)`
    where `fractions` maps `("correct" | index | "partial") -> float`.
  - `demo.content.CoursePlan` — `NamedTuple(units, skipped_quiz_ids, answerable_quizzes,
    in_progress_candidates, questions, warnings)`; `questions` maps `unit_id ->
    list[QuestionPlan]`.
  - `demo.content.build_course_plan(course) -> CoursePlan`.

- [ ] **Step 1: Write the failing test**

`tests/demo/test_content.py`:

```python
import pytest


@pytest.mark.django_db
def test_plan_caches_fractions_and_skips_only_quizzes():
    """R1 needs a fraction per written response and the generator may not call
    mark() in the pupil loop, so the cache holds (answer, fraction) pairs."""
    from demo.content import build_course_plan
    from tests.demo.fixtures import small_course

    course = small_course()
    plan = build_course_plan(course)

    assert plan.units, "published units in pre-order"
    for unit_id, questions in plan.questions.items():
        for q in questions:
            assert q.fractions["correct"] == 1.0
            for i in range(len(q.answers.wrong)):
                assert q.fractions[i] == 0.0


@pytest.mark.django_db
def test_a_lesson_with_an_unanswerable_self_check_is_never_skipped():
    """R3 applies to QUIZ units only. A lesson holding an extendedresponse would
    otherwise drop out of the progress matrix's numerator while the denominator
    still counted it."""
    from demo.content import build_course_plan
    from tests.demo.fixtures import small_course

    course = small_course(lesson_with_unanswerable_selfcheck=True)
    plan = build_course_plan(course)

    lesson_ids = {u.pk for u in plan.units if u.unit_type == "lesson"}
    assert not (lesson_ids & plan.skipped_quiz_ids)


@pytest.mark.django_db
def test_a_quiz_with_no_gradeable_question_gets_no_submission_and_a_warning():
    from demo.content import build_course_plan
    from tests.demo.fixtures import small_course

    course = small_course(quiz_without_questions=True)
    plan = build_course_plan(course)

    assert plan.answerable_quizzes, "the good quizzes survive"
    kinds = {w.kind for w in plan.warnings}
    assert "quiz_skipped" in kinds or "sentinel_answered" in kinds
```

- [ ] **Step 2: Write the shared fixture builder**

`tests/demo/fixtures.py` — the `small` fixture from the spec's inventory. It deliberately
breaks two coincidences: element `order` must disagree with `pk`, and a later part's units are
created first, so `pk` order is not pre-order.

```python
"""Fixture courses for the demo tests. `small` is the default; it carries the
two deliberate coincidence-breakers and a 3-variant question for T28."""

from decimal import Decimal

from courses.models import (
    Choice, ChoiceQuestionElement, ContentNode, Course, Element,
    QuestionElement, ShortNumericQuestionElement, TextElement,
)


def _unit(course, parent, title, unit_type, *, obligatory=True, published=True):
    return ContentNode.objects.create(
        course=course, parent=parent, kind="unit", title=title,
        unit_type=unit_type, obligatory=obligatory, published=published,
    )


def _choice_question(unit, *, correct="2", options=("2", "3", "4", "6")):
    q = ChoiceQuestionElement.objects.create(
        stem="pick", marking_mode=QuestionElement.MarkingMode.AUTO,
        max_marks=Decimal("1"),
    )
    for text in options:
        Choice.objects.create(question=q, text=text, is_correct=(text == correct))
    return Element.objects.create(unit=unit, content_object=q)


def small_course(
    *, lesson_with_unanswerable_selfcheck=False, quiz_without_questions=False
):
    course = Course.objects.create(slug="small", title="Small", language="pl")
    # PART 2 IS CREATED FIRST: pre-order must not coincide with pk order, or the
    # "flat order_by('order')" mutant is invisible.
    part_b = ContentNode.objects.create(
        course=course, kind="part", title="Part B", order=1
    )
    part_a = ContentNode.objects.create(
        course=course, kind="part", title="Part A", order=0
    )
    for i in range(6):
        _unit(course, part_a, f"A lesson {i}", "lesson")
    quiz_a = _unit(course, part_a, "A quiz", "quiz")
    # Three wrong variants (four options, one correct) — T28's question.
    _choice_question(quiz_a)
    _choice_question(quiz_a, correct="3")
    for i in range(6):
        _unit(course, part_b, f"B lesson {i}", "lesson")
    quiz_b = _unit(course, part_b, "B quiz", "quiz")
    q = ShortNumericQuestionElement.objects.create(
        stem="2+2?", value="4", tolerance="0",
        marking_mode=QuestionElement.MarkingMode.AUTO, max_marks=Decimal("1"),
    )
    Element.objects.create(unit=quiz_b, content_object=q)
    prose = Element.objects.create(
        unit=quiz_b, content_object=TextElement.objects.create(body="<p>hi</p>")
    )
    # ELEMENT ORDER MUST DISAGREE WITH PK: reorder after creation.
    prose.order = 0
    prose.save(update_fields=["order"])

    if lesson_with_unanswerable_selfcheck:
        from courses.models import ExtendedResponseQuestionElement

        lesson = ContentNode.objects.filter(
            course=course, unit_type="lesson"
        ).first()
        er = ExtendedResponseQuestionElement.objects.create(
            stem="explain", marking_mode=QuestionElement.MarkingMode.REVIEW,
            max_marks=Decimal("5"),
        )
        Element.objects.create(unit=lesson, content_object=er)

    if quiz_without_questions:
        empty = _unit(course, part_b, "Prose-only quiz", "quiz")
        Element.objects.create(
            unit=empty, content_object=TextElement.objects.create(body="<p>x</p>")
        )

    return course
```

- [ ] **Step 3: Run the tests and watch them fail**

```bash
uv run pytest tests/demo/test_content.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'demo.content'`.

- [ ] **Step 4: Write the warnings module**

`demo/warnings.py`:

```python
"""The single channel for everything the generator has to report.

A closed set of machine keys plus a translated display map, split the way the
DemoKit.status_key property is: the command prints keys, PR 3's tab renders the
map. `unit_id` is optional — two kinds have no unit.
"""

from typing import NamedTuple, Optional

from django.utils.translation import gettext_lazy as _


class Warning(NamedTuple):
    kind: str
    unit_id: Optional[int]
    reason: str


DISPLAY = {
    "quiz_skipped": _("Quiz skipped: it holds a question the demo cannot answer."),
    "question_dropped": _("An unmarked question was left unanswered."),
    "variant_dropped": _("A wrong-answer variant failed validation."),
    "sentinel_answered": _("A question has no usable wrong answer; all pupils answer it correctly."),
    "partial_fallback": _("A partial answer failed validation; the wrong answer is used."),
    "fewer_in_progress_than_target": _("Fewer unfinished quizzes than intended."),
    "no_qualifying_pupil": _("No pupil could be left with an unfinished quiz; the review queue will be empty."),
    "active_webhook_endpoint": _("A webhook endpoint is enabled: demo data will be sent to it."),
}

KINDS = frozenset(DISPLAY)
```

- [ ] **Step 5: Write the content pass**

`demo/content.py`:

```python
"""The kit-wide content pass (spec §4.4 step 5.5).

Runs ONCE per kit, before any pupil is touched: resolve the published-unit list,
validate every top-level question of every published QUIZ, and cache the answers
WITH THEIR FRACTIONS so the pupil loop never calls mark().
"""

from typing import NamedTuple

from courses.models import QuestionElement
from courses.rollups import units_in_order
from demo import builders
from demo.warnings import Warning


class QuestionPlan(NamedTuple):
    element_id: int
    max_marks: object
    answers: object  # builders.Answers
    fractions: dict  # "correct" -> float, int index -> float, "partial" -> float
    gradeable: bool  # not NOT_MARKED
    sentinel: bool


class CoursePlan(NamedTuple):
    units: list
    skipped_quiz_ids: set
    answerable_quizzes: list  # "surviving quiz": answerable AND has a gradeable question
    in_progress_candidates: list  # answerable_quizzes minus units with < 2 answerable
    questions: dict  # unit_id -> [QuestionPlan]
    warnings: list


def _top_level_questions(unit):
    """R9: the set compute_scores and the review gate use. The explicit order_by
    is load-bearing — Element.order is for_fields=["unit"], and an unordered
    queryset lets Postgres return rows in any order, breaking determinism."""
    elements = (
        unit.elements.filter(parent__isnull=True)
        .order_by("order", "pk")
        .prefetch_related("content_object")
    )
    return [e for e in elements if isinstance(e.content_object, QuestionElement)]


def build_course_plan(course):
    units = units_in_order(course, drafts="hide")
    units = [u for u in units if u.published]  # belt and braces over drafts="hide"

    skipped, answerable, candidates, questions, warns = set(), [], [], {}, []

    for unit in units:
        if unit.unit_type != "quiz":
            continue  # R3 is about QUIZZES; lesson self-checks are never touched
        plans, skip_reason, gradeable_n, answerable_n = [], None, 0, 0
        for element in _top_level_questions(unit):
            q = element.content_object
            mode = q.marking_mode
            not_marked = mode == QuestionElement.MarkingMode.NOT_MARKED
            if mode == QuestionElement.MarkingMode.REVIEW:
                skip_reason = "a REVIEW question cannot be answered"
                break
            if type(q) in builders.UNANSWERABLE_QUESTION_TYPES:
                if not_marked:
                    warns.append(Warning("question_dropped", unit.pk, type(q).__name__))
                    continue
                skip_reason = f"{type(q).__name__} has no builder"
                break
            answers = builders.build(q)
            if answers is None:
                if not_marked:
                    warns.append(Warning("question_dropped", unit.pk, "row unanswerable"))
                    continue
                skip_reason = f"{type(q).__name__} row is unanswerable"
                break

            fractions = {"correct": q.mark(answers.correct).fraction}
            sentinel = answers.wrong is builders.NO_WRONG_ANSWER
            surviving = []
            if not sentinel:
                for variant in answers.wrong:
                    f = q.mark(variant).fraction
                    if f == 0.0:
                        fractions[len(surviving)] = f
                        surviving.append(variant)
                    else:
                        warns.append(Warning("variant_dropped", unit.pk, str(f)))
                if not surviving:
                    sentinel = True
            if sentinel:
                warns.append(Warning("sentinel_answered", unit.pk, type(q).__name__))
                answers = builders.Answers(answers.correct, builders.NO_WRONG_ANSWER, None)
            else:
                answers = builders.Answers(answers.correct, surviving, answers.partial)

            if answers.partial is not None:
                pf = q.mark(answers.partial).fraction
                if 0 < pf < 1:
                    fractions["partial"] = pf
                else:
                    warns.append(Warning("partial_fallback", unit.pk, str(pf)))
                    answers = builders.Answers(answers.correct, answers.wrong, None)

            plans.append(
                QuestionPlan(
                    element_id=element.pk, max_marks=q.max_marks, answers=answers,
                    fractions=fractions, gradeable=not not_marked, sentinel=sentinel,
                )
            )
            answerable_n += 1
            gradeable_n += 0 if not_marked else 1

        if skip_reason is not None:
            skipped.add(unit.pk)
            warns.append(Warning("quiz_skipped", unit.pk, skip_reason))
            continue
        questions[unit.pk] = plans
        if gradeable_n:
            answerable.append(unit)
            if answerable_n >= 2:
                candidates.append(unit)

    return CoursePlan(units, skipped, answerable, candidates, questions, warns)
```

- [ ] **Step 6: Run the tests**

```bash
uv run pytest tests/demo/test_content.py -v
```

Expected: PASS (three tests).

- [ ] **Step 7: Falsify the quiz-only scope**

Delete the `if unit.unit_type != "quiz": continue` guard and re-run.

Expected: `test_a_lesson_with_an_unanswerable_self_check_is_never_skipped` FAILS. **Revert by
hand.**

- [ ] **Step 8: Commit**

```bash
git add demo/content.py demo/warnings.py tests/demo/test_content.py tests/demo/fixtures.py
git commit -m "feat(demo): kit-wide content pass — validate once, cache answers and fractions"
```

---

### Task 7: The class shape — bands, depths, slices

Pure functions over the plan from Task 6. No DB writes, so this task is where the arithmetic
gets pinned cheaply.

**Files:**
- Create: `demo/generator.py` (first slice)
- Test: `tests/demo/test_class_shape.py`

**Interfaces:**
- Produces:
  - `demo.generator.assign_bands(rng, pupil_count) -> list[str]` — one band name per pupil, in
    creation order.
  - `demo.generator.frontier_index(plan, frontier_part) -> int`
  - `demo.generator.pupil_depth(rng, band, frontier) -> int` — consumes exactly one draw.

- [ ] **Step 1: Write the failing test**

`tests/demo/test_class_shape.py`:

```python
import random

import pytest

from demo import generator
from demo.constants import AVERAGE, STRONG, STRUGGLING


def test_bands_are_a_fixed_partition_not_a_weighted_draw():
    """A per-pupil weighted draw could legitimately give a 20-pupil class with no
    strugglers, which makes the acceptance criterion non-deterministic."""
    bands = generator.assign_bands(random.Random(1), 20)
    assert len(bands) == 20
    assert bands.count(STRONG) == 4
    assert bands.count(STRUGGLING) == 4
    assert bands.count(AVERAGE) == 12


def test_the_partition_is_integer_arithmetic_off_the_share_constants():
    """floor(0.20 * 15) is at the mercy of binary representation."""
    bands = generator.assign_bands(random.Random(1), 15)
    assert bands.count(STRONG) == 3
    assert bands.count(STRUGGLING) == 3
    assert bands.count(AVERAGE) == 9


def test_every_band_is_populated_at_the_minimum_pupil_count():
    from demo.constants import MIN_PUPILS

    bands = generator.assign_bands(random.Random(1), MIN_PUPILS)
    assert set(bands) == {STRONG, AVERAGE, STRUGGLING}


def test_bands_are_deterministic_for_a_seed():
    assert generator.assign_bands(random.Random(9), 20) == generator.assign_bands(
        random.Random(9), 20
    )


@pytest.mark.parametrize(
    "band,lo,hi", [(STRONG, 70, 90), (AVERAGE, 61, 78), (STRUGGLING, 42, 55)]
)
def test_depth_scales_with_the_band(band, lo, hi):
    """frontier = floor(0.75 * 100) = 75; multipliers 1.15/1.00/0.70 with +/-8%."""
    depths = [generator.pupil_depth(random.Random(s), band, 75) for s in range(50)]
    assert all(lo <= d <= hi for d in depths), (min(depths), max(depths))


def test_depth_is_clamped_into_the_unit_range():
    assert generator.pupil_depth(random.Random(1), STRONG, 0) == 0
```

- [ ] **Step 2: Run it and watch it fail**

```bash
uv run pytest tests/demo/test_class_shape.py -v
```

Expected: FAIL — `ImportError: cannot import name 'assign_bands'`.

- [ ] **Step 3: Write the class shape**

Create `demo/generator.py`:

```python
"""The class: who is in which band, how far each pupil got, and what they did.

DETERMINISM (spec R5). All content randomness comes from one
random.Random(kit.seed), consumed in this fixed order:

  1. per pupil in creation order: gender, given name, surname (+1 per rejected
     duplicate)                                        -- demo.names.draw_names
  2. the band partition and its single shuffle         -- assign_bands
  3. per pupil in order: jitter, then per unit in PRE-ORDER: the lesson
     completion draw, or per question in element order (one draw, or two for a
     partial-capable type, plus one variant pick when the answer came out wrong
     and more than one variant survives); then, as item 3a, that pupil's
     reach-forward rows
  4. the IN_PROGRESS pass

A NOT_MARKED question, a sentinel question, an R3-skipped quiz, an
all-NOT_MARKED quiz and a non-lesson non-quiz unit consume NO draws.
"""

import math

from demo.constants import (
    AVERAGE, BANDS, FRONTIER_FRACTION, JITTER, STRONG, STRONG_PCT,
    STRUGGLING, STRUGGLING_PCT,
)
from demo.errors import InvalidFrontierPart


def assign_bands(rng, pupil_count):
    """A fixed partition, shuffled once, zipped with the pupils in creation order."""
    strong = pupil_count * STRONG_PCT // 100
    struggling = pupil_count * STRUGGLING_PCT // 100
    bands = (
        [STRONG] * strong
        + [STRUGGLING] * struggling
        + [AVERAGE] * (pupil_count - strong - struggling)
    )
    rng.shuffle(bands)
    return bands


def frontier_index(plan, frontier_part=None, course=None):
    """The published-unit index the class is working around.

    `frontier_part` is tested with `is not None`: part 0 is a legal AND falsy
    value, and `if frontier_part:` would silently turn --frontier-part 0 into
    the fraction.
    """
    total = len(plan.units)
    if frontier_part is not None:
        parts = [n for n in course.nodes.filter(parent__isnull=True).order_by("order", "pk")]
        if frontier_part >= len(parts):
            raise InvalidFrontierPart(f"part {frontier_part} does not exist")
        wanted = parts[frontier_part]
        ids = set(wanted._subtree_node_ids())
        positions = [i for i, u in enumerate(plan.units) if u.pk in ids]
        if not positions:
            raise InvalidFrontierPart(
                f"part {frontier_part} contains no published unit"
            )
        return positions[-1]
    return math.floor(FRONTIER_FRACTION * total)


def pupil_depth(rng, band, frontier, unit_count=None):
    """Consumes exactly one draw (the jitter). `round` is Python's banker's
    rounding, NOT int(x + 0.5) — the two disagree at exact halves."""
    jitter = rng.uniform(-JITTER, JITTER)
    depth = round(frontier * BANDS[band]["depth"] * (1 + jitter))
    top = (unit_count - 1) if unit_count else max(depth, 0)
    return max(0, min(depth, top))
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/demo/test_class_shape.py -v
```

Expected: PASS (seven, counting the parametrised three).

- [ ] **Step 5: Falsify the integer arithmetic**

Change `pupil_count * STRONG_PCT // 100` to `int(0.20 * pupil_count)` and re-run.

Expected: `test_the_partition_is_integer_arithmetic_off_the_share_constants` FAILS at 15
pupils (`0.2 * 15` is `3.0000000000000004`, so `int()` gives 3 — **if it passes, try 35**:
the point is that float arithmetic is representation-dependent and the integer form is not).
**Revert by hand.**

- [ ] **Step 6: Commit**

```bash
git add demo/generator.py tests/demo/test_class_shape.py
git commit -m "feat(demo): band partition, frontier and per-pupil depth"
```

---

### Task 8: The writes — progress, submissions and responses

**Files:**
- Modify: `demo/generator.py`
- Test: `tests/demo/test_generator_writes.py`

**Interfaces:**
- Consumes: `demo.content.build_course_plan`, `demo.generator.assign_bands/pupil_depth`.
- Produces: `demo.generator.generate(rng, kit, plan, pupils) -> list[Warning]` — writes every
  pupil's progress and finalized submissions; `pupils` is the list of `User` rows in creation
  order.

- [ ] **Step 1: Write the failing test**

`tests/demo/test_generator_writes.py`:

```python
import random

import pytest


def _run(course, pupil_count=5, seed=11):
    from courses.models import Enrollment
    from demo.content import build_course_plan
    from demo.generator import generate
    from tests.factories import make_verified_user

    pupils = []
    for i in range(pupil_count):
        u = make_verified_user(username=f"p{i}", email=f"p{i}@demo.invalid")
        Enrollment.objects.create(student=u, course=course)
        pupils.append(u)
    plan = build_course_plan(course)
    warnings, _bands, _depths = generate(
        random.Random(seed), None, plan, pupils, course=course
    )
    return pupils, plan, warnings


@pytest.mark.django_db
def test_every_stored_fraction_is_the_mark_of_the_stored_answer():
    """T1 — the derived-score rule. Without to_stored_fraction the comparison is
    Decimal vs float and fails on every partial."""
    from courses.models import QuestionResponse
    from courses.quiz import answer_from_json
    from courses.scoring import to_stored_fraction
    from tests.demo.fixtures import small_course

    course = small_course()
    _run(course)

    responses = QuestionResponse.objects.select_related("element").all()
    assert responses.exists()
    for r in responses:
        question = r.element.content_object
        answer = answer_from_json(r.latest_answer, question)
        assert r.fraction == to_stored_fraction(question.mark(answer).fraction)


@pytest.mark.django_db
def test_progress_mode_and_results_mode_both_populate():
    """T2a and T2b — two independent readers of the matrix."""
    from courses.models import QuizSubmission, UnitProgress
    from tests.demo.fixtures import small_course

    course = small_course()
    _run(course)

    assert UnitProgress.objects.filter(completed=True).exists()
    assert UnitProgress.objects.filter(completed=True, completed_at=None).count() == 0
    submitted = QuizSubmission.objects.filter(status=QuizSubmission.Status.SUBMITTED)
    assert submitted.exists()
    assert submitted.filter(score=None).count() == 0


@pytest.mark.django_db
def test_a_non_kit_student_gains_nothing(settings):
    """T3 / R7 — the generator writes only for the pupils it is handed."""
    from courses.models import Enrollment, QuizSubmission, UnitProgress
    from tests.demo.fixtures import small_course
    from tests.factories import make_verified_user

    course = small_course()
    outsider = make_verified_user(username="real", email="real@example.com")
    Enrollment.objects.create(student=outsider, course=course)

    _run(course)

    assert not UnitProgress.objects.filter(student=outsider).exists()
    assert not QuizSubmission.objects.filter(student=outsider).exists()


@pytest.mark.django_db
def test_a_skipped_quiz_receives_no_submission():
    """T5 — whole-unit skip, never a single question."""
    from courses.models import QuizSubmission
    from tests.demo.fixtures import small_course

    course = small_course(quiz_without_questions=True)
    _pupils, plan, _w = _run(course)

    for unit in plan.units:
        if unit.unit_type == "quiz" and unit.pk not in {
            u.pk for u in plan.answerable_quizzes
        }:
            assert not QuizSubmission.objects.filter(unit=unit).exists()
```

- [ ] **Step 2: Run it and watch it fail**

```bash
uv run pytest tests/demo/test_generator_writes.py -v
```

Expected: FAIL — `ImportError: cannot import name 'generate'`.

- [ ] **Step 3: Write the generator**

Append to `demo/generator.py`:

```python
from django.utils import timezone

from courses.models import QuestionResponse, QuizSubmission, UnitProgress
from courses.quiz import answer_to_json, finalize_submission
from courses.rollups import is_obligatory_lesson
from courses.scoring import earned_marks, to_stored_fraction
from demo.builders import NO_WRONG_ANSWER
from demo.constants import P_PARTIAL_GIVEN_WRONG


def _pick_answer(rng, qplan, p_correct):
    """One question's decision. Returns (answer, fraction).

    Draw accounting, pinned:
      * NOT_MARKED or sentinel  -> zero draws, always the correct answer
      * otherwise               -> one draw (correct?)
      * partial-capable         -> a second draw ALWAYS, even when the first said
                                   correct (then discarded)
      * answered wrong with >1 surviving variant -> one further pick draw
    """
    answers = qplan.answers
    if not qplan.gradeable or qplan.sentinel or answers.wrong is NO_WRONG_ANSWER:
        return answers.correct, qplan.fractions["correct"]

    correct_roll = rng.random() < p_correct
    partial_capable = answers.partial is not None
    partial_roll = rng.random() < P_PARTIAL_GIVEN_WRONG if partial_capable else False

    if correct_roll:
        return answers.correct, qplan.fractions["correct"]
    if partial_capable and partial_roll:
        return answers.partial, qplan.fractions["partial"]
    index = rng.randrange(len(answers.wrong)) if len(answers.wrong) > 1 else 0
    return answers.wrong[index], qplan.fractions[index]


def _complete(student, unit):
    """save()/get_or_create, NEVER bulk_create: UnitProgress.save() is what
    stamps completed_at, and the model declares that invariant for every write
    path."""
    progress, _ = UnitProgress.objects.get_or_create(student=student, unit=unit)
    if not progress.completed:
        progress.completed = True
        progress.save()


def _answer_quiz(rng, student, unit, qplans, p_correct, *, finalize=True, limit=None):
    submission, _ = QuizSubmission.objects.select_for_update().get_or_create(
        student=student, unit=unit,
        defaults={"status": QuizSubmission.Status.IN_PROGRESS},
    )
    if submission.status == QuizSubmission.Status.SUBMITTED:
        return submission
    now = timezone.now()
    rows = []
    for qplan in qplans[: limit if limit is not None else len(qplans)]:
        answer, fraction = _pick_answer(rng, qplan, p_correct)
        stored = to_stored_fraction(fraction)
        rows.append(
            QuestionResponse(
                submission=submission, element_id=qplan.element_id,
                fraction=stored, earned_marks=earned_marks(stored, qplan.max_marks),
                latest_answer=answer_to_json(answer), attempt_count=1,
                last_attempt_at=now, locked=False,
            )
        )
    # QuestionResponse has no save() override (verified), so bulk_create is safe
    # here — and this is the highest-volume write by an order of magnitude.
    QuestionResponse.objects.bulk_create(rows)
    if finalize:
        finalize_submission(unit, submission)
        _complete(student, unit)
    return submission


def generate(rng, kit, plan, pupils, *, course, frontier_part=None):
    """Write every pupil's activity. Returns the warnings it accumulated."""
    warnings = []
    bands = assign_bands(rng, len(pupils))
    frontier = frontier_index(plan, frontier_part, course)
    answerable_ids = {u.pk for u in plan.answerable_quizzes}
    first_lesson = next((u for u in plan.units if is_obligatory_lesson(u)), None)
    first_quiz = plan.answerable_quizzes[0] if plan.answerable_quizzes else None

    depths = []
    for pupil, band in zip(pupils, bands, strict=True):
        cfg = BANDS[band]
        depth = pupil_depth(rng, band, frontier, len(plan.units))
        depths.append(depth)
        did_lesson = did_quiz = False

        for unit in plan.units[: depth + 1]:
            if unit.unit_type == "lesson":
                obligatory = is_obligatory_lesson(unit)
                p = cfg["p_lesson"] if obligatory else cfg["p_optional"]
                if rng.random() < p:
                    _complete(pupil, unit)
                    did_lesson = did_lesson or obligatory
            elif unit.unit_type == "quiz" and unit.pk in answerable_ids:
                _answer_quiz(rng, pupil, unit, plan.questions[unit.pk], cfg["p_correct"])
                did_quiz = True
            # An R3-skipped quiz, or any other unit kind: NO draws at all.

        # Item 3a: the reach-forward. Guarantees the post-generation invariant by
        # CONSTRUCTION rather than by dice — a pupil whose slice holds no
        # obligatory lesson or no surviving quiz reaches the first one in
        # pre-order. The lesson is forced with NO draw.
        if not did_lesson and first_lesson is not None:
            _complete(pupil, first_lesson)
        if not did_quiz and first_quiz is not None:
            _answer_quiz(
                rng, pupil, first_quiz, plan.questions[first_quiz.pk], cfg["p_correct"]
            )

    return warnings, bands, depths
```

⚠️ `generate` returns `(warnings, bands, depths)` — Task 9 consumes `bands` and `depths` for
the IN_PROGRESS selection, Task 10 consumes `warnings`. Every call site in this plan unpacks
all three; keep it that way rather than narrowing the signature.

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/demo/test_generator_writes.py -v
```

Expected: PASS (four tests).

- [ ] **Step 5: Falsify the progress write**

Comment out the `_complete(...)` call inside the lesson branch and re-run.

Expected: `test_progress_mode_and_results_mode_both_populate` FAILS on the `UnitProgress`
assertion while the results half still passes — which is the point of splitting them.
**Revert by hand.**

- [ ] **Step 6: Commit**

```bash
git add demo/generator.py tests/demo/test_generator_writes.py
git commit -m "feat(demo): generate lesson progress and finalized quiz submissions"
```

---

### Task 9: The IN_PROGRESS pass

Two pupils are left with an unfinished quiz so the review queue has entries and "Force submit"
has a target — the demo's fourth requirement.

**Files:**
- Modify: `demo/generator.py`
- Test: `tests/demo/test_in_progress.py`

**Interfaces:**
- Produces: `demo.generator.leave_in_progress(rng, plan, pupils, bands, depths) ->
  list[Warning]` — called by `generate` after every pupil's finalized pass.

- [ ] **Step 1: Write the failing test**

`tests/demo/test_in_progress.py`:

```python
import pytest


@pytest.mark.django_db
def test_the_review_queue_is_non_empty_for_the_kit_teacher():
    """T25 — §1's fourth requirement has no other test. pending_reviews_for
    filters on reviewable_students and quiz_units_in_order, so a submission
    written for the wrong scope leaves the queue silently empty."""
    from courses.models import QuizSubmission, UnitProgress
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    kit = provision_for_test(small_course())
    in_progress = QuizSubmission.objects.filter(
        status=QuizSubmission.Status.IN_PROGRESS
    )
    assert in_progress.exists()

    # R4's negative half: an unfinished quiz carries NO completed progress.
    for submission in in_progress:
        assert not UnitProgress.objects.filter(
            student=submission.student, unit=submission.unit, completed=True
        ).exists()

    # And it is only kit pupils.
    assert set(in_progress.values_list("student_id", flat=True)) <= set(
        kit.users.values_list("pk", flat=True)
    )


@pytest.mark.django_db
def test_a_one_question_quiz_is_never_an_in_progress_target():
    """randint(1, n-1) raises at n == 1, and a prefix must be strictly proper."""
    from courses.models import QuizSubmission
    from demo.content import build_course_plan
    from tests.demo.fixtures import small_course

    course = small_course()
    plan = build_course_plan(course)
    one_question = [
        u for u in plan.units
        if u.unit_type == "quiz" and len(plan.questions.get(u.pk, [])) == 1
    ]
    assert one_question, "the fixture needs a single-question quiz"
    assert not set(one_question) & set(plan.in_progress_candidates)

    from tests.demo.helpers import provision_for_test

    provision_for_test(course)
    for unit in one_question:
        assert not QuizSubmission.objects.filter(
            unit=unit, status=QuizSubmission.Status.IN_PROGRESS
        ).exists()
```

- [ ] **Step 2: Write the provisioning test helper**

`tests/demo/helpers.py` — a thin wrapper so tests do not re-type the override and the seed:

```python
from django.test import override_settings

from demo.constants import DEFAULT_DAYS


def provision_for_test(course, *, label="SP 12", pupils=5, days=DEFAULT_DAYS, seed=4242):
    """Every provisioning test needs VENDOR_INSTANCE on (test settings pin it
    False) and an EXPLICIT seed (the service draws one from secrets otherwise,
    so content assertions would run against a fresh random class each time)."""
    from demo.services import provision_kit

    with override_settings(VENDOR_INSTANCE=True):
        return provision_kit(
            label, course=course, days=days, pupils=pupils, seed=seed
        ).kit
```

- [ ] **Step 3: Run it and watch it fail**

```bash
uv run pytest tests/demo/test_in_progress.py -v
```

Expected: FAIL — `demo.services.provision_kit` does not exist yet (Task 10). That is fine and
expected: write the pass now, and this file goes green at the end of Task 10. Run the
`plan.in_progress_candidates` half first by commenting the provisioning lines if you want a
green step here.

- [ ] **Step 4: Write the pass**

Append to `demo/generator.py`:

```python
from demo.constants import IN_PROGRESS_PUPILS
from demo.warnings import Warning as DemoWarning


def _usable_target(plan, pupil, depth, submitted_unit_ids):
    """The STATIC, draw-free predicate. Selection runs before the pass, so a
    predicate phrased as 'yields a conforming prefix' would force an implementer
    to simulate draws — perturbing a stream nothing pins."""
    for unit in plan.in_progress_candidates:
        position = next(i for i, u in enumerate(plan.units) if u.pk == unit.pk)
        if position <= depth or unit.pk in submitted_unit_ids:
            continue
        qplans = plan.questions[unit.pk]
        n = len(qplans)
        first_gradeable = next(
            (i for i, q in enumerate(qplans) if q.gradeable), None
        )
        # 0-based: a prefix of length L <= n-1 covers indices 0..L-1.
        if first_gradeable is not None and first_gradeable <= n - 2:
            return unit
    return None


def leave_in_progress(rng, plan, pupils, bands, depths):
    """The shallowest pupils WITH A USABLE TARGET get an unfinished quiz.

    Not 'the first two in creation order': the shallowest pupils are exactly the
    ones the reach-forward already gave a finalized submission after their
    depth, so the weaker rule selects pupils with nothing to write. Ties break
    on (depth, creation index) — bands share multipliers and jitter often rounds
    to the same integer.
    """
    from courses.models import QuizSubmission

    warnings = []
    ranked = sorted(range(len(pupils)), key=lambda i: (depths[i], i))
    chosen = []
    for i in ranked:
        submitted = set(
            QuizSubmission.objects.filter(student=pupils[i]).values_list(
                "unit_id", flat=True
            )
        )
        target = _usable_target(plan, pupils[i], depths[i], submitted)
        if target is not None:
            chosen.append((i, target))
        if len(chosen) == IN_PROGRESS_PUPILS:
            break

    for i, unit in chosen:
        qplans = plan.questions[unit.pk]
        n = len(qplans)
        length = rng.randint(1, n - 1)
        # If the drawn prefix holds no gradeable response, EXTEND forward to the
        # first gradeable question, consuming no further draw.
        if not any(q.gradeable for q in qplans[:length]):
            first_gradeable = next(i for i, q in enumerate(qplans) if q.gradeable)
            length = min(first_gradeable + 1, n - 1)
        _answer_quiz(
            rng, pupils[i], unit, qplans, BANDS[bands[i]]["p_correct"],
            finalize=False, limit=length,
        )

    if not chosen:
        warnings.append(
            DemoWarning("no_qualifying_pupil", None, "no pupil had a usable target")
        )
    elif len(chosen) < IN_PROGRESS_PUPILS:
        warnings.append(
            DemoWarning(
                "fewer_in_progress_than_target", None, f"{len(chosen)} of {IN_PROGRESS_PUPILS}"
            )
        )
    return warnings
```

Then call it at the end of `generate`, before the return:

```python
    warnings.extend(leave_in_progress(rng, plan, pupils, bands, depths))
    return warnings, bands, depths
```

- [ ] **Step 5: Commit (tests go green at the end of Task 10)**

```bash
git add demo/generator.py tests/demo/test_in_progress.py tests/demo/helpers.py
git commit -m "feat(demo): leave two pupils with an unfinished quiz for the review queue"
```

---

### Task 10: `provision_kit`

**Files:**
- Modify: `demo/services.py`
- Test: `tests/demo/test_provision.py`

**Interfaces:**
- Produces:
  - `demo.services.ProvisionResult` — dataclass `kit, teacher_password, student_password,
    warnings`, both passwords `field(repr=False)`.
  - `demo.services.provision_kit(label, *, course, days, pupils, frontier_part=None,
    seed=None, created_by=None) -> ProvisionResult`.

- [ ] **Step 1: Write the failing test**

`tests/demo/test_provision.py`:

```python
import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from demo import errors


@pytest.mark.django_db
def test_a_kit_provisions_a_teacher_a_student_and_pupils():
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    kit = provision_for_test(small_course(), pupils=5)

    assert kit.users.count() == 7  # teacher + student + 5 pupils
    assert kit.teacher.is_staff and not kit.student.is_staff
    assert kit.group in kit.teacher.taught_groups.all()
    # Every user is in kit.users the moment it is created: R7 filters the
    # generator's writes by it and purge_kit's deletion set IS it.
    assert kit.teacher in kit.users.all()
    assert kit.student in kit.users.all()


@pytest.mark.django_db
def test_the_reps_student_can_reach_a_quiz_and_shows_a_human_name():
    """T20 — §1's requirement 2 has no other test. A Student that came out staff
    silently gets the read-only previewer instead of a real submission."""
    from courses.access import can_access_course
    from grouping.models import GroupMembership
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    course = small_course()
    kit = provision_for_test(course)

    assert not kit.student.is_staff
    assert GroupMembership.objects.filter(group=kit.group, student=kit.student).exists()
    assert can_access_course(kit.student, course)
    # The analytics templates render display_name|default:username and nothing
    # else, so a pupil without one shows as "sp-12-p01".
    pupil = kit.users.exclude(pk__in=[kit.teacher_id, kit.student_id]).first()
    assert pupil.display_name and " " in pupil.display_name


@pytest.mark.django_db
def test_passwords_authenticate_and_never_persist():
    """T22 — and the repr, since a dataclass repr would leak both into any
    traceback Django's error reporter renders."""
    from django.contrib.auth import authenticate

    from demo.services import provision_kit
    from tests.demo.fixtures import small_course

    course = small_course()
    with override_settings(VENDOR_INSTANCE=True):
        result = provision_kit("SP 12", course=course, days=14, pupils=5, seed=1)

    assert authenticate(
        username=result.kit.teacher.username, password=result.teacher_password
    )
    assert result.teacher_password not in repr(result)
    assert result.student_password not in repr(result)
    for field in ("label", "slug"):
        assert result.teacher_password not in getattr(result.kit, field)


@pytest.mark.django_db
def test_every_pupil_holds_progress_and_a_scored_submission():
    """The post-generation invariant, satisfiable BY CONSTRUCTION (the forced
    first lesson and the reach-forward), not left to the dice."""
    from courses.models import QuizSubmission, UnitProgress
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    kit = provision_for_test(small_course(), pupils=5)
    pupils = kit.users.exclude(pk__in=[kit.teacher_id, kit.student_id])
    for pupil in pupils:
        assert UnitProgress.objects.filter(student=pupil, completed=True).exists()
        assert QuizSubmission.objects.filter(
            student=pupil, status=QuizSubmission.Status.SUBMITTED
        ).exclude(score=None).exists()


@pytest.mark.django_db
def test_bounds_and_preconditions_raise_named_errors():
    """T15b/T22 — enforced in the SERVICE, so PR 3's form inherits them."""
    from courses.models import Course
    from demo.services import provision_kit
    from tests.demo.fixtures import small_course

    course = small_course()
    with override_settings(VENDOR_INSTANCE=True):
        with pytest.raises(errors.InvalidBounds) as exc:
            provision_kit("SP", course=course, days=14, pupils=2, seed=1)
        assert exc.value.field == "pupils"

        with pytest.raises(errors.InvalidBounds):
            provision_kit("SP", course=course, days=0, pupils=5, seed=1)

        with pytest.raises(errors.InvalidLabel):
            provision_kit("   ", course=course, days=14, pupils=5, seed=1)

        empty = Course.objects.create(slug="empty", title="Empty", language="pl")
        with pytest.raises(errors.EmptyCourse):
            provision_kit("SP", course=empty, days=14, pupils=5, seed=1)


@pytest.mark.django_db
def test_a_second_kit_for_the_same_school_gets_distinct_usernames():
    """T17 — a taken name BUMPS the integer; it is never adopted."""
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    course = small_course()
    first = provision_for_test(course, label="SP 12")
    second = provision_for_test(course, label="SP 12")

    assert first.teacher.username != second.teacher.username
    assert first.slug == second.slug  # the SLUG is deliberately not unique


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=False)
def test_provisioning_refuses_on_a_school_box():
    from demo.models import DemoKit
    from demo.services import provision_kit
    from tests.demo.fixtures import small_course

    course = small_course()
    with pytest.raises(ImproperlyConfigured):
        provision_kit("SP", course=course, days=14, pupils=5, seed=1)
    assert DemoKit.objects.count() == 0


@pytest.mark.django_db
def test_provisioning_is_silent():
    """T12 — R6. The fixture carries an ENABLED endpoint, or the webhook half of
    this test is green on a build that fires one per enrolment."""
    from django.core import mail

    from integrations.models import WebhookDelivery, WebhookEndpoint
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    endpoint = WebhookEndpoint.load()
    endpoint.enabled = True
    endpoint.url = "https://sis.example/hook"
    endpoint.save()

    before = WebhookDelivery.objects.count()
    result_kit = provision_for_test(small_course())

    assert mail.outbox == []
    assert WebhookDelivery.objects.count() == before
    # ...and the operator is TOLD the endpoint is live (it is a data-leak
    # surface the moment a rep presses Force submit).
    assert result_kit is not None


@pytest.mark.django_db
def test_wrong_answers_vary_between_pupils():
    """T28 — what PR 5's per-question view will render. Two guards, or the
    assertion is decided by the dice."""
    from courses.models import QuestionResponse
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    kit = provision_for_test(small_course(), pupils=20, seed=99)

    by_element = {}
    for r in QuestionResponse.objects.filter(fraction=0):
        by_element.setdefault(r.element_id, []).append(repr(r.latest_answer))
    multi = [v for v in by_element.values() if len(v) >= 2]
    assert multi, "guard: at least one question must be wrong for >= 2 pupils"
    assert any(len(set(v)) >= 2 for v in multi), (
        "guard: at least two distinct stored wrong answers"
    )
```

- [ ] **Step 2: Run it and watch it fail**

```bash
uv run pytest tests/demo/test_provision.py -v
```

Expected: FAIL — `ImportError: cannot import name 'provision_kit'`.

- [ ] **Step 3: Write `provision_kit`**

Append to `demo/services.py`:

```python
import secrets
from dataclasses import dataclass, field
from datetime import timedelta

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.debug import sensitive_variables

from accounts.emails import ensure_verified_primary_email
from accounts.services import set_user_role
from courses.models import QuizSubmission, UnitProgress
from courses.rollups import is_obligatory_lesson
from demo import errors
from demo.constants import (
    DEFAULT_DAYS, DEFAULT_PUPILS, EMAIL_DOMAIN, LABEL_MAX, MAX_DAYS,
    MAX_DISAMBIGUATOR, MAX_PUPILS, MIN_DAYS, MIN_PUPILS, PASSWORD_ALPHABET,
    PASSWORD_LENGTH, SLUG_FALLBACK, SLUG_MAX,
)
from demo.content import build_course_plan
from demo.generator import generate
from demo.models import DemoKit
from demo.names import draw_names
from demo.warnings import Warning as DemoWarning
from grouping.models import Group
from grouping.services import add_students_to_group
from institution.roles import STUDENT, TEACHER

User = get_user_model()


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
    """Case-insensitive, across User.username, User.email AND allauth's
    EmailAddress — addresses live in both tables, and ensure_verified_primary_email
    raises a bare ValueError mid-transaction on a verified row bound elsewhere."""
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


def _make_user(username, *, display_name, password=None, staff=False, role=None,
               first_name="", last_name=""):
    user = User.objects.create_user(
        username=username, email=f"{username}@{EMAIL_DOMAIN}", password=password,
        # is_staff at CREATION time, not via set_user_role afterwards: the
        # cohort post_save receiver skips staff, and set_user_role grants the
        # flag only after the row exists.
        is_staff=staff,
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
def provision_kit(label, *, course, days=DEFAULT_DAYS, pupils=DEFAULT_PUPILS,
                  frontier_part=None, seed=None, created_by=None):
    require_vendor()

    label = (label or "").strip()
    if not label or len(label) > LABEL_MAX:
        raise errors.InvalidLabel("label must be non-blank and at most 200 characters")
    if not MIN_PUPILS <= pupils <= MAX_PUPILS:
        raise errors.InvalidBounds("pupils", f"pupils must be {MIN_PUPILS}-{MAX_PUPILS}")
    if not MIN_DAYS <= days <= MAX_DAYS:
        raise errors.InvalidBounds("days", f"days must be {MIN_DAYS}-{MAX_DAYS}")

    plan = build_course_plan(course)
    if not plan.units:
        raise errors.EmptyCourse(f"{course.slug} has no published unit")

    slug = slugify(label, allow_unicode=False)[:SLUG_MAX] or SLUG_FALLBACK
    base = _free_base(slug, pupils)
    teacher_name, student_name, pupil_names = _usernames(base, pupils)

    seed = secrets.randbelow(2**31) if seed is None else seed
    kit = DemoKit.objects.create(
        label=label, slug=slug, course=course, seed=seed, pupil_count=pupils,
        frontier_part=frontier_part, created_by=created_by,
        expires_at=timezone.now() + timedelta(days=days),
    )

    group = Group.objects.create(name=f"Klasa demo — {label[:150]} (#{kit.pk})", course=course)
    kit.group = group

    teacher_password, student_password = _password(), _password()
    teacher = _make_user(
        teacher_name, display_name=f"Nauczyciel demo — {label} (#{kit.pk})"[:150],
        password=teacher_password, staff=True, role=TEACHER,
    )
    group.teachers.add(teacher)
    student = _make_user(
        student_name, display_name=f"Uczeń demo — {label} (#{kit.pk})"[:150],
        password=student_password, role=STUDENT,
    )
    kit.teacher, kit.student = teacher, student
    kit.save(update_fields=["group", "teacher", "student"])
    kit.users.add(teacher, student)

    import random

    rng = random.Random(seed)
    names = draw_names(rng, pupils)
    pupil_users = []
    for username, (first, last) in zip(pupil_names, names, strict=True):
        pupil = _make_user(
            username, display_name=f"{first} {last}", first_name=first,
            last_name=last, role=STUDENT,
        )
        kit.users.add(pupil)
        pupil_users.append(pupil)

    # The SERVICE, never a direct Enrollment.objects.create.
    add_students_to_group(group, [student, *pupil_users], added_by=teacher)

    warnings, _bands, _depths = generate(
        rng, kit, plan, pupil_users, course=course, frontier_part=frontier_part
    )
    warnings.extend(plan.warnings)
    warnings.extend(_webhook_warnings())

    for pupil in pupil_users:
        has_lesson = UnitProgress.objects.filter(
            student=pupil, completed=True
        ).filter(unit__unit_type="lesson").exists()
        has_score = QuizSubmission.objects.filter(
            student=pupil, status=QuizSubmission.Status.SUBMITTED
        ).exclude(score=None).exists()
        if not (has_lesson and has_score):
            raise errors.EmptyKit(
                f"{course.slug} produced no usable activity for {pupil.username}"
            )

    return ProvisionResult(kit, teacher_password, student_password, warnings)


def _webhook_warnings():
    """Warn, never refuse: a refusal would let a data-protection nicety block
    provisioning, and a human-only check is what Risk 5 says stops happening."""
    from integrations.models import WebhookEndpoint

    endpoint = WebhookEndpoint.load()
    if endpoint.enabled and endpoint.url:
        return [DemoWarning("active_webhook_endpoint", None, endpoint.url)]
    return []
```

- [ ] **Step 4: Run the provisioning and in-progress tests**

```bash
uv run pytest tests/demo/test_provision.py tests/demo/test_in_progress.py -v
```

Expected: PASS. ⚠️ If `test_every_pupil_holds_progress_and_a_scored_submission` fails, the
reach-forward is not firing — check `first_lesson` / `first_quiz` in `generate`, not the test.

- [ ] **Step 5: Falsify the collision scan**

Change `_taken` to check `User.objects.filter(username__in=...)` only, then add a test user
whose *email* collides, and re-run `test_a_second_kit_for_the_same_school_gets_distinct_usernames`.

Expected: the provisioning blows up with allauth's `ValueError` mid-transaction instead of
bumping cleanly. **Revert by hand.**

- [ ] **Step 6: Commit**

```bash
git add demo/services.py tests/demo/test_provision.py
git commit -m "feat(demo): provision_kit — users, group, enrolment and generated activity"
```

---

### Task 11: `purge_kit`, `revoke_kit`, `extend_kit`

**Files:**
- Modify: `demo/services.py`
- Test: `tests/demo/test_lifecycle.py`

**Interfaces:**
- Produces:
  - `demo.services.purge_kit(kit, *, reason) -> None`
  - `demo.services.revoke_kit(kit) -> None`
  - `demo.services.extend_kit(kit, *, days) -> ExtendResult` — dataclass
    `kit, new_expires_at, long_lived`
  - `demo.services.purge_expired(*, dry_run=False) -> list[DemoKit]`

- [ ] **Step 1: Write the failing test**

`tests/demo/test_lifecycle.py`:

```python
from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone

from demo import errors


@pytest.mark.django_db
def test_purge_removes_every_kit_user_and_the_group_and_keeps_the_row():
    """T8. The rep has created a collection and force-submitted first, because
    those are the FKs most likely to block a delete."""
    from django.contrib.auth import get_user_model

    from demo.models import DemoKit
    from demo.services import purge_kit
    from grouping.models import Collection, Group
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    kit = provision_for_test(small_course())
    Collection.objects.create(name="Demo", course=kit.course, owner=kit.teacher)
    user_ids = list(kit.users.values_list("pk", flat=True))
    group_id = kit.group_id

    purge_kit(kit, reason=DemoKit.ClosedReason.REVOKED)

    assert not get_user_model().objects.filter(pk__in=user_ids).exists()
    assert not Group.objects.filter(pk=group_id).exists()
    kit.refresh_from_db()
    assert kit.closed_at is not None
    assert kit.status_key == "closed_revoked"
    assert kit.teacher_id is None and kit.group_id is None


@pytest.mark.django_db
def test_purge_tolerates_a_half_dismantled_kit():
    """A group deleted by hand must not make the kit un-closable for ever."""
    from demo.models import DemoKit
    from demo.services import purge_kit
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    kit = provision_for_test(small_course())
    kit.group.delete()
    kit.refresh_from_db()

    purge_kit(kit, reason=DemoKit.ClosedReason.EXPIRED)
    kit.refresh_from_db()
    assert kit.closed_at is not None


@pytest.mark.django_db
def test_purge_expired_selects_only_expired_open_kits_and_is_idempotent():
    """T15. The idempotence case needs an ALREADY-CLOSED kit whose expires_at is
    past, or it passes because the second run found nothing."""
    from demo.models import DemoKit
    from demo.services import purge_expired
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    course = small_course()
    live = provision_for_test(course, label="Live")
    expired = provision_for_test(course, label="Expired")
    DemoKit.objects.filter(pk=expired.pk).update(
        expires_at=timezone.now() - timedelta(days=1)
    )

    purged = purge_expired()
    assert [k.pk for k in purged] == [expired.pk]

    assert purge_expired() == []  # closed_at IS NULL keeps it idempotent
    live.refresh_from_db()
    assert live.closed_at is None


@pytest.mark.django_db
def test_extend_moves_from_now_and_flags_a_long_lived_kit():
    """T15b. max(expires_at, now()) matters for a kit that expired yesterday."""
    from demo.models import DemoKit
    from demo.services import extend_kit
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    kit = provision_for_test(small_course())
    DemoKit.objects.filter(pk=kit.pk).update(
        expires_at=timezone.now() - timedelta(days=1)
    )
    kit.refresh_from_db()

    result = extend_kit(kit, days=14)
    assert result.new_expires_at > timezone.now()
    assert result.long_lived is False

    DemoKit.objects.filter(pk=kit.pk).update(
        created_at=timezone.now() - timedelta(days=50)
    )
    kit.refresh_from_db()
    assert extend_kit(kit, days=30).long_lived is True


@pytest.mark.django_db
def test_extend_and_revoke_refuse_a_closed_kit():
    from demo.models import DemoKit
    from demo.services import extend_kit, purge_kit, revoke_kit
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    kit = provision_for_test(small_course())
    purge_kit(kit, reason=DemoKit.ClosedReason.REVOKED)
    kit.refresh_from_db()

    with pytest.raises(errors.KitAlreadyClosed):
        extend_kit(kit, days=7)
    with pytest.raises(errors.KitAlreadyClosed):
        revoke_kit(kit)


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=False)
def test_the_cleanup_half_is_exempt_from_the_vendor_guard():
    """R8: guarding a cleanup path is the one way the guard could leave
    stranger-known logins alive on prod."""
    from demo.models import DemoKit
    from demo.services import purge_expired, revoke_kit
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    kit = provision_for_test(small_course())  # provisions with the flag ON
    revoke_kit(kit)  # must NOT raise with the flag off
    kit.refresh_from_db()
    assert kit.status_key == "closed_revoked"
    assert purge_expired() == []
```

- [ ] **Step 2: Run it and watch it fail**

```bash
uv run pytest tests/demo/test_lifecycle.py -v
```

Expected: FAIL — `ImportError: cannot import name 'purge_kit'`.

- [ ] **Step 3: Write the lifecycle services**

Append to `demo/services.py`:

```python
from demo.constants import LONG_LIVED_DAYS
from grouping.services import delete_group


@dataclass
class ExtendResult:
    kit: DemoKit
    new_expires_at: object
    long_lived: bool


def _require_open(kit):
    if kit.closed_at is not None:
        raise errors.KitAlreadyClosed(f"kit #{kit.pk} was closed on {kit.closed_at:%Y-%m-%d}")


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
    nightly for ever. Each kit gets its own transaction so one failure does not
    leave the others' logins alive."""
    due = list(
        DemoKit.objects.filter(expires_at__lte=timezone.now(), closed_at__isnull=True)
    )
    if dry_run:
        return due
    purged = []
    for kit in due:
        purge_kit(kit, reason=DemoKit.ClosedReason.EXPIRED)
        purged.append(kit)
    return purged
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/demo/test_lifecycle.py -v
```

Expected: PASS (six tests).

- [ ] **Step 5: Falsify the purge predicate**

Drop `closed_at__isnull=True` from `purge_expired` and re-run.

Expected: `test_purge_expired_selects_only_expired_open_kits_and_is_idempotent` FAILS on the
second `purge_expired()` call. **Revert by hand.**

- [ ] **Step 6: Commit**

```bash
git add demo/services.py tests/demo/test_lifecycle.py
git commit -m "feat(demo): purge, revoke and extend, with an idempotent purge predicate"
```

---

### Task 12: The `demo_access` command

Follows this codebase's existing subcommand shape: a positional `action` with `choices`,
dispatched in `handle` (see `courses/management/commands/migrate_course_content.py:361`).

**Files:**
- Create: `demo/management/__init__.py`, `demo/management/commands/__init__.py`,
  `demo/management/commands/demo_access.py`
- Test: `tests/demo/test_command.py`

**Interfaces:**
- Produces: `manage.py demo_access {create,list,extend,revoke,purge}`.

- [ ] **Step 1: Write the failing test**

`tests/demo/test_command.py`:

```python
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_create_prints_both_logins_and_the_expiry_once():
    from tests.demo.fixtures import small_course

    small_course()
    out = StringIO()
    call_command(
        "demo_access", "create", "--label", "SP 12", "--course", "small",
        "--pupils", "5", "--seed", "1", stdout=out,
    )
    printed = out.getvalue()
    assert "sp-12-nauczyciel" in printed and "sp-12-uczen" in printed
    assert "expires" in printed.lower()


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_list_hides_closed_kits_until_all_and_prints_the_status_key():
    """T26 — list is Risk 5's early warning, and the assertion is on the machine
    key so it cannot follow the process locale."""
    from demo.models import DemoKit
    from demo.services import revoke_kit
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    course = small_course()
    live = provision_for_test(course, label="Live")
    dead = provision_for_test(course, label="Dead")
    revoke_kit(dead)

    out = StringIO()
    call_command("demo_access", "list", stdout=out)
    assert "Live" in out.getvalue() and "Dead" not in out.getvalue()
    assert "active" in out.getvalue()

    out_all = StringIO()
    call_command("demo_access", "list", "--all", stdout=out_all)
    assert "closed_revoked" in out_all.getvalue()
    assert live.teacher.username in out.getvalue()


@pytest.mark.django_db
def test_the_guarded_and_exempt_subcommands_are_split_as_specified():
    """T13 — enumerated FROM THE PARSER, never listed by hand and never pinned
    by count. A guard on `create` alone would keep a hand-written version green
    while `purge` refused to run on prod."""
    from demo.management.commands.demo_access import Command

    parser = Command().create_parser("manage.py", "demo_access")
    actions = {
        choice
        for action in parser._actions
        if action.dest == "action"
        for choice in action.choices
    }
    guarded, exempt = {"create", "extend"}, {"purge", "revoke", "list"}
    assert actions == guarded | exempt

    for name in guarded:
        with pytest.raises(CommandError):
            call_command("demo_access", name, "--label", "x", "--course", "small")

    call_command("demo_access", "purge", "--dry-run")  # must NOT raise
    call_command("demo_access", "list")


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_a_missing_kit_id_is_a_clean_error():
    with pytest.raises(CommandError):
        call_command("demo_access", "revoke", "9999")
```

- [ ] **Step 2: Run it and watch it fail**

```bash
uv run pytest tests/demo/test_command.py -v
```

Expected: FAIL — `Unknown command: 'demo_access'`.

- [ ] **Step 3: Write the command**

`demo/management/commands/demo_access.py`:

```python
"""Issue and retire school demo kits.

The subcommand shape mirrors migrate_course_content: a positional `action` with
`choices`, dispatched in handle(). `create` and `extend` are vendor-guarded;
`purge`, `revoke` and `list` are NOT (spec R8) — guarding a cleanup path is the
one way the guard could leave stranger-known logins alive on prod.
"""

from django.core.management.base import BaseCommand, CommandError

from courses.models import Course
from demo import errors
from demo.constants import DEFAULT_DAYS, DEFAULT_PUPILS
from demo.models import DemoKit
from demo.services import extend_kit, provision_kit, purge_expired, revoke_kit


class Command(BaseCommand):
    help = "Create, list, extend, revoke and purge school demo kits."

    def add_arguments(self, parser):
        parser.add_argument(
            "action", choices=("create", "list", "extend", "revoke", "purge")
        )
        parser.add_argument("kit_id", nargs="?", type=int)
        parser.add_argument("--label")
        parser.add_argument("--course", help="course slug (required for create)")
        parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
        parser.add_argument("--pupils", type=int, default=DEFAULT_PUPILS)
        parser.add_argument("--frontier-part", type=int, default=None)
        parser.add_argument("--seed", type=int, default=None)
        parser.add_argument("--all", action="store_true")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **o):
        try:
            getattr(self, f"_{o['action']}")(o)
        except errors.DemoKitError as exc:
            raise CommandError(str(exc)) from exc
        except Exception as exc:  # ImproperlyConfigured from the vendor guard
            raise CommandError(str(exc)) from exc

    def _kit(self, o):
        kit = DemoKit.objects.filter(pk=o["kit_id"]).first()
        if kit is None:
            raise errors.KitNotFound(f"no demo kit with id {o['kit_id']}")
        return kit

    def _create(self, o):
        if not o["course"]:
            raise errors.DemoKitError("--course <slug> is required")
        course = Course.objects.filter(slug=o["course"]).first()
        if course is None:
            raise errors.DemoKitError(f"no course with slug {o['course']!r}")
        result = provision_kit(
            o["label"], course=course, days=o["days"], pupils=o["pupils"],
            frontier_part=o["frontier_part"], seed=o["seed"],
        )
        kit = result.kit
        self.stdout.write(self.style.SUCCESS(f"Demo kit #{kit.pk} for {kit.label}"))
        self.stdout.write(f"  teacher: {kit.teacher.username}  {result.teacher_password}")
        self.stdout.write(f"  pupil:   {kit.student.username}  {result.student_password}")
        self.stdout.write(f"  expires: {kit.expires_at:%Y-%m-%d %H:%M} UTC")
        self.stdout.write("  (the passwords are not stored; copy them now)")
        for warning in result.warnings:
            self.stdout.write(self.style.WARNING(f"  ! {warning.kind}: {warning.reason}"))

    def _list(self, o):
        kits = DemoKit.objects.all()
        if not o["all"]:
            kits = kits.filter(closed_at__isnull=True)
        for kit in kits:
            teacher = kit.teacher.username if kit.teacher else "-"
            self.stdout.write(
                f"#{kit.pk}\t{kit.label}\t{kit.course.slug}\t{kit.pupil_count}\t"
                f"{teacher}\t{kit.created_at:%Y-%m-%d}\t{kit.expires_at:%Y-%m-%d}\t"
                f"{kit.status_key}"
            )

    def _extend(self, o):
        result = extend_kit(self._kit(o), days=o["days"])
        self.stdout.write(f"#{result.kit.pk} now expires {result.new_expires_at:%Y-%m-%d}")
        if result.long_lived:
            self.stdout.write(
                self.style.WARNING("  ! this kit has been alive for over 60 days")
            )

    def _revoke(self, o):
        kit = self._kit(o)
        revoke_kit(kit)
        self.stdout.write(f"#{kit.pk} revoked")

    def _purge(self, o):
        due = purge_expired(dry_run=o["dry_run"])
        verb = "would purge" if o["dry_run"] else "purged"
        for kit in due:
            self.stdout.write(f"{verb} #{kit.pk} {kit.label}")
        self.stdout.write(f"{verb} {len(due)} kit(s)")
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/demo/test_command.py -v
```

Expected: PASS (four tests).

- [ ] **Step 5: Commit**

```bash
git add demo/management/ tests/demo/test_command.py
git commit -m "feat(demo): the demo_access management command"
```

---

### Task 13: Determinism — the golden class

T7 proves the generator is self-consistent; **T7b is what actually defends the draw order**,
because T7 runs the same code twice and cannot see a reordering.

**Files:**
- Test: `tests/demo/test_determinism.py`, `tests/demo/golden_class.json`

**Interfaces:**
- Consumes everything above. Produces no production code.

- [ ] **Step 1: Write the tests**

`tests/demo/test_determinism.py`:

```python
import json
from pathlib import Path

import pytest

GOLDEN = Path(__file__).with_name("golden_class.json")


def _projection(kit):
    """The generated values, EXCLUDING timestamps: every row keeps a wall-clock
    stamp (there is no back-dating), so a naive row comparison is red on correct
    code."""
    from courses.models import QuestionResponse, UnitProgress

    rows = []
    for pupil in kit.users.exclude(pk__in=[kit.teacher_id, kit.student_id]).order_by(
        "username"
    ):
        progress = sorted(
            UnitProgress.objects.filter(student=pupil, completed=True).values_list(
                "unit__title", flat=True
            )
        )
        answers = [
            [r.element_id, str(r.fraction), json.dumps(r.latest_answer, sort_keys=True)]
            for r in QuestionResponse.objects.filter(
                submission__student=pupil
            ).order_by("element_id")
        ]
        rows.append(
            {"username": pupil.username, "name": pupil.display_name,
             "progress": progress, "answers": answers}
        )
    return rows


@pytest.mark.django_db
def test_the_same_seed_produces_the_same_class():
    """T7 — self-consistency. Its only honest mutant breaks determinism itself
    (reseed from secrets per run); a REORDERING mutant leaves it green, which is
    why those live on T7b."""
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    first = _projection(provision_for_test(small_course(), seed=2024))
    second = _projection(provision_for_test(small_course(), seed=2024))
    assert first == second


@pytest.mark.django_db
def test_the_golden_class_is_unchanged():
    """T7b — the ONLY test that pins an absolute stream. Its mutants are each
    reordering the spec enumerates: swap the jitter draw ahead of the band
    shuffle; iterate questions in pk order; draw the partial only when the first
    draw said wrong; consume draws for an R3-skipped quiz.

    Landing a DELIBERATE order change means regenerating this file in the same
    commit — that is the point of it.
    """
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    actual = _projection(provision_for_test(small_course(), pupils=5, seed=777))
    if not GOLDEN.exists():  # first run: record, then read the diff by eye
        GOLDEN.write_text(json.dumps(actual, indent=2, ensure_ascii=False), "utf-8")
        pytest.fail("golden file written — inspect it, then re-run")
    assert actual == json.loads(GOLDEN.read_text("utf-8"))
```

- [ ] **Step 2: Generate the golden file**

```bash
uv run pytest tests/demo/test_determinism.py::test_the_golden_class_is_unchanged -v
```

Expected: FAIL with "golden file written". **Open `tests/demo/golden_class.json` and read
it**: five pupils with Polish names, progress lists that differ between pupils, and stored
answers that are not all identical. If it looks wrong, the generator is wrong — fix it before
accepting the file.

- [ ] **Step 3: Re-run both tests**

```bash
uv run pytest tests/demo/test_determinism.py -v
```

Expected: PASS (two tests).

- [ ] **Step 4: Falsify the draw order**

In `_pick_answer`, move the `partial_roll` draw inside the `if not correct_roll:` branch (so it
is drawn only when needed) and re-run.

Expected: `test_the_golden_class_is_unchanged` FAILS while `test_the_same_seed_produces_the_
same_class` still PASSES — which is precisely the division of labour between the two.
**Revert by hand.**

- [ ] **Step 5: Commit**

```bash
git add tests/demo/test_determinism.py tests/demo/golden_class.json
git commit -m "test(demo): pin the generator's draw order with a golden class"
```

---

### Task 14: The runbook — the purge cron and the ops steps

**Files:**
- Modify: `docs/deployment.md` (§7)

**Interfaces:** none.

- [ ] **Step 1: Add the cron line and the ops notes**

In `docs/deployment.md` §7, after the `purge_notifications` and backup cron lines, add:

````markdown
And the demo-kit purge — **one physical line**, in the root crontab:

```cron
45 3 * * * cd /opt/libli && docker compose -f docker-compose.prod.yml --env-file .env.production exec -T app /app/.venv/bin/python manage.py demo_access purge >> /var/log/libli-demo-purge.log 2>&1
```

`45 3`, clear of the 02:15 backup and the 03:30 notifications purge. Test it once by hand
with `--dry-run` first, and check `logrotate` covers `/var/log/libli-*.log`.

⚠️ **A silently failing purge leaves live logins on prod.** Three ways it can stop: the app
container being down (including the ~24 s of every deploy), one kit raising (each kit has its
own transaction, so the others still close and the run exits non-zero), and — if `purge` were
ever vendor-gated — a lost `LIBLI_VENDOR_INSTANCE`. That is why it is not. Add
`demo_access list` to the routine you already use to look at the box: it shows
`pending_purge` rows.

**Before the first kit:** set `LIBLI_VENDOR_INSTANCE=true` in `.env.production` (measured
2026-09-12: unset, so `/for-schools/` is 404 and `demo_access create` refuses), and fill
`Institution.contact_email` (measured: blank). ⚠️ The same flag publishes `/for-schools/`, so
turning it on is a publishing decision — see the spec's §5.
````

- [ ] **Step 2: Commit**

```bash
git add docs/deployment.md
git commit -m "docs(deployment): demo-kit purge cron and the pre-first-kit ops steps"
```

---

### Task 15: Boundary and contract tests

Four spec tests that no earlier task reaches. Each protects a rule the spec argues at length
and that every other test would leave green.

**Files:**
- Test: `tests/demo/test_boundaries.py`

**Interfaces:** consumes everything above; no production code unless a test goes red.

- [ ] **Step 1: Write the tests**

`tests/demo/test_boundaries.py`:

```python
import pytest
from django.test import override_settings

from demo import errors


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_frontier_part_zero_is_honoured_not_treated_as_falsy():
    """T21 — part 0 is a legal AND falsy value, so `if frontier_part:` silently
    turns --frontier-part 0 into the 0.75 fraction."""
    from demo.content import build_course_plan
    from demo.generator import frontier_index
    from tests.demo.fixtures import small_course

    course = small_course()
    plan = build_course_plan(course)

    part_zero = frontier_index(plan, 0, course)
    default = frontier_index(plan, None, course)
    assert part_zero != default, "part 0 must not collapse to the fraction"

    with pytest.raises(errors.InvalidFrontierPart):
        frontier_index(plan, 99, course)


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_degenerate_labels_produce_usable_identifiers():
    """T17b — four boundaries §4.2 specifies, each producing user-visible
    identifiers on prod. ⚠️ The label must NOT be Polish: slugify transliterates
    diacritics (Łódź -> odz), so a Polish label never exercises the fallback."""
    from demo.services import provision_kit
    from tests.demo.fixtures import small_course

    course = small_course()

    kit = provision_kit("###", course=course, days=14, pupils=5, seed=1).kit
    assert kit.slug == "demo"
    assert not kit.teacher.username.startswith("-")

    with pytest.raises(errors.InvalidLabel):
        provision_kit("x" * 250, course=course, days=14, pupils=5, seed=1)

    long_label = "y" * 200
    kit2 = provision_kit(long_label, course=course, days=14, pupils=5, seed=1).kit
    assert len(kit2.group.name) <= 200
    assert len(kit2.teacher.display_name) <= 150
    assert kit2.teacher.display_name != kit2.student.display_name

    kit3 = provision_kit("Padding", course=course, days=14, pupils=40, seed=1).kit
    pupils = kit3.users.exclude(pk__in=[kit3.teacher_id, kit3.student_id])
    widths = {len(u.username.rsplit("-p", 1)[1]) for u in pupils}
    assert widths == {2}, "pupil numbers pad to the width of --pupils"


def test_every_warning_kind_has_a_display_string():
    """T29 — a missing entry is a KeyError, or an untranslated cell in a panel
    PR 3 requires to be fully translated."""
    from demo.warnings import DISPLAY, KINDS

    assert set(DISPLAY) == KINDS
    for kind in KINDS:
        assert str(DISPLAY[kind]).strip()


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_the_generator_never_rewrites_an_existing_timestamp():
    """T18 — Q1 is resolved: there is no back-dating, so a reinstated queryset
    update with no student filter would rewrite a real pupil's completed_at
    while adding NO rows, passing every count-based assertion."""
    from courses.models import Enrollment, UnitProgress
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test
    from tests.factories import make_verified_user

    course = small_course()
    outsider = make_verified_user(username="real2", email="real2@example.com")
    Enrollment.objects.create(student=outsider, course=course)
    unit = course.nodes.filter(unit_type="lesson").first()
    progress = UnitProgress.objects.create(
        student=outsider, unit=unit, completed=True
    )
    stamped = UnitProgress.objects.get(pk=progress.pk).completed_at

    provision_for_test(course)

    assert UnitProgress.objects.get(pk=progress.pk).completed_at == stamped
```

- [ ] **Step 2: Run them**

```bash
uv run pytest tests/demo/test_boundaries.py -v
```

Expected: PASS (four tests). ⚠️ If the padding assertion fails, `_usernames` is padding to a
fixed width instead of `len(str(pupils))` — fix the code, not the test.

- [ ] **Step 3: Falsify the falsy-zero rule**

In `frontier_index`, change `if frontier_part is not None:` to `if frontier_part:` and re-run.

Expected: `test_frontier_part_zero_is_honoured_not_treated_as_falsy` FAILS. **Revert by hand.**

- [ ] **Step 4: Commit**

```bash
git add tests/demo/test_boundaries.py
git commit -m "test(demo): frontier-part zero, degenerate labels, warning kinds, no timestamp rewrites"
```

---

## Final verification

- [ ] **Run the whole demo suite plus every test that touches what we changed**

```bash
uv run pytest tests/demo/ tests/test_seed_demo_course.py -v
```

Expected: all green. ⚠️ **Grep the summary line** — pytest can exit 0 with failures in the
body.

- [ ] **Check migrations and lint**

```bash
uv run python manage.py makemigrations --check --dry-run
uv run ruff check --no-cache .
uv run ruff format --check .
```

- [ ] **Provision against the local mat-pp copy and LOOK at it** (spec §8, "beyond the suite")

```bash
uv run python manage.py demo_access create --label "Test School" --course mat-pp --seed 1
```

Then log in as the printed teacher and read the matrix, the drill-down, the review queue and
the pupil view, **in light and dark**. Record the wall-clock of the provision — PR 3's tab
depends on whether it fits inside a web request. Check:
- results mode: at least two-thirds of the course's gradeable quiz units hold a score for at
  least half the pupils;
- progress mode: the class shows **gaps**, not a clean staircase;
- the review queue is non-empty;
- names read as a Polish class list, not `test-school-p01`.

Then purge it: `uv run python manage.py demo_access revoke <id>`.

- [ ] **Open the PR** with the spec linked and the measured provisioning time in the body.

---

## Self-review notes

**Spec coverage.** R1/R1b (Task 5, 6, 8), R2 (Task 6), R3 (Task 6), R4 (Task 8, 9), R5
(Task 7, 8, 13), R6 (Task 10), R7 (Task 8), R8 (Task 3, 11, 12), R9 (Task 6). §4.2 model
(Task 2), §4.4 provisioning (Task 10), §4.5 generator (Tasks 7–9), §4.6 command (Task 12),
§5 ops (Task 14).

**Deliberately NOT in this plan** (they belong to the later PRs):
- PR 3's admin tab — T10, T11, T26's tab half.
- PR 5's per-question view and its access test (T30).
- PR 4's `/for-schools/` copy.
- **T24** (the bands must differ) needs the `wide` fixture; fold it into the PR 3 plan or add
  it here if the local mat-pp run suggests the bands are not visibly distinct.
- **T14** (`/admin/` lists zero models) and **T9** (cross-kit isolation) — both need a second
  kit and the analytics views; they belong with PR 3's surface work.

**Test-to-task map** (spec §8 numbering): T1/T2a/T2b/T3/T5 → Task 8 · T1b/T6 → Task 5 ·
T2c → Task 6 · T7/T7b → Task 13 · T8/T15/T15b → Task 11 · T12/T17/T20/T22/T28 → Task 10 ·
T13/T26 → Task 12 · T16 → Tasks 10–11 (asserted on behaviour: the `Enrollment` rows
`add_students_to_group` writes, and `delete_group`'s post-delete recompute) · T17b/T18/T21/T29
→ Task 15 · T19 → Task 1 · T25 → Task 9 · T27 → Task 4.

**Type consistency checked:** `generate()` returns `(warnings, bands, depths)` at all three
call sites; `Answers` is `(correct, wrong, partial)` everywhere; `build_course_plan` returns
`CoursePlan` and every consumer uses its field names; `provision_kit` returns
`ProvisionResult` and `extend_kit` returns `ExtendResult`, both unpacked by attribute.

