"""Playwright e2e for the collapsible course outline (spec T6-T19).

Real browser gestures only. Marked `e2e` (run with -m e2e).

FOLD ASSERTIONS USE checkVisibility(), NEVER to_be_hidden(): Playwright's
visibility contract is "non-empty bounding box and not visibility:hidden", and a
closed <details> keeps a STALE non-zero rect — this repo measured exactly that in
tests/test_e2e_unit_nav.py. Worse, it is state-dependent: content never laid out
may report 0x0 and pass, while the same assertion after a real fold gesture
fails. to_be_hidden() IS correct for the tag filter's [hidden] rows, which are
display:none, and is used for exactly those.
"""

import json
import os
import re

import pytest
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _course_with_two_chapters(username="outliner"):
    """part > (chapter A > unit A1) + (chapter B > unit B1), plus a depth-0 unit.

    Every container holds a visible unit, or build_outline's pruning drops it
    before the template ever sees it. The depth-0 unit pins the mixed shape:
    units and containers coexist at the same depth, so "top level open" cannot
    mean "show only containers".
    """
    from courses.models import Enrollment
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    user = make_verified_user(
        username=username,
        email=f"{username}@test.example.com",
        password=TEST_PASSWORD,
    )
    course = CourseFactory(title="Algebra")
    Enrollment.objects.create(student=user, course=course)
    part = ContentNodeFactory(course=course, kind="part", unit_type=None, parent=None)
    chap_a = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=part, title="Chapter A"
    )
    chap_b = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=part, title="Chapter B"
    )
    unit_a = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=chap_a, title="Unit A1"
    )
    unit_b = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=chap_b, title="Unit B1"
    )
    root_unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="Root Unit"
    )
    return {
        "user": user,
        "course": course,
        "part": part,
        "chap_a": chap_a,
        "chap_b": chap_b,
        "unit_a": unit_a,
        "unit_b": unit_b,
        "root_unit": root_unit,
    }


def _title_sel(node_pk):
    """The clickable title span of ONE group.

    `[data-node='N'] .outline-node__title` is a descendant selector, and a
    container's <details> contains every descendant group's title too — on a part
    it resolves to three spans and .click() raises a strict-mode violation.
    Scoping through `> summary` keeps it to exactly one, at any depth.
    """
    return f"[data-node='{node_pk}'] > summary .outline-node__title"


def _visible(page, selector):
    """checkVisibility() — see the module docstring for why not to_be_hidden()."""
    return page.evaluate(
        "sel => { const el = document.querySelector(sel);"
        "         return !!el && el.checkVisibility(); }",
        selector,
    )


def _is_open(page, node_pk):
    return page.evaluate(
        "pk => document.querySelector(`[data-node='${pk}']`).open", str(node_pk)
    )


def _has_open_attr(page, node_pk):
    """Attribute read, for contexts where page.evaluate is unavailable (JS off)."""
    return page.locator(f"[data-node='{node_pk}']").get_attribute("open") is not None


def _stored(page):
    return page.evaluate(
        "() => { const k = Object.keys(localStorage)"
        ".find(x => x.startsWith('libli_outline_open:'));"
        "        return k ? localStorage.getItem(k) : null; }"
    )


def _wait_for_write(page):
    """Persistence runs inside setTimeout(write, 0) because <summary> activation
    is post-dispatch. Any reload that races it fails intermittently on a CORRECT
    build — the worst thing to debug a mutant against."""
    page.wait_for_function(
        "() => Object.keys(localStorage).some("
        "  k => k.startsWith('libli_outline_open:'))"
    )


@pytest.mark.django_db(transaction=True)
def test_first_visit_opens_depth0_only(page, live_server):
    """T6 + T7. Mutant: render every <details> open."""
    f = _course_with_two_chapters("t7")
    _login(page, live_server, "t7")
    page.goto(f"{live_server.url}/courses/{f['course'].slug}/")

    # The attribute half is what actually pins D1; a visibility-only assertion
    # also passes under a stray display:none.
    assert _is_open(page, f["part"].pk) is True
    assert _is_open(page, f["chap_a"].pk) is False

    assert _visible(page, f"[data-node='{f['chap_a'].pk}'] > summary")
    assert not _visible(page, f"#node-{f['unit_a'].pk}")
    # Mixed shape: a depth-0 unit row is an ordinary row, always visible.
    assert _visible(page, f"#node-{f['root_unit'].pk}")

    # T6: the computed ACCESSIBLE NAME, not DOM text — a text assertion would
    # merely duplicate the render-tier T3. Do NOT use get_by_role("button", ...):
    # <summary> has no entry in Playwright's implicit-role table, so that locator
    # resolves to ZERO elements and fails on a correct build. Nor
    # page.accessibility.snapshot(), which no longer exists in this version.
    # Only the negative assertion discriminates: under the T6 mutant the name
    # becomes "Chapter A 0/1 required Start fresh", which still matches
    # ^Chapter A. The positive one is a liveness check that the locator resolves
    # and the name is computed at all.
    summary = page.locator(f"[data-node='{f['chap_a'].pk}'] > summary")
    expect(summary).to_have_accessible_name(re.compile(r"^Chapter A"))
    expect(summary).not_to_have_accessible_name(re.compile("Start fresh"))


@pytest.mark.django_db(transaction=True)
def test_fold_state_survives_a_round_trip(page, live_server):
    """T8. Mutant: take the snapshot SYNCHRONOUSLY inside the click handler
    instead of inside setTimeout(..., 0) — it reads the pre-click state, so the
    newly-opened chapter is absent from the stored `open` array."""
    f = _course_with_two_chapters("t8")
    _login(page, live_server, "t8")
    page.goto(f"{live_server.url}/courses/{f['course'].slug}/")

    # Click the TITLE SPAN, not the summary's padding: that click target is what
    # falsifies an e.target.matches() implementation.
    page.locator(_title_sel(f["chap_a"].pk)).click()
    expect(page.locator(f"#node-{f['unit_a'].pk}")).to_be_visible()
    _wait_for_write(page)

    # Assert on the "open" ARRAY, not on the raw JSON string: under the mutant
    # chap_a's pk lands in "closed", so its digits are still in the blob and a
    # substring test passes. (It is pk-fragile too — "4" is in '["14"]'.)
    # The round
    # trip below can be served from Chromium's back/forward cache — nothing in
    # this project sends Cache-Control: no-store — which restores the live DOM
    # WITHOUT re-running outline_tree.js, leaving the chapter open regardless of
    # what was persisted and turning the mutant green.
    assert str(f["chap_a"].pk) in json.loads(_stored(page))["open"]

    page.locator(f"#node-{f['unit_a'].pk} a.outline-unit").click()
    page.wait_for_url(f"**/u/{f['unit_a'].pk}/")
    page.go_back()
    page.reload()  # defeats bfcache: forces a real re-run of the restore path

    assert _is_open(page, f["chap_a"].pk) is True
    assert _is_open(page, f["chap_b"].pk) is False


@pytest.mark.django_db(transaction=True)
def test_expand_all_then_collapse_all(page, live_server):
    """T9. Mutant: make write() a no-op in the toggle-all click handler — the
    reload assertion below goes red. (The separate "label set inline in the click
    handler instead of via syncLabel" mutant belongs to T14, not here.)"""
    f = _course_with_two_chapters("t9")
    _login(page, live_server, "t9")
    page.goto(f"{live_server.url}/courses/{f['course'].slug}/")

    button = page.locator("[data-outline-toggle-all]")
    expect(button).to_be_visible()
    expect(button).to_have_text("Expand all")

    button.click()
    expect(page.locator(f"#node-{f['unit_a'].pk}")).to_be_visible()
    expect(page.locator(f"#node-{f['unit_b'].pk}")).to_be_visible()
    expect(button).to_have_text("Collapse all")

    _wait_for_write(page)
    page.reload()
    assert _is_open(page, f["chap_a"].pk) is True

    page.locator("[data-outline-toggle-all]").click()
    # Collapse all folds depth 0 too.
    assert _is_open(page, f["part"].pk) is False


def _tag_a_unit(user, unit, name="exam"):
    """The tag MUST be authored by the logged-in student: tags_for_outline filters
    on tag__author=request.user, so a tag owned by anyone else leaves filter_chips
    empty, _tags_filter_bar.html renders nothing, tags.js runs setupFilter only
    `if (bar)` — and every filter assertion below becomes vacuous."""
    from tags.models import Tag
    from tags.models import UnitTag

    tag = Tag.objects.create(author=user, name=name)
    UnitTag.objects.create(tag=tag, unit=unit)
    return tag


@pytest.mark.django_db(transaction=True)
def test_filter_unfolds_matches_and_clearing_restores_the_fold_state(page, live_server):
    """T10 — the R1 guard, the single most damaging thing this feature could get
    wrong: a student's fold state silently destroyed by using the tag filter, with
    the damage only visible after they clear it.

    TWO SEPARATE MUTANTS, because this test guards two different failures.

    (1) The persistence mutant MUST BE TWO-PART: persist inside a `toggle` handler
    AND remove the filterActive write guard. Moving persistence onto `toggle`
    alone does NOT redden this — the suppression still blocks writes during the
    filtered phase, and the post-clear programmatic toggles merely re-write the
    restored state.

    (2) The §6.2 specificity mutant, for the `to_be_hidden()` assertion below:
    change `.outline-node--part, .outline-node--chapter, .outline-node--section
    { display: grid; ... }` to `.outline-tree .outline-node.outline-node--part,
    ...` (three simple selectors, (0,3,0)). A merely (0,2,0) variant — e.g.
    `.outline-tree .outline-node--part, ...` — does NOT redden this: it ties
    `.outline-node[hidden]`'s (0,2,0) exactly, and a CSS specificity tie is
    broken by source order, not left unresolved — `.outline-node[hidden]` is
    declared later in app.css (line ~633 vs. the grid rule at ~576), so it
    keeps winning and containers stay hidden. The real guard is two-part: do
    not out-specify (0,2,0) for this rule, AND do not move it below the
    `[hidden]` guard in the file. Nothing else in the suite catches this.
    """
    f = _course_with_two_chapters("t10")
    tag = _tag_a_unit(f["user"], f["unit_b"])
    _login(page, live_server, "t10")
    page.goto(f"{live_server.url}/courses/{f['course'].slug}/")

    # Open chapter A, leave B folded — this is the state that must survive.
    page.locator(_title_sel(f["chap_a"].pk)).click()
    expect(page.locator(f"#node-{f['unit_a'].pk}")).to_be_visible()
    _wait_for_write(page)
    before = _stored(page)

    page.locator(f"a.tag-chip[data-tag-id='{tag.pk}']").click()
    # The match lives inside folded chapter B: it must become visible.
    expect(page.locator(f"#node-{f['unit_b'].pk}")).to_be_visible()
    expect(page.locator("[data-outline-toggle-all]")).to_be_disabled()
    # A tag_hidden CONTAINER row must compute hidden. This is the guard against
    # §6.2's `display: grid` out-specifying `.outline-node[hidden] {display:none}`
    # (0,2,0) — today's e2e proves that only for a unit row. to_be_hidden() is
    # correct here: these rows are display:none, not folded content. See the
    # class docstring: the mutant that reddens this must clear (0,2,0) outright
    # (e.g. (0,3,0)) — a merely-tied (0,2,0) variant loses on source order to
    # the later-declared `.outline-node[hidden]` and this assertion stays green.
    expect(page.locator(f"#node-{f['chap_a'].pk}")).to_be_hidden()

    page.locator(f"a.tag-chip[data-tag-id='{tag.pk}']").click()
    assert _is_open(page, f["chap_a"].pk) is True
    assert _is_open(page, f["chap_b"].pk) is False, "the pre-filter fold state returns"
    assert _stored(page) == before, "the forced-open state was never persisted"
    expect(page.locator("[data-outline-toggle-all]")).to_be_enabled()


@pytest.mark.django_db(transaction=True)
def test_clearing_a_filter_with_no_stored_key_returns_to_the_default(page, live_server):
    """T11. The load path and the filter-clear restore have OPPOSITE rules for a
    missing key: load leaves the DOM alone, restore treats it as an empty
    partition and drives every group from data-depth. Sharing one rule leaves a
    first-visit student with a fully force-opened tree.

    Mutant: make the restore a no-op when the key is absent."""
    f = _course_with_two_chapters("t11")
    tag = _tag_a_unit(f["user"], f["unit_b"])
    _login(page, live_server, "t11")
    page.goto(f"{live_server.url}/courses/{f['course'].slug}/")

    assert _stored(page) is None, "never written — this is the whole point"

    page.locator(f"a.tag-chip[data-tag-id='{tag.pk}']").click()
    expect(page.locator(f"#node-{f['unit_b'].pk}")).to_be_visible()

    page.locator(f"a.tag-chip[data-tag-id='{tag.pk}']").click()
    assert _is_open(page, f["chap_b"].pk) is False, "back to the D1 default"


@pytest.mark.django_db(transaction=True)
def test_a_filtered_deep_link_load_never_writes_storage(page, live_server):
    """T12. filterActive must be seeded from the PAGE at init, not from the
    libli:tagfilter event — that event arrives after the deep-link handler has
    already run and written.

    Mutant: seed filterActive only from the libli:tagfilter event instead of at
    init — the storage assertion reddens.

    NOT a mutant: dropping `button.disabled = filterActive` from init step 2. On
    a ?tags=N load tags.js's setupFilter ends with an unconditional
    applyFilter(active), dispatching count:1, and §5's count>0 branch sets
    disabled anyway — so the end state is identical and to_be_disabled() (which
    retries) can never see the difference. The init assignment is
    defence-in-depth with no independent e2e observable; do not go looking for
    one.
    """
    f = _course_with_two_chapters("t12")
    tag = _tag_a_unit(f["user"], f["unit_b"])
    _login(page, live_server, "t12")
    page.goto(
        f"{live_server.url}/courses/{f['course'].slug}/"
        f"?tags={tag.pk}#node-{f['chap_b'].pk}"
    )

    expect(page.locator(f"#node-{f['unit_b'].pk}")).to_be_visible()
    expect(page.locator("[data-outline-toggle-all]")).to_be_disabled()
    assert _stored(page) is None, "the server's force-opened tree must not persist"


@pytest.mark.django_db(transaction=True)
def test_deep_link_opens_the_target_and_its_ancestors(page, live_server):
    """T13 cases (a) and (b). Case (c) lives in its own test below, because its
    precondition is an EMPTY store that these cases would have populated.

    (a) Dropping the ancestor-opening loop does NOT redden in Chromium —
        MEASURED (Chromium 148.0.7778.96 via Playwright 1.60.0): the browser
        natively re-opens a folded ancestor `<details>` to reveal a
        fragment-navigation target, so `chap_b` ends up open with the JS loop
        removed entirely, regardless of fixture depth. Do NOT delete the loop
        on the strength of this test — spec §4.4 requires it for engines
        without that native behaviour, and it is what makes the write at the
        end of openHashTarget() correct.

        THREE container levels deep is kept by ruling (spec §4.4), not
        because it rescues the ancestor-loop mutant — it doesn't, for the
        reason above, independent of depth. What the extra level actually
        buys: a target (`section`) that is itself a NESTED container, so
        "the target's own `<details>` opens" and the `:target` highlight are
        exercised on a container reached through a real intermediate
        ancestor (`chap_b`, server-FOLDED), not just a depth-0 part. The two
        mutants below DO redden and are the real evidence the handler runs:
        open the ancestors but not the target's own `<details>` (this is
        what `assert _is_open(page, section.pk) is True` guards, plus T13(c)
        separately covers the count===0 restore guard); and dropping the
        `:target` twin from app.css.
    (b) A #node-<unit-pk> owns no <details> — id="node-N" is on EVERY <li>.
        Mutant: unconditional li.querySelector(":scope > details").open = true.

    Scroll-into-view is deliberately NOT asserted: this fixture renders ~6 rows
    in a 1280x720 viewport, so nothing scrolls and a getBoundingClientRect check
    would pass whether or not scrollIntoView ran. §4.4's scroll is covered by the
    screenshot gate instead.
    """
    from tests.factories import ContentNodeFactory

    f = _course_with_two_chapters("t13")
    section = ContentNodeFactory(
        course=f["course"],
        kind="section",
        unit_type=None,
        parent=f["chap_b"],
        title="Deep Section",
    )
    ContentNodeFactory(
        course=f["course"],
        kind="unit",
        unit_type="lesson",
        parent=section,
        title="Deep Unit",
    )
    _login(page, live_server, "t13")

    page.goto(f"{live_server.url}/courses/{f['course'].slug}/#node-{section.pk}")
    assert _is_open(page, f["part"].pk) is True
    # chap_b is depth 1, so the server rendered it FOLDED. In THIS browser that
    # is Chromium's own native fragment-navigation reveal, not proof the JS
    # ancestor loop ran — see the class docstring's confirmed limitation.
    assert _is_open(page, f["chap_b"].pk) is True, "a folded ancestor was opened"
    assert _is_open(page, section.pk) is True, "the target's OWN details opens"

    # The :target highlight must land on a container reached through
    # outline_tree.js's own deep-link path — the string assertion in
    # test_outline_anchors.py cannot prove that. Mirrors test_e2e_link_dialog.py.
    bg = page.locator(f"[data-node='{section.pk}'] > summary").evaluate(
        "el => getComputedStyle(el).backgroundColor"
    )
    assert bg not in ("rgba(0, 0, 0, 0)", "transparent")

    # (b) a unit-pk hash owns no <details> — it must not throw. The visibility
    # line is a liveness check (root_unit is depth 0 and visible either way), NOT
    # the discriminator; `errors == []` is.
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{live_server.url}/courses/{f['course'].slug}/#node-{f['root_unit'].pk}")
    expect(page.locator(f"#node-{f['root_unit'].pk}")).to_be_visible()
    # Wait for the effect the mutant produces rather than reading immediately: a
    # fragment navigation fires no load event, so nothing above synchronises with
    # the handler at all.
    page.wait_for_timeout(200)
    assert errors == [], f"deep link to a unit row threw: {errors}"


@pytest.mark.django_db(transaction=True)
def test_deep_link_survives_a_failing_storage_write(page, live_server):
    """T13(c) — the count===0 guard, in its OWN test because the spec's
    precondition is "no stored key". Run inside the test above, cases (a)/(b)
    would already have written a partition; with the guard removed the handler
    would then re-open the target FROM STORAGE and pass on the broken build.
    Stubbing setItem blocks new writes but does not clear an existing key, so
    getItem is stubbed too.

    Mutant: remove the `if (!filterActive) return;` guard in the count===0 branch.
    """
    f = _course_with_two_chapters("t13c")
    # Renders the filter bar, without which tags.js never calls setupFilter and
    # no libli:tagfilter event fires at all — the case would be vacuous.
    _tag_a_unit(f["user"], f["unit_b"], name="rev")
    _login(page, live_server, "t13c")
    page.add_init_script(
        "Object.defineProperty(Storage.prototype, 'setItem', "
        "{value: () => { throw new Error('denied'); }});"
        "Object.defineProperty(Storage.prototype, 'getItem', {value: () => null});"
    )
    page.goto(f"{live_server.url}/courses/{f['course'].slug}/#node-{f['chap_b'].pk}")

    assert _is_open(page, f["chap_b"].pk) is True, (
        "tags.js dispatches count:0 on every unfiltered load that renders a filter "
        "bar; without the guard it slams the just-opened ancestors shut"
    )


@pytest.mark.django_db(transaction=True)
def test_label_tracks_a_single_summary_toggle(page, live_server):
    """T14 — the R3 guard. Mutant: register the toggle listener without
    capture:true. `toggle` does not bubble, so a plain delegated listener never
    fires and the label silently stops updating.

    T9 alone cannot catch this: an implementation that sets the label inline in
    the button handler passes T9 with no toggle listener at all.

    NOT the toggle-all button, even for setup — MEASURED: a
    button.click()-then-close-one-summary design (the original shape here)
    cannot discriminate this mutant. syncLabel's output is a boolean ("any group
    closed?"), so "expand all, then close one via a summary click" is a round
    trip back to the SAME "Expand all" text the page starts with. Under the
    mutant the label never updates at all (confirmed: it reads "Expand all"
    both immediately after the button click and after the summary click), and
    under a correct build two genuine updates land and cancel out to the exact
    same string — both builds show identical final text, so a final-state-only
    assertion passes on both. Two summary gestures instead, opening
    (not closing), so the transition is monotonic and cannot cancel out: open
    chap_b first (setup, synced on unit_b's visibility, not on the label — this
    step's expected label is unchanged either way and would prove nothing), then
    open chap_a (the discriminator) — the only remaining closed group, so this
    is the first and only gesture that can flip the label to "Collapse all".
    Under the mutant the label is stuck at "Expand all" and this assertion
    reddens cleanly; under a correct build it is the summary listener, and only
    the summary listener, that gets it to "Collapse all"."""
    f = _course_with_two_chapters("t14")
    _login(page, live_server, "t14")
    page.goto(f"{live_server.url}/courses/{f['course'].slug}/")

    button = page.locator("[data-outline-toggle-all]")

    # Setup: open chap_b directly via its summary — not the discriminator, so
    # synced on structure (unit_b becoming visible), not on the label.
    page.locator(_title_sel(f["chap_b"].pk)).click()
    expect(page.locator(f"#node-{f['unit_b'].pk}")).to_be_visible()

    # The discriminator: opening chap_a is the ONLY remaining closed group, so
    # this single summary gesture is what flips the label to "Collapse all".
    page.locator(_title_sel(f["chap_a"].pk)).click()
    expect(button).to_have_text("Collapse all")


@pytest.mark.django_db(transaction=True)
def test_storage_partition_semantics(page, live_server):
    """T15, four cases."""
    from tests.factories import ContentNodeFactory

    f = _course_with_two_chapters("t15")
    # A second depth-0 root, holding a visible unit so pruning keeps it.
    root_b = ContentNodeFactory(
        course=f["course"], kind="part", unit_type=None, parent=None, title="Part Two"
    )
    ContentNodeFactory(
        course=f["course"], kind="unit", unit_type="lesson", parent=root_b, title="P2U"
    )
    _login(page, live_server, "t15")
    url = f"{live_server.url}/courses/{f['course'].slug}/"
    key = f"libli_outline_open:{f['course'].slug}"

    # (a) a deliberately collapsed depth-0 root stays collapsed.
    # Mutant: union the stored set with the server default.
    page.goto(url)
    page.locator(_title_sel(f["part"].pk)).click()
    _wait_for_write(page)  # the write is deferred; reloading before it races it
    page.reload()
    assert _is_open(page, f["part"].pk) is False

    # (b) a group in NEITHER array is new since the last write: it falls back to
    # its data-depth default rather than to "closed".
    page.evaluate(
        "([k, pk]) => localStorage.setItem(k, JSON.stringify("
        "{v: 1, open: [], closed: [String(pk)]}))",
        [key, f["part"].pk],
    )
    # Mutant: treat an id in neither array as closed.
    page.reload()
    assert _is_open(page, root_b.pk) is True, "omitted depth-0 root uses data-depth"

    # (c) numeric ids must still apply. The seed CONTRADICTS the default (a
    # depth-1 chapter stored open, default closed), or the case is vacuous.
    # Mutant: drop String() on the read side only.
    page.evaluate(
        "([k, pk]) => localStorage.setItem(k, JSON.stringify("
        "{v: 1, open: [Number(pk)], closed: []}))",
        [key, f["chap_a"].pk],
    )
    page.reload()
    assert _is_open(page, f["chap_a"].pk) is True, "numeric ids normalise via String()"

    # (d) unparseable -> treat as absent, render the server default, never throw.
    # Mutant: drop the try/catch around JSON.parse in read().
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.evaluate("k => localStorage.setItem(k, 'not json')", key)
    page.reload()
    assert _is_open(page, f["part"].pk) is True
    assert errors == []


@pytest.mark.django_db(transaction=True)
def test_start_fresh_link_does_not_disturb_the_fold_state(page, live_server):
    """T16. Fold first, so the baseline is a real non-empty partition — without
    that, "before" and "after" are both None and the assertion compares absence
    to absence.

    The reset navigation is ABORTED by a route handler rather than followed, so
    the assertions below can read the live page instead of racing a real
    navigation. A bare route.abort() is NOT equivalent: MEASURED (Chromium
    148.0.7778.96 via Playwright 1.60.0) — the default error code ("failed",
    net::ERR_FAILED) does not leave this page intact. Chromium commits a
    chrome-error://chromewebdata/ document over the live DOM once the aborted
    top-level navigation fails, and every assertion below throws on a null
    querySelector, on a correct build as much as a broken one. errorCode=
    "aborted" (net::ERR_ABORTED) is the one Chromium treats as a cancelled
    navigation rather than a failed load, so it leaves the current document in
    place — this argument is load-bearing, not decoration; do not "simplify" it
    back to a bare abort().

    This test's named mutant (move the reset link back inside the <summary>)
    CANNOT REDDEN IN CHROMIUM — MEASURED (same versions as above, via a
    temporary capture-phase `toggle` counter): clicking the nested link fires
    ZERO toggle events. A click target that is itself an interactive element
    with its own defined activation behaviour (an <a href>) suppresses the
    ancestor <summary>'s native disclosure-toggle activation — only the anchor's
    navigation activates. So under the mutant the group never toggles, the
    scheduled write() re-persists the SAME unchanged partition (stored value
    still equals `before`), and the nested link stays reachable by the very
    next Tab press regardless of open/closed state, since a <summary>'s own
    content is always visible independent of its <details>. Fold-state,
    stored-value and keyboard assertions all stay green on both builds.

    What this test IS, then, is a regression pin, not a falsifiable mutant
    guard: the reset link renders as a sibling of the <details> (not nested in
    the <summary>), carries the correct href, is keyboard-reachable, and
    clicking it never corrupts the stored partition. Its falsifiable coverage —
    the actual proof that the link is NOT nested inside the summary — lives in
    `test_reset_link_is_a_sibling_of_details_not_inside_the_summary` (T3, DOM
    structure) and in `test_first_visit_opens_depth0_only` (T6, the
    `not_to_have_accessible_name(re.compile("Start fresh"))` assertion, which
    DOES redden under this exact mutant).
    """
    f = _course_with_two_chapters("t16")
    _login(page, live_server, "t16")
    page.goto(f"{live_server.url}/courses/{f['course'].slug}/")

    page.locator(_title_sel(f["chap_a"].pk)).click()
    _wait_for_write(page)
    before = _stored(page)
    assert before is not None

    page.route("**/reset/**", lambda route: route.abort("aborted"))
    # NOT `> a.outline-node__reset`: under the mutant the link moves inside the
    # <summary> and a direct-child locator would fail to resolve, reddening this
    # test on T3's structural point instead of on the storage invariant it exists
    # to prove.
    link = page.locator(f"#node-{f['chap_a'].pk} a.outline-node__reset")
    expect(link).to_be_visible()
    link.click()

    page.wait_for_timeout(200)  # let any scheduled write land before asserting
    assert _is_open(page, f["chap_a"].pk) is True, "the group must not have toggled"
    assert _stored(page) == before, "and nothing must have been persisted"
    page.unroute("**/reset/**")

    # The link really does navigate (the route abort is a test device, not the
    # product behaviour). courses/urls.py registers progress_reset at
    # courses/<slug>/reset/<node_pk>/ — there is no "progress/" segment.
    reset_url = f"/courses/{f['course'].slug}/reset/{f['chap_a'].pk}/"
    expect(link).to_have_attribute("href", re.compile(re.escape(reset_url)))

    # Keyboard reachability. Collapse chapter A first: with the group OPEN the
    # next tab stop after the summary is the unit link INSIDE the disclosure, not
    # the sibling reset link — D9 puts that link after </details> in DOM order.
    page.locator(_title_sel(f["chap_a"].pk)).click()
    page.locator(f"[data-node='{f['chap_a'].pk}'] > summary").focus()
    page.keyboard.press("Tab")
    assert page.evaluate(
        "() => document.activeElement.classList.contains('outline-node__reset')"
    )


@pytest.mark.django_db(transaction=True)
def test_nested_type_scale_and_guide_rule_survive_the_details_nesting(
    page, live_server
):
    """T17 — the R6 guard. Both halves are pure-CSS regressions that leave a
    correct DOM and a worse page, with nothing red.

    Mutants, applied separately: (1) omit the `> .outline-node__group >`
    type-scale twins; (2) leave `.outline-node > ul` un-re-pointed.
    """
    from tests.factories import ContentNodeFactory

    f = _course_with_two_chapters("t17")
    section = ContentNodeFactory(
        course=f["course"],
        kind="section",
        unit_type=None,
        parent=f["chap_a"],
        title="A Section",
    )
    ContentNodeFactory(
        course=f["course"], kind="unit", unit_type="lesson", parent=section, title="SU"
    )
    _login(page, live_server, "t17")
    page.goto(f"{live_server.url}/courses/{f['course'].slug}/")
    page.locator("[data-outline-toggle-all]").click()  # expand all

    chapter_size = page.evaluate(
        "pk => getComputedStyle(document.querySelector("
        "`[data-node='${pk}'] > summary .outline-node__title`)).fontSize",
        str(f["chap_a"].pk),
    )
    assert chapter_size == "17.6px", "1.1rem — the nested chapter type scale"

    section_style = page.evaluate(
        "pk => { const el = document.querySelector("
        "  `[data-node='${pk}'] > summary .outline-node__title`);"
        "  const s = getComputedStyle(el);"
        "  return {size: s.fontSize, transform: s.textTransform}; }",
        str(section.pk),
    )
    assert section_style["size"] == "12px", ".75rem — the section micro-type"
    assert section_style["transform"] == "uppercase"

    guide = page.evaluate(
        "pk => { const ul = document.querySelector(`[data-node='${pk}'] > ul`);"
        "  const s = getComputedStyle(ul);"
        "  return {border: s.borderLeftWidth, pad: s.paddingLeft}; }",
        str(f["chap_a"].pk),
    )
    assert guide["border"] == "1px", "the nested hairline guide rule still applies"
    assert guide["pad"] != "0px"


@pytest.mark.django_db(transaction=True)
def test_toggle_all_stays_hidden_when_there_are_no_groups(page, live_server):
    """T18. "Every group is open" is vacuously true on a container-free course, so
    an un-hidden button would read Collapse all and do nothing.

    Mutant: drop the `&& groups.length` guard from init step 2 so the button is
    un-hidden unconditionally."""
    from courses.models import Enrollment
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    user = make_verified_user(
        username="t18", email="t18@test.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory(title="Flat")
    Enrollment.objects.create(student=user, course=course)
    ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="Only"
    )
    _login(page, live_server, "t18")
    page.goto(f"{live_server.url}/courses/{course.slug}/")

    button = page.locator("[data-outline-toggle-all]")
    # to_be_hidden() is satisfied by ZERO matching elements, so a build that
    # stopped rendering the button entirely would pass without this count check.
    expect(button).to_have_count(1)
    expect(button).to_be_hidden()


@pytest.mark.django_db(transaction=True)
def test_folding_and_filtering_work_with_js_off(browser, live_server):
    """T19 — guards D3 and D8 together.

    The outline view is @login_required, so a bare
    new_context(java_script_enabled=False) lands on the login page and the
    assertions pass or fail for the wrong reason. Follow the existing precedent
    in tests/test_e2e_before_after.py: log in with JS on, capture storage_state,
    then open the no-JS context with it.

    Every state read here uses _has_open_attr, NOT _is_open — as a choice, not a
    constraint: page.evaluate DOES still work with java_script_enabled=False
    (Playwright's injected script runs in a utility world), but an attribute read
    is the honest probe here. It reads what the browser itself updated, so the
    assertion cannot be satisfied by anything outline_tree.js did.

    Two mutants: emit a bare `open` in the template (the default half reddens);
    drop the D8 `or active_tag_ids and not item.tag_hidden` arm (the filtered
    half reddens).
    """
    f = _course_with_two_chapters("t19")
    tag = _tag_a_unit(f["user"], f["unit_b"])

    ctx = browser.new_context()
    page = ctx.new_page()
    _login(page, live_server, "t19")
    # _login's submit click does not await the navigation, and storage_state()
    # does not serialise against it — every other test happens to, via its next
    # goto(). Without this the no-JS context can start cookie-less and land on
    # the login page, failing for the wrong reason, intermittently.
    page.goto(f"{live_server.url}/courses/{f['course'].slug}/")
    storage_state = ctx.storage_state()
    ctx.close()

    nojs = browser.new_context(java_script_enabled=False, storage_state=storage_state)
    page = nojs.new_page()
    page.goto(f"{live_server.url}/courses/{f['course'].slug}/")

    assert _has_open_attr(page, f["part"].pk) is True
    assert _has_open_attr(page, f["chap_a"].pk) is False

    # Native <details> still folds with no JS at all.
    page.locator(f"[data-node='{f['chap_a'].pk}'] > summary").click()
    assert _has_open_attr(page, f["chap_a"].pk) is True

    # D8: the server opens the ancestors of a match, so a no-JS filtered outline
    # is not empty.
    page.goto(f"{live_server.url}/courses/{f['course'].slug}/?tags={tag.pk}")
    assert _has_open_attr(page, f["chap_b"].pk) is True
    expect(page.locator(f"#node-{f['unit_b'].pk}")).to_be_visible()
    nojs.close()
