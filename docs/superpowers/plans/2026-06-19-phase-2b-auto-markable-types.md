# Phase 2b — Auto-markable Types Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three keyboard-input, server-auto-marked question element types — short text (normalized match), short numeric (value ± tolerance), and fill-blanks (multi-gap) — that plug into Phase 2a's `QuestionElement`/`mark()` foundation and render formatively in lessons.

**Architecture:** Each new type is a concrete subclass of the existing abstract `QuestionElement` (own table + GFK content-type), authored through the existing per-unit editor (`FORM_FOR_TYPE` dispatch, add-menu cards, `save_element`), and answered through the existing `check_answer` round-trip (JS-fragment + no-JS full-POST). 2b generalizes three 2a touchpoints that are currently choice-specific: `check_answer`'s POST parsing (→ per-type `build_answer`), the feedback partial (→ per-type `feedback_context` + `{% include reveal_template %}`), and `build_lesson_context`'s prefetch/math-scan (→ per-type branches). No persistence (that is 2c).

**Tech Stack:** Django (server-rendered), `Decimal` arithmetic, `nh3` sanitizer, vendored KaTeX, `fetch`+`X-CSRFToken` transport, pytest + Playwright (`-m e2e`). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-06-19-phase-2b-auto-markable-types-design.md`

## Global Constraints

- **No new dependency.** Reuse Django, `courses.sanitize.sanitize_html`, vendored KaTeX, the `fetch`+`X-CSRFToken` transport.
- **Server is the sole marking authority.** `mark()` runs only server-side; clients submit raw input, never scores. Correctness signals (`accepted`/`value`/`tolerance`/`is_correct`) never reach a render except via `reveal` for the single element whose `element.pk == feedback_for_pk`.
- **No persistence.** `check_answer` marks and returns feedback; nothing is stored. No Response/Attempt model, no marking modes, no max-marks/attempts (all → 2c).
- **i18n gate.** Every new user-facing string is wrapped (`gettext`/`{% trans %}`) and has a Polish translation; `compilemessages -l pl` must pass.
- **DoD gate (run before declaring done):** `pytest -q` (e2e excluded) green; `pytest -m e2e` green; `ruff check .` + `ruff format --check .`; `python manage.py makemigrations --check --dry-run` (exactly one new migration, already created); `python manage.py check`; `python manage.py collectstatic --noinput`; `python manage.py compilemessages -l pl`.
- **Environment.** The virtualenv is `.venv`; invoke tools as `./.venv/Scripts/python.exe -m pytest …` (Windows / Git-Bash). Templates live under the repo-root `templates/` dir (NOT `courses/templates/`).
- **All-or-nothing verdict; float fraction.** Multi-blank `fraction = n_correct / n_blanks` is an inexact `float`; the formative verdict (`correct`) is the only behavioral signal in 2b. Tests assert `fraction` with `pytest.approx`, never `==` on non-terminating values.

---

## File Structure

**New files:**
- `courses/fillblank.py` — fill-blank marker parsing (U+FFFF sentinel strip, balanced-math masking, marker→token+accepted extraction) and the render-time token→`<input>` split/safe-join. Pure functions, no Django models.
- `templates/courses/elements/shorttextquestionelement.html`, `shortnumericquestionelement.html`, `fillblankquestionelement.html` — the three student-facing question forms (each its own isolated `<form>`). NOTE: created as stem-only stubs in Task 5 (the base `QuestionElement.render()` dispatches to `{model_name}.html`); filled with the real forms in Tasks 7–8.
- `templates/courses/elements/_reveal_choice.html`, `_reveal_shorttext.html`, `_reveal_shortnumeric.html`, `_reveal_fillblank.html` — per-type feedback reveal includes.
- `templates/courses/manage/editor/_edit_shorttextquestion.html`, `_edit_shortnumericquestion.html`, `_edit_fillblankquestion.html` — editor partials (host form includes `_edit_<type_key>.html`, so the filename suffix MUST equal the model-derived `type_key`).
- `tests/test_questions_2b_marking.py`, `tests/test_questions_2b_fillblank_parse.py`, `tests/test_questions_2b_forms.py`, `tests/test_questions_2b_authoring.py`, `tests/test_questions_2b_consumption.py`, `tests/test_e2e_questions_2b.py`, `tests/test_i18n_questions_2b.py`.

**Modified files:**
- `courses/marking.py` — add `normalize_text`, `parse_number`.
- `courses/models.py` — 3 new element models + `Blank`; `mark()`/`build_answer()`/`feedback_context()`/`render()`/`REVEAL_TEMPLATE` per type; `ChoiceQuestionElement` gains `build_answer()`/`feedback_context()`/`REVEAL_TEMPLATE` + widened `render()` signature; `ELEMENT_MODELS += 3`.
- `courses/element_forms.py` — 3 new forms + `FORM_FOR_TYPE` entries.
- `courses/builder.py` — `save_element` branches for the 3 new types.
- `courses/views_manage.py` — add 3 keys to the `element_add`/`element_save` allowlist tuples.
- `courses/views.py` — generalize `check_answer` (`build_answer` + `feedback_context`); `build_lesson_context` per-type prefetch/scan + union `question_ct_ids` + `submitted_values` seed; `lesson_unit` seeds `submitted_values`.
- `courses/templatetags/courses_extras.py` — `render_element` gains `submitted_values`; new `render_fill_blanks` tag.
- `templates/courses/elements/_question_feedback.html` — shared chrome + `{% include reveal_template %}`.
- `templates/courses/lesson_unit.html` — `render_element` call gains `submitted_values=`.
- `templates/courses/manage/editor/_add_menu.html` — 3 new add cards.
- `courses/static/courses/css/…` — minimal styles (token-driven) for text/numeric/blank inputs + reveal.
- `locale/pl/LC_MESSAGES/django.po` — Polish strings.

---

## Task 1: Marking primitives (`normalize_text`, `parse_number`)

**Files:**
- Modify: `courses/marking.py`
- Test: `tests/test_questions_2b_marking.py`

**Interfaces:**
- Produces: `normalize_text(s: str, *, case_sensitive: bool = False) -> str`; `parse_number(s: str) -> Decimal | None`. Consumed by the model `mark()` methods (Task 2) and the numeric form (Task 4).

- [ ] **Step 1: Write the failing test**

Create `tests/test_questions_2b_marking.py`:

```python
from decimal import Decimal

import pytest

from courses.marking import normalize_text
from courses.marking import parse_number


def test_normalize_text_trims_collapses_and_casefolds():
    assert normalize_text("  Hello   World ") == "hello world"
    assert normalize_text("ŁÓDŹ") == "łódź"
    assert normalize_text("a\tb\nc") == "a b c"


def test_normalize_text_case_sensitive_keeps_case_but_still_trims():
    assert normalize_text("  Foo  Bar ", case_sensitive=True) == "Foo Bar"
    assert normalize_text("Foo", case_sensitive=True) != normalize_text("foo")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("3,14", Decimal("3.14")),
        ("3.14", Decimal("3.14")),
        ("-3,14", Decimal("-3.14")),
        ("+5", Decimal("5")),
        (".5", Decimal("0.5")),
        (",5", Decimal("0.5")),
        ("-.5", Decimal("-0.5")),
        ("1,234", Decimal("1.234")),
        ("  42 ", Decimal("42")),
        ("5,", None),
        ("5.", None),
        (".", None),
        ("1 234", None),
        ("- 5", None),
        ("3 ,14", None),
        ("1,2,3", None),
        ("", None),
        ("abc", None),
    ],
)
def test_parse_number_grammar(raw, expected):
    assert parse_number(raw) == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_questions_2b_marking.py -q`
Expected: FAIL with `ImportError: cannot import name 'normalize_text'`.

- [ ] **Step 3: Implement the helpers**

Append to `courses/marking.py`:

```python
import re
from decimal import Decimal
from decimal import InvalidOperation

_WS_RE = re.compile(r"\s+")
# Optional sign; then either int part with optional [.,]frac, OR a leading-bare
# decimal (.5 / ,5). No thousands separators, no internal whitespace.
_NUM_RE = re.compile(r"^[+-]?(\d+([.,]\d+)?|[.,]\d+)$")


def normalize_text(s, *, case_sensitive=False):
    """Trim, collapse internal whitespace runs to one space, and (unless
    case_sensitive) casefold. The shared text-match primitive for short-text and
    fill-blank marking."""
    s = _WS_RE.sub(" ", (s or "").strip())
    return s if case_sensitive else s.casefold()


def parse_number(s):
    """Parse a single number to Decimal, or None if malformed. Accepts a single
    '.' OR ',' decimal separator (',' normalized to '.'); rejects thousands
    separators and any internal whitespace. See the spec §2.1 boundary table."""
    s = (s or "").strip()
    if not _NUM_RE.match(s):
        return None
    try:
        return Decimal(s.replace(",", "."))
    except InvalidOperation:
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_questions_2b_marking.py -q`
Expected: PASS (all rows).

- [ ] **Step 5: Lint and commit**

```bash
./.venv/Scripts/python.exe -m ruff check courses/marking.py tests/test_questions_2b_marking.py
./.venv/Scripts/python.exe -m ruff format courses/marking.py tests/test_questions_2b_marking.py
git add courses/marking.py tests/test_questions_2b_marking.py
git commit -m "feat(2b): normalize_text + parse_number marking primitives"
```

---

## Task 2: Models + migration (3 types + Blank; `mark()` + `build_answer()`)

**Files:**
- Modify: `courses/models.py` (after `Choice`, around line 391; `ELEMENT_MODELS` at lines 134-142)
- Create: `courses/migrations/0014_*` (generated)
- Test: append to `tests/test_questions_2b_marking.py`

**Interfaces:**
- Consumes: `normalize_text`, `parse_number` (Task 1); `QuestionElement`, `MarkResult` (2a).
- Produces:
  - `ShortTextQuestionElement(accepted: TextField, case_sensitive: BooleanField)` with `mark(answer: str)`, `build_answer(post) -> str`.
  - `ShortNumericQuestionElement(value: DecimalField, tolerance: DecimalField)` with `mark(answer: str)`, `build_answer(post) -> str`.
  - `FillBlankQuestionElement` (stem holds tokens) with `blanks` related, `mark(answer: list[str])`, `build_answer(post) -> list[str]`.
  - `Blank(question FK, accepted: TextField, case_sensitive: BooleanField, order: OrderField)`.
  - `render()`/`feedback_context()`/`REVEAL_TEMPLATE` are added in Tasks 6-8, NOT here.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_questions_2b_marking.py`:

```python
@pytest.mark.django_db
def test_shorttext_mark_multi_answer_normalized():
    from courses.models import ShortTextQuestionElement

    q = ShortTextQuestionElement.objects.create(
        stem="<p>Capital of France?</p>", accepted="Paris\nParyż"
    )
    assert q.mark("  paris ").correct is True
    assert q.mark("PARYŻ").correct is True
    assert q.mark("London").correct is False
    assert q.mark("London").fraction == 0.0
    assert q.mark("").correct is False  # empty → incorrect
    assert q.mark("Paris").reveal  # representative answer present on both verdicts


@pytest.mark.django_db
def test_shorttext_case_sensitive():
    from courses.models import ShortTextQuestionElement

    q = ShortTextQuestionElement.objects.create(accepted="Na", case_sensitive=True)
    assert q.mark("Na").correct is True
    assert q.mark("na").correct is False


@pytest.mark.django_db
def test_shortnumeric_mark_tolerance_and_decimal_comma():
    from decimal import Decimal

    from courses.models import ShortNumericQuestionElement

    q = ShortNumericQuestionElement.objects.create(
        value=Decimal("3.14"), tolerance=Decimal("0.01")
    )
    assert q.mark("3,15").correct is True  # within tolerance, comma decimal
    assert q.mark("3.13").correct is True  # at the boundary
    assert q.mark("3.20").correct is False
    assert q.mark("abc").correct is False  # unparseable → incorrect
    assert q.mark("").correct is False
    exact = ShortNumericQuestionElement.objects.create(value=Decimal("2"))
    assert exact.mark("2").correct is True and exact.mark("2.0001").correct is False


@pytest.mark.django_db
def test_fillblank_mark_per_blank_and_fraction():
    from courses.models import Blank
    from courses.models import FillBlankQuestionElement

    q = FillBlankQuestionElement.objects.create(stem="ignored-for-mark")
    Blank.objects.create(question=q, accepted="Paris")
    Blank.objects.create(question=q, accepted="Seine\nseine")

    full = q.mark(["paris", "Seine"])
    assert full.correct is True and full.fraction == pytest.approx(1.0)
    partial = q.mark(["paris", "Rhine"])
    assert partial.correct is False and partial.fraction == pytest.approx(0.5)
    # short list padded with "" → those blanks wrong
    assert q.mark(["paris"]).correct is False
    # long list truncated to n_blanks (extra entries ignored, still all-correct)
    assert q.mark(["paris", "Seine", "extra"]).correct is True
    # reveal is an ordered per-blank summary with the first accepted piece
    rev = list(partial.reveal)
    assert rev[0]["index"] == 0 and rev[0]["correct"] is True
    assert rev[1]["correct"] is False and rev[1]["accepted"] == "Seine"


@pytest.mark.django_db
def test_build_answer_shapes():
    from django.http import QueryDict

    from courses.models import Blank
    from courses.models import FillBlankQuestionElement
    from courses.models import ShortNumericQuestionElement
    from courses.models import ShortTextQuestionElement

    post = QueryDict(mutable=True)
    post["answer"] = "  foo "
    post.setlist("blank", ["a", "b"])
    assert ShortTextQuestionElement().build_answer(post) == "  foo "
    assert ShortNumericQuestionElement().build_answer(post) == "  foo "
    fb = FillBlankQuestionElement.objects.create(stem="x")
    Blank.objects.create(question=fb, accepted="a")
    assert fb.build_answer(post) == ["a", "b"]


@pytest.mark.django_db
def test_new_types_in_element_models():
    from courses.models import ELEMENT_MODELS

    for name in (
        "shorttextquestionelement",
        "shortnumericquestionelement",
        "fillblankquestionelement",
    ):
        assert name in ELEMENT_MODELS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_questions_2b_marking.py -q -k "shorttext or shortnumeric or fillblank or build_answer or element_models"`
Expected: FAIL with `ImportError: cannot import name 'ShortTextQuestionElement'`.

- [ ] **Step 3: Add the models**

In `courses/models.py`, extend `ELEMENT_MODELS` (lines 134-142):

```python
ELEMENT_MODELS = [
    "textelement",
    "imageelement",
    "videoelement",
    "iframeelement",
    "mathelement",
    "htmlelement",
    "choicequestionelement",
    "shorttextquestionelement",
    "shortnumericquestionelement",
    "fillblankquestionelement",
]
```

Add the two new imports at the top of `courses/models.py` (next to the existing `from courses.marking import MarkResult` at line 14 — do NOT re-import `MarkResult`):

```python
from courses.marking import normalize_text
from courses.marking import parse_number
```

Insert after the `Choice` class (after line 391):

```python
def _accepted_lines(blob):
    """Split a newline-delimited accepted-answers blob into non-blank lines."""
    return [ln for ln in (blob or "").splitlines() if ln.strip()]


class ShortTextQuestionElement(QuestionElement):
    """Free-text answer marked by normalized comparison against >=1 accepted lines."""

    accepted = models.TextField(blank=True)  # newline-delimited accepted answers
    case_sensitive = models.BooleanField(default=False)
    elements = GenericRelation(Element)

    def build_answer(self, post):
        return post.get("answer", "")

    def mark(self, answer):
        wanted = {
            normalize_text(a, case_sensitive=self.case_sensitive)
            for a in _accepted_lines(self.accepted)
        }
        got = normalize_text(answer, case_sensitive=self.case_sensitive)
        is_correct = got in wanted and got != "" if wanted else False
        lines = _accepted_lines(self.accepted)
        return MarkResult(
            correct=is_correct,
            fraction=1.0 if is_correct else 0.0,
            reveal=lines[0] if lines else "",
        )


class ShortNumericQuestionElement(QuestionElement):
    """Numeric answer marked correct iff within an absolute tolerance of value."""

    value = models.DecimalField(max_digits=20, decimal_places=8)
    tolerance = models.DecimalField(
        max_digits=20, decimal_places=8, default=0, validators=[MinValueValidator(0)]
    )
    elements = GenericRelation(Element)

    def build_answer(self, post):
        return post.get("answer", "")

    def mark(self, answer):
        n = parse_number(answer)
        is_correct = n is not None and abs(n - self.value) <= self.tolerance
        return MarkResult(
            correct=is_correct,
            fraction=1.0 if is_correct else 0.0,
            reveal={"value": self.value, "tolerance": self.tolerance},
        )


class FillBlankQuestionElement(QuestionElement):
    """Stem with ordered blank tokens; each gap text-matched against its own answers."""

    elements = GenericRelation(Element)

    def build_answer(self, post):
        return post.getlist("blank")

    def mark(self, answer):
        blanks = list(self.blanks.all())
        n = len(blanks)
        vals = list(answer or [])
        vals = (vals + [""] * n)[:n]  # pad short / truncate long → exactly n
        reveal = []
        n_correct = 0
        for i, blank in enumerate(blanks):
            lines = _accepted_lines(blank.accepted)
            wanted = {
                normalize_text(a, case_sensitive=blank.case_sensitive) for a in lines
            }
            got = normalize_text(vals[i], case_sensitive=blank.case_sensitive)
            ok = got in wanted and got != "" if wanted else False
            if ok:
                n_correct += 1
            reveal.append(
                {"index": i, "correct": ok, "accepted": lines[0] if lines else ""}
            )
        fraction = (n_correct / n) if n else 0.0
        return MarkResult(
            correct=(n_correct == n and n > 0),
            fraction=fraction,
            reveal=tuple(reveal),
        )


class Blank(models.Model):
    question = models.ForeignKey(
        FillBlankQuestionElement, on_delete=models.CASCADE, related_name="blanks"
    )
    accepted = models.TextField(blank=True)  # newline-delimited; parsed from {{a|b}}
    case_sensitive = models.BooleanField(default=False)  # reserved: always False in 2b
    order = OrderField(for_fields=["question"], blank=True)

    class Meta:
        ordering = ["order", "pk"]

    def __str__(self):
        return self.accepted
```

Add the validator import at the top of `courses/models.py` (near line 6, with the other validators):

```python
from django.core.validators import MinValueValidator
```

- [ ] **Step 4: Generate the migration**

Run: `./.venv/Scripts/python.exe manage.py makemigrations courses`
Expected: creates `courses/migrations/0014_*.py` adding `ShortTextQuestionElement`, `ShortNumericQuestionElement`, `FillBlankQuestionElement`, `Blank`, **and** an `AlterField` on `Element.content_type` (validation-only, mirrors 0010/0013). Verify there is exactly one new migration file.

- [ ] **Step 5: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_questions_2b_marking.py -q`
Expected: PASS. Then `./.venv/Scripts/python.exe manage.py makemigrations --check --dry-run` → no changes.

- [ ] **Step 6: Lint and commit**

```bash
./.venv/Scripts/python.exe -m ruff check courses/models.py
./.venv/Scripts/python.exe -m ruff format courses/models.py tests/test_questions_2b_marking.py
git add courses/models.py courses/migrations/0014_*.py tests/test_questions_2b_marking.py
git commit -m "feat(2b): short-text/numeric/fill-blank models + mark() + build_answer()"
```

---

## Task 3: Fill-blank parsing module (`courses/fillblank.py`)

**Files:**
- Create: `courses/fillblank.py`
- Test: `tests/test_questions_2b_fillblank_parse.py`

**Interfaces:**
- Produces:
  - `strip_sentinel(s: str) -> str` — remove all `U+FFFF` from author text.
  - `parse(clean_stem: str) -> tuple[str, list[list[str]]]` — returns `(token_stem, blanks)` where `token_stem` has each `{{…}}` replaced by a `￿{n}￿` token and `blanks[i]` is the i-th gap's non-blank accepted pieces. Raises `FillBlankError` on a bad/empty/unterminated marker or zero markers.
  - `render_inputs(token_stem: str, submitted_values) -> str` — safe HTML with each token replaced by an `<input name="blank">` (value from `submitted_values[n]`, escaped; missing index → empty).
  - `FillBlankError(ValueError)`.
- Consumed by: the fill-blank form (Task 4) and the `render_fill_blanks` tag (Task 8).

- [ ] **Step 1: Write the failing test**

Create `tests/test_questions_2b_fillblank_parse.py`:

```python
import pytest

from courses import fillblank
from courses.fillblank import FillBlankError


def test_parse_basic_and_alternates():
    token_stem, blanks = fillblank.parse("The capital is {{Paris|paris}}.")
    assert blanks == [["Paris", "paris"]]
    assert token_stem == "The capital is ￿0￿."


def test_parse_multiple_and_adjacent():
    _, blanks = fillblank.parse("{{a}} and {{b}}{{c}}")
    assert blanks == [["a"], ["b"], ["c"]]


def test_parse_drops_blank_pieces():
    _, blanks = fillblank.parse("x {{a|}}")
    assert blanks == [["a"]]


@pytest.mark.parametrize("stem", ["{{}}", "{{|}}", "no markers here", "open {{ only"])
def test_parse_rejects(stem):
    with pytest.raises(FillBlankError):
        fillblank.parse(stem)


def test_parse_skips_balanced_math_braces():
    # {{ inside balanced \(...\) is LaTeX, not a marker; a real blank still parses.
    token_stem, blanks = fillblank.parse(r"\(x^{{2}}\) equals {{four}}")
    assert blanks == [["four"]]
    assert r"\(x^{{2}}\)" in token_stem  # math restored verbatim
    assert "￿0￿" in token_stem


def test_parse_unbalanced_math_does_not_swallow_markers():
    # An unterminated \( stays literal; the marker after it is still found.
    _, blanks = fillblank.parse(r"open \( math {{gap}}")
    assert blanks == [["gap"]]


def test_parse_markers_are_single_line():
    with pytest.raises(FillBlankError):
        fillblank.parse("{{a\nb}}")  # newline inside marker → unterminated


def test_strip_sentinel_removes_uffff():
    assert fillblank.strip_sentinel("a￿0￿b") == "a0b"


def test_render_inputs_interleaves_and_escapes():
    html = fillblank.render_inputs("A ￿0￿ B ￿1￿", ["x", '"y"'])
    assert html.count("<input") == 2
    assert "A " in html and " B " in html
    assert "&quot;y&quot;" in html  # value escaped
    assert 'name="blank"' in html


def test_render_inputs_defensive_on_short_values():
    html = fillblank.render_inputs("￿0￿ ￿1￿", ["only"])
    assert html.count("<input") == 2  # missing index → empty value, no IndexError
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_questions_2b_fillblank_parse.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'courses.fillblank'`.

- [ ] **Step 3: Implement the module**

Create `courses/fillblank.py`:

```python
"""Fill-blank stem parsing and render-time token substitution.

Author flow (in the form): sanitize_html(raw) -> strip_sentinel -> parse(). parse()
masks balanced KaTeX spans, extracts {{a|b}} markers into ordered Blank answer
lists, and replaces each marker with an opaque token `\\uffff{n}\\uffff`. The
sentinel U+FFFF is stripped from author input first (strip_sentinel), so a stored
token can never be forged from prose. Render flow (in the tag): render_inputs()
splits the token-stem and safe-joins server-built <input>s — the only unescaped
insertions.
"""

import re

from django.utils.html import format_html
from django.utils.safestring import mark_safe

SENTINEL = "￿"
_TOKEN = SENTINEL + "{}" + SENTINEL
_TOKEN_RE = re.compile(SENTINEL + r"(\d+)" + SENTINEL)
# Parse-time, never-persisted math placeholder. 'M' prefix keeps it disjoint from
# the digits-only blank token regex, so the two never cross-match.
_MATH_PLACEHOLDER = SENTINEL + "M{}" + SENTINEL
_MATH_PLACEHOLDER_RE = re.compile(SENTINEL + r"M(\d+)" + SENTINEL)
# Balanced KaTeX spans, non-greedy, may span lines (display math).
_MATH_RE = re.compile(r"\\\(.*?\\\)|\\\[.*?\\\]", re.DOTALL)
# Marker: non-greedy, allows empty interior (so {{}} is matched then rejected);
# NOT DOTALL → a marker may not span lines (single-line invariant).
_MARKER_RE = re.compile(r"\{\{(.*?)\}\}")


class FillBlankError(ValueError):
    """Raised on a malformed/empty/unterminated marker or a stem with no blanks."""


def strip_sentinel(s):
    return (s or "").replace(SENTINEL, "")


def _mask_math(s):
    spans = []

    def _grab(m):
        spans.append(m.group(0))
        return _MATH_PLACEHOLDER.format(len(spans) - 1)

    return _MATH_RE.sub(_grab, s), spans


def _restore_math(s, spans):
    return _MATH_PLACEHOLDER_RE.sub(lambda m: spans[int(m.group(1))], s)


def parse(clean_stem):
    """clean_stem: sanitized author stem with the sentinel already stripped.
    Returns (token_stem, blanks). Raises FillBlankError on a bad stem."""
    masked, spans = _mask_math(clean_stem)
    blanks = []

    def _swap(m):
        pieces = [p.strip() for p in m.group(1).split("|")]
        pieces = [p for p in pieces if p]
        if not pieces:
            raise FillBlankError("empty marker")
        blanks.append(pieces)
        return _TOKEN.format(len(blanks) - 1)

    token_masked = _MARKER_RE.sub(_swap, masked)
    if "{{" in token_masked:
        raise FillBlankError("unterminated marker")
    if not blanks:
        raise FillBlankError("no blanks")
    return _restore_math(token_masked, spans), blanks


def render_inputs(token_stem, submitted_values=None):
    """Split a stored token-stem and safe-join server-built <input>s. The text
    segments are already-sanitized HTML (trusted); only the <input>s are inserted,
    with the repopulation value HTML-escaped."""
    vals = list(submitted_values or [])
    parts = _TOKEN_RE.split(token_stem or "")
    out = []
    for i, part in enumerate(parts):
        if i % 2 == 0:
            out.append(part)  # trusted sanitized HTML
        else:
            n = int(part)
            v = vals[n] if 0 <= n < len(vals) else ""
            out.append(
                str(
                    format_html(
                        '<input type="text" name="blank" value="{}" '
                        'class="question__blank-input" autocomplete="off">',
                        v,
                    )
                )
            )
    return mark_safe("".join(out))  # noqa: S308 — segments sanitized; inputs escaped
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_questions_2b_fillblank_parse.py -q`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
./.venv/Scripts/python.exe -m ruff check courses/fillblank.py tests/test_questions_2b_fillblank_parse.py
./.venv/Scripts/python.exe -m ruff format courses/fillblank.py tests/test_questions_2b_fillblank_parse.py
git add courses/fillblank.py tests/test_questions_2b_fillblank_parse.py
git commit -m "feat(2b): fill-blank marker parsing + token render (courses/fillblank.py)"
```

---

## Task 4: Authoring forms (`element_forms.py`)

**Files:**
- Modify: `courses/element_forms.py` (imports near line 6; `FORM_FOR_TYPE` at lines 197-205)
- Test: `tests/test_questions_2b_forms.py`

**Interfaces:**
- Consumes: the three models (Task 2), `courses.fillblank` (Task 3).
- Produces: `ShortTextQuestionElementForm`, `ShortNumericQuestionElementForm`, `FillBlankQuestionElementForm`; `FORM_FOR_TYPE` keys `"shorttextquestion"`, `"shortnumericquestion"`, `"fillblankquestion"`. The fill-blank form exposes `form.parsed_blanks: list[list[str]]` after `is_valid()` (consumed by the builder, Task 5).

> **`type_key` naming (critical for the edit path).** The `element_form` edit view derives the key as `el.content_object.__class__.__name__.lower().replace("element","")` — so `ShortTextQuestionElement` → `"shorttextquestion"`, `ShortNumericQuestionElement` → `"shortnumericquestion"`, `FillBlankQuestionElement` → `"fillblankquestion"`. The `FORM_FOR_TYPE` keys, the `element_add`/`element_save` allowlist entries, the add-card `data-add-type`, and the `_edit_<type_key>.html` partial filenames MUST all use these full derived keys (exactly as 2a's `"choicequestion"` matches `ChoiceQuestionElement`). The student-facing question/reveal template filenames (`shorttext.html`, `_reveal_shorttext.html`, …) are referenced directly in `render()`/`REVEAL_TEMPLATE` and stay short — they are independent of `type_key`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_questions_2b_forms.py`:

```python
import pytest

from courses.element_forms import FORM_FOR_TYPE


def _form(key, data):
    return FORM_FOR_TYPE[key](data=data)


@pytest.mark.django_db
def test_shorttext_form_requires_one_accepted_line():
    assert _form("shorttextquestion", {"stem": "<p>q</p>", "accepted": "Paris"}).is_valid()
    bad = _form("shorttextquestion", {"stem": "<p>q</p>", "accepted": "   \n  "})
    assert not bad.is_valid() and "accepted" in bad.errors


@pytest.mark.django_db
def test_shortnumeric_form_accepts_comma_decimal_and_rejects_negative_tolerance():
    from decimal import Decimal

    ok = _form(
        "shortnumericquestion", {"stem": "<p>q</p>", "value": "3,14", "tolerance": "0,01"}
    )
    assert ok.is_valid()
    assert ok.cleaned_data["value"] == Decimal("3.14")
    assert ok.cleaned_data["tolerance"] == Decimal("0.01")
    bad = _form("shortnumericquestion", {"stem": "<p>q</p>", "value": "abc"})
    assert not bad.is_valid() and "value" in bad.errors
    neg = _form("shortnumericquestion", {"stem": "<p>q</p>", "value": "1", "tolerance": "-1"})
    assert not neg.is_valid() and "tolerance" in neg.errors


@pytest.mark.django_db
def test_fillblank_form_parses_markers_and_rewrites_stem():
    f = _form("fillblankquestion", {"stem": "<p>The capital is {{Paris|paris}}.</p>"})
    assert f.is_valid(), f.errors
    assert f.parsed_blanks == [["Paris", "paris"]]
    assert "{{" not in f.cleaned_data["stem"]  # stem rewritten to a token
    assert "￿0￿" in f.cleaned_data["stem"]


@pytest.mark.django_db
def test_fillblank_form_rejects_stem_without_markers():
    f = _form("fillblankquestion", {"stem": "<p>no blanks here</p>"})
    assert not f.is_valid() and "stem" in f.errors


@pytest.mark.django_db
def test_fillblank_form_strips_forged_sentinel_from_author_stem():
    # An author pasting a literal U+FFFF token cannot forge a placeholder.
    f = _form("fillblankquestion", {"stem": "<p>forged ￿0￿ then {{real}}</p>"})
    assert f.is_valid(), f.errors
    assert f.parsed_blanks == [["real"]]
    # exactly one token (index 0), the real blank — the forged one was stripped
    assert f.cleaned_data["stem"].count("￿") == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_questions_2b_forms.py -q`
Expected: FAIL with `KeyError: 'shorttext'`.

- [ ] **Step 3: Implement the forms**

In `courses/element_forms.py`, add to the model imports (near line 6):

```python
from courses import fillblank
from courses.marking import parse_number
from courses.models import FillBlankQuestionElement
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from courses.sanitize import sanitize_html
```

Add the three form classes (after `ChoiceFormSet`/`build_choice_formset`, before `FORM_FOR_TYPE`):

```python
class ShortTextQuestionElementForm(forms.ModelForm):
    class Meta:
        model = ShortTextQuestionElement
        fields = ["stem", "explanation", "accepted", "case_sensitive"]
        widgets = {
            "stem": forms.Textarea(attrs={"rows": 3, "data-rte-source": ""}),
            "explanation": forms.Textarea(attrs={"rows": 2, "data-rte-source": ""}),
            "accepted": forms.Textarea(attrs={"rows": 3}),
        }

    def clean_accepted(self):
        value = self.cleaned_data.get("accepted", "")
        if not [ln for ln in value.splitlines() if ln.strip()]:
            raise forms.ValidationError(_("Add at least one accepted answer."))
        return value


class ShortNumericQuestionElementForm(forms.ModelForm):
    class Meta:
        model = ShortNumericQuestionElement
        fields = ["stem", "explanation", "value", "tolerance"]
        widgets = {
            "stem": forms.Textarea(attrs={"rows": 3, "data-rte-source": ""}),
            "explanation": forms.Textarea(attrs={"rows": 2, "data-rte-source": ""}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Replace the locale-sensitive DecimalField parsing with parse_number so
        # authors get the same ','/'.'  leniency as students (PL/EN bilingual).
        self.fields["value"] = forms.CharField()
        self.fields["tolerance"] = forms.CharField(required=False)

    def _num(self, field, *, required):
        raw = self.cleaned_data.get(field, "")
        if not raw and not required:
            return None
        parsed = parse_number(raw)
        if parsed is None:
            raise forms.ValidationError(_("Enter a number (e.g. 3.14 or 3,14)."))
        return parsed

    def clean_value(self):
        return self._num("value", required=True)

    def clean_tolerance(self):
        parsed = self._num("tolerance", required=False)
        if parsed is None:
            return 0
        if parsed < 0:
            raise forms.ValidationError(_("Tolerance cannot be negative."))
        return parsed


class FillBlankQuestionElementForm(forms.ModelForm):
    parsed_blanks = None  # list[list[str]] after a successful clean()

    class Meta:
        model = FillBlankQuestionElement
        fields = ["stem", "explanation"]
        widgets = {
            "stem": forms.Textarea(attrs={"rows": 3, "data-rte-source": ""}),
            "explanation": forms.Textarea(attrs={"rows": 2, "data-rte-source": ""}),
        }

    def clean_stem(self):
        raw = self.cleaned_data.get("stem", "")
        clean = fillblank.strip_sentinel(sanitize_html(raw))
        try:
            token_stem, blanks = fillblank.parse(clean)
        except fillblank.FillBlankError:
            raise forms.ValidationError(
                _("Mark at least one blank with {{answer}} (use | for alternatives).")
            ) from None
        self.parsed_blanks = blanks
        return token_stem
```

Note: `ShortNumericQuestionElementForm.clean_value/clean_tolerance` return `Decimal`s that `ModelForm._post_clean` assigns to the `DecimalField` model fields; a value exceeding `max_digits=20`/`decimal_places=8` then raises a model-level `ValidationError` surfaced on the field (the spec's "validation error, not silent quantize").

Extend `FORM_FOR_TYPE` (lines 197-205):

```python
FORM_FOR_TYPE = {
    "text": TextElementForm,
    "image": ImageElementForm,
    "video": VideoElementForm,
    "iframe": IframeElementForm,
    "math": MathElementForm,
    "html": HtmlElementForm,
    "choicequestion": ChoiceQuestionElementForm,
    "shorttextquestion": ShortTextQuestionElementForm,
    "shortnumericquestion": ShortNumericQuestionElementForm,
    "fillblankquestion": FillBlankQuestionElementForm,
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_questions_2b_forms.py -q`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
./.venv/Scripts/python.exe -m ruff check courses/element_forms.py tests/test_questions_2b_forms.py
./.venv/Scripts/python.exe -m ruff format courses/element_forms.py tests/test_questions_2b_forms.py
git add courses/element_forms.py tests/test_questions_2b_forms.py
git commit -m "feat(2b): short-text/numeric/fill-blank authoring forms + FORM_FOR_TYPE"
```

---

## Task 5: Builder save + dispatch allowlists + editor partials + add cards

**Files:**
- Modify: `courses/builder.py` (`save_element`, lines 202-262)
- Modify: `courses/views_manage.py` (allowlist tuples at lines 748-756 and 771-779)
- Create: `templates/courses/manage/editor/_edit_shorttextquestion.html`, `_edit_shortnumericquestion.html`, `_edit_fillblankquestion.html`
- Modify: `templates/courses/manage/editor/_add_menu.html`
- Test: `tests/test_questions_2b_authoring.py`

**Interfaces:**
- Consumes: `FORM_FOR_TYPE` (Task 4), `FillBlankQuestionElementForm.parsed_blanks` (Task 4), models (Task 2). All `type_key`s are the model-derived full keys `shorttextquestion`/`shortnumericquestion`/`fillblankquestion` (see the Task 4 naming note).
- Produces: working create/edit/delete of all three types through `element_save`; fill-blank `Blank` rows rebuilt on each save.

- [ ] **Step 1: Write the failing test**

Create `tests/test_questions_2b_authoring.py`:

```python
import pytest
from django.urls import reverse

from courses.models import Blank
from courses.models import Element
from courses.models import FillBlankQuestionElement
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa


def _unit(course):
    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )


def _base(unit, type_key, element="new"):
    return {
        "ctx": "editor",
        "type": type_key,
        "element": element,
        "unit": unit.pk,
        "unit_token": unit.updated.isoformat(),
        "el_title": "",
        "explanation": "",
    }


@pytest.mark.django_db
def test_add_card_is_render_only_for_each_type(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    for key in ("shorttextquestion", "shortnumericquestion", "fillblankquestion"):
        resp = client.post(
            reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
            {"type": key, "unit": unit.pk},
            HTTP_X_REQUESTED_WITH="fetch",
        )
        assert resp.status_code == 200
    assert Element.objects.filter(unit=unit).count() == 0


@pytest.mark.django_db
def test_save_shorttext(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    data = _base(unit, "shorttextquestion")
    data.update(stem="<p>Capital?</p>", accepted="Paris\nParyż")
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        data,
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    q = ShortTextQuestionElement.objects.get()
    assert q.accepted == "Paris\nParyż"
    assert Element.objects.filter(unit=unit, object_id=q.pk).count() == 1


@pytest.mark.django_db
def test_save_shortnumeric_comma_decimal(client):
    from decimal import Decimal

    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    data = _base(unit, "shortnumericquestion")
    data.update(stem="<p>Pi?</p>", value="3,14", tolerance="0,01")
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        data,
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    q = ShortNumericQuestionElement.objects.get()
    assert q.value == Decimal("3.14") and q.tolerance == Decimal("0.01")


@pytest.mark.django_db
def test_save_fillblank_creates_blanks_and_rebuilds_on_edit(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    data = _base(unit, "fillblankquestion")
    data["stem"] = "<p>{{Paris}} on the {{Seine|seine}}.</p>"
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        data,
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    q = FillBlankQuestionElement.objects.get()
    assert [b.accepted for b in q.blanks.all()] == ["Paris", "Seine\nseine"]
    assert [b.order for b in q.blanks.all()] == [0, 1]
    el = Element.objects.get(unit=unit, object_id=q.pk)

    # Edit: a new single-blank stem fully replaces the old blanks.
    unit.refresh_from_db()
    edit = _base(unit, "fillblankquestion", element=str(el.pk))
    edit["stem"] = "<p>Just {{one}}.</p>"
    resp2 = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        edit,
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp2.status_code == 200
    q.refresh_from_db()
    assert [b.accepted for b in q.blanks.all()] == ["one"]
    assert Blank.objects.filter(question=q).count() == 1  # old blanks gone


@pytest.mark.django_db
def test_save_fillblank_invalid_returns_422_and_persists_nothing(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    data = _base(unit, "fillblankquestion")
    data["stem"] = "<p>no markers</p>"
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        data,
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 422
    assert FillBlankQuestionElement.objects.count() == 0
    assert Blank.objects.count() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_questions_2b_authoring.py -q`
Expected: FAIL — `element_add` returns 400 (`bad type`) for the new keys.

- [ ] **Step 3: Add the type keys to both allowlist tuples**

In `courses/views_manage.py`, both `element_add` (lines 748-756) and `element_save` (lines 771-779) gate on a fixed tuple. Add the three keys to **each**:

```python
    if type_key not in (
        "text",
        "image",
        "video",
        "iframe",
        "math",
        "html",
        "choicequestion",
        "shorttextquestion",
        "shortnumericquestion",
        "fillblankquestion",
    ):
        return HttpResponseBadRequest("bad type")
```

- [ ] **Step 4: Add the builder save branch**

In `courses/builder.py` `save_element`, the current `if type_key == "choicequestion":` block (line 218) is followed by `else:` (line 247). Insert a new branch **before** the `else`, after the choicequestion block:

```python
    elif type_key == "fillblankquestion":
        from courses.element_forms import FillBlankQuestionElementForm

        form = FillBlankQuestionElementForm(data=post_data, instance=instance)
        if not form.is_valid():
            raise ElementFormInvalid(form)
        obj = form.save()  # token-stem stored; QuestionElement.save() sanitises
        obj.blanks.all().delete()  # rebuild from the freshly-parsed markers
        from courses.models import Blank

        for pieces in form.parsed_blanks:
            Blank.objects.create(question=obj, accepted="\n".join(pieces))
```

The short-text and short-numeric types need no special handling — they flow through the existing `else` branch (a plain `FORM_FOR_TYPE[type_key](...)` + `form.save()`), since `FORM_FOR_TYPE` already has their entries and they take no `course` extra.

- [ ] **Step 5: Create the editor partials**

The host form (`_host_form.html:14`) includes `_edit_<type_key>.html`, so the filename suffix MUST be the full model-derived `type_key`. Create `templates/courses/manage/editor/_edit_shorttextquestion.html`:

```html
{% load i18n %}
<div class="el-editor el-editor--question">
  <label class="el-editor__label">{% trans "Question" %}</label>
  <div class="el-editor--text">
    {% include "courses/manage/editor/_rte_toolbar.html" %}
    <textarea name="stem" class="rte-source" data-rte-source rows="3">{{ form.stem.value|default:"" }}</textarea>
  </div>
  {% for e in form.stem.errors %}<p class="field-error">{{ e }}</p>{% endfor %}

  <label class="el-editor__label">{% trans "Accepted answers (one per line)" %}</label>
  <textarea name="accepted" rows="3">{{ form.accepted.value|default:"" }}</textarea>
  {% for e in form.accepted.errors %}<p class="field-error">{{ e }}</p>{% endfor %}

  <label class="el-editor__check">
    <input type="checkbox" name="case_sensitive" {% if form.case_sensitive.value %}checked{% endif %}>
    {% trans "Case sensitive" %}
  </label>

  <label class="el-editor__label">{% trans "Explanation (optional)" %}</label>
  <div class="el-editor--text">
    {% include "courses/manage/editor/_rte_toolbar.html" %}
    <textarea name="explanation" class="rte-source" data-rte-source rows="2">{{ form.explanation.value|default:"" }}</textarea>
  </div>
</div>
```

Create `templates/courses/manage/editor/_edit_shortnumericquestion.html`:

```html
{% load i18n %}
<div class="el-editor el-editor--question">
  <label class="el-editor__label">{% trans "Question" %}</label>
  <div class="el-editor--text">
    {% include "courses/manage/editor/_rte_toolbar.html" %}
    <textarea name="stem" class="rte-source" data-rte-source rows="3">{{ form.stem.value|default:"" }}</textarea>
  </div>
  {% for e in form.stem.errors %}<p class="field-error">{{ e }}</p>{% endfor %}

  <label class="el-editor__label">{% trans "Correct value" %}</label>
  <input type="text" name="value" inputmode="decimal" value="{{ form.value.value|default:'' }}">
  {% for e in form.value.errors %}<p class="field-error">{{ e }}</p>{% endfor %}

  <label class="el-editor__label">{% trans "Tolerance (±, optional)" %}</label>
  <input type="text" name="tolerance" inputmode="decimal" value="{{ form.tolerance.value|default:'' }}">
  {% for e in form.tolerance.errors %}<p class="field-error">{{ e }}</p>{% endfor %}

  <label class="el-editor__label">{% trans "Explanation (optional)" %}</label>
  <div class="el-editor--text">
    {% include "courses/manage/editor/_rte_toolbar.html" %}
    <textarea name="explanation" class="rte-source" data-rte-source rows="2">{{ form.explanation.value|default:"" }}</textarea>
  </div>
</div>
```

Create `templates/courses/manage/editor/_edit_fillblankquestion.html`:

```html
{% load i18n %}
<div class="el-editor el-editor--question">
  <label class="el-editor__label">{% trans "Sentence with blanks" %}</label>
  <p class="el-editor__hint">{% trans "Mark each blank with {{answer}}. Use | for alternatives, e.g. {{colour|color}}." %}</p>
  <div class="el-editor--text">
    {% include "courses/manage/editor/_rte_toolbar.html" %}
    <textarea name="stem" class="rte-source" data-rte-source rows="3">{{ form.stem.value|default:"" }}</textarea>
  </div>
  {% for e in form.stem.errors %}<p class="field-error">{{ e }}</p>{% endfor %}

  <label class="el-editor__label">{% trans "Explanation (optional)" %}</label>
  <div class="el-editor--text">
    {% include "courses/manage/editor/_rte_toolbar.html" %}
    <textarea name="explanation" class="rte-source" data-rte-source rows="2">{{ form.explanation.value|default:"" }}</textarea>
  </div>
</div>
```

Note on the fill-blank edit `stem` value: on an edit re-render the textarea would show the *token-stem* (`￿0￿`), not the author's `{{…}}`. This is acceptable for 2b — the spec defers a marker round-trip; the editor partial shows stored content and the author re-marks if they change the stem. (Do not attempt to reverse tokens→markers in 2b.)

- [ ] **Step 6: Add the add-menu cards**

In `templates/courses/manage/editor/_add_menu.html`, add three cards after the choice cards (line 12):

```html
    <button type="button" class="typecard" data-add-type="shorttextquestion"><span class="ic">⌨</span>{% trans "Short text" %}</button>
    <button type="button" class="typecard" data-add-type="shortnumericquestion"><span class="ic">#</span>{% trans "Short numeric" %}</button>
    <button type="button" class="typecard" data-add-type="fillblankquestion"><span class="ic">▭</span>{% trans "Fill in the blanks" %}</button>
```

The add JS posts `data-add-type` verbatim as `type`; these keys are 1:1 with `type_key` (no translation layer like choice's `choice-single`/`choice-multi`), so `element_add` accepts them directly.

- [ ] **Step 7: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_questions_2b_authoring.py -q`
Expected: PASS.

- [ ] **Step 8: Lint and commit**

```bash
./.venv/Scripts/python.exe -m ruff check courses/builder.py courses/views_manage.py tests/test_questions_2b_authoring.py
./.venv/Scripts/python.exe -m ruff format courses/builder.py courses/views_manage.py tests/test_questions_2b_authoring.py
git add courses/builder.py courses/views_manage.py templates/courses/manage/editor/_edit_shorttextquestion.html templates/courses/manage/editor/_edit_shortnumericquestion.html templates/courses/manage/editor/_edit_fillblankquestion.html templates/courses/manage/editor/_add_menu.html tests/test_questions_2b_authoring.py
git commit -m "feat(2b): builder save + dispatch + editor partials + add cards"
```

---

## Task 6: Generalize `check_answer` + feedback partial (2a refactor; choice stays green)

**Files:**
- Modify: `courses/models.py` (`ChoiceQuestionElement`, lines 326-373)
- Modify: `courses/views.py` (`check_answer`, lines 186-224)
- Modify: `templates/courses/elements/_question_feedback.html`
- Create: `templates/courses/elements/_reveal_choice.html`
- Test: `tests/test_questions_consumption.py` (existing 2a suite must stay green)

**Interfaces:**
- Produces on `QuestionElement` subclasses: `feedback_context(self, mark_result) -> dict` and a `REVEAL_TEMPLATE` class attribute. `ChoiceQuestionElement` also gains `build_answer(self, post) -> set[int]`.
- `check_answer` becomes type-agnostic: `answer = question.build_answer(request.POST)`; JS branch renders `_question_feedback.html` with `question.feedback_context(result)`.

- [ ] **Step 1: Add `build_answer`/`feedback_context`/`REVEAL_TEMPLATE` to `ChoiceQuestionElement`**

First, **add the shared `feedback_context` + a `REVEAL_TEMPLATE` slot to the `QuestionElement` BASE** (note: the base already has a `render()` method from Task 5 — leave it; Task 7 extends it). Insert into `class QuestionElement` (after its `render`, before the abstract `mark`):

```python
    REVEAL_TEMPLATE = None  # each concrete type sets its per-type reveal include

    def feedback_context(self, mark_result):
        # The dict the JS-fragment check_answer feeds to _question_feedback.html.
        # Shared by all question types; ChoiceQuestionElement overrides to add choices.
        return {
            "el": self,
            "mark_result": mark_result,
            "reveal_template": self.REVEAL_TEMPLATE,
        }
```

Then, in `ChoiceQuestionElement` (after `correct_ids`, before `mark`), add its `REVEAL_TEMPLATE`, `build_answer`, and a `feedback_context` **override** that adds the `choices` queryset:

```python
    REVEAL_TEMPLATE = "courses/elements/_reveal_choice.html"

    def build_answer(self, post):
        # getlist + int-coerce + validate against own choices (logic moved out of
        # the view); foreign/forged ids are dropped, never error-leaking.
        valid = {c.pk for c in self.choices.all()}
        submitted = set()
        for raw in post.getlist("choice"):
            try:
                submitted.add(int(raw))
            except (TypeError, ValueError):
                continue
        return submitted & valid

    def feedback_context(self, mark_result):
        ctx = super().feedback_context(mark_result)
        ctx["choices"] = list(self.choices.all())
        return ctx
```

Also **widen `ChoiceQuestionElement.render`'s signature to add `submitted_values=None`** (ignored by choice — it repopulates from `selected_ids`) and add `"reveal_template": self.REVEAL_TEMPLATE` to its context dict. This makes all four `QuestionElement.render` signatures identical *now*, so Task 7's `render_element` can forward `submitted_values` to every type without a `TypeError`. Replace the method header and the `return`:

```python
    def render(
        self,
        *,
        element=None,
        feedback_for_pk=None,
        selected_ids=frozenset(),
        submitted_values=None,
        mark_result=None,
    ):
        # `element` is the Element join-row (carries the unit + pk for the form
        # action and the per-element feedback gate). `submitted_values` is accepted
        # for signature uniformity but unused (choices repopulate from selected_ids).
        choices = list(self.choices.all())
        unit = element.unit if element is not None else None
        return render_to_string(
            "courses/elements/choicequestion.html",
            {
                "el": self,
                "element": element,
                "choices": choices,
                "slug": unit.course.slug if unit is not None else "",
                "node_pk": unit.pk if unit is not None else "",
                "feedback_for_pk": feedback_for_pk,
                "selected_ids": set(selected_ids or ()),
                "mark_result": mark_result,
                "reveal_template": self.REVEAL_TEMPLATE,
            },
        )
```

- [ ] **Step 2: Split the feedback partial**

Replace `templates/courses/elements/_question_feedback.html` with the shared chrome + per-type include:

```html
{% load i18n %}
{% if mark_result %}
  <div class="question__verdict {% if mark_result.correct %}is-correct{% else %}is-incorrect{% endif %}">
    {% if mark_result.correct %}
      <span class="question__glyph" aria-hidden="true">✓</span>{% trans "Correct" %}
    {% else %}
      <span class="question__glyph" aria-hidden="true">✗</span>{% trans "Incorrect" %}
    {% endif %}
  </div>
  {% include reveal_template %}
  {% if el.explanation %}
    <div class="question__explanation">{{ el.explanation|safe }}</div>
  {% endif %}
{% endif %}
```

Create `templates/courses/elements/_reveal_choice.html` (the extracted 2a loop):

```html
{% load i18n %}
<ul class="question__reveal">
  {% for c in choices %}
    <li class="question__reveal-item {% if c.pk in mark_result.reveal %}answer-correct{% endif %}">
      <span>{{ c.text }}</span>
      {% if c.pk in mark_result.reveal %}<span class="question__tick" aria-hidden="true">✓</span>{% endif %}
    </li>
  {% endfor %}
</ul>
```

- [ ] **Step 3: Generalize `check_answer`**

Replace the body of `check_answer` after the `question` type gate (`courses/views.py`, lines 200-224) with:

```python
    answer = question.build_answer(request.POST)
    result = question.mark(answer)  # NOTHING is persisted

    if _wants_fragment(request):
        return render(
            request,
            "courses/elements/_question_feedback.html",
            question.feedback_context(result),
        )
    # No-JS: re-render the whole lesson unit with this question's feedback inline.
    ctx = build_lesson_context(node, request.user)
    selected = answer if isinstance(answer, (set, frozenset)) else frozenset()
    submitted = None if isinstance(answer, (set, frozenset)) else answer
    ctx.update(
        feedback_for_pk=element.pk,
        selected_ids=selected,
        submitted_values=submitted,
        mark_result=result,
    )
    return render(request, "courses/lesson_unit.html", ctx)
```

Remove the now-unused `choices`/`valid_ids`/`submitted` block (old lines 200-208) — `build_answer` owns it. Keep the `isinstance(question, QuestionElement)` gate (already broad — do not narrow it). The `selected_ids`/`submitted_values` split lets choice keep its id-set channel while the new types use the raw-string channel; `build_lesson_context` will seed the `submitted_values` default in Task 7.

NOTE: `build_lesson_context` does not yet accept/define `submitted_values` — until Task 7 seeds it, the no-JS branch's `ctx.update(submitted_values=…)` just adds a key the template ignores. The choice consumption tests use the JS-fragment path (`feedback_context`) and the no-JS path (which still renders choice via `selected_ids`), both of which work now.

- [ ] **Step 4: Run the 2a consumption suite to verify no regression**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_questions_consumption.py tests/test_questions_models.py -q`
Expected: PASS (choice behavior unchanged — fragment shows `is-correct`/`is-incorrect`, no-JS reveals only the answered question).

- [ ] **Step 5: Lint and commit**

```bash
./.venv/Scripts/python.exe -m ruff check courses/models.py courses/views.py
./.venv/Scripts/python.exe -m ruff format courses/models.py courses/views.py
git add courses/models.py courses/views.py templates/courses/elements/_question_feedback.html templates/courses/elements/_reveal_choice.html
git commit -m "refactor(2b): generalize check_answer + feedback partial (per-type build_answer/feedback_context)"
```

---

## Task 7: Short-text & short-numeric rendering + `submitted_values` threading

**Files:**
- Modify: `courses/models.py` (`ShortTextQuestionElement`, `ShortNumericQuestionElement`)
- Modify: `courses/templatetags/courses_extras.py` (`render_element`)
- Modify: `courses/views.py` (`build_lesson_context`, `lesson_unit`)
- Modify: `templates/courses/lesson_unit.html` (line 16)
- Modify (fill the Task 5 stubs): `templates/courses/elements/shorttextquestionelement.html`, `shortnumericquestionelement.html`
- Create: `templates/courses/elements/_reveal_shorttext.html`, `_reveal_shortnumeric.html`
- Test: `tests/test_questions_2b_consumption.py`

**Interfaces:**
- Consumes: the base `QuestionElement.render()` + stub templates (Task 5); the `feedback_context`/`REVEAL_TEMPLATE` pattern on the base (Task 6).
- Produces: an extended base `render()` (adds `submitted_values`/`slug`/`node_pk`/`reveal_template`); `REVEAL_TEMPLATE` on both simple types; filled student-facing templates `shorttextquestionelement.html`/`shortnumericquestionelement.html`; `render_element(…, submitted_values=None)`; `build_lesson_context` seeds `submitted_values=None` and uses the union `question_ct_ids` + per-type prefetch/scan.

- [ ] **Step 1: Write the failing test**

Create `tests/test_questions_2b_consumption.py`:

```python
import pytest
from django.urls import reverse

from courses.models import Blank
from courses.models import Element
from courses.models import Enrollment
from courses.models import FillBlankQuestionElement
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_login


def _enrolled_unit(client):
    user = make_login(client, "stu")
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    return course, unit


def _check_url(course, unit, el):
    return reverse(
        "courses:check_answer",
        kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": el.pk},
    )


@pytest.mark.django_db
def test_shorttext_initial_render_has_input_no_answer_leak(client):
    course, unit = _enrolled_unit(client)
    q = ShortTextQuestionElement.objects.create(stem="<p>Cap?</p>", accepted="Paris")
    Element.objects.create(unit=unit, content_object=q)
    resp = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    )
    body = resp.content.decode()
    assert 'name="answer"' in body
    assert "Paris" not in body  # accepted answer never in the initial render


@pytest.mark.django_db
def test_shorttext_check_answer_fragment(client):
    course, unit = _enrolled_unit(client)
    q = ShortTextQuestionElement.objects.create(stem="<p>Cap?</p>", accepted="Paris")
    el = Element.objects.create(unit=unit, content_object=q)
    url = _check_url(course, unit, el)
    assert b"is-incorrect" in client.post(
        url, {"answer": "London"}, HTTP_X_REQUESTED_WITH="fetch"
    ).content
    ok = client.post(url, {"answer": " paris "}, HTTP_X_REQUESTED_WITH="fetch")
    assert b"is-correct" in ok.content
    assert b"Paris" in ok.content  # reveal shown on the answered question only


@pytest.mark.django_db
def test_shortnumeric_check_answer_fragment(client):
    from decimal import Decimal

    course, unit = _enrolled_unit(client)
    q = ShortNumericQuestionElement.objects.create(
        stem="<p>Pi?</p>", value=Decimal("3.14"), tolerance=Decimal("0.01")
    )
    el = Element.objects.create(unit=unit, content_object=q)
    url = _check_url(course, unit, el)
    assert b"is-correct" in client.post(
        url, {"answer": "3,15"}, HTTP_X_REQUESTED_WITH="fetch"
    ).content
    assert b"is-incorrect" in client.post(
        url, {"answer": "9"}, HTTP_X_REQUESTED_WITH="fetch"
    ).content


@pytest.mark.django_db
def test_shorttext_no_js_repopulates_only_answered(client):
    course, unit = _enrolled_unit(client)
    q1 = ShortTextQuestionElement.objects.create(stem="<p>A?</p>", accepted="x")
    q2 = ShortTextQuestionElement.objects.create(stem="<p>B?</p>", accepted="y")
    el1 = Element.objects.create(unit=unit, content_object=q1)
    Element.objects.create(unit=unit, content_object=q2)
    resp = client.post(_check_url(course, unit, el1), {"answer": "myguess"})  # no-JS
    body = resp.content.decode()
    assert "lesson-unit__title" in body  # whole page
    assert body.count("myguess") == 1  # only the answered question repopulates
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_questions_2b_consumption.py -q`
Expected: FAIL — the Task 5 stub templates render only the stem (no `<form>`/`name="answer"`), so `test_shorttext_initial_render_has_input_no_answer_leak` fails on `assert 'name="answer"' in body`, and the check-answer tests fail (no feedback rendered).

- [ ] **Step 3: Extend the base `render()` and set `REVEAL_TEMPLATE` on the two simple types**

Task 5 added a base `QuestionElement.render()` (dispatching to `courses/elements/{model_name}.html`) so the new types are renderable in the editor preview. The three new types SHARE that base render (they don't get per-type render methods); choice keeps its own override. `feedback_context` is already inherited from the `QuestionElement` base (Task 6) — do NOT add per-type copies.

In `courses/models.py`, **replace the base `QuestionElement.render()`** (the one Task 5 added) with this extended version — it adds `submitted_values`, `slug`/`node_pk`, and `reveal_template` to the context so the new-type templates can build their form action, repopulate, and include feedback:

```python
    def render(
        self,
        *,
        element=None,
        feedback_for_pk=None,
        selected_ids=frozenset(),
        submitted_values=None,
        mark_result=None,
    ):
        name = self._meta.model_name
        unit = element.unit if element is not None else None
        return render_to_string(
            f"courses/elements/{name}.html",
            {
                "el": self,
                "element": element,
                "slug": unit.course.slug if unit is not None else "",
                "node_pk": unit.pk if unit is not None else "",
                "feedback_for_pk": feedback_for_pk,
                "selected_ids": set(selected_ids or ()),
                "submitted_values": submitted_values,
                "mark_result": mark_result,
                "reveal_template": self.REVEAL_TEMPLATE,
            },
        )
```

Then add ONLY a `REVEAL_TEMPLATE` class attribute to each of the two simple types (no other methods — `mark`/`build_answer` exist from Task 2; `render`/`feedback_context` are inherited):

```python
class ShortTextQuestionElement(QuestionElement):
    ...
    REVEAL_TEMPLATE = "courses/elements/_reveal_shorttext.html"
```

```python
class ShortNumericQuestionElement(QuestionElement):
    ...
    REVEAL_TEMPLATE = "courses/elements/_reveal_shortnumeric.html"
```

- [ ] **Step 4: Thread `submitted_values` through `render_element`**

In `courses/templatetags/courses_extras.py`, update `render_element`:

```python
@register.simple_tag
def render_element(
    element,
    feedback_for_pk=None,
    selected_ids=frozenset(),
    submitted_values=None,
    mark_result=None,
):
    obj = element.content_object
    if obj is None:
        return ""
    if isinstance(obj, HtmlElement):
        return mark_safe(obj.render(unit=element.unit, course=element.unit.course))  # noqa: S308
    if isinstance(obj, QuestionElement):
        return mark_safe(  # noqa: S308 — templates escape user text; correctness never leaks
            obj.render(
                element=element,
                feedback_for_pk=feedback_for_pk,
                selected_ids=selected_ids,
                submitted_values=submitted_values,
                mark_result=mark_result,
            )
        )
    return mark_safe(obj.render())  # noqa: S308 — each element template escapes its own fields
```

- [ ] **Step 5: Seed `submitted_values` in the lesson context + union `question_ct_ids` + per-type scan**

In `courses/views.py`, update the import (line 20) to include the new types and replace `build_lesson_context`'s question-collection / prefetch / scan / ct-id block (lines 46-69):

```python
from courses.models import ChoiceQuestionElement
from courses.models import FillBlankQuestionElement
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
```

```python
    questions = [
        el.content_object
        for el in elements
        if isinstance(el.content_object, QuestionElement)
    ]
    choice_qs = [q for q in questions if isinstance(q, ChoiceQuestionElement)]
    fill_qs = [q for q in questions if isinstance(q, FillBlankQuestionElement)]
    if choice_qs:
        prefetch_related_objects(choice_qs, "choices")
    if fill_qs:
        prefetch_related_objects(fill_qs, "blanks")

    math_ct_id = ContentType.objects.get_for_model(MathElement).id
    html_ct_id = ContentType.objects.get_for_model(HtmlElement).id
    question_models = [
        ChoiceQuestionElement,
        ShortTextQuestionElement,
        ShortNumericQuestionElement,
        FillBlankQuestionElement,
    ]
    question_ct_ids = {
        ContentType.objects.get_for_model(m).id for m in question_models
    }

    def _question_has_math(q):
        if has_math_delimiters(q.stem):
            return True
        if isinstance(q, ChoiceQuestionElement):
            return any(has_math_delimiters(c.text) for c in q.choices.all())
        if isinstance(q, FillBlankQuestionElement):
            return any(has_math_delimiters(b.accepted) for b in q.blanks.all())
        return False

    has_math = any(el.content_type_id == math_ct_id for el in elements) or any(
        isinstance(el.content_object, QuestionElement)
        and _question_has_math(el.content_object)
        for el in elements
    )
    has_html = any(el.content_type_id == html_ct_id for el in elements)
    has_questions = any(el.content_type_id in question_ct_ids for el in elements)
```

Add `"submitted_values": None` to the dict `build_lesson_context` returns (alongside the other keys, so every no-JS re-render has the key defined for non-answered questions):

```python
    return {
        "course": node.course,
        "unit": node,
        "is_quiz": False,
        "elements": elements,
        "has_math": has_math,
        "has_html": has_html,
        "has_questions": has_questions,
        "submitted_values": None,
        "progress": progress,
        "element_count": len(current_ids),
        "seen_count": seen_count,
    }
```

In `lesson_unit` (line 122), extend the GET seed:

```python
    ctx.update(
        feedback_for_pk=None,
        selected_ids=frozenset(),
        submitted_values=None,
        mark_result=None,
    )
```

- [ ] **Step 6: Thread `submitted_values` into the lesson template tag call**

In `templates/courses/lesson_unit.html` (line 16):

```html
      <section data-element-id="{{ el.pk }}">{% render_element el feedback_for_pk=feedback_for_pk selected_ids=selected_ids submitted_values=submitted_values mark_result=mark_result %}</section>
```

- [ ] **Step 7: Fill the stub question templates + create the reveal includes**

**Replace** the Task 5 stub `templates/courses/elements/shorttextquestionelement.html` with the real form (it currently shows only the stem). Note the input value uses `submitted_values` (the base render passes the raw value; for short-text it is a scalar string):

```html
{% load i18n %}
<div class="el el--question" data-question>
  <div class="question__stem">{{ el.stem|safe }}</div>
  {% if element %}
  <form class="question__form" method="post"
        action="{% url 'courses:check_answer' slug=slug node_pk=node_pk element_pk=element.pk %}">
    {% csrf_token %}
    <input type="text" name="answer" class="question__text-input" autocomplete="off"
           value="{% if element.pk == feedback_for_pk %}{{ submitted_values }}{% endif %}">
    <button type="submit" class="btn btn--small">{% trans "Check" %}</button>
    <div class="question__feedback" data-question-feedback>
      {% if element.pk == feedback_for_pk %}
        {% include "courses/elements/_question_feedback.html" %}
      {% endif %}
    </div>
  </form>
  {% endif %}
</div>
```

**Replace** the stub `templates/courses/elements/shortnumericquestionelement.html` — identical except the input adds `inputmode="decimal"`:

```html
{% load i18n %}
<div class="el el--question" data-question>
  <div class="question__stem">{{ el.stem|safe }}</div>
  {% if element %}
  <form class="question__form" method="post"
        action="{% url 'courses:check_answer' slug=slug node_pk=node_pk element_pk=element.pk %}">
    {% csrf_token %}
    <input type="text" name="answer" inputmode="decimal" class="question__text-input" autocomplete="off"
           value="{% if element.pk == feedback_for_pk %}{{ submitted_values }}{% endif %}">
    <button type="submit" class="btn btn--small">{% trans "Check" %}</button>
    <div class="question__feedback" data-question-feedback>
      {% if element.pk == feedback_for_pk %}
        {% include "courses/elements/_question_feedback.html" %}
      {% endif %}
    </div>
  </form>
  {% endif %}
</div>
```

Create `templates/courses/elements/_reveal_shorttext.html`:

```html
{% load i18n %}
<p class="question__reveal-text">{% trans "Correct answer:" %} <strong>{{ mark_result.reveal }}</strong></p>
```

Create `templates/courses/elements/_reveal_shortnumeric.html` (suppress `± tolerance` when zero; `floatformat` with no grouping keeps the value re-typeable):

```html
{% load i18n %}
<p class="question__reveal-text">{% trans "Expected:" %}
  <strong>{{ mark_result.reveal.value|floatformat:"-8" }}</strong>{% if mark_result.reveal.tolerance %} ± {{ mark_result.reveal.tolerance|floatformat:"-8" }}{% endif %}
</p>
```

(`floatformat:"-8"` strips trailing zeros from the `decimal_places=8` column, uses the active-locale decimal separator with **no** thousands grouping, and is re-typeable into `parse_number`. `{% if mark_result.reveal.tolerance %}` is falsy for `Decimal("0")`, so a zero tolerance suppresses the `± …` suffix.)

- [ ] **Step 8: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_questions_2b_consumption.py tests/test_questions_consumption.py -q`
Expected: PASS (new simple-type tests + the 2a choice suite both green).

- [ ] **Step 9: Lint and commit**

```bash
./.venv/Scripts/python.exe -m ruff check courses/models.py courses/views.py courses/templatetags/courses_extras.py
./.venv/Scripts/python.exe -m ruff format courses/models.py courses/views.py courses/templatetags/courses_extras.py tests/test_questions_2b_consumption.py
git add courses/models.py courses/views.py courses/templatetags/courses_extras.py templates/courses/lesson_unit.html templates/courses/elements/shorttextquestionelement.html templates/courses/elements/shortnumericquestionelement.html templates/courses/elements/_reveal_shorttext.html templates/courses/elements/_reveal_shortnumeric.html tests/test_questions_2b_consumption.py
git commit -m "feat(2b): short-text/numeric rendering + submitted_values threading"
```

---

## Task 8: Fill-blank rendering (`render_fill_blanks` tag + template + reveal)

**Files:**
- Modify: `courses/models.py` (`FillBlankQuestionElement` — add `REVEAL_TEMPLATE` only; render/feedback_context inherited)
- Modify: `courses/templatetags/courses_extras.py` (add `render_fill_blanks`)
- Modify (fill the Task 5 stub): `templates/courses/elements/fillblankquestionelement.html`
- Create: `templates/courses/elements/_reveal_fillblank.html`
- Test: append to `tests/test_questions_2b_consumption.py`

**Interfaces:**
- Consumes: `courses.fillblank.render_inputs` (Task 3); the base `render()`/`feedback_context()` + `REVEAL_TEMPLATE` pattern (Tasks 5–7); `submitted_values` threading (Task 7).
- Produces: `FillBlankQuestionElement.REVEAL_TEMPLATE`; the filled `fillblankquestionelement.html`; `{% render_fill_blanks el submitted_values %}`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_questions_2b_consumption.py`:

```python
def _fillblank_in_unit(unit):
    q = FillBlankQuestionElement.objects.create(stem="The capital is ￿0￿.")
    Blank.objects.create(question=q, accepted="Paris")
    return q, Element.objects.create(unit=unit, content_object=q)


@pytest.mark.django_db
def test_fillblank_initial_render_has_input_no_leak(client):
    course, unit = _enrolled_unit(client)
    q, el = _fillblank_in_unit(unit)
    resp = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    )
    body = resp.content.decode()
    assert 'name="blank"' in body
    assert "￿" not in body  # tokens never reach the client
    assert "Paris" not in body  # accepted answer not leaked initially


@pytest.mark.django_db
def test_fillblank_check_answer_fragment_correct_and_partial(client):
    course, unit = _enrolled_unit(client)
    q = FillBlankQuestionElement.objects.create(stem="￿0￿ and ￿1￿")
    Blank.objects.create(question=q, accepted="a")
    Blank.objects.create(question=q, accepted="b")
    el = Element.objects.create(unit=unit, content_object=q)
    url = _check_url(course, unit, el)
    ok = client.post(url, {"blank": ["a", "b"]}, HTTP_X_REQUESTED_WITH="fetch")
    assert b"is-correct" in ok.content
    partial = client.post(url, {"blank": ["a", "WRONG"]}, HTTP_X_REQUESTED_WITH="fetch")
    assert b"is-incorrect" in partial.content
    assert b"answer-correct" in partial.content  # the right gap still marked
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_questions_2b_consumption.py -q -k fillblank`
Expected: FAIL — the Task 5 stub `fillblankquestionelement.html` renders `{{ el.stem }}` (escaped), so there is no `name="blank"` input AND the raw `￿0￿` token leaks into the page, failing `assert 'name="blank"' in body` / `assert "￿" not in body`.

- [ ] **Step 3: Set `REVEAL_TEMPLATE` on `FillBlankQuestionElement`**

`render()` and `feedback_context()` are inherited from the `QuestionElement` base (extended in Task 7 — its context already passes `submitted_values`, which for fill-blank is the positional `getlist("blank")`). Add ONLY the class attribute to `FillBlankQuestionElement`:

```python
class FillBlankQuestionElement(QuestionElement):
    ...
    REVEAL_TEMPLATE = "courses/elements/_reveal_fillblank.html"
```

The base `render()` dispatches to `courses/elements/fillblankquestionelement.html` (`{model_name}.html`), which Step 5 fills in.

- [ ] **Step 4: Add the `render_fill_blanks` tag**

Append to `courses/templatetags/courses_extras.py`:

```python
@register.simple_tag
def render_fill_blanks(el, submitted_values=None):
    """Render a fill-blank stem: text segments (sanitized HTML) interleaved with
    server-built <input name="blank"> elements (escaped values). See courses.fillblank."""
    from courses import fillblank

    return fillblank.render_inputs(el.stem, submitted_values)
```

- [ ] **Step 5: Fill the stub question template + create the reveal include**

**Replace** the Task 5 stub `templates/courses/elements/fillblankquestionelement.html` with:

```html
{% load i18n courses_extras %}
<div class="el el--question el--fillblank" data-question>
  {% if element %}
  <form class="question__form" method="post"
        action="{% url 'courses:check_answer' slug=slug node_pk=node_pk element_pk=element.pk %}">
    {% csrf_token %}
    <div class="question__stem">
      {% if element.pk == feedback_for_pk %}
        {% render_fill_blanks el submitted_values %}
      {% else %}
        {% render_fill_blanks el %}
      {% endif %}
    </div>
    <button type="submit" class="btn btn--small">{% trans "Check" %}</button>
    <div class="question__feedback" data-question-feedback>
      {% if element.pk == feedback_for_pk %}
        {% include "courses/elements/_question_feedback.html" %}
      {% endif %}
    </div>
  </form>
  {% else %}
    <div class="question__stem">{% render_fill_blanks el %}</div>
  {% endif %}
</div>
```

Create `templates/courses/elements/_reveal_fillblank.html`:

```html
{% load i18n %}
<ol class="question__reveal question__reveal--blanks">
  {% for item in mark_result.reveal %}
    <li class="question__reveal-item {% if item.correct %}answer-correct{% else %}answer-wrong{% endif %}">
      {% if item.correct %}
        <span class="question__tick" aria-hidden="true">✓</span>
      {% else %}
        <span class="question__glyph" aria-hidden="true">✗</span>
        <span class="question__reveal-text">{% trans "Correct answer:" %} <strong>{{ item.accepted }}</strong></span>
      {% endif %}
    </li>
  {% endfor %}
</ol>
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_questions_2b_consumption.py -q`
Expected: PASS.

- [ ] **Step 7: Lint and commit**

```bash
./.venv/Scripts/python.exe -m ruff check courses/models.py courses/templatetags/courses_extras.py
./.venv/Scripts/python.exe -m ruff format courses/models.py courses/templatetags/courses_extras.py tests/test_questions_2b_consumption.py
git add courses/models.py courses/templatetags/courses_extras.py templates/courses/elements/fillblankquestionelement.html templates/courses/elements/_reveal_fillblank.html tests/test_questions_2b_consumption.py
git commit -m "feat(2b): fill-blank rendering (render_fill_blanks tag + templates)"
```

---

## Task 9: No-leak invariant + minimal CSS

**Files:**
- Modify: a token-driven CSS file under `courses/static/courses/css/` (the one carrying the existing `.question__*` rules — find it in Step 1)
- Test: append to `tests/test_questions_2b_consumption.py`

**Interfaces:**
- Produces: the security regression tests (initial render clean for all types; post-submit reveals only the answered question) and minimal styles for the new inputs/reveals.

- [ ] **Step 1: Locate the existing question CSS**

Run: `./.venv/Scripts/python.exe -m grep -rl "question__choice" courses/static/courses/css/ 2>/dev/null || grep -rl "question__" courses/static/courses/css/`
Expected: one file (e.g. `courses/static/courses/css/lesson.css`). Use that file in Step 4.

- [ ] **Step 2: Write the failing no-leak test**

Append to `tests/test_questions_2b_consumption.py`:

```python
@pytest.mark.django_db
def test_post_submit_reveals_only_answered_across_types(client):
    course, unit = _enrolled_unit(client)
    answered = ShortTextQuestionElement.objects.create(stem="<p>A?</p>", accepted="x")
    other = ShortTextQuestionElement.objects.create(stem="<p>B?</p>", accepted="secret")
    el = Element.objects.create(unit=unit, content_object=answered)
    Element.objects.create(unit=unit, content_object=other)
    resp = client.post(_check_url(course, unit, el), {"answer": "x"})  # no-JS
    body = resp.content.decode()
    assert "is-correct" in body  # the answered question revealed
    assert "secret" not in body  # the OTHER question's accepted answer stays hidden
    assert body.count("question__reveal-text") == 1  # exactly one reveal block
```

- [ ] **Step 3: Run test to verify it passes (behavior already correct)**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_questions_2b_consumption.py::test_post_submit_reveals_only_answered_across_types -q`
Expected: PASS (the `feedback_for_pk` gate already enforces this — this test pins the invariant). If it FAILS, a render leaked correctness; fix before proceeding.

- [ ] **Step 4: Add minimal styles**

Append to the CSS file found in Step 1 (token-driven, matching the existing `.question__*` conventions):

```css
.question__text-input,
.question__blank-input {
  font: inherit;
  padding: var(--space-1, 0.25rem) var(--space-2, 0.5rem);
  border: 1px solid var(--color-border, #ccc);
  border-radius: var(--radius-sm, 4px);
}
.question__blank-input { width: 8ch; margin: 0 0.15rem; }
.question__reveal--blanks { margin: var(--space-2, 0.5rem) 0; padding-left: 1.25rem; }
.question__reveal-item.answer-wrong { color: var(--color-danger, #b00020); }
.question__reveal-text { margin: var(--space-1, 0.25rem) 0; }
```

- [ ] **Step 5: Verify collectstatic and run the full consumption suite**

```bash
./.venv/Scripts/python.exe manage.py collectstatic --noinput
./.venv/Scripts/python.exe -m pytest tests/test_questions_2b_consumption.py tests/test_questions_consumption.py -q
```
Expected: PASS.

- [ ] **Step 6: Lint and commit**

```bash
./.venv/Scripts/python.exe -m ruff format tests/test_questions_2b_consumption.py
git add courses/static/courses/css/ tests/test_questions_2b_consumption.py
git commit -m "feat(2b): no-leak regression tests + question input/reveal styles"
```

---

## Task 10: i18n (Polish) + add-menu / editor strings

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po`
- Test: `tests/test_i18n_questions_2b.py`

**Interfaces:**
- Produces: Polish translations for every new user-facing string; `compilemessages -l pl` green.

- [ ] **Step 1: Write the failing i18n test**

Create `tests/test_i18n_questions_2b.py` (mirror `tests/test_i18n_questions.py`):

```python
import pytest
from django.utils import translation


@pytest.mark.parametrize(
    "msgid",
    [
        "Short text",
        "Short numeric",
        "Fill in the blanks",
        "Accepted answers (one per line)",
        "Correct value",
        "Correct answer:",
        "Expected:",
    ],
)
def test_pl_translation_present(msgid):
    with translation.override("pl"):
        assert translation.gettext(msgid) != msgid  # a non-identity PL string exists
```

- [ ] **Step 2: Regenerate the message catalog**

Run: `./.venv/Scripts/python.exe manage.py makemessages -l pl`
Expected: new `msgid` entries (the strings above plus the editor hint, field labels, and validation errors) appear as empty `msgstr ""` in `locale/pl/LC_MESSAGES/django.po`.

- [ ] **Step 3: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_i18n_questions_2b.py -q`
Expected: FAIL (empty `msgstr` → `gettext` returns the msgid).

- [ ] **Step 4: Fill in the Polish translations**

Edit `locale/pl/LC_MESSAGES/django.po`, setting `msgstr` for each new `msgid`. Use:

```
msgid "Short text"
msgstr "Krótki tekst"

msgid "Short numeric"
msgstr "Liczba"

msgid "Fill in the blanks"
msgstr "Uzupełnij luki"

msgid "Accepted answers (one per line)"
msgstr "Akceptowane odpowiedzi (po jednej w wierszu)"

msgid "Case sensitive"
msgstr "Rozróżniaj wielkość liter"

msgid "Correct value"
msgstr "Poprawna wartość"

msgid "Tolerance (±, optional)"
msgstr "Tolerancja (±, opcjonalnie)"

msgid "Sentence with blanks"
msgstr "Zdanie z lukami"

msgid "Mark each blank with {{answer}}. Use | for alternatives, e.g. {{colour|color}}."
msgstr "Oznacz każdą lukę jako {{odpowiedź}}. Użyj | dla wariantów, np. {{kolor|barwa}}."

msgid "Correct answer:"
msgstr "Poprawna odpowiedź:"

msgid "Expected:"
msgstr "Oczekiwano:"

msgid "Check"
msgstr "Sprawdź"

msgid "Add at least one accepted answer."
msgstr "Dodaj co najmniej jedną akceptowaną odpowiedź."

msgid "Enter a number (e.g. 3.14 or 3,14)."
msgstr "Wpisz liczbę (np. 3.14 lub 3,14)."

msgid "Tolerance cannot be negative."
msgstr "Tolerancja nie może być ujemna."

msgid "Mark at least one blank with {{answer}} (use | for alternatives)."
msgstr "Oznacz co najmniej jedną lukę jako {{odpowiedź}} (użyj | dla wariantów)."
```

(`"Check"` may already exist from 2a — if `makemessages` reports it as already present, leave the existing entry.)

- [ ] **Step 5: Compile and run the test**

```bash
./.venv/Scripts/python.exe manage.py compilemessages -l pl
./.venv/Scripts/python.exe -m pytest tests/test_i18n_questions_2b.py -q
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo tests/test_i18n_questions_2b.py
git commit -m "i18n(2b): Polish strings for short-text/numeric/fill-blank questions"
```

---

## Task 11: Playwright e2e (author + answer each type, JS + no-JS)

**Files:**
- Create: `tests/test_e2e_questions_2b.py`
- Test: itself (run with `-m e2e`)

**Interfaces:**
- Consumes: the full stack (Tasks 1-10). Mirrors the harness in `tests/test_e2e_questions.py` (login helper, `_make_pa_user`, `_seed_course_unit`).

- [ ] **Step 1: Write the e2e test**

Create `tests/test_e2e_questions_2b.py` (reuse the helpers from `test_e2e_questions.py` verbatim — copy `_allow_async_unsafe`, `_make_pa_user`, `_login`, `_seed_course_unit`). Author each type directly in the DB, then drive the student answer flow through the browser:

```python
import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _make_pa_user(username):
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    user.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return user


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _seed(username, slug):
    from django.contrib.auth import get_user_model

    from courses.models import Blank
    from courses.models import Element
    from courses.models import Enrollment
    from courses.models import FillBlankQuestionElement
    from courses.models import ShortNumericQuestionElement
    from courses.models import ShortTextQuestionElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    User = get_user_model()
    owner = User.objects.get(username=username)
    course = CourseFactory(slug=slug, owner=owner)
    Enrollment.objects.create(student=owner, course=course)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="L"
    )
    st = ShortTextQuestionElement.objects.create(stem="<p>Cap?</p>", accepted="Paris")
    Element.objects.create(unit=unit, content_object=st)
    sn = ShortNumericQuestionElement.objects.create(stem="<p>Pi?</p>", value="3.14", tolerance="0.01")
    Element.objects.create(unit=unit, content_object=sn)
    fb = FillBlankQuestionElement.objects.create(stem="On the ￿0￿.")
    Blank.objects.create(question=fb, accepted="Seine")
    Element.objects.create(unit=unit, content_object=fb)
    return course, unit


def test_answer_all_types_js_path(page, live_server):
    user = _make_pa_user("pa2b")
    course, unit = _seed("pa2b", "e2e-2b")
    _login(page, live_server, "pa2b")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")

    forms = page.locator("form.question__form")
    # 1) short-text wrong then right
    st = forms.nth(0)
    st.locator("input[name='answer']").fill("London")
    st.locator("button[type='submit']").click()
    page.wait_for_selector("form.question__form:nth-of-type(1) .is-incorrect")
    st.locator("input[name='answer']").fill("paris")
    st.locator("button[type='submit']").click()
    page.wait_for_selector(".is-correct")

    # 3) fill-blank right (JS fragment swap)
    fb = forms.nth(2)
    fb.locator("input[name='blank']").fill("Seine")
    fb.locator("button[type='submit']").click()
    page.wait_for_selector("form.question__form:nth-of-type(3) .is-correct")


def test_answer_no_js_full_post(page, live_server, context):
    # Disable JS → the form does a full-page POST to check_answer.
    context.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>true})")
    user = _make_pa_user("pa2bnojs")
    course, unit = _seed("pa2bnojs", "e2e-2b-nojs")
    _login(page, live_server, "pa2bnojs")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    sn = page.locator("form.question__form").nth(1)
    sn.locator("input[name='answer']").fill("3,15")
    sn.locator("button[type='submit']").click()
    page.wait_for_load_state("networkidle")
    assert page.locator(".is-correct").count() >= 1
    # repopulation: the answered numeric input keeps the typed value
    assert page.locator("form.question__form").nth(1).locator("input[name='answer']").input_value() == "3,15"
```

(If the no-JS approach via `webdriver` flag does not reliably disable `question.js` in this harness, follow whatever no-JS toggle `tests/test_e2e_questions.py`'s no-JS test uses — copy its exact mechanism.)

- [ ] **Step 2: Run the e2e tests**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_e2e_questions_2b.py -m e2e -q`
Expected: PASS (both tests).

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e_questions_2b.py
git commit -m "test(2b): Playwright e2e — author + answer short-text/numeric/fill-blank (JS + no-JS)"
```

---

## Task 12: Full DoD gate + final commit

**Files:** none (verification only).

- [ ] **Step 1: Run the entire default suite**

Run: `./.venv/Scripts/python.exe -m pytest -q`
Expected: PASS (e2e excluded by default).

- [ ] **Step 2: Run the e2e suite**

Run: `./.venv/Scripts/python.exe -m pytest -m e2e -q`
Expected: PASS.

- [ ] **Step 3: Lint + format gate**

```bash
./.venv/Scripts/python.exe -m ruff check .
./.venv/Scripts/python.exe -m ruff format --check .
```
Expected: clean.

- [ ] **Step 4: Migration + system checks + static + messages**

```bash
./.venv/Scripts/python.exe manage.py makemigrations --check --dry-run
./.venv/Scripts/python.exe manage.py check
./.venv/Scripts/python.exe manage.py collectstatic --noinput
./.venv/Scripts/python.exe manage.py compilemessages -l pl
```
Expected: `makemigrations --check` reports no changes (exactly the one 0014 migration already committed); `check` clean; collectstatic + compilemessages succeed.

- [ ] **Step 5: Final verification commit (if any formatting changed)**

```bash
git add -A
git status   # confirm nothing unexpected
git commit -m "chore(2b): DoD gate green — auto-markable types complete" --allow-empty
```

---

## Notes for the executor

- **Do not narrow** the `isinstance(question, QuestionElement)` gate in `check_answer` (it is already broad in 2a — Task 6 relies on this).
- **Fill-blank stem storage:** the stored `stem` is the token-stem (`￿{n}￿` placeholders), never the raw `{{…}}`. The form rewrites it in `clean_stem`; the builder rebuilds `Blank` rows from `form.parsed_blanks`. Never reverse tokens→markers in 2b.
- **`submitted_values` is one value per page** (the answered question's), forwarded to every element's `render()`; each template gates repopulation/feedback on `element.pk == feedback_for_pk`, so it never bleeds into other questions.
- **`fraction` is a float**; assert it with `pytest.approx`, never `==` on `n/m`.
- If any task's tests reveal a 2a regression, STOP and fix before proceeding — the choice suites (`test_questions_consumption.py`, `test_questions_models.py`, `test_questions_authoring.py`, `test_e2e_questions.py`) must stay green throughout.
