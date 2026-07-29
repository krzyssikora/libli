# Slice 2 ledger — builder title filter + expand/collapse-all

Branch `worktree-builder-large-course-perf`. 17-task plan, executed Tasks 0–16.
This file is the slice verdict: per-task commit ranges, falsification results,
the measured numbers against the plan's target table, and every deviation with
its reason.

Companion: `2026-07-28-affected-tests-slice2.md` holds the Task 0 before-state
that every red below is classified against.

---

## 1. Per-task commit ranges

Baseline of the range is `48f49117` (the last plan-review commit). Every commit
below is on this branch, in order.

| Task | Commit(s) | Subject |
|---|---|---|
| 0 | `b9c81a08` | baseline the tests slice 2 can affect |
| 1 | `1e622598` | filter derivation module — fold, floor, match, walk |
| 2 | `5ccd8294` | q outranks both session reads; `_remember_open` gates on `q_active` |
| 3 | `43429abd` | FilterContext — one q resolution, restricted map, effect 2 |
| 4 | `99b5cb3b` | `manage_tree` endpoint + `data-tree-url` |
| 5 | `7f310d26` | `X-Builder-Info` header + always-present info slot |
| 6 | `0a926f1a`, `494b22b7` | q rides the no-JS path (forms, hrefs, redirects, picker) + review fix wave |
| 7 | `f9075f13` | `builder_force` — the no-JS force-include channel |
| 8 | `1df30b10` | suppress ordering while a filter is active |
| 9 | `a5b00bde`, `d4f5a547` | filter + bulk controls markup and CSS; min-width floor so the row wraps |
| 11 | `8367eb30` | applied-q tracker + `setTreeParams` across every request path |
| 12 | `f20e51fa` | filter fetch, clear path, stash, shared generation counter |
| 13 | `4e518179`, `44698ffc` | `X-Builder-Info` client registry + review fix wave |
| 14 | `796616a6`, `a3d93912`, `146db5b0` | expand-all / collapse-all; slice-1 minors; busy-counter review wave |
| 15 | `3d09e2d3`, `51df92c5` | eight new msgids; builder.html shadow-catalog stabilisation |
| 16 | this commit | measurements, dark-mode fix, ledger |

Task 10 produced no commit of its own on this branch; its work landed inside the
Task 9/11 commits and its report (`.superpowers/sdd/task-10-report.md`) records
the falsifications separately.

## 2. Falsification results

Not re-derived here — each task's own report under `.superpowers/sdd/` holds the
mutation, the RED exit code, and the restore. Summary of what those reports say,
read at Task 16:

- Tasks 1–5, 7–9, 11–15 each ran their briefed falsifications and **every
  mutation produced exit 1 (RED)** on the named row, followed by a restore and a
  green re-run.
- **Task 6 is the one exception worth carrying forward.** Falsification #1 *as
  the brief wrote it* **stayed GREEN** (exit 0). The executing agent did not
  wave it through: it strengthened the test with an added assertion and
  re-falsified to RED. Recorded because it is the concrete instance of this
  project's "falsify tests, don't run them" rule catching a vacuous guard.
- **Task 2** recorded a scoping correction: the "move below notice" mutation is
  not independent of the sentinel mutation (the two session reads are adjacent),
  so it reddens both named tests rather than one. The guard is still
  load-bearing; the brief's "must fail" list was just not exhaustive.
- **M16 (`window.addEventListener("blur", …)` disarm) ships unfalsified in this
  environment** and that is documented, with the concrete check that would flip
  it, in `2026-07-28-affected-tests-slice2.md` §"M16".
- **M10 was investigated and DROPPED**, not deferred — same file, §"M10".

## 3. Suite migration (Task 16 Step 1)

Five foreground invocations, one at a time, `-p no:warnings` so the exit code is
the sole verdict. **All five exited 0. There were no reds at all** — neither
migration nor regression.

| # | Files | Exit |
|---|---|---|
| 1 | `test_builder_filter`, `test_builder_filter_views`, `test_builder_open_ids`, `test_builder_lazy_scopes` | **0** |
| 2 | `test_manage_node_ops`, `test_manage_element_ops`, `test_manage_move_picker`, `test_manage_affordance`, `test_builder_styles`, `test_builder_js_invariants` | **0** |
| 3 | `test_i18n_po_health`, `test_manage_builder`, `test_tree_badge`, `test_manage_duplicate_button`, `test_builder_duplicate_unit`, `test_manage_node_duplicate` | **0** |
| 4 | `test_e2e_builder_filter`, `test_e2e_builder_toggle`, `test_e2e_builder_reorder` (`-m e2e`) | **0** |
| 5 | `test_e2e_builder_ws2`, `test_e2e_builder_authoring`, `test_e2e_builder`, `test_e2e_builder_tree_layout`, `test_e2e_inline_rename` (`-m e2e`) | **0** |

Chunks 2, 4 and 5 were run a **second** time after the CSS change in §6 below;
both runs exited 0.

Counts from `--collect-only -q` (never from parsing run output), against the
Task 0 baseline:

| File | Task 0 | Task 16 | Δ |
|---|---|---|---|
| `test_builder_filter.py` | — (new) | 11 | +11 |
| `test_builder_filter_views.py` | — (new) | 44 | +44 |
| `test_builder_lazy_scopes.py` | 32 | 36 | +4 |
| `test_builder_open_ids.py` | 15 | 20 | +5 |
| `test_manage_node_ops.py` | 31 | 31 | 0 |
| `test_manage_element_ops.py` | 14 | 15 | +1 |
| `test_manage_move_picker.py` | 2 | 2 | 0 |
| `test_manage_affordance.py` | 6 | 6 | 0 |
| `test_builder_styles.py` | 9 | 11 | +2 |
| `test_builder_js_invariants.py` | 2 | 2 | 0 |
| `test_manage_builder.py` | 18 | 18 | 0 |
| `test_builder_duplicate_unit.py` | 9 | 9 | 0 |
| `test_manage_node_duplicate.py` | 5 | 5 | 0 |
| `test_tree_badge.py` | 7 | 7 | 0 |
| `test_manage_duplicate_button.py` | 4 | 4 | 0 |
| `test_i18n_po_health.py` | 12 | 12 | 0 |
| **unit total** | **166** | **233** | **+67** |
| `test_e2e_builder_filter.py` | — (new) | 29 | +29 |
| `test_e2e_builder_toggle.py` | 16 | 16 | 0 |
| `test_e2e_builder_reorder.py` | 2 | 2 | 0 |
| `test_e2e_builder_ws2.py` | 9 | 9 | 0 |
| `test_e2e_builder_authoring.py` | 3 | 3 | 0 |
| `test_e2e_builder.py` | 3 | 3 | 0 |
| `test_e2e_builder_tree_layout.py` | 6 | 6 | 0 |
| `test_e2e_inline_rename.py` | 24 | 25 | +1 |
| **e2e total** | **63** | **93** | **+30** |

One `s` in chunk 5's dot output — the same single skip the Task 0 baseline
recorded (`test_window_blur_does_not_commit`, whose `document.hasFocus()` guard
trips in this environment). A skip is not a failure and does not move the exit
code.

**Verdict on the Task 0 rule.** The rule was that the five files named as
encoding changed behaviour *may* go red as intended migration, and anything else
going red is a regression. **Nothing went red.** The behaviour changes were
migrated into those files by the tasks that made them (visible as the count
deltas above), so there was nothing left to migrate at Task 16.
`test_manage_builder.py` — required to stay green throughout — is green at 18/18.

## 4. Measurements

### 4a. Which database

The perf data (`mat-pp`, 954 nodes) lives in the **shared dev database**; this
worktree's `.env` points `DATABASE_URL` at `libli_blcp` so pytest uses
`test_libli_blcp`. **Every probe below therefore carries an explicit
`DATABASE_URL=postgres://libli:libli@localhost:5432/libli` prefix.** Without it a
probe silently measures an empty database and prints plausible-looking nonsense.
Each probe's own output line `nodes in course : 954` is the receipt that it hit
the real data.

### 4b. Server-side template render (`scripts/perf/probe_tree_render.py`)

```
DATABASE_URL=postgres://libli:libli@localhost:5432/libli SLUG=mat-pp Q=trygo \
  uv run python manage.py shell -c "exec(open('scripts/perf/probe_tree_render.py').read())"
DATABASE_URL=postgres://libli:libli@localhost:5432/libli SLUG=mat-pp OPEN=all \
  uv run python manage.py shell -c "exec(open('scripts/perf/probe_tree_render.py').read())"
DATABASE_URL=postgres://libli:libli@localhost:5432/libli SLUG=mat-pp \
  uv run python manage.py shell -c "exec(open('scripts/perf/probe_tree_render.py').read())"
```

All exit 0. Conditions: `DEBUG=True` (the probe sets it, so `connection.queries`
is populated), warm template cache (the probe renders once before timing), one
process, no HTTP.

| Q | shown/total | open scopes | `<li>` rows | bytes | warm render | queries |
|---|---|---|---|---|---|---|
| `trygo` | 11 / 11 | 5 | 21 | 52,398 | **17.6 ms** | 1 |
| *(none)*, `OPEN=all` | — | 139 | 1,094 | 2,943,784 | **918.9 ms** | 1 |
| *(none)*, `OPEN` unset | — | 139 | 1,094 | 2,943,784 | **924.1 ms** | 1 |

The brief's third command is the second command: `OPEN` defaults to `"all"`, so
omitting it is not a distinct condition. Both are recorded rather than one being
silently dropped; the 918.9 / 924.1 ms pair also gives the run-to-run spread
(0.6 %) for this probe.

**`trygo` is not the worst case, so it cannot check the plan's `≥ 700 ms`
prediction** — that prediction is for ≈226 rows across ~126 scopes, and `trygo`
matches 11 titles. To find the real worst case I enumerated every 2–5 character
folded substring of all 954 titles and ran `filtered_map` on the 200 most common
(throwaway script, dev DB, not committed). The peak is `iz` at **212 tree rows
across 113 scopes** — close to the plan's ≈226/~126 estimate, which was
therefore a good structural prediction.

| Q | shown/total | open scopes | tree rows | `<li>` rows | bytes | warm render |
|---|---|---|---|---|---|---|
| `iz` (worst case found) | 100 / 103 | 113 | 212 | 326 | 825,975 | **281.8 ms** |
| `quiz` (realistic worst) | 95 / 95 | 115 | 212 | 326 | 827,061 | **272.8 ms** |
| `nie` | 100 / 228 | 91 | 187 | 281 | 704,938 | **243.7 ms** |

`<li>` counts exceed tree-row counts because `_add_affordance.html` contributes
an `<li>` per open scope.

### 4c. Browser round trips

Harness: Chromium (Playwright), 1400×900, `manage.py runserver --noreload` on
127.0.0.1:8010 with `DJANGO_DEBUG=true` and
`DATABASE_URL=postgres://libli:libli@localhost:5432/libli`. Single-threaded, no
cache, DEBUG on — so these are a **dev-server ceiling, not production
latency**. Every number below has a same-harness comparison so signal is
separable from floor.

Instrumentation: a `MutationObserver` on `.builder[data-busy]` plus a 50 ms
`setInterval` heartbeat, both installed before the gesture; the largest gap
between heartbeats is the worst main-thread block.

**Filter round trip**, `Q=iz` (the worst case from §4b):

| leg | ms |
|---|---|
| last keystroke → idle (**includes the 300 ms input debounce**) | **860** |
| keystroke → `data-busy` set | 349 |
| `data-busy` set → cleared | 511 |
| first tree request → idle | **526** |
| worst main-thread block | 179 |

One request: `GET /build/tree/?q=iz`. Rows after: **212** — matches the
server-side probe exactly. Info notice: **"Filtered: 100 / 103"** — matches
`shown=100 total=103`.

**Expand-all**, unfiltered, 954 nodes / 139 container scopes:

| leg | ms |
|---|---|
| click → idle | **1,244** |
| click → `data-busy` set | 89 |
| `data-busy` set → cleared | 1,155 |
| first tree request → idle | 1,179 |
| worst main-thread block | 608 |

Busy transitions recorded by the observer: `[[199, 1], [1386, 0]]` — **exactly
two**, i.e. `data-busy` went on once and off once and was continuously present
for the entire operation. Rows after: **954**. One request:
`GET /build/tree/?open=all&q=`.

**Toggle round trip.** Seven samples each, same harness, master served from the
main checkout on :8011 with the same `DATABASE_URL`:

| build | samples (gesture → idle, ms) | median |
|---|---|---|
| master `e13898c9` | 194, 196, 202, 203, 213, 235, 245 | **203 ms** |
| this branch | 192, 194, 195, 195, 200, 200, 238 | **195 ms** |

Under an active filter, re-expanding a scope: 217 ms gesture → idle, **122 ms
first request → idle** (`GET /build/node/109/scope/?open=<113 pks>&q=iz`).

*Collapsing* under a filter issues **no request at all** and never sets
`data-busy` — measured (`saw_busy: false`, zero tree requests). Under a filter
every kept container is in `chains`, so nothing arrives collapsed; the collapse
is pure DOM. The 2,133 ms figure in the raw JSON for that row is my own 2,000 ms
"wait for busy" timeout expiring, **not** a 2.1 s collapse.

**Unfiltered page load** (`scripts/perf/probe_browser.py`, three runs each):

| build | elements | rows | transfer | TTFB | wall |
|---|---|---|---|---|---|
| master `e13898c9` | 973 | 21 | 83 KB | 144–259 ms | 0.34 / 0.38 / 0.51 s |
| this branch | 976 | 21 | 84 KB | 119–149 ms | 0.31 / 0.35 / 0.39 s |

Command (branch):

```
BASE=http://127.0.0.1:8010 SESSION=<key> SLUG=mat-pp \
  uv run python scripts/perf/probe_browser.py
```

(the session key was minted with
`DATABASE_URL=postgres://libli:libli@localhost:5432/libli MINT=1 uv run python
manage.py shell -c "exec(open('scripts/perf/probe_browser.py').read())"`.)

### 4d. `_render_scope`'s full-cmap rebuild — reported, NOT optimised

Per the plan this is deliberately out of scope; narrowing it would help only the
*unfiltered* toggle (under a filter the full map is required by both
`_open_ids`'s sanitisation and the ancestor walk) and would fork the fragment
contract. Measured anyway so the decision rests on a number:

```
DATABASE_URL=postgres://libli:libli@localhost:5432/libli \
  uv run python manage.py shell -c "exec(open(<throwaway>).read())"
```

- `_children_map(course)` on `mat-pp`: **median 17.7 ms** (min 17.2, max 19.2, 7 samples)
- `filtered_map(cmap, 'iz')`: **median 3.2 ms**; `filtered_map(cmap, 'trygo')`: **3.1 ms**

**This falsifies the "~89 ms" figure the Task 16 brief carries** for that
rebuild: on today's code and today's `mat-pp` it is 17.7 ms, roughly 5× cheaper
than the brief states. Combined with the filter walk that is ~21 ms of the
122–126 ms fragment round trip, so the rebuild is not the binding constraint on
the toggle and the sanctioned remedy is not needed. **No optimisation was made.**

### 4e. Verdict against the plan's target table

| Metric | Target | Measured | Verdict |
|---|---|---|---|
| filter round trip | < 1 s | **860 ms** keystroke→idle (incl. 300 ms debounce); **526 ms** request→idle — worst-case `Q=iz`, 212 rows / 113 scopes | **PASS** |
| — its prediction | ≥ 700 ms | server render alone **281.8 ms** | prediction **FALSIFIED — too pessimistic** (see below) |
| expand-all | busy visible throughout; no "Page unresponsive" | busy on at t=199 ms, off at t=1386 ms, **two transitions, no gap**; worst main-thread block **608 ms** | **PASS** |
| — its prediction | ~2.5 s server-side | full round trip **1,244 ms**; server-side warm render **918.9 ms** | prediction **beaten** |
| toggle round trip | < 300 ms | **195 ms** median (branch) vs **203 ms** (master), same harness; **217 ms** filtered | **PASS**, no regression |
| unfiltered page load | no regression on 991 ms / 83 KB / 968 elements | **976 elements / 84 KB / 0.31–0.39 s** vs master **973 / 83 KB / 0.34–0.51 s** | **PASS** |

**On the falsified `≥ 700 ms` prediction.** The plan derived it from a row-linear
model (226 rows × ~2.6 ms/row from slice 1's 2,477 ms / 944 rows) and flagged it
as a *lower bound* on "the number most at risk". The measured worst case is
281.8 ms of template render for 212 rows — **~1.33 ms/row, half the modelled
rate**. The model assumed the per-row cost measured on a 944-row unfiltered
render carries over, but a large part of that cost is superlinear in total
output size (2.81 MB vs 0.79 MB here), so it does not. This is a prediction that
was too pessimistic, not a target that was missed; the target itself passes with
~140 ms of headroom on the request→idle leg.

**On the recorded 991 ms page-load baseline.** That wall-clock number is not
reproducible on today's harness for *either* build — master itself loads in
0.34–0.51 s here. So the 991 ms is a floor artefact of the harness it was
captured on, and the operative comparison is the same-harness master column,
which shows +3 elements and +1 KB (the filter form and the two bulk buttons) and
wall times inside each other's spread. The stable dimensions (elements, transfer,
rows) are the ones to trust.

**No target was missed.**

## 5. Screenshots (Task 16 Step 4)

Chromium 1400×900 and 700×900, light and dark **judged separately**, against
`mat-pp` on the dev server. Covered: the header at both widths, a filtered tree,
the "Filtered: n / m" notice, an empty filtered scope, and the disabled
grip/arrows. Screenshots are working artefacts and are not committed.

Measured DOM state under `Q=iz` (212 rows), which is what the "disabled
grip/arrows" requirement reduces to:

- `.ica--grip`: **212 present, 212 disabled**, `[draggable="true"]`: **0**
- reorder buttons (`[data-op="reorder"] button[name="direction"]`): **424
  present, 424 disabled**

Empty filtered scope (`?q=zzzqqq`): 0 rows, empty text **"No matching titles."**
(not the unfiltered "No children yet."), notice **"Filtered: 0 / 0"**, and the
add-affordance still rendered so the scope is not a dead end.

## 6. Deviations from the plan

1. **Extra probe runs beyond the three the brief lists.** `Q=trygo` matches 11
   titles, so it cannot test a target framed around ≈226 rows. I searched for the
   real worst case (`iz`, 212 rows / 113 scopes) and measured that too. Without
   it the `< 1 s` target would have been "confirmed" by a 17.6 ms render of a
   21-row tree — a pass for the wrong reason.

2. **Browser-side measurement added.** Three of the four targets (expand-all
   busy/responsiveness, toggle round trip, page load) are properties of the real
   page, which `probe_tree_render.py` cannot observe. I drove them with
   throwaway Playwright scripts and a `data-busy` MutationObserver, and served
   **master from the main checkout on a second port** so every number has a
   same-harness before. The main checkout was only read from and served; nothing
   was written to it and no branch was switched there.

3. **One CSS fix, outside Task 16's stated file list.** The dark-mode screenshot
   caught the new filter field rendering as a **white box**: `app.css:136` themes
   `input[type=text|email|password|url], select, textarea` and **`type=search` is
   not in that list**, and no `.input` class applies here. Measured computed
   style in dark mode before the fix: background `rgb(255,255,255)`, colour
   `rgb(242,239,233)` — the typed query at roughly **1.05:1 contrast, i.e.
   invisible**. After the fix: `rgb(21,19,15)` on `rgb(242,239,233)` in dark and
   `rgb(250,248,243)` on `rgb(30,28,24)` in light, both ≈16:1.

   The fix is four declarations on `.builder__filter input[type="search"]` in
   `builder.css`, mirroring `app.css:136` exactly except for `width` (the flex
   basis owns sizing). It was scoped to the one control this slice added rather
   than fixed platform-wide, because widening `app.css:136` to include
   `input[type=search]` would also apply `width: 100%` to the media-manager,
   link-dialog, roster and catalog search boxes and could move those layouts.

   **Latent platform defect, for the backlog — NOT introduced by this slice.**
   The same white-box-in-dark-mode bug is live on master today for every bare
   `input[type="search"]`: measured on master's `/manage/people/` search field,
   background `rgb(255,255,255)` / colour `rgb(189,182,168)`. Other instances:
   `templates/courses/catalog.html:26`, `templates/grouping/group_form.html:15`
   and `:34`. The real fix is to add `input[type=search]` to `app.css:136` and
   audit the four call sites for the `width: 100%` side effect.

4. **`-p no:warnings` on every pytest run.** The warnings summary prints full
   node IDs and this suite contains `..._after_a_FAILED_fetch...`, so an
   unanchored `grep FAILED` reports failures on a green run. Exit code is the
   sole verdict; counts come from `--collect-only -q`.

5. **One line added to the probe's output header** beyond the briefed diff:
   `q={Q!r} q_active={q_on}` on the `slug=… open=…` line, so a reader can tell a
   filtered run from an unfiltered one at a glance and can see the below-floor
   case without reading the code.

## 7. Open items before the PR

- The branch is **44 commits behind master**. It must be rebased and the `.mo`
  files regenerated *after* the rebase — a tracked binary `.mo` has no 3-way
  merge. Not done here: rebasing is the PR step, and this worktree has been
  switched under a running agent before.
- `grep -c "#, fuzzy"` returns **0 for both** `locale/pl` and `locale/en`
  catalogs, verified at Task 16.
- The dark-mode `input[type=search]` platform gap in §6.3 should be filed.
