# Numeric question: exact fractions — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `ShortNumericQuestionElement` store its correct value and tolerance as canonical
text and compare both sides as exact `Fraction`s, so `3/2` and `1/3` work from both the author's
and the student's side, and editing a tolerance stops corrupting it.

**Architecture:** `value`/`tolerance` move from `DecimalField(20,8)` to `CharField(64)` holding a
canonical string. `courses/marking.py` gains the canonicalisers, two field validators and a
`TOO_LONG` sentinel; `mark()` compares via the existing `parse_numeric_value`. A five-operation
irreversible migration converts existing rows. The same parser is hardened against a pre-existing
`int()`-digit-limit crash that already reaches student input through `blank_matches`.

**Tech Stack:** Django 5.2.15, Python 3.13.12, PostgreSQL, pytest + pytest-xdist, Playwright
(e2e), `uv` for all tooling.

**Spec:** `docs/superpowers/specs/2026-08-09-numeric-question-fractions-design.md`. The spec is
normative — where this plan and the spec disagree, the spec wins and the plan is the bug.

## Global Constraints

- **Run tooling through `uv run`.** `ruff`, `pytest` and `python` are not on `PATH`.
- **Start the test-DB container before any pytest run.** If it is down the suite looks hung for
  ~4m21s before failing.
- **Scope every test run narrowly** (`-k`, or a single file). A whole-repo sweep is a branch gate,
  not a task step.
- **e2e needs `-m e2e`** or it silently deselects and exits 5.
- **Falsify, don't run.** Every new test must be demonstrated RED before it counts. Pick the
  mutant from the *failure mode*, not from the assertion. Where a test cannot be red on `master`
  (most of them — `master`'s `DecimalField` cannot hold `1/3`), the falsification is against a
  named mutant of the new code, given per test below.
- **Never write an assertion that cannot fail.** Two places in this plan explicitly say a
  behaviour is *not* test-coverable; do not invent assertions there.
- `MAX_STORED_NUMERIC_CHARS = 64` and `MAX_PARSED_NUMERIC_CHARS = 256` are **separate constants**
  and must not be merged.
- New user-facing strings use `gettext_lazy` and need hand-written Polish. `locale/en` msgstrs
  stay intentionally empty.
- Commit after every task. Do not skip hooks.

## File Structure

**Modified:**

| file | responsibility after this change |
|---|---|
| `courses/marking.py` | the two caps, `TOO_LONG`, `format_decimal_plain`, the coercion prologue, `canonical_numeric_text`, `canonical_tolerance_text`, `validate_numeric_text`, `validate_tolerance_text` |
| `courses/guessnumber.py` | `format_target` becomes a delegate to `format_decimal_plain` |
| `courses/models.py` | `ShortNumericQuestionElement` fields, `clean()`, `mark()`; import list |
| `courses/migrations/0058_shortnumeric_text_value.py` | **new** — the five-op irreversible conversion with frozen helpers |
| `courses/element_forms.py` | `ShortNumericQuestionElementForm`; `_num` and the `__init__` override deleted |
| `courses/transfer/payloads.py` | `_val_short_numeric` |
| `courses/transfer/importer.py` | `_build_numeric` |
| `courses/transfer/schema.py` | `FORMAT_VERSION` 10 → 11 |
| `courses/lal_loader/builders.py` | the `numeric` branch |
| `templates/courses/manage/editor/_edit_shortnumericquestion.html` | inputmode, placeholder, maxlength, filter |
| `templates/courses/elements/shortnumericquestionelement.html` | inputmode |
| `templates/courses/elements/_reveal_shortnumeric.html` | print canonical strings |
| `docs/help/course-admin/quiz-editors.md` + `.pl.md` | author-facing docs |
| `locale/{pl,en}/LC_MESSAGES/django.po` | six new msgids |

`courses/transfer/export.py` is **not** modified — `_ser_numeric` already emits `str(el.value)`,
which is now the canonical string.

---

### Task 1: Harden the parser and share the formatter

Closes defect 4 and removes the twin formatter. No short-numeric behaviour changes yet, so the
whole existing suite must stay green.

**Files:**
- Modify: `courses/marking.py`
- Modify: `courses/guessnumber.py:54-61`
- Test: `tests/test_questions_2b_marking.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `MAX_STORED_NUMERIC_CHARS: int = 64`, `MAX_PARSED_NUMERIC_CHARS: int = 256`,
  `format_decimal_plain(d) -> str`, `_coerce_numeric_input(s) -> str`, and a hardened
  `parse_numeric_value(s) -> Fraction | None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_questions_2b_marking.py`:

```python
def test_parse_numeric_value_rejects_over_long_input_instead_of_raising():
    # Pre-existing crash: int() on >4300 digits raises ValueError under CPython >=3.11,
    # and this parser runs on student input via blank_matches.
    from courses.marking import parse_numeric_value

    assert parse_numeric_value("1" * 5000 + "/2") is None


def test_parse_numeric_value_accepts_100_chars_so_fill_blank_is_not_narrowed():
    # Pins the 256 comparison cap, NOT the 64 storage cap. Collapsing the two
    # constants would silently stop 65-4300 char numbers matching in fill-blank.
    from courses.marking import parse_numeric_value
    from fractions import Fraction

    assert parse_numeric_value("1" * 100) == Fraction(int("1" * 100))


def test_parse_numeric_value_coerces_decimal_without_e_notation():
    from decimal import Decimal
    from fractions import Fraction

    from courses.marking import parse_numeric_value

    assert parse_numeric_value(Decimal("1.5")) == Fraction(3, 2)
    # str(Decimal("0.00000000")) is '0E-8', which no grammar matches.
    assert parse_numeric_value(Decimal("0.00000000")) == Fraction(0)


def test_parse_numeric_value_coerces_json_floats_without_e_notation():
    from fractions import Fraction

    from courses.marking import parse_numeric_value

    assert parse_numeric_value(2.5) == Fraction(5, 2)
    # str(0.00001) is '1e-05'.
    assert parse_numeric_value(0.00001) == Fraction(1, 100000)
    # Decimal(0.1) is 55 digits of binary noise; Decimal(str(0.1)) is not.
    assert parse_numeric_value(0.1) == Fraction(1, 10)


def test_parse_numeric_value_rejects_bool_without_raising():
    # isinstance(True, int) is True; Decimal("True") raises InvalidOperation.
    from courses.marking import parse_numeric_value

    assert parse_numeric_value(True) is None


def test_parse_number_did_not_get_a_length_guard():
    # views.py:1162 and element_forms.py:314/338 parse raw input through
    # parse_number; it never calls int(str) so it was never vulnerable.
    from decimal import Decimal

    from courses.marking import parse_number

    assert parse_number("9" * 5000) == Decimal("9" * 5000)


def test_format_decimal_plain_keeps_precision_and_avoids_exponent():
    from decimal import Decimal

    from courses.marking import format_decimal_plain

    assert format_decimal_plain(Decimal("40401.00000000")) == "40401"
    assert format_decimal_plain(Decimal("0.10000000")) == "0.1"
    assert format_decimal_plain(Decimal("0.00000000")) == "0"
    # Default context precision is 28; without localcontext this returns "0.1".
    long_value = "0.1000000000000000000000000000000001"
    assert format_decimal_plain(Decimal(long_value)) == long_value


def test_format_target_delegates_to_format_decimal_plain():
    from decimal import Decimal

    from courses.guessnumber import format_target

    assert format_target(Decimal("40401.00000000")) == "40401"
    assert format_target(Decimal("40401.50000000")) == "40401.5"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_questions_2b_marking.py -k "over_long or 100_chars or coerces or bool_without or did_not_get or format_decimal_plain or format_target_delegates" -v`

Expected: FAIL. `over_long` fails with `ValueError: Exceeds the limit (4300 digits)`, not an
assertion error — that is the failure mode being fixed. The `format_decimal_plain` and coercion
tests fail with `ImportError`/`AttributeError`.

- [ ] **Step 3: Implement in `courses/marking.py`**

Add the imports `from decimal import localcontext` alongside the existing decimal imports, then
add above `parse_number`:

```python
# The storage cap for ShortNumericQuestionElement.value/tolerance. MUST equal those
# fields' max_length — that equality is what makes an oversized transfer payload
# produce a clean TransferError instead of a ValidationError deep in _clean_save.
MAX_STORED_NUMERIC_CHARS = 64
# The comparison-side cap, used only by parse_numeric_value. Deliberately NOT the
# same constant: parse_numeric_value is blank_matches' parser, so a 64-char cap here
# would silently stop 65-4300 character numbers matching in fill-blank, fill-in-table
# and fill-&-confirm. 256 stays far below the 4300-digit int() limit while changing
# no plausible existing content.
MAX_PARSED_NUMERIC_CHARS = 256

# Returned by canonical_numeric_text/canonical_tolerance_text when the input parses
# but its canonical form will not fit the column, so the form can say "too long"
# rather than "enter a number or fraction". Compared by identity. NEVER stored or
# rendered: a sentinel reaching a CharField is stringified into "<object object ...>".
# Note TOO_LONG is not None, so `if x is not None` is never a sufficient guard.
TOO_LONG = object()


def format_decimal_plain(d):
    """Format a Decimal as plain notation with trailing zeros stripped.

    Takes a Decimal (or anything Decimal() accepts) — NEVER raw author text:
    Decimal("1,5") raises InvalidOperation, so the comma must already be gone.

    Two load-bearing details:
    - "f" forces fixed-point. Decimal("40401").normalize() is Decimal("4.0401E+4"),
      whose plain str() the parsers reject, making the element uneditable.
    - localcontext raises the precision. normalize() applies the CURRENT context,
      whose default precision is 28, so a 29+ significant-digit value would be
      silently rounded — reachable now that the column is a 64-char CharField.
      The +16 is headroom if the storage cap is ever raised.
    """
    with localcontext() as ctx:
        ctx.prec = MAX_STORED_NUMERIC_CHARS + 16
        return format(Decimal(d).normalize(), "f")


def _coerce_numeric_input(s):
    """Coerce arbitrary input to text the grammars can match.

    A bare str() is wrong for every numeric type. str(Decimal("0.00000000")) is
    '0E-8'; Python switches floats to exponent form below 1e-4 and above 1e16, so
    str(0.00001) is '1e-05'. _NUM_RE has no exponent branch, so all of those would
    parse as None. Reachable two ways: every Decimal read from the old numeric(20,8)
    column below 1e-6, and JSON numbers in a LAL manifest.
    """
    if s is None:
        return ""
    if isinstance(s, Decimal):
        return format(s, "f")
    # bool must be excluded explicitly: isinstance(True, int) is True and
    # Decimal("True") raises InvalidOperation. A JSON `true` falls through to
    # str() -> "True" -> no grammar matches -> None, which is what callers expect.
    if isinstance(s, (int, float)) and not isinstance(s, bool):
        # Decimal(str(f)), never Decimal(f): Decimal(0.1) is 55 digits of binary
        # noise, which would blow the storage cap and change the stored value.
        return format(Decimal(str(s)), "f")
    return str(s)
```

Then replace `parse_numeric_value`'s opening two lines. It currently reads:

```python
    s = (s or "").strip()
    m = _MIXED_RE.match(s)
```

Replace with:

```python
    s = _coerce_numeric_input(s).strip()
    if len(s) > MAX_PARSED_NUMERIC_CHARS:
        # Guard BEFORE any regex: the branches below call int() on captured digit
        # runs, and int() raises ValueError above 4300 digits (CPython >=3.11).
        # blank_matches feeds this student input, so an unguarded call is a live 500.
        return None
    m = _MIXED_RE.match(s)
```

Extend `parse_numeric_value`'s docstring with a line noting that `parse_number` deliberately does
**not** get this guard — it goes through `Decimal`, which has no digit limit, and guarding it
would regress `views.py:1162` and `element_forms.py:314`/`:338`.

In `courses/guessnumber.py`, replace the body of `format_target`:

```python
def format_target(target):
    """Canonical author-facing text for a stored Decimal (§2.6).

    Delegates to courses.marking.format_decimal_plain, which owns the "f"-is-
    load-bearing rationale (40401 must not render as 4.0401E+4) and the raised
    precision. Kept as a named function because the guess-number spec refers to it.
    """
    return format_decimal_plain(target)
```

and add `from courses.marking import format_decimal_plain` to its imports.

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `uv run pytest tests/test_questions_2b_marking.py -k "over_long or 100_chars or coerces or bool_without or did_not_get or format_decimal_plain or format_target_delegates" -v`

Expected: PASS (8 tests).

- [ ] **Step 5: Verify nothing else regressed**

Run: `uv run pytest tests/test_questions_2b_marking.py tests/test_guessnumber_form.py tests/test_guessnumber_endpoint.py -v`

Expected: all PASS. The fill-blank marking tests in particular must be green **unmodified** —
they are the evidence that the 256 cap did not narrow existing matching.

- [ ] **Step 6: Falsify the two highest-value tests**

Temporarily set `ctx.prec = 28` in `format_decimal_plain` and re-run
`-k format_decimal_plain`: the long-value assertion must fail with `'0.1'`. Restore.

Temporarily change `_coerce_numeric_input`'s `Decimal` branch to `return str(s)` and re-run
`-k coerces`: `Decimal("0.00000000")` must come back `None`. Restore.

Record both observed failures in the task report. A test that did not go red does not count.

- [ ] **Step 7: Commit**

```bash
git add courses/marking.py courses/guessnumber.py tests/test_questions_2b_marking.py
git commit -m "fix(marking): guard parse_numeric_value against the int() digit limit

parse_numeric_value calls int() on captured digit runs, and CPython >=3.11 raises
ValueError above 4300 digits. blank_matches feeds it student input, so fill-blank,
fill-in-table and fill-&-confirm can be crashed by a pasted digit string today.

Adds a 256-char comparison cap (deliberately separate from the 64-char storage cap
added next, so existing fill-blank matching is unchanged), a Decimal/float-aware
coercion prologue that avoids E-notation, and moves guessnumber.format_target's
formatter into marking as format_decimal_plain with a raised decimal context."
```

---

### Task 2: The canonicalisers

**Files:**
- Modify: `courses/marking.py`
- Test: `tests/test_questions_2b_marking.py`

**Interfaces:**
- Consumes: `MAX_STORED_NUMERIC_CHARS`, `TOO_LONG`, `format_decimal_plain`,
  `_coerce_numeric_input`, `parse_number`, `parse_numeric_value`, `_MIXED_RE`, `_FRAC_RE`.
- Produces: `canonical_numeric_text(s) -> str | None | TOO_LONG`,
  `canonical_tolerance_text(s) -> str | None | TOO_LONG`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_questions_2b_marking.py`:

```python
import pytest

from courses.marking import TOO_LONG
from courses.marking import canonical_numeric_text
from courses.marking import canonical_tolerance_text
from courses.marking import parse_numeric_value

# Every row of the spec's canonicalisation table. Do not trim this list.
CANONICAL_ROWS = [
    ("1,5", "1.5"),
    ("1.50", "1.5"),
    ("0.10000000", "0.1"),
    ("40401.00000000", "40401"),
    (" 3 / 2 ", "3/2"),
    ("1  1/2", "1 1/2"),
    ("+7", "7"),
    ("+3/2", "3/2"),
    ("-0.50", "-0.5"),
    ("06/4", "6/4"),
    ("-06/4", "-6/4"),
    ("1 0/2", "1 0/2"),
    ("-1 1/2", "-1 1/2"),
    ("+1 1/2", "1 1/2"),
    (".5", "0.5"),
    (",5", "0.5"),
    ("-.5", "-0.5"),
    ("+,5", "0.5"),
    ("-0 1/2", "-0 1/2"),
    ("0", "0"),
    ("00", "0"),
    ("-0", "0"),
    ("-0.0", "0"),
    ("0/4", "0"),
    ("00/4", "0"),
    ("-0/4", "0"),
    ("0 0/4", "0"),
    ("-0 0/4", "0"),
]

REJECTED_ROWS = ["1/0", "1 1/0", "abc", "", "1" * 65]


@pytest.mark.parametrize("raw,expected", CANONICAL_ROWS)
def test_canonical_numeric_text_table(raw, expected):
    assert canonical_numeric_text(raw) == expected


@pytest.mark.parametrize("raw", REJECTED_ROWS)
def test_canonical_numeric_text_rejects(raw):
    assert canonical_numeric_text(raw) is None


@pytest.mark.parametrize("raw", ["." + "1" * 63, "," + "1" * 63, "-." + "1" * 62])
def test_canonical_numeric_text_rejects_output_overflow(raw):
    # 64 chars in, 65 chars out. Only reachable because format_decimal_plain
    # raises the precision; in the default 28-digit context this canonicalises
    # to 30 chars and fits.
    assert len(raw) == 64
    assert canonical_numeric_text(raw) is TOO_LONG


def test_canonical_numeric_text_preserves_long_precision():
    long_value = "0.1000000000000000000000000000000001"
    assert canonical_numeric_text(long_value) == long_value


@pytest.mark.parametrize("raw,expected", CANONICAL_ROWS)
def test_canonical_numeric_text_round_trips_and_is_idempotent(raw, expected):
    # Excludes the None/TOO_LONG rows by construction: feeding a sentinel back
    # in is not a meaningful round-trip.
    assert parse_numeric_value(expected) == parse_numeric_value(raw)
    assert canonical_numeric_text(expected) == expected


def test_canonical_numeric_text_accepts_json_numbers():
    # The LAL manifest is json.loads'd, so these reach the canonicaliser directly.
    assert canonical_numeric_text(2.5) == "2.5"
    assert canonical_numeric_text(0.00001) == "0.00001"
    assert canonical_numeric_text(True) is None


def test_canonical_tolerance_text_collapses_every_zero_to_empty():
    for raw in ["", "0", "0.00000000", "0/5", "-0", 0, 0.0]:
        assert canonical_tolerance_text(raw) == ""


def test_canonical_tolerance_text_keeps_positive_and_rejects_negative():
    assert canonical_tolerance_text("1/100") == "1/100"
    assert canonical_tolerance_text("0,01") == "0.01"
    assert canonical_tolerance_text(0.00001) == "0.00001"
    assert canonical_tolerance_text("-1") is None
    assert canonical_tolerance_text("abc") is None
    assert canonical_tolerance_text("." + "1" * 63) is TOO_LONG
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_questions_2b_marking.py -k "canonical" -v`

Expected: FAIL — `ImportError: cannot import name 'canonical_numeric_text'`.

- [ ] **Step 3: Implement in `courses/marking.py`**

Add after `parse_numeric_value`:

```python
def canonical_numeric_text(s):
    """Canonical storage text for a number or fraction; None if it does not parse;
    TOO_LONG if it parses but its canonical form will not fit the column.

    Tries the three grammars in the SAME ORDER as parse_numeric_value (mixed,
    fraction, decimal). Sharing the regexes is not enough to prevent drift — the
    order is, because the load-bearing \\s+ in _MIXED_RE interacts with greediness.

    Structural form is preserved (mixed stays mixed, fraction stays fraction) and
    fractions are NOT reduced: an author who writes 6/4 reopens the editor and sees
    6/4. Reduction happens only at comparison time, inside Fraction.
    """
    s = _coerce_numeric_input(s).strip()
    if len(s) > MAX_STORED_NUMERIC_CHARS:
        return None

    result = None
    m = _MIXED_RE.match(s)
    if m:
        sign, whole, numerator, denominator = m.groups()
        if int(denominator) == 0:
            return None
        # _MIXED_RE carries the sign in its OWN group and leaves the whole part
        # unsigned, unlike _FRAC_RE where the sign lives inside the numerator.
        # Dropping this re-prepend silently stores "1 1/2" for "-1 1/2".
        value = int(whole) + Fraction(int(numerator), int(denominator))
        if sign == "-":
            value = -value
        if value == 0:
            return "0"
        prefix = "-" if sign == "-" else ""
        result = f"{prefix}{int(whole)} {int(numerator)}/{int(denominator)}"
    else:
        m = _FRAC_RE.match(s)
        if m:
            numerator, denominator = int(m.group(1)), int(m.group(2))
            if denominator == 0:
                return None
            if numerator == 0:
                return "0"
            result = f"{numerator}/{denominator}"
        else:
            dec = parse_number(s)
            if dec is None:
                return None
            if dec == 0:
                # Covers "0", "00", "-0", "-0.0" — never store "-0".
                return "0"
            result = format_decimal_plain(dec)

    # Canonicalisation is NOT length-preserving: "." + 63 digits is a legal 64-char
    # input whose canonical form is "0.111..." at 65. Without this re-check that
    # input dies in _post_clean's full_clean with a max-length error the author
    # cannot act on, or reaches _clean_save's unwrapped full_clean as a 500.
    if len(result) > MAX_STORED_NUMERIC_CHARS:
        return TOO_LONG
    return result


def canonical_tolerance_text(s):
    """Canonical storage text for a tolerance.

    Zero has exactly ONE encoding: the empty string. Blank input and every spelling
    of zero both map to "". Without this, an author typing 0 would store the truthy
    string "0" and the reveal would start printing "+/- 0" where a zero tolerance is
    hidden today. This helper is the single place that decision is made.

    Returns "" for blank-or-zero, the canonical text for a positive value, TOO_LONG
    propagated from canonical_numeric_text, and None for unparseable OR negative.
    """
    text = _coerce_numeric_input(s).strip()
    if text == "":
        return ""
    canonical = canonical_numeric_text(text)
    if canonical is None or canonical is TOO_LONG:
        return canonical
    if canonical == "0":
        return ""
    if parse_numeric_value(canonical) < 0:
        return None
    return canonical
```

`Fraction` is already imported at the top of `marking.py`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_questions_2b_marking.py -k "canonical" -v`

Expected: PASS.

- [ ] **Step 5: Falsify three tests**

1. Drop the `if len(result) > MAX_STORED_NUMERIC_CHARS` re-check → the three
   `output_overflow` cases return a 65-char string instead of `TOO_LONG`.
2. Delete the mixed-path `prefix` and emit `f"{int(whole)} ..."` → `-1 1/2` canonicalises to
   `1 1/2`, a silently wrong stored answer.
3. Make `canonical_tolerance_text` fall through to `canonical_numeric_text` for zero (remove the
   `canonical == "0"` branch) → `"0"` is returned and the `± 0` reveal regression reappears.

Restore after each and record the observed failure.

- [ ] **Step 6: Commit**

```bash
git add courses/marking.py tests/test_questions_2b_marking.py
git commit -m "feat(marking): add canonical_numeric_text and canonical_tolerance_text

Write-side normalisers that make a number or fraction round-trip exactly:
trailing zeros stripped, comma normalised, structural form preserved, fractions
left unreduced, every spelling of zero collapsed to '0' (and, for a tolerance,
to '')."
```

---

### Task 3: The model validators

**Files:**
- Modify: `courses/marking.py`
- Test: `tests/test_questions_2b_marking.py`

**Interfaces:**
- Consumes: `canonical_numeric_text`, `canonical_tolerance_text`, `TOO_LONG`.
- Produces: `validate_numeric_text(value)`, `validate_tolerance_text(value)`. **Migration `0058`
  serialises these as the dotted paths `courses.marking.validate_numeric_text` /
  `courses.marking.validate_tolerance_text`, so they must never be moved or renamed without a
  follow-up migration.**

- [ ] **Step 1: Write the failing tests**

```python
def test_validate_numeric_text_rejects_unparseable_and_too_long():
    from django.core.exceptions import ValidationError

    from courses.marking import validate_numeric_text

    with pytest.raises(ValidationError):
        validate_numeric_text("abc")
    # 64 chars, passes MaxLengthValidator, canonicalises to 65. A None-only check
    # lets this through and stores non-canonical, uneditable text.
    with pytest.raises(ValidationError):
        validate_numeric_text("." + "1" * 63)
    validate_numeric_text("3/2")  # must not raise


def test_validate_tolerance_text_accepts_blank_and_rejects_negative():
    from django.core.exceptions import ValidationError

    from courses.marking import validate_tolerance_text

    validate_tolerance_text("")  # must not raise
    validate_tolerance_text("1/100")
    with pytest.raises(ValidationError):
        validate_tolerance_text("-1")
    with pytest.raises(ValidationError):
        validate_tolerance_text("abc")
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_questions_2b_marking.py -k "validate_numeric_text or validate_tolerance_text" -v`

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement in `courses/marking.py`**

Add `from django.core.exceptions import ValidationError` and
`from django.utils.translation import gettext_lazy as _` to the imports, then:

```python
def validate_numeric_text(value):
    """Field validator for ShortNumericQuestionElement.value.

    Must reject TOO_LONG as well as None. A 64-character input whose canonical form
    is 65 passes MaxLengthValidator; if this checks only for None it also passes
    here, clean() correctly declines to rewrite it, and non-canonical text is saved
    — leaving an element that cannot be re-saved from the editor.
    """
    result = canonical_numeric_text(value)
    if result is None or result is TOO_LONG:
        raise ValidationError(_("Enter a number or fraction."))


def validate_tolerance_text(value):
    """Field validator for ShortNumericQuestionElement.tolerance.

    Accepts "" (full_clean never passes it here — run_validators skips empty_values
    — but a direct unit test will, so the behaviour is pinned rather than incidental).
    """
    if value == "":
        return
    result = canonical_tolerance_text(value)
    if result is None or result is TOO_LONG:
        raise ValidationError(_("Enter a non-negative number or fraction."))
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_questions_2b_marking.py -k "validate_numeric_text or validate_tolerance_text" -v`

Expected: PASS.

- [ ] **Step 5: Falsify**

Change both validators to check only `is None`. The `"." + "1"*63` assertion must fail. Restore.

- [ ] **Step 6: Commit**

```bash
git add courses/marking.py tests/test_questions_2b_marking.py
git commit -m "feat(marking): add validate_numeric_text/validate_tolerance_text

Model-level field validators replacing the MinValueValidator(0) that the tolerance
column loses. Both reject the TOO_LONG sentinel as well as None: a 64-char input
canonicalising to 65 otherwise passes every gate and stores uneditable text."
```

---

### Task 4: Model fields, `clean()`, `mark()`, and migration `0058`

The model change and the migration must land in one commit — a model/migration mismatch fails
`makemigrations --check` and every DB-backed test.

**Files:**
- Modify: `courses/models.py:22-25` (imports), `:2150-2173` (the element)
- Create: `courses/migrations/0058_shortnumeric_text_value.py`
- Test: `tests/test_questions_2b_marking.py`, `courses/tests/test_shortnumeric_migration.py` (new)
- Fix (breaks in this task): `tests/test_questions_2b_authoring.py:81`,
  `tests/test_lal_loader_units.py:597`

**Interfaces:**
- Consumes: everything from tasks 1–3.
- Produces: `ShortNumericQuestionElement.value: str`, `.tolerance: str` (`""` = zero),
  `.clean()`, `.mark(answer) -> MarkResult` with `reveal={"value": str, "tolerance": str}`.

- [ ] **Step 1: Write the failing model tests**

Append to `tests/test_questions_2b_marking.py`:

```python
@pytest.mark.django_db
def test_shortnumeric_marks_exact_fractions():
    from courses.models import ShortNumericQuestionElement

    q = ShortNumericQuestionElement.objects.create(stem="g?", value="1/3", tolerance="")
    assert q.mark("1/3").correct is True
    assert q.mark("2/6").correct is True
    assert q.mark("0.333").correct is False
    assert q.mark("0.33333333").correct is False


@pytest.mark.django_db
def test_shortnumeric_accepts_every_spelling_of_the_same_value():
    from courses.models import ShortNumericQuestionElement

    q = ShortNumericQuestionElement.objects.create(stem="g?", value="3/2", tolerance="")
    for answer in ["3/2", "6/4", "15/10", "1 1/2", "1.5", "1,5"]:
        assert q.mark(answer).correct is True, answer


@pytest.mark.django_db
def test_shortnumeric_fractional_tolerance():
    from courses.models import ShortNumericQuestionElement

    q = ShortNumericQuestionElement.objects.create(stem="?", value="1.5", tolerance="1/100")
    assert q.mark("1.505").correct is True
    assert q.mark("1.52").correct is False


@pytest.mark.django_db
def test_shortnumeric_zero_tolerance_from_both_spellings():
    from courses.models import ShortNumericQuestionElement

    for tol in ["", "0"]:
        q = ShortNumericQuestionElement.objects.create(stem="?", value="1.0", tolerance=tol)
        assert q.mark("1.0").correct is True
        assert q.mark("1.01").correct is False


@pytest.mark.django_db
def test_shortnumeric_junk_value_marks_incorrect_without_raising():
    from courses.models import ShortNumericQuestionElement

    q = ShortNumericQuestionElement.objects.create(stem="?", value="junk", tolerance="")
    assert q.mark("1").correct is False


@pytest.mark.django_db
def test_shortnumeric_full_clean_rejects_and_reports_the_right_key():
    from django.core.exceptions import ValidationError

    from courses.models import ShortNumericQuestionElement

    with pytest.raises(ValidationError) as bad_value:
        ShortNumericQuestionElement(stem="?", value="abc").full_clean()
    assert "value" in bad_value.value.error_dict

    # value="1" is load-bearing: without it, value=="" raises "cannot be blank"
    # and the test passes whether or not validate_tolerance_text exists.
    with pytest.raises(ValidationError) as bad_tol:
        ShortNumericQuestionElement(stem="?", value="1", tolerance="-1").full_clean()
    assert "tolerance" in bad_tol.value.error_dict

    with pytest.raises(ValidationError) as too_long:
        ShortNumericQuestionElement(stem="?", value="." + "1" * 63).full_clean()
    assert "value" in too_long.value.error_dict


@pytest.mark.django_db
def test_shortnumeric_clean_canonicalises_and_does_not_null_a_rejected_field():
    from django.core.exceptions import ValidationError

    from courses.models import ShortNumericQuestionElement

    ok = ShortNumericQuestionElement(stem="?", value="1.50000000", tolerance="0")
    ok.full_clean()
    assert ok.value == "1.5"
    assert ok.tolerance == ""

    # full_clean runs clean() even after clean_fields() raised, so an unguarded
    # rewrite would leave None (or the TOO_LONG object) in a non-null column.
    bad = ShortNumericQuestionElement(stem="?", value="abc")
    with pytest.raises(ValidationError):
        bad.full_clean()
    assert bad.value == "abc"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_questions_2b_marking.py -k "shortnumeric_marks or spelling or fractional_tolerance or zero_tolerance_from or junk_value or full_clean_rejects or clean_canonicalises" -v`

Expected: FAIL — the `DecimalField` rejects `"1/3"` with `InvalidOperation`/`ValidationError`.

- [ ] **Step 3: Change the model**

In `courses/models.py`, replace line 25's `from courses.marking import parse_number` with:

```python
from courses.marking import TOO_LONG
from courses.marking import canonical_numeric_text
from courses.marking import canonical_tolerance_text
from courses.marking import parse_numeric_value
from courses.marking import validate_numeric_text
from courses.marking import validate_tolerance_text
```

(`parse_number`'s only use in this file is `mark()` at line 2167; leaving the import would fail
ruff F401 at the branch gate.)

Then replace the fields and `mark()`:

```python
    value = models.CharField(max_length=64, validators=[validate_numeric_text])
    tolerance = models.CharField(
        max_length=64, blank=True, default="", validators=[validate_tolerance_text]
    )
    elements = GenericRelation(Element)

    def build_answer(self, post):
        return post.get("answer", "")

    def clean(self):
        # Canonicality is ENFORCED here, not merely conventional at each caller:
        # the validators check parseability, so value="1.50000000" tolerance="0"
        # would otherwise validate and store non-canonical text (defect 3
        # reconstituted, plus a truthy "0" tolerance that prints "+/- 0").
        #
        # Both guards are load-bearing. full_clean() runs clean() EVEN WHEN
        # clean_fields() has already raised, so on value="abc" this executes with
        # a rejecting canonicaliser; an unguarded assignment would leave None in a
        # non-null column, and a None-only guard would leave the TOO_LONG object,
        # which to_python stringifies into "<object object at 0x...>".
        super().clean()
        canonical_value = canonical_numeric_text(self.value)
        if canonical_value is not None and canonical_value is not TOO_LONG:
            self.value = canonical_value
        canonical_tolerance = canonical_tolerance_text(self.tolerance)
        if canonical_tolerance is not None and canonical_tolerance is not TOO_LONG:
            self.tolerance = canonical_tolerance

    def mark(self, answer):
        want = parse_numeric_value(self.value)
        got = parse_numeric_value(answer)
        tol = parse_numeric_value(self.tolerance)
        # Explicit `is None`, NOT `... or Fraction(0)`: Fraction(0) is falsy, so the
        # `or` form is right only by accident and breaks under any reordering.
        if tol is None:
            tol = Fraction(0)
        # `want is not None` is a real guard: a hand-edited row or a pre-migration
        # import can hold junk, and the check endpoint must mark incorrect, never 500.
        is_correct = want is not None and got is not None and abs(got - want) <= tol
        return MarkResult(
            correct=is_correct,
            fraction=1.0 if is_correct else 0.0,
            reveal={"value": self.value, "tolerance": self.tolerance},
        )
```

Add `from fractions import Fraction` to `courses/models.py` imports if absent.

- [ ] **Step 4: Write migration `0058`**

Create `courses/migrations/0058_shortnumeric_text_value.py`:

```python
"""Convert ShortNumericQuestionElement.value/tolerance from numeric(20,8) to text.

DELIBERATELY IRREVERSIBLE. RunPython has no reverse_code, so `migrate` backwards
raises IrreversibleError. This is not laziness: reversing would run step 3's
RemoveField backwards BEFORE the data step, re-adding `value` as a non-null
DecimalField with no default, which fails outright on any populated table — a
`backwards` function would be unreachable code masquerading as a rollback path.
The reverse is also lossy by nature: 1/3 has no Decimal form, which is the entire
premise of this change. Rolling back this deploy means restoring a database backup.
"""

from decimal import Decimal
from decimal import localcontext

from django.db import migrations
from django.db import models

import courses.marking

BATCH = 500


def _format_decimal_plain(value):
    """FROZEN copy of courses.marking.format_decimal_plain.

    Deliberately not imported. A migration must keep doing what it did the day it
    shipped; importing live helpers means a later change to the precision or the
    storage cap retroactively alters what 0058 does on a fresh deploy. prec is
    hard-coded because MAX_STORED_NUMERIC_CHARS is equally forbidden to import; the
    old column is numeric(20,8), so 80 is far more than sufficient.
    """
    with localcontext() as ctx:
        ctx.prec = 80
        return format(Decimal(value).normalize(), "f")


def forwards(apps, schema_editor):
    Element = apps.get_model("courses", "ShortNumericQuestionElement")

    # Counting pass FIRST. A negative tolerance canonicalises to None, and writing
    # NULL into a non-null column would raise IntegrityError partway through an
    # IRREVERSIBLE production migration. Abort before any write so the operator
    # repairs the data deliberately. RuntimeError, not CommandError: this must fail
    # identically under `manage.py migrate` and under pytest.
    negative = list(
        Element.objects.filter(tolerance__lt=0).values_list("pk", flat=True)[:50]
    )
    if negative:
        raise RuntimeError(
            "Cannot migrate: ShortNumericQuestionElement rows have a negative "
            f"tolerance (pks: {negative}). Repair them before running 0058."
        )

    batch = []
    for row in Element.objects.all().iterator(chunk_size=BATCH):
        # Operate on the Decimal DIRECTLY. str(Decimal("0.00000000")) is '0E-8' —
        # E-notation, which the grammars reject — so routing these through a text
        # canonicaliser would return None for EVERY zero tolerance and every value
        # below 1e-6, i.e. most rows.
        row.value_text = _format_decimal_plain(row.value)
        if row.tolerance == 0:
            row.tolerance_text = ""
        elif row.tolerance < 0:
            # Unreachable: the counting pass aborted. Belt-and-braces.
            raise RuntimeError(f"negative tolerance survived the counting pass: pk={row.pk}")
        else:
            row.tolerance_text = _format_decimal_plain(row.tolerance)
        if row.value_text is None or row.tolerance_text is None:
            raise RuntimeError(f"refusing to write NULL for pk={row.pk}")
        batch.append(row)
        # Accumulate and FLUSH. batch_size bounds rows per statement, not Python
        # objects held, so a single terminal bulk_update would hold every row.
        if len(batch) >= BATCH:
            Element.objects.bulk_update(batch, ["value_text", "tolerance_text"])
            batch.clear()
    if batch:
        Element.objects.bulk_update(batch, ["value_text", "tolerance_text"])


class Migration(migrations.Migration):
    dependencies = [("courses", "0057_contentnode_published")]

    operations = [
        migrations.AddField(
            model_name="shortnumericquestionelement",
            name="value_text",
            field=models.CharField(default="", max_length=64),
        ),
        migrations.AddField(
            model_name="shortnumericquestionelement",
            name="tolerance_text",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.RunPython(forwards),
        migrations.RemoveField(model_name="shortnumericquestionelement", name="value"),
        migrations.RemoveField(model_name="shortnumericquestionelement", name="tolerance"),
        migrations.RenameField(
            model_name="shortnumericquestionelement",
            old_name="value_text",
            new_name="value",
        ),
        migrations.RenameField(
            model_name="shortnumericquestionelement",
            old_name="tolerance_text",
            new_name="tolerance",
        ),
        migrations.AlterField(
            model_name="shortnumericquestionelement",
            name="value",
            field=models.CharField(
                max_length=64, validators=[courses.marking.validate_numeric_text]
            ),
        ),
        migrations.AlterField(
            model_name="shortnumericquestionelement",
            name="tolerance",
            field=models.CharField(
                blank=True,
                default="",
                max_length=64,
                validators=[courses.marking.validate_tolerance_text],
            ),
        ),
    ]
```

- [ ] **Step 5: Write the migration tests**

Create `courses/tests/test_shortnumeric_migration.py`, following
`courses/tests/test_publish_migration.py` as the template:

```python
"""Migration 0058 conversion tests.

transaction=True is MANDATORY: these tests unapply and re-apply a migration, which
cannot run inside the test's atomic block. The `finally` restore is equally
mandatory — a half-restored migration state poisons every later test on the same
xdist worker with failures that land nowhere near this file.
"""

from decimal import Decimal

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = [("courses", "0057_contentnode_published")]
AFTER = [("courses", "0058_shortnumeric_text_value")]


def _migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return executor


@pytest.mark.django_db(transaction=True)
def test_0058_strips_trailing_zeros_and_empties_zero_tolerance():
    try:
        old_apps = _migrate(BEFORE).loader.project_state(BEFORE).apps
        Element = old_apps.get_model("courses", "ShortNumericQuestionElement")
        plain = Element.objects.create(
            stem="a", value=Decimal("1.50000000"), tolerance=Decimal("0.10000000")
        )
        zero_tol = Element.objects.create(
            stem="b", value=Decimal("40401.00000000"), tolerance=Decimal("0")
        )
        # The row that catches the str() trap: str(Decimal("0.00000001")) is '1E-8'.
        tiny = Element.objects.create(
            stem="c", value=Decimal("2.00000000"), tolerance=Decimal("0.00000001")
        )

        new_apps = _migrate(AFTER).loader.project_state(AFTER).apps
        New = new_apps.get_model("courses", "ShortNumericQuestionElement")
        assert (New.objects.get(pk=plain.pk).value, New.objects.get(pk=plain.pk).tolerance) == ("1.5", "0.1")
        assert (New.objects.get(pk=zero_tol.pk).value, New.objects.get(pk=zero_tol.pk).tolerance) == ("40401", "")
        assert New.objects.get(pk=tiny.pk).tolerance == "0.00000001"
    finally:
        _migrate(AFTER)


@pytest.mark.django_db(transaction=True)
def test_0058_aborts_on_a_negative_tolerance_before_writing_anything():
    try:
        old_apps = _migrate(BEFORE).loader.project_state(BEFORE).apps
        Element = old_apps.get_model("courses", "ShortNumericQuestionElement")
        Element.objects.create(
            stem="neg", value=Decimal("1.00000000"), tolerance=Decimal("-0.5")
        )
        with pytest.raises(RuntimeError, match="negative"):
            _migrate(AFTER)
    finally:
        Element = _migrate(BEFORE).loader.project_state(BEFORE).apps.get_model(
            "courses", "ShortNumericQuestionElement"
        )
        Element.objects.all().delete()
        _migrate(AFTER)


@pytest.mark.django_db(transaction=True)
def test_0058_is_irreversible():
    from django.db.migrations.exceptions import IrreversibleError

    try:
        _migrate(AFTER)
        with pytest.raises(IrreversibleError):
            _migrate(BEFORE)
    finally:
        _migrate(AFTER)
```

- [ ] **Step 6: Fix the two existing tests this task breaks**

`tests/test_questions_2b_authoring.py:81` — change
`q.value == Decimal("3.14") and q.tolerance == Decimal("0.01")` to
`q.value == "3.14" and q.tolerance == "0.01"`.

`tests/test_lal_loader_units.py:597` — change `obj.value == Decimal("2.5")` to
`obj.value == "2.5"` (`"2.5" == Decimal("2.5")` is `False`).

- [ ] **Step 7: Run everything for this task**

```bash
uv run pytest tests/test_questions_2b_marking.py courses/tests/test_shortnumeric_migration.py -v
uv run pytest tests/test_questions_2b_authoring.py tests/test_lal_loader_units.py -v
uv run pytest courses/tests/test_publish_makemigrations.py -v
```

Expected: all PASS. `test_no_pending_migrations` is the check that the hand-written five-op chain
left a state matching the model — a leftover `default`, a missing `blank` or a different validator
ordering all surface here and nowhere else.

- [ ] **Step 8: Falsify**

1. In the migration, replace `_format_decimal_plain(row.tolerance)` with `str(row.tolerance)` and
   drop the `tolerance == 0` branch → the `tiny` assertion fails on `'1E-8'`. This is the mutant
   that would have taken down the production migration.
2. Delete the counting pass → the negative-tolerance test dies with `IntegrityError` mid-write
   instead of a clean `RuntimeError`.
3. Remove the `is not TOO_LONG` half of `clean()`'s guards → `clean_canonicalises` still passes,
   but a `value="." + "1"*63` instance ends up holding the sentinel. (Note: the guard's `None`
   half is covered by `test_..._does_not_null_a_rejected_field`.)

- [ ] **Step 9: Commit**

```bash
git add courses/models.py courses/migrations/0058_shortnumeric_text_value.py \
  courses/tests/test_shortnumeric_migration.py tests/test_questions_2b_marking.py \
  tests/test_questions_2b_authoring.py tests/test_lal_loader_units.py
git commit -m "feat(courses): store the numeric answer as canonical text

value/tolerance move from DecimalField(20,8) to CharField(64) holding canonical
text, compared as exact Fractions. 1/3 no longer rounds to 0.33333333, and an
author can enter 3/2. Zero tolerance has one encoding: the empty string.

Migration 0058 is irreversible by design and operates on Decimals directly —
str(Decimal('0.00000000')) is '0E-8', which the grammars reject, so a text
canonicaliser would NULL every zero-tolerance row mid-run."
```

---

### Task 5: The authoring form, the editor template, and i18n

**Files:**
- Modify: `courses/element_forms.py:744-786`
- Modify: `templates/courses/manage/editor/_edit_shortnumericquestion.html`
- Modify: `locale/pl/LC_MESSAGES/django.po`, `locale/en/LC_MESSAGES/django.po`
- Test: `tests/test_questions_2b_forms.py`, `tests/test_i18n_questions_2b.py`
- Fix (breaks in this task): `tests/test_questions_2b_forms.py:28-29`

**Interfaces:**
- Consumes: `canonical_numeric_text`, `canonical_tolerance_text`, `TOO_LONG`,
  `parse_numeric_value`.
- Produces: `clean_value`/`clean_tolerance` returning canonical `str`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_questions_2b_forms.py` (reuse the file's existing `_form` helper):

```python
def test_shortnumeric_form_stores_canonical_text():
    ok = _form("shortnumericquestion", {"stem": "<p>q</p>", "value": "3/2", "tolerance": "0"})
    assert ok.is_valid(), ok.errors
    assert ok.cleaned_data["value"] == "3/2"
    assert ok.cleaned_data["tolerance"] == ""

    comma = _form("shortnumericquestion", {"stem": "<p>q</p>", "value": "1,5", "tolerance": ""})
    assert comma.is_valid()
    assert comma.cleaned_data["value"] == "1.5"


def test_shortnumeric_form_unparseable_tolerance_is_a_field_error_not_a_typeerror():
    # canonical_tolerance_text returns None for BOTH negative and unparseable, so
    # the negative re-derivation runs on "abc" too — and None < 0 raises TypeError.
    bad = _form("shortnumericquestion", {"stem": "<p>q</p>", "value": "1", "tolerance": "abc"})
    assert not bad.is_valid()
    assert "tolerance" in bad.errors

    zero_denominator = _form(
        "shortnumericquestion", {"stem": "<p>q</p>", "value": "1", "tolerance": "1/0"}
    )
    assert not zero_denominator.is_valid()
    assert "tolerance" in zero_denominator.errors


def test_shortnumeric_form_negative_tolerance_keeps_its_own_message():
    neg = _form("shortnumericquestion", {"stem": "<p>q</p>", "value": "1", "tolerance": "-1"})
    assert not neg.is_valid()
    assert any("negative" in str(e).lower() for e in neg.errors["tolerance"])


def test_shortnumeric_form_distinguishes_the_two_length_failures():
    # 64 chars: passes MaxLengthValidator, canonical form is 65 -> custom message.
    overflow = _form(
        "shortnumericquestion", {"stem": "<p>q</p>", "value": "." + "1" * 63, "tolerance": ""}
    )
    assert not overflow.is_valid()
    assert any("too long" in str(e).lower() for e in overflow.errors["value"])

    # >64 chars: never reaches clean_value -> Django's built-in message.
    too_many = _form(
        "shortnumericquestion", {"stem": "<p>q</p>", "value": "1" * 70, "tolerance": ""}
    )
    assert not too_many.is_valid()
    assert any("64 characters" in str(e) for e in too_many.errors["value"])


@pytest.mark.django_db
def test_shortnumeric_editor_round_trips_a_fraction_and_a_tolerance():
    from courses.element_forms import ShortNumericQuestionElementForm
    from courses.models import ShortNumericQuestionElement

    q = ShortNumericQuestionElement.objects.create(stem="?", value="3/2", tolerance="0.1")
    form = ShortNumericQuestionElementForm(instance=q)
    assert form["value"].value() == "3/2"
    # Defect 3: this rendered "0.10000000" before, so inserting a digit made nine
    # decimal places and DecimalValidator refused the edit.
    assert form["tolerance"].value() == "0.1"

    # The user's exact reported sequence: change 0.1 to 0.01.
    edited = ShortNumericQuestionElementForm(
        {"stem": "<p>?</p>", "value": "3/2", "tolerance": "0.01",
         "marking_mode": q.marking_mode, "max_attempts": q.max_attempts,
         "max_marks": q.max_marks, "explanation": ""},
        instance=q,
    )
    assert edited.is_valid(), edited.errors


def test_guess_number_tolerance_error_text_is_unchanged():
    # Guards against a blanket find-replace of the msgid shared with :340.
    bad = _form("guessnumberquestion", {"stem": "<p>Guess {{5}}</p>", "tolerance": "abc"})
    assert not bad.is_valid()
    assert any("3.14 or 3,14" in str(e) for e in bad.errors["tolerance"])
```

Also update the two pre-existing assertions at `tests/test_questions_2b_forms.py:28-29` to
`== "3.14"` and `== "0.01"` — `clean_*` now return `str`, and `"0,01"` canonicalises to `"0.01"`,
**not** `""`, because it is non-zero.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_questions_2b_forms.py -k shortnumeric -v`

Expected: FAIL. The round-trip test in particular shows `'0.10000000'`.

- [ ] **Step 3: Rewrite the form**

Replace `ShortNumericQuestionElementForm`'s `__init__`, `_num`, `clean_value` and
`clean_tolerance` (`courses/element_forms.py:761-786`) with:

```python
    def clean_value(self):
        raw = self.cleaned_data.get("value", "")
        canonical = canonical_numeric_text(raw)
        if canonical is TOO_LONG:
            raise forms.ValidationError(
                _("That number is too long (at most 64 characters once normalised).")
            )
        if canonical is None:
            raise forms.ValidationError(
                _("Enter a number or fraction (e.g. 3.14, 3,14 or 3/2).")
            )
        return canonical

    def clean_tolerance(self):
        raw = self.cleaned_data.get("tolerance", "")
        canonical = canonical_tolerance_text(raw)
        if canonical is TOO_LONG:
            raise forms.ValidationError(
                _("That number is too long (at most 64 characters once normalised).")
            )
        if canonical is not None:
            return canonical
        # canonical_tolerance_text collapses "unparseable" and "negative" into one
        # None, so re-derive the reason. The `is not None` guard is NOT optional:
        # unparseable input reaches here too, and None < 0 raises TypeError — a 500
        # in the editor on the commonest bad input.
        parsed = parse_numeric_value(raw)
        if parsed is not None and parsed < 0:
            raise forms.ValidationError(_("Tolerance cannot be negative."))
        raise forms.ValidationError(
            _("Enter a number or fraction (e.g. 3.14, 3,14 or 3/2).")
        )
```

Delete the `__init__` override and the `_num` helper entirely. Do **not** add a custom
over-length branch: the fields are now ModelForm-generated from `CharField(max_length=64)`, so
`MaxLengthValidator` fires inside `field.clean()` before `clean_value` runs, and a custom branch
would be dead code.

Add the imports `canonical_numeric_text`, `canonical_tolerance_text`, `TOO_LONG`,
`parse_numeric_value` from `courses.marking`. **Leave line 340's
`_("Enter a number (e.g. 3.14 or 3,14).")` untouched** — that is `GuessNumberElementForm`, which
must not advertise fractions.

- [ ] **Step 4: Update the editor template**

In `templates/courses/manage/editor/_edit_shortnumericquestion.html`, replace lines 11 and 15:

```html
  <input type="text" name="value" inputmode="text" maxlength="64"
         placeholder="{% trans '3.14, 3/2 or 1 1/2' %}"
         value="{{ form.value.value|default_if_none:'' }}">
```

```html
  <input type="text" name="tolerance" inputmode="text" maxlength="64"
         placeholder="{% trans '3.14, 3/2 or 1 1/2' %}"
         value="{{ form.tolerance.value|default_if_none:'' }}">
```

The `default_if_none` swap is a **no-op tidy** — `"0"` is a truthy string, so both filters behave
identically now that the field is a `CharField`. Do not write a test for it; none can fail.

- [ ] **Step 5: Regenerate and hand-translate the catalogues**

```bash
uv run python manage.py makemessages -l pl -l en
```

Then in `locale/pl/LC_MESSAGES/django.po`: clear every `#, fuzzy` marker `msgmerge` added,
**delete** each wrongly prefilled msgstr, and **hand-write** the Polish for the new msgids:

| msgid | Polish |
|---|---|
| `Enter a number or fraction (e.g. 3.14, 3,14 or 3/2).` | `Wpisz liczbę lub ułamek (np. 3,14 lub 3/2).` |
| `That number is too long (at most 64 characters once normalised).` | `Ta liczba jest za długa (najwyżej 64 znaki po znormalizowaniu).` |
| `3.14, 3/2 or 1 1/2` | `3,14, 3/2 lub 1 1/2` |
| `Enter a number or fraction.` | `Wpisz liczbę lub ułamek.` |
| `Enter a non-negative number or fraction.` | `Wpisz nieujemną liczbę lub ułamek.` |

In `locale/en/LC_MESSAGES/django.po`: clear fuzzy markers only. **Leave the en msgstrs empty** —
`test_no_fuzzy_entries` covers both catalogues but `test_pl_has_no_untranslated_msgid` is PL-only.

The old msgid `Enter a number (e.g. 3.14 or 3,14).` **stays in both catalogues** — line 340 still
references it. Expect its `#:` comment to narrow from `:340 :774` to `:340`; that is correct.

Add the five new msgids to the parametrised list in
`tests/test_i18n_questions_2b.py::test_pl_translation_present`.

- [ ] **Step 6: Run the tests**

```bash
uv run pytest tests/test_questions_2b_forms.py -v
uv run pytest tests/test_i18n_questions_2b.py tests/test_i18n_po_health.py -v
```

Expected: all PASS.

- [ ] **Step 7: Falsify**

Drop the `parsed is not None` guard in `clean_tolerance` → the unparseable-tolerance test fails
with `TypeError`, not an assertion error. Restore.

Change the 64-char length test to a 70-char input → it fails with Django's built-in message,
demonstrating why the two cases are separate tests. Restore.

- [ ] **Step 8: Commit**

```bash
git add courses/element_forms.py templates/courses/manage/editor/_edit_shortnumericquestion.html \
  locale/pl/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.po \
  tests/test_questions_2b_forms.py tests/test_i18n_questions_2b.py
git commit -m "feat(editor): accept fractions in the numeric-question editor

clean_value/clean_tolerance canonicalise instead of parsing to Decimal, so a
tolerance of 0.1 renders as '0.1' rather than '0.10000000' — the bug that made
editing it to 0.01 produce nine decimal places and get refused."
```

---

### Task 6: The student and reveal templates

**Files:**
- Modify: `templates/courses/elements/shortnumericquestionelement.html:8`
- Modify: `templates/courses/elements/_reveal_shortnumeric.html:3`
- Test: `tests/test_questions_2b_consumption.py`

**Interfaces:** Consumes `mark()`'s `reveal` dict of canonical strings.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.django_db
def test_shortnumeric_reveal_shows_the_canonical_string(client, ...):
    # Use the file's existing consumption-test scaffolding to render feedback for
    # an element with value="1/3", tolerance="".
    ...
    assert "1/3" in html
    assert "0.33333333" not in html
    assert "±" not in html  # zero tolerance renders no tolerance clause


@pytest.mark.django_db
def test_shortnumeric_reveal_under_polish_locale_keeps_the_dot():
    # Accepted trade-off: canonical storage is '.'-only, so the reveal no longer
    # localises the separator. Pinned so the behaviour is deliberate.
    from django.utils import translation

    with translation.override("pl"):
        ...
        assert "3.14" in html


@pytest.mark.django_db
def test_student_numeric_input_uses_text_inputmode():
    # The mobile trap: inputmode="decimal" renders a numeric keypad with no "/",
    # so the whole feature would be untypable on a phone while desktop tests pass.
    ...
    assert 'inputmode="text"' in html
```

Fill the `...` from the existing fixtures in `tests/test_questions_2b_consumption.py`.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_questions_2b_consumption.py -k "reveal or inputmode" -v`

Expected: FAIL — the reveal shows `0.33333333` and the input shows `inputmode="decimal"`.

- [ ] **Step 3: Edit the templates**

`shortnumericquestionelement.html:8` — `inputmode="decimal"` → `inputmode="text"`.

`_reveal_shortnumeric.html` line 3 becomes:

```html
  <strong>{{ mark_result.reveal.value }}</strong>{% if mark_result.reveal.tolerance %} ± {{ mark_result.reveal.tolerance }}{% endif %}
```

The `{% if %}` is correct **only because** zero tolerance is canonically `""`.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_questions_2b_consumption.py -v`

Expected: PASS. Update the two construction sites at `:65` to canonical strings while here.

- [ ] **Step 5: Commit**

```bash
git add templates/courses/elements/shortnumericquestionelement.html \
  templates/courses/elements/_reveal_shortnumeric.html \
  tests/test_questions_2b_consumption.py
git commit -m "feat(courses): let students type fractions and reveal the canonical answer

inputmode=text is the load-bearing half: a decimal keypad has no '/' key, so on a
phone the feature would be untypable while every desktop test passed."
```

---

### Task 7: Transfer — validator, importer, format version

**Files:**
- Modify: `courses/transfer/payloads.py:432-439`
- Modify: `courses/transfer/importer.py:671-677`
- Modify: `courses/transfer/schema.py:14`
- Test: `tests/test_transfer_validation.py`, `tests/test_transfer_import.py`,
  `tests/test_transfer_export.py`
- Fix (breaks in this task): `tests/test_transfer_validation.py:548`, `:557`

**Interfaces:** Consumes the canonicalisers and `TOO_LONG`. Produces no new symbols.

- [ ] **Step 1: Write the failing tests**

In `tests/test_transfer_validation.py`:

```python
def test_short_numeric_rejects_unparseable_value():
    _reject(
        doc_with(el_of("short_numeric", q_fields(value="abc", tolerance="0"))),
        "is not a valid number or fraction",
    )


def test_short_numeric_rejects_non_string_value_with_the_type_message():
    # The wrong-type branch is otherwise untested: the existing test's wrong-type
    # half is a TEXT element matching "text", not short_numeric.
    _reject(
        doc_with(el_of("short_numeric", q_fields(value=42, tolerance="0"))),
        "must be a decimal string",
    )


def test_short_numeric_rejects_a_canonical_overflow():
    _reject(
        doc_with(el_of("short_numeric", q_fields(value="." + "1" * 63, tolerance="0"))),
        "is not a valid number or fraction",
    )


def test_short_numeric_negative_tolerance_keeps_the_element_naming_message():
    _reject(
        doc_with(el_of("short_numeric", q_fields(value="1", tolerance="-1"))),
        "tolerance must not be negative",
    )


def test_short_numeric_unparseable_tolerance_rejects_without_a_typeerror():
    _reject(
        doc_with(el_of("short_numeric", q_fields(value="1", tolerance="abc"))),
        "is not a valid number or fraction",
    )


def test_short_numeric_accepts_empty_tolerance():
    # The export round-trip case: every zero-tolerance element now exports "".
    _accept(doc_with(el_of("short_numeric", q_fields(value="3/2", tolerance=""))))
```

Update `:548` and `:557` from `"decimal"` to `"is not a valid number or fraction"`.
(`Infinity`/`NaN` still reject — no grammar matches them — only the message changes.)

In `tests/test_transfer_import.py`:

```python
def test_zero_tolerance_element_round_trips(...):
    # Mutant: route the importer's tolerance through canonical_numeric_text —
    # "" becomes None and every existing zero-tolerance element fails to import.
    ...
    assert (copy.value, copy.tolerance) == ("3/2", "")


def test_fraction_value_round_trips(...):
    ...
    assert copy.value == "1/3"


def test_legacy_v10_payload_canonicalises(...):
    # "1.50000000" / "0.00000000" -> "1.5" / ""
    ...


def test_format_version_is_eleven():
    from courses.transfer.schema import FORMAT_VERSION

    assert FORMAT_VERSION == 11


def test_duplicate_element_preserves_a_fraction_and_empty_tolerance(...):
    # duplicate_element runs export -> _val_short_numeric -> _build_numeric in one
    # process; the cheapest end-to-end check of the ""-tolerance contract.
    from courses.builder import duplicate_element
    ...
    assert (copy.value, copy.tolerance) == ("3/2", "")
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_transfer_validation.py tests/test_transfer_import.py -k "short_numeric or tolerance or format_version or duplicate or round_trips" -v`

- [ ] **Step 3: Rewrite `_val_short_numeric`**

```python
def _val_short_numeric(data, elid, media_kinds):
    _exact_keys(data, Q_KEYS + ["value", "tolerance"], _("short_numeric data"))
    _check_question_fields(data, elid)
    for key in ("value", "tolerance"):
        if not isinstance(data[key], str):
            _err(_("%(what)s must be a decimal string."), what=key)
    if canonical_numeric_text(data["value"]) in (None, TOO_LONG):
        _err(_("%(what)s is not a valid number or fraction."), what="value")
    tolerance = canonical_tolerance_text(data["tolerance"])
    # Order is fixed. TOO_LONG first, so an over-long NEGATIVE tolerance (which
    # parses fine at the 256-char comparison cap) reports the length problem
    # rather than the sign. Then the negative branch, which keeps its
    # element-naming message — folding it into the generic parse failure would
    # drop the element id from a whole-course import's diagnostics.
    if tolerance is TOO_LONG:
        _err(_("%(what)s is not a valid number or fraction."), what="tolerance")
    if tolerance is None:
        parsed = parse_numeric_value(data["tolerance"])
        # `is not None` guard: unparseable input reaches here too, and None < 0
        # would turn `"tolerance": "abc"` into a 500 in the import view.
        if parsed is not None and parsed < 0:
            _err(_("Element '%(el)s': tolerance must not be negative."), el=elid)
        _err(_("%(what)s is not a valid number or fraction."), what="tolerance")
    return set()
```

Note `in (None, TOO_LONG)` uses `==` semantics on a `str`; that is safe here because a canonical
string never equals `None` or the sentinel object. Keep the `check_decimal_str` import only if
other validators still use it.

- [ ] **Step 4: Rewrite `_build_numeric`**

```python
def _build_numeric(data, assets):
    value = canonical_numeric_text(data["value"])
    tolerance = canonical_tolerance_text(data["tolerance"])
    # The payload validator already accepted these, so a rejection here is an
    # internal-consistency failure — and it must be a TransferError. _clean_save
    # does not wrap full_clean(), and the import view catches only TransferError,
    # so any other type turns a bad payload into a 500. "" is VALID, not a failure.
    if value is None or value is TOO_LONG or tolerance is None or tolerance is TOO_LONG:
        raise TransferError(_("short_numeric data is not a valid number or fraction."))
    q = ShortNumericQuestionElement(**_q_kwargs(data), value=value, tolerance=tolerance)
    return _clean_save(q), ()
```

- [ ] **Step 5: Bump `FORMAT_VERSION`**

`courses/transfer/schema.py:14` → `FORMAT_VERSION = 11`.

**Before merging**, re-read `FORMAT_VERSION` on the merge base and confirm no other open PR also
took 11 — two branches bumping the same line to the same value merge with no conflict. The same
check applies to the migration number: the base's leaf is `0057_contentnode_published`.

- [ ] **Step 6: Run**

```bash
uv run pytest tests/test_transfer_validation.py tests/test_transfer_import.py tests/test_transfer_export.py -v
```

Also repurpose `tests/test_transfer_export.py:121 test_short_numeric_decimals_are_strings`: it is
now tautological (`str()` on a `CharField` is a no-op), so change it to assert that a
fraction-valued element exports its canonical string.

- [ ] **Step 7: Falsify**

Route the importer's tolerance through `canonical_numeric_text` → the zero-tolerance round-trip
raises. Change `_val_short_numeric` to test only `is None` → the canonical-overflow test lets the
sentinel through. Drop the `parsed is not None` guard → the unparseable-tolerance test raises
`TypeError`.

- [ ] **Step 8: Commit**

```bash
git add courses/transfer/payloads.py courses/transfer/importer.py courses/transfer/schema.py \
  tests/test_transfer_validation.py tests/test_transfer_import.py tests/test_transfer_export.py
git commit -m "feat(transfer): carry canonical numeric text, FORMAT_VERSION 11

Deploy before transferring any course: an older build reading a fraction-bearing
zip would otherwise fail with a misleading 'not a valid decimal number' instead of
'unsupported format version'."
```

---

### Task 8: The LAL loader

**Files:**
- Modify: `courses/lal_loader/builders.py:397-406`
- Test: `tests/test_lal_loader_units.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_build_numeric_accepts_json_numbers(tmp_path):
    # The manifest is json.loads'd, so these are ordinary content. Decimal(2.5)
    # accepts them on master; a text canonicaliser without the coercion prologue
    # would raise AttributeError, and a bare str() would turn 0.00001 into '1e-05'.
    obj = build_element(
        course, unit,
        {"type": "numeric", "stem": "<p>n</p>", "value": 2.5, "tolerance": 0.00001},
        source_root=tmp_path, source_dir="x", allow_html=False,
    )
    assert (obj.value, obj.tolerance) == ("2.5", "0.00001")


def test_build_numeric_accepts_a_fraction(tmp_path):
    obj = build_element(
        course, unit,
        {"type": "numeric", "stem": "<p>n</p>", "value": "3/2", "tolerance": "0"},
        source_root=tmp_path, source_dir="x", allow_html=False,
    )
    assert (obj.value, obj.tolerance) == ("3/2", "")


def test_build_numeric_raises_loader_error_on_junk(tmp_path):
    from courses.lal_loader.builders import LoaderError

    with pytest.raises(LoaderError, match="unit"):
        build_element(
            course, unit,
            {"type": "numeric", "stem": "<p>n</p>", "value": "abc", "tolerance": "0"},
            source_root=tmp_path, source_dir="x", allow_html=False,
        )
```

Use the file's existing `_unit`/`CourseFactory` scaffolding for `course`/`unit`.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_lal_loader_units.py -k "build_numeric" -v`

- [ ] **Step 3: Implement**

```python
    if etype == "numeric":
        value = canonical_numeric_text(el["value"])
        tolerance = canonical_tolerance_text(el.get("tolerance", "0"))
        # No upstream validator here, unlike the transfer importer. Passing None
        # into objects.create() would surface as a context-free IntegrityError
        # mid-import; the old Decimal(...) at least raised at the parse site.
        if value is None or value is TOO_LONG or tolerance is None or tolerance is TOO_LONG:
            raise LoaderError(
                f"invalid numeric value {el['value']!r} in unit {unit.pk}"
            )
        return _attach(
            unit,
            ShortNumericQuestionElement.objects.create(
                stem=el["stem"], value=value, tolerance=tolerance,
                **_max_marks_kwargs(el),
            ),
        )
```

Add the three `courses.marking` imports. Remove the now-unused `Decimal` import **only if** no
other branch in the file uses it.

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_lal_loader_units.py -v`

Expected: PASS. Add the `tolerance == ""` assertion to
`test_build_numeric_with_points_sets_max_marks` while the file is open.

- [ ] **Step 5: Falsify**

Drop the coercion prologue from `canonical_numeric_text` → the JSON-numbers test raises
`AttributeError`. Route floats through a bare `str()` → `0.00001` becomes `None` and the loader
aborts. `2.5` alone passes under both mutants, which is why the small float is in the test.

- [ ] **Step 6: Commit**

```bash
git add courses/lal_loader/builders.py tests/test_lal_loader_units.py
git commit -m "feat(lal): canonicalise numeric values, raise LoaderError on junk"
```

---

### Task 9: Sweep the remaining tests and update the author docs

**Files:**
- Modify: `tests/test_quiz_answer.py:109`, `tests/test_quiz_consumption_render.py:50`,
  `tests/test_transfer_export.py:144`, `tests/test_transfer_import.py:186`,
  `courses/tests/test_question_restore.py:136`, `:290`
- Modify: `docs/help/course-admin/quiz-editors.md`, `docs/help/course-admin/quiz-editors.pl.md`

- [ ] **Step 1: Re-derive the sweep rather than trusting this list**

```bash
uv run python -c "print('grep both packages')"
grep -rn "ShortNumericQuestionElement" tests/ courses/tests/
grep -rn "short_numeric" tests/ courses/tests/
```

Every construction site must pass canonical **strings**. `courses/tests/` is a second test
package — scoping the sweep to `tests/` alone is how the restore sites get missed.

- [ ] **Step 2: Convert each site**

`value=Decimal("3.14")` → `value="3.14"`; `tolerance=Decimal("0")` and `tolerance=0` → `tolerance=""`;
`value=42` → `value="42"`. Leave
`tests/test_questions_2b_marking.py::test_shortnumeric_mark_tolerance_and_decimal_comma`
**green and unmodified** — it builds an in-memory instance with `value=Decimal("3.14")` and is the
only end-to-end evidence that the coercion prologue works. Add canonical-string equivalents
alongside it rather than replacing it.

- [ ] **Step 3: Update the author docs**

In `docs/help/course-admin/quiz-editors.md` (Short numeric section) and its Polish twin, replace
the "a numeric answer … tolerance 0 means an exact match" wording with: the field accepts a
decimal (`3.14` or `3,14`), a fraction (`3/2`) or a mixed number (`1 1/2`), for both the answer
and the tolerance; any equal value is accepted, so `6/4` matches `3/2`; **leave tolerance blank
for an exact match**. Keep the two files structurally parallel.

- [ ] **Step 4: Run the affected files**

```bash
uv run pytest tests/test_quiz_answer.py tests/test_quiz_consumption_render.py \
  courses/tests/test_question_restore.py -v
```

- [ ] **Step 5: Commit**

```bash
git add tests/ courses/tests/ docs/help/
git commit -m "test: sweep short-numeric construction sites to canonical strings

Also updates the author manuals: tolerance is now left BLANK for an exact match,
not set to 0."
```

---

### Task 10: e2e and the branch gate

**Files:**
- Modify: `tests/test_e2e_questions_2b.py`

- [ ] **Step 1: Write the e2e tests**

```python
@pytest.mark.e2e
def test_student_can_answer_with_a_fraction(page, ...):
    # Drive the real input, not a direct POST.
    ...
    page.fill("input[name='answer']", "3/2")   # element's value is "1.5"
    page.click("button[type='submit']")
    expect(page.locator("[data-question-feedback]")).to_contain_text("Correct")


@pytest.mark.e2e
def test_student_numeric_input_offers_a_full_keyboard(page, ...):
    # The only test that can catch the mobile trap — a desktop browser types "/"
    # regardless of the inputmode hint.
    ...
    assert page.get_attribute("input[name='answer']", "inputmode") == "text"


@pytest.mark.e2e
def test_reveal_shows_the_fraction_and_hides_a_zero_tolerance(page, ...):
    ...
    expect(page.locator(".question__reveal-text")).to_contain_text("1/3")
    expect(page.locator(".question__reveal-text")).not_to_contain_text("±")
```

- [ ] **Step 2: Run them**

Run: `uv run pytest tests/test_e2e_questions_2b.py -m e2e -k "fraction or keyboard or reveal" -v`

`-m e2e` is mandatory or the tests silently deselect and pytest exits 5.

- [ ] **Step 3: Screenshot the editor and the reveal in both themes**

Capture light and dark. Judge the dark screenshots **separately** — do not assume a light-mode
pass carries over.

- [ ] **Step 4: Branch gate**

Only now, run the whole suite. This is a branch gate, not a task step; expect roughly an hour, so
start the run detached and poll the PID rather than backgrounding it through the harness (a
backgrounded pytest gets reaped mid-run and orphans the test database).

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest -q --verbosity=0
uv run pytest -m e2e -q --verbosity=0
```

- [ ] **Step 5: Pre-merge collision check**

```bash
git fetch origin
git show origin/master:courses/transfer/schema.py | grep FORMAT_VERSION
ls courses/migrations/ | tail -3
gh pr list --state open
```

Confirm no other open PR also took `FORMAT_VERSION = 11` or a `0058_*` migration. Two branches
taking the same value merge **without a conflict**.

- [ ] **Step 6: Commit**

```bash
git add tests/test_e2e_questions_2b.py
git commit -m "test(e2e): drive a fraction answer through the real student input"
```

---

## Self-Review

**Spec coverage.** Every spec section maps to a task: storage/validators/canonicalisers → 1–3;
model, `clean()`, `mark()`, migration `0058` → 4; form + i18n + editor template → 5; student and
reveal templates → 6; transfer + `FORMAT_VERSION` → 7; LAL loader → 8; affected-test sweep +
author docs → 9; e2e + branch gate → 10. The `rollups._fmt_mark` third twin is explicitly left
alone per the spec and needs no task.

**Placeholder scan.** Tasks 6, 7, 8 and 10 contain `...` inside test bodies where the existing
file's fixtures must be reused. These are **not** placeholders for undecided behaviour — the
assertions are complete and exact; the elision is only the scaffolding already present in each
file. Every implementation code block is complete.

**Type consistency.** `canonical_numeric_text` / `canonical_tolerance_text` return
`str | None | TOO_LONG` everywhere they appear. `TOO_LONG` is compared by identity at every site
except `_val_short_numeric`'s `in (None, TOO_LONG)` membership test, which is safe on a `str` and
noted inline. `mark()`'s `reveal` carries `str` values, matching the template edits in Task 6.

**Two things the plan must NOT test**, both restated from the spec because inventing an assertion
for either would produce a test that cannot fail:
1. `if tol is None` versus `... or Fraction(0)` in `mark()` — behaviourally identical.
2. `|default:''` versus `|default_if_none:''` in the editor template — identical for a `CharField`.
