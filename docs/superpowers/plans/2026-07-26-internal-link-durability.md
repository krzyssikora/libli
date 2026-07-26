# Internal Link Durability (Part 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep internal links pointing at the right node when content is exported and imported through the Studio UI, and warn an author before they delete a node other content links to.

**Architecture:** One registry (`courses/richtext.py`) enumerates every place an internal link can be stored — 16 models, 27 plain `TextField`s — and both features consume it. Export records which link targets are inside the exported set; import rewrites onto the new pks in a post-pass over the created instances. The anchor scanner is attribute-aware because nh3 does **not** escape `>` inside attribute values.

**Tech Stack:** Django, pytest + pytest-django, nh3.

**Spec:** `docs/superpowers/specs/2026-07-26-internal-link-durability-design.md`

**Depends on:** Part 1 (`2026-07-26-internal-content-links.md`) — the `/courses/n/<pk>/` route must exist. **Does not include the production cutover**: `migrate_course_content` is part 3, and running the mat-pp cutover on part 2 alone would silently flatten every cross-part link.

## Global Constraints

- Run everything through `uv run`.
- `uv run pytest` defaults to `-m 'not e2e'`; nothing in this plan needs a browser.
- Use `tests.factories.TEST_PASSWORD`; never hardcode a password.
- All new user-visible strings are translatable, with **non-empty** Polish msgstrs (`tests/test_i18n_po_health.py::test_pl_has_no_untranslated_msgid`).
- Falsify every guard: delete the behaviour, confirm RED, restore.
- The registry is the single source of "where can a link live". Nothing else may enumerate rich-text fields.

---

### Task 1: `courses/richtext.py` — the registry and helpers

**Files:**
- Create: `courses/richtext.py`
- Test: `tests/test_richtext.py` (create)

**Interfaces:**
- Consumes: `courses:node_permalink` (part 1).
- Produces:
  - `RICH_TEXT_FIELDS: list[tuple[type[Model], str]]` — 27 entries over 16 models.
  - `find_link_targets(html) -> set[int]`
  - `rewrite_links(html, mapping, *, on_missing) -> tuple[str, int]` where `on_missing` is `"keep"` or `"unwrap"`, and the int is the flattened count.
  - `iter_rich_text(instance) -> Iterator[tuple[str, str]]` yielding `(field_name, value)`.
  - `rewrite_instance(instance, mapping, *, on_missing) -> tuple[list[str], int]` yielding `(changed field names, flattened)`.
  - `count_inbound_links(course, node) -> int`

  Tasks 2, 3 and 4 use these names exactly.

- [ ] **Step 1: Write the failing tests for the scanner**

Create `tests/test_richtext.py`:

```python
import pytest

from courses.richtext import (
    RICH_TEXT_FIELDS,
    find_link_targets,
    rewrite_links,
)


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
        '<a title="unterminated href="/courses/n/12/">x</a>',   # unterminated quote
        '<a href="/courses/n/12/"',                              # no unquoted >
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


def test_registry_shape():
    assert len(RICH_TEXT_FIELDS) == 27
    assert len({m for m, _f in RICH_TEXT_FIELDS}) == 16


def test_registry_excludes_switchgrid():
    # No authoring surface (data-stem, not data-rte-source, so part 1's dialog can
    # never put a link there) AND sanitize_cell strips any anchor on import. Machinery
    # with nothing to do.
    from courses.models import SwitchGridElement

    assert all(m is not SwitchGridElement for m, _f in RICH_TEXT_FIELDS)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_richtext.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'courses.richtext'`.

- [ ] **Step 3: Write the module**

Create `courses/richtext.py`:

```python
"""Where an internal link can live, and how to scan or rewrite one.

One registry, two consumers: the transfer link-rewrite and the delete-time inbound
count. Keeping it in one place is the point -- two overlapping guesses about "which
fields hold rich text" would drift.
"""

import re

from django.db.models import Q

from courses.models import (
    CalloutElement,
    Element,
    FillGateElement,
    GuessNumberElement,
    QuestionElement,
    SpoilerElement,
    SwitchGateElement,
    TextElement,
)

# Introspected, and safe ONLY here: every concrete question type inherits the same two
# fields from the same abstract QuestionElement.save(), so a new question type is
# covered automatically. No such uniformity exists among the other element types, which
# are listed by hand below.
CONCRETE_QUESTION_MODELS = [
    m for m in QuestionElement.__subclasses__() if not m._meta.abstract
]

# 16 models / 27 fields. Each entry traced to an actual sanitize_html call site, not
# read off field names:
#   - body/success_message are sanitised in save()
#   - the three `stem`s are sanitised FORM-side and deliberately not in save(), because
#     sentinel-token stems must go sanitize_html -> strip_sentinel -> parse in order
#   - the question models inherit stem/explanation from QuestionElement.save()
# SwitchGridElement.lines[*].stem is deliberately absent -- see the module docstring in
# the spec: no authoring surface, and sanitize_cell destroys any anchor on import.
RICH_TEXT_FIELDS = [
    (TextElement, "body"),
    (SpoilerElement, "body"),
    (CalloutElement, "body"),
    (FillGateElement, "stem"),
    (GuessNumberElement, "stem"),
    (GuessNumberElement, "success_message"),
    (SwitchGateElement, "stem"),
] + [(m, f) for m in CONCRETE_QUESTION_MODELS for f in ("stem", "explanation")]

_FIELDS_BY_MODEL = {}
for _model, _field in RICH_TEXT_FIELDS:
    _FIELDS_BY_MODEL.setdefault(_model, []).append(_field)

# Anchored, matching part 1's dialog exactly. A prefix match would make the delete
# count and the rewrite disagree with the dialog about what an internal link is.
PERMALINK_PREFIX = "/courses/n/"
_PERMALINK = re.compile(r"^/courses/n/(\d+)/$")


class _Unscannable(Exception):
    """The body met a fail-closed condition; return it byte-identical."""


def _scan_anchors(html):
    """Yield (tag_start, tag_end, href_span) for every <a> open tag.

    Attribute-aware on purpose. MEASURED: nh3 does NOT escape `>` inside attribute
    values, and `title` is an allowed <a> attribute, so `<a title="a > b" href=...>`
    is ordinary sanitised content. A naive `<a[^>]*>` matches `<a title="a >` -- a
    syntactically CLEAN match of the wrong span, which silently misses the href
    instead of failing. So consume quoted values until an UNQUOTED '>'.
    """
    i = 0
    n = len(html)
    while True:
        m = re.compile(r"<a(?=[\s>])", re.I).search(html, i)
        if not m:
            return
        j = m.end()
        href = None
        while j < n:
            c = html[j]
            if c == ">":
                break
            if c in "\"'":
                quote = c
                k = html.find(quote, j + 1)
                if k == -1:
                    raise _Unscannable("unterminated quoted attribute value")
                j = k + 1
                continue
            am = re.compile(r"href\s*=\s*(\"([^\"]*)\"|'([^']*)')", re.I).match(html, j)
            if am:
                href = (
                    am.group(2) if am.group(2) is not None else am.group(3),
                    am.start(1),
                    am.end(1),
                )
                j = am.end()
                continue
            j += 1
        else:
            raise _Unscannable("<a with no unquoted '>'")
        yield m.start(), j + 1, href
        i = j + 1


def find_link_targets(html):
    """Node pks referenced by an internal-link href. Never matches visible text."""
    if not html:
        return set()
    out = set()
    try:
        for _s, _e, href in _scan_anchors(html):
            if not href:
                continue
            mm = _PERMALINK.match(href[0])
            if mm:
                out.add(int(mm.group(1)))
    except _Unscannable:
        return set()
    return out


def rewrite_links(html, mapping, *, on_missing):
    """Remap internal-link hrefs. Returns (html, flattened_count).

    Only <a> href ATTRIBUTES are touched -- never text content. A bs4 round trip would
    re-escape entities (see the repo's recorded str(Tag) trap) and stored bodies carry
    \\(...\\) math whose escaping sanitize.py::_canon_math is precise about; a naive
    whole-document regex would rewrite a literal /courses/n/12/ that an author typed in
    prose. On any fail-closed condition the WHOLE body comes back byte-identical and
    contributes 0 -- never mangled markup.
    """
    if not html:
        return html, 0
    try:
        anchors = list(_scan_anchors(html))
    except _Unscannable:
        return html, 0

    edits = []           # (start, end, replacement) on the ORIGINAL string
    flattened = 0
    for start, end, href in anchors:
        if not href:
            continue
        mm = _PERMALINK.match(href[0])
        if not mm:
            continue
        pk = int(mm.group(1))
        if pk in mapping:
            new = f"{PERMALINK_PREFIX}{mapping[pk]}/"
            edits.append((href[1], href[2], f'"{new}"'))
        elif on_missing == "unwrap":
            close = re.compile(r"</a\s*>", re.I).search(html, end)
            if close is None:
                return html, 0          # fail closed: no matching </a>
            edits.append((start, end, ""))
            edits.append((close.start(), close.end(), ""))
            flattened += 1

    if not edits:
        return html, 0
    out = []
    cursor = 0
    for start, end, repl in sorted(edits):
        out.append(html[cursor:start])
        out.append(repl)
        cursor = end
    out.append(html[cursor:])
    return "".join(out), flattened


def iter_rich_text(instance):
    """Yield (field_name, value) for every registry field on one element instance."""
    for field in _FIELDS_BY_MODEL.get(type(instance), []):
        yield field, getattr(instance, field, "") or ""


def rewrite_instance(instance, mapping, *, on_missing):
    """Rewrite every registry field on one instance.

    Returns (changed field names, flattened count). The caller saves with
    update_fields=changed, so no caller has to know the registry's shape.
    """
    changed = []
    flattened = 0
    for field, value in iter_rich_text(instance):
        new, flat = rewrite_links(value, mapping, on_missing=on_missing)
        flattened += flat
        if new != value:
            setattr(instance, field, new)
            changed.append(field)
    return changed, flattened


def count_inbound_links(course, node):
    """Distinct Element join rows ELSEWHERE in `course` linking into `node`'s subtree.

    Elements, not anchors: two anchors in one body pointing at two doomed nodes count
    once, because the author's unit of repair is "this element needs editing". And
    outside the subtree, because a link INSIDE the doomed subtree dies with its target
    -- counting those would report a large number for a self-contained part whose
    lessons cross-link each other, the opposite of the warning's purpose.

    Query shape matters. Matching each subtree pk as its own LIKE would build one OR
    term per (pk x field) -- hundreds across 16 models for a big part. Instead: one
    course-scoped query per model on the CONSTANT substring, then intersect in Python
    on the few rows that hold any internal link at all.
    """
    subtree = set(node._subtree_node_ids())
    total = 0
    for model, fields in _FIELDS_BY_MODEL.items():
        predicate = Q()
        for field in fields:
            predicate |= Q(**{f"{field}__contains": PERMALINK_PREFIX})
        rows = (
            model.objects.filter(predicate)
            .filter(elements__unit__course=course)
            .exclude(elements__unit_id__in=subtree)
            .distinct()
        )
        for row in rows:
            targets = set()
            for _field, value in iter_rich_text(row):
                targets |= find_link_targets(value)
            if targets & subtree:
                total += 1
    return total
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_richtext.py -q`
Expected: PASS.

- [ ] **Step 5: Falsify the attribute-aware scanner**

Temporarily replace `_scan_anchors` with a naive `re.finditer(r"<a[^>]*>", html)`-based version. Run the tests. Expected: both `test_raw_gt_inside_an_attribute` cases FAIL. Restore.

- [ ] **Step 6: Commit**

```bash
git add courses/richtext.py tests/test_richtext.py
git commit -m "feat(links): rich-text registry + attribute-aware link scanner"
```

---

### Task 2: The registry drift guard

**Files:**
- Test: `tests/test_richtext_drift.py` (create)

**Interfaces:**
- Consumes: `RICH_TEXT_FIELDS`, `CONCRETE_QUESTION_MODELS` (Task 1).
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Write the guard**

Create `tests/test_richtext_drift.py`:

```python
"""A new element type with a rich-text body that nobody adds to RICH_TEXT_FIELDS would
silently escape both the transfer rewrite and the delete warning. This is the tripwire.

It greps the WHOLE courses/ package, not a hand-maintained file list: an earlier draft
allowlisted three files, missed templatetags/courses_extras.py outright, and could not
have seen a call site added in any other module (courses/switchgrid.py already
establishes that helper modules do sanitising work).
"""

import ast
from pathlib import Path

from courses.richtext import CONCRETE_QUESTION_MODELS

COURSES = Path(__file__).resolve().parent.parent / "courses"

# (file, qualname, assignment target) MULTISET. Three refinements, each load-bearing:
#   - qualname (not def) because def names and targets repeat across classes: the 14
#     sites collapse to just 8 distinct (file, def, target) triples, so copying
#     TextElement -- a `body` field plus `save: self.body = sanitize_html(self.body)` --
#     would produce a triple ALREADY in the set and the guard would stay green for the
#     exact case it exists to catch.
#   - the target, because QuestionElement.save() already holds two calls.
#   - a multiset, for two calls sharing one qualname AND one target in one method.
# Third element is None when the call's result is not assigned (a bare return, or a
# call nested in an expression such as a keyword argument).
EXPECTED = [
    ("models.py", "TextElement.save", "self.body"),
    ("models.py", "SpoilerElement.save", "self.body"),
    ("models.py", "CalloutElement.save", "self.body"),
    ("models.py", "GuessNumberElement.save", "self.success_message"),
    ("models.py", "QuestionElement.save", "self.stem"),
    ("models.py", "QuestionElement.save", "self.explanation"),
    ("element_forms.py", "FillGateElementForm.clean_stem", "clean"),
    ("element_forms.py", "GuessNumberElementForm.clean_stem", "clean"),
    ("element_forms.py", "SwitchGateElementForm.clean", "clean_stem"),
    ("element_forms.py", "SwitchGridElementForm.clean", "clean_stem"),
    ("element_forms.py", "FillBlankQuestionElementForm.clean_stem", "clean"),
    ("element_forms.py", "DragFillBlankQuestionElementForm.clean_stem", "clean"),
    ("transfer/importer.py", "_build_guess_number", None),
    # Render-time re-sanitise (the |sanitize filter), NOT a storage location. Recorded
    # rather than omitted, so the baseline is the whole truth.
    ("templatetags/courses_extras.py", "sanitize", None),
]


def _sites():
    found = []
    for path in sorted(COURSES.rglob("*.py")):
        rel = path.relative_to(COURSES).as_posix()
        if rel.startswith("tests/") or rel == "sanitize.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        stack = []

        class V(ast.NodeVisitor):
            def _named(self, node):
                stack.append(node.name)
                self.generic_visit(node)
                stack.pop()

            visit_ClassDef = visit_FunctionDef = _named

            def visit_Assign(self, node):
                for call in ast.walk(node.value):
                    if _is_sanitize(call):
                        found.append((rel, ".".join(stack), _target(node)))
                self.generic_visit(node)

            def generic_visit(self, node):
                # Calls not on an Assign RHS record target None.
                if isinstance(node, ast.Call) and _is_sanitize(node):
                    parents = getattr(node, "_seen", False)
                    if not parents:
                        pass
                super().generic_visit(node)

        def _is_sanitize(node):
            return (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "sanitize_html"
            )

        def _target(assign):
            t = assign.targets[0]
            if isinstance(t, ast.Attribute):
                return f"{getattr(t.value, 'id', '?')}.{t.attr}"
            if isinstance(t, ast.Name):
                return t.id
            return None

        assigned = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for sub in ast.walk(node.value):
                    if _is_sanitize(sub):
                        assigned.add(id(sub))

        # Walk once with a qualname stack, recording every call.
        def walk(node, stack):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.ClassDef, ast.FunctionDef)):
                    walk(child, stack + [child.name])
                    continue
                if isinstance(child, ast.Assign):
                    tgt = _target(child)
                    for sub in ast.walk(child.value):
                        if _is_sanitize(sub):
                            found.append((rel, ".".join(stack), tgt))
                    continue
                for sub in ast.walk(child):
                    if _is_sanitize(sub) and id(sub) not in assigned:
                        found.append((rel, ".".join(stack), None))
                        break
                walk(child, stack)

        walk(tree, [])
    return found


def test_sanitize_html_call_sites_match_the_registry_baseline():
    got = sorted(_sites())
    expected = sorted(EXPECTED)
    assert got == expected, (
        "The set of sanitize_html() call sites changed.\n"
        "If the new site is on a form whose Meta.model is in CONCRETE_QUESTION_MODELS "
        "AND its field is stem/explanation, it is covered automatically -- just update "
        "EXPECTED.\n"
        "Otherwise courses/richtext.py::RICH_TEXT_FIELDS needs an entry OR a documented "
        "exclusion (see the switch-grid precedent in the spec).\n"
        f"got:      {got}\nexpected: {expected}"
    )


def test_question_models_are_introspected_not_listed():
    assert len(CONCRETE_QUESTION_MODELS) == 10
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/test_richtext_drift.py -q`
Expected: PASS. If the collected sites differ from `EXPECTED`, read the diff — either the AST walk is wrong (fix the walk) or the repo genuinely changed (fix `EXPECTED`). Do not "make it pass" by pasting the output without reading it.

- [ ] **Step 3: Falsify — the cheapest drift case**

Add to `courses/models.py`, inside `TextElement`, a second sanitised field:

```python
    subtitle = models.TextField(blank=True)
```

and in its `save()`, above `super().save(...)`:

```python
        self.subtitle = sanitize_html(self.subtitle)
```

Run: `uv run pytest tests/test_richtext_drift.py -q`
Expected: FAIL — the multiset gains `("models.py", "TextElement.save", "self.subtitle")`. **This is the case a `(file, def, target)` triple would have missed.** Now revert both edits (no migration needed since you never ran `makemigrations`).

- [ ] **Step 4: Commit**

```bash
git add tests/test_richtext_drift.py
git commit -m "test(links): drift guard over every sanitize_html call site"
```

---

### Task 3: Export `link_nodes` and bump the archive format

**Files:**
- Modify: `courses/transfer/schema.py` (`FORMAT_VERSION`, `validate_document`)
- Modify: `courses/transfer/export.py`
- Modify: `tests/test_transfer_schema.py:57`, `tests/test_tabs_transfer.py` (rename + bump), `tests/test_table_transfer.py:265` (stale comment)
- Test: `tests/test_link_transfer.py` (create)

**Interfaces:**
- Consumes: `iter_rich_text`, `find_link_targets` (Task 1).
- Produces: `document["link_nodes"]` — a dict of decimal-string old pk → export id (`"n7"`). Task 4 consumes it.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_link_transfer.py` (the import half arrives in Task 4):

```python
import pytest

from courses.transfer.export import build_export
from courses.transfer.schema import FORMAT_VERSION, TransferError, validate_document
from courses.models import TextElement
from tests.factories import ContentNodeFactory, CourseFactory, add_element


def _text(body):
    """A saved TextElement. There is no TextElementFactory; this is the repo's idiom
    (see tests/test_guessnumber_endpoint.py). Note save() sanitises the body -- a
    relative href passes through untouched, which is the whole premise."""
    obj = TextElement(body=body)
    obj.save()
    return obj

pytestmark = pytest.mark.django_db


def _course_with_link():
    course = CourseFactory()
    chapter = ContentNodeFactory(course=course, kind="chapter", parent=None, title="Ch")
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=chapter, title="U"
    )
    el = _text(f'<a href="/courses/n/{chapter.pk}/">ch</a>')
    add_element(unit, el)
    return course, chapter, unit


def test_export_records_in_scope_link_targets():
    course, chapter, _unit = _course_with_link()
    _manifest, document, _assets, _problems = build_export(course)
    assert str(chapter.pk) in document["link_nodes"]
    assert document["link_nodes"][str(chapter.pk)].startswith("n")


def test_export_leaves_bodies_byte_identical():
    course, chapter, _unit = _course_with_link()
    _m, document, _a, _p = build_export(course)
    bodies = [e["data"]["body"] for e in document["elements"] if e["type"] == "text"]
    assert bodies == [f'<a href="/courses/n/{chapter.pk}/">ch</a>']


def test_format_version_is_6():
    assert FORMAT_VERSION == 6


def test_v5_archive_without_link_nodes_still_validates():
    # setdefault BEFORE _exact_keys is what makes the key optional in both directions:
    # without it a v5 doc fails "missing the key", and a new doc fails "unknown key".
    course, _chapter, _unit = _course_with_link()
    _m, document, _a, _p = build_export(course)
    del document["link_nodes"]
    validate_document(document, kind="course")   # must not raise


@pytest.mark.parametrize(
    "bad",
    [
        [],                                  # not a dict
        {"abc": "n1"},                        # non-decimal key
        {"1": 2},                             # non-string value
        {"1" * 20: "n1"},                     # over-long key
    ],
)
def test_malformed_link_nodes_is_a_transfer_error(bad):
    course, _chapter, _unit = _course_with_link()
    _m, document, _a, _p = build_export(course)
    document["link_nodes"] = bad
    with pytest.raises(TransferError):
        validate_document(document, kind="course")
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_link_transfer.py -q`
Expected: FAIL — `KeyError: 'link_nodes'`.

- [ ] **Step 3: Bump the version and admit the key**

In `courses/transfer/schema.py`:

```python
FORMAT_VERSION = 6
```

In `validate_document`, **before** the existing `_exact_keys(doc, ...)` call:

```python
    # Optional-key pattern, mirroring the FORMAT_VERSION-2 width/height addition in
    # payloads.py. _exact_keys both REQUIRES every listed key and REJECTS every
    # unlisted one, so without this a v5 archive fails "missing the key 'link_nodes'"
    # and a new archive fails "unknown key 'link_nodes'".
    if isinstance(doc, dict):
        doc.setdefault("link_nodes", {})
```

Add `"link_nodes"` to the key list in that `_exact_keys` call, then validate its shape immediately after the `media = check_list(...)` line:

```python
    link_nodes = doc["link_nodes"]
    if not isinstance(link_nodes, dict):
        _err(_("course.json: link_nodes must be an object."))
    if len(link_nodes) > settings.TRANSFER_MAX_NODES:
        _err(
            _("course.json: link_nodes lists more than %(n)d entries."),
            n=settings.TRANSFER_MAX_NODES,
        )
    for key, value in link_nodes.items():
        # Length cap matters: a 100_000-digit key would make a bare int() raise
        # ValueError past CPython's 4300-digit conversion limit, turning a hostile
        # archive into a 500 -- which these validators exist to prevent.
        if not isinstance(key, str) or not key.isdecimal() or len(key) > 12:
            _err(_("course.json: link_nodes has an invalid node id."))
        if not isinstance(value, str):
            _err(_("course.json: link_nodes has an invalid archive reference."))
```

- [ ] **Step 4: Emit the map at export**

In `courses/transfer/export.py`, in the pass that walks joins and builds `element_dicts`, accumulate targets. Place the scan **after** the existing `if join.content_object is None: ... continue` guard — a broken join contributes no link targets, and `iter_rich_text(None)` would raise:

```python
    referenced = set()
    ...
        # inside the loop, after the content_object-is-None guard:
        for _field, value in iter_rich_text(join.content_object):
            referenced |= find_link_targets(value)
```

Then, where `document` is assembled:

```python
        # Only targets INSIDE the exported set. Scanning the concrete instances (not
        # the payload dicts) is the only option consistent with the registry: element
        # dicts are {"type": ..., "data": {payload keys}}, and applying a (model, field)
        # registry to those would need both a type_key->model map and a
        # field->payload-key map -- a second vocabulary the importer deliberately avoids.
        "link_nodes": {
            str(pk): node_ids[pk] for pk in sorted(referenced) if pk in node_ids
        },
```

Add the imports at the top of `export.py`:

```python
from courses.richtext import find_link_targets
from courses.richtext import iter_rich_text
```

- [ ] **Step 5: Update the two version assertions**

In `tests/test_transfer_schema.py:57`, change `assert FORMAT_VERSION == 5` to `== 6`.
In `tests/test_tabs_transfer.py`, rename `test_format_version_is_5` to `test_format_version_is_6` and bump its assertion.
In `tests/test_table_transfer.py:265`, update the stale comment `(4 <= FORMAT_VERSION=5)` to `=6`.

- [ ] **Step 6: Run**

Run: `uv run pytest tests/test_link_transfer.py tests/test_transfer_schema.py tests/test_tabs_transfer.py tests/test_table_transfer.py -q`
Expected: PASS.

- [ ] **Step 7: Falsify the setdefault**

Remove the `doc.setdefault("link_nodes", {})` line. Run
`uv run pytest tests/test_link_transfer.py -q`. Expected:
`test_v5_archive_without_link_nodes_still_validates` FAILS with "missing the key". Restore.

- [ ] **Step 8: Commit**

```bash
git add courses/transfer/schema.py courses/transfer/export.py tests/
git commit -m "feat(links): export link_nodes; archive FORMAT_VERSION 5 -> 6"
```

---

### Task 4: Import-side rewrite

**Files:**
- Modify: `courses/transfer/importer.py`
- Modify: `courses/views_transfer.py`
- Test: `tests/test_link_transfer.py` (extend)

**Interfaces:**
- Consumes: `document["link_nodes"]` (Task 3), `rewrite_instance` (Task 1).
- Produces: two new **keyword-only** arguments on each entry point; the existing positional signatures are untouched.
  - `import_course(zf, manifest, document, media_entries, user, *, on_missing="unwrap", report=None)`
  - `import_subtree(zf, manifest, document, media_entries, target_course, insertion_node, user, *, on_missing="unwrap", report=None)`
  - `materialize_duplicate(document, media_map, target_course, insertion_node, *, on_missing="keep", report=None)`

  When `report` is a dict it receives `{"flattened_links": int}`. **Return types are unchanged** — that is the whole point of the out-param.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_link_transfer.py`:

```python
def _round_trip(course, user, report, *, document_hook=None):
    """Export  to a buffer and import it back as a new course.

    import_course takes (zf, manifest, document, media_entries, user) -- it is NOT a
    file-taking helper. This mirrors tests/test_transfer_import.py::_import_zip.
    """
    import io

    from courses.transfer.export import build_export, write_archive_from
    from courses.transfer.importer import (
        import_course,
        open_archive,
        validate_archive_document,
    )

    manifest, document, assets, _problems = build_export(course)
    if document_hook:
        document_hook(document)
    buf = io.BytesIO()
    write_archive_from(manifest, document, assets, buf)
    buf.seek(0)
    with open_archive(buf, expected_kind="course") as (zf, mani, doc, media):
        validate_archive_document(zf, mani, doc, media, kind="course")
        return import_course(zf, mani, doc, media, user, report=report)


def test_round_trip_rewrites_to_the_new_pk():
    course, chapter, _unit = _course_with_link()
    report = {}
    new_course = _round_trip(course, course.owner, report)

    from courses.models import ContentNode, TextElement

    new_chapter = ContentNode.objects.get(course=new_course, title="Ch")
    body = TextElement.objects.filter(
        elements__unit__course=new_course
    ).first().body
    assert f"/courses/n/{new_chapter.pk}/" in body
    assert f"/courses/n/{chapter.pk}/" not in body   # NOT the original
    assert report["flattened_links"] == 0


def test_unmapped_link_is_flattened_and_counted():
    course, _chapter, _unit = _course_with_link()
    report = {}
    # Simulate a target outside the exported set (what a subtree export produces).
    new_course = _round_trip(
        course, course.owner, report,
        document_hook=lambda doc: doc.__setitem__("link_nodes", {}),
    )

    from courses.models import TextElement

    body = TextElement.objects.filter(elements__unit__course=new_course).first().body
    assert "<a" not in body
    assert "ch" in body
    assert report["flattened_links"] == 1


def test_duplicate_unit_keeps_an_out_of_scope_link():
    # The case the naive rule gets wrong: those pks still resolve in this install, so
    # flattening a working link would be a regression.
    from courses import builder as builder_svc

    course, chapter, unit = _course_with_link()
    copy_pk = builder_svc.duplicate_unit(
        course, unit.pk, token=unit.updated.isoformat()
    )
    from courses.models import Element, TextElement

    copied = TextElement.objects.filter(elements__unit_id=copy_pk).first()
    assert f"/courses/n/{chapter.pk}/" in copied.body   # unchanged


def test_duplicate_unit_rewrites_a_self_link():
    # The only in-scope rewrite this path can exercise: duplicate_unit raises for
    # anything that is not a unit, so the exported document always holds one node.
    from courses import builder as builder_svc
    from courses.models import TextElement

    course = CourseFactory()
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    el = _text(f'<a href="/courses/n/{unit.pk}/">self</a>')
    add_element(unit, el)
    copy_pk = builder_svc.duplicate_unit(
        course, unit.pk, token=unit.updated.isoformat()
    )
    copied = TextElement.objects.filter(elements__unit_id=copy_pk).first()
    assert f"/courses/n/{copy_pk}/" in copied.body
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_link_transfer.py -q`
Expected: FAIL — the imported body still holds the original pk.

- [ ] **Step 3: Have `_create_elements` return what it created**

In `courses/transfer/importer.py`, `_create_elements` currently keeps its created join rows in a local and returns `None`. Return them:

```python
def _create_elements(document, node_map, assets):
    ...
    created = []
    ...
        join = Element.objects.create(
            unit=node_map[el["unit"]], title=el["title"], content_object=concrete
        )
        created.append(join)
    ...
    return created
```

Update the three internal call sites to capture the return.

- [ ] **Step 4: Add the rewrite post-pass**

Add near the top of `importer.py`:

```python
from courses.richtext import rewrite_instance
```

And a helper:

```python
def _rewrite_links(document, node_map, created_joins, *, on_missing, report):
    """Remap internal links onto the newly created nodes.

    Runs over the created INSTANCES rather than the payload dicts: payload keys are a
    second vocabulary that would have to be kept in step with the model fields, and the
    registry already describes the models.

    link_nodes maps old pk -> export id, so the inversion looks up each VALUE ("n7") in
    node_map -- never the key, which is a source pk that node_map has never seen.
    """
    mapping = {}
    for old_pk, export_id in (document.get("link_nodes") or {}).items():
        node = node_map.get(export_id)
        if node is None:
            continue                     # unresolvable, same as absent -- never a 500
        try:
            mapping[int(old_pk)] = node.pk
        except (TypeError, ValueError):
            continue
    flattened = 0
    for join in created_joins:
        obj = join.content_object
        if obj is None:
            continue
        changed, flat = rewrite_instance(obj, mapping, on_missing=on_missing)
        flattened += flat
        if changed:
            obj.save(update_fields=changed)
    if report is not None:
        report["flattened_links"] = report.get("flattened_links", 0) + flattened
```

- [ ] **Step 5: Thread the policy through the three entry points**

Give each entry point two **keyword** arguments with the policy as a *default* — the policy is a property of the entry point, not of the call site, and a required argument would put the decision where it can drift. `report` is an out-param specifically so the **return types do not change**: nine test modules consume those returns directly (eight under `tests/`, plus `courses/tests/test_spoiler_transfer.py`), several through shared helpers whose own contracts would change in turn.

```python
def import_course(zf, manifest, document, media_entries, user, *, on_missing="unwrap", report=None):
    ...
        node_map = _create_nodes(document, course)
        created = _create_elements(document, node_map, assets)
        _rewrite_links(document, node_map, created, on_missing=on_missing, report=report)
```

```python
def import_subtree(
    zf, manifest, document, media_entries, target_course, insertion_node, user,
    *, on_missing="unwrap", report=None,
):
    ...
        node_map = _create_nodes(document, target_course, root_parent=insertion_node)
        created = _create_elements(document, node_map, assets)
        _rewrite_links(document, node_map, created, on_missing=on_missing, report=report)
        return node_map[document["nodes"][0]["id"]]
```

```python
def materialize_duplicate(
    document, media_map, target_course, insertion_node,
    *, on_missing="keep", report=None,
):
    ...
        node_map = _create_nodes(document, target_course, root_parent=insertion_node)
        created = _create_elements(document, node_map, media_map)
        _rewrite_links(document, node_map, created, on_missing=on_missing, report=report)
        return node_map[document["nodes"][0]["id"]]
```

`courses/builder.py` needs **no change** — `duplicate_unit` calls `materialize_duplicate`, which now defaults to `keep`.

- [ ] **Step 6: Report the count in the UI**

In `courses/views_transfer.py`, add the import and pass a `report` dict on **both** import paths, then emit a **second, separate** message after the existing success. A separate message rather than a folded-in clause is deliberate: folding would *change* the two existing msgids, so `makemessages --no-obsolete` would drop the old entries and demand fresh Polish translations for strings that did not really change.

```python
from django.utils.translation import ngettext
```

```python
                report = {}
                new_course = import_course(zf, mani, doc, media, request.user, report=report)
                messages.success(
                    request,
                    _("Course “%(title)s” imported.") % {"title": new_course.title},
                )
                _warn_flattened(request, report)
```

and a module-level helper:

```python
def _warn_flattened(request, report):
    """Second message, so the two existing success msgids are untouched.

    ngettext, not {% blocktrans count %}: this is Python, not a template. Precedent:
    courses/views_review.py:208.
    """
    n = report.get("flattened_links", 0)
    if not n:
        return
    messages.warning(
        request,
        ngettext(
            "%(n)s internal link had no target in this archive and was turned into "
            "plain text.",
            "%(n)s internal links had no target in this archive and were turned into "
            "plain text.",
            n,
        )
        % {"n": n},
    )
```

Apply the same three lines on the `import_subtree` path around `_("Content imported.")`.

- [ ] **Step 7: Run**

Run: `uv run pytest tests/test_link_transfer.py -q`
Expected: PASS.

- [ ] **Step 8: Run the whole transfer suite**

Run: `uv run pytest tests/ courses/tests/ -k transfer -q`
Expected: PASS — no call site broke, which is the point of the out-param.

- [ ] **Step 9: Falsify the keep/unwrap split**

Change `materialize_duplicate`'s default to `"unwrap"`. Run
`uv run pytest tests/test_link_transfer.py -q`. Expected:
`test_duplicate_unit_keeps_an_out_of_scope_link` FAILS. Restore.

- [ ] **Step 10: Commit**

```bash
git add courses/transfer/importer.py courses/views_transfer.py tests/test_link_transfer.py
git commit -m "feat(links): rewrite internal links on import; warn on flattened ones"
```

---

### Task 5: Delete-time inbound-link warning

**Files:**
- Modify: `courses/views_manage.py` (`node_delete`'s GET branch)
- Modify: `templates/courses/manage/node_confirm_delete.html`
- Test: `tests/test_inbound_link_warning.py` (create)

**Interfaces:**
- Consumes: `count_inbound_links` (Task 1).
- Produces: `counts["inbound_links"]` in the confirm-page context.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_inbound_link_warning.py`:

```python
import pytest
from django.urls import reverse

from courses.richtext import count_inbound_links
from courses.models import TextElement
from tests.factories import (
    ContentNodeFactory,
    CourseFactory,
    add_element,
    make_login,
)


def _text(body):
    """A saved TextElement -- there is no TextElementFactory in this repo."""
    obj = TextElement(body=body)
    obj.save()
    return obj

pytestmark = pytest.mark.django_db


def _scene(client=None):
    owner = make_login(client, "owner") if client else None
    course = CourseFactory(owner=owner) if owner else CourseFactory()
    chapter = ContentNodeFactory(course=course, kind="chapter", parent=None, title="Ch")
    inner = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=chapter, title="Inner"
    )
    outside = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="Outside"
    )
    return course, chapter, inner, outside


def test_zero_with_no_links():
    _course, chapter, _inner, _outside = _scene()
    assert count_inbound_links(chapter.course, chapter) == 0


def test_counts_a_link_from_outside_the_subtree():
    course, chapter, _inner, outside = _scene()
    add_element(outside, _text(f'<a href="/courses/n/{chapter.pk}/">c</a>'))
    assert count_inbound_links(course, chapter) == 1


def test_counts_links_to_a_descendant_not_just_the_node():
    course, chapter, inner, outside = _scene()
    add_element(outside, _text(f'<a href="/courses/n/{inner.pk}/">i</a>'))
    assert count_inbound_links(course, chapter) == 1


def test_counts_elements_not_anchors():
    # Two anchors in ONE body pointing at two doomed nodes count once: the author's
    # unit of repair is "this element needs editing".
    course, chapter, inner, outside = _scene()
    body = (
        f'<a href="/courses/n/{chapter.pk}/">c</a> '
        f'<a href="/courses/n/{inner.pk}/">i</a>'
    )
    add_element(outside, _text(body=body))
    assert count_inbound_links(course, chapter) == 1


def test_ignores_links_originating_inside_the_doomed_subtree():
    # A link inside the subtree dies with its target. Counting those would report a
    # large number for a self-contained part whose lessons cross-link each other --
    # the opposite of the warning's purpose.
    course, chapter, inner, _outside = _scene()
    add_element(inner, _text(f'<a href="/courses/n/{chapter.pk}/">c</a>'))
    assert count_inbound_links(course, chapter) == 0


def test_ignores_links_from_another_course():
    course, chapter, _inner, _outside = _scene()
    other = CourseFactory()
    other_unit = ContentNodeFactory(
        course=other, kind="unit", unit_type="lesson", parent=None, title="X"
    )
    add_element(other_unit, _text(f'<a href="/courses/n/{chapter.pk}/">c</a>'))
    assert count_inbound_links(course, chapter) == 0


def test_confirm_page_shows_the_sentence_only_when_non_zero(client):
    course, chapter, _inner, outside = _scene(client)
    url = reverse("courses:manage_node_delete", kwargs={"slug": course.slug})
    html = client.get(url, {"node": chapter.pk}).content.decode()
    assert "link" not in html.lower() or "links here" not in html.lower()

    add_element(outside, _text(f'<a href="/courses/n/{chapter.pk}/">c</a>'))
    html = client.get(url, {"node": chapter.pk}).content.decode()
    assert "links here" in html.lower() or "link here" in html.lower()


def test_scan_is_one_query_per_model_not_per_element(
    client, django_assert_num_queries
):
    # The fixture must hold at least TWO link-bearing elements of the SAME model
    # OUTSIDE the doomed subtree -- among the rows the scan actually reads. Putting
    # them inside would make this vacuous: the scan excludes the subtree, so those rows
    # are never queried per-model and could not distinguish per-model from per-element.
    course, chapter, _inner, outside = _scene(client)
    for _ in range(2):
        add_element(
            outside, _text(f'<a href="/courses/n/{chapter.pk}/">c</a>')
        )
    url = reverse("courses:manage_node_delete", kwargs={"slug": course.slug})
    client.get(url, {"node": chapter.pk})           # warm caches
    # Shape: 16 registry-model queries + _subtree_node_ids' per-depth queries PLUS one
    # for the terminating empty frontier + the pre-existing per-node _descendant_count
    # and _element_count walks + the view's fixed queries (session, user, course+perm,
    # get_node_or_404). Derive the number from that shape; if the run disagrees, read
    # the query log and find out which group changed before touching the number.
    with django_assert_num_queries(27):
        client.get(url, {"node": chapter.pk})
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_inbound_link_warning.py -q`
Expected: FAIL — `count_inbound_links` returns 0 for the counted cases (or the template lacks the sentence).

- [ ] **Step 3: Wire the count into the view**

In `courses/views_manage.py`, add the import and extend the existing `counts` dict in `node_delete`'s GET branch:

```python
from courses.richtext import count_inbound_links
```

```python
        counts = {
            "descendants": _descendant_count(node),
            "elements": _element_count(node),
            "inbound_links": count_inbound_links(course, node),
        }
```

- [ ] **Step 4: Add the sentence**

In `templates/courses/manage/node_confirm_delete.html`, after the existing `<p>`:

```html
  {% if counts.inbound_links %}
    <p class="op-warning">
      {% blocktrans count n=counts.inbound_links %}{{ n }} other element in this course links here.{% plural %}{{ n }} other elements in this course link here.{% endblocktrans %}
    </p>
  {% endif %}
```

Leave the existing `This removes {{ d }} descendant node(s) and {{ e }} element(s).` line **exactly as it is** — correcting its `(s)` suffixes is an unrelated i18n fix and would put an unrelated msgid change in this diff.

- [ ] **Step 5: Run**

Run: `uv run pytest tests/test_inbound_link_warning.py -q`
Expected: PASS. If the query count differs, read the reported number against the shape in the comment before changing it.

- [ ] **Step 6: Falsify the subtree exclusion**

Remove the `.exclude(elements__unit_id__in=subtree)` clause from `count_inbound_links`. Run the tests. Expected: `test_ignores_links_originating_inside_the_doomed_subtree` FAILS. Restore.

- [ ] **Step 7: Commit**

```bash
git add courses/views_manage.py courses/richtext.py templates/courses/manage/node_confirm_delete.html tests/test_inbound_link_warning.py
git commit -m "feat(links): warn before deleting a node other content links to"
```

---

### Task 6: Translations and the full suite

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po`, `locale/en/LC_MESSAGES/django.po` (+ `.mo`)

- [ ] **Step 1: Extract**

Run: `uv run python manage.py makemessages -l pl -l en --no-obsolete`

Expect **two** new msgids (each with plural forms): the delete-confirm sentence and the flattened-links warning. The two existing import success strings must be **unchanged** — if `makemessages` shows them as removed/added, the warning was folded in rather than added separately; go back and fix that.

- [ ] **Step 2: Translate**

Fill the Polish forms. Polish has **three** plural forms — every one must be non-empty. Clear any fuzzy entry properly: both the `#, fuzzy` line *and* the `#| msgid` comment.

- [ ] **Step 3: Verify and compile**

Run: `uv run pytest tests/test_i18n_po_health.py -q`
Run: `uv run python manage.py compilemessages`

- [ ] **Step 4: Full suite + lint**

Run: `uv run pytest -q`
Run: `uv run ruff check . && uv run ruff format --check .`

Both green. If a pre-existing failure appears that your diff cannot explain, do not fold a fix into this branch — a flaky or unrelated failure belongs in its own PR.

- [ ] **Step 5: Commit**

```bash
git add locale/
git commit -m "i18n(links): pl/en strings for the durability warnings"
```

---

## Self-Review

**Spec coverage.** §1 registry, accessor protocol, href predicate, scanner, drift guard → Tasks 1, 2. §2 export + schema + version bump → Task 3. §3 import post-pass, `on_missing` table, `report` out-param, the separate warning → Task 4. §4 delete warning, count definition, query shape → Task 5. §i18n → Task 6. §Error handling is covered by the malformed-`link_nodes` parametrisation (Task 3), the unresolvable-value skip (Task 4), and the fail-closed cases (Task 1).

**Deliberately not here:** the `migrate_course_content` cutover. It is part 3, has its own spec, and has not yet been through review. Task 4's `on_missing` gains its third value (`defer`) there, not here.

**Placeholder scan.** No TBDs. Every step carries the actual code. The one number an implementer must verify rather than copy is the query count in Task 5 Step 1 — its derivation is spelled out in the comment, and the step says to read the query log rather than record the first run.

**Type consistency.** `rewrite_links` returns `(html, int)` in Task 1 and is unpacked as such in `rewrite_instance` (same task) and nowhere else. `rewrite_instance` returns `(changed, flattened)` and is unpacked that way in Task 4's `_rewrite_links`. `report["flattened_links"]` is written in Task 4 and read in Task 4's `_warn_flattened` and Task 4's tests. `count_inbound_links(course, node) -> int` is defined in Task 1 and called with exactly that signature in Task 5.
