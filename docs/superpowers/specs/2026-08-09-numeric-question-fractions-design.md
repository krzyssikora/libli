# Numeric question: exact fractions

## Purpose

`ShortNumericQuestionElement` ("Numeric question") cannot handle fractions. Three
author-reported defects, plus one latent crash found while scoping them:

1. **A student cannot answer `3/2`.** For "Enter the gradient of the line", students type
   `3/2`, not `1.5`. Today that input is not *wrong*, it is *unparseable*, and is marked
   incorrect.
2. **An author cannot set a fraction as the correct answer.** The editor rejects `3/2`.
3. **Editing the tolerance corrupts it.** With a saved tolerance of `0.1`, the editor renders
   the stored `Decimal` as `0.10000000`. Inserting a `0` after the point yields
   `0.010000000` — **nine** decimal places — which Django's model-level `DecimalValidator`
   rejects with "Ensure that there are no more than 8 decimal places." The author sees a
   correct-looking edit refused. Trailing zeros should never have been rendered.
4. **Latent 500 (pre-existing, not caused by this change).** `parse_numeric_value` calls
   `int()` on the regex-captured numerator/denominator. Under CPython ≥ 3.11 (this repo runs
   3.13.12), `int()` on a string of more than 4300 digits raises `ValueError`. That parser
   already runs on **student-submitted** input via `blank_matches`, so a student pasting a
   5000-digit numerator into a fill-blank crashes the check endpoint today. Verified:

   ```
   >>> parse_numeric_value('1'*5000 + '/2')
   ValueError: Exceeds the limit (4300 digits) for integer string conversion
   ```

Defects 1, 2 and 3 share one root cause: `value` and `tolerance` are
`DecimalField(max_digits=20, decimal_places=8)`, and marking uses `parse_number`, a
decimals-only parser. `1/3` has no exact `Decimal` form, so a rounded `0.33333333` is stored
and the student's exact `1/3` no longer equals it. Defect 4 is unrelated in origin but is
in scope because this change makes short-numeric a fourth caller of the affected parser.

**Non-goals.** Guess-the-number keeps its `Decimal` target (`guessnumber.format_target`
already strips trailing zeros, so it has neither defect 3 nor a fraction request).
`parse_number` is not removed and the two parsers are not merged — this change moves *one
caller* off the Decimal path precisely because Decimal storage is the bug. No new authoring
option such as "require simplified form."

## Architecture / components

### Storage: canonical text, compared as exact rationals

`courses/models.py`, `ShortNumericQuestionElement` (currently line 2150):

| field | before | after |
|---|---|---|
| `value` | `DecimalField(max_digits=20, decimal_places=8)` | `CharField(max_length=64)` |
| `tolerance` | `DecimalField(max_digits=20, decimal_places=8, default=0, validators=[MinValueValidator(0)])` | `CharField(max_length=64, blank=True, default="")` |

An empty `tolerance` means zero. The stored text is **canonical**, not raw author input.

### `courses/marking.py` — two new functions

**`MAX_NUMERIC_INPUT_CHARS = 64`** — a module constant.

**`canonical_numeric_text(s)` → `str | None`.** The write-side normaliser. Returns the
canonical storage text, or `None` if `s` does not parse. It shares `_MIXED_RE`, `_FRAC_RE`
and `parse_number` with the existing parsers, so its grammar cannot drift from
`parse_numeric_value`'s.

```
"1,5"          -> "1.5"       comma to point
"1.50"         -> "1.5"       trailing zeros stripped
"0.10000000"   -> "0.1"       defect 3, at the source
"40401.00000000" -> "40401"
" 3 / 2 "      -> "3/2"       whitespace around the slash collapsed
"1  1/2"       -> "1 1/2"     mixed number keeps exactly one space
"+7"           -> "7"         redundant plus dropped
"-0.50"        -> "-0.5"
"-0"           -> "0"         negative zero normalised
"06/4"         -> "6/4"       leading zeros dropped, value NOT reduced
"1/0"          -> None
"abc"          -> None
```

Decimals go through `format(Decimal(s).normalize(), "f")`. This is the recipe
`courses/guessnumber.py:54 format_target` already uses, and the reason guess-the-number does
not have defect 3. The `"f"` format is load-bearing: `Decimal("40401").normalize()` is
`Decimal("4.0401E+4")`, whose plain `str()` the parsers would then reject.

Fractions are stored **as typed, not reduced**: an author who writes `6/4` reopens the editor
and sees `6/4`. Reduction happens only at comparison time, inside `Fraction`.

**Invariant (property-tested):** for every input where `canonical_numeric_text(s)` is not
`None`, `parse_numeric_value(canonical_numeric_text(s)) == parse_numeric_value(s)`, and
`canonical_numeric_text` is idempotent.

**Length guard in `parse_numeric_value`** — defect 4. Before matching, return `None` if the
stripped input exceeds `MAX_NUMERIC_INPUT_CHARS`. This is a *parser* guard, not a form guard,
because the crashing caller is `blank_matches` on student input. `parse_number` gets the same
guard for symmetry; its callers already bound length via `DecimalField`, so nothing there
changes behaviourally. 64 characters is far beyond any real answer and far below 4300 digits.

### Marking

```python
def mark(self, answer):
    want = parse_numeric_value(self.value)
    got = parse_numeric_value(answer)
    tol = parse_numeric_value(self.tolerance)
    if tol is None:
        tol = Fraction(0)
    is_correct = want is not None and got is not None and abs(got - want) <= tol
    return MarkResult(
        correct=is_correct,
        fraction=1.0 if is_correct else 0.0,
        reveal={"value": self.value, "tolerance": self.tolerance},
    )
```

Two deliberate details:

- `tol` uses an explicit `if tol is None`, **not** `parse_numeric_value(...) or Fraction(0)`.
  `Fraction(0)` is falsy, so the `or` form yields the right answer by accident for a stored
  `"0"` and would silently break under any later reordering.
- `want is not None` is a real guard, not defensive noise. `value` is validated on write, but
  a hand-edited row, a pre-migration import, or a future loader bug could hold junk, and the
  check endpoint must degrade to "incorrect", never 500.

`reveal` now carries the canonical **strings** rather than `Decimal`s.

Everything else about the element is untouched: absolute tolerance, `marking_mode`,
`max_attempts`, `max_marks`, `RESTORABLE_IN_LESSON`.

### Authoring form

`courses/element_forms.py`, `ShortNumericQuestionElementForm` (currently line 744). `value`
and `tolerance` are already overridden to `CharField` in `__init__` to get the `,`/`.`
leniency; that override is removed, since the model fields are now `CharField` natively.

- `clean_value` — reject raw input longer than `MAX_NUMERIC_INPUT_CHARS` with its own message
  before parsing, then `canonical_numeric_text`; `None` raises
  `Enter a number or fraction (e.g. 3.14, 3,14 or 3/2).` Returns the canonical **string**.
- `clean_tolerance` — empty input returns `""`. Otherwise the same length check and
  canonicalisation, then a negative check via `parse_numeric_value(...) < 0` raising the
  existing `Tolerance cannot be negative.` A fractional tolerance such as `1/100` is accepted.
- `1/0` fails to parse and lands on the same "enter a number or fraction" message. There is no
  `ZeroDivisionError` path, because `parse_numeric_value` returns `None` for a zero
  denominator rather than raising.

New strings go through `gettext_lazy` and both `locale/pl` and `locale/en` catalogues are
regenerated. Per the project's i18n note, `makemessages` fuzzy-prefills a wrong Polish
translation; any fuzzy marker on these entries must be cleared **and** the wrong msgstr
deleted.

### Templates

`templates/courses/manage/editor/_edit_shortnumericquestion.html`

- Both inputs: `inputmode="decimal"` → `inputmode="text"`.
- Both inputs gain `placeholder` text (`3.14, 3/2 or 1 1/2`) and the "Correct value" label
  keeps its wording.

`templates/courses/elements/shortnumericquestionelement.html:8`

- `inputmode="decimal"` → `inputmode="text"`. **This is the mobile trap.** A `decimal`
  inputmode renders a numeric keypad with no `/` key, so on a phone the entire feature would
  be untypable while every desktop test passed.
- No visible "fractions accepted" hint for students — that would leak that the answer *is* a
  fraction.

`templates/courses/elements/_reveal_shortnumeric.html`

- Drop `|floatformat:"-8"` and print the stored strings. `{% if mark_result.reveal.tolerance %}`
  keeps working because `""` is falsy. The reveal reads `Expected: 1/3`, not
  `Expected: 0.33333333`.

### Migration `0058`

One migration file. Operations stay **separate and ordered**; they must not be collapsed into
a single `AlterField`, which cannot convert `numeric` to `varchar` while preserving the
trailing-zero strip:

1. `AddField` `value_text` (`CharField(max_length=64, default="")`) and `tolerance_text`
   (`CharField(max_length=64, blank=True, default="")`).
2. `RunPython(forwards, backwards)`.
3. `RemoveField` `value`, `RemoveField` `tolerance`.
4. `RenameField` `value_text` → `value`, `tolerance_text` → `tolerance`.
5. `AlterField` `value` to drop the temporary `default=""` (the field is required).

`forwards` — for each row, `value_text = format(Decimal(value).normalize(), "f")` with the
zero special-case, and `tolerance_text = ""` when `tolerance == 0`, else the same
normalisation. This retro-fixes defect 3 on every existing element.

`backwards` — documented as **lossy**: `Fraction` → `Decimal(numerator) / Decimal(denominator)`
quantised to 8 dp, `ROUND_HALF_UP`, with `""` → `0`. A value that will not fit
`max_digits=20` after quantisation raises, rather than silently truncating.

The migration is written against **historical models** only (no import of the live model
class) and iterates with `.iterator()` so a large courseset does not load in one go.

### Transfer and loaders

- `courses/transfer/payloads.py:432 _val_short_numeric` — replace both
  `check_decimal_str(..., 20, 8)` calls with a string-type check plus `parse_numeric_value`,
  raising `TransferError` on `None`; the negative-tolerance check reads the parsed `Fraction`.
  An absent/empty tolerance is valid.
- `courses/transfer/importer.py:672 _build_numeric` — `Decimal(data["value"])` becomes
  `canonical_numeric_text(data["value"])`. Validation already happened in the payload
  validator, so a `None` here is an internal-consistency failure and raises.
- `courses/transfer/export.py:362 _ser_numeric` — the wire shape is unchanged
  (`str(el.value)`), but now naturally emits the canonical string.
- `courses/transfer/schema.py:14` — `FORMAT_VERSION` **10 → 11**. Without the bump, an older
  build reading a fraction-bearing zip fails with the misleading "value is not a valid decimal
  number"; with it, the importer's existing `version > FORMAT_VERSION` check refuses the file
  with "unsupported format version". **Operational consequence: deploy before transferring any
  course.**
- `courses/lal_loader/builders.py:400` — `Decimal(el["value"])` and
  `Decimal(el.get("tolerance", "0"))` become `canonical_numeric_text(...)`, with `"0"`
  tolerance mapping to `""`.
- `tests/factories.py` — the short-numeric factory's `value`/`tolerance` defaults become
  canonical strings.

Backward compatibility of *reading*: an existing version-10 zip carries `"value":
"1.50000000"`, which `parse_numeric_value` accepts and `canonical_numeric_text` stores as
`"1.5"`. No old export becomes unimportable.

`courses/rollups.py` and `courses/views.py` reference `ShortNumericQuestionElement` only as a
type-registry entry and never touch `value`/`tolerance`; both are unaffected.

## Data flow

**Authoring.** Author types `3/2` → `clean_value` length-checks → `canonical_numeric_text`
→ `"3/2"` → `CharField`. Reopening the editor renders `"3/2"` verbatim: exact round-trip, no
trailing zeros, nothing to corrupt.

**Answering.** Student posts `answer="1 1/2"` → `build_answer` → `mark` →
`parse_numeric_value` on both sides → `Fraction(3, 2)` vs `Fraction(3, 2)` →
`abs(0) <= Fraction(0)` → correct.

**Equality is exact rational**, so with answer `3/2` and no tolerance, all of `3/2`, `6/4`,
`15/10`, `1 1/2`, `1.5` and `1,5` are correct — the same rule `blank_matches` has applied in
fill-blank since PR #218. With answer `1/3`, `2/6` is correct and `0.333` / `0.33333333` are
not, which is the whole point.

**Reveal.** `mark_result.reveal` carries the canonical strings straight to the template.

## Error handling

| Situation | Behaviour |
|---|---|
| Student submits unparseable text (`abc`, empty, `1/0`) | `got is None` → marked incorrect. No exception. |
| Student submits a >64-char answer | Parser length guard → `None` → incorrect. No `ValueError`, no 500. This also closes the pre-existing fill-blank crash. |
| Author submits unparseable `value` | Field error `Enter a number or fraction (e.g. 3.14, 3,14 or 3/2).` |
| Author submits `value` over 64 chars | Its own field error, raised before parsing, so nothing oversized reaches the DB. |
| Author submits a negative tolerance | Existing `Tolerance cannot be negative.` |
| Stored `value` is junk (hand-edited row, legacy import) | `want is None` → marked incorrect, feedback still renders. Never a 500. |
| Import payload has a bad `value`/`tolerance` | `TransferError` from the payload validator, before any model is constructed. |
| Import zip is newer than the running build | Existing `version > FORMAT_VERSION` rejection, now correctly triggered by the 10 → 11 bump. |
| Migration `backwards` hits a value that will not fit 8 dp / 20 digits | Raises. A lossy reverse is documented; a silently wrong one is not acceptable. |

## Testing

The project rule is **falsify, don't run**: every test must be demonstrated RED before the
fix, with the mutant chosen from the *failure mode* rather than from the assertion. Tests
that cannot fail are the recurring defect in this codebase, so each item below names its
mutant.

Test DB note: the test-DB container must be started before any pytest run, and runs stay
narrowly scoped (`-k` / single files); a whole-repo sweep is a branch gate, not a task step.

**Parser unit tests** (`tests/test_questions_2b_marking.py`)

- `canonical_numeric_text` table covering every row of the canonicalisation table above.
  *Mutant:* drop the `"f"` from `format(..., "f")` — `40401` must then fail as `4.0401E+4`.
- Negative-zero → `"0"`. *Mutant:* remove the zero special-case.
- Round-trip property: canonical output re-parses to the same `Fraction`, and is idempotent.
- Length guard: a 5000-digit numerator returns `None` from `parse_numeric_value`.
  *Mutant:* remove the guard — the test must fail with `ValueError`, not with a wrong return.
- The existing `parse_number("1/2") is None` regression test stays green, pinning that the
  two parsers remain separate.

**Marking tests**

- Answer `1/3`, tolerance empty: `1/3` and `2/6` correct; `0.333`, `0.33333333` incorrect.
  This is the defect-4 test from the user's report and must fail on current `master`.
- Answer `3/2`: `3/2`, `6/4`, `1 1/2`, `1.5`, `1,5` all correct.
- Answer `1.5`, tolerance `1/100`: `1.505` correct, `1.52` incorrect — a fractional tolerance
  against a decimal answer.
- Zero tolerance from **both** sources: a stored `""` and a stored `"0"` each mark `1.0`
  correct and `1.01` incorrect against answer `1.0`. *Mutant:* make an empty tolerance default
  to something non-zero.
  **Explicitly not testable:** `if tol is None` versus `parse_numeric_value(...) or Fraction(0)`
  are behaviourally identical — `Fraction(0)` is falsy but `or` then yields `Fraction(0)`
  anyway, so no input distinguishes them. The explicit form is a readability and
  future-robustness choice, and the plan must **not** invent an assertion that pretends to
  cover it. Writing an assertion that cannot fail is the failure mode this project keeps
  hitting.
- Junk stored `value`: marks incorrect, does not raise.

**Form tests** (`tests/test_questions_2b_forms.py`)

- Saving `3/2` stores exactly `"3/2"`; saving `1,5` stores `"1.5"`.
- **Defect 3 regression:** save tolerance `0.1`, reload the edit form, assert the rendered
  field value is exactly `"0.1"`. *Mutant:* skip canonicalisation in `clean_tolerance` — the
  field renders `"0.10000000"` and the test fails. A second test posts `0.01` over a saved
  `0.1` and asserts the form is valid, which is the user's exact reported sequence and is RED
  on `master`.
- `1/0` is a field error, not a 500.
- Over-length input is a field error.

**Migration test**

- Build rows at the old schema with `value=Decimal("1.50000000")`,
  `tolerance=Decimal("0.10000000")` and `tolerance=Decimal("0")`; run `0058` forwards; assert
  `"1.5"`, `"0.1"`, `""`. *Mutant:* drop `.normalize()` — the assertions fail on the trailing
  zeros, which is precisely the defect being retro-fixed.

**Transfer round-trip tests** (`tests/test_transfer_export.py`, `tests/test_transfer_import.py`)

- Export → import an element with `value="1/3"` preserves `"1/3"`.
- A legacy payload with `"1.50000000"` imports as `"1.5"`.
- A payload with `"value": "abc"` raises `TransferError`, not `InvalidOperation`.
- `FORMAT_VERSION == 11` is asserted, and a version-12 zip is refused.

**e2e** (`tests/test_e2e_questions_2b.py`, `-m e2e`)

- A student types `3/2` into a numeric question whose answer is `1.5` and gets correct
  feedback, driving the real input rather than posting directly.
- The student input's `inputmode` is asserted to be `text`. *Mutant:* revert to `decimal` —
  this is the only test that can catch the mobile trap, since a desktop browser types `/`
  regardless of the hint.
- The reveal shows `1/3`, asserted on rendered text.

Screenshot verification of the editor and the reveal in **both light and dark**, judged
separately, per the project's UI rule.
