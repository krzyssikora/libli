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
- ⚠️ **Start the test-DB container before the first pytest step.** Against a stopped
  container the first run looks *hung* for 4m21s before it fails. Do this once, before
  Task 1 Step 2, and never background a pytest run — a backgrounded run orphans the test
  DB and the next one dies with `DuplicateDatabase`.
- ⚠️ **The lint gate, in full.** `pyproject.toml` sets `select = ["E", "F", "I", "UP", "B",
  "S"]`, `ignore = ["S101"]`, `target-version = "py313"`, **no explicit `line-length` (so the
  default 88 applies)**, and `tests/**` ignores only `S105/S106/S107`. Seven consequences bite
  this plan's code blocks, and **all seven surface only at the Final-verification step**,
  across a dozen files at once. Fix them as you write, not at the end:
  1. **Single-line imports** (`I001`, `force-single-line = true`). **Any `from x import A, B`
     — parenthesized or not — is shorthand in this plan** and must be written one name per
     line. The parenthesized blocks are the obvious ones; so are `from demo import errors,
     names`, `from demo.constants import AVERAGE, STRONG, STRUGGLING`, `from courses.quiz
     import answer_to_json, finalize_submission`, `from dataclasses import dataclass, field`
     and roughly twenty more. See `courses/management/commands/seed_demo_course.py:6-56`,
     which spells `from courses.models import Choice` / `from courses.models import
     ChoiceQuestionElement` on separate lines.
  2. **Imports go in the file's header** (`E402`). Several tasks say "Append to
     `demo/generator.py`" / "`demo/services.py`" and then show an import block at the top of
     the appended text. **Do not paste it there.** Merge those imports into the module header
     that Task 7/3 already wrote, and append only the functions. An import after a `def` is
     `E402`.
  3. **`random.Random(...)` is `S311`** — flagged on the *constructor*, not on the method
     calls. There is no existing `random` usage anywhere in this repo, so there is no house
     convention to copy. **Decision for this plan: a per-file-ignore, not fifteen `noqa`s.**
     Task 2 Step 7 adds it to `pyproject.toml`:
     ```toml
     [tool.ruff.lint.per-file-ignores]
     "demo/**" = ["S311"]        # deterministic content generation; secrets covers
     "tests/demo/**" = ["S311"]  # the seed and the passwords (spec R5/§4.6)
     ```
     ⚠️ Add these **alongside** the existing `tests/**` entries, not replacing them.
  4. **`typing.Optional` / `typing.Union` are banned** (`UP045`/`UP007` at py313). Write
     `int | None`.
  5. **88 columns** (`E501`). **A dozen-plus lines in the blocks below exceed it as written** —
     the longer `demo/warnings.py` `DISPLAY` strings, `demo/content.py`'s
     `warns.append(DemoWarning("question_dropped", ...))` and `skip_reason = f"..."` lines, the
     `Group.objects.create` name f-string, the `KitAlreadyClosed` f-string, the
     `fewer_in_progress_than_target` argument line, `demo_access.py`'s `"... and N more"`
     write, and `test_content.py`'s `saw_sentinel` message, among others. **Do not work from
     this list** — it is illustrative and was already incomplete once. Run
     `uv run ruff check --no-cache <file>` after pasting each block and fix what it names. For
     the `DISPLAY` entries, wrap the text inside the `_(` call. The repo's convention for a
     line that genuinely cannot be wrapped is an explicit `# noqa: E501` (see
     `config/settings/base.py:141`) — none of ours needs one.
  6. **`I001` enforces ORDERING too, not just splitting** — section order (stdlib /
     third-party / first-party), alphabetical within each section, **and it checks
     function-local import blocks as well as module headers**. So after splitting a block,
     re-sort it.
  7. **`ruff format --check .` is a SEPARATE gate** from `ruff check`, and it is the last
     command in Final verification. It explodes any collection or call carrying a **magic
     trailing comma** to one element per line — which reformats all four `demo/names.py` name
     tuples and every multi-argument `models.ForeignKey(...)` written packed-with-a-trailing-
     comma below. Either drop the trailing comma where the block should stay packed, or run
     `uv run ruff format <file>` as you write each one and take its output. Do not leave this
     to the end.
- **Polish copy** in this PR is limited to display names, the checked-in name lists **and
  eleven new msgids**: the ten `demo/warnings.py` `DISPLAY` strings, plus `_("Revoked")` from
  `demo/models.py`'s `ClosedReason` (Task 2 Step 6). ⚠️ `_("Expired")` is **already** in
  `locale/pl/LC_MESSAGES/django.po:133`, so only `"Revoked"` needs filling from that pair.
  **Twelve msgids extracted from the new code, eleven of them new, eleven to write** — Step 4b
  lists all eleven verbatim and is the authority on the count. Task 6 Step 4b carries the catalog step: `makemessages -l
  pl`, fill them, `compilemessages`, commit both `.po` and `.mo` in the same commit. ⚠️ Rebase
  and **regenerate** the `.mo` before the PR — a stale branch conflicts on the binary.

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

## Branching — read before Task 1

**ONE branch, ONE pull request, fifteen commits.** The title says "PR 1 + PR 2" because the
work has two *logical* halves — the safety guard, then the demo app — and the spec numbers them
that way. It does **not** mean two pull requests: there is one Final verification and one "Open
the PR" step, and Task 1's guard is three files that nobody should wait on.

⚠️ **Create the branch before Task 1 Step 1.** Master is the default branch and *is* the
protected test gate this plan leans on (Task 2 Step 7, Task 9's preamble); committing Task 1
Step 6 onto it directly bypasses exactly the gate the plan relies on.

```bash
git switch -c feat/demo-access-core
```

If you are running under a skill that already provisioned a worktree and branch, confirm with
`git branch --show-current` and skip this — do not create a second one.

If you decide to ship Task 1 separately after all (it is self-contained, and a smaller PR is
easier to review), branch it off master on its own, open it, and rebase the demo-app branch on
top once it merges — but say so up front rather than discovering the split mid-task.

---

### Task 1: PR 1 — `seed_demo_course` refuses to run in production

The command creates `demo_admin` as a **Platform Admin with the password `demo-pass-123`
hardcoded in this repo**, and `docs/deployment.md` §7 has told the operator to run it on the
live box since the first deployment. Prod was measured clean on 2026-09-12 (spec §5.0), so
this is prevention, not cleanup.

**Files:**
- Modify: `courses/management/commands/seed_demo_course.py` (imports + top of `handle`)
- Modify: `docs/deployment.md` — **two sites**, §7 (~440-448) and the gotchas bullet at ~810
- Modify: `README.md:36`, `docs/development/setup.md:86` and
  `docs/development/architecture.md:80` — all three still present `seed_demo_course` as freely
  runnable. **`README.md` is the one a new developer hits first.**
- Modify: `tests/capture_help_screenshots.py` — it calls the command and the guard breaks it
  (see Step 5)
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

Expected: PASS. The 12 pre-existing tests run under the test settings, where `DEBUG` is False,
so they will now fail — **that is the point**; they exercise the fixture deliberately.

**Repair them in ONE line, not twelve.** `tests/test_seed_demo_course.py:5` already declares

```python
@pytest.fixture(autouse=True)
def _isolate_media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
```

which already holds the `settings` fixture for every test in the module. Add
`settings.DEBUG = True` to its body. Twelve signature edits are unnecessary, and the new test
above is unaffected because it sets `settings.DEBUG = False` in its own body, which runs after
the autouse fixture.

⚠️ `settings` is a pytest-django fixture, not a module-level import — that is why it has to be
reached through a fixture at all. Confirm all 12 originals still pass: the run reports
**13 passed** (12 originals + the guard Step 1 appended), and
`grep -c "^def test_" tests/test_seed_demo_course.py` now returns **13**, not 12 — Step 1 added
its test to this same file.

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

⚠️ **Retitle §7 while you are here.** It reads `## 7. Second course and scheduled jobs`
(`docs/deployment.md:440`), but after this edit the section no longer creates a second course —
it forbids it — and Task 14 then adds the demo-purge cron to the same section. Change it to
`## 7. Scheduled jobs`. (The numbering is what later references use; keep the `7.`)

⚠️ **There is a SECOND site.** `docs/deployment.md:810-812` still reads "The demo-activity
seeder is separate, unbuilt work; `seed_demo_course` provides one enrolled student on its own
course so the analytics surfaces are reachable." After this PR that sentence is wrong twice
over — the command now refuses on prod, and the demo-activity seeder is exactly what PR 2
builds. An operator reading the gotchas list would still believe it is runnable. Replace that
bullet with:

```markdown
- **Analytics on an imported course will be empty** until a class has used it. To make the
  analytics surfaces reachable for a demo, issue a demo kit: `manage.py demo_access create
  --label "<school>" --course <slug>`. (`seed_demo_course` is a local screenshot fixture and
  refuses to run with `DEBUG=False` — see §7.)
```

⚠️ **And three more docs, outside `deployment.md`.** A developer whose local settings module
has `DEBUG=False` now gets a bare `CommandError` with nothing explaining the new precondition:

- **`README.md:36`** — under "# 5. (Optional) seed a demo course with an enrolled student",
  the most-read entry point in the repo. Add "(local only; refuses to run with `DEBUG=False`)".
- `docs/development/setup.md:86` shows `uv run python manage.py seed_demo_course` as a plain
  setup step — same parenthetical.
- `docs/development/architecture.md:80` lists it among the management commands — same
  parenthetical.

⚠️ **THE CALLER AUDIT, in full** — one caller actually breaks:

- **`tests/capture_help_screenshots.py:403`** does `call_command("seed_demo_course")` under
  `config.settings.test`, where `DEBUG` is False. It is **not** collected by the default run
  (`python_files = ["test_*.py"]` does not match `capture_*`), so nothing goes red — the
  help-screenshot regeneration workflow simply starts raising `CommandError` the next time
  someone runs that file explicitly, with no clue why. **Fix it at the CALL SITE**, not with an
  autouse fixture:

  ```python
  from django.test import override_settings

  with override_settings(DEBUG=True):  # seed_demo_course is DEBUG-only since PR 1
      call_command("seed_demo_course")  # once, before the locale loop
  ```

  ⚠️ Narrow on purpose. An autouse `settings.DEBUG = True` would flip the flag for the whole
  of `test_capture_help_screenshots` — a `live_server` + Playwright run whose entire output is
  committed PNGs — changing error-page rendering, `connection.queries` accumulation and static
  handling for the duration. A strictly larger blast radius than the one line that needs it, in
  the one file the plan admits nothing routinely runs.

  **Verify it**, since nothing else will:

  ```bash
  uv run pytest tests/capture_help_screenshots.py -m e2e -v
  ```

  ⚠️ `-m e2e` is mandatory — `addopts` carries `-m 'not e2e'`, so without it the file collects
  zero tests and reports a misleading green. Start the test-DB container first (see the Global
  Constraints), and expect a browser run. If you cannot run it here, say so in the PR body
  rather than claiming the fix is verified.

- `courses/tests/test_callout_numbering_render.py:184` calls `Command()._callout` directly,
  never `handle()`, so the guard does not touch it. No change needed.

- [ ] **Step 6: Commit**

```bash
git add courses/management/commands/seed_demo_course.py tests/test_seed_demo_course.py
git add tests/capture_help_screenshots.py
git add README.md docs/deployment.md docs/development/setup.md docs/development/architecture.md
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
  - `demo.models.DemoKit` with fields `label, slug, course, course_slug, group, teacher,
    student, users, seed, pupil_count, frontier_part, created_at, expires_at, created_by,
    closed_at, closed_reason` and property `status_key -> str`. **Every FK is nullable and
    `SET_NULL`** — the row outlives the kit by design, so none of them may `PROTECT`.
  - `demo.models.DemoKit.ClosedReason` (`EXPIRED`, `REVOKED`).
  - `demo.constants` — every name in the block below.
  - `demo.errors.DemoKitError` and its nine subclasses.

- [ ] **Step 1: Write the failing test**

Create `tests/demo/__init__.py` (empty) and `tests/demo/test_model.py`:

```python
from datetime import timedelta  # stdlib FIRST — I001 checks section order

import pytest
from django.utils import timezone


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
# ⚠️ MAX_PUPILS is bounded by the NAME POOLS, which hold exactly 40 entries each
# (MIN_NAMES_PER_LIST below). Raising it without extending demo/names.py makes
# every provisioning at the new ceiling raise NamePoolExhausted — after the kit,
# group, teacher and student rows have been written.
# tests/demo/test_names.py::test_the_pools_cover_the_maximum_class pins the pair.
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

# band -> {"p_correct", "depth" (a multiplier), "p_lesson", "p_optional"}.
# The class SHARES are not in here: they are STRONG_PCT / STRUGGLING_PCT above,
# because assign_bands partitions on integers while these four are probabilities.
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


class InvalidFrontierPart(InvalidBounds):
    """A subclass of InvalidBounds, so PR 3's form attaches it to a FIELD like
    the other two bounds errors rather than surfacing it as a form-wide error."""

    def __init__(self, message):
        super().__init__("frontier_part", message)


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


class PurgeFailed(DemoKitError):
    """Raised AFTER purge_expired has attempted every due kit, so one bad kit
    cannot strand the rest. Carries the kits that DID close, so the command can
    still report them before the non-zero exit."""

    def __init__(self, message, purged):
        self.purged = purged
        super().__init__(message)
```

- [ ] **Step 6: Write the model**

`demo/models.py`:

```python
from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from demo.constants import LABEL_MAX
from demo.constants import SLUG_MAX


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

    label = models.CharField(max_length=LABEL_MAX)
    # NOT unique: a closed kit's row is retained, so a unique slug would
    # permanently block a second demo for the same school. Uniqueness lives on
    # the usernames instead (services._free_base).
    # max_length is SLUG_MAX, not a loose 200: the constant's whole job is to
    # leave room for "-NNN-nauczyciel" inside username's 150, and a column twice
    # the size lets a direct write break that invariant silently.
    slug = models.SlugField(max_length=SLUG_MAX)
    # SET_NULL, not PROTECT. The row is retained for ever (see the class
    # docstring), so PROTECT would mean every closed kit permanently blocks its
    # course from deletion: after a few dozen demos, dropping or replacing
    # mat-pp raises ProtectedError, and neither `revoke` nor `purge` can clear
    # it because neither nulls this FK. `course_slug` below keeps the historical
    # record readable after the course is gone.
    course = models.ForeignKey(
        "courses.Course", on_delete=models.SET_NULL, null=True, blank=True
    )
    # Denormalised at creation so `demo_access list` and the retained row still
    # say WHICH course the demo was for once the FK is nulled.
    course_slug = models.SlugField(max_length=SLUG_MAX, blank=True)
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

- [ ] **Step 7: Register the app, update the app-set guard, and open the S311 per-file-ignore**

In `config/settings/base.py`, add `"demo",` to `INSTALLED_APPS` after `"support",`.

⚠️ **`tests/test_element_state_write_routes.py:69` WILL GO RED, and it is a branch-protection
gate, not a local one.** `test_the_first_party_app_set_is_what_we_think_it_is` builds
`_first_party_roots()` from `apps.get_app_configs()` filtered to `path.parent == ROOT`, and
asserts equality against a hard-coded set of ten names. `demo/` sits directly under the repo
root, so it becomes an eleventh member and the assertion fails. The guard's own comment says
"If a tenth app ships, this guard must be re-read rather than silently skipping it" — so read
it, confirm `demo/` genuinely holds first-party source that the write-route scan should cover
(it does: `demo/services.py` and `demo/generator.py` write model state), then add `"demo"` to
the set and re-run.

⚠️ **Also fix `_first_party_roots()`'s docstring at line 39**, which says "the 9 first-party
apps". That count is *already* wrong — ten ship today, since it predates `support` — and this
branch makes it eleven. Keep the edit **line-count neutral** (the repo's citation-rot rule):
replace `9` with `eleven` in place, do not rewrap the paragraph.

```bash
uv run pytest tests/test_element_state_write_routes.py -v
```

This is the **third** registry-wide drift guard, alongside `tests/test_list_referenced_files.py`
and `tests/test_transfer_schema.py` — see Final verification.

In `pyproject.toml`, **add** to the existing `[tool.ruff.lint.per-file-ignores]` block (keep
the two `S105/S106/S107` entries that are already there):

```toml
"demo/**" = ["S311"]
"tests/demo/**" = ["S311"]
```

Done here rather than at the end so the lint gate is green from the first `random.Random(`
this plan writes — see the Global Constraints for why `S311` is the right rule to silence and
`secrets` is what covers the security-sensitive draws.

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
git add demo/ config/settings/base.py pyproject.toml tests/demo/
git add tests/test_element_state_write_routes.py  # the app-set guard, per Step 7
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


def test_the_pools_cover_the_maximum_class():
    """MAX_PUPILS and MIN_NAMES_PER_LIST are BOTH 40 today, which makes
    `--pupils 40` the exact boundary — and nothing else relates them. Raise
    MAX_PUPILS (an obvious operator tweak; it sits under "operator bounds") and
    every provisioning at the new ceiling raises NamePoolExhausted AFTER the
    kit, group, teacher and student rows are written. The check above stays green
    throughout, because it compares the lists against the wrong constant.

    Derived, never a `== 40` pin on either side."""
    from demo import names
    from demo.constants import MAX_PUPILS

    shortest = min(
        len(names.FEMININE_GIVEN), len(names.MASCULINE_GIVEN),
        len(names.FEMININE_SURNAMES), len(names.MASCULINE_SURNAMES),
    )
    assert shortest >= MAX_PUPILS, (
        f"the name pools ({shortest}) cannot fill a class of MAX_PUPILS "
        f"({MAX_PUPILS}) — extend the lists or lower the bound"
    )


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
    """The PRE-CHECK half: count exceeds the shortest list, so draw_names refuses
    before the loop."""
    from demo import errors, names

    monkeypatch.setattr(names, "FEMININE_SURNAMES", ("Kowalska",))
    monkeypatch.setattr(names, "MASCULINE_SURNAMES", ("Kowalski",))
    monkeypatch.setattr(names, "FEMININE_GIVEN", ("Anna",))
    monkeypatch.setattr(names, "MASCULINE_GIVEN", ("Jan",))
    with pytest.raises(errors.NamePoolExhausted):
        names.draw_names(random.Random(1), 10)


def test_the_retry_limit_itself_raises_rather_than_spinning(monkeypatch):
    """The RETRY half. The test above never reaches the `while` loop — it trips
    the pre-check and returns — so without this case NAME_RETRY_LIMIT is dead
    code and a live spin ships untested.

    ⚠️ THE POOL CANNOT BE SHAPED TO REACH THIS BRANCH. Any pool short enough to
    exhaust distinct pairs also satisfies `min(len(...)) < count`, so the
    pre-check fires first and raises the OTHER message. (An earlier draft of this
    test claimed four 2-element lists with count=4 would pass the pre-check;
    2 < 4, so it does not — the test was red on correct code.) The only way in is
    to drop the retry budget to zero and force one collision.
    """
    from demo import errors, names

    monkeypatch.setattr(names, "NAME_RETRY_LIMIT", 0)
    monkeypatch.setattr(names, "FEMININE_GIVEN", ("Anna", "Maria"))
    monkeypatch.setattr(names, "MASCULINE_GIVEN", ("Jan", "Piotr"))
    monkeypatch.setattr(names, "FEMININE_SURNAMES", ("Kowalska", "Nowak"))
    monkeypatch.setattr(names, "MASCULINE_SURNAMES", ("Kowalski", "Nowak"))

    class _FixedRng:
        """Every draw returns the same value, so pupil 2 collides with pupil 1."""

        def random(self):
            return 0.0  # < 0.5 -> feminine, every time

        def randrange(self, n):
            return 0  # "Anna", "Kowalska", every time

    with pytest.raises(errors.NamePoolExhausted) as exc:
        names.draw_names(_FixedRng(), 2)  # 2 <= 2, so the pre-check passes
    assert "retries" in str(exc.value), "the RETRY branch, not the pre-check"
```

⚠️ Two things make this test honest. The message assertion, because **both branches raise the
same class** — without it the test passes on a build where the retry loop was deleted and the
pre-check fired. And `NAME_RETRY_LIMIT` being read **at call time inside `draw_names`**, not
captured at import: if the implementation binds the constant as a default argument, the
monkeypatch is inert and this test silently stops testing anything.

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

    `rng` is a `random.Random`. (Stated here rather than via a `noqa`'d unused
    `import random` at the top, which reads as an accident to the next person.)

    NAME_RETRY_LIMIT is read as a MODULE GLOBAL inside the loop below — never
    captured as a default argument — so the retry test can monkeypatch it.

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

Expected: PASS (**six** tests). Step 5 adds a seventh, the cramped-pool case — it is not in
this file yet, so do not go hunting for it here.

- [ ] **Step 5: Falsify the distinctness rule**

⚠️ **Not against the production lists.** With the `while` loop removed, 40 draws split ~20/20
by gender into a 40×40 = 1600-pair space per gender; expected collisions are ~0.12 per gender,
so the mutant leaves the test green roughly **four times in five**. A falsification that is a
coin flip teaches nothing.

Use a shaped pool instead. Add this test alongside the others:

```python
def test_pairs_are_distinct_on_a_pool_where_collisions_are_forced(monkeypatch):
    """The distinctness mutant is only visible on a CRAMPED pool AND A SEED THAT
    ACTUALLY COLLIDES.

    ⚠️ THE SEED IS LOAD-BEARING — re-verify it if these pools change. `count` has
    to be 4, not 40, because the pre-check `min(len(...)) < count` fires first;
    and at count=4 only about a third of seeds collide at all (98 of the first
    300). `Random(5)` is one of the two-thirds that do NOT: with and without the
    retry loop it yields the identical
    [('C','W'), ('B','W'), ('A','Y'), ('B','Z')], so the mutant would be a
    guaranteed false green.

    `Random(1)` is verified to collide: with the loop it draws four distinct
    pairs; without it, ('D','Z') twice.
    """
    from demo import names

    for attr in ("FEMININE_GIVEN", "MASCULINE_GIVEN"):
        monkeypatch.setattr(names, attr, ("A", "B", "C", "D"))
    for attr in ("FEMININE_SURNAMES", "MASCULINE_SURNAMES"):
        monkeypatch.setattr(names, attr, ("W", "X", "Y", "Z"))

    drawn = names.draw_names(random.Random(1), 4)  # 4 <= 4: pre-check passes
    assert len(set(drawn)) == 4
```

Then remove the `while` loop and re-run.

Expected: `test_pairs_are_distinct_on_a_pool_where_collisions_are_forced` FAILS, with
`('D', 'Z')` drawn twice. ⚠️ If it PASSES, **check the seed before checking the code** — at
`count=4` only ~1 seed in 3 collides, and an earlier draft of this step used `Random(5)`, which
produces byte-identical output either way. **Revert by hand** — do not `git checkout`, which
would take the whole file with it.

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
`parse_numeric_value` and `canonical_numeric_text` live in **`courses/marking.py`** (lines 128
and 169). There is no `courses/numeric.py`; importing one is a `ModuleNotFoundError` on the
first `import demo.builders`, which every task from here on depends on.
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
    for text in ("r1", "r2"):
        # ⚠️ ROWS USE `statement`, COLUMNS USE `label`. GridRow (courses/models.py:2818)
        # and MultiGridRow (:2905) declare `statement`; only the *Column models
        # have `label`. Passing label= is a TypeError that kills the whole module
        # before a single assertion runs.
        GridRow.objects.create(question=cg, statement=text, correct_column=cols[0])
    made.append(cg)

    mg = MultiGridQuestionElement.objects.create(
        stem="MultiGrid", marking_mode=QuestionElement.MarkingMode.AUTO,
        max_marks=Decimal("1"),
    )
    # `label`, not `l`: ruff selects E, and E741 rejects `l` as a binding name.
    # tests/** only ignores S105/S106/S107.
    mcols = [
        MultiGridColumn.objects.create(question=mg, label=label)
        for label in ("a", "b", "c")
    ]
    for text in ("r1", "r2"):
        row = MultiGridRow.objects.create(question=mg, statement=text)  # statement, not label
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


def test_the_wrong_text_pool_covers_the_variant_count():  # no django_db: constants only
    """WRONG_TEXTS is the pool _shorttext and _fillblank draw from, and
    WRONG_VARIANTS is how many variants every builder may return. Today both are
    3 and the relationship is only a COMMENT — raise WRONG_VARIANTS to 4 and
    every text-shaped question silently caps at three with no warning. Same shape
    as the MAX_PUPILS / name-pool coupling; derived, never a `== 3` pin."""
    from demo.constants import WRONG_TEXTS, WRONG_VARIANTS

    assert len(WRONG_TEXTS) >= WRONG_VARIANTS
    assert len(set(WRONG_TEXTS)) == len(WRONG_TEXTS)


def test_every_question_type_is_classified():
    """T6 — derived, never a len(...) == N pin. A new question type fails until
    someone puts it in the registry or in UNANSWERABLE_QUESTION_TYPES.

    No `django_db`: this walks `__subclasses__` and touches no row. Same rule as
    Task 6 Step 4a's warning-kind test — don't pay for a database you never use."""
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
def test_numeric_wrong_answers_are_decimal_text_not_fractions():
    """A pupil types "5.5", never "11/2". parse_numeric_value returns a Fraction
    and canonical_numeric_text deliberately PRESERVES fraction form, so the naive
    str()/canonicalise route stores "11/2" for every non-integer row — which is
    most of mat-pp."""
    from decimal import Decimal

    from courses.models import QuestionElement, ShortNumericQuestionElement
    from demo import builders

    q = ShortNumericQuestionElement.objects.create(
        stem="half?", value="4.5", tolerance="0",
        marking_mode=QuestionElement.MarkingMode.AUTO, max_marks=Decimal("1"),
    )
    answers = builders.build(q)
    assert answers.correct == "4.5"
    for variant in answers.wrong:
        assert "/" not in variant, variant
        assert q.mark(variant).fraction == 0.0


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

from decimal import Decimal
from fractions import Fraction
from typing import NamedTuple

# ⚠️ ALPHABETICAL: courses.marking BEFORE courses.models. I001 checks ordering,
# not only splitting, and an earlier draft had marking stranded below models.
#
# ⚠️ courses/numeric.py DOES NOT EXIST. The parser lives in courses/marking.py,
# and it is the same one ShortNumericQuestionElement.mark uses
# (courses/models.py:2567) — which is the only reason our "correct" answer marks
# 1.0. (canonical_numeric_text is deliberately NOT imported: it preserves
# fraction form rather than converting it — see _decimal_text below.)
from courses.marking import parse_numeric_value
from courses.models import (
    ChoiceGridQuestionElement, ChoiceQuestionElement,
    DragFillBlankQuestionElement, DragToImageQuestionElement,
    ExtendedResponseQuestionElement, FillBlankQuestionElement,
    MatchPairQuestionElement, MultiGridQuestionElement,
    ShortNumericQuestionElement, ShortTextQuestionElement, _accepted_lines,
)
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
    tol = parse_numeric_value(q.tolerance)
    # Explicit `is None`, NOT `... or Fraction(0)`: Fraction(0) is falsy, so the
    # `or` form is right only by accident. courses/models.py:2570 carries this
    # exact comment about this exact expression — do not reintroduce the form it
    # rejects.
    if tol is None:
        tol = Fraction(0)
    upper = want + tol  # mark() is abs(got - want) <= tol — ABSOLUTE tolerance
    # DECIMAL TEXT, never str(Fraction): a row with value="4.5" would otherwise
    # store every pupil's answer as "9/2" — it marks correct, but PR 5's
    # per-question view shows the rep an answer no pupil would type.
    # ⚠️ canonical_numeric_text DOES NOT DO THIS FOR YOU. It deliberately
    # PRESERVES structural form and does not reduce fractions
    # (courses/marking.py:178-181: "an author who writes 6/4 reopens the editor
    # and sees 6/4"), so canonical_numeric_text("9/2") is "9/2". Divide through
    # Decimal first; that is what actually produces decimal text.
    wrong = [_decimal_text(upper + n) for n in (1, 2, 3)][:WRONG_VARIANTS]
    return Answers(q.value, wrong, None)


def _decimal_text(value):
    """A Fraction as the decimal a pupil would type. `format(..., "f")` avoids
    scientific notation; normalize() trims the trailing zeros Decimal division
    leaves behind."""
    quotient = Decimal(value.numerator) / Decimal(value.denominator)
    return format(quotient.normalize(), "f")


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
    # No `len(correct[0]) >= 1` conjunct: the `any(not sets ...)` guard above
    # already returned None for an empty row, so it is always true. What actually
    # decides between the two constructions below is whether row 0 has >= 2
    # correct columns (drop one) or exactly 1 (swap in a wrong one).
    if len(rows) >= 2:
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

Expected: PASS (five tests). ⚠️ If `test_every_question_type_is_classified` fails, a question
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

⚠️ **Accepted consequence: the demo's "awaiting review" queue is structurally empty.**
`pending_reviews_for` (`courses/review.py:236`) returns two lists — `in_progress` and
`awaiting` (submitted work holding an unreviewed REVIEW response). Because the pass skips
**any quiz containing a REVIEW question, whole**, no kit can ever produce an `awaiting` row.
Task 9 fills the `in_progress` half only. This is a deliberate trade — writing a plausible
extended-response answer is the thing the builders explicitly refuse to guess at — but it
means **PR 3 and PR 4 must not advertise teacher marking as part of the demo**. If a school
rep asks to see marking, that is a follow-up: write one pupil an unreviewed REVIEW response
rather than skipping the quiz. Recorded again in "Deliberately NOT in this plan".

**Files:**
- Create: `demo/warnings.py`, `demo/content.py`
- Test: `tests/demo/test_content.py`

**Interfaces:**
- Produces:
  - `demo.warnings.DemoWarning` — `@dataclass(frozen=True)` with fields `(kind, unit_id,
    reason)` and a validating `__post_init__`; `unit_id` may be `None`. **A frozen dataclass,
    not a NamedTuple** — see Step 4. **Named `DemoWarning` at the definition, not
    `Warning`** — the bare name shadows the builtin exception base, which is why two of the
    three consumers were already aliasing it on import while the third did not. One spelling
    everywhere.
  - `demo.warnings.KINDS` — the closed `frozenset`; `demo.warnings.DISPLAY` — `dict[kind,
    lazy str]`.
  - `demo.content.QuestionPlan` — `NamedTuple(element_id, max_marks, answers, fractions,
    gradeable, sentinel)` where `fractions` maps `("correct" | index | "partial") -> float`.
    **Six fields.** `demo/generator.py` reads `qplan.max_marks`, `qplan.gradeable` and
    `qplan.sentinel`; there is no `partial_ok` field anywhere in this plan — a Task 7/8
    implementer building against a four-field shape writes code that cannot run.
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
    from demo import builders
    from demo.content import build_course_plan
    from tests.demo.fixtures import small_course

    course = small_course()
    plan = build_course_plan(course)

    assert plan.units, "published units in pre-order"
    saw_sentinel = False
    for unit_id, questions in plan.questions.items():
        for q in questions:
            assert q.fractions["correct"] == 1.0
            if q.sentinel:
                # NO_WRONG_ANSWER is a bare sentinel object with no __len__, so
                # len() below would raise TypeError — turning a content
                # regression into an unrelated crash the moment the fixture
                # grows an all-correct question.
                assert q.answers.wrong is builders.NO_WRONG_ANSWER
                saw_sentinel = True
                continue
            for i in range(len(q.answers.wrong)):
                assert q.fractions[i] == 0.0
    assert saw_sentinel, (
        "the fixture must carry a sentinel question (see 'All-correct quiz')"
    )
    # The NOT_MARKED branch must be REACHABLE, not merely present in the fixture.
    # A row whose builder returns None is dropped by build_course_plan and never
    # becomes a QuestionPlan, which silently kills every gradeable=False code
    # path downstream.
    assert any(
        not q.gradeable for qs in plan.questions.values() for q in qs
    ), "no QuestionPlan has gradeable=False — see 'Notes quiz' in the fixture"


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
def test_a_quiz_with_no_gradeable_question_is_excluded_and_warned():
    """The PLAN half only — nothing here touches QuizSubmission (the name used to
    promise that and deliver it in a different task). The submission half is
    Task 8's `test_a_skipped_quiz_receives_no_submission`.

    ⚠️ ONE kind, not an `or` of two. A prose-only quiz never enters the
    question loop, so `skip_reason` stays None and the old `or` form asserted on
    two kinds that this fixture cannot produce — it failed on correct code. The
    `no_gradeable_question` branch added in Step 5 is what makes it pass."""
    from demo.content import build_course_plan
    from tests.demo.fixtures import small_course

    course = small_course(quiz_without_questions=True)
    plan = build_course_plan(course)

    assert plan.answerable_quizzes, "the good quizzes survive"
    empty = [u for u in plan.units if u.title == "Prose-only quiz"][0]
    assert empty.pk not in {u.pk for u in plan.answerable_quizzes}
    assert ("no_gradeable_question", empty.pk) in {
        (w.kind, w.unit_id) for w in plan.warnings
    }


@pytest.mark.django_db
def test_a_quiz_holding_a_review_question_is_skipped_WHOLE():
    """R3's headline rule, and the ONLY test that drives skip_reason.

    ⚠️ The skip is per-UNIT, never per-question: "Reviewed quiz" also holds a
    perfectly good choice question, and it must NOT survive on its own. This is
    also the path that makes the awaiting-review queue structurally empty (see
    this task's preamble) — so if this test ever starts failing because the skip
    was narrowed to the offending question, that consequence changed too.
    """
    from demo.content import build_course_plan
    from tests.demo.fixtures import small_course

    course = small_course(quiz_with_review_question=True)
    plan = build_course_plan(course)

    reviewed = [u for u in plan.units if u.title == "Reviewed quiz"][0]
    assert reviewed.pk in plan.skipped_quiz_ids
    assert reviewed.pk not in {u.pk for u in plan.answerable_quizzes}
    assert reviewed.pk not in plan.questions, "a skipped quiz gets NO question list"

    warning = [w for w in plan.warnings if w.unit_id == reviewed.pk]
    assert [w.kind for w in warning] == ["quiz_skipped"]
    assert "REVIEW" in warning[0].reason

    # The good quizzes are untouched — the skip is scoped to the one unit.
    assert plan.answerable_quizzes
```

- [ ] **Step 2: Write the shared fixture builder**

`tests/demo/fixtures.py` — the `small` fixture from the spec's inventory. It deliberately
breaks two coincidences: element `order` must disagree with `pk`, and a later part's units are
created first, so `pk` order is not pre-order.

```python
"""Fixture courses for the demo tests. `small` is the default.

It carries seven deliberate properties, each pinned by an assertion somewhere:
  * part B is CREATED FIRST, so pre-order != pk order;
  * "Late quiz"'s TWO questions sort against pk order, so the (unit, ordinal)
    keys move if `_top_level_questions` drops its explicit `order_by`. (quiz_b's
    prose/question swap also disagrees with pk, but quiz_b holds only ONE
    question, so no test can observe it — keep both, rely on this one.)
  * a 3-wrong-variant choice question, for T28;
  * a LATE multi-question quiz past every reachable depth, so
    `in_progress_candidates` is non-empty for Task 9;
  * an ALL-CORRECT choice question, so the NO_WRONG_ANSWER sentinel branch is
    exercised;
  * a NOT_MARKED question sharing "Notes quiz" with a graded one, so the
    no-fraction branch is exercised;
  * a TWO-BLANK fill-blank question IN PART A, the only partial-capable row —
    without it the whole partial half of _pick_answer is dead in every
    end-to-end test, and its POSITION matters as much as its existence (see the
    comment at its creation).
Change any of them and read the assertions that name them before you do."""

from decimal import Decimal

from courses.models import (
    Blank, Choice, ChoiceQuestionElement, ContentNode, Course, Element,
    FillBlankQuestionElement, QuestionElement, ShortNumericQuestionElement,
    ShortTextQuestionElement, TextElement,
)


def _unit(course, parent, title, unit_type, *, obligatory=True, published=True):
    return ContentNode.objects.create(
        course=course, parent=parent, kind="unit", title=title,
        unit_type=unit_type, obligatory=obligatory, published=published,
    )


def _choice_question(
    unit, *, correct="2", options=("2", "3", "4", "6"), all_correct=False
):
    q = ChoiceQuestionElement.objects.create(
        stem="pick", marking_mode=QuestionElement.MarkingMode.AUTO,
        max_marks=Decimal("1"), multiple=all_correct,
    )
    for text in options:
        Choice.objects.create(
            question=q, text=text, is_correct=all_correct or (text == correct)
        )
    return Element.objects.create(unit=unit, content_object=q)


def small_course(
    *, slug="small", lesson_with_unanswerable_selfcheck=False,
    quiz_without_questions=False, quiz_with_review_question=False,
):
    """⚠️ `slug` is a PARAMETER because `Course.slug` is `unique=True`
    (courses/models.py:127). Any test that needs two courses in one transaction —
    Task 10 Step 6's scaling test is the one — must pass a distinct slug for the
    second, or the create raises IntegrityError.
    (Note the separate rule in Task 13: for comparing two KITS, build ONE course
    and provision twice. Two courses there would compare disjoint row sets.)"""
    course = Course.objects.create(slug=slug, title="Small", language="pl")
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

    # THE PARTIAL-CAPABLE QUESTION, and it must live IN PART A — inside every
    # band's reach. _fillblank returns a partial whenever there are >= 2 blanks,
    # and this is the only such row in the fixture: without it `_pick_answer`'s
    # partial branch, P_PARTIAL_GIVEN_WRONG, the content pass's partial
    # validation and the `partial_fallback` warning are dead in every end-to-end
    # test, and Task 13's draw-order mutant (which moves the partial draw) cannot
    # turn the golden test red.
    #
    # ⚠️ POSITION IS THE WHOLE POINT. Parked at the END of Part B it sat near the
    # tail of the outline, while the depth bands reach roughly 8-9 (struggling),
    # 11-13 (average) and 13-15 (strong) — so a 20-pupil class answered it at all
    # only ~55% of the time, and the partial assertion held maybe 1 run in 40.
    # Here it is in Part A, below the SHALLOWEST depth any band can produce:
    #     round(floor(0.75 * len(plan.units)) * 0.70 * 0.92)
    # The fixture currently builds 18 published units (9 under each part), giving
    # a floor of 8 against this quiz's index of 7. ⚠️ RE-DERIVE FROM THE
    # EXPRESSION, never from the numbers — they move whenever a unit is added.
    # Task 9's first test derives the same floor and asserts a candidate survives.
    fb_quiz = _unit(course, part_a, "Blanks quiz", "quiz")
    fb = FillBlankQuestionElement.objects.create(
        stem="2 + {{2}} = {{4}}",
        marking_mode=QuestionElement.MarkingMode.AUTO, max_marks=Decimal("2"),
    )
    Blank.objects.create(question=fb, accepted="2")
    Blank.objects.create(question=fb, accepted="4")
    Element.objects.create(unit=fb_quiz, content_object=fb)
    _choice_question(fb_quiz, correct="4")  # a second question, so it is 2-deep
    for i in range(6):
        _unit(course, part_b, f"B lesson {i}", "lesson")
    quiz_b = _unit(course, part_b, "B quiz", "quiz")
    q = ShortNumericQuestionElement.objects.create(
        stem="2+2?", value="4", tolerance="0",
        marking_mode=QuestionElement.MarkingMode.AUTO, max_marks=Decimal("1"),
    )
    question_el = Element.objects.create(unit=quiz_b, content_object=q)
    prose = Element.objects.create(
        unit=quiz_b, content_object=TextElement.objects.create(body="<p>hi</p>")
    )
    # ELEMENT ORDER MUST DISAGREE WITH PK.
    # ⚠️ Element.order is an OrderField(for_fields=["unit"]) that AUTO-ASSIGNS on
    # create: the question gets 0 and the prose gets 1. Setting prose to 0 alone
    # makes BOTH 0, and `order_by("order", "pk")` then breaks the tie on pk —
    # yielding exactly pk order, so the mutant this is supposed to catch
    # (dropping the explicit order_by) stays green. Swap them properly: the prose
    # must sort FIRST while holding the HIGHER pk.
    prose.order = 0
    prose.save(update_fields=["order"])
    question_el.order = 1
    question_el.save(update_fields=["order"])
    assert prose.pk > question_el.pk, "the fixture's own property, pinned"

    # A LATE, MULTI-QUESTION QUIZ. Without it `in_progress_candidates` holds only
    # "A quiz", while _usable_target's `position <= depth` rejects anything at or
    # below the SHALLOWEST depth any band can produce —
    # round(floor(0.75 * len(units)) * 0.70 * 0.92). (Compute it from the fixture
    # rather than trusting a literal here: units get added and the number moves.
    # Task 9's first test derives it and asserts a candidate survives.) With no
    # surviving candidate, `chosen` is always empty and Task 9's review-queue
    # test fails on correct code.
    late_quiz = _unit(course, part_b, "Late quiz", "quiz")
    late_a = _choice_question(late_quiz)
    late_b = _choice_question(late_quiz, correct="3")
    # ELEMENT ORDER MUST DISAGREE WITH PK **IN A UNIT THAT HAS TWO QUESTIONS**.
    # ⚠️ quiz_b's prose/question swap below is NOT enough on its own:
    # _top_level_questions filters down to QuestionElements, and quiz_b holds
    # exactly one, so its ordinal is 0 whatever the queryset order — dropping
    # `.order_by("order", "pk")` would leave every test AND the golden file green.
    # Swapping these two makes the (unit, ordinal) keys in the golden projection
    # actually change under that mutant.
    late_a.order, late_b.order = 1, 0
    late_a.save(update_fields=["order"])
    late_b.save(update_fields=["order"])
    assert late_b.pk > late_a.pk, "the later-created question must sort FIRST"

    # A NOT_MARKED question, sharing a quiz with a graded one. The generator
    # writes it an ANSWER but NO fraction (courses/views.py does the same), and
    # compute_scores ignores it — so without this row that whole branch is
    # untested and nothing stops the generator stamping 1.0 on ungraded work.
    notes_quiz = _unit(course, part_a, "Notes quiz", "quiz")
    _choice_question(notes_quiz, correct="3")
    # ⚠️ `accepted` MUST BE NON-EMPTY. `_accepted_lines` (courses/models.py:2465)
    # drops blank lines, so accepted="" yields [] and `_shorttext` returns None —
    # build_course_plan then takes the `question_dropped` branch and the row never
    # becomes a QuestionPlan at all. The effect is worse than a missing fixture:
    # `gradeable=False` becomes UNREACHABLE plan-wide, so _pick_answer's
    # `not qplan.gradeable` early-out and _answer_quiz's `if qplan.gradeable else
    # None` — the branch that stops the generator stamping 1.0 on [N] questions —
    # are dead code that every test leaves green.
    unmarked = ShortTextQuestionElement.objects.create(
        stem="Your own notes?", accepted="cokolwiek",
        marking_mode=QuestionElement.MarkingMode.NOT_MARKED, max_marks=Decimal("0"),
    )
    Element.objects.create(unit=notes_quiz, content_object=unmarked)

    # A SENTINEL question: every option correct, so _choice finds no wrong pick
    # and build() returns NO_WRONG_ANSWER. Exercises the sentinel branch in
    # build_course_plan and in _pick_answer, which no other fixture row reaches.
    sentinel_quiz = _unit(course, part_b, "All-correct quiz", "quiz")
    _choice_question(sentinel_quiz, correct=None, options=("2", "3"), all_correct=True)

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

    if quiz_with_review_question:
        # R3's WHOLE-QUIZ SKIP — the one path nothing else drives.
        # ⚠️ The ExtendedResponse in `lesson_with_unanswerable_selfcheck` is in a
        # LESSON (deliberately: R3 is quiz-only), and `quiz_without_questions`
        # exits via `no_gradeable_question`, not via skip_reason. So without this
        # flag `plan.skipped_quiz_ids` is EMPTY in every test, no test ever sees a
        # `quiz_skipped` warning, and the rule that fires constantly on real
        # mat-pp — and that makes the awaiting-review queue structurally empty —
        # ships with zero positive coverage.
        from courses.models import ExtendedResponseQuestionElement

        reviewed = _unit(course, part_b, "Reviewed quiz", "quiz")
        _choice_question(reviewed)  # a GOOD question, so the skip is whole-unit
        er = ExtendedResponseQuestionElement.objects.create(
            stem="explain", marking_mode=QuestionElement.MarkingMode.REVIEW,
            max_marks=Decimal("5"),
        )
        Element.objects.create(unit=reviewed, content_object=er)

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

Named DemoWarning, NOT Warning: the bare name shadows the builtin exception
base, and all three consumers spell it the same way here rather than two of them
aliasing it on import.
"""

from dataclasses import dataclass

from django.utils.translation import gettext_lazy as _


@dataclass(frozen=True)
class DemoWarning:
    """⚠️ A frozen dataclass, NOT a NamedTuple.

    `typing.NamedTuple` lists `__new__` in its `_prohibited` set, so defining one
    raises `AttributeError: Cannot overwrite NamedTuple attribute __new__` at
    CLASS-CREATION time — `import demo.warnings` fails, and with it every module
    from Task 6 onward. (Verified under this repo's interpreter.) A frozen
    dataclass validates in `__post_init__` instead, and the consumers only ever
    use attribute access (`w.kind`, `w.unit_id`, `w.reason`) plus equality, all
    of which it provides.
    """

    kind: str
    unit_id: int | None  # `X | None`, never Optional[X]: ruff UP045 at py313
    reason: str

    def __post_init__(self):
        # THIS is what makes KINDS a closed set. Without it `DemoWarning("quiz_skiped",
        # ...)` is accepted everywhere, survives Task 15's `set(DISPLAY) == KINDS`
        # test (which only compares the map with itself), and surfaces as a
        # KeyError in PR 3's template months later.
        if self.kind not in KINDS:
            raise ValueError(f"unknown warning kind {self.kind!r}; add it to DISPLAY")


DISPLAY = {
    "quiz_skipped": _("Quiz skipped: it holds a question the demo cannot answer."),
    "question_dropped": _("An unmarked question was left unanswered."),
    "variant_dropped": _("A wrong-answer variant failed validation."),
    "sentinel_answered": _("A question has no usable wrong answer; all pupils answer it correctly."),
    "partial_fallback": _("A partial answer failed validation; the wrong answer is used."),
    "fewer_in_progress_than_target": _("Fewer unfinished quizzes than intended."),
    "no_qualifying_pupil": _("No pupil could be left with an unfinished quiz; the review queue will be empty."),
    "active_webhook_endpoint": _("A webhook endpoint is enabled: demo data will be sent to it."),
    "no_gradeable_question": _("Quiz skipped: it holds no question the demo can grade."),
    "correct_answer_rejected": _("A question's own correct answer did not mark full marks; the quiz was skipped."),
}

KINDS = frozenset(DISPLAY)
```

⚠️ `KINDS` is defined AFTER `DISPLAY` but referenced inside `__post_init__`, which only runs at
call time — that is fine. It is **not** fine to move the class below a `KINDS` reference at
module scope.

- [ ] **Step 4a: Prove the closed set is actually closed**

Add to `tests/demo/test_content.py` (this task's own file — `test_boundaries.py` does not exist
until Task 15, and the validation should be pinned in the commit that introduces it):

```python
def test_an_unknown_warning_kind_is_refused():
    """Without this, __post_init__ could be deleted and every other test stays
    green — Task 15's `set(DISPLAY) == KINDS` only compares the map with itself.
    No django_db mark: this touches no database."""
    from demo.warnings import DemoWarning

    with pytest.raises(ValueError):
        DemoWarning("quiz_skiped", None, "typo")

    DemoWarning("quiz_skipped", None, "the correctly spelled one")  # must not raise
```

- [ ] **Step 4b: Put the display strings in the Polish catalog**

`makemessages` extracts **eleven** new msgids here: these ten `DISPLAY` strings **plus
`_("Revoked")` from `demo/models.py`'s `ClosedReason`**, which Task 2 introduced two tasks ago
and which has no entry in the catalog. (`_("Expired")` is already translated at
`locale/pl/LC_MESSAGES/django.po:133`.) The operator-facing surface is Polish, so none of them
can ship untranslated:

```bash
uv run python manage.py makemessages -l pl
# transcribe the msgstr values below into locale/pl/LC_MESSAGES/django.po
uv run python manage.py compilemessages
```

**The eleven `msgstr` values — transcribe, do not invent.** `compilemessages` makes them
permanent, so leaving an implementer to draft eleven operator-facing Polish strings unaided is
the one step in this plan whose output quality would be unspecified:

```po
msgid "Quiz skipped: it holds a question the demo cannot answer."
msgstr "Pominięto quiz: zawiera pytanie, na które demo nie potrafi odpowiedzieć."

msgid "Quiz skipped: it holds no question the demo can grade."
msgstr "Pominięto quiz: nie zawiera pytania, które demo potrafi ocenić."

msgid "An unmarked question was left unanswered."
msgstr "Pytanie nieoceniane pozostało bez odpowiedzi."

msgid "A wrong-answer variant failed validation."
msgstr "Wariant błędnej odpowiedzi nie przeszedł walidacji."

msgid "A question has no usable wrong answer; all pupils answer it correctly."
msgstr "Pytanie nie ma użytecznej błędnej odpowiedzi; wszyscy uczniowie odpowiadają na nie poprawnie."

msgid "A partial answer failed validation; the wrong answer is used."
msgstr "Odpowiedź częściowa nie przeszła walidacji; użyto błędnej odpowiedzi."

msgid "A question's own correct answer did not mark full marks; the quiz was skipped."
msgstr "Poprawna odpowiedź pytania nie uzyskała pełnej punktacji; quiz został pominięty."

msgid "Fewer unfinished quizzes than intended."
msgstr "Mniej nieukończonych quizów niż zakładano."

msgid "No pupil could be left with an unfinished quiz; the review queue will be empty."
msgstr "Żaden uczeń nie mógł zostać z nieukończonym quizem; kolejka do sprawdzenia będzie pusta."

msgid "A webhook endpoint is enabled: demo data will be sent to it."
msgstr "Webhook jest włączony: dane demo zostaną do niego wysłane."

msgid "Revoked"
msgstr "Cofnięte"
```

⚠️ **`"Cofnięte"`, not `"Cofnięty"` — it has to agree with its neighbour.** `_("Expired")` is
already translated at `django.po:133` as **`"Wygasłe"`** (neuter, written for invitation
statuses), and PR 3's tab renders the two `ClosedReason` labels side by side. `"Wygasłe"` next
to a masculine `"Cofnięty"` reads as a bug in the operator UI. If PR 3's column heading implies
a different noun, change **both** together rather than one.

⚠️ These are a starting draft by a non-native writer — **read them before committing**, since
they are what a school representative's operator sees.

⚠️ **Check for `#, fuzzy` entries before you compile.** The catalog currently has zero. If
`makemessages` pre-fills one from a similar string it is almost certainly the WRONG
translation, and clearing it takes **two** deletions — the `#, fuzzy` line *and* the wrong
`msgstr`. `grep -c "#, fuzzy" locale/pl/LC_MESSAGES/django.po` must still be 0 when you are
done.

⚠️ Commit the `.po` **and** the binary `.mo` in the same commit as `demo/warnings.py` (Step 8's
`git add` includes both), and regenerate the `.mo` after any rebase — a stale branch conflicts
on the binary and the conflict cannot be resolved by hand.

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
from demo.warnings import DemoWarning


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
    """R9: the set compute_scores and the review gate use.

    The explicit order_by RESTATES `Element.Meta.ordering = ["order", "pk"]`
    (courses/models.py:346). It is not what makes the queryset ordered — Meta
    already does — so removing it changes nothing today. It is here so that a
    future Meta change cannot silently move every ordinal in the golden file:
    determinism depends on this key, and the dependency should be visible at the
    only place that reads it.

    ⚠️ Do not "simplify" it away on the grounds that it is redundant. And note
    that the falsifying mutant is `.order_by()` (the no-arg form, which CLEARS
    Meta.ordering) or `.order_by("pk")` — dropping the call entirely is a no-op.
    """
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
                    warns.append(DemoWarning("question_dropped", unit.pk, type(q).__name__))
                    continue
                skip_reason = f"{type(q).__name__} has no builder"
                break
            answers = builders.build(q)
            if answers is None:
                if not_marked:
                    warns.append(DemoWarning("question_dropped", unit.pk, "row unanswerable"))
                    continue
                skip_reason = f"{type(q).__name__} row is unanswerable"
                break

            correct_fraction = q.mark(answers.correct).fraction
            # THE CORRECT ANSWER IS VALIDATED TOO, not just the variants and the
            # partial. Otherwise a real mat-pp row shaped unlike our seven
            # fixtures can hand back an answer that marks 0.4, and every pupil in
            # the kit stores it as their "correct" response at fraction 0.4 —
            # silently, with no warning and no skip. Task 5's honest-builder test
            # catches that for the FIXTURES; this catches it for the course.
            if correct_fraction != 1.0:
                if not_marked:
                    warns.append(
                        DemoWarning("question_dropped", unit.pk, "correct answer marked "
                                    f"{correct_fraction}")
                    )
                    continue
                warns.append(
                    DemoWarning("correct_answer_rejected", unit.pk,
                                f"{type(q).__name__} marked {correct_fraction}")
                )
                skip_reason = f"{type(q).__name__}'s correct answer marked {correct_fraction}"
                break

            fractions = {"correct": correct_fraction}
            sentinel = answers.wrong is builders.NO_WRONG_ANSWER
            surviving = []
            if not sentinel:
                for variant in answers.wrong:
                    f = q.mark(variant).fraction
                    if f == 0.0:
                        fractions[len(surviving)] = f
                        surviving.append(variant)
                    else:
                        warns.append(DemoWarning("variant_dropped", unit.pk, str(f)))
                if not surviving:
                    sentinel = True
            if sentinel:
                warns.append(DemoWarning("sentinel_answered", unit.pk, type(q).__name__))
                answers = builders.Answers(answers.correct, builders.NO_WRONG_ANSWER, None)
            else:
                answers = builders.Answers(answers.correct, surviving, answers.partial)

            if answers.partial is not None:
                pf = q.mark(answers.partial).fraction
                if 0 < pf < 1:
                    fractions["partial"] = pf
                else:
                    warns.append(DemoWarning("partial_fallback", unit.pk, str(pf)))
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
            warns.append(DemoWarning("quiz_skipped", unit.pk, skip_reason))
            continue
        questions[unit.pk] = plans
        if gradeable_n:
            answerable.append(unit)
            if answerable_n >= 2:
                candidates.append(unit)
        else:
            # A quiz that reached here with nothing gradeable — a prose-only quiz
            # never enters the loop at all, so skip_reason is None and this is the
            # ONLY place it can be reported. Without this branch the kit silently
            # contains a quiz no pupil will ever have a score for, and the
            # operator is never told.
            warns.append(
                DemoWarning("no_gradeable_question", unit.pk, f"{len(plans)} question(s)")
            )

    return CoursePlan(units, skipped, answerable, candidates, questions, warns)
```

- [ ] **Step 6: Run the tests**

```bash
uv run pytest tests/demo/test_content.py tests/test_i18n_po_health.py -v
```

Expected: PASS (five demo tests, plus the catalog health guards). ⚠️ `test_i18n_po_health.py`
is the real check behind Step 4b's fuzzy warning — `test_no_fuzzy_entries`,
`test_no_obsolete_entries` and `test_pl_has_no_untranslated_msgid` run against the actual
catalogs, so a blank `msgstr` or a `makemessages` fuzzy pre-fill fails here rather than
shipping.

- [ ] **Step 7: Falsify the quiz-only scope and the whole-unit skip**

Two mutants, reverting each by hand:

1. Narrow the skip to the offending question — replace the REVIEW branch's
   `skip_reason = …; break` with a bare `continue`.
   Expected: `test_a_quiz_holding_a_review_question_is_skipped_WHOLE` FAILS — the quiz
   survives on its good choice question. This is the mutant that matters: a per-question skip
   looks more useful and quietly changes what R3 means.
2. Delete the `if unit.unit_type != "quiz": continue` guard and re-run.

Expected: `test_a_lesson_with_an_unanswerable_self_check_is_never_skipped` FAILS. **Revert by
hand.**

- [ ] **Step 7b: Pin the element ordering here; falsify it in Task 13**

`tests/demo/test_content.py` cannot see an ordering change on its own, so add this assertion
to `test_plan_caches_fractions_and_skips_only_quizzes`:

```python
    # The (unit, ordinal) keys the golden file is built from. "Late quiz"'s two
    # questions were created in one order and given the OPPOSITE `order`, so this
    # is the one place the plan's ordering is observable.
    late = [u for u in plan.units if u.title == "Late quiz"][0]
    ids = [q.element_id for q in plan.questions[late.pk]]
    assert ids == sorted(ids, reverse=True), "element order must not be pk order"
```

The falsification belongs with the golden test, not here — see **Task 13 Step 4b**. (An
earlier draft told you to run it at this point "once Task 13 exists", which no step ever
returned to do.)

- [ ] **Step 8: Commit**

```bash
git add demo/content.py demo/warnings.py tests/demo/test_content.py tests/demo/fixtures.py
# The catalog, per Step 4b — the .po AND the binary .mo, or the PR ships eleven
# untranslated msgids and the "regenerate after rebase" warning has nothing to act on.
git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo
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
  - `demo.generator.frontier_index(plan, frontier_part, course) -> int` — **`course` is
    required**, not an optional trailing argument: when `frontier_part is not None` the body
    does `course.nodes.filter(...)`, so the two-argument form raises `AttributeError:
    'NoneType' object has no attribute 'nodes'`. Both call sites (Task 8's `generate`, Task
    15's boundary test) pass all three.
  - `demo.generator.pupil_depth(rng, band, frontier, unit_count=None) -> int` — consumes
    exactly one draw.

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


@pytest.mark.parametrize(
    "pupils,strong,struggling,average",
    [(15, 3, 3, 9), (18, 3, 3, 12)],
)
def test_the_partition_is_integer_arithmetic_off_the_share_constants(
    pupils, strong, struggling, average
):
    """FLOOR, not half-up rounding. 18 is the load-bearing case: `18 * 20 // 100`
    is 3 while `round(18 * 20 / 100)` is 4, so it separates the integer form from
    the rounding mutant. 15 alone does not — see Step 5."""
    bands = generator.assign_bands(random.Random(1), pupils)
    assert bands.count(STRONG) == strong
    assert bands.count(STRUGGLING) == struggling
    assert bands.count(AVERAGE) == average


def test_every_band_is_populated_at_the_minimum_pupil_count():
    from demo.constants import MIN_PUPILS

    bands = generator.assign_bands(random.Random(1), MIN_PUPILS)
    assert set(bands) == {STRONG, AVERAGE, STRUGGLING}


def test_bands_are_deterministic_for_a_seed():
    assert generator.assign_bands(random.Random(9), 20) == generator.assign_bands(
        random.Random(9), 20
    )


@pytest.mark.parametrize("band", [STRONG, AVERAGE, STRUGGLING])
def test_depth_scales_with_the_band(band):
    """Bounds are DERIVED from the constants, never hard-coded.

    ⚠️ The hard-coded version of this test (70-90 / 61-78 / 42-55) failed on
    correct code: with frontier=75 the true ceilings are round(75*1.15*1.08)=93,
    round(75*1.00*1.08)=81 and round(75*0.70*1.08)=57. Deriving them also means a
    JITTER or multiplier change cannot leave the test asserting a stale window.
    """
    from demo.constants import BANDS, JITTER

    frontier = 75
    centre = frontier * BANDS[band]["depth"]
    lo, hi = round(centre * (1 - JITTER)), round(centre * (1 + JITTER))
    depths = [generator.pupil_depth(random.Random(s), band, frontier) for s in range(50)]
    assert all(lo <= d <= hi for d in depths), (min(depths), max(depths), lo, hi)
    # A guard: 50 seeds must actually spread, or the bounds check is vacuous.
    assert len(set(depths)) > 1


def test_the_bands_are_separated_at_the_same_frontier():
    """What the parametrised test above CANNOT see: it checks each band against
    its own window, so a build where every band used the AVERAGE multiplier
    passes all three. This pins the ordering between them."""
    from demo.constants import BANDS

    frontier = 75
    centres = {
        b: round(frontier * BANDS[b]["depth"]) for b in (STRONG, AVERAGE, STRUGGLING)
    }
    assert centres[STRUGGLING] < centres[AVERAGE] < centres[STRONG]


def test_depth_is_clamped_into_the_unit_range():
    assert generator.pupil_depth(random.Random(1), STRONG, 0) == 0
    # The unit_count clamp: a frontier near the end must not index past the list.
    assert generator.pupil_depth(random.Random(1), STRONG, 13, 14) <= 13
    # is-not-None, not truthiness: 0 is rejected loudly rather than falling
    # through to the unclamped branch.
    with pytest.raises(ValueError):
        generator.pupil_depth(random.Random(1), STRONG, 5, 0)
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


def frontier_index(plan, frontier_part, course):
    """The published-unit index the class is working around.

    `course` is REQUIRED (no default): the frontier_part branch dereferences it,
    and a default of None turns a wiring mistake into an AttributeError deep in
    the body instead of a TypeError at the call.

    `frontier_part` is tested with `is not None`: part 0 is a legal AND falsy
    value, and `if frontier_part:` would silently turn --frontier-part 0 into
    the fraction.
    """
    total = len(plan.units)
    if frontier_part is not None:
        parts = list(
            course.nodes.filter(parent__isnull=True).order_by("order", "pk")
        )
        # BOTH ends. `>= len(parts)` alone lets -1 through: it passes the
        # `is not None` branch, passes this check, and `parts[-1]` then silently
        # selects the LAST part — the opposite of what the operator typed. The
        # run reaches DemoKit.objects.create(frontier_part=-1), where
        # PositiveSmallIntegerField raises a DB error that the command's
        # `except (DemoKitError, ImproperlyConfigured)` deliberately does not
        # catch, so the operator gets a raw traceback.
        if not 0 <= frontier_part < len(parts):
            raise InvalidFrontierPart(
                f"part {frontier_part} does not exist (0..{len(parts) - 1})"
            )
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
    rounding, NOT int(x + 0.5) — the two disagree at exact halves.

    `unit_count is not None`, NOT truthiness: this is the same falsy-zero trap
    the frontier_part docstring spends a paragraph on, and writing it the other
    way here would let `unit_count=0` silently fall through to the UNCLAMPED
    branch. provision_kit raises EmptyCourse before that can happen today, but
    this is a public interface Task 15's boundary test calls directly.
    """
    if unit_count is not None and unit_count < 1:
        raise ValueError("unit_count must be >= 1 when given")
    jitter = rng.uniform(-JITTER, JITTER)
    depth = round(frontier * BANDS[band]["depth"] * (1 + jitter))
    top = (unit_count - 1) if unit_count is not None else max(depth, 0)
    return max(0, min(depth, top))
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/demo/test_class_shape.py -v
```

Expected: PASS (ten: two partition cases, three band cases, and five singletons).

- [ ] **Step 5: Falsify the integer arithmetic**

⚠️ **Do not use `int(0.20 * pupil_count)` as the mutant.** Python's `0.2` is slightly *greater*
than one fifth, so `int(0.2 * n) == n * 20 // 100` for every integer `n` — verified across
1..200, zero disagreements. That mutant is behaviourally identical, produces a green run, and
teaches you nothing. ("Try 35" does not rescue it.)

Use a mutant that genuinely differs: change `pupil_count * STRONG_PCT // 100` to
`round(pupil_count * STRONG_PCT / 100)`. The two disagree at `pupil_count` 8, 9, 13, 14, 18,
19, 23, 24, 28, 29, 33, 34, 38, 39 — floor vs half-up. **Step 1's parametrisation already
carries the `pupil_count=18` case** (integer form: 3 strong, 3 struggling, 12 average; `round`
form: 4 and 4), which is the one that separates them — do not add it again. Apply the mutant
and re-run.

Expected: `test_the_partition_is_integer_arithmetic_off_the_share_constants` FAILS at 18
pupils. **Revert by hand** — do not `git checkout`, which would take the whole file.

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
- Produces: `demo.generator.generate(rng, plan, pupils, *, course, frontier_part=None) ->
  (list[DemoWarning], list[str], list[int])` — writes every pupil's progress and finalized
  submissions; `pupils` is the list of `User` rows in creation order. It returns the
  `(warnings, bands, depths)` triple, **not** a bare warnings list.

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
        random.Random(seed), plan, pupils, course=course
    )
    return pupils, plan, warnings


@pytest.mark.django_db
def test_every_stored_fraction_is_the_mark_of_the_stored_answer():
    """T1 — the derived-score rule. Without to_stored_fraction the comparison is
    Decimal vs float and fails on every partial."""
    from courses.models import QuestionElement, QuestionResponse
    from courses.quiz import answer_from_json
    from courses.scoring import to_stored_fraction
    from tests.demo.fixtures import small_course

    course = small_course()
    _run(course)

    responses = QuestionResponse.objects.select_related("element").all()
    assert responses.exists()
    unmarked = 0
    for r in responses:
        question = r.element.content_object
        if question.marking_mode == QuestionElement.MarkingMode.NOT_MARKED:
            # Matches courses/views.py: a NOT_MARKED response carries an answer
            # but NO fraction. Pinned here so the generator cannot drift into
            # stamping 1.0 on questions nothing grades.
            assert r.fraction is None and r.earned_marks is None
            assert r.latest_answer is not None
            unmarked += 1
            continue
        # ⚠️ QUESTION FIRST. The real signature is
        # `answer_from_json(question, latest_answer)` (courses/quiz.py:192) —
        # note that answer_to_json takes only the payload, so the pair is NOT
        # symmetrical. Reversed, every `isinstance(question, ...)` branch inside
        # is False, the function hands back the model object, and this headline
        # derived-score test marks a model instance instead of an answer.
        answer = answer_from_json(question, r.latest_answer)
        assert r.fraction == to_stored_fraction(question.mark(answer).fraction)

    assert unmarked, "the fixture must carry a NOT_MARKED question (see 'Notes quiz')"


@pytest.mark.django_db
def test_progress_mode_and_results_mode_both_populate():
    """T2a and T2b — two independent readers of the matrix.

    ⚠️ THE LESSON ASSERTION MUST BE SCOPED AND COUNT-SENSITIVE. A bare
    `UnitProgress.objects.filter(completed=True).exists()` is green on a build
    with NO lesson writes at all, because two other paths still populate it:
    `_answer_quiz(finalize=True)` calls `_complete` for every answered quiz, and
    `generate`'s reach-forward forces `first_lesson` for any pupil whose
    `did_lesson` is False — which, with the depth-loop writes gone, is ALL of
    them. Counting lesson rows is what separates "the loop wrote them" (~50 for
    5 pupils) from "only the reach-forward did" (exactly 5).
    """
    from courses.models import QuizSubmission, UnitProgress
    from tests.demo.fixtures import small_course

    course = small_course()
    pupils, _plan, _w = _run(course)

    lesson_rows = UnitProgress.objects.filter(
        completed=True, unit__unit_type="lesson"
    ).count()
    assert lesson_rows > len(pupils), (
        f"{lesson_rows} completed lessons for {len(pupils)} pupils — that is the "
        "reach-forward alone; the depth loop wrote nothing"
    )
    # Vacuous against the generator, kept as a REGRESSION GUARD: UnitProgress.save()
    # stamps completed_at on every write path, so this can only fail if someone
    # reintroduces a queryset `.update(completed=True)`, which bypasses save().
    assert UnitProgress.objects.filter(completed=True, completed_at=None).count() == 0
    submitted = QuizSubmission.objects.filter(status=QuizSubmission.Status.SUBMITTED)
    assert submitted.exists()
    assert submitted.filter(score=None).count() == 0


@pytest.mark.django_db
def test_some_pupil_lands_a_partial_answer():
    """The partial half of _pick_answer has NO other end-to-end coverage: the
    builders test exercises it in isolation, and every other fixture question
    returns partial=None. Without this, P_PARTIAL_GIVEN_WRONG, the
    fractions["partial"] key and the partial_fallback branch are dead code that
    every test leaves green.

    ⚠️ 20 pupils and a pinned seed, not 5: with p_partial 0.4 applied only to
    wrong answers, a 5-pupil class can legitimately produce none.

    ⚠️ This test depends on "Blanks quiz" sitting inside EVERY band's depth
    (Part A, index 7). The guard below asserts that precondition directly, so a
    fixture move reports as "nobody reached it" rather than as a mysterious
    dice failure.

    ⚠️ TWO FAILURE MODES, and they need different responses. If `reached` is
    EMPTY, the fixture moved — fix the fixture. If `reached` is non-empty but
    `partials` is empty, it is the DICE, not the code: P(no partial anywhere) is
    about 4% for an arbitrary seed at 20 pupils. Try the next seed and pin it.
    Re-verify the pinned seed whenever BANDS, P_PARTIAL_GIVEN_WRONG or the pupil
    count changes.
    """
    from courses.models import QuestionResponse
    from demo.content import build_course_plan
    from tests.demo.fixtures import small_course

    course = small_course()
    _pupils, plan, _w = _run(course, pupil_count=20, seed=99)

    blanks = [u for u in plan.units if u.title == "Blanks quiz"][0]
    blank_elements = {q.element_id for q in plan.questions[blanks.pk]}
    reached = QuestionResponse.objects.filter(element_id__in=blank_elements)
    assert reached.exists(), (
        "no pupil reached 'Blanks quiz' — it has moved out of the bands' depth"
    )

    partials = [r for r in reached if 0 < float(r.fraction) < 1]
    assert partials, "no pupil scored a strict partial on the two-blank question"


@pytest.mark.django_db
def test_a_non_kit_student_gains_nothing():
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
    """T5 — the WRITE half of the whole-unit skip.

    ⚠️ Uses `quiz_with_review_question`, not `quiz_without_questions`: a
    prose-only quiz exits via the `no_gradeable_question` branch and never sets
    `skip_reason`, so the earlier version of this test drove a different path
    than its docstring claimed. Task 6's
    `test_a_quiz_holding_a_review_question_is_skipped_WHOLE` covers the plan
    half; this covers the fact that no row is written for it.
    """
    from courses.models import QuizSubmission
    from tests.demo.fixtures import small_course

    course = small_course(quiz_with_review_question=True)
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

Append to `demo/generator.py` — ⚠️ **the imports go into the module header Task 7 wrote, not
here** (`E402`); only the functions are appended:

```python
# --- into the header ---
from django.utils import timezone

from courses.models import QuestionResponse, QuizSubmission, UnitProgress
from courses.quiz import answer_to_json, finalize_submission
from courses.rollups import is_obligatory_lesson
from courses.scoring import earned_marks, to_stored_fraction
from demo.builders import NO_WRONG_ANSWER
from demo.constants import P_PARTIAL_GIVEN_WRONG

# --- appended below the existing functions ---


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
    # select_for_update is KEPT deliberately, and only for the contract:
    # finalize_submission's docstring says "Caller holds select_for_update on the
    # submission". It is a no-op on the create path (there is no row to lock) and
    # there is no concurrent writer here — every user was created inside this same
    # transaction — so do not read it as concurrency protection.
    submission, _ = QuizSubmission.objects.select_for_update().get_or_create(
        student=student, unit=unit,
        defaults={"status": QuizSubmission.Status.IN_PROGRESS},
    )
    if submission.status == QuizSubmission.Status.SUBMITTED:
        return submission
    # ⚠️ SINGLE-SHOT per (pupil, unit). The guard above covers a re-finalized
    # quiz, NOT general re-entry: QuestionResponse carries
    # UniqueConstraint(["submission", "element"]), so a second call against a
    # still-IN_PROGRESS submission would raise IntegrityError at the bulk_create
    # below. All THREE callers guarantee it cannot happen:
    #   1. generate's depth loop — visits each unit at most once;
    #   2. generate's reach-forward — fires only when `did_quiz` is False, which
    #      means no submission exists for ANY answerable quiz, first_quiz included;
    #   3. leave_in_progress — skips every unit already in `submitted_unit_ids`.
    # Keep it that way. (2) is the one that is not obvious from its call site.
    now = timezone.now()
    rows = []
    for qplan in qplans[:limit]:  # qplans[:None] is already the whole list
        answer, fraction = _pick_answer(rng, qplan, p_correct)
        # ⚠️ NOT_MARKED ROWS STORE NO FRACTION. courses/views.py:1654-1664 sets
        # `response.fraction` / `earned_marks` ONLY when marking_mode is AUTO and
        # leaves them None otherwise. Writing 1.0 here would make every `[N]`
        # question in the kit render as fully correct on any surface that shows a
        # stored fraction — and compute_scores ignores NOT_MARKED, so no scoring
        # test could ever see it. It would surface first in the mat-pp eyeball,
        # and again in PR 5's per-question view.
        stored = to_stored_fraction(fraction) if qplan.gradeable else None
        rows.append(
            QuestionResponse(
                submission=submission, element_id=qplan.element_id,
                fraction=stored,
                earned_marks=(
                    earned_marks(stored, qplan.max_marks) if stored is not None else None
                ),
                latest_answer=answer_to_json(answer), attempt_count=1,
                last_attempt_at=now, locked=False,
            )
        )
    # QuestionResponse has no save() override (verified), so bulk_create is safe
    # here — and this is the highest-volume write by an order of magnitude.
    QuestionResponse.objects.bulk_create(rows)
    # ⚠️ NO `Attempt` ROWS, deliberately. The real answer path
    # (courses/views.py:1674) creates one Attempt per response; we write
    # attempt_count=1 with nothing behind it. What that costs: any surface that
    # JOINS Attempt shows a count with no history — PR 5's per-question view is
    # the stated consumer, so PR 5 must either read attempt_count alone or this
    # decision must be revisited there. Writing them here would add ~pupils x
    # questions rows for a demo that never replays an attempt; it consumes no
    # draw either way, so the draw order is unaffected.
    if finalize:
        finalize_submission(unit, submission)
        _complete(student, unit)
    return submission


def generate(rng, plan, pupils, *, course, frontier_part=None):
    """Write every pupil's activity. Returns `(warnings, bands, depths)`.

    The triple, not a bare warnings list — Task 9 consumes bands and depths for
    the IN_PROGRESS selection, and narrowing this docstring is how a caller comes
    to unpack one value.

    NO `kit` PARAMETER. The body never read it and the plan's own test passed
    None for it — a positional argument that is legitimately None at half the
    call sites is an invitation to start using it and break the other half. R7
    scoping comes from `pupils`, which is the list the caller already filtered.
    """
    warnings = []
    bands = assign_bands(rng, len(pupils))
    frontier = frontier_index(plan, frontier_part, course)  # all three, always
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

Expected: PASS (five tests).

- [ ] **Step 5: Falsify the progress write**

Comment out the `_complete(...)` call inside the **lesson branch of the depth loop** — and
leave the reach-forward and `_answer_quiz`'s `_complete` alone, so the mutant is exactly "the
depth loop's lesson writes are gone". Re-run.

Expected: `test_progress_mode_and_results_mode_both_populate` FAILS on the lesson-count
assertion (it drops to exactly one row per pupil — the forced `first_lesson`) while the
results half still passes, which is the point of splitting them.

⚠️ If it PASSES, the assertion has been loosened back to a bare `.exists()`. That form is
green on this mutant for two independent reasons — quiz units write `UnitProgress` too, and
the reach-forward fires for every pupil once `did_lesson` is universally False. **Revert by
hand.**

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
  list[DemoWarning]` — called by `generate` after every pupil's finalized pass.
- Consumes: `demo.generator._usable_target(plan, depth, submitted_unit_ids)` — internal, and
  deliberately takes no `pupil`.

⚠️ **This task ends GREEN, like every other.** An earlier draft had it commit two knowingly
red tests "until Task 10", with an optional "comment the provisioning lines out" workaround and
no instruction to uncomment them — which is how Task 10 Step 4 comes to report PASS on a
half-commented file, and how branch protection (the repo's actual test gate) gets a red commit.
The provisioning-dependent half of T25 now lives in **Task 10's** test file, where
`provision_kit` exists. What stays here is the pure, plan-level half, which goes green as soon
as the pass is written.

- [ ] **Step 1: Write the failing test**

`tests/demo/test_in_progress.py`:

```python
import pytest


@pytest.mark.django_db
def test_a_candidate_exists_beyond_every_reachable_depth():
    """THE FIXTURE GUARD, and the reason "Late quiz" exists.

    `_usable_target` rejects any unit at `position <= depth`, and a pupil shallow
    enough to miss a quiz is handed it anyway by generate()'s reach-forward —
    which puts it in `submitted_unit_ids` and trips the second rejection. So if
    every candidate sits at or below the shallowest depth, `chosen` is ALWAYS
    empty, no IN_PROGRESS row is ever written, and T25 fails on correct code.
    That is exactly what the original fixture did. Pin it here, cheaply, rather
    than debugging it through a provisioning run.
    """
    from demo.constants import BANDS, JITTER, MIN_PUPILS, STRUGGLING
    from demo.content import build_course_plan
    from demo.generator import frontier_index
    from tests.demo.fixtures import small_course

    course = small_course()
    plan = build_course_plan(course)
    frontier = frontier_index(plan, None, course)
    # The shallowest depth any band can produce: the smallest multiplier at the
    # most negative jitter. Derived, never a literal.
    min_depth = round(frontier * BANDS[STRUGGLING]["depth"] * (1 - JITTER))

    positions = {u.pk: i for i, u in enumerate(plan.units)}
    reachable = [
        u for u in plan.in_progress_candidates if positions[u.pk] > min_depth
    ]
    assert reachable, (
        "no in-progress candidate sits past the shallowest possible depth "
        f"({min_depth}); the review queue can never fill"
    )
    assert MIN_PUPILS >= 2


@pytest.mark.django_db
def test_a_one_question_quiz_is_never_an_in_progress_target():
    """randint(1, n-1) raises at n == 1, and a prefix must be strictly proper."""
    from demo.content import build_course_plan
    from tests.demo.fixtures import small_course

    course = small_course()
    plan = build_course_plan(course)
    one_question = [
        u for u in plan.units
        if u.unit_type == "quiz" and len(plan.questions.get(u.pk, [])) == 1
    ]
    assert one_question, "the fixture needs a single-question quiz"
    assert not {u.pk for u in one_question} & {
        u.pk for u in plan.in_progress_candidates
    }


@pytest.mark.django_db
def test_no_qualifying_pupil_is_reported_not_silently_swallowed():
    """Both shortfall branches tell the operator that §1's fourth requirement — a
    non-empty review queue — silently failed. Nothing else drives them: Task 15's
    DISPLAY test only proves the map is self-consistent, so without this they are
    dead code every test leaves green, and the
    f"{len(chosen)} of {IN_PROGRESS_PUPILS}" reason could be malformed forever.

    Driven directly rather than through a course shaped to fail: every pupil is
    handed a depth past the end of the outline, so _usable_target's
    `position <= depth` rejects every candidate."""
    import random

    from demo.content import build_course_plan
    from demo.generator import leave_in_progress
    from demo.warnings import KINDS
    from tests.demo.fixtures import small_course

    plan = build_course_plan(small_course())
    deep = len(plan.units) + 1
    warnings = leave_in_progress(
        random.Random(1), plan, pupils=[None, None], bands=["average"] * 2,
        depths=[deep, deep],
    )

    assert [w.kind for w in warnings] == ["no_qualifying_pupil"]
    assert warnings[0].kind in KINDS  # the closed-set guard actually fired
    assert warnings[0].reason
```

⚠️ `pupils=[None, None]` works only because no pupil is ever selected — the `QuizSubmission`
lookup runs against `student=None` and returns empty. If you extend this test to a case where
`chosen` is non-empty, pass real users.

⚠️ The membership check is on **pks**, not on model instances: two queries for the same row
produce unequal Python objects in some paths, and a set intersection of instances would then
be empty for the wrong reason.

- [ ] **Step 2: Write the provisioning test helper**

`tests/demo/helpers.py` — a thin wrapper so tests do not re-type the override and the seed.
Written now because Task 10's tests all use it:

```python
from django.test import override_settings

from demo.constants import DEFAULT_DAYS


def provision_for_test(
    course, *, label="SP 12", pupils=5, days=DEFAULT_DAYS, seed=4242, full=False
):
    """Every provisioning test needs VENDOR_INSTANCE on (test settings pin it
    False) and an EXPLICIT seed (the service draws one from secrets otherwise,
    so content assertions would run against a fresh random class each time).

    `full=True` returns the whole ProvisionResult instead of just `.kit` — the
    warnings and the two passwords are otherwise unreachable, which silently
    defeated the webhook half of T12.
    """
    from demo.services import provision_kit

    with override_settings(VENDOR_INSTANCE=True):
        result = provision_kit(
            label, course=course, days=days, pupils=pupils, seed=seed
        )
    return result if full else result.kit
```

⚠️ The `override_settings` block ends when `provision_for_test` returns. Any test that then
calls `extend_kit` — which is vendor-guarded — must carry its **own**
`@override_settings(VENDOR_INSTANCE=True)`; see Task 11.

- [ ] **Step 3: Run them**

```bash
uv run pytest tests/demo/test_in_progress.py -v
```

Expected: **2 passed, 1 failed** — `ImportError: cannot import name 'leave_in_progress'`, which
Step 4 writes. (`failed`, not `error`: the import is inside the function body, so it raises
during the call phase; pytest reserves `ERROR` for collection and fixture setup.) The third test (`test_no_qualifying_pupil_is_reported_not_silently_swallowed`)
drives the pass itself, so it cannot run yet; that one IS the red half of this task's cycle.

⚠️ **The other two go GREEN immediately, and that is correct** — they read only `build_course_plan`
(Task 6) and `frontier_index` (Task 7), both of which exist, and `small_course` already carries
"Late quiz" because Task 6 Step 2 wrote it that way. They are not a red/green cycle for
`leave_in_progress`; they are **fixture guards** that make the pass in Step 4 possible at all,
placed here so a later fixture edit that removes the late quiz fails loudly and cheaply rather
than surfacing as an empty review queue in Task 10.

If either of **those two named fixture guards** fails, the fixture has regressed — repair
`tests/demo/fixtures.py`, not the assertions. (The third test's ImportError is expected and is
not a fixture problem.)

- [ ] **Step 4: Write the pass**

Append to `demo/generator.py` — ⚠️ **header imports into the header** (`E402`):

```python
# --- into the header ---
from demo.constants import IN_PROGRESS_PUPILS
from demo.warnings import DemoWarning  # no alias: it is named DemoWarning at source

# --- appended below ---


def _usable_target(plan, depth, submitted_unit_ids):
    """The STATIC, draw-free predicate. Selection runs before the pass, so a
    predicate phrased as 'yields a conforming prefix' would force an implementer
    to simulate draws — perturbing a stream nothing pins.

    No `pupil` parameter: the caller already resolved it into
    `submitted_unit_ids`, and a parameter the body never reads sends a reader
    hunting for logic that is not here.
    """
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
    # (No local `from courses.models import QuizSubmission` — Task 8 already put
    # it in the module header, and a function-local re-import tells the next
    # reader there is an import cycle here. There is not.)
    warnings = []
    ranked = sorted(range(len(pupils)), key=lambda i: (depths[i], i))
    chosen = []
    for i in ranked:
        submitted = set(
            QuizSubmission.objects.filter(student=pupils[i]).values_list(
                "unit_id", flat=True
            )
        )
        target = _usable_target(plan, depths[i], submitted)
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
            # `idx`, not `i` and not `n`: the genexp has its own scope so reusing
            # either is not a bug, but `i` is the PUPIL index this loop is keyed
            # on and `n` is len(qplans) on the line below — a reader should not
            # have to prove scoping rules to read a function about which pupil
            # gets which unit.
            first_gradeable = next(idx for idx, q in enumerate(qplans) if q.gradeable)
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

- [ ] **Step 5: Run the tests**

```bash
uv run pytest tests/demo/test_in_progress.py -v
```

Expected: PASS (three tests) — the two plan-level fixture guards, plus the shortfall-warning
test that Step 4's `leave_in_progress` has now made importable. None of them needs
`provision_kit`.

- [ ] **Step 6: Commit**

```bash
git add demo/generator.py tests/demo/test_in_progress.py tests/demo/helpers.py
git commit -m "feat(demo): leave two pupils with an unfinished quiz for the review queue"
```

---

### Task 10: `provision_kit`

**Files:**
- Modify: `demo/services.py`
- Modify: **`notifications/services.py`** — a ContextVar mute plus one early return in
  `notify()` (Step 3b). The only out-of-app code change in PR 2; it must be committed and
  tested with it.
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
    # Sweep EVERY string-valued column on the row, not just label/slug.
    # ⚠️ The old two-field loop was vacuous: `label` is operator input and `slug`
    # is derived from it, so neither could ever hold a freshly generated
    # 14-character secret — it was green on a build that added a
    # `teacher_password` column.
    result.kit.refresh_from_db()
    for f in result.kit._meta.get_fields():
        if not getattr(f, "concrete", False):
            continue
        value = getattr(result.kit, f.attname, None)
        if isinstance(value, str):
            assert result.teacher_password not in value, f.name
            assert result.student_password not in value, f.name


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
    """T15b/T22 — enforced in the SERVICE, so PR 3's form inherits them.

    ⚠️ ONE import block. `with` creates no scope, so re-importing `DemoKit` or
    `small_course` beside the later cases puts two bindings in the same function
    scope — `F811 redefinition of unused ...`, a real lint failure that surfaces
    only at Final verification."""
    from courses.models import Course
    from demo.models import DemoKit
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

        # A course with units but NOTHING ANSWERABLE — caught up front, by the
        # course-shaped message, not by the per-pupil EmptyKit loop after every
        # row has been written. Assert on the empty DemoKit table: a late raise
        # also rolls back, so pytest.raises alone cannot tell them apart.
        prose_only = small_course(slug="prose-only", quiz_without_questions=True)
        prose_only.nodes.filter(unit_type="quiz").exclude(
            title="Prose-only quiz"
        ).update(published=False)
        before = DemoKit.objects.count()
        with pytest.raises(errors.EmptyCourse) as exc:
            provision_kit("SP", course=prose_only, days=14, pupils=5, seed=1)
        assert "quiz" in str(exc.value)
        assert DemoKit.objects.count() == before

        # frontier_part is validated UP FRONT, like days and pupils — not deep
        # inside generate() after every user has been written. Asserting on the
        # empty DemoKit table is what proves the check ran early; a late raise
        # still rolls back, so `pytest.raises` alone cannot tell the difference.
        before = DemoKit.objects.count()
        with pytest.raises(errors.InvalidFrontierPart) as exc:
            provision_kit(
                "SP", course=course, days=14, pupils=5, seed=1, frontier_part=99
            )
        assert exc.value.field == "frontier_part"  # it is an InvalidBounds
        assert DemoKit.objects.count() == before


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
def test_provisioning_is_silent(django_capture_on_commit_callbacks):
    """T12 — R6.

    ⚠️ TWO TRAPS, both of which made the earlier version of this test green on a
    build that mails the world.

    1. `mail.outbox == []` alone proves NOTHING here. provision_kit is
       @transaction.atomic and pytest-django rolls back, so the on_commit
       callbacks that actually send are DISCARDED, never run. The assertion is
       green whether or not the suppression exists. Hence
       `django_capture_on_commit_callbacks(execute=True)`, which runs them.
    2. The observable, transaction-independent fact is the Notification ROWS —
       assert on those too, because they are written synchronously and would show
       up in the demo Teacher's own bell menu.
    """
    from django.core import mail

    from integrations.models import WebhookDelivery, WebhookEndpoint
    from notifications.models import Notification
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    endpoint = WebhookEndpoint.load()
    endpoint.enabled = True
    endpoint.url = "https://sis.example/hook"
    endpoint.save()

    before = WebhookDelivery.objects.count()
    with django_capture_on_commit_callbacks(execute=True):
        result = provision_for_test(small_course(), full=True)

    assert mail.outbox == []
    assert not Notification.objects.filter(
        recipient__in=result.kit.users.all()
    ).exists(), "enrolment notifications leaked into the kit users' bell menus"

    # The mute is SCOPED, not global: it must be OFF again afterwards, or every
    # other request in this worker loses its notifications for the duration.
    # ⚠️ Assert on a real notify() call, not just on the flag — a module-attribute
    # swap that forgot to restore would leave the flag False and notify() dead.
    from notifications.services import notify
    from tests.factories import make_verified_user

    bystander = make_verified_user(username="bystander", email="b@example.com")
    assert notify(
        recipient=bystander,
        kind=Notification.Kind.ENROLLED,
        target=result.kit.course,
        data={"course_title": "x", "course_slug": "small"},
    ) is not None, "notify() was still muted after provisioning returned"
    # ⚠️ The delivery count below is a REGRESSION GUARD ONLY, and is currently
    # vacuous: emit_result_finalized is called from courses/views.py and
    # courses/review.py, never from finalize_submission, so the generator's path
    # cannot create a WebhookDelivery on ANY build. Keep it for the day someone
    # routes the generator through the view layer — do not read it as live cover.
    assert WebhookDelivery.objects.count() == before
    # ...and the operator is TOLD the endpoint is live (it is a data-leak
    # surface the moment a rep presses Force submit).
    # ⚠️ This needs the FULL ProvisionResult. The old form asserted
    # `result_kit is not None` on the bare `.kit` — true on every build,
    # including one where _webhook_warnings() returns [] unconditionally, so the
    # half of the test its own comment describes was measuring nothing.
    hits = [w for w in result.warnings if w.kind == "active_webhook_endpoint"]
    assert len(hits) == 1
    assert hits[0].reason == endpoint.url


@pytest.mark.django_db
def test_the_review_queue_is_non_empty_for_the_kit_teacher():
    """T25 — §1's fourth requirement. MOVED HERE from Task 9 because it needs
    provision_kit; Task 9 keeps only the plan-level half so it can end green.

    pending_reviews_for filters on reviewable_students AND quiz_units_in_order,
    so a submission written for the wrong scope leaves the queue silently empty —
    asserting on the QuizSubmission table alone would not catch that, which is
    why the queue itself is queried.
    """
    from courses.models import QuizSubmission, UnitProgress
    from courses.review import pending_reviews_for
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    course = small_course()
    kit = provision_for_test(course)

    queue = pending_reviews_for(kit.teacher, course, drafts="hide")
    assert queue["in_progress"], "the teacher's own queue, not just the table"
    # ⚠️ queue["awaiting"] is EXPECTED to be empty — any quiz holding a REVIEW
    # question is skipped whole (see Task 6's accepted consequence). Asserting it
    # non-empty would be red on correct code.

    in_progress = QuizSubmission.objects.filter(
        status=QuizSubmission.Status.IN_PROGRESS
    )
    assert in_progress.count() == 2  # IN_PROGRESS_PUPILS, by construction

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
def test_the_demo_teacher_can_read_every_course_on_the_box():
    """⚠️ THIS TEST DOCUMENTS A KNOWN WIDENING, and is expected to PASS — read
    the note under Step 3 before changing it.

    `accessible_courses` (courses/access.py:22-23) returns Course.objects.all() for
    ANY is_staff user, and the demo Teacher receives is_staff=True from its
    TEACHER role — `set_user_role` derives the flag via `role_is_staff`, so this
    is not something _make_user chose. So a school rep's demo login can read every
    other course hosted on the vendor instance, including another school's kit.
    Pinning it here means the day someone narrows staff access, this test goes
    red and the narrowing is a deliberate decision rather than a surprise.
    """
    from courses.access import accessible_courses
    from courses.models import Course
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    course = small_course()
    other = Course.objects.create(slug="other", title="Other", language="pl")
    kit = provision_for_test(course)

    assert kit.teacher.is_staff
    assert other in accessible_courses(kit.teacher)
    # The rep's STUDENT login is correctly narrow — that half is not a widening.
    assert other not in accessible_courses(kit.student)


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

⚠️ **Known widening, accepted for the PR 1–2 interval.** The Teacher ends up `is_staff=True`
because `set_user_role(TEACHER)` derives the flag from `role_is_staff` — and
`courses/access.py:22-23` grants **every** `is_staff` user read access to **every** course on the
box. On the vendor instance that means one school's demo Teacher can open another school's
demo course, and any other course hosted there. Two reasons this ships anyway: the vendor
instance hosts only courses we author and the kits we issue, and kits are time-limited and
purged. It is **not** acceptable once PR 3 lets kits be issued from a web form: narrowing it
(a non-staff Teacher role, or scoping `accessible_courses` by group) is PR 3 work, and T9's
cross-kit isolation test belongs with it. The test above pins the current behaviour so the
narrowing cannot happen silently. Also listed under "Deliberately NOT in this plan".

Append to `demo/services.py` — ⚠️ **this whole import block belongs in the module header Task 3
wrote, above `require_vendor`** (`E402`); append only the dataclass and the functions:

```python
# --- into the header ---
import contextlib
import random
import secrets
# (no `contextvars` here — the ContextVar lives in notifications/services.py,
#  where notify() can read it; see Step 3b.)
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
# `is_obligatory_lesson` IS used here — by the up-front "no obligatory lesson"
# check in provision_kit. (It was briefly dropped as unused when that check lived
# only in the generator; restore it, or the check is an F821.)
from courses.rollups import is_obligatory_lesson
from demo import errors
from demo.constants import (
    DEFAULT_DAYS, DEFAULT_PUPILS, EMAIL_DOMAIN, LABEL_MAX, MAX_DAYS,
    MAX_DISAMBIGUATOR, MAX_PUPILS, MIN_DAYS, MIN_PUPILS, PASSWORD_ALPHABET,
    PASSWORD_LENGTH, SLUG_FALLBACK, SLUG_MAX,
)
from demo.content import build_course_plan
from demo.generator import frontier_index  # NOT just `generate` — the up-front
from demo.generator import generate        # frontier_part check below calls it
from demo.models import DemoKit
from demo.names import draw_names
from demo.warnings import DemoWarning
from grouping.models import Group
from grouping.services import add_students_to_group
from institution.roles import STUDENT, TEACHER, seed_roles

User = get_user_model()

# --- appended below require_vendor ---


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


def _make_user(username, *, display_name, password=None, role=None,
               first_name="", last_name=""):
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
        username=username, email=f"{username}@{EMAIL_DOMAIN}", password=password,
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
        # The CONSTANT, not a literal 200: a hard-coded number in the message is
        # one that lies the day LABEL_MAX changes — the exact failure the
        # constants module's own docstring argues against.
        raise errors.InvalidLabel(
            f"label must be non-blank and at most {LABEL_MAX} characters"
        )
    if not MIN_PUPILS <= pupils <= MAX_PUPILS:
        raise errors.InvalidBounds("pupils", f"pupils must be {MIN_PUPILS}-{MAX_PUPILS}")
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
        label=label, slug=slug, course=course, course_slug=course.slug,
        seed=seed, pupil_count=pupils,
        frontier_part=frontier_part, created_by=created_by,
        expires_at=timezone.now() + timedelta(days=days),
    )

    group = Group.objects.create(name=f"Klasa demo — {label[:150]} (#{kit.pk})", course=course)
    kit.group = group

    teacher_password, student_password = _password(), _password()
    teacher = _make_user(
        teacher_name, display_name=f"Nauczyciel demo — {label} (#{kit.pk})"[:150],
        password=teacher_password, role=TEACHER,  # role_is_staff(TEACHER) -> is_staff
    )
    group.teachers.add(teacher)
    student = _make_user(
        student_name, display_name=f"Uczeń demo — {label} (#{kit.pk})"[:150],
        password=student_password, role=STUDENT,
    )
    kit.teacher, kit.student = teacher, student
    kit.save(update_fields=["group", "teacher", "student"])
    kit.users.add(teacher, student)

    rng = random.Random(seed)  # imported at module level; there is no cycle here
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
```

- [ ] **Step 3b: Give `notifications` a mute switch**

The ContextVar belongs where `notify()` can read it. In `notifications/services.py`, add at
module level:

```python
import contextlib
import contextvars

# Per-thread / per-async-task mute. Set by callers that create many rows in one
# operation and must stay silent — demo.services.provision_kit enrols 6-41 users
# at once (spec R6). NOT a module-attribute swap: provisioning can run inside a
# web request for up to a minute, and rebinding `notify` globally would silence
# every OTHER request in that worker for the duration.
_MUTED = contextvars.ContextVar("notifications_muted", default=False)


@contextlib.contextmanager
def muted():
    token = _MUTED.set(True)
    try:
        yield
    finally:
        _MUTED.reset(token)
```

and make it the first statement of `notify()`, beside the existing
`recipient == actor` no-op:

```python
    if _MUTED.get():
        return None
```

⚠️ Put it **before** `Notification.objects.create(...)`, so neither the row nor the
`transaction.on_commit(...)` email is produced. Returning `None` matches the existing
self-notification early-out, so no caller needs to change.

- [ ] **Step 4: Run the provisioning and in-progress tests**

```bash
uv run pytest tests/demo/test_provision.py tests/demo/test_in_progress.py notifications/tests/ -v
```

⚠️ `notifications/tests/` is included because Step 3b changed `notify()` — run it here, at the
task that made the edit, not only at the end.

Expected: PASS. ⚠️ If `test_every_pupil_holds_progress_and_a_scored_submission` fails, the
reach-forward is not firing — check `first_lesson` / `first_quiz` in `generate`, not the test.

- [ ] **Step 5: Falsify the collision scan**

Insert a squatter at the top of
`test_a_second_kit_for_the_same_school_gets_distinct_usernames`, before the first
`provision_for_test` — it holds the *email* the kit wants, but not the username:

```python
    from tests.factories import make_verified_user

    make_verified_user(username="squatter", email="sp-12-nauczyciel@demo.invalid")
```

Re-run: it must still PASS (the kit bumps to `sp-12-2-…`). Then change `_taken` to check
`User.objects.filter(username__in=lowered)` only, and re-run.

Expected: **an `IntegrityError` on `User.email`'s unique index**
(`accounts/models.py:24` — `email = models.EmailField(..., unique=True)`), raised inside
`create_user` before allauth is reached. ⚠️ The original wording predicted allauth's
`ValueError`; that is the signal only when the collision is an `EmailAddress` row with no
matching `User.email`. Either way the provisioning dies mid-transaction instead of bumping
cleanly, which is the point. **Revert by hand** — both the `_taken` change and the squatter.

- [ ] **Step 6: Measure the cost NOW, not at the end**

The kit-wide content pass removed the 20× per-pupil multiplier, but **the 1× cost is still
unbounded and nothing has measured it.** `_top_level_questions` is a query per unit, every
`mark()` re-queries its own children, `_complete`/`_answer_quiz` do a `get_or_create` per
(pupil, unit), and `finalize_submission` re-queries the unit's elements per submission. On
mat-pp that is plausibly tens of thousands of queries. **PR 3 puts this behind a web request**,
so the number decides whether PR 3's tab can call the service synchronously at all — and
learning it after Task 15 means learning it too late to shape the design.

**Budget: a 20-pupil kit on mat-pp provisions in ≤ 60 s.** Under that, PR 3 can call the
service inline (with a generous timeout). Over it, PR 3 needs a job/progress surface, which is
a design change, not a tuning exercise — say so in the PR body rather than optimising here.

Add a cheap query-count pin to `tests/demo/test_provision.py`:

```python
@pytest.mark.django_db
def test_provisioning_queries_do_not_scale_with_the_class(
    django_assert_max_num_queries,
):
    """The 20x multiplier this whole design removes lives in the PUPIL LOOP, so
    that is what has to be measured.

    ⚠️ `django_assert_max_num_queries`, NOT `django_assert_num_queries` — the
    latter wraps assertNumQueries and asserts EQUALITY (`exact=True`), so a
    ceiling written with it fails on correct code the moment the count is
    anything but the literal.

    ⚠️ And it must provision TWICE at different class sizes. A single
    `build_course_plan(course)` pin cannot see the regression it would be named
    for: that function takes no pupil count and touches no pupil, so
    reintroducing per-pupil mark() calls inside _answer_quiz leaves it green.
    """
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    # ⚠️ DISTINCT SLUGS. Course.slug is unique=True, so a second bare
    # small_course() raises IntegrityError and this test cannot run at all.
    small_five = small_course(slug="scale-5")
    with django_assert_max_num_queries(2000) as five:
        provision_for_test(small_five, label="Five", pupils=5)

    small_ten = small_course(slug="scale-10")
    with django_assert_max_num_queries(4000) as ten:
        provision_for_test(small_ten, label="Ten", pupils=10)

    # THE MARGINAL COST PER PUPIL — the quantity a per-pupil content pass
    # inflates. Measured on the correct build (see below) and pinned with
    # headroom.
    #
    # ⚠️ NOT A RATIO. `assert len(ten) < len(five) * 2.5` cannot fail for ANY
    # input: query cost is B + p*X (a fixed base plus a per-pupil term), so the
    # 5->10 ratio is (B + 10X)/(B + 5X), which is strictly less than 2 for every
    # B > 0 and approaches 2 only as B -> 0. Moving the content pass inside the
    # loop multiplies X — it does not make growth superlinear — so the ratio
    # stays under 2 either way and the guard is green on the broken build.
    per_pupil = (len(ten) - len(five)) / 5
    assert per_pupil <= MEASURED_PER_PUPIL * 1.5, (
        f"{per_pupil:.1f} queries per additional pupil vs a measured "
        f"{MEASURED_PER_PUPIL} — the content pass is running inside the loop"
    )
```

⚠️ **Every number here is a placeholder — MEASURE FIRST, then set all three.** Nothing has
counted these: `_top_level_questions` is a query per unit, `mark()` re-queries its own
children, `finalize_submission` → `compute_scores` re-queries elements and GFK targets per
submission, and `_free_base`'s `_taken` is three queries per disambiguator attempt. A 5-pupil
run over 18 units could plausibly land either side of 2000.

So: **run it once with both ceilings at `100_000` and the `per_pupil` assertion replaced by a
deliberate failure** that renders the numbers:

```python
    pytest.fail(f"five={len(five)} ten={len(ten)} per_pupil={(len(ten) - len(five)) / 5}")
```

⚠️ **A `print()` will not work here.** `addopts` carries `-q` and pytest captures stdout, so a
*passing* test shows you nothing — and with the assertion commented out it does pass. Either
fail deliberately as above, or run that single node with `-s`:

```bash
uv run pytest "tests/demo/test_provision.py::test_provisioning_queries_do_not_scale_with_the_class" -s -v
```

Then:

- set each ceiling to roughly **1.5×** its measured count;
- set `MEASURED_PER_PUPIL` (a module constant in the test file) to the measured marginal cost;
- write all three numbers into this step **and** into the PR body.

⚠️ **A later breach means investigating, not bumping.** Raising a number to get green destroys
the only tripwire this task installs. **`per_pupil` is the real test** — the two absolute
ceilings are a coarse backstop that also moves whenever the fixture grows a unit, but the
marginal cost is what the design's whole "validate once, kit-wide" argument is about.

Then time a local mat-pp run (see Final verification for the env-var spelling) and **write the
seconds and the verdict into the PR body**.

- [ ] **Step 7: Commit**

```bash
# ⚠️ notifications/services.py IS PART OF THIS COMMIT. Step 3b creates `muted()`
# and notify()'s early return there, and demo/services.py imports that name — a
# commit without it pushes a branch whose every provisioning test fails on an
# ImportError, while the dirty local tree stayed green.
git add demo/services.py notifications/services.py tests/demo/test_provision.py
git commit -m "feat(demo): provision_kit — users, group, enrolment and generated activity

Adds a ContextVar mute to notifications.services so a kit's 6-41 enrolments
stay silent (spec R6) without a process-global patch: PR 3 calls this inside
a web request."
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
  - `demo.services.purge_expired(*, dry_run=False) -> list[DemoKit]`, raising
    `demo.errors.PurgeFailed` after attempting every due kit if any failed.
    ⚠️ Spelled **`errors.PurgeFailed`** at the raise site, like every other error in
    `demo/services.py` — one spelling, as with `DemoWarning`.

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

    from courses.models import QuizSubmission
    from demo.models import DemoKit
    from demo.services import purge_kit
    from grouping.models import Collection, Group
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    kit = provision_for_test(small_course())
    Collection.objects.create(name="Demo", course=kit.course, owner=kit.teacher)
    # Force-submit one of the kit's quizzes, so QuizSubmission.submitted_by —
    # the FK this test's docstring singles out — is actually populated. Without
    # this the delete path it claims to exercise is untested (it is SET_NULL, so
    # the test passed either way, which is exactly the problem).
    unfinished = QuizSubmission.objects.filter(
        student__in=kit.users.all(), status=QuizSubmission.Status.IN_PROGRESS
    ).first()
    assert unfinished is not None, "the kit must carry an in-progress submission"
    unfinished.submitted_by = kit.teacher
    unfinished.status = QuizSubmission.Status.SUBMITTED
    unfinished.save(update_fields=["submitted_by", "status"])

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

    # --dry-run IS A PREVIEW, and the runbook tells the operator to trust it on
    # prod. Prove it changes nothing: a build that ignores (or inverts) the flag
    # purges the kits here, and without these three assertions every test stays
    # green while the "safe preview" silently destroys a live demo.
    from django.contrib.auth import get_user_model

    previewed = purge_expired(dry_run=True)
    assert [k.pk for k in previewed] == [expired.pk]
    expired.refresh_from_db()
    assert expired.closed_at is None, "--dry-run closed a kit"
    assert get_user_model().objects.filter(demo_kits=expired).exists(), (
        "--dry-run deleted the kit's users"
    )

    purged = purge_expired()
    assert [k.pk for k in purged] == [expired.pk]

    assert purge_expired() == []  # closed_at IS NULL keeps it idempotent
    live.refresh_from_db()
    assert live.closed_at is None


@pytest.mark.django_db
def test_one_failing_kit_does_not_strand_the_others(monkeypatch):
    """C4 — the runbook tells the operator "each kit has its own transaction, so
    the others still close and the run exits non-zero". Without the try/except in
    purge_expired that sentence is false: the first exception leaves every later
    kit's logins LIVE ON PROD, which is the exact failure the cron warning exists
    for."""
    from demo import services
    from demo.models import DemoKit
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    course = small_course()
    first = provision_for_test(course, label="First")
    second = provision_for_test(course, label="Second")
    DemoKit.objects.filter(pk__in=[first.pk, second.pk]).update(
        expires_at=timezone.now() - timedelta(days=1)
    )

    real_purge = services.purge_kit

    def explode_on_first(kit, *, reason):
        if kit.pk == first.pk:
            raise RuntimeError("boom")
        return real_purge(kit, reason=reason)

    monkeypatch.setattr(services, "purge_kit", explode_on_first)

    with pytest.raises(errors.PurgeFailed) as exc:
        services.purge_expired()

    second.refresh_from_db()
    assert second.closed_at is not None, "the second kit was stranded"
    assert [k.pk for k in exc.value.purged] == [second.pk]
    first.refresh_from_db()
    assert first.closed_at is None


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_extend_moves_from_now_and_flags_a_long_lived_kit():
    """T15b. max(expires_at, now()) matters for a kit that expired yesterday.

    ⚠️ The override is REQUIRED and is not inherited: extend_kit calls
    require_vendor() as its first statement, config/settings/test.py:37 pins
    VENDOR_INSTANCE=False, and provision_for_test's own context manager has
    already exited by the time this test calls extend_kit. Without it the test
    errors on ImproperlyConfigured.
    """
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
@override_settings(VENDOR_INSTANCE=True)
def test_extend_and_revoke_refuse_a_closed_kit():
    """Same override, same reason — and without it the ImproperlyConfigured
    raised by the guard would fail the `pytest.raises(KitAlreadyClosed)` for a
    reason that has nothing to do with the rule under test."""
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


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=False)
def test_extend_is_guarded_by_the_vendor_flag():
    """The OTHER half of R8, which nothing else covers. The exemption test above
    proves purge/revoke stay open; this proves extend does not — without it, a
    build that dropped require_vendor() from extend_kit is green everywhere."""
    from django.core.exceptions import ImproperlyConfigured

    from demo.services import extend_kit
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    kit = provision_for_test(small_course())
    with pytest.raises(ImproperlyConfigured) as exc:
        extend_kit(kit, days=7)
    assert "LIBLI_VENDOR_INSTANCE" in str(exc.value)
```

- [ ] **Step 2: Run it and watch it fail**

```bash
uv run pytest tests/demo/test_lifecycle.py -v
```

Expected: FAIL — `ImportError: cannot import name 'purge_kit'`.

- [ ] **Step 3: Write the lifecycle services**

Append to `demo/services.py` — ⚠️ **imports into the header** (`E402`):

```python
# --- into the header ---
import logging

from demo.constants import LONG_LIVED_DAYS
from grouping.services import delete_group

logger = logging.getLogger(__name__)

# --- appended below ---


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
        raise errors.PurgeFailed(f"{len(failures)} kit(s) failed to purge: {ids}", purged)
    return purged
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/demo/test_lifecycle.py -v
```

Expected: PASS (eight tests).

- [ ] **Step 5: Falsify the purge predicate, the dry-run flag and the failure isolation**

Three mutants, one at a time, **reverting each by hand** before the next:

1. Drop `closed_at__isnull=True` from `purge_expired`.
   Expected: `test_purge_expired_selects_only_expired_open_kits_and_is_idempotent` FAILS on the
   second `purge_expired()` call.
2. Delete the `if dry_run: return due` line.
   Expected: the same test FAILS on `assert expired.closed_at is None, "--dry-run closed a
   kit"` — the preview the runbook tells the operator to trust would have purged for real.
3. Remove the `try/except` from `purge_expired`'s loop (let the exception propagate).
   Expected: `test_one_failing_kit_does_not_strand_the_others` FAILS with `RuntimeError: boom`
   instead of `PurgeFailed`, and the second kit is left open — live logins on prod.

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
    # "once" is in the test's NAME, so assert it: a build that printed the expiry
    # three times would otherwise stay green.
    assert printed.lower().count("expires") == 1


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

    # ⚠️ EVERY ARGUMENT MUST BE VALID, or the guard is never reached.
    # The earlier version of this test built no fixture and passed no kit id, so
    # `create` died on "no course with slug 'small'" and `extend` on KitNotFound
    # — both BEFORE the service was called. Both pytest.raises(CommandError)
    # assertions were green on a build with no vendor guard at all.
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    course = small_course()
    kit = provision_for_test(course)  # provisions with the flag ON, then drops it

    for name, args in (
        ("create", ("--label", "SP 99", "--course", "small", "--pupils", "5")),
        ("extend", (str(kit.pk), "--days", "7")),
    ):
        with pytest.raises(CommandError) as exc:
            call_command("demo_access", name, *args)
        # The MESSAGE, not merely the class: it is what distinguishes the guard
        # from every other way these subcommands can fail.
        assert "LIBLI_VENDOR_INSTANCE" in str(exc.value), name

    call_command("demo_access", "purge", "--dry-run")  # must NOT raise
    call_command("demo_access", "list")
    call_command("demo_access", "revoke", str(kit.pk))  # exempt, and must work


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_a_missing_kit_id_is_a_clean_error():
    with pytest.raises(CommandError):
        call_command("demo_access", "revoke", "9999")


@pytest.mark.django_db
def test_the_warning_block_is_bounded_however_many_warnings_there_are():
    """The passwords are the two lines the operator needs. Warnings are emitted
    PER QUESTION and PER VARIANT, so on mat-pp an ungrouped list runs to
    thousands of lines and buries them. Grouping is what keeps the block
    readable; this pins it against a course of any size."""
    from demo.management.commands.demo_access import Command
    from demo.warnings import DemoWarning

    out = StringIO()
    # ⚠️ `Command(stdout=out)`, NOT `Command()` then `command.stdout = out`.
    # BaseCommand.__init__ wraps stdout in an OutputWrapper whose write() appends
    # the missing newline; assigning a bare StringIO over it removes that, so
    # every write concatenates, `splitlines()` returns ONE line, and the
    # line-count assertion below is green on any implementation — including the
    # 501-ungrouped-lines one this test exists to reject.
    command = Command(stdout=out)
    command._print_warnings(
        [DemoWarning("variant_dropped", n, str(n)) for n in range(1, 501)]
        + [DemoWarning("active_webhook_endpoint", None, "https://sis.example/hook")]
    )
    printed = out.getvalue()

    assert len(printed.splitlines()) < 20, "the block must not scale with the course"
    assert "variant_dropped x500" in printed  # the count survives grouping
    assert "https://sis.example/hook" in printed, (
        "the data-protection warning must never be the one summarised away"
    )


@pytest.mark.django_db
def test_a_failing_purge_reports_the_survivors_and_still_exits_non_zero(monkeypatch):
    """The COMMAND half of C4. Task 11 Step 5's third mutant covers the service
    (purge_expired attempts every kit, then re-raises); this covers what the cron
    log actually shows — the kits that DID close, printed before the non-zero
    exit — and that handle() turns PurgeFailed into a CommandError."""
    from datetime import timedelta

    from django.utils import timezone

    from demo import services
    from demo.models import DemoKit
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    course = small_course()
    doomed = provision_for_test(course, label="Doomed")
    survivor = provision_for_test(course, label="Survivor")
    DemoKit.objects.filter(pk__in=[doomed.pk, survivor.pk]).update(
        expires_at=timezone.now() - timedelta(days=1)
    )

    real_purge = services.purge_kit
    monkeypatch.setattr(
        services,
        "purge_kit",
        lambda kit, *, reason: (_ for _ in ()).throw(RuntimeError("boom"))
        if kit.pk == doomed.pk
        else real_purge(kit, reason=reason),
    )

    out = StringIO()
    with pytest.raises(CommandError) as exc:
        call_command("demo_access", "purge", stdout=out)

    assert f"#{survivor.pk}" in out.getvalue(), "the survivor was never reported"
    assert f"#{doomed.pk}" in str(exc.value)
```

- [ ] **Step 2: Run it and watch it fail**

```bash
uv run pytest tests/demo/test_command.py -v
```

Expected: FAIL — `Unknown command: 'demo_access'`.

- [ ] **Step 3: Write the command**

**First create the two package markers** — `demo/management/__init__.py` and
`demo/management/commands/__init__.py`, both **empty**. Without them Django's command
discovery never finds the module, and Step 2's `Unknown command: 'demo_access'` persists
through Step 4 with a thoroughly misleading cause.

Then `demo/management/commands/demo_access.py`:

```python
"""Issue and retire school demo kits.

The subcommand shape mirrors migrate_course_content: a positional `action` with
`choices`, dispatched in handle(). `create` and `extend` are vendor-guarded;
`purge`, `revoke` and `list` are NOT (spec R8) — guarding a cleanup path is the
one way the guard could leave stranger-known logins alive on prod.
"""

from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import BaseCommand, CommandError

from courses.models import Course
from demo import errors
from demo.constants import DEFAULT_DAYS, DEFAULT_PUPILS, LONG_LIVED_DAYS
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
        # NAMED exceptions only. A blanket `except Exception` swallowed every
        # AttributeError, TypeError and IntegrityError from the services into a
        # CommandError with no traceback — the worst possible surface for
        # debugging a failed provision on prod, and it made the DemoKitError
        # clause above dead code.
        except (errors.DemoKitError, ImproperlyConfigured) as exc:
            raise CommandError(str(exc)) from exc

    def _kit(self, o):
        kit = DemoKit.objects.filter(pk=o["kit_id"]).first()
        if kit is None:
            raise errors.KitNotFound(f"no demo kit with id {o['kit_id']}")
        return kit

    def _create(self, o):
        # Both flags, symmetrically. Without the label check, omitting --label
        # surfaces as provision_kit's "label must be non-blank…", which never
        # names the flag the operator actually forgot.
        if not o["label"]:
            raise errors.DemoKitError('--label "<school>" is required')
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
        self._print_warnings(result.warnings)

    # Warnings are PER QUESTION and PER VARIANT over a whole course. On mat-pp —
    # hundreds of published quizzes — printing one line each buries the two lines
    # that matter (the passwords) and the one that is a data-protection signal
    # (active_webhook_endpoint) under thousands of lines of noise. Group them.
    # The full list stays on ProvisionResult.warnings for PR 3's tab.
    WARNING_SAMPLES = 3

    def _print_warnings(self, warnings):
        if not warnings:
            return
        by_kind = {}
        for warning in warnings:
            by_kind.setdefault(warning.kind, []).append(warning)
        self.stdout.write(self.style.WARNING(f"  {len(warnings)} warning(s):"))
        for kind in sorted(by_kind):
            group = by_kind[kind]
            self.stdout.write(self.style.WARNING(f"  ! {kind} x{len(group)}"))
            for warning in group[: self.WARNING_SAMPLES]:
                # `is not None`, not truthiness — the same falsy-zero rule this
                # plan applies to frontier_part and unit_count. Real pks are
                # never 0, so this is consistency rather than a live bug.
                where = (
                    f"unit {warning.unit_id}" if warning.unit_id is not None else "kit"
                )
                self.stdout.write(f"      {where}: {warning.reason}")
            if len(group) > self.WARNING_SAMPLES:
                self.stdout.write(f"      ... and {len(group) - self.WARNING_SAMPLES} more")

    def _list(self, o):
        kits = DemoKit.objects.all()
        if not o["all"]:
            kits = kits.filter(closed_at__isnull=True)
        for kit in kits:
            teacher = kit.teacher.username if kit.teacher else "-"
            # course_slug, not kit.course.slug — `course` is SET_NULL and a kit
            # can outlive its course, which would be an AttributeError here.
            self.stdout.write(
                f"#{kit.pk}\t{kit.label}\t{kit.course_slug}\t{kit.pupil_count}\t"
                f"{teacher}\t{kit.created_at:%Y-%m-%d}\t{kit.expires_at:%Y-%m-%d}\t"
                f"{kit.status_key}"
            )

    def _extend(self, o):
        result = extend_kit(self._kit(o), days=o["days"])
        self.stdout.write(f"#{result.kit.pk} now expires {result.new_expires_at:%Y-%m-%d}")
        if result.long_lived:
            # The CONSTANT, not a literal 60 — same rule as LABEL_MAX above.
            self.stdout.write(
                self.style.WARNING(
                    f"  ! this kit has been alive for over {LONG_LIVED_DAYS} days"
                )
            )

    def _revoke(self, o):
        kit = self._kit(o)
        revoke_kit(kit)
        self.stdout.write(f"#{kit.pk} revoked")

    def _purge(self, o):
        verb = "would purge" if o["dry_run"] else "purged"
        try:
            due = purge_expired(dry_run=o["dry_run"])
        except errors.PurgeFailed as exc:
            # Report what DID close before the non-zero exit — handle() turns
            # this into a CommandError, and the cron log is the only place
            # anyone will see either half.
            for kit in exc.purged:
                self.stdout.write(f"{verb} #{kit.pk} {kit.label}")
            raise
        for kit in due:
            self.stdout.write(f"{verb} #{kit.pk} {kit.label}")
        self.stdout.write(f"{verb} {len(due)} kit(s)")
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/demo/test_command.py -v
```

Expected: PASS (six tests).

- [ ] **Step 5: Commit**

Also update `docs/development/architecture.md` in **two** places, or the branch ships a new
operator-facing command and a whole new app the architecture doc never mentions — while the
very line being edited describes the command it replaces:

1. **Line 80**, the management-command list (Task 1 edits the same line to annotate
   `seed_demo_course`): add `demo_access`.
2. **The `## The apps` table at lines 8-23**, which opens "libli is a single Django project
   (`config/`) with **nine** local apps" and lists one row per app.

   ⚠️ **The existing count is ALREADY WRONG: the table omits `support`**, which is in
   `INSTALLED_APPS` and in `test_element_state_write_routes.py`'s first-party set. So the edit
   is **nine → eleven**, with **two** new rows, not one:

   | `support` | *(describe from the app's own code — it is the pre-existing omission, not part of this PR's scope; if you would rather not, change the count to ten and add only `demo`, leaving the discrepancy as it was.)* |
   | `demo` | Time-limited **school demo kits**: a Teacher + Student login and ~20 fake pupils with generated activity, provisioned and purged by `demo_access`. Vendor-instance only. |

⚠️ Count against `INSTALLED_APPS` at edit time, not against the existing prose — the sentence is
prose, not a test, and nothing catches it drifting.

```bash
git add demo/management/ tests/demo/test_command.py docs/development/architecture.md
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
    """The generated values, EXCLUDING timestamps AND PRIMARY KEYS.

    Timestamps: every row keeps a wall-clock stamp (there is no back-dating), so
    a naive row comparison is red on correct code.

    ⚠️ PKS ARE THE BIGGER TRAP, and this repo has hit it four times. An earlier
    draft projected `r.element_id`, which broke BOTH tests below:
      * self-consistency built two separate courses and compared their element
        pks — never equal, whatever the generator does, so the test could not
        pass;
      * the golden file would have pinned absolute pks into a checked-in
        artefact. Postgres sequences are not reset by pytest-django's rollback,
        so those values depend on everything that ran earlier in the session —
        a different chunk under `-n`, a reordered run, or any new fixture
        anywhere in tests/ makes the file mismatch with NO change to the draw
        order. The one test that exists to pin the draw order would have been
        the flakiest in the suite.

    The stable key is POSITIONAL: (unit title, index of the question within its
    unit in the plan's own element order).
    """
    # One sorted block — I001 checks function-local imports too.
    from courses.models import QuestionResponse, UnitProgress
    from courses.quiz import answer_to_json
    from demo.content import build_course_plan

    plan = build_course_plan(kit.course)
    # element pk -> ("Unit title", ordinal within the unit, {json -> slot label})
    key_of = {}
    for unit in plan.units:
        for i, q in enumerate(plan.questions.get(unit.pk, [])):
            # ⚠️ THE STORED PAYLOAD CARRIES PKS TOO. A choice answer is a set of
            # Choice pks; the grid builders store column pks. So dumping
            # latest_answer verbatim reintroduces exactly the trap the key above
            # removes. Instead, map each payload back to WHICH SLOT the generator
            # picked — "correct", "partial", or "wrong-N". That is precisely what
            # the draw order decides, and it is pk-free.
            slots = {repr(answer_to_json(q.answers.correct)): "correct"}
            if q.answers.partial is not None:
                slots[repr(answer_to_json(q.answers.partial))] = "partial"
            if not q.sentinel:
                for n, variant in enumerate(q.answers.wrong):
                    slots[repr(answer_to_json(variant))] = f"wrong-{n}"
            key_of[q.element_id] = (unit.title, i, slots)

    rows = []
    for pupil in kit.users.exclude(pk__in=[kit.teacher_id, kit.student_id]).order_by(
        "username"
    ):
        progress = sorted(
            UnitProgress.objects.filter(student=pupil, completed=True).values_list(
                "unit__title", flat=True
            )
        )
        answers = []
        for r in QuestionResponse.objects.filter(submission__student=pupil):
            title, ordinal, slots = key_of[r.element_id]
            slot = slots.get(repr(r.latest_answer))
            assert slot is not None, (
                f"stored answer matches no cached slot for {title}[{ordinal}] — "
                "the generator wrote something the content pass never validated"
            )
            answers.append([title, ordinal, str(r.fraction), slot])
        answers.sort()
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

    # ONE course, TWO kits. Building `small_course()` twice would compare two
    # disjoint sets of rows — and it also exercises the username disambiguator
    # for free, since the second kit takes the same label.
    course = small_course()
    first = _projection(provision_for_test(course, seed=2024))
    second = _projection(provision_for_test(course, seed=2024))
    # The usernames differ by design (sp-12-... vs sp-12-2-...), so compare
    # everything except that field. A `def`, not a lambda assignment — ruff's
    # E731 rejects the latter and tests/** does not ignore E.
    def without_username(rows):
        return [{k: v for k, v in row.items() if k != "username"} for row in rows]

    assert without_username(first) == without_username(second)
    assert first[0]["username"] != second[0]["username"], "the disambiguator ran"


@pytest.mark.django_db
def test_the_golden_class_is_unchanged():
    """T7b — the ONLY test that pins an absolute stream. Its mutants are each
    reordering the spec enumerates: swap the jitter draw ahead of the band
    shuffle; iterate questions in pk order; draw the partial only when the first
    draw said wrong; consume draws for an R3-skipped quiz.

    Landing a DELIBERATE order change means regenerating this file in the same
    commit — that is the point of it.

    The projection is pk-free (see _projection): the file records unit titles,
    question ordinals and slot labels, so it survives a different test order, a
    different xdist chunk and any new fixture elsewhere in tests/.
    """
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    actual = _projection(provision_for_test(small_course(), pupils=5, seed=777))

    # PRECONDITION FOR STEP 4's MUTANT, asserted rather than assumed. Moving the
    # partial draw only perturbs the stream if some pupil actually ANSWERS a
    # partial-capable question. If no recorded response belongs to the two-blank
    # question, the mutant is a no-op and the plan's headline draw-order defence
    # reports a false green. "Blanks quiz" lives in Part A precisely so this
    # holds for every band — see the fixture.
    # ⚠️ ANSWERED **CORRECTLY**, not merely answered. Step 4's mutant moves the
    # partial draw inside `if not correct_roll:`, so it only perturbs the stream
    # for a pupil whose first roll came out CORRECT (the draw then happens in the
    # unmutated build and not in the mutated one). A run where every pupil got
    # the two-blank question wrong draws identically either way.
    # ⚠️ (TITLE, ORDINAL), not the title alone. "Blanks quiz" holds TWO questions:
    # the two-blank fill-blank at ordinal 0 — the only partial-capable row in the
    # fixture — and a plain choice question at ordinal 1. Matching on the title
    # alone passes when a pupil answered the CHOICE question correctly, which
    # says nothing about the fill-blank, so the guard installed to prevent a
    # false green could itself be one.
    answered_correctly = {
        (row[0], row[1]) for r in actual for row in r["answers"] if row[3] == "correct"
    }
    assert ("Blanks quiz", 0) in answered_correctly, (
        "no pupil answered the two-blank fill-blank question CORRECTLY; Step 4's "
        "mutant would be a no-op and this test would not defend the draw order"
    )

    if not GOLDEN.exists():  # first run: record, then read the diff by eye
        GOLDEN.write_text(json.dumps(actual, indent=2, ensure_ascii=False), "utf-8")
        pytest.fail("golden file written — inspect it, then re-run")
    assert actual == json.loads(GOLDEN.read_text("utf-8"))
```

- [ ] **Step 2: Generate the golden file**

```bash
uv run pytest tests/demo/test_determinism.py::test_the_golden_class_is_unchanged -v
```

⚠️ **Two failure modes.** If instead it fails on the `"Blanks quiz" in answered_correctly`
precondition, seed 777 produced no pupil who answered the two-blank question correctly — that
is the dice, not the code. Try the next seed, and remember the change is **coupled**: the seed
constant and `golden_class.json` must move together, in the same commit.

Expected: FAIL with "golden file written". **Open `tests/demo/golden_class.json` and read
it**: five pupils with Polish names, progress lists that differ between pupils, stored answer
slots that are not all `"correct"`, and **at least one `"Blanks quiz"` row** (the assertion
above enforces that, but look at it — a `"partial"` slot among them is what Step 4's mutant
moves). If it looks wrong, the generator is wrong — fix it before accepting the file.

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

- [ ] **Step 4b: Falsify the element ordering**

The mutant Task 6 Step 7b set up, run here because the golden file is what observes it.

In `_top_level_questions`, change `.order_by("order", "pk")` to **`.order_by("pk")`** and
re-run.

⚠️ **Not "drop the `.order_by(...)` call".** `Element.Meta.ordering = ["order", "pk"]`
(courses/models.py:346) would keep the queryset ordered by exactly the same key, so deleting
the call is a behaviourally identical mutant and a guaranteed false green. `.order_by("pk")`
(or the no-arg `.order_by()`, which clears Meta) is what actually changes the order.

Expected: **`test_plan_caches_fractions_and_skips_only_quizzes`' ordering assertion FAILS**
(Task 6 Step 7b's `assert ids == sorted(ids, reverse=True)`). That is the assertion which
observes this mutant.

⚠️ **`test_the_golden_class_is_unchanged` is expected to stay GREEN, and that is correct — do
not go hunting.** "Late quiz"'s two questions are structurally identical: both are
`_choice_question` rows with four options, one correct, three surviving wrong variants,
`max_marks=1`, `gradeable=True`, `sentinel=False`, `partial=None`. `_projection` records
`[title, ordinal, fraction, slot]` where `slot` is the POSITIONAL label (`wrong-0`), never the
answer's content, and `_pick_answer` consumes the same draws in the same order for either
question. So swapping which element sits at ordinal 0 leaves every projected row
byte-identical. (The two IN_PROGRESS pupils are the same story: `rng.randint(1, n-1)` with
`n=2` is always 1, so only ordinal 0 is answered either way.)

If you want the golden file to observe ordering too, make the two questions
projection-distinguishable — give one a different `max_marks`, or a different surviving-variant
count — and regenerate the file in the same commit. Not required: Step 7b's assertion already
pins it, cheaply and without a coupled regeneration.

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

    # BOTH ends of the range. -1 is the one that used to slip through: it is a
    # legal int, it is < len(parts), and parts[-1] silently selects the LAST
    # part before the DB rejects the negative on write.
    for bad in (99, -1):
        with pytest.raises(errors.InvalidFrontierPart) as exc:
            frontier_index(plan, bad, course)
        assert exc.value.field == "frontier_part"  # it subclasses InvalidBounds


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
uv run pytest tests/demo/ tests/test_seed_demo_course.py notifications/tests/ \
  tests/test_i18n_po_health.py tests/test_element_state_write_routes.py -v
```

Expected: all green. ⚠️ **Grep the summary line** — pytest can exit 0 with failures in the
body.

⚠️ **`notifications/tests/` is in that command on purpose.** Task 10 Step 3b adds an
unconditional early return at the top of `notify()` — the only out-of-app *code* change in this
PR — and that package holds 28 test modules (`test_services.py`, `test_wire_enrolled.py`,
`test_emit_helpers.py`, `test_email_wiring.py` …) that no other step runs. Without this, the
mute's only verification is one assertion inside `test_provisioning_is_silent`.

⚠️ Three of those modules — `test_e2e_bell.py`, `test_e2e_email_prefs.py`,
`test_e2e_notifications.py` — **collect nothing** under `addopts = "-m 'not e2e'"`. So this
command covers the mute at the service level only; its browser-level behaviour (the bell
dropdown) is not exercised. Accepted: the mute is a single early return whose ContextVar
defaults to `False`, and the service tests are where that is observable.

⚠️ **`tests/test_i18n_po_health.py` and `tests/test_element_state_write_routes.py` are in that
command for the same reason** — the branch edits the Polish catalog and the app registry, and
both files own those as repo-wide invariants. The i18n guards (`test_no_fuzzy_entries`,
`test_no_obsolete_entries`, `test_pl_has_no_untranslated_msgid`) are what actually enforce Task
6 Step 4b's "check for `#, fuzzy`" warning; a manual `grep -c` is not a gate.

⚠️ **Beyond that, no whole-repo sweep is needed** (a sweep is a branch gate, not a task step).
The branch makes **four** edits outside `demo/`:
1. `"demo"` into `INSTALLED_APPS`. **Three** drift guards enumerate the registry:
   `tests/test_list_referenced_files.py:71` (iterates `apps.get_models()` looking for
   `FileField`s) — inert, `DemoKit` declares none; `tests/test_transfer_schema.py:28` (pins
   `apps.get_app_config("courses")`) — inert, `DemoKit` is not a `courses` model; and
   `tests/test_element_state_write_routes.py:69` (a hard-coded first-party app set) — **this
   one moves**, and Task 2 Step 7 updates it. If you add a `FileField` to `DemoKit` later, the
   first is the test that will tell you.
2. A per-file-ignore in `pyproject.toml`.
3. `notify()`'s early return — safe by construction because the ContextVar defaults to
   `False`, so every existing caller behaves exactly as before; the `notifications/tests/` run
   above is what proves it.
4. `locale/pl/LC_MESSAGES/django.po` and `django.mo` — eleven new msgids, guarded by the i18n
   health tests above.

- [ ] **Check migrations and lint**

```bash
uv run python manage.py makemigrations --check --dry-run
uv run ruff check --no-cache .
uv run ruff format --check .
```

- [ ] **Provision against the local mat-pp copy and LOOK at it** (spec §8, "beyond the suite")

⚠️ **Apply the migration to your LOCAL dev database first.** Task 2 Step 8 only *generates*
`demo/migrations/0001_initial.py`; pytest creates its own test DB, so nothing in this plan has
ever applied it to the database this command talks to. Without it `demo_demokit` does not
exist and the run dies on a `ProgrammingError` before producing the timing number the budget
and the PR body both need:

```bash
uv run python manage.py migrate
```

```bash
# Bash — `time` FIRST. `VAR=x time cmd` is NOT the shell keyword: prefixed by an
# assignment, `time` is parsed as an ordinary command word, and this machine's
# Git Bash has no /usr/bin/time — it fails with "time: command not found".
time LIBLI_VENDOR_INSTANCE=true uv run python manage.py demo_access create \
  --label "Test School" --course mat-pp --pupils 20 --seed 1
```

```powershell
# PowerShell (this machine's primary shell — `VAR=value cmd` is a PARSE ERROR here)
$env:LIBLI_VENDOR_INSTANCE = "true"
Measure-Command {
  uv run python manage.py demo_access create `
    --label "Test School" --course mat-pp --pupils 20 --seed 1 | Out-Default
}
```

⚠️ The `| Out-Default` is load-bearing: `Measure-Command` swallows its block's stdout, and
without it **the printed passwords never reach the screen** — and they are not stored anywhere.
⚠️ `--pupils 20` is explicit because the budget is stated for a 20-pupil kit.

⚠️ **The env var is required.** `config/settings/base.py:288` reads
`VENDOR_INSTANCE = env.bool("LIBLI_VENDOR_INSTANCE", default=False)` and no dev settings module
overrides it, so `provision_kit`'s `require_vendor()` refuses before touching mat-pp — and this
is the only step that produces the wall-clock number the PR body must carry.
⚠️ **Editing `.env` will NOT help if the variable is already exported** in your shell; a
`.env` file cannot override an exported var. Export it, or prefix it as above.

Then log in as the printed teacher and read the matrix, the drill-down, the review queue and
the pupil view, **in light and dark**. Record the wall-clock of the provision against **Task 10
Step 6's budget: ≤ 60 s for a 20-pupil kit**. Under it, PR 3 can call the service inline; over
it, PR 3 needs a job/progress surface — state which in the PR body. Check:
- results mode: at least two-thirds of the course's gradeable quiz units hold a score for at
  least half the pupils;
- progress mode: the class shows **gaps**, not a clean staircase;
- the review queue is non-empty;
- names read as a Polish class list, not `test-school-p01`.

Then purge it: `uv run python manage.py demo_access revoke <id>` — no env var needed, because
`revoke` is exempt from the vendor guard (R8).

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
- **Narrowing the demo Teacher's course access.** `is_staff=True` grants read access to every
  course on the box (`courses/access.py:22-23`), so one school's demo Teacher can open another's.
  Accepted for the PR 1–2 interval (see Task 10 Step 3) and **pinned by a passing test**, so
  the narrowing is a decision, not a surprise. It must land with PR 3, before kits can be
  issued from a web form.
- **Teacher marking / the "awaiting review" queue.** Structurally empty, because any quiz with
  a REVIEW question is skipped whole (see Task 6). PR 3 and PR 4 must not advertise marking as
  part of the demo. The follow-up, if a rep asks for it: write one pupil an unreviewed REVIEW
  response instead of skipping the quiz.

**Test-to-task map** (spec §8 numbering): T1/T2a/T2b/T3/T5 → Task 8 · T1b/T6 → Task 5 ·
T2c → Task 6 · T7/T7b → Task 13 · T8/T15/T15b → Task 11 · T12/T17/T20/T22/T28 → Task 10 ·
T13/T26 → Task 12 · T16 → Tasks 10–11 (asserted on behaviour: the `Enrollment` rows
`add_students_to_group` writes, and `delete_group`'s post-delete recompute) · T17b/T18/T21/T29
→ Task 15 · T19 → Task 1 · **T25 → Task 10** (moved off Task 9, which needs no `provision_kit`
and now ends green like every other task) · T27 → Task 4.

**Type consistency checked:** `generate(rng, plan, pupils, *, course, frontier_part=None)`
returns `(warnings, bands, depths)` at both call sites and takes **no `kit`**; `frontier_index`
takes all three of `(plan, frontier_part, course)` at **all three** call sites —
`generate`, `provision_kit`'s up-front validation, and Task 15's boundary test — and
`demo/services.py` **imports it by name** (not only `generate`, which was the original
omission: an unbound `frontier_index` is an F821 that kills every provisioning test); `Answers` is
`(correct, wrong, partial)` everywhere; `QuestionPlan` is the six-field
`(element_id, max_marks, answers, fractions, gradeable, sentinel)`; `build_course_plan` returns
`CoursePlan` and every consumer uses its field names; `provision_kit` returns
`ProvisionResult` and `extend_kit` returns `ExtendResult`, both unpacked by attribute; the
warning type is spelled `DemoWarning` at its definition and at all three import sites.

**Names verified against the repo** (not recalled): `parse_numeric_value` and
`canonical_numeric_text` are in `courses/marking.py`; `answer_from_json(question,
latest_answer)` takes the question FIRST while `answer_to_json(answer)` takes only the payload;
`accessible_courses` returns all courses for `is_staff`; `Element.order` is
`OrderField(for_fields=["unit"])`; `pending_reviews_for` returns `{"awaiting", "in_progress"}`.

