# In-app Role Manuals (`/help/`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an in-app, permission-gated, bilingual help system at `/help/` that serves role-specific user manuals (Platform Admin / Course Admin / Teacher) rendered from repo-authored markdown.

**Architecture:** Generalize slice-1's single-guide seed into a `core.help` module holding the shared markdown renderer plus a `Topic` registry. Two `@login_required` views (`help_index`, `help_topic`) render markdown into shared templates; a context processor drives a top-level "Help" nav link. Topics are gated by a representative marker permission per role; the index and sidebar show only what the viewer can act on.

**Tech Stack:** Django (server-rendered templates), `markdown` (already a dependency), pytest + pytest-django, factory_boy test helpers, gettext i18n (EN/PL), `uv` for tooling.

## Global Constraints

- **Audience:** staff only — Platform Admin, Course Admin, Teacher. Students are excluded (empty index, no nav link).
- **Gating perms (verbatim from spec, verified against `institution/roles.py`):** Course Admin topics → `grouping.change_group`; Teacher topics → `grouping.view_collection`; PA topics per-topic → `courses.add_course` (create-a-course, export-import), `accounts.view_user` (users-roles, invitations), `institution.change_institution` (branding-settings, sso, first-run-wizard, notifications, integrations), `courses.change_subject` (subjects), `grouping.change_cohort` (cohorts). **Never** use `courses.change_course` as a marker (PA-only).
- **404 not 403** on unknown slug or missing marker perm — never reveal a topic's existence.
- **Registry ↔ file:** a `Topic` is in `TOPICS` only once its English `.md` file exists. EN mandatory, `.pl.md` optional (falls back to EN).
- **URLs reverse via the `core:` namespace** (`core:help_index`, `core:help_topic`).
- **Slugs are flat and globally unique**; duplicates `raise ValueError` at import (not `assert`, which `-O` strips).
- **Never hardcode test passwords** — use `tests.factories.TEST_PASSWORD` (via the existing helpers).
- **i18n:** UI chrome uses `gettext_lazy` / `{% trans %}`; markdown content lives in `.pl.md` siblings, not gettext. Clear `makemessages` fuzzy flags.
- **DoD runs BOTH** `uv run ruff check .` AND `uv run ruff format --check .`, plus full `uv run pytest`, i18n catalog tests, and `collectstatic` before visual QA.
- **Tooling:** bash `ruff`/`pytest`/`python` are NOT on PATH — always `uv run <tool>`.

---

## File Structure

**New:**
- `core/help.py` — shared renderer (`render_markdown_doc`, `DOCS_ROOT`), `localized_doc_path`, `Topic` dataclass, `TOPICS` registry, `ROLE_GROUP_ORDER`, `ROLE_FOLDER`, `get_topic`, `topics_for`, `user_has_any_help`.
- `core/views_help.py` — `help_index`, `help_topic`.
- `templates/help/index.html`, `templates/help/doc.html`.
- `core/static/core/css/doc-page.css` — shared doc/breadcrumb/sidebar/index styling (extracted from `webhook_guide.html`).
- `docs/help/<role>/<slug>.md` + `.pl.md` per topic.
- `tests/test_help.py` — all help-system tests (incl. relocated renderer tests).

**Modified:**
- `integrations/docs.py` — shim: re-export `render_markdown_doc` + `DOCS_ROOT` from `core.help`.
- `core/urls.py` — two routes.
- `core/context_processors.py` — `help_availability` processor.
- `config/settings/base.py` — register the processor.
- `templates/base.html` — "Help" nav link.
- `templates/integrations/webhook_guide.html` — link the shared CSS, drop inline `<style>`.
- `tests/factories.py` — `make_ca`, `make_teacher`, `make_student` (+ `_make_role` DRY helper; refactor `make_pa` onto it).
- `integrations/tests/test_docs.py` — deleted (renderer tests move to `tests/test_help.py`).
- PL locale catalog (`locale/pl/LC_MESSAGES/django.po`).

---

## Task 1: Relocate the markdown renderer to `core.help`

Pure refactor — no behavior change. Moves `render_markdown_doc` + `DOCS_ROOT` from `integrations/docs.py` into the help system's home, leaving a re-export shim so every existing importer keeps working.

**Files:**
- Create: `core/help.py`
- Modify: `integrations/docs.py`
- Create: `tests/test_help.py`
- Delete: `integrations/tests/test_docs.py`

**Interfaces:**
- Produces: `core.help.render_markdown_doc(rel_path) -> str`, `core.help.DOCS_ROOT: Path`.
- Consumes: nothing new.

- [ ] **Step 1: Move the renderer tests into `tests/test_help.py` (monkeypatching `core.help`)**

Create `tests/test_help.py`:

```python
import pytest

from core import help as core_help


def test_renders_fenced_code_and_tables(tmp_path, monkeypatch):
    doc = tmp_path / "sample.md"
    doc.write_text(
        "# Title\n\n```python\nx = 1\n```\n\n| A | B |\n|---|---|\n| 1 | 2 |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(core_help, "DOCS_ROOT", tmp_path)
    html = core_help.render_markdown_doc("sample.md")
    assert "<pre>" in html and "<code" in html
    assert "<table>" in html and "<th>A</th>" in html


def test_missing_file_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(core_help, "DOCS_ROOT", tmp_path)
    with pytest.raises(FileNotFoundError):
        core_help.render_markdown_doc("nope.md")
```

- [ ] **Step 2: Run the tests to confirm they fail (module not yet present)**

Run: `uv run pytest tests/test_help.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.help'` (or `AttributeError`).

- [ ] **Step 3: Create `core/help.py` with the moved renderer**

```python
"""In-app help system: trusted-markdown renderer + role-aware topic registry.

Content is repo-authored (fixed paths only), never user input, so the renderer
applies no sanitization. A missing file is a packaging/deploy bug — fail loud."""

from pathlib import Path

import markdown

# core/help.py -> parent is the app dir; its parent is the repo root, which
# holds docs/.
DOCS_ROOT = Path(__file__).resolve().parent.parent / "docs"


def render_markdown_doc(rel_path):
    text = (DOCS_ROOT / rel_path).read_text(encoding="utf-8")
    return markdown.markdown(text, extensions=["fenced_code", "tables"])
```

- [ ] **Step 4: Replace `integrations/docs.py` with a re-export shim**

```python
"""Backwards-compatible shim. The trusted-markdown renderer moved to core.help
(the shared home for the in-app help system). Both names are re-exported so
existing integrations imports keep resolving:
  - integrations/views.py imports render_markdown_doc
  - integrations/tests/test_guide_content.py imports DOCS_ROOT
Tests that need to redirect the docs root must monkeypatch core.help.DOCS_ROOT
(this module only re-binds the name once, at import)."""

from core.help import DOCS_ROOT  # noqa: F401
from core.help import render_markdown_doc  # noqa: F401
```

- [ ] **Step 5: Delete the old renderer test file**

```bash
git rm integrations/tests/test_docs.py
```

- [ ] **Step 6: Run help + integrations suites**

Run: `uv run pytest tests/test_help.py integrations/tests/ -v`
Expected: PASS — new renderer tests pass; `test_guide_content.py` and `test_guide_view.py` still pass (import `DOCS_ROOT` / `render_markdown_doc` via the shim).

- [ ] **Step 7: Commit**

```bash
git add core/help.py integrations/docs.py tests/test_help.py
git commit -m "refactor(help): relocate markdown renderer to core.help with re-export shim"
```

---

## Task 2: Role test helpers (`make_ca`, `make_teacher`, `make_student`)

Adds the CA/Teacher/Student login helpers the gating tests need. They mirror `make_pa` — crucially calling `seed_roles()` so the role Group carries its permissions (without it, `has_perm` is always False and gating tests silently pass on empty).

**Files:**
- Modify: `tests/factories.py`
- Modify: `tests/test_help.py`

**Interfaces:**
- Produces: `make_ca(client, username="ca")`, `make_teacher(client, username="teacher")`, `make_student(client, username="student")` — each returns a logged-in `User` with the role Group and cleared perm caches.
- Consumes: existing `make_login`, `seed_roles`, `TEST_PASSWORD`.

- [ ] **Step 1: Write failing tests for the helpers**

Append to `tests/test_help.py`:

```python
import pytest

from tests.factories import make_ca, make_student, make_teacher


@pytest.mark.django_db
def test_make_ca_holds_ca_marker(client):
    user = make_ca(client)
    assert user.has_perm("grouping.change_group")
    assert not user.has_perm("courses.change_course")  # CA is NOT a PA


@pytest.mark.django_db
def test_make_teacher_holds_teacher_marker(client):
    user = make_teacher(client)
    assert user.has_perm("grouping.view_collection")
    assert not user.has_perm("grouping.change_group")  # Teacher is not a CA


@pytest.mark.django_db
def test_make_student_holds_no_markers(client):
    user = make_student(client)
    assert not user.has_perm("grouping.change_group")
    assert not user.has_perm("grouping.view_collection")
    assert not user.has_perm("accounts.view_user")
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/test_help.py -k "make_" -v`
Expected: FAIL — `ImportError: cannot import name 'make_ca'`.

- [ ] **Step 3: Add a shared `_make_role` helper and the three helpers; refactor `make_pa` onto it**

In `tests/factories.py`, add `COURSE_ADMIN`, `STUDENT`, `TEACHER` to the `institution.roles` imports:

```python
from institution.roles import COURSE_ADMIN
from institution.roles import PLATFORM_ADMIN
from institution.roles import STUDENT
from institution.roles import TEACHER
from institution.roles import seed_roles
```

Replace the existing `make_pa` with the shared helper plus role-specific wrappers:

```python
def _make_role(client, role_name, username):
    """Log in a user carrying `role_name`'s permission Group.

    Views load request.user fresh from the session, so they always see the group.
    For the returned in-memory object, drop cached perm sets so a direct
    `user.has_perm(...)` in a test reflects the just-added group."""
    seed_roles()
    user = make_login(client, username)
    user.groups.add(AuthGroup.objects.get(name=role_name))
    for attr in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
        user.__dict__.pop(attr, None)
    return user


def make_pa(client, username="pa"):
    """Log in a Platform Admin (group holds courses.* + institution.* perms)."""
    return _make_role(client, PLATFORM_ADMIN, username)


def make_ca(client, username="ca"):
    """Log in a Course Admin (holds grouping.change_group, not courses.change_course)."""
    return _make_role(client, COURSE_ADMIN, username)


def make_teacher(client, username="teacher"):
    """Log in a Teacher (holds grouping.view_collection)."""
    return _make_role(client, TEACHER, username)


def make_student(client, username="student"):
    """Log in a plain Student (holds no staff marker perms)."""
    return _make_role(client, STUDENT, username)
```

- [ ] **Step 4: Run the helper tests**

Run: `uv run pytest tests/test_help.py -k "make_" -v`
Expected: PASS.

- [ ] **Step 5: Confirm `make_pa` refactor didn't regress existing callers**

Run: `uv run pytest tests/ integrations/tests/ grouping/ -q`
Expected: PASS (behavior identical; `make_pa` now delegates).

- [ ] **Step 6: Commit**

```bash
git add tests/factories.py tests/test_help.py
git commit -m "test(help): add make_ca/make_teacher/make_student role login helpers"
```

---

## Task 3: Topic registry + invariant tests + three seed topics

Introduces the `Topic` dataclass and a `TOPICS` registry seeded with one real topic per role (builder / analytics / users-roles), each with EN + PL markdown, plus the import-time slug-uniqueness guard and the parametrized invariant tests.

**Files:**
- Modify: `core/help.py`
- Create: `docs/help/course-admin/builder.md`, `docs/help/course-admin/builder.pl.md`
- Create: `docs/help/teacher/analytics.md`, `docs/help/teacher/analytics.pl.md`
- Create: `docs/help/platform-admin/users-roles.md`, `docs/help/platform-admin/users-roles.pl.md`
- Modify: `tests/test_help.py`

**Interfaces:**
- Produces: `Topic(slug, role, perm, title, path)`; `TOPICS: list[Topic]`; `ROLE_GROUP_ORDER: list[str]`; `ROLE_FOLDER: dict[str, str]`; `get_topic(slug) -> Topic | None`.
- Consumes: `institution.roles` constants + `ROLE_LABELS`.

- [ ] **Step 1: Write failing invariant tests**

Append to `tests/test_help.py`:

```python
from django.contrib.auth.models import Permission

from core.help import ROLE_FOLDER, TOPICS, get_topic


def test_slugs_are_globally_unique():
    slugs = [t.slug for t in TOPICS]
    assert len(set(slugs)) == len(slugs)


@pytest.mark.parametrize("topic", TOPICS, ids=lambda t: t.slug)
def test_topic_folder_matches_role(topic):
    assert topic.path.startswith(ROLE_FOLDER[topic.role]), topic.slug


@pytest.mark.parametrize("topic", TOPICS, ids=lambda t: t.slug)
def test_topic_english_file_exists_and_renders(topic):
    from core import help as core_help

    path = core_help.DOCS_ROOT / topic.path
    assert path.exists(), f"missing EN file for {topic.slug}: {topic.path}"
    html = core_help.render_markdown_doc(topic.path)
    assert html.strip()


@pytest.mark.parametrize("topic", TOPICS, ids=lambda t: t.slug)
def test_topic_polish_file_renders_if_present(topic):
    from core import help as core_help

    pl_rel = topic.path.removesuffix(".md") + ".pl.md"
    if (core_help.DOCS_ROOT / pl_rel).exists():
        assert core_help.render_markdown_doc(pl_rel).strip()


@pytest.mark.django_db
@pytest.mark.parametrize("topic", TOPICS, ids=lambda t: t.slug)
def test_topic_perm_is_real(topic):
    app_label, codename = topic.perm.split(".")
    assert Permission.objects.filter(
        content_type__app_label=app_label, codename=codename
    ).exists(), topic.perm


def test_get_topic_returns_none_for_unknown():
    assert get_topic("does-not-exist") is None
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/test_help.py -k "topic or slug" -v`
Expected: FAIL — `ImportError: cannot import name 'TOPICS'`.

- [ ] **Step 3: Add the registry to `core/help.py`**

Add the imports and registry below the renderer:

```python
from dataclasses import dataclass

from institution.roles import COURSE_ADMIN
from institution.roles import PLATFORM_ADMIN
from institution.roles import ROLE_LABELS
from institution.roles import TEACHER
from django.utils.translation import gettext_lazy as _


@dataclass(frozen=True)
class Topic:
    slug: str          # globally unique URL segment (e.g. "builder")
    role: str          # storage constant from institution.roles (grouping key)
    perm: str          # representative marker permission gating visibility
    title: object      # gettext_lazy display title
    path: str          # base markdown rel path, e.g. "help/course-admin/builder.md"


# Fixed display order of role groups on the index/sidebar (spec §Components).
ROLE_GROUP_ORDER = [PLATFORM_ADMIN, COURSE_ADMIN, TEACHER]

# The docs/ folder each role's topics live under (folder<->role invariant).
ROLE_FOLDER = {
    PLATFORM_ADMIN: "help/platform-admin/",
    COURSE_ADMIN: "help/course-admin/",
    TEACHER: "help/teacher/",
}

# Registry. A Topic is listed ONLY once its English .md file exists (unwritten
# topics are simply absent — that is the scaffold-remainder contract). Marker
# perms per the spec's gating table.
TOPICS = [
    Topic(
        "users-roles", PLATFORM_ADMIN, "accounts.view_user",
        _("Users & roles"), "help/platform-admin/users-roles.md",
    ),
    Topic(
        "builder", COURSE_ADMIN, "grouping.change_group",
        _("Building a course"), "help/course-admin/builder.md",
    ),
    Topic(
        "analytics", TEACHER, "grouping.view_collection",
        _("The analytics matrix"), "help/teacher/analytics.md",
    ),
]

# Fail loud at import on a duplicate slug. Explicit raise (NOT assert, which
# `python -O` strips) so an optimized deploy still refuses to boot on drift.
_slugs = [t.slug for t in TOPICS]
if len(set(_slugs)) != len(_slugs):
    raise ValueError(f"Duplicate help topic slug(s) in TOPICS: {_slugs}")

_BY_SLUG = {t.slug: t for t in TOPICS}


def get_topic(slug):
    return _BY_SLUG.get(slug)
```

- [ ] **Step 4: Write the three seed markdown files (EN + PL)**

Write substantive (not placeholder) manual prose. `docs/help/course-admin/builder.md`:

```markdown
# Building a course

The **course builder** is where you shape a course's structure and fill it with
lessons and quizzes. Open it from **Manage → your course → Builder**.

## Structure presets

Each course uses one of four structure presets, chosen in the builder legend:

- **Flat** — a single flat list of units, no grouping.
- **Chapters** — units grouped into chapters.
- **Parts** — chapters grouped into parts.
- **Full** — parts → chapters → sections → units, the deepest layout.

Pick the shallowest preset that fits your material; you can deepen it later and
existing units are preserved.

## Adding units

Use **Add unit** to create a *lesson* (content pages) or a *quiz* (assessed
questions). Drag units to reorder them; the outline on the left mirrors what
students see.

## Next steps

- [Content editors](content-editors) — building lesson pages.
- [Quiz editors](quiz-editors) — authoring questions.
```

`docs/help/course-admin/builder.pl.md` — the same content in Polish (headings, prose, and the cross-links translated; slugs in links stay verbatim, e.g. `(content-editors)`). Write a genuine Polish translation; do not leave English text.

Write `docs/help/teacher/analytics.md` + `.pl.md` (the analytics matrix: rows = students, columns = course structure, colour bands, switching progress/results) and `docs/help/platform-admin/users-roles.md` + `.pl.md` (the People page: adding users, assigning the four roles, deactivating accounts) in the same substantive, bilingual style.

- [ ] **Step 5: Run the invariant tests**

Run: `uv run pytest tests/test_help.py -k "topic or slug or get_topic" -v`
Expected: PASS — all three seed topics have EN+PL files that render, folders match roles, perms resolve.

- [ ] **Step 6: Commit**

```bash
git add core/help.py docs/help/ tests/test_help.py
git commit -m "feat(help): topic registry + invariants + three seed manuals (EN/PL)"
```

---

## Task 4: `localized_doc_path` language resolution

The pure function that picks the `.pl.md` sibling when present and falls back to English — with the exact rule that avoids the `Path.stem` directory-dropping trap and the `None`-language crash.

**Files:**
- Modify: `core/help.py`
- Modify: `tests/test_help.py`

**Interfaces:**
- Produces: `localized_doc_path(base: str, lang: str | None) -> str`.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_help.py`:

```python
from core.help import localized_doc_path


def test_localized_path_english_returns_base():
    assert localized_doc_path("help/teacher/analytics.md", "en") == (
        "help/teacher/analytics.md"
    )


def test_localized_path_none_lang_returns_base():
    # translation.get_language() can return None; must not raise.
    assert localized_doc_path("help/teacher/analytics.md", None) == (
        "help/teacher/analytics.md"
    )


def test_localized_path_pl_returns_sibling_when_present():
    # Seed topic analytics ships a .pl.md, so PL resolves to it (dir preserved).
    assert localized_doc_path("help/teacher/analytics.md", "pl") == (
        "help/teacher/analytics.pl.md"
    )


def test_localized_path_pl_falls_back_when_absent(tmp_path, monkeypatch):
    from core import help as core_help

    (tmp_path / "help").mkdir()
    (tmp_path / "help" / "x.md").write_text("# x", encoding="utf-8")
    monkeypatch.setattr(core_help, "DOCS_ROOT", tmp_path)
    # No help/x.pl.md on disk -> fall back to the English base.
    assert core_help.localized_doc_path("help/x.md", "pl") == "help/x.md"


def test_localized_path_normalizes_regional_code():
    assert localized_doc_path("help/teacher/analytics.md", "pl-PL") == (
        "help/teacher/analytics.pl.md"
    )
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/test_help.py -k "localized" -v`
Expected: FAIL — `ImportError: cannot import name 'localized_doc_path'`.

- [ ] **Step 3: Implement `localized_doc_path`**

Add to `core/help.py` (below `render_markdown_doc`):

```python
def localized_doc_path(base, lang):
    """Return the localized markdown path for `base` under language `lang`.

    Coalesces a falsy lang to English (get_language() can return None), normalizes
    a regional code (pl-PL -> pl), and — if the code is not English — returns the
    `<name>.<code>.md` sibling iff it exists on disk, else the English base.
    Uses removesuffix/slicing (NOT Path.stem, which would drop the help/<role>/
    directory prefix and make the existence check always miss)."""
    code = (lang or "en").split("-")[0]
    if code == "en":
        return base
    candidate = base.removesuffix(".md") + f".{code}.md"
    if (DOCS_ROOT / candidate).exists():
        return candidate
    return base
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_help.py -k "localized" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/help.py tests/test_help.py
git commit -m "feat(help): localized_doc_path with EN fallback and safe lang coalescing"
```

---

## Task 5: `topics_for` grouping + `user_has_any_help`

The perm-filtered, fixed-order grouping the index/sidebar/nav all consume. Labels are resolved to `ROLE_LABELS` here in Python (Django templates can't do variable-key dict lookups).

**Files:**
- Modify: `core/help.py`
- Modify: `tests/test_help.py`

**Interfaces:**
- Produces: `topics_for(user) -> list[dict]` where each dict is `{"role": <const>, "label": <lazy str>, "topics": [Topic, ...]}`, groups in `ROLE_GROUP_ORDER`, empty groups omitted; `user_has_any_help(user) -> bool`.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_help.py`:

```python
from institution.roles import COURSE_ADMIN, PLATFORM_ADMIN, TEACHER
from core.help import topics_for, user_has_any_help
from tests.factories import make_pa


def _slugs_by_role(groups):
    return {g["role"]: [t.slug for t in g["topics"]] for g in groups}


@pytest.mark.django_db
def test_topics_for_pa_sees_all_three_groups(client):
    user = make_pa(client)
    groups = topics_for(user)
    # Fixed order: PA, CA, Teacher.
    assert [g["role"] for g in groups] == [PLATFORM_ADMIN, COURSE_ADMIN, TEACHER]
    by_role = _slugs_by_role(groups)
    assert "users-roles" in by_role[PLATFORM_ADMIN]
    assert "builder" in by_role[COURSE_ADMIN]
    assert "analytics" in by_role[TEACHER]


@pytest.mark.django_db
def test_topics_for_teacher_sees_only_teacher(client):
    groups = topics_for(make_teacher(client))
    assert [g["role"] for g in groups] == [TEACHER]
    assert "analytics" in _slugs_by_role(groups)[TEACHER]


@pytest.mark.django_db
def test_topics_for_ca_sees_ca_and_teacher(client):
    groups = topics_for(make_ca(client))
    assert set(g["role"] for g in groups) == {COURSE_ADMIN, TEACHER}


@pytest.mark.django_db
def test_topics_for_student_sees_nothing(client):
    assert topics_for(make_student(client)) == []


@pytest.mark.django_db
def test_group_label_is_translated_string(client):
    from institution.roles import ROLE_LABELS

    groups = topics_for(make_pa(client))
    for g in groups:
        assert g["label"] == ROLE_LABELS[g["role"]]


@pytest.mark.django_db
def test_user_has_any_help(client):
    assert user_has_any_help(make_pa(client))
    assert user_has_any_help(make_teacher(client))
    assert not user_has_any_help(make_student(client))
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/test_help.py -k "topics_for or has_any_help or group_label" -v`
Expected: FAIL — `ImportError: cannot import name 'topics_for'`.

- [ ] **Step 3: Implement `topics_for` and `user_has_any_help`**

Add to `core/help.py`:

```python
def topics_for(user):
    """Perm-filtered, fixed-order role groups for the index and sidebar.

    Returns [{"role": <const>, "label": ROLE_LABELS[<const>], "topics": [...]}, ...]
    for each role in ROLE_GROUP_ORDER that has at least one topic the user may see.
    The label is resolved here (not in the template — Django can't do a variable-key
    dict lookup); topics keep registry order."""
    groups = []
    for role in ROLE_GROUP_ORDER:
        topics = [t for t in TOPICS if t.role == role and user.has_perm(t.perm)]
        if topics:
            groups.append(
                {"role": role, "label": ROLE_LABELS[role], "topics": topics}
            )
    return groups


def user_has_any_help(user):
    """True iff `user` can see at least one topic (drives the nav flag)."""
    if not getattr(user, "is_authenticated", False):
        return False
    return any(user.has_perm(t.perm) for t in TOPICS)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_help.py -k "topics_for or has_any_help or group_label" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/help.py tests/test_help.py
git commit -m "feat(help): topics_for grouping + user_has_any_help nav flag"
```

---

## Task 6: Views, URLs, templates, and shared CSS

The rendering slice — `help_index` + `help_topic`, their routes, the two templates, and the extracted shared stylesheet (also repointing `webhook_guide.html`). Tested end-to-end via the client.

**Files:**
- Create: `core/views_help.py`
- Modify: `core/urls.py`
- Create: `templates/help/index.html`, `templates/help/doc.html`
- Create: `core/static/core/css/doc-page.css`
- Modify: `templates/integrations/webhook_guide.html`
- Modify: `tests/test_help.py`

**Interfaces:**
- Consumes: `get_topic`, `topics_for`, `localized_doc_path`, `render_markdown_doc`.
- Produces: URL names `core:help_index`, `core:help_topic`.

- [ ] **Step 1: Write failing view tests**

Append to `tests/test_help.py`:

```python
from django.urls import reverse


@pytest.mark.django_db
def test_index_lists_permitted_topics(client):
    make_pa(client)
    resp = client.get(reverse("core:help_index"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Users &amp; roles" in body or "Users & roles" in body


@pytest.mark.django_db
def test_index_empty_state_for_student(client):
    make_student(client)
    resp = client.get(reverse("core:help_index"))
    assert resp.status_code == 200
    assert "No manuals are available" in resp.content.decode()


@pytest.mark.django_db
def test_topic_renders_for_permitted_user(client):
    make_ca(client)
    resp = client.get(reverse("core:help_topic", args=["builder"]))
    assert resp.status_code == 200
    assert "Building a course" in resp.content.decode()


@pytest.mark.django_db
def test_topic_404_for_unknown_slug(client):
    make_pa(client)
    resp = client.get(reverse("core:help_topic", args=["nope"]))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_topic_404_when_missing_marker_perm(client):
    make_teacher(client)  # no grouping.change_group
    resp = client.get(reverse("core:help_topic", args=["builder"]))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_topic_requires_login(client):
    resp = client.get(reverse("core:help_topic", args=["builder"]))
    assert resp.status_code == 302  # @login_required redirect


@pytest.mark.django_db
def test_topic_renders_polish_via_session(client):
    make_teacher(client)
    session = client.session
    session["_language"] = "pl"
    session.save()
    resp = client.get(reverse("core:help_topic", args=["analytics"]))
    assert resp.status_code == 200
    # A distinctive Polish string that appears only in analytics.pl.md.
    assert "uczni" in resp.content.decode().lower()
```

Note: adjust the `"uczni"` assertion to a real substring of your `analytics.pl.md` (e.g. part of "uczniów"). The point is: a string present in PL and absent in EN.

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/test_help.py -k "index or topic_" -v`
Expected: FAIL — `NoReverseMatch` for `core:help_index`.

- [ ] **Step 3: Create the views**

`core/views_help.py`:

```python
"""Staff-facing help pages rendered from trusted repo markdown (core.help)."""

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render
from django.utils import translation

from core.help import get_topic
from core.help import localized_doc_path
from core.help import render_markdown_doc
from core.help import topics_for


@login_required
def help_index(request):
    return render(request, "help/index.html", {"groups": topics_for(request.user)})


@login_required
def help_topic(request, slug):
    topic = get_topic(slug)
    # 404 (not 403) on unknown slug OR missing marker perm — never reveal existence.
    if topic is None or not request.user.has_perm(topic.perm):
        raise Http404("No such help topic")
    rel_path = localized_doc_path(topic.path, translation.get_language())
    html = render_markdown_doc(rel_path)
    # Sidebar = the perm-filtered sibling list for this topic's role group.
    groups = topics_for(request.user)
    siblings = next((g["topics"] for g in groups if g["role"] == topic.role), [])
    return render(
        request,
        "help/doc.html",
        {"content": html, "topic": topic, "siblings": siblings},
    )
```

- [ ] **Step 4: Add the routes**

In `core/urls.py`, add the import and two paths:

```python
from core import views_help
```

```python
    path("help/", views_help.help_index, name="help_index"),
    path("help/<slug:slug>/", views_help.help_topic, name="help_topic"),
```

- [ ] **Step 5: Create the shared stylesheet**

`core/static/core/css/doc-page.css` — extract the `.doc-page` rules currently inline in `webhook_guide.html` and add the new index/breadcrumb/sidebar classes:

```css
/* Shared styling for markdown doc pages: the SIS webhook guide and the /help/
   system (index + topic pages). Uses design tokens so light/dark both work. */
.doc-page { max-width: 52rem; margin: 0 auto; padding: 1rem 0 4rem; }
.doc-page h2 { margin-top: 2.25rem; border-bottom: 1px solid var(--border-default);
  padding-bottom: .25rem; }
.doc-page pre { background: var(--surface-2, rgba(127,127,127,.12));
  padding: 1rem; border-radius: .5rem; overflow-x: auto; }
.doc-page code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.doc-page table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
.doc-page th, .doc-page td { border: 1px solid var(--border-default);
  padding: .4rem .6rem; text-align: left; }

/* Index */
.help-index { max-width: 52rem; margin: 0 auto; padding: 1rem 0 4rem; }
.help-index__group { margin-top: 2rem; }
.help-index__list { list-style: none; padding: 0; margin: .5rem 0 0; }
.help-index__list li { margin: .35rem 0; }
.help-index__empty { color: var(--text-muted, #666); margin-top: 1.5rem; }

/* Topic layout: sidebar + article */
.doc-layout { display: flex; gap: 2rem; align-items: flex-start;
  max-width: 60rem; margin: 0 auto; }
.doc-sidebar { flex: 0 0 14rem; padding-top: 1rem; }
.doc-sidebar__back { display: inline-block; margin-bottom: 1rem; }
.doc-sidebar__list { list-style: none; padding: 0; margin: 0; }
.doc-sidebar__item { display: block; padding: .3rem .5rem; border-radius: .375rem; }
.doc-sidebar__item.is-active { background: var(--surface-2, rgba(127,127,127,.12));
  font-weight: 600; }
.doc-breadcrumb { color: var(--text-muted, #666); margin-bottom: 1rem; }
.doc-layout .doc-page { margin: 0; }

@media (max-width: 48rem) {
  .doc-layout { flex-direction: column; }
  .doc-sidebar { flex-basis: auto; }
}
```

- [ ] **Step 6: Create the templates**

`templates/help/index.html`:

```html
{% extends "base.html" %}
{% load i18n static %}
{% block head_title %}{% trans "Help" %} · libli{% endblock %}
{% block extra_css %}<link rel="stylesheet" href="{% static 'core/css/doc-page.css' %}">{% endblock %}
{% block content %}
<div class="help-index">
  <h1>{% trans "Help" %}</h1>
  {% for group in groups %}
    <section class="help-index__group">
      <h2>{{ group.label }}</h2>
      <ul class="help-index__list">
        {% for topic in group.topics %}
          <li><a href="{% url 'core:help_topic' topic.slug %}">{{ topic.title }}</a></li>
        {% endfor %}
      </ul>
    </section>
  {% empty %}
    <p class="help-index__empty">{% trans "No manuals are available for your account." %}</p>
  {% endfor %}
</div>
{% endblock %}
```

`templates/help/doc.html`:

```html
{% extends "base.html" %}
{% load i18n static %}
{% block head_title %}{{ topic.title }} · libli{% endblock %}
{% block extra_css %}<link rel="stylesheet" href="{% static 'core/css/doc-page.css' %}">{% endblock %}
{% block content %}
<div class="doc-layout">
  <aside class="doc-sidebar">
    <a class="doc-sidebar__back" href="{% url 'core:help_index' %}">{% trans "← All help" %}</a>
    <ul class="doc-sidebar__list">
      {% for sib in siblings %}
        <li>
          <a class="doc-sidebar__item{% if sib.slug == topic.slug %} is-active{% endif %}"
             {% if sib.slug == topic.slug %}aria-current="page"{% endif %}
             href="{% url 'core:help_topic' sib.slug %}">{{ sib.title }}</a>
        </li>
      {% endfor %}
    </ul>
  </aside>
  <article class="doc-page">
    <nav class="doc-breadcrumb"><a href="{% url 'core:help_index' %}">{% trans "Help" %}</a> / {{ topic.title }}</nav>
    {{ content|safe }}
  </article>
</div>
{% endblock %}
```

- [ ] **Step 7: Repoint `webhook_guide.html` to the shared CSS**

Replace the whole file with (drops the inline `<style>` block):

```html
{% extends "base.html" %}
{% load i18n static %}
{% block head_title %}{% trans "SIS webhook integration guide" %} · libli{% endblock %}
{% block extra_css %}<link rel="stylesheet" href="{% static 'core/css/doc-page.css' %}">{% endblock %}
{% block content %}
<article class="doc-page">{{ content|safe }}</article>
{% endblock %}
```

- [ ] **Step 8: Run the view tests + the webhook guide view test**

Run: `uv run pytest tests/test_help.py integrations/tests/test_guide_view.py -v`
Expected: PASS — help pages render; the webhook guide still renders (now via shared CSS).

- [ ] **Step 9: Commit**

```bash
git add core/views_help.py core/urls.py templates/help/ core/static/core/css/doc-page.css templates/integrations/webhook_guide.html tests/test_help.py
git commit -m "feat(help): index + topic views, templates, shared doc-page CSS"
```

---

## Task 7: Nav link via context processor

Wires the top-level "Help" nav link, driven by a registry-derived `help_available` flag so it never diverges from what the index would show.

**Files:**
- Modify: `core/context_processors.py`
- Modify: `config/settings/base.py`
- Modify: `templates/base.html`
- Modify: `tests/test_help.py`

**Interfaces:**
- Produces: template context var `help_available: bool`.
- Consumes: `core.help.user_has_any_help`.

- [ ] **Step 1: Write failing nav tests**

Append to `tests/test_help.py`:

```python
@pytest.mark.django_db
def test_nav_help_link_present_for_staff(client):
    make_teacher(client)
    resp = client.get(reverse("courses:my_courses"))
    assert reverse("core:help_index") in resp.content.decode()


@pytest.mark.django_db
def test_nav_help_link_absent_for_student(client):
    make_student(client)
    resp = client.get(reverse("courses:my_courses"))
    assert reverse("core:help_index") not in resp.content.decode()
```

Note: if `courses:my_courses` is not the right landing URL for a logged-in user in this codebase, use the project's authenticated home route (the same one other nav tests hit, e.g. in `integrations/tests/test_guide_view.py`).

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/test_help.py -k "nav_help" -v`
Expected: FAIL — link absent (context var not yet provided / nav not added).

- [ ] **Step 3: Add the context processor**

Append to `core/context_processors.py`:

```python
def help_availability(request):
    """Expose `help_available` so base.html can show the Help nav link only when
    the user can see at least one manual (single source of truth with the index)."""
    from core.help import user_has_any_help

    user = getattr(request, "user", None)
    return {"help_available": user_has_any_help(user)}
```

- [ ] **Step 4: Register the processor**

In `config/settings/base.py`, add to the `context_processors` list (beside the other `core.context_processors.*` entries):

```python
                "core.context_processors.help_availability",
```

- [ ] **Step 5: Add the nav link**

In `templates/base.html`, after the "My groups" block (the `{% if perms.grouping.view_collection or perms.grouping.view_group %}...{% endif %}` around line 95-97) and before the Admin dropdown comment, add:

```html
          {% if help_available %}
          <a class="app-nav__link" href="{% url 'core:help_index' %}">{% trans "Help" %}</a>
          {% endif %}
```

- [ ] **Step 6: Run the nav tests**

Run: `uv run pytest tests/test_help.py -k "nav_help" -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add core/context_processors.py config/settings/base.py templates/base.html tests/test_help.py
git commit -m "feat(help): top-level Help nav link via help_available context processor"
```

---

## Task 8: Course Admin content batch

Adds the remaining Course Admin topics (registry entries + EN/PL markdown). Content-writing task; the gate is the parametrized content-integrity/folder/perm tests already in `tests/test_help.py` staying green as topics are added.

**Files:**
- Modify: `core/help.py` (extend `TOPICS`)
- Create: `docs/help/course-admin/content-editors.md` + `.pl.md`
- Create: `docs/help/course-admin/quiz-editors.md` + `.pl.md`
- Create: `docs/help/course-admin/media-manager.md` + `.pl.md`

**Interfaces:**
- Produces: three new `Topic` entries (`content-editors`, `quiz-editors`, `media-manager`), all `role=COURSE_ADMIN`, `perm="grouping.change_group"`.

- [ ] **Step 1: Write the EN + PL markdown**

Write substantive bilingual manuals (mirroring Task 3's style and cross-link convention) for:
- `content-editors` — the lesson content editor and each block type (text, media, math, embeds, etc.).
- `quiz-editors` — the quiz editor and each question type (choice, fill-blank, short-text/numeric, drag-fill, match-pair, drag-to-image, extended-response).
- `media-manager` — uploading, browsing, and picking media assets.

Each file must be non-empty and render; the `.pl.md` must be a real Polish translation (link slugs verbatim).

- [ ] **Step 2: Register the topics**

Add to `TOPICS` in `core/help.py` (in the Course Admin section):

```python
    Topic(
        "content-editors", COURSE_ADMIN, "grouping.change_group",
        _("Content editors"), "help/course-admin/content-editors.md",
    ),
    Topic(
        "quiz-editors", COURSE_ADMIN, "grouping.change_group",
        _("Quiz editors"), "help/course-admin/quiz-editors.md",
    ),
    Topic(
        "media-manager", COURSE_ADMIN, "grouping.change_group",
        _("Media manager"), "help/course-admin/media-manager.md",
    ),
```

- [ ] **Step 3: Run the parametrized registry tests (now cover the new topics)**

Run: `uv run pytest tests/test_help.py -k "topic or topics_for" -v`
Expected: PASS — new topics have EN+PL files, correct folder/perm, and appear in the CA group.

- [ ] **Step 4: Commit**

```bash
git add core/help.py docs/help/course-admin/
git commit -m "docs(help): Course Admin manuals — content/quiz editors, media manager (EN/PL)"
```

---

## Task 9: Teacher content batch

Adds the remaining Teacher topics.

**Files:**
- Modify: `core/help.py`
- Create (EN + PL each): `docs/help/teacher/drill-down.md`, `quiz-review.md`, `groups-collections.md`, `roster.md`, `gradebook-export.md`, `notes-tags.md`

**Interfaces:**
- Produces: six new Teacher `Topic` entries, `perm="grouping.view_collection"`.

- [ ] **Step 1: Write the EN + PL markdown**

Substantive bilingual manuals for: `drill-down` (recursive column expand + per-student cherry-pick subsets), `quiz-review` (review queue + force-submit), `groups-collections` (groups, cohorts, collections), `roster` (cohort/name filters, adding students), `gradebook-export` (CSV/XLSX/print), `notes-tags` (personal notes + tags on units).

- [ ] **Step 2: Register the topics**

Add to `TOPICS` (Teacher section):

```python
    Topic("drill-down", TEACHER, "grouping.view_collection",
          _("Analytics drill-down"), "help/teacher/drill-down.md"),
    Topic("quiz-review", TEACHER, "grouping.view_collection",
          _("Quiz review"), "help/teacher/quiz-review.md"),
    Topic("groups-collections", TEACHER, "grouping.view_collection",
          _("Groups & collections"), "help/teacher/groups-collections.md"),
    Topic("roster", TEACHER, "grouping.view_collection",
          _("Roster management"), "help/teacher/roster.md"),
    Topic("gradebook-export", TEACHER, "grouping.view_collection",
          _("Gradebook export"), "help/teacher/gradebook-export.md"),
    Topic("notes-tags", TEACHER, "grouping.view_collection",
          _("Notes & tags"), "help/teacher/notes-tags.md"),
```

- [ ] **Step 3: Run the parametrized tests**

Run: `uv run pytest tests/test_help.py -k "topic or topics_for" -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add core/help.py docs/help/teacher/
git commit -m "docs(help): Teacher manuals — analytics, review, groups, roster, export, notes (EN/PL)"
```

---

## Task 10: Platform Admin content batch

Adds the remaining PA topics, including the `integrations` topic that links out to the existing `/integrations/webhook/` guide.

**Files:**
- Modify: `core/help.py`
- Create (EN + PL each): `docs/help/platform-admin/create-a-course.md`, `export-import.md`, `invitations.md`, `branding-settings.md`, `sso.md`, `subjects.md`, `cohorts.md`, `integrations.md`, `first-run-wizard.md`, `notifications.md`

**Interfaces:**
- Produces: ten new PA `Topic` entries with the per-topic perms from the Global Constraints.

- [ ] **Step 1: Write the EN + PL markdown**

Substantive bilingual manuals for each. The `integrations` topic gives a short overview and links to the receiver guide, e.g.:

```markdown
# Integrations (grade sync)

libli can push finalized quiz results to your school information system (SIS) or
e-register via a signed webhook. Configure the endpoint under **Admin →
Institution settings → Integrations**, then send a test event to verify your
receiver before enabling live delivery.

For the receiver contract (payload, headers, HMAC signature verification, retry
and idempotency semantics) see the dedicated **[SIS webhook guide](/integrations/webhook/)**.
```

Use a genuine Polish translation in `integrations.pl.md` (the `/integrations/webhook/` URL stays verbatim; that view already serves the Polish guide by UI language).

- [ ] **Step 2: Register the topics**

Add to `TOPICS` (PA section) with the correct per-topic perms:

```python
    Topic("create-a-course", PLATFORM_ADMIN, "courses.add_course",
          _("Creating a course"), "help/platform-admin/create-a-course.md"),
    Topic("export-import", PLATFORM_ADMIN, "courses.add_course",
          _("Course export & import"), "help/platform-admin/export-import.md"),
    Topic("invitations", PLATFORM_ADMIN, "accounts.view_user",
          _("Invitations"), "help/platform-admin/invitations.md"),
    Topic("branding-settings", PLATFORM_ADMIN, "institution.change_institution",
          _("Branding & settings"), "help/platform-admin/branding-settings.md"),
    Topic("sso", PLATFORM_ADMIN, "institution.change_institution",
          _("SSO (OIDC)"), "help/platform-admin/sso.md"),
    Topic("subjects", PLATFORM_ADMIN, "courses.change_subject",
          _("Subjects"), "help/platform-admin/subjects.md"),
    Topic("cohorts", PLATFORM_ADMIN, "grouping.change_cohort",
          _("Cohorts"), "help/platform-admin/cohorts.md"),
    Topic("integrations", PLATFORM_ADMIN, "institution.change_institution",
          _("Integrations"), "help/platform-admin/integrations.md"),
    Topic("first-run-wizard", PLATFORM_ADMIN, "institution.change_institution",
          _("First-run wizard"), "help/platform-admin/first-run-wizard.md"),
    Topic("notifications", PLATFORM_ADMIN, "institution.change_institution",
          _("Notifications"), "help/platform-admin/notifications.md"),
```

- [ ] **Step 3: Run the full help suite**

Run: `uv run pytest tests/test_help.py -v`
Expected: PASS — all topics have EN+PL, correct folder/perm; PA index now lists every PA topic; a PA sees all three groups fully populated.

- [ ] **Step 4: Commit**

```bash
git add core/help.py docs/help/platform-admin/
git commit -m "docs(help): Platform Admin manuals — users, settings, SSO, integrations, etc. (EN/PL)"
```

---

## Task 11: i18n catalog + full DoD gate

Extracts the new UI strings, writes their Polish translations, and runs the complete Definition-of-Done gate.

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po`

**Interfaces:** none (finalization).

- [ ] **Step 1: Extract messages**

Run: `uv run python manage.py makemessages -l pl`
This picks up the new `gettext_lazy` titles and `{% trans %}` chrome ("Help", "No manuals are available for your account.", "← All help", topic titles, etc.).

- [ ] **Step 2: Fix fuzzy matches and translate**

Open `locale/pl/LC_MESSAGES/django.po`. For every new msgid: **remove any `#, fuzzy` flag** (makemessages fuzzy-matches new short strings to unrelated old ones — a known gotcha) and write the correct Polish `msgstr`. Verify no new string is left with an empty or fuzzy translation.

- [ ] **Step 3: Compile and run the i18n catalog tests**

Run: `uv run python manage.py compilemessages -l pl`
Run: `uv run pytest -k "i18n or catalog or locale" -q`
Expected: PASS — no obsolete `#~` entries, no empty/fuzzy new strings.

- [ ] **Step 4: Run ruff (both check and format)**

Run: `uv run ruff check .`
Run: `uv run ruff format --check .`
Expected: both clean. If format reports files, run `uv run ruff format .` and re-stage.

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest -q`
Expected: PASS (full suite green).

- [ ] **Step 6: collectstatic + visual QA**

Run: `uv run python manage.py collectstatic --noinput`
Then visually verify (per the "verify UI with screenshots" norm) in **light and dark**:
- `/help/` index (as a PA — all three groups) and empty state (as a student).
- A topic page (`/help/builder/`) — breadcrumb, sidebar with active item, rendered markdown.
- The SIS webhook guide (`/integrations/webhook/`) — still styled via the shared CSS after losing its inline block.

- [ ] **Step 7: Commit**

```bash
git add locale/pl/LC_MESSAGES/django.po
git commit -m "i18n(help): Polish catalog for help system UI strings"
```

---

## Self-Review Notes (author checklist — already reconciled)

- **Spec coverage:** renderer relocation (T1), role helpers (T2), registry + invariants + seeds (T3), `localized_doc_path` (T4), `topics_for`/nav flag (T5), views/URLs/templates/CSS (T6), nav + context processor + settings (T7), content batches CA/Teacher/PA (T8–T10), i18n + DoD (T11). Every spec §Testing item maps to a step in T1–T7/T11; every §Content-inventory topic maps to T3/T8/T9/T10.
- **Scaffold-remainder fallback:** the system is fully working and green after T7 with three seed topics. Content tasks T8–T10 are independent; stopping after any of them leaves a green, shippable system with the remaining topics as follow-ups (they are simply absent from `TOPICS`).
- **Type consistency:** `Topic(slug, role, perm, title, path)`, `topics_for -> list[{"role","label","topics"}]`, `get_topic -> Topic|None`, `localized_doc_path(base, lang) -> str`, `user_has_any_help(user) -> bool` — used identically across tasks and templates.
- **PL-fallback** is proven at the `localized_doc_path` unit level (T4); the view inherits it. The bilingual view test (T6) uses option (a) — set session `_language` directly — so no `make_login` change is needed.
