# Fill-in table inline `{{answer}}` gaps — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a course author type `{{answer}}` into a normal Fill-in table cell so the box renders inline in that cell's text (with maths either side), checked per box — the author-side repair for LAL-imported tables that lost the text beside their input.

**Architecture:** A static cell gains an optional `gaps` list (one list of accepted alternatives per box). The form parses the author's `{{…}}` markers at save into opaque U+FFFF tokens in `html` plus `gaps` (the Fill-in-the-blank pattern, reusing `courses/fillblank.py`); the editor gets `{{…}}` back via the reverse conversion; the student render replaces tokens with server-built inputs keyed `r/c/g`; the check view marks each box. All parse/reverse/repair logic lives in `courses/filltable.py`.

**Tech Stack:** Django 5 templates + JSONField, vanilla JS, `nh3`, pytest + Playwright (e2e).

**Spec:** `docs/superpowers/specs/2026-09-24-filltable-inline-gaps-design.md` — read it alongside this plan; section numbers (§N) below refer to it. Its "Owner decisions" table (D1–D6) is owner intent: do not reverse any of it.

## Global Constraints

- Branch `feat/filltable-inline-gaps`. Work in that checkout only; one agent per worktree.
- **Start the test DB container before ANY pytest run:** `docker compose -p libli-test -f docker-compose.test.yml up -d --wait` (otherwise pytest looks hung for minutes).
- Run tools through uv: `uv run pytest …`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run python manage.py …`. Bare `pytest`/`ruff`/`python` are not on PATH.
- **Never pass `-q` to pytest** (addopts already has it; doubling hides the summary). Use `-v` or nothing. Always read the summary line — the exit code can lie.
- e2e tests are excluded by default: run them with `-m e2e`, focused by file, in the foreground. Never run two pytest processes at once.
- Scope test runs narrowly to the files a task touches. The whole-suite run is a branch gate (Task 11), never a task step.
- Sentinel: `SENTINEL = "\uffff"`, token `\uffff{n}\uffff`, reused from `courses/fillblank.py` (`SENTINEL`, `_TOKEN_RE`, `_MARKER_RE`, `mask_math`, `restore_math`, `strip_sentinel`, `FillBlankError`). In Python source write it as the escape `"\uffff"`, never the raw character.
- `MAX_GAPS_PER_CELL = 10`.
- Static cell = any cell whose `kind` is neither `"answer"` nor `"image"`.
- `r`/`c` everywhere are RAW 0-based list indices (same as `answer_cells` and today's `data-r`/`data-c`); user-facing row/column numbers are those + 1.
- New/changed user-facing strings (exact msgids):
  - `Add at least one answer — mark an answer cell, or type {{answer}} in a cell.` (replaces `Mark at least one answer cell (use the “Answer cell” button).` everywhere)
  - `Row %(r)d, column %(c)d: an answer box {{…}} is empty or not closed.`
  - `Row %(r)d, column %(c)d: an answer box cannot contain maths — put the maths outside the braces, e.g. {{9}} \(\pi\).`
  - `Row %(r)d, column %(c)d: at most %(n)d answer boxes per cell.`
  - `Answer, row %(r)s, column %(c)s, box %(g)s` (multi-box aria-label; the single-box label REUSES the existing msgid `Answer, row %(r)s, column %(c)s`)
  - `Type {{answer}} in a cell to put an answer box inside its text; separate accepted alternatives with |.`
  - `Element '%(el)s': fill-in table gaps must be a list.`
- Any template string containing `{{answer}}` MUST be emitted with `{% trans '…' %}` — never `{% blocktranslate %}` or plain template text (there `{{answer}}` is parsed as a variable and renders empty).
- Django `{# #}` comments are single-line only; use `{% comment %}` for multi-line.
- `ruff check` AND `ruff format --check` both gate CI.
- Commits end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Reverting a mutant: edit it back BY HAND and read `git diff`. Never `git checkout -- <file>` (it destroys uncommitted work).

## Review Focus

1. **A table saved before this feature** — READ unchanged (pinned by Task 2's "no gaps = unchanged" test); RE-SAVED unchanged when it has no markers (pinned by Task 3's `test_resave_marker_free_table_is_identical`). The one save-side change — `strip_sentinel` removing a pre-existing U+FFFF — is guarded only by Task 11's prod audit.
2. **Author re-opens a table with boxes and saves without touching it** — the boxes survive. Pinned by Task 6's editor round-trip test (and its mutant).
3. **Student answers only some boxes of a multi-box cell** — each box painted independently, box 0 included. Pinned by Task 10's e2e (box 0 answered wrong) and its two paint-selector mutants.
4. **Author pastes formatted text into a marker** (`{{<b>9</b>}}`, a coloured span) — the answer is still `9`. Pinned by Task 1.
5. **Gated table whose only answers are boxes** — gate stays on through the real form. Pinned by Task 3's form gate test (and its mutant).

---

### Task 1: Gap helpers in `courses/filltable.py`

**Files:**
- Modify: `courses/filltable.py`
- Test: `tests/test_filltable_gaps.py` (create)

**Interfaces:**
- Consumes: `courses.fillblank`: `SENTINEL`, `_TOKEN_RE`, `_MARKER_RE`, `mask_math(s) -> (masked, spans)`, `restore_math(s, spans)`, `strip_sentinel(s)`, `FillBlankError`.
- Produces (all in `courses/filltable.py`):
  - `MAX_GAPS_PER_CELL = 10`
  - `class GapMathError(FillBlankError)`
  - `parse_cell_gaps(cell_html: str) -> tuple[str, list[list[str]]]` — raises `GapMathError` / `FillBlankError`
  - `author_cell_html(cell: dict) -> str`
  - `reconcile_gaps(cell_html, gaps) -> tuple[str, list[list[str]]]` — never raises
  - `gap_cells(cells) -> Iterator[tuple[int, int, int, list[str]]]`
  - `is_static_cell(cell: dict) -> bool`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_filltable_gaps.py`:

```python
"""Pure helpers for Fill-in table inline gaps (spec §2, §4). No DB."""

import pytest

from courses.fillblank import FillBlankError
from courses.filltable import MAX_GAPS_PER_CELL
from courses.filltable import GapMathError
from courses.filltable import author_cell_html
from courses.filltable import gap_cells
from courses.filltable import parse_cell_gaps
from courses.filltable import reconcile_gaps

S = "\uffff"


def tok(n):
    return f"{S}{n}{S}"


# --- parse_cell_gaps ---------------------------------------------------------


def test_one_gap_before_maths():
    assert parse_cell_gaps(r"{{9}} \(\pi\)") == (tok(0) + r" \(\pi\)", [["9"]])


def test_two_gaps_between_maths():
    h, gaps = parse_cell_gaps(r"\((x+2)^2+(y\) {{-1}} \()^2=\) {{16}}")
    assert h == r"\((x+2)^2+(y\) " + tok(0) + r" \()^2=\) " + tok(1)
    assert gaps == [["-1"], ["16"]]


def test_braces_inside_maths_stay_literal():
    src = r"\(\frac{{a}}{b}\) and {{2}}"
    h, gaps = parse_cell_gaps(src)
    assert h == r"\(\frac{{a}}{b}\) and " + tok(0)
    assert gaps == [["2"]]


def test_alternatives_trimmed():
    assert parse_cell_gaps("{{ 9 | 9,0 }}") == (tok(0), [["9", "9,0"]])


def test_no_markers_is_not_an_error():
    assert parse_cell_gaps("plain <b>text</b>") == ("plain <b>text</b>", [])


def test_lt_in_answer_is_decoded():
    # sanitised html arrives with `<` escaped
    assert parse_cell_gaps("{{a&lt;b}}") == (tok(0), [["a<b"]])


@pytest.mark.parametrize(
    "src",
    [
        "{{<b>9</b>}}",
        '{{<span class="tc-red">9</span>}}',
        '{{<span title="a>b">9</span>}}',
    ],
)
def test_markup_inside_marker_is_stripped(src):
    assert parse_cell_gaps(src)[1] == [["9"]]


def test_straddling_tag_keeps_answer():
    h, gaps = parse_cell_gaps("<b>{{9</b>}}")
    assert gaps == [["9"]]
    assert h == "<b>" + tok(0)  # unbalanced; save() re-sanitises (Task 2)


def test_split_brace_pair_is_literal():
    assert parse_cell_gaps("{<b>{</b>9}}") == ("{<b>{</b>9}}", [])


@pytest.mark.parametrize("src", ["{{}}", "{{ | }}", "{{9", "a {{9 b"])
def test_empty_or_unclosed_raises_plain_error(src):
    with pytest.raises(FillBlankError) as exc:
        parse_cell_gaps(src)
    assert not isinstance(exc.value, GapMathError)


def test_maths_inside_marker_raises_gap_math_error():
    with pytest.raises(GapMathError):
        parse_cell_gaps(r"{{9\(\pi\)}}")


def test_maths_overlapping_marker_end_reports_unclosed():
    with pytest.raises(FillBlankError) as exc:
        parse_cell_gaps(r"{{9\(x}}\)")
    assert not isinstance(exc.value, GapMathError)


def test_existing_sentinel_is_stripped_before_parse():
    assert parse_cell_gaps("a" + tok(0) + "{{1}}") == ("a0" + tok(0), [["1"]])


# --- author_cell_html + idempotence -----------------------------------------


def test_author_html_restores_markers_and_escapes():
    cell = {"html": tok(0) + r" \(\pi\)", "gaps": [["9", "9,0"]]}
    assert author_cell_html(cell) == r"{{9|9,0}} \(\pi\)"
    assert author_cell_html({"html": tok(0), "gaps": [["a<b"]]}) == "{{a&lt;b}}"


def test_author_html_identity_without_gaps():
    assert author_cell_html({"html": "x" + tok(0)}) == "x" + tok(0)
    assert author_cell_html({"html": "x"}) == "x"


@pytest.mark.parametrize(
    "src",
    [
        "{{9}}",
        r"{{9}} \(\pi\)",
        r"\((x+2)^2+(y\) {{-1}} \()^2=\) {{16}}",
        r"\(\frac{{a}}{b}\) {{2}}",
        "{{ 9 | 9,0 }}",
        "{{a&lt;b}}",
        "no gaps",
    ],
)
def test_parse_author_parse_is_idempotent(src):
    h, gaps = parse_cell_gaps(src)
    again = parse_cell_gaps(author_cell_html({"html": h, "gaps": gaps}))
    assert again == (h, gaps)


# --- reconcile_gaps (§4) -----------------------------------------------------


def test_reconcile_clean_input_unchanged():
    assert reconcile_gaps(tok(0) + tok(1), [["a"], ["b"]]) == (
        tok(0) + tok(1),
        [["a"], ["b"]],
    )


def test_reconcile_entry_cleaning():
    h, g = reconcile_gaps(tok(0), [[" a ", "", 3, "b"]])
    assert (h, g) == (tok(0), [["a", "b"]])


def test_reconcile_non_list_entry_is_empty_and_token_removed():
    assert reconcile_gaps("x" + tok(0) + "y", ["nope"]) == ("xy", [])


def test_reconcile_duplicate_token_keeps_first():
    assert reconcile_gaps(tok(0) + "-" + tok(0), [["a"]]) == (tok(0) + "-", [["a"]])


def test_reconcile_orphan_token_removed():
    assert reconcile_gaps(tok(0) + tok(5), [["a"]]) == (tok(0), [["a"]])


def test_reconcile_orphan_entry_dropped():
    assert reconcile_gaps(tok(0), [["a"], ["b"]]) == (tok(0), [["a"]])


def test_reconcile_renumbers_in_document_order():
    assert reconcile_gaps(tok(1) + tok(0), [["a"], ["b"]]) == (
        tok(0) + tok(1),
        [["b"], ["a"]],
    )


def test_reconcile_truncates_to_cap():
    n = MAX_GAPS_PER_CELL + 2
    h, g = reconcile_gaps("".join(tok(i) for i in range(n)), [[str(i)] for i in range(n)])
    assert len(g) == MAX_GAPS_PER_CELL
    assert h == "".join(tok(i) for i in range(MAX_GAPS_PER_CELL))


def test_reconcile_all_removed_returns_empty_list():
    assert reconcile_gaps("x", [["a"]]) == ("x", [])


@pytest.mark.parametrize("bad", [None, "str", 5, {"a": 1}])
def test_reconcile_non_list_gaps(bad):
    assert reconcile_gaps("x" + tok(0), bad) == ("x", [])


def test_reconcile_non_string_html():
    assert reconcile_gaps(None, [["a"]]) == ("", [])


def test_reconcile_is_idempotent():
    once = reconcile_gaps(tok(2) + tok(0) + tok(0), [["a"], [" "], ["c"]])
    assert reconcile_gaps(*once) == once


# --- gap_cells ---------------------------------------------------------------


def test_gap_cells_yields_lists_for_static_cells_only():
    cells = [
        [{"kind": "static", "html": tok(0) + tok(1), "gaps": [["a"], ["b", "B"]]}],
        [{"kind": "answer", "answer": "x", "gaps": [["no"]]}, {"kind": "static"}],
    ]
    assert list(gap_cells(cells)) == [(0, 0, 0, ["a"]), (0, 0, 1, ["b", "B"])]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_filltable_gaps.py -v`
Expected: collection error — `ImportError: cannot import name 'MAX_GAPS_PER_CELL' from 'courses.filltable'`.

- [ ] **Step 3: Implement the helpers**

Append to `courses/filltable.py` (keep the existing three functions unchanged; add the imports at the top of the file):

```python
import html as _html
import re

import nh3

from courses.fillblank import _MARKER_RE
from courses.fillblank import _TOKEN_RE
from courses.fillblank import SENTINEL
from courses.fillblank import FillBlankError
from courses.fillblank import mask_math
from courses.fillblank import restore_math
from courses.fillblank import strip_sentinel

# Inline answer boxes typed as {{answer}} inside a static cell's text (spec
# 2026-09-24-filltable-inline-gaps §2/§4). The LAL corpus peaks at 2 per cell.
MAX_GAPS_PER_CELL = 10

_TOKEN = SENTINEL + "{}" + SENTINEL
# fillblank.mask_math's placeholder: SENTINEL + "M<n>" + SENTINEL.
_MATH_PLACEHOLDER_RE = re.compile(SENTINEL + r"M\d+" + SENTINEL)


class GapMathError(FillBlankError):
    """A {{…}} marker whose interior holds a maths span. Its own class so the form
    picks the maths message by type, never by the exception's text."""


def is_static_cell(cell):
    return isinstance(cell, dict) and cell.get("kind") not in ("answer", "image")


def _marker_text(interior):
    # A real parser, never a <[^>]*> regex: nh3 leaves `>` unescaped inside
    # attribute values, so a regex would leak `b">` out of <span title="a>b">.
    return _html.unescape(nh3.clean(interior, tags=set()))


def parse_cell_gaps(cell_html):
    """Sanitised static-cell html -> (token_html, gaps). Each {{a|b}} marker outside
    \\(…\\)/\\[…\\] becomes a U+FFFF token; its alternatives (tags stripped, entities
    decoded, trimmed, blanks dropped) go into `gaps`. Zero markers is fine.

    Raises GapMathError for maths inside a marker, FillBlankError for an empty or
    unterminated one."""
    s = strip_sentinel(cell_html if isinstance(cell_html, str) else "")
    masked, spans = mask_math(s)
    gaps = []

    def _swap(m):
        interior = m.group(1)
        if _MATH_PLACEHOLDER_RE.search(interior):
            raise GapMathError("math in marker")
        pieces = [p.strip() for p in _marker_text(interior).split("|")]
        pieces = [p for p in pieces if p]
        if not pieces:
            raise FillBlankError("empty marker")
        gaps.append(pieces)
        return _TOKEN.format(len(gaps) - 1)

    token_masked = _MARKER_RE.sub(_swap, masked)
    if "{{" in token_masked:
        raise FillBlankError("unterminated marker")
    return restore_math(token_masked, spans), gaps


def author_cell_html(cell):
    """The editor's view of a static cell: tokens back to {{alt|alt}}, alternatives
    html-escaped (mirrors fillblank.to_author_stem). Identity without `gaps`."""
    h = cell.get("html") or ""
    gaps = cell.get("gaps")
    if not gaps:
        return h

    def _swap(m):
        n = int(m.group(1))
        pieces = gaps[n] if 0 <= n < len(gaps) else []
        return "{{" + "|".join(_html.escape(p, quote=False) for p in pieces) + "}}"

    return _TOKEN_RE.sub(_swap, h)


def _clean_entry(entry):
    if not isinstance(entry, list):
        return []
    return [a.strip() for a in entry if isinstance(a, str) and a.strip()]


def reconcile_gaps(cell_html, gaps):
    """Read-side repair so tokens and `gaps` always agree (spec §4). Never raises;
    idempotent; returns [] for gaps when no box survives."""
    h = cell_html if isinstance(cell_html, str) else ""
    entries = [_clean_entry(e) for e in gaps] if isinstance(gaps, list) else []
    seen = set()
    kept = []

    def _swap(m):
        n = int(m.group(1))
        if (
            n in seen
            or n >= len(entries)
            or not entries[n]
            or len(kept) >= MAX_GAPS_PER_CELL
        ):
            return ""
        seen.add(n)
        kept.append(entries[n])
        return _TOKEN.format(len(kept) - 1)

    return _TOKEN_RE.sub(_swap, h), kept


def gap_cells(cells):
    """Yield (row, col, gap_index, alternatives) for every inline gap, 0-based."""
    for r, row in enumerate(cells or []):
        if not isinstance(row, list):
            continue
        for c, cell in enumerate(row):
            if not is_static_cell(cell):
                continue
            for g, alts in enumerate(cell.get("gaps") or []):
                yield r, c, g, alts
```

If `ruff` flags the private-name imports (`_MARKER_RE`, `_TOKEN_RE`), add `# noqa: PLC2701` only if that rule is enabled — check with `uv run ruff check courses/filltable.py`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_filltable_gaps.py tests/test_filltable_form.py -v`
Expected: all PASS (the existing form tests prove the three old helpers are untouched).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff format courses/filltable.py tests/test_filltable_gaps.py
uv run ruff check courses/filltable.py tests/test_filltable_gaps.py
git add courses/filltable.py tests/test_filltable_gaps.py
git commit -m "feat(filltable): parse, reverse and reconcile inline {{answer}} gaps

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Model keeps `gaps`, gate counts them, done-state display

**Files:**
- Modify: `courses/models.py` — `FillTableElement._cell` (static branch, ~line 1535), `normalize_data` gate block (~1596-1602), `canonical_cells` (~1616-1640)
- Test: `tests/test_filltable_gaps_model.py` (create)

**Interfaces:**
- Consumes: `reconcile_gaps`, `gap_cells`, `is_static_cell` (Task 1).
- Produces: normalized static cells carry `gaps: list[list[str]]` only when non-empty; `canonical_cells` static cells with gaps carry `gaps_display: list[str]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_filltable_gaps_model.py`:

```python
import pytest

from courses.models import FillTableElement

pytestmark = pytest.mark.django_db

S = "\uffff"


def tok(n):
    return f"{S}{n}{S}"


def _norm(cells, **kw):
    return FillTableElement.normalize_data({"cells": cells, **kw})


def test_static_cell_without_gaps_is_unchanged_even_with_literal_token():
    # §1: the live, hand-edited course must be byte-identical on read.
    raw = {"kind": "static", "html": "a" + tok(0) + "b"}
    assert _norm([[raw]])["cells"][0][0] == {
        "kind": "static",
        "html": "a" + tok(0) + "b",
        "halign": "left",
        "valign": "top",
    }


def test_gaps_carried_and_reconciled():
    raw = {"kind": "static", "html": tok(1) + tok(0), "gaps": [["a"], [" b "]]}
    cell = _norm([[raw]])["cells"][0][0]
    assert cell["html"] == tok(0) + tok(1)
    assert cell["gaps"] == [["b"], ["a"]]


def test_all_gaps_removed_omits_key():
    cell = _norm([[{"kind": "static", "html": "x", "gaps": [["a"]]}]])["cells"][0][0]
    assert "gaps" not in cell


def test_non_list_gaps_drops_key_and_tokens():
    cell = _norm([[{"kind": "static", "html": "x" + tok(0), "gaps": "bad"}]])
    assert cell["cells"][0][0] == {
        "kind": "static",
        "html": "x",
        "halign": "left",
        "valign": "top",
    }


def test_answer_and_image_cells_ignore_gaps():
    cell = _norm([[{"kind": "answer", "answer": "1", "gaps": [["x"]]}]])
    assert "gaps" not in cell["cells"][0][0]


def test_gate_kept_for_gaps_only_table():
    nd = _norm([[{"kind": "static", "html": tok(0), "gaps": [["9"]]}]], gate=True)
    assert nd["gate"] is True


def test_gate_still_off_with_no_answers_and_no_gaps():
    nd = _norm([[{"kind": "static", "html": "x"}]], gate=True)
    assert nd["gate"] is False


def test_save_rebalances_straddling_tag():
    el = FillTableElement(
        data={"cells": [[{"kind": "static", "html": "<b>" + tok(0), "gaps": [["9"]]}]]}
    )
    el.save()
    h = el.data["cells"][0][0]["html"]
    assert h.count("<b>") == h.count("</b>") == 1
    assert tok(0) in h


def test_canonical_cells_adds_gaps_display_without_mutating_data():
    el = FillTableElement(
        data={
            "cells": [
                [{"kind": "static", "html": tok(0) + tok(1), "gaps": [["9", "9,0"], ["x"]]}]
            ]
        }
    )
    before = repr(el.data)
    cell = el.canonical_cells[0][0]
    assert cell["gaps_display"] == ["9", "x"]
    assert cell["gaps"] == [["9", "9,0"], ["x"]]
    assert repr(el.data) == before
```

- [ ] **Step 2: Run to verify failures**

Run: `uv run pytest tests/test_filltable_gaps_model.py -v`
Expected: exactly four FAIL — `test_gaps_carried_and_reconciled` (KeyError `gaps`), `test_non_list_gaps_drops_key_and_tokens` (token still in html), `test_gate_kept_for_gaps_only_table` (False), `test_canonical_cells_adds_gaps_display_without_mutating_data` (KeyError). These PASS already and pin behaviour: `test_static_cell_without_gaps_is_unchanged_even_with_literal_token`, `test_all_gaps_removed_omits_key`, `test_answer_and_image_cells_ignore_gaps`, `test_gate_still_off_with_no_answers_and_no_gaps`, `test_save_rebalances_straddling_tag`.

- [ ] **Step 3: Implement**

In `FillTableElement._cell`, replace the final `else:` static branch:

```python
        else:
            cell = {
                "kind": FillTableElement.STATIC,
                "html": raw.get("html") or "",
                "halign": halign,
                "valign": valign,
            }
            # Inline {{answer}} gaps (spec 2026-09-24 §3/§4). ONLY when the raw
            # cell has the key: a cell without one passes through untouched even
            # if its html holds a literal U+FFFF token -- §1's byte-identical
            # promise for every table saved before this feature.
            if "gaps" in raw:
                from courses.filltable import reconcile_gaps

                html, gaps = reconcile_gaps(cell["html"], raw.get("gaps"))
                cell["html"] = html
                if gaps:
                    cell["gaps"] = gaps
```

In `normalize_data`, replace the gate block body:

```python
        gate = bool(data.get("gate"))
        if gate:
            from courses.filltable import answer_cells
            from courses.filltable import gap_cells
            from courses.filltable import is_blank_answer

            answers = [ans for _r, _c, ans in answer_cells(cells)]
            has_gap = next(gap_cells(cells), None) is not None
            gate = (bool(answers) or has_gap) and not any(
                is_blank_answer(a) for a in answers
            )
```

Extend the comment above it (the "(a) no answer cell at all" line) to read "(a) no answer cell and no inline gap at all".

In `canonical_cells`, update the docstring's "static cells pass through unchanged" to "static cells pass through unchanged, except that a cell with inline `gaps` gains `gaps_display` (the first alternative of each box)", and add a branch inside the inner loop:

```python
                if cell.get("kind") == self.ANSWER:
                    alts = split_alternatives(cell.get("answer", ""))
                    out_row.append({**cell, "answer": alts[0] if alts else ""})
                elif cell.get("gaps"):
                    # The SINGLE source of each inline box's done-state value.
                    out_row.append(
                        {**cell, "gaps_display": [g[0] for g in cell["gaps"]]}
                    )
                else:
                    out_row.append(cell)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_filltable_gaps_model.py tests/test_filltable_model.py tests/test_filltable_restore.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff format courses/models.py tests/test_filltable_gaps_model.py
uv run ruff check courses/models.py tests/test_filltable_gaps_model.py
git add courses/models.py tests/test_filltable_gaps_model.py
git commit -m "feat(filltable): cells keep reconciled gaps; gate counts them

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Form parses `{{…}}` at save

**Files:**
- Modify: `courses/element_forms.py` — `FillTableElementForm.clean_data` (~line 1638) and `resolved_grid_cells` (~1694)
- Modify: `tests/test_filltable_form.py:51` (old message assertion)
- Test: `tests/test_filltable_gaps_form.py` (create)

**Interfaces:**
- Consumes: `parse_cell_gaps`, `GapMathError`, `MAX_GAPS_PER_CELL`, `gap_cells`, `author_cell_html`, `is_static_cell` (Task 1); `courses.sanitize.sanitize_cell`; `courses.fillblank.FillBlankError`.
- Produces: `cleaned_data["data"]` static cells hold token html + `gaps`; `form.resolved_grid_cells` static cells carry `author_html: str` (consumed by Task 6's template).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_filltable_gaps_form.py`:

```python
import json

import pytest

from courses.element_forms import FillTableElementForm
from courses.models import FillTableElement

pytestmark = pytest.mark.django_db

S = "\uffff"


def _bind(cells, **kw):
    return FillTableElementForm(data={"data": json.dumps({"cells": cells, **kw})})


def _errors(f):
    assert not f.is_valid()
    return " ".join(str(e) for e in f.errors["data"])


def test_gaps_only_table_saves_with_tokens():
    f = _bind([[{"kind": "static", "html": r"{{9}} \(\pi\)"}]])
    assert f.is_valid(), f.errors
    cell = f.cleaned_data["data"]["cells"][0][0]
    assert cell["html"] == f"{S}0{S}" + r" \(\pi\)"
    assert cell["gaps"] == [["9"]]


def test_gate_survives_for_gaps_only_table_through_the_form():
    # §3: parse must run BEFORE normalize_data or the gate is silently dropped.
    f = _bind([[{"kind": "static", "html": "{{9}}"}]], gate=True)
    assert f.is_valid(), f.errors
    assert f.cleaned_data["data"]["gate"] is True


def test_posted_gaps_key_is_ignored():
    """The guarantee comes from strip_sentinel (posted html cannot carry a real
    token) + reconcile_gaps (gaps without tokens are dropped). The form's
    cell.pop("gaps") is defence in depth and is NOT separately falsifiable --
    this test pins the end result, not the pop."""
    f = _bind(
        [
            [
                {"kind": "static", "html": "plain", "gaps": [["evil"]]},
                {"kind": "answer", "answer": "1"},
            ]
        ]
    )
    assert f.is_valid(), f.errors
    assert "gaps" not in f.cleaned_data["data"]["cells"][0][0]


def test_markup_in_marker_is_stripped():
    f = _bind([[{"kind": "static", "html": "{{<b>9</b>}}"}]])
    assert f.is_valid(), f.errors
    assert f.cleaned_data["data"]["cells"][0][0]["gaps"] == [["9"]]


@pytest.mark.parametrize("html", ["{{}}", "x {{9"])
def test_empty_or_unclosed_marker_names_the_cell(html):
    f = _bind(
        [
            [{"kind": "answer", "answer": "1"}, {"kind": "static", "html": "ok"}],
            [{"kind": "static", "html": "ok"}, {"kind": "static", "html": html}],
        ]
    )
    msg = _errors(f)
    assert "Row 2, column 2" in msg
    assert "empty or not closed" in msg


def test_maths_in_marker_gets_maths_message():
    msg = _errors(_bind([[{"kind": "static", "html": r"{{9\(\pi\)}}"}]]))
    assert "Row 1, column 1" in msg
    assert "cannot contain maths" in msg


def test_cap_ten_saves_eleven_rejected():
    ok = _bind([[{"kind": "static", "html": "{{1}}" * 10}]])
    assert ok.is_valid(), ok.errors
    msg = _errors(_bind([[{"kind": "static", "html": "{{1}}" * 11}]]))
    assert "at most 10 answer boxes" in msg


def test_parse_error_wins_over_cap():
    msg = _errors(_bind([[{"kind": "static", "html": "{{1}}" * 11 + "{{}}"}]]))
    assert "empty or not closed" in msg


def test_no_answers_and_no_gaps_new_message():
    msg = _errors(_bind([[{"kind": "static", "html": "a"}]]))
    assert "Add at least one answer" in msg
    assert "{{answer}}" in msg


def test_resaving_stored_cells_keeps_gaps():
    # What the editor posts back after Task 6: author_html of the stored cells.
    first = _bind([[{"kind": "static", "html": "{{9|9,0}} x"}]], gate=True)
    assert first.is_valid(), first.errors
    el = FillTableElement(data=first.cleaned_data["data"])
    el.save()
    form = FillTableElementForm(instance=el)
    posted = [
        [{"kind": "static", "html": c["author_html"]} for c in row]
        for row in form.resolved_grid_cells
    ]
    again = _bind(posted, gate=True)
    assert again.is_valid(), again.errors
    assert again.cleaned_data["data"]["cells"] == el.normalize_data(el.data)["cells"]


def test_resave_marker_free_table_is_identical():
    cells = [
        [
            {"kind": "static", "html": "<b>czas</b> \\(x^2\\)"},
            {"kind": "answer", "answer": "4 | four"},
        ]
    ]
    el = FillTableElement(data={"cells": cells})
    el.save()
    before = el.normalize_data(el.data)["cells"]
    f = _bind(el.data["cells"])
    assert f.is_valid(), f.errors
    assert f.cleaned_data["data"]["cells"] == before


def test_resolved_grid_cells_author_html():
    el = FillTableElement(
        data={"cells": [[{"kind": "static", "html": f"{S}0{S}", "gaps": [["a<b"]]}]]}
    )
    cell = FillTableElementForm(instance=el).resolved_grid_cells[0][0]
    assert cell["author_html"] == "{{a&lt;b}}"
```

In `tests/test_filltable_form.py`, change line 51 to:

```python
    assert any("add at least one answer" in str(e).lower() for e in f.errors["data"])
```

- [ ] **Step 2: Run to verify failures**

Run: `uv run pytest tests/test_filltable_gaps_form.py tests/test_filltable_form.py -v`
Expected: FAIL — gaps-only tables rejected ("Mark at least one answer cell"), no `author_html` key, old-message test fails on the new assertion.

- [ ] **Step 3: Implement `clean_data`**

In `FillTableElementForm.clean_data`, add imports at the top of the method and a raw walk between `_scan_spans(raw_cells)` and `nd = FillTableElement.normalize_data(...)`:

```python
    def clean_data(self):
        from courses.fillblank import FillBlankError
        from courses.filltable import MAX_GAPS_PER_CELL
        from courses.filltable import GapMathError
        from courses.filltable import answer_cells
        from courses.filltable import gap_cells
        from courses.filltable import is_blank_answer
        from courses.filltable import is_static_cell
        from courses.filltable import parse_cell_gaps
        from courses.sanitize import sanitize_cell

        data = self.cleaned_data.get("data")
        raw_cells = data.get("cells") if isinstance(data, dict) else None
        # Raw scan FIRST: rejects an out-of-range span before normalize_data
        # clamps it out of sight. Coerces malformed input rather than raising.
        _scan_spans(raw_cells)
        # Parse {{answer}} markers on the RAW cells, BEFORE normalize_data: it
        # derives `gate` from the answers it can see, so parsing afterwards would
        # store gate:false for a table whose only answers are inline boxes
        # (spec 2026-09-24-filltable-inline-gaps §3). A posted `gaps` key is
        # discarded -- only what the html parses to is stored.
        for r, row in enumerate(raw_cells if isinstance(raw_cells, list) else []):
            if not isinstance(row, list):
                continue
            for c, cell in enumerate(row):
                if not isinstance(cell, dict):
                    continue
                cell.pop("gaps", None)
                if not is_static_cell(cell):
                    continue
                html = cell.get("html")
                try:
                    token_html, gaps = parse_cell_gaps(
                        sanitize_cell(html if isinstance(html, str) else "")
                    )
                except GapMathError:
                    raise forms.ValidationError(
                        _(
                            "Row %(r)d, column %(c)d: an answer box cannot contain "
                            "maths — put the maths outside the braces, e.g. "
                            "{{9}} \\(\\pi\\)."
                        )
                        % {"r": r + 1, "c": c + 1}
                    ) from None
                except FillBlankError:
                    raise forms.ValidationError(
                        _(
                            "Row %(r)d, column %(c)d: an answer box {{…}} is empty "
                            "or not closed."
                        )
                        % {"r": r + 1, "c": c + 1}
                    ) from None
                if len(gaps) > MAX_GAPS_PER_CELL:
                    raise forms.ValidationError(
                        _(
                            "Row %(r)d, column %(c)d: at most %(n)d answer boxes "
                            "per cell."
                        )
                        % {"r": r + 1, "c": c + 1, "n": MAX_GAPS_PER_CELL}
                    )
                cell["html"] = token_html
                if gaps:
                    cell["gaps"] = gaps
        nd = FillTableElement.normalize_data(data if isinstance(data, dict) else {})
```

⚠️ The maths message's msgid must be exactly `Row %(r)d, column %(c)d: an answer box cannot contain maths — put the maths outside the braces, e.g. {{9}} \(\pi\).` — in the Python source that is `\\(\\pi\\)` inside a normal string (or use a raw string). Check the extracted msgid in Task 9.

Replace the no-answer check:

```python
        answers = list(answer_cells(cells))
        if not answers and next(gap_cells(cells), None) is None:
            raise forms.ValidationError(
                _(
                    "Add at least one answer — mark an answer cell, or type "
                    "{{answer}} in a cell."
                )
            )
```

(The blank-answer check below it stays as-is.)

Also update the comment in `FillTableElementForm.grid_data` that says the no-answer and blank-answer grids "are ALSO two of clean_data's five rejection reasons" and "A no-op for the other three rejection paths": there are now eight rejection paths, and `preserve` is a no-op for the six that do not suppress `gate` (spans, caps, image scope, and the three new marker errors — empty/unclosed, maths, cap). Reword to name them rather than count. In `FillTableElement.normalize_data`, check the "TWO grid shapes do that" intro still reads true after Task 2 (it does — the two shapes are now "no answer cell and no gap" and "blank answer cell"); adjust the wording if not.

- [ ] **Step 4: Implement `resolved_grid_cells`**

Replace the body of `FillTableElementForm.resolved_grid_cells` (keep its docstring, append one paragraph):

```python
        from courses.filltable import author_cell_html
        from courses.filltable import is_static_cell

        cells = FillTableElement.resolve_image_cells(
            self.grid_data["cells"], course=self.course
        )
        # The editor must show {{answer}}, never the stored U+FFFF tokens: a token
        # posted back is stripped to a bare digit and every box in the table is lost
        # on the next save (spec §7). Identity for a cell without `gaps`.
        return [
            [
                {**cell, "author_html": author_cell_html(cell)}
                if is_static_cell(cell)
                else cell
                for cell in row
            ]
            for row in cells
        ]
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_filltable_gaps_form.py tests/test_filltable_form.py tests/test_filltable_editor_partial.py -v`
Expected: all PASS.

- [ ] **Step 6: Falsify the gate-ordering test (spec "Falsify")**

Mutant: move the whole `for r, row in enumerate(raw_cells …)` walk to AFTER `nd = FillTableElement.normalize_data(...)` and make it walk `nd["cells"]` instead. Run `uv run pytest tests/test_filltable_gaps_form.py::test_gate_survives_for_gaps_only_table_through_the_form -v` → must FAIL (`assert False is True`). Revert BY HAND, `git diff` shows only the intended changes, re-run → PASS.

- [ ] **Step 7: Commit**

```bash
uv run ruff format courses/element_forms.py tests/test_filltable_gaps_form.py tests/test_filltable_form.py
uv run ruff check courses/element_forms.py tests/test_filltable_gaps_form.py tests/test_filltable_form.py
git add courses/element_forms.py tests/test_filltable_gaps_form.py tests/test_filltable_form.py
git commit -m "feat(filltable): the form parses {{answer}} boxes before normalising

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Student render — inline inputs, done state, no leak

**Files:**
- Modify: `courses/filltable.py` (add `cell_parts`)
- Modify: `courses/models.py` — `FillTableElement.render` (~line 1670)
- Modify: `templates/courses/elements/_filltable_cell.html`
- Modify: `courses/static/courses/css/courses.css` — after the `.el--filltable .filltable__input { min-width: … }` block (~line 1771-1773)
- Test: `tests/test_filltable_gaps_render.py` (create)

**Interfaces:**
- Consumes: normalized/canonical cells from Task 2 (`gaps`, `gaps_display`).
- Produces: `cell_parts(cell, r, c, *, done) -> SafeString`; rendered inputs `class="filltable__input filltable__input--inline"` with `data-r`, `data-c`, `data-g` (consumed by Task 5's JS and Task 10's e2e).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_filltable_gaps_render.py`:

```python
import re

import pytest

from courses.models import Element
from courses.models import FillTableElement
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db

S = "\uffff"


def _el(cells, **kw):
    el = FillTableElement(data={"cells": cells, **kw})
    el.save()
    return el


def _render(el, done=False):
    if not done:
        return el.render(element=None, state=None)
    _course, unit = make_course_with_unit()
    row = Element.objects.create(unit=unit, content_object=el)
    return el.render(element=row, state={row.pk: {"done": True}})


TWO_GAPS = [
    [
        {
            "kind": "static",
            "html": r"\(y\) " + f"{S}0{S} and {S}1{S}",
            "gaps": [["ZQXanswerone"], ["ZQXanswertwo", "ZQXalt"]],
        }
    ]
]


def test_inline_inputs_rendered_with_rcg():
    html = _render(_el(TWO_GAPS))
    inputs = re.findall(r"<input[^>]*filltable__input--inline[^>]*>", html)
    assert len(inputs) == 2
    assert 'data-r="0" data-c="0" data-g="0"' in inputs[0]
    assert 'data-g="1"' in inputs[1]
    assert "box 2" in inputs[1]
    assert r"\(y\) " in html
    assert S not in html


def test_single_gap_label_has_no_box_number():
    html = _render(_el([[{"kind": "static", "html": f"{S}0{S}", "gaps": [["9"]]}]]))
    label = re.search(r'aria-label="([^"]*)"', html.split("filltable__input--inline")[1])
    assert label.group(1) == "Answer, row 1, column 1"


def test_answers_never_reach_the_page():
    html = _render(_el(TWO_GAPS))
    assert "ZQX" not in html


def test_done_state_shows_first_alternative_locked():
    html = _render(_el(TWO_GAPS), done=True)
    inputs = re.findall(r"<input[^>]*filltable__input--inline[^>]*>", html)
    assert 'value="ZQXanswerone"' in inputs[0]
    assert "readonly" in inputs[0]
    assert "filltable__input--correct" in inputs[0]
    assert f'size="{len("ZQXanswerone")}"' in inputs[0]
    assert "ZQXanswertwo" in inputs[1] and "ZQXalt" not in inputs[1]


def test_done_state_value_is_escaped():
    el = _el([[{"kind": "static", "html": f"{S}0{S}", "gaps": [['a<b"c']]}]])
    html = _render(el, done=True)
    assert 'value="a&lt;b&quot;c"' in html
    assert 'a<b"c' not in html


def test_cell_without_gaps_renders_no_gap_input():
    html = _render(
        _el(
            [
                [
                    {"kind": "static", "html": "a" + f"{S}0{S}"},
                    {"kind": "answer", "answer": "1"},
                ]
            ]
        )
    )
    assert "data-g=" not in html
```

- [ ] **Step 2: Run to verify failures**

Run: `uv run pytest tests/test_filltable_gaps_render.py -v`
Expected: FAIL — no `filltable__input--inline` inputs; raw U+FFFF in the output.

- [ ] **Step 3: Add `cell_parts` to `courses/filltable.py`**

```python
def cell_parts(cell, r, c, *, done):
    """A static cell's html with each token replaced by its inline <input>, as ONE
    safe string. Text segments are trusted (sanitised at save); every input is
    built with format_html, the ONLY escaping they get (spec §5). In the done state
    each box shows its gaps_display value, readonly, sized to fit -- `readonly` (not
    `disabled`) is what the CSS width release keys on."""
    from django.utils.html import format_html
    from django.utils.safestring import mark_safe
    from django.utils.translation import gettext as _

    n_gaps = len(cell.get("gaps") or [])
    display = cell.get("gaps_display") or []
    out = []
    for i, part in enumerate(_TOKEN_RE.split(cell.get("html") or "")):
        if i % 2 == 0:
            out.append(part)
            continue
        g = int(part)
        if n_gaps == 1:
            # Reuses the answer-cell template's msgid exactly.
            label = _("Answer, row %(r)s, column %(c)s") % {"r": r + 1, "c": c + 1}
        else:
            label = _("Answer, row %(r)s, column %(c)s, box %(g)s") % {
                "r": r + 1,
                "c": c + 1,
                "g": g + 1,
            }
        if done:
            v = display[g] if 0 <= g < len(display) else ""
            out.append(
                format_html(
                    '<input type="text" class="filltable__input '
                    'filltable__input--inline filltable__input--correct" '
                    'data-r="{}" data-c="{}" data-g="{}" value="{}" size="{}" '
                    'readonly aria-label="{}">',
                    r,
                    c,
                    g,
                    v,
                    max(len(v), 2),
                    label,
                )
            )
        else:
            out.append(
                format_html(
                    '<input type="text" class="filltable__input '
                    'filltable__input--inline" data-r="{}" data-c="{}" '
                    'data-g="{}" aria-label="{}">',
                    r,
                    c,
                    g,
                    label,
                )
            )
    return mark_safe("".join(str(p) for p in out))  # noqa: S308 — see docstring
```

- [ ] **Step 4: Wire it into `FillTableElement.render`**

Replace the `if ctx["mine"].get("done"): … else: …` cell assignments so both branches go through one helper. Add a static method on `FillTableElement`:

```python
    @staticmethod
    def _with_parts(cells, *, done):
        """Precompute each gapped static cell's `parts` (spec §5). In the non-done
        branch `gaps` is REMOVED so no template can ever emit the answers."""
        from courses.filltable import cell_parts

        out = []
        for r, row in enumerate(cells):
            new_row = []
            for c, cell in enumerate(row):
                if cell.get("kind") not in (FillTableElement.ANSWER, "image") and cell.get(
                    "gaps"
                ):
                    parts = cell_parts(cell, r, c, done=done)
                    if done:
                        cell = {**cell, "parts": parts}
                    else:
                        cell = {
                            **{k: v for k, v in cell.items() if k != "gaps"},
                            "parts": parts,
                        }
                new_row.append(cell)
            out.append(new_row)
        return out
```

In `render()`:
- done branch: `ctx["data"] = {**nd, "cells": self._with_parts(self.canonical_cells, done=True)}`
- else branch: `ctx["data"] = {**nd, "cells": self._with_parts(self.resolved_cells, done=False)}`

- [ ] **Step 5: Template**

In `templates/courses/elements/_filltable_cell.html`, change the final `{% else %}{{ cell.html|safe }}{% endif %}` to:

```django
{% else %}{% if cell.parts %}{{ cell.parts }}{% else %}{{ cell.html|safe }}{% endif %}{% endif %}
```

(The file is one line; keep it one line. `cell.parts` is already a SafeString.)

- [ ] **Step 6: CSS**

In `courses/static/courses/css/courses.css`, directly AFTER the block

```css
.el--filltable .filltable__input {
  min-width: calc(4ch + 2 * var(--space-3) + 2px);
}
```

add:

```css
/* INLINE ANSWER BOX ({{answer}} typed into a static cell's text; spec
   2026-09-24-filltable-inline-gaps §5). Sits in running text and maths, so it
   must not fill the cell or pad the line. (0,2,0) and AFTER the min-width floor
   above (same specificity) so `min-width: 0` wins on source order. The width is
   content + padding + border because app.css's (0,1,1) rule makes the box
   border-box; ~6ch of content, fixed -- never sized to the answer. */
.el--filltable .filltable__input--inline {
  display: inline-block;
  width: calc(6ch + 2 * var(--space-1) + 2px);
  min-width: 0;
  padding-block: 0;
  padding-inline: var(--space-1);
  vertical-align: baseline;
}
/* Done state only: the server sets `readonly` + a fitting `size`, so a long first
   answer is not clipped. [readonly], NEVER :read-only -- the live lock() sets
   `disabled`, which matches :read-only, and with no `size` the box would jump to
   the UA's 20ch on the moment of success. (0,3,0) beats the width above. */
.el--filltable .filltable__input--inline[readonly] { width: auto; }
```

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/test_filltable_gaps_render.py tests/test_filltable_restore.py tests/test_filltable_context.py tests/test_filltable_model.py tests/test_imagezoom_render.py tests/test_css_comments_are_terminated_once.py tests/test_css_citations_are_durable.py tests/test_table_css.py -v`
Expected: all PASS.

- [ ] **Step 8: Falsify the leak test**

Mutant: in `_with_parts`, keep `gaps` in the non-done branch (`cell = {**cell, "parts": parts}`) AND change the template's `{{ cell.parts }}` to `{{ cell.parts }}<span hidden>{{ cell.gaps }}</span>`. Run `uv run pytest tests/test_filltable_gaps_render.py::test_answers_never_reach_the_page -v` → must FAIL. Revert both by hand; re-run → PASS. (This proves the test detects a leak; the structural removal of `gaps` is what makes such a template edit harmless.)

- [ ] **Step 9: Commit**

```bash
uv run ruff format courses/filltable.py courses/models.py tests/test_filltable_gaps_render.py
uv run ruff check courses/ tests/test_filltable_gaps_render.py
git add courses/filltable.py courses/models.py templates/courses/elements/_filltable_cell.html courses/static/courses/css/courses.css tests/test_filltable_gaps_render.py
git commit -m "feat(filltable): render inline answer boxes in static cells

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Checking — server per box, JS keys and paint

**Files:**
- Modify: `courses/views.py` — `filltable_check` (~line 1286-1310)
- Modify: `courses/static/courses/js/filltable.js` — `paint` (~line 18) and `submit` (~line 54)
- Test: `tests/test_filltable_gaps_check.py` (create)

**Interfaces:**
- Consumes: `gap_cells` (Task 1); inputs with `data-g` (Task 4).
- Produces: POST key `r{r}c{c}g{g}`; response cell `{"r", "c", "g", "correct"}` for gaps (answer cells unchanged, no `g`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_filltable_gaps_check.py` (reuses the fixtures pattern of `tests/test_filltable_check.py`):

```python
import pytest
from django.test import Client
from django.urls import reverse

from courses.models import FillTableElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element
from tests.factories import make_login

pytestmark = pytest.mark.django_db

S = "\uffff"


@pytest.fixture
def client_and_element():
    c = Client()
    user = make_login(c, "ftgap-owner")

    def _make(cells, **kw):
        course = CourseFactory(owner=user)
        unit = ContentNodeFactory(
            course=course, kind="unit", unit_type="lesson", parent=None
        )
        el = FillTableElement(data={"cells": cells, **kw})
        el.save()
        return c, add_element(unit, el)

    return _make


CELLS = [
    [
        {"kind": "static", "html": f"{S}0{S} and {S}1{S}", "gaps": [["9"], ["Ab", "x"]]},
        {"kind": "answer", "answer": "4"},
    ]
]


def _check(client, element, fields):
    r = client.post(reverse("courses:filltable_check", args=[element.pk]), fields)
    return r.json()


def test_each_gap_marked_separately(client_and_element):
    client, element = client_and_element(CELLS)
    data = _check(client, element, {"r0c0g0": "8", "r0c0g1": "x", "r0c1": "4"})
    by_key = {(d["r"], d["c"], d.get("g")): d["correct"] for d in data["cells"]}
    assert by_key == {(0, 0, 0): False, (0, 0, 1): True, (0, 1, None): True}
    assert data["all_correct"] is False


def test_all_correct_needs_answer_cells_and_gaps(client_and_element):
    client, element = client_and_element(CELLS)
    data = _check(client, element, {"r0c0g0": "9", "r0c0g1": "ab", "r0c1": "4"})
    assert data["all_correct"] is True
    data = _check(client, element, {"r0c0g0": "9", "r0c0g1": "ab", "r0c1": "5"})
    assert data["all_correct"] is False


def test_case_sensitivity_applies_to_gaps(client_and_element):
    client, element = client_and_element(CELLS, case_sensitive=True)
    data = _check(client, element, {"r0c0g0": "9", "r0c0g1": "ab", "r0c1": "4"})
    g1 = [d for d in data["cells"] if d.get("g") == 1][0]
    assert g1["correct"] is False


def test_gaps_only_table(client_and_element):
    client, element = client_and_element(
        [[{"kind": "static", "html": f"{S}0{S}", "gaps": [["9"]]}]]
    )
    data = _check(client, element, {"r0c0g0": "9"})
    assert data == {"cells": [{"r": 0, "c": 0, "g": 0, "correct": True}], "all_correct": True}
```

- [ ] **Step 2: Run to verify failures**

Run: `uv run pytest tests/test_filltable_gaps_check.py -v`
Expected: FAIL — gap cells absent from the response; gaps-only table returns the empty body.

- [ ] **Step 3: Implement the view**

In `filltable_check`, add `from courses.filltable import gap_cells` and, after the existing `for r, c, answer in answer_cells(...)` loop and before `if not cells:`:

```python
    for r, c, g, alts in gap_cells(nd["cells"]):
        got = request.POST.get(f"r{r}c{c}g{g}", "")
        ok = blank_matches(got, alts, case_sensitive=case_sensitive)
        cells.append({"r": r, "c": c, "g": g, "correct": ok})
        all_correct = all_correct and ok
```

Update the docstring's "Per-cell correctness only" to "Per-cell (and per inline box) correctness only".

- [ ] **Step 4: Implement the JS**

In `courses/static/courses/js/filltable.js`, `paint`:

```js
  function paint(root, cells) {
    (cells || []).forEach(function (cell) {
      // Presence, NOT truthiness: the first inline box has g === 0. A box shares
      // its cell's r/c, so the g term is what picks the right box; an answer
      // cell (no g) never matches an inline box.
      var sel = '.filltable__input[data-r="' + cell.r + '"][data-c="' + cell.c + '"]';
      sel += ("g" in cell) ? '[data-g="' + cell.g + '"]' : ":not([data-g])";
      var inp = root.querySelector(sel);
      if (!inp) return;
      inp.classList.remove("filltable__input--correct", "filltable__input--incorrect");
      if (cell.correct === true) inp.classList.add("filltable__input--correct");
      else if (cell.correct === false) inp.classList.add("filltable__input--incorrect");
    });
  }
```

In `submit`:

```js
    inputs(root).forEach(function (inp) {
      var key = "r" + inp.dataset.r + "c" + inp.dataset.c;
      if (inp.dataset.g !== undefined) key += "g" + inp.dataset.g;
      body.append(key, inp.value);
    });
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_filltable_gaps_check.py tests/test_filltable_check.py -v`
Expected: all PASS. (The JS is exercised by Task 10's e2e, which also carries the `data-g` mutant.)

- [ ] **Step 6: Commit**

```bash
uv run ruff format courses/views.py tests/test_filltable_gaps_check.py
uv run ruff check courses/views.py tests/test_filltable_gaps_check.py
git add courses/views.py courses/static/courses/js/filltable.js tests/test_filltable_gaps_check.py
git commit -m "feat(filltable): check and paint each inline answer box

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Editor — show `{{…}}`, hint, submit guard

**Files:**
- Modify: `templates/courses/manage/editor/_edit_filltable.html` — `data-msg-no-answer` (line 17), the two static-cell branches (~lines 127/130), hint after the grid (~line 140)
- Modify: `courses/static/courses/js/filltable_editor.js` — `onSubmit` (~lines 1032-1066)
- Modify: `tests/test_editor_twin_drift.py` — `_functions` docstring only
- Modify: `tests/test_filltable_editor_partial.py` — comments at ~339 and ~497 quoting the old message
- Test: `tests/test_filltable_gaps_editor.py` (create)

**Interfaces:**
- Consumes: `resolved_grid_cells[..]["author_html"]` (Task 3).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_filltable_gaps_editor.py`:

```python
import pytest
from django.template.loader import render_to_string

from courses.element_forms import FORM_FOR_TYPE
from courses.models import FillTableElement

pytestmark = pytest.mark.django_db

S = "\uffff"


def _render(instance):
    form = FORM_FOR_TYPE["filltable"](instance=instance)
    return render_to_string(
        "courses/manage/editor/_edit_filltable.html",
        {"form": form, "type_key": "filltable"},
    )


def test_stored_gaps_shown_as_markers_in_td_and_th():
    el = FillTableElement(
        data={
            "cells": [
                [
                    {
                        "kind": "static",
                        "html": f"{S}0{S} x",
                        "gaps": [["9", "9,0"]],
                        "header": True,
                    },
                    {"kind": "static", "html": f"{S}0{S}", "gaps": [["a<b"]]},
                ]
            ]
        }
    )
    html = _render(el)
    assert "{{9|9,0}} x</th>" in html
    assert "{{a&lt;b}}</td>" in html
    assert S not in html


def test_hint_and_no_answer_message_keep_literal_braces():
    html = _render(FillTableElement())
    assert "Type {{answer}} in a cell" in html
    assert (
        'data-msg-no-answer="Add at least one answer — mark an answer cell, '
        'or type {{answer}} in a cell."'
    ) in html
```

- [ ] **Step 2: Run to verify failures**

Run: `uv run pytest tests/test_filltable_gaps_editor.py -v`
Expected: FAIL — tokens in the output, no hint, old message.

- [ ] **Step 3: Template**

1. Line 17 → `data-msg-no-answer="{% trans 'Add at least one answer — mark an answer cell, or type {{answer}} in a cell.' %}"`
2. In BOTH static branches (the `<th contenteditable…>` and `<td contenteditable…>`), replace `{{ cell.html|safe }}` with `{{ cell.author_html|safe }}`.
3. Directly after the grid wrapper's closing `</div></div>` (the line after `</table>`), add:

```django
  <p class="el-editor__hint">{% trans 'Type {{answer}} in a cell to put an answer box inside its text; separate accepted alternatives with |.' %}</p>
```

(`el-editor__hint` is the class the fill-blank editor uses for its own `{{answer}}` hint — `templates/courses/manage/editor/_edit_fillblankquestion.html` — which also proves `{% trans %}` keeps a literal `{{answer}}`. Do not invent new CSS.)

- [ ] **Step 4: JS submit guard**

In `filltable_editor.js` `onSubmit`, replace the `if (answerInputs.length === 0) { … }` block with:

```js
    // Brace-free on purpose: tests/test_editor_twin_drift.py delimits function
    // bodies by counting braces per line, so a literal double open-brace would
    // swallow the rest of this file; \x7b and \x7d are the escapes.
    var markerOpen = "\x7b\x7b";
    var hasGap = Array.prototype.some.call(
      grid.querySelectorAll("td[contenteditable], th[contenteditable]"),
      function (cell) { return cell.textContent.indexOf(markerOpen) !== -1; }
    );
    if (answerInputs.length === 0 && !hasGap) {
      e.preventDefault();
      e.stopPropagation();
      showAnswerError(
        editor,
        editor.getAttribute("data-msg-no-answer") ||
          "Add at least one answer — mark an answer cell, or type \x7b\x7banswer\x7d\x7d in a cell."
      );
      return;
    }
```

No new NAMED function is added (the callback is anonymous), so `EXPECTED_COUNTS[FILL_JS]` stays 37.

Brace balance check (the drift guard counts braces in comments and strings too, and `onSubmit` has no twin, so nothing else would catch an imbalance): no COMMENT or STRING line you added may be brace-unbalanced. Verify:

```bash
git diff -U0 courses/static/courses/js/filltable_editor.js | grep '^+[^+]' | awk '{o=gsub(/\{/,"{"); c=gsub(/\}/,"}"); if (o!=c) print "UNBALANCED: " $0}'
```
Expected: exactly ONE line — `UNBALANCED: +    if (answerInputs.length === 0 && !hasGap) {` — the `if` header whose `}` is the unchanged closing line (its balance is the same as the line it replaced). Any other line printed, especially a comment or string, is a defect: fix it.

- [ ] **Step 5: Drift-guard docstring + stale comments**

In `tests/test_editor_twin_drift.py` `_functions` docstring, the sentence wraps across two lines:

```
    literal, a template string, and a comment. The first three do not occur in
    either editor; the fourth does (`{% trans %}`, `LAYOUT {r, c}`) but every
```
Change it to:

```
    literal, a template string, and a comment. The first three must never carry
    a literal brace in either editor -- use the JS hex escape for the brace
    instead, as filltable_editor.js onSubmit does; the fourth does
    (`{% trans %}`, `LAYOUT {r, c}`) but every
```
(Words, not `\x7b`: this docstring is a normal Python string, where `\x7b` would itself become a brace.)
(re-wrap the rest of the paragraph so lines stay under 88 characters). Then `git grep -n -i "at least one answer cell" -- tests courses/tests` and update EVERY hit to the new rule/message (comment/docstring-only changes) — known: `tests/test_filltable_editor_partial.py` ~179, ~339, ~497 and `tests/test_e2e_table_cell_images.py` ~623. Add any extra files touched to the Step 8 `git add`.

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/test_filltable_gaps_editor.py tests/test_filltable_editor_partial.py tests/test_editor_twin_drift.py tests/test_filltable_gaps_form.py tests/test_filltable_manage_plumbing.py tests/test_text_colour_toolbars.py tests/test_cell_selector_guard.py tests/test_editor_js_scroll_invariants.py tests/test_colour_glue_drift.py -v`
Expected: all PASS.

Then the e2e that drives the no-answer guard and the error placement (the hint now sits between the grid and the error): `uv run pytest tests/test_e2e_editor_scroll_containment.py -m e2e -v` → PASS.

- [ ] **Step 7: Falsify the editor round-trip**

Mutant: change the `<td>` static branch back to `{{ cell.html|safe }}`. Run `uv run pytest tests/test_filltable_gaps_editor.py::test_stored_gaps_shown_as_markers_in_td_and_th -v` → must FAIL. Revert by hand; repeat for the `<th>` branch (both must be individually detected). Re-run → PASS.

- [ ] **Step 8: Commit**

```bash
uv run ruff format tests/test_filltable_gaps_editor.py tests/test_editor_twin_drift.py tests/test_filltable_editor_partial.py
uv run ruff check tests/test_filltable_gaps_editor.py tests/test_editor_twin_drift.py tests/test_filltable_editor_partial.py
git add templates/courses/manage/editor/_edit_filltable.html courses/static/courses/js/filltable_editor.js tests/test_editor_twin_drift.py tests/test_filltable_editor_partial.py tests/test_filltable_gaps_editor.py
git commit -m "feat(filltable): editor shows {{answer}} boxes, hints, accepts gaps-only tables

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Transfer — validator, FORMAT_VERSION 16, round-trip

**Files:**
- Modify: `courses/transfer/payloads.py` — `_val_fill_table` (~line 781)
- Modify: `courses/transfer/schema.py:14` — `FORMAT_VERSION = 16`
- Modify (15 → 16): `courses/tests/test_beforeafter_transfer.py:169`, `courses/tests/test_caption_transfer.py:62`, `courses/tests/test_image_size_transfer.py:44`, `tests/test_link_transfer.py:54`, `tests/test_table_transfer.py:299`, `tests/test_tabs_transfer.py:62`, `tests/test_transfer_schema.py:79`, and `tests/test_transfer_export.py:222` (`manifest["format_version"] == 15`)
- Test: `tests/test_filltable_transfer.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_filltable_transfer.py`:

```python
def test_gaps_round_trip_through_export_and_import():
    S = "\uffff"
    src = FillTableElement(
        data={
            "cells": [
                [
                    {"kind": "static", "html": f"{S}0{S} x", "gaps": [["9", "9,0"]]},
                    {"kind": "answer", "answer": "4"},
                ]
            ]
        }
    )
    src.save()
    payload = SERIALIZERS["fill_table"][1](src, set())
    VALIDATORS["fill_table"](payload, "e1", set())
    obj, _children = BUILDERS["fill_table"](payload, {})
    cell = obj.normalize_data(obj.data)["cells"][0][0]
    assert cell["html"] == f"{S}0{S} x"
    assert cell["gaps"] == [["9", "9,0"]]


def test_v15_payload_without_gaps_imports_unchanged():
    # An archive written before this feature (format 15) has no `gaps` anywhere.
    payload = {
        "header_row": False,
        "header_col": False,
        "case_sensitive": False,
        "gate": False,
        "border": "grid",
        "prompt": "",
        "cells": [
            [
                {"kind": "static", "html": "<b>t</b>", "halign": "left", "valign": "top"},
                {"kind": "answer", "answer": "4", "halign": "left", "valign": "top"},
            ]
        ],
    }
    VALIDATORS["fill_table"](payload, "e1", set())
    obj, _children = BUILDERS["fill_table"](payload, {})
    assert obj.normalize_data(obj.data)["cells"] == payload["cells"]


def test_validator_rejects_non_list_gaps():
    with pytest.raises(TransferError):
        VALIDATORS["fill_table"](
            {"cells": [[{"kind": "static", "html": "x", "gaps": "bad"}]]}, "e1", set()
        )


def test_validator_leaves_entry_level_gap_damage_to_reconcile():
    VALIDATORS["fill_table"](
        {"cells": [[{"kind": "static", "html": "x", "gaps": [["a", 3], "bad"]]}]},
        "e1",
        set(),
    )  # must not raise
```

Check the top of the file imports `TransferError` (`from courses.transfer.schema import TransferError`); add it if missing.

- [ ] **Step 2: Run to verify failures**

Run: `uv run pytest tests/test_filltable_transfer.py -v`
Expected: exactly ONE failure — `test_validator_rejects_non_list_gaps` (no raise). Three PASS already, by design: `test_gaps_round_trip_through_export_and_import` (export copies `dict(c)`, Task 2 keeps `gaps` — the guard for that free behaviour), `test_v15_payload_without_gaps_imports_unchanged` (no gaps anywhere), `test_validator_leaves_entry_level_gap_damage_to_reconcile` (the validator is lenient by design).

- [ ] **Step 3: Implement the validator**

In `_val_fill_table`, inside the `for cell in row:` loop after the non-dict check:

```python
            if (
                cell.get("kind") not in ("answer", "image")
                and "gaps" in cell
                and not isinstance(cell["gaps"], list)
            ):
                _err(
                    _("Element '%(el)s': fill-in table gaps must be a list."),
                    el=elid,
                )
```

- [ ] **Step 4: Bump the format version**

`courses/transfer/schema.py`: `FORMAT_VERSION = 16`. Add a one-line comment above it if the file has a version-history comment style elsewhere (grep `FORMAT_VERSION` comments in `payloads.py`, e.g. "added in FORMAT_VERSION 14"); otherwise none. Change the seven `assert FORMAT_VERSION == 15` lines to `== 16`, AND the eighth pin spelled differently: `tests/test_transfer_export.py:222` `assert manifest["format_version"] == 15` → `== 16`. Then confirm no other pin, both spellings, excluding the docs that quote them: `git grep -nE 'FORMAT_VERSION == 15|format_version"\] == 15' -- ':!docs'` → no output.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_filltable_transfer.py tests/test_transfer_schema.py tests/test_table_transfer.py tests/test_tabs_transfer.py tests/test_link_transfer.py courses/tests/test_beforeafter_transfer.py courses/tests/test_caption_transfer.py courses/tests/test_image_size_transfer.py tests/test_transfer_export.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
uv run ruff format courses/transfer tests/test_filltable_transfer.py
uv run ruff check courses/transfer tests/test_filltable_transfer.py
git add courses/transfer tests/test_filltable_transfer.py courses/tests/test_beforeafter_transfer.py courses/tests/test_caption_transfer.py courses/tests/test_image_size_transfer.py tests/test_link_transfer.py tests/test_table_transfer.py tests/test_tabs_transfer.py tests/test_transfer_schema.py tests/test_transfer_export.py
git commit -m "feat(transfer): fill-table gaps travel; format version 16

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Builder summary counts boxes; recolour skips gapped cells

**Files:**
- Modify: `courses/templatetags/courses_manage_extras.py:192`
- Modify: `courses/recolour/dbscan.py` — `find_matches` cell loop (~line 131)
- Test: `tests/test_table_manage_plumbing.py` (extend), `tests/test_recolour_dbscan.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_table_manage_plumbing.py` (reuse its imports of `element_summary`; add `from courses.models import FillTableElement` if absent — check the file's existing `_filltable` helper for how it builds the element row and mirror it):

```python
def test_filltable_summary_counts_inline_gaps():
    S = "\uffff"
    el = FillTableElement(
        data={
            "cells": [
                [
                    {"kind": "static", "html": f"{S}0{S}{S}1{S}", "gaps": [["a"], ["b"]]},
                    {"kind": "answer", "answer": "1"},
                ]
            ]
        }
    )
    assert element_summary(el) == "1×2 fill-in table, 3 answer(s)"
```

(If `element_summary` takes the `Element` join row rather than the concrete element, build it exactly the way `_filltable(gate)` in that file does.)

Append to `tests/test_recolour_dbscan.py`:

```python
def test_a_filltable_cell_with_gaps_is_never_matched():
    # Recolouring rewrites cell["html"] wholesale; on a gapped cell that would
    # orphan its gaps and reconcile_gaps would silently drop every box.
    from courses.models import FillTableElement

    course = CourseFactory()
    _part, unit = _unit(course)
    ft = FillTableElement.objects.create(
        data={"cells": [[{"kind": "static", "html": "a", "gaps": [["x"]]}]]}
    )
    Element.objects.create(unit=unit, content_object=ft)
    matches = find_matches(course, {"a": '<span class="tc-red">a</span>'}, set())
    assert [m for m in matches if m.model is FillTableElement] == []
```

Also append (the §9 verification — passes before and after the guard, because exact matching is what protects real gapped cells):

```python
def test_a_real_gapped_cell_is_not_matched_by_its_text():
    from courses.models import FillTableElement

    tok = "\uffff0\uffff"
    course = CourseFactory()
    _part, unit = _unit(course)
    ft = FillTableElement.objects.create(
        data={"cells": [[{"kind": "static", "html": "a" + tok, "gaps": [["x"]]}]]}
    )
    Element.objects.create(unit=unit, content_object=ft)
    matches = find_matches(course, {"a": '<span class="tc-red">a</span>'}, set())
    assert [m for m in matches if m.model is FillTableElement] == []
```

(`FillTableElement.objects.create` does not run the form, and `_cell` drops tokenless gaps only on read — the stored row keeps `gaps` here, which is the shape the guard is for. Confirm with `ft.refresh_from_db(); assert ft.data["cells"][0][0]["gaps"]` as a precondition line.)

- [ ] **Step 2: Run to verify failures**

Run: `uv run pytest tests/test_table_manage_plumbing.py tests/test_recolour_dbscan.py -v`
Expected: summary says `1 answer(s)`; the recolour test finds a match.

- [ ] **Step 3: Implement**

`courses_manage_extras.py`:

```python
        n_ans = sum(1 for row in d["cells"] for c in row if c["kind"] == "answer")
        n_ans += sum(len(c.get("gaps") or []) for row in d["cells"] for c in row)
```

**Spec §9 check, plus a defence-in-depth guard.** `find_matches` matches only when a cell's stored html EQUALS a key exactly, and keys are built from LAL source, which never contains U+FFFF — so a real gapped cell (html with tokens) is never matched and its tokens survive. That is the §9 verification; pin it with the second test below. The guard `if cell.get("gaps"): continue` additionally covers the only reachable hole: a `gaps` key on a token-less cell (direct model writes), where a wholesale html rewrite would orphan the gaps. Say in the PR: "recolour cannot touch cells with inline boxes (exact match excludes their tokens; an explicit guard covers the rest)".

`dbscan.py`, after the `if cell.get("kind") not in (None, "static"): continue` guard:

```python
                    # Defence in depth: exact matching already excludes a cell whose
                    # html holds inline-box tokens (LAL keys never contain U+FFFF);
                    # this also skips a token-less cell that carries `gaps`, where a
                    # wholesale rewrite would orphan them (spec 2026-09-24 §9).
                    if cell.get("gaps"):
                        continue
```

- [ ] **Step 4: Run tests** — same command → PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff format courses/templatetags courses/recolour tests/test_table_manage_plumbing.py tests/test_recolour_dbscan.py
uv run ruff check courses/templatetags courses/recolour tests/test_table_manage_plumbing.py tests/test_recolour_dbscan.py
git add courses/templatetags/courses_manage_extras.py courses/recolour/dbscan.py tests/test_table_manage_plumbing.py tests/test_recolour_dbscan.py
git commit -m "feat(filltable): summary counts inline boxes; recolour skips gapped cells

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Translations and help

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po`, `locale/en/LC_MESSAGES/django.po` (+ compiled `.mo`)
- Modify: `docs/help/course-admin/interactive-elements.md`, `docs/help/course-admin/interactive-elements.pl.md` (Fill-in table section)

- [ ] **Step 1: Extract**

Run: `uv run python manage.py makemessages -l pl -l en` (use the project's usual flags — check `git log -p -1 -- locale/pl/LC_MESSAGES/django.po | head -20` for how the last catalog commit was produced, e.g. `--no-location`, and match it).

- [ ] **Step 2: Write every new msgstr from this table — unconditionally**

`makemessages` fuzzy-matches by similarity and WILL pre-fill wrong text (the no-answer msgid is close to the old one). Overwrite each msgstr, remove every `#, fuzzy` on these entries, and delete the obsolete old no-answer entry if `makemessages` left it commented (`#~`).

| msgid | pl msgstr |
|---|---|
| `Add at least one answer — mark an answer cell, or type {{answer}} in a cell.` | `Dodaj co najmniej jedną odpowiedź — oznacz komórkę z odpowiedzią albo wpisz {{odpowiedź}} w komórce.` |
| `Row %(r)d, column %(c)d: an answer box {{…}} is empty or not closed.` | `Wiersz %(r)d, kolumna %(c)d: pole odpowiedzi {{…}} jest puste albo niezamknięte.` |
| `Row %(r)d, column %(c)d: an answer box cannot contain maths — put the maths outside the braces, e.g. {{9}} \(\pi\).` | `Wiersz %(r)d, kolumna %(c)d: pole odpowiedzi nie może zawierać wzoru — umieść wzór poza nawiasami, np. {{9}} \(\pi\).` |
| `Row %(r)d, column %(c)d: at most %(n)d answer boxes per cell.` | `Wiersz %(r)d, kolumna %(c)d: w jednej komórce może być najwyżej %(n)d pól odpowiedzi.` |
| `Answer, row %(r)s, column %(c)s, box %(g)s` | `Odpowiedź, wiersz %(r)s, kolumna %(c)s, pole %(g)s` |
| `Type {{answer}} in a cell to put an answer box inside its text; separate accepted alternatives with \|.` | `Wpisz {{odpowiedź}} w komórce, aby wstawić pole odpowiedzi w jej tekst; akceptowane warianty oddziel znakiem \|.` |
| `Element '%(el)s': fill-in table gaps must be a list.` | `Element '%(el)s': pola odpowiedzi tabeli do uzupełnienia muszą być listą.` |

⚠️ **Backslashes in `.po`:** the table shows strings as they render. In `django.po` a backslash must be doubled — `makemessages` writes the maths msgid as `… e.g. {{9}} \\(\\pi\\).`, and the msgstr must be written the same way: `… np. {{9}} \\(\\pi\\).` A single `\(` is an invalid escape and breaks `compilemessages`.

⚠️ The Polish hint and no-answer text say `{{odpowiedź}}` as an EXAMPLE placeholder — that is only illustrative text; the marker syntax itself is language-neutral. **Flag these Polish strings to the owner in the PR for wording review** (they are an author-facing instruction).

The `en` catalog: leave msgstr empty (English falls back to msgid) unless the en catalog convention in this repo fills them — match what neighbouring entries do.

- [ ] **Step 3: Compile and verify**

Run `uv run python manage.py compilemessages -l pl -l en`, then verify per ENTRY (a line grep cannot: `msgmerge --previous` puts `#, fuzzy` and `#| msgid` lines above a wrapped `msgid ""`). Save as a scratch script (NOT a heredoc — bash heredocs eat backslashes) and run with `uv run python <script>`:

```python
import polib  # if missing: uv run --with polib python <script>

EXPECTED = {
    "Add at least one answer — mark an answer cell, or type {{answer}} in a cell.":
        "Dodaj co najmniej jedną odpowiedź — oznacz komórkę z odpowiedzią albo wpisz {{odpowiedź}} w komórce.",
    "Row %(r)d, column %(c)d: an answer box {{…}} is empty or not closed.":
        "Wiersz %(r)d, kolumna %(c)d: pole odpowiedzi {{…}} jest puste albo niezamknięte.",
    "Row %(r)d, column %(c)d: an answer box cannot contain maths — put the maths outside the braces, e.g. {{9}} " + chr(92) + "(" + chr(92) + "pi" + chr(92) + ").":
        "Wiersz %(r)d, kolumna %(c)d: pole odpowiedzi nie może zawierać wzoru — umieść wzór poza nawiasami, np. {{9}} " + chr(92) + "(" + chr(92) + "pi" + chr(92) + ").",
    "Row %(r)d, column %(c)d: at most %(n)d answer boxes per cell.":
        "Wiersz %(r)d, kolumna %(c)d: w jednej komórce może być najwyżej %(n)d pól odpowiedzi.",
    "Answer, row %(r)s, column %(c)s, box %(g)s":
        "Odpowiedź, wiersz %(r)s, kolumna %(c)s, pole %(g)s",
    "Type {{answer}} in a cell to put an answer box inside its text; separate accepted alternatives with |.":
        "Wpisz {{odpowiedź}} w komórce, aby wstawić pole odpowiedzi w jej tekst; akceptowane warianty oddziel znakiem |.",
    "Element '%(el)s': fill-in table gaps must be a list.":
        "Element '%(el)s': pola odpowiedzi tabeli do uzupełnienia muszą być listą.",
}
po = polib.pofile("locale/pl/LC_MESSAGES/django.po")
bad = []
for msgid, want in EXPECTED.items():
    e = po.find(msgid)
    if e is None or e.obsolete:
        bad.append(("MISSING", msgid))
    elif "fuzzy" in e.flags:
        bad.append(("FUZZY", msgid))
    elif e.msgstr != want:
        bad.append(("WRONG", msgid, e.msgstr))
print(bad or "OK")

# The en catalog: present, not obsolete, not fuzzy (msgstr empty or per the
# neighbouring entries' convention -- makemessages fuzzy-prefills here too).
en = polib.pofile("locale/en/LC_MESSAGES/django.po")
en_bad = [
    m
    for m in EXPECTED
    if (e := en.find(m)) is None or e.obsolete or "fuzzy" in e.flags
]
print(en_bad or "EN OK")
```
Expected: `OK` then `EN OK`. Then confirm the compiled catalog renders single backslashes:

```bash
uv run python manage.py shell -c "from django.utils import translation; from django.utils.translation import gettext as g; translation.activate('pl'); print(g('Row %(r)d, column %(c)d: an answer box cannot contain maths — put the maths outside the braces, e.g. {{9}} \\\\(\\\\pi\\\\).') % {'r': 1, 'c': 1})"
```
Expected: a Polish line ending `np. {{9}} \(\pi\).` (one backslash each). If it prints English, the msgid spelling differs — compare with the `.po` entry.

- [ ] **Step 4: Help pages**

Add one paragraph to the end of the Fill-in table section of each help file.

`interactive-elements.md`:

```markdown
You can also put an answer box **inside a cell's text**: type the accepted answer
in double braces, e.g. `{{9}} \(\pi\)` shows a box followed by π, and
`\(NWD(15, 16)=\) {{1}}` puts the box after the maths. Separate accepted
alternatives with `|` (`{{9|9,0}}`). A cell may hold up to 10 boxes; maths cannot
go inside the braces.
```

`interactive-elements.pl.md`:

```markdown
Pole odpowiedzi możesz też wstawić **w tekst komórki**: wpisz akceptowaną
odpowiedź w podwójnych nawiasach klamrowych, np. `{{9}} \(\pi\)` pokaże pole, a
za nim π, a `\(NWD(15, 16)=\) {{1}}` wstawi pole za wzorem. Akceptowane warianty
oddziel znakiem `|` (`{{9|9,0}}`). Komórka może zawierać do 10 pól; wzoru nie
można umieścić wewnątrz nawiasów.
```

Render check: run `uv run pytest tests/test_help.py -v` → PASS (the existing help text already shows `{{answer}}` in backticks, so the Markdown path is known to keep braces).

- [ ] **Step 5: Commit**

```bash
git add locale docs/help/course-admin/interactive-elements.md docs/help/course-admin/interactive-elements.pl.md
git commit -m "i18n+docs(filltable): inline answer box strings and help

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: e2e — author types boxes, student checks each one

**Files:**
- Create: `tests/test_e2e_filltable_gaps.py`

**Interfaces:**
- Consumes: everything above; helpers copied (not imported) from `tests/test_e2e_filltable.py` per that file's idiom — `_login`, `_unit_url`, `_make_pa_user`, `_goto_editor`, `_open_edit`, plus `_editor_unit` (a trimmed `_editor_context` without image assets).

- [ ] **Step 1: Write the test**

```python
"""e2e for inline {{answer}} boxes in a Fill-in table (spec 2026-09-24 §5-§7).
Drives the REAL editor (typing into contenteditable cells, saving) and the REAL
student gesture (typing, Check). Helpers are copied from test_e2e_filltable.py."""

import os
import re

import pytest
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD
from tests.factories import add_element

pytestmark = pytest.mark.e2e

_CORRECT = re.compile(r"\bfilltable__input--correct\b")
_INCORRECT = re.compile(r"\bfilltable__input--incorrect\b")


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


# Helpers copied from tests/test_e2e_filltable.py (that file's idiom: local copies,
# no cross-test-module imports).


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _unit_url(live_server, unit):
    from django.urls import reverse

    path = reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    return f"{live_server.url}{path}"


def _make_pa_user(username):
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles
    from tests.factories import make_verified_user

    seed_roles()
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    user.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return user


def _editor_unit(username, slug):
    from django.contrib.auth import get_user_model

    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    _make_pa_user(username)
    owner = get_user_model().objects.get(username=username)
    course = CourseFactory(slug=slug, owner=owner)
    return ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )


def _goto_editor(page, live_server, username, unit):
    _login(page, live_server, username)
    page.goto(
        f"{live_server.url}/manage/courses/{unit.course.slug}/build/unit/{unit.pk}/edit/"
    )
    page.wait_for_selector('[data-scope="editor"]')


def _open_edit(page, element_pk):
    page.locator(f'.el-act-edit[data-element-id="{element_pk}"]').click()
    page.wait_for_selector("[data-edit-slot] [data-filltable-editor]")


def _seed_static_table(unit):
    """2x1 all-static table: saveable at model level; the FORM would reject it
    until the author types a box -- which is exactly the gesture under test."""
    from courses.models import FillTableElement

    el = FillTableElement(
        data={"cells": [[{"kind": "static", "html": "a"}], [{"kind": "static", "html": "b"}]]}
    )
    el.save()
    return add_element(unit, el)


def _type_into_cell(page, cell, text):
    cell.click()
    page.keyboard.press("Control+A")
    page.keyboard.press("Delete")
    page.keyboard.type(text)


@pytest.mark.django_db(transaction=True)
def test_author_types_boxes_student_checks_each(page, live_server):
    from tests.factories import EnrollmentFactory
    from tests.factories import make_verified_user

    unit = _editor_unit("ftgap_author", "ftgap")
    element = _seed_static_table(unit)
    _goto_editor(page, live_server, "ftgap_author", unit)
    _open_edit(page, element.pk)

    cells = page.locator("[data-edit-slot] [data-table-grid] td[contenteditable]")
    _type_into_cell(page, cells.nth(0), "{{9}} \\(\\pi\\)")
    _type_into_cell(page, cells.nth(1), "\\((x+2)^2+(y\\) {{-1}} \\()^2=\\) {{16}}")
    page.locator("[data-edit-slot] .editor-form__actions button[type='submit']").click()
    page.wait_for_selector("[data-edit-slot] [data-filltable-editor]", state="detached")

    # Re-open: the editor shows the markers again (not tokens), then save unchanged.
    _open_edit(page, element.pk)
    expect(cells.nth(0)).to_contain_text("{{9}}")
    page.locator("[data-edit-slot] .editor-form__actions button[type='submit']").click()
    page.wait_for_selector("[data-edit-slot] [data-filltable-editor]", state="detached")

    student = make_verified_user(
        username="ftgap_student", email="ftgap_student@t.example.com", password=TEST_PASSWORD
    )
    EnrollmentFactory(student=student, course=unit.course)
    page.context.clear_cookies()
    _login(page, live_server, "ftgap_student")
    page.goto(_unit_url(live_server, unit))

    table = page.locator(".filltable").first
    pi_box = table.locator('.filltable__input--inline[data-r="0"][data-c="0"][data-g="0"]')
    g0 = table.locator('.filltable__input--inline[data-r="1"][data-c="0"][data-g="0"]')
    g1 = table.locator('.filltable__input--inline[data-r="1"][data-c="0"][data-g="1"]')
    expect(table.locator(".katex").first).to_be_visible()  # maths beside the boxes

    width_before = g1.bounding_box()["width"]

    pi_box.fill("9")
    g0.fill("1")  # WRONG (box 0 -- the g === 0 trap)
    g1.fill("16")  # right
    table.locator(".filltable__confirm").click()
    expect(g0).to_have_class(_INCORRECT)
    expect(g1).to_have_class(_CORRECT)
    expect(pi_box).to_have_class(_CORRECT)

    g0.fill("-1")
    table.locator(".filltable__confirm").click()
    expect(g0).to_have_class(_CORRECT)
    expect(table.locator(".filltable__confirm")).to_be_hidden()  # locked

    # The live lock sets `disabled`; the done-state width release must not fire.
    assert abs(g1.bounding_box()["width"] - width_before) < 2
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/test_e2e_filltable_gaps.py -m e2e -v`
Expected: PASS. If it fails on `_type_into_cell` (contenteditable selection quirks), inspect the saved `data` via `FillTableElement.objects.get(pk=element.object_id).data` in a debugger before changing the gesture — never replace the gesture with a `page.evaluate` that writes the DOM directly.

- [ ] **Step 3: Falsify the paint selector (`data-g` term)**

Mutant in `filltable.js` `paint`: replace the `sel += …` line with `sel += ("g" in cell) ? "" : ":not([data-g])";`. Run the e2e → must FAIL (box 1 never painted / box 0 painted with box 1's verdict). Revert by hand.

Second mutant: `sel += cell.g ? '[data-g="' + cell.g + '"]' : ":not([data-g])";` (truthiness). Run → must FAIL on `g0` (never painted). Revert by hand.

- [ ] **Step 4: Falsify the width release**

Mutant in `courses.css`: `.el--filltable .filltable__input--inline[readonly]` → `.el--filltable .filltable__input--inline:read-only`. Run the e2e → must FAIL on the width assertion. Revert by hand; `git diff` clean apart from committed work; re-run → PASS.

- [ ] **Step 5: Screenshots (light AND dark), judged separately**

Create a TEMPORARY file `tests/test_e2e_filltable_gaps_shots.py` (do not commit) that seeds, via the ORM, one table with the three cases — `{{9}} \(\pi\)`, the two-box expression, and a done-state table whose first alternative is `12345678901234` — for a student whose `theme` is `"light"` and a second student with `theme="dark"` (the `<html data-theme>` comes from `user.theme`, not a cookie), and saves `page.locator(".filltable").first.screenshot(path=…)` into the session scratchpad directory. Seed the done state with `UnitProgress(student=…, unit=…, element_state={str(row.pk): {"done": True}})` (see `tests/test_filltable_restore.py::_seed_filltable`). Also screenshot the EDITOR for the Platform Admin author in light and dark (`user.theme`): open the table in the editor and capture the grid plus the hint line below it. `.el-editor__hint` carries `margin: calc(var(--space-2) * -1) 0 0` (`editor.css`), built to sit under a form field; directly after the scrolling grid it may overlap the grid's bottom edge or scrollbar. If it does, add `.el-editor--filltable .el-editor__hint { margin-top: var(--space-2); }` to `editor.css` and re-shoot. Run it with `-m e2e`, then READ each PNG and judge: box baseline sits on the text/maths baseline; line height not visibly taller than a plain row; ~6 characters visible; the long done-state value is fully visible; dark mode box/text contrast readable. Tune the `--inline` CSS values if any check fails (re-run Tasks 4/10 tests after). Delete the temporary file.

- [ ] **Step 6: Commit**

```bash
uv run ruff format tests/test_e2e_filltable_gaps.py
uv run ruff check tests/test_e2e_filltable_gaps.py
git add tests/test_e2e_filltable_gaps.py
git commit -m "test(filltable): e2e for authored inline boxes, per-box verdicts, lock width

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: Branch gate and the pre-merge prod audit

**Files:** none (verification only), plus the PR description.

- [ ] **Step 0: Rebase onto current master and regenerate catalogs**

This branch commits binary `.mo` files, which conflict on any catalog change merged since the branch point, and the gates below must run on the real base.

```bash
git fetch origin
git rebase origin/master
```
If `locale/*/LC_MESSAGES/django.po` or `.mo` conflict: take master's copies (`git checkout origin/master -- locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo locale/en/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.mo`), `git add` them and `git rebase --continue`. Then, regardless of conflicts, re-run Task 9 Steps 1–3 (makemessages, write the seven msgstrs, compilemessages, the polib check → `OK`) and commit the regenerated catalogs as `i18n(filltable): regenerate catalogs after rebase`. All later steps run on the rebased branch.

- [ ] **Step 0b: Re-point line citations this branch moved**

Tasks 2, 4 and 5 insert lines into `courses/models.py` and `courses/views.py`; comments elsewhere cite line numbers below those insertions (known: `courses/tests/test_preview_nested_markers.py`, `demo/builders.py`, `courses/rollups.py`, `courses/templatetags/courses_extras.py`, `demo/generator.py`). No test catches a stale `.py` citation. Run:

```bash
git grep -nE "(models|views)\.py:[0-9]+" -- ':!docs'
```
For each hit whose cited line now points at different code than on `origin/master` (compare `git show origin/master:courses/models.py | sed -n '<N>p'` with the current line), replace the number with the symbol name (e.g. `models.py FillTableElement.render`) — never just bump the number. Commit as `docs(comments): cite symbols, not lines, where this branch moved them`.

- [ ] **Step 1: Lint gates**

```bash
uv run ruff format --check .
uv run ruff check .
```
Expected: both clean.

- [ ] **Step 2: Whole-suite run, in chunks (a single full run is OOM-killed)**

First record the total: `uv run pytest --collect-only 2>&1 | tail -3` (note the "N tests collected" count). Run the non-e2e suite in chunks that together cover EVERY test directory, each foreground, reading every summary line:
1. `uv run pytest tests/test_[a-f]*`
2. `uv run pytest tests/test_[g-o]*`
3. `uv run pytest tests/test_[p-z]* tests/demo tests/lal_import`
4. `uv run pytest courses/tests integrations notifications`

Then reconcile against the real list of test directories: `find . -name 'test_*.py' -not -path './docs/*' -not -path './.venv/*' -not -path './node_modules/*' | xargs -n1 dirname | sort -u`. Every directory printed must be covered by a chunk (a `tests/test_*` glob covers `./tests`); add any missing one to chunk 4. The chunk pass/skip counts should sum to the non-e2e part of the collected total.

Then the e2e files this branch can affect (the paint selector, the inline CSS next to the min-width floor, the editor submit guard and the hint placed after the grid): `uv run pytest tests/test_e2e_filltable*.py tests/test_e2e_table_editor.py tests/test_e2e_spanning_roundtrip.py tests/test_e2e_spanning_merge.py tests/test_e2e_table_cell_images.py tests/test_e2e_editor_scroll_containment.py -m e2e -v`. Any failure outside the files this branch touched: A/B it against `origin/master` before blaming the diff.

- [ ] **Step 3: Check nobody else has taken FORMAT_VERSION 16**

Master first — an identical `15 → 16` edit on both sides merges with NO conflict, giving two different formats both called 16:

```bash
git fetch origin
git show origin/master:courses/transfer/schema.py | grep '^FORMAT_VERSION'
```
Expected: `FORMAT_VERSION = 15`. If it shows 16 or more, STOP: bump this branch to master's value + 1, update the eight pinned tests to match (Task 7 Step 4's list), re-run Task 7 Step 5, and tell the owner.

Then open PRs:

```bash
gh pr list --state open --json number,headRefName --jq '.[].headRefName' | while read b; do git fetch -q origin "$b" && git grep -n "^FORMAT_VERSION" "origin/$b" -- courses/transfer/schema.py; done
```
Expected: every open branch shows 15 (or none). If another shows 16, stop and tell the owner — two identical bumps merge silently.

- [ ] **Step 4: Pre-merge prod audit (spec §10) — REQUIRES PROD ACCESS; ask the owner if you have none**

Save as `audit_filltable.py` locally (read-only):

```python
import re
from courses.models import FillTableElement

MATH = re.compile(r"\\\(.*?\\\)|\\\[.*?\\\]", re.S)
DOLLARS = re.compile(r"\$\$.*?\$\$", re.S)
hits = []
for el in FillTableElement.objects.all().only("pk", "data"):
    for r, row in enumerate((el.data or {}).get("cells") or []):
        for c, cell in enumerate(row if isinstance(row, list) else []):
            if not isinstance(cell, dict) or cell.get("kind") in ("answer", "image"):
                continue
            h = cell.get("html") or ""
            if not isinstance(h, str):
                continue
            masked = MATH.sub("", h)
            if "\uffff" in h or "{{" in masked or "}}" in masked or any(
                "{{" in m for m in DOLLARS.findall(h)
            ):
                hits.append((el.pk, r, c, h[:80]))
print(len(hits))
for h in hits:
    print(h)
```

Run on prod: `ssh root@<ip> 'cd /opt/libli && bash manage.sh shell' < audit_filltable.py`.
Record the count and ids in the PR description. **Zero → proceed. Any hit → STOP and bring the list to the owner before merging; do not decide.**

- [ ] **Step 5: PR**

Push and open the PR. Description: what authors can now type (with the π example), the spec link, the audit result, the Polish strings flagged for owner wording review (Task 9), FORMAT_VERSION 16, and that no live content changes until an author edits a cell. End with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
