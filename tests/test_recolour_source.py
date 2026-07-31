"""The source walk and the key map, on a synthetic out/ tree.

The synthetic tree is deliberate: the real corpus is 835 files and asserting against
it would make this a change-detector. Task 1 and Task 8 measure the real corpus.
"""

import json

from courses.recolour.source import SKIP_CONFLICT
from courses.recolour.source import SKIP_FIDELITY
from courses.recolour.source import SKIP_REGION
from courses.recolour.source import SKIP_UNCHANGED
from courses.recolour.source import build_key_map
from courses.recolour.source import walk_source

RED = '<span style="color: red;">a</span>'
BLUE = '<span style="color: blue;">a</span>'


def _tree(tmp_path, files):
    """files: {"<part>/<name>.json": <python object>}"""
    for rel, payload in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload), "utf-8")
    return tmp_path


def test_walk_finds_every_shape(tmp_path):
    root = _tree(
        tmp_path,
        {
            "010_p/010_u.json": {
                "elements": [
                    {"type": "text", "body": RED},
                    {"type": "choice", "stem": RED, "choices": []},
                    {"type": "fill_gate", "stem": RED, "answers": []},
                    {"type": "fillblank", "stem": RED, "blanks": []},
                    {"type": "table", "data": {"cells": [[{"html": RED}]]}},
                ]
            }
        },
    )
    shapes = sorted(o.shape for o in walk_source(root, excluded_dirs=()))
    assert shapes == ["cell", "composed", "html", "html", "stem"]


def test_walk_recurses_into_spoilers_and_tabs(tmp_path):
    root = _tree(
        tmp_path,
        {
            "010_p/010_u.json": {
                "elements": [
                    {
                        "type": "spoiler",
                        "label": "L",
                        "elements": [{"type": "text", "body": RED}],
                    },
                    {
                        "type": "tabs",
                        "tabs": [
                            {
                                "id": "t1",
                                "label": "T",
                                "elements": [{"type": "text", "body": BLUE}],
                            }
                        ],
                    },
                ]
            }
        },
    )
    assert len(walk_source(root, excluded_dirs=())) == 2


def test_walk_skips_manifest_and_the_list_shaped_flags_file(tmp_path):
    # flags.json is a JSON LIST. Without the skip the walk raises
    # AttributeError: 'list' object has no attribute 'get'.
    root = _tree(
        tmp_path,
        {
            "010_p/manifest.json": {"part": {"order": 1}},
            "010_p/flags.json": [{"type": "text", "body": RED}],
            "010_p/010_u.json": {"elements": [{"type": "text", "body": RED}]},
        },
    )
    assert len(walk_source(root, excluded_dirs=())) == 1


def test_walk_honours_the_source_side_exclusion(tmp_path):
    root = _tree(
        tmp_path,
        {
            "001_zbiory_liczbowe/010_u.json": {
                "elements": [{"type": "text", "body": RED}]
            },
            "010_p/010_u.json": {"elements": [{"type": "text", "body": RED}]},
        },
    )
    occ = walk_source(root, excluded_dirs=("001_zbiory_liczbowe",))
    assert [o.part for o in occ] == ["010_p"]


def test_walk_ignores_switchgrid_line_stems_and_choice_option_text(tmp_path):
    # Out of backfill scope: line stems are not an RTE surface, and Choice.text
    # passes through none of the three sanitisers.
    #
    # Asserted on field_paths, NOT on emptiness: walk_source emits every non-empty
    # registry field, and the palette filter lives in build_key_map. The choice
    # element's own `stem` is legitimately walked -- only its option text is not.
    root = _tree(
        tmp_path,
        {
            "010_p/010_u.json": {
                "elements": [
                    {"type": "switch_grid", "prompt": "", "lines": [{"stem": RED}]},
                    {
                        "type": "choice",
                        "stem": "plain",
                        "choices": [{"text": RED, "is_correct": True}],
                    },
                ]
            }
        },
    )
    occ = walk_source(root, excluded_dirs=())
    assert [o.field_path for o in occ] == ["elements[1].stem"]
    assert build_key_map(occ).producers == 0  # neither carries palette colour


def test_only_palette_bearing_occurrences_produce_a_key(tmp_path):
    root = _tree(
        tmp_path,
        {
            "010_p/010_u.json": {
                "elements": [
                    {"type": "text", "body": RED},
                    {"type": "text", "body": '<span style="color: purple;">a</span>'},
                    {"type": "text", "body": "<p>plain</p>"},
                ]
            }
        },
    )
    km = build_key_map(walk_source(root, excluded_dirs=()))
    assert km.producers == 1
    assert len(km.entries) == 1
    assert km.emitted == 1
    assert km.emitted_occurrences == 1


def test_the_key_maps_to_a_DIFFERENT_value():
    from courses.recolour.source import Occurrence

    km = build_key_map([Occurrence("p", "f.json", "elements[0].body", "html", RED)])
    ((key, value),) = km.entries.items()
    assert key == "a"
    assert value == '<span class="tc-red">a</span>'


def test_a_no_op_colouring_is_named_unchanged_and_never_enters_the_map():
    # The failure mode the gate's `value != key` clause exists for. A span-only
    # colouriser leaves <strong style="color:red"> untouched, the sanitiser strips
    # `style`, and the value comes out byte-identical to the key -- a silent no-op
    # that would otherwise score as a success.
    #
    # The real colouriser does NOT have that bug, so this test constructs the shape
    # directly: a palette colour on a tag both sanitisers delete outright, where
    # key and value are both the empty string no matter what the colouriser does.
    from courses.recolour.source import Occurrence

    raw = '<script style="color: red;">a</script>'
    km = build_key_map([Occurrence("p", "f.json", "x", "html", raw)])
    # It DID carry palette colour, so it counts in the denominator...
    assert km.producers == 1
    # ...but it can never count in the numerator.
    assert km.entries == {}
    assert [r for _o, r in km.skips if r == SKIP_UNCHANGED]


def test_an_ordinary_occurrence_is_not_reported_as_unchanged():
    from courses.recolour.source import Occurrence

    km = build_key_map([Occurrence("p", "f.json", "x", "html", RED)])
    assert not [r for _o, r in km.skips if r == SKIP_UNCHANGED]


def test_two_different_colourings_of_one_key_are_refused():
    from courses.recolour.source import Occurrence

    km = build_key_map(
        [
            Occurrence("p", "f.json", "x", "html", RED),
            Occurrence("p", "g.json", "y", "html", BLUE),
        ]
    )
    assert km.entries == {}
    assert [r for _o, r in km.skips if r == SKIP_CONFLICT]


def test_a_conflict_stays_refused_when_the_first_colouring_recurs():
    # Stickiness. Without the `refused` set the third occurrence re-inserts the
    # key with RED's value and the run writes a colouring two sources disagree on.
    from courses.recolour.source import Occurrence

    km = build_key_map(
        [
            Occurrence("p", "f.json", "x", "html", RED),
            Occurrence("p", "g.json", "y", "html", BLUE),
            Occurrence("p", "h.json", "z", "html", RED),
        ]
    )
    assert km.entries == {}
    assert km.produced == []


def test_the_same_colouring_twice_is_not_a_conflict():
    from courses.recolour.source import Occurrence

    km = build_key_map(
        [
            Occurrence("p", "f.json", "x", "html", RED),
            Occurrence("p", "g.json", "y", "html", RED),
        ]
    )
    assert len(km.entries) == 1
    assert km.producers == 2
    assert not [r for _o, r in km.skips if r == SKIP_CONFLICT]


def test_a_lossy_round_trip_is_skipped_and_named():
    # The one guard between a lossy bs4 round-trip and a corrupted write. MEASURED
    # on the current corpus it never fires (0 of 319), which is exactly why it needs
    # a synthetic case: a branch that never executes in production and has no test
    # is a branch nobody knows is broken.
    #
    # An unclosed tag is the reliable trigger: bs4 closes it on serialisation, so
    # decode_contents() != source. MEASURED: '<p style="color: red;">a' round-trips
    # to '<p style="color: red;">a</p>'.
    from courses.recolour.source import Occurrence

    raw = '<p style="color: red;">a'
    km = build_key_map([Occurrence("p", "f.json", "x", "html", raw)])
    # It carries palette colour, so it counts in the denominator...
    assert km.producers == 1
    # ...but it is never written.
    assert km.entries == {}
    assert [r for _o, r in km.skips if r == SKIP_FIDELITY]


def test_a_region_intersecting_occurrence_is_refused_and_named():
    from courses.recolour.source import Occurrence

    occ = Occurrence(
        "p", "f.json", "x", "html", 'a \\(<span style="color: red;">x</span>+y\\) b'
    )
    km = build_key_map([occ])
    assert km.entries == {}
    # startswith, not ==: the stored reason is prefixed with the specific refusal
    # (`protected-region: colour intersects a maths region`). SKIP_UNCHANGED and
    # SKIP_CONFLICT are stored bare, which is what makes this one easy to miss.
    assert [r for _o, r in km.skips if r.startswith(SKIP_REGION)]


def test_per_part_counters_are_populated():
    from courses.recolour.source import Occurrence

    km = build_key_map(
        [
            Occurrence("010_p", "f.json", "x", "html", RED),
            Occurrence("020_q", "g.json", "y", "html", BLUE),
        ]
    )
    assert km.per_part["010_p"]["producers"] == 1
    assert km.per_part["020_q"]["producers"] == 1
