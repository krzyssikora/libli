"""Replay the import write path for one field, twice.

The KEY replays the sanitiser AS IT BEHAVED AT IMPORT TIME (the frozen LEGACY_*
allowlists), over the source with every <span> unwrapped. The VALUE replays the
CURRENT path over the coloured source. The two differ by construction, and that is
the point: a key that replays the current code yields `<strong class="">x</strong>`
where the DB holds `<strong>x</strong>`, and never matches.

The rule for choosing a composition is "reproduce the full import write path, in
order, including any save()-time sanitiser that runs after the builder's explicit
one" -- NOT "the sanitiser that owns the field", which is ambiguous for exactly the
fields that are sanitised twice.
"""

from functools import partial

from courses.recolour.colouriser import colourise
from courses.recolour.colouriser import strip_spans
from courses.sanitize import LEGACY_ALLOWED_CLASSES
from courses.sanitize import LEGACY_CELL_ALLOWED_CLASSES
from courses.sanitize import sanitize_cell
from courses.sanitize import sanitize_html
from courses.switchgrid import sanitize_stem_segments

# Which sanitiser composition each field shape replays:
#   html     sanitize_html
#            body, success_message, choice/numeric/shorttext stem
#   cell     sanitize_cell
#            table + filltable cells
#   stem     sanitize_stem_segments
#            fill gate, switch gate, guess_number stem
#   composed sanitize_html(sanitize_stem_segments(x))
#            fillblank stem -- the builder sanitises, then QuestionElement.save()
#            sanitises again
SHAPE_HTML = "html"
SHAPE_CELL = "cell"
SHAPE_STEM = "stem"
SHAPE_COMPOSED = "composed"
SHAPES = (SHAPE_HTML, SHAPE_CELL, SHAPE_STEM, SHAPE_COMPOSED)

_legacy_html = partial(sanitize_html, allowed_classes=LEGACY_ALLOWED_CLASSES)
_legacy_cell = partial(sanitize_cell, allowed_classes=LEGACY_CELL_ALLOWED_CLASSES)


def _legacy_stem(value):
    return sanitize_stem_segments(value, sanitiser=_legacy_cell)


_LEGACY = {
    SHAPE_HTML: _legacy_html,
    SHAPE_CELL: _legacy_cell,
    SHAPE_STEM: _legacy_stem,
    SHAPE_COMPOSED: lambda v: _legacy_html(_legacy_stem(v)),
}

_CURRENT = {
    SHAPE_HTML: sanitize_html,
    SHAPE_CELL: sanitize_cell,
    SHAPE_STEM: sanitize_stem_segments,
    SHAPE_COMPOSED: lambda v: sanitize_html(sanitize_stem_segments(v)),
}


def legacy_replay(value, shape):
    """The pre-slice-1 sanitiser composition for `shape`."""
    return _LEGACY[shape](value or "")


def current_replay(value, shape):
    """The post-slice-1 sanitiser composition for `shape`."""
    return _CURRENT[shape](value or "")


def key_for(raw, shape):
    """The exact string the loader stored for this source value."""
    stripped = strip_spans(raw)
    # The legacy replay uses the LIVE tag sets, which now contain `span`. That is
    # only inert because strip_spans has removed every one. A survivor would add a
    # <span class=""> the DB does not have and zero the key with no diagnostic.
    assert "<span" not in stripped, f"strip_spans left a span tag: {stripped[:120]!r}"
    return legacy_replay(stripped, shape)


def value_for(raw, shape):
    """(the coloured string to store, tc-* classes emitted)."""
    coloured, emitted = colourise(raw)
    return current_replay(coloured, shape), emitted
