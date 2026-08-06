"""Shared image-cell resolution for TableElement and FillTableElement.

Both models replace an image cell's `media` int pk with its MediaAsset for
rendering, with the same unresolved-asset fallback. They differ ONLY in the shape
of the replacement cell, so that shape is injected via `empty_cell` and there is
exactly ONE definition of the behaviour. This is single-definition-BY-CONSTRUCTION
rather than by test: tests/test_editor_twin_drift.py guards the two JS editors and
has no visibility into Python, so nothing would catch a copy-paste divergence here.
"""


def resolve_image_cells(cells, *, empty_cell, course=None):
    """`cells` with each image cell's int `media` pk replaced by its MediaAsset.

    One `in_bulk` pass. An unresolved pk degrades to `empty_cell(cell)` with the
    cell's `header`/`colspan`/`rowspan` CARRIED THROUGH — a dangling asset must
    never 500 a lesson, and must never silently un-span a cell and shift the grid
    (which is what `_ser_fill_table` has always done on the export side).

    `empty_cell` is a callable taking the original cell and returning only the
    model-specific BASE shape; carrying the span keys is this function's job, not
    the caller's — otherwise each caller would reimplement it and diverge.

    `course` scopes the lookup to that course's IMAGE assets, matching what
    clean_data validates. The editor passes it (it resolves author-submitted pks
    on a rejected save); the student render does not (its data already passed
    clean_data). An out-of-scope pk simply fails to resolve and takes the same
    fallback — no second branch, no second shape.

    MediaAsset is imported INSIDE the function so this module stays importable from
    `courses/models.py` at MODULE scope. Today the two delegators import `tablecells`
    function-locally, so a module-level `from courses.models import MediaAsset` would in
    fact resolve - but the guard is what keeps that refactor safe, and it is the same
    function-local pattern `_ser_fill_table` uses for the identical symbol.
    """
    from courses.models import MediaAsset

    # .get, not subscripting, and the same isinstance shape _ser_table uses: a stored
    # {"kind": "image"} with no `media` is reachable by this spec's own defensive
    # argument, and a KeyError here would 500 a lesson render.
    ids = [
        c["media"]
        for row in cells
        for c in row
        if isinstance(c, dict)
        and c.get("kind") == "image"
        and isinstance(c.get("media"), int)
        and not isinstance(c.get("media"), bool)
    ]
    if not ids:
        assets = {}
    elif course is None:
        assets = MediaAsset.objects.in_bulk(ids)
    else:
        assets = MediaAsset.objects.filter(
            course=course, kind="image", pk__in=ids
        ).in_bulk()

    out = []
    for row in cells:
        out_row = []
        for c in row:
            if not isinstance(c, dict) or c.get("kind") != "image":
                out_row.append(c)
                continue
            asset = assets.get(c.get("media"))
            if asset is not None:
                out_row.append({**c, "media": asset})
                continue
            fallback = empty_cell(c)
            for key in ("header", "colspan", "rowspan"):
                if key in c:
                    fallback[key] = c[key]
            out_row.append(fallback)
        out.append(out_row)
    return out
