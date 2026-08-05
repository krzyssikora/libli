import pytest

from courses.models import TableElement

pytestmark = pytest.mark.django_db


def _grid(rows, cols, **top):
    cells = [
        [{"html": f"r{r}c{c}", "halign": "left", "valign": "top"} for c in range(cols)]
        for r in range(rows)
    ]
    return {
        "header_row": False,
        "header_col": False,
        "border": "grid",
        "cells": cells,
        **top,
    }


def test_renders_table_with_overflow_wrapper():
    html = TableElement(data=_grid(2, 2)).render()
    assert "el--table" in html and "<table" in html
    assert "el--table--border-grid" in html


def test_header_row_makes_first_row_th_scope_col():
    html = TableElement(data=_grid(2, 2, header_row=True)).render()
    assert 'scope="col"' in html


def test_header_col_makes_first_col_th_scope_row():
    html = TableElement(data=_grid(2, 2, header_col=True)).render()
    assert 'scope="row"' in html


def test_corner_th_has_no_scope():
    html = TableElement(data=_grid(2, 2, header_row=True, header_col=True)).render()
    # In a 2x2 with both headers: exactly one scope="col" (the top-right header
    # cell) and one scope="row" (the bottom-left) — the (0,0) corner <th> gets
    # NO scope. Counting the scopes proves the corner is scope-less without
    # depending on class-attribute whitespace.
    assert html.count('scope="col"') == 1
    assert html.count('scope="row"') == 1


def test_alignment_classes_emitted():
    d = _grid(1, 1)
    d["cells"][0][0].update(halign="center", valign="middle")
    html = TableElement(data=d).render()
    assert "ta-center" in html and "va-middle" in html


def test_border_header_both_toggles_off_is_noop_not_error():
    html = TableElement(data=_grid(2, 2, border="header")).render()
    assert "el--table--border-header" in html  # renders, no exception


def test_math_left_as_raw_text_for_client_typeset():
    d = _grid(1, 1)
    d["cells"][0][0]["html"] = r"\(x\)"
    html = TableElement(data=d).render()
    assert r"\(x\)" in html


def test_image_cell_renders_the_asset_with_preset_class_and_zoom_hook(
    course_with_image,
):
    from courses.models import TableElement

    course, asset = course_with_image
    el = TableElement.objects.create(data=TableElement.normalize_data({
        "header_row": False, "header_col": False, "border": "grid",
        "cells": [[{"kind": "image", "media": asset.pk, "alt": "a graph",
                    "size": "medium"}]],
    }))
    html = el.render()
    assert 'class="cell-img cell-img--medium"' in html
    assert f'src="{asset.file.url}"' in html
    assert 'alt="a graph"' in html
    assert "data-zoomable" in html


def test_partial_defaults_size_when_the_key_is_absent(course_with_image):
    """|default:'full' — a bare {{ cell.size }} yields `cell-img--`, which matches no
    rule, and nothing else caps the image once max-width leaves the base.

    Rendered at the PARTIAL level with a context that has no `size` key at all. Going
    through el.render() cannot falsify the mutant: render() calls normalize_data,
    which materialises size:"full", so `cell.size` is always populated at the template
    and the output is `cell-img--full` with or without the filter. (This is the shape
    tests/test_imagezoom_render.py already uses for _filltable_cell.html.)
    """
    from django.template.loader import render_to_string

    _course, asset = course_with_image
    html = render_to_string(
        "courses/elements/_table_cell.html",
        {"cell": {"kind": "image", "media": asset, "alt": ""}},
    )
    assert "cell-img--full" in html
    assert 'cell-img--"' not in html
    assert "cell-img-- " not in html


def test_text_cell_bytes_are_unchanged_by_the_partial_factoring(db):
    """The mutant: a trailing newline or a leading indent in _table_cell.html.
    {% spaceless %} strips whitespace only BETWEEN tags, so whitespace adjacent to
    TEXT survives and changes rendered bytes for all 7,246 existing cells.
    The cell MUST be non-empty: with html:"" the include emits only its newline and
    `<td>\\n</td>` collapses to `<td></td>`, so an empty fixture cannot falsify."""
    from courses.models import TableElement

    el = TableElement.objects.create(data=TableElement.normalize_data({
        "header_row": False, "header_col": False, "border": "grid",
        "cells": [[{"html": "cell text", "halign": "center", "valign": "top"}]],
    }))
    assert '<td class="ta-center va-top">cell text</td>' in el.render()


def test_header_cell_bytes_are_unchanged_too(db):
    """Four of the five branches are <th>; a rule phrased only for <td> leaves a
    header-row table's bytes unpinned."""
    from courses.models import TableElement

    el = TableElement.objects.create(data=TableElement.normalize_data({
        "header_row": True, "header_col": False, "border": "grid",
        "cells": [[{"html": "head text", "halign": "left", "valign": "top"}]],
    }))
    assert '<th scope="col" class="ta-left va-top">head text</th>' in el.render()


def test_table_cell_partial_has_no_trailing_newline():
    """Byte-level: an editor will silently re-add one."""
    import pathlib

    from django.conf import settings

    p = pathlib.Path(settings.BASE_DIR) / "templates/courses/elements/_table_cell.html"
    assert p.read_bytes()[-1:] not in (b"\n", b"\r")
