# Guess the number

A numeric self-check element with directional ("too big" / "too small") feedback. This is the last
unbuilt item on the interactive-elements roadmap, ported from the legacy Demo Course `.more_less_guess`
widget. This spec also carries one small bundled label rename (see §8).

## 1. Purpose

### 1.1 What it is

The author writes a stem containing exactly one `{{target}}` token. The student types a number into
the input the token becomes, and clicks Check (or presses Enter). The server compares it to the target
and answers with one of three verdicts:

- **correct** — reveal a custom success message, lock the input;
- **too big** / **too small** — a directional nudge; the student tries again, unlimited times.

### 1.2 Why it exists — evidence from real usage

**Legacy source root:** `C:/Users/krzys/Documents/teaching/LAL/html/`. Every legacy path below is
relative to it, and none of them exist in this repo — an implementer wanting to check a behavioural
claim about "the legacy" must look there.

The demo (`_template.html`, "Zgadnij liczbę między 10 a 20") frames the widget as a guessing game, but
the real lesson usages are **numeric self-checks** where the direction hint nudges a student to recheck
their arithmetic. There are **five `.more_less_guess` instances across two lesson files**:

- `001_zbiory_liczbowe/140_liczby_r_zast.html` — **2 instances** (targets `100`, `8`). "O ile procent
  więcej tabletów sprzedała firma TeraSoft niż firma OpenArch?" — input below a prose prompt. This is
  the file whose success message is a full explanation carrying math:
  `Tak, TeraSoft sprzedała o \(100\%\) niż OpenArch.`
- `005_wyrazenia_algebraiczne/wyr_alg_145_wsm.html` — **3 instances** (targets `40401`, `998001`,
  `39999`). `\(201^2=\)` immediately followed by the input, **inline**, with the three rows stacked.
  Its success messages are bare praise: `Świetnie!`, `Znakomicie!`, `Doskonale!`.

A third file, `150_f_wykladnicza/010_test.html`, seeds `more_less_answers` with `200: 14` as a test
fixture rather than a lesson usage.

Read honestly, the evidence says: **4 of 5 success messages are bare praise; exactly 1 is a
math-bearing explanation.** That one is still decisive — the element must support math in the success
message, because an author demonstrably wants it — but the "full explanation" is the minority case, not
the norm, and the design should not overclaim it.

**All five targets are integers.** That is the real evidence that `tolerance = 0` is the correct
default, with non-zero tolerance serving the game/approximation framing rather than the observed usage.

Three consequences are load-bearing throughout:

1. the input must be able to sit **inline**, flowing against rendered KaTeX (§2.2, §5);
2. both the stem **and** the success message can carry math, so the element must be math-bearing on
   both fields (§2.5 — a hard dependency, not a nicety);
3. wrong answers are **expected and repeated**, which is what forces the ungraded design (§1.3).

### 1.3 Why a new element and not an enhancement

The roadmap requires verifying overlap with existing elements before adding a new one. That check was
done, and the overlap is substantial:

- `ShortNumericQuestionElement` (`courses/models.py`) already has exactly these matching semantics —
  `value` + absolute `tolerance`, parsed via `parse_number`. It already supports unlimited attempts in
  lessons (`max_attempts` is dormant outside quiz units) and a `NOT_MARKED` marking mode.
- `FillBlankQuestionElement` already does inline `{{token}}` authoring, and `blank_matches` already has
  a numeric branch, so `\(201^2=\){{40401}}` with `3,14 == 3.14` works today.

**The only genuinely novel behaviour is the directional hint.** A new element is still the right call,
and the decisive reason is **marks**. Both candidates for enhancement are `QuestionElement` subclasses,
which route every check through `check_answer` and record a `QuestionResponse` — feeding analytics and
the gradebook. This element is built around making *many wrong attempts*; recording each guess as a
graded response is wrong, and "guess a number between 10 and 20" as a gradebook row is nonsense.

The whole sibling family — Switch grid, Fill-in table, and both reveal gates — is ungraded *on
purpose*, for exactly this reason. This element joins that family.

Rejected alternatives, for the record:

- **Enhance `ShortNumericQuestionElement`** with a `directional_hint` flag: smallest possible diff, but
  stays graded, and its `stem` is a block prompt so it cannot produce the inline `201² = [input]`
  layout.
- **Enhance `FillBlankQuestionElement`** with a per-blank numeric hint: gets inline tokens free, but is
  also graded, has no per-blank tolerance, and bolts numeric-comparison config onto a text-blank
  element.

### 1.4 Non-goals (YAGNI — explicitly decided)

- **min/max range fields.** The stem states the range in prose ("Zgadnij liczbę między 10 a 20"); an
  auto-rendered range hint would be a second way to say the same thing.
- **Guess history / attempt counter.** Only the latest verdict is shown, as in the legacy widget.
- **Per-instance custom hint wording.** The "too big"/"too small" strings are i18n defaults (§9). (The
  *success* message is customisable — §1.2 shows one author wanting it; the hint wording has no such
  evidence.)
- **Cross-reload persistence.** Nothing is stored per student. A reload resets the widget.
- **Quiz availability — out of scope.** The Interactive palette group is quiz-hidden, but that gate
  (`{% if not unit_is_quiz %}` in `_add_menu.html`) blocks *adding* only. An element already in a lesson
  survives a later `unit_type` flip to quiz, and the transfer validator does not check the host unit's
  type; on either path the widget renders into `quiz_unit.html`, which loads no `guessnumber.js`, so the
  Check button is **never un-hidden** (§2.7) and the student sees a bare, unusable input — and pressing
  Enter in it reloads the quiz page (implicit submission, §2.7). No answers are lost, since each question
  posts to its own form. This is pre-existing and shared with every Interactive sibling — accepted, not
  solved here.
- **Answer secrecy.** See §4.4 — the success message is deliberately public to the client.

## 2. Architecture / components

### 2.1 Model — `GuessNumberElement(ElementBase)`

A plain `ElementBase` subclass, **not** a `QuestionElement`. Ungraded, lesson-only, persists nothing,
reveals nothing — explicitly **not** a reveal gate (mirror `SwitchGridElement`'s docstring, which is
the clearest statement of the self-check contract).

| Field | Type | Notes |
|---|---|---|
| `stem` | `TextField(blank=True)` | The `￿0￿` token-stem. **Not** sanitised in `save()` — sanitisation is a form-side ordered pipeline (§2.3). |
| `target` | `DecimalField(max_digits=20, decimal_places=8)` | Derived from the token by the form; never a form field itself (§2.3). |
| `tolerance` | `DecimalField(max_digits=20, decimal_places=8, default=0, MinValueValidator(0))` | `0` = exact match (the default, and what all five real usages need — §1.2). `> 0` enables the approximation/bisection game. |
| `success_message` | `TextField(blank=True)` | Rich text + math, sanitised in `save()` with **`sanitize_html`** (§2.4). Blank falls back to a generic translated "Correct!". |
| `elements` | `GenericRelation(Element)` | Cascade: deleting this removes its join-row. |

`target`/`tolerance` deliberately mirror `ShortNumericQuestionElement`'s field shapes so numeric
behaviour stays consistent across the codebase.

**`render` must return rendered HTML, not a context dict.** The base `ElementBase.render` does not pass
`eid`, so this type overrides it, following `FillGateElement.render` / `SwitchGateElement.render`
exactly:

```python
def render(self, **_kwargs):
    from django.template.loader import render_to_string

    join = self.elements.order_by("pk").first()
    return render_to_string(
        "courses/elements/guessnumberelement.html",
        {"el": self, "eid": join.pk if join else 0},
    )
```

`eid` is the **`Element` join-row pk, not the concrete model pk** — that is what the endpoint takes,
and the distinction matters for nesting. The `**_kwargs` signature absorbs the render-context seam's
kwargs (`checklist`/`slug`/`node_pk`), which this element ignores.

### 2.2 Authoring

The author types one stem, e.g. `\(201^2=\){{40401}}`. Token placement decides layout for free, via
ordinary inline flow — a token at the end of a line renders the input inline (math flows into it); a
token on its own line renders it stacked. This is what lets one field serve both real usages.

`tolerance` and `success_message` are separate form fields (mirroring `ShortNumericQuestionElement`) —
deliberately not crammed into the token, which stays a pure answer marker.

### 2.3 Token module, form, and validation

#### 2.3.1 `courses/guessnumber.py`

Neither existing token mechanism fits off the shelf, so this element gets its own small module,
modelled directly on **`courses/switchgate.py`** (the single-token-stem precedent) and reusing
`courses/fillblank.py`'s primitives:

- `courses.fillblank.parse()` extracts token *contents* but splits on `|` into alternatives, numbers
  tokens `￿0￿…￿n￿`, and raises on "no blanks" — its `to_author_stem(token_stem, blanks)` needs a
  `blanks` list this element does not have.
- `courses.switchgate.parse_stem()` enforces exactly-one, but only for the *fixed literal* `{{choice}}`
  marker, which carries no payload.

`courses/guessnumber.py` therefore provides, mirroring `switchgate.py`'s shape:

```python
SENTINEL_TOKEN = fillblank.SENTINEL + "0" + fillblank.SENTINEL   # reuse fillblank's sentinel

class GuessNumberError(ValueError):
    """Carries a `code` so clean_stem can map each check to its own message (§2.3.3).

    ValueError accepts no keyword arguments, so the code must be a positional
    __init__ parameter — `GuessNumberError(code="token_count")` would TypeError."""

    def __init__(self, code, *args):
        self.code = code
        super().__init__(code, *args)

def parse_stem(clean: str) -> tuple[str, str]:
    """-> (token_stem, raw_target_str). Exactly one {{...}} token; math masked first."""

def to_author_stem(token_stem: str, target: Decimal) -> str:
    """Inverse: SENTINEL_TOKEN -> '{{' + format_target(target) + '}}'."""

def render_stem(token_stem: str, widget_html: str) -> SafeString:
    """Split on the sentinel, splice the widget in.

    Import and REUSE switchgate.render_stem — SENTINEL_TOKEN is byte-identical in
    both modules, so a copy would be pure duplication (the same argument §2.3.1
    makes for promoting mask_math rather than re-writing its regex)."""

def format_target(target: Decimal) -> str:
    """Canonical author-facing text for a stored target (§2.6)."""
```

**Math must be masked before token scanning.** `fillblank._mask_math` / `_restore_math` exist precisely
so that braces inside KaTeX (e.g. `\text{{x}}`) are not misread as a token. Since `parse_stem` lives in
a *different* module, the cross-module import is a settled fact, not a contingency: **promote them to
public `fillblank.mask_math` / `fillblank.restore_math`** (they are currently private and used nowhere
else) rather than duplicating the regex. That makes `courses/fillblank.py` a touch-point (§7).

#### 2.3.2 `GuessNumberElementForm`

A **`ModelForm`** over `["stem", "tolerance", "success_message"]` — `target` is deliberately absent, so
it stays derived. Being a `ModelForm` matters beyond style: `save_element` (`courses/builder.py`) has a
generic `else` branch that does `FORM_FOR_TYPE[type_key](data, files, instance=instance).save()`, which
every `ModelForm` element rides with **no builder branch** (`FillGateElementForm` does exactly this).
Only plain `forms.Form` types (`SwitchGateElementForm`) need a dedicated `elif`. This element needs
none.

The form has **three** parts, not two — all three are load-bearing:

```python
# Module-level in courses/element_forms.py. gettext_LAZY is mandatory: an eager
# gettext() here froze labels to English once already (PR #46, and §8.2 repeats
# the warning). Keyed by GuessNumberError.code.
_GUESS_STEM_ERRORS = {
    "token_count":  gettext_lazy("Write the answer in double braces, e.g. {{42}}."),
    "alternatives": gettext_lazy('Use exactly one answer in braces — alternatives '
                                 'separated by "|" are not supported here.'),
}


class GuessNumberElementForm(forms.ModelForm):
    parsed_target = None  # Decimal after a successful clean_stem

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # (a) Show the author their token, not the raw ￿0￿ stem.
        if self.instance and self.instance.pk:
            self.initial["stem"] = guessnumber.to_author_stem(
                self.instance.stem, self.instance.target
            )
        # (b) Same ','/'.' leniency the students get — see below.
        self.fields["tolerance"] = forms.CharField(required=False)

    def clean_stem(self):
        raw = self.cleaned_data.get("stem", "")
        clean = fillblank.strip_sentinel(sanitize_html(raw))
        try:
            token_stem, raw_target = guessnumber.parse_stem(clean)   # checks 1-2 (§2.3.3)
        except guessnumber.GuessNumberError as e:
            raise forms.ValidationError(_GUESS_STEM_ERRORS[e.code]) from e
        self.parsed_target = <checks 3-4 on raw_target>              # stashed for save()
        return token_stem                                            # returns ONE value

    def clean_tolerance(self):
        ...                                                          # parse_number; blank -> 0

    def save(self, commit=True):
        self.instance.target = self.parsed_target
        return super().save(commit)
```

**(a) `__init__` must populate `initial["stem"]`.** Without it, `guessnumber.to_author_stem` and
`format_target` (§2.3.1) have no caller at all, the edit form shows the raw `￿0￿` token-stem, and §6's
headline round-trip test cannot pass. Both `FillGateElementForm.__init__` and
`SwitchGateElementForm.__init__` do exactly this. `parsed_target = None` is a **class attribute** (as
`FillGateElementForm`'s `parsed_blanks = None` is), so any path touching it after a failed clean gets
`None` rather than `AttributeError`.

**(b) `tolerance` must be re-declared as a `CharField`, not left as the ModelForm default.** A plain
`ModelForm` over a `DecimalField` would (i) **reject a Polish author's `0,5`** — while §2.6 mandates
that the same author's `{{40401,5}}` be accepted in the very same form — and (ii) make `tolerance`
**required**, since `DecimalField(default=0)` without `blank=True` yields `formfield(required=True)`,
even though §1.2 shows all five real usages wanting the default `0`.

`ShortNumericQuestionElementForm.__init__` already solves this exactly, and its comment states the
reason: *"Replace the locale-sensitive DecimalField parsing with parse_number so authors get the same
','/'.' leniency as students (PL/EN bilingual)."* Mirror it: `forms.CharField(required=False)` plus a
`clean_tolerance` that runs `parse_number`, returns `0` on blank, and rejects negatives. **Reuse its
existing msgids** — `_("Enter a number (e.g. 3.14 or 3,14).")` and `_("Tolerance cannot be negative.")` —
rather than minting new ones.

**Pipeline ordering is a security invariant, not style.** `courses/fillblank.py` mandates
`sanitize_html(raw)` → `strip_sentinel` → `parse`, as `FillGateElementForm.clean_stem` implements.
`strip_sentinel` must run on raw author input **before** parsing, so a stored token can never be forged
from prose. The model's `save()` leaves `stem` alone. (`success_message` *is* sanitised in `save()` — it
carries no tokens, so it has no ordering constraint; §2.4.)

#### 2.3.3 Validation — all raised as form errors, never coerced or deferred to the DB

Four checks, in this exact order. **Which layer owns which is pinned**, because otherwise an implementer
cannot tell where a given failure is raised, and all four collapse into one indistinguishable message:

| # | Check | Owner | Failure |
|---|---|---|---|
| 1 | Exactly one `{{...}}` token (zero or 2+ → error) | `guessnumber.parse_stem` | `GuessNumberError("token_count")` |
| 2 | No literal `|` inside the token | `guessnumber.parse_stem` | `GuessNumberError("alternatives")` |
| 3 | Token contents parse via `parse_number` → `Decimal` | `clean_stem` | `ValidationError` |
| 4 | The parsed `Decimal` fits `max_digits=20, decimal_places=8` | `clean_stem` | `ValidationError` |

**The empty token `{{}}` is deliberately left to check 3.** `fillblank._MARKER_RE` (`\{\{(.*?)\}\}`,
which `parse_stem` mirrors) allows an empty interior, so `{{}}` is *one* token and passes check 1, then
fails check 3 with "The answer must be a number…". `fillblank.parse` raises a distinct "empty marker"
error for this case, but a fifth code is not worth it here: check 3's message already tells the author
exactly what to do, and an empty token is a typo, not a distinct intent. Noted so the behaviour reads as
a decision rather than an oversight.

`GuessNumberError` carries a `code` attribute so `clean_stem` maps each to its **own** author-facing
message (§9). Check 2 exists to make `{{40401|40402}}` an *explicit* error rather than silently two
fill-blank alternatives — which only works if its message is distinguishable from check 1's.

Check 4 is mandatory, not defensive: `target` is derived, not a form field, so Django's ModelForm
`_post_clean` excludes it from `full_clean` and its `DecimalValidator` never fires. Without it the DB
raises a numeric-overflow `DataError` (a 500), and over-precise input is silently rounded.

**The real bound is 12 integer digits, not 20.** `check_decimal_str` rejects when
`digits - exponent > max_digits - decimal_places`, i.e. `20 - 8 = 12`. A 13-digit target already errors.
State this as a product limit: **at most 12 digits before the decimal point and 8 after.**

**Reuse `check_decimal_str(value, what, max_digits, decimal_places)` — defined in
`courses/transfer/schema.py`** (`payloads.py` merely imports it), so authoring and import agree on one
bound. Two things this requires, and both are easy to get wrong:

- **It raises `TransferError`, not `ValidationError`.** Called bare from `clean_stem`, a `TransferError`
  escapes `form.is_valid()` uncaught — a 500, which is exactly the failure step 4 exists to prevent.
  Wrap it: `try: check_decimal_str(...) except TransferError as e: raise forms.ValidationError(<author
  message>) from e`. Do not surface the helper's own text ("%(what)s has too many digits.") — it is
  transfer-flavoured and reads wrong in the editor.
- **Feed it `str(parsed)`, never the raw token text.** It does `Decimal(value)` on a string and rejects
  `InvalidOperation`, so raw `"40401,5"` would raise → the comma round-trip §6 mandates would become a
  form error. Running `parse_number` first (step 3) and passing `str(parsed)` is what makes `{{40401,5}}`
  pass **and** `{{40401.000000000}}` (9 dp) fail rather than round.

### 2.4 `success_message` — sanitiser and escaping

Use **`sanitize_html`**, the same path `SpoilerElement.body` and `CalloutElement.body` use. Both are
docstring'd "rich text + math", both are math-detected via `has_math_delimiters(obj.body)` in
`_element_has_math`, and `FillGateElement.stem` — math-bearing, in `math.js`'s selector list — likewise
uses `sanitize_html` in its `clean_stem`. This element's own stem (§2.3) uses it too. `sanitize_html` is
simply this codebase's established path for a rich-text-plus-math body.

**`sanitize_cell` would be wrong here, for a concrete reason.** It cleans to
`CELL_TAGS = {"strong", "b", "em", "i", "u", "br"}` — no `<p>`, `<div>`, `<ul>`, `<li>`, `<a>`. Since
the edit partial mounts the same RTE surface (`data-rte-source`) the sibling stems use, and
contenteditable in Chrome/Safari wraps each Enter-separated line in a `<div>`, a multi-paragraph success
message authored in Chrome would silently collapse to one run-on line while Firefox (which emits `<br>`)
would be unaffected — a browser-dependent content-loss bug. Every existing `sanitize_cell` field
(switchgate `options`, table cells, gallery `desc`) is a short inline fragment and none mounts an RTE;
every `data-rte-source` field in the tree is a `sanitize_html` field.

`sanitize_cell`'s real benefit is narrow and does not apply: it stashes balanced math spans behind a
nonce so a tokenizer-hostile fragment like `\(a<b\)` is not mangled, and canonicalises via `_canon_math`.
Spoiler and Callout accept that same limitation on their math-bearing bodies; this element accepts it
too, rather than trading a rare escaping edge case for guaranteed block-markup loss.

`render_guess_number` (§2.7) emits the message, and **owns the blank fallback** — the two paths differ
in trust and must not be conflated:

- `el.success_message` non-blank → `mark_safe(el.success_message)` inside the `format_html`
  composition, carrying the `# noqa: S308 — sanitized at save()` comment the sibling tags use. Sound
  precisely *because* `save()` sanitised it.
- `el.success_message` blank → the tag emits the translated `_("Correct!")` **escaped** through
  `format_html`, never through `mark_safe`. It is a trusted literal, not saved content, and routing it
  through the `mark_safe` path meant for sanitised author HTML would blur that distinction for no gain.

Doing the fallback server-side is what lets `[data-guess-success]` always carry content, which is why
§2.7 needs no `data-msg-correct` and why a blank message can never render an empty box.

(There is no `|safe` filter anywhere, because there is no template — `guessnumberelement.html` is a
one-liner that delegates to the tag.)

**The edit partial mounts `data-rte-source` textareas for both `stem` and `success_message`**, with
`_rte_toolbar.html` — this is what makes the block-markup argument above real rather than hypothetical.
Follow `ShortNumericQuestionElementForm`'s route (`Meta.widgets = {...: forms.Textarea(attrs={
"data-rte-source": ""})}` + `{{ form.field }}`) rather than `_edit_switchgate.html`'s hand-rolled
`<textarea name="stem" data-rte-source>`; both work, and the hand-rolled shape still reads
`initial["stem"]` via `{{ form.stem.value }}` so §2.3.2a survives either way, but `Meta.widgets` keeps
the `data-rte-source` requirement in the form rather than in a template an implementer can forget.

### 2.5 Math wiring (hard dependency, two separate mechanisms)

**(a) `_element_has_math` gates KaTeX itself.** It (`courses/views.py`) is the documented **single
source of truth** for "does this element carry math?", and `has_math` is what makes
`templates/courses/lesson_unit.html` load `katex.min.js`, `auto-render.min.js` **and** `math.js` at all
(`{% if has_math %}`). An unknown type falls through to the container helpers and returns `False`.

Without a clause here, a unit whose only math is a guess-number stem (`\(201^2=\)`) — the element's
headline use case — loads **no KaTeX**, and everything below is moot. Add exactly one clause, covering
**both** fields:

```python
if isinstance(obj, GuessNumberElement):
    return has_math_delimiters(obj.stem) or has_math_delimiters(obj.success_message)
```

**(b) Inline-math rendering — one mechanism, not two.**

The stem's inline `\(…\)` math is already covered end-to-end by two *existing* mechanisms, provided the
element opts into the first:

- *Initial load, both surfaces:* `math.js` calls `renderInlineText(document)` once at load over a
  selector list (`.el--text, .el--table, …, .stepper, .markdone`). **Add `.guessnumber` to it.** This
  covers the lesson page and the editor alike, because `editor.html` also loads `math.js`.
- *After an editor fragment swap:* `editor.js` already defines its own `renderPreviewMath(scope)`
  (auto-render over the whole preview) and `applyFragments` calls it **before** the `libliInit*` chain.
  A freshly-swapped stem is therefore already typeset.

So `guessnumber.js` needs **no** `typesetMath` of its own. `switchgate.js` has one only because
`.switchgate` is deliberately *absent* from `math.js`'s selector list — it opted out of the first
mechanism and had to re-add it per-widget. This element opts in, so adding `typesetMath` too would be a
second, redundant path with a *different* delimiter set (`math.js`'s `INLINE_DELIMS` vs auto-render's
`$$`-inclusive defaults) — a real inconsistency, not just duplication.

### 2.6 Number formatting — the round-trip rule

The author's literal token text is **not** stored; the editor rebuilds the token from `target`. That
makes the formatting rule load-bearing, because the naive options are both broken:

- `str(target)` → `Decimal('40401.00000000')` renders `{{40401.00000000}}` (quantized by
  `decimal_places=8`);
- `str(target.normalize())` → `Decimal('4.0401E+4')` renders `{{4.0401E+4}}`, which `parse_number`
  then **rejects** on the next save, making the element uneditable.

The rule is therefore:

```python
def format_target(target: Decimal) -> str:
    return format(target.normalize(), "f")   # 'f' = fixed-point; never scientific notation
```

`format(…, "f")` strips the exponent `normalize()` introduces, so `40401.00000000 → "40401"` and
`40401.50000000 → "40401.5"`.

**Separator policy:** the rebuilt token always uses `.`, even if the author typed `,`. `parse_number`
accepts both on input; the canonical stored/rebuilt form is `.`. So `{{40401,5}}` re-renders as
`{{40401.5}}` — an intentional canonicalisation, and it must be tested (§6), because silent
comma/period drift is a bug this codebase has shipped before (the `dragimage` `parseFloat` locale bug).

**Sign policy:** `parse_number`'s `_NUM_RE` accepts a leading sign, so a redundant `+` is dropped
(`{{+5}}` → `{{5}}`) while `-` is preserved (`{{-5}}` → `{{-5}}`). Same family of author-facing
canonicalisation as the separator, so it is named here rather than discovered later.

**This author-facing form is deliberately distinct from the archive form** — transfer exports `str(...)`
(§7.1), not `format_target`.

### 2.7 Template, render tag, DOM hooks, and JS

Files:

- `templates/courses/elements/guessnumberelement.html` — a **one-liner**: `{% load courses_extras %}` +
  `{% render_guess_number el eid %}`, mirroring `switchgateelement.html`.
- **`courses/templatetags/courses_extras.py`** — the new `render_guess_number(el, eid)` tag, modelled on
  `render_switch_gate`. This is where the DOM contract below is actually emitted, and it cannot be a
  template because the widget must be **spliced into the token-stem** by `guessnumber.render_stem` —
  something a template cannot express. (Needing `reverse` is *not* the reason;
  `fillgateelement.html` calls `{% url 'courses:fillgate_check' eid %}` in a template quite happily.)
- `templates/courses/manage/editor/_edit_guessnumber.html` — the edit-form partial. **Mandatory:** its
  absence 500s (`TemplateDoesNotExist`) the instant the palette card is clicked; `slidebreak` is the
  only element that legitimately lacks one.
- `courses/static/courses/js/guessnumber.js` — exposes an idempotent `window.libliInitGuessNumbers`.

**DOM contract** (pinned, because three consumers depend on exact names — `math.js`'s selector,
`libliInitGuessNumbers`'s query, and the e2e):

**The `<form>` is the outer container and wraps the stem; only inline markup is spliced at the token.**

```html
<form class="guessnumber" data-guessnumber
      data-element-pk="…" data-check-url="…"        <!-- no action -->
      data-msg-high="…" data-msg-low="…">
  …stem HTML, with this spliced in at the ￿0￿ token: …
      <input data-guess-input type="text" inputmode="decimal" aria-label="Your answer">
      <button data-guess-check type="submit" hidden>Check</button>
  …rest of stem…
  <div data-guess-live aria-live="polite">        <!-- ALWAYS rendered, never hidden -->
    <p   data-guess-hint    hidden></p>           <!-- JS fills text + un-hides -->
    <div data-guess-success hidden>…</div>        <!-- pre-rendered; JS un-hides -->
  </div>
</form>
```

| Hook | Name |
|---|---|
| Container (**is** the form) | `<form class="guessnumber" data-guessnumber data-element-pk="…" data-check-url="…">` |
| `math.js` selector addition | `.guessnumber` |
| JS query | `[data-guessnumber]` |
| Idempotency ready-flag | `dataset.guessnumberReady === "1"` (sibling convention: `dataset.switchgateReady`) |
| Spliced at the token (inline only) | `[data-guess-input]`, `[data-guess-check]` |
| Live region (persistent, never `hidden`) | `[data-guess-live]` |
| Visible hint slot (child of the region) | `[data-guess-hint]` |
| Success slot (pre-rendered, child of the region) | `[data-guess-success]` |
| Hint text source | `data-msg-high` / `data-msg-low` on the container |
| State classes | `is-wrong` / `is-correct` on `[data-guess-input]`; `guessnumber--done` on the container |

**Why the live region *contains* the slots instead of being one of them.** Accessibility dictates this
structure, and it is the one arrangement that satisfies three requirements that otherwise conflict:

1. A live region must already be in the accessibility tree **before** its content changes, or the change
   is not announced. `hidden` removes a node from that tree, so putting `aria-live` on a `hidden` div and
   un-hiding it inserts region *and* content in one step — a pattern NVDA/JAWS/VoiceOver handle
   inconsistently and frequently miss.
2. The success message **must** be pre-rendered for KaTeX to typeset it at page load (§2.5b). KaTeX
   processes `hidden` subtrees fine, so a hidden *child* is no obstacle.
3. The hint must be **visibly** shown — colour alone cannot carry the wrong state (§5).

Making `[data-guess-live]` a permanent wrapper resolves all three: it is always in the tree, so
un-hiding **either** child is a content change *inside an existing region* and announces reliably; the
success child is pre-rendered for KaTeX; and both children are visible, styled slots.

This also means the math-bearing explanation is announced, not just a "Correct!" gist — §1.2's one
decisive success-message use case (`Tak, TeraSoft sprzedała o \(100\%\)…`) is exactly the content a
screen-reader user most needs.

**`[data-guess-success]` always has content, so there is no `data-msg-correct`.** The blank-message
fallback (§2.1) is applied **server-side** in `render_guess_number` (§2.4), so JS never composes it.

**Hint text** reaches the JS via `data-msg-*` attributes on the container — the
`{% trans %}`-into-data-attr convention already used by `editor.js` (`data-msg-<key>`) — so no strings
are hardcoded in JS.

**`type="text"`, not `type="number"`** — pinned, because this is a silent killer. `type="number"` makes
Chrome and Firefox return `""` from `.value` for `40401,5`, so the Polish comma support that §1.2, §2.6
and §3.1 all treat as load-bearing would die in the browser before `parse_number` ever saw it — and
every comma test in §6 is server- or form-side, so it would ship green. `inputmode="decimal"` still gets
the numeric keypad on mobile. `parse_number` owns all parsing.

**State classes** follow `fillgate.js`'s family convention (`is-wrong`/`is-correct` on the input,
`fillgate--done` on the container): the CSS styles them, the JS toggles them, and §6's e2e asserts them.

Four constraints force exactly this shape:

1. **Enter needs a `<form>`.** `fillgate.js` gets Enter free because its widget *is* a form
   (`form.addEventListener("submit", …)`); an `<input>` in a bare `<div>` fires no submit event.
2. **But a `<form>` must not be spliced *into* the stem.** `sanitize_html`'s `ALLOWED_TAGS` includes
   `p`, `div`, `ul`/`li`, so an RTE-authored stem is plausibly `<p>\(201^2=\){{40401}}</p>`. The HTML
   parser auto-closes an open `<p>` on a `<form>` or `<div>` start tag, hoisting the widget and all
   following prose out of the paragraph. `switchgate.render_stem` is safe only because everything it
   splices is inline (`<button>`/`<span>`) — this element inherits the helper, so it must inherit the
   constraint. **Spliced markup MUST be inline-only.**
3. **The inline row must flow.** `<form>`/`<div>` are `display: block`, so splicing the whole widget at
   the token would break `201² = [input] [Check]` across lines. Wrapping instead of splicing avoids this
   entirely: the `<form>` keeps its default `display: block` as the element's outer box, and only the
   spliced input/button row needs the baseline treatment §5 decides.
4. **Both data attributes live on the same element.** `render_switch_gate` puts `data-element-pk` and
   `data-check-url` together on its container; splitting them would force the JS to read one from the
   container and the other from a descendant, and would leave §4's `data-element-pk == "0"` preview
   guard on a different node from the URL it gates.

Omitting `action` is what keeps a no-JS Enter from navigating to the JSON endpoint — `data-check-url`
carries the URL instead.

**The Check button ships `hidden` and is armed by JS.** Both precedents do exactly this —
`fillgateelement.html` renders `<button type="submit" class="fillgate__confirm" hidden>` and
`fillgate.js` does `if (btn) btn.hidden = false;  // arm Confirm now that JS is live` (switchgate.js
likewise). `libliInitGuessNumbers` un-hides `[data-guess-check]`.

**What `hidden` does and does not buy** — stated precisely, because it is easy to over-claim:

- It **does** make the click path inert without JS (no visible control to press) and keeps this element
  consistent with both siblings.
- It **does not** prevent submission. Per the HTML spec, implicit submission fires a click at the form's
  *default button* — the first `type=submit` in tree order — and `hidden`/`display:none` does not
  disqualify it (only `disabled` does; the "hidden submit button" trick is precisely how Enter is
  normally enabled). And with no button at all, a form with a single implicit-submission-blocking field
  — which this form has, exactly one `<input>` — submits on Enter anyway.

**So without JS, Enter in the guess input reloads the page.** That is accepted, and it is what
`fillgate` already does: only `e.preventDefault()` in the JS handler (§3.2) suppresses navigation, and
without JS there is no handler. The blast radius is deliberately nil — the input carries **no `name`**,
so nothing leaks into the query string, and the GET lands back on the same lesson URL. Any claim that
the no-JS or quiz path is "inert" refers to the click path only.

**The success message is server-rendered into `[data-guess-success]`, not returned by the endpoint.**
This is load-bearing: a success message may contain math (§1.2), and KaTeX must process it at page load.
JS only un-hides it. (Its cost — the message is public to the client — is weighed in §4.4.) The
directional hints need no pre-rendering, because they are plain text with no math: JS writes them into
`[data-guess-hint]` from the container's `data-msg-*` attributes.

**No prepaint watchdog is needed, by design.** The reveal gates need one because they *hide lesson
content* and must fail open if JS dies. This element hides nothing — dead JS costs only the feedback,
never trapped content. A flat `has_guess_number` flag in `build_lesson_context` gates the `<script>`
tag in `lesson_unit.html`; that is the whole wiring.

**The `has_guess_number` flag must not be written the obvious way.** `build_lesson_context`'s
`elements` list is scoped `parent__isnull=True`, so a flag computed from that list silently misses
tab-nested and column-nested children, and the JS never loads for them. Use the flat
`node.elements.filter(...)` form. This has bitten twice; both stepper and mark-done ship explicit
regression tests for it (§6).

## 3. Data flow

1. **Render.** `render_guess_number` builds the widget HTML per §2.7 — the wrapping `<form>`, the inline
   `<input>` + hidden Check spliced into the token-stem at the sentinel by `guessnumber.render_stem`,
   and the persistent `[data-guess-live]` region holding an empty `[data-guess-hint]` and a pre-rendered
   `[data-guess-success]`, both `hidden`.
2. **Trigger.** Check click or Enter, both via the form's native `submit` event — see §3.2.
3. **Request.** `POST guess=<str>`, CSRF from the `csrftoken` cookie sent as an `X-CSRFToken` header
   (the convention both gate scripts use; `{% csrf_token %}` in the template is a MarkDone-only thing).
4. **Server.** Resolve element (soft) → access gate → `parse_number(guess)` → verdict.
5. **Response.** `{"correct": bool, "direction": "high"|"low"|null}`, where `direction` is from the
   **student's** perspective: `"high"` means *your guess is too big*.
6. **Apply.**
   - `correct` → hide `[data-guess-hint]`, un-hide `[data-guess-success]`, swap the input's `is-wrong`
     for `is-correct`, lock it `readonly`, add `guessnumber--done` to the container.
   - a direction → write the container's `data-msg-high` / `data-msg-low` text into
     `[data-guess-hint]` and un-hide it, and add `is-wrong` to the input. The red "wrong" state applies
     to *any* wrong answer, directional or unparseable, so §5's wrong state and §4's unparseable row are
     the same visual treatment.
   - unparseable (`direction: null`, `correct: false`) → `is-wrong` on the input, hint slot stays hidden.

   Either child appearing inside the already-present `[data-guess-live]` region announces it (§2.7).
   Nothing cascades; no content is revealed.

### 3.1 Verdict logic

```
n = parse_number(guess)
if n is None:           → {"correct": false, "direction": null}
elif abs(n - target) <= tolerance: → {"correct": true,  "direction": null}
elif n > target:        → {"correct": false, "direction": "high"}
else:                   → {"correct": false, "direction": "low"}
```

`parse_number` (`courses/marking.py`) is reused rather than reimplemented: it accepts a single `.`
**or** `,` decimal separator (so Polish `40401,0` works), rejects thousands separators and internal
whitespace, and returns `None` on anything malformed. Tolerance comparison is inclusive (`<=`), so a
guess exactly `tolerance` away from the target is correct.

Direction is measured against `target`, not against the edge of the tolerance band. With a non-zero
tolerance a guess just outside the band reports the direction it lies in, which is what a bisection
search needs.

**The legacy `standardizeDP` `eval()` is deliberately not ported.** The legacy ran `eval()` on student
input (`script.js:14-23`, legacy root per §1.2) as a decimal-separator hack, which silently also let
`2+3` evaluate to `5`. That is an accident of the hack, not a feature; `parse_number` replaces it.

### 3.2 Submit triggers

**Check click or Enter — both the same native `submit` event on the inner form (§2.7). Never blur.**
The sibling precedent (`fillgate.js`, `switchgate.js`) submits only on an explicit Confirm click or form
submit, never on blur, and for good reason: blur-submit stamps a "too big" on a student who merely
tabbed away mid-thought. The legacy widget's blur-submit is not carried over.

The Check button sits **immediately after the input, inline**, so the `201² = [input] [Check]` row still
flows as one line.

The submit handler's required behaviour, in order:

- **`e.preventDefault()` first.** The "no `action`" argument (§2.7) explains only *where* an unhandled
  submit would navigate — not that it doesn't. Without `preventDefault`, every Check click and Enter
  navigates (GET to the current URL) instead of firing the fetch.
- **In-flight guard.** Ignore a submit while one is pending, so two responses cannot race. Without it a
  slow "too big" for guess *n* can land after "correct" for guess *n+1* and clobber the locked success
  state.
- **Post-lock guard.** Once correct, the widget is inert: no further submits, even though a `readonly`
  input still emits events.

**A fresh attempt starts clean.** Typing in the input clears any visible verdict (hint or red tint),
mirroring `switchgate.js`, whose `advance` calls `hideFeedback` for the same reason.

## 4. Error handling

| Situation | Behaviour |
|---|---|
| Unparseable input (`abc`, `1 000`, `1.2.3`) | `{"correct": false, "direction": null}` → input goes red, no directional hint. Matches the legacy, which showed no direction for non-numeric input. |
| Missing or wrong-type `element_pk` | Benign `200 {"correct": false, "direction": null}` (soft lookup). Non-informative, so pks cannot be probed to distinguish element types. |
| No course access | `raise PermissionDenied` → **403**, after the element resolves (the `switchgate_check` shape). Deliberately unlike the benign-200 row above. |
| Network failure / non-200 | `.catch()` leaves the widget editable and shows no verdict — never locks, never falsely passes (fillgate precedent). |
| Unsaved editor preview (`data-element-pk == "0"`) | No-op; the widget renders but does not submit. |
| Empty input | Clears the verdict; no request. |
| Concurrent submits | Suppressed by the in-flight guard (§3.2), so responses cannot apply out of order. |
| JS absent entirely | The **click** path is inert — the Check button is never un-hidden (§2.7). **Enter still submits and reloads the same lesson URL**, because `hidden` does not disqualify the default button from implicit submission; only `preventDefault` suppresses it, and there is no JS to run it. The input carries no `name`, so nothing leaks into the query string. Accepted, and identical to `fillgate`. No lesson content is hidden or lost — no watchdog needed. |
| Over-long / over-precise token | Rejected as a form error at authoring time (§2.3.3), never reaching the DB. |

### 4.1 Check endpoint

`guessnumber_check`, flat route `courses/element/<int:element_pk>/guessnumber-check/`, `@require_POST`
`@login_required`. The name follows the `<form-key>_check` convention every sibling uses
(`fillgate_check`, `switchgate_check`, `switchgrid_check`, `filltable_check`). Persists nothing — no
`QuestionResponse`, no `UnitProgress`.

Uses the **soft pk lookup** (`.filter(pk=...).first()`, benign `200` on a missing or wrong-type pk),
which is the newer convention established by `switchgate_check` and followed by `switchgrid_check` and
`filltable_check` — deliberately **not** `fillgate_check`'s `get_object_or_404`. The course-access gate
runs after the element resolves.

### 4.4 Accepted: the success message is public to the client

Server-rendering the success message (§2.7) ships it to every client at page load, readable via View
Source — and per §1.2 that text may state the answer outright ("Tak, TeraSoft sprzedała o \(100\%\)…").

This is **accepted**, on the same reasoning as the rest of the design: the element is ungraded, nothing
is recorded, and a determined student can extract the target in a handful of guesses anyway — the
directional hint is a binary search by construction. It also matches the Spoiler/reveal-gate family,
which likewise ships revealable content to the client. Server-side *checking* still earns its place by
keeping the target itself out of the DOM.

The cost is real for the game framing, so the edit partial's hint text must warn authors (§9): **the
success message is visible in the page source — do not put anything there that must stay secret.**

## 5. Styling

No view ships unstyled. This element defines real visual states, so they need explicit rules and a
light+dark pass:

- **States:** default; wrong (`is-wrong` on the input, per §4, with `[data-guess-hint]` visible for a
  directional verdict); success (`is-correct` on the input, `readonly`, `guessnumber--done` on the
  container, `[data-guess-success]` visible, and the **Check button `disabled`** so the post-lock
  inertness of §3.2 is visible rather than only behavioural).
- `[data-guess-hint]` and `[data-guess-success]` are the two visible verdict slots. They sit inside the
  always-present `[data-guess-live]` wrapper, which is a plain grouping node with no styling of its own.
- **Inline baseline alignment** is the one genuinely new design problem: the input and Check button sit
  inline against a KaTeX-rendered `\(201^2=\)`, whose baseline is not a plain text baseline. This must
  be decided deliberately, not left to default `vertical-align`.
- Hint and success colours reuse the existing feedback tokens (the same palette the sibling self-checks
  use), so this element does not invent a second vocabulary for "wrong" and "correct".
- **Accessibility.** The verdict is the one thing this element exists to communicate, so a silent
  verdict is a product failure, not a polish item. §2.7 pins the shape: `[data-guess-live]` is a
  permanent wrapper (never `hidden`) whose two children — the hint and the success message — are
  un-hidden in place, so both announce reliably *and* both are visible. The input carries an
  `aria-label` (§9). Colour alone must not carry the wrong state: the red tint always accompanies hint
  text, never replaces it.
- Verify with Playwright screenshots in **both light and dark** before shipping, and run the
  `frontend-design` skill over both the student widget and the authoring form.

## 6. Testing

**Token module / form**
- Round-trip: author `{{40401}}` → `target == Decimal("40401")` → editor re-renders exactly `{{40401}}`
  (not `{{40401.00000000}}`, not `{{4.0401E+4}}`).
- Round-trip boundaries: integer; trailing zeros (`{{40401.50}}`); 8 significant decimals; a value that
  would normalize to an exponent; a **negative** target (`{{-5}}` → `{{-5}}`) and a redundant sign
  (`{{+5}}` → `{{5}}`, §2.6).
- Comma round-trip: `{{40401,5}}` → `target == Decimal("40401.5")` → editor re-renders `{{40401.5}}`
  (canonicalised — §2.6).
- `target` is actually assigned: saving a valid form persists the right `target` (guards the
  `IntegrityError`/`target=None` trap of §2.3.2).
- Editing an existing element populates `initial["stem"]` with the **author** token, not the raw `￿0￿`
  stem (guards §2.3.2a — without `__init__`, `to_author_stem` has no caller at all).
- Exactly-one-token validation: zero tokens → form error; two tokens → form error.
- Non-numeric token contents → form error.
- `|` inside the token → explicit form error, with a message **distinct from** the zero-token error
  (guards §2.3.3's per-code mapping, not just "some error").
- Bounds — the real limit is `max_digits - decimal_places = 12` integer digits: **12 integer digits
  accepted, 13 rejected** as a form error (not a DB `DataError`, not an uncaught `TransferError` —
  guards both halves of §2.3.3); >8 decimal places → form error, not silent rounding.
- `tolerance` accepts `0,5` (Polish comma) and blank tolerance saves as `0` — guards §2.3.2b, i.e. the
  plain-ModelForm trap where the same form accepts `{{40401,5}}` but rejects `0,5`.
- Math masking: a stem whose KaTeX contains braces is not misparsed as a token.
- Sentinel forging: a stem containing a literal `￿0￿` in prose is stripped before parse.
- `tolerance` rejects negatives; `success_message` is sanitised with `sanitize_html` and **retains both
  math and block markup** (guards the `sanitize_cell` collapse of §2.4).

**Endpoint**
- Correct / high / low verdicts.
- Tolerance boundary: `abs(n - target) == tolerance` → **correct** (inclusive).
- Comma decimals: `40401,0` and `40401.0` both correct.
- Unparseable → `correct: false, direction: null`.
- Soft-pk probes: missing pk and wrong-type pk → benign `200`.
- Access gate: a user without course access → **403**.
- `require_POST`; `login_required`.
- **Nothing is persisted** — no `QuestionResponse`, no `UnitProgress` row created.

**Context flags** (each guards a trap this codebase has already fallen into)
- `build_lesson_context(...)["has_guess_number"] is True` for a **top-level** element, for one **nested
  in a tab**, and for one **nested in a two-column column** — the `parent__isnull=True` trap (§2.7).
  The e2e below exercises rendering, not the flag, and would pass even with a wrong query.
- `build_lesson_context(...)["has_math"] is True` for math in the **stem** and, independently, for math
  in the **success_message** — the `_element_has_math` clause (§2.5a). Without this the headline
  `\(201^2=\)` use case renders raw.

**Wiring / authoring** (each guards a step that has historically been missed)
- `manage_element_add` for `guessnumber` returns 200 — covers the
  `element_add` → `_host_form` → `_edit_guessnumber` render path, which row/palette tests do not reach.
  The reveal-gate `_edit_` partial was missed exactly this way (fixed in PR #100).
- `manage_editor` GET asserts the `guessnumber.js` `<script>` tag is present — gallery and reveal-gate
  both shipped with a broken preview because `editor.html` never loaded the enhancer.
- A stem authored as a `<p>`-wrapped paragraph renders with the input **still inside the paragraph** —
  guards §2.7's inline-only splice rule, i.e. the parser-hoisting trap.
- Transfer export/import round-trip, including a Decimal with trailing zeros.
- Transfer: a non-string `stem` (e.g. `42`) raises `TransferError`, **not** a `TypeError` 500 (guards
  §7.1's `check_str`-before-`_check_token_stem` ordering).

**e2e**
- Wrong-high → "too big"; wrong-low → "too small"; correct → success message shown and input locked.
  Assert the state classes (`is-wrong` / `is-correct`, `guessnumber--done`), not just visible text.
- `[data-guess-live]` receives the verdict text on each of the three outcomes (the a11y contract of
  §2.7 — a silent verdict is the failure this element cannot afford).
- Typing after a verdict clears it (§3.2).
- After lock, further interaction submits nothing.
- Enter (not just the Check click) submits.
- **Typing `40401,5` into the real input is accepted** — the one test that would have caught a
  `type="number"` input silently returning `""` for a comma (§2.7). Every other comma test in this spec
  is server- or form-side and would pass regardless.
- Nested inside tabs.

**i18n**
- EN/PL catalogs complete, including every new msgid in §9; catalog tests run (the §8 rename *removes*
  translatable strings, which is exactly the case that has broken catalog tests before).

## 7. Touch-points

Adding an element type means keeping this set in lockstep; a miss in any one of them is a 500 or a
silently broken surface. **Symbol names, not line numbers** — the file positions drift every slice.

- `ELEMENT_MODELS` (`courses/models.py`) **30 → 31**, plus an `alter_element_content_type` migration.
  Next migration number is **0049**.
- `FORMAT_VERSION` (`courses/transfer/schema.py`) **stays 4** — a new element type is not an on-disk
  shape change.
- The `ELEMENT_MODELS` count is asserted in **two** places: `tests/test_transfer_schema.py` **and**
  `tests/test_models_multigrid.py`. Both must go 30 → 31.
- `courses/views.py`: the `_element_has_math` clause (§2.5a), the `has_guess_number` flag in
  `build_lesson_context` (§2.7), and the `guessnumber_check` view (§4.1).
- `courses/urls.py`: the flat check route.
- `courses/guessnumber.py`: new token module (§2.3.1).
- `courses/fillblank.py`: promote `_mask_math`/`_restore_math` to public `mask_math`/`restore_math`
  (§2.3.1) — a cross-module import, so the rename is required, not optional.
- `courses/templatetags/courses_extras.py`: the new `render_guess_number` tag (§2.7).
- `templates/courses/lesson_unit.html`: the `has_guess_number`-gated `<script src="…guessnumber.js"
  defer>` tag. **No prepaint watchdog block** — unlike the gates (§2.7). This is the exact class of
  silent-breakage miss this list exists to catch; every sibling has one here.
- `FORM_FOR_TYPE` (`courses/element_forms.py`) + `GuessNumberElementForm` (§2.3.2).
- **`save_element` (`courses/builder.py`) needs no branch** — the form is a `ModelForm`, so it rides the
  generic `else`, as `FillGateElementForm` does.
- **New files** (mandated by §2.7, listed here because §7 is the checklist an implementer works from):
  `templates/courses/elements/guessnumberelement.html`,
  `templates/courses/manage/editor/_edit_guessnumber.html`,
  `courses/static/courses/js/guessnumber.js`.
- `templates/courses/manage/editor/_add_menu.html` palette card, plus the icon sprite at
  `templates/courses/manage/_icon_sprite.html` (where `#el-switchgate` lives); the
  `element_add`/`element_save` allow-tuples and `_EDITOR_TYPE_LABELS` (`courses/views_manage.py`);
  `_ELEMENT_LABELS` (`courses/templatetags/courses_manage_extras.py`).
- **`element_summary` needs no branch.** It already ends in a generic fallback that picks up any element
  with a `stem` and rewrites `￿N￿` tokens to `___` — which is how `FillGateElement` and
  `SwitchGateElement` get their summaries with no per-class code. `GuessNumberElement` has a `stem`, so
  it inherits the right behaviour for free.
- Transfer trio: `SERIALIZERS` (`courses/transfer/export.py`), `VALIDATORS`
  (`courses/transfer/payloads.py`), `BUILDERS` (`courses/transfer/importer.py`) — payload in §7.1.
- `NESTABLE_TYPE_KEYS` (`courses/builder.py`) holds **transfer** keys → add `guess_number`. Also add
  `"guessnumber": "guess_number"` to the module-level `_NESTABLE_FORM_KEY_ALIASES` dict in the same
  file, which `resolve_scope` consults before the `NESTABLE_TYPE_KEYS` membership check.
- `math.js` selector (§2.5b); the stylesheet (§5).
- JS enhancer wired into **both** `editor.js` (re-run `window.libliInitGuessNumbers(preview)` after each
  fragment swap, next to the gallery/tabs re-inits) **and** `editor.html` (the `<script defer>` tag).
- i18n EN/PL (§9).

**Naming:** model `GuessNumberElement`; `ELEMENT_MODELS` entry `guessnumberelement`; form key
`guessnumber`; transfer key `guess_number`; endpoint `guessnumber_check`; JS `guessnumber.js`; templates
`courses/elements/guessnumberelement.html` and `courses/manage/editor/_edit_guessnumber.html`. Transfer
keys are snake_case and differ from form keys — that divergence is the established convention, not an
inconsistency to fix.

### 7.1 Transfer payload

`Decimal` is **not** JSON-serializable (`json.dumps(Decimal(...))` raises `TypeError`), so decimals
travel as strings — the settled convention `_ser_numeric` / `_val_short_numeric` / `_build_numeric`
already use for `ShortNumericQuestionElement`.

```json
{
  "stem": "<token-stem string, sentinel form>",
  "target": "40401.00000000",
  "tolerance": "0E-8",
  "success_message": "<sanitised html>"
}
```

Those example values are what `str()` **actually** produces from a persisted row: a
`DecimalField(decimal_places=8)` round-trips as `Decimal('40401.00000000')`, and a zero tolerance as
`Decimal('0E-8')`. The archive form is deliberately **not** the author-facing form — do not "fix" this
by applying `format_target` (§2.6) on export, which would diverge from `_ser_numeric`.

- **Export:** `str(el.target)` / `str(el.tolerance)`.
- **Validate**, in this order:
  1. `_exact_keys(data, ["stem", "target", "tolerance", "success_message"], _("guess_number data"))` —
     the opening move of every *question* validator, `_val_short_numeric` included. (Not of every
     sibling: `_val_fill_gate` and `_val_switch_gate` skip key-presence entirely and read
     `data.get("stem", "")` directly — the weaker pattern this spec deliberately does not follow.)
     Without it a payload missing `success_message` `KeyError`s into a 500 instead of a `TransferError`,
     and unknown keys pass silently.
  2. **`check_str(data["stem"], _("stem"))` — before any token work.** `_exact_keys` checks key presence
     only, never types, and `_check_token_stem` immediately runs `_TOKEN_RE.finditer(stem)`, which
     raises `TypeError` (a 500) on `{"stem": 42}`. Every existing caller type-checks first — both
     `_val_fill_gate` and `_val_switch_gate` open with an `isinstance(stem, str)` check, and the
     fill-blank validators reach `_check_token_stem` only after `_check_question_fields`, whose first
     line is `check_str(data["stem"], _("stem"))`. Dropping `_val_switch_gate`'s *token* pattern (below)
     must not also drop its type guard.
  3. `_check_token_stem(data["stem"], 1, elid)` (`courses/transfer/payloads.py`), which does both halves
     — exact `0..n-1` token match **and** the stray-sentinel check. Do not model this on
     `_val_switch_gate`'s `stem.count(SENTINEL_TOKEN) != 1`, the weaker pattern (no stray check).
  4. `check_decimal_str(data["target"], "target", 20, 8)` and the same for `tolerance`; a non-negative
     `tolerance` check; `check_str` on `success_message`.
- **Build:** rehydrate with `Decimal(data["target"])`, and **`stem=sanitize_html(data["stem"])`**.
  Sanitising on import is required for symmetry, not paranoia: §2.1 deliberately keeps `stem` out of the
  model's `save()`, so a builder that passed the archive's stem through verbatim would store it unchecked
  and `render_stem` would then `mark_safe` it — while `success_message` *is* sanitised, silently, because
  `save()` handles it. `_check_token_stem`'s stray-sentinel check guards token forging, not markup.
  A bare `sanitize_html` over the whole stem is safe here because **nh3 preserves the U+FFFF sentinel**,
  so the token survives the clean. Note this is deliberately *not* `_build_switch_grid`'s shape: that one
  calls `switchgrid.sanitize_stem_segments`, which splits on `_TOKEN_RE` and cleans each segment with
  `sanitize_cell`, because switch-grid's segments are cell-flavoured. This element's stem is a
  `sanitize_html` field (§2.4), so it cleans whole. (`_build_fill_gate`/`_build_switch_gate` sanitise
  nothing, which is the gap this element declines to inherit.)

## 8. Bundled scope — rename the Two-column label to "Columns"

User-requested, and to ship in this same PR. **Label-only.** The model, form, and transfer keys stay
`twocolumnelement` / `twocolumn` / `two_column`; no migration, no `FORMAT_VERSION` bump.

It is a genuine correctness fix rather than a preference: the element already supports **2–4** columns,
so "Two columns" is a misnomer.

### 8.1 `msgid "Columns"` already exists — this merges into it rather than minting it

It lives in both catalogs today (PL already translated "Kolumny") and is currently the **column-count
field label**. Two consequences:

1. **No new PL translation is needed** for "Columns".
2. **The editor would show the word twice in a row** — heading "Columns" (`_EDITOR_TYPE_LABELS`) with
   the field label "Columns" directly beneath it. §8.2 resolves this.

### 8.2 Change sites

- `courses/templatetags/courses_manage_extras.py` — `_("Two columns")` → `_("Columns")`
- `courses/views_manage.py` — `_EDITOR_TYPE_LABELS["twocolumn"]`, `gettext_lazy("Two-column layout")` →
  `gettext_lazy("Columns")`
- `templates/courses/manage/editor/_add_menu.html` — `{% trans "Two-column layout" %}` →
  `{% trans "Columns" %}`
- **`templates/courses/manage/editor/_edit_twocolumn.html`** — `{% trans "Columns" %}` →
  `{% trans "Number of columns" %}`. **This site is the one that actually fixes the doubling.** The
  template hardcodes the label text and renders `{{ form.column_count }}` bare, so
  `TwoColumnElementForm`'s `label=_("Columns")` is **never rendered** — changing only the form's `label=`
  would produce no visual change at all.
- `courses/element_forms.py` — `TwoColumnElementForm.column_count`'s `label=_("Columns")` →
  `_("Number of columns")`, in lockstep, only to keep the msgid set clean (it is dead in this template).

Catalogs: `"Two columns"` ("Dwie kolumny") and `"Two-column layout"` ("Układ dwukolumnowy") both become
unreferenced and drop out; `"Columns"` stays (now with different referents); `"Number of columns"` is
added (§9).

No test currently asserts either renamed label (verified). Module-level translatable dicts must keep
using `gettext_lazy` — eager `gettext` froze labels to English once already (PR #46). Watch the
`makemessages` fuzzy-flag gotcha when the msgids shift.

## 9. New translatable strings

Text is specified here so it is a product decision, not an implementer's guess. This table is
**exhaustive** — every string the spec mandates appears in it, including the form errors.

**New msgids:**

| msgid (EN) | PL | Used by |
|---|---|---|
| `Guess the number` | `Zgadnij liczbę` | palette card, `_EDITOR_TYPE_LABELS`, `_ELEMENT_LABELS` |
| `Check` | `Sprawdź` | `[data-guess-check]` (§2.7) |
| `Correct!` | `Dobrze!` | blank-`success_message` fallback, emitted **escaped** by `render_guess_number` into `[data-guess-success]` (§2.4). Its only consumer — there is no `data-msg-correct`, because the success slot always has server-rendered content (§2.7). |
| `The number is too big, try again.` | `Liczba jest za duża, spróbuj ponownie.` | `data-msg-high` on the `.guessnumber` container (§2.7); JS copies it into `[data-guess-hint]` |
| `The number is too small, try again.` | `Liczba jest za mała, spróbuj ponownie.` | `data-msg-low` on the `.guessnumber` container (§2.7); JS copies it into `[data-guess-hint]` |
| `Write the answer in double braces, e.g. {{42}}.` | `Wpisz odpowiedź w podwójnym nawiasie klamrowym, np. {{42}}.` | check 1 — `code="token_count"` (§2.3.3) |
| `Use exactly one answer in braces — alternatives separated by "\|" are not supported here.` | `Użyj dokładnie jednej odpowiedzi w nawiasie — alternatywy oddzielone znakiem „\|” nie są tu obsługiwane.` | check 2 — `code="alternatives"` |
| `The answer must be a number (e.g. 42 or 3,14).` | `Odpowiedź musi być liczbą (np. 42 lub 3,14).` | check 3 |
| `The answer has too many digits (at most 12 before and 8 after the decimal point).` | `Odpowiedź ma za dużo cyfr (najwyżej 12 przed przecinkiem i 8 po).` | check 4 — replaces the transfer-flavoured helper text (§2.3.3) |
| `Prompt with the answer` | `Treść z odpowiedzią` | `_edit_guessnumber.html` stem field label |
| `Mark the answer with {{42}} (exactly once).` | `Zaznacz odpowiedź jako {{42}} (dokładnie raz).` | `_edit_guessnumber.html` stem hint — the token *is* the whole authoring interface (§2.2), so the syntax must be discoverable without triggering an error first. Mirrors `_edit_switchgate.html`'s "Mark the choice position with {{choice}} (exactly once)." and `_edit_fillgate.html`'s equivalent. |
| `Tolerance (±, optional)` | `Tolerancja (±, opcjonalnie)` | `_edit_guessnumber.html` field label |
| `Success message` | `Komunikat po poprawnej odpowiedzi` | `_edit_guessnumber.html` field label |
| `Your answer` | `Twoja odpowiedź` | `aria-label` on `[data-guess-input]` (§2.7). Without it the input is spliced inline into `201² = [input]` with no programmatic association to any prose, so a screen reader announces a bare "edit blank" — a WCAG 4.1.2 failure. |
| `The success message is visible in the page source — do not put anything secret here.` | `Komunikat o sukcesie jest widoczny w źródle strony — nie umieszczaj tu nic tajnego.` | edit-partial hint (§4.4) |
| `guess_number data` | `dane guess_number` | `_exact_keys` label (§7.1); sibling `short_numeric data` is a real msgid |
| `Number of columns` | `Liczba kolumn` | §8.2 |

**Reused, already in the catalogs — do not mint duplicates:**

| msgid | Where it comes from |
|---|---|
| `Enter a number (e.g. 3.14 or 3,14).` | `ShortNumericQuestionElementForm._num` — reused by `clean_tolerance` (§2.3.2) |
| `Tolerance cannot be negative.` | `ShortNumericQuestionElementForm.clean_tolerance` — same |
| `Columns` | already exists (PL "Kolumny"); §8 merges into it |
| `stem` | existing transfer label, reused by §7.1's `check_str` |

The legacy carries two Polish variants of each hint — `_template.html`'s "Liczba jest za duża, spróbuj
ponownie." and `140_liczby_r_zast.html`'s "To za dużo, spróbuj ponownie.". The fuller `_template.html`
wording is chosen, since §1.4 makes this a single fixed default rather than per-instance text.
