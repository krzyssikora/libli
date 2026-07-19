# Matematyka Content Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Populate the local "matematyka" course from the LAL static-HTML corpus (21 parts, 702 lessons, 95 quizzes) using native libli elements, via a deterministic HTML→JSON parser and an idempotent Django loader command.

**Architecture:** Two decoupled stages. A **pure-Python parser** (`scripts/lal_import/`, BeautifulSoup) walks each source folder and emits, per part, a `manifest.json` (tree + human-editable names), one JSON file per unit (ordered element dicts), and a `flags.json` (unmapped-pattern worklist). A **Django management command** (`import_lal_content`) reads those artifacts and writes the `ContentNode` tree + concrete `Element`s idempotently, keyed on tree position. The intermediate JSON is the editable source of truth after a one-time seed; the loader is always re-runnable.

**Tech Stack:** Python 3, Django, BeautifulSoup4 (new dep), nh3 (existing sanitizer), pytest + factory_boy, `uv` for tooling.

## Global Constraints

Every task's requirements implicitly include this section. Values are copied verbatim from the spec (`docs/superpowers/specs/2026-07-19-matematyka-content-import-design.md`).

- **Zero `HtmlElement` is the goal.** An unmapped fragment is emitted as `{"type":"html","flagged":true,"raw":…,"reason":…}` AND logged to `flags.json`; the loader refuses to write it unless `--allow-html` is passed. Never ship an HTML blob silently.
- **Math delimiters are unchanged** — `\( … \)` inline, `\[ … \]` display (libli's KaTeX uses the same delimiters). **But** `<`/`>` inside any `\(…\)` or `\[…\]` span MUST be entity-escaped (`<`→`&lt;`, `>`→`&gt;`). **Ordering is critical: the escape MUST run on the RAW HTML string BEFORE constructing the `BeautifulSoup` object** — `html.parser` tokenizes a literal `<` inside `\(y<z\)` as a stray start-tag and irreversibly mangles the DOM, so escaping `str(node)` afterwards is too late. Every parser entry point that builds a soup (`parse_lesson`, `parse_quiz`) escapes its `html` argument as its first statement; downstream functions (`table_element`, and all `str(node)` extraction) then see already-escaped markup and MUST NOT re-escape (escaping is idempotent on already-`&lt;` content, but the invariant is "escape once, at the raw boundary"). Fields that end up sanitized by nh3 (and rendered `|safe`): `TextElement.body`, `SpoilerElement.body`, table cell `html`, `QuestionElement.stem` — these must hold the **escaped entity** `\(y&lt;z\)`. NOT sanitized: `MathElement.latex` (raw LaTeX), and `Choice.text`/`Choice.feedback`, which the choice templates render **autoescaped** (`{{ c.text }}`, no `|safe`) — these must hold the **literal** `\(y<z\)` so Django's autoescape produces the single correct `\(y&lt;z\)`. This falls out of bs4 automatically: a stem comes from `str(Tag)`, which **re-escapes** to `\(y&lt;z\)`; a choice option comes from a bare-text `str(NavigableString)`, which **decodes** back to literal `\(y<z\)`. So the one pre-escape at the raw boundary yields the right stored form for *both* field classes — no per-field unescape is needed. (Locked by tests in Tasks 8 and 14.)
- **File ordering:** integer value of the *first maximal run of digits* in the filename, ascending; tie-break lexicographic on the full filename. Duplicate token → deterministic tie-break + a `flags.json` warning.
- **Node identity is positional at every level** including Part: Part = `(course, part.order)` where `part.order` = folder index in the sorted 3-digit-folder list; chapter/unit = `(parent, order)`. `title`/`kind`/`unit_type` updated in place. No new `ContentNode` field.
- **Elements are rebuilt, not upserted:** on each load the loader deletes a unit's existing `Element`s + concrete rows, then recreates from JSON in array order (`Element.order` is an auto-assigning `OrderField(for_fields=["unit"])`).
- **Media deduped by content hash:** add a nullable indexed `MediaAsset.content_hash` (SHA-256 hex). Loader queries `(course, content_hash)` before creating. Element→`MediaAsset` FK is `on_delete=PROTECT`, so an element rebuild never deletes a shared asset.
- **Output dir:** `scripts/lal_import/out/<source_folder>/` (`--json-dir` overrides the `out/` root). **`--source-root` is strictly required** (no baked default) on both parser and loader; assets resolve as `<source-root>/<source_dir>/<media_src>`.
- **`seed_hash`** = SHA-256 of a canonical JSON serialization of the unit payload with the `seed_hash` and `fully_mapped` keys **excluded** (`json.dumps(..., sort_keys=True, separators=(",", ":"))`). Only the parser stamps `seed_hash`; AI/hand fixups mutate payload only.
- **Loader flags:** `--course <slug>` (default `matematyka`), `--part`, `--json-dir`, `--source-root`, `--allow-html`, `--gc-media`, `--set-policy`. **Parser flags:** `--source-root`, `--refresh-unmapped`, `--refresh-elements`, `--force`.
- **Model field ceilings:** `Choice.text`/`Choice.feedback` `max_length=500`; `TableElement.MAX_ROWS=50`, `MAX_COLS=20`.
- **Embed allowlist:** add the edpuzzle and Lumi hostnames to `ALLOWED_EMBED_DOMAINS`; loader asserts every iframe host is allowlisted before writing.
- **Depth policy:** loader verifies (and with `--set-policy` sets) `uses_parts=True`, `uses_chapters=True`; `uses_sections` left off.
- **Choice widget:** `[ ]`/`[x]` = checkbox → `multiple=True`; `( )`/`(x)` = radio → `multiple=False` (from bracket shape, never correct-count).
- **Tooling:** run tests with `uv run pytest`; format-check with `uv run ruff format --check`. Parser tests are pure-Python (no DB); loader tests need the DB (unique `DATABASE_URL` per worktree — see the test-DB-contention note).

## File Structure

**Parser (pure Python, no Django import):**
- `scripts/lal_import/__init__.py` — package marker
- `scripts/lal_import/ordering.py` — filename ordering token + sort + duplicate detection
- `scripts/lal_import/grouping.py` — group ordered files into chapters (quiz-terminated + trailing)
- `scripts/lal_import/naming.py` — de-slug/diacritic-placeholder titles (part / lesson / quiz)
- `scripts/lal_import/mathsafe.py` — escape `<`/`>` inside math spans
- `scripts/lal_import/numbers.py` — detect/normalize a numeric answer token
- `scripts/lal_import/lesson.py` — lesson DOM → ordered element dicts
- `scripts/lal_import/tables.py` — `<table>` → table element dict (rectangular/headers/flags)
- `scripts/lal_import/quiz.py` — quiz DSL → question element dicts (+ segmentation)
- `scripts/lal_import/emit.py` — `seed_hash` canonical form + write unit/manifest/flags
- `scripts/lal_import/parser.py` — argparse CLI + re-parse guards (`--refresh-*`/`--force`)

**Model + settings:**
- `courses/models.py` — add `MediaAsset.content_hash`
- `courses/migrations/00NN_mediaasset_content_hash.py` — migration
- `config/settings/base.py` — add edpuzzle/Lumi to `ALLOWED_EMBED_DOMAINS`

**Loader (Django):**
- `courses/lal_loader/__init__.py`
- `courses/lal_loader/media.py` — source resolution + content-hash dedup + asset create
- `courses/lal_loader/builders.py` — element dict → concrete element object
- `courses/lal_loader/guards.py` — course resolution, depth policy, owned-set collision, iframe allowlist
- `courses/lal_loader/tree.py` — positional node upsert + orphan prune + element rebuild
- `courses/management/commands/import_lal_content.py` — command wiring

**Tests:**
- `tests/lal_import/test_ordering.py`, `test_grouping.py`, `test_naming.py`, `test_mathsafe.py`, `test_numbers.py`, `test_lesson.py`, `test_tables.py`, `test_quiz.py`, `test_emit.py`, `test_parser_cli.py`
- `tests/test_import_lal_content.py` — loader command (DB)
- `tests/test_lal_loader_units.py` — media/builders/tree/guards unit tests (DB)

---

## Task 1: Parser package scaffolding + filename ordering

**Files:**
- Create: `scripts/lal_import/__init__.py`, `scripts/lal_import/ordering.py`
- Create: `tests/lal_import/__init__.py`, `tests/lal_import/test_ordering.py`
- Modify: `pyproject.toml` (add `beautifulsoup4` dependency)

**Interfaces:**
- Produces: `ordering_token(filename: str) -> int` (raises `ValueError` if no digit run); `sort_key(filename: str) -> tuple[int, str]`; `ordered_html_files(names: list[str]) -> list[str]`; `duplicate_token_warnings(names: list[str]) -> list[dict]` (each `{"kind":"duplicate_ordering_token","reason":str,"names":list[str]}`).

- [ ] **Step 1: Add the BeautifulSoup dependency**

In `pyproject.toml`, add to the `dependencies` list (next to `"nh3>=0.3.5",`):

```toml
    "beautifulsoup4>=4.12",
```

Then run `uv sync` and confirm it installs.

- [ ] **Step 2: Write the failing test**

`tests/lal_import/test_ordering.py`:

```python
import pytest
from scripts.lal_import.ordering import (
    ordering_token, ordered_html_files, duplicate_token_warnings,
)

def test_token_leading_digits():
    assert ordering_token("005_zbiory.html") == 5

def test_token_after_alpha_prefix():
    assert ordering_token("wyr_alg_010_potegi.html") == 10
    assert ordering_token("f_lin_020_x.html") == 20

def test_token_missing_raises():
    with pytest.raises(ValueError):
        ordering_token("neolms.html")

def test_order_is_numeric_not_lexicographic():
    names = ["100_a.html", "020_b.html", "005_c.html"]
    assert ordered_html_files(names) == ["005_c.html", "020_b.html", "100_a.html"]

def test_duplicate_token_warns_but_still_orders():
    names = ["010_a.html", "010_b.html"]
    assert ordered_html_files(names) == ["010_a.html", "010_b.html"]
    warns = duplicate_token_warnings(names)
    assert len(warns) == 1
    assert warns[0]["kind"] == "duplicate_ordering_token"
    assert set(warns[0]["names"]) == {"010_a.html", "010_b.html"}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/lal_import/test_ordering.py -q`
Expected: FAIL — `ModuleNotFoundError: scripts.lal_import.ordering`.

- [ ] **Step 4: Write the implementation**

`scripts/lal_import/__init__.py`: empty file.
`tests/lal_import/__init__.py`: empty file.
`scripts/lal_import/ordering.py`:

```python
"""Deterministic ordering of a part folder's .html files by their numeric token."""

import re
from collections import defaultdict

_DIGITS = re.compile(r"\d+")


def ordering_token(filename):
    """Integer value of the first maximal run of digits in the filename.

    Raises ValueError when the filename has no digit run (the parser fails loud
    rather than ordering silently wrong).
    """
    m = _DIGITS.search(filename)
    if m is None:
        raise ValueError(f"no ordering token (digit run) in filename: {filename!r}")
    return int(m.group())


def sort_key(filename):
    """(token, filename): numeric primary key, lexicographic tie-break."""
    return (ordering_token(filename), filename)


def ordered_html_files(names):
    return sorted(names, key=sort_key)


def duplicate_token_warnings(names):
    """One warning record per set of files sharing an ordering token."""
    by_token = defaultdict(list)
    for n in names:
        by_token[ordering_token(n)].append(n)
    out = []
    for token, group in by_token.items():
        if len(group) > 1:
            out.append({
                "kind": "duplicate_ordering_token",
                "reason": f"{len(group)} files share ordering token {token}",
                "names": sorted(group),
            })
    return out
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/lal_import/test_ordering.py -q`
Expected: PASS (5 passed).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock scripts/lal_import tests/lal_import
git commit -m "feat(lal-import): filename ordering token + bs4 dep"
```

---

## Task 2: Chapter grouping

**Files:**
- Create: `scripts/lal_import/grouping.py`
- Test: `tests/lal_import/test_grouping.py`

**Interfaces:**
- Consumes: `ordered_html_files` (Task 1).
- Produces: `group_into_chapters(ordered_names: list[str]) -> list[dict]`. Each chapter dict: `{"units": [{"source_html": str, "unit_type": "lesson"|"quiz"}], "ends_with_quiz": bool}`. A `*_quiz.html` closes the current chapter (inclusive). Files after the final quiz form a trailing quiz-less chapter (`ends_with_quiz=False`). `is_quiz(name)` helper: name stem ends with `_quiz`.

- [ ] **Step 1: Write the failing test**

`tests/lal_import/test_grouping.py`:

```python
from scripts.lal_import.grouping import group_into_chapters, is_quiz

def test_is_quiz():
    assert is_quiz("039_zbiory_quiz.html")
    assert not is_quiz("010_zbiory.html")

def test_quiz_closes_chapter():
    names = ["005_a.html", "010_b.html", "039_c_quiz.html", "040_d.html", "074_e_quiz.html"]
    chapters = group_into_chapters(names)
    assert len(chapters) == 2
    assert [u["source_html"] for u in chapters[0]["units"]] == ["005_a.html", "010_b.html", "039_c_quiz.html"]
    assert chapters[0]["ends_with_quiz"] is True
    assert chapters[0]["units"][-1]["unit_type"] == "quiz"
    assert chapters[0]["units"][0]["unit_type"] == "lesson"

def test_trailing_lessons_form_quizless_chapter():
    names = ["005_a.html", "039_a_quiz.html", "300_podsumowanie.html"]
    chapters = group_into_chapters(names)
    assert len(chapters) == 2
    assert chapters[1]["ends_with_quiz"] is False
    assert [u["source_html"] for u in chapters[1]["units"]] == ["300_podsumowanie.html"]

def test_single_lesson_no_quiz():
    chapters = group_into_chapters(["010_only.html"])
    assert len(chapters) == 1
    assert chapters[0]["ends_with_quiz"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/lal_import/test_grouping.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

`scripts/lal_import/grouping.py`:

```python
"""Group a part's ordered .html files into chapters terminated by a *_quiz.html."""


def is_quiz(name):
    stem = name[:-5] if name.endswith(".html") else name
    return stem.endswith("_quiz")


def group_into_chapters(ordered_names):
    chapters = []
    current = []
    for name in ordered_names:
        unit_type = "quiz" if is_quiz(name) else "lesson"
        current.append({"source_html": name, "unit_type": unit_type})
        if unit_type == "quiz":
            chapters.append({"units": current, "ends_with_quiz": True})
            current = []
    if current:  # trailing lessons after the last quiz (or a quiz-less part)
        chapters.append({"units": current, "ends_with_quiz": False})
    return chapters
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/lal_import/test_grouping.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/lal_import/grouping.py tests/lal_import/test_grouping.py
git commit -m "feat(lal-import): chapter grouping by quiz boundary"
```

---

## Task 3: Title de-slugging (part / lesson / quiz)

**Files:**
- Create: `scripts/lal_import/naming.py`
- Test: `tests/lal_import/test_naming.py`

**Interfaces:**
- Produces: `deslug(stem: str) -> str` (strip leading digit token + alpha prefix noise → spaces, ASCII-folded placeholder — NO diacritic guessing); `part_title_placeholder(folder: str) -> str`; `lesson_title(soup, source_html: str) -> str` (first `<h2>` text, else `deslug`); `quiz_title(source_html: str) -> str` (always `deslug`, never `<h2>`).
- Consumes: a `BeautifulSoup` object for `lesson_title`.

- [ ] **Step 1: Write the failing test**

`tests/lal_import/test_naming.py`:

```python
from bs4 import BeautifulSoup
from scripts.lal_import.naming import (
    deslug, part_title_placeholder, lesson_title, quiz_title,
)

def test_part_placeholder_is_ascii_folded_no_diacritics():
    # Parser emits the ASCII placeholder; diacritics are restored by hand in Phase 1.
    assert part_title_placeholder("005_wyrazenia_algebraiczne") == "wyrazenia algebraiczne"
    assert part_title_placeholder("001_zbiory_liczbowe") == "zbiory liczbowe"

def test_lesson_title_from_first_h2():
    soup = BeautifulSoup("<h2>Zbiory - pojęcia podstawowe</h2><p>x</p>", "html.parser")
    assert lesson_title(soup, "005_zbiory.html") == "Zbiory - pojęcia podstawowe"

def test_lesson_title_falls_back_to_filename():
    soup = BeautifulSoup("<p>no heading</p>", "html.parser")
    assert lesson_title(soup, "060_liczby_r.html") == "liczby r"

def test_quiz_title_ignores_any_h2():
    assert quiz_title("039_zbiory_quiz.html") == "zbiory quiz"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/lal_import/test_naming.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

`scripts/lal_import/naming.py`:

```python
"""Human-facing title placeholders derived from filenames/headings.

Diacritics are NOT guessed here — the parser emits an ASCII-folded placeholder and
the Phase-1 reading pass restores Polish diacritics in the manifest by hand.
"""

import re

_LEADING_TOKEN = re.compile(r"^\d+[_-]?")


def deslug(stem):
    """Strip a leading numeric token, then turn separators into spaces."""
    stem = _LEADING_TOKEN.sub("", stem)
    return re.sub(r"[_-]+", " ", stem).strip()


def _stem(source_html):
    return source_html[:-5] if source_html.endswith(".html") else source_html


def part_title_placeholder(folder):
    return deslug(folder)


def lesson_title(soup, source_html):
    h2 = soup.find("h2")
    if h2 is not None and h2.get_text(strip=True):
        return h2.get_text(strip=True)
    return deslug(_stem(source_html))


def quiz_title(source_html):
    return deslug(_stem(source_html))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/lal_import/test_naming.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/lal_import/naming.py tests/lal_import/test_naming.py
git commit -m "feat(lal-import): title de-slugging for part/lesson/quiz"
```

---

## Task 4: Math `<`/`>` escaping

**Files:**
- Create: `scripts/lal_import/mathsafe.py`
- Test: `tests/lal_import/test_mathsafe.py`

**Interfaces:**
- Produces: `escape_math_delimited(text: str) -> str` — within every `\(…\)` and `\[…\]` span, replace `<`→`&lt;` and `>`→`&gt;`; leave text outside spans untouched.

- [ ] **Step 1: Write the failing test**

`tests/lal_import/test_mathsafe.py`:

```python
from scripts.lal_import.mathsafe import escape_math_delimited

def test_escapes_inside_inline_span():
    assert escape_math_delimited(r"gdy \(y<z\) koniec") == r"gdy \(y&lt;z\) koniec"

def test_escapes_inside_display_span():
    assert escape_math_delimited(r"\[a<b>c\]") == r"\[a&lt;b&gt;c\]"

def test_leaves_text_outside_spans_untouched():
    # A real HTML tag outside math must survive verbatim.
    assert escape_math_delimited(r"<p>x</p> \(a<b\)") == r"<p>x</p> \(a&lt;b\)"

def test_no_math_is_identity():
    assert escape_math_delimited("<strong>plain</strong>") == "<strong>plain</strong>"

def test_survives_nh3_roundtrip():
    import nh3
    body = escape_math_delimited(r"<p>gdy \(y<z\) tak</p>")
    cleaned = nh3.clean(body)
    assert r"\(y&lt;z\)" in cleaned  # the whole span survives sanitization

def test_escape_before_bs4_yields_wellformed_dom():
    # THE ordering guarantee (see Global Constraints): escaping the RAW string
    # first lets BeautifulSoup build a correct DOM. Escaping AFTER BS4 cannot —
    # this test locks in the escape-then-parse order the parser tasks rely on.
    from bs4 import BeautifulSoup
    raw = r"<p>gdy \(y<z\) tak</p>"
    good = BeautifulSoup(escape_math_delimited(raw), "html.parser")
    assert good.p is not None and good.p.get_text() == r"gdy \(y&lt;z\) tak"
    # And the broken order mangles it (documents WHY the order matters):
    bad = BeautifulSoup(raw, "html.parser")
    assert bad.get_text() != r"gdy \(y&lt;z\) tak"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/lal_import/test_mathsafe.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

`scripts/lal_import/mathsafe.py`:

```python
"""Escape <,> inside \\(...\\) and \\[...\\] math spans so nh3 doesn't eat them.

nh3 is an HTML parser; a fragment like \\(y<z\\) reads as a stray tag and is
deleted. Escaping to entities inside math spans keeps the span intact through
sanitization; the browser decodes the entities and KaTeX typesets correctly.
"""

import re

# Non-greedy match of \( ... \) or \[ ... \]; DOTALL so multi-line display math works.
_MATH_SPAN = re.compile(r"\\\((.*?)\\\)|\\\[(.*?)\\\]", re.DOTALL)


def _escape(s):
    return s.replace("<", "&lt;").replace(">", "&gt;")


def escape_math_delimited(text):
    def repl(m):
        if m.group(1) is not None:
            return r"\(" + _escape(m.group(1)) + r"\)"
        return r"\[" + _escape(m.group(2)) + r"\]"

    return _MATH_SPAN.sub(repl, text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/lal_import/test_mathsafe.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/lal_import/mathsafe.py tests/lal_import/test_mathsafe.py
git commit -m "feat(lal-import): escape <,> inside math spans for nh3 safety"
```

---

## Task 5: Numeric answer detection

**Files:**
- Create: `scripts/lal_import/numbers.py`
- Test: `tests/lal_import/test_numbers.py`

**Interfaces:**
- Produces: `normalize_numeric(token: str) -> str | None` — returns a canonical decimal string (`,`→`.`) if the token is a single number, else `None`. Mirrors `courses.marking.parse_number`'s acceptance (single `.` or `,`; no thousands separators; no internal whitespace) but stays pure-Python (no Django import).

- [ ] **Step 1: Write the failing test**

`tests/lal_import/test_numbers.py`:

```python
from scripts.lal_import.numbers import normalize_numeric

def test_integer():
    assert normalize_numeric("2") == "2"

def test_polish_comma_becomes_dot():
    assert normalize_numeric("2,5") == "2.5"

def test_negative_and_dot():
    assert normalize_numeric("-3.14") == "-3.14"

def test_text_is_not_numeric():
    assert normalize_numeric("dwa") is None
    assert normalize_numeric("1/2") is None  # fraction is not a plain number token

def test_internal_space_rejected():
    assert normalize_numeric("1 000") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/lal_import/test_numbers.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

`scripts/lal_import/numbers.py`:

```python
"""Pure-Python numeric-token detector matching courses.marking.parse_number rules."""

import re

_NUM_RE = re.compile(r"^[+-]?\d+([.,]\d+)?$")


def normalize_numeric(token):
    """Canonical decimal string if `token` is a single number, else None."""
    token = (token or "").strip()
    if not _NUM_RE.match(token):
        return None
    return token.replace(",", ".")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/lal_import/test_numbers.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/lal_import/numbers.py tests/lal_import/test_numbers.py
git commit -m "feat(lal-import): numeric answer token detection"
```

---

## Task 6: Lesson element mapping (text/math/video/image/iframe/spoiler)

**Files:**
- Create: `scripts/lal_import/lesson.py`
- Test: `tests/lal_import/test_lesson.py`

**Interfaces:**
- Consumes: `escape_math_delimited` (Task 4); `table_element` (Task 7, imported lazily — implement the `<table>` branch to call it, and Task 7 lands the function; until then that branch is covered by Task 7's tests).
- Produces: `parse_lesson(html: str, source_html: str) -> tuple[list[dict], list[dict]]` returning `(elements, flags)`. Element dicts follow the schema below. The first `<h2>` (the unit title) is skipped, not emitted. Each **flag record** is `{"kind": str, "reason": str, "raw_excerpt": str}`; `seed_part` (Task 10) later stamps the owning `"unit_json"` onto each record before writing `flags.json`.

**Note on element dict schemas (authoritative — the JSON-key → model-field table):**
```
{"type":"text","body": <sanitized-ready html, math-escaped>}
{"type":"math","latex": <raw tex, NO escaping>}
{"type":"video","media_src": <path relative to source .html dir>}
{"type":"image","media_src": <path>, "alt": <str>, "figcaption": <str>}
{"type":"iframe","url": <str>, "title": <str>}
{"type":"spoiler","label": <str>, "body": <html, math-escaped>}
{"type":"table", ...}                         # Task 7
{"type":"html","flagged":true,"raw": <html>, "reason": <str>}   # unmapped
```

- [ ] **Step 1: Write the failing test**

`tests/lal_import/test_lesson.py`:

```python
from scripts.lal_import.lesson import parse_lesson

VIDEO_LESSON = """
<h2>Zbiory - pojęcia podstawowe</h2>
<p>Obejrzyj nagrania.</p>
<h3>Sekcja</h3>
<figure><video controls><source src="static/zbiory.mp4" type="video/mp4"/></video></figure>
"""

def test_h2_title_is_skipped_and_paragraph_kept():
    elements, flags = parse_lesson(VIDEO_LESSON, "005_zbiory.html")
    types = [e["type"] for e in elements]
    assert "video" in types
    # The <h2> is the unit title, not body; the <h3> + <p> survive as text.
    text_bodies = " ".join(e["body"] for e in elements if e["type"] == "text")
    assert "Zbiory - pojęcia podstawowe" not in text_bodies
    assert "Obejrzyj nagrania." in text_bodies

def test_video_media_src_extracted():
    elements, _ = parse_lesson(VIDEO_LESSON, "005_zbiory.html")
    vid = next(e for e in elements if e["type"] == "video")
    assert vid["media_src"] == "static/zbiory.mp4"

def test_inline_math_is_escaped_and_body_wellformed():
    # Exact-equality (not substring): a substring check would pass on corrupted
    # output. The <p> must be intact and the math span escaped.
    elements, _ = parse_lesson(r"<p>gdy \(y<z\)</p>", "x.html")
    body = next(e["body"] for e in elements if e["type"] == "text")
    assert body == r"<p>gdy \(y&lt;z\)</p>"

def test_second_h2_becomes_text_not_flag():
    # Only the FIRST <h2> is the unit title; later ones are body headings (spec §5).
    elements, flags = parse_lesson("<h2>Title</h2><p>a</p><h2>Sekcja 2</h2>", "x.html")
    text = " ".join(e["body"] for e in elements if e["type"] == "text")
    assert "Sekcja 2" in text
    assert "Title" not in text
    assert flags == []

def test_spoiler_from_show_solution():
    html = (
        '<div class="show_solution ks_button">zobacz</div>'
        '<div class="question_solution hidden">Zbiór pusty \\(\\emptyset\\).</div>'
    )
    elements, flags = parse_lesson(html, "x.html")
    sp = next(e for e in elements if e["type"] == "spoiler")
    assert sp["label"] == "zobacz"
    assert "emptyset" in sp["body"]
    # The consumed solution div must NOT be re-emitted as an "unmapped div" flag.
    assert flags == []

def test_image_with_figcaption():
    html = '<figure><img src="static/wykres.png" alt="wykres"/><figcaption>Rys 1</figcaption></figure>'
    elements, _ = parse_lesson(html, "x.html")
    img = next(e for e in elements if e["type"] == "image")
    assert img["media_src"] == "static/wykres.png"
    assert img["alt"] == "wykres"
    assert img["figcaption"] == "Rys 1"

def test_iframe_url_kept():
    html = '<iframe src="https://www.geogebra.org/material/iframe/id/abc"></iframe>'
    elements, _ = parse_lesson(html, "x.html")
    frame = next(e for e in elements if e["type"] == "iframe")
    assert "geogebra.org" in frame["url"]

def test_sole_block_display_math_becomes_mathelement():
    elements, _ = parse_lesson(r"<p>\[a<b\]</p>", "x.html")
    assert elements[0]["type"] == "math"
    assert elements[0]["latex"] == r"a<b"          # literal, for [data-katex]

def test_mid_paragraph_display_math_stays_text():
    elements, _ = parse_lesson(r"<p>Wynik: \[x\] gotowe</p>", "x.html")
    assert elements[0]["type"] == "text"           # not a sole \[...\] block

def test_relative_href_is_flagged():
    elements, flags = parse_lesson('<p>zob. <a href="040_x.html">tu</a></p>', "x.html")
    assert any(f["kind"] == "relative_href" for f in flags)
    assert elements[0]["type"] == "text"           # text still emitted (warning only)

def test_absolute_href_not_flagged():
    _, flags = parse_lesson('<p><a href="https://x.example">t</a></p>', "x.html")
    assert not any(f["kind"] == "relative_href" for f in flags)

def test_html_comment_is_ignored():
    elements, flags = parse_lesson("<!-- editor note --><p>a</p>", "x.html")
    assert flags == []
    assert [e["type"] for e in elements] == ["text"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/lal_import/test_lesson.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

`scripts/lal_import/lesson.py`:

```python
"""Walk a lesson's DOM top-to-bottom, emitting ordered libli element dicts.

The stub HTML head (bootstrap link, script tags, MathJax/H5P resizer) is ignored;
only body-level content elements map. Anything unrecognized is flagged, never
silently dropped.
"""

import re

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from scripts.lal_import.mathsafe import escape_math_delimited

# Tags whose inner HTML is valid TextElement body content (survive nh3). h2 is
# included: the FIRST h2 is consumed as the unit title, later ones are body.
_TEXT_TAGS = {"h2", "h3", "h4", "p", "ul", "ol", "blockquote", "pre"}
_INLINE_TAGS = {"strong", "em", "b", "i", "u", "code", "a"}
_IGNORE_TAGS = {"script", "link", "style"}
_OK_SCHEMES = {"http", "https", "mailto"}
# A block whose entire content is one \[...\] display span -> MathElement.
_DISPLAY_MATH = re.compile(r"^\\\[(.*)\\\]$", re.DOTALL)


def _flag(reason, node):
    return {"kind": "unmapped_pattern", "reason": reason,
            "raw_excerpt": str(node)[:300]}


def _sole_block_math_latex(node):
    """If node's whole content is a single \\[...\\] display span (no child tags),
    return the inner LaTeX. get_text() decodes entities, so `<` comes back literal —
    exactly what the autoescaped [data-katex] MathElement template needs."""
    if node.name not in {"p", "div"} or node.find(True) is not None:
        return None
    m = _DISPLAY_MATH.match(node.get_text().strip())
    return m.group(1) if m else None


def _flag_relative_hrefs(node, flags):
    """nh3 drops non-http/https/mailto <a href> silently; flag them (spec §5)."""
    anchors = ([node] if getattr(node, "name", None) == "a" else []) + \
        (node.find_all("a", href=True) if isinstance(node, Tag) else [])
    for a in anchors:
        href = a.get("href", "")
        scheme = href.split(":", 1)[0].lower() if ":" in href else ""
        if scheme not in _OK_SCHEMES:
            flags.append({"kind": "relative_href",
                          "reason": f"relative/local <a href> dropped by nh3: {href}",
                          "raw_excerpt": str(a)[:300]})


def _unmapped(reason, node, elements, flags):
    """Content-loss: emit a flagged html ELEMENT (so the loader gate fails loud)
    AND a flag record (spec §4.1 / I5) — never a flag record alone."""
    elements.append({"type": "html", "flagged": True, "raw": str(node),
                     "reason": reason})
    flags.append(_flag(reason, node))


def _is_show_solution_button(node):
    return (isinstance(node, Tag) and node.name == "div"
            and "show_solution" in (node.get("class") or []))


def parse_lesson(html, source_html):
    # Escape math <,> on the RAW string BEFORE parsing (Global Constraints / C1),
    # so BeautifulSoup builds a correct DOM. Never re-escape below.
    soup = BeautifulSoup(escape_math_delimited(html), "html.parser")
    root = soup.body or soup
    elements, flags = [], []
    h2_skipped = False
    children = list(root.children)
    consumed = set()  # ids of nodes already folded into a Spoiler (I2)
    for i, node in enumerate(children):
        if id(node) in consumed:
            continue
        if isinstance(node, Comment):
            continue  # HTML comments carry no content (Comment ⊂ NavigableString)
        if isinstance(node, NavigableString):
            if node.strip():
                _unmapped("bare text node in lesson body", node, elements, flags)
            continue
        if not isinstance(node, Tag) or node.name in _IGNORE_TAGS:
            continue
        name = node.name

        if name == "h2" and not h2_skipped:
            h2_skipped = True  # first <h2> is the unit title, not body
            continue

        if name in _TEXT_TAGS or name in _INLINE_TAGS:
            latex = _sole_block_math_latex(node)
            if latex is not None:
                elements.append({"type": "math", "latex": latex})  # display math
            else:
                _flag_relative_hrefs(node, flags)  # warn on nh3-dropped hrefs (I2)
                elements.append({"type": "text", "body": str(node)})  # already escaped
            continue

        if name == "figure":
            _emit_figure(node, elements, flags)
            continue
        if name == "video":
            _emit_video(node, elements, flags)
            continue
        if name == "img":
            elements.append(_image_dict(node))
            continue
        if name == "iframe":
            src = node.get("src", "")
            elements.append({"type": "iframe", "url": src, "title": node.get("title", "")})
            continue
        if _is_show_solution_button(node):
            sol = _next_solution(children, i + 1)
            if sol is not None:
                consumed.add(id(sol))  # so the loop does not re-flag it (I2)
                elements.append({
                    "type": "spoiler",
                    "label": node.get_text(strip=True) or "zobacz",
                    "body": "".join(str(c) for c in sol.children),  # already escaped
                })
                continue
            _unmapped("show_solution button without solution", node, elements, flags)
            continue
        if name == "table":
            from scripts.lal_import.tables import table_element
            el, tflags = table_element(node)
            elements.append(el)
            flags.extend(tflags)
            continue

        _unmapped(f"unmapped <{name}> in lesson body", node, elements, flags)
    return elements, flags


def _next_solution(children, start):
    for j in range(start, len(children)):
        n = children[j]
        if isinstance(n, Tag) and "question_solution" in (n.get("class") or []):
            return n
    return None


def _image_dict(img):
    return {"type": "image", "media_src": img.get("src", ""),
            "alt": img.get("alt", ""), "figcaption": ""}


def _emit_figure(fig, elements, flags):
    video = fig.find("video")
    img = fig.find("img")
    cap = fig.find("figcaption")
    caption = cap.get_text(strip=True) if cap else ""
    if video is not None:
        _emit_video(video, elements, flags)
    elif img is not None:
        d = _image_dict(img)
        d["figcaption"] = caption
        elements.append(d)
    else:
        _unmapped("figure without video or img", fig, elements, flags)


def _emit_video(video, elements, flags):
    source = video.find("source")
    src = (source.get("src") if source else "") or video.get("src", "")
    if not src:
        _unmapped("video without a source src", video, elements, flags)
        return
    elements.append({"type": "video", "media_src": src})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/lal_import/test_lesson.py -q`
Expected: PASS. (The `<table>` branch imports Task 7; these tests exercise no table, so the lazy import is not hit.)

- [ ] **Step 5: Commit**

```bash
git add scripts/lal_import/lesson.py tests/lal_import/test_lesson.py
git commit -m "feat(lal-import): lesson DOM to element dicts (text/media/spoiler)"
```

---

## Task 7: Table element mapping

**Files:**
- Create: `scripts/lal_import/tables.py`
- Test: `tests/lal_import/test_tables.py`

**Interfaces:**
- Consumes: nothing from other tasks. **Its `table_tag` argument comes from an already-math-escaped soup** (its only caller, `parse_lesson`, escaped the raw HTML before parsing), so `table_element` does NOT escape — cell `<`/`>` inside math are already entities.
- Produces: `table_element(table_tag) -> tuple[dict, list[dict]]`. On a clean rectangle returns `({"type":"table","data": {...}}, [])` with `data` matching `TableElement.normalize_data`'s shape (`header_row`, `header_col`, `border`, `cells`). On spans/nested/ragged returns a flagged `{"type":"html","flagged":True,...}` dict plus a flag record.

- [ ] **Step 1: Write the failing test**

`tests/lal_import/test_tables.py`:

```python
from bs4 import BeautifulSoup
from scripts.lal_import.tables import table_element

def _t(html):
    return BeautifulSoup(html, "html.parser").find("table")

def test_rectangular_table_maps_to_grid():
    el, flags = table_element(_t(
        "<table><tr><td>a</td><td>b</td></tr><tr><td>c</td><td>d</td></tr></table>"
    ))
    assert el["type"] == "table"
    assert flags == []
    cells = el["data"]["cells"]
    assert cells[0][0]["html"] == "a"
    assert cells[1][1]["html"] == "d"
    assert el["data"]["header_row"] is False

def test_th_first_row_marks_header_row():
    el, _ = table_element(_t(
        "<table><tr><th>H1</th><th>H2</th></tr><tr><td>1</td><td>2</td></tr></table>"
    ))
    assert el["data"]["header_row"] is True

def test_math_in_cell_preserved_from_escaped_input():
    # Input is already math-escaped (parse_lesson escapes before building the soup),
    # so the cell html carries the entity verbatim — exact assert, not substring.
    el, _ = table_element(_t(r"<table><tr><td>\(a&lt;b\)</td></tr></table>"))
    assert el["data"]["cells"][0][0]["html"] == r"\(a&lt;b\)"

def test_colspan_is_flagged_not_dropped():
    el, flags = table_element(_t(
        '<table><tr><td colspan="2">wide</td></tr><tr><td>a</td><td>b</td></tr></table>'
    ))
    assert el["type"] == "html" and el["flagged"] is True
    assert any(f["kind"] == "table_span" for f in flags)

def test_ragged_rows_flagged():
    el, flags = table_element(_t(
        "<table><tr><td>a</td><td>b</td></tr><tr><td>c</td></tr></table>"
    ))
    assert el["type"] == "html"
    assert any(f["kind"] == "table_ragged" for f in flags)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/lal_import/test_tables.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

`scripts/lal_import/tables.py`:

```python
"""Convert a source <table> to a rectangular TableElement grid, or flag it.

The table tag comes from an already-math-escaped soup (parse_lesson escapes the
raw HTML before parsing), so cell content is emitted verbatim — never re-escaped.
"""

from bs4 import Tag


def _rows(table):
    # Flatten thead/tbody: any <tr> anywhere under the table.
    return table.find_all("tr")


def _cells(tr):
    return [c for c in tr.find_all(["td", "th"], recursive=False)] or \
           tr.find_all(["td", "th"])


def _flag_html(table, kind, reason):
    return ({"type": "html", "flagged": True, "raw": str(table), "reason": reason},
            [{"kind": kind, "reason": reason, "raw_excerpt": str(table)[:300]}])


def table_element(table):
    rows = _rows(table)
    if not rows:
        return _flag_html(table, "table_empty", "table has no rows")

    grid = [_cells(tr) for tr in rows]

    # Reject spans.
    for tr in rows:
        for c in tr.find_all(["td", "th"]):
            if c.get("colspan") or c.get("rowspan"):
                return _flag_html(table, "table_span",
                                  "table uses rowspan/colspan")
    # Nested table?
    if any(c.find("table") for tr in rows for c in tr.find_all(["td", "th"])):
        return _flag_html(table, "table_nested", "table nests another table")
    # Ragged?
    width = len(grid[0])
    if any(len(r) != width for r in grid):
        return _flag_html(table, "table_ragged", "rows have differing cell counts")

    header_row = all(c.name == "th" for c in grid[0])
    header_col = all(r[0].name == "th" for r in grid)

    cells = []
    for r in grid:
        cells.append([
            {"html": "".join(str(x) for x in c.children).strip(),  # already escaped
             "halign": "left", "valign": "top"}
            for c in r
        ])
    data = {"header_row": header_row, "header_col": header_col,
            "border": "grid", "cells": cells}
    return {"type": "table", "data": data}, []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/lal_import/test_tables.py tests/lal_import/test_lesson.py -q`
Expected: PASS (both files — the lesson `<table>` branch now resolves).

- [ ] **Step 5: Commit**

```bash
git add scripts/lal_import/tables.py tests/lal_import/test_tables.py
git commit -m "feat(lal-import): table to rectangular grid, spans flagged"
```

---

## Task 8: Quiz DSL parser

**Files:**
- Create: `scripts/lal_import/quiz.py`
- Test: `tests/lal_import/test_quiz.py`

**Interfaces:**
- Consumes: `escape_math_delimited` (Task 4), `normalize_numeric` (Task 5).
- **Escapes `html` at entry** (before the soup is built — C1). Content-loss cases (`mixed_zadanie`, `stem_without_answer`, `quiz_stem_media`) emit a `{"type":"html","flagged":true,…}` element **in addition to** a flag record, so the loader's per-element gate (Task 14) refuses them; warning-only cases (`unknown_hint`, `choice_over_500`) emit a flag record only (I5).
- Produces: `parse_quiz(html: str) -> tuple[list[dict], list[dict]]` → `(question_elements, flags)`. Question dicts:
  - `{"type":"choice","stem": <escaped html>, "multiple": bool, "choices":[{"text":str,"is_correct":bool,"feedback":str}]}`
  - `{"type":"numeric","stem": <escaped html>, "value": str, "tolerance": "0"}`
  - `{"type":"shorttext","stem": <escaped html>, "accepted":[str], "case_sensitive": false}`
  Flags: mixed Zadanie, unknown hint form, over-length choice (>500), non-prose stem media, unmatched DSL.

- [ ] **Step 1: Write the failing test**

`tests/lal_import/test_quiz.py`:

```python
from scripts.lal_import.quiz import parse_quiz

CHOICE_QUIZ = r"""
<p>Dany jest zbiór \(A=\{3,4,7\}\).</p>
[x] \(3\in A\)
[ ] \(6\in A\) {{selected: czy 6 jest elementem \(A\)?}}
[x] \(\{3,7\}\subset A\)
"""

NUMERIC_QUIZ = r"""
<p>Ile elementów ma \(A\cap B\)?</p>
= 2
"""

def test_choice_bracket_shape_is_multiselect():
    qs, flags = parse_quiz(CHOICE_QUIZ)
    assert len(qs) == 1
    q = qs[0]
    assert q["type"] == "choice"
    assert q["multiple"] is True
    assert [c["is_correct"] for c in q["choices"]] == [True, False, True]

def test_choice_feedback_extracted():
    qs, _ = parse_quiz(CHOICE_QUIZ)
    fb = qs[0]["choices"][1]["feedback"]
    assert "6 jest elementem" in fb

def test_stem_math_escaped_exactly():
    qs, _ = parse_quiz(r"<p>Dla \(a<b\) zachodzi</p>" + "\n= 1\n")
    assert qs[0]["stem"] == r"<p>Dla \(a&lt;b\) zachodzi</p>"

def test_numeric_answer():
    qs, _ = parse_quiz(NUMERIC_QUIZ)
    assert qs[0]["type"] == "numeric"
    assert qs[0]["value"] == "2"
    assert qs[0]["tolerance"] == "0"

def test_radio_bracket_is_single_select():
    qs, _ = parse_quiz("<p>Q</p>\n(x) a\n( ) b\n")
    assert qs[0]["multiple"] is False

def test_mixed_zadanie_flagged_and_emits_flagged_element():
    qs, flags = parse_quiz("<p>Q</p>\n[x] a\n= 5\n")
    assert any(f["kind"] == "mixed_zadanie" for f in flags)
    assert any(q.get("flagged") for q in qs)   # a flagged element, not silent drop

def test_quiz_stem_media_flagged_and_emits_flagged_element():
    qs, flags = parse_quiz('<p>Q</p><img src="x.png"/>\n= 1\n')
    assert any(f["kind"] == "quiz_stem_media" for f in flags)
    assert any(q.get("flagged") for q in qs)

def test_unknown_hint_flagged():
    qs, flags = parse_quiz("<p>Q</p>\n[ ] a {{unselected: no}}\n")
    assert any(f["kind"] == "unknown_hint" for f in flags)

def test_two_questions_segmented_without_comments():
    qs, _ = parse_quiz("<p>Q1</p>\n= 1\n<p>Q2</p>\n= 2\n")
    assert len(qs) == 2
    assert qs[0]["value"] == "1" and qs[1]["value"] == "2"

def test_zadanie_comment_is_a_boundary_not_unmatched_dsl():
    # bs4 Comment nodes stringify to their inner text (no <!-- markers), so they
    # must be detected structurally — never string-matched — and never flagged.
    html = "<!-- Zadanie 1 -->\n<p>Q1</p>\n= 1\n<!-- Zadanie 2 -->\n<p>Q2</p>\n= 2\n"
    qs, flags = parse_quiz(html)
    assert not any(f["kind"] == "unmatched_dsl" for f in flags)
    assert [q["value"] for q in qs] == ["1", "2"]

def test_choice_math_stored_literal_for_autoescape():
    # C1: choice option math must be stored with a LITERAL '<' (bs4 NavigableString
    # decodes it), so the autoescaped choice template renders it correctly.
    qs, _ = parse_quiz(r"<p>Q</p>" + "\n[x] \\(y<z\\)\n")
    assert qs[0]["choices"][0]["text"] == r"\(y<z\)"   # literal <, not &lt;
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/lal_import/test_quiz.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

`scripts/lal_import/quiz.py`:

```python
"""Parse OpenEdX-style quiz DSL (bare text lines between <p> stems) into questions."""

import re

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from scripts.lal_import.mathsafe import escape_math_delimited
from scripts.lal_import.numbers import normalize_numeric

_OPTION = re.compile(r"^\s*([\[(])\s*([ xX]?)\s*[\])]\s*(.*)$")
_HINT = re.compile(r"\{\{\s*(\w+)\s*:\s*(.*?)\s*\}\}\s*$", re.DOTALL)
_STEM_STRIP_TAGS = {"img", "table", "figure", "iframe", "h2"}


def _flag(kind, reason, excerpt=""):
    return {"kind": kind, "reason": reason, "raw_excerpt": excerpt[:300]}


def _flag_element(reason, raw):
    return {"type": "html", "flagged": True, "raw": raw, "reason": reason}


def _split_hint(text):
    m = _HINT.search(text)
    if not m:
        return text.strip(), None, None
    return text[:m.start()].strip(), m.group(1), m.group(2)


def parse_quiz(html):
    # Escape math <,> on the RAW string before parsing (C1); never re-escape below.
    soup = BeautifulSoup(escape_math_delimited(html), "html.parser")
    root = soup.body or soup
    questions, flags = [], []
    cur = _new_q()

    def flush():
        nonlocal cur
        el, qflags = _finish(cur)
        if el is not None:
            questions.append(el)
        flags.extend(qflags)
        cur = _new_q()

    for node in root.children:
        if isinstance(node, Comment):
            # <!-- Zadanie N --> is an authoritative question boundary (spec §6).
            # bs4 stringifies a Comment to its inner text (no markers), so it MUST
            # be caught here structurally, never string-matched in _consume_line.
            flush()
            continue
        if isinstance(node, Tag):
            if node.name in _STEM_STRIP_TAGS:
                # content-loss: emit a flagged element AND a flag record (I5)
                questions.append(_flag_element(
                    f"<{node.name}> media cannot live in a sanitized stem", str(node)))
                flags.append(_flag("quiz_stem_media",
                                   f"<{node.name}> cannot live in a sanitized stem",
                                   str(node)))
                continue
            if node.name in {"p", "div"}:
                if cur["answers_seen"]:      # boundary: stem after answers
                    flush()
                cur["stem_html"].append(str(node))  # already escaped
            continue
        if not isinstance(node, NavigableString):
            continue
        for line in str(node).splitlines():
            if not line.strip():
                continue
            _consume_line(line, cur, flags)
    flush()
    return questions, flags


def _new_q():
    return {"stem_html": [], "options": [], "answers": [], "answers_seen": False,
            "bracket": None}


def _consume_line(line, cur, flags):
    m = _OPTION.match(line)
    if m:
        cur["answers_seen"] = True
        bracket = "[" if m.group(1) == "[" else "("
        cur["bracket"] = cur["bracket"] or bracket
        is_correct = m.group(2).lower() == "x"
        text, hint_key, hint_val = _split_hint(m.group(3))
        feedback = ""
        if hint_key is not None:
            if hint_key == "selected":
                feedback = hint_val
            else:
                flags.append(_flag("unknown_hint",
                                   f"hint form {{{{{hint_key}:}}}} not mapped", line))
        cur["options"].append({"text": text, "is_correct": is_correct,
                               "feedback": feedback})
        return
    if line.lstrip().startswith("="):
        cur["answers_seen"] = True
        cur["answers"].append(line.lstrip()[1:].strip())
        return
    # Comments are handled structurally in parse_quiz (bs4 Comment nodes), never here.
    flags.append(_flag("unmatched_dsl", "line matched no DSL shape", line))


def _finish(cur):
    stem = "".join(cur["stem_html"])  # already math-escaped at parse_quiz entry
    has_choice = bool(cur["options"])
    has_fill = bool(cur["answers"])
    if has_choice and has_fill:
        # content-loss: emit a flagged element AND a flag record (I5)
        return (_flag_element("question has both an option group and a = answer", stem),
                [_flag("mixed_zadanie",
                       "question has both an option group and a = answer", stem)])
    flags = []
    for opt in cur["options"]:
        if len(opt["text"]) > 500 or len(opt["feedback"]) > 500:
            flags.append(_flag("choice_over_500",
                              "choice text/feedback exceeds 500 chars", opt["text"]))
    if has_choice:
        multiple = cur["bracket"] == "["
        return ({"type": "choice", "stem": stem, "multiple": multiple,
                 "choices": cur["options"]}, flags)
    if has_fill:
        num = normalize_numeric(cur["answers"][0])
        if num is not None and len(cur["answers"]) == 1:
            return ({"type": "numeric", "stem": stem, "value": num,
                     "tolerance": "0"}, flags)
        return ({"type": "shorttext", "stem": stem, "accepted": cur["answers"],
                 "case_sensitive": False}, flags)
    if stem.strip():
        return (_flag_element("stem had no answer DSL", stem),
                [_flag("stem_without_answer", "stem had no answer DSL", stem)])
    return None, []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/lal_import/test_quiz.py -q`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/lal_import/quiz.py tests/lal_import/test_quiz.py
git commit -m "feat(lal-import): quiz DSL parser (choice/numeric/text + flags)"
```

---

## Task 9: Emit — seed_hash, unit JSON, manifest, flags

**Files:**
- Create: `scripts/lal_import/emit.py`
- Test: `tests/lal_import/test_emit.py`

**Interfaces:**
- Produces:
  - `seed_hash(unit_payload: dict) -> str` — SHA-256 hex over `json.dumps({k:v for k,v in payload.items() if k not in {"seed_hash","fully_mapped"}}, sort_keys=True, separators=(",",":"))`.
  - `unit_payload(elements: list[dict], flags: list[dict]) -> dict` — `{"elements":…, "fully_mapped": <no flagged element AND no flag records>, "seed_hash": <computed>}`. Taking `flags` is what makes warning-only units (a flag record but no flagged element — e.g. a quiz `unknown_hint`) still report `fully_mapped:false`, so `--refresh-unmapped` and the Phase-1 review both see them (I5).
  - `is_fully_mapped(elements) -> bool` — no element has `flagged` truthy.

- [ ] **Step 1: Write the failing test**

`tests/lal_import/test_emit.py`:

```python
from scripts.lal_import.emit import seed_hash, unit_payload, is_fully_mapped

def test_fully_mapped_true_when_no_flag():
    assert is_fully_mapped([{"type": "text", "body": "x"}]) is True

def test_fully_mapped_false_with_flag():
    assert is_fully_mapped([{"type": "html", "flagged": True, "raw": "x"}]) is False

def test_seed_hash_excludes_self_and_fully_mapped():
    p = unit_payload([{"type": "text", "body": "x"}], [])
    # Adding/altering the excluded keys must NOT change the hash.
    p2 = dict(p)
    p2["seed_hash"] = "different"
    p2["fully_mapped"] = not p2["fully_mapped"]
    assert seed_hash(p) == seed_hash(p2)

def test_seed_hash_changes_with_payload():
    a = unit_payload([{"type": "text", "body": "x"}], [])
    b = unit_payload([{"type": "text", "body": "y"}], [])
    assert a["seed_hash"] != b["seed_hash"]

def test_payload_stamps_hash_and_flag():
    p = unit_payload([{"type": "text", "body": "x"}], [])
    assert p["fully_mapped"] is True
    assert p["seed_hash"] == seed_hash(p)

def test_flag_record_alone_marks_not_fully_mapped():
    # A warning-only flag (no flagged element) still forces fully_mapped=false.
    p = unit_payload([{"type": "choice", "stem": "x", "multiple": True, "choices": []}],
                     [{"kind": "unknown_hint", "reason": "…", "raw_excerpt": ""}])
    assert p["fully_mapped"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/lal_import/test_emit.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

`scripts/lal_import/emit.py`:

```python
"""seed_hash canonicalization and the unit-payload shape."""

import hashlib
import json

_EXCLUDED = {"seed_hash", "fully_mapped"}


def is_fully_mapped(elements):
    return not any(e.get("flagged") for e in elements)


def seed_hash(payload):
    core = {k: v for k, v in payload.items() if k not in _EXCLUDED}
    canonical = json.dumps(core, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def unit_payload(elements, flags):
    payload = {"elements": elements,
               "fully_mapped": is_fully_mapped(elements) and not flags}
    payload["seed_hash"] = seed_hash(payload)
    return payload
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/lal_import/test_emit.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/lal_import/emit.py tests/lal_import/test_emit.py
git commit -m "feat(lal-import): seed_hash canonical form + unit payload"
```

---

## Task 10: Parser CLI + re-parse guards

**Files:**
- Create: `scripts/lal_import/parser.py`
- Test: `tests/lal_import/test_parser_cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `seed_part(source_root: Path, folder: str, out_root: Path, mode: str) -> dict` where `mode ∈ {"seed","refresh-unmapped","refresh-elements","force"}`; returns the manifest dict it wrote. Writes `<out_root>/<folder>/manifest.json`, one `<unit>.json` per unit, and `flags.json`. Re-parse guard: default `seed` refuses if the folder dir already exists; `refresh-unmapped` rewrites only units with `fully_mapped==False` AND stored `seed_hash` matching a recompute; `refresh-elements` rewrites units whose `seed_hash` still matches (i.e. not hand-edited); `force` rewrites all and overwrites the manifest. **The manifest is written only by `seed`/`force`; `refresh-*` never rewrite it** (so hand-edited part/chapter/unit titles are preserved — spec §4.1, I4) and instead re-read it to return. `flags.json` is always regenerated from a fresh full parse; in refresh modes it can therefore still list the original parser flags of a unit that was hand-fixed (and hence NOT rewritten) — per-unit `fully_mapped` in the unit JSON is the authoritative "is this resolved" signal, `flags.json` is a coarse worklist. Also `main(argv)` argparse entry (`--source-root` required, `--json-dir`, `--refresh-unmapped`, `--refresh-elements`, `--force`, `folder` positional).

- [ ] **Step 1: Write the failing test**

`tests/lal_import/test_parser_cli.py` (uses `tmp_path`; builds a tiny 2-file part on disk):

```python
import json
from pathlib import Path
from scripts.lal_import.parser import seed_part

def _make_source(root: Path):
    part = root / "005_demo"
    (part / "static").mkdir(parents=True)
    (part / "010_intro.html").write_text(
        "<h2>Intro</h2><p>Witaj \\(x<y\\)</p>", encoding="utf-8")
    (part / "039_x_quiz.html").write_text(
        "<p>Ile?</p>\n= 2\n", encoding="utf-8")
    return part

def test_seed_writes_manifest_units_and_flags(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    _make_source(root)
    out = tmp_path / "out"
    manifest = seed_part(root, "005_demo", out, mode="seed")

    assert manifest["part"]["source_folder"] == "005_demo"
    assert manifest["part"]["title"] == "demo"          # ASCII placeholder
    assert len(manifest["chapters"]) == 1
    units = manifest["chapters"][0]["units"]
    assert [u["unit_type"] for u in units] == ["lesson", "quiz"]

    intro = json.loads((out / "005_demo" / units[0]["unit_json"]).read_text("utf-8"))
    body = " ".join(e.get("body", "") for e in intro["elements"])
    assert r"\(x&lt;y\)" in body                          # math escaped
    assert intro["fully_mapped"] is True
    assert (out / "005_demo" / "flags.json").exists()

def test_seed_refuses_second_seed(tmp_path):
    root = tmp_path / "src"; root.mkdir(); _make_source(root)
    out = tmp_path / "out"
    seed_part(root, "005_demo", out, mode="seed")
    try:
        seed_part(root, "005_demo", out, mode="seed")
        assert False, "expected refusal on re-seed"
    except FileExistsError:
        pass

def test_manifest_part_order_from_scan(tmp_path):
    root = tmp_path / "src"; root.mkdir()
    (root / "005_demo").mkdir(); (root / "010_next").mkdir()
    _make_source(root)  # fills 005_demo
    (root / "010_next" / "010_a.html").write_text("<p>hi</p>", "utf-8")
    out = tmp_path / "out"
    m0 = seed_part(root, "005_demo", out, mode="seed")
    m1 = seed_part(root, "010_next", out, mode="seed")
    assert m0["part"]["order"] == 0
    assert m1["part"]["order"] == 1

def test_refresh_preserves_hand_edited_manifest_titles(tmp_path):
    root = tmp_path / "src"; root.mkdir(); _make_source(root)
    out = tmp_path / "out"
    seed_part(root, "005_demo", out, mode="seed")
    # Simulate the Phase-1 hand-edit of a unit title in the manifest.
    mpath = out / "005_demo" / "manifest.json"
    m = json.loads(mpath.read_text("utf-8"))
    m["chapters"][0]["units"][0]["title"] = "Human Intro Title"
    mpath.write_text(json.dumps(m), "utf-8")
    # A refresh must NOT clobber that edited unit title.
    seed_part(root, "005_demo", out, mode="refresh-elements")
    after = json.loads(mpath.read_text("utf-8"))
    assert after["chapters"][0]["units"][0]["title"] == "Human Intro Title"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/lal_import/test_parser_cli.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

`scripts/lal_import/parser.py`:

```python
"""CLI + orchestration: seed a part's manifest + unit JSON + flags.json."""

import argparse
import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

from scripts.lal_import.emit import seed_hash, unit_payload
from scripts.lal_import.grouping import group_into_chapters
from scripts.lal_import.lesson import parse_lesson
from scripts.lal_import.naming import lesson_title, part_title_placeholder, quiz_title
from scripts.lal_import.ordering import duplicate_token_warnings, ordered_html_files
from scripts.lal_import.quiz import parse_quiz

_THREE_DIGIT = re.compile(r"^\d{3}")


def _three_digit_folders(source_root):
    return sorted(p.name for p in Path(source_root).iterdir()
                  if p.is_dir() and _THREE_DIGIT.match(p.name))


def _part_order(source_root, folder):
    return _three_digit_folders(source_root).index(folder)


def _parse_unit(part_dir, source_html, unit_type):
    html = (part_dir / source_html).read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    if unit_type == "quiz":
        elements, flags = parse_quiz(html)
        title = quiz_title(source_html)
    else:
        elements, flags = parse_lesson(html, source_html)
        title = lesson_title(soup, source_html)
    return elements, flags, title


def seed_part(source_root, folder, out_root, mode="seed"):
    source_root = Path(source_root)
    out_root = Path(out_root)
    part_dir = source_root / folder
    out_dir = out_root / folder

    if out_dir.exists() and mode == "seed":
        raise FileExistsError(
            f"{out_dir} already seeded; use --refresh-unmapped/--refresh-elements/--force")

    names = [p.name for p in part_dir.glob("*.html")]
    ordered = ordered_html_files(names)
    all_flags = list(duplicate_token_warnings(ordered))
    chapters_src = group_into_chapters(ordered)

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "part": {"source_folder": folder, "order": _part_order(source_root, folder),
                 "title": part_title_placeholder(folder)},
        "chapters": [],
    }
    for c_i, ch in enumerate(chapters_src):
        units_meta = []
        for u_i, u in enumerate(ch["units"]):
            src = u["source_html"]
            unit_json = src[:-5] + ".json"
            elements, flags, title = _parse_unit(part_dir, src, u["unit_type"])
            for f in flags:
                f["unit_json"] = unit_json
            all_flags.extend(flags)
            _write_unit(out_dir / unit_json, unit_payload(elements, flags), mode)
            units_meta.append({"order": u_i, "unit_json": unit_json,
                               "source_html": src, "source_dir": folder,
                               "unit_type": u["unit_type"], "title": title})
        manifest["chapters"].append(
            {"order": c_i, "title": f"__PLACEHOLDER chapter {c_i + 1}__",
             "units": units_meta})

    # Only seed/force write the manifest. seed runs only on a fresh dir (guarded
    # above), so its manifest is brand-new; force intentionally discards names.
    # refresh-* NEVER touch the manifest — hand-edited part/chapter/unit titles are
    # fully preserved (spec §4.1, I4). flags.json (a derived worklist) is always
    # regenerated.
    if mode in ("seed", "force"):
        (out_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        manifest = json.loads((out_dir / "manifest.json").read_text("utf-8"))
    (out_dir / "flags.json").write_text(
        json.dumps(all_flags, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def _write_unit(path, payload, mode):
    """Honor the re-parse guard for an individual unit file."""
    if not path.exists() or mode == "force":
        _dump(path, payload)
        return
    existing = json.loads(path.read_text(encoding="utf-8"))
    stored = existing.get("seed_hash")
    untouched = stored == seed_hash(existing)
    if mode == "refresh-unmapped" and not existing.get("fully_mapped") and untouched:
        _dump(path, payload)
    elif mode == "refresh-elements" and untouched:
        _dump(path, payload)
    # else: preserve the edited unit (do nothing)


def _dump(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(description="Seed LAL import JSON for one part.")
    ap.add_argument("folder")
    ap.add_argument("--source-root", required=True)
    ap.add_argument("--json-dir", default="scripts/lal_import/out")
    ap.add_argument("--refresh-unmapped", action="store_true")
    ap.add_argument("--refresh-elements", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    mode = ("force" if args.force else
            "refresh-elements" if args.refresh_elements else
            "refresh-unmapped" if args.refresh_unmapped else "seed")
    seed_part(args.source_root, args.folder, args.json_dir, mode=mode)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/lal_import/test_parser_cli.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Run the whole parser suite + format check**

Run: `uv run pytest tests/lal_import/ -q && uv run ruff format --check scripts/lal_import tests/lal_import`
Expected: all pass; format check clean (fix with `uv run ruff format` if not).

- [ ] **Step 6: Commit**

```bash
git add scripts/lal_import/parser.py tests/lal_import/test_parser_cli.py
git commit -m "feat(lal-import): parser CLI + re-parse guards (seed/refresh/force)"
```

---

## Task 11: `MediaAsset.content_hash` field + migration

**Files:**
- Modify: `courses/models.py` (`MediaAsset`)
- Create: `courses/migrations/00NN_mediaasset_content_hash.py` (generated)
- Test: `tests/test_lal_loader_units.py` (new file — first test)

**Interfaces:**
- Produces: `MediaAsset.content_hash` — `CharField(max_length=64, blank=True, default="", db_index=True)`.

- [ ] **Step 1: Write the failing test**

`tests/test_lal_loader_units.py`:

```python
import pytest
from tests.factories import CourseFactory
from courses.models import MediaAsset

pytestmark = pytest.mark.django_db

def test_mediaasset_has_content_hash_field():
    course = CourseFactory()
    a = MediaAsset.objects.create(course=course, kind="image",
                                  original_filename="x.png",
                                  content_hash="a" * 64)
    a.refresh_from_db()
    assert a.content_hash == "a" * 64

def test_content_hash_is_indexed():
    field = MediaAsset._meta.get_field("content_hash")
    assert field.db_index is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_lal_loader_units.py -q`
Expected: FAIL — `MediaAsset() got unexpected keyword 'content_hash'`.

- [ ] **Step 3: Add the field**

In `courses/models.py`, inside `class MediaAsset`, after `original_filename`:

```python
    # SHA-256 hex of the file bytes; used by the LAL import loader for durable
    # (course, content_hash) dedup. Blank on assets created before/without hashing.
    content_hash = models.CharField(max_length=64, blank=True, default="", db_index=True)
```

- [ ] **Step 4: Generate + apply the migration**

Run:
```bash
uv run python manage.py makemigrations courses
uv run python manage.py migrate
```
Expected: a new `courses/migrations/00NN_mediaasset_content_hash.py` adding the field.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_lal_loader_units.py -q`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add courses/models.py courses/migrations/00*_mediaasset_content_hash.py tests/test_lal_loader_units.py
git commit -m "feat(courses): add MediaAsset.content_hash for import dedup"
```

---

## Task 12: Add edpuzzle/Lumi to the embed allowlist

**Files:**
- Modify: `config/settings/base.py` (`ALLOWED_EMBED_DOMAINS`)
- Test: `tests/test_lal_loader_units.py` (append)

**Interfaces:**
- Produces: `settings.ALLOWED_EMBED_DOMAINS` includes `edpuzzle.com` and the Lumi host (`app.lumi.education`). Confirm exact hosts against the source before finalizing (Global Constraints).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_lal_loader_units.py`:

```python
from django.conf import settings
from courses.validators import validate_embed_url

def test_edpuzzle_and_lumi_allowlisted():
    hosts = {h.lower() for h in settings.ALLOWED_EMBED_DOMAINS}
    assert "edpuzzle.com" in hosts
    assert "app.lumi.education" in hosts

def test_edpuzzle_embed_url_validates():
    # Should NOT raise now that the host is allowlisted.
    validate_embed_url("https://edpuzzle.com/embed/media/63fdefbfd6b9684157f590c5")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_lal_loader_units.py -k allowlist -q` and `-k edpuzzle -q`
Expected: FAIL — host not in allowlist / `validate_embed_url` raises.

- [ ] **Step 3: Add the hosts (default literal AND any env override)**

`ALLOWED_EMBED_DOMAINS` is env-driven: `env.list("LIBLI_ALLOWED_EMBED_DOMAINS", default=[…])`. `env.list` uses the default **only when the env var is unset**, so editing the default literal alone is inert whenever the var is defined.

First edit the default list literal in `config/settings/base.py` (keep existing entries):

```python
    "edpuzzle.com",
    "app.lumi.education",
```

Then check whether the var is set in any environment the tests/dev run under:

```bash
grep -rn "LIBLI_ALLOWED_EMBED_DOMAINS" .env .env.* config/ 2>/dev/null
printenv LIBLI_ALLOWED_EMBED_DOMAINS || echo "(unset)"
```

If it is set anywhere (`.env`, CI config, shell), add `edpuzzle.com` and `app.lumi.education` to **that** value too — otherwise `test_edpuzzle_and_lumi_allowlisted` stays red and every edpuzzle/Lumi iframe is rejected at load. (Confirm the exact Lumi host against the source files; the samples show `app.Lumi.education` — compare case-insensitively, which `validate_embed_url` already does.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_lal_loader_units.py -k "allowlist or edpuzzle" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add config/settings/base.py tests/test_lal_loader_units.py
git commit -m "feat(courses): allowlist edpuzzle + Lumi embed hosts"
```

---

## Task 13: Loader media resolution + content-hash dedup

**Files:**
- Create: `courses/lal_loader/__init__.py`, `courses/lal_loader/media.py`
- Test: `tests/test_lal_loader_units.py` (append)

**Interfaces:**
- Produces:
  - `resolve_source(source_root: Path, source_dir: str, media_src: str) -> Path`.
  - `get_or_create_asset(course, kind: str, path: Path) -> MediaAsset` — hash the bytes (SHA-256), reuse an existing `(course, content_hash)` asset or create one whose `.file` is saved from the bytes with `original_filename = path.name`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_lal_loader_units.py`:

```python
from pathlib import Path
from courses.lal_loader.media import resolve_source, get_or_create_asset

def test_resolve_source_joins_root_dir_src(tmp_path):
    p = resolve_source(tmp_path, "001_x", "static/a.png")
    assert p == Path(tmp_path) / "001_x" / "static" / "a.png"

def test_dedup_reuses_asset_for_identical_bytes(tmp_path):
    course = CourseFactory()
    f = tmp_path / "a.png"; f.write_bytes(b"PNGBYTES")
    g = tmp_path / "b.png"; g.write_bytes(b"PNGBYTES")  # same bytes, different name
    a1 = get_or_create_asset(course, "image", f)
    a2 = get_or_create_asset(course, "image", g)
    assert a1.pk == a2.pk                       # deduped by content, not name
    assert a1.content_hash and len(a1.content_hash) == 64

def test_different_bytes_make_different_assets(tmp_path):
    course = CourseFactory()
    f = tmp_path / "a.png"; f.write_bytes(b"ONE")
    g = tmp_path / "a.png2"; g.write_bytes(b"TWO")
    assert get_or_create_asset(course, "image", f).pk != \
           get_or_create_asset(course, "image", g).pk
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_lal_loader_units.py -k "resolve or dedup or different_bytes" -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

`courses/lal_loader/__init__.py`: empty.
`courses/lal_loader/media.py`:

```python
"""Media resolution + durable content-hash dedup for the LAL import loader."""

import hashlib
from pathlib import Path

from django.core.files.base import ContentFile

from courses.models import MediaAsset


def resolve_source(source_root, source_dir, media_src):
    return Path(source_root) / source_dir / media_src


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def get_or_create_asset(course, kind, path):
    path = Path(path)
    data = path.read_bytes()
    digest = _sha256(data)
    existing = MediaAsset.objects.filter(course=course, content_hash=digest).first()
    if existing is not None:
        return existing
    asset = MediaAsset(course=course, kind=kind, original_filename=path.name,
                       content_hash=digest)
    asset.file.save(path.name, ContentFile(data), save=False)
    asset.save()
    return asset
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_lal_loader_units.py -k "resolve or dedup or different_bytes" -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add courses/lal_loader/__init__.py courses/lal_loader/media.py tests/test_lal_loader_units.py
git commit -m "feat(lal-loader): media resolution + content-hash dedup"
```

---

## Task 14: Element builders (dict → concrete element)

**Files:**
- Create: `courses/lal_loader/builders.py`
- Test: `tests/test_lal_loader_units.py` (append)

**Interfaces:**
- Consumes: `get_or_create_asset`, `resolve_source` (Task 13); `canonicalize_geogebra_url` (`courses.geogebra`).
- Produces: `build_element(course, unit, el: dict, *, source_root, source_dir, allow_html: bool) -> object` — creates the concrete model instance, attaches it via `Element.objects.create(unit=unit, content_object=obj)` in caller order, and returns the concrete object. Raises `LoaderError` on a `flagged` element unless `allow_html`. `LoaderError(Exception)` is defined here.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_lal_loader_units.py`:

```python
from decimal import Decimal
from tests.factories import ContentNodeFactory
from courses.lal_loader.builders import build_element, LoaderError
from courses.models import (TextElement, MathElement, SpoilerElement,
                            ChoiceQuestionElement, ShortNumericQuestionElement,
                            ShortTextQuestionElement, Element)

def _unit(course):
    return ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=None)

def test_build_text_element(tmp_path):
    course = CourseFactory(); unit = _unit(course)
    obj = build_element(course, unit, {"type": "text", "body": "<p>hi</p>"},
                        source_root=tmp_path, source_dir="x", allow_html=False)
    assert isinstance(obj, TextElement)
    assert Element.objects.filter(unit=unit).count() == 1

def test_build_choice_with_choices(tmp_path):
    course = CourseFactory(); unit = _unit(course)
    obj = build_element(course, unit, {
        "type": "choice", "stem": "<p>Q</p>", "multiple": True,
        "choices": [{"text": "a", "is_correct": True, "feedback": ""},
                    {"text": "b", "is_correct": False, "feedback": "no"}],
    }, source_root=tmp_path, source_dir="x", allow_html=False)
    assert isinstance(obj, ChoiceQuestionElement)
    assert obj.multiple is True
    assert obj.choices.count() == 2
    assert obj.choices.filter(is_correct=True).count() == 1

def test_build_numeric(tmp_path):
    course = CourseFactory(); unit = _unit(course)
    obj = build_element(course, unit, {"type": "numeric", "stem": "<p>n</p>",
                                       "value": "2.5", "tolerance": "0"},
                        source_root=tmp_path, source_dir="x", allow_html=False)
    assert isinstance(obj, ShortNumericQuestionElement)
    assert obj.value == Decimal("2.5")

def test_build_shorttext(tmp_path):
    course = CourseFactory(); unit = _unit(course)
    obj = build_element(course, unit, {"type": "shorttext", "stem": "<p>t</p>",
                                       "accepted": ["ala", "ola"],
                                       "case_sensitive": False},
                        source_root=tmp_path, source_dir="x", allow_html=False)
    assert isinstance(obj, ShortTextQuestionElement)
    assert obj.accepted == "ala\nola"

def test_flagged_element_refused_without_allow_html(tmp_path):
    course = CourseFactory(); unit = _unit(course)
    with pytest.raises(LoaderError):
        build_element(course, unit, {"type": "html", "flagged": True, "raw": "<x/>"},
                      source_root=tmp_path, source_dir="x", allow_html=False)

def test_over_500_char_choice_raises_loader_error(tmp_path):
    course = CourseFactory(); unit = _unit(course)
    with pytest.raises(LoaderError):
        build_element(course, unit, {
            "type": "choice", "stem": "<p>Q</p>", "multiple": False,
            "choices": [{"text": "x" * 501, "is_correct": True, "feedback": ""}],
        }, source_root=tmp_path, source_dir="x", allow_html=False)

def test_escaped_math_in_stem_survives_sanitize_on_save(tmp_path):
    # Spec §5: a \(a<b\) span (parser-escaped to \(a&lt;b\)) must survive the model's
    # sanitize_html on save — verified through a real QuestionElement.stem, not a
    # bare nh3.clean call.
    course = CourseFactory(); unit = _unit(course)
    obj = build_element(course, unit, {
        "type": "numeric", "stem": r"<p>gdy \(a&lt;b\)</p>", "value": "1",
        "tolerance": "0"}, source_root=tmp_path, source_dir="x", allow_html=False)
    obj.refresh_from_db()
    assert r"\(a&lt;b\)" in obj.stem

def test_choice_literal_math_stored_then_autoescapes(tmp_path):
    # C1 end-to-end: the parser stores literal '<' in Choice.text; Django autoescape
    # (the choice template) then renders the single correct \(y&lt;z\).
    from django.utils.html import escape
    course = CourseFactory(); unit = _unit(course)
    obj = build_element(course, unit, {
        "type": "choice", "stem": "<p>Q</p>", "multiple": True,
        "choices": [{"text": r"\(y<z\)", "is_correct": True, "feedback": ""}],
    }, source_root=tmp_path, source_dir="x", allow_html=False)
    text = obj.choices.first().text
    assert text == r"\(y<z\)"                      # stored literal
    assert escape(text) == r"\(y&lt;z\)"           # autoescape -> single entity
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_lal_loader_units.py -k build -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

`courses/lal_loader/builders.py`:

```python
"""Turn a parsed element dict into a concrete libli element attached to a unit."""

from decimal import Decimal

from courses.geogebra import canonicalize_geogebra_url
from courses.lal_loader.media import get_or_create_asset, resolve_source
from courses.models import (
    Choice, ChoiceQuestionElement, Element, HtmlElement, IframeElement,
    ImageElement, MathElement, ShortNumericQuestionElement,
    ShortTextQuestionElement, SpoilerElement, TableElement, TextElement,
    VideoElement,
)


class LoaderError(Exception):
    pass


def build_element(course, unit, el, *, source_root, source_dir, allow_html):
    etype = el.get("type")
    if el.get("flagged"):
        if not allow_html:
            raise LoaderError(
                f"flagged element ({el.get('reason', 'unmapped')}) in unit "
                f"{unit.pk}; fix the JSON or pass --allow-html")
        obj = HtmlElement.objects.create(html=el.get("raw", ""))
        return _attach(unit, obj)

    if etype == "text":
        return _attach(unit, TextElement.objects.create(body=el["body"]))
    if etype == "math":
        return _attach(unit, MathElement.objects.create(latex=el["latex"]))
    if etype == "spoiler":
        return _attach(unit, SpoilerElement.objects.create(
            label=el.get("label", ""), body=el["body"]))
    if etype == "iframe":
        url = canonicalize_geogebra_url(el["url"])
        return _attach(unit, IframeElement.objects.create(
            url=url, title=el.get("title", "")))
    if etype == "image":
        path = resolve_source(source_root, source_dir, el["media_src"])
        asset = get_or_create_asset(course, "image", path)
        return _attach(unit, ImageElement.objects.create(
            media=asset, alt=el.get("alt", ""), figcaption=el.get("figcaption", "")))
    if etype == "video":
        path = resolve_source(source_root, source_dir, el["media_src"])
        asset = get_or_create_asset(course, "video", path)
        return _attach(unit, VideoElement.objects.create(media=asset))
    if etype == "table":
        return _attach(unit, TableElement.objects.create(
            data=TableElement.normalize_data(el["data"])))
    if etype == "choice":
        # Validate lengths BEFORE any create, so we fail loud with LoaderError
        # (not a mid-transaction DB DataError) and leave no orphan question.
        for c in el["choices"]:
            if len(c["text"]) > 500 or len(c.get("feedback", "")) > 500:
                raise LoaderError(
                    f"choice text/feedback exceeds 500 chars in unit {unit.pk}; "
                    "shorten or split the option (Choice fields are varchar(500))")
        q = ChoiceQuestionElement.objects.create(
            stem=el["stem"], multiple=bool(el.get("multiple")))
        for c in el["choices"]:
            Choice.objects.create(question=q, text=c["text"],
                                  is_correct=bool(c.get("is_correct")),
                                  feedback=c.get("feedback", ""))
        return _attach(unit, q)
    if etype == "numeric":
        return _attach(unit, ShortNumericQuestionElement.objects.create(
            stem=el["stem"], value=Decimal(el["value"]),
            tolerance=Decimal(el.get("tolerance", "0"))))
    if etype == "shorttext":
        return _attach(unit, ShortTextQuestionElement.objects.create(
            stem=el["stem"], accepted="\n".join(el["accepted"]),
            case_sensitive=bool(el.get("case_sensitive"))))
    raise LoaderError(f"unknown element type {etype!r} in unit {unit.pk}")


def _attach(unit, obj):
    Element.objects.create(unit=unit, content_object=obj)
    return obj
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_lal_loader_units.py -k build -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add courses/lal_loader/builders.py tests/test_lal_loader_units.py
git commit -m "feat(lal-loader): element builders (dict to concrete element)"
```

---

## Task 15: Loader guards (course / policy / owned-set / allowlist)

**Files:**
- Create: `courses/lal_loader/guards.py`
- Test: `tests/test_lal_loader_units.py` (append)

**Interfaces:**
- Produces:
  - `resolve_course(slug: str) -> Course` (raises `LoaderError` if missing).
  - `ensure_depth_policy(course, set_policy: bool)` — verify `uses_parts` & `uses_chapters` True; if `set_policy`, set+save them; else raise `LoaderError` when either is False.
  - `owned_part_orders(json_dir: Path) -> set[int]` — read every `<json-dir>/*/manifest.json`'s `part.order`.
  - `assert_no_foreign_top_level(course, owned: set[int])` — raise `LoaderError` if a `parent=None` node's `order` is not in `owned`.
  - `assert_iframe_hosts_allowlisted(elements: list[dict])` — call `validate_embed_url` on each iframe url; re-raise as `LoaderError`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_lal_loader_units.py`:

```python
from courses.lal_loader.guards import (
    resolve_course, ensure_depth_policy, owned_part_orders,
    assert_no_foreign_top_level, assert_iframe_hosts_allowlisted,
)
from courses.models import ContentNode

def test_resolve_course_missing_raises():
    with pytest.raises(LoaderError):
        resolve_course("does-not-exist")

def test_ensure_policy_raises_when_off_without_flag():
    course = CourseFactory(uses_parts=False, uses_chapters=True)
    with pytest.raises(LoaderError):
        ensure_depth_policy(course, set_policy=False)

def test_ensure_policy_sets_when_flagged():
    course = CourseFactory(uses_parts=False, uses_chapters=False, uses_sections=True)
    ensure_depth_policy(course, set_policy=True)
    course.refresh_from_db()
    assert course.uses_parts and course.uses_chapters
    assert course.uses_sections is False        # sections turned off (spec §4.4)

def test_owned_part_orders_reads_all_manifests(tmp_path):
    for folder, order in [("001_a", 0), ("005_b", 1)]:
        d = tmp_path / folder; d.mkdir()
        (d / "manifest.json").write_text(
            f'{{"part": {{"order": {order}}}, "chapters": []}}', "utf-8")
    assert owned_part_orders(tmp_path) == {0, 1}

def test_foreign_top_level_node_refused():
    course = CourseFactory()
    ContentNode.objects.create(course=course, parent=None, kind="part",
                               title="foreign", order=9)
    with pytest.raises(LoaderError):
        assert_no_foreign_top_level(course, owned={0, 1})

def test_owned_top_level_node_ok():
    course = CourseFactory()
    ContentNode.objects.create(course=course, parent=None, kind="part",
                               title="mine", order=0)
    assert_no_foreign_top_level(course, owned={0, 1})  # no raise

def test_iframe_host_not_allowlisted_raises():
    with pytest.raises(LoaderError):
        assert_iframe_hosts_allowlisted([{"type": "iframe", "url": "https://evil.example/x"}])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_lal_loader_units.py -k "policy or owned or foreign or iframe_host or resolve_course" -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

`courses/lal_loader/guards.py`:

```python
"""Fail-loud preconditions for the LAL import loader."""

import json
from pathlib import Path

from django.core.exceptions import ValidationError

from courses.geogebra import canonicalize_geogebra_url
from courses.lal_loader.builders import LoaderError
from courses.models import ContentNode, Course
from courses.validators import validate_embed_url


def resolve_course(slug):
    try:
        return Course.objects.get(slug=slug)
    except Course.DoesNotExist as e:
        raise LoaderError(f"no Course with slug {slug!r}; create it first") from e


def ensure_depth_policy(course, set_policy):
    if set_policy:
        # Import writes Part->Chapter->Unit; turn sections off (spec §4.4). A
        # pre-existing uses_sections=True is otherwise harmless — the ContentNode
        # invariant permits skipping the optional Section level.
        course.uses_parts = True
        course.uses_chapters = True
        course.uses_sections = False
        course.save(update_fields=["uses_parts", "uses_chapters", "uses_sections"])
        return
    if not (course.uses_parts and course.uses_chapters):
        raise LoaderError(
            f"course {course.slug!r} lacks uses_parts/uses_chapters; "
            "pass --set-policy to enable them")


def owned_part_orders(json_dir):
    orders = set()
    for manifest in Path(json_dir).glob("*/manifest.json"):
        data = json.loads(manifest.read_text(encoding="utf-8"))
        orders.add(data["part"]["order"])
    return orders


def assert_no_foreign_top_level(course, owned):
    foreign = (ContentNode.objects.filter(course=course, parent__isnull=True)
               .exclude(order__in=owned))
    if foreign.exists():
        bad = list(foreign.values_list("order", "title")[:5])
        raise LoaderError(
            f"course {course.slug!r} has top-level nodes not owned by this import "
            f"(orders/titles {bad}); refusing to touch a foreign tree")


def assert_iframe_hosts_allowlisted(elements):
    # Validate the SAME url the builder will store (canonicalized), so the check
    # and the stored value can't disagree on host (M3). GeoGebra canonicalization
    # keeps the host; non-GeoGebra urls pass through unchanged.
    for el in elements:
        if el.get("type") == "iframe":
            url = canonicalize_geogebra_url(el["url"])
            try:
                validate_embed_url(url)
            except ValidationError as e:
                raise LoaderError(f"iframe host not allowlisted: {url}") from e
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_lal_loader_units.py -k "policy or owned or foreign or iframe_host or resolve_course" -q`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add courses/lal_loader/guards.py tests/test_lal_loader_units.py
git commit -m "feat(lal-loader): fail-loud loader preconditions"
```

---

## Task 16: Positional tree upsert + orphan prune + element rebuild

**Files:**
- Create: `courses/lal_loader/tree.py`
- Test: `tests/test_lal_loader_units.py` (append)

**Interfaces:**
- Consumes: `build_element` (Task 14).
- Produces:
  - `upsert_node(course, parent, order, kind, title, unit_type=None) -> ContentNode` — match `(course/parent, order, kind)` else create; update `title`/`unit_type` in place.
  - `prune_orphans(course, parent, keep_count)` — delete children (of `parent`, or top-level when `parent is None`) whose `order >= keep_count`, via `ContentNode.delete`.
  - `rebuild_unit_elements(course, unit, element_dicts, *, source_root, source_dir, allow_html)` — delete the unit's `Element`s + concrete rows (using the same subtree-safe delete `ContentNode.delete` uses), then `build_element` each dict in order.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_lal_loader_units.py`:

```python
from courses.lal_loader.tree import upsert_node, prune_orphans, rebuild_unit_elements
from courses.models import ContentNode, Element, TextElement

def test_upsert_is_idempotent_and_renames_in_place():
    course = CourseFactory()
    n1 = upsert_node(course, None, 0, "part", "orig")
    n2 = upsert_node(course, None, 0, "part", "renamed")
    assert n1.pk == n2.pk                       # same node, matched by (course, order)
    n2.refresh_from_db()
    assert n2.title == "renamed"
    assert ContentNode.objects.filter(course=course, parent=None).count() == 1

def test_prune_deletes_higher_index_orphans():
    course = CourseFactory()
    part = upsert_node(course, None, 0, "part", "p")
    for i in range(3):
        upsert_node(course, part, i, "chapter", f"c{i}")
    prune_orphans(course, part, keep_count=2)    # keep orders 0,1; drop 2
    assert ContentNode.objects.filter(parent=part).count() == 2

def test_rebuild_wipes_then_recreates_in_order(tmp_path):
    course = CourseFactory()
    unit = upsert_node(course, None, 0, "unit", "u", unit_type="lesson")
    els = [{"type": "text", "body": "<p>one</p>"}, {"type": "text", "body": "<p>two</p>"}]
    rebuild_unit_elements(course, unit, els, source_root=tmp_path, source_dir="x", allow_html=False)
    rebuild_unit_elements(course, unit, els, source_root=tmp_path, source_dir="x", allow_html=False)
    rows = list(Element.objects.filter(unit=unit).order_by("order"))
    assert len(rows) == 2                        # rebuilt, not duplicated
    assert TextElement.objects.filter(elements__unit=unit).count() == 2
    assert rows[0].order < rows[1].order         # JSON array order preserved
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_lal_loader_units.py -k "upsert or prune or rebuild" -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

`courses/lal_loader/tree.py`:

```python
"""Positional node upsert, orphan prune, and per-unit element rebuild."""

from courses.lal_loader.builders import build_element
from courses.models import ContentNode, Element, _delete_element_content_objects


def upsert_node(course, parent, order, kind, title, unit_type=None):
    node = ContentNode.objects.filter(
        course=course, parent=parent, order=order, kind=kind).first()
    if node is None:
        return ContentNode.objects.create(
            course=course, parent=parent, order=order, kind=kind,
            title=title, unit_type=unit_type)
    node.title = title
    node.unit_type = unit_type
    node.save(update_fields=["title", "unit_type"])
    return node


def prune_orphans(course, parent, keep_count):
    stale = ContentNode.objects.filter(course=course, parent=parent,
                                       order__gte=keep_count)
    for node in stale:
        node.delete()  # ContentNode.delete sweeps element content objects too


def rebuild_unit_elements(course, unit, element_dicts, *, source_root,
                          source_dir, allow_html):
    rows = Element.objects.filter(unit=unit)
    _delete_element_content_objects(rows)   # delete concrete rows first (no orphans)
    rows.delete()                           # then the join rows
    for el in element_dicts:
        build_element(course, unit, el, source_root=source_root,
                      source_dir=source_dir, allow_html=allow_html)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_lal_loader_units.py -k "upsert or prune or rebuild" -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add courses/lal_loader/tree.py tests/test_lal_loader_units.py
git commit -m "feat(lal-loader): positional node upsert + prune + element rebuild"
```

---

## Task 17: `import_lal_content` management command (end-to-end)

**Files:**
- Create: `courses/management/commands/import_lal_content.py`
- Test: `tests/test_import_lal_content.py`

**Interfaces:**
- Consumes: all loader modules (Tasks 13–16); reads the parser's `out/<folder>/` artifacts (Task 10 shape).
- Produces: the `import_lal_content` command with flags from Global Constraints; loads one part per invocation; `--gc-media` sweeps unreferenced assets.

- [ ] **Step 1: Write the failing test**

`tests/test_import_lal_content.py` (seeds JSON with the parser, then loads it):

```python
import pytest
from pathlib import Path
from django.core.management import call_command
from tests.factories import CourseFactory
from courses.models import ContentNode, Element, ChoiceQuestionElement
from scripts.lal_import.parser import seed_part

pytestmark = pytest.mark.django_db

def _seed(tmp_path):
    src = tmp_path / "src"
    part = src / "001_demo"; (part / "static").mkdir(parents=True)
    (part / "010_intro.html").write_text("<h2>Intro</h2><p>Witaj</p>", "utf-8")
    (part / "039_x_quiz.html").write_text("<p>Zbiór \\(A\\)?</p>\n[x] tak\n[ ] nie\n", "utf-8")
    out = tmp_path / "out"
    seed_part(src, "001_demo", out, mode="seed")
    return src, out

def test_load_builds_part_chapter_units(tmp_path):
    course = CourseFactory(slug="matematyka")
    src, out = _seed(tmp_path)
    call_command("import_lal_content", "--course", "matematyka",
                 "--part", "001_demo", "--json-dir", str(out),
                 "--source-root", str(src))
    part = ContentNode.objects.get(course=course, parent=None, kind="part")
    assert part.title == "demo"
    chapters = ContentNode.objects.filter(parent=part, kind="chapter")
    assert chapters.count() == 1
    units = ContentNode.objects.filter(parent=chapters.first(), kind="unit").order_by("order")
    assert [u.unit_type for u in units] == ["lesson", "quiz"]
    assert ChoiceQuestionElement.objects.filter(elements__unit=units[1]).exists()

def test_load_is_idempotent(tmp_path):
    CourseFactory(slug="matematyka")
    src, out = _seed(tmp_path)
    for _ in range(2):
        call_command("import_lal_content", "--course", "matematyka",
                     "--part", "001_demo", "--json-dir", str(out),
                     "--source-root", str(src))
    parts = ContentNode.objects.filter(parent=None, kind="part")
    assert parts.count() == 1                       # no duplicate tree on re-run
    unit = ContentNode.objects.get(kind="unit", unit_type="lesson")
    assert Element.objects.filter(unit=unit).count() == 1

def test_missing_course_errors(tmp_path):
    src, out = _seed(tmp_path)
    with pytest.raises(Exception):
        call_command("import_lal_content", "--course", "nope",
                     "--part", "001_demo", "--json-dir", str(out),
                     "--source-root", str(src))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_import_lal_content.py -q`
Expected: FAIL — Unknown command `import_lal_content`.

- [ ] **Step 3: Write the command**

`courses/management/commands/import_lal_content.py`:

```python
"""Load one seeded LAL part (manifest + unit JSON) into a course, idempotently."""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from courses.lal_loader.builders import LoaderError
from courses.lal_loader.guards import (
    assert_iframe_hosts_allowlisted, assert_no_foreign_top_level,
    ensure_depth_policy, owned_part_orders, resolve_course,
)
from courses.lal_loader.tree import prune_orphans, rebuild_unit_elements, upsert_node
from courses.models import MediaAsset


class Command(BaseCommand):
    help = "Load one seeded LAL part into a course (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--course", default="matematyka")
        parser.add_argument("--part", required=True)
        parser.add_argument("--json-dir", default="scripts/lal_import/out")
        parser.add_argument("--source-root", required=True)
        parser.add_argument("--allow-html", action="store_true")
        parser.add_argument("--gc-media", action="store_true")
        parser.add_argument("--set-policy", action="store_true")

    def handle(self, *args, **o):
        try:
            self._run(o)
        except LoaderError as e:
            raise CommandError(str(e)) from e

    def _run(self, o):
        json_dir = Path(o["json_dir"])
        part_dir = json_dir / o["part"]
        manifest = json.loads((part_dir / "manifest.json").read_text("utf-8"))

        course = resolve_course(o["course"])
        ensure_depth_policy(course, o["set_policy"])
        assert_no_foreign_top_level(course, owned_part_orders(json_dir))

        with transaction.atomic():
            part = upsert_node(course, None, manifest["part"]["order"], "part",
                               manifest["part"]["title"])
            for ch in manifest["chapters"]:
                chapter = upsert_node(course, part, ch["order"], "chapter", ch["title"])
                for u in ch["units"]:
                    unit = upsert_node(course, chapter, u["order"], "unit",
                                       u["title"], unit_type=u["unit_type"])
                    payload = json.loads(
                        (part_dir / u["unit_json"]).read_text("utf-8"))
                    assert_iframe_hosts_allowlisted(payload["elements"])
                    rebuild_unit_elements(
                        course, unit, payload["elements"],
                        source_root=o["source_root"], source_dir=u["source_dir"],
                        allow_html=o["allow_html"])
                prune_orphans(course, chapter, len(ch["units"]))
            prune_orphans(course, part, len(manifest["chapters"]))

        if o["gc_media"]:
            self._gc_media(course)
        self.stdout.write(self.style.SUCCESS(
            f"loaded part {o['part']} into course {course.slug}"))

    def _gc_media(self, course):
        from courses.models import ImageElement, VideoElement
        used = set(ImageElement.objects.filter(media__course=course)
                   .values_list("media_id", flat=True))
        used |= set(VideoElement.objects
                    .filter(media__isnull=False, media__course=course)
                    .values_list("media_id", flat=True))
        orphans = MediaAsset.objects.filter(course=course).exclude(pk__in=used)
        count = orphans.count()
        orphans.delete()
        self.stdout.write(f"gc-media: deleted {count} unreferenced assets")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_import_lal_content.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Full suite + format check**

Run:
```bash
uv run pytest tests/lal_import tests/test_lal_loader_units.py tests/test_import_lal_content.py -q
uv run ruff format --check scripts/lal_import courses/lal_loader courses/management/commands/import_lal_content.py
uv run ruff check scripts/lal_import courses/lal_loader courses/management/commands/import_lal_content.py
```
Expected: all pass; format clean; `ruff check` reports no F401/unused or other lint errors (fix any before committing).

- [ ] **Step 6: Commit**

```bash
git add courses/management/commands/import_lal_content.py tests/test_import_lal_content.py
git commit -m "feat(lal-loader): import_lal_content management command (end-to-end)"
```

---

## Task 18: Execution — Phase 1 scan, Phase 2 pilot, Phase 3 batches

This task has **no unit tests** — it runs the built pipeline against the real corpus and produces the human review artifacts. Each phase ends with an author checkpoint.

**Environment:** set `SOURCE_ROOT="C:/Users/krzys/Documents/teaching/LAL/html"` for the commands below.

- [ ] **Step 1: Real-file smoke check (BEFORE the bulk run)**

The parser tasks used only synthetic fragments; this is its first contact with a real file, and it is **guarded by explicit assertions** so a wrong structural assumption (a wrapping container `<div>`, math with literal `<`, DSL line shape) surfaces here — not silently across 21 unguarded parts. Run a throwaway check on the two files the spec names:

```bash
uv run python - <<'PY'
from pathlib import Path
from scripts.lal_import.lesson import parse_lesson
from scripts.lal_import.quiz import parse_quiz
root = Path(r"C:/Users/krzys/Documents/teaching/LAL/html/001_zbiory_liczbowe")
els, lflags = parse_lesson((root/"005_zbiory.html").read_text("utf-8"), "005_zbiory.html")
print("lesson types:", [e["type"] for e in els], "flags:", lflags)
# Hard gate: a clean real file must produce elements and NO flags/flagged elements.
assert els, "lesson produced no elements — structural assumption is wrong"
assert not any(e.get("flagged") for e in els) and not lflags, \
    f"unexpected flags on a clean lesson: {lflags}"
qs, qflags = parse_quiz((root/"039_zbiory_quiz.html").read_text("utf-8"))
print("quiz types:", [q["type"] for q in qs], "flags:", qflags)
assert qs, "quiz produced no questions"
assert not any(q.get("flagged") for q in qs) and not qflags, \
    f"unexpected flags on a clean quiz: {qflags}"
print("SMOKE OK")
PY
```
Expected: `SMOKE OK`. If a real file is wrapped in a container `<div>` (so the top-level walk sees one node), or shows unexpected flags, **fix the parser (e.g. descend into a single wrapping container) and add a regression test before proceeding** — do not run the bulk seed on a parser that flags a clean file.

- [ ] **Step 2: Phase 1 — seed all 21 parts**

For each 3-digit folder (in order), run the parser to seed JSON:

```bash
for d in "$SOURCE_ROOT"/[0-9][0-9][0-9]_*/; do \
  uv run python -m scripts.lal_import.parser "$(basename "$d")" --source-root "$SOURCE_ROOT"; \
done
```
Expected: `scripts/lal_import/out/<folder>/` created for all 21 parts, each with `manifest.json`, unit JSONs, and `flags.json`.

- [ ] **Step 3: Phase 1 — fill chapter names + build the review doc**

For each part's `manifest.json`, read the units' content and replace each chapter's `__PLACEHOLDER chapter N__` title and the `part.title` placeholder (restore Polish diacritics) with a human name. Then generate `docs/superpowers/plans/lal-review.md`: every Part → its Chapters (names) → Units, plus an aggregated summary of all `flags.json` entries (grouped by `kind`). **Checkpoint:** the author reviews/renames before any DB write.

- [ ] **Step 4: Phase 1 — resolve flags to zero (AI fixups)**

For every `flags.json` entry, either (a) add a parser rule and re-run `--refresh-unmapped` for that part, or (b) hand-edit the unit JSON to a native element. Confirm no unit JSON has `fully_mapped: false` remaining (except any deliberately author-signed `--allow-html` cases). **Checkpoint:** author signs off on the flag resolution.

- [ ] **Step 5: Phase 2 — pilot part 001 into the course**

```bash
uv run python manage.py import_lal_content --course matematyka --part 001_zbiory_liczbowe \
  --source-root "$SOURCE_ROOT" --set-policy
```
Then open the course in libli (`uv run python manage.py runserver`, or the project's run skill) and review part 001 **rendered** — video playback, math typesetting, spoilers, tables, the 5 quizzes. Confirm the pilot open-questions from spec §11 (video-ceiling enforcement point; `( )` radios; `TableElement` header-column support; numeric/ShortText matching). Adjust parser rules and re-seed with `--refresh-elements` (name-preserving) as needed. **Checkpoint:** author approves the rendered pilot; conversion rules are locked.

- [ ] **Step 6: Phase 3 — batch the remaining 20 parts**

For each remaining folder in order, load and spot-check:

```bash
uv run python manage.py import_lal_content --course matematyka --part <folder> \
  --source-root "$SOURCE_ROOT"
```
For a newly-covered pattern use parser `--refresh-unmapped` then re-load; for a rule correction use `--refresh-elements` then re-load (both preserve manifest names). After the final part, run one media GC:

```bash
uv run python manage.py import_lal_content --course matematyka --part 150_f_wykladnicza \
  --source-root "$SOURCE_ROOT" --gc-media
```
**Checkpoint:** author spot-checks each part; the populated course is the deliverable.

- [ ] **Step 7: Commit the review artifacts**

```bash
git add docs/superpowers/plans/lal-review.md
git commit -m "docs(lal-import): Phase-1 review doc (parts/chapters/flags)"
```
(Commit the `scripts/lal_import/out/` JSON only if the author chose "commit" for the intermediate artifacts — spec §11 open question.)

---

## Self-Review

**Spec coverage:** §3 tree/ordering/naming → Tasks 1–3, 17; §4.1 parser + guards → Tasks 6–10; §4.2 unit JSON/seed_hash → Tasks 6–9; §4.3 fixup invariant → Task 18 Step 3 (+ seed_hash only-parser-stamps enforced by Task 10's `_write_unit`); §4.4 loader/positional identity/prune/rebuild → Tasks 15–17; §4.5 manifest/flags → Tasks 10, 18; §5 element mapping + math escaping → Tasks 4, 6, 7, 14; §6 quiz DSL → Task 8; §7 media/dedup/allowlist/source-root → Tasks 11–13, 15; §8 phases → Task 18; depth policy → Task 15; embed allowlist → Task 12. All covered.

**Placeholder scan:** every code step contains real code; no "TBD"/"similar to above". The `manifest.json` chapter titles literally contain `__PLACEHOLDER…__` sentinels — that is intentional runtime data (filled in Phase 1), not a plan placeholder.

**Type consistency:** element dict schema (Global Constraints + Task 6 note) is used identically by the parser (Tasks 6–8) and the loader builder (Task 14): `text.body`, `math.latex`, `video/image.media_src`, `iframe.url/title`, `spoiler.label/body`, `table.data`, `choice.stem/multiple/choices[].{text,is_correct,feedback}`, `numeric.stem/value/tolerance`, `shorttext.stem/accepted/case_sensitive`. `seed_hash`/`unit_payload` names match across Tasks 9 and 10. Loader function names (`upsert_node`, `prune_orphans`, `rebuild_unit_elements`, `build_element`, `get_or_create_asset`, `resolve_source`, guard functions) match between definition and use in Task 17.
