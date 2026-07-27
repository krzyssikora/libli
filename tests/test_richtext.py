import pytest
from django.urls import reverse

from courses.models import CalloutElement
from courses.models import FillGateElement
from courses.models import GuessNumberElement
from courses.models import SpoilerElement
from courses.models import SwitchGateElement
from courses.models import TextElement
from courses.richtext import CONCRETE_QUESTION_MODELS
from courses.richtext import PERMALINK_PREFIX
from courses.richtext import RICH_TEXT_FIELDS
from courses.richtext import find_link_targets
from courses.richtext import iter_rich_text
from courses.richtext import rewrite_instance
from courses.richtext import rewrite_links

# ---- the literal is tied to the route --------------------------------------


def test_prefix_matches_the_route(db):
    # Part 1 identified "/courses/n/" as a drift hazard the route NAME does not
    # protect. This part adds two more copies of the literal; this is the tie the
    # spec asks for.
    assert reverse("courses:node_permalink", kwargs={"node_pk": 1}) == "/courses/n/1/"
    assert PERMALINK_PREFIX == "/courses/n/"
    assert find_link_targets('<a href="/courses/n/1/">x</a>') == {1}


# ---- find_link_targets ----------------------------------------------------


def test_no_links():
    assert find_link_targets("<p>plain</p>") == set()


def test_one_link():
    assert find_link_targets('<a href="/courses/n/12/">x</a>') == {12}


def test_several_links():
    html = '<a href="/courses/n/1/">a</a> and <a href="/courses/n/2/">b</a>'
    assert find_link_targets(html) == {1, 2}


def test_external_link_ignored():
    assert find_link_targets('<a href="https://x.test/">x</a>') == set()


def test_malformed_pk_ignored():
    assert find_link_targets('<a href="/courses/n/abc/">x</a>') == set()


def test_query_suffix_is_not_an_internal_link():
    # Part 1 pins the internal-link test as the ANCHORED ^/courses/n/(\d+)/$ -- the
    # dialog, this rewrite and the delete count must all agree. A prefix match here
    # would make them disagree about what an internal link even is.
    assert find_link_targets('<a href="/courses/n/12/?x=1">x</a>') == set()


def test_literal_in_visible_text_is_not_a_link():
    # The string an author may plausibly type. Matching it would silently inflate
    # every delete count and rewrite prose.
    assert find_link_targets("<p>go to /courses/n/12/ now</p>") == set()


# ---- the attribute-aware scanner ------------------------------------------


@pytest.mark.parametrize(
    "html",
    [
        '<a title="a > b" href="/courses/n/12/">W</a>',
        '<a href="/courses/n/12/" title="a > b">W</a>',
    ],
)
def test_raw_gt_inside_an_attribute(html):
    # MEASURED: nh3 does NOT escape > inside attribute values, and `title` is an
    # allowed <a> attribute. A naive <a[^>]*> matches `<a title="a >` -- a
    # syntactically CLEAN match of the wrong span -- so the href falls outside it and
    # the link is silently missed. Assert the rewrite, not the absence of damage: a
    # "byte-identical" assertion passes the broken version.
    assert find_link_targets(html) == {12}
    out, flat = rewrite_links(html, {12: 99}, on_missing="unwrap")
    assert "/courses/n/99/" in out
    assert flat == 0


def test_href_containing_a_raw_gt():
    html = '<a href="/courses/n/12/?q=a>b">y</a>'
    # Not an internal link (query suffix), and must not corrupt anything.
    assert find_link_targets(html) == set()


@pytest.mark.parametrize(
    "html",
    [
        '<a data-href="/courses/n/999/" href="/courses/n/12/">x</a>',
        '<a href="/courses/n/12/" data-href="/courses/n/999/">x</a>',
    ],
)
def test_spoofed_data_href_attribute_does_not_displace_the_real_href(html):
    # Reachable: FillGateElement/SwitchGateElement.stem never go through
    # sanitize_html (see the RICH_TEXT_FIELDS comment), so a hand-crafted transfer
    # archive controls this content directly. Without an attribute-name boundary,
    # the href-matching regex fires on the "href" SUBSTRING inside any longer
    # attribute name -- e.g. data-href -- and scan order decides which value wins.
    # Reversing the two attributes must not change the answer.
    assert find_link_targets(html) == {12}
    out, flat = rewrite_links(html, {12: 99}, on_missing="unwrap")
    assert "/courses/n/99/" in out
    assert "/courses/n/999/" in out  # the fake data-href is untouched, not rewritten
    assert flat == 0


def test_unquoted_href_value_fails_closed():
    # Not a silent miss: nh3's own output always quotes attribute values, so an
    # unquoted href is reachable only via a hand-crafted archive that bypassed
    # sanitize_html (same reachability as the spoofed-attribute case above).
    # Fail-closed means the WHOLE body comes back untouched -- a well-formed
    # internal link elsewhere in the SAME body must not be found or rewritten
    # either. (A version that merely treats the malformed href as "no href" and
    # keeps scanning would still find and rewrite the second anchor below -- that
    # is the silent-miss failure class this module exists to prevent, and the
    # scenario a single malformed anchor with nothing after it cannot distinguish
    # from a genuine fail-closed implementation.)
    html = '<a href=/courses/n/12/>bad</a> <a href="/courses/n/34/">good</a>'
    assert find_link_targets(html) == set()
    out, flat = rewrite_links(html, {34: 999}, on_missing="unwrap")
    assert out == html
    assert flat == 0


def test_href_inside_html_comment_is_still_matched_known_limitation():
    # KNOWN LIMITATION, pinned not fixed: the scanner is a deliberate non-parser --
    # a regex-based scan for <a ...> open tags -- with no notion of an HTML comment.
    # A literal "<a href=...>" that happens to sit inside <!-- ... --> is
    # indistinguishable from a real anchor and IS matched. This is the documented
    # tradeoff of avoiding a full HTML parser (see the module docstring); this test
    # records current behaviour, it does not assert the behaviour is desirable.
    html = '<!-- <a href="/courses/n/12/">note</a> -->'
    assert find_link_targets(html) == {12}


def test_href_inside_code_block_is_still_matched_known_limitation():
    # Same known limitation for literal (unescaped) anchor markup sitting inside a
    # <code> block's text content -- the scanner cannot tell it isn't a real anchor.
    html = '<code><a href="/courses/n/12/">sample</a></code>'
    assert find_link_targets(html) == {12}


# ---- rewrite_links --------------------------------------------------------


def test_rewrite_maps_known_targets():
    out, flat = rewrite_links(
        '<a href="/courses/n/12/">x</a>', {12: 500}, on_missing="unwrap"
    )
    assert out == '<a href="/courses/n/500/">x</a>'
    assert flat == 0


def test_keep_leaves_unmapped_links_alone():
    html = '<a href="/courses/n/12/">x</a>'
    out, flat = rewrite_links(html, {}, on_missing="keep")
    assert out == html
    assert flat == 0


def test_unwrap_flattens_unmapped_links_keeping_text():
    out, flat = rewrite_links(
        'go <a href="/courses/n/12/">there</a> now', {}, on_missing="unwrap"
    )
    assert "<a" not in out
    assert "go there now" in out
    assert flat == 1


def test_unwrap_preserves_inner_markup():
    out, _flat = rewrite_links(
        '<a href="/courses/n/12/">the <b>vertex</b></a>', {}, on_missing="unwrap"
    )
    assert "<b>vertex</b>" in out
    assert "<a" not in out


def test_external_links_are_never_touched():
    html = '<a href="https://x.test/">x</a>'
    out, flat = rewrite_links(html, {}, on_missing="unwrap")
    assert out == html
    assert flat == 0


def test_byte_identity_outside_anchors():
    # A body carrying an inline math span AND a literal /courses/n/... in visible text
    # comes back unchanged apart from the intended href. This case fails under both a
    # bs4 round trip (which re-escapes entities) and a naive whole-document regex.
    html = (
        "<p>see \\(x^2 &gt; 1\\) and type /courses/n/7/ then "
        '<a href="/courses/n/12/">here</a></p>'
    )
    out, _flat = rewrite_links(html, {12: 99}, on_missing="unwrap")
    assert "\\(x^2 &gt; 1\\)" in out
    assert "type /courses/n/7/ then" in out
    assert "/courses/n/99/" in out


# ---- fail-closed ----------------------------------------------------------


@pytest.mark.parametrize(
    "html",
    [
        '<a title="unterminated href="/courses/n/12/">x</a>',  # unterminated quote
        '<a href="/courses/n/12/"',  # no unquoted >
    ],
)
def test_fail_closed_conditions_return_the_body_untouched(html):
    out, flat = rewrite_links(html, {12: 99}, on_missing="unwrap")
    assert out == html
    assert flat == 0


def test_unwrap_without_a_closing_tag_fails_closed():
    # Reachable: _build_fill_gate/_build_switch_gate never re-sanitise their stems, so
    # a hand-crafted archive can carry unbalanced markup.
    html = '<a href="/courses/n/12/">dangling'
    out, flat = rewrite_links(html, {}, on_missing="unwrap")
    assert out == html
    assert flat == 0


# ---- the registry ---------------------------------------------------------


def test_an_unknown_on_missing_raises():
    with pytest.raises(ValueError):
        rewrite_links('<a href="/courses/n/1/">x</a>', {}, on_missing="defer")


def test_registry_shape():
    assert len(RICH_TEXT_FIELDS) == 27
    assert len({m for m, _f in RICH_TEXT_FIELDS}) == 16
    assert len(CONCRETE_QUESTION_MODELS) == 10


def test_every_question_model_contributes_both_fields():
    # These 20 entries arrive via a comprehension rather than hand-written lines, so a
    # typo in the ("stem", "explanation") tuple would silently halve the coverage.
    for model in CONCRETE_QUESTION_MODELS:
        assert (model, "stem") in RICH_TEXT_FIELDS
        assert (model, "explanation") in RICH_TEXT_FIELDS


@pytest.mark.parametrize(
    "model,field",
    [
        (TextElement, "body"),
        (SpoilerElement, "body"),
        (CalloutElement, "body"),
        (FillGateElement, "stem"),
        (GuessNumberElement, "stem"),
        (GuessNumberElement, "success_message"),
        (SwitchGateElement, "stem"),
    ],
)
def test_iter_rich_text_reaches_every_hand_listed_field(db, model, field):
    # The spec's completeness spot-check. Store a link in each hand-listed location and
    # assert the registry sees it -- these are exactly the fields a widget-derived
    # registry would have missed.
    obj = model(**{field: '<a href="/courses/n/77/">x</a>'})
    found = dict(iter_rich_text(obj))
    assert field in found
    assert find_link_targets(found[field]) == {77}


def test_iter_rich_text_yields_nothing_for_a_non_registry_model(db):
    from courses.models import StepperElement

    assert list(iter_rich_text(StepperElement(prompt="plain"))) == []


def test_rewrite_instance_returns_only_the_changed_fields(db):
    obj = GuessNumberElement(
        stem='<a href="/courses/n/1/">s</a>',
        success_message="<p>no links here</p>",
    )
    changed, flattened = rewrite_instance(obj, {1: 900}, on_missing="unwrap")
    assert changed == ["stem"]  # success_message untouched -> not in update_fields
    assert flattened == 0
    assert "/courses/n/900/" in obj.stem


def test_registry_excludes_switchgrid_and_the_exclusion_is_behavioural(db):
    # Not a list-membership tautology: assert the two facts that JUSTIFY the exclusion.
    from courses import switchgrid
    from courses.models import SwitchGridElement
    from courses.sanitize import sanitize_html

    assert all(m is not SwitchGridElement for m, _f in RICH_TEXT_FIELDS)

    # (a) an anchor SURVIVES the form's sanitize_html on the way in ...
    anchor = '<a href="/courses/n/5/">x</a>'
    assert sanitize_html(anchor) == anchor
    # (b) ... and is then STRIPPED by the import path, because sanitize_stem_segments
    # applies sanitize_cell, whose CELL_TAGS has no <a>. If that inconsistency is ever
    # fixed, this assertion flips and the exclusion must be revisited.
    assert "<a" not in switchgrid.sanitize_stem_segments(anchor)
