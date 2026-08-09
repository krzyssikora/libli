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

**Two separate constants.** These bound different things and must not be welded together:

- **`MAX_STORED_NUMERIC_CHARS = 64`** — the *storage* cap for this one element. It must equal
  the model fields' `max_length`; that equality is what makes an oversized transfer payload
  produce a clean `TransferError` instead of a `full_clean()` `ValidationError` deeper in
  `_clean_save`. Pinned by a one-line test asserting
  `MAX_STORED_NUMERIC_CHARS == ShortNumericQuestionElement._meta.get_field("value").max_length`
  **and the same for `tolerance`**, since `canonical_tolerance_text` guards at the same width and
  a drifted `tolerance` column would otherwise go unnoticed. Used by `canonical_numeric_text`,
  `canonical_tolerance_text` and the transfer validator.
- **`MAX_PARSED_NUMERIC_CHARS = 256`** — the *comparison-side* cap, used only by
  `parse_numeric_value`. Its job is to stay comfortably below the 4300-digit `int()` limit
  (defect 4) while not silently changing how existing content matches.

Keeping these as one constant would be a real regression at three elements this feature does
not otherwise touch. `parse_numeric_value` is `blank_matches`'s parser, so a single 64-char cap
would flip every 65-to-4300-character numeric student answer — and every 65+ character authored
accepted line — from "matches numerically" to "does not match" in fill-blank, fill-in-table and
fill-&-confirm. (Text matching is unaffected either way: when the numeric branch declines, the
normalised-text comparison still runs.) 256 is chosen as generous enough that no plausible
authored or typed number is affected, and the fill-blank marking tests must stay green
unmodified as the evidence for that.

**Bounding the output, not just the input.** The cap on `canonical_numeric_text` must be
re-checked against the **canonical result**, because canonicalisation is not length-preserving:
`_NUM_RE` admits a bare leading separator, so `"." + "1"*63` is a legal 64-character input whose
canonical form is `"0.111…"` at **65** characters. Verified in this repo's interpreter under the
specified precision. Without the output check, that input passes `clean_value` and then dies in
`_post_clean`'s `full_clean()` with "at most 64 characters" — for a string the author never
typed — and in transfer it reaches `_clean_save`'s unwrapped `full_clean()` as an uncaught
`ValidationError`, i.e. a 500. It also breaks both stated invariants, since
`canonical_numeric_text` would not be idempotent on that class. So: guard the input, build the
canonical string, then return the sentinel `TOO_LONG` (rule 4 below) if the **result** exceeds
`MAX_STORED_NUMERIC_CHARS`.

Note this overflow only exists *because* of the raised precision above — in the default
28-digit context the same input canonicalises to 30 characters. The two fixes interact, which is
why the output check is specified here rather than assumed.

**`format_decimal_plain(d)` → `str`.** Trailing-zero-stripping plain-notation formatter,
**moved here from `courses/guessnumber.py:54 format_target`**, which becomes a thin delegate.
This repo already tracks code-identical twin functions as a standing defect class, and the
precision fix below would otherwise have to be applied twice or silently diverge.

There is a **third** twin: `_fmt_mark` (`courses/rollups.py:644`) is
`f"{Decimal(value).normalize():f}"` — semantically the same function, with the same
default-precision-28 exposure, and a docstring repeating the same exponent rationale. It is
**deliberately left alone**: marks are always a bounded `DecimalField`, so the precision issue is
unreachable there, and folding an analytics formatter into the marking module would couple two
unrelated subsystems for no behavioural gain. Naming it here so the next reader does not
rediscover it as unnoticed drift.

```python
def format_decimal_plain(d):
    """Format a Decimal as plain notation with trailing zeros stripped.

    Takes a Decimal (or anything Decimal() accepts) — NEVER raw author text:
    Decimal("1,5") raises InvalidOperation, so the comma must already be gone.
    """
    with localcontext() as ctx:
        ctx.prec = MAX_STORED_NUMERIC_CHARS + 16
        return format(Decimal(d).normalize(), "f")
```

The argument contract is load-bearing. On the decimal canonicalisation path the call is
`format_decimal_plain(parse_number(s))`, **not** `format_decimal_plain(s)` — `parse_number` is
what turns `"1,5"` into `Decimal("1.5")`, and passing the raw text instead raises
`InvalidOperation` on the very first row of the canonicalisation table. The `+ 16` is guard
headroom so the precision stays sufficient if the storage cap is ever raised; the cap alone
would already cover a 64-character input.

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

**`canonical_numeric_text(s)` → `str | None | TOO_LONG`.** The write-side normaliser: canonical storage
text, or `None` if `s` does not parse. It shares `_MIXED_RE`, `_FRAC_RE` and `parse_number` with
the existing parsers, so its grammar cannot drift from `parse_numeric_value`'s.

It must try the three grammars in the **same order** as `parse_numeric_value` — mixed, then
fraction, then decimal. Sharing the regexes is not by itself enough to prevent drift; the order
is what guarantees it, and the load-bearing `\s+` in `_MIXED_RE` (without which `11/2` reads as
one-and-a-half) exists precisely because order and greediness interact. The round-trip and
idempotence tests are only meaningful under this shared order.

The rule, in full:

0. **Coerce non-string input first**, using the identical prologue as `parse_numeric_value`
   (`None` → `""`, `Decimal` → `format(d, "f")`, else `str(s)`). This is not symmetry for its own
   sake: the LAL manifest is parsed with `json.loads` (`courses/lal_loader/guards.py:42`), so
   `{"value": 2.5, "tolerance": 0}` is perfectly ordinary manifest content that reaches
   `canonical_numeric_text` directly. Today `Decimal(2.5)` accepts it; without the prologue,
   `.strip()` on a `float` raises `AttributeError` mid-import — a context-free crash, which is
   worse than the `Decimal(...)` it replaces and fails the bar the loader bullet sets. The
   direct loader call is the load-bearing justification. `clean()` is a secondary, narrower
   exposure: `clean_fields()` **does** write `to_python` results back
   (`setattr(self, f.attname, f.clean(raw_value, self))`, Django 5.2.15 `db/models/base.py`), so
   a validating field is already a `str` by the time `clean()` runs — the raw value survives only
   on the *error* path, which `full_clean()` does not stop `clean()` from reaching.
1. Apply the `MAX_STORED_NUMERIC_CHARS` guard to the **stripped input** — this function
   calls `int()` itself, and is reached directly from the LAL loader on unvalidated data. Both
   guards measure the **stripped** string, matching Django's `forms.CharField(strip=True)` so the
   parser and the form-level `MaxLengthValidator` cannot disagree about a whitespace-padded input.
2. If the parsed value is **zero**, return `"0"` — regardless of which grammar matched or what
   sign was written.
3. Otherwise **preserve the author's structural form** (mixed stays mixed, fraction stays
   fraction, decimal stays decimal), re-emitting each integer part via `str(int(part))` and the
   decimal path via `format_decimal_plain(parse_number(s))`. A leading `+` is dropped; a leading
   `-` is kept and written once, in front.
   **The two grammars carry the sign differently.** In `_FRAC_RE` the sign lives *inside* the
   numerator group, so `str(int("-06"))` handles it for free. In `_MIXED_RE` the sign is a
   **separate** group and the whole part is unsigned, so the mixed path must re-prepend group 1
   explicitly; forgetting to yields `"1 1/2"` for `"-1 1/2"` — a silently wrong stored answer.
4. Re-check the **canonical result** against `MAX_STORED_NUMERIC_CHARS`. On overflow return the
   sentinel `TOO_LONG` rather than a plain `None`, so the form can say "too long" instead of
   telling an author who typed a perfectly well-formed number to "enter a number or fraction".
   Every caller that does not care about the distinction treats `TOO_LONG` exactly as `None`
   (a single `if result is None or result is TOO_LONG` at each site); only `clean_value` /
   `clean_tolerance` branch on it. The one extra sentinel is worth it because the misleading
   alternative describes a problem the author does not have.

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
| `"-1 1/2"` | `"-1 1/2"` | mixed sign re-prepended from `_MIXED_RE` group 1 |
| `"+1 1/2"` | `"1 1/2"` | plus dropped on the mixed path |
| `".5"` / `",5"` | `"0.5"` | bare leading separator; `format_decimal_plain` inserts the `0` |
| `"-.5"` / `"+,5"` | `"-0.5"` / `"0.5"` | same, with the sign rules |
| `"0"` / `"00"` / `"-0"` / `"-0.0"` | `"0"` | zero rule |
| `"0/4"` / `"00/4"` / `"-0/4"` | `"0"` | zero rule beats form preservation |
| `"0 0/4"` / `"-0 0/4"` | `"0"` | zero rule |
| `"1/0"` | `None` | zero denominator, fraction path |
| `"1 1/0"` | `None` | zero denominator, **mixed** path — `parse_numeric_value` has a *second, separate* guard for this; copying only the `_FRAC_RE` one yields `ZeroDivisionError` |
| `"abc"`, `""` | `None` | no grammar matches |
| 65+ input characters | `None` | input length guard |
| `"-0 1/2"` | `"-0 1/2"` | non-zero mixed with a zero whole part; form preserved |
| `"." + "1"*63`, `"," + "1"*63`, `"-." + "1"*62` (all 64 chars) | `TOO_LONG` | canonical result is 65 chars — **output** length guard. All three members of the class, not just the first |

**`canonical_tolerance_text(s)` → `str | None | TOO_LONG`.** Returns `""` for blank input **or**
any spelling of zero; the canonical text for a positive value; `TOO_LONG` propagated from
`canonical_numeric_text` for the length case; and `None` for unparseable **or negative** input.
This single helper is the one place the zero encoding is decided, and the form, the importer and
the LAL loader all use it. (The migration uses a frozen, `Decimal`-native variant — see below.)

**The `TOO_LONG` sentinel.** `TOO_LONG = object()`, module-level in `courses/marking.py`,
compared by identity. It exists so an author who typed a well-formed but over-long number gets a
length message instead of "enter a number or fraction". It is **never stored and never
rendered** — a sentinel that reaches a `CharField` is stringified by `to_python` into
`<object object at 0x…>`, so every call site must handle it. Because `TOO_LONG is not None` is
true, a `if x is not None` guard is **not** sufficient anywhere. Three sites *branch* on the
distinction — `clean_value`, `clean_tolerance` and `_val_short_numeric` — and the rest simply
treat it as a rejection (`if result is None or result is TOO_LONG`):

| call site | handling |
|---|---|
| `clean_value` / `clean_tolerance` | the only sites that branch: `TOO_LONG` → the length message, checked **first** |
| `validate_numeric_text` / `validate_tolerance_text` | `None` **or** `TOO_LONG` → `ValidationError`; the length case reuses msgid 5/6 rather than adding a seventh |
| `ShortNumericQuestionElement.clean()` | rewrite only when the result is neither `None` nor `TOO_LONG` |
| `_val_short_numeric` | **branches**, in the fixed order given in the transfer section: `TOO_LONG` → parse-failure message; then the guarded negative re-derivation; then the parse-failure message. Collapsing `TOO_LONG` into the `None` path would misreport an over-long *negative* tolerance (which parses fine at the 256-char comparison cap) as "must not be negative" |
| `_build_numeric` | `None` **or** `TOO_LONG` → `TransferError` |
| LAL loader | `None` **or** `TOO_LONG` → `LoaderError` |

**`validate_numeric_text(value)` and `validate_tolerance_text(value)`** — Django field
validators, and they live **in `courses/marking.py`** beside the canonicalisers. Naming the
module is not a style note: migration `0058`'s `AlterField` serialises each validator as a dotted
import path, so `courses.marking.validate_numeric_text` becomes a permanent interface that every
future `migrate` run resolves. These two functions must not later be moved or renamed without a
follow-up migration.

- `validate_numeric_text` raises `ValidationError` when `canonical_numeric_text` returns `None`
  **or `TOO_LONG`**.
- `validate_tolerance_text` **accepts `""`** (returns `None`) and raises when
  `canonical_tolerance_text` returns `None` **or `TOO_LONG`**, i.e. for unparseable, negative, or
  over-long input. In practice `full_clean()` never passes `""` to it at all — Django's
  `run_validators` skips values in `empty_values` — but a direct unit test will, so the behaviour
  is specified rather than incidental.

**Both must test for the sentinel, or the model-level gate has a hole exactly where it matters.**
A 64-character `"." + 63 digits` value passes `MaxLengthValidator`; if the validator checks only
for `None`, it also passes validation; and `clean()`'s guard then correctly declines to rewrite —
so non-canonical text is saved. The element is afterwards **uneditable**, because reopening the
editor and saving routes the stored value back through `clean_value`, which reports "too long".
That is precisely the silent-violation scenario the validators were added to close.

**Canonicality is enforced at the model, not merely at each caller.** The validators check
*parseability*, so `ShortNumericQuestionElement(value="1.50000000", tolerance="0").full_clean()`
would otherwise pass and store non-canonical text — defect 3 reconstituted, plus a truthy `"0"`
tolerance that makes the reveal print "± 0". A list of write paths that happen to be correct
today is not an invariant; the next management command or data fix silently violates it. So
`ShortNumericQuestionElement.clean()` is overridden to rewrite `self.value` and `self.tolerance`
through the canonicalisers, leaving the validators as the parse-failure gate. `full_clean()`
calls `clean()`, so every path that validates is covered. `objects.create()` does **not** call
`full_clean()`, which is exactly why the LAL loader still canonicalises explicitly.

**`clean()` must rewrite only on a non-`None` result**, and it calls `super().clean()` first:

```python
def clean(self):
    super().clean()
    c = canonical_numeric_text(self.value)
    if c is not None and c is not TOO_LONG:
        self.value = c
    t = canonical_tolerance_text(self.tolerance)
    if t is not None and t is not TOO_LONG:
        self.tolerance = t
```

The guards are load-bearing, not defensive style, and they must test **both** rejection values.
Django's `full_clean()` runs `clean()` **even when `clean_fields()` has already raised** — its
source comments this explicitly — so on `value="abc"` the validator reports the error *and*
`clean()` still executes. An unguarded assignment would leave the instance holding `None` in a
non-null `CharField`; a `None`-only guard would leave it holding the `TOO_LONG` object, which
`to_python` stringifies into `<object object at 0x…>` and writes to the row. Both are the
context-free-corruption hazard this spec goes out of its way to prevent in the LAL loader, and
both are reachable on ordinary input. `super().clean()` is called because
`ShortNumericQuestionElement` sits under a base shared by 14 element types; no ancestor defines
`clean()` today, so omitting it is harmless now and silently wrong the moment one does.

**Invariants**, holding wherever `canonical_numeric_text(s)` is **neither `None` nor
`TOO_LONG`** — the enumerated invariant table skips those rows, because `TOO_LONG is not None`
and feeding the sentinel back in stringifies it to `<object object at 0x…>`, which matches no
grammar — so the round-trip comparison sees `None` against a real `Fraction`, and the idempotence
check sees `None` against the sentinel. Both produce a red test that is not a real defect. Pinned
by an enumerated table covering every other row above plus the >28-digit case —
**not** by a property-testing library. `hypothesis` is not in `pyproject.toml` or `uv.lock`, and
this spec does not authorise adding a dependency:

- for every input where `canonical_numeric_text(s)` is neither `None` nor `TOO_LONG`,
  `parse_numeric_value(canonical_numeric_text(s)) == parse_numeric_value(s)`;
- `canonical_numeric_text` is idempotent.

**Length guard — defect 4.** `parse_numeric_value` returns `None` when the stripped input
exceeds `MAX_PARSED_NUMERIC_CHARS`; `canonical_numeric_text` uses `MAX_STORED_NUMERIC_CHARS`.
Both check **before** any regex match. This is a *parser* guard, not a form guard, because the
crashing caller is `blank_matches` on student input — so the fix also closes the live crash in
fill-blank, fill-in-table and fill-&-confirm.

**`parse_number` deliberately does NOT get this guard.** It never calls `int()` on a captured
string — it goes through `Decimal`, which has no digit limit — so it was never vulnerable to
defect 4, and a guard there would be a pure behaviour regression at **three** live call sites:
`courses/views.py:1162` parses a raw student guess for the guess-the-number endpoint,
`courses/element_forms.py:314` parses the author's target out of the stem, and
`courses/element_forms.py:338` parses the author's guess-number tolerance. (A fourth,
`element_forms.py:772`, is the short-numeric one this change removes.) Guarding only the two
functions that call `int()` leaves all three untouched.

**Non-string input.** `parse_numeric_value` currently opens with `(s or "").strip()`, which
raises `AttributeError` — a 500 — for a `Decimal`, `int` or `float`, exactly what an un-migrated
in-process instance or an un-updated test constructs. The coercion is:

```python
if s is None:
    s = ""
elif isinstance(s, Decimal):
    s = format(s, "f")
elif isinstance(s, (int, float)) and not isinstance(s, bool):
    s = format(Decimal(str(s)), "f")
else:
    s = str(s)
```

**A bare `str()` is wrong for every numeric type, not just `Decimal`.** `str(Decimal("0.00000000"))`
is `'0E-8'` and `str(Decimal("0.00000001"))` is `'1E-8'`; Python switches floats to exponent form
below 1e-4 and above 1e16, so `str(0.00001)` is `'1e-05'` and `str(1e16)` is `'1e+16'`. `_NUM_RE`
has no exponent branch, so all of these canonicalise to `None`. Since the old column is
`numeric(20,8)`, *every* `Decimal` read back from it below 1e-6 — including every zero —
stringifies that way; and a LAL manifest carrying `"tolerance": 0.00001` is ordinary JSON that
`Decimal(0.00001)` accepts on `master` today. Routing floats through the bare `str()` branch
would abort that import with `LoaderError`. Verified in this repo's interpreter.

Three details in the branch order:

- **`Decimal(str(f))`, never `Decimal(f)`,** for floats. `Decimal(0.1)` is
  `0.1000000000000000055511151231257827021181583404541015625` — 55 digits of binary noise, which
  would blow the storage cap and change the stored value. `Decimal(str(0.1))` is `Decimal("0.1")`.
- **`bool` is excluded explicitly** because `isinstance(True, int)` is true, and `Decimal("True")`
  raises `InvalidOperation`. A JSON `true` in a manifest must fall to the `str()` branch, match no
  grammar, and return `None` so the loader raises `LoaderError` — not crash.
- `NaN`/`Infinity` (which `json.loads` does accept) format as `'NaN'`/`'Infinity'`, match no
  grammar, and return `None`. Correct by construction.

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
  `Enter a number or fraction (e.g. 3.14, 3,14 or 3/2).`, `TOO_LONG` raises
  `That number is too long (at most 64 characters once normalised).` Returns the canonical
  **string**.
- `clean_tolerance` — `canonical_tolerance_text`, with the same `TOO_LONG` branch. A fractional
  tolerance such as `1/100` is accepted.

  **Recovering *why* the tolerance was rejected.** `canonical_tolerance_text` collapses
  "unparseable" and "negative" into one `None`, so the form cannot tell them apart from the
  return value alone and must re-derive it:

  ```python
  p = parse_numeric_value(raw)
  if p is not None and p < 0:
      raise ValidationError(_("Tolerance cannot be negative."))
  raise ValidationError(_("Enter a number or fraction (e.g. 3.14, 3,14 or 3/2)."))
  ```

  **The `p is not None` guard is not optional.** The re-derivation also runs for *unparseable*
  input, where `parse_numeric_value` likewise returns `None` — and `None < 0` raises `TypeError`.
  Without the guard, typing `abc` or `1/0` into the tolerance field is a **500 in the editor**,
  and the same payload is a 500 in the import view, since `TransferError` is the only exception
  it catches. Precedence is fixed: `TOO_LONG` is checked **before** this block, so an over-length
  negative reports the length problem.
- `1/0` fails to parse and lands on the "number or fraction" message. There is no
  `ZeroDivisionError` path, because `parse_numeric_value` returns `None` for a zero denominator
  rather than raising.

**No custom over-length message.** Because the fields are now ModelForm-generated from a
`CharField(max_length=64)`, Django's `MaxLengthValidator` runs inside `field.clean()`, which
completes *before* `clean_value()` is called. A custom over-length branch would be dead code and
a test asserting its message would fail. The expected behaviour is Django's built-in
"Ensure this value has at most 64 characters".

`_num` — the private helper both `clean_*` methods currently delegate to
(`courses/element_forms.py:768`), and the home of the shared msgid at line 774 — is **deleted**
along with the `__init__` override; nothing else calls it. One consequence to expect: the PL
catalogue entry's `#:` reference comment narrows from `element_forms.py:340 element_forms.py:774`
to `:340` only, so that line changing in the diff is correct, not accidental.

**The error string is shared and must not be blanket-replaced.** The literal
`_("Enter a number (e.g. 3.14 or 3,14).")` appears **twice** in `element_forms.py`: at line 774
(short-numeric, the one that changes) and at line 340 (`GuessNumberElementForm`, which must NOT
advertise fractions, per the non-goals). Only the short-numeric occurrence changes, and the old
msgid **stays in both catalogues** because line 340 still references it — it is not an orphan to
delete. **i18n is a three-step job here, and stopping after two regresses the Polish UI.**
The PL catalogue entry for `"Enter a number (e.g. 3.14 or 3,14)."` currently carries a real
translation of the old string
(`"Wpisz liczbę (np. 3.14 lub 3,14)."`). Introducing a *new* msgid, clearing the fuzzy marker and
deleting the wrong prefilled msgstr leaves the new entry **empty**, so a Polish author who
mistypes now sees English where today they see Polish. So: (1) clear the fuzzy marker, (2) delete
the wrong prefilled msgstr, (3) **hand-write** a Polish msgstr for each new string — for the main
one, something like `"Wpisz liczbę lub ułamek (np. 3,14 lub 3/2)."`. New strings use
`gettext_lazy`. The new msgids are added to the parametrised list in
`tests/test_i18n_questions_2b.py::test_pl_translation_present`, so an empty translation fails the
suite rather than shipping.

**Step (1) covers both catalogues.** `tests/test_i18n_po_health.py::test_no_fuzzy_entries`
iterates `CATALOGS = {"pl", "en"}`, so a fuzzy marker `msgmerge` leaves on the **en** entry also
fails the gate — while `test_pl_has_no_untranslated_msgid` is deliberately PL-only, so the empty
`en` msgstr is correct and must be left alone.

**The complete list of new msgids** — `test_i18n_po_health.py::test_pl_has_no_untranslated_msgid`
scans the whole PL catalogue, so every one of these fails the suite until hand-translated:

1. the value/tolerance parse error (`Enter a number or fraction (e.g. 3.14, 3,14 or 3/2).`);
2. the `TOO_LONG` form message (`That number is too long (at most 64 characters once
   normalised).`);
3. the editor placeholder (`3.14, 3/2 or 1 1/2`);
4. the transfer validator's `%(what)s is not a valid number or fraction.`;
5. `validate_numeric_text`'s message — `Enter a number or fraction.`;
6. `validate_tolerance_text`'s message — `Enter a non-negative number or fraction.`

Items 5 and 6 are the model validators' `ValidationError` text, which no earlier section
specified; they are deliberately terser than the form's, since they surface to whoever bypassed
the form rather than to an author mid-edit.

### Templates

`templates/courses/manage/editor/_edit_shortnumericquestion.html`

- Both inputs: `inputmode="decimal"` → `inputmode="text"`, plus
  `placeholder="{% trans '3.14, 3/2 or 1 1/2' %}"` and `maxlength="64"`. The placeholder **must**
  be wrapped in `{% trans %}` — every other placeholder in `templates/courses/manage/editor/`
  is, and the decimal separator is locale-sensitive (a Polish author expects `3,14`). The
  template hand-writes its `<input>` rather than rendering the widget, so without `maxlength` the
  new storage cap would surface only after a server round-trip. The model validator remains the
  real gate.
- **`|default:''` → `|default_if_none:''` on both inputs — a no-op tidy, explicitly not a bug fix
  and not independently testable.** An earlier draft of this spec claimed `"0"` would render
  blank; that is **wrong**. `default` substitutes for *falsy* values, and the string `"0"` is
  truthy, so both filters return `"0"` identically once the field is a `CharField`. (The hazard
  was real only for the old `Decimal("0E-8")`, which *is* falsy — so `default` was correct here
  only by accident.) The swap is made because the line is already being edited and
  `default_if_none` is the filter that actually expresses the intent; it changes no rendered
  output today, so **no test can distinguish it** and the plan must not invent one. A zero
  round-trip test is still worth writing, but it belongs to the canonicalisation rule, not to
  this filter.

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
- **Accepted locale change:** Django localises `Decimal` template variables, so under `pl` the
  reveal currently renders `3,14000000` and the editor `3,14000000`. Printing a plain string
  means both now render `3.14` — Polish users lose the decimal comma along with the trailing
  zeros. This is accepted rather than fixed: canonical storage is `.`-only by construction, a
  fraction has no locale form at all, and re-localising only the decimal grammar would make the
  editor display something the author cannot round-trip. Pinned by an assertion under
  `translation.override("pl")` so the behaviour is deliberate rather than incidental.

### Migration `0058`

One migration file. Operations stay **separate and ordered**; they must not be collapsed into a
single `AlterField`, which cannot convert `numeric` to `varchar` while preserving the
trailing-zero strip:

1. `AddField` `value_text` (`CharField(max_length=64, default="")`) and `tolerance_text`
   (`CharField(max_length=64, blank=True, default="")`).
2. `RunPython(forwards, migrations.RunPython.noop)` — the reverse is a deliberate no-op, not an
   omission (see below).
3. `RemoveField` `value`, `RemoveField` `tolerance`.
4. `RenameField` `value_text` → `value`, `tolerance_text` → `tolerance`.
5. `AlterField` `value` to drop the temporary `default=""` and attach `validate_numeric_text`;
   `AlterField` `tolerance` to attach `validate_tolerance_text`.

`forwards` operates on the `Decimal`s **directly**, never routing them through a text
canonicaliser:

```python
value_text = format_decimal_plain(value)          # Decimal in, plain text out
if tolerance == 0:
    tolerance_text = ""
elif tolerance < 0:
    # Unreachable: the counting pass already aborted. Belt-and-braces, matching
    # the write-site backstop below.
    raise RuntimeError(f"negative tolerance survived the counting pass: pk={pk}")
else:
    tolerance_text = format_decimal_plain(tolerance)
```

**`str(tolerance)` would fail on the majority of rows.** The column is `numeric(20,8)`, so a
zero tolerance reads back as `Decimal('0.00000000')` whose `str()` is `'0E-8'` — E-notation,
which `_NUM_RE` rejects. Routing that through `canonical_tolerance_text` returns `None` for
every zero tolerance and every value below 1e-6, `bulk_update` writes NULL into a non-null
column, and the **irreversible** production migration dies with `IntegrityError` partway
through. `format_decimal_plain` takes a `Decimal` and emits `'0'`, exactly as
`guessnumber.format_target` already does. Verified in this repo's interpreter.

As a backstop, the write site asserts `value_text is not None and tolerance_text is not None`
and raises `RuntimeError` if either is — so *any* future `None`, from any cause, aborts before a
NULL reaches the database rather than after. This retro-fixes defect 3 on every existing element. Written against **historical models** only (no
import of the live model class), and **accumulate-and-flush**: pull from
`.iterator(chunk_size=500)` into a list, `bulk_update` once the list reaches 500, clear it,
repeat, then flush the remainder. A single terminal `bulk_update` over the whole iterator would
defeat the point — `batch_size` bounds rows per SQL statement, not Python objects held, so every
row would be in memory anyway.

**Frozen helper copies.** The migration must **not** import from `courses.marking`; it inlines
its own copies. The historical-models rule exists so a migration keeps doing what it did the day
it shipped, and importing live helpers reintroduces exactly that hazard by the back door: a
later change to the zero rule, the precision, or the storage cap would retroactively alter what
`0058` does on a fresh deploy, and the migration test would stop describing the migration that
ships. It also couples the migration to `courses.marking` remaining importable at that path
forever.

This is affordable **only because** the migration is `Decimal`-native. Frozen-copying
`canonical_tolerance_text` would drag in `canonical_numeric_text`, `parse_number`,
`parse_numeric_value`, all three regexes, the storage cap and the `TOO_LONG` sentinel — a page of
code, at which point an implementer would reasonably give up and import after all. The three-line
`Decimal` branch above plus `format_decimal_plain` needs no regexes and no sentinel. The two
concerns reinforce each other; neither is optional.

The frozen `format_decimal_plain` **hard-codes `ctx.prec = 80`** rather than referencing
`MAX_STORED_NUMERIC_CHARS`, which it is forbidden to import. The old column is `numeric(20,8)`,
so 80 is far more than sufficient for anything the migration can read.

**Negative legacy tolerances must be handled explicitly.** `canonical_tolerance_text` returns
`None` for a negative value, and this spec establishes that negative tolerances are constructible
today — `courses/lal_loader/builders.py` has no negative check and `objects.create()` bypasses
`MinValueValidator`. Assigning that `None` into `bulk_update` would write NULL into a `NOT NULL`
column and raise `IntegrityError` **partway through a production data migration**, with no
`migrate` path back out since this migration is irreversible. So `forwards` runs a **counting
pass first**: if any row has a negative tolerance, raise `RuntimeError` before any write, with a
message listing the offending element ids, so the operator repairs the data deliberately rather
than discovering it mid-write. (`RuntimeError`, not `CommandError`: the function must fail the
same way whether invoked by `manage.py migrate` or by the migration test, and it is not a
management command.) A pre-migration audit query is included in the PR description. A migration
test seeds `tolerance=Decimal("-0.5")` and asserts `pytest.raises(RuntimeError)`.

**The reverse is a documented no-op: `reverse_code=migrations.RunPython.noop`.**

The obvious choice — omitting `reverse_code` so Django raises `IrreversibleError` — is **wrong**,
and for a reason that only surfaces when the tests are written. `Migration.unapply()` checks
`operation.reversible` for *every* operation and raises **before running any of them**
(`django/db/migrations/migration.py:153`). pytest-django builds the test database at the leaf,
so any test of the data conversion must first unapply `0058` to create old-schema rows. A truly
irreversible migration therefore makes the conversion **untestable through the executor** — and
the conversion is the part that would take down production, since routing a scale-8 `Decimal`
through `str()` yields `'0E-8'` and NULLs every zero-tolerance row.

Testability wins, and almost nothing is given up:

- **The data is never reconstructed.** `noop` means reversing does not invent `Decimal`s from
  text. `1/3` has no `Decimal` form, so guessing would be worse than refusing.
- **A production rollback still fails, loudly.** Reversing runs step 3's `RemoveField` backwards,
  re-adding `value` as a non-null `DecimalField` with no default — which errors at the database
  layer on any populated table. The protection is a `NOT NULL` violation instead of
  `IrreversibleError`; the operator is stopped either way.
- **In tests it succeeds**, because `transaction=True` leaves the table empty, and adding a
  non-null column to an empty table is fine. That is exactly the window the conversion tests need.

**Operational consequence is unchanged: rolling back this deploy means restoring a database
backup, not running `migrate` backwards.** The migration's module docstring must say so, since
the `noop` alone no longer signals it.

### Transfer and loaders

- `_val_short_numeric` (`courses/transfer/payloads.py:432`) — replace both
  `check_decimal_str(..., 20, 8)` calls with a string-type check plus `canonical_numeric_text` /
  `canonical_tolerance_text`, raising `TransferError` on `None` **or `TOO_LONG`**. The
  `tolerance` **key must still be present** — `_exact_keys` (`courses/transfer/schema.py:97`) errors on any missing key, and
  loosening it would break the missing-key rejection tests — but its **value may be `""`**.
  **The explicit negative check stays.** Folding it into the generic parse failure would replace
  `"Element '<id>': tolerance must not be negative."` — which names the element and says exactly
  what is wrong — with an element-less "not a valid number or fraction" for a payload whose
  tolerance is a perfectly good number with the wrong sign. On a whole-course import that is a
  real diagnostic regression. So `_val_short_numeric` keeps a negative branch that preserves the
  existing message; only the *parse* failure path changes. The msgid at
  `courses/transfer/payloads.py:438` therefore stays in use, and it is in any case still
  referenced by `_val_guess_number` at line 356.

  **The branch needs a mechanism, because the value it used to read is gone.** Today the check is
  `tolerance = check_decimal_str(...); if tolerance < 0`. With `check_decimal_str` removed there
  is no `Decimal` to compare, and `canonical_tolerance_text` collapses negative into `None`. So
  `_val_short_numeric` re-derives it, in this fixed order — the same three-way shape as
  `clean_tolerance`:
  1. `TOO_LONG` → the parse-failure message;
  2. `None`, **and** `p = parse_numeric_value(data["tolerance"])` is `not None` **and** `p < 0`
     → the existing `"Element '%(el)s': tolerance must not be negative."`;
  3. `None` otherwise → the parse-failure message.

  The `p is not None` guard carries the same weight here as in `clean_tolerance`: unparseable
  input reaches this branch too, and `None < 0` would turn `"tolerance": "abc"` into a 500 in
  the import view instead of a rejected upload.

  **The exact messages, since two tests pin their substrings.** `check_decimal_str` emits three
  today; the replacement emits two:
  - non-string input keeps the existing `"%(what)s must be a decimal string."`, unchanged.
    **This branch will have no test coverage unless one is added.** The wrong-type half of
    `test_malformed_decimal_and_wrong_type_reject` is `_reject(el_of("text", {"body": 42}), "text")`
    — a *text* element, matching `"text"`, nothing to do with short-numeric. The only
    `"decimal"`-matching assertion in that test is its malformed half, which the affected-tests
    table changes. So add a payload test for `"value": 42` asserting the
    `"must be a decimal string"` substring. The wording is **knowingly stale** — the field now
    accepts fractions too — and is retained only to keep the msgid shared with `check_decimal_str`
    and `_val_guess_number`; it is not an oversight to tidy later;
  - anything `canonical_*` rejects (unparseable, zero denominator, over-length, negative
    tolerance) emits a single new `"%(what)s is not a valid number or fraction."`.

  The "has too many digits" message disappears, since length is now bounded by
  `MAX_STORED_NUMERIC_CHARS` rather than by digit counts. `Infinity`/`NaN` still reject — no
  grammar matches them — via the new message.
- `_build_numeric` (`courses/transfer/importer.py:672`) — **both** `Decimal(...)` calls change:
  `value=canonical_numeric_text(data["value"])` and
  `tolerance=canonical_tolerance_text(data["tolerance"])`. Validation already happened in the
  payload validator, so `None` **or `TOO_LONG`** here is an internal-consistency failure — and it
  raises **`TransferError`**, not a bare `ValueError`. `_clean_save` (`courses/transfer/importer.py:482`)
  does not wrap `full_clean()`, and the import view catches `TransferError`, so any other
  exception type here turns an internally-inconsistent payload into a 500 rather than a rejected
  upload. `""` is a valid tolerance result and must **not** be treated as failure — this is the
  round-trip case, since export emits `""` for every zero-tolerance element.
- `_ser_numeric` (`courses/transfer/export.py:362`) — the wire shape is unchanged
  (`str(el.value)`), but now naturally emits the canonical string, including `""` for tolerance.
- `courses/transfer/schema.py:14` — `FORMAT_VERSION` **10 → 11**. Without the bump, an older
  build reading a fraction-bearing zip fails with the misleading "value is not a valid decimal
  number"; with it, the importer's existing `version > FORMAT_VERSION` check refuses the file
  with "unsupported format version". **Operational consequence: deploy before transferring any
  course.** Because two branches bumping this line to the *same* number merge without a conflict
  — a hazard this project has already hit — re-read `FORMAT_VERSION` on the merge base before
  merging and confirm no other open PR also took 11. The `FORMAT_VERSION == 11` assertion test is
  the tripwire. **The same pre-merge check covers the migration number:** the base's latest is
  `0057_contentnode_published`, several PRs are open, and two branches both adding `0058_*`
  produce "Conflicting migrations detected".
- `courses/lal_loader/builders.py:400` — `Decimal(el["value"])` and
  `Decimal(el.get("tolerance", "0"))` become `canonical_numeric_text` / `canonical_tolerance_text`.
  Unlike the importer, the loader has **no upstream validator**, so a `None` or `TOO_LONG` must
  raise **`LoaderError`** (`courses/lal_loader/builders.py:41`, already used at lines 100, 137, 380 and
  417) with a message in the house style — `f"... in unit {unit.pk}"` — rather than being passed
  into `objects.create(value=None)` and surfacing as a context-free `IntegrityError` mid-import.
  The old `Decimal(...)` at least raised at the parse site; the replacement must not be worse.

Backward compatibility of *reading*: an existing version-10 zip carries `"value": "1.50000000"`
and `"tolerance": "0.00000000"`, which canonicalise to `"1.5"` and `""`. No old export becomes
unimportable.

`courses/rollups.py` and `courses/views.py` reference `ShortNumericQuestionElement` only as a
type-registry entry and never touch `value`/`tolerance`; both are unaffected.

`courses/models.py:25`'s `from courses.marking import parse_number` becomes **dead** once
`mark()` stops calling it — line 2167 is its only use in the file — so ruff's F401 fails the
branch gate unless it is replaced by the new imports (`parse_numeric_value`,
`canonical_numeric_text`, `canonical_tolerance_text`, `validate_numeric_text`,
`validate_tolerance_text`).

### Author documentation

`docs/help/course-admin/quiz-editors.md:60-64` and its Polish twin `quiz-editors.pl.md:66-72`
document the Short numeric editor as taking "a numeric answer" with "tolerance 0 means an exact
match". Both statements become wrong: the field now accepts fractions and mixed numbers, and an
exact match is expressed by leaving tolerance **blank**, not by typing `0`. This repo treats the
role manuals as a maintained deliverable, so both files are updated and kept structurally
parallel.

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

**Duplicating an element** is a fourth path, and the one authors hit most.
`duplicate_element` (`courses/builder.py:791`) calls `build_element_export` and feeds the result
straight into `graft_elements` in the same process, so copying a short-numeric element runs
export → `_val_short_numeric` → `_build_numeric` end to end. It is the cheapest place to catch a
regression in the `""`-tolerance validator contract, and it gets a test: duplicating a
zero-tolerance fraction element yields a copy holding `"3/2"` and `""`.

## Error handling

| Situation | Behaviour |
|---|---|
| Student submits unparseable text (`abc`, empty, `1/0`) | `got is None` → marked incorrect. No exception. |
| Student submits a >256-char answer | `MAX_PARSED_NUMERIC_CHARS` guard → `None` → incorrect. No `ValueError`, no 500. This also closes the pre-existing fill-blank crash. |
| Author enters a 64-char value whose canonical form is 65 chars (`.` + 63 digits) | Output-length re-check → `TOO_LONG` → `That number is too long (at most 64 characters once normalised).` |
| The same 64-char value arrives in a transfer payload | `_val_short_numeric` treats `TOO_LONG` as a rejection → `TransferError`, never a sentinel reaching the column. |
| Author submits an **unparseable** tolerance (`abc`, `1/0`) | The number-or-fraction field error. The negative-branch re-derivation is guarded (`p is not None and p < 0`), so this never evaluates `None < 0`. |
| Author submits unparseable `value` | Field error `Enter a number or fraction (e.g. 3.14, 3,14 or 3/2).` |
| Author submits `value` over 64 chars | Django's built-in `MaxLengthValidator` message, from `field.clean()` before `clean_value` runs. |
| Author submits a negative tolerance | Existing `Tolerance cannot be negative.` |
| Author submits `0` as the tolerance | Stored as `""`; the reveal shows no `±`. |
| Stored `value` is junk *text* | `want is None` → marked incorrect, feedback still renders. Never a 500. |
| Stored `value` is a non-string (`Decimal`, `int`) from an un-migrated in-process instance | Coerced via the `Decimal`-aware prologue (`format(d, "f")`, never a bare `str()`) and marks **correctly**. A bare `str()` would yield `'0E-8'` for a scale-8 zero and silently mismatch. |
| A write path bypasses the form (loader, shell) with junk or a negative tolerance | Model-level `validate_numeric_text` / `validate_tolerance_text` reject inside `full_clean()`. |
| Import payload has a bad `value`/`tolerance`, or a missing `tolerance` **key** | `TransferError` from the payload validator, before any model is constructed. |
| Import payload has `"tolerance": ""` | Valid — the canonical zero encoding, and the export round-trip case. |
| Import zip is newer than the running build | Existing `version > FORMAT_VERSION` rejection, now correctly triggered by the 10 → 11 bump. |
| LAL source has an unparseable value | `LoaderError` naming the element and unit; never `objects.create(value=None)`. |
| A row somehow holds a non-canonical `"0"` tolerance | The reveal would print "± 0". Unreachable through any path that calls `full_clean()`, because the model's `clean()` rewrites it to `""`; reachable only via a raw `objects.create`/`update`, which is why `clean()` exists rather than a per-caller convention. |
| Migration `0058` meets a pre-existing **negative** tolerance | Counting pass aborts before any write, naming the offending element ids. Never a mid-migration `IntegrityError`. |
| Someone runs `migrate` backwards past `0058` **with data present** | The reverse re-adds a non-null `DecimalField` with no default and the database rejects it. No `Decimal`s are invented from text (the data reverse is a `noop`). Rollback is a database restore. |

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
  only test that catches the raised-precision silent-truncation defect.
- Zero-form rows (`-0`, `0/4`, `00/4`, `-0/4`, `0 0/4`, `-0.0`) all canonicalise to `"0"`.
  *Mutant:* remove the zero rule — `-0/4` comes back as `-0/4` or `"-0"`.
- Round-trip and idempotence over the same enumerated table, **excluding** the `None` and
  `TOO_LONG` rows (feeding a sentinel back in is not a meaningful round-trip).
- **JSON-numeric input**, the LAL manifest case: `canonical_numeric_text(2.5)` returns `"2.5"`,
  `canonical_tolerance_text(0)` returns `""`, and — the case that matters —
  `canonical_tolerance_text(0.00001)` returns `"0.00001"`. *Mutant a:* drop the coercion prologue
  — a `float` raises `AttributeError` mid-import. *Mutant b:* route floats through a bare
  `str()` — `0.00001` becomes `'1e-05'`, canonicalises to `None`, and the loader aborts. Only the
  small-float case catches mutant b; `2.5` passes under both. A loader test feeding
  `{"value": 2.5, "tolerance": 0.00001}` covers it end to end.
- A JSON `true` returns `None` rather than raising. *Mutant:* fold `bool` into the numeric
  branch — `Decimal("True")` raises `InvalidOperation`.
- `canonical_tolerance_text`: `""`, `"0"`, `"0.00000000"`, `"0/5"` → `""`; `"1/100"` → `"1/100"`;
  `"-1"` → `None`. *Mutant:* have it fall through to `canonical_numeric_text` for zero — `"0"` is
  returned and the "± 0" reveal regression reappears.
- Length guard: a 5000-digit numerator returns `None` from **both** `parse_numeric_value` and
  `canonical_numeric_text`. *Mutant:* remove either guard — the test fails with `ValueError`,
  not with a wrong return value.
- **Output-length guard:** `canonical_numeric_text("." + "1"*63)` returns `TOO_LONG`. *Mutant:*
  check only the input length — the function returns a 65-character string that will not fit the
  column. This is the only test that catches the interaction between the raised precision and
  the storage cap.
- Zero denominator on **both** paths: `"1/0"` and `"1 1/0"` each return `None`. *Mutant:* guard
  only the fraction branch — the mixed input raises `ZeroDivisionError`.
- **The two caps are independent:** `parse_numeric_value` accepts a 100-character numeric string
  (pinning that it uses the 256 cap, not the 64 one), while `canonical_numeric_text` rejects it.
  *Mutant:* collapse them into one constant — the fill-blank behaviour silently narrows.
- Non-string input: `parse_numeric_value(Decimal("1.5"))` returns `Fraction(3, 2)`, not
  `AttributeError`; and `parse_numeric_value(Decimal("0.00000000"))` returns `Fraction(0)`.
  *Mutant:* coerce with a bare `str()` — the second case becomes `'0E-8'`, which no grammar
  matches, and returns `None`. This is the same root cause as the migration's `str()` trap, at a
  second call site.
- `parse_number` is asserted to still accept a 5000-digit string, pinning that it did **not**
  receive a length guard and that `views.py:1162` / `element_forms.py:314` are unaffected.
- The existing `parse_number("1/2") is None` regression test stays green, pinning that the two
  parsers remain separate.
- `MAX_STORED_NUMERIC_CHARS` equals the model field's `max_length`.
- `validate_tolerance_text("")` does not raise.

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
- **The fraction round-trip, same mechanism:** save `3/2`, reload the edit form, assert the
  rendered value is exactly `"3/2"`. The Purpose section's headline promise ("reopening the
  editor renders `3/2` verbatim") is otherwise never asserted, and removing the `__init__`
  override changes precisely this initial-value path.
- **The two length failures are different tests and must not be conflated.** A *64-character*
  `"." + 63 digits` value reports the custom
  `That number is too long (at most 64 characters once normalised).` — it passes
  `MaxLengthValidator` and is caught by the canonical-output check. A *>64-character* input never
  reaches `clean_value` at all and reports Django's built-in max-length message. Writing the
  first test with a 70-character input is the natural mistake and makes it fail.
- An **unparseable tolerance** (`abc`) is a field error, not a `TypeError`. *Mutant:* drop the
  `p is not None` guard in the negative re-derivation — the editor 500s on the commonest bad
  input, and no existing test covers a bad *tolerance* (only a bad value).
- `1/0` is a field error, not a 500.
- A >64-character input produces Django's built-in max-length error (the other half of the pair
  above).
- The guess-number tolerance error text is asserted **unchanged**, guarding against a blanket
  find-replace of the shared msgid.

**Model-validator test**

- `ShortNumericQuestionElement(value="abc")` and
  `ShortNumericQuestionElement(value="1", tolerance="-1")` each raise `ValidationError` from
  `full_clean()`, asserted **on the error-dict key** (`"value"` / `"tolerance"`), not merely that
  some `ValidationError` was raised. *Mutant:* drop the `validators=[...]` argument.
  **The `value="1"` is load-bearing.** `value` is a non-blank `CharField` with no default, so
  `ShortNumericQuestionElement(tolerance="-1")` has `value == ""` and `clean_fields()` raises
  "This field cannot be blank" whether or not `validate_tolerance_text` exists — the named mutant
  would leave the test green. Asserting the key is what makes it able to fail.
- **The validator catches the sentinel too:** `ShortNumericQuestionElement(value="." + "1"*63)`
  raises from `full_clean()` with key `"value"`. *Mutant:* have the validator check only for
  `None` — the 64-character input passes `MaxLengthValidator` **and** the validator, `clean()`
  correctly declines to rewrite, and a non-canonical, uneditable element is saved.
- **Canonicalisation is enforced, not assumed:** `ShortNumericQuestionElement(value="1.50000000",
  tolerance="0")` after `full_clean()` holds `value == "1.5"` and `tolerance == ""`. *Mutant:*
  remove the `clean()` override — the validators still pass and defect 3 is reconstituted in
  storage. This is the test that turns the write-path list into an invariant.
- **`clean()` does not null a rejected field:** `ShortNumericQuestionElement(value="abc")` raises
  `ValidationError` from `full_clean()` **and** leaves `instance.value == "abc"`. *Mutant:* drop
  the `is not None` guard in `clean()` — the instance is left holding `None` in a non-null
  column, and `full_clean()` runs `clean()` even after `clean_fields()` raised, so this is
  reachable on the ordinary invalid-input path, not an exotic one.

**Migration test** — follow `courses/tests/test_publish_migration.py` as the template. Its
constraints are mandatory here and this repo has already been bitten by ignoring them:
`@pytest.mark.django_db(transaction=True)`, and a `finally` block that re-migrates to the leaf.
Three of the tests below unapply and re-apply `0058`, one of them deliberately aborting `forwards`
mid-run and one deliberately raising on the way down; a half-restored migration state poisons
every later test on that xdist worker with failures that land nowhere near this file.

- Build rows at the old schema with `value=Decimal("1.50000000")`,
  `tolerance=Decimal("0.10000000")` and `tolerance=Decimal("0")`; run `0058` forwards; assert
  `"1.5"`, `"0.1"`, `""`. *Mutant:* drop `format_decimal_plain` in favour of `str()` — the
  assertions fail on the trailing zeros, which is precisely the defect being retro-fixed.
- **The E-notation row:** include `tolerance=Decimal("0.00000001")` and a plain zero, asserting
  `"0.00000001"` and `""`. *Mutant:* route the tolerance through `str()` — both become
  E-notation, canonicalise to `None`, and the migration dies on `IntegrityError`. Without this
  row the migration looks healthy on any fixture that happens to use round numbers, and fails on
  the real database.
- A row with `tolerance=Decimal("-0.5")` aborts the migration with the named error, **before**
  any row is written. *Mutant:* drop the counting pass — the run dies on `IntegrityError`
  partway through, which is unrecoverable given the irreversibility.
- Reversing `0058` **with rows present** fails at the database layer (re-adding a non-null
  `DecimalField` with no default), asserted as `django.db.utils.Error` — deliberately the base
  class, because the exact subclass is backend-specific and pinning it would test Postgres, not
  us. This replaces the `IrreversibleError` assertion an earlier draft called for; see the
  reverse-is-a-noop rationale above for why true irreversibility had to be given up.
- No **new** makemigrations test is needed:
  `courses/tests/test_publish_makemigrations.py::test_no_pending_migrations` already runs
  `makemigrations courses --check --dry-run`. It must be run as part of the migration task's
  verification, because a hand-written five-op chain easily lands on a migration state that
  differs from the model in some attribute (a leftover `default`, a missing `blank`, validator
  ordering).

**Transfer round-trip tests** (`tests/test_transfer_export.py`, `tests/test_transfer_import.py`)

- Export → import an element with `value="1/3"` preserves `"1/3"`.
- **Export → import a zero-tolerance element** round-trips `""` without error. *Mutant:* route
  the importer's tolerance through `canonical_numeric_text` — `""` becomes `None` and the import
  raises. This is the `""`-tolerance import failure, and it breaks every existing zero-tolerance
  element, so it must be a named test.
- A legacy payload with `"1.50000000"` / `"0.00000000"` imports as `"1.5"` / `""`.
- A payload with `"value": "abc"` raises `TransferError`, not `InvalidOperation`.
- A payload **missing** the `tolerance` key still raises (the `_exact_keys` contract is unchanged).
- A **non-string** `"value": 42` raises with the `"must be a decimal string"` substring — the
  branch is otherwise untested (see the transfer section).
- A 64-character `"." + 63 digits` value raises `TransferError`. *Mutant:* test only for `None` —
  `TOO_LONG` passes the validator and the sentinel object reaches the column.
- A **negative** tolerance raises with the element-naming `"tolerance must not be negative"`
  message, not the generic parse failure. *Mutant:* fold the negative branch into the parse
  failure — the element id vanishes from a whole-course import's diagnostics.
- An **unparseable** `"tolerance": "abc"` raises `TransferError` with the parse-failure substring.
  *Mutant:* drop the `p is not None` guard — the import view 500s instead of rejecting. No
  existing transfer test exercises a bad tolerance at all.
- `FORMAT_VERSION == 11` is asserted, and a version-12 zip is refused.
- **Duplicate-element:** duplicating a zero-tolerance `3/2` element yields a copy holding `"3/2"`
  and `""`, exercising export → validate → build in one process.

**Existing tests affected** — per the project's affected-tests discipline these are enumerated
now, not discovered at the branch gate. The split matters: a table that mixes "will fail" with
"should be tidied" is useless as RED/GREEN evidence, because an implementer who sees a listed
test stay green cannot tell whether the change landed. Re-derive this table by grepping every
`ShortNumericQuestionElement` construction and every assertion on `.value` / `.tolerance` under
**both** `tests/` **and** `courses/tests/` — the repo has two test packages, and scoping the
sweep to one of them is how the LAL and restore sites below get missed.

*(a) Fails after the change — must be edited:*

| file:line | current assertion | needed edit |
|---|---|---|
| `tests/test_questions_2b_authoring.py:81` | `q.value == Decimal("3.14") and q.tolerance == Decimal("0.01")` | compare to `"3.14"` / `"0.01"` |
| `tests/test_questions_2b_forms.py:28-29` | `ok.cleaned_data["value"] == Decimal("3.14")` and `["tolerance"] == Decimal("0.01")` | compare to `"3.14"` / `"0.01"`; `clean_*` now return `str`. Note `tolerance="0,01"` canonicalises to `"0.01"`, **not** `""` — it is non-zero. This file is also where the new form tests go, so leaving it unlisted would make the pre-existing red indistinguishable from a new one |
| `tests/test_lal_loader_units.py:597` | `obj.value == Decimal("2.5")` | `obj.value == "2.5"`; `"2.5" == Decimal("2.5")` is `False` |
| `tests/test_transfer_validation.py:548` | `_reject(..., "decimal")` for `value="abc"` | the parse-failure message becomes `"is not a valid number or fraction"`; update the substring to match that, not a looser one |
| `tests/test_transfer_validation.py:557` | `_reject(..., "decimal")` for `Infinity`/`NaN` | same substring change; the *rejection* still holds, since no grammar matches them |

*(b) Still passes, but should be updated for clarity:*

| file:line | why it survives | suggested edit |
|---|---|---|
| `tests/test_questions_2b_consumption.py:65` | `CharField.to_python` stringifies a `Decimal` on save, so `objects.create(value=Decimal("3.14"))` stores `"3.14"`; the test never reads it back as a `Decimal` | pass canonical strings so the intent is legible |
| `tests/test_quiz_answer.py:109` | same coercion | `value="4", tolerance=""` |
| `tests/test_lal_loader_units.py` `test_build_numeric_with_points_sets_max_marks` | feeds `tolerance: "0"`, which now canonicalises to `""`, but asserts only on `max_marks` | add a `tolerance == ""` assertion while it is open |
| `tests/test_transfer_export.py:121` `test_short_numeric_decimals_are_strings` | **becomes tautological.** Its whole point is that a `Decimal` field serialises to a string; once `value` *is* a `CharField`, `str()` is a no-op and the test can no longer fail for the reason it was written — this repo's recurring "assertion that cannot fail" defect | repurpose it: assert a fraction-valued element exports its *canonical* string |
| `courses/tests/test_question_restore.py:136` and `:290` | both `objects.create(stem="Q", value=42, tolerance=0)` — **ints**, which survive via `CharField.to_python`. They do **not** exercise the non-string parse path: they post to the check endpoint, which refetches from the DB, so `mark()` already sees strings | pass canonical strings (`value="42", tolerance=""`) so the suite stops seeding the non-canonical `"0"` tolerance the error table calls unreachable |
| `tests/test_questions_2b_marking.py:219` `test_shortnumeric_mark_tolerance_and_decimal_comma` | **this** is the test that depends on the new coercion: it calls `q.mark(...)` on the in-memory instance built with `value=Decimal("3.14")`, so `self.value` is still a `Decimal`. It is also the element's primary marking test and was missing from both halves of this table | keep it green as coercion evidence, then add canonical-string equivalents alongside rather than replacing it |
| `tests/test_quiz_consumption_render.py:50`, `tests/test_transfer_export.py:144`, `tests/test_transfer_import.py:186` | three further construction sites | sweep them in the same pass; canonical strings |

`tests/factories.py` needs **no** change: it re-exports `ShortNumericQuestionElement` as a name
but defines no factory for it, so there are no `value`/`tolerance` defaults there to update.

The fill-blank / fill-in-table / fill-&-confirm marking tests must stay green **unmodified** —
they are the evidence that `MAX_PARSED_NUMERIC_CHARS` did not silently change existing matching.

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
