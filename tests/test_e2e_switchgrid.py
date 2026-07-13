"""Playwright e2e for the "Switch grid" self-check element (SwitchGridElement, plan
Task 10). Drives the REAL student gesture end-to-end — clicks the inline cyclers to
change the visible option and clicks the actual Check button — never a page.evaluate
shortcut into the grading endpoint or the JS internals (this repo's standing lesson: an
e2e that bypasses the real gesture ships broken UX green).

Covers the behaviour matrix from the task brief:
  1. A seeded grid whose correct options are reachable by cycling; open the lesson page.
  2. Clicking a cycler cycles its visible option; after enough clicks the correct
     option shows.
  3. Check -> per-cycler feedback classes (switchgrid--correct / switchgrid--incorrect)
     appear and the summary shows.
  4. A fully-correct grid -> success summary + cyclers locked (switchgrid--locked) +
     Check hidden (and a locked cycler no longer cycles).
  5. An incorrect grid -> "try again" (retry) summary AND cyclers stay interactive (NOT
     locked); re-cycling clears the stale feedback class; a corrected re-Check succeeds.

The grid is seeded via the ORM (a fixture-style helper) so the option lists + answer
indices are deterministic — but the CYCLE/CHECK interaction is real browser clicks.
Mirrors the login/seed/unit harness of tests/test_e2e_switchgate.py. Marked e2e
(excluded from the default run; run focused + foreground with -m e2e or by file)."""

import os
import re

import pytest
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD
from tests.factories import add_element
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e

_CORRECT = re.compile(r"\bswitchgrid--correct\b")
_INCORRECT = re.compile(r"\bswitchgrid--incorrect\b")
_LOCKED = re.compile(r"\bswitchgrid--locked\b")
_SUCCESS = re.compile(r"\bswitchgrid--success\b")
_RETRY = re.compile(r"\bswitchgrid--retry\b")


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    # Sync Playwright + Django ORM in the same thread.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


# ---------------------------------------------------------------------------
# Login / seed helpers (mirrored from tests/test_e2e_switchgate.py)
# ---------------------------------------------------------------------------


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _seed_student(username):
    return make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )


def _new_unit(username, unit_type="lesson"):
    """An enrolled student + a fresh lesson unit. Returns (student, unit)."""
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory

    student = _seed_student(username)
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type=unit_type)
    EnrollmentFactory(student=student, course=course)
    return student, unit


def _unit_url(live_server, unit):
    from django.urls import reverse

    name = "courses:quiz_unit" if unit.unit_type == "quiz" else "courses:lesson_unit"
    path = reverse(name, kwargs={"slug": unit.course.slug, "node_pk": unit.pk})
    return f"{live_server.url}{path}"


def _switchgrid(prompt, lines):
    """Build a SwitchGridElement from author `{{choice}}` markup, as the form's
    clean()/save() would: parse each line's stem to its sentinel token-stem via
    parse_stem_multi (the raw sentinel is NEVER pasted here — file tools corrupt it).

    `lines` is a list of (author_stem, [(options, answer), ...]) where the k-th
    `{{choice}}` in the stem pairs with the k-th cycler tuple. Options are sanitised
    in the model's save()."""
    from courses import switchgrid
    from courses.models import SwitchGridElement

    built = []
    for stem, cyclers in lines:
        token_stem, _n = switchgrid.parse_stem_multi(stem)
        built.append(
            {
                "stem": token_stem,
                "cyclers": [
                    {"options": list(opts), "answer": ans} for opts, ans in cyclers
                ],
            }
        )
    return SwitchGridElement.objects.create(prompt=prompt, lines=built)


# Shared locators (scoped to the first grid on the page).
def _grid(page):
    return page.locator(".switchgrid").first


def _cycler(page, i):
    return _grid(page).locator("[data-switchgrid-cycler]").nth(i)


def _confirm(page):
    return _grid(page).locator(".switchgrid__confirm")


def _summary(page):
    return _grid(page).locator("[data-switchgrid-summary]")


def _option(cycler, i):
    return cycler.locator(".switchgrid__option").nth(i)


# The seeded grid used by both tests: ONE line, TWO cyclers.
#   cycler 0: options [A, B, C], answer index 2  (reach by 2 clicks from the default)
#   cycler 1: options [X, Y],    answer index 1  (reach by 1 click from the default)
def _seed_two_cycler_grid(unit):
    add_element(
        unit,
        _switchgrid(
            "Set both:",
            [
                (
                    "First {{choice}} then {{choice}}",
                    [(["A", "B", "C"], 2), (["X", "Y"], 1)],
                )
            ],
        ),
    )


# ---------------------------------------------------------------------------
# 1. Cycle to the correct options -> Check -> success + per-cycler green + lock
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_switchgrid_correct_path_locks_and_summarizes(page, live_server):
    """Cycle both cyclers to their correct option, Check, and assert: per-cycler
    switchgrid--correct feedback, the success summary, cyclers locked, Check hidden,
    and that a locked cycler no longer cycles."""
    _student, unit = _new_unit("sgrid_ok")
    _seed_two_cycler_grid(unit)
    _login(page, live_server, "sgrid_ok")
    page.goto(_unit_url(live_server, unit))

    c0, c1 = _cycler(page, 0), _cycler(page, 1)
    # At rest: option 0 of each cycler is the visible one, others hidden.
    expect(_option(c0, 0)).to_be_visible()
    expect(_option(c0, 2)).to_be_hidden()
    expect(_confirm(page)).to_be_visible()
    expect(_summary(page)).to_be_hidden()

    # Cycle cycler 0 to index 2 ("C"): two clicks (0 -> 1 -> 2).
    c0.click()
    expect(_option(c0, 1)).to_be_visible()
    c0.click()
    expect(_option(c0, 2)).to_be_visible()
    expect(_option(c0, 0)).to_be_hidden()

    # Cycle cycler 1 to index 1 ("Y"): one click.
    c1.click()
    expect(_option(c1, 1)).to_be_visible()

    _confirm(page).click()

    # Per-cycler green feedback + success summary.
    expect(c0).to_have_class(_CORRECT)
    expect(c1).to_have_class(_CORRECT)
    expect(_summary(page)).to_be_visible()
    expect(_summary(page)).to_have_class(_SUCCESS)

    # Solved -> both cyclers locked and Check hidden.
    expect(c0).to_have_class(_LOCKED)
    expect(c1).to_have_class(_LOCKED)
    expect(_confirm(page)).to_be_hidden()

    # A locked cycler no longer cycles (advance() bails on the locked class).
    c0.click()
    expect(_option(c0, 2)).to_be_visible()


# ---------------------------------------------------------------------------
# 2. Incorrect -> retry summary + mixed feedback + still interactive; then recover
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_switchgrid_incorrect_retry_then_recover(page, live_server):
    """One cycler right, one wrong -> Check shows the retry summary with mixed
    per-cycler feedback (green + red), cyclers stay UNLOCKED and Check stays live.
    Re-cycling the wrong cycler clears its stale red class; correcting it and
    re-Checking then succeeds and locks."""
    _student, unit = _new_unit("sgrid_bad")
    _seed_two_cycler_grid(unit)
    _login(page, live_server, "sgrid_bad")
    page.goto(_unit_url(live_server, unit))

    c0, c1 = _cycler(page, 0), _cycler(page, 1)

    # cycler 0 -> correct ("C", index 2); cycler 1 left at index 0 ("X") = WRONG.
    c0.click()
    c0.click()
    expect(_option(c0, 2)).to_be_visible()
    expect(_option(c1, 0)).to_be_visible()

    _confirm(page).click()

    # Mixed feedback: cycler 0 green, cycler 1 red; retry summary; NOT locked.
    expect(c0).to_have_class(_CORRECT)
    expect(c1).to_have_class(_INCORRECT)
    expect(_summary(page)).to_be_visible()
    expect(_summary(page)).to_have_class(_RETRY)
    expect(c0).not_to_have_class(_LOCKED)
    expect(c1).not_to_have_class(_LOCKED)
    expect(_confirm(page)).to_be_visible()

    # Re-cycle the wrong cycler -> its stale red class clears + advances to "Y".
    c1.click()
    expect(c1).not_to_have_class(_INCORRECT)
    expect(_option(c1, 1)).to_be_visible()

    # Re-Check now that both are correct -> success + lock.
    _confirm(page).click()
    expect(c0).to_have_class(_CORRECT)
    expect(c1).to_have_class(_CORRECT)
    expect(_summary(page)).to_have_class(_SUCCESS)
    expect(c0).to_have_class(_LOCKED)
    expect(c1).to_have_class(_LOCKED)
    expect(_confirm(page)).to_be_hidden()


# ===========================================================================
# Editor-driving e2e (Task 5): the AUTHOR builds/edits a Switch grid in the
# manage editor. Drives REAL gestures (fill the actual stem/option inputs,
# click the actual add/remove/save controls) -- never a page.evaluate shortcut
# around the stem-reconcile / submit-guard core interactions.
#
# Harness mirrors tests/test_e2e_editor_ws3.py: a Platform-Admin owner, the
# allauth login, and the manage-editor URL
# (courses:manage_editor -> /manage/courses/<slug>/build/unit/<pk>/edit/). The
# add-menu -> type-card flow mounts the per-type editor partial in the appended
# row's [data-edit-slot]; switchgrid_editor.js self-initialises on that swap
# (editor.js calls window.libliInitSwitchGridEditors), so the cyclers reconcile
# and carry their positional "Cycler N" labels.
# ===========================================================================

# The exact create seed (see courses.element_forms._SG_SEED_STEM); one {{choice}}.
_SEED_STEM = "2 {{choice}} 2 = 4"


def _make_pa_user(username):
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    user.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return user


def _seed_authoring_unit(pa, slug):
    """A PA-owned course + a fresh lesson unit to author elements into."""
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    course = CourseFactory(slug=slug, owner=pa)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    return course, unit


def _editor_url(live_server, course, unit):
    return f"{live_server.url}/manage/courses/{course.slug}/build/unit/{unit.pk}/edit/"


def _open_switchgrid_add(page):
    """Open the add-menu, click the Switch-grid card, and wait for the editor
    partial (with its reconciled cyclers) to mount in the appended edit slot."""
    page.locator("[data-add-toggle]").click()
    page.locator("[data-add-type='switchgrid']").click()
    page.wait_for_selector("[data-edit-slot] form[data-op='element-save']")
    page.wait_for_selector("[data-switchgrid-editor]")


# ---- editor locators (scoped to the single editor in the edit slot) ----
def _sg_editor(page):
    return page.locator("[data-switchgrid-editor]")


def _sg_lines(page):
    return _sg_editor(page).locator("[data-line-row]")


def _sg_line(page, i):
    return _sg_lines(page).nth(i)


def _sg_stem(line):
    return line.locator("[data-stem]")


def _sg_cyclers(line):
    return line.locator("[data-cycler-row]")


def _sg_cycler(line, j):
    return _sg_cyclers(line).nth(j)


def _sg_opt_inputs(cycler):
    return cycler.locator("input[type='text']")


def _sg_radios(cycler):
    return cycler.locator("input[type='radio']")


def _sg_option_rows(cycler):
    return cycler.locator(".el-editor__option-row")


def _sg_save(page):
    return page.locator(
        "[data-edit-slot] form[data-op='element-save'] button[type='submit']"
    ).first


def _fill_cycler(cycler, values, answer):
    """Fill a cycler's option text inputs and pick `answer` (real gestures)."""
    inputs = _sg_opt_inputs(cycler)
    for k, v in enumerate(values):
        inputs.nth(k).fill(v)
    _sg_radios(cycler).nth(answer).check()


# ---------------------------------------------------------------------------
# (a) create default; type/delete/re-type a 2nd {{choice}}; stash restore
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_editor_marker_add_delete_retype_restores_stash(page, live_server):
    pa = _make_pa_user("sged_a")
    course, unit = _seed_authoring_unit(pa, "sged-a")
    _login(page, live_server, "sged_a")
    page.goto(_editor_url(live_server, course, unit))
    page.wait_for_selector('[data-scope="editor"]')
    _open_switchgrid_add(page)

    # Create default: exactly one line, one cycler labelled "Cycler 1", two options.
    expect(_sg_lines(page)).to_have_count(1)
    line = _sg_line(page, 0)
    expect(_sg_cyclers(line)).to_have_count(1)
    expect(_sg_cycler(line, 0).locator("[data-cycler-label]")).to_have_text("Cycler 1")
    expect(_sg_opt_inputs(_sg_cycler(line, 0))).to_have_count(2)
    expect(_sg_stem(line)).to_have_value(_SEED_STEM)

    # Type a 2nd {{choice}} into the stem -> a 2nd cycler "Cycler 2" appears.
    _sg_stem(line).fill("2 {{choice}} 2 {{choice}} 4")
    expect(_sg_cyclers(line)).to_have_count(2)
    expect(_sg_cycler(line, 1).locator("[data-cycler-label]")).to_have_text("Cycler 2")

    # Fill the 2nd cycler so the stash has distinctive data to restore.
    _fill_cycler(_sg_cycler(line, 1), ["ALPHA", "BETA"], 1)

    # Delete the 2nd {{choice}} -> the 2nd cycler block is removed (stashed).
    _sg_stem(line).fill(_SEED_STEM)
    expect(_sg_cyclers(line)).to_have_count(1)

    # Re-type it -> the stashed options ("ALPHA"/"BETA") are restored.
    _sg_stem(line).fill("2 {{choice}} 2 {{choice}} 4")
    expect(_sg_cyclers(line)).to_have_count(2)
    restored = _sg_cycler(line, 1)
    expect(_sg_opt_inputs(restored).nth(0)).to_have_value("ALPHA")
    expect(_sg_opt_inputs(restored).nth(1)).to_have_value("BETA")
    expect(_sg_radios(restored).nth(1)).to_be_checked()


# ---------------------------------------------------------------------------
# (b) remove-x an option / a line; min-guards do nothing
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_editor_remove_controls_and_min_guards(page, live_server):
    pa = _make_pa_user("sged_b")
    course, unit = _seed_authoring_unit(pa, "sged-b")
    _login(page, live_server, "sged_b")
    page.goto(_editor_url(live_server, course, unit))
    page.wait_for_selector('[data-scope="editor"]')
    _open_switchgrid_add(page)

    line = _sg_line(page, 0)
    cyc = _sg_cycler(line, 0)

    # Add an option -> 3, then remove one -> 2 (remove control works).
    cyc.locator("[data-add-option]").click()
    expect(_sg_option_rows(cyc)).to_have_count(3)
    _sg_option_rows(cyc).nth(2).locator("[data-remove-option]").click()
    expect(_sg_option_rows(cyc)).to_have_count(2)

    # Min-guard: the x on a 2-option cycler does nothing (stays at 2).
    _sg_option_rows(cyc).nth(0).locator("[data-remove-option]").click()
    expect(_sg_option_rows(cyc)).to_have_count(2)

    # Add a 2nd line, then remove it (remove-line works) -> back to 1.
    _sg_editor(page).locator("[data-add-line]").click()
    expect(_sg_lines(page)).to_have_count(2)
    _sg_line(page, 1).locator("[data-remove-line]").first.click()
    expect(_sg_lines(page)).to_have_count(1)

    # Min-guard: the x on the last remaining line does nothing (stays at 1).
    _sg_line(page, 0).locator("[data-remove-line]").first.click()
    expect(_sg_lines(page)).to_have_count(1)


# ---------------------------------------------------------------------------
# (c) remove a MIDDLE line, Add line, fill, Save -> ordered stored lines
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_editor_remove_middle_line_saves_ordered(page, live_server):
    from courses.models import Element
    from courses.switchgrid import to_author_stem_multi

    pa = _make_pa_user("sged_c")
    course, unit = _seed_authoring_unit(pa, "sged-c")
    _login(page, live_server, "sged_c")
    page.goto(_editor_url(live_server, course, unit))
    page.wait_for_selector('[data-scope="editor"]')
    _open_switchgrid_add(page)

    # Grow to three lines (indices 0,1,2) and fill each distinctly.
    _sg_editor(page).locator("[data-add-line]").click()
    _sg_editor(page).locator("[data-add-line]").click()
    expect(_sg_lines(page)).to_have_count(3)
    for n in range(3):
        ln = _sg_line(page, n)
        _sg_stem(ln).fill(f"L{n} {{{{choice}}}}")
        _fill_cycler(_sg_cycler(ln, 0), [f"a{n}", f"b{n}"], 0)

    # Remove the MIDDLE line (L1). Remaining DOM: L0, L2 (gappy indices 0,2).
    _sg_line(page, 1).locator("[data-remove-line]").first.click()
    expect(_sg_lines(page)).to_have_count(2)

    # Add a fresh line (monotonic index 3 -> no field collision) and fill it.
    _sg_editor(page).locator("[data-add-line]").click()
    expect(_sg_lines(page)).to_have_count(3)
    ln3 = _sg_line(page, 2)
    _sg_stem(ln3).fill("L3 {{choice}}")
    _fill_cycler(_sg_cycler(ln3, 0), ["a3", "b3"], 0)

    _sg_save(page).click()
    page.wait_for_selector('[data-scope="preview"] .switchgrid')

    el = Element.objects.get(unit=unit)
    obj = el.content_object
    stems = [to_author_stem_multi(ln["stem"]) for ln in obj.lines]
    assert stems == ["L0 {{choice}}", "L2 {{choice}}", "L3 {{choice}}"]
    assert [ln["cyclers"][0]["options"] for ln in obj.lines] == [
        ["a0", "b0"],
        ["a2", "b2"],
        ["a3", "b3"],
    ]


# ---------------------------------------------------------------------------
# (d) multi-{{choice}} line, one cycler blank -> Save -> inline guard message,
#     NOT the server marker-mismatch, and nothing created
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_editor_blank_cycler_blocks_save_with_inline_message(page, live_server):
    from courses.models import Element

    pa = _make_pa_user("sged_d")
    course, unit = _seed_authoring_unit(pa, "sged-d")
    _login(page, live_server, "sged_d")
    page.goto(_editor_url(live_server, course, unit))
    page.wait_for_selector('[data-scope="editor"]')
    _open_switchgrid_add(page)

    line = _sg_line(page, 0)
    _sg_stem(line).fill("X {{choice}} Y {{choice}}")
    expect(_sg_cyclers(line)).to_have_count(2)

    # Fill cycler 1, leave cycler 2 wholly blank.
    _fill_cycler(_sg_cycler(line, 0), ["p", "q"], 0)

    _sg_save(page).click()

    # The submit guard fires an inline message on the blank cycler (client-only;
    # a server round-trip would have swapped the form and wiped [data-inline-error]).
    err = _sg_cycler(line, 1).locator("[data-inline-error]")
    expect(err).to_be_visible()
    expect(err).to_contain_text("Cycler 2")
    # The POST was blocked -> nothing created, and no server marker-mismatch shown.
    assert Element.objects.filter(unit=unit).count() == 0
    assert page.locator(".field-error", has_text="exactly once").count() == 0


# ---------------------------------------------------------------------------
# (e) author a full valid grid -> Save -> stored lines correct
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_editor_full_valid_grid_saves(page, live_server):
    from courses.models import Element
    from courses.models import SwitchGridElement
    from courses.switchgrid import to_author_stem_multi

    pa = _make_pa_user("sged_e")
    course, unit = _seed_authoring_unit(pa, "sged-e")
    _login(page, live_server, "sged_e")
    page.goto(_editor_url(live_server, course, unit))
    page.wait_for_selector('[data-scope="editor"]')
    before = SwitchGridElement.objects.count()
    _open_switchgrid_add(page)

    line = _sg_line(page, 0)
    _sg_stem(line).fill("1 {{choice}} 1")
    _fill_cycler(_sg_cycler(line, 0), ["+", "-"], 1)  # answer index 1

    _sg_save(page).click()
    page.wait_for_selector('[data-scope="preview"] .switchgrid')

    assert SwitchGridElement.objects.count() == before + 1
    obj = Element.objects.get(unit=unit).content_object
    assert len(obj.lines) == 1
    assert to_author_stem_multi(obj.lines[0]["stem"]) == "1 {{choice}} 1"
    assert obj.lines[0]["cyclers"] == [{"options": ["+", "-"], "answer": 1}]


# ---------------------------------------------------------------------------
# (f) type a new {{choice}} and Save immediately (debounce race) -> the submit
#     guard flushes; NEVER the server "marker != cycler count" error
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_editor_save_during_debounce_flushes_guard(page, live_server):
    from courses.models import Element

    pa = _make_pa_user("sged_f")
    course, unit = _seed_authoring_unit(pa, "sged-f")
    _login(page, live_server, "sged_f")
    page.goto(_editor_url(live_server, course, unit))
    page.wait_for_selector('[data-scope="editor"]')
    _open_switchgrid_add(page)

    line = _sg_line(page, 0)
    # Make cycler 1 valid so ONLY the freshly-typed 2nd marker is in question.
    _fill_cycler(_sg_cycler(line, 0), ["p", "q"], 0)

    # Type a 2nd {{choice}} and click Save WITHIN the debounce window: the submit
    # guard must flush+reconcile so the new (blank) cycler materialises and is
    # caught inline -- it must NEVER reach the server as a marker/cycler mismatch.
    _sg_stem(line).fill("X {{choice}} Y {{choice}}")
    _sg_save(page).click()

    err = line.locator("[data-cycler-row] [data-inline-error]")
    expect(err.first).to_be_visible()
    assert Element.objects.filter(unit=unit).count() == 0
    assert page.locator(".field-error", has_text="exactly once").count() == 0
