# Sub-spec B3: switch_steps non-step content image extraction

## Purpose

Sub-spec B of the matematyka image-loss recovery is the parser-only tail. After
B1 (reveal-table `question_answer` prompts) shipped, **40 images / 21 files**
remain (`classify_lost_imgs.py` buckets: `question_div_stem` 15,
`reveal_table_cell` 11, `details_nontable` 10, `inline_or_other` 2,
`fill_table_cell` 2). Per the B1 lesson, those buckets are **coarse heuristics
that do not map 1:1 to parser mechanisms**; a per-file DOM investigation of all 21
files regrouped the losses into five real mechanisms. **This slice (B3) is the
largest and cleanest: content that is a direct child of a `.switch_steps`
container but is NOT a `.switch_step` — 16 images across 9 files.**

A LAL `switch_steps` block is a cycler-gated progressive reveal, mapped by
`scripts/lal_import/lesson.py:_emit_switch_gate_chain` (lesson.py ~693) to a
SwitchGate chain: `[step0 content][SwitchGate][step1 content][SwitchGate]…`. It
iterates **only** `container.find_all(class_="switch_step", recursive=False)` and
walks each step's content. **Any direct child of `.switch_steps` that is not a
`.switch_step` is never visited, so its images are silently dropped** — this
includes a leading `<figure><img>`, a bare `<img>`, an image-table
(`div.table_wrapper > table.my_table_*` of diagrams), intervening `<p>`/`<ul>`
prose, and un-classed step-like `<div>`s.

### Affected files (per-image DOM investigation, not bucket labels)

Each lost image below was confirmed to be **NON-STEP direct content of
`.switch_steps`** (via `parents` walk: nearest `.switch_steps` ancestor reached
with no intervening `.switch_step`):

| File | imgs | Non-step shape |
|---|---|---|
| `050_ulamki_algebraiczne/330_funkcja_homograficzna` | 6 | `div.table_wrapper > table.my_table_noborder.vertical_table` image-table (first child of `switch_steps`) |
| `090_trygonometria_1/080_tryg_dowolne_katy` | 2 | bare `<img>` (question60) + bare `<img>` (question70), first child of each `switch_steps` |
| `104_geometria_3_czworokaty/290_romby` | 2 | two `<figure><img>` direct children |
| `100_geometria_2/280_kolo_okrag` | 2 | two bare `<div>` (carry a `>> wybierz >>` cycler but LACK the `switch_step` class) — see caveat |
| `104_geometria_3_czworokaty/090_wstep` | 1 | `<figure><img>` direct child |
| `104_geometria_3_czworokaty/020_wstep` | 1 | `<figure><img>` direct child |
| `104_geometria_3_czworokaty/180_trapezy` | 1 | `<figure><img>` direct child |
| `104_geometria_3_czworokaty/620_podobne` | 1 | `<figure><img>` direct child |
| `140_geometria_analityczna_2/300_odleglosci` | 1 | `<figure><img>` direct child |

Total **16**. Note this pulls images the classifier labelled `reveal_table_cell`
(330's 6 — its table has a `my_table*` class so the classifier bucketed it as a
reveal cell, but there is no `show_solution`/`question_solution`, so it is NOT a
reveal table; it is a plain image-table stranded in `switch_steps`) and
`details_nontable` (the `<figure>`s, whose only shared trait was a `<details>`
ancestor). The true mechanism is identical for all 16: **non-`.switch_step`
direct children of `.switch_steps` are never walked.**

## Scope

- **In scope:** in `_emit_switch_gate_chain`, walk **every** direct child of the
  `.switch_steps` container in document order — a `.switch_step` runs the existing
  per-step content/gate logic (unchanged); anything else is routed through `_walk`
  in place, so figures/image-tables/bare-imgs/prose emit as native sibling
  elements in reading order relative to the gates. Parser-only
  (`_emit_switch_gate_chain` + one extracted helper, `scripts/lal_import/lesson.py`).
- **Out of scope (other B slices):**
  - **B-reveal — reveal-table non-solution-cell images (3 / 2):**
    `090_trygonometria_1/011_zwiazki_tryg` (2, first-`<td>` label-cell diagrams),
    `104_geometria_3_czworokaty/040_wstep` (1, a `<figure>` in a `<tr>` with no
    `question_solution`, skipped by `_reveal_table_spoilers`).
  - **B2 — one_choice / stem prompt images (6 / 3):**
    `100_geometria_2/180_pole_trojkata` (3, `<img>` in `div.statement` of a
    one_choice list), `030_kwadratowa/kwadratowa_140_wlasnosci` (2, image cells in
    a one_choice *table*), `080_geometria_analityczna/110_geo_an` (1, bare stem div).
  - **B-fill — fill_step images (6 / 2):** `090_trygonometria_1/040`+`044_tryg_tozsamosci`.
  - **B-tail (9 / ~6):** `020_uklady_rownan/uk_rown_30` slideshow (3),
    `030_kwadratowa/kwadratowa_161`+`162` tab-panel (2), `100_geometria_2/250_pole_trojkata`
    mixed fill-cell (2), `100_geometria_2/030_twierdzenie_sinusow` img-inside-gate-line (1).
- **No model, loader, transfer, or editor change** — recovered content is ordinary
  `image`/`text`/`math`/`video` dicts the pipeline already renders, transfers, and edits.

## Background: the current switch-chain path

- **`_walk` dispatch (lesson.py ~371):** a `<div class="switch_steps">` →
  `_emit_switch_gate_chain(node, elements, flags, consumed, state)`.
- **`_emit_switch_gate_chain(container, elements, flags, consumed, state)`
  (lesson.py ~693):**
  ```
  answers = state.get("switch_answers", {}).get(_enclosing_qid(container), [])
  gate_idx = 0
  for step in container.find_all(class_="switch_step", recursive=False):
      content = []
      for child in step.children:
          if _is_switch_gate_line(child):      # a .switch_line carrying .switch_show_next
              _walk(content, …); content = []
              stem, cyclers = switch_line_stem_cyclers(child)
              options = cyclers[0]["options"] if cyclers else []
              raw = answers[gate_idx] if gate_idx < len(answers) else 0
              options, answer = strip_lead_prompt(options, raw)
              elements.append({"type":"switch_gate","stem":stem,"options":options,"answer":answer})
              gate_idx += 1
          else:
              content.append(child)
      _walk(content, …)
  ```
  The outer `find_all(class_="switch_step", recursive=False)` is the defect: it
  skips every non-`switch_step` direct child.
- **`_walk` already routes images correctly** (proven by B1 and the nestable-spoiler
  work): a bare `<img>` → `ImageElement`; a `<figure><img>` → `_emit_figure`
  (figcaption preserved); a `<div class="table_wrapper"><table>` of diagrams →
  descend → the `name == "table"` branch → (no `table_input`, not
  `_is_reveal_table`) → `node.find("img")` → `_emit_image_table` (cells unpacked to
  captioned `ImageElement`s); a text block containing `<img>` → the prose split
  (`_emit_text_with_images`). So walking non-step children needs no new emitter.
- **`gate_idx` semantics:** the SwitchGate answer index increments once per emitted
  gate, in document order, and is looked up positionally against
  `switch_answers[qid]`. It MUST keep incrementing across steps exactly as today —
  walking non-step content between steps must NOT touch `gate_idx` (non-step content
  has no gates).

## Design

Refactor `_emit_switch_gate_chain` so the outer loop visits **all** direct
children of `container` in document order, dispatching by whether a child is a
`.switch_step`:

```
def _emit_switch_gate_chain(container, elements, flags, consumed, state):
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

**Non-step children are buffered and flushed as a full sibling run, NOT walked
one-at-a-time.** Every existing `_walk` call receives a *full* list of siblings, and
several handlers depend on that sibling context — `_emit_multi_many` /
`_emit_widget_placeholder` coalesce consecutive siblings; the `show_next`
(`_next_show_step`) lookahead and the `show_solution` button
(`_find_solution` / `_followed_by_show_solution`) scans inspect neighbouring nodes
by index. Passing each non-step child in its own one-element list would silently
break these (e.g. a `show_solution` button and its sibling `question_solution` div,
both non-step children, would each be walked alone → two spurious "unmapped" /
"button without solution" flags instead of one solution region). Buffering the run
between steps and flushing once (mirroring the step-content buffer in
`_emit_switch_step`) preserves the invariant. None of the 9 affected files contains
such sibling-coupled non-step content today, but the buffer-and-flush formulation
costs nothing and removes the latent regression.

The per-step body (the inner `for child in step.children` content/gate loop) moves
verbatim into a new helper that returns the updated `gate_idx`:

```
def _emit_switch_step(step, elements, flags, consumed, state, answers, gate_idx):
    content = []
    for child in step.children:
        if _is_switch_gate_line(child):
            _walk(content, elements, flags, consumed, state); content = []
            stem, cyclers = switch_line_stem_cyclers(child)
            options = cyclers[0]["options"] if cyclers else []
            raw = answers[gate_idx] if gate_idx < len(answers) else 0
            options, answer = strip_lead_prompt(options, raw)
            elements.append({"type":"switch_gate","stem":stem,"options":options,"answer":answer})
            gate_idx += 1
        else:
            content.append(child)
    _walk(content, elements, flags, consumed, state)
    return gate_idx
```

Behaviour: a `.switch_step` child produces the same `[content…][SwitchGate]…`
sequence as today, with `gate_idx` threaded through; a non-step child (figure,
image-table, bare img, prose) is walked in place, emitting its native elements in
document order. Result for e.g. 330: `[6 image-table ImageElements][step0
content][gate?]…`; for 090_wstep: `[figure ImageElement][prose text][step
content + gates]`.

`container.children` yields `NavigableString` whitespace nodes between the block
children; they accumulate into `pending` and are stripped by `_walk`'s
`NavigableString` branch when the run is flushed, so passing them through is a
no-op — no need to pre-filter.

### Edge cases (pin in planning)

- **`gate_idx` continuity:** the helper returns the running index; the outer loop
  reassigns it. Non-step children never emit gates, so they never consume an answer
  slot — identical gate→answer alignment to today. A regression test on an existing
  multi-gate file (007/funkcje_030, verified 4 gates) must show byte-identical gate
  stems/options/answers and count.
- **Ordering:** document order is preserved because we iterate `container.children`
  directly (not a `find_all` that would re-group). A prompt figure that precedes the
  first `switch_step` now renders before the first gate; an image-table between two
  steps renders between them.
- **280_kolo_okrag caveat (accepted, known-minor):** its two images sit in bare
  `<div>`s that carry a `>> wybierz >>` cycler but LACK the `switch_step` class
  (source authoring quirk). With this change those divs are `_walk`ed → the image is
  recovered as an `ImageElement`, but the cycler renders as **static text** (`>>
  wybierz >>` + the option spans) rather than an interactive SwitchGate. This is
  strictly better than today (image AND text both dropped). Do NOT add special
  handling to re-interpret an un-classed div as a step — out of scope; note it.
- **`_is_switch_gate_line` on a non-Tag:** unchanged — it already guards
  `isinstance(node, Tag)`. The new outer-loop `isinstance(child, Tag)` guard mirrors
  it so a whitespace `NavigableString` is treated as non-step and walked (stripped).
- **Nested `switch_steps`:** none observed among the 9 files as a *direct* child of
  another `switch_steps`; if one occurred, the inner `switch_steps` (a non-step
  child) would be `_walk`ed → its own `_emit_switch_gate_chain` runs (recursion),
  which is correct. No special handling needed.
- **No `consumed` change:** the container is fully handled here; its descendants are
  never enqueued elsewhere. Do not add `consumed.add`.
- **In-spoiler / in-tabs context:** `_emit_switch_gate_chain` is reached via `_walk`,
  which may run inside a spoiler's or tab's child list. Walking non-step content
  there emits into that same child list (inline), consistent with how step content
  already behaves. `state` (incl. `in_spoiler`) flows through unchanged.

### Why parser-only

Every recovered element is one the loader/renderer/transfer/editor already handle
(`ImageElement`, `TextElement`, `MathElement`, `VideoElement`, and — for 330 — the
`_emit_image_table` sequence of `ImageElement`s). The only change is the parser
ceasing to skip non-step children.

## Testing

TDD, falsifiable (RED first). Extend the switch-chain tests in
`tests/lal_import/test_lesson.py` (the `_emit_switch_gate_chain` / SwitchGate
coverage from Group B #2). Fixtures must include a real `.switch_steps` shell so
dispatch reaches `_emit_switch_gate_chain`.

- **Non-step figure before steps:** a `switch_steps` whose first child is
  `<figure><img src="p.png"></figure>` followed by a `.switch_step` (with a
  `switch_show_next` gate line) emits, in order, an `image` for `p.png` THEN the
  step content THEN a `switch_gate`. RED today (only the gate/step emitted; `p.png`
  dropped).
- **Non-step image-table (330 shape):** a `switch_steps` whose first child is
  `div.table_wrapper > table.my_table_noborder` with N image cells and **no label
  rows** (so `_emit_image_table`'s caption-folding does not collapse a cell) emits N
  `image` elements before the step/gate sequence. Assert on the set of emitted
  `image` `media_src`s matching the N fixture srcs, not a bare element count (a label
  cell directly above an image is folded into its `figcaption`, changing the count).
  RED today.
- **Bare `<img>` direct child (080 shape):** emitted as an `image`.
- **Gate continuity regression:** a two-step, two-gate `switch_steps` with a
  non-step figure between the steps still emits exactly two `switch_gate`s with the
  same stems/options/answers as without the figure (asserts `gate_idx` threading).
- **Bare-div-with-cycler (280 shape):** a non-`switch_step` `<div>` holding an
  `<img>` and a `>> wybierz >>` cycler emits the `image`; assert the image is
  present (the static-cycler text is acceptable, not asserted precisely).
- **Whitespace-only children** between steps produce no spurious element.
- **Regression:** existing SwitchGate tests (stem token, options, answer index,
  step content order) still pass unchanged.
- **Primary acceptance gate = repo tests, not the out-of-tree measure.** The
  binding pass/fail criterion is the `test_lesson.py` assertions above, which live in
  the repo and any session can run (`uv run pytest tests/lal_import/test_lesson.py`).
  The 40→24 corpus measure is a **secondary cross-check**, not the gate, because it
  depends on tooling outside the repo.
- **Integration / count (secondary cross-check):** re-parsing the 9 affected files,
  total lost drops **40 → 24** and every listed non-step image is emitted.
  **Measurement prerequisites:** the external source tree
  (`C:/Users/krzys/Documents/teaching/LAL/html`) must be present; the
  measure/classifier scripts are NOT in the repo — they live in this session's
  scratchpad (`…/3d978e0d-998a-49aa-ba37-f4912685068b/scratchpad/`, files
  `measure_lost_imgs_recursive.py`, `classify_lost_imgs.py`, `ancestry.py`) and were
  copied forward from the prior session; both already count fill-table image cells and
  parse source HTML live (no reseed needed to measure). If a fresh session lacks them,
  reconstruct from the algorithm: parse each `NNN_*/….html` under the source root with
  `parse_lesson`, recursively collect every emitted `image` `media_src` (descending
  `elements`/`tabs`, plus `fill_table` `data.cells` image kinds), diff against
  `soup.find_all("img")` srcs, and count the shortfall. Run with
  `PYTHONPATH=<worktree> DATABASE_URL=…libli_mat DJANGO_SETTINGS_MODULE=config.settings.local`.
  Reseed a part (`parser <part> --force`) only before *loading* it.

## Verification

- Re-measure (`classify_lost_imgs.py`): total 40 → 24; the 16 listed images gone
  from the lost set; no new lost images introduced.
- Reseed + reload the two highest-value parts into `libli_mat`
  (`050_ulamki_algebraiczne` for 330's 6-image table; `104_geometria_3_czworokaty`
  for the figure group), render a sample unit (330's unit: the 6 `homograficzna_ksztalt`
  diagrams now visible in the switch sequence). Spot-check for text leaks
  (previously-dropped chrome newly surfaced as text) across the reloaded units.
  Hand the user the URLs (DEBUG server per the worktree `.env`).

## Out of scope / follow-up slices

See Scope above: B-reveal (reveal-table label/non-solution cells, 3), B2
(one_choice/stem prompts, 6), B-fill (fill_step images, 6), B-tail (slideshow +
tab-panel + mixed fill-cell + gate-line img, 9). Each is an independent parser
slice with its own spec; re-measure after each.
