# Demo access — PR 3: the admin tab — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A vendor-only "Demo access" tab in institution settings that issues, lists, extends and revokes school demo kits through `demo/services.py`, with the kit Teacher narrowed to non-staff and the concurrent-create race turned into a named error.

**Architecture:** Two small service changes in `demo/services.py`, then the tab in `institution` (views, form, one partial template, one small script). One-time credentials travel in a session list that is written and read through a *separate* `SessionStore`, never through `request.session`, so no stale snapshot is ever saved over other tabs' keys. Every business rule stays in the service; the tab maps service errors to form errors.

**Tech Stack:** Django 5.2, DB-backed sessions, Django templates, vanilla JS, pytest + pytest-django, BeautifulSoup (`beautifulsoup4`, already a dependency), pytest-playwright.

**Spec:** `docs/superpowers/specs/2026-09-12-demo-access-admin-tab-design.md` (below: "the spec"). Its parent is `docs/superpowers/specs/2026-09-12-demo-access-for-schools-design.md` ("the parent"). Read the spec's §4.3–§4.4 before Tasks 5 and 6 — the session rules there are the part of this PR that needed eight review rounds.

## Global Constraints

- **Ships dark** (spec A2): nothing in this PR sets `LIBLI_VENDOR_INSTANCE`. Every demo test turns the flag on itself (`vendor` fixture or `override_settings`); `config/settings/test.py` pins it False.
- **No new bounds in the tab.** No `max_length`, `min_value` or `max_value` on `DemoKitForm`; the service enforces `LABEL_MAX = 200`, `MIN_PUPILS = 5`, `MAX_PUPILS = 40`, `MIN_DAYS = 1`, `MAX_DAYS = 90` (`demo/constants.py`).
- **Non-POST to an action view → 302 to `?tab=demo`**, written `if request.method != "POST"`, never `== "GET"` (spec A5, #307).
- **Every action view:** `@login_required` → `@permission_required("institution.change_institution", raise_exception=True)` → `if not django_settings.VENDOR_INSTANCE: raise Http404` → non-POST redirect → kit lookup 404. `settings` is a *view* in `institution/views_manage.py`; always read the flag as `django_settings.VENDOR_INSTANCE`.
- **Session key:** `"demo_kit_results"`. Never assign it on `request.session` except through `_mirror_demo_results`. Never call `SessionStore.load()` directly in view code — read with `.get()` (it caches).
- **No teacher marking in any copy** (spec A6): nothing about marking answers, grading written work or the awaiting-review queue.
- **Every string translatable**, `pl` filled, 0 fuzzy (`tests/test_i18n_po_health.py`).
- **Tests:** start the test DB container first (`docker compose -p libli-test -f docker-compose.test.yml up -d --wait`). Run tools through `uv run`. **Never pass `-q`** (`addopts` already has it; doubling it suppresses the summary). **Grep the summary line** — the exit code has lied before. e2e needs `-m e2e`. Scope runs to the files named in the step; the whole suite is a branch gate, not a task step, and is OOM-killed if run in one go.
- **In a worktree** there is no `.env`: `export TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli` in the same shell before `uv run pytest` (editing a copied `.env` does not override an exported var).
- **Mutants are applied and reverted BY HAND**, never with `git checkout`/`git restore` (that has destroyed uncommitted work three times). After reverting, `git diff` must show only the intended change.
- **Seeds:** every provisioning test is seeded — `tests/demo/helpers.py::provision_for_test` (seed 4242) for kits a test acts on; `seed_the_view(monkeypatch)` (Task 6) for creates through the tab. Tab-driven creates post `pupils=MIN_PUPILS`.
- Lint gate is **both** `uv run ruff check .` **and** `uv run ruff format --check .`. ⚠️ **Before every task's commit**, run `uv run ruff check --fix --no-cache <the files that task changed>` then `uv run ruff format <those files>`, and include the result in that commit. Ruff here selects `I` with one-import-per-line sorting, so "add imports" anywhere other than their sorted place is an `I001` — caught per task, not four commits later in Task 10. Imports go in their sorted block: stdlib (`import time`, `from datetime import datetime`, `from importlib import import_module`) above Django, Django above first-party.

## Before you start (not code)

- [ ] **Confirm prod holds no kit.** Ask Krzysztof to run, on libli.pl, `cd /opt/libli && docker compose -f docker-compose.prod.yml --env-file .env.production exec -T app /app/.venv/bin/python manage.py demo_access list --all` and confirm it prints nothing (spec §6: no staff kit Teacher to back-fill). Do not SSH to prod yourself.
- [ ] **Branch.** Work on `feat/demo-admin-tab` from `master` (in a worktree if running under subagent-driven-development). Copy the spec and this plan onto it if they are not on `master` yet (`git checkout docs/demo-admin-tab-spec -- docs/superpowers/specs/2026-09-12-demo-access-admin-tab-design.md docs/superpowers/plans/2026-09-13-demo-access-admin-tab.md`). ⚠️ `git checkout <branch> -- <paths>` also STAGES both files, so commit them on their own straight away — `git commit -m "docs: PR 3 spec and plan"` — or Task 1's commit swallows them.

## File structure

| File | Responsibility | Tasks |
|---|---|---|
| `demo/services.py` | non-staff kit Teacher; `_named_collision` | 1, 2 |
| `demo/models.py` | `STATUS_DISPLAY` | 3 |
| `institution/forms.py` | `DemoKitForm` | 6 |
| `institution/views_manage.py` | tab context; settings view credential read/discard; three action views; session helpers | 3–6 |
| `institution/urls.py` | three routes | 4, 6 |
| `templates/institution/manage/_tabs.html` | tab link | 3 |
| `templates/institution/manage/settings.html` | panel include | 3 |
| `templates/institution/manage/_demo_tab.html` | the whole panel (built up through slot comments) | 3–7 |
| `institution/static/institution/js/demo_tab.js` | submit-once, `pageshow` re-enable, bfcache card clearing | 7 |
| `tests/demo/conftest.py` | `vendor` fixture | 3 |
| `tests/demo/tab_helpers.py` | URL, session and HTML helpers for tab tests | 3, 5, 6 |
| `tests/demo/test_provision.py` | P1, P2 | 1, 2 |
| `tests/demo/test_tab_list.py` | P3 (panel), P11 | 3 |
| `tests/demo/test_tab_actions.py` | P3 (extend/revoke), P12, P13 | 4 |
| `tests/demo/test_tab_credentials.py` | P4 (read half), P6, P10 (all kinds), P15, P17, P18, P19b, P20 | 5 |
| `tests/demo/test_tab_create.py` | P3 (create), P4, P5, P7, P8, P9, P10 (provision), P11 (error page), P14, P16, P19a | 6 |
| `tests/test_settings_action_method_guard.py` | three new action URLs | 4, 6 |
| `tests/test_e2e_demo_tab.py` | the one e2e | 7 |
| `locale/{pl,en}/LC_MESSAGES/django.{po,mo}` | strings | 8 |
| parent spec, spec, `docs/deployment.md` | amendments | 9 |

---

### Task 1: The kit Teacher is non-staff (spec §3.1, P1)

**Files:**
- Modify: `demo/services.py` (`_make_user` docstring; teacher creation in `provision_kit`)
- Modify: `tests/demo/test_provision.py:25` and replace `test_the_demo_teacher_can_read_every_course_on_the_box` (`:305-330`)

**Interfaces:**
- Consumes: `provision_kit` (existing), `tests.demo.helpers.provision_for_test`, `tests.demo.fixtures.small_course`.
- Produces: kit Teachers with `is_staff == False`. Nothing else changes shape.

- [ ] **Step 1: Write the failing test.** In `tests/demo/test_provision.py`, change line 25 from `assert kit.teacher.is_staff and not kit.student.is_staff` to:

```python
    assert not kit.teacher.is_staff and not kit.student.is_staff
```

Then replace the whole `test_the_demo_teacher_can_read_every_course_on_the_box` function (decorator included) with:

```python
@pytest.mark.django_db
def test_the_demo_teacher_reads_only_its_kit_course(client):
    """P1 (PR 3 spec §3.1). A kit Teacher is NOT staff, so accessible_courses
    takes its taught-groups branch — the kit's course alone — and Django admin
    refuses it.

    What this closes is COURSE CONTENT across courses plus an /admin/ login. It is
    not pupil data: group scoping already kept kit A's Teacher out of kit B's
    pupils (parent T9). Driven as the role, through real requests, because a
    queryset assertion cannot see a view that gates on something else.
    """
    from django.urls import reverse

    from courses.access import accessible_courses
    from courses.models import ContentNode
    from courses.models import Course
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    course = small_course()
    other = Course.objects.create(slug="other", title="Other", language="pl")
    kit = provision_for_test(course)

    assert not kit.teacher.is_staff
    assert set(accessible_courses(kit.teacher)) == {course}
    # The rep's Student login was always narrow.
    assert other not in accessible_courses(kit.student)

    client.force_login(kit.teacher)
    lesson = ContentNode.objects.filter(
        course=course, unit_type="lesson", published=True
    ).first()
    quiz = ContentNode.objects.filter(
        course=course, unit_type="quiz", published=True
    ).first()
    reachable = [
        reverse("courses:course_outline", kwargs={"slug": course.slug}),
        reverse(
            "courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": lesson.pk}
        ),
        reverse("courses:quiz_unit", kwargs={"slug": course.slug, "node_pk": quiz.pk}),
        reverse("courses:manage_analytics", kwargs={"slug": course.slug}),
        reverse("courses:manage_review_queue", kwargs={"slug": course.slug}),
    ]
    for url in reachable:
        assert client.get(url).status_code == 200, url

    outline_of_other = reverse("courses:course_outline", kwargs={"slug": other.slug})
    assert client.get(outline_of_other).status_code == 403  # PermissionDenied

    admin = client.get("/admin/")
    assert admin.status_code == 302
    assert admin["Location"].startswith("/admin/login/")
```

(No `CohortMembership` assertion: it holds on every build — spec P1.)

- [ ] **Step 2: Run it to see it fail.**

Run: `uv run pytest tests/demo/test_provision.py -k "reads_only_its_kit_course or provisions_a_teacher"`
Expected: both FAIL on `assert not kit.teacher.is_staff`. None of the `reachable` URLs should redirect: a non-enrolled viewer of a quiz gets the previewer (`courses/views.py` `quiz_unit`, `"previewing": not enrolled`), which renders with 200. If any returns non-200 on the fixed build (Step 4) — a 302 (print `response["Location"]`), a 403 from `course_outline`/`lesson_unit`/`quiz_unit`, or a 404 from `review_queue`/`analytics_matrix` — STOP and establish which gate refused the non-staff Teacher: `courses.access.accessible_courses`' taught-groups branch, or `grouping.scoping.can_review_course` / `groups_visible_to`. Do not loosen the assertion (no `follow=True`) and do not widen any gate to make it pass; that refusal may be exactly the behaviour change this task must not introduce.

- [ ] **Step 3: Implement.** In `demo/services.py`, replace the teacher block:

```python
    teacher = _make_user(
        teacher_name,
        display_name=f"Nauczyciel demo — {label} (#{kit.pk})"[:150],
        password=teacher_password,
        role=TEACHER,  # role_is_staff(TEACHER) -> is_staff
    )
```

with:

```python
    teacher = _make_user(
        teacher_name,
        display_name=f"Nauczyciel demo — {label} (#{kit.pk})"[:150],
        password=teacher_password,
        role=TEACHER,  # role_is_staff(TEACHER) -> is_staff; cleared just below
    )
    # PR 3 spec A1/§3.1: a kit Teacher is NOT staff. set_user_role is the last
    # writer of is_staff (accounts/services.py:36-37), so this must come AFTER it.
    # It narrows accessible_courses to the taught-groups branch (the kit's course
    # only) and closes the /admin/ login. Cohorts are unaffected: this save fires
    # post_save with created=False, and is_staff_user still sees the Teacher role.
    # A Platform Admin changing this user's role later re-grants staff — accepted.
    teacher.is_staff = False
    teacher.save(update_fields=["is_staff"])
```

In `_make_user`'s docstring, replace the last paragraph:

```
    The role is therefore the single authority: `role_is_staff(TEACHER)` is True,
    which IS the course-access widening documented above.
```

with:

```
    The role is therefore the single authority: `role_is_staff(TEACHER)` is True —
    and provision_kit clears the flag on the kit Teacher straight after this
    returns (PR 3 spec §3.1), undoing the course-access widening.
```

- [ ] **Step 4: Run to see it pass.**

Run: `uv run pytest tests/demo tests/test_access_taught_courses.py`
Expected: summary line reports all passed, 0 failed. (Every kit Teacher is now non-staff, and the other demo test modules drive that Teacher — so the whole `tests/demo` package, still a scoped run.)

- [ ] **Step 5: Falsify.** Delete the two lines `teacher.is_staff = False` / `teacher.save(update_fields=["is_staff"])` by hand. Run `uv run pytest tests/demo/test_provision.py -k reads_only_its_kit_course` → FAIL. Restore the two lines by hand; `git diff demo/services.py` shows them present.

- [ ] **Step 6: Commit.**

```bash
git add demo/services.py tests/demo/test_provision.py
git commit -m "feat(demo): kit Teacher is non-staff — reads only its kit course"
```

---

### Task 2: A concurrent create becomes `UsernameCollision` (spec §3.2, P2)

**Files:**
- Modify: `demo/services.py`
- Test: `tests/demo/test_provision.py` (append)

**Interfaces:**
- Consumes: `errors.UsernameCollision` (existing).
- Produces: `provision_kit` raises `UsernameCollision` (with `__cause__` an `IntegrityError`) when user creation hits the unique index. Its message contains no "retry".

- [ ] **Step 1: Write the failing tests.** Append to `tests/demo/test_provision.py`:

```python
@pytest.mark.django_db
def test_a_concurrent_create_surfaces_as_a_named_collision(monkeypatch):
    """P2 (PR 3 spec §3.2). Two creates for one slug both pass `_taken` — neither
    sees the other's uncommitted users — and the loser hits the username unique
    index. A pre-existing user plus a blind scan reproduces that without threads."""
    from django.contrib.auth import get_user_model
    from django.db import IntegrityError

    from demo.models import DemoKit
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    course = small_course()
    get_user_model().objects.create_user(username="sp-12-nauczyciel")
    monkeypatch.setattr("demo.services._taken", lambda names: False)

    with pytest.raises(errors.UsernameCollision) as caught:
        provision_for_test(course, label="SP 12")

    assert isinstance(caught.value.__cause__, IntegrityError)
    assert "retry" not in str(caught.value).lower()
    assert not DemoKit.objects.exists()


@pytest.mark.django_db
def test_an_integrity_error_outside_user_creation_is_not_a_collision(monkeypatch):
    """The catch wraps USER CREATION ONLY: a generator bug must surface as itself,
    never as "a kit for this label may have just been created"."""
    from django.db import IntegrityError

    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    def broken_generator(*args, **kwargs):
        raise IntegrityError("generator bug")

    monkeypatch.setattr("demo.services.generate", broken_generator)

    with pytest.raises(IntegrityError):
        provision_for_test(small_course())
```

- [ ] **Step 2: Run to see the first fail.**

Run: `uv run pytest tests/demo/test_provision.py -k "named_collision or not_a_collision"`
Expected: `test_a_concurrent_create_surfaces_as_a_named_collision` FAILS (a bare `IntegrityError` escapes); the other passes already (it is the guard against over-wrapping).

- [ ] **Step 3: Implement.** In `demo/services.py` add `from django.db import IntegrityError` beside `from django.db import transaction`. Add, above `_make_user`:

```python
@contextlib.contextmanager
def _named_collision(slug):
    """PR 3 spec §3.2 — restores the parent's §4.4 step 0, which PR 2 shipped
    without.

    Two concurrent creates for one slug both pass `_taken`: neither can see the
    other's uncommitted users, so the loser blocks on the username unique index
    and then raises IntegrityError. From the tab that is a double-clicked Create.

    ⚠️ NO QUERY and NO RETRY here: the atomic block is already marked for
    rollback, so any ORM call raises TransactionManagementError and buries the
    named error. It wraps USER CREATION ONLY, so an IntegrityError from anywhere
    else — a generator bug — is never mislabelled as a collision. The message never
    says "retry": the realistic cause is a double run whose other half has just
    committed a live kit.
    """
    try:
        yield
    except IntegrityError as exc:
        raise errors.UsernameCollision(
            f"login names for {slug!r} are already taken: another create for it "
            "may still be running or may just have finished — check the kit list "
            "before creating again"
        ) from exc
```

In `provision_kit`, wrap the three `_make_user` calls — and nothing else — so the teacher block reads:

```python
    with _named_collision(slug):
        teacher = _make_user(
            teacher_name,
            display_name=f"Nauczyciel demo — {label} (#{kit.pk})"[:150],
            password=teacher_password,
            role=TEACHER,  # role_is_staff(TEACHER) -> is_staff; cleared just below
        )
```

(the Task 1 `is_staff` lines stay after the `with` block, unindented), the student block:

```python
    with _named_collision(slug):
        student = _make_user(
            student_name,
            display_name=f"Uczeń demo — {label} (#{kit.pk})"[:150],
            password=student_password,
            role=STUDENT,
        )
```

and the pupil loop body:

```python
    for username, (first, last) in zip(pupil_names, names, strict=True):
        with _named_collision(slug):
            pupil = _make_user(
                username,
                display_name=f"{first} {last}",
                first_name=first,
                last_name=last,
                role=STUDENT,
            )
        kit.users.add(pupil)
        pupil_users.append(pupil)
```

- [ ] **Step 4: Run to see them pass.**

Run: `uv run pytest tests/demo/test_provision.py tests/demo/test_command.py`
(if `tests/demo/test_command.py` does not exist, run `uv run pytest tests/demo` instead)
Expected: all passed.

- [ ] **Step 5: Falsify — two mutants, one at a time, by hand.**
  1. Replace the body of `_named_collision` with a bare `yield` (no try). Run the Step 2 command → the collision test FAILS. Restore.
  2. Remove the three `with _named_collision(slug):` wrappers (dedent the calls) and instead wrap the entire body of `provision_kit` after `slug = ...` in one `with _named_collision(slug):`. Run the Step 2 command → `test_an_integrity_error_outside_user_creation_is_not_a_collision` FAILS. Restore by hand; `git diff demo/services.py` shows the three narrow wrappers.

- [ ] **Step 6: Commit.**

```bash
git add demo/services.py tests/demo/test_provision.py
git commit -m "fix(demo): a concurrent create raises UsernameCollision, not IntegrityError"
```

---

### Task 3: The Demo panel and the kit list (spec §4.1, §4.6; P3 panel half, P11)

**Files:**
- Modify: `demo/models.py` (append `STATUS_DISPLAY`)
- Modify: `institution/views_manage.py` (`_tabs`, `_settings_context`, `settings`, new `_demo_context`)
- Modify: `templates/institution/manage/_tabs.html`, `templates/institution/manage/settings.html`
- Create: `templates/institution/manage/_demo_tab.html`
- Create: `tests/demo/conftest.py`, `tests/demo/tab_helpers.py`, `tests/demo/test_tab_list.py`

**Interfaces:**
- Consumes: `DemoKit.status_key` (`demo/models.py:88-97`).
- Produces:
  - `demo.models.STATUS_DISPLAY: dict[str, lazy str]` keyed by every `status_key`.
  - `_settings_context(request, inst, active_tab, *, ..., demo_form=None, demo_show_all=False)` — adds context keys `demo_form`, `demo_kits`, `demo_show_all`, `demo_extend_label` (all `None`/`False` off the Demo tab; `demo_form` and `demo_extend_label` are filled by Tasks 6 and 4).
  - Each kit in `demo_kits` carries `.status_label`.
  - `_demo_tab.html` with slot comments `{# demo:results #}`, `{# demo:create-form #}`, `{# demo:row-actions #}`, `{# demo:scripts #}` that later tasks replace.
  - Test fixture `vendor`; helpers `demo_tab_url(show_all=False)`, `soup(response)`, `row_ids(response)`.

- [ ] **Step 1: Write the fixture and helpers.** Create `tests/demo/conftest.py`:

```python
import pytest


@pytest.fixture
def vendor(settings):
    """The demo tab exists only on the vendor instance, and config/settings/test.py
    pins VENDOR_INSTANCE False. pytest-django's `settings` restores it afterwards."""
    settings.VENDOR_INSTANCE = True
    return settings
```

Create `tests/demo/tab_helpers.py`:

```python
"""Shared helpers for the PR 3 demo-tab tests."""

from bs4 import BeautifulSoup
from django.urls import reverse


def demo_tab_url(show_all=False):
    url = reverse("institution:settings") + "?tab=demo"
    return f"{url}&all=1" if show_all else url


def soup(response):
    return BeautifulSoup(response.content, "html.parser")


def row_ids(response):
    """Kit pks of the list rows, in page order. Located by the data-demo-kit hook,
    never by an id substring — course, group and user pks share the page."""
    return [int(tr["data-demo-kit"]) for tr in soup(response).select("tr[data-demo-kit]")]
```


- [ ] **Step 2: Write the failing tests.** Create `tests/demo/test_tab_list.py`:

```python
from datetime import timedelta

import pytest
from django.utils import timezone

from demo.models import DemoKit
from demo.services import revoke_kit
from tests.demo.fixtures import small_course
from tests.demo.helpers import provision_for_test
from tests.demo.tab_helpers import demo_tab_url
from tests.demo.tab_helpers import row_ids
from tests.demo.tab_helpers import soup


def test_the_tab_is_absent_on_a_school_box(pa_client):
    """P3, panel half. Flag off: no link, no panel, and ?tab=demo falls back to
    branding with a 200 — a hidden tab is not a 404."""
    response = pa_client.get(demo_tab_url())
    body = response.content.decode()

    assert response.status_code == 200
    assert response.context["active_tab"] == "branding"
    assert "?tab=demo" not in body
    assert "data-demo-list" not in body


def test_the_tab_is_present_and_open_on_the_vendor_box(pa_client, vendor):
    response = pa_client.get(demo_tab_url())
    page = soup(response)

    assert response.context["active_tab"] == "demo"
    assert page.select_one('a[href$="?tab=demo"]') is not None
    panel = page.select_one('div[data-tab="demo"]')
    assert panel is not None and not panel.has_attr("hidden")
    assert panel.select_one("[data-demo-list]") is not None


def test_the_panel_renders_nothing_on_another_tab(pa_client, vendor):
    """Spec §4.1: the hidden panel on other tabs renders nothing against the None
    context, and builds no kit list."""
    response = pa_client.get(demo_tab_url().replace("tab=demo", "tab=branding"))

    assert response.context["demo_kits"] is None
    assert "data-demo-list" not in response.content.decode()


def test_the_list_shows_open_kits_newest_first_and_all_adds_closed(pa_client, vendor):
    """P11."""
    course = small_course()
    oldest = provision_for_test(course, label="Alpha")
    middle = provision_for_test(course, label="Beta")
    newest = provision_for_test(course, label="Gamma")
    DemoKit.objects.filter(pk=middle.pk).update(
        expires_at=timezone.now() - timedelta(days=1)
    )
    revoke_kit(oldest)

    default = pa_client.get(demo_tab_url())
    assert row_ids(default) == [newest.pk, middle.pk]

    everything = pa_client.get(demo_tab_url(show_all=True))
    assert row_ids(everything) == [newest.pk, middle.pk, oldest.pk]
    closed_row = soup(everything).select_one(f'tr[data-demo-kit="{oldest.pk}"]')
    assert "—" in closed_row.get_text()  # the teacher FK was nulled by the purge


def test_status_display_covers_every_status_key():
    from demo.models import STATUS_DISPLAY

    keys = {"active", "pending_purge"} | {
        f"closed_{value}" for value in DemoKit.ClosedReason.values
    }
    assert set(STATUS_DISPLAY) == keys


@pytest.mark.parametrize("value", ["0", "yes", "true"])
def test_only_the_literal_one_shows_closed_kits(pa_client, vendor, value):
    course = small_course()
    closed = provision_for_test(course, label="Closed")
    revoke_kit(closed)

    response = pa_client.get(demo_tab_url() + f"&all={value}")
    assert row_ids(response) == []
```


- [ ] **Step 3: Run to see them fail.**

Run: `uv run pytest tests/demo/test_tab_list.py`
Expected: FAIL — `ImportError: cannot import name 'STATUS_DISPLAY'`, `KeyError: 'demo_kits'`, `active_tab` is `branding` on the vendor box. **Four cases PASS already, and that is expected:** `test_the_tab_is_absent_on_a_school_box` and the three `test_only_the_literal_one_shows_closed_kits` cases, because the branding fallback renders no demo link and no rows. Do not change them to make them red — Step 8's mutants are what prove they can fail.

- [ ] **Step 4: Implement `STATUS_DISPLAY`.** Append to `demo/models.py` (and add `from django.utils.translation import pgettext_lazy` beside the existing `gettext_lazy` import):

```python
# Translated labels for DemoKit.status_key, used only by PR 3's tab. They sit
# beside the property that produces the keys, as demo.warnings.DISPLAY sits beside
# KINDS; `demo_access list` prints the keys, never these. A msgctxt because
# "Active" already exists in the catalog with another meaning. ⚠️ The Polish must
# agree with ClosedReason's neuter "Wygasłe" / "Cofnięte".
STATUS_DISPLAY = {
    "active": pgettext_lazy("demo kit status", "Active"),
    "pending_purge": pgettext_lazy("demo kit status", "Expired — pending purge"),
    "closed_expired": pgettext_lazy("demo kit status", "Closed (expired)"),
    "closed_revoked": pgettext_lazy("demo kit status", "Closed (revoked)"),
}
```

- [ ] **Step 5: Implement the context.** In `institution/views_manage.py`:

Add imports (keep ruff's one-per-line sorted style):

```python
from demo.models import STATUS_DISPLAY
from demo.models import DemoKit
```

Replace `_tabs`:

```python
def _tabs():
    """Per REQUEST, not at import. A module-level conditional tuple is evaluated
    once, so override_settings(VENDOR_INSTANCE=True) would never reach it and the
    gate would half-work: the tab link renders, ?tab=pricing falls back to
    branding, and the panel never opens. Demo access (PR 3) is vendor-only for the
    same reason Pricing is."""
    vendor_tabs = ("pricing", "demo") if django_settings.VENDOR_INSTANCE else ()
    return _BASE_TABS + vendor_tabs
```

Add below `_active_tab`:

```python
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
        "demo_extend_label": None,
    }
```

Change `_settings_context`'s signature to add two keyword parameters after `pricing=None,`:

```python
    pricing=None,
    demo_form=None,
    demo_show_all=False,
):
```

and change its `return {` … `}` to `return {` … `, **_demo_context(active_tab, demo_form, demo_show_all)}` — i.e. add as the last entry of the returned dict:

```python
        **_demo_context(active_tab, demo_form, demo_show_all),
    }
```

Replace the `settings` view body:

```python
@login_required
@permission_required("institution.change_institution", raise_exception=True)
def settings(request):
    inst = Institution.load()
    ctx = _settings_context(
        request,
        inst,
        _active_tab(request),
        # Spec §4.6: only the literal "1" shows closed kits.
        demo_show_all=request.GET.get("all") == "1",
    )
    return render(request, "institution/manage/settings.html", ctx)
```

- [ ] **Step 6: Implement the templates.** In `templates/institution/manage/_tabs.html`, replace:

```django
  {% if vendor_instance %}
  <a class="settings__tab{% if active_tab == 'pricing' %} is-on{% endif %}"
     href="{% url 'institution:settings' %}?tab=pricing">{% trans "Pricing" %}</a>
  {% endif %}
```

with:

```django
  {% if vendor_instance %}
  <a class="settings__tab{% if active_tab == 'pricing' %} is-on{% endif %}"
     href="{% url 'institution:settings' %}?tab=pricing">{% trans "Pricing" %}</a>
  <a class="settings__tab{% if active_tab == 'demo' %} is-on{% endif %}"
     href="{% url 'institution:settings' %}?tab=demo">{% trans "Demo access" %}</a>
  {% endif %}
```

In `templates/institution/manage/settings.html`, replace:

```django
  <div data-tab="pricing" {% if active_tab != "pricing" %}hidden{% endif %}>
    {% include "institution/manage/_pricing_tab.html" %}
  </div>
  {% endif %}
```

with:

```django
  <div data-tab="pricing" {% if active_tab != "pricing" %}hidden{% endif %}>
    {% include "institution/manage/_pricing_tab.html" %}
  </div>
  <div data-tab="demo" {% if active_tab != "demo" %}hidden{% endif %}>
    {% include "institution/manage/_demo_tab.html" %}
  </div>
  {% endif %}
```

Create `templates/institution/manage/_demo_tab.html`:

```django
{% load i18n static %}
{% if active_tab == "demo" %}
{# PR 3 spec §4.1: the whole body, scripts included, renders only on the Demo tab. #}
{# ⚠️ Every link and form action here is absolute ({% url %}): this panel also renders on the create view's error page, served at .../demo/create/. #}
<div class="settings__section">
  <h2 class="settings__section-title">{% trans "Demo access" %}</h2>
  <p class="settings__help">{% trans "A demo kit is a Teacher login — class analytics, per-pupil progress and force-submitting an unfinished quiz — a pupil login that starts with a blank record, and an example class of generated pupils. It lasts the chosen number of days and is then deleted automatically." %}</p>
</div>
{# demo:results #}
{# demo:create-form #}
<div class="settings__section" data-demo-list>
  <h2 class="settings__section-title">{% trans "Demo kits" %}</h2>
  <p class="settings__help">
    {% if demo_show_all %}
    <a href="{% url 'institution:settings' %}?tab=demo">{% trans "Show open kits only" %}</a>
    {% else %}
    <a href="{% url 'institution:settings' %}?tab=demo&amp;all=1" data-demo-show-all>{% trans "Show closed kits too" %}</a>
    {% endif %}
  </p>
  {% if demo_kits %}
  <div class="scroll-x" data-scroll-x><table class="settings__table">
    <thead>
      <tr>
        <th>#</th>
        <th>{% trans "Label" %}</th>
        <th>{% trans "Course" %}</th>
        <th>{% trans "Pupils" %}</th>
        <th>{% trans "Teacher login" %}</th>
        <th>{% trans "Created" %}</th>
        <th>{% trans "Expires" %}</th>
        <th>{% trans "Status" %}</th>
        <th>{% trans "Actions" %}</th>
      </tr>
    </thead>
    <tbody>
      {% for kit in demo_kits %}
      <tr data-demo-kit="{{ kit.pk }}">
        <td>{{ kit.pk }}</td>
        <td>{{ kit.label }}</td>
        <td>{{ kit.course_slug }}</td>
        <td>{{ kit.pupil_count }}</td>
        <td>{% if kit.teacher %}{{ kit.teacher.username }}{% else %}—{% endif %}</td>
        <td>{{ kit.created_at|date }}</td>
        <td>{{ kit.expires_at|date }}</td>
        <td>{{ kit.status_label }}</td>
        <td>{# demo:row-actions #}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table></div>
  {% else %}
  <p class="settings__help">{% trans "No demo kits." %}</p>
  {% endif %}
</div>
{# demo:scripts #}
{% endif %}
```

- [ ] **Step 7: Run to see them pass.**

Run: `uv run pytest tests/demo/test_tab_list.py tests/test_pricing_settings_tab.py`
Expected: all passed.

- [ ] **Step 8: Falsify — two mutants, one at a time, by hand, restoring after each.**
  1. In `_demo_context`, delete the two lines `if not show_all:` / `kits = kits.filter(closed_at__isnull=True)`. Run `uv run pytest tests/demo/test_tab_list.py -k "newest_first or literal_one"` → both FAIL.
  2. In the `settings` view, change `demo_show_all=request.GET.get("all") == "1"` to `demo_show_all=bool(request.GET.get("all"))`. Run `uv run pytest tests/demo/test_tab_list.py -k literal_one` → all three parametrised cases FAIL.

- [ ] **Step 9: Commit.**

```bash
git add demo/models.py institution/views_manage.py templates/institution/manage/_tabs.html templates/institution/manage/settings.html templates/institution/manage/_demo_tab.html tests/demo/conftest.py tests/demo/tab_helpers.py tests/demo/test_tab_list.py
git commit -m "feat(institution): vendor-only Demo access tab with the kit list"
```

---

### Task 4: Extend and revoke (spec §4.1, §4.7; P3 extend/revoke, P12, P13)

**Files:**
- Modify: `institution/urls.py`, `institution/views_manage.py`, `templates/institution/manage/_demo_tab.html`, `tests/test_settings_action_method_guard.py`
- Create: `tests/demo/test_tab_actions.py`

**Interfaces:**
- Consumes: `demo.services.extend_kit(kit, *, days) -> ExtendResult(kit, new_expires_at, long_lived)`, `demo.services.revoke_kit(kit)`, `demo.errors.KitAlreadyClosed`, Task 3's `_demo_context`.
- Produces: URL names `institution:settings_demo_extend` and `institution:settings_demo_revoke` (kwarg `kit_id`); helpers `_demo_list_url(request)` and `_demo_kit_or_404(kit_id)`; context key `demo_extend_label`.

- [ ] **Step 1: Write the failing tests.** Create `tests/demo/test_tab_actions.py`:

```python
from datetime import timedelta

import pytest
from django.contrib import messages as django_messages
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format

from demo.constants import DEFAULT_DAYS
from demo.constants import LONG_LIVED_DAYS
from demo.models import DemoKit
from demo.services import revoke_kit
from tests.demo.fixtures import small_course
from tests.demo.helpers import provision_for_test
from tests.demo.tab_helpers import demo_tab_url
from tests.demo.tab_helpers import soup
from tests.factories import make_teacher


def _extend(client, kit, **data):
    return client.post(
        reverse("institution:settings_demo_extend", kwargs={"kit_id": kit.pk}), data
    )


def _revoke(client, kit, **data):
    return client.post(
        reverse("institution:settings_demo_revoke", kwargs={"kit_id": kit.pk}), data
    )


def _messages(response, level=None):
    found = list(get_messages(response.wsgi_request))
    return [str(m) for m in found if level is None or m.level == level]


def test_extend_moves_an_active_kit_by_the_default_and_does_not_warn(
    pa_client, vendor
):
    """P12."""
    kit = provision_for_test(small_course())
    before = kit.expires_at

    response = _extend(pa_client, kit)

    kit.refresh_from_db()
    assert kit.expires_at == before + timedelta(days=DEFAULT_DAYS)
    success = _messages(response, django_messages.SUCCESS)
    assert any(date_format(timezone.localtime(kit.expires_at)) in m for m in success)
    assert _messages(response, django_messages.WARNING) == []


def test_extend_restarts_a_pending_purge_kit_from_now(pa_client, vendor):
    kit = provision_for_test(small_course())
    DemoKit.objects.filter(pk=kit.pk).update(
        expires_at=timezone.now() - timedelta(days=1)
    )

    _extend(pa_client, kit)

    kit.refresh_from_db()
    target = timezone.now() + timedelta(days=DEFAULT_DAYS)
    assert abs((kit.expires_at - target).total_seconds()) < 60
    assert kit.status_key == "active"


def test_extend_warns_about_a_long_lived_kit(pa_client, vendor):
    kit = provision_for_test(small_course())
    DemoKit.objects.filter(pk=kit.pk).update(
        created_at=timezone.now() - timedelta(days=50)
    )

    response = _extend(pa_client, kit)

    warnings = _messages(response, django_messages.WARNING)
    assert len(warnings) == 1
    assert f"more than {LONG_LIVED_DAYS} days" in warnings[0]


def test_extend_refuses_a_closed_kit(pa_client, vendor):
    kit = provision_for_test(small_course())
    revoke_kit(kit)
    kit.refresh_from_db()
    before = kit.expires_at

    response = _extend(pa_client, kit)

    kit.refresh_from_db()
    assert kit.expires_at == before
    assert _messages(response, django_messages.ERROR)


@pytest.mark.parametrize(("posted", "suffix"), [("1", "&all=1"), ("x", "")])
def test_extend_returns_to_the_list_it_came_from(pa_client, vendor, posted, suffix):
    kit = provision_for_test(small_course())

    response = _extend(pa_client, kit, all=posted)

    assert response["Location"] == demo_tab_url() + suffix


def test_revoke_closes_the_kit_and_deletes_its_logins(pa_client, vendor):
    """P13."""
    kit = provision_for_test(small_course())
    user_ids = list(kit.users.values_list("pk", flat=True))

    response = _revoke(pa_client, kit)

    kit.refresh_from_db()
    assert kit.closed_reason == DemoKit.ClosedReason.REVOKED
    assert not get_user_model().objects.filter(pk__in=user_ids).exists()
    assert _messages(response, django_messages.SUCCESS)


def test_revoke_refuses_a_closed_kit(pa_client, vendor):
    kit = provision_for_test(small_course())
    revoke_kit(kit)

    response = _revoke(pa_client, kit)

    assert _messages(response, django_messages.ERROR)


@pytest.mark.parametrize(("posted", "suffix"), [("1", "&all=1"), ("x", "")])
def test_revoke_returns_to_the_list_it_came_from(pa_client, vendor, posted, suffix):
    kit = provision_for_test(small_course())

    response = _revoke(pa_client, kit, all=posted)

    assert response["Location"] == demo_tab_url() + suffix


def test_a_closed_row_has_no_actions(pa_client, vendor):
    """Asserted on ?all=1 — the default list excludes closed kits, so asserting
    there would be vacuous — and against an open row on the same page, so the
    test cannot pass because action forms never render at all."""
    course = small_course()
    closed = provision_for_test(course, label="Closed")
    open_kit = provision_for_test(course, label="Open")
    revoke_kit(closed)

    page = soup(pa_client.get(demo_tab_url(show_all=True)))

    closed_row = page.select_one(f'tr[data-demo-kit="{closed.pk}"]')
    open_row = page.select_one(f'tr[data-demo-kit="{open_kit.pk}"]')
    assert closed_row.select("form") == []
    assert open_row.select_one("form[data-demo-extend]") is not None
    assert open_row.select_one("form[data-demo-revoke]") is not None


def test_extend_and_revoke_404_on_a_school_box_for_a_real_open_kit(pa_client):
    """P3. A REAL open kit: against a missing id the views' own kit lookup 404s,
    which would keep this green with the vendor check deleted."""
    kit = provision_for_test(small_course())
    before = kit.expires_at

    assert _extend(pa_client, kit).status_code == 404
    assert _revoke(pa_client, kit).status_code == 404

    kit.refresh_from_db()
    assert kit.closed_at is None
    assert kit.expires_at == before


def test_the_actions_need_change_institution(client, vendor):
    kit = provision_for_test(small_course())
    make_teacher(client)

    assert _extend(client, kit).status_code == 403
    assert _revoke(client, kit).status_code == 403
```

- [ ] **Step 2: Run to see them fail.**

Run: `uv run pytest tests/demo/test_tab_actions.py`
Expected: FAIL — `NoReverseMatch: 'settings_demo_extend'`.

- [ ] **Step 3: Implement the routes.** In `institution/urls.py`, after the `settings_pricing` path:

```python
    path(
        "manage/settings/demo/<int:kit_id>/extend/",
        views_manage.settings_demo_extend,
        name="settings_demo_extend",
    ),
    path(
        "manage/settings/demo/<int:kit_id>/revoke/",
        views_manage.settings_demo_revoke,
        name="settings_demo_revoke",
    ),
```

- [ ] **Step 4: Implement the views.** In `institution/views_manage.py` add imports:

```python
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import ngettext

from demo import errors as demo_errors
from demo.constants import DEFAULT_DAYS
from demo.constants import LONG_LIVED_DAYS
from demo.services import extend_kit
from demo.services import revoke_kit
```

In `_demo_context`, replace `"demo_extend_label": None,` in the Demo-tab return (not the off-tab one) with:

```python
        "demo_extend_label": ngettext(
            "Extend by %(days)d day", "Extend by %(days)d days", DEFAULT_DAYS
        )
        % {"days": DEFAULT_DAYS},
```

Append at the end of the module:

```python
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
```

- [ ] **Step 5: Implement the row actions.** In `_demo_tab.html`, replace `<td>{# demo:row-actions #}</td>` with:

```django
        <td>
          {% if not kit.closed_at %}
          <form method="post" action="{% url 'institution:settings_demo_extend' kit.pk %}" data-demo-extend>
            {% csrf_token %}
            {% if demo_show_all %}<input type="hidden" name="all" value="1">{% endif %}
            <button class="btn" type="submit">{{ demo_extend_label }}</button>
          </form>
          <form method="post" action="{% url 'institution:settings_demo_revoke' kit.pk %}" data-demo-revoke
                data-confirm="{% trans 'Revoke this demo kit? Its logins are deleted immediately.' %}">
            {% csrf_token %}
            {% if demo_show_all %}<input type="hidden" name="all" value="1">{% endif %}
            <button class="btn" type="submit">{% trans "Revoke" %}</button>
          </form>
          {% endif %}
        </td>
```

Replace `{# demo:scripts #}` with (keep the slot for Task 7):

```django
{# confirm.js binds once, to the forms that exist when it runs — `defer` makes that placement-independent. #}
<script src="{% static 'support/js/confirm.js' %}" defer></script>
{# demo:scripts #}
```

- [ ] **Step 6: Extend the method guard.** In `tests/test_settings_action_method_guard.py`, replace the block from `# Every settings action view.` through the end of `test_settings_action_redirects_instead_of_running_on_non_post` with:

```python
# Every settings action view, with the URL kwargs its route needs. The first six
# share the `_action` helper, so they stand or fall together; the rest carry their
# own copy of the guard. The demo views reject a non-POST before they look the kit
# up, so any kit id will do.
ACTION_URLS = [
    ("institution:settings_branding", {}),
    ("institution:settings_access", {}),
    ("institution:settings_uploads", {}),
    ("institution:settings_notifications", {}),
    ("institution:settings_public_pages", {}),
    ("institution:settings_pricing", {}),
    ("institution:settings_notifications_purge", {}),
    ("institution:settings_sso", {}),
    ("institution:settings_integrations", {}),
    ("institution:settings_integrations_test", {}),
    ("institution:settings_page_overrides", {}),  # already correct since #279
    ("institution:settings_support", {}),
    ("institution:settings_demo_extend", {"kit_id": 1}),
    ("institution:settings_demo_revoke", {"kit_id": 1}),
]

# The four that fell through. GET is excluded deliberately: it was always
# handled, so including it would let the test pass on the broken build.
NON_POST_METHODS = ["head", "options", "put", "delete"]


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
@pytest.mark.parametrize(("url_name", "kwargs"), ACTION_URLS)
@pytest.mark.parametrize("method", NON_POST_METHODS)
def test_settings_action_redirects_instead_of_running_on_non_post(
    client, url_name, kwargs, method
):
    """A non-POST is turned away at the door, exactly as a GET is.

    302 rather than 405 follows the contract these views already state ("actions
    are POST targets") and matches #279's fix, so the whole family behaves one
    way. A 200 here means the body rendered -- i.e. the request reached the
    action.

    VENDOR_INSTANCE=True is needed by settings_pricing and the demo action views
    (each 404s without the flag, and the guard would assert nothing) -- harmless
    for the views that do not read it.
    """
    make_pa(client)

    response = getattr(client, method)(reverse(url_name, kwargs=kwargs))

    assert response.status_code == 302, (
        f"{url_name} answered {method.upper()} with {response.status_code}; "
        "a non-POST must be redirected, not executed"
    )
```

- [ ] **Step 7: Run to see them pass.**

Run: `uv run pytest tests/demo/test_tab_actions.py tests/demo/test_tab_list.py tests/test_settings_action_method_guard.py`
Expected: all passed.

- [ ] **Step 8: Falsify — one at a time, by hand, restoring after each.**
  1. Delete `if not django_settings.VENDOR_INSTANCE: raise Http404` from both demo action views → `test_extend_and_revoke_404_on_a_school_box_for_a_real_open_kit` FAILS (extend raises `ImproperlyConfigured`, revoke closes the kit).
  2. In `settings_demo_extend`, delete the `if result.long_lived:` block → `test_extend_warns_about_a_long_lived_kit` FAILS.
  3. Change `if result.long_lived:` to `if True:` → `test_extend_moves_an_active_kit_by_the_default_and_does_not_warn` FAILS.
  4. In `_demo_list_url`, return `_index_url("demo")` unconditionally → both `returns_to_the_list` tests FAIL on the `"1"` case.
  5. In `settings_demo_revoke`, replace `revoke_kit(kit)` with `pass` → `test_revoke_closes_the_kit_and_deletes_its_logins` FAILS.
  6. In `_demo_tab.html`, delete `{% if not kit.closed_at %}` and its `{% endif %}` → `test_a_closed_row_has_no_actions` FAILS.

- [ ] **Step 9: Commit.**

```bash
git add institution/urls.py institution/views_manage.py templates/institution/manage/_demo_tab.html tests/test_settings_action_method_guard.py tests/demo/test_tab_actions.py
git commit -m "feat(institution): extend and revoke demo kits from the tab"
```

---

### Task 5: The credentials card — the read side (spec §4.4, §4.5; P4 read half, P6, P10 all kinds, P15, P17, P18, P19b, P20)

**Files:**
- Modify: `institution/views_manage.py`, `templates/institution/manage/_demo_tab.html`, `tests/demo/tab_helpers.py`
- Create: `tests/demo/test_tab_credentials.py`

**Interfaces:**
- Consumes: Task 3's context; `demo.warnings.DISPLAY`; `courses.models.ContentNode`.
- Produces (used by Task 6):
  - constants `DEMO_RESULTS_KEY = "demo_kit_results"`, `DEMO_RESULT_TTL = 15 * 60`;
  - `_session_store(request) -> SessionStore` (a separate store on the request's session key);
  - `_mirror_demo_results(request, saved: list | None) -> None`;
  - `_pending_demo_results(request) -> tuple[list[dict], list[dict]]` (cards, notices);
  - `_discard_shown_results(request, kit_ids: set[int]) -> list | None`;
  - the entry shape of spec §4.3 (keys `kit_id, label, teacher_username, teacher_password, student_username, student_password, expires_at, stored_at, warnings`);
  - test helpers `session_store(client)`, `stored_session(client)`, `write_stored_session(client, **items)`, `pending_entry(kit, *, age_seconds=0, warnings=None)`, `add_pending(client, *entries)`.

- [ ] **Step 1: Add the session helpers.** Append to `tests/demo/tab_helpers.py` (and add `import time` and `from importlib import import_module` at the top, and `from django.conf import settings as django_settings`):

```python
def session_store(client):
    """A SEPARATE store on the client's session row — the way another tab's
    request would see it."""
    engine = import_module(django_settings.SESSION_ENGINE)
    return engine.SessionStore(session_key=client.session.session_key)


def stored_session(client):
    """What the database holds right now for this client's session."""
    return dict(session_store(client).load())


def write_stored_session(client, **items):
    store = session_store(client)
    for key, value in items.items():
        store[key] = value
    store.save()


def pending_entry(kit, *, age_seconds=0, warnings=None):
    """A spec §4.3 entry for a REAL kit (an entry whose kit is missing or closed
    becomes a "closed before" notice, never a card). Distinctive fake passwords, so
    a substring check cannot collide with anything else on the page."""
    return {
        "kit_id": kit.pk,
        "label": kit.label,
        "teacher_username": f"teacher-of-{kit.pk}",
        "teacher_password": f"TeacherPw{kit.pk}x",
        "student_username": f"student-of-{kit.pk}",
        "student_password": f"StudentPw{kit.pk}x",
        "expires_at": kit.expires_at.isoformat(),
        "stored_at": time.time() - age_seconds,
        "warnings": warnings or {},
    }


def add_pending(client, *entries):
    store = session_store(client)
    store["demo_kit_results"] = [*store.get("demo_kit_results", []), *entries]
    store.save()
```

- [ ] **Step 2: Write the failing tests.** Create `tests/demo/test_tab_credentials.py`:

```python
import pytest
from django.utils import translation

from demo.services import revoke_kit
from demo.warnings import DISPLAY
from demo.warnings import KINDS
from institution import views_manage
from tests.demo.fixtures import small_course
from tests.demo.helpers import provision_for_test
from tests.demo.tab_helpers import add_pending
from tests.demo.tab_helpers import demo_tab_url
from tests.demo.tab_helpers import pending_entry
from tests.demo.tab_helpers import session_store
from tests.demo.tab_helpers import soup
from tests.demo.tab_helpers import stored_session
from tests.demo.tab_helpers import write_stored_session

KEY = "demo_kit_results"


def test_a_card_is_shown_once_with_no_store(pa_client, vendor):
    """P4, read half (Task 6 drives the real create)."""
    kit = provision_for_test(small_course())
    entry = pending_entry(kit)
    add_pending(pa_client, entry)

    first = pa_client.get(demo_tab_url())
    body = first.content.decode()
    assert entry["teacher_password"] in body and entry["student_password"] in body
    assert "no-store" in first["Cache-Control"]

    second = pa_client.get(demo_tab_url()).content.decode()
    assert entry["teacher_password"] not in second
    assert KEY not in stored_session(pa_client)


def test_an_entry_past_the_ttl_becomes_a_notice(pa_client, vendor):
    """P6."""
    kit = provision_for_test(small_course())
    add_pending(pa_client, pending_entry(kit, age_seconds=16 * 60))

    body = pa_client.get(demo_tab_url()).content.decode()

    assert f"TeacherPw{kit.pk}x" not in body
    assert f"Credentials for kit #{kit.pk} were never displayed" in body
    assert "was closed before its credentials were displayed" not in body
    assert KEY not in stored_session(pa_client)


def test_a_card_for_a_closed_kit_becomes_a_notice(pa_client, vendor):
    """P17."""
    kit = provision_for_test(small_course())
    add_pending(pa_client, pending_entry(kit))
    revoke_kit(kit)

    body = pa_client.get(demo_tab_url()).content.decode()

    assert f"Kit #{kit.pk} was closed before its credentials were displayed." in body
    assert f"TeacherPw{kit.pk}x" not in body


def test_only_a_real_get_takes_credentials(pa_client, vendor):
    """P15."""
    kit = provision_for_test(small_course())
    add_pending(pa_client, pending_entry(kit))

    pa_client.head(demo_tab_url())
    assert KEY in stored_session(pa_client)

    speculative = pa_client.get(demo_tab_url(), HTTP_SEC_PURPOSE="prefetch;prerender")
    speculative_body = speculative.content.decode()
    assert KEY in stored_session(pa_client)
    assert f"TeacherPw{kit.pk}x" not in speculative_body
    assert "Credentials are waiting — reload this page." in speculative_body

    assert f"TeacherPw{kit.pk}x" in pa_client.get(demo_tab_url()).content.decode()


def test_every_warning_kind_renders_inside_the_wrapper(pa_client, vendor):
    """P10, all-kinds half. Asserted on text inside data-demo-warnings — never "a
    200": a missing template key renders an empty string, not an error."""
    kit = provision_for_test(small_course())
    summary = {kind: {"count": 1, "unit_ids": [], "detail": None} for kind in KINDS}
    add_pending(pa_client, pending_entry(kit, warnings=summary))

    wrapper = soup(pa_client.get(demo_tab_url())).select_one("[data-demo-warnings]")
    text = wrapper.get_text(" ")

    with translation.override("en"):
        for kind in KINDS:
            assert str(DISPLAY[kind]) in text, kind
        assert text.count(str(DISPLAY["active_webhook_endpoint"])) == 1


def test_taking_credentials_writes_nothing_else(pa_client, vendor, monkeypatch):
    """P18. Another tab saves mid-render — an unrelated key, and a kit that
    finished meanwhile. The discard must remove only what this page showed."""
    course = small_course()
    shown = provision_for_test(course, label="Shown")
    late = provision_for_test(course, label="Late")
    add_pending(pa_client, pending_entry(shown))

    original = views_manage._settings_context

    def another_tab_saves(*args, **kwargs):
        store = session_store(pa_client)
        store["element_clip"] = "mid-render"
        store[KEY] = [*store.get(KEY, []), pending_entry(late)]
        store.save()
        return original(*args, **kwargs)

    monkeypatch.setattr(views_manage, "_settings_context", another_tab_saves)

    body = pa_client.get(demo_tab_url()).content.decode()

    assert f"TeacherPw{shown.pk}x" in body
    stored = stored_session(pa_client)
    assert [entry["kit_id"] for entry in stored[KEY]] == [late.pk]
    assert stored["element_clip"] == "mid-render"


def test_a_middleware_modified_session_does_not_resurrect_a_shown_entry(
    pa_client, vendor
):
    """P19(b). A stored language outside enabled_languages (default ["en", "pl"])
    makes LanguageSeederMiddleware modify request.session on this request."""
    kit = provision_for_test(small_course())
    add_pending(pa_client, pending_entry(kit))
    write_stored_session(pa_client, _language="de")

    assert f"TeacherPw{kit.pk}x" in pa_client.get(demo_tab_url()).content.decode()

    assert KEY not in stored_session(pa_client)
    write_stored_session(pa_client, _language="de")
    assert f"TeacherPw{kit.pk}x" not in pa_client.get(demo_tab_url()).content.decode()


def test_a_render_failure_keeps_the_credentials(pa_client, vendor, monkeypatch):
    """P20."""
    kit = provision_for_test(small_course())
    add_pending(pa_client, pending_entry(kit))

    def broken(*args, **kwargs):
        raise RuntimeError("render failed")

    monkeypatch.setattr(views_manage, "_settings_context", broken)
    with pytest.raises(RuntimeError):
        pa_client.get(demo_tab_url())

    assert KEY in stored_session(pa_client)
    monkeypatch.undo()
    assert f"TeacherPw{kit.pk}x" in pa_client.get(demo_tab_url()).content.decode()
```

- [ ] **Step 3: Run to see them fail.**

Run: `uv run pytest tests/demo/test_tab_credentials.py`
Expected: FAIL — no card, no notice, no warnings wrapper.

- [ ] **Step 4: Implement the helpers.** In `institution/views_manage.py` add imports:

```python
import time
from datetime import datetime
from importlib import import_module

from django.contrib.sessions.backends.base import UpdateError
from django.utils.cache import add_never_cache_headers
from django.views.decorators.debug import sensitive_variables

from courses.models import ContentNode
from demo.warnings import DISPLAY as DEMO_WARNING_DISPLAY
```

Add below `_demo_context`:

```python
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
```

Replace the `settings` view, adding `@sensitive_variables()` as its outermost decorator (the context carries the cards' passwords):

```python
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
```

- [ ] **Step 5: Implement the card.** In `_demo_tab.html`, replace `{# demo:results #}` with:

```django
{% if demo_waiting %}
<div class="alert alert--info" data-demo-waiting>{% trans "Credentials are waiting — reload this page." %}</div>
{% endif %}
{% for notice in demo_notices %}
<div class="alert alert--warning" data-demo-notice="{{ notice.kit_id }}">
  {% if notice.kind == "closed" %}
  {% blocktrans with id=notice.kit_id %}Kit #{{ id }} was closed before its credentials were displayed.{% endblocktrans %}
  {% else %}
  {% blocktrans with id=notice.kit_id %}Credentials for kit #{{ id }} were never displayed and are gone; revoke it and create another.{% endblocktrans %}
  {% endif %}
</div>
{% endfor %}
{% for card in demo_results %}
<div class="settings__section" data-demo-card="{{ card.kit_id }}">
  <h2 class="settings__section-title">{% blocktrans with id=card.kit_id label=card.label %}Demo kit #{{ id }} — {{ label }}{% endblocktrans %}</h2>
  <div class="alert alert--warning">{% trans "These passwords are not stored — copy them now." %}</div>
  <div class="scroll-x" data-scroll-x><table class="settings__table">
    <tbody>
      <tr>
        <th>{% trans "Teacher login" %}</th>
        <td><code data-demo-teacher-username>{{ card.teacher_username }}</code></td>
        <td><code data-demo-teacher-password>{{ card.teacher_password }}</code></td>
      </tr>
      <tr>
        <th>{% trans "Pupil login" %}</th>
        <td><code data-demo-student-username>{{ card.student_username }}</code></td>
        <td><code data-demo-student-password>{{ card.student_password }}</code></td>
      </tr>
      <tr><th>{% trans "Log in at" %}</th><td colspan="2"><code>{{ demo_login_url }}</code></td></tr>
      <tr><th>{% trans "Expires" %}</th><td colspan="2">{{ card.expires_at|date }}</td></tr>
    </tbody>
  </table></div>
  {% if card.warning_lines %}
  <div data-demo-warnings>
    <h3 class="settings__label">{% trans "Warnings" %}</h3>
    <ul>
      {% for line in card.warning_lines %}
      <li>{{ line.text }} ({{ line.count }}){% if line.detail %} <code>{{ line.detail }}</code>{% endif %}{% if line.titles %} — {{ line.titles|join:", " }}{% endif %}</li>
      {% endfor %}
    </ul>
  </div>
  {% endif %}
</div>
{% endfor %}
```

- [ ] **Step 6: Run to see them pass.**

Run: `uv run pytest tests/demo/test_tab_credentials.py tests/demo/test_tab_list.py tests/demo/test_tab_actions.py`
Expected: all passed.

- [ ] **Step 7: Falsify — one at a time, by hand, restoring after each.**
  1. In the `settings` view, delete `and request.method == "GET"` → `test_only_a_real_get_takes_credentials` FAILS (HEAD takes the entry).
  2. In `settings`, replace the speculative branch's body `waiting = bool(request.session.get(DEMO_RESULTS_KEY))` with `cards, notices = _pending_demo_results(request)` → `test_only_a_real_get_takes_credentials` FAILS at `assert KEY in stored_session(pa_client)` after the speculative GET (the discard ran).
  3. In `_pending_demo_results`, delete the `elif now - entry["stored_at"] > DEMO_RESULT_TTL:` branch (two lines) → `test_an_entry_past_the_ttl_becomes_a_notice` FAILS.
  4. In `_pending_demo_results`, replace `if entry["kit_id"] not in open_ids:` with `if False:` → `test_a_card_for_a_closed_kit_becomes_a_notice` FAILS.
  5. In `_discard_shown_results`, replace the body after the guard with `request.session.pop(DEMO_RESULTS_KEY, None); return []` → `test_taking_credentials_writes_nothing_else` FAILS (`element_clip` and `late` lost).
  6. In `_discard_shown_results`, replace `remaining = [...]` with `remaining = []` → P18 FAILS (the late entry lost).
  7. Make `_mirror_demo_results` `return` immediately → `test_a_middleware_modified_session_does_not_resurrect_a_shown_entry` FAILS.
  8. Move the discard into `_pending_demo_results` (call `_discard_shown_results(request, {e["kit_id"] for e in entries})` before `return cards, notices`) → `test_a_render_failure_keeps_the_credentials` FAILS.
  9. In `_attach_warning_lines`, change `order = [webhook, *(...)]` to `order = [webhook, *DEMO_WARNING_DISPLAY]` → `test_every_warning_kind_renders_inside_the_wrapper` FAILS on the count.
  10. In `settings`, delete the line `_mirror_demo_results(request, _discard_shown_results(request, shown))` → `test_a_card_is_shown_once_with_no_store` FAILS (the second GET still shows the password).
  11. In `settings`'s speculative branch, replace `waiting = bool(request.session.get(DEMO_RESULTS_KEY))` with `waiting = False` → `test_only_a_real_get_takes_credentials` FAILS on the waiting notice.
  12. In `_attach_warning_lines`, replace `*(kind for kind in DEMO_WARNING_DISPLAY if kind != webhook)` with a hand-written tuple of every kind except `"no_gradeable_question"` → `test_every_warning_kind_renders_inside_the_wrapper` FAILS.

- [ ] **Step 8: Commit.**

```bash
git add institution/views_manage.py templates/institution/manage/_demo_tab.html tests/demo/tab_helpers.py tests/demo/test_tab_credentials.py
git commit -m "feat(institution): show one-time demo credentials on the Demo tab"
```

---

### Task 6: The create form — the write side (spec §4.2, §4.3; P3 create, P4, P5, P7, P8, P9, P10 provision, P11 error page, P14, P16, P19a)

**Files:**
- Modify: `institution/forms.py`, `institution/views_manage.py`, `institution/urls.py`, `templates/institution/manage/_demo_tab.html`, `tests/demo/tab_helpers.py`, `tests/test_settings_action_method_guard.py`
- Create: `tests/demo/test_tab_create.py`

**Interfaces:**
- Consumes: `demo.services.provision_kit(label, *, course, days, pupils, frontier_part=None, seed=None, created_by=None) -> ProvisionResult(kit, teacher_password, student_password, warnings)`; `DemoWarning(kind, unit_id, reason)`; the `demo.errors` hierarchy; Task 5's `_session_store`, `_mirror_demo_results`, `DEMO_RESULTS_KEY`.
- Produces: `institution.forms.DemoKitForm` (fields `course`, `label`, `days`, `pupils`); URL `institution:settings_demo_create`; `_demo_result_entry(result) -> dict`; `_store_demo_result(request, entry) -> list | None`; `_attach_demo_error(form, exc)`; test helpers `create_url()`, `create_data(course, **overrides)`, `seed_the_view(monkeypatch, *, seed=4242, before_return=None)`.

- [ ] **Step 1: Add the create helpers.** Append to `tests/demo/tab_helpers.py` (add `from demo.constants import DEFAULT_DAYS` and `from demo.constants import MIN_PUPILS` at the top):

```python
def create_url():
    return reverse("institution:settings_demo_create")


def create_data(course, **overrides):
    """Tab-driven creates post MIN_PUPILS: the form's initial is DEFAULT_PUPILS
    (20), and each extra pupil costs ~137 queries."""
    data = {
        "course": course.pk,
        "label": "SP 12",
        "days": DEFAULT_DAYS,
        "pupils": MIN_PUPILS,
    }
    data.update(overrides)
    return data


def seed_the_view(monkeypatch, *, seed=4242, before_return=None):
    """The view passes no seed, so the service would draw one from `secrets`.
    Wrap the name the view resolves; `before_return(result)` runs after the real
    provision, standing in for whatever else happens while a kit is being built."""
    from institution import views_manage

    real = views_manage.provision_kit

    def seeded(*args, **kwargs):
        result = real(*args, seed=seed, **kwargs)
        if before_return is not None:
            before_return(result)
        return result

    monkeypatch.setattr(views_manage, "provision_kit", seeded)
```

- [ ] **Step 2: Write the failing tests.** Create `tests/demo/test_tab_create.py`:

```python
from django.conf import settings as django_settings
from django.contrib.auth import authenticate
from django.contrib.sessions.models import Session
from django.utils import translation

from courses.models import ContentNode
from courses.models import Course
from demo import errors
from demo.constants import MAX_PUPILS
from demo.constants import MIN_PUPILS
from demo.models import DemoKit
from demo.warnings import DISPLAY
from institution import views_manage
from integrations.models import WebhookEndpoint
from tests.demo.fixtures import small_course
from tests.demo.helpers import provision_for_test
from tests.demo.tab_helpers import add_pending
from tests.demo.tab_helpers import create_data
from tests.demo.tab_helpers import create_url
from tests.demo.tab_helpers import demo_tab_url
from tests.demo.tab_helpers import pending_entry
from tests.demo.tab_helpers import row_ids
from tests.demo.tab_helpers import seed_the_view
from tests.demo.tab_helpers import session_store
from tests.demo.tab_helpers import soup
from tests.demo.tab_helpers import stored_session
from tests.demo.tab_helpers import write_stored_session
from tests.factories import make_teacher

KEY = "demo_kit_results"


def test_create_404s_on_a_school_box(pa_client):
    """P3, create half."""
    assert pa_client.post(create_url(), create_data(small_course())).status_code == 404
    assert not DemoKit.objects.exists()


def test_create_needs_change_institution(client, vendor):
    make_teacher(client)
    assert client.post(create_url(), create_data(small_course())).status_code == 403


def test_a_create_redirects_and_shows_the_credentials_once(
    pa_client, vendor, monkeypatch
):
    """P4."""
    course = small_course()
    seed_the_view(monkeypatch)

    response = pa_client.post(create_url(), create_data(course))

    assert response.status_code == 302
    assert response["Location"] == demo_tab_url()
    kit = DemoKit.objects.get()
    assert kit.created_by.username == "pa"
    entry = stored_session(pa_client)[KEY][0]

    first = pa_client.get(demo_tab_url())
    # Asserted INSIDE the card: the kit list prints the teacher username too.
    card = soup(first).select_one(f'[data-demo-card="{kit.pk}"]')
    assert card is not None
    card_text = card.get_text(" ")
    for shown in (
        kit.teacher.username,
        kit.student.username,
        entry["teacher_password"],
        entry["student_password"],
    ):
        assert shown in card_text
    assert "no-store" in first["Cache-Control"]
    teacher = authenticate(
        username=kit.teacher.username, password=entry["teacher_password"]
    )
    student = authenticate(
        username=kit.student.username, password=entry["student_password"]
    )
    assert teacher is not None and student is not None

    second_response = pa_client.get(demo_tab_url())
    second = second_response.content.decode()
    assert entry["teacher_password"] not in second
    assert entry["student_password"] not in second
    assert kit.pk in row_ids(second_response)  # the list still shows the kit
    assert KEY not in stored_session(pa_client)


def test_credentials_wait_while_another_tab_is_open(pa_client, vendor, monkeypatch):
    """P5: a dropped connection self-heals on the next Demo-tab GET."""
    seed_the_view(monkeypatch)
    pa_client.post(create_url(), create_data(small_course()))
    password = stored_session(pa_client)[KEY][0]["teacher_password"]

    branding = pa_client.get(demo_tab_url().replace("tab=demo", "tab=branding"))
    assert password not in branding.content.decode()
    assert KEY in stored_session(pa_client)

    assert password in pa_client.get(demo_tab_url()).content.decode()


def test_two_creates_before_any_get_both_show(pa_client, vendor, monkeypatch):
    """P7."""
    course = small_course()
    seed_the_view(monkeypatch)
    pa_client.post(create_url(), create_data(course, label="First school"))
    pa_client.post(create_url(), create_data(course, label="Second school"))

    entries = stored_session(pa_client)[KEY]
    assert len(entries) == 2
    body = pa_client.get(demo_tab_url()).content.decode()
    for entry in entries:
        assert entry["teacher_password"] in body


def test_the_form_holds_no_bounds_of_its_own(pa_client, vendor, monkeypatch):
    """P8. Field errors come from the SERVICE; the form holds no bound."""
    course = small_course()
    seed_the_view(monkeypatch)

    too_few = pa_client.post(create_url(), create_data(course, pupils=4))
    pupil_errors = " ".join(too_few.context["demo_form"].errors["pupils"])
    assert str(MIN_PUPILS) in pupil_errors and str(MAX_PUPILS) in pupil_errors
    assert not DemoKit.objects.exists()

    blank = pa_client.post(create_url(), create_data(course, label="   "))
    assert "label" in blank.context["demo_form"].errors

    empty = Course.objects.create(slug="empty", title="Empty", language="pl")
    no_units = pa_client.post(create_url(), create_data(empty))
    assert "This course cannot hold a demo." in str(
        no_units.context["demo_form"].non_field_errors()
    )

    # The bound moves with the service's constant, so the form cannot hold one.
    monkeypatch.setattr("demo.services.MIN_PUPILS", 3)
    pa_client.post(create_url(), create_data(course, pupils=4))
    assert DemoKit.objects.filter(pupil_count=4).exists()


def test_a_service_message_is_escaped(pa_client, vendor, monkeypatch):
    """P8, escaping half."""

    def raises(*args, **kwargs):
        raise errors.EmptyCourse("<b>bold</b>")

    monkeypatch.setattr(views_manage, "provision_kit", raises)

    response = pa_client.post(create_url(), create_data(small_course()))

    html = str(response.context["demo_form"].non_field_errors())
    assert "<code>&lt;b&gt;bold&lt;/b&gt;</code>" in html
    assert "<b>bold</b>" not in html


def test_a_failed_create_leaves_pending_credentials_alone(
    pa_client, vendor, monkeypatch
):
    """P9. X's kit already holds the sp-12-* logins, and a blind scan turns the
    second "SP 12" create into the double-submit's UsernameCollision."""
    course = small_course()
    kit_x = provision_for_test(course, label="SP 12")
    add_pending(pa_client, pending_entry(kit_x))
    seed_the_view(monkeypatch)
    monkeypatch.setattr("demo.services._taken", lambda names: False)

    response = pa_client.post(create_url(), create_data(course, label="SP 12"))

    assert response.status_code == 200
    errors_html = str(response.context["demo_form"].non_field_errors())
    # The link is asserted INSIDE the errors: the tab nav carries ?tab=demo too.
    assert f'href="{demo_tab_url()}"' in errors_html
    assert "retry" not in errors_html.lower()
    assert [entry["kit_id"] for entry in stored_session(pa_client)[KEY]] == [kit_x.pk]
    assert f"TeacherPw{kit_x.pk}x" in pa_client.get(demo_tab_url()).content.decode()


def test_warnings_from_a_real_provision(pa_client, vendor, monkeypatch):
    """P10, provision half."""
    endpoint = WebhookEndpoint.load()
    endpoint.enabled = True
    endpoint.url = "https://sis.example.edu/libli-hook"
    endpoint.secret = "not-a-real-signing-key"  # noqa: S105
    endpoint.save()
    course = small_course(quiz_with_review_question=True)
    reviewed = ContentNode.objects.get(course=course, title="Reviewed quiz")
    seed_the_view(monkeypatch)

    response = pa_client.post(create_url(), create_data(course))
    # No other test provisions this fixture variant. A 200 here means the kit
    # rolled back (EmptyKit) and the form re-rendered — see Step 7's seed note —
    # rather than a confusing KeyError on the session below.
    assert response.status_code == 302

    summary = stored_session(pa_client)[KEY][0]["warnings"]
    assert reviewed.pk in summary["quiz_skipped"]["unit_ids"]
    assert summary["active_webhook_endpoint"]["detail"] == endpoint.url
    assert summary["quiz_skipped"]["detail"] is None

    wrapper = soup(pa_client.get(demo_tab_url())).select_one("[data-demo-warnings]")
    text = wrapper.get_text(" ")
    with translation.override("en"):
        skipped = str(DISPLAY["quiz_skipped"])
        webhook = str(DISPLAY["active_webhook_endpoint"])
    assert text.index(endpoint.url) < text.index(skipped)
    assert text.count(webhook) == 1
    assert "Reviewed quiz" in text
    assert "a REVIEW question cannot be answered" not in text
    assert "has no builder" not in text


def test_the_show_all_link_works_from_a_create_error_page(pa_client, vendor):
    """P11. The panel renders at .../demo/create/ too, so a relative href would
    lose all=1 through the create view's non-POST redirect."""
    response = pa_client.post(create_url(), create_data(small_course(), label=""))

    href = soup(response).select_one("a[data-demo-show-all]")["href"]
    assert href == demo_tab_url(show_all=True)
    followed = pa_client.get(href)
    assert followed.status_code == 200
    assert followed.context["demo_show_all"] is True


def test_the_write_goes_through_a_fresh_store(pa_client, vendor, monkeypatch):
    """P14. Other tabs save while the kit is being built."""
    course = small_course()
    other = provision_for_test(course, label="Other school")

    def other_tabs_save(result):
        store = session_store(pa_client)
        store["element_clip"] = "mid-provision"
        store[KEY] = [*store.get(KEY, []), pending_entry(other)]
        store.save()

    seed_the_view(monkeypatch, before_return=other_tabs_save)

    pa_client.post(create_url(), create_data(course))

    new_kit = DemoKit.objects.exclude(pk=other.pk).get()
    stored = stored_session(pa_client)
    assert [entry["kit_id"] for entry in stored[KEY]] == [other.pk, new_kit.pk]
    assert stored["element_clip"] == "mid-provision"


def test_an_ended_session_is_not_resurrected(pa_client, vendor, monkeypatch):
    """P16(a). A logout in another tab while the kit is being built."""
    key = pa_client.session.session_key
    seed_the_view(
        monkeypatch,
        before_return=lambda result: Session.objects.filter(session_key=key).delete(),
    )

    response = pa_client.post(create_url(), create_data(small_course()))

    assert response.status_code == 302
    assert response["Location"] == demo_tab_url()
    assert django_settings.SESSION_COOKIE_NAME not in response.cookies
    assert Session.objects.count() == 0
    assert DemoKit.objects.exists()


def test_a_row_deleted_after_the_read_leaves_no_orphan(pa_client, vendor, monkeypatch):
    """P16(b). The row vanishes right after the fresh store's first database read.
    The patch is started with monkeypatch INSIDE the wrapper and stays active for
    the rest of the request; a `with mock.patch` block would end when the wrapper
    returns, before the view's store reads."""
    from django.contrib.sessions.backends.db import SessionStore as DbSessionStore

    original = DbSessionStore._get_session_from_db
    fired = []

    def delete_after_first_read(store):
        found = original(store)
        if found is not None and not fired:
            fired.append(True)
            Session.objects.filter(session_key=store.session_key).delete()
        return found

    seed_the_view(
        monkeypatch,
        before_return=lambda result: monkeypatch.setattr(
            DbSessionStore, "_get_session_from_db", delete_after_first_read
        ),
    )

    response = pa_client.post(create_url(), create_data(small_course()))

    assert fired
    assert response.status_code == 302
    assert django_settings.SESSION_COOKIE_NAME not in response.cookies
    assert Session.objects.count() == 0


def test_a_middleware_modified_session_does_not_undo_the_write(
    pa_client, vendor, monkeypatch
):
    """P19(a)."""
    seed_the_view(monkeypatch)
    write_stored_session(pa_client, _language="de")

    pa_client.post(create_url(), create_data(small_course()))

    assert [entry["kit_id"] for entry in stored_session(pa_client)[KEY]] == [
        DemoKit.objects.get().pk
    ]
```

- [ ] **Step 3: Run to see them fail.**

Run: `uv run pytest tests/demo/test_tab_create.py`
Expected: FAIL — `NoReverseMatch: 'settings_demo_create'`, or `AttributeError: … has no attribute 'provision_kit'` for the tests that patch `views_manage.provision_kit` (it is imported there only in Step 5).

- [ ] **Step 4: Implement the form.** In `institution/forms.py`, add `from courses.models import Course`, `from demo.constants import DEFAULT_DAYS` and `from demo.constants import DEFAULT_PUPILS` to the imports, and append:

```python
class DemoKitForm(forms.Form):
    """PR 3 spec §4.2. ⚠️ NO max_length / min_value / max_value: every bound lives
    in demo.services.provision_kit, and this form inherits them by calling it. A
    bound copied here would drift from the service's — P8 proves there is none.
    Requiredness and integer coercion are type-level and stay."""

    # No initial course: the parent spec forbids a default, so the operator picks.
    course = forms.ModelChoiceField(
        queryset=Course.objects.order_by("title"), label=_("Course")
    )
    label = forms.CharField(label=_("Label"))
    days = forms.IntegerField(label=_("Days"), initial=DEFAULT_DAYS)
    pupils = forms.IntegerField(label=_("Pupils"), initial=DEFAULT_PUPILS)
```

(If importing `courses.models` here raises a circular import at startup, move the import inside a `def __init__` that sets `self.fields["course"].queryset = Course.objects.order_by("title")`, with the class-level field built on `Course.objects.none()`.)

- [ ] **Step 5: Implement the view.** In `institution/views_manage.py` add imports:

```python
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext
from django.views.decorators.debug import sensitive_post_parameters

from demo.constants import LABEL_MAX
from demo.constants import MAX_DAYS
from demo.constants import MAX_PUPILS
from demo.constants import MIN_DAYS
from demo.constants import MIN_PUPILS
from demo.services import provision_kit
from institution.forms import DemoKitForm
```

In `_demo_context`, change `"demo_form": form,` (the Demo-tab return) to `"demo_form": form or DemoKitForm(),`.

Append:

```python
# Spec §4.2: display only — the bounds are enforced by provision_kit.
_DEMO_BOUNDS = {"pupils": (MIN_PUPILS, MAX_PUPILS), "days": (MIN_DAYS, MAX_DAYS)}
DEMO_WARNING_SAMPLE = 3  # unit ids kept per warning kind (spec §4.3)


def _demo_error_sentence(exc):
    """The translated lead sentence for a DemoKitError with no form field."""
    if isinstance(exc, demo_errors.UsernameCollision):
        # ONE msgid for the whole sentence, so Polish word order is free; the URL
        # enters only as an escaped argument, never inside the translated text.
        # Not "try again": from the tab this is a double submit whose other request
        # has just committed a live kit, and this page shows no card.
        return format_html(
            gettext(
                "A kit for this label may have just been created. "
                "{link_start}Open the Demo tab{link_end} — its credentials appear "
                "there — before creating again."
            ),
            link_start=format_html('<a href="{}">', _index_url("demo")),
            link_end=mark_safe("</a>"),
        )
    if isinstance(exc, demo_errors.EmptyCourse):
        return _("This course cannot hold a demo.")
    if isinstance(exc, demo_errors.EmptyKit):
        return _("The generated class came out empty and was rolled back.")
    if isinstance(exc, demo_errors.NamePoolExhausted):
        return _("Ran out of distinct pupil names; use fewer pupils.")
    return _("The demo kit could not be created.")


def _attach_demo_error(form, exc):
    """Spec §4.2's table. The service's own messages are English; a non-field error
    is a translated sentence plus that text ESCAPED inside <code> — built with
    format_html, never mark_safe over an f-string."""
    if isinstance(exc, demo_errors.InvalidLabel):
        form.add_error(
            "label",
            _("Enter a label of at most %(max)s characters.") % {"max": LABEL_MAX},
        )
    elif isinstance(exc, demo_errors.InvalidBounds) and exc.field in _DEMO_BOUNDS:
        low, high = _DEMO_BOUNDS[exc.field]
        form.add_error(
            exc.field,
            _("Must be between %(min)s and %(max)s.") % {"min": low, "max": high},
        )
    else:
        form.add_error(
            None, format_html("{} <code>{}</code>", _demo_error_sentence(exc), str(exc))
        )


@sensitive_variables()
def _demo_result_entry(result):
    """Spec §4.3's entry. `warnings` is a per-kind SUMMARY: a mat-pp provision emits
    warnings per question and per variant, and none of their English `reason`s is
    displayed — except the webhook's, which is its endpoint URL."""
    kit = result.kit
    summary = {}
    for warning in result.warnings:
        item = summary.setdefault(
            warning.kind, {"count": 0, "unit_ids": [], "detail": None}
        )
        item["count"] += 1
        if (
            warning.unit_id is not None
            and warning.unit_id not in item["unit_ids"]
            and len(item["unit_ids"]) < DEMO_WARNING_SAMPLE
        ):
            item["unit_ids"].append(warning.unit_id)
        if warning.kind == "active_webhook_endpoint":
            item["detail"] = warning.reason
    return {
        "kit_id": kit.pk,
        "label": kit.label,
        "teacher_username": kit.teacher.username,
        "teacher_password": result.teacher_password,
        "student_username": kit.student.username,
        "student_password": result.student_password,
        "expires_at": kit.expires_at.isoformat(),
        "stored_at": time.time(),
        "warnings": summary,
    }


@sensitive_variables()
def _store_demo_result(request, entry):
    """Spec §4.3 steps 1-3. Returns the saved list, or None when nothing was saved
    (then nothing may be mirrored — mirroring [*existing, entry] would put both
    passwords into request.session for a save that fails anyway)."""
    fresh = _session_store(request)
    existing = fresh.get(DEMO_RESULTS_KEY, [])  # the cached read — never .load()
    if fresh.session_key is None:
        # The row is gone (a logout in another tab, an expiry). Without this guard
        # fresh.save() would create() an orphan row holding both passwords.
        return None
    saved = [*existing, entry]
    fresh[DEMO_RESULTS_KEY] = saved
    try:
        fresh.save()  # explicit: the backend writes the whole store on save()
    except UpdateError:
        return None  # the row vanished between the read and the save
    return saved


@sensitive_variables()
@sensitive_post_parameters()
@login_required
@permission_required("institution.change_institution", raise_exception=True)
def settings_demo_create(request):
    if not django_settings.VENDOR_INSTANCE:  # aliased -- `settings` is a VIEW here
        raise Http404
    if request.method != "POST":
        return redirect(_index_url("demo"))  # non-POST: see _action
    form = DemoKitForm(request.POST)
    if form.is_valid():
        data = form.cleaned_data
        try:
            # Inline, by design (spec A3): ~40 s for 20 pupils, well inside
            # gunicorn's --timeout 1800. No frontier_part, no seed.
            result = provision_kit(
                data["label"],
                course=data["course"],
                days=data["days"],
                pupils=data["pupils"],
                created_by=request.user,
            )
        except demo_errors.DemoKitError as exc:
            _attach_demo_error(form, exc)
        else:
            saved = _store_demo_result(request, _demo_result_entry(result))
            response = redirect(_index_url("demo"))
            _mirror_demo_results(request, saved)
            return response
    # Spec §4.4: this error page neither takes nor writes pending credentials — it
    # answers a POST, so a reload re-submits. Always the default (open-only) list.
    ctx = _settings_context(request, Institution.load(), "demo", demo_form=form)
    return render(request, "institution/manage/settings.html", ctx)
```

In `institution/urls.py`, before the extend path:

```python
    path(
        "manage/settings/demo/create/",
        views_manage.settings_demo_create,
        name="settings_demo_create",
    ),
```

In `tests/test_settings_action_method_guard.py`, add `("institution:settings_demo_create", {}),` above the extend entry in `ACTION_URLS`.

- [ ] **Step 6: Implement the form markup.** In `_demo_tab.html`, replace `{# demo:create-form #}` with:

```django
<form class="settings__form" method="post" action="{% url 'institution:settings_demo_create' %}" data-demo-create>
  {% csrf_token %}
  <div class="settings__section">
    <h2 class="settings__section-title">{% trans "Create demo kit" %}</h2>
    {% if demo_form.non_field_errors %}
    <div class="alert alert--error" data-demo-form-errors>
      {% for error in demo_form.non_field_errors %}<p>{{ error }}</p>{% endfor %}
    </div>
    {% endif %}
    {% for field in demo_form %}
    <div class="settings__field">
      <label class="settings__label" for="{{ field.id_for_label }}">{{ field.label }}</label>
      {{ field }}
      {{ field.errors }}
    </div>
    {% endfor %}
    <p class="settings__help">{% trans "Creating a kit can take a minute or more; keep this page open. If the page stops responding, wait a couple of minutes, then reopen the Demo tab — the credentials appear there once the kit exists. Do not create again until it shows in the list." %}</p>
    <div class="settings__actions">
      {# No `name`: the submit handler disables this button, and a named disabled button drops its pair from the POST. #}
      <button class="btn" type="submit" data-demo-submit>{% trans "Create demo kit" %}</button>
    </div>
  </div>
</form>
```

- [ ] **Step 7: Run to see them pass.**

Run: `uv run pytest tests/demo/test_tab_create.py tests/demo/test_tab_credentials.py tests/demo/test_tab_list.py tests/demo/test_tab_actions.py tests/test_settings_action_method_guard.py`
Expected: all passed. ⚠️ If `test_the_form_holds_no_bounds_of_its_own`'s last assertion fails because the four-pupil kit rolled back with `EmptyKit` under seed 4242 (the band partition is thinnest there) — or `test_warnings_from_a_real_provision`'s 302 assertion fails the same way (no other test provisions its `quiz_with_review_question` fixture, and the extra unit moves the depth floor) — change that test's EXISTING `seed_the_view(monkeypatch)` call (the line after `course = small_course()`) to `seed_the_view(monkeypatch, seed=N)` for N = 1…10 until one provisions. **If none of the ten does, STOP and report back** — do not change `pupils=4`, the patched `MIN_PUPILS`, or the fixture to force it (a 2–4 pupil class is one band, `demo/constants.py:13-14`, and may fail for every seed). The likely replacement, for Krzysztof to approve, proves the same no-bounds claim away from the band partition: patch `demo.services.MIN_DAYS` to 0 and post `days=0` with `pupils=MIN_PUPILS`. ⚠️ never ADD a second `seed_the_view` call: it would wrap the already-seeded wrapper and pass `seed` twice, a `TypeError` that reads like a new failure — keep that seed with a comment saying why, and move on — the assertion's point is that the form let the value through.

- [ ] **Step 8: Falsify — one at a time, by hand, restoring after each.**
  1. Delete the vendor check from `settings_demo_create` → `test_create_404s_on_a_school_box` FAILS (`ImproperlyConfigured` raised).
  2. Add `min_value=5` to `DemoKitForm.pupils` → `test_the_form_holds_no_bounds_of_its_own` FAILS.
  3. In `_attach_demo_error`, replace the `format_html("{} <code>{}</code>", ...)` call with `mark_safe(f"{_demo_error_sentence(exc)} <code>{exc}</code>")` → `test_a_service_message_is_escaped` FAILS.
  4. In `_demo_error_sentence`, replace the collision `format_html(...)` with `_("A kit for this label may have just been created.")` → `test_a_failed_create_leaves_pending_credentials_alone` FAILS on the link.
  5. In the create view's error path, before `ctx = ...`, add `request.session.pop(DEMO_RESULTS_KEY, None)` → P9 FAILS.
  6. In `_store_demo_result`, delete `fresh.save()` → `test_two_creates_before_any_get_both_show` FAILS.
  7. In `_store_demo_result`, replace `existing = fresh.get(DEMO_RESULTS_KEY, [])` with `existing = request.session.get(DEMO_RESULTS_KEY, [])` → `test_the_write_goes_through_a_fresh_store` FAILS (Y lost).
  8. Replace the body of `_store_demo_result` after `saved = [...]` with `request.session[DEMO_RESULTS_KEY] = saved; return saved` → P14 FAILS (`element_clip` overwritten) **and** `test_a_row_deleted_after_the_read_leaves_no_orphan` FAILS (the middleware's save force-updates the deleted row: a 400 `SessionInterrupted`, not the 302).
  9. Delete the `if fresh.session_key is None: return None` guard → `test_an_ended_session_is_not_resurrected` FAILS (an orphan row).
  10. Replace `existing = fresh.get(DEMO_RESULTS_KEY, [])` with `existing = fresh.load().get(DEMO_RESULTS_KEY, [])` → `test_a_row_deleted_after_the_read_leaves_no_orphan` FAILS (an orphan row).
  11. Remove the `try:`/`except UpdateError:` around `fresh.save()` → P16(b) FAILS (`UpdateError` raised in the test).
  12. Make `_mirror_demo_results` `return` immediately → `test_a_middleware_modified_session_does_not_undo_the_write` FAILS.
  13. In `_demo_tab.html`, change the show-all link to `href="?tab=demo&amp;all=1"` → `test_the_show_all_link_works_from_a_create_error_page` FAILS.
  14. In `_demo_result_entry`, drop the `if warning.kind == "active_webhook_endpoint":` branch → `test_warnings_from_a_real_provision` FAILS.
  15. In `settings_demo_create`'s success branch, replace `response = redirect(_index_url("demo"))` with `response = render(request, "institution/manage/settings.html", _settings_context(request, Institution.load(), "demo"))` → `test_a_create_redirects_and_shows_the_credentials_once` FAILS on the 302.
  16. In `settings`, delete `active_tab == "demo" and ` from the take condition → `test_credentials_wait_while_another_tab_is_open` FAILS (the branding GET took and discarded the entry without rendering it).
  17. In `_attach_warning_lines`, move the webhook last: `order = [*(kind for kind in DEMO_WARNING_DISPLAY if kind != webhook), webhook]` → `test_warnings_from_a_real_provision` FAILS on the index comparison.
  18. In `_demo_result_entry`, replace the `if warning.kind == "active_webhook_endpoint":` guard with an unconditional `item["detail"] = warning.reason` → `test_warnings_from_a_real_provision` FAILS (`quiz_skipped`'s detail is not None, and the REVIEW reason renders).
  19. In `_store_demo_result`, replace `saved = [*existing, entry]` with `saved = [entry]` → `test_two_creates_before_any_get_both_show` FAILS (one entry).

- [ ] **Step 9: Commit.**

```bash
git add institution/forms.py institution/views_manage.py institution/urls.py templates/institution/manage/_demo_tab.html tests/demo/tab_helpers.py tests/demo/test_tab_create.py tests/test_settings_action_method_guard.py
git commit -m "feat(institution): create demo kits from the tab"
```

---

### Task 7: `demo_tab.js` and the e2e (spec §4.2, §4.4, §4.7, §5 e2e)

**Files:**
- Create: `institution/static/institution/js/demo_tab.js`, `tests/test_e2e_demo_tab.py`
- Modify: `templates/institution/manage/_demo_tab.html`

**Interfaces:**
- Consumes: hooks `form[data-demo-create]`, `form[data-demo-extend]`, `form[data-demo-revoke]`, `[data-demo-card]`, `[data-demo-teacher-username]`, `[data-demo-teacher-password]`, `tr[data-demo-kit]`, `[data-demo-submit]` (Tasks 3–6).
- Produces: nothing later tasks read.

- [ ] **Step 1: Write the e2e** (it locks a flow that exists since Task 6, so it passes at once — Step 5 is what proves it can fail). Create `tests/test_e2e_demo_tab.py`:

```python
"""PR 3 spec §5: the one e2e — issue a kit through the tab, use its Teacher login,
revoke it through the confirm dialog. Marked e2e (run with -m e2e)."""

import os

import pytest
from django.urls import reverse
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e

REVOKE_PROMPT = "Revoke this demo kit? Its logins are deleted immediately."


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username, password):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(password)
    form.locator("button[type='submit']").click()
    page.wait_for_url(lambda url: "/accounts/login/" not in url)


@pytest.mark.django_db(transaction=True)
def test_issue_use_and_revoke_a_demo_kit(
    page, browser, live_server, settings, monkeypatch
):
    from django.contrib.auth.models import Group

    from demo.constants import MIN_PUPILS
    from demo.models import DemoKit
    from institution import views_manage
    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles
    from tests.demo.fixtures import small_course
    from tests.factories import TEST_PASSWORD
    from tests.factories import make_verified_user

    settings.VENDOR_INSTANCE = True
    seed_roles()
    admin = make_verified_user(
        username="demo_pa", email="demo_pa@t.example.com", password=TEST_PASSWORD
    )
    admin.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    course = small_course()
    real = views_manage.provision_kit
    monkeypatch.setattr(
        views_manage, "provision_kit", lambda *a, **kw: real(*a, seed=4242, **kw)
    )
    demo_tab = f"{live_server.url}{reverse('institution:settings')}?tab=demo"

    _login(page, live_server, "demo_pa", TEST_PASSWORD)
    page.goto(demo_tab)
    page.select_option("#id_course", str(course.pk))
    page.fill("#id_label", "SP 12")
    page.fill("#id_pupils", str(MIN_PUPILS))
    page.locator("[data-demo-submit]").click()

    card = page.locator("[data-demo-card]")
    expect(card).to_be_visible(timeout=120_000)
    username = card.locator("[data-demo-teacher-username]").inner_text()
    password = card.locator("[data-demo-teacher-password]").inner_text()
    kit = DemoKit.objects.get()

    teacher_context = browser.new_context()
    try:
        teacher_page = teacher_context.new_page()
        _login(teacher_page, live_server, username, password)
        analytics = reverse("courses:manage_analytics", kwargs={"slug": course.slug})
        landed = teacher_page.goto(f"{live_server.url}{analytics}")
        # goto returns the LAST response of a redirect chain, and a bounce to the
        # login page is a 200 too — so assert WHERE the page ended up as well.
        assert landed.status == 200
        assert teacher_page.url == f"{live_server.url}{analytics}"
    finally:
        teacher_context.close()

    prompts = []

    def accept(dialog):
        prompts.append(dialog.message)
        dialog.accept()

    page.on("dialog", accept)
    page.goto(demo_tab)
    row = page.locator(f'tr[data-demo-kit="{kit.pk}"]')
    row.locator("form[data-demo-revoke] button").click()
    expect(row).to_have_count(0)
    # Without the recording, a Revoke that never prompts still removes the row.
    assert prompts == [REVOKE_PROMPT]
```

- [ ] **Step 2: Run it.**

Run: `uv run pytest -m e2e tests/test_e2e_demo_tab.py`
Expected: PASS already (the flow exists since Task 6) — this e2e locks the flow, and Step 5 falsifies it. If it fails, fix the cause before writing the script.

- [ ] **Step 3: Write the script.** Create `institution/static/institution/js/demo_tab.js`:

```javascript
// PR 3 spec §4.2 / §4.4. Loaded with `defer` by _demo_tab.html.
(function () {
  "use strict";

  // Submit-once for Create (a ~40 s request) and for each row's Extend (two POSTs
  // would extend twice). The buttons carry no `name`, so disabling them inside the
  // handler drops nothing from the POST. Revoke is NOT disabled: its confirm
  // dialog already stops a double click, and a button disabled here would stay
  // dead after a cancelled confirm.
  function disableOnSubmit(selector) {
    document.querySelectorAll(selector).forEach(function (form) {
      form.addEventListener("submit", function (event) {
        if (event.defaultPrevented) return;
        var button = form.querySelector('button[type="submit"]');
        if (!button) return;
        button.disabled = true;
        button.setAttribute("aria-busy", "true");
        button.setAttribute("data-demo-disabled", "");
      });
    });
  }

  disableOnSubmit("form[data-demo-create]");
  disableOnSubmit("form[data-demo-extend]");

  window.addEventListener("pageshow", function (event) {
    // A Back navigation restored from bfcache must not leave dead buttons.
    document.querySelectorAll("[data-demo-disabled]").forEach(function (button) {
      button.disabled = false;
      button.removeAttribute("aria-busy");
      button.removeAttribute("data-demo-disabled");
    });
    // `no-store` only discourages bfcache (Chrome restores such pages when no
    // cookie changed), so a restored page drops its credential cards.
    if (event.persisted) {
      document.querySelectorAll("[data-demo-card]").forEach(function (card) {
        card.remove();
      });
    }
  });
})();
```

In `_demo_tab.html`, replace `{# demo:scripts #}` with:

```django
<script src="{% static 'institution/js/demo_tab.js' %}" defer></script>
```

- [ ] **Step 4: Run again.**

Run: `uv run pytest -m e2e tests/test_e2e_demo_tab.py` then `uv run pytest tests/demo/test_tab_list.py`
Expected: both pass.

- [ ] **Step 5: Falsify.** In `_demo_tab.html`, remove `defer` from the `confirm.js` tag and move that tag to directly after `{% if active_tab == "demo" %}` (above the list). Run the e2e → FAILS (`prompts == []`, no dialog). Restore by hand.

- [ ] **Step 6: Commit.**

```bash
git add institution/static/institution/js/demo_tab.js templates/institution/manage/_demo_tab.html tests/test_e2e_demo_tab.py
git commit -m "feat(institution): demo tab submit-once, bfcache clearing, and e2e"
```

---

### Task 8: Polish strings (spec §4.8)

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.mo`, `locale/en/LC_MESSAGES/django.po`, `locale/en/LC_MESSAGES/django.mo`

**Interfaces:** none.

- [ ] **Step 1: Extract.**

Run: `uv run python manage.py makemessages -l pl -l en --no-obsolete`
(`--no-obsolete` is the repo's standard — `docs/development/conventions.md` — because `tests/test_i18n_po_health.py` fails on any `#~` entry.)

- [ ] **Step 2: Fill the Polish catalog.** For every msgid below, open `locale/pl/LC_MESSAGES/django.po`, find it, and set the `msgstr`. **If the entry is marked `#, fuzzy`, delete all three of: the `#, fuzzy` line, any `#| msgid …` line, and the prefilled wrong `msgstr` — then write the one below** (makemessages guesses from near-miss msgids and has shipped "Revoked" → "Cofnij" before). If a msgid already existed with a non-empty, non-fuzzy translation (e.g. "Course", "Label", "Days", "Status", "Created", "Revoke"), keep it.

| msgid (msgctxt) | msgstr |
|---|---|
| Demo access | Dostęp demo |
| A demo kit is a Teacher login — class analytics, per-pupil progress and force-submitting an unfinished quiz — a pupil login that starts with a blank record, and an example class of generated pupils. It lasts the chosen number of days and is then deleted automatically. | Zestaw demo to login nauczyciela — analityka klasy, postępy poszczególnych uczniów i wymuszanie oddania niedokończonego quizu — login ucznia, który zaczyna z pustym kontem, oraz przykładowa klasa wygenerowanych uczniów. Działa przez wybraną liczbę dni, a potem jest automatycznie usuwany. |
| Demo kits | Zestawy demo |
| Show closed kits too | Pokaż także zamknięte zestawy |
| Show open kits only | Pokaż tylko otwarte zestawy |
| Label | Etykieta |
| Course | Kurs |
| Pupils | Uczniowie |
| Teacher login | Login nauczyciela |
| Pupil login | Login ucznia |
| Created | Utworzono |
| Expires | Wygasa |
| Status | Status |
| Actions | Akcje |
| No demo kits. | Brak zestawów demo. |
| Active (demo kit status) | Aktywne |
| Expired — pending purge (demo kit status) | Wygasłe — czeka na usunięcie |
| Closed (expired) (demo kit status) | Zamknięte (wygasłe) |
| Closed (revoked) (demo kit status) | Zamknięte (cofnięte) |
| Extend by %(days)d day / days | [0] Przedłuż o %(days)d dzień · [1] Przedłuż o %(days)d dni · [2] Przedłuż o %(days)d dni |
| Revoke this demo kit? Its logins are deleted immediately. | Cofnąć ten zestaw demo? Jego loginy zostaną natychmiast usunięte. |
| Kit #%(id)s is already closed. | Zestaw #%(id)s jest już zamknięty. |
| Kit #%(id)s now expires on %(date)s. | Zestaw #%(id)s wygasa teraz %(date)s. |
| After this extension the kit will have been open for more than %(days)d day. / days. | [0] Po tym przedłużeniu zestaw będzie działał dłużej niż %(days)d dzień. · [1] Po tym przedłużeniu zestaw będzie działał dłużej niż %(days)d dni. · [2] Po tym przedłużeniu zestaw będzie działał dłużej niż %(days)d dni. |
| Kit #%(id)s revoked; its logins were deleted. | Zestaw #%(id)s cofnięty; jego loginy zostały usunięte. |
| Credentials are waiting — reload this page. | Dane logowania czekają — odśwież tę stronę. |
| Kit #%(id)s was closed before its credentials were displayed. | Zestaw #%(id)s został zamknięty, zanim wyświetlono jego dane logowania. |
| Credentials for kit #%(id)s were never displayed and are gone; revoke it and create another. | Dane logowania zestawu #%(id)s nie zostały wyświetlone i przepadły; cofnij zestaw i utwórz nowy. |
| Demo kit #%(id)s — %(label)s | Zestaw demo #%(id)s — %(label)s |
| These passwords are not stored — copy them now. | Te hasła nie są nigdzie zapisywane — skopiuj je teraz. |
| Log in at | Adres logowania |
| Warnings | Ostrzeżenia |
| Create demo kit | Utwórz zestaw demo |
| Creating a kit can take a minute or more; keep this page open. If the page stops responding, wait a couple of minutes, then reopen the Demo tab — the credentials appear there once the kit exists. Do not create again until it shows in the list. | Tworzenie zestawu może potrwać minutę lub dłużej; nie zamykaj tej strony. Jeśli strona przestanie odpowiadać, odczekaj kilka minut i ponownie otwórz kartę Dostęp demo — dane logowania pojawią się tam, gdy zestaw powstanie. Nie twórz go ponownie, dopóki nie pojawi się na liście. |
| Days | Dni |
| Enter a label of at most %(max)s characters. | Etykieta może mieć najwyżej %(max)s znaków. |
| Must be between %(min)s and %(max)s. | Wartość musi mieścić się między %(min)s a %(max)s. |
| A kit for this label may have just been created. {link_start}Open the Demo tab{link_end} — its credentials appear there — before creating again. | Zestaw dla tej etykiety mógł właśnie zostać utworzony. {link_start}Otwórz kartę Dostęp demo{link_end} — pojawią się tam jego dane logowania — zanim utworzysz kolejny. |
| This course cannot hold a demo. | Ten kurs nie nadaje się do demo. |
| The generated class came out empty and was rolled back. | Wygenerowana klasa wyszła pusta i została wycofana. |
| Ran out of distinct pupil names; use fewer pupils. | Zabrakło różnych imion uczniów; wybierz mniej uczniów. |
| The demo kit could not be created. | Nie udało się utworzyć zestawu demo. |

⚠️ These are a non-native draft: the PR description must list them for Krzysztof's read (spec §4.8), especially the four status labels, which must agree with the existing neuter `Wygasłe` / `Cofnięte`.

- [ ] **Step 3: Check no stray fuzzy or obsolete entries.**

Run: `uv run python -c "import pathlib;t=pathlib.Path('locale/pl/LC_MESSAGES/django.po').read_text(encoding='utf-8');print(t.count('#, fuzzy'), t.count('#~'))"`
Expected: `0 0`. (The `grep '$'` anchor misses on CRLF `.po` files — use this instead.)

- [ ] **Step 4: Compile and run the catalog gate.**

Run: `uv run python manage.py compilemessages -l pl -l en` then `uv run pytest tests/test_i18n_po_health.py`
Expected: all passed.

- [ ] **Step 5: Re-run the tests that compare English copy.** Run `uv run pytest tests/demo/test_tab_actions.py tests/demo/test_tab_credentials.py tests/demo/test_tab_create.py` — they assert English wording (the long-lived warning, the notices, "This course cannot hold a demo."), which an accidental msgid edit during extraction would break; the tests run in `en`. The Polish render itself is checked by hand in Task 10 Step 4.

- [ ] **Step 6: Commit.**

```bash
git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo locale/en/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.mo
git commit -m "i18n(institution): Polish strings for the Demo access tab"
```

---

### Task 9: Documentation (spec §6, §7)

**Files:**
- Modify: `docs/superpowers/specs/2026-09-12-demo-access-for-schools-design.md`, `docs/superpowers/specs/2026-09-12-demo-access-admin-tab-design.md`, `docs/deployment.md`

**Interfaces:** none.

Every edit below is an exact old → new replacement. Use the Edit tool (or equivalent), never a scripted `sed` — a scripted edit that matches nothing fails silently; read the `git diff` afterwards.

- [ ] **Step 1: Parent §3.3.** Replace:

```
  `/admin/`. Acceptable while `mat-pp` is the only course on libli.pl; it is a standing
  caveat before a private course is added there.
```

with:

```
  `/admin/`. Acceptable while `mat-pp` is the only course on libli.pl; it is a standing
  caveat before a private course is added there.
  ⚠️ **Amended by PR 3 (2026-09-13): a *kit* Teacher is no longer staff** — `provision_kit`
  clears `is_staff` after `set_user_role` — so it reads only its kit's course and has no
  `/admin/` login (PR 3 spec §3.1). This bullet and the next stay true of ordinary Teachers.
```

- [ ] **Step 2: Parent §3.7.** Replace:

```
- the kit's **Student and ~20 pupils join the Default cohort**; the Teacher does not
  (staff are skipped);
```

with:

```
- the kit's **Student and ~20 pupils join the Default cohort**; the Teacher does not
  (staff are skipped) — ⚠️ *amended by PR 3: the Teacher is created non-staff, joins Default
  on insert and leaves on `set_user_role`'s role change; since PR 3 its exclusion rests on the
  Teacher role group alone (PR 3 spec §2.6, §3.1)*;
```

- [ ] **Step 3: Parent §4.4 step 0.** Replace:

```
   disambiguating integer) is caught and re-raised as the same named collision error.
```

with:

```
   disambiguating integer) is caught and re-raised as the same named collision error.
   ⚠️ **PR 2 shipped without this catch; PR 3 restores it** (PR 3 spec §2.5, §3.2).
```

- [ ] **Step 4: Parent §4.4 step 2.** Replace:

```
2. **Teacher login** — created with **`is_staff=True` in the initial `create_user` call**,
```

with:

```
2. **Teacher login** — ⚠️ *(as built: created non-staff, made staff by `set_user_role`, and
   cleared again by PR 3 — PR 3 spec §3.1; the `is_staff=True`-at-creation wording below never
   matched the code)* created with **`is_staff=True` in the initial `create_user` call**,
```

- [ ] **Step 5: Parent §4.6 admin tab.** Replace:

```
- create form (**course**, label, days, pupils) → POST → **redirect** to a result page that
```

with:

```
- ⚠️ **Superseded by the PR 3 spec (§4.2–§4.4, 2026-09-13):** there is no result page —
  credentials render at the top of the Demo panel from a session list written and read through
  a *separate* session store, with a warnings summary rather than the raw list; the cache is not
  an option (per-process `LocMemCache`); and a non-POST answers 302 to `?tab=demo`, not 405. The
  bullets below are kept as history.
- create form (**course**, label, days, pupils) → POST → **redirect** to a result page that
```

- [ ] **Step 6: Parent §5 step 0.** Replace:

```
     the decision is to stop issuing kits or to narrow a rep's read access (Risk 2).
```

with:

```
     the decision is to stop issuing kits or to narrow a rep's read access (Risk 2).
     ⚠️ **Retired for kit Teachers by PR 3** — a kit Teacher reads only its kit's course
     (PR 3 spec §3.1).
```

- [ ] **Step 7: Parent §6.** Replace:

```
**PR 3 — admin tab.** Views, templates, form, i18n, e2e. No new business logic: every action
calls PR 2's services.
```

with:

```
**PR 3 — admin tab.** Views, templates, form, i18n, e2e. No new business logic: every action
calls PR 2's services. ⚠️ *(Amended: PR 3 also carries two service changes — the non-staff kit
Teacher and the restored collision catch; PR 3 spec §3.)*
```

- [ ] **Step 8: Parent T10, T11, T14, T22 and Risk 2.** Five replacements, each a whole line.

T10 — replace:

```
  each action view returns 404. With the flag on: Platform Admin only; non-POST → 405.
```

with:

```
  each action view returns 404. With the flag on: Platform Admin only; non-POST → 405
  ⚠️ *(amended by PR 3: 302 to `?tab=demo`, matching every settings action view; the "gate on
  the tab list" mutant below is equivalent to the real check — PR 3 spec P3)*.
```

T11 — replace:

```
- **T11 Credentials are shown once.** The password appears in the first render of the result
```

with:

```
- **T11 Credentials are shown once.** ⚠️ *Superseded by PR 3 spec P4–P6, P9, P15 (no result
  page).* The password appears in the first render of the result
```

T14 — replace:

```
- **T14 `/admin/` exposes nothing.** A kit Teacher's `/admin/` index lists zero models
```

with:

```
- **T14 `/admin/` exposes nothing.** ⚠️ *Never implemented; superseded by PR 3 spec P1 — a kit
  Teacher is non-staff and `/admin/` refuses it.* A kit Teacher's `/admin/` index lists zero models
```

T22 — replace:

```
  field**, and after PR 3's result page is read once the password is gone from the session.
```

with:

```
  field**, and after PR 3's result page is read once the password is gone from the session
  ⚠️ *(PR 3 has no result page: P4 asserts the in-panel card is shown once)*.
```

Risk 2 — replace:

```
2. **Teacher reads every course.** §3.3. A standing caveat for the day a second, private
```

with:

```
2. **Teacher reads every course.** ⚠️ **Closed for kit Teachers by PR 3** (non-staff; PR 3
   spec §3.1). §3.3. A standing caveat for the day a second, private
```

- [ ] **Step 9: The PR 3 spec's status line.** In `docs/superpowers/specs/2026-09-12-demo-access-admin-tab-design.md`, replace `**Status:** approved in brainstorming 2026-09-12. Not yet planned, not yet built.` with a status line built from the review history rather than from this plan. Count first, on the branch that holds the review commits — they are not on `master` or on the feature branch, where the file arrived without history: `git log docs/demo-admin-tab-spec --format=%s -- docs/superpowers/specs/2026-09-12-demo-access-admin-tab-design.md` — R = the number of subjects starting `spec(demo-access-admin-tab-design): round` (never the `plan(` round commits, which may touch the spec too), A = the sum of their `applied N` (8 and 73 when this plan was written; more if the spec was reviewed again since). Then write `**Status:** approved 2026-09-12; spec-review R rounds, A applied. Plan: docs/superpowers/plans/2026-09-13-demo-access-admin-tab.md. Built in PR 3.` with the two numbers substituted.

- [ ] **Step 10: Runbook.** In `docs/deployment.md`, replace:

```
a **publishing decision, not an ops chore** — see the spec's §5. Do not flip it merely to
rehearse a kit.
```

with:

```
a **publishing decision, not an ops chore** — see the spec's §5. Do not flip it merely to
rehearse a kit. Once it is on, kits can also be issued, extended and revoked from **Settings →
Demo access** (`/manage/settings/?tab=demo`), which calls the same services as `demo_access`;
provision and revoke the first throwaway kit there, which also measures the prod wall-clock.
```

- [ ] **Step 11: Read the diff, then commit.**

Run: `git diff --stat` — three files; `git diff docs/` — every replacement landed once.

```bash
git add docs/superpowers/specs/2026-09-12-demo-access-for-schools-design.md docs/superpowers/specs/2026-09-12-demo-access-admin-tab-design.md docs/deployment.md
git commit -m "docs(demo): PR 3 amendments to the parent spec, spec status, runbook"
```

---

### Task 10: Gates and the local pass

**Files:** none new.

- [ ] **Step 1: Lint.**

Run: `uv run ruff check --no-cache .` and `uv run ruff format --check .`
Expected: both clean. If `ruff format --check` lists files, run `uv run ruff format <those files>` and commit `style: ruff format`. If ruff flags `S308` on `mark_safe("</a>")`, add `# noqa: S308 - literal closing tag, no input` to that line.

- [ ] **Step 2: Migrations.**

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: `No changes detected`.

- [ ] **Step 3: Scoped suites.**

Run: `uv run pytest tests/demo tests/test_settings_action_method_guard.py tests/test_pricing_settings_tab.py tests/test_i18n_po_health.py tests/test_access_taught_courses.py tests/test_courses_access.py`
Then: `uv run pytest -m e2e tests/test_e2e_demo_tab.py tests/test_e2e_settings.py`
Expected: grep each summary line — `N passed`, `0 failed`, no `error`. The whole-repo run is the branch gate CI performs; do not run it in one process locally (it is OOM-killed with 0-byte output).

- [ ] **Step 4: The local pass against `mat-pp`** (spec §5 "Beyond the suite"; needs the dev DB with `mat-pp`, `LIBLI_VENDOR_INSTANCE=true` exported for this shell only, and `uv run python manage.py runserver`):
  - [ ] If a service worker serves stale JS/CSS, unregister it first (DevTools → Application).
  - [ ] Create a **20-pupil** kit on `mat-pp` through the tab; record the wall-clock the browser shows, for the PR description.
  - [ ] Read the warnings panel at real volume: webhook line first if one is enabled, counts plausible, unit titles present.
  - [ ] Screenshot the Demo tab with a card, in **light and dark**, and judge dark separately.
  - [ ] From the card page, navigate to another settings tab, press Back — no password is restored; then Back and Forward — still none.
  - [ ] Log in as the kit's Teacher (analytics, drill-down, review queue load; another course's outline is 403 if a second course exists locally; `/admin/` refuses) and as its Student (a quiz can be taken).
  - [ ] Double-click Create for a second (5-pupil) kit: exactly one kit appears, and the button showed disabled while the request ran.
  - [ ] Extend a kit, then press Back: the Extend buttons are clickable again (`pageshow` re-enable).
  - [ ] Click Revoke and cancel the confirm: Revoke is still clickable and the kit is still open.
  - [ ] Switch your user language to Polish: the tab reads "Dostęp demo" and no English string remains in the Demo panel.
  - [ ] Revoke the kit through the tab; the confirm prompt appears; the row leaves the default list.

- [ ] **Step 5: Human review items for the PR description** (not automatable, spec §4.8):
  - the tab's copy contains nothing about marking answers, grading written work or the awaiting-review queue (A6);
  - the Polish strings of Task 8, especially the four status labels against `Wygasłe` / `Cofnięte`.

- [ ] **Step 6: Push and open the PR** only when Krzysztof asks. The PR body states: ships dark (no flag change), the two service changes, the measured wall-clock, the screenshots, and the Step 5 review items. End it with the attribution line the session requires.
