# Author Live-View Links Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give an author three ways to reach the existing student-facing page of their course and units: a Studio "View" link, a "Last edited" card on the dashboard, and a "View live" link in the unit editor.

**Architecture:** Server-rendered Django only. `core.views.home` gains one query (`last_edited_unit`). `templates/core/home.html` gets the card and per-row "View" actions. `courses.views_manage._editor_page` gains a `can_view_live` flag rendered in the editor crumb. A small CSS addition in `core/static/core/css/app.css`. No models, no migrations, no JS.

**Tech Stack:** Django templates, pytest + pytest-django, BeautifulSoup (already used in tests), Playwright (`-m e2e`), gettext (`locale/pl`).

**Spec:** `docs/superpowers/specs/2026-10-16-author-live-view-links-design.md`. Read it in full before any task. Its Owner decisions D1–D3 and Calls C1–C7 are binding.

## Global Constraints

- Worktree: `C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/author-live-view-links`. Run every command there, and never touch the main checkout.
- Tools via uv: `uv run pytest …`, `uv run ruff check .`, `uv run ruff format .`, `uv run python manage.py …`. Never pass `-q` to pytest (addopts has it). e2e needs `-m e2e`.
- pytest-timeout is NOT installed: never pass `--timeout`; set the Bash tool timeout instead (up to 600000 ms).
- Start the test DB first: `docker compose -p libli-test -f docker-compose.test.yml up -d --wait`. One pytest run at a time, in the FOREGROUND with an explicit timeout. Never background pytest or wait on a notification.
- Test fixtures: `make_login` / `make_pa` / `make_teacher` / `make_verified_user` from `tests/factories.py`. Never `UserFactory` + `force_login`.
- Any dashboard GET by a `make_pa` user calls `core.services.mark_onboarded()` first. Every dashboard test asserts `status_code == 200`. Every negative assertion is paired with a positive one on the same response.
- Pin `ContentNode.updated` only via `ContentNode.objects.filter(pk=…).update(updated=…)` (it is `auto_now`).
- Dashboard links (card, Studio "View") have **no** `target`. Only the editor "View live" link is `target="_blank" rel="noopener"`.
- Titles on the dashboard go through `|strip_math_delimiters` (`{% load courses_extras %}`). No KaTeX on the dashboard.
- Live-page URL rule: `courses:quiz_unit` when `unit_type == ContentNode.UnitType.QUIZ`, else `courses:lesson_unit`.
- No changes to `courses/access.py`, `lesson_unit`, `quiz_unit`, `course_outline`, the builder, or any `updated` bump.
- Django `{# #}` comments are single-line only. Use `{% comment %}` for multi-line.
- Icons, if any: monochrome inline SVG with `currentColor`, never emoji.
- Falsify every new test: apply the named mutant by hand, see RED, then revert by hand (never `git checkout` the file). Read `git diff` to confirm the revert.
- Keep each task's test run narrow (`-k` / node ids). One branch-wide run, in Task 6 only.
- CSS edits: run every `tests/test_*css*.py` afterwards. `test_css_citations_are_durable.py` polices line citations in CSS comments, so cite selectors, not line numbers.
- Before every commit: `uv run ruff check .` and `uv run ruff format --check .`. Stage files by explicit path, never `git add -A`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **Error re-render of the editor.** After a failed rename (422), the "View live" link must still be there. Pinned in Task 3.
2. **Maths in titles.** A unit or course title with `\(…\)` must not show raw delimiters on the dashboard, including in the screen-reader-only course name. Pinned in Tasks 1 and 2.
3. **Long unbroken titles at 360px.** No horizontal page scroll. Pinned in Task 5 (e2e).
4. **Polish UI.** The Studio action must not render "Widok" (the noun already in the catalogue). Pinned in Task 1, translated in Task 4.
5. **Platform Admin who is not the owner.** Their "Last edited" card shows nothing of another author's, and the editor shows no link that would 403. Pinned in Tasks 2 and 3.

---

### Task 1: Studio "View" action and wrapping row titles

**Files:**
- Modify: `templates/core/home.html` (Teaching row title anchor, around lines 33-35; Studio list, around lines 48-52; the `{% load %}` line)
- Modify: `core/static/core/css/app.css` (after the `.dash-list .dash-row__action:focus-visible` rule)
- Test: `tests/test_dashboard_panels.py`

**Interfaces:**
- Produces: the class `dash-row__title` on the title `<a>` of every Teaching and Studio row. `{% load courses_extras %}` in `home.html`, which Task 2 relies on.

- [ ] **Step 1: Write the failing tests** in `tests/test_dashboard_panels.py`. Add a helper that parses the response with BeautifulSoup (`html.parser`) and returns the Studio section (`section[data-section="manage"]`).

```python
def test_studio_row_title_goes_to_builder_and_view_to_outline(client):
    owner = make_login(client, "studio_view")
    course = CourseFactory(title="Algebra", owner=owner)
    resp = client.get(reverse("home"))
    assert resp.status_code == 200
    row = _studio(resp).select_one("li.dash-row")
    title = row.select_one("a.dash-row__title")
    action = row.select_one("a.dash-row__action")
    assert title["href"] == reverse("courses:manage_builder", kwargs={"slug": course.slug})
    assert action["href"] == reverse("courses:course_outline", kwargs={"slug": course.slug})
    assert not action.has_attr("target") and not title.has_attr("target")
    assert len(row.select("a")) == 2
    assert client.get(action["href"]).status_code == 200

def test_studio_view_link_names_the_course_without_math_delimiters(client):
    owner = make_login(client, "studio_math")
    CourseFactory(title=r"Pole \(x^2\)", owner=owner)
    resp = client.get(reverse("home"))
    action = _studio(resp).select_one("a.dash-row__action")
    hidden = action.select_one(".visually-hidden").get_text()
    assert "Pole x^2" in hidden and r"\(" not in hidden

def test_studio_view_action_is_not_the_widok_noun_in_polish(client):
    owner = make_login(client, "studio_pl")
    CourseFactory(title="Algebra", owner=owner)
    _polish(client)  # session[LANGUAGE_SESSION_KEY] = "pl", as in test_analytics_student_page.py
    resp = client.get(reverse("home"))
    assert resp.status_code == 200
    action = _studio(resp).select_one("a.dash-row__action")
    visible = action.find(string=True, recursive=False).strip()
    assert visible and visible != "Widok"

def test_teaching_row_title_carries_dash_row_title(client):
    _user, course = _teaching_setup(client, "teach_title")
    resp = client.get(reverse("home"))
    title = BeautifulSoup(resp.content, "html.parser").select_one(
        'section[data-section="teaching"] li.dash-row a.dash-row__title')
    assert title["href"] == reverse("courses:course_outline", kwargs={"slug": course.slug})
```

- [ ] **Step 2: Run them and confirm they fail.** Run `uv run pytest tests/test_dashboard_panels.py -k "studio_row_title or studio_view or teaching_row_title"`. Expected: 4 FAIL (no `dash-row__title` / `dash-row__action` in Studio).

- [ ] **Step 3: Implement the markup.** In `home.html`, add `{% load courses_extras %}` next to `i18n`. Add `class="dash-row__title"` to the Teaching title anchor. Change each Studio `<li>` to `<li class="dash-row">`, with the title `<a class="dash-row__title" href="{% url 'courses:manage_builder' … %}">` (unchanged target) and a new `<a class="dash-row__action" href="{% url 'courses:course_outline' slug=course.slug %}">{% translate "View" context "dashboard row action: open the course as students see it" %}<span class="visually-hidden"> {{ course.title|strip_math_delimiters }}</span></a>`.

- [ ] **Step 4: Implement the CSS.** In `app.css`, right after the `.dash-row__action:focus-visible` rule, add `.dash-list .dash-row__title { min-width: 0; overflow-wrap: anywhere; }`. Its comment explains why (unbreakable titles overflow the flex row at phone width) and cites `.outline-unit__title` by selector.

- [ ] **Step 5: Run the tests and confirm they pass.** Same command as Step 2: 4 PASS. Also run `uv run pytest tests/test_dashboard_panels.py` (the whole file, which includes the existing Studio test) and every CSS test: `uv run pytest tests/ -k "css"`. All green.

- [ ] **Step 6: Falsify.** Swap the two hrefs in the Studio row: RED. Drop the `context` from the `translate` tag: the PL test is RED only after Task 4 adds a PL translation, so note this mutant for Task 4 and do not claim it here. Drop `|strip_math_delimiters` on the hidden span: RED. Revert each by hand.

- [ ] **Step 7: Commit.** `git add templates/core/home.html core/static/core/css/app.css tests/test_dashboard_panels.py`, message `feat(dashboard): Studio "View" link to the student-facing outline`.

---

### Task 2: "Last edited" card

**Files:**
- Modify: `core/views.py` (`home`)
- Modify: `templates/core/home.html` (Studio panel, right after its `<h2 class="dash-panel__title">`)
- Modify: `core/static/core/css/app.css` (new `.dash-recent` block, after the Task 1 rule)
- Test: `tests/test_dashboard_panels.py`

**Interfaces:**
- Consumes: `{% load courses_extras %}` from Task 1.
- Produces: context key `last_edited_unit: ContentNode | None` (with `course` selected), and the card element `[data-last-edited]` containing exactly one `<a>`. Task 5 relies on both.

- [ ] **Step 1: Write the failing tests.** Add helpers `_card(resp)` (returns `soup.select_one("[data-last-edited]")`) and `_unit(course, **kw)` (`ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="lesson", **kw)`), plus `_pin(node, dt)` (queryset `.update(updated=dt)`). Use a fixed `base = timezone.now()` and `base ± timedelta(minutes=…)`.

```python
def test_last_edited_shows_latest_updated_owned_unit(client):
    owner = make_login(client, "le_latest")
    course = CourseFactory(title="Geo", owner=owner)
    older_pk_unit = _unit(course, title="First")   # lower pk
    newer_pk_unit = _unit(course, title="Second")
    _pin(older_pk_unit, base + timedelta(minutes=5)); _pin(newer_pk_unit, base)
    resp = client.get(reverse("home"))
    assert resp.status_code == 200
    card = _card(resp); links = card.select("a")
    assert len(links) == 1 and not links[0].has_attr("target")
    assert links[0]["href"] == reverse("courses:lesson_unit",
        kwargs={"slug": course.slug, "node_pk": older_pk_unit.pk})
    assert "First" in links[0].get_text() and "Geo" in links[0].get_text()
    assert "Last edited" in card.get_text() and "Last edited" not in links[0].get_text()

def test_last_edited_tie_breaks_on_higher_pk(client): ...      # both pinned to base; href is the higher pk's
def test_last_edited_draft_unit_is_shown_and_opens(client): ... # published=False; client.get(href) == 200
def test_last_edited_quiz_links_to_quiz_unit(client): ...       # make_quiz_unit(course); href == quiz_unit URL
def test_last_edited_strips_math_from_both_titles(client): ...  # unit r"Pole \(x^2\)", course r"Kurs \(y\)"; "Pole x^2" and "Kurs y" in card text; r"\(" not in card text
def test_last_edited_skips_containers(client): ...              # owned kind="section" node pinned later than the owned unit; href is the unit's
def test_last_edited_ignores_other_authors_for_platform_admin(client):
    pa = make_pa(client, "le_pa"); mark_onboarded()
    own = _unit(CourseFactory(title="PA course", owner=pa), title="Mine")
    other = _unit(CourseFactory(title="Other course"), title="Theirs")
    _pin(own, base); _pin(other, base + timedelta(hours=1))
    resp = client.get(reverse("home")); assert resp.status_code == 200
    text = _card(resp).get_text()
    assert "Mine" in text and "Theirs" not in text
def test_no_card_when_studio_shows_but_nothing_owned(client):
    make_pa(client, "le_none"); mark_onboarded()
    _unit(CourseFactory(title="Someone else's"))
    resp = client.get(reverse("home")); body = resp.content.decode()
    assert resp.status_code == 200 and 'data-section="manage"' in body
    assert "data-last-edited" not in body and "Last edited" not in body
def test_last_edited_query_skipped_for_students(client):
    make_student(client, "le_student")
    with CaptureQueriesContext(connection) as ctx:
        resp = client.get(reverse("home"))
    assert resp.status_code == 200 and 'data-section="manage"' not in resp.content.decode()
    assert not any('"updated" DESC' in q["sql"] for q in ctx.captured_queries)
```

Write each `...` body in the style of the two full ones. Every test asserts 200 and pairs its negatives with a positive.

- [ ] **Step 2: Run them and confirm they fail.** Run `uv run pytest tests/test_dashboard_panels.py -k "last_edited or no_card"`. Expected: all FAIL (no card).

- [ ] **Step 3: Implement the query in `home`.** When `can_manage_courses`, set `last_edited_unit = ContentNode.objects.filter(kind=ContentNode.Kind.UNIT, course__owner=request.user).select_related("course").order_by("-updated", "-pk").first()`, otherwise `None`. Pass it in the context. The comment names D3's approximation in one line and points to the spec.

- [ ] **Step 4: Implement the card.** Inside the Studio section, as the first element after the `<h2>`, add `{% if last_edited_unit %}<div class="dash-recent" data-last-edited>`. Inside it, a `<p class="dash-recent__label">{% translate "Last edited" %}</p>` and an `<a class="dash-recent__link" href="{% if last_edited_unit.unit_type == 'quiz' %}{% url 'courses:quiz_unit' … %}{% else %}{% url 'courses:lesson_unit' … %}{% endif %}">` wrapping two block `<span>`s, `dash-recent__unit` and `dash-recent__course`. Both titles go through `|strip_math_delimiters`. The block spans give the screen-reader separator.

- [ ] **Step 5: Implement the CSS.** `.dash-recent` gets `position: relative`, a token border, radius, padding and background, and no `overflow: hidden`. `.dash-recent__link::after` gets `content: ""; position: absolute; inset: 0;`. Add `.dash-recent:focus-within` with `outline: 2px solid var(--primary); outline-offset: 2px;` (as `.resume:focus-visible`), and the default outline on `.dash-recent__link:focus-visible` set to `none`. `.dash-recent__unit` and `.dash-recent__course` get `display: block; min-width: 0; overflow-wrap: anywhere;`, with the course title in `--text-secondary`. Use only existing tokens, so dark mode follows.

- [ ] **Step 6: Run the tests and confirm they pass.** Run the Step 2 command (all PASS), then the whole of `tests/test_dashboard_panels.py` and `uv run pytest tests/ -k "css"`.

- [ ] **Step 7: Falsify.** Each of these mutants must go RED, then be reverted by hand: drop `course__owner` (PA test), drop `kind=UNIT` (containers test), change `-updated` to `updated` (latest test), change `-pk` to `pk` (tie-break test), always use `lesson_unit` (quiz test), drop `|strip_math_delimiters` on the course title (maths test), and move the label inside the `<a>` (latest test).

- [ ] **Step 8: Commit.** `git add core/views.py templates/core/home.html core/static/core/css/app.css tests/test_dashboard_panels.py`, message `feat(dashboard): "Last edited" card opens the unit's live page`.

---

### Task 3: Editor "View live" link

**Files:**
- Modify: `courses/views_manage.py` (`_editor_page` context dict, and the import of `can_access_course`)
- Modify: `templates/courses/manage/editor/editor.html` (`editor-crumb`, before the "Media library" link)
- Modify: `courses/static/courses/css/editor.css` (`.editor-crumb__media` currently carries `margin-left: auto`; move the auto margin so both links sit right)
- Test: `tests/test_unit_edit_link.py`

**Interfaces:**
- Produces: context key `can_view_live: bool` from `_editor_page`, and the anchor `a.editor-crumb__live`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_editor_view_live_link_for_owner_draft_lesson(client):
    owner = make_student(client, "vl_owner")
    course = CourseFactory(owner=owner)
    unit = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="lesson", published=False)
    resp = client.get(reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk}))
    assert resp.status_code == 200
    link = BeautifulSoup(resp.content, "html.parser").select_one("a.editor-crumb__live")
    assert link["href"] == reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    assert link["target"] == "_blank" and "noopener" in link["rel"]
    assert client.get(link["href"]).status_code == 200

def test_editor_view_live_link_for_quiz_targets_quiz_unit(client): ...   # make_quiz_unit; href == quiz_unit URL

def test_editor_no_view_live_for_non_owner_platform_admin(client):
    pa = make_pa(client, "vl_pa")           # not is_staff, not owner
    course = CourseFactory()
    unit = _lesson_unit(course)
    resp = client.get(reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk}))
    body = resp.content.decode()
    assert resp.status_code == 200
    assert reverse("courses:manage_media", kwargs={"slug": course.slug}) in body
    assert "editor-crumb__live" not in body
    assert reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk}) not in body
    assert "View live" not in body

def test_editor_view_live_survives_422_rerender(client):
    owner = make_student(client, "vl_422")
    course = CourseFactory(owner=owner); unit = _lesson_unit(course)
    unit.refresh_from_db()
    resp = client.post(reverse("courses:manage_node_rename", kwargs={"slug": course.slug}),
        {"node": unit.pk, "ctx": "editor", "token": unit.updated.isoformat(), "title": ""})
    assert resp.status_code == 422
    assert "editor-crumb__live" in resp.content.decode()
```

- [ ] **Step 2: Run them and confirm they fail.** Run `uv run pytest tests/test_unit_edit_link.py -k "view_live"`. Expected: the owner, quiz and 422 tests FAIL. The PA test passes vacuously today (no link yet). It goes RED under the Step 6 mutant.

- [ ] **Step 3: Implement the flag.** Import `can_access_course` from `courses.access`. In `_editor_page`'s context dict, next to `"course": unit.course`, add `"can_view_live": can_access_course(request.user, unit.course)`. The comment says why it lives here (three callers, including two 422 re-renders) and not in `editor()`.

- [ ] **Step 4: Implement the link.** In the crumb, before "Media library": `{% if can_view_live %}<a class="editor-crumb__live" href="{% if unit_is_quiz %}{% url 'courses:quiz_unit' slug=course.slug node_pk=unit.pk %}{% else %}{% url 'courses:lesson_unit' slug=course.slug node_pk=unit.pk %}{% endif %}" target="_blank" rel="noopener">{% translate "View live" %}<span class="visually-hidden">&nbsp;{% translate "(opens in a new tab)" %}</span></a>{% endif %}`. In `editor.css`, give the live link `margin-left: auto` with `font-size: .85rem; white-space: nowrap;`, and take `margin-left: auto` off `.editor-crumb__media` only when it follows the live link (`.editor-crumb__live + .editor-crumb__media { margin-left: 0; }`).

- [ ] **Step 5: Run the tests and confirm they pass.** Run the Step 2 command (all 4 PASS), then `uv run pytest tests/test_unit_edit_link.py` and `uv run pytest tests/ -k "css"`.

- [ ] **Step 6: Falsify.** Each must go RED, then be reverted by hand: replace the flag with `True` (PA test), move the flag out of `_editor_page` into `editor()`'s call (422 test, by passing it as a kwarg; simulate it by computing the flag only when `status == 200`), and drop the `unit_is_quiz` branch (quiz test).

- [ ] **Step 7: Commit.** `git add courses/views_manage.py templates/courses/manage/editor/editor.html courses/static/courses/css/editor.css tests/test_unit_edit_link.py`, message `feat(editor): "View live" link to the unit's student-facing page`.

---

### Task 4: Polish translations

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.mo`

- [ ] **Step 1: Extract.** Run `uv run python manage.py makemessages -l pl`. Then grep the `.po` for the three new entries. `msgctxt "dashboard row action: open the course as students see it"` + `msgid "View"`, and `msgid "Last edited"` and `msgid "View live"`. Use a grep without a `$` anchor, because the `.po` is CRLF.

- [ ] **Step 2: Fill in the translations.** `View` (context) → `Zobacz`. `Last edited` → `Ostatnio edytowane`. `View live` → `Zobacz na żywo`. Clear any `#, fuzzy` flag on these entries. A fuzzy entry needs two deletions: the flag line and any `#|` previous-msgid lines. Check that no other entry gained a wrong fuzzy guess.

- [ ] **Step 3: Compile.** Run `uv run python manage.py compilemessages -l pl`.

- [ ] **Step 4: Verify.** Run `uv run pytest tests/test_dashboard_panels.py -k "polish"`: PASS, and the action now reads "Zobacz". Falsify: drop the `context` from the template tag, re-run makemessages and compilemessages. The test must be RED ("Widok"). Then revert the template by hand, re-run both commands, and confirm GREEN.

- [ ] **Step 5: Commit.** `git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo`, message `i18n(pl): author live-view link strings`.

---

### Task 5: Phone-width e2e and screenshots

**Files:**
- Create: `tests/test_e2e_author_live_view.py`

**Interfaces:**
- Consumes: `[data-last-edited]`, `.dash-recent__label`, `a.dash-row__title` (Tasks 1–2); `.lesson-unit__title` and `.draft-banner` on the live page.

- [ ] **Step 1: Write the test.** Use the module conventions of `tests/test_e2e_settings.py`: `pytestmark = pytest.mark.e2e`, the `DJANGO_ALLOW_ASYNC_UNSAFE` session fixture, `_login`, and `@pytest.mark.django_db(transaction=True)`. Fixture: a verified owner, a course titled `"Kurs" + "x" * 80` (unbroken), and one **draft** lesson unit in it titled `"Lekcja" + "y" * 80`, with an element added so the page renders content. Then:

```python
page.set_viewport_size({"width": 360, "height": 800})
_login(page, live_server, "e2e_author"); page.goto(f"{live_server.url}/")
card = page.locator("[data-last-edited]"); card.wait_for()
assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
box = page.locator("[data-last-edited] .dash-recent__label").bounding_box()
cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
assert page.evaluate("([x, y]) => !!document.elementFromPoint(x, y).closest('[data-last-edited] a')", [cx, cy])
page.mouse.click(cx, cy)
page.locator(".lesson-unit__title").wait_for()
page.locator(".draft-banner").wait_for()
```

- [ ] **Step 2: Run it and confirm it fails without the CSS.** Comment out the `.dash-list .dash-row__title` rule and the `overflow-wrap` on `.dash-recent__unit` / `.dash-recent__course` by hand. Run `uv run pytest tests/test_e2e_author_live_view.py -m e2e`. Expected: RED on `scrollWidth`. Then remove the `::after` overlay instead. Expected: RED on `elementFromPoint`. Restore both by hand and confirm with `git diff`.

- [ ] **Step 3: Run it and confirm it passes.** Same command: PASS.

- [ ] **Step 4: Screenshots (not committed).** With a scratch script under the session scratchpad (not `tests/`, never a `capture_*` file), take light and dark screenshots at 360px of the Studio panel, with the card keyboard-focused (`page.keyboard.press("Tab")` until the card link is focused), and of the editor crumb at desktop width. Judge dark mode separately: contrast of the label, the course title and the focus ring. Fix anything wrong in `app.css` / `editor.css` and re-run the Task 1–3 CSS tests.

- [ ] **Step 5: Commit.** `git add tests/test_e2e_author_live_view.py` (plus any CSS fixed in Step 4, by path), message `test(e2e): author live-view card works at phone width`.

---

### Task 6: Branch verification

- [ ] **Step 1: Find the affected tests.** Run `uv run python scripts/affected_tests.py` if it exists. If it names a full run, do a full run.
- [ ] **Step 2: Unit suite.** Run it in the ~4 chunks the repo's OOM note describes (`--ignore-glob` patterns, static args), in the foreground. Grep each summary line. Do not trust the exit code alone.
- [ ] **Step 3: e2e.** Run `-m e2e` over the dashboard, editor and new files at least (`-k "dashboard or editor or author_live_view or smoke"`), or the full arm if Step 1 says so.
- [ ] **Step 4: Lint.** `uv run ruff check .` and `uv run ruff format --check .`.
- [ ] **Step 5:** If anything fails, fix it in a commit scoped to the owning task's files, and report what failed and why.
