"""The user-visible pin for this change: a callout with children and a callout
with only text must be the same width, and so must every question card.

MANDATORY as e2e, not a render test: the server emits no computed style, and a
cascade defect leaves the rendered HTML byte-identical.
"""

import os

import pytest

from tests.factories import TEST_PASSWORD  # noqa: F401 -- used by the copied _login
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element
from tests.factories import make_verified_user  # noqa: F401 -- used by _make_pa_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


# Copied VERBATIM from tests/test_e2e_callout_container.py (same PA-user helper,
# same login-form drive), which copied them from tests/test_e2e_depth3.py.
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


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _lesson_url(live_server, unit):
    from django.urls import reverse

    path = reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    return f"{live_server.url}{path}"


# A title whose max-content width runs well past the 736px prose cap. Since the
# <h1> sits in .lesson-unit__heading at `flex: 0 1 auto` it shrink-wraps to its own
# content, so only a title this wide is held by the cap at all; with the factory's
# short "Node N" the cap assertion below would pass no matter what the CSS says.
WIDE_TITLE = (
    "Przedzialy liczbowe i dzialania na przedzialach oraz ich zastosowania w zadaniach"
)


def _seed_unit(username, title=None):
    """`title=None` keeps ContentNodeFactory's short sequence title ("Node N").

    Shared with the three-item test, which must keep that default -- only the
    two-item cap test needs a title wider than the prose cap.
    """
    user = _make_pa_user(username)
    course = CourseFactory(owner=user)
    kw = {} if title is None else {"title": title}
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson", **kw
    )
    return user, course, unit


# The article is `.lesson` on a lesson page and `.quiz` on a quiz page, and
# getBoundingClientRect() returns the BORDER box -- reading the article's own box
# gives 920, not the 872 its children see. Hence clientWidth minus padding.
COLUMN_JS = """() => {
  const a = document.querySelector('.quiz, .lesson');
  const s = getComputedStyle(a);
  return a.clientWidth - parseFloat(s.paddingLeft) - parseFloat(s.paddingRight);
}"""

# Takes the selector as an ARGUMENT rather than interpolating it into the source:
# an f-string carrying JS braces has to double every one of them, and a single
# missed pair is a SyntaxError at evaluate() time, not a failed assertion.
BOX_JS = """(sel) => {
  const e = document.querySelector(sel);
  if (!e) return null;
  return {w: e.getBoundingClientRect().width,
          c: e.clientWidth, s: e.scrollWidth};
}"""


def _width(page, sel):
    box = page.evaluate(BOX_JS, sel)
    assert box is not None, f"{sel} is not present on the page"
    return box["w"]


def _uncapped_title_width(page):
    """The <h1>'s rendered width with the 46rem prose cap NEUTRALISED, restored after.

    This is the quantity that decides whether the cap is what holds the title down:
    min(the title's max-content width, the heading group's own line). There is no
    separate "content width" to read instead -- with the cap gone the <h1> is still
    `flex: 0 1 auto` inside .lesson-unit__heading, so getBoundingClientRect().width
    and scrollWidth both report that same minimum.

    page.add_style_tag returns an ElementHandle and the injected rule does NOT
    expire on its own; left in place it would neutralise the cap for the very
    assertion the guard protects. Hence the explicit remove() in `finally`.

    `!important` is required, not defensive: the cap selector is
    `html.unit-tree-collapsed [data-unit-shell] .lesson-unit__title`, specificity
    (0,3,1), which a bare `.lesson-unit__title` override at (0,1,0) loses to
    however late it is injected.
    """
    style = page.add_style_tag(
        content=".lesson-unit__title { max-width: none !important; }"
    )
    try:
        return _width(page, ".lesson-unit__title")
    finally:
        style.evaluate("e => e.remove()")


def _collapsed(page, live_server, unit):
    """Seed the collapsed state BEFORE first paint, then PROVE it took.

    The class is set by the TOC-pin JS from localStorage, never by the server.
    The explicit class assertion is not decoration: expanded, the column is 648px
    and every capped element also measures 648, so a pure equality test would pass
    in the wrong state.
    """
    page.set_viewport_size({"width": 1280, "height": 900})
    page.add_init_script("localStorage.setItem('libli_unit_tree_collapsed', '1');")
    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector("html.unit-tree-collapsed")
    assert page.evaluate(
        "() => document.documentElement.classList.contains('unit-tree-collapsed')"
    ), "not in the collapsed state; every width assertion below would be vacuous"


@pytest.mark.django_db(transaction=True)
def test_every_tinted_block_and_its_chrome_is_one_width(page, live_server):
    from courses.models import CalloutElement
    from courses.models import ChoiceGridQuestionElement
    from courses.models import Element
    from courses.models import ShortTextQuestionElement
    from courses.models import TableElement

    user, _course, unit = _seed_unit("pa_uniform")

    prose = CalloutElement.objects.create(kind="note", body="<p>prose only</p>")
    add_element(unit, prose)
    wide = CalloutElement.objects.create(kind="example", body="<p>with a table</p>")
    wide_join = add_element(unit, wide)
    Element.objects.create(
        unit=unit,
        content_object=TableElement.objects.create(
            data={"cells": [[{"html": "A"}, {"html": "B"}]]}
        ),
        parent=wide_join,
        tab_id=CalloutElement.SLOT_ID,
    )
    # A question element makes has_stateful_elements true, so .lesson-unit__reset
    # renders and the head is the THREE-item row the title comment below assumes.
    # This unit keeps _seed_unit's default short title on purpose -- see that
    # comment for why the two title assertions below are inert either way.
    add_element(
        unit,
        ShortTextQuestionElement.objects.create(stem="Name a prime.", accepted="7"),
    )
    add_element(unit, ChoiceGridQuestionElement.objects.create(stem="Grid?"))

    _login(page, live_server, user.username)
    _collapsed(page, live_server, unit)

    column = page.evaluate(COLUMN_JS)
    for sel in (
        ".callout:not(:has(> .callout__children))",
        ".callout:has(> .callout__children)",
        ".el--question:not(.el--choicegrid)",
        ".el--choicegrid",
        # Chrome that frames the cards. This is the one entry the spec flags as a
        # judgement call beyond the literal request, and the ONLY test that covers
        # it -- the quiz page now has a .lesson-unit__head too (it gained one with
        # the heading group), but nothing measures it there, and
        # test_e2e_unit_head_layout.py never collapses the TOC.
        ".lesson-unit__head",
    ):
        w = _width(page, sel)
        # Compared against the READ column, never a hard-coded 872: the derived
        # geometry moves whenever .app-main, the pin lane or the article padding does.
        assert abs(w - column) < 2, (
            f"{sel} is {w}, column is {column}; it must fill the column"
        )

    # The defect exactly as the user reported it.
    prose_w = _width(page, ".callout:not(:has(> .callout__children))")
    wide_w = _width(page, ".callout:has(> .callout__children)")
    assert abs(prose_w - wide_w) < 2, (
        f"the two callout shapes still differ: {prose_w} vs {wide_w}"
    )

    # INERT BY CONSTRUCTION -- read this before trusting it as coverage. This unit
    # has a question element, so has_stateful_elements is true and the head is a
    # THREE-item flex row (heading group | pill | reset), and it keeps the factory's
    # short "Node N" title. Inside .lesson-unit__heading the <h1> is `flex: 0 1 auto`,
    # so it shrink-wraps to that title's own content -- a few dozen pixels, an order
    # of magnitude below either bound: NO prose-cap mutation reddens either
    # assertion. They are a regression guard on the head keeping its pill and reset,
    # nothing more. The real pin on the title's cap is
    # test_lesson_title_caps_in_a_two_item_head below, which seeds a title whose
    # content is wider than the cap and guards that that is still true.
    title_w = _width(page, ".lesson-unit__title")
    assert title_w < 738, f"the title must stay within the prose cap, got {title_w}"
    assert title_w < column - 50, (
        f"the title must not fill the widened head: {title_w} vs column {column}"
    )


@pytest.mark.django_db(transaction=True)
def test_lesson_title_caps_in_a_two_item_head(page, live_server):
    """The pin the three-item test cannot carry.

    Seeds NO stateful element, so has_stateful_elements is false,
    .lesson-unit__reset does not render, and the head is a TWO-item row
    (heading group | pill). The group is `flex: 1 1 auto`, so it takes the whole
    remainder -- the head's ~872 less its 16px gap and the completion pill, which
    this arm MEASURED at ~756 (the uncapped <h1> reads 756.25px, so the pill is
    ~100 wide, not the ~110 an earlier version of this docstring assumed). Inside
    the group the <h1> is `flex: 0 1 auto` and shrink-wraps to its own content.
    WIDE_TITLE is therefore load-bearing: its max-content runs well past 756, so
    the <h1> is pressed against BOTH bounds and the smaller of them -- the 736 cap
    -- is what holds it down. Drop .lesson-unit__title from the prose-cap
    allow-list and the title springs to the group's ~756, reddening the assertion
    below.
    """
    from courses.models import CalloutElement

    user, _course, unit = _seed_unit("pa_title", title=WIDE_TITLE)
    add_element(
        unit,
        CalloutElement.objects.create(kind="note", body="<p>no stateful element</p>"),
    )

    _login(page, live_server, user.username)
    _collapsed(page, live_server, unit)

    assert page.locator(".lesson-unit__reset").count() == 0, (
        "the reset link renders, so this is a three-item head; the heading group "
        "would then be ~640 wide, under the cap, and the assertion below would be "
        "inert -- the fixture must seed no stateful element"
    )

    # Fixture-validity guard, then a DIRECTIONAL assertion. The guard is pointed
    # AT THE TITLE, not at the head's leftover space: since the <h1> shrink-wraps
    # inside the heading group, the space left beside the pill no longer says
    # anything about how wide the title wants to be, and a short-title fixture
    # would sail under 736 with the cap deleted. What decides the assertion below
    # is the width the <h1> takes with max-width neutralised, i.e.
    # min(its max-content, the group's ~756 line) -- so that is what is measured.
    #
    # The bound is `>= 740`, not `> 736`: the guarded assertion is `title_w < 738`,
    # so a fixture landing in (736, 738] would clear a `> 736` guard and still
    # leave that assertion green no matter what the cap does.
    #
    # Still deliberately not `abs(title_w - 736) < 2`: a wider pill -- a bigger
    # font, more padding, or a longer locale string such as the Polish "Oznacz jako
    # ukonczone" -- shrinks the group below 736, at which point the title is sized
    # by the group rather than the cap and an exact-token assertion would go RED on
    # correct CSS. The guard fails first and says so, instead of letting the arm
    # quietly stop testing anything.
    uncapped_w = _uncapped_title_width(page)
    assert uncapped_w >= 740, (
        f"this fixture no longer exercises the cap: with max-width neutralised the "
        f"title measures {uncapped_w}, at or under 736 plus the assertion's own "
        f"2px slack, so the cap is not what holds it down. Lengthen WIDE_TITLE, "
        f"widen the head, or shorten the pill."
    )
    title_w = _width(page, ".lesson-unit__title")
    assert title_w < 738, (
        f"the title must be held at the 46rem cap, got {title_w} "
        f"(uncapped it measures {uncapped_w})"
    )


@pytest.mark.django_db(transaction=True)
def test_prose_inside_a_widened_box_stays_capped(page, live_server):
    """The other half of the design: the BOX widens, its PROSE does not.

    All five newly-capped containers are measured here. Asserts the 736 token, not
    "narrower than its own box": both containers have padding, so a child is ALWAYS
    strictly narrower than its parent's border box, cap or no cap -- that assertion
    cannot fail and would read as a pin while proving nothing.

    Fixture and locator requirements, each load-bearing:
      - the container callout carries a non-empty body, because calloutelement.html
        renders .callout__body under `{% if el.body %}` -- a children-only callout
        has no body element and the locator would resolve to nothing;
      - the short-text card is located STRUCTURALLY. There is no `.el--shorttext`
        class: shorttextquestionelement.html emits a bare
        `<div class="el el--question" data-question>`, and only the five grid-ish
        types plus fillblank carry a type modifier. Scoping on the input is what
        makes the locator resolve;
      - the short-text question is ANSWERED below. Its .question__feedback div is
        NOT :empty (the `{% if %}` sits on its own line, leaving a whitespace text
        node), so it renders as a zero-height box with a real width -- one
        whitespace edit away from courses.css
        `.el--question .question__feedback:empty { display: none }`. Driving an
        answer means the arm measures a box with actual content, and the width is
        read via getBoundingClientRect (BOX_JS) rather than bounding_box(), which
        is unreliable on a zero-height element.

    The Choice rows are realistic content, not a width requirement: courses.css
    makes .question__choices a block <ul> with no width rule, so it fills its
    container with or without <li> children.
    """
    from courses.models import CalloutElement
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement
    from courses.models import Element
    from courses.models import ExtendedResponseQuestionElement
    from courses.models import ShortTextQuestionElement
    from courses.models import TableElement

    user, _course, unit = _seed_unit("pa_prose")

    body = CalloutElement.objects.create(kind="note", body="<p>explanatory text</p>")
    body_join = add_element(unit, body)
    Element.objects.create(
        unit=unit,
        content_object=TableElement.objects.create(
            data={"cells": [[{"html": "A"}, {"html": "B"}]]}
        ),
        parent=body_join,
        tab_id=CalloutElement.SLOT_ID,
    )
    add_element(
        unit,
        ExtendedResponseQuestionElement.objects.create(stem="<p>Explain briefly.</p>"),
    )
    mcq = ChoiceQuestionElement.objects.create(stem="<p>Pick one.</p>")
    Choice.objects.create(question=mcq, text="The first option", is_correct=True)
    Choice.objects.create(question=mcq, text="The second option", is_correct=False)
    add_element(unit, mcq)
    add_element(
        unit,
        ShortTextQuestionElement.objects.create(
            stem="<p>Name a prime.</p>", accepted="7"
        ),
    )

    _login(page, live_server, user.username)
    _collapsed(page, live_server, unit)

    # Drive a real answer so the feedback slot carries content. The short-text
    # card has no type modifier class, so scope it on the input it is the only
    # bearer of.
    st = "[data-question]:has(input.question__text-input)"
    st_card = page.locator(st)
    st_card.locator("input.question__text-input").fill("11")
    st_card.locator("button[type='submit']").click()
    # `arg` is keyword-only on wait_for_function (unlike evaluate, which takes it
    # positionally) -- passing it positionally raises TypeError, not a failed wait.
    page.wait_for_function(
        "(sel) => { const f = document.querySelector(sel + ' .question__feedback');"
        " return f && f.textContent.trim().length > 0; }",
        arg=st,
    )

    column = page.evaluate(COLUMN_JS)
    for sel in (
        ".callout__body",
        ".el--question .question__stem",
        ".question__choices",
        f"{st} .question__feedback",
        "textarea.question__text-input",
    ):
        w = _width(page, sel)
        assert abs(w - 736) < 2, f"{sel} must stay capped at 46rem, got {w}"
        assert w < column - 50, (
            f"{sel} is {w} against a column of {column} -- the cap is not binding"
        )


@pytest.mark.django_db(transaction=True)
def test_expanded_state_has_no_cap_at_all(page, live_server):
    """The Non-goal, pinned by COMPUTED STYLE rather than width.

    A width test here cannot fail: the expanded column is 648px, BELOW the 736px
    cap, so a rule that lost its html.unit-tree-collapsed prefix would change no
    measured width and the test would pass on its own mutant. maxWidth === 'none'
    is what the mutant actually reddens.
    """
    from courses.models import CalloutElement
    from courses.models import ChoiceGridQuestionElement
    from courses.models import ShortTextQuestionElement

    user, _course, unit = _seed_unit("pa_expanded")
    add_element(unit, CalloutElement.objects.create(kind="note", body="<p>t</p>"))
    add_element(
        unit,
        ShortTextQuestionElement.objects.create(stem="Name a prime.", accepted="7"),
    )
    # Both card shapes, per the spec. The grid card was never in the cap, so it is
    # the arm that would catch a NEW unscoped rule reaching a previously-uncapped
    # element -- a case the plain card cannot show.
    add_element(unit, ChoiceGridQuestionElement.objects.create(stem="Grid?"))

    page.set_viewport_size({"width": 1280, "height": 900})
    _login(page, live_server, user.username)
    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector("[data-unit-shell]")
    assert not page.evaluate(
        "() => document.documentElement.classList.contains('unit-tree-collapsed')"
    ), "this test must run EXPANDED; collapsed it proves nothing"

    for sel in (".callout", ".el--question:not(.el--choicegrid)", ".el--choicegrid"):
        mw = page.evaluate(
            "(s) => getComputedStyle(document.querySelector(s)).maxWidth", sel
        )
        assert mw == "none", f"{sel} has max-width {mw} in the expanded state"


@pytest.mark.django_db(transaction=True)
def test_short_answer_input_still_caps_at_22rem(page, live_server):
    """Specificity guard. The new entry MUST be `textarea.question__text-input`.

    Written with a bare class it still out-specifies
    `.quiz input.question__text-input` (courses.css) on the class
    component, and the single-line short-text/short-numeric boxes would silently
    jump from 352px to 736px.

    The collapsed assertion inside _collapsed() is mandatory here: the 22rem rule
    is unscoped, so the input measures 352 in BOTH states and the mutant diverges
    only collapsed.
    """
    from courses.models import ShortTextQuestionElement

    user, _course, unit = _seed_unit("pa_input")
    add_element(
        unit,
        ShortTextQuestionElement.objects.create(stem="Name a prime.", accepted="7"),
    )

    _login(page, live_server, user.username)
    _collapsed(page, live_server, unit)

    w = _width(page, "input.question__text-input")
    assert abs(w - 352) < 2, f"the short-answer input must stay at 22rem, got {w}"


@pytest.mark.django_db(transaction=True)
def test_grid_and_fieldset_stems_cap_without_squeezing_their_widgets(page, live_server):
    """Two behaviour changes the Purpose section does not mention, pinned so they
    are intentional rather than incidental.

    1. The five grid types were excluded from the cap entirely, so their stems
       filled the card's inner box (~830). They now cap at 736.
    2. fillblank and dragfill put their widget INSIDE a `<fieldset class=
       "question__stem">`. A fieldset defaults to min-inline-size: min-content,
       which can refuse a max-width. MEASURED at spec time: it does not here --
       both stems bind at 736 and neither overflows (B0). This is the pin for
       that, so a future content or layout change that breaks it is caught.

    The choicegrid fixture MUST have a non-empty stem AND real columns/rows:
    choicegridquestionelement renders .question__stem under `{% if el.stem %}`, and
    render_choice_grid iterates el.columns/el.rows -- with neither seeded the table
    is an empty <thead><th></th></thead><tbody></tbody>.
    """
    from courses.models import Blank
    from courses.models import ChoiceGridQuestionElement
    from courses.models import DragBlank
    from courses.models import DragFillBlankQuestionElement
    from courses.models import FillBlankQuestionElement
    from courses.models import GridColumn
    from courses.models import GridRow

    user, _course, unit = _seed_unit("pa_stems")

    grid = ChoiceGridQuestionElement.objects.create(stem="Pick one per row.")
    cols = [
        GridColumn.objects.create(question=grid, label=label)
        for label in (
            "Strongly agree",
            "Agree",
            "Neither agree nor disagree",
            "Disagree",
            "Strongly disagree",
        )
    ]
    for statement in (
        "The first statement under consideration here",
        "The second statement under consideration here",
    ):
        GridRow.objects.create(
            question=grid, statement=statement, correct_column=cols[0]
        )
    add_element(unit, grid)

    gapped = (
        "The capital of France is ￿0￿, which stands on the "
        "￿1￿, and the capital of Italy is ￿2￿, which "
        "stands on the ￿3￿ river in central Europe."
    )
    fb = FillBlankQuestionElement.objects.create(stem=gapped)
    for i, ans in enumerate(("Paris", "Seine", "Rome", "Tiber")):
        Blank.objects.create(question=fb, order=i, accepted=ans)
    add_element(unit, fb)

    df = DragFillBlankQuestionElement.objects.create(
        stem=gapped, distractors="Madrid\nLisbon\nDanube\nVistula\nBerlin\nWarsaw"
    )
    for tok in ("Paris", "Seine", "Rome", "Tiber"):
        DragBlank.objects.create(question=df, correct_token=tok)
    add_element(unit, df)

    _login(page, live_server, user.username)
    _collapsed(page, live_server, unit)

    # The pool ships `hidden` and EMPTY -- dnd.js reveals and fills it. Reading
    # before that returns clientWidth 0, which would satisfy "no overflow" and
    # fabricate a pass. Sync first, then assert it is genuinely live.
    page.wait_for_selector(".el--dragfill [data-dnd-pool]:not([hidden])")
    page.wait_for_function(
        "() => document.querySelectorAll('.el--dragfill .dnd__chip').length > 0"
    )
    pool = page.evaluate(BOX_JS, ".el--dragfill .dnd__pool")
    assert pool is not None and pool["c"] > 0, (
        f"INVALID: the pool is not live, the measurement is void: {pool}"
    )

    grid_stem = _width(page, ".el--choicegrid .question__stem")
    scroll_x = _width(page, ".el--choicegrid .scroll-x")
    assert abs(grid_stem - 736) < 2, f"grid stem must cap at 46rem, got {grid_stem}"
    # Directional. .scroll-x is the edge-shading wrapper (it does not itself scroll
    # -- the inner .choicegrid-scroll does) and the bare <fieldset> around it has no
    # min-inline-size: 0, so its width is not pinned to the card's inner box. A
    # generous constant here would be the fragility this suite bans.
    assert scroll_x > grid_stem + 2, (
        f"the grid widget must stay wider than the capped stem: "
        f"scroll-x {scroll_x} vs stem {grid_stem}"
    )

    for sel in (".el--fillblank .question__stem", ".el--dragfill .question__stem"):
        box = page.evaluate(BOX_JS, sel)
        assert box is not None, f"{sel} is not present"
        assert abs(box["w"] - 736) < 2, (
            f"{sel}: the fieldset min-inline-size floor refused the cap: {box}"
        )
        assert box["s"] <= box["c"] + 1, f"{sel} overflows horizontally: {box}"
