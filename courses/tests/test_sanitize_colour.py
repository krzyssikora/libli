from courses.colour import TC_CLASS_TAGS
from courses.sanitize import ALIGN_CLASS_VALUES
from courses.sanitize import LEGACY_ALLOWED_CLASSES
from courses.sanitize import LEGACY_CELL_ALLOWED_CLASSES
from courses.sanitize import sanitize_cell
from courses.sanitize import sanitize_html


def test_body_keeps_tc_class_on_every_allowed_carrier():
    for tag in sorted(TC_CLASS_TAGS):
        attrs = ' href="/x/"' if tag == "a" else ""
        out = sanitize_html(f'<{tag}{attrs} class="tc-red">x</{tag}>')
        assert "tc-red" in out, f"{tag} lost its colour class: {out}"


def test_body_strips_tc_class_on_a_tag_outside_the_carrier_set():
    assert "tc-red" not in sanitize_html('<p class="tc-red">x</p>')


def test_body_strips_a_foreign_class_and_all_inline_style():
    out = sanitize_html('<span class="evil" style="color: red">x</span>')
    assert "evil" not in out
    assert "style" not in out


def test_cell_keeps_tc_class():
    assert "tc-blue" in sanitize_cell('<b class="tc-blue">x</b>')
    assert "tc-blue" in sanitize_cell('<span class="tc-blue">x</span>')


def test_cell_does_not_allow_tc_on_br():
    """br is in CELL_TAGS but not TC_CLASS_TAGS, so it must not gain a class key."""
    assert "tc-red" not in sanitize_cell('<br class="tc-red">')


def test_both_paths_are_idempotent():
    for sanitise in (sanitize_html, sanitize_cell):
        once = sanitise('<span class="tc-green">x</span>')
        assert sanitise(once) == once


def test_cell_still_protects_maths_spans():
    assert sanitize_cell(r"\(a<b\)") == r"\(a&lt;b\)"


def test_align_values_are_not_mutated_by_the_colour_merge():
    """ALLOWED_CLASSES was built by a comprehension binding ONE set object to seven
    keys. Any in-place merge would widen the align family for every tag at once."""
    assert ALIGN_CLASS_VALUES == {"ta-left", "ta-center", "ta-right"}


def test_allowlist_entries_are_not_shared_objects():
    """Same aliasing trap, one level down: two keys must not be the same set."""
    from courses.sanitize import ALLOWED_CLASSES
    from courses.sanitize import CELL_ALLOWED_CLASSES

    for mapping in (ALLOWED_CLASSES, CELL_ALLOWED_CLASSES):
        sets = list(mapping.values())
        for i, first in enumerate(sets):
            for second in sets[i + 1 :]:
                assert first is not second, "allowlist entries share one set object"


def test_legacy_snapshot_excludes_the_colour_family():
    """Slice 2's key generator replays the PRE-colour sanitiser: the DB holds
    <strong>x</strong>, but post-change nh3 emits <strong class=""> for a tag that is
    an allowed_classes key. Freezing the old allowlist is what keeps keys matching."""
    # Pin the exact key set: an emptiness-only check passes vacuously for {} and would
    # absorb a drift instead of catching it.
    assert set(LEGACY_ALLOWED_CLASSES) == {
        "p",
        "div",
        "h2",
        "h3",
        "h4",
        "blockquote",
        "li",
    }
    assert LEGACY_CELL_ALLOWED_CLASSES == {}
    for values in LEGACY_ALLOWED_CLASSES.values():
        assert values == {"ta-left", "ta-center", "ta-right"}
        assert not any(v.startswith("tc-") for v in values)


def test_marker_interior_markup_is_knowingly_accepted():
    """Allowing span widened what survives inside {{...}}. The editor refuses to
    produce this (D10), but the server path does not reject it. Recorded, not fixed.
    If this ever fails, someone closed the hole — update the spec's D10 section.
    """
    assert "<span>" in sanitize_html("<p>{{<span>a</span>|b}}</p>")
