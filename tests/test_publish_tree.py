"""Task 13: the tree UI -- publish/obligatory toggles on every builder row.

TREE1-TREE10. TREE11 belongs to Task 12 (tests/test_publish_strip.py) and is
not repeated here.
"""

import pytest
from bs4 import BeautifulSoup
from django.urls import reverse

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import QuizSubmissionFactory
from tests.factories import make_login
from tests.factories import make_quiz_unit


def _setup(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    return owner, course


def _get(client, course, params=None):
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    return client.get(url, params or {}).content.decode()


def _row(soup, pk):
    return soup.select_one(f'li[data-node="{pk}"] form.tree__rowhead')


@pytest.mark.django_db
def test_tree1_hidden_rename_precedes_both_flag_toggles_in_source_order(client):
    """TREE1. Assert SOURCE ORDER, not behaviour: a Django test client cannot
    exercise "Enter renames". Implicit submission picks the form's first
    submit control in tree order, so the hidden Rename button's index among
    the form's submit controls must be lower than either flag toggle's.
    Mutant: place the toggles before Rename in the template -> Enter would
    publish instead of renaming."""
    _, course = _setup(client)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", title="U1"
    )
    body = _get(client, course)
    soup = BeautifulSoup(body, "html.parser")
    form = _row(soup, unit.pk)
    assert form is not None

    submit_controls = [b for b in form.find_all("button") if b.get("type") == "submit"]
    rename_idx = next(
        i
        for i, b in enumerate(submit_controls)
        if "visually-hidden" in (b.get("class") or [])
    )
    flag_idxs = [i for i, b in enumerate(submit_controls) if b.get("data-op") == "flag"]
    assert len(flag_idxs) == 2
    assert rename_idx < min(flag_idxs)


@pytest.mark.django_db
def test_tree2_unit_row_glyph_is_binary_on_its_own_flags(client):
    """TREE2. A unit's glyph reads its own two booleans, using the masked
    icm--* classes -- not a #bi-* sprite href."""
    _, course = _setup(client)
    live = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        title="Live",
        published=True,
        obligatory=True,
    )
    draft = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        title="Draft",
        published=False,
        obligatory=False,
    )
    body = _get(client, course)
    soup = BeautifulSoup(body, "html.parser")

    def classes(pk, flag):
        return _row(soup, pk).select_one(f'[data-flag="{flag}"]').get("class") or []

    assert "icm--live" in classes(live.pk, "published")
    assert "icm--req" in classes(live.pk, "obligatory")
    assert "icm--draft" in classes(draft.pk, "published")
    assert "icm--opt" in classes(draft.pk, "obligatory")
    # No `assert "#bi-live" not in body` here. Final-review A2: the strings
    # "bi-live"/"bi-draft" occur NOWHERE in this repository -- Task 13's
    # accepted deviation implemented the glyphs as masked icm--* classes and no
    # bi-* symbol was ever added -- so no implementation can emit them and the
    # assertions could not fail. The alternate-mechanism mutant they targeted
    # (render the glyph as <use href="#bi-live">) is already killed by the four
    # positive assertions above, which redden first.


@pytest.mark.django_db
def test_tree3_empty_container_is_inert_not_disabled(client):
    """TREE3. Count-based inert case (zero units / zero lessons): assert the
    NON-CLICKABLE property (no href, aria-disabled="true"), never the string
    "disabled" -- that attribute is invalid on <a> and blocks nothing."""
    _, course = _setup(client)
    chapter = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=None, title="Empty"
    )
    body = _get(client, course)
    soup = BeautifulSoup(body, "html.parser")
    row = _row(soup, chapter.pk)
    for flag in ("published", "obligatory"):
        ctrl = row.select_one(f'[data-flag="{flag}"]')
        assert ctrl.name == "a"
        assert ctrl.get("href") is None
        assert ctrl.get("aria-disabled") == "true"
        # No `assert ctrl.get("disabled") is None`. Final-review A3: this is
        # verbatim the anti-pattern the docstring two lines above warns
        # against. The template never writes `disabled` on an anchor and the
        # attribute is invalid on <a> in any case, so it could not fail -- and
        # a mutant that deletes aria-disabled and adds the live branch's href
        # (the exact break this test exists to prevent) leaves it green.


@pytest.mark.django_db
def test_tree4_container_glyph_folds_the_full_subtree_under_a_filter(client):
    """TREE4. Seed 6 units, 2 live, filter to only the 2 live ones. The
    container must still render the MIXED glyph, folded from the full
    (unrestricted) subtree -- not the 2-of-2 "all live" a fold over the
    filtered children_map would produce. Assert the glyph, not a count: under
    a filter the anchor is inert and its title is the filter tooltip."""
    _, course = _setup(client)
    chapter = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=None, title="Ch"
    )
    for i in range(2):
        ContentNodeFactory(
            course=course,
            kind="unit",
            unit_type="lesson",
            parent=chapter,
            title=f"Alpha {i}",
            published=True,
        )
    for i in range(4):
        ContentNodeFactory(
            course=course,
            kind="unit",
            unit_type="lesson",
            parent=chapter,
            title=f"Beta {i}",
            published=False,
        )
    body = _get(client, course, {"q": "Alpha"})
    soup = BeautifulSoup(body, "html.parser")
    row = _row(soup, chapter.pk)
    ctrl = row.select_one('[data-flag="published"]')
    assert "icm--live-mixed" in (ctrl.get("class") or [])


@pytest.mark.django_db
def test_tree5_container_anchors_inert_under_filter_unit_toggles_stay_live(client):
    """TREE5. A third, separate inert case from TREE3's count-based ones: a
    container anchor is inert whenever the filter is active, regardless of
    its counts. A unit row's toggles stay live -- they affect only the one
    row shown."""
    _, course = _setup(client)
    chapter = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=None, title="Ch"
    )
    hit = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=chapter,
        title="Alpha",
        published=True,
    )
    ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=chapter,
        title="Other",
        published=False,
    )
    body = _get(client, course, {"q": "Alpha"})
    soup = BeautifulSoup(body, "html.parser")
    chapter_row = _row(soup, chapter.pk)
    for flag in ("published", "obligatory"):
        ctrl = chapter_row.select_one(f'[data-flag="{flag}"]')
        assert ctrl.name == "a"
        assert ctrl.get("href") is None
        assert ctrl.get("aria-disabled") == "true"
        assert ctrl.get("tabindex") == "-1"

    unit_row = _row(soup, hit.pk)
    ctrl = unit_row.select_one('[data-flag="published"]')
    assert ctrl.name == "button"
    assert ctrl.get("formaction") is not None
    assert ctrl.get("aria-disabled") is None


@pytest.mark.django_db
def test_tree6_quiz_plus_obligatory_lesson_is_all_obligatory_not_mixed(client):
    """TREE6. A container of one quiz + one obligatory lesson renders
    "all obligatory". Mutant: share one total_unit_count between both
    tri-states -> the quiz's inert flag drags the obligatory glyph to
    mixed."""
    _, course = _setup(client)
    chapter = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=None, title="Ch"
    )
    make_quiz_unit(course=course, parent=chapter, title="Q1", published=True)
    ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=chapter,
        title="L1",
        published=True,
        obligatory=True,
    )
    body = _get(client, course)
    soup = BeautifulSoup(body, "html.parser")
    row = _row(soup, chapter.pk)
    ctrl = row.select_one('[data-flag="obligatory"]')
    classes = ctrl.get("class") or []
    assert "icm--req" in classes
    assert "icm--req-mixed" not in classes


@pytest.mark.django_db
def test_tree7_quiz_row_publish_control_by_state(client):
    """TREE7. Three quiz renderings: published+submissions -> confirming
    anchor; no submissions -> button; DRAFTED+submissions -> button (the
    state every quiz lands in right after the carve-out fires -- a two-case
    test misses it). Mutant B: key on "has submissions" without
    "and node.published" -> the drafted quiz would wrongly render an
    anchor."""
    _, course = _setup(client)
    confirming = make_quiz_unit(
        course=course, parent=None, title="Confirming", published=True
    )
    QuizSubmissionFactory(unit=confirming)
    plain = make_quiz_unit(course=course, parent=None, title="Plain", published=True)
    drafted = make_quiz_unit(
        course=course, parent=None, title="Drafted", published=False
    )
    QuizSubmissionFactory(unit=drafted)

    body = _get(client, course)
    soup = BeautifulSoup(body, "html.parser")

    def publish_ctrl(pk):
        return _row(soup, pk).select_one('[data-flag="published"]')

    c = publish_ctrl(confirming.pk)
    assert c.name == "a"
    assert c.get("data-flag-confirm") == str(confirming.pk)

    p = publish_ctrl(plain.pk)
    assert p.name == "button"
    assert p.get("data-op") == "flag"

    d = publish_ctrl(drafted.pk)
    assert d.name == "button", "drafted quiz with submissions must POST, not confirm"
    assert d.get("data-op") == "flag"


@pytest.mark.django_db
def test_tree8_legend_renders_six_rows_one_per_state(client):
    """TREE8. builder.html renders six legend rows, one per state, each
    naming one of the six icm--* classes (or six bi-* symbols, whichever
    mechanism the legend actually uses)."""
    _, course = _setup(client)
    body = _get(client, course)
    soup = BeautifulSoup(body, "html.parser")
    legend = soup.select_one(".flag-legend")
    assert legend is not None
    for cls in (
        "icm--live",
        "icm--draft",
        "icm--live-mixed",
        "icm--req",
        "icm--opt",
        "icm--req-mixed",
    ):
        assert legend.select_one(f".{cls}") is not None, cls
    # Final-review A5. The test is NAMED "renders six rows" but asserted no
    # count: a legend that grew a seventh row, or dropped <dl> rows while
    # keeping the spans, was invisible to it -- precisely the drift signal spec
    # 5 says TREE8 exists to provide.
    assert len(legend.select(".flag-legend__row")) == 6


@pytest.mark.django_db
def test_tree9_quiz_obligatory_control_is_an_inert_button_and_server_422s(client):
    """TREE9. Markup half: the quiz row's obligatory control is
    type="button" with NO formaction -- never "no href" (a button has no
    href under any implementation, so that assertion cannot fail). Server
    half: POSTing flag=obligatory on a quiz unit returns 422."""
    _, course = _setup(client)
    # obligatory=False, deliberately the OPPOSITE of what the rejected POST
    # below writes (value="1"). Seeded True -- make_quiz_unit's default -- the
    # "unchanged" assertion could not fail: a mutant that wrote before raising
    # would set True over True and stay green. The state has to differ from the
    # write for "unchanged" to mean anything.
    quiz = make_quiz_unit(
        course=course, parent=None, title="Q1", published=True, obligatory=False
    )
    body = _get(client, course)
    soup = BeautifulSoup(body, "html.parser")
    row = _row(soup, quiz.pk)
    ctrl = row.select_one('[data-flag="obligatory"]')
    assert ctrl.name == "button"
    assert ctrl.get("type") == "button"
    assert ctrl.get("formaction") is None
    # Final-review m4. Both a11y attributes were unasserted, so dropping either
    # from _tree_node.html passed silently -- and they are the only thing that
    # tells a screen-reader user, or a keyboard user tabbing the row, that this
    # control is dead. `disabled` is deliberately NOT used (a disabled button
    # never shows its title tooltip, which is the only explanation the CA gets),
    # so these two carry the whole of the inertness contract.
    assert ctrl.get("aria-disabled") == "true"
    assert ctrl.get("tabindex") == "-1"

    url = reverse("courses:manage_node_flag", kwargs={"slug": course.slug})
    resp = client.post(
        url,
        {
            "node": quiz.pk,
            "flag": "obligatory",
            "value": "1",
            "scope": "node",
            "token": quiz.updated.isoformat(),
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 422
    # Spec 9 TREE9 asks for "returns 422 and leaves `obligatory` UNCHANGED".
    # A 422 that wrote first would satisfy the status assertion alone. See the
    # fixture comment above for why this is seeded False, not True.
    quiz.refresh_from_db()
    assert quiz.obligatory is False


@pytest.mark.django_db
def test_tree10_quiz_only_container_publish_live_obligatory_inert(client):
    """TREE10. A quiz-only container has units (fc.1 > 0) but no lessons
    (fc.3 == 0): its publish control is live while its obligatory control is
    inert. Mutant: key inertness on unit count -> the obligatory control
    would render a tri-state over an empty denominator instead of inert."""
    _, course = _setup(client)
    chapter = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=None, title="Ch"
    )
    make_quiz_unit(course=course, parent=chapter, title="Q1", published=True)
    make_quiz_unit(course=course, parent=chapter, title="Q2", published=True)
    body = _get(client, course)
    soup = BeautifulSoup(body, "html.parser")
    row = _row(soup, chapter.pk)

    pub = row.select_one('[data-flag="published"]')
    assert "icm--live" in (pub.get("class") or [])

    ob = row.select_one('[data-flag="obligatory"]')
    assert ob.get("href") is None
    assert ob.get("aria-disabled") == "true"
