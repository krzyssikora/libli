import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "courses/static/courses/css/courses.css"
EDITOR_CSS = ROOT / "courses/static/courses/css/editor.css"
TABLE_JS = ROOT / "courses/static/courses/js/table_editor.js"
FILL_JS = ROOT / "courses/static/courses/js/filltable_editor.js"


def test_courses_css_defines_table_element():
    css = CSS.read_text(encoding="utf-8")
    for cls in [
        ".el--table",
        ".el--table--border-grid",
        ".el--table--border-rows",
        ".el--table--border-header",
        ".el--table--border-none",
        ".ta-center",
        ".va-middle",
    ]:
        assert cls in css, f"missing table element class: {cls}"


def test_editor_css_styles_every_control_class_the_js_emits():
    """table_editor.js injects the row/column handles client-side, so nothing but
    a name match ties its class names to editor.css. They once drifted apart
    (`.table-row-handle` in CSS vs `.table-editor__rowctl` in JS), which left the
    hover-reveal handles permanently unstyled. Pin the contract.

    The pattern is a strict SUPERSET of the old `className = "…"` scan: it also
    catches the CELL_IMG_CLASS map's literals, which are never assigned via a
    bare `className = "…"` (classList.add reads them out of the map).
    """
    js = TABLE_JS.read_text(encoding="utf-8")
    css = EDITOR_CSS.read_text(encoding="utf-8")

    emitted = set(re.findall(r'"(table-editor__[\w-]+)"', js))
    assert emitted, "expected table_editor.js to assign table-editor__* classes"
    for cls in sorted(emitted):
        # Boundary-anchored on BOTH sides, and against editor.css ONLY -- never
        # concatenated with courses.css, where `.filltable-editor__img--small`
        # would satisfy a naive substring match on `.table-editor__img--small`.
        assert re.search(rf"(?<![\w-])\.{re.escape(cls)}(?![\w-])", css), (
            f"editor.css never styles .{cls} (emitted by table_editor.js)"
        )
    # Existence, not just naming: `.ta-center > .table-editor__img` would satisfy
    # the naming check above with the base rule itself entirely absent.
    assert re.search(r"^\.table-editor__img\s*\{", css, re.M)


def test_js_size_defaults_match_python_and_are_used():
    from courses.models import TableElement

    # Symmetric across both editor files (Task 8 Step 8 widens this loop): each
    # declares both constants and USES `|| CELL_IMAGE_INSERT` in its own
    # setImageCell. The INSERT needle pins the FULL statement, not the bare
    # `|| CELL_IMAGE_INSERT` token: the CELL_IMG_CLASS comment above the map
    # (`` `|| CELL_IMAGE_INSERT` serves conversion AND re-pick... ``) contains
    # that bare token too, so the narrower needle would stay green even with
    # setImageCell's real assignment deleted. Both editors' setImageCell
    # happens to spell the assignment identically (`td.dataset.size =
    # td.dataset.size || CELL_IMAGE_INSERT`), so one shared needle is correct
    # here -- but it is checked against EACH file's own source, not a
    # concatenation, so either file could fail independently.
    #
    # The DEFAULT needle has the same discrimination problem: each file has TWO
    # code occurrences of `|| CELL_IMAGE_DEFAULT` (the serialize assignment and
    # the size-select population), so a bare `"|| CELL_IMAGE_DEFAULT" in src`
    # needle stays green even with one of the two deleted. Pin the FULL
    # serialize statement instead, which both files spell identically.
    for js in (TABLE_JS, FILL_JS):
        src = js.read_text(encoding="utf-8")
        assert (
            f'var CELL_IMAGE_DEFAULT = "{TableElement.DEFAULT_CELL_IMAGE_SIZE}"' in src
        )
        assert (
            f'var CELL_IMAGE_INSERT = "{TableElement.EDITOR_INSERT_CELL_IMAGE_SIZE}"'
            in src
        )
        assert "size: td.dataset.size || CELL_IMAGE_DEFAULT" in src
        assert "td.dataset.size = td.dataset.size || CELL_IMAGE_INSERT" in src


def test_filltable_editor_classes_the_js_names_are_styled():
    js = FILL_JS.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")  # courses.css ONLY, never concatenated
    emitted = set(re.findall(r'"(filltable-editor__[\w-]+)"', js))
    assert emitted, "expected filltable_editor.js to name filltable-editor__* classes"
    for cls in sorted(emitted):
        assert re.search(rf"(?<![\w-])\.{re.escape(cls)}(?![\w-])", css), cls
    # And the base rule itself exists, not merely the name (`.ta-center >
    # .filltable-editor__img` satisfies the name check on its own). re.M is mandatory.
    assert re.search(r"^\.filltable-editor__img\s*\{", css, re.M)


def test_courses_css_defines_the_cell_image_scale():
    # Comments STRIPPED first, same as the sibling test below: the explanatory comment
    # this slice adds names `.cell-img--medium` (to record the equal-specificity trap),
    # so an unstripped boundary-anchored search is satisfied by the comment and the
    # medium entry cannot fail even with its rule deleted. Medium is the one preset with
    # e2e coverage, i.e. the entry least likely to be caught elsewhere.
    css = re.sub(r"/\*[\s\S]*?\*/", "", CSS.read_text(encoding="utf-8"))
    # Naming: every class is present, boundary-anchored on BOTH sides so
    # `.cell-img` is not satisfied by `.cell-img--small`.
    for cls in [
        "cell-img",
        "cell-img--small",
        "cell-img--medium",
        "cell-img--large",
        "cell-img--full",
    ]:
        assert re.search(rf"(?<![\w-])\.{re.escape(cls)}(?![\w-])", css), cls
    # Existence: the BASE RULE itself, not just the name. `.ta-center > .cell-img`
    # satisfies the naming check with the base rule entirely absent.
    assert re.search(r"^\.cell-img\s*\{", css, re.M)


def test_filltable_img_rule_is_deleted_not_merely_reduced():
    """The decision is deletion — a no-op stub invites re-adding max-width and
    re-opens the equal-specificity trap. The CLASS stays on the element."""
    # Comments are STRIPPED first: the explanatory comment this slice adds names
    # `.filltable__img` to record why it went, and a boundary-anchored regex would
    # match inside it, failing against the exact CSS this plan mandates.
    css = re.sub(r"/\*[\s\S]*?\*/", "", CSS.read_text(encoding="utf-8"))
    assert not re.search(r"(?<![\w-])\.filltable__img(?![\w-])", css)


def test_print_block_follows_the_preset_block():
    """@media print adds no specificity, so ordering is what makes it win.

    Anchor on the NEW rule. `170mm` already appears twice in courses.css — a comment
    near line 96 and C1's `.el--image--full img` block near line 107 — both roughly a
    thousand lines BEFORE the region this block lands in, so a bare
    `css.index("170mm")` is false wherever the new block sits.
    """
    css = CSS.read_text(encoding="utf-8")
    m = re.search(r"@media print\s*\{[^}]*\.cell-img--full[^}]*170mm", css, re.S)
    assert m, "no @media print block bounding .cell-img--full at 170mm"
    assert css.index(".cell-img--full") < m.start()
