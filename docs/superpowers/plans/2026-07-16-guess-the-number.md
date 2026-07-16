# Guess the number — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `GuessNumberElement` — an ungraded numeric self-check with "too big"/"too small" directional feedback — as the 31st unit element, and rename the Two-column element's label to "Columns".

**Architecture:** A plain `ElementBase` subclass (NOT a `QuestionElement`: it records no marks, because the element is built around repeated wrong guesses). Authors write one stem containing a single `{{42}}` token; a new `courses/guessnumber.py` module (modelled on `courses/switchgate.py`) parses it into a `￿0￿` token-stem plus a `target` Decimal. A `render_guess_number` template tag splices an inline input + Check button into the stem. A flat, soft-pk JSON endpoint compares the guess with `parse_number` and returns a verdict; nothing is persisted.

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
  `U+FFFF`, and the file-writing tools silently corrupt it to `U+FFFC` (object-replacement). A test
  asserting against a literal sentinel therefore compares the *wrong character* and fails in a way that
  looks like a logic bug. This plan was written with 13 such corruptions and they were stripped; do not
  reintroduce them. Always reference it in code:
  - `fillblank.SENTINEL` — the bare character
  - `guessnumber.SENTINEL_TOKEN` — the full `<S>0<S>` token
  - For a *stray* sentinel (the transfer stray-check test), build it:
    `STRAY_SENTINEL = fillblank.SENTINEL + "9" + fillblank.SENTINEL`
  To check a file for corruption, grep it for the object-replacement character
  (`python -c "import io,sys; print(io.open(sys.argv[1],encoding='utf-8').read().count(chr(0xFFFC)))" <file>`)
  — expect `0`. Note this plan itself is expected to contain **zero** such characters; the only
  mentions of the corrupted codepoint anywhere in it are by escape (`chr(0xFFFC)`), never literal.

**Ordering constraints (do not reorder):**
- Task 10 (transfer `SERIALIZERS`) must precede Task 11 (`NESTABLE_TYPE_KEYS`) — `tests/test_filltable_transfer.py` asserts the invariant `NESTABLE_TYPE_KEYS <= set(SERIALIZERS)`.
- Task 3 flips `len(ELEMENT_MODELS)` 30→31 and must fix **both** count asserts in the same commit.

---

## File Structure

**New files**
| Path | Responsibility |
|---|---|
| `courses/guessnumber.py` | Token-stem parse/render/format helpers. Pure, no DB. |
| `courses/migrations/0049_guessnumberelement.py` | Model + `alter_element_content_type`. |
| `templates/courses/elements/guessnumberelement.html` | One-liner: delegates to the render tag. |
| `templates/courses/manage/editor/_edit_guessnumber.html` | Authoring form partial. |
| `courses/static/courses/js/guessnumber.js` | Submit handling, verdict application. |
| `tests/test_guessnumber_module.py` | Task 2 unit tests. |
| `tests/test_guessnumber_form.py` | Task 4 form tests. |
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
- Test: `tests/test_fillblank.py` (existing — must stay green)

- [ ] **Step 1: Rename both helpers and all call sites**

In `courses/fillblank.py`, rename `_mask_math` → `mask_math` and `_restore_math` → `restore_math`, updating every internal call site (`parse`, and any other reference).

- [ ] **Step 2: Verify nothing else referenced the private names**

```bash
grep -rn "_mask_math\|_restore_math" courses/ tests/
```
Expected: no output (all references renamed).

- [ ] **Step 3: Run the existing fill-blank suite**

```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_gn uv run pytest tests/test_fillblank.py -q
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
Authors type ``{{42}}``; it is stored as the ￿0￿ sentinel token (reusing
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
- Create: `courses/migrations/0049_guessnumberelement.py` (generated)
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
    repeatedly, which is why it is not a QuestionElement. `stem` holds the ￿0￿
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

Spec §2.3.2 / §2.3.3. All three parts are load-bearing; omitting `__init__` leaves `to_author_stem` with no caller and omitting `save()` writes `target=None` → `IntegrityError`.

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

In `courses/element_forms.py` (import `gettext_lazy`, `guessnumber`, `check_decimal_str`, `TransferError` as needed):

```python
# gettext_LAZY is mandatory: an eager gettext() here froze labels to English
# once already (PR #46). Keyed by GuessNumberError.code.
_GUESS_STEM_ERRORS = {
    "token_count": gettext_lazy("Write the answer in double braces, e.g. {{42}}."),
    "alternatives": gettext_lazy(
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
            # Show the author their token, not the raw ￿0￿ stem — without this
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

    def save(self, commit=True):
        self.instance.target = self.parsed_target
        return super().save(commit)
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
- Modify: `courses/templatetags/courses_extras.py`
- Create: `templates/courses/elements/guessnumberelement.html`
- Create: `tests/test_guessnumber_render.py`

**Interfaces:**
- Produces: `{% render_guess_number el eid %}`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_guessnumber_render.py`:

```python
from decimal import Decimal

import pytest

from courses.models import GuessNumberElement
from courses.templatetags.courses_extras import render_guess_number


@pytest.mark.django_db
def test_renders_contract_hooks():
    el = GuessNumberElement.objects.create(stem="x" + guessnumber.SENTINEL_TOKEN + "y", target=Decimal("42"))
    html = render_guess_number(el, 7)
    assert 'class="guessnumber"' in html and "data-guessnumber" in html
    assert 'data-element-pk="7"' in html
    assert "/element/7/guessnumber-check/" in html  # data-check-url
    assert "action=" not in html                    # no action: no-JS must not POST JSON
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
def test_widget_is_spliced_inline_inside_an_enclosing_paragraph():
    # sanitize_html allows <p>; the parser hoists a <form>/<div> out of an open
    # <p>, splitting the stem. Only inline markup may be spliced.
    el = GuessNumberElement.objects.create(
        stem="<p>201 = " + guessnumber.SENTINEL_TOKEN + " done</p>", target=Decimal("42")
    )
    html = render_guess_number(el, 1)
    body = html[html.index("<p>") : html.index("</p>")]
    assert "data-guess-input" in body  # input stayed inside the paragraph
```

- [ ] **Step 2: Run to verify it fails**

```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_gn uv run pytest tests/test_guessnumber_render.py -q
```
Expected: FAIL — `ImportError: cannot import name 'render_guess_number'`.

- [ ] **Step 3: Write the tag**

In `courses/templatetags/courses_extras.py`, modelled on `render_switch_gate`:

```python
@register.simple_tag
def render_guess_number(el, eid):
    """Render the numeric input spliced into the stem at its ￿0￿ token.

    The <form> WRAPS the stem (it is the container); only inline markup is
    spliced, because the parser hoists block elements out of an enclosing <p>.
    See courses.guessnumber."""
    check_url = reverse("courses:guessnumber_check", args=[eid])
    widget = format_html(
        '<input data-guess-input type="text" inputmode="decimal" '
        'aria-label="{}"><button data-guess-check type="submit" hidden>{}</button>',
        _("Your answer"),
        _("Check"),
    )
    body = guessnumber.render_stem(el.stem, widget)
    msg = el.success_message or ""
    has_text = bool(strip_tags(msg).strip())
    success = mark_safe(msg) if has_text else format_html("{}", _("Correct!"))  # noqa: S308 — sanitized at save()
    return format_html(
        '<form class="guessnumber" data-guessnumber data-element-pk="{}" '
        'data-check-url="{}" data-msg-high="{}" data-msg-low="{}">{}'
        '<div data-guess-live aria-live="polite">'
        '<p data-guess-hint hidden></p>'
        '<div data-guess-success hidden>{}</div></div></form>',
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

- [ ] **Step 4: Run to verify it passes**

```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_gn uv run pytest tests/test_guessnumber_render.py -q
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add courses/templatetags/courses_extras.py templates/courses/elements/guessnumberelement.html tests/test_guessnumber_render.py
git commit -m "feat(guessnumber): render tag + student template

The <form> wraps the stem and only the inline input/button is spliced at the
token — a spliced <form> would be hoisted out of an enclosing <p>. Blank-message
fallback is server-side and tests text content, not truthiness (the RTE posts
<p><br></p>)."
```

---

### Task 6: Check endpoint + route

Spec §4.1. Soft pk lookup, persists nothing.

**Files:**
- Modify: `courses/views.py`, `courses/urls.py`
- Create: `tests/test_guessnumber_endpoint.py`

**Interfaces:**
- Produces: `courses:guessnumber_check`; response `{"correct": bool, "direction": "high"|"low"|null}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_guessnumber_endpoint.py`. Follow `tests/test_switchgate_endpoint.py`'s fixtures for course/unit/enrolment setup and `tests.factories.TEST_PASSWORD` (never a literal password).

```python
from decimal import Decimal

import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import GuessNumberElement
from courses.models import QuestionResponse


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
def test_verdicts(client_enrolled, gn_eid, guess, correct, direction):
    r = _post(client_enrolled, gn_eid, guess)
    assert r.status_code == 200
    assert r.json() == {"correct": correct, "direction": direction}


@pytest.mark.django_db
def test_tolerance_boundary_is_inclusive(client_enrolled, gn_tolerant_eid):
    # target=42, tolerance=0.5 -> exactly 42.5 is CORRECT
    assert _post(client_enrolled, gn_tolerant_eid, "42.5").json()["correct"] is True
    assert _post(client_enrolled, gn_tolerant_eid, "42.6").json() == {
        "correct": False,
        "direction": "high",
    }


@pytest.mark.django_db
@pytest.mark.parametrize("guess", ["42,0", "42.0"])
def test_comma_and_period_decimals_both_correct(client_enrolled, gn_eid, guess):
    assert _post(client_enrolled, gn_eid, guess).json()["correct"] is True


@pytest.mark.django_db
def test_missing_pk_is_benign_200(client_enrolled):
    r = _post(client_enrolled, 999999, "42")
    assert r.status_code == 200
    assert r.json() == {"correct": False, "direction": None}


@pytest.mark.django_db
def test_wrong_type_pk_is_benign_200(client_enrolled, other_element_eid):
    r = _post(client_enrolled, other_element_eid, "42")
    assert r.status_code == 200
    assert r.json() == {"correct": False, "direction": None}


@pytest.mark.django_db
def test_no_course_access_is_403(client_stranger, gn_eid):
    assert _post(client_stranger, gn_eid, "42").status_code == 403


@pytest.mark.django_db
def test_get_not_allowed(client_enrolled, gn_eid):
    url = reverse("courses:guessnumber_check", args=[gn_eid])
    assert client_enrolled.get(url).status_code == 405


@pytest.mark.django_db
def test_anonymous_redirected(client, gn_eid):
    assert _post(client, gn_eid, "42").status_code in (302, 403)


@pytest.mark.django_db
def test_nothing_is_persisted(client_enrolled, gn_eid):
    _post(client_enrolled, gn_eid, "43")
    assert QuestionResponse.objects.count() == 0
```

Add the fixtures (`gn_eid`, `gn_tolerant_eid`, `other_element_eid`, `client_enrolled`, `client_stranger`) in the same file, mirroring the switchgate endpoint tests.

- [ ] **Step 2: Run to verify it fails**

```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_gn uv run pytest tests/test_guessnumber_endpoint.py -q
```
Expected: FAIL — `NoReverseMatch: 'guessnumber_check' not found`.

- [ ] **Step 3: Write the view + route**

In `courses/views.py`, next to `switchgate_check`:

```python
@require_POST
@login_required
def guessnumber_check(request, element_pk):
    """Compare a guess with the target; answer correct / too-high / too-low.

    Soft pk lookup (200 on a missing or wrong-type pk, like switchgate_check —
    NOT fillgate_check's get_object_or_404), so pks cannot be probed to tell
    element types apart. Persists nothing: no QuestionResponse, no UnitProgress.
    """
    miss = JsonResponse({"correct": False, "direction": None})
    join = Element.objects.filter(pk=element_pk).select_related("unit__course").first()
    if join is None or not isinstance(join.content, GuessNumberElement):
        return miss
    _require_course_access(request.user, join.unit.course)  # raises PermissionDenied -> 403
    el = join.content
    n = parse_number(request.POST.get("guess", ""))
    if n is None:
        return miss
    if abs(n - el.target) <= el.tolerance:
        return JsonResponse({"correct": True, "direction": None})
    return JsonResponse(
        {"correct": False, "direction": "high" if n > el.target else "low"}
    )
```

Use whichever access helper `switchgate_check` uses (match it exactly). In `courses/urls.py`, beside the sibling check routes:

```python
path(
    "element/<int:element_pk>/guessnumber-check/",
    views.guessnumber_check,
    name="guessnumber_check",
),
```

- [ ] **Step 4: Run to verify it passes**

```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_gn uv run pytest tests/test_guessnumber_endpoint.py -q
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add courses/views.py courses/urls.py tests/test_guessnumber_endpoint.py
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

Create `tests/test_guessnumber_context.py`. Model the tab-nesting fixtures on `tests/test_context_stepper.py`.

```python
@pytest.mark.django_db
def test_has_math_true_for_math_in_stem(lesson_with_gn_math_stem, user):
    assert build_lesson_context(lesson_with_gn_math_stem, user)["has_math"] is True


@pytest.mark.django_db
def test_has_math_true_for_math_in_success_message(lesson_with_gn_math_success, user):
    # Independently of the stem — an unknown type returns False and loads NO KaTeX.
    assert build_lesson_context(lesson_with_gn_math_success, user)["has_math"] is True


@pytest.mark.django_db
def test_has_guess_number_top_level(lesson_with_gn, user):
    assert build_lesson_context(lesson_with_gn, user)["has_guess_number"] is True


@pytest.mark.django_db
def test_has_guess_number_nested_in_tab(lesson_with_gn_in_tab, user):
    # build_lesson_context's `elements` list is parent__isnull=True, so a flag
    # computed from it misses nested children and the JS never loads.
    assert build_lesson_context(lesson_with_gn_in_tab, user)["has_guess_number"] is True


@pytest.mark.django_db
def test_has_guess_number_nested_in_column(lesson_with_gn_in_column, user):
    assert build_lesson_context(lesson_with_gn_in_column, user)["has_guess_number"] is True
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

  function initOne(form) {
    if (form.dataset.guessnumberReady === "1") return;
    form.dataset.guessnumberReady = "1";

    var input = form.querySelector("[data-guess-input]");
    var check = form.querySelector("[data-guess-check]");
    var hint = form.querySelector("[data-guess-hint]");
    var success = form.querySelector("[data-guess-success]");
    var pk = form.getAttribute("data-element-pk");
    var url = form.getAttribute("data-check-url");
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

    form.addEventListener("submit", function (e) {
      e.preventDefault();              // without this, Enter/click NAVIGATES
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
            if (check) check.disabled = true;  // disabled DOES block implicit submit
            form.classList.add("guessnumber--done");
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
    });
  }

  function init(root) {
    (root || document).querySelectorAll("[data-guessnumber]").forEach(initOne);
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

preventDefault first (else Enter navigates), in-flight + post-lock guards, and
Check is disabled on success — disabled is the only thing that blocks implicit
submission. No typesetMath: math.js + editor.js already cover both paths."
```

---

### Task 9: Editor authoring surface

Spec §2.4 / §7 / §9. The `_edit_` partial is mandatory: its absence 500s the instant the palette card is clicked.

**Files:**
- Create: `templates/courses/manage/editor/_edit_guessnumber.html`
- Modify: `templates/courses/manage/editor/_add_menu.html`, `templates/courses/manage/_icon_sprite.html`, `courses/views_manage.py`, `courses/templatetags/courses_manage_extras.py`
- Create: `tests/test_guessnumber_authoring.py`

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.django_db
def test_element_add_renders_the_edit_partial(client_author, unit):
    # element_add -> _host_form -> _edit_guessnumber. Row/palette tests never
    # reach this path; the reveal-gate partial was missed exactly this way.
    r = client_author.get(reverse("courses:manage_element_add", args=[unit.pk]) + "?type=guessnumber")
    assert r.status_code == 200


@pytest.mark.django_db
def test_element_add_post_creates(client_author, unit):
    r = client_author.post(
        reverse("courses:manage_element_add", args=[unit.pk]),
        {"type": "guessnumber", "stem": "{{42}}", "tolerance": "", "success_message": ""},
    )
    assert r.status_code == 200


@pytest.mark.django_db
def test_editor_loads_the_enhancer_script(client_author, unit):
    # editor.html forgetting the <script> shipped gallery and reveal-gate with a
    # dead preview. Guard it.
    r = client_author.get(reverse("courses:manage_editor", args=[unit.pk]))
    assert "guessnumber.js" in r.content.decode()


@pytest.mark.django_db
def test_palette_card_present(client_author, unit):
    r = client_author.get(reverse("courses:manage_editor", args=[unit.pk]))
    assert 'data-add-type="guessnumber"' in r.content.decode()


@pytest.mark.django_db
def test_each_rte_field_has_its_own_toolbar_wrapper(client_author, unit):
    # wireRte resolves a toolbar via closest(".el-editor--text"); two RTE fields
    # sharing one wrapper means one Bold click mutates both surfaces.
    html = client_author.get(
        reverse("courses:manage_element_add", args=[unit.pk]) + "?type=guessnumber"
    ).content.decode()
    assert html.count("el-editor--text") == 2
    assert html.count("data-rte-toolbar") == 2
    assert html.count("data-rte-source") == 2
```

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
- `courses/templatetags/courses_manage_extras.py`: `_ELEMENT_LABELS["guessnumberelement"] = _("Guess the number")`. **No `element_summary` branch** — its generic `stem` fallback already rewrites `￿N￿` → `___`.

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

```python
from courses import fillblank
from courses import guessnumber

# Built, never typed: a literal U+FFFF is corrupted to U+FFFC on write.
STRAY_SENTINEL = fillblank.SENTINEL + "9" + fillblank.SENTINEL


@pytest.mark.django_db
def test_serializer_registered():
    assert "guess_number" in SERIALIZERS


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


def test_validator_rejects_missing_key():
    with pytest.raises(TransferError):
        _val_guess_number({"stem": guessnumber.SENTINEL_TOKEN, "target": "42", "tolerance": "0"}, "e1")


def test_validator_rejects_unknown_key():
    with pytest.raises(TransferError):
        _val_guess_number(
            {"stem": guessnumber.SENTINEL_TOKEN, "target": "42", "tolerance": "0",
             "success_message": "", "extra": 1}, "e1"
        )


def test_non_string_stem_is_transfer_error_not_500():
    # _check_token_stem runs _TOKEN_RE.finditer(stem) -> TypeError (500) on an
    # int. check_str must run FIRST.
    with pytest.raises(TransferError):
        _val_guess_number(
            {"stem": 42, "target": "42", "tolerance": "0", "success_message": ""}, "e1"
        )


def test_stray_sentinel_rejected():
    with pytest.raises(TransferError):
        _val_guess_number(
            {"stem": guessnumber.SENTINEL_TOKEN + STRAY_SENTINEL, "target": "42", "tolerance": "0",
             "success_message": ""}, "e1"
        )


def test_negative_tolerance_rejected():
    with pytest.raises(TransferError):
        _val_guess_number(
            {"stem": guessnumber.SENTINEL_TOKEN, "target": "42", "tolerance": "-1",
             "success_message": ""}, "e1"
        )


@pytest.mark.django_db
def test_builder_sanitises_the_imported_stem():
    # stem is deliberately out of the model's save(), so an unsanitised archive
    # stem would be stored verbatim and then mark_safe'd by render_stem.
    el = _build_guess_number(
        {"stem": "<script>x</script>" + guessnumber.SENTINEL_TOKEN, "target": "42",
         "tolerance": "0", "success_message": ""}, unit=None
    )
    assert "<script>" not in el.stem
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

`payloads.py` — `_val_guess_number`, registered in `VALIDATORS`, in **this order**:

```python
def _val_guess_number(data, elid):
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

`importer.py` — `_build_guess_number`, registered in `BUILDERS`:

```python
def _build_guess_number(data, unit):
    return GuessNumberElement.objects.create(
        stem=sanitize_html(data["stem"]),  # stem is out of save(); sanitise here
        target=Decimal(data["target"]),
        tolerance=Decimal(data["tolerance"]),
        success_message=data["success_message"],  # save() sanitises this one
    )
```

Match each registry's existing call signature exactly.

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

- [ ] **Step 1: Write the rules**

Cover: the inline row (`input` + Check aligned against a KaTeX-rendered `\(201^2=\)` baseline — the one genuinely new design problem, decide it deliberately rather than leaving default `vertical-align`); `is-wrong` (red tint); `is-correct`; `guessnumber--done`; `[data-guess-hint]` and `[data-guess-success]` using the **existing feedback tokens** (do not invent a second vocabulary for wrong/correct). `[data-guess-live]` is a plain grouping node with no styling of its own.

- [ ] **Step 2: Run the frontend-design skill**

Run `frontend-design` over both the student widget and the authoring form.

- [ ] **Step 3: Verify by screenshot in BOTH themes**

Drive a lesson containing the element with Playwright (foreground). Capture light and dark. Self-critique before proceeding: is the input baseline aligned with the rendered math? Are hint and success legible in both themes?

- [ ] **Step 4: Commit**

```bash
git add courses/static/courses/css/
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

- [ ] **Step 3: Compile and test**

```bash
uv run python manage.py compilemessages
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_gn uv run pytest tests/test_i18n_catalogs.py -q
```
Expected: PASS (find the catalog test's real filename first).

- [ ] **Step 4: Commit**

```bash
git add locale/
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

`"Two columns"` and `"Two-column layout"` become unreferenced and drop out. `"Columns"` **already exists** (PL `Kolumny`) — do not re-mint. Add `"Number of columns"` / `Liczba kolumn`.

```bash
uv run python manage.py makemessages -l en -l pl && uv run python manage.py compilemessages
```

- [ ] **Step 3: Verify the doubling is gone**

Screenshot the two-column editor row: the heading should read "Columns" and the field label "Number of columns" — not "Columns" twice.

- [ ] **Step 4: Run the affected suites**

```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_gn uv run pytest tests/test_e2e_twocolumn.py tests/test_manage_editor_menu.py tests/test_i18n_catalogs.py -q
```
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
8. **Nested in tabs:** the element works inside a tab panel.

- [ ] **Step 2: Run it (foreground)**

```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_gn uv run pytest tests/test_e2e_guessnumber.py -q
```
Expected: PASS.

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
