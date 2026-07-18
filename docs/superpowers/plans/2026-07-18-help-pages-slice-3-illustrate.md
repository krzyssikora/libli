# Help pages slice 3 — illustrate every remaining topic — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every one of the 23 in-app help topics at least one committed screenshot in both English and Polish, captured deterministically from the seeded demo course via a declarative dual-locale Playwright harness.

**Architecture:** One enriched, idempotent seed command (`seed_demo_course`) provides every surface's data. A single declarative `SHOTS` registry in the rewritten capture harness drives, once per locale (en, pl), a login → navigate → wait → clip → save loop, under a frozen clock and a capture-only urlconf that serves MEDIA. A parametrized coverage-gate test asserts every topic embeds a locale-matched, on-disk image in both languages.

**Tech Stack:** Django 5, pytest + pytest-django (`live_server`) + pytest-playwright (`browser`/`page`), freezegun (new dev dep), Python markdown, WhiteNoise (prod static — irrelevant under test's plain storage).

## Global Constraints

- **Scope:** 23 topics (5 course-admin, 11 platform-admin, 7 teacher), each illustrated in EN **and** PL. Light mode only. Docs + capture harness + seed only — **no** `doc-page.css` changes, **no** product/access changes.
- **No i18n catalog churn:** alt text and image paths live in the markdown files, not the gettext catalog. This slice adds **no** translatable strings — `makemessages` must show 0 new/obsolete/fuzzy entries.
- **Image naming:** `core/static/core/img/help/<name>.<locale>.png` (e.g. `builder-tree.en.png`, `builder-tree.pl.png`).
- **Embed sentinel:** `![<alt in the doc's language>](static:core/img/help/<name>.<locale>.png)` — EN alt in `*.md`, PL alt in `*.pl.md`.
- **Harness is a regeneration tool, not CI:** file stays named `capture_help_screenshots.py` (no `test_` prefix → not auto-collected under `python_files=["test_*.py"]`); the single runnable function keeps a `test_` name so an explicit path collects it; it is **never** `@pytest.mark.e2e`.
- **Seed stays fully idempotent** (get_or_create / `_upsert` discipline). Runs once per capture run; other tests also call it.
- **Clock frozen** for the whole capture run (seed + all captures) to a fixed instant `2026-07-18 12:00:00`.
- **No literal pk in any captured URL** — the `url` field is a capture-time callable using `reverse(app:name, kwargs=...)` from stable-key lookups (course slug, unit title, group name, username).
- **PL-locale falsifiability:** in the PL pass, before each screenshot assert `'lang="pl"'` is in `page.content()` (base.html renders `<html lang="{{ LANGUAGE_CODE }}">`), so a wrong-locale render fails the run.
- **Coverage gate:** every topic's EN and PL markdown embeds ≥1 `static:` image; **every** referenced `static:` path resolves via `django.contrib.staticfiles.finders.find`; **every** embedded image in a doc carries the doc's locale suffix (`.en.png` in `*.md`, `.pl.png` in `*.pl.md`).

## Corrections to the spec discovered during planning (grounded in code — call out in the PR)

1. **Settings-tab surfaces use `institution:settings?tab=<tab>` (GET), not the dedicated routes.** `settings_branding/_sso/_integrations/_notifications` are POST handlers that redirect GET to `reverse('institution:settings')+"?tab="+tab` (`institution/views_manage.py`). The spec's dedicated-route mapping is superseded.
2. **The notifications *help topic* documents the PA Institution-settings Notifications tab** (retention/prefs — per `docs/help/platform-admin/notifications.md` prose: "Admin → Institution settings → Notifications"), **not** the `notifications:list` inbox. So it maps to `settings?tab=notifications`, and the spec's Notification-row seeding + `created_at` backdating are **dropped** (not needed for that surface).
3. **Export is a file download**, so export-import is captured on `courses:manage_course_import` (`import_course.html`), not the export route.
4. **PL-locale proof is `lang="pl"` in `page.content()`** (base.html sets `<html lang="{{ LANGUAGE_CODE }}">`) — strictly better than the spec's chrome-string check (role/surface-independent, present even on the wizard). No per-shot override needed.
5. **`django.conf.urls.static.static()` returns `[]` when `DEBUG=False`** (test settings), so the capture urlconf wires `django.views.static.serve` directly via `re_path`, not `static()`.
6. **interactive-elements host = "Bonus lesson"** (seed adds a `RevealGateElement` there); **content-editors consumption = "Core lesson"** (seed co-locates the shared `demo.png` image there).

## File Structure

- `pyproject.toml` — add `freezegun` to `[dependency-groups] dev`.
- `tests/capture_urls.py` — **new.** Capture-only ROOT_URLCONF: `config.urls` patterns + a `serve`-backed `/media/` route.
- `tests/test_capture_urls.py` — **new.** Smoke test: MEDIA served 200 under the capture urlconf.
- `courses/management/commands/seed_demo_course.py` — **modify.** Add PA user, interactive element, co-located image, note, tag, collection, REVIEW question + unreviewed submission, SSO config, webhook, cohort, branding, explicit `last_login`.
- `tests/test_seed_demo_course.py` — **modify.** Assert the new seed objects; keep idempotency assertions.
- `tests/capture_help_screenshots.py` — **rewrite.** Declarative `SHOTS` registry + dual-locale loop + freeze + capture urlconf + per-shot MEDIA tripwire + PL-lang assertion.
- `docs/help/**/*.md` and `*.pl.md` — **modify.** Embed shot(s) per topic (EN + PL). Builder image refs renamed.
- `core/static/core/img/help/*.png` — **new/regenerated.** ~29 shots × 2 locales.
- `tests/test_help.py` — **modify.** Replace `test_all_topics_static_refs_resolve` + `test_builder_topic_embeds_existing_screenshot` with the new dual-locale coverage gate.

---

## Task 1: Substrate — freeze dep + capture urlconf + MEDIA smoke test

**Files:**
- Modify: `pyproject.toml` (`[dependency-groups] dev`)
- Create: `tests/capture_urls.py`
- Create: `tests/test_capture_urls.py`

**Interfaces:**
- Produces: module `tests.capture_urls` with `urlpatterns` serving `/media/<path>` via `django.views.static.serve` reading `settings.MEDIA_ROOT` at request time; consumed by Task 3 via `override_settings(ROOT_URLCONF="tests.capture_urls")`.

- [ ] **Step 1: Add the freeze dependency**

In `pyproject.toml`, under `[dependency-groups]` `dev = [ ... ]`, add the line (keep the list sorted/comma-correct):

```toml
    "freezegun>=1.5",
```

- [ ] **Step 2: Install it**

Run: `uv sync`
Expected: resolves and installs `freezegun`; `uv.lock` updates.

- [ ] **Step 3: Write the capture urlconf**

Create `tests/capture_urls.py`:

```python
"""Capture-only ROOT_URLCONF: the real routes plus an unconditional /media/ route.

Django's `static()` helper returns [] when DEBUG is False (test settings set
DEBUG=False), and `config/urls.py` only wires media under `if settings.DEBUG`, so a
lesson-consumption capture would 404 on its MEDIA image. This urlconf serves media
directly via `django.views.static.serve`, reading MEDIA_ROOT at request time so an
`override_settings(MEDIA_ROOT=...)` in tests takes effect. Activated by the capture
harness via `override_settings(ROOT_URLCONF="tests.capture_urls")`.
"""

from django.conf import settings
from django.urls import re_path
from django.views.static import serve

from config.urls import urlpatterns as _base_urlpatterns


def _serve_media(request, path):
    # document_root read per-request so override_settings(MEDIA_ROOT=...) applies.
    return serve(request, path, document_root=settings.MEDIA_ROOT)


urlpatterns = list(_base_urlpatterns) + [
    re_path(r"^media/(?P<path>.*)$", _serve_media),
]
```

- [ ] **Step 4: Write the failing smoke test**

Create `tests/test_capture_urls.py`:

```python
from django.test import override_settings


@override_settings(ROOT_URLCONF="tests.capture_urls")
def test_capture_urls_serves_media(client, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    (tmp_path / "smoke.txt").write_bytes(b"ok")
    resp = client.get("/media/smoke.txt")
    assert resp.status_code == 200
    assert b"ok" in b"".join(resp.streaming_content)
```

- [ ] **Step 5: Run it**

Run: `uv run pytest tests/test_capture_urls.py -v`
Expected: PASS (the capture urlconf serves the tmp media file 200).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock tests/capture_urls.py tests/test_capture_urls.py
git commit -m "feat(help-capture): freezegun dep + capture urlconf serving MEDIA under test"
```

---

## Task 2: Seed enrichment

**Files:**
- Modify: `courses/management/commands/seed_demo_course.py`
- Modify: `tests/test_seed_demo_course.py`

**Interfaces:**
- Consumes: existing helpers `_user`, `_node`, `_upsert`, `_image`, `_quiz`, `_group`, `self.course`, `self.teacher`, `self.group_students`.
- Produces (stable lookup keys for Task 3's URL callables): PA user `demo_admin`; `RevealGateElement` on "Bonus lesson"; shared `demo.png` `ImageElement` also on "Core lesson"; a `Note` + `Tag` by `demo_teacher`; `Collection(name="Demo Collection")`; a REVIEW `ExtendedResponseQuestionElement` on "Demo quiz" + a SUBMITTED `QuizSubmission` by `demo_student`; a disabled SSO `SocialApp`; a `WebhookEndpoint` + one `WebhookDelivery`; `Cohort(name="Autumn 2026")`; institution branding fields; explicit `last_login` on `demo_teacher`/`demo_admin`.

- [ ] **Step 1: Add imports**

At the top of `seed_demo_course.py`, add:

```python
import datetime

from django.contrib.sites.models import Site
from django.utils import timezone

from accounts.models import Invitation
from accounts.sso_config import save_sso_config
from courses.models import ExtendedResponseQuestionElement
from courses.models import RevealGateElement
from grouping.models import Cohort
from grouping.models import Collection
from institution.roles import PLATFORM_ADMIN
from institution.roles import STUDENT
from integrations.models import WebhookDelivery
from integrations.models import WebhookEndpoint
from notes.models import Note
from notifications.models import Notification  # noqa: F401 (kept for future bell shot; may be removed)
from tags.models import Tag
from tags.models import UnitTag
```

(Drop the `Notification` import if the linter flags it unused — the notifications topic uses the settings tab, no rows needed.)

- [ ] **Step 2: Create the PA user and seed explicit last_login**

In `handle`, after the existing `student`/`s1`/`s2`/`s3` block and `course.owner` assignment, add:

```python
        admin = self._user(
            "demo_admin",
            "Demo Admin",
            email="demo_admin@demo.example",
            role=PLATFORM_ADMIN,
        )
        self.admin = admin
        # People list shows last_login|date else "Never". Seed it explicitly so the
        # shot is order/pass-independent (the freeze pins value, not presence).
        fixed_login = timezone.now() - datetime.timedelta(days=1)
        User.objects.filter(pk__in=[teacher.pk, admin.pk]).update(last_login=fixed_login)
```

- [ ] **Step 3: Co-locate the shared demo image on the content-rich unit + add the interactive element**

In `handle`, after the existing content-element block (`self._table(lesson)`), add:

```python
        # content-editors consumption shot captures "Core lesson"; give it a MEDIA image
        # so the broken-image tripwire is load-bearing. _image reuses the shared demo.png
        # MediaAsset (filter by course+filename), so no second asset is created.
        self._image(lesson, "core-image", "Worked example diagram")
        # interactive-elements shot captures "Bonus lesson"; add a reveal-gate self-check.
        self._reveal_gate(extra)
```

Add the helper method (near `_spoiler`):

```python
    def _reveal_gate(self, unit):
        self._upsert(unit, RevealGateElement, label="Show more")
```

- [ ] **Step 4: Add note, tag, collection**

In `handle`, after `self._group(quiz)`, add:

```python
        self._note(student, lesson)
        self._tag(student, lesson)
        self._collection(course, teacher)
```

Add helpers:

```python
    def _note(self, author, unit):
        anchor = unit.elements.first()
        Note.objects.get_or_create(
            author=author,
            unit=unit,
            element=anchor,
            defaults={"body": "My private note on this block."},
        )

    def _tag(self, author, unit):
        tag, _ = Tag.objects.get_or_create(
            author=author, name="Revision", defaults={"color": "amber"}
        )
        UnitTag.objects.get_or_create(tag=tag, unit=unit)

    def _collection(self, course, owner):
        col, _ = Collection.objects.get_or_create(
            name="Demo Collection", course=course, defaults={"owner": owner}
        )
        group = Group.objects.get(name="Demo Group", course=course)
        col.groups.add(group)
```

- [ ] **Step 5: Add the REVIEW question + demo_student's unreviewed submission**

In `handle`, after the `_collection(...)` call, add:

```python
        self._review_flow(quiz, student)
```

Add helpers (note: added AFTER `_group` so the 3 group submissions' frozen `max_score` is unchanged; `demo_student` is enrolled, ungrouped, and reachable to the owner via `reviewable_students`):

```python
    def _review_question(self, quiz):
        er = ExtendedResponseQuestionElement.objects.filter(
            element__unit=quiz
        ).first()
        if er is None:
            er = ExtendedResponseQuestionElement.objects.create(
                stem="Explain your reasoning.",
                marking_mode=QuestionElement.MarkingMode.REVIEW,
                max_marks=Decimal("5"),
            )
            self.q_review = Element.objects.create(unit=quiz, content_object=er)
        else:
            self.q_review = Element.objects.get(
                unit=quiz, content_type__model="extendedresponsequestionelement"
            )
        return self.q_review

    def _review_flow(self, quiz, student):
        review_el = self._review_question(quiz)
        submission, _ = QuizSubmission.objects.get_or_create(
            student=student,
            unit=quiz,
            defaults={"status": QuizSubmission.Status.IN_PROGRESS},
        )
        if submission.status == QuizSubmission.Status.SUBMITTED:
            return  # already finalized on a prior run — idempotent
        QuestionResponse.objects.get_or_create(
            submission=submission,
            element=review_el,
            defaults={
                "latest_answer": "Because the discriminant is positive.",
                "attempt_count": 1,
            },  # reviewed_at stays None -> lands in the review queue
        )
        finalize_submission(quiz, submission)
```

- [ ] **Step 6: Seed PA-surface state (SSO, webhook, cohort, branding, invitation)**

In `handle`, after `_review_flow(...)`, add:

```python
        self._sso_config()
        self._webhook()
        self._cohort()
        self._branding()
        self._invitation(teacher)
```

Add helpers:

```python
    def _sso_config(self):
        save_sso_config(
            name="Demo IdP",
            server_url="https://idp.demo.example",
            client_id="demo-client",
            client_secret="demo-secret",
            enabled=False,  # saved but disabled
            site=Site.objects.get_current(),
        )

    def _webhook(self):
        ep = WebhookEndpoint.load()
        ep.enabled = True
        ep.url = "https://sis.demo.example/hook"
        ep.secret = "demo-hmac"  # noqa: S105
        ep.save()
        WebhookDelivery.objects.get_or_create(
            dedupe_key="demo-1",
            defaults={
                "event": WebhookDelivery.Event.RESULT_FINALIZED,
                "payload": {"submission_id": 1, "score": "2.00"},
                "status": WebhookDelivery.Status.DELIVERED,
            },
        )

    def _cohort(self):
        Cohort.objects.get_or_create(name="Autumn 2026")

    def _branding(self):
        from core.services import get_site_config  # noqa: F401 (cache invalidated on save)
        from institution.models import Institution

        inst, _ = Institution.objects.get_or_create(pk=1)
        inst.display_name = "Demo Academy"
        inst.save()  # post_save signal invalidates the get_site_config cache

    def _invitation(self, teacher):
        Invitation.objects.get_or_create(
            email="invitee@demo.example",
            defaults={"role": STUDENT, "invited_by": teacher},
        )
```

> Note: confirm `Institution`'s branding field name (`display_name` vs `name`/`brand_name`) against `institution/models.py` and the `_branding_tab.html` form before running; use whatever field the Branding tab renders. If the get_or_create(pk=1) pattern conflicts with an existing singleton accessor (e.g. `Institution.load()`), use that accessor instead.

- [ ] **Step 7: Write/extend the seed tests**

In `tests/test_seed_demo_course.py`, add (they rely on the existing autouse `_isolate_media_root(settings, tmp_path)` fixture):

```python
def test_seed_creates_pa_and_review_and_collection():
    from django.contrib.auth import get_user_model
    from courses.models import ContentNode, Element, QuizSubmission
    from grouping.models import Cohort, Collection
    from notes.models import Note
    from tags.models import Tag

    call_command("seed_demo_course")
    User = get_user_model()

    admin = User.objects.get(username="demo_admin")
    assert admin.is_staff and admin.last_login is not None

    quiz = ContentNode.objects.get(title="Demo quiz")
    assert Element.objects.filter(
        unit=quiz, content_type__model="extendedresponsequestionelement"
    ).exists()
    student = User.objects.get(username="demo_student")
    sub = QuizSubmission.objects.get(student=student, unit=quiz)
    assert sub.status == QuizSubmission.Status.SUBMITTED

    assert Collection.objects.filter(name="Demo Collection").count() == 1
    assert Cohort.objects.filter(name="Autumn 2026").exists()
    assert Note.objects.filter(author__username="demo_student").exists()
    assert Tag.objects.filter(author__username="demo_student", name="Revision").exists()


def test_seed_review_submission_is_in_review_queue():
    from courses.models import Course
    from courses.review import pending_reviews_for
    from django.contrib.auth import get_user_model

    call_command("seed_demo_course")
    User = get_user_model()
    teacher = User.objects.get(username="demo_teacher")
    course = Course.objects.get(slug="demo-course")
    pending = pending_reviews_for(teacher, course)
    assert pending["awaiting"], "expected an awaiting-review submission for the queue shot"


def test_seed_is_idempotent_second_run():
    call_command("seed_demo_course")
    call_command("seed_demo_course")  # must not raise / duplicate
    from grouping.models import Collection

    assert Collection.objects.filter(name="Demo Collection").count() == 1
```

> Confirm `pending_reviews_for`'s return shape (`["awaiting"]` list) against `courses/review.py:236` before finalizing the assertion; adjust the key if the real API differs.

- [ ] **Step 8: Run the seed tests**

Run: `uv run pytest tests/test_seed_demo_course.py -v`
Expected: PASS (all new + existing seed tests green).

- [ ] **Step 9: Run the full non-e2e suite to catch analytics-tolerance regressions**

Run: `uv run pytest -q`
Expected: PASS. If `test_seed_quiz_group_populate_analytics` or similar fails on an exact count/score, the REVIEW element shifted an assertion — verify it's a tolerant check (`percent is not None`, `>= 5`) per research; if a hard count broke, adjust that test to the new element count (document why in the commit).

- [ ] **Step 10: Commit**

```bash
git add courses/management/commands/seed_demo_course.py tests/test_seed_demo_course.py
git commit -m "feat(seed): enrich demo course for slice-3 help screenshots"
```

---

## Task 3: Capture harness rewrite (declarative dual-locale registry)

**Files:**
- Modify (rewrite): `tests/capture_help_screenshots.py`

**Interfaces:**
- Consumes: `tests.capture_urls`, `seed_demo_course`, the seeded objects (Task 2).
- Produces: `core/static/core/img/help/<name>.<locale>.png` for every entry in `SHOTS` × {en, pl}; a `test_shots_cover_every_topic` self-check.

- [ ] **Step 1: Write the new harness**

Replace the entire contents of `tests/capture_help_screenshots.py` with:

```python
"""Deterministic dual-locale help-screenshot capture (regeneration tool, not CI).

Regenerate committed help screenshots:

    uv run playwright install chromium   # first time only
    uv run python -m pytest tests/capture_help_screenshots.py

Not `test_`-prefixed as a filename -> not auto-collected by `python_files=["test_*.py"]`;
the single `test_`-named function is collected only when the path is passed explicitly.
Never marked `@pytest.mark.e2e`, so the explicit run isn't deselected by `-m 'not e2e'`.
"""

import os

import pytest
from django.conf import settings
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from freezegun import freeze_time

pytestmark = pytest.mark.django_db(transaction=True)  # committed rows visible to the server

FREEZE_AT = "2026-07-18 12:00:00"
DEMO_PASSWORD = "demo-pass-123"  # mirrors the seed's DEMO_PASSWORD
OUT_DIR = settings.BASE_DIR / "core" / "static" / "core" / "img" / "help"


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _u(name, **kwargs):
    """Resolve a namespaced URL from stable lookups at capture time (no literal pk)."""
    from courses.models import ContentNode, Course, QuizSubmission
    from django.contrib.auth import get_user_model
    from grouping.models import Collection, Group

    User = get_user_model()
    course = Course.objects.get(slug="demo-course")

    def unit(title):
        return ContentNode.objects.get(course=course, title=title)

    if name == "settings":
        # settings tabs are one page with ?tab=; kwargs carries {"tab": ...}
        return reverse("institution:settings") + f"?tab={kwargs['tab']}"
    if name == "manage_builder":
        return reverse("courses:manage_builder", kwargs={"slug": "demo-course"})
    if name == "manage_editor":
        return reverse("courses:manage_editor",
                       kwargs={"slug": "demo-course", "pk": unit(kwargs["unit"]).pk})
    if name == "lesson_unit":
        return reverse("courses:lesson_unit",
                       kwargs={"slug": "demo-course", "node_pk": unit(kwargs["unit"]).pk})
    if name == "manage_media":
        return reverse("courses:manage_media", kwargs={"slug": "demo-course"})
    if name == "manage_analytics":
        return reverse("courses:manage_analytics", kwargs={"slug": "demo-course"})
    if name == "manage_analytics_student":
        pk = User.objects.get(username=kwargs["username"]).pk
        return reverse("courses:manage_analytics_student",
                       kwargs={"slug": "demo-course", "student_pk": pk})
    if name == "manage_review_queue":
        return reverse("courses:manage_review_queue", kwargs={"slug": "demo-course"})
    if name == "manage_review_submission":
        sub = QuizSubmission.objects.get(student__username="demo_student",
                                         unit=unit("Demo quiz"))
        return reverse("courses:manage_review_submission",
                       kwargs={"slug": "demo-course", "submission_pk": sub.pk})
    if name == "my_groups":
        return reverse("grouping:my_groups")
    if name == "group_detail":
        pk = Group.objects.get(name="Demo Group", course=course).pk
        return reverse("grouping:group_detail", kwargs={"pk": pk})
    if name == "collection_detail":
        pk = Collection.objects.get(name="Demo Collection").pk
        return reverse("grouping:collection_detail", kwargs={"pk": pk})
    if name == "notes_overview":
        return reverse("notes:overview")
    if name == "my_tags":
        return reverse("tags:my_tags")
    if name == "manage_course_list":
        return reverse("courses:manage_course_list")
    if name == "manage_course_create":
        return reverse("courses:manage_course_create")
    if name == "manage_course_import":
        return reverse("courses:manage_course_import")
    if name == "people":
        return reverse("accounts:people")
    if name == "people_invitations":
        return reverse("accounts:people_invitations")
    if name == "manage_subject_list":
        return reverse("courses:manage_subject_list")
    if name == "cohort_list":
        return reverse("grouping:cohort_list")
    if name == "setup":
        return reverse("institution:setup")
    raise ValueError(f"unknown route key {name!r}")


# name, login_as, route-callable-args, wait_selector, clip_selector
SHOTS = [
    # --- course-admin (demo_teacher) ---
    ("builder-tree",   "demo_teacher", ("manage_builder", {}),                    ".builder__tree",       "section.builder"),
    ("content-editor", "demo_teacher", ("manage_editor", {"unit": "Core lesson"}), ".editor-head__title",  "section.editor"),
    ("content-consume","demo_teacher", ("lesson_unit", {"unit": "Core lesson"}),  "article.lesson",       "article.lesson"),
    ("quiz-editor",    "demo_teacher", ("manage_editor", {"unit": "Demo quiz"}),  ".editor-head__title",  "section.editor"),
    ("interactive",    "demo_teacher", ("lesson_unit", {"unit": "Bonus lesson"}), "article.lesson",       "article.lesson"),
    ("media-manager",  "demo_teacher", ("manage_media", {}),                      ".media-manager",       "section.media-manager"),
    # --- teacher (demo_teacher) ---
    ("analytics-matrix","demo_teacher",("manage_analytics", {}),                  ".analytics__matrix",   "section.manage"),
    ("drill-down",     "demo_teacher", ("manage_analytics_student", {"username": "demo_s1"}), ".breakdown__tree", "section.manage"),
    ("review-queue",   "demo_teacher", ("manage_review_queue", {}),              "section.manage",        "section.manage"),
    ("review-submission","demo_teacher",("manage_review_submission", {}),        ".review-topbar__title", ".review-shell"),
    ("groups",         "demo_teacher", ("my_groups", {}),                        ".dash-cards",           "section.manage"),
    ("group-detail",   "demo_teacher", ("group_detail", {}),                     ".manage__title",        "section.manage"),
    ("collection-detail","demo_teacher",("collection_detail", {}),              ".manage__title",         "section.manage"),
    ("roster",         "demo_teacher", ("group_detail", {}),                     ".manage__title",        "section.manage"),
    ("gradebook-export","demo_teacher",("manage_analytics", {}),                 ".analytics__matrix",    "section.manage"),
    ("notes-hub",      "demo_teacher", ("notes_overview", {}),                   "section.tnhub",         "section.tnhub"),
    ("my-tags",        "demo_teacher", ("my_tags", {}),                          "section.my-tags",       "section.my-tags"),
    # --- platform-admin (demo_admin) ---
    ("course-list",    "demo_admin",   ("manage_course_list", {}),               ".course-list",          "section.manage"),
    ("course-create",  "demo_admin",   ("manage_course_create", {}),             "form.form",             "section.manage"),
    ("import",         "demo_admin",   ("manage_course_import", {}),             ".dropzone",             "section.manage"),
    ("people",         "demo_admin",   ("people", {}),                           ".people-table",         "section.manage"),
    ("invitations",    "demo_admin",   ("people_invitations", {}),               ".invite-form",          "section.manage"),
    ("branding",       "demo_admin",   ("settings", {"tab": "branding"}),        ".settings__tabs",       "section.settings"),
    ("sso",            "demo_admin",   ("settings", {"tab": "sso"}),             ".settings__tabs",       "section.settings"),
    ("integrations",   "demo_admin",   ("settings", {"tab": "integrations"}),    ".settings__tabs",       "section.settings"),
    ("subjects",       "demo_admin",   ("manage_subject_list", {}),              ".card-list",            "section.manage"),
    ("cohorts",        "demo_admin",   ("cohort_list", {}),                      ".card-list",            "main.app-main"),
    ("notifications",  "demo_admin",   ("settings", {"tab": "notifications"}),   ".settings__tabs",       "section.settings"),
    ("wizard",         "demo_admin",   ("setup", {}),                            ".setup__panel",         "section.setup"),
]

# Which topic doc(s) each shot belongs to (for the coverage-gate cross-check in Task 7).
TOPIC_SHOTS = {
    "builder": ["builder-tree"],
    "content-editors": ["content-editor", "content-consume"],
    "quiz-editors": ["quiz-editor"],
    "interactive-elements": ["interactive"],
    "media-manager": ["media-manager"],
    "analytics": ["analytics-matrix"],
    "drill-down": ["drill-down"],
    "quiz-review": ["review-queue", "review-submission"],
    "groups-collections": ["groups", "group-detail", "collection-detail"],
    "roster": ["roster"],
    "gradebook-export": ["gradebook-export"],
    "notes-tags": ["notes-hub", "my-tags"],
    "create-a-course": ["course-list", "course-create"],
    "export-import": ["import"],
    "users-roles": ["people"],
    "invitations": ["invitations"],
    "branding-settings": ["branding"],
    "sso": ["sso"],
    "integrations": ["integrations"],
    "subjects": ["subjects"],
    "cohorts": ["cohorts"],
    "notifications": ["notifications"],
    "first-run-wizard": ["wizard"],
}


def test_shots_cover_every_topic():
    """Self-check: every registered help topic has at least one shot mapped."""
    from core.help import TOPICS

    shot_names = {s[0] for s in SHOTS}
    for names in TOPIC_SHOTS.values():
        for n in names:
            assert n in shot_names, f"TOPIC_SHOTS references unknown shot {n!r}"
    topic_slugs = {t.slug for t in TOPICS}
    assert set(TOPIC_SHOTS) == topic_slugs, (
        f"TOPIC_SHOTS/TOPICS mismatch: {set(TOPIC_SHOTS) ^ topic_slugs}"
    )


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(DEMO_PASSWORD)
    form.locator("button[type='submit']").click()
    page.wait_for_load_state("networkidle")


def _set_language(locale):
    from django.contrib.auth import get_user_model

    get_user_model().objects.filter(
        username__in=["demo_teacher", "demo_admin"]
    ).update(language=locale)


@override_settings(ROOT_URLCONF="tests.capture_urls")
def test_capture_help_screenshots(live_server, browser):
    with freeze_time(FREEZE_AT):
        call_command("seed_demo_course")  # once, before the locale loop
        OUT_DIR.mkdir(parents=True, exist_ok=True)

        for locale in ("en", "pl"):
            _set_language(locale)  # login signal seeds session _language from this
            for persona in ("demo_teacher", "demo_admin"):
                persona_shots = [s for s in SHOTS if s[1] == persona]
                if not persona_shots:
                    continue
                # Fresh context => fresh session (correct user/locale) + re-applied
                # viewport/media, matching the repo's browser.new_context() idiom.
                ctx = browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    color_scheme="light",
                    reduced_motion="reduce",
                )
                page = ctx.new_page()
                _login(page, live_server, persona)

                for name, _who, (route, args), wait_sel, clip_sel in persona_shots:
                    bad_images = []
                    page.on(
                        "response",
                        lambda r: bad_images.append((r.url, r.status))
                        if r.request.resource_type == "image"
                        and r.status >= 400
                        and "/media/" in r.url
                        else None,
                    )
                    page.goto(live_server.url + _u(route, **args))
                    page.locator(wait_sel).first.wait_for(state="visible")
                    page.wait_for_load_state("networkidle")
                    if locale == "pl":
                        assert 'lang="pl"' in page.content(), (
                            f"{name}: expected PL chrome (lang=pl) but page is not Polish"
                        )
                    assert not bad_images, f"{name}: broken MEDIA image(s): {bad_images}"
                    page.locator(clip_sel).first.screenshot(
                        path=str(OUT_DIR / f"{name}.{locale}.png")
                    )
                    page.remove_listener("response", page.listeners("response")[-1]) \
                        if page.listeners("response") else None

                ctx.close()
```

> The per-shot `response` listener add/remove is fiddly; an acceptable simpler alternative is to register one listener per context that appends to a per-shot list you clear before each `goto` (reset `bad_images` to a fresh list the listener closes over via a mutable holder). Keep whichever the implementer verifies works; the invariant is: **a >=400 `/media/` image request fails that shot.**

- [ ] **Step 2: Run the self-check test (fast, no browser)**

Run: `uv run pytest tests/capture_help_screenshots.py::test_shots_cover_every_topic -v`
Expected: PASS — every topic slug maps to ≥1 shot and every shot name exists.

- [ ] **Step 3: Install chromium (first time) and run the full capture**

Run: `uv run playwright install chromium`
Then: `uv run pytest tests/capture_help_screenshots.py::test_capture_help_screenshots -v`
Expected: PASS. Produces ~58 PNGs under `core/static/core/img/help/`. If a shot fails on a wait/clip selector, open that template (paths in the plan's Task 4-6 tables) and correct the selector; if a PL assertion fails, the locale didn't take — verify `_set_language` + fresh context ordering.

- [ ] **Step 4: Eyeball a sample**

Open 3-4 PNGs across roles and both locales (e.g. `builder-tree.en.png`, `content-consume.en.png`, `sso.pl.png`, `wizard.pl.png`). Confirm: light mode, correct surface, PL shots show Polish chrome, `content-consume` shows the worked-example image (not a broken icon).

- [ ] **Step 5: Commit harness + images**

```bash
git add tests/capture_help_screenshots.py core/static/core/img/help/
git commit -m "feat(help-capture): declarative dual-locale screenshot harness + regenerated images"
```

---

## Task 4: Course-admin docs — embed shots (EN + PL) + builder rename

**Files:**
- Modify: `docs/help/course-admin/{builder,content-editors,quiz-editors,interactive-elements,media-manager}.md` and their `.pl.md` siblings
- Modify: `tests/test_help.py` (update the builder-specific test's image name)
- Delete: `core/static/core/img/help/builder-tree.png` (superseded by `.en.png`)

**Embed pattern:** insert `![<alt>](static:core/img/help/<name>.<locale>.png)` after the topic's first `##` heading (or after the intro paragraph). EN alt in `*.md`, PL alt in `*.pl.md`.

| Topic file | Image(s) | EN alt | PL alt |
|---|---|---|---|
| builder | builder-tree | The course builder showing the demo course tree | Kreator kursu pokazujący drzewo kursu demo |
| content-editors | content-editor | The lesson editor with content blocks | Edytor lekcji z blokami treści |
| content-editors | content-consume | A lesson page as students see it | Strona lekcji widziana przez uczniów |
| quiz-editors | quiz-editor | The quiz editor with questions | Edytor quizu z pytaniami |
| interactive-elements | interactive | A lesson with a reveal-gate self-check | Lekcja z elementem interaktywnym „Pokaż więcej” |
| media-manager | media-manager | The media library for a course | Biblioteka mediów kursu |

- [ ] **Step 1: Rename the builder image references**

In `docs/help/course-admin/builder.md`, change `builder-tree.png` → `builder-tree.en.png`. In `builder.pl.md`, add/point the image to `builder-tree.pl.png` (with the PL alt above).

- [ ] **Step 2: Delete the old builder image**

```bash
git rm core/static/core/img/help/builder-tree.png
```

- [ ] **Step 3: Update the builder test**

In `tests/test_help.py::test_builder_topic_embeds_existing_screenshot`, replace both occurrences of `builder-tree.png` with `builder-tree.en.png` (the rendered `src="/static/core/img/help/builder-tree.en.png"` assertion and the `finders.find("core/img/help/builder-tree.en.png")` call).

- [ ] **Step 4: Embed the remaining course-admin images**

For each row above, add the EN embed line to the `.md` and the PL embed line to the `.pl.md`, at a sensible spot (after the intro / relevant heading). Example for content-editors `.md`:

```markdown
![The lesson editor with content blocks](static:core/img/help/content-editor.en.png)
```

and its `.pl.md`:

```markdown
![Edytor lekcji z blokami treści](static:core/img/help/content-editor.pl.png)
```

- [ ] **Step 5: Verify these topics' refs resolve**

Run: `uv run pytest "tests/test_help.py::test_all_topics_static_refs_resolve" tests/test_help.py::test_builder_topic_embeds_existing_screenshot -v`
Expected: PASS (every referenced static path resolves; builder points at the renamed image).

- [ ] **Step 6: Commit**

```bash
git add docs/help/course-admin/ tests/test_help.py
git commit -m "docs(help): illustrate course-admin topics (EN+PL); rename builder image"
```

---

## Task 5: Teacher docs — embed shots (EN + PL)

**Files:**
- Modify: `docs/help/teacher/{analytics,drill-down,quiz-review,groups-collections,roster,gradebook-export,notes-tags}.md` + `.pl.md`

| Topic file | Image(s) | EN alt | PL alt |
|---|---|---|---|
| analytics | analytics-matrix | The analytics matrix of results | Macierz wyników analitycznych |
| drill-down | drill-down | A per-student results breakdown | Szczegółowe wyniki ucznia |
| quiz-review | review-queue | The quiz review queue | Kolejka sprawdzania quizów |
| quiz-review | review-submission | Reviewing a submitted answer | Sprawdzanie przesłanej odpowiedzi |
| groups-collections | groups | Your groups and collections | Twoje grupy i kolekcje |
| groups-collections | group-detail | A group's detail page | Strona szczegółów grupy |
| groups-collections | collection-detail | A collection's detail page | Strona szczegółów kolekcji |
| roster | roster | A group roster of students | Lista uczniów w grupie |
| gradebook-export | gradebook-export | The gradebook export controls | Opcje eksportu dziennika ocen |
| notes-tags | notes-hub | The tags & notes hub | Centrum tagów i notatek |
| notes-tags | my-tags | Your personal tags | Twoje osobiste tagi |

- [ ] **Step 1: Embed all teacher images**

For each row, add the EN line to the `.md` and the PL line to the `.pl.md`.

- [ ] **Step 2: Verify refs resolve**

Run: `uv run pytest "tests/test_help.py::test_all_topics_static_refs_resolve" -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add docs/help/teacher/
git commit -m "docs(help): illustrate teacher topics (EN+PL)"
```

---

## Task 6: Platform-admin docs — embed shots (EN + PL)

**Files:**
- Modify: `docs/help/platform-admin/{create-a-course,export-import,users-roles,invitations,branding-settings,sso,subjects,cohorts,integrations,notifications,first-run-wizard}.md` + `.pl.md`

| Topic file | Image(s) | EN alt | PL alt |
|---|---|---|---|
| create-a-course | course-list | The course list in Studio | Lista kursów w Studio |
| create-a-course | course-create | The new-course form | Formularz tworzenia kursu |
| export-import | import | The course import screen | Ekran importu kursu |
| users-roles | people | The people management table | Tabela zarządzania użytkownikami |
| invitations | invitations | The invitations screen | Ekran zaproszeń |
| branding-settings | branding | The branding settings tab | Zakładka ustawień wyglądu |
| sso | sso | The SSO (OIDC) settings tab | Zakładka ustawień SSO (OIDC) |
| subjects | subjects | The subjects list | Lista przedmiotów |
| cohorts | cohorts | The cohorts list | Lista roczników |
| integrations | integrations | The integrations settings tab | Zakładka ustawień integracji |
| notifications | notifications | The notifications settings tab | Zakładka ustawień powiadomień |
| first-run-wizard | wizard | The first-run setup wizard | Kreator pierwszego uruchomienia |

- [ ] **Step 1: Embed all platform-admin images**

For each row, add the EN line to the `.md` and the PL line to the `.pl.md`.

- [ ] **Step 2: Verify refs resolve**

Run: `uv run pytest "tests/test_help.py::test_all_topics_static_refs_resolve" -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add docs/help/platform-admin/
git commit -m "docs(help): illustrate platform-admin topics (EN+PL)"
```

---

## Task 7: Coverage gate — dual-locale, per-image, on-disk (supersede old tests)

**Files:**
- Modify: `tests/test_help.py`

**Interfaces:**
- Consumes: `core.help.TOPICS`, `core.help.render_markdown_doc`, `django.contrib.staticfiles.finders`.
- Produces: `test_every_topic_illustrated_both_locales` (replaces `test_all_topics_static_refs_resolve` and `test_builder_topic_embeds_existing_screenshot`).

- [ ] **Step 1: Remove the superseded tests**

In `tests/test_help.py`, delete `test_all_topics_static_refs_resolve` and `test_builder_topic_embeds_existing_screenshot`.

- [ ] **Step 2: Add the new gate**

```python
import re

import pytest
from django.contrib.staticfiles import finders

from core.help import TOPICS, render_markdown_doc

_IMG = re.compile(r'<img[^>]*\bsrc="static:([^"]+)"')


def _doc_images(rel_path):
    html = render_markdown_doc(rel_path, resolve_static=False)
    return _IMG.findall(html)


@pytest.mark.parametrize("topic", TOPICS, ids=lambda t: t.slug)
def test_every_topic_illustrated_both_locales(topic):
    for locale, suffix in (("en", ".en.png"), ("pl", ".pl.png")):
        if locale == "en":
            path = topic.path
        else:
            path = topic.path.removesuffix(".md") + ".pl.md"
            # Do NOT use localized_doc_path (falls back to EN if the .pl.md is absent).
            from core.help import DOCS_ROOT
            assert (DOCS_ROOT / path).exists(), f"missing PL doc: {path}"
        images = _doc_images(path)
        assert images, f"{path}: embeds no static: image"
        for rel in images:
            assert finders.find(rel) is not None, f"{path}: unresolved image {rel}"
            assert rel.endswith(suffix), (
                f"{path}: image {rel} lacks the {suffix} locale suffix"
            )
```

- [ ] **Step 3: Run it**

Run: `uv run pytest "tests/test_help.py::test_every_topic_illustrated_both_locales" -v`
Expected: PASS for all 23 topics (46 assertions of EN+PL coverage).

- [ ] **Step 4: Falsify the gate (prove it's not vacuous)**

Temporarily change one image reference in `docs/help/course-admin/builder.pl.md` from `builder-tree.pl.png` to `builder-tree.en.png`. Run the gate.
Expected: FAIL on the `.pl.png` locale-suffix assertion for the `builder` param.
Then revert the change and re-run — Expected: PASS. (This proves the gate catches a PL doc reusing an EN image.)

- [ ] **Step 5: Commit**

```bash
git add tests/test_help.py
git commit -m "test(help): dual-locale per-image on-disk coverage gate; drop superseded scans"
```

---

## Task 8: Final verification & DoD

**Files:** none (verification only; fix-forward into the relevant task's files if something fails).

- [ ] **Step 1: Regenerate all images from scratch (determinism check)**

Run: `uv run pytest tests/capture_help_screenshots.py::test_capture_help_screenshots`
Then: `git status --short core/static/core/img/help/`
Expected: no diff (a re-run under the frozen clock reproduces byte-stable-enough images; if a handful differ trivially, inspect — large diffs indicate non-determinism to fix).

- [ ] **Step 2: Full non-e2e suite**

Run: `uv run pytest -q`
Expected: PASS (≈3160+ tests). No regressions.

- [ ] **Step 3: Lint & format**

Run: `uv run ruff check` then `uv run ruff format --check`
Expected: clean.

- [ ] **Step 4: i18n negative check (no catalog churn)**

Run: `uv run python manage.py makemessages -l pl --no-obsolete` then `git status --short locale/`
Expected: no changes to `locale/pl/LC_MESSAGES/django.po` (this slice added no translatable strings). If it changed, a `{% trans %}`/gettext string sneaked in — revert it. Discard any incidental `.po` churn: `git checkout -- locale/`.

- [ ] **Step 5: DoD checklist**

Confirm: (1) all 23 topics have ≥1 committed EN+PL screenshot; (2) seed enriched + idempotent, all seed tests green; (3) harness runs green, tripwire clean, PL shots assert `lang="pl"`; (4) coverage gate green + proven falsifiable; (5) full suite + ruff green, no i18n churn; (6) `doc-page.css` untouched (`git diff --stat` shows no CSS), no product/access change in the diff.

- [ ] **Step 6: Final commit (if any verification fixups)**

```bash
git add -A
git commit -m "chore(help): slice-3 final verification fixups"
```

---

## Self-review notes (author)

- **Spec coverage:** every spec component maps to a task — harness (T3), capture urlconf + freeze (T1), seed enrichment incl. REVIEW/collection/note/tag/interactive/image/last_login/PA-state (T2), doc embeds all 23 both locales (T4-6), coverage gate incl. supersede + locale suffix + PL-exists (T7), regeneration + DoD (T8).
- **Spec deviations** are listed up front ("Corrections to the spec…") and grounded in code — plan-review should confirm each.
- **Known soft spots for plan-review/implementer to verify against source before running:** the `Institution` branding field name + singleton accessor (T2 S6); `pending_reviews_for` return shape (T2 S7); exact `wait_selector`/`clip_selector` values per surface (T3 S3 — correct against the templates cited in T4-6 tables if a shot fails); the per-shot `response`-listener add/remove idiom (T3 S1 note). These are localized and self-correcting at run time (a wrong selector fails that shot loudly).
