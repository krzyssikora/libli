"""The key must equal what the LOADER STORED AT IMPORT TIME -- so these tests run
the real loader with the PRE-SLICE-1 allowlists patched in, rather than asserting
one sanitiser call against another.

The patching is the whole point, and leaving it out makes every assertion here fail
for the right reason in the wrong place. MEASURED on this branch: the loader running
TODAY stores `jeśli ( <span>założenie</span> ) to ( teza )` for the fixture below,
because slice 1 put `span` in ALLOWED_TAGS. The DB was written BEFORE slice 1, so it
holds `jeśli ( założenie ) to ( teza )` -- which is exactly what `key_for` produces.
The production key construction is right; an unpatched loader is simply the wrong
oracle for it.

This is also the test that would have caught the composed-path defect: a key built
with sanitize_html alone, or sanitize_stem_segments alone, matches nothing for
FillBlankQuestionElement.stem, and nothing anywhere says so.
"""

import pytest

from courses.fillblank import SENTINEL
from courses.lal_loader.builders import build_element
from courses.models import ChoiceQuestionElement
from courses.models import ContentNode
from courses.models import FillBlankQuestionElement
from courses.models import FillGateElement
from courses.models import TableElement
from courses.models import TextElement
from courses.recolour.replay import current_replay
from courses.recolour.replay import key_for
from courses.recolour.replay import legacy_replay
from courses.recolour.replay import value_for
from tests.factories import CourseFactory

pytestmark = pytest.mark.django_db

# Imported, never written as an escape: SENTINEL is U+FFFF, and the visually
# identical U+FFFD would make the two stem fixtures below silently vacuous.
S = SENTINEL


def _unit(course):
    part = ContentNode.objects.create(
        course=course, parent=None, order=0, kind="part", title="P"
    )
    ch = ContentNode.objects.create(
        course=course, parent=part, order=0, kind="chapter", title="C"
    )
    return ContentNode.objects.create(
        course=course, parent=ch, order=0, kind="unit", title="U", unit_type="lesson"
    )


def _patch_loader_to_legacy(monkeypatch):
    """Make the loader behave as it did AT IMPORT TIME (pre-slice-1 allowlists).

    Patched at the points of USE, not just at the definition, and both are needed:
    `courses/models.py` binds each sanitiser at module import (`from
    courses.sanitize import sanitize_cell` / `sanitize_html`, models.py:25-26), so
    patching `courses.sanitize` alone would never reach `QuestionElement.save()` or
    `TableElement._sanitized_data`. Conversely `courses/switchgrid.py` imports
    `sanitize_cell` INSIDE `sanitize_stem_segments`, so only the `courses.sanitize`
    patch reaches the gate-stem path.
    """
    import nh3

    from courses import models as courses_models
    from courses import sanitize as courses_sanitize
    from courses.sanitize import ALLOWED_ATTRIBUTES
    from courses.sanitize import ALLOWED_TAGS
    from courses.sanitize import ALLOWED_URL_SCHEMES
    from courses.sanitize import CELL_TAGS
    from courses.sanitize import LEGACY_ALLOWED_CLASSES
    from courses.sanitize import LEGACY_CELL_ALLOWED_CLASSES
    from courses.sanitize import sanitize_cell

    # The legacy CLASS allowlists are not sufficient on their own, and this is the
    # part that is easy to get wrong. MEASURED: patching only the classes leaves the
    # loader storing `<span>założenie</span>`, because slice 1 added `span` to BOTH
    # tag sets -- and all six comparisons below then fail against keys that are in
    # fact correct. The ORACLE feeds RAW source (spans intact) through the sanitiser,
    # so it needs the pre-slice-1 TAGS as well.
    #
    # The production key generator does NOT need this: `key_for` runs `strip_spans`
    # first, so no span ever reaches the sanitiser and the live tag sets are inert
    # there -- which is exactly what its `assert "<span" not in stripped` pins down.
    legacy_tags = ALLOWED_TAGS - {"span"}
    legacy_cell_tags = CELL_TAGS - {"span"}

    def legacy_html(value, *_a, **_kw):
        return nh3.clean(
            value or "",
            tags=legacy_tags,
            attributes=ALLOWED_ATTRIBUTES,
            allowed_classes=LEGACY_ALLOWED_CLASSES,
            link_rel=None,
            url_schemes=ALLOWED_URL_SCHEMES,
        )

    def legacy_cell(value, *_a, **_kw):
        # Reuses the real sanitize_cell for the maths-stashing logic, overriding
        # only the two allowlists via the keyword-only parameters added above.
        return sanitize_cell(
            value,
            tags=legacy_cell_tags,
            allowed_classes=LEGACY_CELL_ALLOWED_CLASSES,
        )

    monkeypatch.setattr(courses_sanitize, "sanitize_html", legacy_html)
    monkeypatch.setattr(courses_sanitize, "sanitize_cell", legacy_cell)
    monkeypatch.setattr(courses_models, "sanitize_html", legacy_html)
    monkeypatch.setattr(courses_models, "sanitize_cell", legacy_cell)


def _load(monkeypatch, el):
    _patch_loader_to_legacy(monkeypatch)
    course = CourseFactory()
    unit = _unit(course)
    build_element(course, unit, el, source_root="", source_dir="", allow_html=False)
    return unit


RED = 'jeśli ( <span style="color: red;">założenie</span> ) to ( teza )'


def test_the_patched_loader_really_is_the_pre_slice_1_loader(monkeypatch):
    # Guards the oracle itself. Without the patch the loader stores
    # `<span>założenie</span>` (span is in ALLOWED_TAGS after slice 1) and every
    # test below fails against a key that is in fact correct.
    _load(monkeypatch, {"type": "text", "body": RED})
    assert "<span" not in TextElement.objects.get().body


def test_html_shape_key_equals_what_the_loader_stored(monkeypatch):
    _load(monkeypatch, {"type": "text", "body": RED})
    stored = TextElement.objects.get().body
    assert key_for(RED, "html") == stored
    # And the pre-change loader really did drop the colour:
    assert "color" not in stored and "tc-" not in stored


def test_choice_stem_is_the_bare_sanitize_html_shape(monkeypatch):
    # builders.py:359 creates ChoiceQuestionElement with a bare stem=el["stem"];
    # QuestionElement.save() applies sanitize_html and nothing else.
    _load(
        monkeypatch,
        {
            "type": "choice",
            "stem": RED,
            "choices": [{"text": "a", "is_correct": True}],
        },
    )
    assert key_for(RED, "html") == ChoiceQuestionElement.objects.get().stem


def test_fill_gate_stem_is_the_stem_segments_shape(monkeypatch):
    # MEASURED: zero coloured fill_gate stems survive source-side exclusion (the
    # corpus's only two sit in the excluded 001_ part), so this synthesised
    # fixture is the ONLY oracle the stem shape ever gets. It is load-bearing.
    src = f'<span style="color: red;">a</span> {S}0{S} b'
    _load(monkeypatch, {"type": "fill_gate", "stem": src, "answers": [["x"]]})
    assert key_for(src, "stem") == FillGateElement.objects.get().stem


def test_fillblank_stem_is_the_COMPOSED_shape(monkeypatch):
    # The composition is real even though the corpus holds zero coloured
    # fillblank stems -- hence a synthesised fixture.
    src = f'<p><span style="color: red;">a</span></p> {S}0{S}'
    _load(monkeypatch, {"type": "fillblank", "stem": src, "blanks": [["x"]]})
    stored = FillBlankQuestionElement.objects.get().stem
    assert key_for(src, "composed") == stored
    # sanitize_html ALONE is not the same string -- this is the silent-miss shape
    # the composed replay exists to prevent (the <p> survives an html-only key and
    # is stripped by the cell pass).
    assert key_for(src, "html") != stored
    # NOT asserted: that the "stem" shape differs. MEASURED over 8 shapes including
    # maths and entities, sanitize_html is a NO-OP on sanitize_cell output, so the
    # composed key and the stem key coincide today. The composition is modelled for
    # FIDELITY to the real write path, not because it currently diverges -- keep it,
    # and re-measure before ever "simplifying" SHAPE_COMPOSED away.


def test_table_cell_is_the_cell_shape(monkeypatch):
    src = '<span style="color: red;">x</span> <strong class="bold">y</strong>'
    _load(
        monkeypatch,
        {"type": "table", "data": {"cells": [[{"html": src}, {"html": ""}]]}},
    )
    stored = TableElement.objects.get().data["cells"][0][0]["html"]
    assert key_for(src, "cell") == stored


def test_legacy_and_current_differ_exactly_where_the_spec_says():
    # nh3 DELETES the class attribute for a tag that is not an allowed_classes
    # key, and emits an empty class="" for one that IS. Adding strong/b/i/u/a to
    # the allowlist in slice 1 therefore moves every such key off the stored
    # value -- the corpus carries 435 nolist, 300 myequation, 201 bold.
    src = '<strong class="yellow_on_gray">x</strong>'
    assert legacy_replay(src, "html") == "<strong>x</strong>"
    assert current_replay(src, "html") == '<strong class="">x</strong>'


def test_value_carries_the_colour_and_differs_from_the_key():
    value, emitted = value_for(RED, "html")
    assert 'class="tc-red"' in value
    assert emitted == 1
    assert value != key_for(RED, "html")


def test_every_carrier_class_produces_a_value_that_DIFFERS_from_its_key():
    # The spec asserts `value != key` per carrier class, and that clause is the whole
    # defence against the span-only no-op: a colouriser that ignored a carrier would
    # emit a value byte-identical to the key, the key would still match, and the run
    # would report ~100% while delivering nothing for that class.
    #
    # One case per row of the spec's carrier table -- span, in-TC_CLASS_TAGS, and
    # outside-TC_CLASS_TAGS -- because they take three different code paths.
    for src in (
        '<span style="color: red;">x</span>',  # span carrier
        '<strong style="color: blue;">x</strong>',  # in TC_CLASS_TAGS
        '<u style="color: red;">x</u>',  # in TC_CLASS_TAGS
        '<p style="color: green;">x</p>',  # outside -- wraps children
        '<li style="color: red;">x</li>',  # outside -- wraps children
        '<figcaption style="color: orange;">x</figcaption>',  # not in ALLOWED_TAGS
    ):
        value, emitted = value_for(src, "html")
        assert emitted == 1, src
        assert "tc-" in value, src
        assert value != key_for(src, "html"), src


def test_value_for_a_non_span_carrier_also_differs_from_the_key():
    src = '<p><strong style="color: blue;">x</strong></p>'
    value, emitted = value_for(src, "html")
    assert value == '<p><strong class="tc-blue">x</strong></p>'
    assert emitted == 1
    assert value != key_for(src, "html")


def test_key_input_never_contains_a_span_tag():
    # The legacy replay uses the live ALLOWED_TAGS, which now CONTAINS span. That
    # is only safe because strip_spans has already removed every one; if a span
    # ever survived, the key would silently gain a <span class=""> the DB does
    # not have. The assertion inside key_for is what makes that loud.
    assert "<span" not in key_for(RED, "html")


def test_current_replay_is_idempotent_on_its_own_output():
    # save() re-sanitises the html shapes and every cell, so a value that is not
    # a fixed point would be rewritten under us and the read-back would fail.
    value, _ = value_for(RED, "html")
    assert current_replay(value, "html") == value
    cell, _ = value_for('<span style="color: red;">x</span>', "cell")
    assert current_replay(cell, "cell") == cell
