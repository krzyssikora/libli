# Phase 2d-i — DnD Substrate + drag-fill-blanks & match-pairs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two new question types — drag-fill-blanks and match-pairs — built on a shared drag-and-drop substrate (a `<select>`-per-target no-JS base with a vanilla-JS drag enhancement, a uniform token-text answer payload, and per-target marking), reusing the 2a/2b/2c marking & quiz machinery with no new views.

**Architecture:** Each type is a `QuestionElement` subclass (own table + a sub-row table) that implements `build_answer` + `mark` and a `REVEAL_TEMPLATE`; both reuse a new pure module `courses/dnd.py` (`build_pool`, `mark_slots`, `render_selects`, `render_match_rows`). The `<select>`s are the source of truth and the no-JS fallback; `static/courses/dnd.js` layers pointer drag-and-drop on top by writing token text into the selects. The types plug into the existing `check_answer` (lesson) and `quiz_answer`/`quiz_finish`/`quiz_results` (quiz) dispatch generically; the work is the two types plus a set of per-type registration touchpoints across `views.py`, `views_manage.py`, `builder.py`, and the editor templates.

**Tech Stack:** Python 3.13 + Django 5.2, PostgreSQL, pytest + factory_boy (real Postgres), Playwright (e2e), vanilla JS (no DnD library), KaTeX for math rendering. Run commands with `uv run …`.

## Global Constraints

Every task's requirements implicitly include this section.

- **No new dependency.** The drag JS is small vanilla JS — no DnD library. No new Python packages.
- **No-JS parity is mandatory.** Every action (answer, finish) works with JavaScript disabled, via the native `<select>`s + full-page form submit. The drag chips and drop-slots are **JS-injected** — absent entirely with JS off (no orphaned UI). Verified by no-JS e2e.
- **Server-authoritative marking.** Submitted token *texts* are validated server-side for pool membership (on the normalized form); forged/non-member tokens score wrong, never error. The client cannot self-report correctness.
- **Token fields are "plain text + KaTeX delimiters, never HTML-sanitised"**, `max_length=500` (matching `Choice.text`). They **adopt the platform's shared math-input widget (KaTeX render + MathLive entry) wherever other KaTeX-bearing fields use it** — that widget is a **cross-cutting authoring enhancement owned by separate, in-flight work, NOT built in 2d-i** (it is authoring-input only; storage and render are unchanged). Do not build MathLive here; just author the token fields as ordinary KaTeX-bearing text inputs/textareas so they inherit it.
- **Reuse the 2c persistence/withhold/scoring machinery unchanged.** No new view functions, URLs, or models beyond the two types + their sub-rows. `QuestionResponse.latest_answer` stores the token-text list as-is.
- **Decimal conventions from 2c.** `mark()` returns a `float` `fraction` in `[0,1]`; the quiz boundary converts to `Decimal` (`fraction × max_marks`) — unchanged, no new code here.
- **Answer payload = list of token-text strings**, one per target, `""` for unfilled. Token text, never a positional index. Correctness is by normalized text, so it is independent of pool order and stable across author edits (only deleting the exact chosen token invalidates it).
- **One canonical pool builder** `dnd.build_pool(question)` is used by **both** render and mark, so they can never disagree.

---

### Task 1: Models + migration + factories

**Files:**
- Modify: `courses/models.py` (add `DragFillBlankQuestionElement`, `DragBlank`, `MatchPairQuestionElement`, `MatchPair` near the other `QuestionElement` subclasses, after `FillBlankQuestionElement`/`Blank`)
- Create: `courses/migrations/0017_dragfill_matchpair.py` (generated)
- Modify: `tests/factories.py` (add + re-export the four factories)
- Test: `tests/test_questions_2d_models.py`

**Interfaces:**
- Produces:
  - `DragFillBlankQuestionElement(QuestionElement)` — `distractors: TextField`, `dragblanks` reverse rel, `REVEAL_TEMPLATE = "courses/elements/_reveal_dragfill.html"`, `expected_tokens() -> list[str]`.
  - `DragBlank(question FK related_name="dragblanks", correct_token CharField(500), order OrderField)`.
  - `MatchPairQuestionElement(QuestionElement)` — `distractors: TextField`, `pairs` reverse rel, `REVEAL_TEMPLATE = "courses/elements/_reveal_matchpair.html"`, `expected_tokens() -> list[str]`.
  - `MatchPair(question FK related_name="pairs", left CharField(500), right CharField(500), order OrderField)`.
  - Factories: `DragFillBlankQuestionElementFactory`, `DragBlankFactory`, `MatchPairQuestionElementFactory`, `MatchPairFactory`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_questions_2d_models.py
import pytest

from courses.models import (
    DragBlank,
    DragFillBlankQuestionElement,
    MatchPair,
    MatchPairQuestionElement,
)


@pytest.mark.django_db
def test_dragfill_expected_tokens_in_order():
    q = DragFillBlankQuestionElement.objects.create(stem="￿0￿ ￿1￿", distractors="Rome")
    DragBlank.objects.create(question=q, correct_token="Paris")
    DragBlank.objects.create(question=q, correct_token="Madrid")
    # The U+FFFF token sentinel must survive QuestionElement.save()'s sanitize_html
    # (nh3.clean) — render_selects/mark depend on it, exactly as fill-blank does.
    q.refresh_from_db()
    assert "￿0￿" in q.stem and "￿1￿" in q.stem
    assert q.expected_tokens() == ["Paris", "Madrid"]
    assert q.REVEAL_TEMPLATE == "courses/elements/_reveal_dragfill.html"


@pytest.mark.django_db
def test_matchpair_expected_tokens_are_right_in_order():
    q = MatchPairQuestionElement.objects.create(stem="<p>Match</p>", distractors="Rome")
    MatchPair.objects.create(question=q, left="France", right="Paris")
    MatchPair.objects.create(question=q, left="Spain", right="Madrid")
    assert q.expected_tokens() == ["Paris", "Madrid"]
    assert [p.left for p in q.pairs.all()] == ["France", "Spain"]
    assert q.REVEAL_TEMPLATE == "courses/elements/_reveal_matchpair.html"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_questions_2d_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'DragFillBlankQuestionElement'`.

- [ ] **Step 3: Add the models**

In `courses/models.py`, after the `Blank` model (the fill-blank sub-row), add:

```python
class DragFillBlankQuestionElement(QuestionElement):
    """Drag tokens into ordered gaps. Marking is per-gap, like fill-blank, but the
    student picks a discrete chip instead of typing. `stem` stores the token-stem
    from fillblank.parse(); each gap's correct token is a DragBlank row."""

    REVEAL_TEMPLATE = "courses/elements/_reveal_dragfill.html"

    distractors = models.TextField(blank=True)  # newline-delimited extra (wrong) tokens
    elements = GenericRelation(Element)

    def expected_tokens(self):
        return [b.correct_token for b in self.dragblanks.all()]


class DragBlank(models.Model):
    question = models.ForeignKey(
        DragFillBlankQuestionElement, on_delete=models.CASCADE, related_name="dragblanks"
    )
    correct_token = models.CharField(max_length=500)  # plain text + KaTeX; never sanitised
    order = OrderField(for_fields=["question"], blank=True)

    class Meta:
        ordering = ["order", "pk"]

    def __str__(self):
        return self.correct_token


class MatchPairQuestionElement(QuestionElement):
    """Match each left label to its right token by drag/select. Marking is per-left,
    against the pair's `right`. `left` labels are targets and never enter the pool."""

    REVEAL_TEMPLATE = "courses/elements/_reveal_matchpair.html"

    distractors = models.TextField(blank=True)  # newline-delimited extra right-items
    elements = GenericRelation(Element)

    def expected_tokens(self):
        return [p.right for p in self.pairs.all()]


class MatchPair(models.Model):
    question = models.ForeignKey(
        MatchPairQuestionElement, on_delete=models.CASCADE, related_name="pairs"
    )
    left = models.CharField(max_length=500)   # target label; plain text + KaTeX
    right = models.CharField(max_length=500)  # correct token for this left; plain text + KaTeX
    order = OrderField(for_fields=["question"], blank=True)

    class Meta:
        ordering = ["order", "pk"]

    def __str__(self):
        return f"{self.left} → {self.right}"
```

- [ ] **Step 4: Generate the migration**

Run: `uv run python manage.py makemigrations courses`
Expected: creates `courses/migrations/0017_dragfill_matchpair.py` adding the four models. Open it and confirm it adds `DragFillBlankQuestionElement`, `DragBlank`, `MatchPairQuestionElement`, `MatchPair` and alters no existing table.

- [ ] **Step 5: Add factories**

In `tests/factories.py`, add the imports (with `# noqa: F401` re-export, matching the existing block) and factories:

```python
from courses.models import DragBlank  # noqa: F401
from courses.models import DragFillBlankQuestionElement  # noqa: F401
from courses.models import MatchPair  # noqa: F401
from courses.models import MatchPairQuestionElement  # noqa: F401


class DragFillBlankQuestionElementFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DragFillBlankQuestionElement

    stem = "￿0￿"
    distractors = ""


class DragBlankFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DragBlank

    question = factory.SubFactory(DragFillBlankQuestionElementFactory)
    correct_token = factory.Sequence(lambda n: f"tok{n}")


class MatchPairQuestionElementFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MatchPairQuestionElement

    distractors = ""


class MatchPairFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MatchPair

    question = factory.SubFactory(MatchPairQuestionElementFactory)
    left = factory.Sequence(lambda n: f"L{n}")
    right = factory.Sequence(lambda n: f"R{n}")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_questions_2d_models.py -v`
Expected: PASS (2 tests).

- [ ] **Step 7: Commit**

```bash
git add courses/models.py courses/migrations/0017_dragfill_matchpair.py tests/factories.py tests/test_questions_2d_models.py
git commit -m "feat(2d-i): drag-fill & match-pair models + migration + factories"
```

---

### Task 2: `dnd.build_pool`

**Files:**
- Create: `courses/dnd.py`
- Test: `tests/test_dnd_build_pool.py`

**Interfaces:**
- Consumes: `question.expected_tokens()` and `question.distractors` (Task 1); `courses.models._accepted_lines`; `courses.marking.normalize_text`.
- Produces: `dnd.build_pool(question) -> list[str]` — deduped (first normalize-key wins, correct tokens before distractors), sorted by `normalize_text`, raw strings.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dnd_build_pool.py
import pytest

from courses import dnd
from courses.models import DragBlank, DragFillBlankQuestionElement


@pytest.mark.django_db
def test_build_pool_dedups_by_normalized_text_first_wins_and_sorts():
    # "Paris" (correct) before "  paris  " (distractor): normalize-equal → first wins.
    q = DragFillBlankQuestionElement.objects.create(
        stem="￿0￿", distractors="Rome\n  paris  \nMadrid"
    )
    DragBlank.objects.create(question=q, correct_token="Paris")
    pool = dnd.build_pool(q)
    # Deduped: the correct-token "Paris" survives, the "  paris  " distractor is dropped.
    assert "Paris" in pool
    assert "  paris  " not in pool
    assert sorted(pool, key=lambda s: s.strip().casefold()) == pool  # deterministic order
    assert set(pool) == {"Paris", "Rome", "Madrid"}


@pytest.mark.django_db
def test_build_pool_drops_blank_distractor_lines():
    q = DragFillBlankQuestionElement.objects.create(stem="￿0￿", distractors="\n\nRome\n  \n")
    DragBlank.objects.create(question=q, correct_token="Paris")
    assert set(dnd.build_pool(q)) == {"Paris", "Rome"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_dnd_build_pool.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'courses.dnd'`.

- [ ] **Step 3: Write `courses/dnd.py` with `build_pool`**

```python
"""Drag-and-drop substrate shared by drag-fill-blanks and match-pairs.

The pool, the per-target marker, and the no-JS <select> renderers all live here so
the two question types (and Phase 2d-ii) cannot diverge. The pool is built ONCE by
build_pool() and used by BOTH render and mark, so they never disagree on membership.
"""

from courses.marking import normalize_text
from courses.models import _accepted_lines


def build_pool(question):
    """Deterministic, de-duplicated token pool. Source order is correct tokens
    (gap/right) first, then distractors in author order; the FIRST occurrence of each
    normalize_text key wins (so which raw form survives a collision is deterministic);
    the final list is sorted by normalize_text (presentational only — correctness is
    by text, so order never affects scoring)."""
    raw = list(question.expected_tokens()) + _accepted_lines(question.distractors)
    seen = set()
    deduped = []
    for tok in raw:
        key = normalize_text(tok)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(tok)
    return sorted(deduped, key=normalize_text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_dnd_build_pool.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add courses/dnd.py tests/test_dnd_build_pool.py
git commit -m "feat(2d-i): dnd.build_pool — canonical deduped token pool"
```

---

### Task 3: `dnd.mark_slots`

**Files:**
- Modify: `courses/dnd.py`
- Test: `tests/test_dnd_mark_slots.py`

**Interfaces:**
- Consumes: `courses.marking.normalize_text`.
- Produces: `dnd.mark_slots(expected, pool, chosen) -> (n_correct: int, reveal: tuple[dict])`. `expected`: ordered raw expected-token strings (length = n_targets, authoritative). `pool`: raw-token list (membership only, on normalized form). `chosen`: per-target submitted token-text list (defensive: missing/out-of-range/`""` → unfilled). `reveal` dicts keyed `{index, correct, accepted}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dnd_mark_slots.py
from courses import dnd


def test_mark_slots_full_partial_zero():
    expected = ["Paris", "Madrid"]
    pool = ["Madrid", "Paris", "Rome"]
    assert dnd.mark_slots(expected, pool, ["Paris", "Madrid"])[0] == 2
    assert dnd.mark_slots(expected, pool, ["Paris", "Rome"])[0] == 1
    assert dnd.mark_slots(expected, pool, ["Rome", "Rome"])[0] == 0


def test_mark_slots_unfilled_and_forged_are_wrong():
    expected = ["Paris"]
    pool = ["Paris", "Rome"]
    assert dnd.mark_slots(expected, pool, [""])[0] == 0          # unfilled
    assert dnd.mark_slots(expected, pool, ["Berlin"])[0] == 0    # not a pool member
    assert dnd.mark_slots(expected, pool, [])[0] == 0            # short list, no IndexError
    assert dnd.mark_slots(expected, pool, ["Paris", "x"])[0] == 1  # long list ok


def test_mark_slots_normalized_match_and_membership():
    # got differs only by case/space from expected AND from the pool's raw form.
    expected = ["Paris"]
    pool = ["Paris", "Rome"]
    assert dnd.mark_slots(expected, pool, ["  paris "])[0] == 1


def test_mark_slots_reveal_shape():
    n, reveal = dnd.mark_slots(["Paris", "Madrid"], ["Paris", "Madrid"], ["Paris", "X"])
    assert reveal == (
        {"index": 0, "correct": True, "accepted": "Paris"},
        {"index": 1, "correct": False, "accepted": "Madrid"},
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_dnd_mark_slots.py -v`
Expected: FAIL — `AttributeError: module 'courses.dnd' has no attribute 'mark_slots'`.

- [ ] **Step 3: Add `mark_slots` to `courses/dnd.py`**

```python
def mark_slots(expected, pool, chosen):
    """Per-target marking shared by both DnD types. `expected` length is
    authoritative (n_targets). Membership AND matching are tested on the normalized
    form, so a chip whose raw form differs from the deduped survivor still matches and
    is never falsely rejected. chosen[i] missing/out-of-range/"" → unfilled (wrong)."""
    pool_norm = {normalize_text(p) for p in pool}
    chosen = list(chosen or [])
    n_correct = 0
    reveal = []
    for i, want in enumerate(expected):
        got = chosen[i] if i < len(chosen) else ""
        got = got or ""
        got_norm = normalize_text(got)
        is_member = got != "" and got_norm in pool_norm
        ok = is_member and got_norm == normalize_text(want)
        if ok:
            n_correct += 1
        reveal.append({"index": i, "correct": ok, "accepted": want})
    return n_correct, tuple(reveal)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_dnd_mark_slots.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add courses/dnd.py tests/test_dnd_mark_slots.py
git commit -m "feat(2d-i): dnd.mark_slots — per-target normalized marking"
```

---

### Task 4: `DragFillBlankQuestionElement.build_answer` + `mark`

**Files:**
- Modify: `courses/models.py` (`DragFillBlankQuestionElement`)
- Test: `tests/test_questions_2d_dragfill_mark.py`

**Interfaces:**
- Consumes: `dnd.build_pool`, `dnd.mark_slots`, `courses.marking.MarkResult`.
- Produces: `DragFillBlankQuestionElement.build_answer(self, post) -> list[str]`; `.mark(self, answer) -> MarkResult` (reveal = tuple of `{index, correct, accepted}`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_questions_2d_dragfill_mark.py
import pytest
from django.http import QueryDict

from courses.models import DragBlank, DragFillBlankQuestionElement


def _q():
    q = DragFillBlankQuestionElement.objects.create(stem="￿0￿ ￿1￿", distractors="Rome")
    DragBlank.objects.create(question=q, correct_token="Paris")
    DragBlank.objects.create(question=q, correct_token="Madrid")
    return q


@pytest.mark.django_db
def test_build_answer_returns_raw_slot_list():
    q = _q()
    post = QueryDict(mutable=True)
    post.setlist("slot", ["Paris", "Madrid"])
    assert q.build_answer(post) == ["Paris", "Madrid"]


@pytest.mark.django_db
def test_mark_full_partial_and_reveal():
    q = _q()
    full = q.mark(["Paris", "Madrid"])
    assert full.correct is True and full.fraction == 1.0
    partial = q.mark(["Paris", "Rome"])
    assert partial.correct is False and partial.fraction == 0.5
    assert partial.reveal == (
        {"index": 0, "correct": True, "accepted": "Paris"},
        {"index": 1, "correct": False, "accepted": "Madrid"},
    )


@pytest.mark.django_db
def test_mark_empty_answer_scores_zero():
    q = _q()
    assert q.mark(q.build_answer(QueryDict())).fraction == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_questions_2d_dragfill_mark.py -v`
Expected: FAIL — `NotImplementedError` (base `mark`) / `AttributeError` on `build_answer`.

- [ ] **Step 3: Implement `build_answer` + `mark`**

Add the import at the top of `courses/models.py` if not present: `from courses.marking import MarkResult` (it already imports `normalize_text`/`parse_number`; add `MarkResult`). Add to `DragFillBlankQuestionElement`:

```python
    def build_answer(self, post):
        return post.getlist("slot")

    def mark(self, answer):
        from courses import dnd

        expected = self.expected_tokens()
        pool = dnd.build_pool(self)
        n_correct, reveal = dnd.mark_slots(expected, pool, answer)
        n = len(expected)
        return MarkResult(
            correct=(n_correct == n and n > 0),
            fraction=(n_correct / n) if n else 0.0,
            reveal=reveal,
        )
```

(The `from courses import dnd` is a local import to avoid a models↔dnd import cycle, since `dnd` imports from `models`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_questions_2d_dragfill_mark.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add courses/models.py tests/test_questions_2d_dragfill_mark.py
git commit -m "feat(2d-i): drag-fill build_answer + mark"
```

---

### Task 5: `MatchPairQuestionElement.build_answer` + `mark`

**Files:**
- Modify: `courses/models.py` (`MatchPairQuestionElement`)
- Test: `tests/test_questions_2d_matchpair_mark.py`

**Interfaces:**
- Consumes: `dnd.build_pool`, `dnd.mark_slots`, `MarkResult`.
- Produces: `MatchPairQuestionElement.build_answer(self, post) -> list[str]`; `.mark(self, answer) -> MarkResult` (reveal = tuple of `{index, correct, accepted, left}`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_questions_2d_matchpair_mark.py
import pytest

from courses.models import MatchPair, MatchPairQuestionElement


def _q():
    q = MatchPairQuestionElement.objects.create(stem="<p>Match</p>", distractors="Rome")
    MatchPair.objects.create(question=q, left="France", right="Paris")
    MatchPair.objects.create(question=q, left="Spain", right="Madrid")
    return q


@pytest.mark.django_db
def test_matchpair_mark_and_reveal_carries_left():
    q = _q()
    res = q.mark(["Paris", "Rome"])
    assert res.fraction == 0.5 and res.correct is False
    assert res.reveal == (
        {"index": 0, "correct": True, "accepted": "Paris", "left": "France"},
        {"index": 1, "correct": False, "accepted": "Madrid", "left": "Spain"},
    )


@pytest.mark.django_db
def test_matchpair_left_label_never_matches():
    # "France" is a left label, not a pool token → choosing it is wrong.
    q = _q()
    assert q.mark(["France", "Madrid"]).fraction == 0.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_questions_2d_matchpair_mark.py -v`
Expected: FAIL — `NotImplementedError` / `AttributeError`.

- [ ] **Step 3: Implement `build_answer` + `mark`**

Add to `MatchPairQuestionElement`:

```python
    def build_answer(self, post):
        return post.getlist("slot")

    def mark(self, answer):
        from courses import dnd

        pairs = list(self.pairs.all())
        expected = [p.right for p in pairs]
        pool = dnd.build_pool(self)
        n_correct, reveal = dnd.mark_slots(expected, pool, answer)
        reveal = tuple({**r, "left": pairs[r["index"]].left} for r in reveal)
        n = len(expected)
        return MarkResult(
            correct=(n_correct == n and n > 0),
            fraction=(n_correct / n) if n else 0.0,
            reveal=reveal,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_questions_2d_matchpair_mark.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add courses/models.py tests/test_questions_2d_matchpair_mark.py
git commit -m "feat(2d-i): match-pair build_answer + mark (left in reveal)"
```

---

### Task 6: `dnd` render helpers (`render_selects`, `render_match_rows`)

**Files:**
- Modify: `courses/dnd.py`
- Test: `tests/test_dnd_render.py`

**Interfaces:**
- Consumes: `courses.fillblank._TOKEN_RE` (the gap-token splitter), `format_html`, `mark_safe`, `gettext`.
- Produces:
  - `dnd.render_selects(token_stem, pool, chosen=None) -> SafeString` — splices a `<select name="slot">` per gap into the token-stem.
  - `dnd.render_match_rows(pairs, pool, chosen=None) -> SafeString` — an `<ol>` of `left` label + `<select name="slot">` rows.
  - `dnd._render_select(pool, chosen) -> SafeString` — one `<select>`: leading empty `<option value="">`, then one option per pool token; pre-selects `chosen` if it is a pool member, else the empty placeholder.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dnd_render.py
from courses import dnd


def test_render_select_has_empty_placeholder_and_escapes():
    html = str(dnd._render_select(["a", "<b>"], chosen=None))
    assert '<select name="slot"' in html
    assert '<option value="">' in html  # mandatory empty placeholder
    assert "&lt;b&gt;" in html          # token HTML-escaped in option
    assert "<b>" not in html


def test_render_select_preselects_member_else_placeholder():
    member = str(dnd._render_select(["Paris", "Rome"], chosen="Paris"))
    assert '<option value="Paris" selected>' in member
    # deleted/non-member token → placeholder selected, no real option selected
    gone = str(dnd._render_select(["Paris", "Rome"], chosen="Berlin"))
    assert '<option value="" selected>' in gone
    assert "selected>Paris" not in gone.replace('value="Paris" ', 'value="Paris"')


def test_render_select_preselects_normalize_variant_member():
    # A stored value differing from the pool's raw survivor only by case/space must
    # still pre-select that option (render/mark agree on normalized membership, C2).
    variant = str(dnd._render_select(["Paris", "Rome"], chosen="  paris "))
    assert '<option value="Paris" selected>' in variant
    assert '<option value="" selected>' not in variant


def test_render_selects_splices_one_select_per_gap():
    html = str(dnd.render_selects("A ￿0￿ B ￿1￿", ["x", "y"], chosen=["x", ""]))
    assert html.count('<select name="slot"') == 2
    assert "A " in html and " B " in html       # text segments preserved
    assert '<option value="x" selected>' in html  # gap 0 pre-selected


def test_render_match_rows_one_select_per_pair_with_left_label():
    class P:
        def __init__(self, left):
            self.left = left

    html = str(dnd.render_match_rows([P("France"), P("Spain")], ["Paris"], chosen=["Paris", ""]))
    assert html.count('<select name="slot"') == 2
    assert "France" in html and "Spain" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_dnd_render.py -v`
Expected: FAIL — `AttributeError: module 'courses.dnd' has no attribute '_render_select'`.

- [ ] **Step 3: Add the render helpers to `courses/dnd.py`**

Add imports at the top:

```python
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _

from courses.fillblank import _TOKEN_RE
```

Add the functions:

```python
def _render_select(pool, chosen):
    """One <select name="slot">: a leading empty placeholder then one option per pool
    token. Pre-select the pool option whose NORMALIZED form equals the (normalized)
    `chosen` — membership/pre-selection are normalize-aware, exactly like mark_slots
    (§3.1), so a stored raw form that differs from the deduped survivor of a
    normalize-collision still pre-selects correctly (render and mark never disagree).
    If no normalized match exists (deleted/forged token, or chosen empty), the
    placeholder is selected (resumes as unfilled, not the first token).
    `build_pool` dedups by normalize_text, so at most one pool option matches."""
    chosen_norm = normalize_text(chosen or "")
    matched = chosen_norm != "" and any(normalize_text(t) == chosen_norm for t in pool)
    placeholder_sel = mark_safe(" selected") if not matched else mark_safe("")
    opts = [format_html('<option value=""{}>{}</option>', placeholder_sel, _("— choose —"))]
    for tok in pool:
        sel = (
            mark_safe(" selected")
            if (matched and normalize_text(tok) == chosen_norm)
            else mark_safe("")
        )
        opts.append(format_html('<option value="{}"{}>{}</option>', tok, sel, tok))
    return format_html(
        '<select name="slot" class="dnd__select">{}</select>', mark_safe("".join(opts))
    )


def render_selects(token_stem, pool, chosen=None):
    """Drag-fill: split the token-stem and splice a <select> per gap. Text segments are
    trusted sanitized HTML; only the server-built <select>s are inserted (escaped)."""
    chosen = list(chosen or [])
    parts = _TOKEN_RE.split(token_stem or "")
    out = []
    for i, part in enumerate(parts):
        if i % 2 == 0:
            out.append(part)  # trusted sanitized HTML segment
        else:
            n = int(part)
            val = chosen[n] if 0 <= n < len(chosen) else ""
            out.append(str(_render_select(pool, val)))
    return mark_safe("".join(out))  # noqa: S308 — segments sanitized; options escaped


def render_match_rows(pairs, pool, chosen=None):
    """Match-pairs: an <ol> of (left label, <select>) rows in pairs order."""
    chosen = list(chosen or [])
    rows = []
    for i, pair in enumerate(pairs):
        val = chosen[i] if i < len(chosen) else ""
        rows.append(
            format_html(
                '<li class="dnd__row"><span class="dnd__left">{}</span>{}</li>',
                pair.left,
                _render_select(pool, val),
            )
        )
    return format_html('<ol class="dnd__rows">{}</ol>', mark_safe("".join(rows)))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_dnd_render.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add courses/dnd.py tests/test_dnd_render.py
git commit -m "feat(2d-i): dnd render helpers — <select>-per-target no-JS base"
```

---

### Task 7: Element templates + templatetags + `_dnd_pool` mount

**Files:**
- Modify: `courses/templatetags/courses_extras.py` (add `render_drag_selects`, `render_match_pairs` tags)
- Create: `templates/courses/elements/dragfillblankquestionelement.html`
- Create: `templates/courses/elements/matchpairquestionelement.html`
- Create: `templates/courses/elements/_dnd_pool.html`
- Test: `tests/test_questions_2d_consumption.py`

**Interfaces:**
- Consumes: `dnd.build_pool`, `dnd.render_selects`, `dnd.render_match_rows` (Task 6); the base `QuestionElement.render()` (renders `courses/elements/<model_name>.html` with `el`, `element`, `submitted_values`, `mode`, `action_url`, `feedback_partial`, `quiz_submitted`, `locked`, `attempts_left`, `feedback_html`, `reveal_template`). The two new types need **no** `render()` override — the base passes everything; the template calls the tag with `el` + `submitted_values`.
- Produces: `{% render_drag_selects el submitted_values %}` and `{% render_match_pairs el submitted_values %}` template tags.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_questions_2d_consumption.py
import pytest
from django.urls import reverse

from courses.models import (
    DragBlank,
    DragFillBlankQuestionElement,
    Element,
    Enrollment,
    MatchPair,
    MatchPairQuestionElement,
)
from tests.factories import ContentNodeFactory, CourseFactory, make_login


def _enrolled_unit(client):
    user = make_login(client, "stu")
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="lesson")
    return course, unit


@pytest.mark.django_db
def test_dragfill_lesson_render_has_selects_and_no_leak_of_explanation(client):
    course, unit = _enrolled_unit(client)
    q = DragFillBlankQuestionElement.objects.create(stem="A ￿0￿", distractors="Rome")
    DragBlank.objects.create(question=q, correct_token="Paris")
    Element.objects.create(unit=unit, content_object=q)
    body = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    ).content.decode()
    assert body.count('name="slot"') == 1           # one <select> per gap
    assert '<option value="">' in body              # empty placeholder
    assert 'value="Paris"' in body and 'value="Rome"' in body  # pool options (not a leak — both are pool members shown to choose from)


@pytest.mark.django_db
def test_matchpair_lesson_render_two_rows(client):
    course, unit = _enrolled_unit(client)
    q = MatchPairQuestionElement.objects.create(stem="<p>m</p>", distractors="Rome")
    MatchPair.objects.create(question=q, left="France", right="Paris")
    MatchPair.objects.create(question=q, left="Spain", right="Madrid")
    Element.objects.create(unit=unit, content_object=q)
    body = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    ).content.decode()
    assert body.count('name="slot"') == 2
    assert "France" in body and "Spain" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_questions_2d_consumption.py -v`
Expected: FAIL — `TemplateDoesNotExist: courses/elements/dragfillblankquestionelement.html`.

- [ ] **Step 3: Add the templatetags**

In `courses/templatetags/courses_extras.py`, after `render_fill_blanks`:

```python
@register.simple_tag
def render_drag_selects(el, submitted_values=None):
    """Render a drag-fill stem: text segments interleaved with server-built
    <select name="slot"> elements (escaped). See courses.dnd."""
    from courses import dnd

    return dnd.render_selects(el.stem, dnd.build_pool(el), submitted_values)


@register.simple_tag
def render_match_pairs(el, submitted_values=None):
    """Render a match-pairs widget: an <ol> of (left label, <select name="slot">)
    rows. See courses.dnd."""
    from courses import dnd

    return dnd.render_match_rows(list(el.pairs.all()), dnd.build_pool(el), submitted_values)
```

- [ ] **Step 4: Create the templates**

`templates/courses/elements/_dnd_pool.html` (JS-injected mount — empty with JS off, so no orphaned chips):

```html
<div class="dnd__pool" data-dnd-pool hidden></div>
```

`templates/courses/elements/dragfillblankquestionelement.html` (mirrors `fillblankquestionelement.html`):

```html
{% load i18n courses_extras %}
<div class="el el--question el--dragfill" data-question data-dnd>
  {% if element %}
  <form class="question__form" method="post" action="{{ action_url }}">
    {% csrf_token %}
    <fieldset class="question__stem" {% if quiz_submitted or locked %}disabled{% endif %}
              style="border:0;padding:0;margin:0;">
      {% if element.pk == feedback_for_pk %}
        {% render_drag_selects el submitted_values %}
      {% else %}
        {% render_drag_selects el %}
      {% endif %}
      {% include "courses/elements/_dnd_pool.html" %}
    </fieldset>
    <button type="submit" class="btn btn--small"
            {% if quiz_submitted or locked %}disabled{% endif %}>{% trans "Check" %}</button>
    <div class="question__feedback" data-question-feedback>
      {% if mode == "quiz" %}{{ feedback_html|safe }}{% elif element.pk == feedback_for_pk %}{% include feedback_partial %}{% endif %}
    </div>
  </form>
  {% else %}
    <div class="question__stem">{% render_drag_selects el %}{% include "courses/elements/_dnd_pool.html" %}</div>
  {% endif %}
</div>
```

`templates/courses/elements/matchpairquestionelement.html`:

```html
{% load i18n courses_extras %}
<div class="el el--question el--matchpair" data-question data-dnd>
  {% if el.stem %}<div class="question__stem">{{ el.stem|safe }}</div>{% endif %}
  {% if element %}
  <form class="question__form" method="post" action="{{ action_url }}">
    {% csrf_token %}
    <fieldset {% if quiz_submitted or locked %}disabled{% endif %}
              style="border:0;padding:0;margin:0;">
      {% if element.pk == feedback_for_pk %}
        {% render_match_pairs el submitted_values %}
      {% else %}
        {% render_match_pairs el %}
      {% endif %}
      {% include "courses/elements/_dnd_pool.html" %}
    </fieldset>
    <button type="submit" class="btn btn--small"
            {% if quiz_submitted or locked %}disabled{% endif %}>{% trans "Check" %}</button>
    <div class="question__feedback" data-question-feedback>
      {% if mode == "quiz" %}{{ feedback_html|safe }}{% elif element.pk == feedback_for_pk %}{% include feedback_partial %}{% endif %}
    </div>
  </form>
  {% else %}
    <div>{% render_match_pairs el %}{% include "courses/elements/_dnd_pool.html" %}</div>
  {% endif %}
</div>
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_questions_2d_consumption.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add courses/templatetags/courses_extras.py templates/courses/elements/dragfillblankquestionelement.html templates/courses/elements/matchpairquestionelement.html templates/courses/elements/_dnd_pool.html tests/test_questions_2d_consumption.py
git commit -m "feat(2d-i): drag-fill & match-pair element templates + tags"
```

---

### Task 8: Reveal partials

**Files:**
- Create: `templates/courses/elements/_reveal_dragfill.html`
- Create: `templates/courses/elements/_reveal_matchpair.html`
- Test: `tests/test_questions_2d_reveal.py`

**Interfaces:**
- Consumes: `mark_result.reveal` tuple — drag-fill `{index, correct, accepted}`, match-pairs `{index, correct, accepted, left}` (Tasks 4-5); rendered by `_question_feedback.html`/`_quiz_question_feedback.html` via `reveal_template` (the base `feedback_context` passes `reveal_template = REVEAL_TEMPLATE`, no override needed).

> **`_reveal_matchpair.html` must render `item.left` OUTSIDE the `{% if item.correct %}…{% else %}…{% endif %}`** (always shown, on correct AND incorrect rows) — unlike `_reveal_fillblank.html`, which has no per-row label. The results-page test (Task 16) and the reveal test below assert the `left` label appears on every row, so do not tuck it inside the incorrect-only branch when mirroring the fill-blank partial.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_questions_2d_reveal.py
import pytest
from django.urls import reverse

from courses.models import (
    DragBlank,
    DragFillBlankQuestionElement,
    Element,
    Enrollment,
    MatchPair,
    MatchPairQuestionElement,
)
from tests.factories import ContentNodeFactory, CourseFactory, make_login


def _enrolled_unit(client):
    user = make_login(client, "stu")
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="lesson")
    return course, unit


def _check_url(course, unit, el):
    return reverse(
        "courses:check_answer",
        kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": el.pk},
    )


@pytest.mark.django_db
def test_dragfill_reveal_shows_correct_token_on_wrong_answer(client):
    course, unit = _enrolled_unit(client)
    q = DragFillBlankQuestionElement.objects.create(stem="A ￿0￿", distractors="Rome")
    DragBlank.objects.create(question=q, correct_token="Paris")
    el = Element.objects.create(unit=unit, content_object=q)
    body = client.post(
        _check_url(course, unit, el), {"slot": ["Rome"]}, HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()
    assert "is-incorrect" in body
    assert "Paris" in body  # lesson is always-reveal → correct token shown


@pytest.mark.django_db
def test_matchpair_reveal_lists_left_labels(client):
    course, unit = _enrolled_unit(client)
    q = MatchPairQuestionElement.objects.create(stem="<p>m</p>")
    MatchPair.objects.create(question=q, left="France", right="Paris")
    el = Element.objects.create(unit=unit, content_object=q)
    body = client.post(
        _check_url(course, unit, el), {"slot": ["Wrong"]}, HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()
    assert "France" in body and "Paris" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_questions_2d_reveal.py -v`
Expected: FAIL — `TemplateDoesNotExist: courses/elements/_reveal_dragfill.html`.

- [ ] **Step 3: Create the reveal partials**

`templates/courses/elements/_reveal_dragfill.html` (mirrors `_reveal_fillblank.html`):

```html
{% load i18n %}
<ol class="question__reveal question__reveal--blanks">
  {% for item in mark_result.reveal %}
    <li class="question__reveal-item {% if item.correct %}answer-correct{% else %}answer-wrong{% endif %}">
      {% if item.correct %}
        <span class="question__tick" aria-hidden="true">✓</span>
      {% else %}
        <span class="question__glyph" aria-hidden="true">✗</span>
        <span class="question__reveal-text">{% trans "Correct token:" %} <strong>{{ item.accepted }}</strong></span>
      {% endif %}
    </li>
  {% endfor %}
</ol>
```

`templates/courses/elements/_reveal_matchpair.html` (shows the left label per row):

```html
{% load i18n %}
<ul class="question__reveal question__reveal--pairs">
  {% for item in mark_result.reveal %}
    <li class="question__reveal-item {% if item.correct %}answer-correct{% else %}answer-wrong{% endif %}">
      <span class="question__reveal-left">{{ item.left }}</span>
      {% if item.correct %}
        <span class="question__tick" aria-hidden="true">✓</span>
      {% else %}
        <span class="question__glyph" aria-hidden="true">✗</span>
        <span class="question__reveal-text">{% trans "Correct match:" %} <strong>{{ item.accepted }}</strong></span>
      {% endif %}
    </li>
  {% endfor %}
</ul>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_questions_2d_reveal.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add templates/courses/elements/_reveal_dragfill.html templates/courses/elements/_reveal_matchpair.html tests/test_questions_2d_reveal.py
git commit -m "feat(2d-i): drag-fill & match-pair reveal partials"
```

---

### Task 9: `dnd.js` — drag enhancement (progressive, e2e-tested)

**Files:**
- Create: `courses/static/courses/js/dnd.js` (the app's JS lives under `courses/static/courses/js/` — e.g. `question.js`, `quiz.js`; referenced via `{% static 'courses/js/<name>.js' %}`. Note a distinct existing `editor_dnd.js` already lives here — the new file is `dnd.js`, no clash.)
- Modify: `templates/courses/lesson_unit.html` (add the `dnd.js` include **inside the existing `{% if has_questions %}` block**, alongside `question.js`) and `templates/courses/quiz_unit.html` (add it **unconditionally**, alongside the `quiz.js` include, which is itself unconditional)
- Test: covered by the Task 18 e2e (no unit test — DOM/pointer behavior).

**Interfaces:**
- Consumes: the rendered `[data-dnd]` question blocks, each containing `<select name="slot">` elements and a `[data-dnd-pool]` mount.
- Produces: no Python interface. Behavior: for each `[data-dnd]`, build the chip set from the union of non-empty `<option>` values of its selects, inject draggable chips into `[data-dnd-pool]` and a drop-slot overlay per select; on drop/keyboard-activate set the target `<select>.value` to the chosen token text and dispatch `change`; **never reorder/add/remove the `<select>` nodes**. If the script throws or never loads, the selects remain fully usable.

- [ ] **Step 1: Write `courses/static/courses/js/dnd.js`**

```javascript
// Progressive drag-and-drop enhancement for drag-fill-blanks & match-pairs.
// The <select name="slot"> elements are the source of truth and the no-JS fallback;
// this script only ever SETS a select's value (it never reorders/removes selects).
(function () {
  "use strict";

  function tokensFromSelects(selects) {
    var seen = Object.create(null);
    var tokens = [];
    selects.forEach(function (sel) {
      Array.prototype.forEach.call(sel.options, function (opt) {
        if (opt.value && !seen[opt.value]) {
          seen[opt.value] = true;
          tokens.push(opt.value);
        }
      });
    });
    return tokens;
  }

  function setSelect(sel, value) {
    sel.value = value;
    sel.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function enhance(block) {
    if (block.dataset.dndReady) return;
    block.dataset.dndReady = "1";
    var selects = Array.prototype.slice.call(block.querySelectorAll('select[name="slot"]'));
    if (!selects.length) return;
    var pool = block.querySelector("[data-dnd-pool]");
    if (!pool) return;

    // Build the draggable chip pool (JS-injected; absent with JS off).
    pool.hidden = false;
    tokensFromSelects(selects).forEach(function (tok) {
      var chip = document.createElement("button");
      chip.type = "button";
      chip.className = "dnd__chip";
      chip.textContent = tok;
      chip.draggable = true;
      chip.dataset.token = tok;
      chip.addEventListener("dragstart", function (e) {
        e.dataTransfer.setData("text/plain", tok);
      });
      pool.appendChild(chip);
    });

    // Each select gets a visible drop-slot; the select itself is hidden but kept.
    selects.forEach(function (sel) {
      sel.classList.add("dnd__select--enhanced");
      var slot = document.createElement("span");
      slot.className = "dnd__slot";
      slot.tabIndex = 0;
      slot.textContent = sel.value || sel.dataset.placeholder || "…";
      sel.parentNode.insertBefore(slot, sel);
      sel.style.display = "none";

      function accept(tok) {
        setSelect(sel, tok);
        slot.textContent = tok || "…";
      }
      slot.addEventListener("dragover", function (e) { e.preventDefault(); });
      slot.addEventListener("drop", function (e) {
        e.preventDefault();
        accept(e.dataTransfer.getData("text/plain"));
      });
      // Keyboard fallback: focus the slot and use the hidden select via arrow keys
      // by re-showing it on Enter (kept simple; the select remains the source of truth).
      slot.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          sel.style.display = "";
          sel.focus();
        }
      });
      sel.addEventListener("change", function () {
        slot.textContent = sel.value || "…";
      });
    });
  }

  function init() {
    document.querySelectorAll("[data-dnd]").forEach(enhance);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
```

(No `dnd:rescan` re-scan hook: `question.js`/`quiz.js` only swap the `[data-question-feedback]` slot's `innerHTML` on a fetch submit — they never re-render the stem/`<select>`s and never dispatch such an event, so the chips/selects persist untouched through a feedback swap and no re-enhance is needed. Do not add a listener for an event nothing fires.)

- [ ] **Step 2: Add the script include to the lesson + quiz templates**

The two host templates gate their question JS **differently** (verified): `lesson_unit.html` loads `question.js` inside `{% if has_questions %}`; `quiz_unit.html` loads `quiz.js` **unconditionally**. Match each:

In `templates/courses/lesson_unit.html`, inside the existing `{% if has_questions %}` block (next to the `question.js` include):

```html
{% if has_questions %}<script src="{% static 'courses/js/question.js' %}" defer></script>
<script src="{% static 'courses/js/dnd.js' %}" defer></script>{% endif %}
```

In `templates/courses/quiz_unit.html`, unconditionally next to the `quiz.js` include:

```html
<script src="{% static 'courses/js/quiz.js' %}" defer></script>
<script src="{% static 'courses/js/dnd.js' %}" defer></script>
```

(`{% load static %}` is already present in both. Either gating is functionally safe since `dnd.js` no-ops when no `[data-dnd]` block exists, but match the host template so the include sits with its peers.)

- [ ] **Step 3: Manual smoke (deferred to e2e)**

No unit test. Behavior is asserted by the Task 18 Playwright tests (drag path + no-JS path + slot-order integrity). Verify the file is valid JS:

Run: `node --check courses/static/courses/js/dnd.js`
Expected: no output (exit 0).

- [ ] **Step 4: Commit**

```bash
git add courses/static/courses/js/dnd.js templates/courses/lesson_unit.html templates/courses/quiz_unit.html
git commit -m "feat(2d-i): dnd.js progressive drag enhancement over <select>s"
```

---

### Task 10: `DragFillBlankQuestionElementForm` + registry

**Files:**
- Modify: `courses/element_forms.py` (add form + register in `FORM_FOR_TYPE`)
- Test: `tests/test_questions_2d_dragfill_form.py`

**Interfaces:**
- Consumes: `fillblank.parse`/`strip_sentinel`, `sanitize_html`, `_MarkingFieldsMixin`, `DragFillBlankQuestionElement`.
- Produces: `DragFillBlankQuestionElementForm` whose `clean_stem` **returns the token-stem** (the `parse()` output, NOT the raw stem) so the saved `obj.stem` is the tokenised form, and sets `self.parsed_dragblanks: list[str]` (one token per gap) — exactly the fill-blank precedent the Task 12 builder rebuild depends on; registered in `FORM_FOR_TYPE["dragfillblankquestion"]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_questions_2d_dragfill_form.py
import pytest

from courses.element_forms import DragFillBlankQuestionElementForm


@pytest.mark.django_db
def test_form_parses_single_token_markers():
    form = DragFillBlankQuestionElementForm(
        data={"stem": "The capital is {{Paris}} and {{Madrid}}.", "distractors": "Rome"}
    )
    assert form.is_valid(), form.errors
    assert form.parsed_dragblanks == ["Paris", "Madrid"]


@pytest.mark.django_db
def test_form_rejects_pipe_with_dragfill_message():
    form = DragFillBlankQuestionElementForm(data={"stem": "{{a|b}}", "distractors": ""})
    assert not form.is_valid()
    assert any("single answer" in str(e).lower() or "one token" in str(e).lower()
               for e in form.errors["stem"])


@pytest.mark.django_db
def test_form_rejects_no_markers_without_fillblank_pipe_hint():
    form = DragFillBlankQuestionElementForm(data={"stem": "no gaps here", "distractors": ""})
    assert not form.is_valid()
    msg = " ".join(str(e) for e in form.errors["stem"]).lower()
    assert "gap" in msg and "alternativ" not in msg  # NOT fill-blank's "use | for alternatives"


@pytest.mark.django_db
def test_form_rejects_over_long_token():
    form = DragFillBlankQuestionElementForm(
        data={"stem": "{{" + "x" * 501 + "}}", "distractors": ""}
    )
    assert not form.is_valid()


@pytest.mark.django_db
def test_form_accepts_exactly_500_char_token():
    # Boundary: 500 is the max_length, so a 500-char token is accepted (501 rejected above).
    form = DragFillBlankQuestionElementForm(
        data={"stem": "{{" + "x" * 500 + "}}", "distractors": ""}
    )
    assert form.is_valid(), form.errors
    assert form.parsed_dragblanks == ["x" * 500]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_questions_2d_dragfill_form.py -v`
Expected: FAIL — `ImportError: cannot import name 'DragFillBlankQuestionElementForm'`.

- [ ] **Step 3: Add the form + import**

Add to `courses/element_forms.py` the model import (`from courses.models import DragFillBlankQuestionElement`) and:

```python
class DragFillBlankQuestionElementForm(_MarkingFieldsMixin, forms.ModelForm):
    parsed_dragblanks = None  # list[str] (one token per gap) after a successful clean()

    class Meta:
        model = DragFillBlankQuestionElement
        fields = ["stem", "distractors", "explanation",
                  "marking_mode", "max_attempts", "max_marks"]
        widgets = {
            "stem": forms.Textarea(attrs={"rows": 3, "data-rte-source": ""}),
            "distractors": forms.Textarea(attrs={"rows": 2}),
            "explanation": forms.Textarea(attrs={"rows": 2, "data-rte-source": ""}),
        }

    def clean_stem(self):
        raw = self.cleaned_data.get("stem", "")
        clean = fillblank.strip_sentinel(sanitize_html(raw))
        try:
            token_stem, blanks = fillblank.parse(clean)
        except fillblank.FillBlankError:
            raise forms.ValidationError(
                _("Mark at least one gap with {{token}}.")
            ) from None
        tokens = []
        for pieces in blanks:
            if len(pieces) != 1:
                raise forms.ValidationError(
                    _("Each gap holds one token — use a single answer per {{…}}, "
                      "not alternatives.")
                )
            if len(pieces[0]) > 500:
                raise forms.ValidationError(_("A token is too long (max 500 characters)."))
            tokens.append(pieces[0])
        self.parsed_dragblanks = tokens
        return token_stem
```

Register in `FORM_FOR_TYPE`:

```python
    "dragfillblankquestion": DragFillBlankQuestionElementForm,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_questions_2d_dragfill_form.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add courses/element_forms.py tests/test_questions_2d_dragfill_form.py
git commit -m "feat(2d-i): DragFillBlankQuestionElementForm (single-token clean_stem)"
```

---

### Task 11: `MatchPairQuestionElementForm` + `build_matchpair_formset` + registry

**Files:**
- Modify: `courses/element_forms.py`
- Test: `tests/test_questions_2d_matchpair_form.py`

**Interfaces:**
- Consumes: `inlineformset_factory`, `MatchPairQuestionElement`, `MatchPair`, `_MarkingFieldsMixin`.
- Produces: `MatchPairQuestionElementForm`; `MatchPairFormSet`; `build_matchpair_formset(*, data=None, files=None, instance=None, prefix="pairs") -> formset`; registered in `FORM_FOR_TYPE["matchpairquestion"]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_questions_2d_matchpair_form.py
import pytest

from courses.element_forms import build_matchpair_formset
from courses.models import MatchPairQuestionElement


def _data(rows, **extra):
    d = {
        "pairs-TOTAL_FORMS": str(len(rows)),
        "pairs-INITIAL_FORMS": "0",
        "pairs-MIN_NUM_FORMS": "0",
        "pairs-MAX_NUM_FORMS": "1000",
    }
    for i, (left, right) in enumerate(rows):
        d[f"pairs-{i}-left"] = left
        d[f"pairs-{i}-right"] = right
    d.update(extra)
    return d


@pytest.mark.django_db
def test_formset_requires_at_least_one_pair():
    fs = build_matchpair_formset(data=_data([]))
    assert not fs.is_valid()


@pytest.mark.django_db
def test_formset_valid_with_one_pair():
    fs = build_matchpair_formset(data=_data([("France", "Paris")]))
    assert fs.is_valid(), fs.errors


@pytest.mark.django_db
def test_formset_rejects_half_filled_row():
    fs = build_matchpair_formset(data=_data([("France", "")]))
    assert not fs.is_valid()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_questions_2d_matchpair_form.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_matchpair_formset'`.

- [ ] **Step 3: Add the form, formset, builder + registry**

Add the model imports (`from courses.models import MatchPair`, `from courses.models import MatchPairQuestionElement`) and:

```python
class MatchPairQuestionElementForm(_MarkingFieldsMixin, forms.ModelForm):
    class Meta:
        model = MatchPairQuestionElement
        fields = ["stem", "distractors", "explanation",
                  "marking_mode", "max_attempts", "max_marks"]
        widgets = {
            "stem": forms.Textarea(attrs={"rows": 2, "data-rte-source": ""}),
            "distractors": forms.Textarea(attrs={"rows": 2}),
            "explanation": forms.Textarea(attrs={"rows": 2, "data-rte-source": ""}),
        }


class BaseMatchPairFormSet(forms.BaseInlineFormSet):
    """At least one non-deleted, fully-filled pair (left AND right). Mirrors
    BaseChoiceFormSet: min_num/validate_min are NOT used (they miscount DELETE/empty
    extra rows)."""

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        kept = [
            f
            for f in self.forms
            if f.cleaned_data
            and not f.cleaned_data.get("DELETE")
            and f.cleaned_data.get("left")
            and f.cleaned_data.get("right")
        ]
        if len(kept) < 1:
            raise forms.ValidationError(_("Add at least one pair."))


MatchPairFormSet = inlineformset_factory(
    MatchPairQuestionElement,
    MatchPair,
    formset=BaseMatchPairFormSet,
    fields=["left", "right"],
    extra=2,
    can_delete=True,
)


def build_matchpair_formset(*, data=None, files=None, instance=None, prefix="pairs"):
    """Construct the MatchPair inline formset. Shared by the render-only and save paths
    so validation cannot drift (mirror of build_choice_formset)."""
    return MatchPairFormSet(data=data, files=files, instance=instance, prefix=prefix)
```

Register in `FORM_FOR_TYPE`:

```python
    "matchpairquestion": MatchPairQuestionElementForm,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_questions_2d_matchpair_form.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add courses/element_forms.py tests/test_questions_2d_matchpair_form.py
git commit -m "feat(2d-i): MatchPairQuestionElementForm + build_matchpair_formset"
```

---

### Task 12: `builder.save_element` persist branches

**Files:**
- Modify: `courses/builder.py` (`save_element`)
- Test: `tests/test_questions_2d_builder.py`

**Interfaces:**
- Consumes: `DragFillBlankQuestionElementForm.parsed_dragblanks`, `build_matchpair_formset`, `ElementFormInvalid`, `DragBlank`.
- Produces: persisted `DragBlank` rows (delete-then-rebuild) for `dragfillblankquestion`; persisted `MatchPair` rows (formset save) for `matchpairquestion`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_questions_2d_builder.py
import pytest

from courses import builder
from courses.models import DragBlank, DragFillBlankQuestionElement, Element
from tests.factories import ContentNodeFactory, CourseFactory, make_pa


def _post(unit, **extra):
    base = {"unit_token": unit.updated.isoformat(), "unit": str(unit.pk)}
    base.update(extra)
    return base


@pytest.mark.django_db
def test_save_dragfill_creates_dragblanks(client):
    make_pa(client, "pa")
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz")
    builder.save_element(
        course, unit.pk, "dragfillblankquestion", "new",
        _post(unit, stem="A {{Paris}} B {{Madrid}}", distractors="Rome", marking_mode="A"),
        {},
    )
    q = DragFillBlankQuestionElement.objects.get()
    assert [b.correct_token for b in q.dragblanks.all()] == ["Paris", "Madrid"]
    assert Element.objects.filter(content_type__model="dragfillblankquestionelement").count() == 1


@pytest.mark.django_db
def test_edit_dragfill_rebuilds_dragblanks_no_stale(client):
    make_pa(client, "pa")
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz")
    builder.save_element(course, unit.pk, "dragfillblankquestion", "new",
                         _post(unit, stem="{{Paris}} {{Madrid}}", distractors=""), {})
    el = Element.objects.get()
    unit.refresh_from_db()
    builder.save_element(course, unit.pk, "dragfillblankquestion", str(el.pk),
                         _post(unit, stem="{{Lisbon}}", distractors=""), {})
    q = DragFillBlankQuestionElement.objects.get()
    assert [b.correct_token for b in q.dragblanks.all()] == ["Lisbon"]  # no stale rows
    assert DragBlank.objects.count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_questions_2d_builder.py -v`
Expected: FAIL — the `else` branch runs `FORM_FOR_TYPE["dragfillblankquestion"](...).save()` but never creates `DragBlank` rows, so `q.dragblanks` is empty → assertion error.

- [ ] **Step 3: Add the two branches**

In `courses/builder.py` `save_element`, between the `fillblankquestion` branch and the `else`, add:

```python
    elif type_key == "dragfillblankquestion":
        from courses.element_forms import DragFillBlankQuestionElementForm

        form = DragFillBlankQuestionElementForm(data=post_data, instance=instance)
        if not form.is_valid():
            raise ElementFormInvalid(form)
        obj = form.save()  # token-stem stored; QuestionElement.save() sanitises
        obj.dragblanks.all().delete()  # rebuild from the freshly-parsed markers
        from courses.models import DragBlank

        for token in form.parsed_dragblanks:
            DragBlank.objects.create(question=obj, correct_token=token)
    elif type_key == "matchpairquestion":
        from courses.element_forms import MatchPairQuestionElementForm
        from courses.element_forms import build_matchpair_formset

        form = MatchPairQuestionElementForm(data=post_data, instance=instance)
        form_valid = form.is_valid()
        formset = build_matchpair_formset(data=post_data, files=files, instance=instance)
        if not form_valid or not formset.is_valid():
            raise ElementFormInvalid(form, formset)
        obj = form.save()
        formset.instance = obj
        formset.save()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_questions_2d_builder.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add courses/builder.py tests/test_questions_2d_builder.py
git commit -m "feat(2d-i): builder.save_element drag-fill (rebuild) + match-pair (formset) branches"
```

---

### Task 13: `views_manage` wiring — allowlists, formset threading, menu, edit partials

**Files:**
- Modify: `courses/views_manage.py` (both `type_key` allowlists; `_render_open_form` + `element_form` formset threading; `_EDITOR_TYPE_LABELS`)
- Modify: `templates/courses/manage/editor/_add_menu.html` (two buttons)
- Create: `templates/courses/manage/editor/_edit_dragfillblankquestion.html`
- Create: `templates/courses/manage/editor/_edit_matchpairquestion.html`
- Test: `tests/test_questions_2d_authoring_views.py`

**Interfaces:**
- Consumes: `build_matchpair_formset` (Task 11), `save_element` branches (Task 12), the `_host_form.html` include of `_edit_<type_key>.html`.
- Produces: the open/edit/save flow works for both new `type_key`s end-to-end (no 400; match-pairs formset renders + re-binds on 422).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_questions_2d_authoring_views.py
import pytest
from django.urls import reverse

from courses.models import ContentNode, DragFillBlankQuestionElement
from tests.factories import ContentNodeFactory, CourseFactory, make_pa


@pytest.mark.django_db
def test_element_add_opens_dragfill_form_not_400(client):
    make_pa(client, "pa")
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz")
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "dragfillblankquestion", "unit": unit.pk},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    assert b'name="slot"' not in resp.content  # authoring form, not the student widget
    assert b'name="stem"' in resp.content


@pytest.mark.django_db
def test_element_add_opens_matchpair_formset(client):
    make_pa(client, "pa")
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz")
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "matchpairquestion", "unit": unit.pk},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    assert b"pairs-TOTAL_FORMS" in resp.content  # the inline formset rendered


@pytest.mark.django_db
def test_matchpair_save_invalid_rerenders_formset_422(client):
    # §4.4 "re-bind on 422": a valid host form + invalid formset (zero pairs) must
    # re-render the bound MatchPair formset, not 400/500. Pins the e.formset path.
    make_pa(client, "pa")
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz")
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {
            "type": "matchpairquestion",
            "unit": unit.pk,
            "element": "new",
            "unit_token": unit.updated.isoformat(),
            "stem": "<p>m</p>",
            "marking_mode": "A",
            "pairs-TOTAL_FORMS": "0",
            "pairs-INITIAL_FORMS": "0",
            "pairs-MIN_NUM_FORMS": "0",
            "pairs-MAX_NUM_FORMS": "1000",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 422
    assert b"pairs-TOTAL_FORMS" in resp.content  # formset re-rendered (bound), not dropped
```

(The exact POST keys `element_ref`/`unit_token` and the 422 status mirror the existing `element_save` contract — confirm against `tests/test_manage_*` / the choice-question save tests when implementing and adjust key names if they differ.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_questions_2d_authoring_views.py -v`
Expected: FAIL — `element_add` returns `HttpResponseBadRequest("bad type")` (400) because the keys are not in the allowlist.

- [ ] **Step 3: Add keys to both allowlists**

In `courses/views_manage.py`, add `"dragfillblankquestion",` and `"matchpairquestion",` to the `if type_key not in (…)` tuple in **both** `element_add` **and** `element_save` (locate each by the `HttpResponseBadRequest("bad type")` guard, not by line number — there are exactly two such tuples).

- [ ] **Step 4: Thread the match-pair formset + labels**

In `_render_open_form`, extend the formset construction (which currently only fires for `choicequestion`):

```python
    if type_key == "choicequestion":
        # ... existing is_multiple + build_choice_formset block (unchanged) ...
    elif type_key == "matchpairquestion" and formset is None:
        from courses.element_forms import build_matchpair_formset

        instance = form.instance if form.instance.pk else None
        formset = build_matchpair_formset(instance=instance)
```

In `element_form` (the edit-open path — locate it by its existing `if type_key == "choicequestion": formset = build_choice_formset(instance=el.content_object)` block, not by line number), extend that block:

```python
    formset = None
    if type_key == "choicequestion":
        formset = build_choice_formset(instance=el.content_object)
    elif type_key == "matchpairquestion":
        from courses.element_forms import build_matchpair_formset

        formset = build_matchpair_formset(instance=el.content_object)
```

(The 422 invalid-re-render path already passes `e.formset` through `_render_open_form` generically — `ElementFormInvalid(form, formset)` from Task 12 carries it; no extra change there.)

Add the two labels to `_EDITOR_TYPE_LABELS`:

```python
    "dragfillblankquestion": _("Drag the words"),
    "matchpairquestion": _("Match pairs"),
```

- [ ] **Step 5: Add the menu buttons**

In `templates/courses/manage/editor/_add_menu.html`, after the `fillblankquestion` button:

```html
    <button type="button" class="typecard" data-add-type="dragfillblankquestion"><span class="ic">🧲</span>{% trans "Drag the words" %}</button>
    <button type="button" class="typecard" data-add-type="matchpairquestion"><span class="ic">🔗</span>{% trans "Match pairs" %}</button>
```

- [ ] **Step 6: Create the per-type edit partials**

`templates/courses/manage/editor/_edit_dragfillblankquestion.html` (mirrors `_edit_fillblankquestion.html`, with a distractors field):

```html
{% load i18n %}
<div class="el-editor el-editor--question">
  <label class="el-editor__label">{% trans "Sentence with gaps" %}</label>
  <p class="el-editor__hint">{% trans "Mark each gap with {{token}} — one token per gap (no | alternatives)." %}</p>
  <div class="el-editor--text">
    {% include "courses/manage/editor/_rte_toolbar.html" %}
    <textarea name="stem" class="rte-source" data-rte-source rows="3">{{ form.stem.value|default:"" }}</textarea>
  </div>
  {% for e in form.stem.errors %}<p class="field-error">{{ e }}</p>{% endfor %}

  <label class="el-editor__label">{% trans "Extra tokens (distractors, one per line)" %}</label>
  <textarea name="distractors" rows="2">{{ form.distractors.value|default:"" }}</textarea>

  {% include "courses/manage/editor/_marking_fields.html" %}

  <label class="el-editor__label">{% trans "Explanation (optional)" %}</label>
  <div class="el-editor--text">
    {% include "courses/manage/editor/_rte_toolbar.html" %}
    <textarea name="explanation" class="rte-source" data-rte-source rows="2">{{ form.explanation.value|default:"" }}</textarea>
  </div>
</div>
```

`templates/courses/manage/editor/_edit_matchpairquestion.html` (mirrors `_edit_choicequestion.html` formset structure):

```html
{% load i18n %}
<div class="el-editor el-editor--question">
  <label class="el-editor__label">{% trans "Prompt (optional)" %}</label>
  <div class="el-editor--text">
    {% include "courses/manage/editor/_rte_toolbar.html" %}
    <textarea name="stem" class="rte-source" data-rte-source rows="2">{{ form.stem.value|default:"" }}</textarea>
  </div>

  <label class="el-editor__label">{% trans "Pairs" %}</label>
  <p class="el-editor__hint">{% trans "Left = the fixed item; right = its matching token." %}</p>
  {{ formset.management_form }}
  <ul class="pair-rows" data-pair-rows>
    {% for f in formset %}
      <li class="pair-row" data-pair-row>
        {{ f.id }}
        {{ f.left }} {{ f.right }}
        {% if formset.can_delete %}
          <label class="pair-row__del">{{ f.DELETE }} {% trans "Remove" %}</label>
        {% endif %}
      </li>
    {% endfor %}
  </ul>
  <button type="button" class="btn btn--small btn--ghost" data-pair-add>＋ {% trans "Add pair" %}</button>
  {% for e in formset.non_form_errors %}<p class="field-error">{{ e }}</p>{% endfor %}

  <label class="el-editor__label">{% trans "Extra tokens (distractors, one per line)" %}</label>
  <textarea name="distractors" rows="2">{{ form.distractors.value|default:"" }}</textarea>

  {% include "courses/manage/editor/_marking_fields.html" %}

  <label class="el-editor__label">{% trans "Explanation (optional)" %}</label>
  <div class="el-editor--text">
    {% include "courses/manage/editor/_rte_toolbar.html" %}
    <textarea name="explanation" class="rte-source" data-rte-source rows="2">{{ form.explanation.value|default:"" }}</textarea>
  </div>
</div>
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_questions_2d_authoring_views.py -v`
Expected: PASS (2 tests).

- [ ] **Step 8: Commit**

```bash
git add courses/views_manage.py templates/courses/manage/editor/_add_menu.html templates/courses/manage/editor/_edit_dragfillblankquestion.html templates/courses/manage/editor/_edit_matchpairquestion.html tests/test_questions_2d_authoring_views.py
git commit -m "feat(2d-i): authoring wiring — allowlists, formset, menu, edit partials"
```

---

### Task 14: `views.py` consumption touchpoints (lesson path)

**Files:**
- Modify: `courses/views.py` (`build_lesson_context` prefetch + `_question_has_math` + `question_models`; `build_quiz_context` prefetch)
- Test: `tests/test_questions_2d_views_touchpoints.py`

**Interfaces:**
- Consumes: `DragFillBlankQuestionElement`, `MatchPairQuestionElement`, `has_math_delimiters`.
- Produces: lesson context loads KaTeX when token/label math is present; new types counted in `has_questions`; both lesson + quiz contexts prefetch `dragblanks`/`pairs`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_questions_2d_views_touchpoints.py
import pytest
from django.urls import reverse

from courses.models import (
    DragBlank,
    DragFillBlankQuestionElement,
    Element,
    Enrollment,
)
from tests.factories import ContentNodeFactory, CourseFactory, make_login


@pytest.mark.django_db
def test_lesson_loads_katex_when_only_math_is_in_a_token(client):
    user = make_login(client, "stu")
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    q = DragFillBlankQuestionElement.objects.create(stem="x ￿0￿", distractors="")
    DragBlank.objects.create(question=q, correct_token=r"\(x^2\)")
    Element.objects.create(unit=unit, content_object=q)
    body = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    ).content.decode()
    assert "katex" in body.lower()  # KaTeX assets loaded because a token carries math
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_questions_2d_views_touchpoints.py -v`
Expected: FAIL — `_question_has_math` returns `False` for the new type (its branches only cover choice/fill-blank), so KaTeX is not loaded.

- [ ] **Step 3: Extend the lesson-context touchpoints**

In `courses/views.py`, add the imports for the two new models (next to the existing `from courses.models import FillBlankQuestionElement`). In `build_lesson_context`:

Extend the prefetch block:

```python
    choice_qs = [q for q in questions if isinstance(q, ChoiceQuestionElement)]
    fill_qs = [q for q in questions if isinstance(q, FillBlankQuestionElement)]
    dragfill_qs = [q for q in questions if isinstance(q, DragFillBlankQuestionElement)]
    matchpair_qs = [q for q in questions if isinstance(q, MatchPairQuestionElement)]
    if choice_qs:
        prefetch_related_objects(choice_qs, "choices")
    if fill_qs:
        prefetch_related_objects(fill_qs, "blanks")
    if dragfill_qs:
        prefetch_related_objects(dragfill_qs, "dragblanks")
    if matchpair_qs:
        prefetch_related_objects(matchpair_qs, "pairs")
```

Add both models to `question_models`:

```python
    question_models = [
        ChoiceQuestionElement,
        ShortTextQuestionElement,
        ShortNumericQuestionElement,
        FillBlankQuestionElement,
        DragFillBlankQuestionElement,
        MatchPairQuestionElement,
    ]
```

Extend `_question_has_math`:

```python
    def _question_has_math(q):
        if has_math_delimiters(q.stem):
            return True
        if isinstance(q, ChoiceQuestionElement):
            return any(has_math_delimiters(c.text) for c in q.choices.all())
        if isinstance(q, FillBlankQuestionElement):
            return any(has_math_delimiters(b.accepted) for b in q.blanks.all())
        if isinstance(q, DragFillBlankQuestionElement):
            return has_math_delimiters(q.distractors) or any(
                has_math_delimiters(b.correct_token) for b in q.dragblanks.all()
            )
        if isinstance(q, MatchPairQuestionElement):
            return has_math_delimiters(q.distractors) or any(
                has_math_delimiters(p.left) or has_math_delimiters(p.right)
                for p in q.pairs.all()
            )
        return False
```

- [ ] **Step 4: Extend the quiz-context prefetch**

In `build_quiz_context`, mirror the prefetch additions (do **NOT** touch `has_math`/`has_questions` there — the quiz path is unconditional per spec §4.4):

```python
    dragfill_qs = [q for q in questions if isinstance(q, DragFillBlankQuestionElement)]
    matchpair_qs = [q for q in questions if isinstance(q, MatchPairQuestionElement)]
    if choice_qs:
        prefetch_related_objects(choice_qs, "choices")
    if fill_qs:
        prefetch_related_objects(fill_qs, "blanks")
    if dragfill_qs:
        prefetch_related_objects(dragfill_qs, "dragblanks")
    if matchpair_qs:
        prefetch_related_objects(matchpair_qs, "pairs")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_questions_2d_views_touchpoints.py -v`
Expected: PASS (1 test).

- [ ] **Step 6: Commit**

```bash
git add courses/views.py tests/test_questions_2d_views_touchpoints.py
git commit -m "feat(2d-i): views consumption touchpoints — prefetch, KaTeX, question gate"
```

---

### Task 15: quiz default-branch routing tests (no code change)

**Files:**
- Test: `tests/test_questions_2d_quiz_routing.py`

**Interfaces:**
- Consumes: `quiz.rehydrate`, `quiz.answer_from_json`, `quiz.answer_to_json` (existing; the new types ride the default non-choice branch). This task pins that behavior so a future refactor can't silently route the new types through the choice branch.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_questions_2d_quiz_routing.py
import pytest

from courses import quiz
from courses.models import DragFillBlankQuestionElement, MatchPairQuestionElement


@pytest.mark.django_db
@pytest.mark.parametrize("model", [DragFillBlankQuestionElement, MatchPairQuestionElement])
def test_round_trip_keeps_token_list_on_default_branch(model):
    q = model.objects.create(stem="x", distractors="")
    stored = ["Paris", "", "Madrid"]
    # write path: list passes through unchanged
    assert quiz.answer_to_json(stored) == stored
    # read paths: token-text list returns untouched, not a choice set
    selected, submitted = quiz.rehydrate(q, stored)
    assert selected == set() and submitted == stored
    assert quiz.answer_from_json(q, stored) == stored
```

- [ ] **Step 2: Run test to verify it passes immediately (regression pin)**

Run: `uv run pytest tests/test_questions_2d_quiz_routing.py -v`
Expected: PASS (2 params). This task adds **no** production code — it is a guard. If it FAILS, a prior task wrongly special-cased a new type in `quiz.py`; fix that, do not edit the test.

- [ ] **Step 3: Commit**

```bash
git add tests/test_questions_2d_quiz_routing.py
git commit -m "test(2d-i): pin drag-fill/match-pair on the quiz default round-trip branch"
```

---

### Task 16: Quiz no-leak (withhold) + results-page reveal for the new types

**Files:**
- Test: `tests/test_questions_2d_quiz_noleak.py`
- Test: `tests/test_questions_2d_results.py`

**Interfaces:**
- Consumes: the 2c quiz machinery (the `quiz_answer` withhold state machine, `quiz_finish`, `quiz_results`/`_results_row`) and the new types' `build_answer`/`mark` + `REVEAL_TEMPLATE` (Tasks 4–5, 8). **No production code** — this task PINS that the new types ride the 2c withhold + results-reveal paths (spec §5.1 no-leak, §5.4 results reveal). If a test fails, fix the offending earlier task, not the test.

> **No-leak signal for DnD types (important):** unlike short-text, a DnD question's **correct token is always visible as a pool `<option>`** the student picks from — so the bare token text is NOT a leak signal here. The withhold signal is whether the **reveal partial renders** (`"Correct token:"` for drag-fill, `"Correct match:"` for match-pairs). These assertions key on that marker, not on the token string.

- [ ] **Step 1: Write the failing no-leak test**

```python
# tests/test_questions_2d_quiz_noleak.py
import pytest

from courses.models import (
    DragBlank,
    DragFillBlankQuestionElement,
    MatchPair,
    MatchPairQuestionElement,
)
from tests.factories import EnrollmentFactory, add_element, make_login, make_quiz_unit


def _quiz(client):
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    return user, unit


@pytest.mark.django_db
def test_dragfill_quiz_withholds_reveal_then_reveals_on_last_attempt(client):
    user, unit = _quiz(client)
    q = DragFillBlankQuestionElement.objects.create(
        stem="Cap is ￿0￿", distractors="Rome", marking_mode="A", max_attempts=2
    )
    DragBlank.objects.create(question=q, correct_token="Paris")
    el = add_element(unit, q)
    url = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/q/{el.pk}/answer/"

    # Wrong, 1 attempt remaining → withhold: the reveal partial must NOT render.
    body1 = client.post(
        url, {"slot": ["Rome"]}, HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()
    assert "Correct token:" not in body1
    assert "question__reveal" not in body1

    # Wrong on the LAST attempt → reveal: the correct token is now shown.
    body2 = client.post(
        url, {"slot": ["Rome"]}, HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()
    assert "Correct token:" in body2 and "Paris" in body2


@pytest.mark.django_db
def test_matchpair_quiz_withholds_then_reveals(client):
    user, unit = _quiz(client)
    q = MatchPairQuestionElement.objects.create(
        stem="<p>m</p>", distractors="Rome", marking_mode="A", max_attempts=2
    )
    MatchPair.objects.create(question=q, left="France", right="Paris")
    el = add_element(unit, q)
    url = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/q/{el.pk}/answer/"
    body1 = client.post(
        url, {"slot": ["Rome"]}, HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()
    assert "Correct match:" not in body1
    body2 = client.post(
        url, {"slot": ["Rome"]}, HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()
    assert "Correct match:" in body2 and "Paris" in body2
```

- [ ] **Step 2: Run it — expected to PASS immediately (regression pin)**

Run: `uv run pytest tests/test_questions_2d_quiz_noleak.py -v`
Expected: PASS (2 tests) once Tasks 4–8 are in. If it FAILS, the withhold path is being bypassed by a new type — fix the offending task (likely the feedback context not gating `reveal_template`), do NOT edit the test.

- [ ] **Step 3: Write the results-reveal test**

```python
# tests/test_questions_2d_results.py
import pytest

from courses.models import (
    DragBlank,
    DragFillBlankQuestionElement,
    MatchPair,
    MatchPairQuestionElement,
)
from tests.factories import EnrollmentFactory, add_element, make_login, make_quiz_unit


@pytest.mark.django_db
def test_results_reveals_dragfill_tokens_including_unanswered(client):
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    base = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz"

    correct = DragFillBlankQuestionElement.objects.create(
        stem="A ￿0￿", distractors="Rome", marking_mode="A"
    )
    DragBlank.objects.create(question=correct, correct_token="Paris")
    el_c = add_element(unit, correct)
    wrong = DragFillBlankQuestionElement.objects.create(
        stem="B ￿0￿", distractors="Oslo", marking_mode="A"
    )
    DragBlank.objects.create(question=wrong, correct_token="Madrid")
    el_w = add_element(unit, wrong)
    unanswered = DragFillBlankQuestionElement.objects.create(
        stem="C ￿0￿", distractors="Bonn", marking_mode="A"
    )
    DragBlank.objects.create(question=unanswered, correct_token="Lisbon")
    add_element(unit, unanswered)  # never answered

    client.post(f"{base}/q/{el_c.pk}/answer/", {"slot": ["Paris"]}, HTTP_X_REQUESTED_WITH="fetch")
    client.post(f"{base}/q/{el_w.pk}/answer/", {"slot": ["Oslo"]}, HTTP_X_REQUESTED_WITH="fetch")
    client.post(f"{base}/finish/")
    body = client.get(f"{base}/results/").content.decode()
    # §3.4 "reveal all": every [A] question reveals its token, incl. the unanswered one
    # (which _results_row reconstructs via mark(build_answer(QueryDict()))).
    assert "Paris" in body and "Madrid" in body and "Lisbon" in body


@pytest.mark.django_db
def test_results_matchpair_row_shows_left_label(client):
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    base = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz"
    q = MatchPairQuestionElement.objects.create(stem="<p>m</p>", marking_mode="A")
    MatchPair.objects.create(question=q, left="France", right="Paris")
    add_element(unit, q)  # unanswered → still reveals
    client.get(f"{base}/")   # GET the quiz first → materializes the QuizSubmission (the
                             # student flow; don't rely on quiz_finish create-if-absent)
    client.post(f"{base}/finish/")
    body = client.get(f"{base}/results/").content.decode()
    assert "France" in body and "Paris" in body  # left label + accepted token revealed
```

- [ ] **Step 4: Run it — expected to PASS (regression pin)**

Run: `uv run pytest tests/test_questions_2d_results.py -v`
Expected: PASS (2 tests). A failure means `_results_row`'s `mark(answer_from_json(...))` / `mark(build_answer(QueryDict()))` reveal reconstruction (spec §4.4) doesn't work for the new types — fix the relevant earlier task.

- [ ] **Step 5: Commit**

```bash
git add tests/test_questions_2d_quiz_noleak.py tests/test_questions_2d_results.py
git commit -m "test(2d-i): quiz no-leak withhold + results-page reveal for DnD types"
```

---

### Task 17: i18n (Polish strings)

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po` (generated, then translated)
- Test: `tests/test_i18n_questions_2d.py`

**Interfaces:**
- Consumes: every `_(...)`/`{% trans %}` string added in Tasks 8, 10, 11, 13 (e.g. "Mark at least one gap with {{token}}.", "Each gap holds one token — …", "A token is too long (max 500 characters).", "Add at least one pair.", "Drag the words", "Match pairs", "Correct token:", "Correct match:", "Extra tokens (distractors, one per line)", "— choose —", "Prompt (optional)", "Pairs", "Left = the fixed item; right = its matching token.").

- [ ] **Step 1: Extract messages**

Run: `uv run python manage.py makemessages -l pl`
Expected: `locale/pl/LC_MESSAGES/django.po` updated with the new `msgid`s above (untranslated `msgstr ""`).

- [ ] **Step 2: Write the failing test**

```python
# tests/test_i18n_questions_2d.py
import pytest
from django.utils import translation


@pytest.mark.parametrize(
    "english",
    [
        "Drag the words",
        "Match pairs",
        "Add at least one pair.",
        "— choose —",
    ],
)
def test_pl_translation_present(english):
    with translation.override("pl"):
        translated = translation.gettext(english)
    assert translated and translated != english  # a real Polish string was provided
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_i18n_questions_2d.py -v`
Expected: FAIL — `msgstr` is empty, so `gettext` returns the English source.

- [ ] **Step 4: Translate the new msgids**

Edit `locale/pl/LC_MESSAGES/django.po`, filling the `msgstr ""` for each new `msgid` (matching the 2b/2c Polish style). Example entries:

```po
msgid "Drag the words"
msgstr "Przeciągnij słowa"

msgid "Match pairs"
msgstr "Dopasuj pary"

msgid "Add at least one pair."
msgstr "Dodaj co najmniej jedną parę."

msgid "— choose —"
msgstr "— wybierz —"

msgid "Mark at least one gap with {{token}}."
msgstr "Oznacz co najmniej jedną lukę za pomocą {{token}}."

msgid ""
"Each gap holds one token — use a single answer per {{…}}, not alternatives."
msgstr ""
"Każda luka mieści jeden token — podaj jedną odpowiedź w {{…}}, bez wariantów."

msgid "A token is too long (max 500 characters)."
msgstr "Token jest za długi (maks. 500 znaków)."

msgid "Correct token:"
msgstr "Poprawny token:"

msgid "Correct match:"
msgstr "Poprawne dopasowanie:"

msgid "Extra tokens (distractors, one per line)"
msgstr "Dodatkowe tokeny (dystraktory, po jednym w wierszu)"

msgid "Prompt (optional)"
msgstr "Polecenie (opcjonalne)"

msgid "Pairs"
msgstr "Pary"

msgid "Left = the fixed item; right = its matching token."
msgstr "Lewa = element stały; prawa = pasujący token."

msgid "Sentence with gaps"
msgstr "Zdanie z lukami"

msgid "Mark each gap with {{token}} — one token per gap (no | alternatives)."
msgstr "Oznacz każdą lukę za pomocą {{token}} — jeden token na lukę (bez wariantów |)."
```

- [ ] **Step 5: Compile and run the test**

Run: `uv run python manage.py compilemessages -l pl && uv run pytest tests/test_i18n_questions_2d.py -v`
Expected: PASS (4 params).

- [ ] **Step 6: Commit**

```bash
git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo tests/test_i18n_questions_2d.py
git commit -m "i18n(2d-i): Polish strings for drag-fill & match-pairs"
```

---

### Task 18: e2e (Playwright, JS + no-JS)

**Files:**
- Create: `tests/test_e2e_questions_2d.py`
- Test: itself (marked `e2e`, excluded from the default run).

**Interfaces:**
- Consumes: the full stack from Tasks 1-17. Mirrors the harness in `tests/test_e2e_quiz.py` / `tests/test_e2e_questions_2b.py` verbatim (session `_allow_async_unsafe` fixture, `_make_student`, `_login`, `browser.new_context(java_script_enabled=False)` + `page.request.post()` for the no-JS path; quiz markers `[data-question]`, `[data-question-feedback]`, `.is-correct`/`.is-incorrect`, `[data-finish-btn]`, the Finish confirm dialog).

- [ ] **Step 1: Write the e2e tests**

```python
# tests/test_e2e_questions_2d.py
"""Playwright e2e for Phase-2d-i drag-fill & match-pairs.

JS path: drag a chip into a gap → the hidden <select> takes the token → submit →
.is-correct. No-JS path: post the <select> value directly → full-page render, correct
token withheld pre-reveal in a quiz. Slot-order integrity: after JS enhancement, the
submitted answer matches the targets in document order.

Marked e2e (run with -m e2e). Mirrors the harness in test_e2e_quiz.py.
"""

import os

import pytest

from courses.models import (
    ContentNode,
    Course,
    DragBlank,
    DragFillBlankQuestionElement,
    Element,
    Enrollment,
)
from tests.factories import TEST_PASSWORD, make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _seed_dragfill_lesson(username):
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    course = Course.objects.create(title="C", slug=f"c-{username}", language="en")
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNode.objects.create(
        course=course, kind="unit", unit_type="lesson", title="U"
    )
    q = DragFillBlankQuestionElement.objects.create(stem="Cap is ￿0￿", distractors="Rome")
    DragBlank.objects.create(question=q, correct_token="Paris")
    el = Element.objects.create(unit=unit, content_object=q)
    return course, unit, el


@pytest.mark.django_db(transaction=True)
def test_dragfill_no_js_select_path(live_server, browser):
    """No-JS: choose the option in the native <select>, submit, see the correct mark."""
    course, unit, el = _seed_dragfill_lesson("nojs2d")
    context = browser.new_context(java_script_enabled=False)
    page = context.new_page()
    _login(page, live_server, "nojs2d")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    page.locator('select[name="slot"]').select_option(value="Paris")
    page.locator('button[type="submit"]').click()
    assert page.locator(".is-correct").count() >= 1
    context.close()


@pytest.mark.django_db(transaction=True)
def test_dragfill_js_drag_path(live_server, page):
    """JS: drag the 'Paris' chip onto the gap's drop-slot → select takes it → correct."""
    course, unit, el = _seed_dragfill_lesson("js2d")
    _login(page, live_server, "js2d")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    chip = page.locator('.dnd__chip[data-token="Paris"]')
    slot = page.locator(".dnd__slot").first
    chip.drag_to(slot)
    # The hidden select must now carry the dragged token (slot-order integrity).
    assert page.locator('select[name="slot"]').input_value() == "Paris"
    page.locator('button[type="submit"]').click()
    assert page.locator(".is-correct").count() >= 1


# ── Quiz seeding (mirrors _seed_quiz in test_e2e_quiz.py) ────────────────────


def _seed_dragfill_quiz(username, slug):
    """Course + QUIZ unit with one 2-gap drag-fill question (max_attempts=2)."""
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    course = Course.objects.create(title="C", slug=slug, language="en")
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNode.objects.create(
        course=course, kind="unit", unit_type="quiz", title="Q"
    )
    q = DragFillBlankQuestionElement.objects.create(
        stem="￿0￿ and ￿1￿", distractors="Rome", marking_mode="A", max_attempts=2
    )
    DragBlank.objects.create(question=q, correct_token="Paris")
    DragBlank.objects.create(question=q, correct_token="Madrid")
    el = Element.objects.create(unit=unit, content_object=q)
    return course, unit, el


@pytest.mark.django_db(transaction=True)
def test_dragfill_quiz_withhold_reveal_resume_js(live_server, browser):
    """Quiz JS flow: wrong (attempt left) → correct token withheld; wrong again (last)
    → reveal; reload → the chosen placement rehydrates (resume)."""
    course, unit, el = _seed_dragfill_quiz("qjs2d", "q-js-2d")
    ctx = browser.new_context()
    page = ctx.new_page()
    _login(page, live_server, "qjs2d")
    quiz_url = f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/quiz/"
    page.goto(quiz_url)
    page.wait_for_selector("[data-question]")

    selects = page.locator('select[name="slot"]')
    feedback = page.locator("[data-question-feedback]").first

    # Wrong, attempt remaining → withhold: the reveal partial must not render.
    selects.nth(0).select_option("Rome")
    selects.nth(1).select_option("Rome")
    page.locator('button[type="submit"]').first.click()
    feedback.locator(".is-incorrect").wait_for(timeout=6000)
    assert "Correct token:" not in page.content()

    # Wrong on the last attempt → reveal.
    selects.nth(0).select_option("Rome")
    selects.nth(1).select_option("Rome")
    page.locator('button[type="submit"]').first.click()
    page.wait_for_timeout(500)
    assert "Correct token:" in page.content()

    # Resume: reload and confirm the last submitted placement rehydrates.
    page.goto(quiz_url)
    assert page.locator('select[name="slot"]').first.input_value() == "Rome"
    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_dragfill_slot_order_integrity_js(live_server, page):
    """Fill the SECOND gap first, then the first; the recorded payload must still pair
    each token with its own target (positional invariant, spec §3.1)."""
    course, unit, el = _seed_dragfill_quiz("order2d", "order-2d")
    _login(page, live_server, "order2d")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/quiz/")
    page.wait_for_selector("[data-question]")
    selects = page.locator('select[name="slot"]')
    selects.nth(1).select_option("Madrid")  # second gap first
    selects.nth(0).select_option("Paris")   # then first gap
    page.locator('button[type="submit"]').first.click()
    page.wait_for_timeout(500)
    from courses.models import QuestionResponse

    resp = QuestionResponse.objects.get(element=el)
    assert resp.latest_answer == ["Paris", "Madrid"]  # order preserved, not swapped


def _seed_matchpair_lesson(username, slug):
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    course = Course.objects.create(title="C", slug=slug, language="en")
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNode.objects.create(
        course=course, kind="unit", unit_type="lesson", title="U"
    )
    from courses.models import MatchPair, MatchPairQuestionElement

    q = MatchPairQuestionElement.objects.create(stem="<p>Match</p>", distractors="Rome")
    MatchPair.objects.create(question=q, left="France", right="Paris")
    el = Element.objects.create(unit=unit, content_object=q)
    return course, unit, el


@pytest.mark.django_db(transaction=True)
def test_matchpair_no_js_select_path(live_server, browser):
    """No-JS match-pairs: pick the right token in the native <select>, submit, correct."""
    course, unit, el = _seed_matchpair_lesson("mpnojs", "mp-nojs")
    context = browser.new_context(java_script_enabled=False)
    page = context.new_page()
    _login(page, live_server, "mpnojs")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    page.locator('select[name="slot"]').select_option(value="Paris")
    page.locator('button[type="submit"]').click()
    assert page.locator(".is-correct").count() >= 1
    context.close()


@pytest.mark.django_db(transaction=True)
def test_matchpair_js_drag_path(live_server, page):
    """JS match-pairs: drag the 'Paris' chip onto the France row's slot → correct."""
    course, unit, el = _seed_matchpair_lesson("mpjs", "mp-js")
    _login(page, live_server, "mpjs")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    page.locator('.dnd__chip[data-token="Paris"]').drag_to(page.locator(".dnd__slot").first)
    assert page.locator('select[name="slot"]').first.input_value() == "Paris"
    page.locator('button[type="submit"]').click()
    assert page.locator(".is-correct").count() >= 1
```

Update the import block at the top of the file to add `Course`, `ContentNode`, `MatchPair`, `MatchPairQuestionElement` alongside the drag-fill imports (they are used by the quiz/match-pairs seeds).

- [ ] **Step 2: Run the e2e suite**

Run: `uv run pytest tests/test_e2e_questions_2d.py -m e2e -v`
Expected: PASS (7 tests). (Requires the Playwright browsers installed, as the existing 2c e2e does.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e_questions_2d.py
git commit -m "test(2d-i): Playwright e2e — drag-fill JS drag + no-JS select paths"
```

---

## Self-Review

**Spec coverage:**
- §2 data model → Task 1. §1.2 `build_pool` → Task 2. §3.2 `mark_slots` + `mark`/`build_answer` → Tasks 3-5. §1.2/§3.1 rendering (`<select>` base, empty placeholder, positional invariant) → Tasks 6-7. §3.3 reveal → Task 8. progressive-enhancement JS → Task 9. §4.1/§4.2 forms → Tasks 10-11. §4.4 authoring touchpoints (builder, views_manage allowlists/formset/menu/edit partials) → Tasks 12-13. §4.4 consumption touchpoints (prefetch, KaTeX lesson-only, question gate) → Task 14. §4.4 resume/round-trip pin → Task 15. **§5.1 quiz no-leak (withhold) + §5.4 results-page reveal (incl. unanswered, match-pairs `left`) → Task 16.** §5.3 i18n → Task 17. §5.4 e2e (lesson JS+no-JS, quiz withhold→reveal→resume, match-pairs JS+no-JS, slot-order integrity) → Task 18.
- Edge cases (§5.2): distractor-only, reusable token, partial/all-empty, normalize-equal, defensive length — covered by Task 3/4/5 unit tests; the **no-leak withhold** and **results-page reveal** paths are now pinned by Task 16; **edit-then-resume** is exercised by the Task 18 quiz-resume e2e (reload rehydrates the stored token-text placement). The no-leak signal for DnD types is the reveal-partial marker, not the bare token (which is a legitimate pool option) — see Task 16.

**Note on the e2e fixture / URL:** the lesson URL pattern `/courses/<slug>/u/<node_pk>/` and the `browser`/`page`/`live_server` fixtures are assumed from the existing 2c e2e; the executor should confirm the exact `reverse("courses:lesson_unit")` path and fixture names against `tests/test_e2e_quiz.py` when implementing Task 18 and adjust the literal URL if it differs.

**Placeholder scan:** no TBD/TODO; every code step carries real code. The only intentionally descriptive step is Task 9 step 3 (JS behavior verified by e2e, not a unit test) — flagged as such.

**Type consistency:** `expected_tokens()`, `build_pool(question)`, `mark_slots(expected, pool, chosen) -> (n_correct, reveal)`, `render_selects(token_stem, pool, chosen)`, `render_match_rows(pairs, pool, chosen)`, `parsed_dragblanks: list[str]`, `build_matchpair_formset(...)` are used consistently across tasks.
