# Sub-spec B3: switch_steps non-step content image extraction — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the LAL parser from dropping images (figures, bare `<img>`, image-tables) that sit as direct children of a `.switch_steps` container but outside any `.switch_step`.

**Architecture:** A single parser-only change in `scripts/lal_import/lesson.py`. `_emit_switch_gate_chain` currently iterates only `.switch_step` children; refactor it to (Task 1) extract the per-step body into a `_emit_switch_step` helper with no behaviour change, then (Task 2) iterate **all** direct children in document order — a `.switch_step` runs the helper (gate logic, `gate_idx` threaded); any other child is buffered and flushed through `_walk`, so figures/image-tables/bare-imgs/prose emit as native sibling elements. No model/loader/transfer/editor change.

**Tech Stack:** Python 3, BeautifulSoup 4 (`bs4`), pytest, `uv run` for all tooling.

## Global Constraints

- **Parser-only.** Touch only `scripts/lal_import/lesson.py` (production) and `tests/lal_import/test_lesson.py` (tests). No model, loader, transfer, or editor change.
- **Math `<`/`>` escaping:** never `str(NavigableString)` on math-bearing content (decodes `<`); the existing helpers (`_walk`, `_emit_figure`, `_emit_image_table`, `switch_line_stem_cyclers`) already handle this — do not add new serialization.
- **`gate_idx` threading invariant:** the SwitchGate answer index increments once per emitted gate in document order and is looked up positionally against `switch_answers[qid]`. Non-step content must never touch `gate_idx`.
- **Full-sibling-run invariant:** every `_walk` call receives a *full* list of siblings (sibling-context handlers — `_find_solution`, `_next_show_step`, `_emit_multi_many` — scan by index). Non-step children are buffered and flushed as ONE `_walk(run)` call, never walked one-at-a-time.
- **Tooling env:** run pytest as `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat DJANGO_SETTINGS_MODULE=config.settings.local uv run pytest …` from the worktree root. (The parser tests don't hit the DB, but the settings module import path expects these.)
- **Commit style:** end commit messages with the two trailer lines used on this branch (`Co-Authored-By: Claude …` / `Claude-Session: …`).

---

## File Structure

- `scripts/lal_import/lesson.py` — the only production file. `_emit_switch_gate_chain` (~line 693) is refactored; a new module-level `_emit_switch_step` is added immediately after it.
- `tests/lal_import/test_lesson.py` — new fixtures + test functions appended near the existing switch tests (`SWITCH_SHOW_NEXT` ~line 1005, `test_switch_show_next_becomes_switch_gate_chain` ~1027).

---

## Task 1: Extract `_emit_switch_step` helper (behaviour-preserving refactor)

Pure refactor: move the per-step body out of `_emit_switch_gate_chain` into a new helper, keeping the `find_all(class_="switch_step", recursive=False)` outer loop. No behaviour change — the existing switch tests are the regression guard.

**Files:**
- Modify: `scripts/lal_import/lesson.py:693-721` (`_emit_switch_gate_chain`)

**Interfaces:**
- Consumes: `_walk`, `_is_switch_gate_line`, `switch_line_stem_cyclers`, `strip_lead_prompt`, `_enclosing_qid` (all already imported/defined in the module).
- Produces: `_emit_switch_step(step, elements, flags, consumed, state, answers, gate_idx) -> int` — emits one `.switch_step`'s content (splitting on gate lines) and returns the updated `gate_idx`. Task 2 relies on this exact signature.

- [ ] **Step 1: Run the existing switch tests to confirm the green baseline**

Run:
```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat DJANGO_SETTINGS_MODULE=config.settings.local \
  uv run pytest tests/lal_import/test_lesson.py -k "switch" -v
```
Expected: PASS (`test_switch_show_next_becomes_switch_gate_chain`, `test_switch_confirm_becomes_switch_grid`, and any other `switch` tests).

- [ ] **Step 2: Refactor — extract the helper, keep the `find_all` loop**

Replace the whole body of `_emit_switch_gate_chain` (currently the `for step in container.find_all(...)` loop with the inline per-step logic) and add the new helper immediately after. The docstring on `_emit_switch_gate_chain` stays as-is for now (Task 2 updates it).

```python
def _emit_switch_gate_chain(container, elements, flags, consumed, state):
    """Group B #2: a .switch_steps block -> [step0 content][SwitchGate][step1
    content][SwitchGate]... Each .switch_step's trailing cycler line becomes a
    SwitchGate whose correct choice reveals the following siblings (the next
    step's content), mirroring the show_next RevealGate chain."""
    answers = state.get("switch_answers", {}).get(_enclosing_qid(container), [])
    gate_idx = 0
    for step in container.find_all(class_="switch_step", recursive=False):
        gate_idx = _emit_switch_step(
            step, elements, flags, consumed, state, answers, gate_idx
        )


def _emit_switch_step(step, elements, flags, consumed, state, answers, gate_idx):
    """Emit one .switch_step's content, splitting on its gate line(s): content
    before a gate line -> native siblings; the gate line -> a switch_gate dict
    (answer looked up positionally in `answers` by `gate_idx`). Returns the
    updated gate_idx so the caller threads it across steps."""
    content = []
    for child in step.children:
        if _is_switch_gate_line(child):
            _walk(content, elements, flags, consumed, state)
            content = []
            stem, cyclers = switch_line_stem_cyclers(child)
            options = cyclers[0]["options"] if cyclers else []
            raw = answers[gate_idx] if gate_idx < len(answers) else 0
            options, answer = strip_lead_prompt(options, raw)
            elements.append(
                {
                    "type": "switch_gate",
                    "stem": stem,
                    "options": options,
                    "answer": answer,
                }
            )
            gate_idx += 1
        else:
            content.append(child)
    _walk(content, elements, flags, consumed, state)
    return gate_idx
```

- [ ] **Step 3: Run the switch tests again to confirm no behaviour change**

Run:
```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat DJANGO_SETTINGS_MODULE=config.settings.local \
  uv run pytest tests/lal_import/test_lesson.py -k "switch" -v
```
Expected: PASS (identical to Step 1).

- [ ] **Step 4: Run the full lal_import suite (broader regression check)**

Run:
```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat DJANGO_SETTINGS_MODULE=config.settings.local \
  uv run pytest tests/lal_import/ -q
```
Expected: PASS (no failures).

- [ ] **Step 5: Commit**

```bash
git add scripts/lal_import/lesson.py
git commit -m "refactor(lal-parser): extract _emit_switch_step helper (no behavior change)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01DAtycPcTv4NLRZctpoTA1u"
```

---

## Task 2: Walk non-step direct children of `.switch_steps` (the behaviour change)

Change the outer loop to iterate **all** direct children in document order, buffering non-step children and flushing them as one `_walk(run)`. Add the falsifying tests first (RED), then the change (GREEN).

**Files:**
- Modify: `scripts/lal_import/lesson.py` (`_emit_switch_gate_chain` outer loop)
- Test: `tests/lal_import/test_lesson.py` (append fixtures + tests near the existing switch tests)

**Interfaces:**
- Consumes: `_emit_switch_step` (from Task 1), `_walk`, `Tag` (imported at `lesson.py:13`).
- Produces: no new public surface; `_emit_switch_gate_chain` now emits non-step content as native sibling `image`/`text`/`math` dicts in document order.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lal_import/test_lesson.py` (after the existing switch tests). Every fixture uses a real `.switch_steps` shell so dispatch reaches `_emit_switch_gate_chain`; `switch_answers` is set via the inline `setItem` script exactly as the existing fixtures do.

```python
# --- Sub-spec B3: non-.switch_step content of .switch_steps is now walked ---

# A <figure> before the first .switch_step (104_geometria_3 / 090_wstep shape).
SWITCH_FIGURE_BEFORE = r"""
<div id="question60">
  <div class="switch_steps">
    <figure><img alt="" src="static/fig1.png"/></figure>
    <div class="switch_step">
      <p>Krok pierwszy.</p>
      <div class="switch_line">
        <div class="switch_value">>> wybierz >></div>
        <div class="switch_value">\(a\)</div>
        <div class="switch_value">\(b\)</div>
        <div class="switch_show_next ks_button">zatwierdź</div>
      </div>
    </div>
    <div class="switch_step hidden"><p>Krok drugi.</p></div>
  </div>
</div>
<script>localStorage.setItem("switch_answers", JSON.stringify({60: [1]}));</script>
"""


def test_switch_nonstep_figure_before_steps_emitted():
    elements, flags = parse_lesson(SWITCH_FIGURE_BEFORE, "x.html")
    assert not any(e.get("flagged") for e in elements)
    imgs = [e for e in elements if e["type"] == "image"]
    assert [e["media_src"] for e in imgs] == ["static/fig1.png"]
    # the prompt figure renders BEFORE the first gate, in document order
    order = [e["type"] for e in elements]
    assert order.index("image") < order.index("switch_gate")
    # no empty text blocks from whitespace NavigableStrings between children
    assert all(e.get("body", "").strip() for e in elements if e["type"] == "text")


# An image-TABLE stranded as the first child of switch_steps (330 shape).
SWITCH_IMAGE_TABLE = r"""
<div id="question50">
  <div class="switch_steps">
    <div class="table_wrapper">
      <table class="my_table_noborder">
        <tr><td><img alt="" src="static/k1.png"/></td>
            <td><img alt="" src="static/k2.png"/></td></tr>
      </table>
    </div>
    <div class="switch_step">
      <p>Opis.</p>
      <div class="switch_line">
        <div class="switch_value">>> wybierz >></div>
        <div class="switch_value">\(a\)</div>
        <div class="switch_show_next ks_button">zatwierdź</div>
      </div>
    </div>
    <div class="switch_step hidden"><p>Dalej.</p></div>
  </div>
</div>
<script>localStorage.setItem("switch_answers", JSON.stringify({50: [1]}));</script>
"""


def test_switch_nonstep_image_table_unpacked():
    elements, flags = parse_lesson(SWITCH_IMAGE_TABLE, "x.html")
    assert not any(e.get("flagged") for e in elements)
    assert not any(e["type"] == "table" for e in elements)  # not a TableElement
    imgs = [e for e in elements if e["type"] == "image"]
    # assert on the src SET (robust to _emit_image_table caption-folding)
    assert {e["media_src"] for e in imgs} == {"static/k1.png", "static/k2.png"}
    assert "switch_gate" in [e["type"] for e in elements]


# A bare <img> direct child (090_trygonometria_1 / 080 shape).
SWITCH_BARE_IMG = r"""
<div id="question70">
  <div class="switch_steps">
    <img alt="" src="static/bare.png"/>
    <div class="switch_step"><p>Treść.</p></div>
  </div>
</div>
"""


def test_switch_nonstep_bare_img_emitted():
    elements, _ = parse_lesson(SWITCH_BARE_IMG, "x.html")
    imgs = [e for e in elements if e["type"] == "image"]
    assert [e["media_src"] for e in imgs] == ["static/bare.png"]


# Two gated steps with a figure BETWEEN them; distinct per-gate answers so a
# gate_idx mis-thread flips the second gate's answer.
SWITCH_GATE_CONTINUITY = r"""
<div id="question80">
  <div class="switch_steps">
    <div class="switch_step">
      <p>Krok 1.</p>
      <div class="switch_line">
        <div class="switch_value">>> wybierz >></div>
        <div class="switch_value">\(p\)</div>
        <div class="switch_value">\(q\)</div>
        <div class="switch_value">\(r\)</div>
        <div class="switch_show_next ks_button">zatwierdź</div>
      </div>
    </div>
    <figure><img alt="" src="static/mid.png"/></figure>
    <div class="switch_step hidden">
      <p>Krok 2.</p>
      <div class="switch_line">
        <div class="switch_value">>> wybierz >></div>
        <div class="switch_value">\(p\)</div>
        <div class="switch_value">\(q\)</div>
        <div class="switch_value">\(r\)</div>
        <div class="switch_show_next ks_button">zatwierdź</div>
      </div>
    </div>
  </div>
</div>
<script>localStorage.setItem("switch_answers", JSON.stringify({80: [2, 1]}));</script>
"""


def test_switch_gate_continuity_with_nonstep_between():
    elements, _ = parse_lesson(SWITCH_GATE_CONTINUITY, "x.html")
    gates = [e for e in elements if e["type"] == "switch_gate"]
    assert len(gates) == 2
    # strip_lead_prompt drops the ">> wybierz >>" placeholder and decrements:
    # LAL 2 -> libli 1 (gate 0), LAL 1 -> libli 0 (gate 1). Distinct: a
    # gate_idx mis-thread (both reading answers[0]) would make gate 1 == 1.
    assert gates[0]["answer"] == 1
    assert gates[1]["answer"] == 0
    # the mid figure renders between the two gates
    order = [e["type"] for e in elements]
    img_i = next(i for i, e in enumerate(elements) if e["type"] == "image")
    assert order.index("switch_gate") < img_i < len(order) - 1
    assert order[img_i + 1 :].count("switch_gate") == 1


# Regression guard for the buffer-and-flush invariant: a show_solution button
# immediately followed by its sibling .question_solution (two adjacent non-step
# children) must pair into ONE solution region, not two unmapped flags.
SWITCH_SIBLING_COUPLED = r"""
<div id="question90">
  <div class="switch_steps">
    <div class="show_solution ks_button">zobacz</div>
    <div class="question_solution hidden"><p>Rozwiązanie.</p></div>
    <div class="switch_step"><p>Krok.</p></div>
  </div>
</div>
"""


def test_switch_nonstep_sibling_coupled_pairs_into_one_region():
    elements, _ = parse_lesson(SWITCH_SIBLING_COUPLED, "x.html")
    # buffer-and-flush walks [button, solution, ...] together so _find_solution
    # pairs them into a single spoiler; per-child walking would emit two flags.
    assert sum(1 for e in elements if e["type"] == "spoiler") == 1
    assert not any(e.get("flagged") for e in elements)


# A bare <div> carrying a cycler but LACKING the switch_step class (280 shape):
# the image is recovered; the cycler renders as static content (not asserted).
SWITCH_BARE_DIV_CYCLER = r"""
<div id="question760">
  <div class="switch_steps">
    <div>
      <img alt="" src="static/wyc.png"/>
      <div class="switch_line">
        <div class="switch_value">>> wybierz >></div>
        <div class="switch_value">\(2\pi r\)</div>
      </div>
    </div>
    <div class="switch_step hidden"><p>Koniec.</p></div>
  </div>
</div>
"""


def test_switch_nonstep_bare_div_with_cycler_recovers_image():
    elements, _ = parse_lesson(SWITCH_BARE_DIV_CYCLER, "x.html")
    imgs = [e for e in elements if e["type"] == "image"]
    assert "static/wyc.png" in [e["media_src"] for e in imgs]
```

- [ ] **Step 2: Run the new tests to verify they fail (RED)**

Run:
```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat DJANGO_SETTINGS_MODULE=config.settings.local \
  uv run pytest tests/lal_import/test_lesson.py -k "nonstep or gate_continuity" -v
```
Expected: FAIL. `test_switch_nonstep_figure_before_steps_emitted`, `_image_table_unpacked`, `_bare_img_emitted`, `_bare_div_with_cycler_recovers_image` fail on the empty `imgs` list (images dropped today). `test_switch_gate_continuity_with_nonstep_between` fails because the `image` for `mid.png` is absent. `test_switch_nonstep_sibling_coupled_pairs_into_one_region` fails because today the non-step button+solution are dropped entirely (0 spoilers) — it is a regression guard for the buffer-and-flush choice, not a master-vs-design RED; to observe its per-child RED, temporarily flush each non-step child individually (see Step 4 note).

- [ ] **Step 3: Implement — iterate all direct children with buffer-and-flush**

Replace the `_emit_switch_gate_chain` body (the `find_all` loop from Task 1) with the document-order buffer-and-flush loop, and update its docstring. `_emit_switch_step` is unchanged.

```python
def _emit_switch_gate_chain(container, elements, flags, consumed, state):
    """Group B #2: a .switch_steps block -> [non-step content][step0 content]
    [SwitchGate][step1 content][SwitchGate]... Direct children are visited in
    document order: a .switch_step becomes gate-split content (via
    _emit_switch_step); any other direct child (a stranded <figure>, bare <img>,
    image-table, or prose) is buffered and walked as native siblings in place, so
    its images/text survive. Non-step children never emit a gate, so gate_idx (the
    positional index into switch_answers[qid]) is untouched by them."""
    answers = state.get("switch_answers", {}).get(_enclosing_qid(container), [])
    gate_idx = 0
    pending = []  # consecutive non-step children, flushed as ONE sibling run
    for child in container.children:
        if isinstance(child, Tag) and "switch_step" in (child.get("class") or []):
            if pending:
                _walk(pending, elements, flags, consumed, state)
                pending = []
            gate_idx = _emit_switch_step(
                child, elements, flags, consumed, state, answers, gate_idx
            )
        else:
            pending.append(child)
    if pending:
        _walk(pending, elements, flags, consumed, state)
```

- [ ] **Step 4: Run the new tests to verify they pass (GREEN)**

Run:
```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat DJANGO_SETTINGS_MODULE=config.settings.local \
  uv run pytest tests/lal_import/test_lesson.py -k "nonstep or gate_continuity" -v
```
Expected: PASS (all six new tests).

Optional RED-observation for the buffer-and-flush guard (do NOT commit this): temporarily change the flush lines to `for c in pending: _walk([c], …)`, rerun `test_switch_nonstep_sibling_coupled_pairs_into_one_region`, confirm it fails (two `flagged` elements, 0 spoilers), then restore the buffered `_walk(pending, …)` form.

- [ ] **Step 5: Run the full lal_import suite (regression)**

Run:
```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat DJANGO_SETTINGS_MODULE=config.settings.local \
  uv run pytest tests/lal_import/ -q
```
Expected: PASS. The existing `test_switch_show_next_becomes_switch_gate_chain` / `test_switch_confirm_becomes_switch_grid` still pass (single-`switch_steps`-of-only-steps case is unchanged behaviour).

- [ ] **Step 6: Lint**

Run:
```bash
uv run ruff check scripts/lal_import/lesson.py tests/lal_import/test_lesson.py
uv run ruff format --check scripts/lal_import/lesson.py tests/lal_import/test_lesson.py
```
Expected: no errors. (If `ruff format --check` reports diffs, run `uv run ruff format` on the two files and re-run.)

- [ ] **Step 7: Commit**

```bash
git add scripts/lal_import/lesson.py tests/lal_import/test_lesson.py
git commit -m "feat(lal-parser): walk non-.switch_step content of switch_steps (sub-spec B3)

Recovers figures/bare-imgs/image-tables stranded as direct children of
.switch_steps but outside any .switch_step (330's 6-diagram table, the
104_* figure group, 080/280/290/300). 17 imgs / 9 files; image loss 40 -> 23.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01DAtycPcTv4NLRZctpoTA1u"
```

---

## Task 3: Integration verification (secondary cross-check + live reload)

Not a unit test — the corpus measure and live render confirm the slice end-to-end. The binding gate was Task 2's `test_lesson.py`; this task is the belt-and-suspenders check.

**Files:** none modified (measurement + manual verification only).

- [ ] **Step 1: Re-measure the corpus image loss**

Run the classifier (session scratchpad; parses source HTML live, so no reseed needed). Concrete path this session:
```bash
SCRATCH="C:/Users/krzys/AppData/Local/Temp/claude/C--Users-krzys-Documents-Python-own-libli--claude-worktrees-matematyka-content-import/3d978e0d-998a-49aa-ba37-f4912685068b/scratchpad"
PYTHONPATH="$PWD" DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat DJANGO_SETTINGS_MODULE=config.settings.local \
  uv run python "$SCRATCH/classify_lost_imgs.py"
```
(If a fresh session lacks the script, reconstruct per the spec's "Integration / count" reconstruction algorithm.)
Expected: `TOTAL lost = 23 across 12 files` (was 40 / 21). The nine B3 files (330, 080, 290, 280, 090_wstep, 020_wstep, 180_trapezy, 620_podobne, 300_odleglosci) drop out of the losing set; no NEW file appears. If any B3 file still shows a lost image, investigate before proceeding.

- [ ] **Step 2: 007/funkcje_030 gate cross-check (optional manual)**

Confirm an unaffected multi-gate corpus file is byte-identical before/after: parse `007_*/funkcje_030…` (or the verified-4-gate file) with `parse_lesson` and confirm the `switch_gate` stems/options/answers/count are unchanged from `git stash`-ed master. (Skip if Step 1 is clean and the suite is green — this is redundant insurance.)

- [ ] **Step 3: Reseed + reload the two highest-value parts into libli_mat**

```bash
uv run python -m scripts.lal_import.parser 050_ulamki_algebraiczne --source-root "C:/Users/krzys/Documents/teaching/LAL/html" --force
uv run python -m scripts.lal_import.parser 104_geometria_3_czworokaty --source-root "C:/Users/krzys/Documents/teaching/LAL/html" --force
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat DJANGO_SETTINGS_MODULE=config.settings.local \
  uv run python manage.py import_lal_content --course matematyka --part 050_ulamki_algebraiczne --source-root "C:/Users/krzys/Documents/teaching/LAL/html" --json-dir scripts/lal_import/out --allow-html
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat DJANGO_SETTINGS_MODULE=config.settings.local \
  uv run python manage.py import_lal_content --course matematyka --part 104_geometria_3_czworokaty --source-root "C:/Users/krzys/Documents/teaching/LAL/html" --json-dir scripts/lal_import/out --allow-html
```
Expected: both parts load without error. (If a part aborts on a pre-existing missing-source-video `FileNotFoundError`, that is the known deferred Minor, unrelated to this slice — note it and continue with the part that loaded.)

- [ ] **Step 4: Render-check 330's unit + spot-check for text leaks**

Start the DEBUG server (worktree `.env` supplies DEBUG + libli_mat + media):
```bash
uv run python manage.py runserver 127.0.0.1:8000
```
Log in as `pilot` / `pilot-pass-123`. Open the unit for `050_ulamki_algebraiczne/330_funkcja_homograficzna` and confirm the six `homograficzna_ksztalt_*` diagrams now render (as `<img>`) in the switch sequence, and a `104_geometria_3_czworokaty` figure unit shows its recovered `<figure>` image. Spot-check the reloaded units for stray chrome text newly surfaced by the non-step walk (previously-dropped content now appearing as unwanted paragraphs) — none expected; if any appears, capture the unit + snippet.

- [ ] **Step 5: Hand the user the URLs + re-measure summary**

Report to the user: the classifier total (40 → 23), and the render URLs (`/courses/matematyka/u/<id>/` for 330's unit and a 104 figure unit) with a one-line note on what each demonstrates.
