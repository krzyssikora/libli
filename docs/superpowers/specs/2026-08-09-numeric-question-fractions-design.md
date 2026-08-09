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

**Non-goals.** Guess-the-number keeps its `Decimal` target. `parse_number` is not removed and
the two parsers are not merged — this change moves *one caller* off the Decimal path precisely
because Decimal storage is the bug. No new authoring option such as "require simplified form".
Resource-exhaustion hardening against a multi-megabyte request body is out of scope: it is
pre-existing, applies to every text field in the app, and belongs to request-size limits rather
than to this parser.

## Architecture / components

### Storage: canonical text, compared as exact rationals

`courses/models.py`, `ShortNumericQuestionElement` (currently line 2150):

| field | before | after |
|---|---|---|
| `value` | `DecimalField(max_digits=20, decimal_places=8)` | `CharField(max_length=64, validators=[validate_numeric_text])` |
| `tolerance` | `DecimalField(max_digits=20, decimal_places=8, default=0, validators=[MinValueValidator(0)])` | `CharField(max_length=64, blank=True, default="", validators=[validate_tolerance_text])` |

**Zero tolerance has exactly one encoding: the empty string.** Every write path — form,
importer, LAL loader, migration — funnels through `canonical_tolerance_text`, which maps blank
*and* any spelling of zero to `""`. Without this, an author typing `0` would store the truthy
string `"0"` and the reveal would start printing "± 0" where today a zero tolerance is hidden.
A correct *value* of zero is unaffected and stores `"0"` — the collapse-to-empty rule is
tolerance-only.

**Model-level validators are required, not optional.** The old `MinValueValidator(0)` was the
only guard outside the form; `courses/lal_loader/builders.py` has no negative check of its own,
and a negative tolerance makes `abs(got - want) <= tol` false for *every* answer — a silently
all-incorrect question. `validate_numeric_text` rejects anything `canonical_numeric_text` cannot
parse; `validate_tolerance_text` additionally rejects negatives. Both run inside `full_clean()`,
which `courses/transfer/importer.py`'s `_clean_save` calls.

### `courses/marking.py` — new functions

**`MAX_NUMERIC_INPUT_CHARS = 64`** — a module constant. It must equal the model fields'
`max_length`; that equality is what makes an oversized transfer payload produce a clean
`TransferError` instead of a `full_clean()` `ValidationError` deeper in `_clean_save`. Pinned by
a one-line test asserting
`MAX_NUMERIC_INPUT_CHARS == ShortNumericQuestionElement._meta.get_field("value").max_length`.

**`format_decimal_plain(d)` → `str`.** Trailing-zero-stripping plain-notation formatter,
**moved here from `courses/guessnumber.py:54 format_target`**, which becomes a thin delegate.
This repo already tracks code-identical twin functions as a standing defect class, and the
precision fix below would otherwise have to be applied twice or silently diverge.

```python
def format_decimal_plain(d):
    with localcontext() as ctx:
        ctx.prec = MAX_NUMERIC_INPUT_CHARS + 16
        return format(Decimal(d).normalize(), "f")
```

Both details are load-bearing:

- **`"f"`** — `Decimal("40401").normalize()` is `Decimal("4.0401E+4")`, whose plain `str()` the
  parsers would then reject, making the element uneditable. This is `format_target`'s existing
  rationale and it carries over unchanged.
- **`localcontext`** — `normalize()` applies the *current* context, whose default precision is
  28. Verified in this repo's interpreter:
  `format(Decimal('0.1000000000000000000000000000000001').normalize(), 'f')` returns `'0.1'`,
  and a 34-digit integer normalises to a different 34-digit integer. Under the old
  `DecimalField(max_digits=20, decimal_places=8)` this was unreachable; a 64-character
  `CharField` makes 29–64-significant-digit input *legal*, so without the raised precision
  canonicalisation would silently change the author's value. `format_target`'s existing callers
  are bounded to 20 digits and are unaffected either way, but they inherit the fix.

**`canonical_numeric_text(s)` → `str | None`.** The write-side normaliser: canonical storage
text, or `None` if `s` does not parse. It shares `_MIXED_RE`, `_FRAC_RE` and `parse_number` with
the existing parsers, so its grammar cannot drift from `parse_numeric_value`'s.

The rule, in full:

1. Apply the `MAX_NUMERIC_INPUT_CHARS` guard **first** (see below) — this function calls `int()`
   itself, and is reached directly from the LAL loader on unvalidated data.
2. If the parsed value is **zero**, return `"0"` — regardless of which grammar matched or what
   sign was written.
3. Otherwise **preserve the author's structural form** (mixed stays mixed, fraction stays
   fraction, decimal stays decimal), re-emitting each integer part via `str(int(part))` and the
   decimal path via `format_decimal_plain`. A leading `+` is dropped; a leading `-` is kept and
   written once, in front.

Fractions are **not reduced**: an author who writes `6/4` reopens the editor and sees `6/4`.
Reduction happens only at comparison time, inside `Fraction`.

| input | output | rule |
|---|---|---|
| `"1,5"` | `"1.5"` | comma to point |
| `"1.50"` | `"1.5"` | trailing zeros stripped |
| `"0.10000000"` | `"0.1"` | defect 3, at the source |
| `"40401.00000000"` | `"40401"` | the `"f"` case |
| `" 3 / 2 "` | `"3/2"` | whitespace around the slash collapsed |
| `"1  1/2"` | `"1 1/2"` | mixed number keeps exactly one space |
| `"+7"` | `"7"` | redundant plus dropped |
| `"+3/2"` | `"3/2"` | plus dropped on the fraction path too |
| `"-0.50"` | `"-0.5"` | sign kept, zeros stripped |
| `"06/4"` | `"6/4"` | leading zeros dropped, value **not** reduced |
| `"-06/4"` | `"-6/4"` | sign written once, in front |
| `"1 0/2"` | `"1 0/2"` | structural form preserved; value is non-zero |
| `"0"` / `"00"` / `"-0"` / `"-0.0"` | `"0"` | zero rule |
| `"0/4"` / `"00/4"` / `"-0/4"` | `"0"` | zero rule beats form preservation |
| `"0 0/4"` | `"0"` | zero rule |
| `"1/0"` | `None` | zero denominator |
| `"abc"`, `""` | `None` | no grammar matches |
| 65+ characters | `None` | length guard |

**`canonical_tolerance_text(s)` → `str | None`.** Returns `""` for blank input **or** any
spelling of zero; the canonical text for a positive value; and `None` for unparseable **or
negative** input. This single helper is the one place the zero encoding is decided, and the form,
the importer, the LAL loader and the migration all use it.

**Invariants**, pinned by an enumerated table covering every row above plus the >28-digit case —
**not** by a property-testing library. `hypothesis` is not in `pyproject.toml` or `uv.lock`, and
this spec does not authorise adding a dependency:

- for every input where `canonical_numeric_text(s)` is not `None`,
  `parse_numeric_value(canonical_numeric_text(s)) == parse_numeric_value(s)`;
- `canonical_numeric_text` is idempotent.

**Length guard — defect 4.** `parse_numeric_value` and `canonical_numeric_text` each return
`None` when the stripped input exceeds `MAX_NUMERIC_INPUT_CHARS`, checked **before** any regex
match. This is a *parser* guard, not a form guard, because the crashing caller is `blank_matches`
on student input — so the fix also closes the live crash in fill-blank, fill-in-table and
fill-&-confirm.

**`parse_number` deliberately does NOT get this guard.** It never calls `int()` on a captured
string — it goes through `Decimal`, which has no digit limit — so it was never vulnerable to
defect 4, and a guard there would be a pure behaviour regression at two live call sites:
`courses/views.py:1162` parses a raw student guess for the guess-the-number endpoint, and
`courses/element_forms.py:314` parses the author's target out of the stem. Guarding only the two
functions that call `int()` leaves both untouched.

**Non-string input.** `parse_numeric_value` currently opens with `(s or "").strip()`, which
raises `AttributeError` — a 500 — for a `Decimal`, `int` or `float`, exactly what an un-migrated
in-process instance or an un-updated test constructs. It becomes
`s = "" if s is None else str(s)`, then strip.

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
  `Fraction(0)` is falsy, so the `or` form yields the right answer by accident and would break
  under any later reordering. See the testing section: this is explicitly *not* test-coverable.
- `want is not None` is a real guard, not defensive noise. `value` is validated on write, but a
  hand-edited row, a pre-migration import, or a future loader bug could hold junk, and the check
  endpoint must degrade to "incorrect", never 500.

`reveal` now carries the canonical **strings** rather than `Decimal`s.

Everything else about the element is untouched: absolute tolerance, `marking_mode`,
`max_attempts`, `max_marks`, `RESTORABLE_IN_LESSON`.

### Authoring form

`courses/element_forms.py`, `ShortNumericQuestionElementForm` (currently line 744). The
`__init__` override that replaces `value`/`tolerance` with bare `CharField`s is **removed** — it
existed only to get `,`/`.` leniency out of a `DecimalField`, and the model fields are now
`CharField` natively.

- `clean_value` — `canonical_numeric_text`; `None` raises
  `Enter a number or fraction (e.g. 3.14, 3,14 or 3/2).` Returns the canonical **string**.
- `clean_tolerance` — `canonical_tolerance_text`; `None` raises the existing
  `Tolerance cannot be negative.` when the input parses but is negative, and the
  "number or fraction" message when it does not parse at all. A fractional tolerance such as
  `1/100` is accepted.
- `1/0` fails to parse and lands on the "number or fraction" message. There is no
  `ZeroDivisionError` path, because `parse_numeric_value` returns `None` for a zero denominator
  rather than raising.

**No custom over-length message.** Because the fields are now ModelForm-generated from a
`CharField(max_length=64)`, Django's `MaxLengthValidator` runs inside `field.clean()`, which
completes *before* `clean_value()` is called. A custom over-length branch would be dead code and
a test asserting its message would fail. The expected behaviour is Django's built-in
"Ensure this value has at most 64 characters".

**The error string is shared and must not be blanket-replaced.** The literal
`_("Enter a number (e.g. 3.14 or 3,14).")` appears **twice** in `element_forms.py`: at line 774
(short-numeric, the one that changes) and at line 340 (`GuessNumberElementForm`, which must NOT
advertise fractions, per the non-goals). Only the short-numeric occurrence changes, and the old
msgid **stays in both catalogues** because line 340 still references it — it is not an orphan to
delete. New strings use `gettext_lazy`. Per the project's i18n note, `makemessages` fuzzy-prefills
a wrong Polish translation; any fuzzy marker on the new entries must be cleared **and** the wrong
msgstr deleted.

### Templates

`templates/courses/manage/editor/_edit_shortnumericquestion.html`

- Both inputs: `inputmode="decimal"` → `inputmode="text"`, plus a `placeholder` of
  `3.14, 3/2 or 1 1/2`.

`templates/courses/elements/shortnumericquestionelement.html:8`

- `inputmode="decimal"` → `inputmode="text"`. **This is the mobile trap.** A `decimal` inputmode
  renders a numeric keypad with no `/` key, so on a phone the entire feature would be untypable
  while every desktop test passed.
- **Accepted trade-off:** `inputmode="text"` is the default for `type="text"`, so the attribute
  is informationally redundant, and every student answering a plain *decimal* question loses the
  numeric keypad. There is no better option: `inputmode` is a property of the input, not of the
  answer, and varying it by whether the correct answer is a fraction would leak the answer. The
  attribute is nonetheless written explicitly rather than deleted, so the intent is visible at
  the call site and the e2e assertion has something to pin.
- No visible "fractions accepted" hint for students — that would leak that the answer *is* a
  fraction.

`templates/courses/elements/_reveal_shortnumeric.html`

- Drop `|floatformat:"-8"` and print the stored strings. `{% if mark_result.reveal.tolerance %}`
  is correct **only because** zero tolerance is canonically `""`; see the storage section. The
  reveal reads `Expected: 1/3`, not `Expected: 0.33333333`.

### Migration `0058`

One migration file. Operations stay **separate and ordered**; they must not be collapsed into a
single `AlterField`, which cannot convert `numeric` to `varchar` while preserving the
trailing-zero strip:

1. `AddField` `value_text` (`CharField(max_length=64, default="")`) and `tolerance_text`
   (`CharField(max_length=64, blank=True, default="")`).
2. `RunPython(forwards)` — **no `reverse_code`** (see below).
3. `RemoveField` `value`, `RemoveField` `tolerance`.
4. `RenameField` `value_text` → `value`, `tolerance_text` → `tolerance`.
5. `AlterField` `value` to drop the temporary `default=""` and attach `validate_numeric_text`;
   `AlterField` `tolerance` to attach `validate_tolerance_text`.

`forwards` — `value_text = format_decimal_plain(value)`, `tolerance_text =
canonical_tolerance_text(str(tolerance))` (so every spelling of zero becomes `""`). This
retro-fixes defect 3 on every existing element. Written against **historical models** only (no
import of the live model class), reading with `.iterator(chunk_size=500)` and writing with
`bulk_update([...], ["value_text", "tolerance_text"], batch_size=500)` so a courseset the size of
mat-pp is neither loaded at once nor updated one row per query.

**The migration is deliberately irreversible.** Omitting `reverse_code` makes Django raise
`IrreversibleError` on the way down. This is not laziness: reversing would run step 3's
`RemoveField` backwards *before* step 2, re-adding `value` as a non-null `DecimalField` with no
default, which fails outright on any populated table — so a `backwards` function would be
unreachable code masquerading as a rollback path. And the reverse is lossy by nature: `1/3` has
no `Decimal` form, which is the entire premise of this change. **Operational consequence:
rolling back this deploy means restoring a database backup, not running `migrate` backwards.**

### Transfer and loaders

- `_val_short_numeric` (`courses/transfer/payloads.py:432`) — replace both
  `check_decimal_str(..., 20, 8)` calls with a string-type check plus `canonical_numeric_text` /
  `canonical_tolerance_text`, raising `TransferError` on `None`. The `tolerance` **key must still
  be present** — `_exact_keys` (`courses/transfer/schema.py:97`) errors on any missing key, and
  loosening it would break the missing-key rejection tests — but its **value may be `""`**.
  The negative-tolerance rejection now comes from `canonical_tolerance_text` returning `None`.
- `_build_numeric` (`courses/transfer/importer.py:672`) — **both** `Decimal(...)` calls change:
  `value=canonical_numeric_text(data["value"])` and
  `tolerance=canonical_tolerance_text(data["tolerance"])`. Validation already happened in the
  payload validator, so `None` here is an internal-consistency failure and raises. `""` is a
  valid tolerance result and must not be treated as failure — this is the round-trip case, since
  export emits `""` for every zero-tolerance element.
- `_ser_numeric` (`courses/transfer/export.py:362`) — the wire shape is unchanged
  (`str(el.value)`), but now naturally emits the canonical string, including `""` for tolerance.
- `courses/transfer/schema.py:14` — `FORMAT_VERSION` **10 → 11**. Without the bump, an older
  build reading a fraction-bearing zip fails with the misleading "value is not a valid decimal
  number"; with it, the importer's existing `version > FORMAT_VERSION` check refuses the file
  with "unsupported format version". **Operational consequence: deploy before transferring any
  course.** Because two branches bumping this line to the *same* number merge without a conflict
  — a hazard this project has already hit — re-read `FORMAT_VERSION` on the merge base before
  merging and confirm no other open PR also took 11. The `FORMAT_VERSION == 11` assertion test is
  the tripwire.
- `courses/lal_loader/builders.py:400` — `Decimal(el["value"])` and
  `Decimal(el.get("tolerance", "0"))` become `canonical_numeric_text` / `canonical_tolerance_text`.
  Unlike the importer, the loader has **no upstream validator**, so a `None` must raise a
  loader-specific error naming the offending element rather than being passed into
  `objects.create(value=None)` and surfacing as a context-free `IntegrityError` mid-import. The
  old `Decimal(...)` at least raised at the parse site; the replacement must not be worse.

Backward compatibility of *reading*: an existing version-10 zip carries `"value": "1.50000000"`
and `"tolerance": "0.00000000"`, which canonicalise to `"1.5"` and `""`. No old export becomes
unimportable.

`courses/rollups.py` and `courses/views.py` reference `ShortNumericQuestionElement` only as a
type-registry entry and never touch `value`/`tolerance`; both are unaffected.

## Data flow

**Authoring.** Author types `3/2` → `clean_value` → `canonical_numeric_text` → `"3/2"` →
`CharField`. Reopening the editor renders `"3/2"` verbatim: exact round-trip, no trailing zeros,
nothing to corrupt.

**Answering.** Student posts `answer="1 1/2"` → `build_answer` → `mark` → `parse_numeric_value`
on both sides → `Fraction(3, 2)` vs `Fraction(3, 2)` → `abs(0) <= Fraction(0)` → correct.

**Equality is exact rational**, so with answer `3/2` and no tolerance, all of `3/2`, `6/4`,
`15/10`, `1 1/2`, `1.5` and `1,5` are correct — the same rule `blank_matches` has applied in
fill-blank since PR #218. With answer `1/3`, `2/6` is correct and `0.333` / `0.33333333` are not,
which is the whole point.

**Reveal.** `mark_result.reveal` carries the canonical strings straight to the template.

## Error handling

| Situation | Behaviour |
|---|---|
| Student submits unparseable text (`abc`, empty, `1/0`) | `got is None` → marked incorrect. No exception. |
| Student submits a >64-char answer | Parser length guard → `None` → incorrect. No `ValueError`, no 500. This also closes the pre-existing fill-blank crash. |
| Author submits unparseable `value` | Field error `Enter a number or fraction (e.g. 3.14, 3,14 or 3/2).` |
| Author submits `value` over 64 chars | Django's built-in `MaxLengthValidator` message, from `field.clean()` before `clean_value` runs. |
| Author submits a negative tolerance | Existing `Tolerance cannot be negative.` |
| Author submits `0` as the tolerance | Stored as `""`; the reveal shows no `±`. |
| Stored `value` is junk *text* | `want is None` → marked incorrect, feedback still renders. Never a 500. |
| Stored `value` is a non-string (`Decimal`, `int`) from an un-migrated in-process instance | Coerced via `str()` in the parser; degrades to incorrect rather than `AttributeError`. |
| A write path bypasses the form (loader, shell) with junk or a negative tolerance | Model-level `validate_numeric_text` / `validate_tolerance_text` reject inside `full_clean()`. |
| Import payload has a bad `value`/`tolerance`, or a missing `tolerance` **key** | `TransferError` from the payload validator, before any model is constructed. |
| Import payload has `"tolerance": ""` | Valid — the canonical zero encoding, and the export round-trip case. |
| Import zip is newer than the running build | Existing `version > FORMAT_VERSION` rejection, now correctly triggered by the 10 → 11 bump. |
| LAL source has an unparseable value | Loader-specific error naming the element; never `objects.create(value=None)`. |
| Someone runs `migrate` backwards past `0058` | `IrreversibleError`. Rollback is a database restore. |

## Testing

The project rule is **falsify, don't run**: every test must be demonstrated RED before being
accepted, with the mutant chosen from the *failure mode* rather than from the assertion. Tests
that cannot fail are the recurring defect in this codebase, so each item below names its mutant.

**On what "RED" means here.** Defect 3's form test is genuinely red on `master`. The fraction
tests are **not** — on `master`, `value` is a `DecimalField` that cannot hold `1/3` at all, so
there is no way to express them against the old schema. For those, the falsification is against a
**mutant of the new code** (revert `mark()` to `parse_number`, drop the `localcontext`, and so
on), and each item below names which. Claiming "red on master" for a test that cannot be
constructed on master would itself be the failure mode this rule exists to prevent.

Test-run mechanics: start the test-DB container before any pytest run, and keep runs narrowly
scoped (`-k` / single files). A whole-repo sweep is a branch gate, not a task step. e2e needs
`-m e2e` or it silently deselects.

**Parser unit tests** (`tests/test_questions_2b_marking.py`)

- `canonical_numeric_text` over **every row** of the canonicalisation table.
  *Mutant:* drop the `"f"` from `format_decimal_plain` — `40401` then fails as `4.0401E+4`.
- A >28-significant-digit input (e.g. `0.1000000000000000000000000000000001`) round-trips
  unchanged. *Mutant:* remove the `localcontext` — the value silently becomes `0.1`. This is the
  only test that catches C1.
- Zero-form rows (`-0`, `0/4`, `00/4`, `-0/4`, `0 0/4`, `-0.0`) all canonicalise to `"0"`.
  *Mutant:* remove the zero rule — `-0/4` comes back as `-0/4` or `"-0"`.
- Round-trip and idempotence over the same enumerated table.
- `canonical_tolerance_text`: `""`, `"0"`, `"0.00000000"`, `"0/5"` → `""`; `"1/100"` → `"1/100"`;
  `"-1"` → `None`. *Mutant:* have it fall through to `canonical_numeric_text` for zero — `"0"` is
  returned and I2's reveal regression reappears.
- Length guard: a 5000-digit numerator returns `None` from **both** `parse_numeric_value` and
  `canonical_numeric_text`. *Mutant:* remove either guard — the test fails with `ValueError`,
  not with a wrong return value.
- Non-string input: `parse_numeric_value(Decimal("1.5"))` returns `Fraction(3, 2)`, not
  `AttributeError`.
- `parse_number` is asserted to still accept a 100-character numeric string, pinning that it did
  **not** receive the length guard.
- The existing `parse_number("1/2") is None` regression test stays green, pinning that the two
  parsers remain separate.
- `MAX_NUMERIC_INPUT_CHARS` equals the model field's `max_length`.

**Marking tests**

- Answer `1/3`, tolerance `""`: `1/3` and `2/6` correct; `0.333`, `0.33333333` incorrect. This is
  **defects 1 and 2**. *Mutant:* revert `mark()` to `parse_number`.
- Answer `3/2`: `3/2`, `6/4`, `1 1/2`, `1.5`, `1,5` all correct.
- Answer `1.5`, tolerance `1/100`: `1.505` correct, `1.52` incorrect — a fractional tolerance
  against a decimal answer.
- Zero tolerance from both spellings: a stored `""` and a stored `"0"` each mark `1.0` correct
  and `1.01` incorrect against answer `1.0`. *Mutant:* make an empty tolerance default to
  something non-zero.
  **Explicitly not testable:** `if tol is None` versus `parse_numeric_value(...) or Fraction(0)`
  are behaviourally identical — `Fraction(0)` is falsy but `or` then yields `Fraction(0)` anyway,
  so no input distinguishes them. The explicit form is a readability and future-robustness
  choice, and the plan must **not** invent an assertion that pretends to cover it.
- Junk stored `value`: marks incorrect, does not raise.

**Form tests** (`tests/test_questions_2b_forms.py`)

- Saving `3/2` stores exactly `"3/2"`; saving `1,5` stores `"1.5"`; saving tolerance `0` stores
  `""`.
- **Defect 3 regression, red on `master`:** save tolerance `0.1`, reload the edit form, assert the
  rendered value is exactly `"0.1"`; then post `0.01` over it and assert the form is valid. This
  is the user's exact reported sequence.
- `1/0` is a field error, not a 500.
- Over-length input produces Django's built-in max-length error.
- The guess-number tolerance error text is asserted **unchanged**, guarding against a blanket
  find-replace of the shared msgid.

**Model-validator test**

- `ShortNumericQuestionElement(value="abc").full_clean()` and `(tolerance="-1").full_clean()`
  each raise `ValidationError`. *Mutant:* drop the `validators=[...]` argument — I4's silent
  all-incorrect question becomes constructible.

**Migration test**

- Build rows at the old schema with `value=Decimal("1.50000000")`,
  `tolerance=Decimal("0.10000000")` and `tolerance=Decimal("0")`; run `0058` forwards; assert
  `"1.5"`, `"0.1"`, `""`. *Mutant:* drop `format_decimal_plain` in favour of `str()` — the
  assertions fail on the trailing zeros, which is precisely the defect being retro-fixed.
- Reversing `0058` raises `IrreversibleError`.

**Transfer round-trip tests** (`tests/test_transfer_export.py`, `tests/test_transfer_import.py`)

- Export → import an element with `value="1/3"` preserves `"1/3"`.
- **Export → import a zero-tolerance element** round-trips `""` without error. *Mutant:* route
  the importer's tolerance through `canonical_numeric_text` — `""` becomes `None` and the import
  raises. This is C2 and it breaks every existing element, so it must be a named test.
- A legacy payload with `"1.50000000"` / `"0.00000000"` imports as `"1.5"` / `""`.
- A payload with `"value": "abc"` raises `TransferError`, not `InvalidOperation`.
- A payload **missing** the `tolerance` key still raises (the `_exact_keys` contract is unchanged).
- `FORMAT_VERSION == 11` is asserted, and a version-12 zip is refused.

**Existing tests that this change breaks** — per the project's affected-tests discipline these are
enumerated now, not discovered at the branch gate:

| file:line | current assertion | needed edit |
|---|---|---|
| `tests/test_questions_2b_authoring.py:81` | `q.value == Decimal("3.14") and q.tolerance == Decimal("0.01")` | compare to `"3.14"` / `"0.01"` |
| `tests/test_questions_2b_consumption.py:65` | constructs `value=Decimal("3.14"), tolerance=Decimal("0.01")` | canonical strings |
| `tests/test_quiz_answer.py:109` | constructs `value=Decimal("4"), tolerance=Decimal("0")` | `value="4", tolerance=""` |
| `tests/test_transfer_validation.py:548` | `_reject(..., "decimal")` for `value="abc"` | the message no longer contains "decimal"; update the substring deliberately to whatever `canonical_numeric_text`'s rejection emits, and state that string in the plan rather than loosening the assertion |
| `tests/test_transfer_validation.py:557` | `_reject(..., "decimal")` for `Infinity`/`NaN` | same; the *rejection* still holds (`_NUM_RE` matches none of them), only the message changes |

`tests/factories.py` needs **no** change: it re-exports `ShortNumericQuestionElement` as a name
but defines no factory for it, so there are no `value`/`tolerance` defaults there to update.

**e2e** (`tests/test_e2e_questions_2b.py`, `-m e2e`)

- A student types `3/2` into a numeric question whose answer is `1.5` and gets correct feedback,
  driving the real input rather than posting directly.
- The student input's `inputmode` is asserted to be `text`. *Mutant:* revert to `decimal` — this
  is the only test that can catch the mobile trap, since a desktop browser types `/` regardless
  of the hint.
- The reveal shows `1/3`, asserted on rendered text, and a zero-tolerance question's reveal shows
  no `±`.

Screenshot verification of the editor and the reveal in **both light and dark**, judged
separately, per the project's UI rule.
