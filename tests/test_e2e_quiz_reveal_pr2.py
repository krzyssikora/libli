"""Playwright: the PR 2 types in the browser (spec 2026-09-25 §2.2 inert drag UI,
§2.4 re-enhancing after a swap, §4 results, §5a lessons)."""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _student(username):
    return make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _seed(username, slug, kinds, unit_type="quiz", max_attempts=2):
    from django.contrib.auth import get_user_model

    from courses.models import Element
    from courses.models import Enrollment
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.reveal_pr2_kit import build

    user = get_user_model().objects.get(username=username)
    course = CourseFactory(slug=slug)
    Enrollment.objects.get_or_create(student=user, course=course)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type=unit_type, parent=None, title="Q"
    )
    kits = []
    for kind in kinds:
        kit = build(kind, max_attempts=max_attempts)
        Element.objects.create(unit=unit, content_object=kit.question)
        kits.append(kit)
    return course, unit, kits


def _quiz_url(live_server, course, unit):
    return f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/quiz/"


def _size_stages(page):
    """MediaAssetFactory's file is not served, so the stage <img> collapses to 0px
    and every overlay target sits at one point (tests/test_e2e_questions_2dii.py
    explains the same trap). A page-level stylesheet sizes EVERY stage -- the one
    a Check swaps in and the key copy's second stage included -- so, unlike a
    one-off inline-style fix, it survives each form swap. Presentation only."""
    page.add_style_tag(
        content="[data-dragimage-stage]{display:block!important;width:400px!important;"
        "height:300px!important}[data-dragimage-stage] .dragimage__img"
        "{width:400px!important;height:300px!important}"
    )


def _drag(q, token, slot_index):
    """Tap-assign: arm the chip, then tap the n-th live slot / target."""
    q.locator("[data-answer-yours] .dnd__chip", has_text=token).first.click()
    q.locator(
        "[data-answer-yours] .dnd__slot, [data-answer-yours] .dragimage__target"
    ).nth(slot_index).click()


def _check(q):
    q.locator("button[type='submit']:not([name='reveal'])").click()


def _drop(target, token="gammadis"):
    """A synthetic drop straight onto a slot / overlay target (spec §2.2: "tapping
    / dragging a chip ... leaves every select unchanged"). Dispatched in the page,
    so none of Playwright's pointer-event traps apply."""
    target.evaluate(
        """(el, tok) => {
            const dt = new DataTransfer();
            dt.setData("text/plain", tok);
            el.dispatchEvent(new DragEvent(
                "drop", {dataTransfer: dt, bubbles: true, cancelable: true}
            ));
        }""",
        token,
    )


def _select_values(q, scope):
    return q.locator(f"{scope} select").evaluate_all("els => els.map(e => e.value)")


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("kind", ["dragfill", "matchpair", "dragimage"])
def test_drag_quiz_check_reveal_inert_copies(browser, live_server, kind):
    _student(f"d_{kind}")
    course, unit, _ = _seed(f"d_{kind}", f"e2e-d-{kind}", [kind])
    page = browser.new_context().new_page()
    _login(page, live_server, f"d_{kind}")
    page.goto(_quiz_url(live_server, course, unit))
    if kind == "dragimage":
        _size_stages(page)
    q = page.locator("[data-question]").first
    _drag(q, "alphakey", 0)
    _drag(q, "gammadis", 1)
    _check(q)
    q.locator(".question__verdict.is-partial").wait_for(timeout=6000)
    # Spec §2.4: the swapped form is a NEW dnd root -- chips must be rebuilt.
    assert q.locator("[data-answer-yours] .dnd__chip").count() >= 3
    targets = q.locator(
        "[data-answer-yours] .dnd__slot, [data-answer-yours] .dragimage__target"
    )
    assert "is-correct" in targets.nth(0).get_attribute("class")
    assert "is-incorrect" in targets.nth(1).get_attribute("class")
    paint = "el => getComputedStyle(el).backgroundColor"
    assert targets.nth(0).evaluate(paint) != targets.nth(1).evaluate(paint)
    # Spec §1.2: the colour stays until the NEXT Check -- re-filling the green part
    # (here with the wrong chip, then back) does not repaint it.
    _drag(q, "gammadis", 0)
    assert (
        _select_values(q, "[data-answer-yours]")[0] == "gammadis"
    )  # the rebuilt UI is LIVE
    assert "is-correct" in targets.nth(0).get_attribute("class")
    _drag(q, "alphakey", 0)
    assert _select_values(q, "[data-answer-yours]")[0] == "alphakey"
    if kind == "dragimage":
        # dnd.js hides the zone rows (and their .sr-only verdicts): each painted
        # overlay target must carry its own non-colour cue (spec §2.1).
        after = "t => (t.nextElementSibling || {}).textContent"
        assert targets.nth(1).evaluate(after) == "incorrect"
        assert targets.nth(1).inner_text().strip() == "gammadis"  # text unchanged
    page.once("dialog", lambda d: d.accept())
    q.locator("[data-reveal-btn]").click()
    q.locator("[data-answer-switch]").wait_for(timeout=6000)
    # Locked "Your answer": tapping a chip then a filled target changes nothing.
    before = _select_values(q, "[data-answer-yours]")
    q.locator("[data-answer-yours] .dnd__chip").first.click(force=True)
    q.locator(
        "[data-answer-yours] .dnd__slot, [data-answer-yours] .dragimage__target"
    ).nth(0).click(force=True)
    _drop(
        q.locator(
            "[data-answer-yours] .dnd__slot, [data-answer-yours] .dragimage__target"
        ).nth(0)
    )
    assert _select_values(q, "[data-answer-yours]") == before
    # The key copy: built by dnd.js (select[data-slot]), inert, showing the key.
    q.locator("label:has([data-answer-view='key'])").click()
    key_targets = q.locator(
        "[data-answer-key] .dnd__slot, [data-answer-key] .dragimage__target"
    )
    assert key_targets.nth(1).inner_text().strip() == "betakey"
    key_chips = q.locator("[data-answer-key] .dnd__chip")
    assert key_chips.count() >= 3  # [].every() is true: prove the pool was built
    assert key_chips.evaluate_all("cs => cs.every(c => c.disabled)")
    key_before = _select_values(q, "[data-answer-key]")
    key_targets.nth(1).click(force=True)
    _drop(key_targets.nth(1), "alphakey")
    assert (
        _select_values(q, "[data-answer-key]") == key_before == ["alphakey", "betakey"]
    )
    # Spec §2.2: a locked "Your answer" on RESUME is inert too -- no script froze it,
    # only the server's disabled fieldset does.
    page.reload()
    if kind == "dragimage":
        _size_stages(page)
    q = page.locator("[data-question]").first
    before = _select_values(q, "[data-answer-yours]")
    live = q.locator(
        "[data-answer-yours] .dnd__slot, [data-answer-yours] .dragimage__target"
    ).nth(0)
    live.click(force=True)
    _drop(live)
    assert _select_values(q, "[data-answer-yours]") == before


@pytest.mark.django_db(transaction=True)
def test_multi_paragraph_drag_stem_keeps_its_spacing_in_both_copies(
    browser, live_server
):
    # The stem's <p>s now sit under .question__stem > [data-dnd]; the prose-rhythm
    # rule must reach through that root, in "Your answer" and in the key copy.
    from courses.fillblank import parse

    _student("d_par")
    course, unit, (kit,) = _seed("d_par", "e2e-d-par", ["dragfill"], max_attempts=1)
    q_model = kit.question
    q_model.stem = parse("<p>One {{alphakey}}.</p><p>Two {{betakey}}.</p>")[0]
    q_model.save()
    page = browser.new_context().new_page()
    _login(page, live_server, "d_par")
    page.goto(_quiz_url(live_server, course, unit))
    q = page.locator("[data-question]").first
    _drag(q, "gammadis", 1)
    _check(q)
    q.locator("[data-answer-switch]").wait_for(timeout=6000)  # 1 attempt: locked
    gap = "p => getComputedStyle(p).marginTop"
    assert q.locator("[data-answer-yours] [data-dnd] > p").nth(1).evaluate(gap) != "0px"
    q.locator("label:has([data-answer-view='key'])").click()
    assert q.locator("[data-answer-key] [data-dnd] > p").nth(1).evaluate(gap) != "0px"


@pytest.mark.django_db(transaction=True)
def test_check_on_one_drag_question_leaves_the_other_alone(browser, live_server):
    _student("d_two")
    course, unit, _ = _seed("d_two", "e2e-d-two", ["dragfill", "matchpair"])
    page = browser.new_context().new_page()
    _login(page, live_server, "d_two")
    page.goto(_quiz_url(live_server, course, unit))
    first, second = (
        page.locator("[data-question]").nth(0),
        page.locator("[data-question]").nth(1),
    )
    chips_before = second.locator(".dnd__chip").count()
    slots_before = second.locator(".dnd__slot").count()
    _drag(first, "alphakey", 0)
    _check(first)
    first.locator("[data-question-feedback] .question__verdict").wait_for(timeout=6000)
    assert second.locator(".dnd__chip").count() == chips_before
    assert second.locator(".dnd__slot").count() == slots_before


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("kind", ["choicegrid", "multigrid"])
def test_grid_lock_keeps_the_students_pick_and_paints_rows(browser, live_server, kind):
    _student(f"g_{kind}")
    course, unit, (kit,) = _seed(f"g_{kind}", f"e2e-g-{kind}", [kind], max_attempts=1)
    page = browser.new_context().new_page()
    _login(page, live_server, f"g_{kind}")
    page.goto(_quiz_url(live_server, course, unit))
    q = page.locator("[data-question]").first
    rows = q.locator("[data-answer-yours] tbody tr")
    rows.nth(0).locator("input").nth(0).check()
    rows.nth(1).locator("input").nth(0).check()  # wrong for row 2 in both kits
    _check(q)
    q.locator("[data-answer-switch]").wait_for(timeout=6000)  # 1 attempt: locked
    rows = q.locator("[data-answer-yours] tbody tr")
    assert (
        rows.nth(1).locator("input").nth(0).is_checked()
    )  # the key copy did not steal it
    # The swapped-in scroll wrapper is wired again (scroll_affordance.js marks it).
    wrap = q.locator("[data-answer-yours] [data-scroll-x]")
    assert wrap.get_attribute("data-scroll-x-ready") == "1"
    stmt = "tr => getComputedStyle(tr.querySelector('td')).backgroundColor"
    assert rows.nth(0).evaluate(stmt) != rows.nth(1).evaluate(stmt)
    q.locator("label:has([data-answer-view='key'])").click()
    key_row2 = q.locator("[data-answer-key] tbody tr").nth(1)
    assert key_row2.locator("input").nth(1).is_checked()
    assert q.locator("[data-answer-view='yours']").is_enabled()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "kind", ["dragfill", "matchpair", "dragimage", "choicegrid", "multigrid"]
)
def test_lesson_check_repaints_and_rebuilds(browser, live_server, kind):
    # Spec §2.4 / §5a: question.js re-enhances every drag type after its swap
    # (drag onto image goes through the separate overlay builder).
    _student(f"l_{kind}")
    course, unit, _ = _seed(f"l_{kind}", f"e2e-l-{kind}", [kind], unit_type="lesson")
    page = browser.new_context().new_page()
    _login(page, live_server, f"l_{kind}")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    if kind == "dragimage":
        _size_stages(page)
    q = page.locator("[data-question]").first
    if kind in ("choicegrid", "multigrid"):
        q.locator("tbody tr").nth(0).locator("input").nth(0).check()
        q.locator("tbody tr").nth(1).locator("input").nth(0).check()
    else:
        _drag(q, "alphakey", 0)
        _drag(q, "gammadis", 1)
    _check(q)
    q.locator(".question__verdict").wait_for(timeout=6000)
    if kind in ("choicegrid", "multigrid"):
        assert "is-incorrect" in q.locator("tbody tr").nth(1).get_attribute("class")
        # question.js re-wired the swapped-in scroll wrapper.
        assert q.locator("[data-scroll-x]").get_attribute("data-scroll-x-ready") == "1"
    else:
        assert q.locator(".dnd__chip").count() >= 3  # question.js re-enhanced
        targets = q.locator(".dnd__slot, .dragimage__target")
        assert "is-incorrect" in targets.nth(1).get_attribute("class")
        if kind == "dragimage":
            after = "t => (t.nextElementSibling || {}).textContent"
            assert targets.nth(1).evaluate(after) == "incorrect"
    assert (
        q.locator("[data-answer-key], [data-answer-switch], [data-reveal-btn]").count()
        == 0
    )


@pytest.mark.django_db(transaction=True)
def test_results_page_drag_ui_is_inert(browser, live_server):
    _student("d_res")
    course, unit, _ = _seed("d_res", "e2e-d-res", ["dragfill"], max_attempts=1)
    page = browser.new_context().new_page()
    _login(page, live_server, "d_res")
    page.goto(_quiz_url(live_server, course, unit))
    q = page.locator("[data-question]").first
    _drag(q, "gammadis", 1)
    _check(q)
    q.locator("[data-answer-switch]").wait_for(timeout=6000)
    page.once("dialog", lambda d: d.accept())
    page.locator("[data-finish-btn]").click()
    page.wait_for_url("**/results/**")
    row = page.locator(".quiz-results__item").first
    assert row.locator("[data-answer-yours] .dnd__slot").count() == 2  # dnd.js loaded
    before = _select_values(row, "[data-answer-yours]")
    row.locator("[data-answer-yours] .dnd__slot").nth(1).click(force=True)
    _drop(row.locator("[data-answer-yours] .dnd__slot").nth(1), "alphakey")
    assert _select_values(row, "[data-answer-yours]") == before
    switch = row.locator("[data-answer-switch]")
    pos = switch.bounding_box()
    row.locator("label:has([data-answer-view='key'])").click()
    assert (
        row.locator("[data-answer-key] .dnd__slot").nth(1).inner_text().strip()
        == "betakey"
    )
    after = switch.bounding_box()
    assert (after["x"], after["y"]) == (pos["x"], pos["y"])  # P5: the switch stays
    # P5 without JS: dnd.js never unhides the chip pool, whose bottom margin
    # otherwise masks the key wrapper's own (it collapses through the wrapper, but
    # stays inside the "yours" fieldset) -- so only here does the key-copy
    # wrapper's inline margin:0 keep the switch still.
    nojs = browser.new_context(
        java_script_enabled=False, storage_state=page.context.storage_state()
    ).new_page()
    nojs.goto(page.url)
    row = nojs.locator(".quiz-results__item").first
    switch = row.locator("[data-answer-switch]")
    pos = switch.bounding_box()
    row.locator("label:has([data-answer-view='key'])").click()
    assert row.locator("[data-answer-key]").is_visible()
    after = switch.bounding_box()
    assert (after["x"], after["y"]) == (pos["x"], pos["y"])


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("unit_type", ["quiz", "lesson"])
@pytest.mark.parametrize("kind", ["dragfill", "matchpair", "dragimage", "choicegrid"])
def test_editor_try_it_rebuilds_the_controls(browser, live_server, kind, unit_type):
    # Spec §2.4: editor.js's try-it branch re-enhances drag roots and re-wires grid
    # scroll wrappers after its swap, in quiz and lesson mode.
    from courses.models import Element
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.reveal_pr2_kit import build
    from tests.test_e2e_questions import _editor_url
    from tests.test_e2e_questions import _make_pa_user

    user = f"pa_{kind}_{unit_type}"
    owner = _make_pa_user(user)
    course = CourseFactory(owner=owner, slug=f"e2e-ed-{kind}-{unit_type}")
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type=unit_type, parent=None, title="E"
    )
    kit = build(kind, max_attempts=2)
    Element.objects.create(unit=unit, content_object=kit.question)
    page = browser.new_context().new_page()
    _login(page, live_server, user)
    page.goto(_editor_url(live_server, unit))
    if kind == "dragimage":
        _size_stages(page)
    q = page.locator("[data-scope='preview'] [data-question]").first
    if kind == "choicegrid":
        q.locator("tbody tr").nth(0).locator("input").nth(0).check()
        q.locator("tbody tr").nth(1).locator("input").nth(0).check()
    else:
        _drag(q, "alphakey", 0)
        _drag(q, "gammadis", 1)
    _check(q)
    q.locator(".question__verdict").wait_for(timeout=6000)
    if kind == "choicegrid":
        wrap = q.locator("[data-answer-yours] [data-scroll-x]")
        assert wrap.get_attribute("data-scroll-x-ready") == "1"  # editor.js re-wired
        assert "is-incorrect" in q.locator("[data-answer-yours] tbody tr").nth(
            1
        ).get_attribute("class")
    else:
        assert q.locator("[data-answer-yours] .dnd__chip").count() >= 3  # re-enhanced
        targets = q.locator(
            "[data-answer-yours] .dnd__slot, [data-answer-yours] .dragimage__target"
        )
        assert "is-incorrect" in targets.nth(1).get_attribute("class")
        if kind == "dragimage":
            after = "t => (t.nextElementSibling || {}).textContent"
            assert targets.nth(1).evaluate(after) == "incorrect"
    if unit_type == "quiz":
        page.once("dialog", lambda d: d.accept())
        q.locator("[data-reveal-btn]").click()
        q.locator("[data-answer-switch]").wait_for(timeout=6000)
        assert q.locator("[data-answer-view='key']").is_enabled()
        if kind != "choicegrid":
            before = _select_values(q, "[data-answer-yours]")
            targets = q.locator(
                "[data-answer-yours] .dnd__slot, [data-answer-yours] .dragimage__target"
            )
            targets.nth(0).click(force=True)
            _drop(targets.nth(0))
            assert _select_values(q, "[data-answer-yours]") == before
