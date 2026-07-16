# Guess the number — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `GuessNumberElement` — an ungraded numeric self-check with "too big"/"too small" directional feedback — as the 31st unit element, and rename the Two-column element's label to "Columns".

**Architecture:** A plain `ElementBase` subclass (NOT a `QuestionElement`: it records no marks, because the element is built around repeated wrong guesses). Authors write one stem containing a single `{{42}}` token; a new `courses/guessnumber.py` module (modelled on `courses/switchgate.py`) parses it into a `<SENTINEL>0<SENTINEL>` token-stem plus a `target` Decimal. A `render_guess_number` template tag splices an inline input + Check button into the stem. A flat, soft-pk JSON endpoint compares the guess with `parse_number` and returns a verdict; nothing is persisted.

**Tech Stack:** Django, Postgres, nh3 (sanitize), KaTeX, vanilla JS, pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-07-16-guess-the-number-design.md` — authoritative, passed 8 review rounds. **Do not redesign.** Where this plan says "per §N", read that spec section; it carries reasoning this plan does not repeat.

## Global Constraints

- **Tooling:** `ruff` / `pytest` / `python` are NOT on PATH. Always `uv run <cmd>`.
- **Test DB isolation (mandatory):** concurrent worktrees collide on Postgres `test_libli`. Prefix every test command with `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_gn`.
- **e2e:** run focused, in the **foreground** only. Never background `-m e2e` (runaway browsers).
- **Naming (fixed, do not vary):** model `GuessNumberElement`; `ELEMENT_MODELS` entry `guessnumberelement`; form key `guessnumber`; transfer key `guess_number`; endpoint `guessnumber_check`; route `courses/element/<int:element_pk>/guessnumber-check/`; JS `guessnumber.js`; container class `.guessnumber`.
- **`FORMAT_VERSION` stays 4.** A new element type is not an on-disk shape change.
- **Migration number:** `0049` (latest is `0048_markdoneelement…`).
- **i18n:** module-level translatable dicts MUST use `gettext_lazy` (eager `gettext` froze labels to English once — PR #46).
- **Do NOT mint these msgids — they already exist:** `Check` (PL `Sprawdź`), `Tolerance (±, optional)` (PL `Tolerancja (±, opcjonalnie)`), `Columns` (PL `Kolumny`), `Enter a number (e.g. 3.14 or 3,14).`, `Tolerance cannot be negative.`, `Element '%(el)s': tolerance must not be negative.`, `stem`. A duplicate `msgid` makes `msgfmt` reject the catalog.
- **Every commit must leave the suite green.** Task order below is dependency-ordered for exactly this reason.
- **NEVER type the sentinel character literally — in code, tests, or this plan.** The sentinel is
  `U+FFFF`, and the file-writing tools silently corrupt it to `U+FFFC` (object-replacement). This plan
  writes it as the placeholder `<SENTINEL>` throughout. Two different substitutions, by context:
  - **In executable code:** emit `fillblank.SENTINEL` / `guessnumber.SENTINEL_TOKEN`. Never a literal.
  - **In docstrings and comments:** `fillblank.SENTINEL` would read as literal prose, so write the
    codepoint by name instead — `U+FFFF` or `\uffff` (e.g. "stored as the U+FFFF-delimited token").
    The sibling docstrings use the raw character; do not copy that here.
  Never paste the `<SENTINEL>` placeholder itself into a file. A test
  asserting against a literal sentinel therefore compares the *wrong character* and fails in a way that
  looks like a logic bug. This plan was written with 13 such corruptions and they were stripped; do not
  reintroduce them. Always reference it in code:
  - `fillblank.SENTINEL` — the bare character
  - `guessnumber.SENTINEL_TOKEN` — the full `<S>0<S>` token
  - For a *stray* sentinel (the transfer stray-check test), it must NOT match `_TOKEN_RE`
    (sentinel + digits + sentinel) or you hit the token-count branch instead of the stray branch:
    `STRAY_SENTINEL = fillblank.SENTINEL + "x"`
  To check a file for corruption, grep it for the object-replacement character
  (`python -c "import io,sys; print(io.open(sys.argv[1],encoding='utf-8').read().count(chr(0xFFFC)))" <file>`)
  — expect `0`. Note this plan itself is expected to contain **zero** such characters; the only
  mentions of the corrupted codepoint anywhere in it are by escape (`chr(0xFFFC)`), never literal.

**Ordering constraints (do not reorder):**
- Task 5 registers the `guessnumber_check` **route** (not the view) because `render_guess_number`
  reverses that URL name — without it every Task 5 test raises `NoReverseMatch`. Task 6 then adds the
  view behind it. A `path()` pointing at a not-yet-defined view would break URL loading, so Task 5
  registers it against a temporary stub that Task 6 replaces (see Task 5, Step 3b).
- Task 10 (transfer `SERIALIZERS`) must precede Task 11 (`NESTABLE_TYPE_KEYS`) — `tests/test_filltable_transfer.py` asserts the invariant `NESTABLE_TYPE_KEYS <= set(SERIALIZERS)`.
- Task 3 flips `len(ELEMENT_MODELS)` 30→31 and must fix **both** count asserts in the same commit.

---

## File Structure

**New files**
| Path | Responsibility |
|---|---|
| `courses/guessnumber.py` | Token-stem parse/render/format helpers. Pure, no DB. |
| `courses/migrations/0049_*.py` | `CreateModel` + an `AlterField` on `Element.content_type`. Django derives the filename from the operations (cf. 0047_twocolumnelement_alter_element_content_type), so use the glob rather than hardcoding a name. |
| `templates/courses/elements/guessnumberelement.html` | One-liner: delegates to the render tag. |
| `templates/courses/manage/editor/_edit_guessnumber.html` | Authoring form partial. |
| `courses/static/courses/js/guessnumber.js` | Submit handling, verdict application. |
| `tests/test_guessnumber_module.py` | Task 2 unit tests. |
| `tests/test_guessnumber_model.py` | Task 3 model tests. |
| `tests/test_guessnumber_form.py` | Task 4 form tests. |
| `tests/test_guessnumber_render.py` | Task 5 render-tag tests. |
| `tests/test_guessnumber_endpoint.py` | Task 6 endpoint tests. |
| `tests/test_guessnumber_context.py` | Task 7 flag tests. |
| `tests/test_guessnumber_authoring.py` | Task 9 editor-surface tests. |
| `tests/test_guessnumber_transfer.py` | Task 10/11 transfer tests. |
| `tests/test_e2e_guessnumber.py` | Task 15 e2e. |

**Modified files**
| Path | Change |
|---|---|
| `courses/fillblank.py` | Promote `_mask_math`/`_restore_math` → public. |
| `courses/models.py` | `GuessNumberElement`; `ELEMENT_MODELS` 30→31. |
| `courses/element_forms.py` | `GuessNumberElementForm`, `_GUESS_STEM_ERRORS`, `FORM_FOR_TYPE`. |
| `courses/templatetags/courses_extras.py` | `render_guess_number` tag. |
| `courses/views.py` | `guessnumber_check`; `_element_has_math` clause; `has_guess_number`. |
| `courses/urls.py` | Flat check route. |
| `courses/views_manage.py` | `_EDITOR_TYPE_LABELS`; `element_add`/`element_save` tuples. |
| `courses/templatetags/courses_manage_extras.py` | `_ELEMENT_LABELS`; **§8** rename. |
| `courses/builder.py` | `NESTABLE_TYPE_KEYS`, `_NESTABLE_FORM_KEY_ALIASES`. |
| `courses/transfer/{export,payloads,importer}.py` | Serializer / validator / builder. |
| `courses/static/courses/js/{math,editor}.js` | `.guessnumber` selector; preview re-init. |
| `templates/courses/{lesson_unit.html,manage/editor/editor.html}` | `<script>` tags. |
| `templates/courses/manage/editor/{_add_menu,_edit_twocolumn}.html`, `manage/_icon_sprite.html` | Palette card, sprite, **§8** rename. |
| `courses/static/courses/css/…` | `.guessnumber` styles (light+dark). |
| `tests/test_transfer_schema.py`, `tests/test_models_multigrid.py` | Count asserts 30→31. |
| `locale/{en,pl}/LC_MESSAGES/django.po` | New msgids (§9). |

---

### Task 1: Promote `fillblank`'s math-masking helpers to public

`courses/guessnumber.py` (Task 2) must mask math before token scanning, so it needs these across a module boundary. They are currently private and used nowhere else, so this is a pure rename (spec §2.3.1).

**Files:**
- Modify: `courses/fillblank.py`
- Test: `tests/test_questions_2b_fillblank_parse.py`, `tests/test_questions_2b_forms.py` (existing — must stay green)

- [ ] **Step 1: Rename both helpers and all call sites**

In `courses/fillblank.py`, rename `_mask_math` → `mask_math` and `_restore_math` → `restore_math`, updating every internal call site (`parse`, and any other reference).

- [ ] **Step 2: Verify nothing else referenced the private names**

```bash
grep -rn "_mask_math\|_restore_math" courses/ tests/
```
Expected: no output (all references renamed).

- [ ] **Step 3: Run the existing fill-blank suite**

```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_gn uv run pytest tests/test_questions_2b_fillblank_parse.py tests/test_questions_2b_forms.py -q
```
Expected: PASS — this is a rename, behaviour is unchanged.

- [ ] **Step 4: Commit**

```bash
git add courses/fillblank.py
git commit -m "refactor(fillblank): promote mask_math/restore_math to public

courses/guessnumber.py needs them across a module boundary; duplicating the
math-masking regex instead would be the bug they exist to prevent."
```

---

### Task 2: `courses/guessnumber.py` — the token module

Pure functions, no DB. Owns checks 1–2 of spec §2.3.3.

**Files:**
- Create: `courses/guessnumber.py`
- Create: `tests/test_guessnumber_module.py`

**Interfaces:**
- Consumes: `fillblank.SENTINEL`, `fillblank.strip_sentinel`, `fillblank.mask_math`, `fillblank.restore_math` (Task 1), `switchgate.render_stem`.
- Produces: `SENTINEL_TOKEN`, `GuessNumberError(code)`, `parse_stem(clean) -> (token_stem, raw_target_str)`, `to_author_stem(token_stem, target) -> str`, `format_target(target) -> str`, `render_stem` (re-exported from `switchgate`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_guessnumber_module.py`:

```python
from decimal import Decimal

import pytest

from courses import fillblank
from courses import guessnumber
from courses.guessnumber import GuessNumberError


def test_parse_stem_extracts_target_and_tokenises():
    token_stem, raw = guessnumber.parse_stem(r"\(201^2=\){{40401}}")
    assert raw == "40401"
    assert token_stem == r"\(201^2=\)" + guessnumber.SENTINEL_TOKEN


def test_parse_stem_rejects_zero_tokens():
    with pytest.raises(GuessNumberError) as e:
        guessnumber.parse_stem("no token here")
    assert e.value.code == "token_count"


def test_parse_stem_rejects_two_tokens():
    with pytest.raises(GuessNumberError) as e:
        guessnumber.parse_stem("{{1}} and {{2}}")
    assert e.value.code == "token_count"


def test_parse_stem_rejects_alternatives_pipe():
    with pytest.raises(GuessNumberError) as e:
        guessnumber.parse_stem("{{40401|40402}}")
    assert e.value.code == "alternatives"


def test_parse_stem_masks_math_so_katex_braces_are_not_tokens():
    # \text{{x}} must NOT be read as a token; the real token is {{5}}.
    token_stem, raw = guessnumber.parse_stem(r"\(\text{{x}}\){{5}}")
    assert raw == "5"
    assert token_stem.count(guessnumber.SENTINEL_TOKEN) == 1


def test_error_code_is_positional_not_kwarg():
    # ValueError accepts no kwargs; the code must be a positional param.
    assert GuessNumberError("token_count").code == "token_count"


@pytest.mark.parametrize(
    "stored,expected",
    [
        (Decimal("40401.00000000"), "40401"),   # trailing zeros dropped
        (Decimal("40401.50000000"), "40401.5"),
        (Decimal("0.00000000"), "0"),
        (Decimal("40401"), "40401"),            # would normalize to 4.0401E+4
        (Decimal("-5"), "-5"),                  # sign preserved
        (Decimal("0.12345678"), "0.12345678"),  # 8 dp survive
    ],
)
def test_format_target_is_fixed_point_never_exponent(stored, expected):
    assert guessnumber.format_target(stored) == expected


def test_to_author_stem_round_trips_the_token():
    token_stem, _ = guessnumber.parse_stem(r"\(201^2=\){{40401}}")
    assert guessnumber.to_author_stem(token_stem, Decimal("40401.00000000")) == (
        r"\(201^2=\){{40401}}"
    )


def test_sentinel_token_matches_fillblanks_sentinel():
    assert guessnumber.SENTINEL_TOKEN == fillblank.SENTINEL + "0" + fillblank.SENTINEL
```

- [ ] **Step 2: Run to verify they fail**

```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_gn uv run pytest tests/test_guessnumber_module.py -q
```
Expected: FAIL — `ModuleNotFoundError: No module named 'courses.guessnumber'`.

- [ ] **Step 3: Write the module**

Create `courses/guessnumber.py`:

```python
"""Single-token stem helper for the Guess-the-number element.

The stem carries exactly one placeholder marking where the numeric input renders.
Authors type ``{{42}}``; it is stored as the <SENTINEL>0<SENTINEL> sentinel token (reusing
courses.fillblank.SENTINEL) and the target is lifted out into its own field.
Unlike switchgate's fixed {{choice}} marker, this token carries a payload; unlike
fillblank, it never splits on '|' into alternatives. See the design doc §2.3.
"""

import re
from decimal import Decimal

from courses import fillblank
from courses.switchgate import render_stem  # noqa: F401 — re-exported; see below

SENTINEL_TOKEN = fillblank.SENTINEL + "0" + fillblank.SENTINEL
_MARKER_RE = re.compile(r"\{\{(.*?)\}\}")


class GuessNumberError(ValueError):
    """Carries a `code` so clean_stem maps each check to its own message (§2.3.3).

    ValueError accepts no keyword arguments, so the code is positional:
    GuessNumberError(code="x") would TypeError."""

    def __init__(self, code, *args):
        self.code = code
        super().__init__(code, *args)


def parse_stem(clean):
    """-> (token_stem, raw_target_str). Math is masked before token scanning.

    Owns checks 1-2 of §2.3.3, each with its own code:
      - not exactly one {{...}} token -> GuessNumberError("token_count")
      - a literal '|' inside the token -> GuessNumberError("alternatives")
    Checks 3-4 (numeric parse, digit bounds) belong to clean_stem, not here.
    """
    masked, spans = fillblank.mask_math(clean or "")
    found = _MARKER_RE.findall(masked)
    if len(found) != 1:
        raise GuessNumberError("token_count")
    if "|" in found[0]:
        raise GuessNumberError("alternatives")
    token_stem = fillblank.restore_math(_MARKER_RE.sub(SENTINEL_TOKEN, masked), spans)
    # NOTE: unlike fillblank.parse, a dangling "{{" left after substitution is
    # NOT an error here — it stays literal stem prose. fillblank raises
    # "unterminated marker" because a lost blank silently drops a question; this
    # element has exactly one token, and if it were the dangling one, check 1
    # already fired. Deliberate, not an oversight.
    return token_stem, found[0].strip()


def format_target(target):
    """Canonical author-facing text for a stored Decimal (§2.6).

    normalize() alone yields Decimal('4.0401E+4') for 40401, which parse_number
    then REJECTS — making the element uneditable. format(..., "f") strips the
    exponent, so 40401.00000000 -> "40401" and 40401.50000000 -> "40401.5".
    """
    return format(Decimal(target).normalize(), "f")


def to_author_stem(token_stem, target):
    """Inverse of parse_stem, for populating the edit form."""
    return (token_stem or "").replace(SENTINEL_TOKEN, "{{" + format_target(target) + "}}")
```

Note `render_stem` is **imported from `switchgate`, not reimplemented** — `SENTINEL_TOKEN` is byte-identical in both modules, so a copy would be pure duplication (§2.3.1).

- [ ] **Step 4: Run to verify they pass**

```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_gn uv run pytest tests/test_guessnumber_module.py -q
```
Expected: PASS (all tests).

- [ ] **Step 5: Lint**

```bash
uv run ruff check courses/guessnumber.py && uv run ruff format --check courses/guessnumber.py
```
Expected: no findings.

- [ ] **Step 6: Commit**

```bash
git add courses/guessnumber.py tests/test_guessnumber_module.py
git commit -m "feat(guessnumber): token-stem module (parse/format/round-trip)

Single {{42}} token -> (token_stem, target). format_target uses
format(normalize(), 'f') because str(normalize()) yields 4.0401E+4, which
parse_number rejects — the element would become uneditable on re-edit."
```

---

### Task 3: Model + migration + `ELEMENT_MODELS` 30→31

**Files:**
- Modify: `courses/models.py`
- Create: `courses/migrations/0049_*.py` (generated — Django names it from the operations)
- Create: `tests/test_guessnumber_model.py`
- Modify: `tests/test_transfer_schema.py`, `tests/test_models_multigrid.py`

**Interfaces:**
- Produces: `GuessNumberElement(stem, target, tolerance, success_message, elements)`, `.render(**_kwargs) -> str`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_guessnumber_model.py`:

```python
from decimal import Decimal

import pytest

from courses.models import ELEMENT_MODELS
from courses.models import GuessNumberElement


def test_guessnumber_in_element_models():
    assert "guessnumberelement" in ELEMENT_MODELS
    assert len(ELEMENT_MODELS) == 31


@pytest.mark.django_db
def test_defaults_tolerance_zero_and_blank_success_message():
    el = GuessNumberElement.objects.create(stem="x", target=Decimal("42"))
    assert el.tolerance == Decimal("0")
    assert el.success_message == ""


@pytest.mark.django_db
def test_success_message_is_sanitised_on_save_and_keeps_math_and_blocks():
    el = GuessNumberElement.objects.create(
        stem="x",
        target=Decimal("42"),
        success_message='<p>Tak, o \\(100\\%\\)</p><script>alert(1)</script>',
    )
    el.refresh_from_db()
    assert "<script>" not in el.success_message
    assert "<p>" in el.success_message           # sanitize_html keeps blocks
    assert "\\(100\\%\\)" in el.success_message  # ...and math


@pytest.mark.django_db
def test_stem_is_NOT_sanitised_on_save():
    # Sanitisation is a form-side ordered pipeline (§2.3.2); save() must not
    # re-run nh3 over an already-tokenised stem.
    raw = "<p>keep me</p>"
    el = GuessNumberElement.objects.create(stem=raw, target=Decimal("42"))
    el.refresh_from_db()
    assert el.stem == raw
```

- [ ] **Step 2: Run to verify it fails**

```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_gn uv run pytest tests/test_guessnumber_model.py -q
```
Expected: FAIL — `ImportError: cannot import name 'GuessNumberElement'`.

- [ ] **Step 3: Add the model**

In `courses/models.py`, append `"guessnumberelement"` to `ELEMENT_MODELS`, and add the model next to `SwitchGateElement`:

```python
class GuessNumberElement(ElementBase):
    """A numeric self-check with directional feedback: a wrong guess is told
    'too big' or 'too small' and can be retried without limit. Records no marks
    and reveals nothing (NOT a reveal gate) — it exists to be got wrong
    repeatedly, which is why it is not a QuestionElement. `stem` holds the <SENTINEL>0<SENTINEL>
    single-token stem (the input position); `target` is lifted out of the token
    by the form. See the design doc."""

    stem = models.TextField(blank=True)
    target = models.DecimalField(max_digits=20, decimal_places=8)
    tolerance = models.DecimalField(
        max_digits=20, decimal_places=8, default=0, validators=[MinValueValidator(0)]
    )
    success_message = models.TextField(blank=True)
    elements = GenericRelation(Element)  # cascade: deleting this removes its join-row

    def save(self, *args, **kwargs):
        # success_message only: `stem` is sanitised form-side, in order
        # (sanitize_html -> strip_sentinel -> parse), so save() must not touch it.
        self.success_message = sanitize_html(self.success_message or "")
        super().save(*args, **kwargs)

    def render(self, **_kwargs):
        from django.template.loader import render_to_string

        join = self.elements.order_by("pk").first()
        return render_to_string(
            "courses/elements/guessnumberelement.html",
            {"el": self, "eid": join.pk if join else 0},
        )
```

- [ ] **Step 4: Generate the migration**

```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_gn uv run python manage.py makemigrations courses
```
Expected: creates `courses/migrations/0049_guessnumberelement…py` containing `CreateModel` **and** an `AlterField` on `Element.content_type` (the `limit_choices_to` change). Verify both are present.

- [ ] **Step 5: Fix both count asserts**

`tests/test_transfer_schema.py`: change `assert len(ELEMENT_MODELS) == 30` → `31`, add `"guessnumberelement"` to the membership tuple, and **rename the test function** `test_element_models_lists_all_30_concrete_element_models` → `test_element_models_lists_all_31_concrete_element_models` (the count is in the name).

`tests/test_models_multigrid.py`: change `assert len(ELEMENT_MODELS) == 30` → `31`.

- [ ] **Step 6: Run the affected tests**

```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_gn uv run pytest tests/test_guessnumber_model.py tests/test_transfer_schema.py tests/test_models_multigrid.py -q
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add courses/models.py courses/migrations/0049_*.py tests/test_guessnumber_model.py tests/test_transfer_schema.py tests/test_models_multigrid.py
git commit -m "feat(guessnumber): GuessNumberElement model + migration 0049

ELEMENT_MODELS 30 -> 31 (both hardcoded count asserts updated). Ungraded
ElementBase subclass, not a QuestionElement: every wrong guess would otherwise
write a QuestionResponse into analytics."
```

---

### Task 4: `GuessNumberElementForm` — three parts

Spec §2.3.2 / §2.3.3. All three parts are load-bearing; omitting `__init__` leaves `to_author_stem` with no caller, and omitting the `target` assignment writes `target=None` → `IntegrityError`.

**The third part is `_post_clean`, not `save()`** — a deliberate divergence from `FillGateElementForm`, which assigns its parsed value in a `save()` override. That pattern only works when the caller runs `is_valid()` first (as `builder.save_element` does) and inserts NULL when it doesn't; see the comment in the snippet below.

**Files:**
- Modify: `courses/element_forms.py`
- Create: `tests/test_guessnumber_form.py`

**Interfaces:**
- Consumes: `guessnumber.parse_stem`, `guessnumber.to_author_stem`, `guessnumber.format_target`, `marking.parse_number`, `transfer.schema.check_decimal_str`, `transfer.schema.TransferError`.
- Produces: `GuessNumberElementForm`; `FORM_FOR_TYPE["guessnumber"]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_guessnumber_form.py`:

```python
from decimal import Decimal

import pytest

from courses import guessnumber
from courses.element_forms import GuessNumberElementForm
from courses.models import GuessNumberElement


def _data(stem=r"\(201^2=\){{40401}}", tolerance="", success_message=""):
    return {"stem": stem, "tolerance": tolerance, "success_message": success_message}


@pytest.mark.django_db
def test_valid_form_assigns_target_from_the_token():
    form = GuessNumberElementForm(_data())
    assert form.is_valid(), form.errors
    el = form.save()
    assert el.target == Decimal("40401")
    assert el.stem.count(guessnumber.SENTINEL_TOKEN) == 1


@pytest.mark.django_db
def test_blank_tolerance_saves_as_zero():
    form = GuessNumberElementForm(_data(tolerance=""))
    assert form.is_valid(), form.errors
    assert form.save().tolerance == Decimal("0")


@pytest.mark.django_db
def test_polish_comma_tolerance_is_accepted():
    # The same form accepts {{40401,5}} in the token; rejecting "0,5" here
    # would be incoherent. Plain ModelForm over a DecimalField does reject it.
    form = GuessNumberElementForm(_data(tolerance="0,5"))
    assert form.is_valid(), form.errors
    assert form.save().tolerance == Decimal("0.5")


@pytest.mark.django_db
def test_negative_tolerance_rejected():
    form = GuessNumberElementForm(_data(tolerance="-1"))
    assert not form.is_valid()
    assert "tolerance" in form.errors


@pytest.mark.django_db
def test_comma_token_parses_and_canonicalises_on_re_edit():
    form = GuessNumberElementForm(_data(stem="{{40401,5}}"))
    assert form.is_valid(), form.errors
    el = form.save()
    assert el.target == Decimal("40401.5")
    assert GuessNumberElementForm(instance=el).initial["stem"] == "{{40401.5}}"


@pytest.mark.django_db
@pytest.mark.parametrize("typed,re_rendered", [("{{+5}}", "{{5}}"), ("{{-5}}", "{{-5}}")])
def test_sign_round_trip_through_the_form(typed, re_rendered):
    # §2.6's sign policy end-to-end: parse_number's _NUM_RE accepts a leading
    # sign, so a redundant + is dropped and - is preserved. Task 2 only unit-tests
    # format_target; this crosses the whole form path.
    el = GuessNumberElementForm(_data(stem=typed)).save()
    el.refresh_from_db()
    assert GuessNumberElementForm(instance=el).initial["stem"] == re_rendered


@pytest.mark.django_db
def test_editing_shows_author_token_not_the_raw_sentinel_stem():
    el = GuessNumberElementForm(_data()).save()
    initial = GuessNumberElementForm(instance=el).initial["stem"]
    assert initial == r"\(201^2=\){{40401}}"


@pytest.mark.django_db
def test_editing_formats_tolerance_initial_not_raw_decimal():
    el = GuessNumberElementForm(_data(tolerance="0,5")).save()
    el.refresh_from_db()
    assert GuessNumberElementForm(instance=el).initial["tolerance"] == "0.5"


@pytest.mark.django_db
@pytest.mark.parametrize("stem", ["no token", "{{1}} {{2}}"])
def test_token_count_errors(stem):
    form = GuessNumberElementForm(_data(stem=stem))
    assert not form.is_valid()
    assert "stem" in form.errors


@pytest.mark.django_db
def test_pipe_alternatives_error_is_distinct_from_token_count_error():
    pipe = GuessNumberElementForm(_data(stem="{{40401|40402}}"))
    none = GuessNumberElementForm(_data(stem="no token"))
    assert not pipe.is_valid() and not none.is_valid()
    assert pipe.errors["stem"] != none.errors["stem"]  # distinct per code


@pytest.mark.django_db
def test_non_numeric_token_rejected():
    form = GuessNumberElementForm(_data(stem="{{abc}}"))
    assert not form.is_valid()


@pytest.mark.django_db
def test_twelve_integer_digits_ok_thirteen_rejected():
    # check_decimal_str's real bound is max_digits - decimal_places = 12.
    assert GuessNumberElementForm(_data(stem="{{" + "1" * 12 + "}}")).is_valid()
    form = GuessNumberElementForm(_data(stem="{{" + "1" * 13 + "}}"))
    assert not form.is_valid()  # a form error, NOT a DB DataError
    assert "stem" in form.errors


@pytest.mark.django_db
def test_nine_decimal_places_rejected_not_silently_rounded():
    form = GuessNumberElementForm(_data(stem="{{0.123456789}}"))
    assert not form.is_valid()


@pytest.mark.django_db
def test_sentinel_in_prose_is_stripped_before_parse():
    form = GuessNumberElementForm(_data(stem=guessnumber.SENTINEL_TOKEN + " {{5}}"))
    assert form.is_valid(), form.errors
    # exactly one token survives — the forged one was stripped
    assert form.save().stem.count(guessnumber.SENTINEL_TOKEN) == 1
```

- [ ] **Step 2: Run to verify it fails**

```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_gn uv run pytest tests/test_guessnumber_form.py -q
```
Expected: FAIL — `ImportError: cannot import name 'GuessNumberElementForm'`.

- [ ] **Step 3: Write the form**

In `courses/element_forms.py`. **`_` in this module already IS `gettext_lazy`** (`from django.utils.translation import gettext_lazy as _`), so use `_(...)` directly — do not add a second alias. `fillblank`, `parse_number` and `sanitize_html` are already imported; the genuinely new imports are `guessnumber`, `check_decimal_str`, `TransferError`, **and
`GuessNumberElement`** (the `Meta.model` reference NameErrors at module import otherwise — which
breaks every test that imports `element_forms`, not just the new ones):

```python
# gettext_LAZY is mandatory: an eager gettext() here froze labels to English
# once already (PR #46). Keyed by GuessNumberError.code.
_GUESS_STEM_ERRORS = {
    "token_count": _("Write the answer in double braces, e.g. {{42}}."),
    "alternatives": _(
        'Use exactly one answer in braces — alternatives separated by "|" are '
        "not supported here."
    ),
}


class GuessNumberElementForm(forms.ModelForm):
    parsed_target = None  # Decimal after a successful clean_stem

    class Meta:
        model = GuessNumberElement
        fields = ["stem", "tolerance", "success_message"]  # target is DERIVED

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Same ','/'.' leniency the students get (PL/EN bilingual), and it makes
        # tolerance optional — a DecimalField(default=0) formfield is required.
        self.fields["tolerance"] = forms.CharField(required=False)
        if self.instance and self.instance.pk:
            # Show the author their token, not the raw <SENTINEL>0<SENTINEL> stem — without this
            # to_author_stem has no caller at all.
            self.initial["stem"] = guessnumber.to_author_stem(
                self.instance.stem, self.instance.target
            )
            # ...and canonical tolerance text, or a CharField str()s the DB
            # Decimal and shows "0.00000000".
            self.initial["tolerance"] = guessnumber.format_target(self.instance.tolerance)

    def clean_stem(self):
        raw = self.cleaned_data.get("stem", "")
        clean = fillblank.strip_sentinel(sanitize_html(raw))
        try:
            token_stem, raw_target = guessnumber.parse_stem(clean)
        except guessnumber.GuessNumberError as e:
            raise forms.ValidationError(_GUESS_STEM_ERRORS[e.code]) from e
        parsed = parse_number(raw_target)
        if parsed is None:
            raise forms.ValidationError(_("The answer must be a number (e.g. 42 or 3,14)."))
        try:
            # target is not a form field, so _post_clean excludes it from
            # full_clean and its DecimalValidator never fires. Without this the
            # DB raises a numeric-overflow DataError (a 500).
            check_decimal_str(str(parsed), "target", 20, 8)
        except TransferError as e:
            raise forms.ValidationError(
                _(
                    "The answer has too many digits (at most 12 before and 8 "
                    "after the decimal point)."
                )
            ) from e
        self.parsed_target = parsed
        return token_stem

    def clean_tolerance(self):
        raw = self.cleaned_data.get("tolerance", "")
        if not raw:
            return 0
        parsed = parse_number(raw)
        if parsed is None:
            raise forms.ValidationError(_("Enter a number (e.g. 3.14 or 3,14)."))
        if parsed < 0:
            raise forms.ValidationError(_("Tolerance cannot be negative."))
        return parsed

    def _post_clean(self):
        # NOT in save(): ModelForm.save() reads self.errors, and THAT is what
        # triggers full_clean() -> clean_stem() -> parsed_target. A save()
        # override assigning self.instance.target first would read None, and
        # construct_instance won't repair it (target isn't in Meta.fields), so
        # the row inserts NULL -> IntegrityError. _post_clean runs after
        # _clean_fields by construction, so parsed_target is always set here.
        super()._post_clean()
        if self.parsed_target is not None:
            self.instance.target = self.parsed_target
```

Register it: `FORM_FOR_TYPE["guessnumber"] = GuessNumberElementForm`.

**Do not** add `label=` kwargs or an RTE `Meta.widgets` — labels are template-side (§9), and `Meta.widgets`' `data-rte-source` is dead code in this codebase.

- [ ] **Step 4: Run to verify it passes**

```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_gn uv run pytest tests/test_guessnumber_form.py -q
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add courses/element_forms.py tests/test_guessnumber_form.py
git commit -m "feat(guessnumber): three-part authoring form

__init__ populates the author token + formatted tolerance; clean_stem stashes
parsed_target; save() assigns it (target is derived, so form.save() would
otherwise write NULL). tolerance is a CharField so Polish '0,5' parses."
```

---

### Task 5: Render tag + student template

Spec §2.7. The `<form>` **wraps** the stem; only inline markup is spliced at the token.

**Files:**
- Modify: `courses/templatetags/courses_extras.py`, `courses/urls.py`, `courses/views.py` (stub)
- Create: `templates/courses/elements/guessnumberelement.html`
- Create: `tests/test_guessnumber_render.py`

**Interfaces:**
- Produces: `{% render_guess_number el eid %}`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_guessnumber_render.py`:

```python
from decimal import Decimal

import pytest

from courses import guessnumber
from courses.models import GuessNumberElement
from courses.templatetags.courses_extras import render_guess_number


@pytest.mark.django_db
def test_renders_contract_hooks():
    el = GuessNumberElement.objects.create(stem="x" + guessnumber.SENTINEL_TOKEN + "y", target=Decimal("42"))
    html = render_guess_number(el, 7)
    assert 'class="guessnumber"' in html and "data-guessnumber" in html
    assert 'data-element-pk="7"' in html
    assert "/element/7/guessnumber-check/" in html  # data-check-url
    assert "<form" not in html                      # no form: implicit submission would
    assert 'type="submit"' not in html              # reload and wipe reveal-gate state
    assert 'type="button"' in html
    assert 'type="text"' in html                    # NOT type=number: kills "40401,5"
    assert "data-guess-input" in html
    assert "data-guess-check" in html and "hidden" in html
    assert "data-guess-live" in html and 'aria-live="polite"' in html
    assert "data-guess-hint" in html
    assert "data-guess-success" in html
    assert "data-msg-high" in html and "data-msg-low" in html


@pytest.mark.django_db
def test_blank_success_message_falls_back_to_correct():
    el = GuessNumberElement.objects.create(stem=guessnumber.SENTINEL_TOKEN, target=Decimal("42"))
    assert "Correct!" in render_guess_number(el, 1)


@pytest.mark.django_db
def test_empty_block_markup_success_message_also_falls_back():
    # The RTE posts <p><br></p> when an author types and deletes — truthy, and
    # it survives sanitize_html, so a `if not success_message` test lets it
    # through and renders an empty box.
    el = GuessNumberElement.objects.create(
        stem=guessnumber.SENTINEL_TOKEN, target=Decimal("42"), success_message="<p><br></p>"
    )
    assert "Correct!" in render_guess_number(el, 1)


@pytest.mark.django_db
def test_success_message_html_is_preserved_not_escaped():
    el = GuessNumberElement.objects.create(
        stem=guessnumber.SENTINEL_TOKEN, target=Decimal("42"), success_message="<p>Tak</p>"
    )
    html = render_guess_number(el, 1)
    assert "<p>Tak</p>" in html and "&lt;p&gt;" not in html


@pytest.mark.django_db
def test_spliced_widget_contains_no_block_level_start_tag():
    # sanitize_html allows <p>; the HTML PARSER auto-closes an open <p> on a
    # <form>/<div> start tag, hoisting the widget and all following prose out of
    # the paragraph. That is parser behaviour — string slicing cannot see it, so
    # assert on the spliced fragment's tags instead of its position.
    el = GuessNumberElement.objects.create(
        stem="<p>201 = " + guessnumber.SENTINEL_TOKEN + " done</p>", target=Decimal("42")
    )
    html = render_guess_number(el, 1)
    start = html.index("<input data-guess-input")
    end = html.index("</button>", start)
    spliced = html[start:end]
    for block in ("<form", "<div", "<p"):
        assert block not in spliced


@pytest.mark.django_db
def test_parsed_dom_keeps_the_input_inside_the_paragraph():
    # The same trap, checked through a real parser rather than string offsets.
    from html.parser import HTMLParser

    el = GuessNumberElement.objects.create(
        stem="<p>201 = " + guessnumber.SENTINEL_TOKEN + " done</p>", target=Decimal("42")
    )

    class Depth(HTMLParser):
        stack, depth_at_input = [], None

        def handle_starttag(self, tag, attrs):
            if tag == "input" and any(a[0] == "data-guess-input" for a in attrs):
                Depth.depth_at_input = list(self.stack)
            elif tag not in ("input", "br"):
                self.stack.append(tag)

        def handle_endtag(self, tag):
            if self.stack and self.stack[-1] == tag:
                self.stack.pop()

    p = Depth()
    p.feed(render_guess_number(el, 1))
    assert "p" in (Depth.depth_at_input or [])  # still inside the paragraph
```

- [ ] **Step 2: Run to verify it fails**

```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_gn uv run pytest tests/test_guessnumber_render.py -q
```
Expected: FAIL — `ImportError: cannot import name 'render_guess_number'`.

- [ ] **Step 3: Write the tag**

In `courses/templatetags/courses_extras.py`, modelled on `render_switch_gate`. **Two new imports are
required** — the module currently has neither: `from django.utils.html import strip_tags`, and
`from courses import guessnumber` (mirroring the existing `from courses import switchgate as _switchgate`
alias style):

```python
@register.simple_tag
def render_guess_number(el, eid):
    """Render the numeric input spliced into the stem at its U+FFFF-delimited token.

    NO <form>: implicit submission cannot be suppressed without JS, and a stray
    Enter reload would wipe reveal.js's in-memory cascade state (it persists
    nothing), re-hiding a gated element. Enter comes from a keydown listener
    instead. The <div> WRAPS the stem; only inline markup is spliced, because
    the parser hoists block elements out of an enclosing <p>."""
    check_url = reverse("courses:guessnumber_check", args=[eid])
    widget = format_html(
        '<input data-guess-input type="text" inputmode="decimal" '
        'aria-label="{}"><button data-guess-check type="button" hidden>{}</button>',
        _("Your answer"),
        _("Check"),
    )
    body = guessnumber.render_stem(el.stem, widget)
    msg = el.success_message or ""
    has_text = bool(strip_tags(msg).strip())
    success = mark_safe(msg) if has_text else format_html("{}", _("Correct!"))  # noqa: S308 — sanitized at save()
    return format_html(
        '<div class="guessnumber" data-guessnumber data-element-pk="{}" '
        'data-check-url="{}" data-msg-high="{}" data-msg-low="{}">{}'
        '<div data-guess-live aria-live="polite">'
        '<p data-guess-hint hidden></p>'
        '<div data-guess-success hidden>{}</div></div></div>',
        eid,
        check_url,
        _("The number is too big, try again."),
        _("The number is too small, try again."),
        body,
        success,
    )
```

Create `templates/courses/elements/guessnumberelement.html`:

```html
{% load courses_extras %}
{% render_guess_number el eid %}
```

- [ ] **Step 3b: Register the route now — the tag reverses it**

`render_guess_number` calls `reverse("courses:guessnumber_check", ...)`, so the URL name must exist or
every test in this task raises `NoReverseMatch`. Add the route in `courses/urls.py` **with the
`courses/` prefix** (every sibling has it; `courses.urls` is included at the root with an empty prefix):

```python
path(
    "courses/element/<int:element_pk>/guessnumber-check/",
    views.guessnumber_check,
    name="guessnumber_check",
),
```

Django imports the view at URL-load time, so add a minimal stub to `courses/views.py` in this task —
Task 6 replaces its body and adds the real tests:

```python
@require_POST
@login_required
def guessnumber_check(request, element_pk):
    raise NotImplementedError  # Task 6
```

- [ ] **Step 4: Run to verify it passes**

```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_gn uv run pytest tests/test_guessnumber_render.py -q
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add courses/templatetags/courses_extras.py templates/courses/elements/guessnumberelement.html courses/urls.py courses/views.py tests/test_guessnumber_render.py
git commit -m "feat(guessnumber): render tag + student template

The <form> wraps the stem and only the inline input/button is spliced at the
token — a spliced <form> would be hoisted out of an enclosing <p>. Blank-message
fallback is server-side and tests text content, not truthiness (the RTE posts
<p><br></p>)."
```

---

### Task 6: Check endpoint (replace the Task 5 stub)

Spec §4.1. Soft pk lookup, persists nothing.

**Files:**
- Modify: `courses/views.py` (replace the Task 5 stub)
- Create: `tests/test_guessnumber_endpoint.py`

**Interfaces:**
- Produces: `courses:guessnumber_check`; response `{"correct": bool, "direction": "high"|"low"|null}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_guessnumber_endpoint.py`.

**Model this file on `tests/test_filltable_check.py`** — the server-side check-endpoint test for a
sibling self-check element. It already demonstrates every fixture this task needs: two **separate
`django.test.Client()` instances** (with a docstring on why they must not share session state), a
factory fixture that ties the element's course to the authed user, a soft-pk 200 miss, a 403 case and a
405 GET. (There is no *switchgate* endpoint test — but that does not mean there is no template.)

Use **`tests.factories.add_element(unit, obj)`** to build the join row; it exists precisely for this
("Attach a saved concrete element `obj` to `unit` via a new Element join-row"). Never a literal password
— use `tests.factories.TEST_PASSWORD` (GitGuardian flags new ones).

The five fixtures. **The element fixtures must depend on the client fixture**, or the enrolled user has
no relationship to the element's course and every non-soft-pk test 403s instead of 200
(`can_access_course` is `accessible_courses(user).filter(pk=course.pk).exists()` — owner OR enrolled OR
staff). `tests/test_filltable_check.py` does this with `CourseFactory(owner=auth_client.user)`:

- `gn_eid(auth_client)` — `CourseFactory(owner=auth_client.user)` then a lesson unit, then
  `GuessNumberElement(target=42, tolerance=0)`, then `add_element(unit, obj)`; yield **the join row's
  `.pk`** (the `eid` contract — NOT the concrete pk).
- `gn_tolerant_eid(auth_client)` — same, `tolerance=Decimal("0.5")`.
- `other_element_eid(auth_client)` — join-row pk of a **different** type (e.g. `TextElement`), for the
  wrong-type soft-pk probe.
- `auth_client` — a fresh `Client()` logged in as the course owner.
- `other_auth_client` — a **separate** fresh `Client()` for a user with no access to that course.

The code block below uses these names consistently — every test takes `auth_client` (or
`other_auth_client` for the 403 case), and the element fixtures are built on `auth_client.user`'s course,
so the authed user actually has access to the element's course.

```python
from decimal import Decimal

import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import GuessNumberElement
from courses.models import QuestionResponse
from courses.models import UnitProgress


def _post(client, eid, guess):
    return client.post(reverse("courses:guessnumber_check", args=[eid]), {"guess": guess})


@pytest.mark.django_db
@pytest.mark.parametrize(
    "guess,correct,direction",
    [
        ("42", True, None),
        ("43", False, "high"),
        ("41", False, "low"),
        ("abc", False, None),      # unparseable: wrong, but no direction
        ("1 000", False, None),    # thousands separator rejected by parse_number
        ("", False, None),
    ],
)
def test_verdicts(auth_client, gn_eid, guess, correct, direction):
    r = _post(auth_client, gn_eid, guess)
    assert r.status_code == 200
    assert r.json() == {"correct": correct, "direction": direction}


@pytest.mark.django_db
def test_tolerance_boundary_is_inclusive(auth_client, gn_tolerant_eid):
    # target=42, tolerance=0.5 -> exactly 42.5 is CORRECT
    assert _post(auth_client, gn_tolerant_eid, "42.5").json()["correct"] is True
    assert _post(auth_client, gn_tolerant_eid, "42.6").json() == {
        "correct": False,
        "direction": "high",
    }


@pytest.mark.django_db
@pytest.mark.parametrize("guess", ["42,0", "42.0"])
def test_comma_and_period_decimals_both_correct(auth_client, gn_eid, guess):
    assert _post(auth_client, gn_eid, guess).json()["correct"] is True


@pytest.mark.django_db
def test_missing_pk_is_benign_200(auth_client):
    r = _post(auth_client, 999999, "42")
    assert r.status_code == 200
    assert r.json() == {"correct": False, "direction": None}


@pytest.mark.django_db
def test_wrong_type_pk_is_benign_200(auth_client, other_element_eid):
    r = _post(auth_client, other_element_eid, "42")
    assert r.status_code == 200
    assert r.json() == {"correct": False, "direction": None}


@pytest.mark.django_db
def test_no_course_access_is_403(other_auth_client, gn_eid):
    assert _post(other_auth_client, gn_eid, "42").status_code == 403


@pytest.mark.django_db
def test_get_not_allowed(auth_client, gn_eid):
    url = reverse("courses:guessnumber_check", args=[gn_eid])
    assert auth_client.get(url).status_code == 405


@pytest.mark.django_db
def test_anonymous_redirected(client, gn_eid):
    assert _post(client, gn_eid, "42").status_code in (302, 403)


@pytest.mark.django_db
def test_nothing_is_persisted(auth_client, gn_eid):
    _post(auth_client, gn_eid, "43")
    assert QuestionResponse.objects.count() == 0
    assert UnitProgress.objects.count() == 0  # the likelier accidental write
```



- [ ] **Step 2: Run to verify it fails**

```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_gn uv run pytest tests/test_guessnumber_endpoint.py -q
```
Expected: FAIL — `NotImplementedError` from the Task 5 stub. **Not** `NoReverseMatch`: Task 5 Step 3b
already registered the route, so the name resolves. (`test_get_not_allowed` and
`test_anonymous_redirected` pass already — they are satisfied by the route plus the decorators.)

- [ ] **Step 3: Write the view body**

In `courses/views.py`, next to `switchgate_check`:

**New imports required in `courses/views.py`** (one per line — isort `force-single-line = true`):
`from courses.marking import parse_number` and `from courses.models import GuessNumberElement`. Neither
is there today (`views.py` imports `blank_matches`/`MarkResult` from `courses.marking`, not
`parse_number`), so the snippet below NameErrors without them.

Copy `switchgate_check`'s shape **exactly** — these are its real interfaces, verified in source:
`Element` exposes the concrete via **`content_object`** (a `GenericForeignKey`); there is no `.content`.
Access is **`can_access_course(user, course)` returning a bool** (already imported in `views.py` from
`courses.access`) — it is a predicate, so you must `raise PermissionDenied` yourself.

```python
@require_POST
@login_required
def guessnumber_check(request, element_pk):
    """Server-side check for a Guess-the-number self-check. Reports correctness and
    a direction only — NOTHING is persisted. Soft pk lookup: a missing or wrong-type
    pk is a 200 {"correct": false, "direction": null}, NOT a 404 (switchgate parity,
    a deliberate deviation from fillgate_check's get_object_or_404)."""
    miss = JsonResponse({"correct": False, "direction": None})
    element = (
        Element.objects.select_related("unit__course").filter(pk=element_pk).first()
    )
    concrete = element.content_object if element else None
    if not isinstance(concrete, GuessNumberElement):
        return miss
    # Resolved element: apply the same access check the sibling gates use.
    if not can_access_course(request.user, element.unit.course):
        raise PermissionDenied
    n = parse_number(request.POST.get("guess", ""))
    if n is None:
        return miss
    if abs(n - concrete.target) <= concrete.tolerance:
        return JsonResponse({"correct": True, "direction": None})
    return JsonResponse(
        {"correct": False, "direction": "high" if n > concrete.target else "low"}
    )
```

The route itself was already registered in Task 5, Step 3b (the render tag reverses it). This task
replaces the `NotImplementedError` stub with the body above — `courses/urls.py` needs no further change.

- [ ] **Step 4: Run to verify it passes**

```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_gn uv run pytest tests/test_guessnumber_endpoint.py -q
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add courses/views.py tests/test_guessnumber_endpoint.py
git commit -m "feat(guessnumber): soft-pk check endpoint

{'correct': bool, 'direction': 'high'|'low'|None}, direction from the student's
perspective. Reuses parse_number (',' and '.' both parse). Persists nothing."
```

---

### Task 7: Context flags — KaTeX gate and script gate

Spec §2.5a / §2.7. Without the `_element_has_math` clause the headline `\(201^2=\)` renders raw.

**Files:**
- Modify: `courses/views.py`, `templates/courses/lesson_unit.html`
- Create: `tests/test_guessnumber_context.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_guessnumber_context.py`.

`tests/test_context_stepper.py` is the closest model — it already asserts `has_stepper` for top-level
*and* tab-nested, the identical trap. But note two things it does **not** give you:

1. It has **no pytest fixtures** — only plain helpers (`_enrolled_lesson(client)`, `_stepper(...)`).
   Copy that shape: helpers plus the pytest-django `client` fixture. Do not expect importable fixtures.
2. It has **no column-nesting case at all**. Write that one from scratch: create a `TwoColumnElement`,
   take a column id from its normalized ids, then attach the child `Element` with `parent=<the
   two-column join row>, tab_id=<column_id>` (the Tabs join-row substrate the two-column element
   reuses). Model it on `tests/test_twocolumn_partial.py`.

Helpers to write here (none exist): `_enrolled_lesson(client)` and `_lesson_with_gn(client, *, stem,
success_message, nest)`, both returning `(course, unit, user)` — there is no pytest `user` fixture, so
the helper must hand the user back. Import
`build_lesson_context` from `courses.views`, plus `pytest`, `Decimal`, `GuessNumberElement`, `reverse`,
and `tests.factories.add_element`.

Helper style, matching `test_context_stepper.py`. **There is no `user` fixture** — pytest-django ships
`client` / `admin_client` / `django_user_model`, never `user`, so each helper returns the user it made:

```python
def _enrolled_lesson(client):
    """-> (course, unit, user). Copy test_context_stepper.py's _enrolled_lesson."""
    ...


def _lesson_with_gn(client, *, stem="{{42}}", success_message="", nest=None):
    """Seed a lesson holding one GuessNumberElement. -> (course, unit, user).

    nest=None      -> top-level
    nest="tab"     -> inside a TabsElement panel
    nest="column"  -> inside a TwoColumnElement column (parent=<2col join row>,
                      tab_id=<column id from its normalized ids>)
    """
    ...


@pytest.mark.django_db
def test_has_math_true_for_math_in_stem(client):
    _c, unit, user = _lesson_with_gn(client, stem=r"\(201^2=\){{40401}}")
    assert build_lesson_context(unit, user)["has_math"] is True


@pytest.mark.django_db
def test_has_math_true_for_math_in_success_message(client):
    # Independently of the stem — an unknown type returns False and loads NO KaTeX.
    _c, unit, user = _lesson_with_gn(client, success_message=r"o \(100\%\)")
    assert build_lesson_context(unit, user)["has_math"] is True


@pytest.mark.django_db
def test_has_guess_number_top_level(client):
    _c, unit, user = _lesson_with_gn(client)
    assert build_lesson_context(unit, user)["has_guess_number"] is True


@pytest.mark.django_db
def test_has_guess_number_nested_in_tab(client):
    # build_lesson_context's `elements` list is parent__isnull=True, so a flag
    # computed from it misses nested children and the JS never loads.
    _c, unit, user = _lesson_with_gn(client, nest="tab")
    assert build_lesson_context(unit, user)["has_guess_number"] is True


@pytest.mark.django_db
def test_has_guess_number_nested_in_column(client):
    _c, unit, user = _lesson_with_gn(client, nest="column")
    assert build_lesson_context(unit, user)["has_guess_number"] is True


@pytest.mark.django_db
def test_lesson_page_loads_the_script(client):
    course, unit, _user = _lesson_with_gn(client)
    # A correct flag with a forgotten <script> tag ships a dead widget and the
    # flag test above still passes. Spec §7 calls this the exact class of
    # silent-breakage miss. Precedents: tests/test_stepper_assets.py,
    # tests/test_lesson_stepper_wiring.py — copy their lesson-GET shape, which
    # is reverse("courses:lesson_unit", slug=..., node_pk=...). There is NO
    # get_absolute_url() anywhere in this project.
    resp = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    )
    assert "guessnumber.js" in resp.content.decode()


@pytest.mark.django_db
def test_lesson_without_the_element_omits_the_script(client):
    course, plain, _user = _enrolled_lesson(client)
    resp = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": plain.pk})
    )
    assert "guessnumber.js" not in resp.content.decode()
```

- [ ] **Step 2: Run to verify it fails**

```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_gn uv run pytest tests/test_guessnumber_context.py -q
```
Expected: FAIL — `KeyError: 'has_guess_number'`.

- [ ] **Step 3: Implement**

In `courses/views.py`, add to `_element_has_math` (one clause, both fields):

```python
    if isinstance(obj, GuessNumberElement):
        return has_math_delimiters(obj.stem) or has_math_delimiters(obj.success_message)
```

In `build_lesson_context`, add the flat flag beside `has_stepper` / `has_markdone`, using the **flat** `node.elements.filter(...)` form (never the `parent__isnull=True` list):

```python
    has_guess_number = node.elements.filter(
        content_type__model="guessnumberelement"
    ).exists()
```

Add it to the returned context. In `templates/courses/lesson_unit.html`, beside the sibling script tags (**no** prepaint watchdog block — this element hides nothing):

```html
{% if has_guess_number %}<script src="{% static 'courses/js/guessnumber.js' %}" defer></script>{% endif %}
```

- [ ] **Step 4: Run to verify it passes**

```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_gn uv run pytest tests/test_guessnumber_context.py -q
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add courses/views.py templates/courses/lesson_unit.html tests/test_guessnumber_context.py
git commit -m "feat(guessnumber): math gate + script gate

_element_has_math covers stem AND success_message: without a clause the whole
KaTeX bundle never loads and \\(201^2=\\) renders raw. has_guess_number uses the
flat query so tab/column-nested elements still load the JS."
```

---

### Task 8: `guessnumber.js` + editor wiring + math.js selector

Spec §2.5b / §2.7 / §3.2.

**Files:**
- Create: `courses/static/courses/js/guessnumber.js`
- Modify: `courses/static/courses/js/math.js`, `courses/static/courses/js/editor.js`, `templates/courses/manage/editor/editor.html`

**Interfaces:**
- Produces: `window.libliInitGuessNumbers(root)` — idempotent.

- [ ] **Step 1: Write `guessnumber.js`**

Model CSRF + fetch on `switchgate.js`. Required behaviour:

```js
(function () {
  function csrf() { /* cookie regex — copy switchgate.js:9-12 verbatim */ }

  function initOne(root) {
    if (root.dataset.guessnumberReady === "1") return;
    root.dataset.guessnumberReady = "1";

    var input = root.querySelector("[data-guess-input]");
    var check = root.querySelector("[data-guess-check]");
    var hint = root.querySelector("[data-guess-hint]");
    var success = root.querySelector("[data-guess-success]");
    var pk = root.getAttribute("data-element-pk");
    var url = root.getAttribute("data-check-url");
    if (pk === "0" || !url) return;      // unsaved editor preview: no-op
    if (check) check.hidden = false;     // arm Check now that JS is live

    var inFlight = false;
    var done = false;

    input.addEventListener("input", function () {
      // A fresh attempt starts clean (switchgate's hideFeedback rule).
      if (done) return;
      hint.hidden = true;
      input.classList.remove("is-wrong");
    });

    // No <form>, so no native submit to hook — deliberately: implicit
    // submission can't be suppressed without JS, and a stray Enter reload
    // would wipe reveal.js's in-memory cascade state.
    if (check) check.addEventListener("click", submit);
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") submit();
    });

    function submit() {
      if (inFlight || done) return;    // in-flight + post-lock guards
      var value = (input.value || "").trim();
      if (!value) return;
      inFlight = true;
      fetch(url, {
        method: "POST",
        headers: { "X-CSRFToken": csrf(), "Content-Type": "application/x-www-form-urlencoded" },
        body: "guess=" + encodeURIComponent(value),
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d.correct) {
            done = true;
            hint.hidden = true;
            success.hidden = false;
            input.classList.remove("is-wrong");
            input.classList.add("is-correct");
            input.readOnly = true;
            if (check) check.disabled = true;  // presentational; `done` is the real guard
            root.classList.add("guessnumber--done");
          } else {
            input.classList.add("is-wrong");
            if (d.direction === "high" || d.direction === "low") {
              hint.textContent = form.getAttribute("data-msg-" + d.direction) || "";
              hint.hidden = false;
            } else {
              hint.hidden = true;      // unparseable: red, no direction
            }
          }
        })
        .catch(function () { /* leave editable; never lock, never falsely pass */ })
        .then(function () { inFlight = false; });
    }
  }

  function init(scope) {
    (scope || document).querySelectorAll("[data-guessnumber]").forEach(initOne);
  }
  window.libliInitGuessNumbers = init;
  init(document);
})();
```

**No `typesetMath` here** — `math.js` covers initial load and `editor.js`'s `renderPreviewMath` covers post-swap (§2.5b).

- [ ] **Step 2: Add `.guessnumber` to math.js's selector list**

In `courses/static/courses/js/math.js`, append `.guessnumber` to `renderInlineText`'s selector list (next to `.stepper`, `.markdone`).

- [ ] **Step 3: Wire the editor — BOTH sites**

`courses/static/courses/js/editor.js`, next to the other re-inits:

```js
    if (preview && window.libliInitGuessNumbers) window.libliInitGuessNumbers(preview);  // re-arm guess-number
```

`templates/courses/manage/editor/editor.html`, next to the sibling enhancer tags:

```html
<script src="{% static 'courses/js/guessnumber.js' %}" defer></script>
```

This second step is the one missed twice before (gallery, reveal-gate). Task 9 adds the test that guards it.

- [ ] **Step 4: Lint**

```bash
uv run ruff check courses/ && uv run ruff format --check courses/
```
Expected: no findings (JS is untouched by ruff; this guards the Python edits so far).

- [ ] **Step 5: Commit**

```bash
git add courses/static/courses/js/guessnumber.js courses/static/courses/js/math.js courses/static/courses/js/editor.js templates/courses/manage/editor/editor.html
git commit -m "feat(guessnumber): enhancer JS + editor/math wiring

Enter via keydown, not a form submit: implicit submission can't be suppressed
without JS, and a stray Enter reload would wipe reveal.js's in-memory cascade
state, re-hiding a gated element. In-flight + post-lock guards. No typesetMath:
math.js + editor.js already cover both paths."
```

---

### Task 9: Editor authoring surface

Spec §2.4 / §7 / §9. The `_edit_` partial is mandatory: its absence 500s the instant the palette card is clicked.

**Files:**
- Create: `templates/courses/manage/editor/_edit_guessnumber.html`
- Modify: `templates/courses/manage/editor/_add_menu.html`, `templates/courses/manage/_icon_sprite.html`, `courses/views_manage.py`, `courses/templatetags/courses_manage_extras.py`
- Create: `tests/test_guessnumber_authoring.py`

- [ ] **Step 1: Write the failing tests**

Both routes are **slug-keyed**, and `element_add` is **POST-only and render-only** — it reads
`request.POST["type"]` and `request.POST["unit"]`, so a GET with `?type=` yields
`HttpResponseBadRequest("bad type")`. Copy `tests/test_editor_stepper_add.py`'s shape verbatim:

```python
from decimal import Decimal

import pytest
from django.urls import reverse

from courses.models import GuessNumberElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def _lesson_unit(course):
    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )


def test_manage_element_add_renders_the_edit_partial_200(client):
    # element_add -> _host_form -> _edit_guessnumber. Row/palette tests never
    # reach this path; the reveal-gate partial was missed exactly this way,
    # 500ing TemplateDoesNotExist on the first palette click (fixed in PR #100).
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "guessnumber", "unit": unit.pk},
    )
    assert resp.status_code == 200
    assert b"data-rte-source" in resp.content


def test_element_save_creates_the_element(client):
    # element_add is render-only; manage_element_save is the real create path,
    # and it exercises save_element's generic `else` branch — the reason the
    # form must be a ModelForm (spec §2.3.2).
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {
            "type": "guessnumber",
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),  # MANDATORY: save_element runs
            "element": "new",                        # _check_token(unit.updated, ...)
            "stem": "{{42}}",                        # and a missing token raises
            "tolerance": "",                         # ConflictError -> 302, creating
            "success_message": "",                   # NOTHING while the test passes.
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    el = GuessNumberElement.objects.get()
    assert el.target == Decimal("42")


def test_editor_loads_the_enhancer_script(client):
    # editor.html forgetting the <script> shipped gallery and reveal-gate with a
    # dead preview. Guard it.
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    )
    assert "guessnumber.js" in resp.content.decode()


def test_palette_card_present(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    )
    assert 'data-add-type="guessnumber"' in resp.content.decode()


def test_each_rte_field_has_its_own_toolbar_wrapper(client):
    # wireRte resolves a toolbar via closest(".el-editor--text"); two RTE fields
    # sharing one wrapper means one Bold click mutates both surfaces.
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    html = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "guessnumber", "unit": unit.pk},
    ).content.decode()
    assert html.count("el-editor--text") == 2
    assert html.count("data-rte-toolbar") == 2
    assert html.count("data-rte-source") == 2
```

The POST shape above is taken from `tests/test_element_add_save.py` and
`tests/test_filltable_manage_plumbing.py` — open one of them before writing this task.

- [ ] **Step 2: Run to verify it fails**

```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_gn uv run pytest tests/test_guessnumber_authoring.py -q
```
Expected: FAIL.

- [ ] **Step 3: Write the partial**

Create `templates/courses/manage/editor/_edit_guessnumber.html`, copying `_edit_shortnumericquestion.html`'s hand-rolled shape verbatim. **Each RTE field gets its own `.el-editor--text` wrapper with its own toolbar include.**

```html
{% load i18n %}
<div class="el-editor el-editor--guessnumber">
  <label class="el-editor__label">{% trans "Prompt with the answer" %}</label>
  <div class="el-editor--text">
    {% include "courses/manage/editor/_rte_toolbar.html" %}
    <textarea name="stem" class="rte-source" data-rte-source rows="3">{{ form.stem.value|default:"" }}</textarea>
  </div>
  <p class="el-editor__hint">{% trans "Mark the answer with {{42}} (exactly once)." %}</p>
  {% for e in form.stem.errors %}<p class="field-error">{{ e }}</p>{% endfor %}

  <label class="el-editor__label">{% trans "Tolerance (±, optional)" %}</label>
  <input type="text" name="tolerance" inputmode="decimal" value="{{ form.tolerance.value|default:'' }}">
  {% for e in form.tolerance.errors %}<p class="field-error">{{ e }}</p>{% endfor %}

  <label class="el-editor__label">{% trans "Success message" %}</label>
  <div class="el-editor--text">
    {% include "courses/manage/editor/_rte_toolbar.html" %}
    <textarea name="success_message" class="rte-source" data-rte-source rows="3">{{ form.success_message.value|default:"" }}</textarea>
  </div>
  <p class="el-editor__hint">{% trans "The success message is visible in the page source — do not put anything secret here." %}</p>
  {% for e in form.success_message.errors %}<p class="field-error">{{ e }}</p>{% endfor %}
</div>
```

- [ ] **Step 4: Wire the palette and labels**

- `_add_menu.html`: add a card in the **Interactive** group (no `{% if not nested %}` guard — the element is nestable):
  `<button type="button" class="typecard" data-add-type="guessnumber"><svg class="ic" aria-hidden="true" focusable="false"><use href="#el-guessnumber"/></svg>{% trans "Guess the number" %}</button>`
- `templates/courses/manage/_icon_sprite.html`: add a monochrome `currentColor` line-SVG `<symbol id="el-guessnumber">` (never a multicolour emoji).
- `courses/views_manage.py`: add `"guessnumber"` to the `element_add` and `element_save` allow-tuples, and `_EDITOR_TYPE_LABELS["guessnumber"] = gettext_lazy("Guess the number")`.
- `courses/templatetags/courses_manage_extras.py`: `_ELEMENT_LABELS["guessnumberelement"] = _("Guess the number")`. **No `element_summary` branch** — its generic `stem` fallback already rewrites `<SENTINEL>N<SENTINEL>` → `___`.

- [ ] **Step 5: Run to verify it passes**

```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_gn uv run pytest tests/test_guessnumber_authoring.py -q
```
Expected: PASS.

- [ ] **Step 6: Check the palette-count assert**

```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_gn uv run pytest tests/test_manage_editor_menu.py -q
```
Expected: PASS — the count assert is quiz-scoped and the Interactive group is quiz-hidden, so an Interactive card should not move it. **If it fails, update the count** (this is a known class of DoD gotcha).

- [ ] **Step 7: Commit**

```bash
git add templates/courses/manage/editor/_edit_guessnumber.html templates/courses/manage/editor/_add_menu.html templates/courses/manage/_icon_sprite.html courses/views_manage.py courses/templatetags/courses_manage_extras.py tests/test_guessnumber_authoring.py
git commit -m "feat(guessnumber): authoring surface (palette card + edit partial)

Hand-rolled RTE textareas, one .el-editor--text wrapper + toolbar per field:
wireRte resolves its toolbar via closest(), so a shared wrapper would bind both
surfaces to one toolbar. Tests guard the _edit_ partial and the editor script."
```

---

### Task 10: Transfer trio

Spec §7.1. Must precede Task 11 (the `NESTABLE_TYPE_KEYS <= set(SERIALIZERS)` invariant).

**Files:**
- Modify: `courses/transfer/export.py`, `courses/transfer/payloads.py`, `courses/transfer/importer.py`
- Create: `tests/test_guessnumber_transfer.py`

- [ ] **Step 1: Write the failing tests**

The `gn_element` fixture (used by three tests) does not exist — write it in this file. It must be a
**saved** row, so `refresh_from_db()` yields the Postgres-quantised Decimal the round-trip test
reasons about:

```python
@pytest.fixture
def gn_element(db):
    return GuessNumberElement.objects.create(
        stem=guessnumber.SENTINEL_TOKEN,
        target=Decimal("40401.50"),
        tolerance=Decimal("0.5"),
        success_message="",
    )
```

Import list (model it on `tests/test_filltable_transfer.py`, which already imports the same trio):

```python
from decimal import Decimal

import pytest

from courses import fillblank
from courses import guessnumber
from courses.builder import _NESTABLE_FORM_KEY_ALIASES
from courses.builder import NESTABLE_TYPE_KEYS
from courses.models import GuessNumberElement
from courses.transfer.export import SERIALIZERS
from courses.transfer.importer import BUILDERS
from courses.transfer.importer import _build_guess_number
from courses.transfer.payloads import VALIDATORS
from courses.transfer.payloads import _val_guess_number
from courses.transfer.schema import TransferError

# Built, never typed: a literal U+FFFF is corrupted to U+FFFC on write.
STRAY_SENTINEL = fillblank.SENTINEL + "x"  # must NOT match _TOKEN_RE (digits only)


@pytest.mark.django_db
def test_registered_in_all_three_registries():
    # Omit the BUILDERS entry and every archive containing the element fails at
    # import with nothing red to warn you; omit VALIDATORS and the payload is
    # never checked. tests/test_filltable_transfer.py asserts all three.
    assert "guess_number" in SERIALIZERS
    assert "guess_number" in VALIDATORS
    assert "guess_number" in BUILDERS


@pytest.mark.django_db
def test_decimals_export_as_strings(gn_element):
    payload = SERIALIZERS["guess_number"][1](gn_element, set())
    assert isinstance(payload["target"], str)
    assert isinstance(payload["tolerance"], str)


@pytest.mark.django_db
def test_round_trip_preserves_values(gn_element):
    # Compare Decimals, not literal strings: str() reflects how the Decimal
    # entered memory, so an in-memory create() serializes unquantized while a
    # DB-loaded row gives "0.00000000" (Postgres). See spec §7.1.
    gn_element.refresh_from_db()
    payload = SERIALIZERS["guess_number"][1](gn_element, set())
    assert Decimal(payload["target"]) == gn_element.target
    assert Decimal(payload["tolerance"]) == gn_element.tolerance


@pytest.mark.django_db
def test_export_validate_import_round_trip(gn_element):
    # The test above only serialises. Chain all three, or a serializer/builder
    # disagreement on decimal shape goes unnoticed (export uses str(), the form
    # uses format_target).
    gn_element.refresh_from_db()
    payload = SERIALIZERS["guess_number"][1](gn_element, set())
    _val_guess_number(payload, "e1", set())
    rebuilt, _children = _build_guess_number(payload, None)
    assert rebuilt.target == gn_element.target
    assert rebuilt.tolerance == gn_element.tolerance
    assert rebuilt.stem == gn_element.stem


def test_validator_rejects_missing_key():
    with pytest.raises(TransferError):
        _val_guess_number(
            {"stem": guessnumber.SENTINEL_TOKEN, "target": "42", "tolerance": "0"},
            "e1",
            set(),
        )


def test_validator_rejects_unknown_key():
    with pytest.raises(TransferError):
        _val_guess_number(
            {"stem": guessnumber.SENTINEL_TOKEN, "target": "42", "tolerance": "0",
             "success_message": "", "extra": 1}, "e1", set()
        )


def test_non_string_stem_is_transfer_error_not_500():
    # _check_token_stem runs _TOKEN_RE.finditer(stem) -> TypeError (500) on an
    # int. check_str must run FIRST.
    with pytest.raises(TransferError):
        _val_guess_number(
            {"stem": 42, "target": "42", "tolerance": "0", "success_message": ""},
            "e1",
            set(),
        )


def test_stray_sentinel_rejected():
    with pytest.raises(TransferError):
        _val_guess_number(
            {"stem": guessnumber.SENTINEL_TOKEN + STRAY_SENTINEL, "target": "42", "tolerance": "0",
             "success_message": ""}, "e1", set()
        )


def test_negative_tolerance_rejected():
    with pytest.raises(TransferError):
        _val_guess_number(
            {"stem": guessnumber.SENTINEL_TOKEN, "target": "42", "tolerance": "-1",
             "success_message": ""}, "e1", set()
        )


@pytest.mark.django_db
def test_builder_sanitises_the_imported_stem():
    # stem is deliberately out of the model's save(), so an unsanitised archive
    # stem would be stored verbatim and then mark_safe'd by render_stem.
    el, children = _build_guess_number(
        {"stem": "<script>x</script>" + guessnumber.SENTINEL_TOKEN, "target": "42",
         "tolerance": "0", "success_message": ""},
        None,  # assets
    )
    assert "<script>" not in el.stem
    assert children == ()
```

- [ ] **Step 2: Run to verify it fails**

```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_gn uv run pytest tests/test_guessnumber_transfer.py -q
```
Expected: FAIL.

- [ ] **Step 3: Implement the trio**

`export.py` — register `"guess_number": (GuessNumberElement, _ser_guess_number)`:

```python
def _ser_guess_number(el, media):
    return {
        "stem": el.stem,
        "target": str(el.target),
        "tolerance": str(el.tolerance),
        "success_message": el.success_message,
    }
```

`payloads.py` — `_val_guess_number`, registered in `VALIDATORS`, in **this order**. The signature is
**3-arg**: the registry dispatches `VALIDATORS[el["type"]](data, el["id"], media_kinds)`, and every
sibling (`_val_short_numeric(data, elid, media_kinds)`) takes three. A 2-arg validator `TypeError`s on
every import containing the element:

```python
def _val_guess_number(data, elid, media_kinds):
    _exact_keys(
        data, ["stem", "target", "tolerance", "success_message"], _("guess_number data")
    )
    check_str(data["stem"], _("stem"))          # BEFORE the token check: _TOKEN_RE
    _check_token_stem(data["stem"], 1, elid)    # ...would TypeError on a non-str
    check_decimal_str(data["target"], "target", 20, 8)
    tolerance = check_decimal_str(data["tolerance"], "tolerance", 20, 8)
    if tolerance < 0:
        _err(_("Element '%(el)s': tolerance must not be negative."), el=elid)
    check_str(data["success_message"], "success_message")
    return set()  # references no media
```

**New imports:** `export.py` needs `from courses.models import GuessNumberElement`; `importer.py` needs
both that and `from courses.sanitize import sanitize_html` (it currently imports only
`switchgrid.sanitize_stem_segments`, so the builder's `sanitize_html` call would NameError). `Decimal`
is already imported in `importer.py`.

`importer.py` — `_build_guess_number`, registered in `BUILDERS`. The signature is **`(data, assets)`**
and it returns a **tuple `(obj, child_rows)`** — every sibling does (`_build_switch_gate(data, assets)`
ends `return obj, ()`). A bare-object return breaks the importer's unpack. The second element is **child model rows** (the
importer does `for row in child_rows: row.full_clean(...); row.save()`), not media refs — `()` is right
here because this element has no child model:

```python
def _build_guess_number(data, assets):
    obj = GuessNumberElement.objects.create(
        stem=sanitize_html(data["stem"]),  # stem is out of save(); sanitise here
        target=Decimal(data["target"]),
        tolerance=Decimal(data["tolerance"]),
        success_message=data["success_message"],  # save() sanitises this one
    )
    return obj, ()  # no child rows
```

- [ ] **Step 4: Run to verify it passes**

```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_gn uv run pytest tests/test_guessnumber_transfer.py -q
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add courses/transfer/ tests/test_guessnumber_transfer.py
git commit -m "feat(guessnumber): transfer serializer/validator/builder

Decimals travel as strings (json.dumps rejects Decimal). check_str(stem) runs
before _check_token_stem, which would TypeError->500 on a non-string. The
builder sanitises stem, since the model's save() deliberately does not."
```

---

### Task 11: Nestable in tabs and columns

**Files:**
- Modify: `courses/builder.py`
- Modify: `tests/test_guessnumber_transfer.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_guessnumber_transfer.py`:

```python
def test_guess_number_is_nestable():
    assert "guess_number" in NESTABLE_TYPE_KEYS       # TRANSFER key
    assert _NESTABLE_FORM_KEY_ALIASES["guessnumber"] == "guess_number"  # FORM key alias
    assert NESTABLE_TYPE_KEYS <= set(SERIALIZERS)     # the standing invariant
```

- [ ] **Step 2: Run to verify it fails**

```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_gn uv run pytest tests/test_guessnumber_transfer.py -q
```
Expected: FAIL — `"guess_number" not in NESTABLE_TYPE_KEYS`.

- [ ] **Step 3: Implement**

In `courses/builder.py`: add `"guess_number"` to `NESTABLE_TYPE_KEYS` (it holds **transfer** keys), and `"guessnumber": "guess_number"` to the module-level `_NESTABLE_FORM_KEY_ALIASES` dict that `resolve_scope` consults.

- [ ] **Step 4: Run the nesting-sensitive suites**

```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_gn uv run pytest tests/test_guessnumber_transfer.py tests/test_guessnumber_context.py tests/test_tabs_transfer.py tests/test_filltable_transfer.py -q
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add courses/builder.py tests/test_guessnumber_transfer.py
git commit -m "feat(guessnumber): allow nesting in tabs and columns

NESTABLE_TYPE_KEYS holds transfer keys, so resolve_scope needs the form-key
alias. Lands after the serializer for the NESTABLE <= SERIALIZERS invariant."
```

---

### Task 12: Styling (light + dark)

Spec §5. No view ships unstyled.

**Files:**
- Modify: the element stylesheet under `courses/static/courses/css/` (follow where `.switchgate` / `.fillgate` rules live)
- Create: `tests/test_guessnumber_css.py`

- [ ] **Step 1: Write the rules**

Cover: the inline row (`input` + Check aligned against a KaTeX-rendered `\(201^2=\)` baseline — the one genuinely new design problem, decide it deliberately rather than leaving default `vertical-align`); `is-wrong` (red tint); `is-correct`; `guessnumber--done`; `[data-guess-hint]` and `[data-guess-success]` using the **existing feedback tokens** (do not invent a second vocabulary for wrong/correct). `[data-guess-live]` is a plain grouping node with no styling of its own.

- [ ] **Step 2: Pin the selectors with a source assertion**

A screenshot-only gate lets a later refactor silently drop the rules, so this repo consistently pins new
element styling with a source test (`tests/test_twocolumn_css.py`, `tests/test_callout_css.py`,
`tests/test_stepper_assets.py::test_css_has_layer_b_and_hidden_rules`). Create
`tests/test_guessnumber_css.py` in that shape. **Scope every assertion to this element** — a bare
`".is-correct" in css` already passes today (`courses.css` has `.question__verdict.is-correct`), so it
would pin nothing. Assert the element-qualified selectors your Step 1 rules actually introduce, e.g.
`.guessnumber`, `.guessnumber--done`, and the input states as you wrote them
(`.guessnumber input.is-wrong` / `.guessnumber input.is-correct` or equivalent).

```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_gn uv run pytest tests/test_guessnumber_css.py -q
```
Expected: PASS.

- [ ] **Step 4: Run the frontend-design skill**

Run `frontend-design` over both the student widget and the authoring form.

- [ ] **Step 5: Verify by screenshot in BOTH themes**

Drive a lesson containing the element with Playwright (foreground). Capture light and dark. Self-critique before proceeding: is the input baseline aligned with the rendered math? Are hint and success legible in both themes?

- [ ] **Step 6: Commit**

```bash
git add courses/static/courses/css/ tests/test_guessnumber_css.py
git commit -m "style(guessnumber): inline widget + verdict states (light+dark)"
```

---

### Task 13: i18n catalogs

Spec §9.

**Files:**
- Modify: `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po`

- [ ] **Step 1: Extract**

```bash
uv run python manage.py makemessages -l en -l pl
```

- [ ] **Step 2: Fill in the Polish, and clear fuzzy flags**

Per spec §9's table. New: `Guess the number`/`Zgadnij liczbę`; `Correct!`/`Dobrze!`; `The number is too big, try again.`/`Liczba jest za duża, spróbuj ponownie.`; `The number is too small, try again.`/`Liczba jest za mała, spróbuj ponownie.`; the four form errors; `Prompt with the answer`/`Treść z odpowiedzią`; `Mark the answer with {{42}} (exactly once).`/`Zaznacz odpowiedź jako {{42}} (dokładnie raz).`; `Success message`/`Komunikat po poprawnej odpowiedzi`; `Your answer`/`Twoja odpowiedź`; the secrecy hint; `guess_number data`/`dane guess_number`.

**Do NOT add** `Check`, `Tolerance (±, optional)`, `Enter a number (e.g. 3.14 or 3,14).`, `Tolerance cannot be negative.`, `Element '%(el)s': tolerance must not be negative.`, `stem` — all exist; a duplicate `msgid` makes `msgfmt` reject the catalog.

**Remove any `#, fuzzy` flags** `makemessages` adds — a fuzzy entry is not used at runtime.

- [ ] **Step 3: Write a real catalog test — `tests/test_i18n_catalog.py` does NOT test the catalogs**

That file (21 lines) contains one test, `test_catalog_heading_translated_to_polish`, which GETs
`courses:catalog` and asserts the **course browse page** renders in Polish. It is about the catalog
*page*, not the `.po` catalogs, and passes whether or not a single guess-number msgid was added,
translated, or left fuzzy. `compilemessages` alone only catches duplicate msgids.

Create `tests/test_i18n_guessnumber.py`, modelled on **`tests/test_i18n_stepper.py`**:

```python
import pytest
from django.utils import translation

MSGIDS = [
    "Guess the number",
    "Correct!",
    "The number is too big, try again.",
    "The number is too small, try again.",
    "Write the answer in double braces, e.g. {{42}}.",
    "The answer must be a number (e.g. 42 or 3,14).",
    "Prompt with the answer",
    "Success message",
    "Your answer",
]


@pytest.mark.parametrize("msgid", MSGIDS)
def test_polish_translation_exists(msgid):
    with translation.override("pl"):
        assert translation.gettext(msgid) != msgid  # untranslated/fuzzy would return the msgid
```

- [ ] **Step 4: Compile and test**

```bash
uv run python manage.py compilemessages
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_gn uv run pytest tests/test_i18n_guessnumber.py -q
```
Expected: PASS. A fuzzy entry returns the msgid unchanged, so this also catches the `makemessages`
fuzzy-flag gotcha.

- [ ] **Step 5: Commit**

```bash
git add locale/ tests/test_i18n_guessnumber.py
git commit -m "i18n(guessnumber): EN/PL catalog entries"
```

---

### Task 14: Rename the Two-column label to "Columns"

Spec §8. **Label-only** — model/form/transfer keys stay `twocolumnelement`/`twocolumn`/`two_column`. No migration, no `FORMAT_VERSION` bump. Justified: the element already supports 2–4 columns, so "Two columns" is a misnomer.

**Files:**
- Modify: `courses/templatetags/courses_manage_extras.py`, `courses/views_manage.py`, `templates/courses/manage/editor/_add_menu.html`, `templates/courses/manage/editor/_edit_twocolumn.html`, `courses/element_forms.py`, `locale/{en,pl}/LC_MESSAGES/django.po`

- [ ] **Step 1: Change the four sites**

- `courses_manage_extras.py`: `_("Two columns")` → `_("Columns")`
- `views_manage.py`: `_EDITOR_TYPE_LABELS["twocolumn"]`, `gettext_lazy("Two-column layout")` → `gettext_lazy("Columns")`
- `_add_menu.html`: `{% trans "Two-column layout" %}` → `{% trans "Columns" %}`
- **`_edit_twocolumn.html`: `{% trans "Columns" %}` → `{% trans "Number of columns" %}`** — **this is the site that actually fixes the doubling.** The template hardcodes the label and renders `{{ form.column_count }}` bare, so `TwoColumnElementForm`'s `label=` is never rendered; changing only the form would produce no visual change at all.
- `element_forms.py`: `TwoColumnElementForm.column_count`'s `label=_("Columns")` → `_("Number of columns")`, in lockstep, purely to keep the msgid set clean (it is dead in this template).

- [ ] **Step 2: Catalogs**

Append `"Number of columns"` to `MSGIDS` in `tests/test_i18n_guessnumber.py` **in this task** — it is
created here, so Task 13 could not have extracted or translated it.


`"Two columns"` and `"Two-column layout"` become unreferenced and drop out. `"Columns"` **already exists** (PL `Kolumny`) — do not re-mint. Add `"Number of columns"` / `Liczba kolumn`.

```bash
uv run python manage.py makemessages -l en -l pl && uv run python manage.py compilemessages
```

- [ ] **Step 3: Verify the doubling is gone**

Screenshot the two-column editor row: the heading should read "Columns" and the field label "Number of columns" — not "Columns" twice.

- [ ] **Step 4: Run the affected suites**

```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_gn uv run pytest tests/test_manage_editor_menu.py tests/test_i18n_guessnumber.py -q
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_gn uv run pytest -m e2e tests/test_e2e_twocolumn.py
```
(The e2e file needs its own `-m e2e` run — the default addopts deselect it.)
Expected: PASS — no test asserts either old label (verified), and this removes translatable strings, which is exactly the case that has broken catalog tests before.

- [ ] **Step 5: Commit**

```bash
git add courses/ templates/ locale/
git commit -m "i18n(twocolumn): rename the element label to \"Columns\"

The element supports 2-4 columns, so \"Two columns\" was a misnomer. Label-only:
keys unchanged, no migration. _edit_twocolumn.html is the site that matters —
the form's label= is dead code there — and the count field becomes \"Number of
columns\" so the editor doesn't show \"Columns\" twice."
```

---

### Task 15: End-to-end

Spec §6. **Foreground only.**

**Files:**
- Create: `tests/test_e2e_guessnumber.py`

- [ ] **Step 1: Write the e2e**

Model setup on `tests/test_e2e_markdone.py`. Drive the **real gestures** — never `page.evaluate` shortcuts (an e2e that bypasses the real click ships broken UX green).

Cases:
1. **Too big:** type `43`, click Check → `[data-guess-hint]` visible with the "too big" text; input has `is-wrong`.
2. **Too small:** type `41`, Check → "too small".
3. **Correct:** type `42`, Check → `[data-guess-success]` visible; input `is-correct` + `readOnly`; form has `guessnumber--done`; Check `disabled`.
4. **Live region:** `[data-guess-live]` contains the verdict text on each outcome.
5. **Typing clears:** after a wrong verdict, typing hides the hint again.
6. **Enter submits** (not just the Check click).
7. **Polish comma:** type `40401,5` into the real input against a `40401.5` target → correct. **This is the one test that catches a `type="number"` input silently returning `""` for a comma** — every other comma test is server- or form-side and passes regardless.
8. **Post-lock inertness (behavioural, not just attributes):** after a correct answer, press Enter in
   the input; assert no navigation occurred and the success state is unchanged. Case 3 checks the
   attributes; this checks that the two guards (`done` in the handler, `disabled` on the button)
   actually hold.
9. **Revealed behind a "Show more" gate, a wrong guess does not re-hide it.** Seed
   `[text][reveal gate][guess element]`, click "Show more", submit a wrong guess, then assert the
   guess element is still visible and the page did not navigate. This is the regression the whole
   no-`<form>` decision exists to prevent: with a form, an un-armed Enter would reload and wipe
   reveal.js's in-memory cascade, forcing the reader to re-reveal.
10. **Nested in tabs:** the element works inside a tab panel.

- [ ] **Step 2: Run it (foreground)**

```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_gn uv run pytest -m e2e tests/test_e2e_guessnumber.py
```
Expected: PASS.

**`-m e2e` is mandatory.** `pyproject.toml` sets `addopts = "-q -m 'not e2e'"`, so without it every test in
the file is deselected and pytest exits 5 ("no tests ran") — the task's entire deliverable would
silently never execute.

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e_guessnumber.py
git commit -m "test(guessnumber): e2e verdicts, lock, Enter, comma, nesting

The comma case drives the real input: a type=number field returns '' for
'40401,5' in Chrome/FF, and every other comma test would still pass."
```

---

### Task 16: Full-suite DoD

- [ ] **Step 1: Lint + format**

```bash
uv run ruff check . && uv run ruff format --check .
```
Expected: no findings.

- [ ] **Step 2: Migrations are complete**

```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_gn uv run python manage.py makemigrations --check --dry-run
```
Expected: "No changes detected".

- [ ] **Step 3: Full suite**

```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_gn uv run pytest -q
```
Expected: PASS.

If a failure is an **unrelated pre-existing flaky**, do NOT patch it inside this diff: prove it is pre-existing (does it fail on `origin/master` too?) and report it for its own branch/PR.

- [ ] **Step 4: Commit any fixes**

```bash
git add -A && git commit -m "chore(guessnumber): full-suite green"
```
