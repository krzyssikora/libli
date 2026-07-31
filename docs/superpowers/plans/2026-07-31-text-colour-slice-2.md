# Text Colour (Slice 2 — Backfill) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the colour the LAL import dropped, by rewriting imported `mat-pp` content in place — matched on content, never on node identity — through a guarded, dry-run-by-default management command run locally before the prod export.

**Architecture:** For every colour-bearing field occurrence in `scripts/lal_import/out/**.json` we build two strings. The **key** replays the sanitiser *as it behaved before slice 1* over the source with every `<span>` unwrapped — that is byte-identical to what the loader actually stored. The **value** replays the *current* sanitiser over the same source with palette colours turned into `tc-*` classes on legal carriers. A DB field is rewritten only when its stored string is byte-identical to a key. Nothing reads or writes `ContentNode.title`.

**Tech Stack:** Django management command, nh3, BeautifulSoup (`html.parser`), pytest.

**Spec:** `docs/superpowers/specs/2026-07-30-text-colour-design.md` — read the "Backfill command", "Key construction", "Acceptance gate", "Matching contract", "Exclusion (D7)" and "Appendix" sections before starting. This plan implements **slice 2 only**; slice 1 shipped as PR #198 and is in `origin/master`.

**Prior ledger:** `.superpowers/sdd/progress.md` holds slice 1's execution ledger. Task 0 archives it.

---

## Measurements already taken (do not re-derive; do falsify if a later step disagrees)

These were run by the plan author against the real corpus and the real local `libli`
database before this plan was written. They are stated here because they close design
questions the spec left open, and because Task 1 must reproduce and extend them.

| # | Claim | How it was measured |
|---|---|---|
| M1 | **A bs4 round-trip is byte-identical on every colour-bearing source value.** 0 of 319 differ. So `BeautifulSoup(x, "html.parser").decode_contents()` may be used for the tree surgery without a byte-fidelity fallback — but the guard in Task 5 Step 3 stays, because it converts a future corpus change from silent corruption into a reported skip. | Walked every `out/*/*.json`, collected every `body`/`stem`/`success_message`/`raw`/`lines[*].stem`/`data.cells[r][c].html` string, filtered on `style="…color`, compared `decode_contents()` to the source. |
| M2 | **`<font color=…>` does not occur.** 0 occurrences among colour-bearing values. Colour arrives only as a `style` attribute. | Same walk. |
| M3 | **Key construction is right for the `sanitize_html` shape: 172 of 172 distinct keys matched (100%).** Built from `text`/`spoiler` bodies in eligible parts (001_/002_ excluded) via span-unwrap → `nh3.clean(…, allowed_classes=LEGACY_ALLOWED_CLASSES)`, looked up against the 10,396 stored `TextElement.body` values in `mat-pp`. | `DATABASE_URL=…/libli uv run python` probe. |
| M4 | **`out/*/flags.json` is a JSON *list*, not a dict.** The source walk must skip `manifest.json` **and** `flags.json`, or it raises `AttributeError: 'list' object has no attribute 'get'`. | Same walk (it crashed until guarded). |
| M5 | **The two excluded parts' node pks in the local `mat-pp` course are `001_zbiory_liczbowe` → **109** and `002_elementy_logiki` → **153**.** Do not hardcode these in code — they are command-line arguments — but they are the values Task 8/9 pass. | `ContentNode.objects.filter(course=mat-pp, parent=None)`. |

M3 covers only the `sanitize_html` shape. The cell, `sanitize_stem_segments` and
composed shapes are **unmeasured** — that is what Task 1 exists for.

---

## Global Constraints

Every task's requirements implicitly include this section.

- **Every shell block in this plan is BASH.** Use the Bash tool, not PowerShell. This
  matters because the three most consequential steps here — Task 1 Step 2, Task 8 Step 4b
  and all of Task 9 — depend on the inline env-prefix form
  `DATABASE_URL="…" uv run python …`, which is a **parse error** in PowerShell, not an
  environment assignment. The PowerShell equivalent, if you must:
  `$env:DATABASE_URL = "postgres://libli:libli@localhost:5432/libli"` on its own line
  first — but note it then persists for the rest of that shell, which is exactly how a
  later command meant for the TEST database ends up hitting the real one.
- **Tooling:** `ruff`/`pytest`/`python` are NOT on PATH. Always `uv run ruff …`, `uv run pytest …`.
- **The plan's code blocks are ruff-clean after `ruff format`, not necessarily before.**
  Pasting a block and running `ruff format` may rewrap a long call or line; that is
  expected and the committed file need not match this document byte-for-byte. What
  must hold is that `ruff check` passes on the formatted tree. VERIFIED: every code
  block in this plan was extracted and run through `ruff format` then `ruff check` —
  `All checks passed!`.
- **Run `uv run ruff format .` BEFORE `uv run ruff check .`, and verify the check AFTER the format.** MEASURED in slice 1: `ruff format` can split a long expression and strand a `# noqa` on the wrong physical line, so a check that passed pre-format fails post-format while the noqa still looks present. Prefer f-strings over percent formatting.
- **Never run two pytest invocations at once** — concurrent runs collide on the Postgres test database.
- **Never background a long test run.** Two slice-1 subagents backgrounded a suite and then stalled waiting on their own job; the controller had to take over both times. Run it in the foreground and wait.
- **Do NOT use `--reuse-db` for a broad suite run.** Migration-created data is absent from a reused DB and you get ~21 false failures that look exactly like real regressions. Use `--reuse-db` only for narrow reruns of a single file (1.4 s vs 15 s).
- **Tasks are STRICTLY SEQUENTIAL in this worktree. Never dispatch two at once**,
  regardless of what any task's Interfaces block says about module-level independence.
  Task 6, for instance, correctly advertises that `dbscan.py` imports nothing from
  `source.py` — that is a statement about imports, not a licence to run it alongside
  Task 5. Two agents in one worktree collide on the `test_libli_blcp` database, on
  `uv run ruff format .` rewriting each other's files mid-edit, and on each other's
  commits; this repo has already paid for that lesson once.
- **BRANCH GUARD — run these two commands and paste their output into your report BEFORE any commit, and abort if either differs:**
  ```bash
  git rev-parse --show-toplevel   # must end in /builder-large-course-perf
  git branch --show-current       # must print text-colour-backfill
  ```
  A slice-1 subagent committed to `master` in the main checkout at `C:\Users\krzys\Documents\Python\own\libli`. This guard is why that cannot recur.
- **Two databases, and mixing them up is the expensive mistake.** This worktree's `.env` points `DATABASE_URL` at `libli_blcp`, so the *test* DB is `test_libli_blcp` and is isolated. The **real `mat-pp` course lives in the `libli` database**. Any probe or run against real data needs an explicit `DATABASE_URL="postgres://libli:libli@localhost:5432/libli"` prefix. Tests never touch it.
- **Falsify every test.** After a test passes, delete or invert the thing it guards, re-run, confirm RED, restore. A passing test proves nothing on its own. Paste the RED output into your report.
- **No hardcoded test passwords** — use `tests.factories.TEST_PASSWORD`.
- **Prose in source is load-bearing:** `tests/test_element_state_write_routes.py` regexes raw source *including comments and docstrings*. Do not write the words `element_state` in a comment in `courses/views.py` (this plan does not touch that file, but the constraint is repo-wide).
- **The command never reads or writes `ContentNode.title`.** Matching is content-based by design (D6). A test asserts every title is unchanged after a run.
- **Dry-run is the default.** `--apply` is opt-in, writes in one transaction, and reads every rewritten field back.
- **Colour slots:** exactly `tc-red`, `tc-blue`, `tc-green`, `tc-orange`. No others.
- **Excluded parts:** `001_zbiory_liczbowe` and `002_elementy_logiki` — on **both** sides (source dirname *and* DB node pk), paired by a single `--exclude <dirname>=<pk>` flag so the correspondence is stated by the operator, never inferred.

---

## File Structure

| File | Responsibility |
|---|---|
| `courses/colour.py` | *modify* — add `slot_for_style(style)`, the helper slice 1 deliberately left undefined; delete the NOTE comment that reserved it |
| `courses/sanitize.py` | *modify* — give `sanitize_html`/`sanitize_cell` a keyword-only `allowed_classes` and `sanitize_cell` a keyword-only `tags`, both defaulted to today's constants, so the legacy replay reuses the real code path instead of copying the maths-stashing logic. `tags` exists for Task 4's test oracle alone |
| `courses/switchgrid.py` | *modify* — `sanitize_stem_segments` takes a keyword-only `sanitiser`, defaulted to `sanitize_cell`, for the same reason |
| `courses/recolour/__init__.py` | **new** — empty package marker |
| `courses/recolour/colouriser.py` | **new** — the two bs4 products of one source fragment: `strip_spans()` (the key's input) and `colourise()` (the value's input, per-carrier rules) |
| `courses/recolour/regions.py` | **new** — the D8/D10 protected-region intersection test, applied to source values |
| `courses/recolour/replay.py` | **new** — replay the import write path for a field shape, twice: `legacy_replay()` (the key) and `current_replay()` (the value) |
| `courses/recolour/source.py` | **new** — walk `out/**.json` → occurrences → the `key → value` map, with conflict detection, region refusals and per-part counters |
| `courses/recolour/dbscan.py` | **new** — the DB registry, the course-scoped/exclusion-filtered candidate queryset, the match pass and the rewrite-with-read-back |
| `courses/management/commands/recolour_imported_content.py` | **new** — argument parsing/validation, the acceptance gate, the report |
| `tests/test_recolour_colouriser.py` | **new** |
| `tests/test_recolour_regions.py` | **new** |
| `tests/test_recolour_replay.py` | **new** — the key-construction tests, asserted against what the **real loader** stores |
| `tests/test_recolour_source.py` | **new** |
| `tests/test_recolour_dbscan.py` | **new** |
| `tests/test_recolour_command.py` | **new** |
| `.superpowers/sdd/progress.md` | *replace* — slice 2's execution ledger. **Gitignored and untracked** (`.gitignore:13`), so it is never `git add`ed, never `git mv`d, and never appears in `git status --porcelain` |
| `tests/test_richtext_drift.py` | *modify* — register `recolour/replay.py` in `EXPECTED`; the guard ASTs every `courses/**/*.py` and `replay.py` adds a `sanitize_html` call site |

---

### Task 0: Branch, ledger, and a clean start

**Files:**
- Rename: `.superpowers/sdd/progress.md` → `.superpowers/sdd/progress-slice-1-DONE.md`
- Create: `.superpowers/sdd/progress.md`

**`.superpowers/` is gitignored (`.gitignore:13`) and nothing under it is tracked.**
MEASURED: `git check-ignore -v .superpowers/sdd/progress.md` matches, and `git
ls-files .superpowers/` is empty. So every ledger step in this plan uses a plain
`mv`, never `git mv`; never `git add`s the ledger; and never expects it in `git
status`. A task whose only artefact is a ledger update therefore makes **no commit
at all** — that is correct, not a missing step.

**Interfaces:**
- Consumes: nothing.
- Produces: the `text-colour-backfill` branch every later task commits to, and an empty
  ledger. Without the rename, slice 1's "Task N complete" lines read as this plan's and
  a resumed session will believe work is done that is not.

- [ ] **Step 1: Verify the branch and the base**

```bash
git rev-parse --show-toplevel
git branch --show-current
git log --oneline -1
```

Expected: toplevel ends in `/builder-large-course-perf`; branch is `text-colour-backfill`;
HEAD is `origin/master`'s tip (the PR #198 merge commit `10a634a3` or later).

If the branch does not exist:

```bash
git fetch origin
git checkout -b text-colour-backfill origin/text-colour-backfill
```

**Branch from the remote feature branch, NOT from `origin/master`.** This plan
document is committed only on `text-colour-backfill`; branching from `origin/master`
would remove the plan you are executing from the working tree. If the file disappears
after a checkout, that is what happened — recover with
`git checkout origin/text-colour-backfill -- docs/superpowers/plans/`.

If the remote branch does not exist either (nothing has been pushed yet), the branch
is local-only and must already be present; do not re-create it.

- [ ] **Step 2: Confirm slice 1 is present**

```bash
uv run python -c "from courses.sanitize import LEGACY_ALLOWED_CLASSES, CELL_ALLOWED_CLASSES; print(sorted(LEGACY_ALLOWED_CLASSES), sorted(CELL_ALLOWED_CLASSES))"
```

Expected: the first list is the seven block/alignment tags (`blockquote div h2 h3 h4 li p`);
the second is the six cell tags that may carry colour (`b em i span strong u`). If the
import fails, you are not on a branch containing slice 1 — stop.

- [ ] **Step 3: Archive slice 1's ledger and open slice 2's**

```bash
mv .superpowers/sdd/progress.md .superpowers/sdd/progress-slice-1-DONE.md
```

Plain `mv`, not `git mv` — the file is untracked, and `git mv` aborts with
`fatal: not under version control`.

Create `.superpowers/sdd/progress.md`:

```markdown
# SDD progress — text colour slice 2 (backfill)

Plan: docs/superpowers/plans/2026-07-31-text-colour-slice-2.md
Spec: docs/superpowers/specs/2026-07-30-text-colour-design.md
Branch: text-colour-backfill (off origin/master, PR #198 merged)
Slice 1's ledger archived as progress-slice-1-DONE.md — its "Task N complete"
lines are NOT this plan's.

## Environment
- .env sets DATABASE_URL -> libli_blcp, so the TEST db is test_libli_blcp.
  The real mat-pp course lives in the `libli` database: any probe against real
  data needs an explicit DATABASE_URL=postgres://libli:libli@localhost:5432/libli
  prefix.
- uv run for everything. ruff format BEFORE ruff check.
- Never run two pytest invocations at once; never background a long suite.
- --reuse-db only for narrow single-file reruns.

## Tasks
Task 0: complete
```

- [ ] **Step 4: Confirm the tree is clean and move on**

The plan document is already committed and the ledger is untracked, so **this task
makes no commit**. Verify that is the actual state rather than assuming it:

```bash
git status --porcelain          # expected: empty
ls .superpowers/sdd/progress.md .superpowers/sdd/progress-slice-1-DONE.md
```

A containment check, not an equality one: `.superpowers/sdd/` also holds ~40 slice-1
briefs, reports and review diffs plus an `archive-builder-perf/` directory. Both named
files must exist; everything else there is history.

An empty `git status` here is the pass condition. If the plan document shows as
modified, something rewrote it — investigate before starting Task 1.

---

### Task 1: Acceptance-gate spike — measure the DB before writing anything

**This task writes no production code.** Its deliverable is a number. Every figure in the
spec is source-side; slice 2 rests entirely on byte-identity against stored values, and
M3 has measured only one of the four field shapes. If the match rate is far below the
gate, key construction is wrong and the rest of this plan must not be written on top of it.

**Files:**
- Create (throwaway, deleted in Step 5): `<scratchpad>/gate_spike.py`
- Modify: `.superpowers/sdd/progress.md`

**Interfaces:**
- Consumes: `courses.sanitize`'s `LEGACY_ALLOWED_CLASSES` / `LEGACY_CELL_ALLOWED_CLASSES`
  (slice-1 scaffolding, no other consumer yet).
- Produces: a measured per-part match rate for **all four** field shapes, recorded in the
  ledger. Tasks 2-7 are written against the shape decisions this confirms.

- [ ] **Step 1: Write the probe**

Write to your scratchpad directory (NOT the repo tree) as `gate_spike.py`. This probe
deliberately reimplements key construction crudely — it exists to falsify the approach
cheaply, and it is deleted in Step 5.

```python
"""Throwaway: does a legacy-replayed key match what mat-pp actually stores?

Deleted at the end of Task 1. Deliberately NOT in the repo tree.
"""

import json
import os
import re
from collections import defaultdict
from pathlib import Path

import sys

import django

# `uv run python <abs path>` sets sys.path[0] to the SCRIPT's directory, and this
# project is not installed as a package, so the repo root is otherwise absent and
# django.setup() dies with `ModuleNotFoundError: No module named 'config'`. Run
# this from the repo root so os.getcwd() is the repo root.
sys.path.insert(0, os.getcwd())
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
django.setup()

import nh3  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

from courses.colour import parse_style_colour  # noqa: E402
from courses.colour import SLOTS  # noqa: E402
from courses.models import ChoiceQuestionElement  # noqa: E402
from courses.models import Course  # noqa: E402
from courses.models import FillBlankQuestionElement  # noqa: E402
from courses.models import FillGateElement  # noqa: E402
from courses.models import FillTableElement  # noqa: E402
from courses.models import GuessNumberElement  # noqa: E402
from courses.models import ShortNumericQuestionElement  # noqa: E402
from courses.models import ShortTextQuestionElement  # noqa: E402
from courses.models import SpoilerElement  # noqa: E402
from courses.models import SwitchGateElement  # noqa: E402
from courses.models import TableElement  # noqa: E402
from courses.models import TextElement  # noqa: E402
from courses.sanitize import ALLOWED_ATTRIBUTES  # noqa: E402
from courses.sanitize import ALLOWED_TAGS  # noqa: E402
from courses.sanitize import ALLOWED_URL_SCHEMES  # noqa: E402
from courses.sanitize import CELL_TAGS  # noqa: E402
from courses.sanitize import LEGACY_ALLOWED_CLASSES  # noqa: E402
from courses.sanitize import LEGACY_CELL_ALLOWED_CLASSES  # noqa: E402
from courses.sanitize import _canon_math  # noqa: E402
from courses.sanitize import _MATH_SPAN  # noqa: E402
from courses.switchgrid import _TOKEN_RE  # noqa: E402
from courses.switchgrid import _token  # noqa: E402

OUT = Path("scripts/lal_import/out")
EXCLUDED_DIRS = ("001_zbiory_liczbowe", "002_elementy_logiki")


def legacy_html(v):
    return nh3.clean(
        v or "",
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        allowed_classes=LEGACY_ALLOWED_CLASSES,
        link_rel=None,
        url_schemes=ALLOWED_URL_SCHEMES,
    )


def legacy_cell(v):
    """A copy of sanitize_cell with the LEGACY class allowlist. The copy is fine
    HERE because the probe is thrown away; Task 4 parameterises the real one.

    Note `tags=CELL_TAGS` (the LIVE set, which contains `span`) and not a legacy tag
    set: the probe strips spans BEFORE calling this, so the tag set is inert here --
    exactly as `key_for`'s assertion documents for production. Task 4's test ORACLE
    is the one place that does need legacy tags, because it feeds RAW source through.
    """
    import secrets

    value = v or ""
    nonce = secrets.token_hex(8)
    spans = []

    def _stash(m):
        spans.append(m.group(0))
        return f"litmathspan{nonce}x{len(spans) - 1}xend"

    protected = _MATH_SPAN.sub(_stash, value)
    cleaned = nh3.clean(
        protected,
        tags=CELL_TAGS,
        attributes={},
        allowed_classes=LEGACY_CELL_ALLOWED_CLASSES,
        url_schemes=set(),
        link_rel=None,
        strip_comments=True,
    )
    ph = re.compile(f"litmathspan{nonce}x(\\d+)xend")
    return ph.sub(lambda m: _canon_math(spans[int(m.group(1))]), cleaned)


def legacy_stem(v):
    parts = _TOKEN_RE.split(v or "")
    return "".join(
        _token(int(p)) if i % 2 else legacy_cell(p) for i, p in enumerate(parts)
    )


REPLAY = {
    "html": legacy_html,
    "cell": legacy_cell,
    "stem": legacy_stem,
    "composed": lambda v: legacy_html(legacy_stem(v)),
}


def strip_spans(v):
    soup = BeautifulSoup(v or "", "html.parser")
    for sp in soup.find_all("span"):
        sp.unwrap()
    return soup.decode_contents()


def has_palette(v):
    soup = BeautifulSoup(v or "", "html.parser")
    return any(
        SLOTS.get(parse_style_colour(t.get("style"))) for t in soup.find_all(style=True)
    )


# (parser type, json key, shape) -> the DB model+field it lands in.
occ = []  # (part, shape, raw)


def emit(part, shape, raw):
    if isinstance(raw, str) and has_palette(raw):
        occ.append((part, shape, raw))


def walk(el, part):
    if not isinstance(el, dict):
        return
    t = el.get("type")
    if t in ("text", "spoiler"):
        emit(part, "html", el.get("body"))
    if t in ("choice", "numeric", "shorttext"):
        emit(part, "html", el.get("stem"))
    if t in ("fill_gate", "switch_gate", "guess_number"):
        emit(part, "stem", el.get("stem"))
    if t == "guess_number":
        emit(part, "html", el.get("success_message"))
    if t == "fillblank":
        emit(part, "composed", el.get("stem"))
    if t in ("table", "fill_table"):
        data = el.get("data")
        if isinstance(data, dict):
            for row in data.get("cells") or []:
                for cell in row if isinstance(row, list) else []:
                    if isinstance(cell, dict):
                        emit(part, "cell", cell.get("html"))
    for ch in el.get("elements") or []:
        walk(ch, part)
    for tab in el.get("tabs") or []:
        if isinstance(tab, dict):
            for ch in tab.get("elements") or []:
                walk(ch, part)


for jf in sorted(OUT.glob("*/*.json")):
    # flags.json is a JSON LIST, not a dict -- skipping it is not optional.
    if jf.name in ("manifest.json", "flags.json"):
        continue
    if jf.parent.name in EXCLUDED_DIRS:
        continue
    data = json.loads(jf.read_text("utf-8"))
    if not isinstance(data, dict):
        continue
    for el in data.get("elements") or []:
        walk(el, jf.parent.name)

course = Course.objects.get(slug="mat-pp")
EXCLUDED_PKS = {109, 153}


def subtree(pks):
    ids, frontier = set(pks), list(pks)
    from courses.models import ContentNode

    while frontier:
        kids = list(
            ContentNode.objects.filter(parent_id__in=frontier).values_list(
                "pk", flat=True
            )
        )
        ids |= set(kids)
        frontier = kids
    return ids


excluded_nodes = subtree(EXCLUDED_PKS)

HTML_MODELS = [
    (TextElement, "body"),
    (SpoilerElement, "body"),
    (GuessNumberElement, "success_message"),
    (ChoiceQuestionElement, "stem"),
    (ShortNumericQuestionElement, "stem"),
    (ShortTextQuestionElement, "stem"),
    (FillGateElement, "stem"),
    (SwitchGateElement, "stem"),
    (GuessNumberElement, "stem"),
    (FillBlankQuestionElement, "stem"),
]
stored = set()
for model, field in HTML_MODELS:
    qs = (
        model.objects.filter(elements__unit__course=course)
        .exclude(elements__unit_id__in=excluded_nodes)
        .values_list(field, flat=True)
    )
    stored |= {v for v in qs if v}
for model in (TableElement, FillTableElement):
    qs = (
        model.objects.filter(elements__unit__course=course)
        .exclude(elements__unit_id__in=excluded_nodes)
        .values_list("data", flat=True)
    )
    for data in qs:
        if not isinstance(data, dict):
            continue
        for row in data.get("cells") or []:
            for cell in row if isinstance(row, list) else []:
                if isinstance(cell, dict) and cell.get("html"):
                    stored.add(cell["html"])

print(f"stored candidate strings: {len(stored)}")
by_part = defaultdict(lambda: [0, 0])
by_shape = defaultdict(lambda: [0, 0])
misses = []
for part, shape, raw in occ:
    key = REPLAY[shape](strip_spans(raw))
    hit = key in stored
    by_part[part][0] += 1
    by_shape[shape][0] += 1
    if hit:
        by_part[part][1] += 1
        by_shape[shape][1] += 1
    else:
        misses.append((part, shape, raw, key))

tot = sum(v[0] for v in by_part.values())
mat = sum(v[1] for v in by_part.values())
print(f"\nOCCURRENCES producing a key: {tot}   MATCHED: {mat}   "
      f"RATE: {100 * mat / tot:.1f}%   (gate: >= 70%)")
print("\nby shape:")
for shape, (n, m) in sorted(by_shape.items()):
    print(f"  {shape:9s} {m:4d}/{n:4d}")
print("\nby part (a part with keys but ZERO matches fails the gate):")
for part, (n, m) in sorted(by_part.items()):
    flag = "  <== ZERO" if n and not m else ""
    print(f"  {part:38s} {m:4d}/{n:4d}{flag}")
print(f"\nfirst misses ({len(misses)}):")
for part, shape, raw, key in misses[:8]:
    print(f"--- {part} [{shape}]")
    print(f"    RAW: {raw[:150]!r}")
    print(f"    KEY: {key[:150]!r}")
```

- [ ] **Step 2: Run it against the REAL database**

```bash
PYTHONUTF8=1 DATABASE_URL="postgres://libli:libli@localhost:5432/libli" \
  uv run python "<scratchpad>/gate_spike.py"
```

`PYTHONUTF8=1` for the same reason Task 8 and Task 9 carry it: without it
`sys.stdout.encoding` is `cp1250` here, and this probe's FAILURE path prints `RAW`/`KEY`
reprs of Polish source — precisely the diagnostic this task exists to produce.

The `DATABASE_URL` prefix is mandatory. Without it you query `libli_blcp`, which does
not hold `mat-pp`, and every count comes back zero — a result that looks exactly like
broken key construction.

- [ ] **Step 3: Read the result against the gate**

The gate is: **≥ 70% of key-producing occurrences match, and no eligible part that
produces at least one key matches zero.**

- **Expected, from M3 and from the round-1/2/3 plan reviews, which each reproduced it:**
  **265 occurrences producing a key, 265 matched, 100.0%** — `html` 181, `cell` 84.
  If the overall figure is not at or near 100%, something in the environment differs
  from the plan author's run — stop and diagnose before anything else, rather than
  noting that 70% was cleared.
- **`cell`, `stem`, `composed` are the unmeasured shapes.** A shape at 0% means its
  replay is wrong (wrong sanitiser, or the composed path applied as a single sanitiser
  rather than `sanitize_html(sanitize_stem_segments(x))`). A shape near 100% confirms it.
- The `composed` shape may legitimately have **zero occurrences** — the spec measured
  zero `fillblank` colour in the corpus. Zero occurrences is not a failure; zero matches
  out of a non-zero count is.
- **`stem` may be zero-occurrence too after exclusion:** the corpus's only coloured
  `fill_gate` stems are the 2 in the excluded `001_` part, and the 2 `switch_grid` line
  stems are out of backfill scope. Only the 2 `choice` stems (the `html` shape) remain.
  Record what you actually see.

**If the overall rate is below 70%, or an eligible part with keys matches zero: STOP.**
Do not start Task 2. Diagnose from the printed misses — compare a `RAW`/`KEY` pair against
the value actually stored for that unit — and report to the controller with the diagnosis.
The spec's rejected alternative (re-running the loader for parts with no post-import edits)
returns to the table at that point, and that is a decision for the user, not for you.

- [ ] **Step 4: Record the measurement in the ledger**

Append to `.superpowers/sdd/progress.md` under `## Tasks`:

```markdown
Task 1: complete (measurement only, no production code)
  ACCEPTANCE GATE (dry, against the real libli/mat-pp DB):
    occurrences producing a key: <N>   matched: <M>   rate: <R>%   (gate >= 70%)
    by shape:  html <m>/<n>   cell <m>/<n>   stem <m>/<n>   composed <m>/<n>
    by part:   <paste the full per-part table>
    zero-matching eligible parts: <none | list>
  VERDICT: <PASS | FAIL>
  Notes: <anything surprising — a shape with zero occurrences, an unexpected miss>
```

- [ ] **Step 5: Delete the probe and prove it never touched the repo**

```bash
rm "<scratchpad>/gate_spike.py"
git status --porcelain   # expected: EMPTY
```

The probe must not reach the repo tree, and an empty `git status` is what proves it.
The ledger is untracked, so it does not appear here and **there is nothing to
commit** — this task ends without a commit, by design. Do not try to `git add` the
ledger; the path is ignored and the command errors.

---

### Task 2: `slot_for_style()` and the colouriser

**Files:**
- Modify: `courses/colour.py` (add `slot_for_style`; delete the trailing NOTE comment at `:98-100`)
- Create: `courses/recolour/__init__.py` (empty)
- Create: `courses/recolour/colouriser.py`
- Test: `tests/test_recolour_colouriser.py`
- Append: `.superpowers/sdd/progress.md` (untracked; no commit)

**Interfaces:**
- Consumes: `courses.colour.parse_style_colour`, `SLOTS`, `TC_CLASS_TAGS`.
- Produces:
  - `courses.colour.slot_for_style(style) -> str | None` — `"red"`/`"blue"`/`"green"`/`"orange"` or `None`.
  - `courses.recolour.colouriser.strip_spans(html) -> str`
  - `courses.recolour.colouriser.colourise(html) -> tuple[str, int]` — `(coloured_html, classes_emitted)`
  - `courses.recolour.colouriser.has_palette_colour(html) -> bool`
  - `courses.recolour.colouriser.roundtrip_is_lossless(html) -> bool`

- [ ] **Step 1: Write the failing test**

Create `tests/test_recolour_colouriser.py`:

```python
"""The colouriser is NOT span-only, and that is the whole point of these tests.

142 of the 588 palette-coloured elements in the corpus sit on <strong>/<p>/<li>/
<u>/<figcaption>/<i>. A span-only implementation delivers nothing for ~21% of
occurrences AND scores ~100% on the acceptance gate, because its output is
byte-identical to the key. Every carrier case below asserts value != key.
"""

from courses.colour import slot_for_style
from courses.recolour.colouriser import colourise
from courses.recolour.colouriser import has_palette_colour
from courses.recolour.colouriser import roundtrip_is_lossless
from courses.recolour.colouriser import strip_spans


def test_slot_for_style_maps_the_four_slots():
    assert slot_for_style("color: red") == "red"
    assert slot_for_style("color:#1F61AD") == "blue"
    assert slot_for_style("color: rgb(63, 107, 36)") == "green"
    assert slot_for_style("color: orange") == "orange"


def test_slot_for_style_rejects_non_palette_and_background():
    # An unanchored `color:` search matches background-color: -- the corpus has both.
    assert slot_for_style("background-color: red") is None
    assert slot_for_style("color: purple") is None
    assert slot_for_style("") is None
    assert slot_for_style(None) is None


def test_strip_spans_unwraps_every_span_not_only_coloured_ones():
    # The pre-slice-1 sanitiser removed ALL spans (span was never in ALLOWED_TAGS).
    # 687 of the corpus's 1197 spans carry no colour at all -- 299 myequation,
    # 142 bare. A key that unwraps only coloured spans matches nothing for those.
    src = (
        '<p><span class="myequation">a</span>'
        '<span style="color: red;">b</span>'
        "<span>c</span></p>"
    )
    assert strip_spans(src) == "<p>abc</p>"


def test_strip_spans_keeps_non_span_markup_byte_for_byte():
    src = '<p>x <strong class="bold">y</strong> <a href="/z/">z</a></p>'
    assert strip_spans(src) == src


def test_span_carrier_gets_the_class_and_loses_the_style():
    out, n = colourise('<span style="color: red;">x</span>')
    assert out == '<span class="tc-red">x</span>'
    assert n == 1


def test_strong_carrier_keeps_the_element_and_gains_the_class():
    # strong is in TC_CLASS_TAGS, so the class rides the element itself.
    # 117 of the 142 non-span carriers are <strong>.
    out, n = colourise('<strong style="color: blue;">x</strong>')
    assert out == '<strong class="tc-blue">x</strong>'
    assert n == 1
    assert out != strip_spans('<strong style="color: blue;">x</strong>')


def test_block_carrier_moves_the_class_onto_a_wrapping_span():
    # p/li/figcaption cannot carry tc-* (the sanitiser would strip it), so the
    # colour moves onto a NEW span around the children.
    out, n = colourise('<p style="color: green;">x <b>y</b></p>')
    assert out == '<p><span class="tc-green">x <b>y</b></span></p>'
    assert n == 1


def test_figcaption_carrier_degrades_without_error():
    # figcaption is not in ALLOWED_TAGS at all: the sanitiser will unwrap the
    # figcaption later, and the colour survives on the inner span.
    out, n = colourise('<figcaption style="color: orange;">cap</figcaption>')
    assert out == '<figcaption><span class="tc-orange">cap</span></figcaption>'
    assert n == 1


def test_unmapped_colour_is_dropped_not_restored():
    # black/gray/magenta/purple/yellow/hex = 109 elements (16%), explicitly
    # accepted as lost: "the colours used in matematyka do not have to reflect
    # the originals, some of them may be skipped".
    out, n = colourise('<span style="color: purple;">x</span>')
    assert out == "x"
    assert n == 0


def test_background_colour_is_not_a_text_colour():
    out, n = colourise('<span style="background-color: red;">x</span>')
    assert out == "x"
    assert n == 0


def test_colourless_spans_are_unwrapped_in_the_value_too():
    # Once span is allowed, nh3 no longer removes them, so writing them back
    # would ship <span class=""> litter into content that is currently clean.
    out, n = colourise(
        '<p><span class="myequation">a</span><span style="color: red;">b</span></p>'
    )
    assert out == '<p>a<span class="tc-red">b</span></p>'
    assert n == 1


def test_two_carriers_in_one_fragment_both_count():
    out, n = colourise(
        'jeśli ( <span style="color: red;">założenie</span> ) to '
        '( <span style="color: blue;">teza</span> )'
    )
    assert out == (
        'jeśli ( <span class="tc-red">założenie</span> ) to '
        '( <span class="tc-blue">teza</span> )'
    )
    assert n == 2


def test_existing_class_is_kept_beside_the_colour_class():
    out, _n = colourise('<strong class="bold" style="color: red;">x</strong>')
    assert out == '<strong class="bold tc-red">x</strong>'


def test_has_palette_colour_distinguishes_the_two_cases():
    assert has_palette_colour('<span style="color: red;">x</span>')
    assert not has_palette_colour('<span style="color: purple;">x</span>')
    assert not has_palette_colour("<p>plain</p>")


def test_roundtrip_is_lossless_on_ordinary_markup():
    # MEASURED: 0 of 319 colour-bearing corpus values differ under a bs4
    # round-trip. This guard turns a future corpus change from silent
    # corruption into a reported skip.
    assert roundtrip_is_lossless('<p>a &lt; b <span style="color: red;">c</span></p>')


def test_entities_survive_the_round_trip():
    # Recorded repo trap: str(NavigableString) DECODES entities while str(Tag)
    # RE-ESCAPES them. decode_contents() is the serialisation that round-trips.
    src = "<p>a &amp; b &lt; c</p>"
    assert strip_spans(src) == src
```

- [ ] **Step 2: Run it to verify it fails**

```bash
uv run pytest tests/test_recolour_colouriser.py -x -q
```

Expected: a collection error. The FIRST import in the file is
`from courses.colour import slot_for_style`, so the error is
`ImportError: cannot import name 'slot_for_style' from 'courses.colour'` — **not**
`ModuleNotFoundError: No module named 'courses.recolour'`, which is what you would see
if the colour import already resolved.

- [ ] **Step 3: Add `slot_for_style` to `courses/colour.py`**

Delete the three-line NOTE at the end of the file (lines 98-100, beginning
`# NOTE: slot_for_style()`) and replace it with:

```python
def slot_for_style(style):
    """The palette slot named by a style attribute's `color` declaration, or None.

    None means "no slot", never "delete". The caller decides what an unmapped
    colour means, and the two callers decide differently: the backfill drops it
    (it cannot be stored anyway), while the render path leaves it exactly as-is
    so existing \\color{purple} content keeps rendering as it does today.
    """
    return SLOTS.get(parse_style_colour(style))
```

- [ ] **Step 4: Create the package and the colouriser**

`courses/recolour/__init__.py` — empty file.

Create `courses/recolour/colouriser.py`:

```python
"""Two products of one imported HTML fragment: its key form and its coloured form.

strip_spans(html)  -- the fragment with EVERY <span> unwrapped. The pre-slice-1
                      sanitiser did exactly this (span was never in ALLOWED_TAGS),
                      so it is the input the KEY replay needs. Unwrapping only
                      COLOURED spans would replay to `<span class="">...` while the
                      DB holds the fully-unwrapped value -- a silent zero-match.

colourise(html)    -- the fragment with every PALETTE colour turned into a tc-*
                      class on a LEGAL carrier, every other inline colour dropped,
                      and every span that did not earn a tc-* class unwrapped.

The carrier rule is the part a naive implementation gets wrong. 142 of the 588
palette-coloured elements sit on a tag other than `span`; a span-only colouriser
leaves <strong style="color:red"> untouched, the sanitiser strips `style`, and the
written value comes out BYTE-IDENTICAL TO THE KEY -- a silent no-op that the
acceptance gate would score as success were it not for its `value != key` clause.

Serialisation goes through decode_contents(), never str(Tag): this repo has a
recorded trap where str(Tag) re-escapes entities while str(NavigableString) decodes
them. One entity difference in one span silently zeroes that key with no error.
"""

from bs4 import BeautifulSoup

from courses.colour import TC_CLASS_TAGS
from courses.colour import slot_for_style


def soup(html):
    """Parse one fragment. Public because regions.py parses the same way, and a
    cross-module reach for an underscore-private name is the kind of coupling that
    goes unnoticed until someone renames it."""
    return BeautifulSoup(html or "", "html.parser")


def strip_spans(html):
    """The fragment with every <span> unwrapped, children kept."""
    parsed = soup(html)
    for span in parsed.find_all("span"):
        span.unwrap()
    return parsed.decode_contents()


def has_palette_colour(html):
    """True when at least one element carries a colour this palette can restore."""
    return any(
        slot_for_style(tag.get("style")) for tag in soup(html).find_all(style=True)
    )


def roundtrip_is_lossless(html):
    """True when parsing and re-serialising returns the source byte-for-byte.

    MEASURED over the whole corpus: 0 of 319 colour-bearing values differ. The
    guard stays because a future corpus change that broke it would otherwise
    corrupt content silently instead of being skipped and reported.
    """
    return soup(html).decode_contents() == (html or "")


def _add_colour_class(tag, slot):
    classes = [c for c in (tag.get("class") or []) if not c.startswith("tc-")]
    classes.append(f"tc-{slot}")
    tag["class"] = classes


def colourise(html):
    """(coloured_html, tc_classes_emitted). See the module docstring."""
    parsed = soup(html)
    emitted = 0
    # find_all materialises the list before any mutation, so wrapping a block
    # carrier's children cannot disturb the iteration -- a nested coloured span
    # is still visited afterwards, at its new depth.
    for tag in parsed.find_all(style=True):
        slot = slot_for_style(tag.get("style"))
        # Both sanitisers strip `style` wholesale (it is in neither
        # ALLOWED_ATTRIBUTES nor sanitize_cell's empty attribute map), so no
        # other declaration on this attribute could have survived anyway.
        del tag["style"]
        if slot is None:
            # Unmapped colour, or a style carrying no colour at all. Dropped, not
            # restored: D1's palette is four slots and the rest are accepted losses.
            continue
        if tag.name.lower() in TC_CLASS_TAGS:
            _add_colour_class(tag, slot)
        else:
            # p / li / figcaption ...: the sanitiser strips tc-* from a tag outside
            # TC_CLASS_TAGS (and strips figcaption entirely), so the colour moves
            # onto a NEW span wrapping the children. Mirrors the editor's
            # "never leave tc-* on a tag outside TC_CLASS_TAGS" rule.
            wrapper = parsed.new_tag("span")
            wrapper["class"] = [f"tc-{slot}"]
            for child in list(tag.contents):
                wrapper.append(child.extract())
            tag.append(wrapper)
        emitted += 1
    for span in parsed.find_all("span"):
        if not any(c.startswith("tc-") for c in (span.get("class") or [])):
            span.unwrap()
    return parsed.decode_contents(), emitted
```

- [ ] **Step 5: Run the tests**

```bash
uv run pytest tests/test_recolour_colouriser.py -q
```

Expected: 16 passed.

- [ ] **Step 6: Falsify — prove the carrier rule is load-bearing**

Make the colouriser span-only by replacing the `if tag.name.lower() in TC_CLASS_TAGS:`
branch body and its `else` with a single `_add_colour_class(tag, slot)` guarded by
`if tag.name.lower() == "span":` (and no else). Re-run:

```bash
uv run pytest tests/test_recolour_colouriser.py -q
```

Expected: RED on **four** tests, all from the same cause — every one of them
exercises a non-span carrier:
`test_strong_carrier_keeps_the_element_and_gains_the_class`,
`test_block_carrier_moves_the_class_onto_a_wrapping_span`,
`test_figcaption_carrier_degrades_without_error` and
`test_existing_class_is_kept_beside_the_colour_class` (a `<strong>` carrier, so it
reddens mechanically under the same mutation). Four failures is the correct result
here, not an unrelated regression. Paste the failure lines into your
report. **Restore the file** and confirm 16 passed again.

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff format .
uv run ruff check .
git rev-parse --show-toplevel
git branch --show-current
git add courses/colour.py courses/recolour/__init__.py courses/recolour/colouriser.py tests/test_recolour_colouriser.py
git commit -m "feat(recolour): slot_for_style and the per-carrier colouriser"
```
- [ ] **Step L: Record the task in the ledger**

Append to `.superpowers/sdd/progress.md` under `## Tasks`:

```markdown
Task 2: complete (commit <sha>)
  - branch guard: <toplevel> / <branch>
  - <N> passed; falsification RED on <test names>, restored
  - anything surprising, and any decision you had to make that the plan did not cover
```

The ledger is untracked, so this is a file write with **no commit**. It is not
bookkeeping: it is the only record a resumed session has of which tasks are genuinely
done, which is the entire reason Task 0 archives slice 1's ledger rather than appending
to it. Git history shows that a commit happened; the ledger is where you say what was
verified and what surprised you.


---

### Task 3: The protected-region guard

**Files:**
- Create: `courses/recolour/regions.py`
- Test: `tests/test_recolour_regions.py`
- Append: `.superpowers/sdd/progress.md` (untracked; no commit)

**Interfaces:**
- Consumes: **Task 2** — `courses.colour.slot_for_style` and
  `courses.recolour.colouriser.soup`. Task 3 has a hard dependency on Task 2 and
  cannot be dispatched before it completes.
- Produces: `courses.recolour.regions.region_verdict(html, *, sentinel_tokens) -> str | None`
  — a short refusal reason, or `None` when colouring this fragment is safe.

**Why this exists.** The editor is forbidden from producing a colour span that intersects
a maths region or a blank marker (D8/D10). The backfill writes colour into exactly the
marker-bearing stems, so without the same test it would store precisely the corruption
D10 exists to prevent. Measured in-scope overlap today is **zero** — but by exclusion,
not by the guard, so a future 0 must not be mistaken for a clean result.

**The source-side vocabulary differs from the editor's.** Measured over all 835 corpus
files, `{{` occurs **zero** times, while the U+FFFF sentinel occurs 3496 times as a
character (~1748 tokens), because the loader feeds `sanitize_stem_segments`, which splits
on `<SENTINEL><digits><SENTINEL>`, not on author braces. So the source-side blank test is
built from `courses.fillblank.SENTINEL` — **U+FFFF**, never written as an escape, because
the visually identical U+FFFD would make every sentinel assertion silently vacuous.
Scanning for `{{…}}` here would be vacuous for a different reason: it never occurs.

**The blank-token rule is NOT the maths rule, and reusing the maths carve-out is a
measured defect this plan's own dry run caught.** A span *enclosing* a `\(…\)` region is
safe, because it wraps the delimiters and `sanitize_cell` stashes the region intact. A
span enclosing a blank token is **not**: `sanitize_stem_segments` splits the stem on the
token and sanitises each segment independently, so nh3 auto-closes the span in the leading
segment and the trailing segment silently loses its colour. For blank tokens, **only
disjoint is safe**.

- [ ] **Step 1: Write the failing test**

Create `tests/test_recolour_regions.py`:

```python
"""D8/D10 applied to the SOURCE side.

The four-case table from the spec, plus fail-closed on an unbalanced delimiter.
`\\(<span class="tc-red">x</span> + y\\)` is still delimiter-balanced, so
sanitize_cell stashes it WITH the span and _canon_math escapes it into the stored
LaTeX permanently. Both sanitisers are idempotent, so re-saving never heals it.
"""

from courses.fillblank import SENTINEL
from courses.recolour.regions import region_verdict

# Imported, never written as an escape: SENTINEL is U+FFFF, and the visually
# identical U+FFFD would make every sentinel test here silently vacuous.
S = SENTINEL


def test_no_region_no_refusal():
    assert region_verdict('<span style="color: red;">x</span>', sentinel_tokens=False) is None


def test_colour_wholly_inside_a_maths_region_is_refused():
    html = 'a \\(<span style="color: red;">x</span> + y\\) b'
    assert region_verdict(html, sentinel_tokens=False) is not None


def test_colour_straddling_a_maths_region_is_refused():
    html = 'a <span style="color: red;">b \\(x</span> + y\\) c'
    assert region_verdict(html, sentinel_tokens=False) is not None


def test_colour_strictly_enclosing_a_clean_region_is_allowed():
    # The span wraps the delimiters rather than splitting them, so the stashed
    # LaTeX is untouched.
    html = '<span style="color: red;">see \\(x+y\\) here</span>'
    assert region_verdict(html, sentinel_tokens=False) is None


def test_colour_enclosing_a_region_with_an_element_boundary_is_refused():
    # Such a region already round-trips lossily through sanitize_cell regardless
    # of colour, so colouring it is not a gesture the storage layer can support.
    html = '<span style="color: red;">see \\(x + <b>y</b>\\) here</span>'
    assert region_verdict(html, sentinel_tokens=False) is not None


def test_unbalanced_delimiter_fails_closed():
    html = '<span style="color: red;">x</span> and \\(y with no close'
    assert region_verdict(html, sentinel_tokens=False) is not None


def test_display_delimiters_are_regions_too():
    html = 'a \\[<span style="color: red;">x</span>\\] b'
    assert region_verdict(html, sentinel_tokens=False) is not None


def test_a_colour_span_ENCLOSING_a_blank_token_is_refused():
    # The asymmetry with maths, and the reason it exists: sanitize_stem_segments
    # SPLITS the stem on the token and sanitises each segment INDEPENDENTLY, so an
    # enclosing span is auto-closed by nh3 in the leading segment and the trailing
    # segment silently loses its colour. The maths carve-out must NOT be reused
    # here -- applying it made this exact case pass while the data was corrupt.
    html = f'<span style="color: red;">pick {S}0{S} now</span>'
    assert region_verdict(html, sentinel_tokens=True) is not None


def test_a_colour_span_STRADDLING_a_blank_token_is_refused():
    html = f'a <span style="color: red;">b {S}0{S}</span> c'
    assert region_verdict(html, sentinel_tokens=True) is not None


def test_a_colour_span_DISJOINT_from_a_blank_token_is_allowed():
    # Disjoint is the only safe relation, and it must stay allowed or every
    # coloured gate stem in the corpus would be refused for nothing.
    html = f'{S}0{S} <span style="color: red;">x</span>'
    assert region_verdict(html, sentinel_tokens=True) is None


def test_sentinel_token_is_ignored_for_non_stem_shapes():
    # An html/cell field never goes through sanitize_stem_segments, so a stray
    # sentinel character there is not a protected region.
    html = f'<span style="color: red;">pick {S}0{S} now</span>'
    assert region_verdict(html, sentinel_tokens=False) is None


def test_unmapped_colour_carriers_are_not_tested():
    # A purple span inside maths is dropped by the colouriser, exactly as the
    # PRE-slice-1 sanitiser dropped it, so the stored value is unchanged and
    # there is no new corruption to refuse.
    html = 'a \\(<span style="color: purple;">x</span> + y\\) b'
    assert region_verdict(html, sentinel_tokens=False) is None
```

- [ ] **Step 2: Run it to verify it fails**

```bash
uv run pytest tests/test_recolour_regions.py -x -q
```

Expected: `ModuleNotFoundError: No module named 'courses.recolour.regions'`.

- [ ] **Step 3: Implement**

Create `courses/recolour/regions.py`:

```python
"""Refuse to colour any source fragment whose colour would land in a protected region.

Detection is an explicit text-offset pass, not a lookup: the interval test needs
global offsets into the fragment's text, and it also needs to know where the ELEMENT
boundaries fall, because a region containing one already round-trips lossily through
sanitize_cell. Both come out of one walk over the parsed tree.
"""

import re

from bs4 import NavigableString

from courses.colour import slot_for_style
from courses.fillblank import SENTINEL

# Balanced \(...\) (inline) or \[...\] (display), non-greedy, no nesting. IMPORTED
# from the sanitiser, never re-declared: the guard and the sanitiser must agree about
# what a region IS, and a copied pattern agrees only by comment -- if the sanitiser's
# pattern ever moves, a duplicate here silently disagrees about region boundaries and
# the D8 refusal starts protecting the wrong span. This repo guards that class of
# drift with tests elsewhere (test_colour_map_drift, the #169 twin guard); importing
# removes the possibility instead of testing for it.
from courses.sanitize import _MATH_SPAN
# Anything delimiter-shaped that survived the region scan means an unclosed or
# unbalanced delimiter: fail closed rather than guess where the region ends.
_LOOSE_DELIM = re.compile(r"\\[()\[\]]")
# The source-side blank marker. NOT `{{...}}`: measured over all 835 corpus files,
# `{{` occurs ZERO times, because the loader feeds sanitize_stem_segments, which
# splits on this token, not on author braces. SENTINEL is imported rather than
# written as an escape -- it is U+FFFF, and the visually similar U+FFFD (the
# replacement character) would make every test here vacuous.
_SENTINEL_TOKEN = re.compile(SENTINEL + r"\d+" + SENTINEL)


def _walk(parsed):
    """(full text, [(start, end) per text node], [(start, end) per coloured tag]).

    A coloured tag's extent is the offset range of the text it contains. An empty
    element has no extent and cannot intersect anything, so it is skipped.
    """
    text_parts = []
    node_spans = []
    tag_spans = []
    cursor = 0

    def visit(node):
        nonlocal cursor
        if isinstance(node, NavigableString):
            s = str(node)
            text_parts.append(s)
            node_spans.append((cursor, cursor + len(s)))
            cursor += len(s)
            return
        if node.name is None:
            return
        start = cursor
        for child in node.children:
            visit(child)
        if slot_for_style(node.get("style")) and cursor > start:
            tag_spans.append((start, cursor))

    for child in parsed.children:
        visit(child)
    return "".join(text_parts), node_spans, tag_spans


def _in_one_text_node(span, node_spans):
    lo, hi = span
    return any(ns <= lo and hi <= ne for ns, ne in node_spans)


def region_verdict(html, *, sentinel_tokens):
    """A short refusal reason, or None when colouring this fragment is safe.

    `sentinel_tokens` is True only for the sanitize_stem_segments field shapes,
    whose segments are sanitised independently.
    """
    from courses.recolour.colouriser import soup

    parsed = soup(html)
    text, node_spans, tag_spans = _walk(parsed)
    if not tag_spans:
        return None

    regions = [(m.start(), m.end(), "maths") for m in _MATH_SPAN.finditer(text)]
    residue = _MATH_SPAN.sub("", text)
    if _LOOSE_DELIM.search(residue):
        return "unbalanced maths delimiter"
    if sentinel_tokens:
        regions += [(m.start(), m.end(), "blank") for m in _SENTINEL_TOKEN.finditer(text)]

    for ts, te in tag_spans:
        for rs, re_, kind in regions:
            if te <= rs or re_ <= ts:
                continue  # disjoint -- the only safe relation for a blank token
            if kind == "blank":
                # NO enclosure carve-out here, and that asymmetry is load-bearing.
                # The maths carve-out works because a span enclosing \(...\) wraps
                # the delimiters and sanitize_cell stashes the region intact. A
                # blank token is the opposite: sanitize_stem_segments SPLITS the
                # stem on the token and sanitises each segment INDEPENDENTLY, so an
                # enclosing span is auto-closed by nh3 in the leading segment and
                # the trailing segment silently loses its colour. MEASURED against
                # the real sanitiser while this plan was written.
                return "colour touches a blank-marker token"
            if ts <= rs and re_ <= te:
                # Strictly enclosing a maths region: allowed only when the region
                # carries no element boundary, i.e. it lies inside a single text
                # node. A region that does already round-trips lossily through
                # sanitize_cell regardless of colour.
                if _in_one_text_node((rs, re_), node_spans):
                    continue
                return "colour encloses a maths region containing an element boundary"
            return "colour intersects a maths region"
    return None
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/test_recolour_regions.py -q
```

Expected: 12 passed.

- [ ] **Step 5: Falsify — prove the element-boundary carve-out is real**

In `region_verdict`, replace the `if _in_one_text_node(...)` guard with an
unconditional `continue`. Re-run:

```bash
uv run pytest tests/test_recolour_regions.py -q
```

Expected: RED on `test_colour_enclosing_a_region_with_an_element_boundary_is_refused`.
Restore, confirm 12 passed.

Now falsify the blank/maths asymmetry — the defect this plan's own dry run caught.
Delete the `if kind == "blank": return …` branch, so blank tokens inherit the maths
enclosure carve-out. Re-run — expected RED on **two** tests:
`test_a_colour_span_ENCLOSING_a_blank_token_is_refused` and
`test_a_colour_span_STRADDLING_a_blank_token_is_refused`. The straddling case also
satisfies the enclosure condition once the branch is gone (the token sits inside a
single text node), so two failures is the correct result here — not an unrelated
regression. Restore.

Then falsify the fail-closed branch: delete the `if _LOOSE_DELIM.search(residue)` block
and re-run — expected RED on `test_unbalanced_delimiter_fails_closed`. Restore.

Paste all three RED outputs into your report.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff format .
uv run ruff check .
git rev-parse --show-toplevel
git branch --show-current
git add courses/recolour/regions.py tests/test_recolour_regions.py
git commit -m "feat(recolour): D8/D10 protected-region guard for source values"
```
- [ ] **Step L: Record the task in the ledger**

Append to `.superpowers/sdd/progress.md` under `## Tasks`:

```markdown
Task 3: complete (commit <sha>)
  - branch guard: <toplevel> / <branch>
  - <N> passed; falsification RED on <test names>, restored
  - anything surprising, and any decision you had to make that the plan did not cover
```

The ledger is untracked, so this is a file write with **no commit**. It is not
bookkeeping: it is the only record a resumed session has of which tasks are genuinely
done, which is the entire reason Task 0 archives slice 1's ledger rather than appending
to it. Git history shows that a commit happened; the ledger is where you say what was
verified and what surprised you.


---

### Task 4: Replay the import write path — the key and the value

**Files:**
- Modify: `courses/sanitize.py` (keyword-only `allowed_classes` on both sanitisers, **and**
  a keyword-only `tags` on `sanitize_cell` — test-oracle only)
- Modify: `courses/switchgrid.py` (keyword-only `sanitiser` on `sanitize_stem_segments`)
- Modify: `tests/test_richtext_drift.py` (register the new `sanitize_html` call site — Step 7b)
- Create: `courses/recolour/replay.py`
- Test: `tests/test_recolour_replay.py`
- Append: `.superpowers/sdd/progress.md` (untracked; no commit)

**Interfaces:**
- Consumes: `courses.recolour.colouriser.strip_spans`, `colourise`.
- Produces:
  - `courses.recolour.replay.SHAPES` — the four shape names: `"html"`, `"cell"`, `"stem"`, `"composed"`.
  - `courses.recolour.replay.legacy_replay(value, shape) -> str` — the KEY sanitiser composition.
  - `courses.recolour.replay.current_replay(value, shape) -> str` — the VALUE sanitiser composition.
  - `courses.recolour.replay.key_for(raw, shape) -> str`
  - `courses.recolour.replay.value_for(raw, shape) -> tuple[str, int]`

**Why the sanitisers gain a parameter rather than being copied.** The legacy replay needs
`sanitize_cell`'s maths-stashing logic verbatim — the nonce, the placeholder, `_canon_math`
— with one different argument. A copy would drift from the original the first time either
is touched. A keyword-only parameter with today's constant as its default changes no
caller and no behaviour.

**Why "the sanitiser that owns the field" is the wrong rule.** Some fields are sanitised
**twice** on the import path. `builders.py:214` creates `FillBlankQuestionElement` with
`stem=sanitize_stem_segments(...)`, and `QuestionElement.save()` then re-applies
`sanitize_html` (`models.py:1604-1605`). The stored value is
`sanitize_html(sanitize_stem_segments(x))`, materially different from `sanitize_html(x)`
— `sanitize_cell` strips block tags and `_canon_math` escapes the maths spans. A key built
with either sanitiser alone matches **nothing** for that field, and it fails silently.

- [ ] **Step 1: Write the failing test**

Create `tests/test_recolour_replay.py`:

```python
"""The key must equal what the LOADER STORED AT IMPORT TIME -- so these tests run
the real loader with the PRE-SLICE-1 allowlists patched in, rather than asserting
one sanitiser call against another.

The patching is the whole point, and leaving it out makes every assertion here fail
for the right reason in the wrong place. MEASURED on this branch: the loader running
TODAY stores `jeśli ( <span>założenie</span> ) to ( teza )` for the fixture below,
because slice 1 put `span` in ALLOWED_TAGS. The DB was written BEFORE slice 1, so it
holds `jeśli ( założenie ) to ( teza )` -- which is exactly what `key_for` produces.
The production key construction is right; an unpatched loader is simply the wrong
oracle for it.

This is also the test that would have caught the composed-path defect: a key built
with sanitize_html alone, or sanitize_stem_segments alone, matches nothing for
FillBlankQuestionElement.stem, and nothing anywhere says so.
"""

import pytest

from courses.fillblank import SENTINEL
from courses.lal_loader.builders import build_element
from courses.models import ChoiceQuestionElement
from courses.models import ContentNode
from courses.models import FillBlankQuestionElement
from courses.models import FillGateElement
from courses.models import TableElement
from courses.models import TextElement
from courses.recolour.replay import current_replay
from courses.recolour.replay import key_for
from courses.recolour.replay import legacy_replay
from courses.recolour.replay import value_for
from tests.factories import CourseFactory

pytestmark = pytest.mark.django_db

# Imported, never written as an escape: SENTINEL is U+FFFF, and the visually
# identical U+FFFD would make the two stem fixtures below silently vacuous.
S = SENTINEL


def _unit(course):
    part = ContentNode.objects.create(
        course=course, parent=None, order=0, kind="part", title="P"
    )
    ch = ContentNode.objects.create(
        course=course, parent=part, order=0, kind="chapter", title="C"
    )
    return ContentNode.objects.create(
        course=course, parent=ch, order=0, kind="unit", title="U", unit_type="lesson"
    )


def _patch_loader_to_legacy(monkeypatch):
    """Make the loader behave as it did AT IMPORT TIME (pre-slice-1 allowlists).

    Patched at the points of USE, not just at the definition, and both are needed:
    `courses/models.py` binds each sanitiser at module import (`from
    courses.sanitize import sanitize_cell` / `sanitize_html`, models.py:25-26), so
    patching `courses.sanitize` alone would never reach `QuestionElement.save()` or
    `TableElement._sanitized_data`. Conversely `courses/switchgrid.py` imports
    `sanitize_cell` INSIDE `sanitize_stem_segments`, so only the `courses.sanitize`
    patch reaches the gate-stem path.
    """
    import nh3

    from courses import models as courses_models
    from courses import sanitize as courses_sanitize
    from courses.sanitize import ALLOWED_ATTRIBUTES
    from courses.sanitize import ALLOWED_TAGS
    from courses.sanitize import ALLOWED_URL_SCHEMES
    from courses.sanitize import CELL_TAGS
    from courses.sanitize import LEGACY_ALLOWED_CLASSES
    from courses.sanitize import LEGACY_CELL_ALLOWED_CLASSES
    from courses.sanitize import sanitize_cell

    # The legacy CLASS allowlists are not sufficient on their own, and this is the
    # part that is easy to get wrong. MEASURED: patching only the classes leaves the
    # loader storing `<span>założenie</span>`, because slice 1 added `span` to BOTH
    # tag sets -- and all six comparisons below then fail against keys that are in
    # fact correct. The ORACLE feeds RAW source (spans intact) through the sanitiser,
    # so it needs the pre-slice-1 TAGS as well.
    #
    # The production key generator does NOT need this: `key_for` runs `strip_spans`
    # first, so no span ever reaches the sanitiser and the live tag sets are inert
    # there -- which is exactly what its `assert "<span" not in stripped` pins down.
    legacy_tags = ALLOWED_TAGS - {"span"}
    legacy_cell_tags = CELL_TAGS - {"span"}

    def legacy_html(value, *_a, **_kw):
        return nh3.clean(
            value or "",
            tags=legacy_tags,
            attributes=ALLOWED_ATTRIBUTES,
            allowed_classes=LEGACY_ALLOWED_CLASSES,
            link_rel=None,
            url_schemes=ALLOWED_URL_SCHEMES,
        )

    def legacy_cell(value, *_a, **_kw):
        # Reuses the real sanitize_cell for the maths-stashing logic, overriding
        # only the two allowlists via the keyword-only parameters added above.
        return sanitize_cell(
            value,
            tags=legacy_cell_tags,
            allowed_classes=LEGACY_CELL_ALLOWED_CLASSES,
        )

    monkeypatch.setattr(courses_sanitize, "sanitize_html", legacy_html)
    monkeypatch.setattr(courses_sanitize, "sanitize_cell", legacy_cell)
    monkeypatch.setattr(courses_models, "sanitize_html", legacy_html)
    monkeypatch.setattr(courses_models, "sanitize_cell", legacy_cell)


def _load(monkeypatch, el):
    _patch_loader_to_legacy(monkeypatch)
    course = CourseFactory()
    unit = _unit(course)
    build_element(course, unit, el, source_root="", source_dir="", allow_html=False)
    return unit


RED = 'jeśli ( <span style="color: red;">założenie</span> ) to ( teza )'


def test_the_patched_loader_really_is_the_pre_slice_1_loader(monkeypatch):
    # Guards the oracle itself. Without the patch the loader stores
    # `<span>założenie</span>` (span is in ALLOWED_TAGS after slice 1) and every
    # test below fails against a key that is in fact correct.
    _load(monkeypatch, {"type": "text", "body": RED})
    assert "<span" not in TextElement.objects.get().body


def test_html_shape_key_equals_what_the_loader_stored(monkeypatch):
    _load(monkeypatch, {"type": "text", "body": RED})
    stored = TextElement.objects.get().body
    assert key_for(RED, "html") == stored
    # And the pre-change loader really did drop the colour:
    assert "color" not in stored and "tc-" not in stored


def test_choice_stem_is_the_bare_sanitize_html_shape(monkeypatch):
    # builders.py:359 creates ChoiceQuestionElement with a bare stem=el["stem"];
    # QuestionElement.save() applies sanitize_html and nothing else.
    _load(
        monkeypatch,
        {
            "type": "choice",
            "stem": RED,
            "choices": [{"text": "a", "is_correct": True}],
        },
    )
    assert key_for(RED, "html") == ChoiceQuestionElement.objects.get().stem


def test_fill_gate_stem_is_the_stem_segments_shape(monkeypatch):
    # MEASURED: zero coloured fill_gate stems survive source-side exclusion (the
    # corpus's only two sit in the excluded 001_ part), so this synthesised
    # fixture is the ONLY oracle the stem shape ever gets. It is load-bearing.
    src = f'<span style="color: red;">a</span> {S}0{S} b'
    _load(monkeypatch, {"type": "fill_gate", "stem": src, "answers": [["x"]]})
    assert key_for(src, "stem") == FillGateElement.objects.get().stem


def test_fillblank_stem_is_the_COMPOSED_shape(monkeypatch):
    # The composition is real even though the corpus holds zero coloured
    # fillblank stems -- hence a synthesised fixture.
    src = f'<p><span style="color: red;">a</span></p> {S}0{S}'
    _load(monkeypatch, {"type": "fillblank", "stem": src, "blanks": [["x"]]})
    stored = FillBlankQuestionElement.objects.get().stem
    assert key_for(src, "composed") == stored
    # sanitize_html ALONE is not the same string -- this is the silent-miss shape
    # the composed replay exists to prevent (the <p> survives an html-only key and
    # is stripped by the cell pass).
    assert key_for(src, "html") != stored
    # NOT asserted: that the "stem" shape differs. MEASURED over 8 shapes including
    # maths and entities, sanitize_html is a NO-OP on sanitize_cell output, so the
    # composed key and the stem key coincide today. The composition is modelled for
    # FIDELITY to the real write path, not because it currently diverges -- keep it,
    # and re-measure before ever "simplifying" SHAPE_COMPOSED away.


def test_table_cell_is_the_cell_shape(monkeypatch):
    src = '<span style="color: red;">x</span> <strong class="bold">y</strong>'
    _load(
        monkeypatch,
        {"type": "table", "data": {"cells": [[{"html": src}, {"html": ""}]]}},
    )
    stored = TableElement.objects.get().data["cells"][0][0]["html"]
    assert key_for(src, "cell") == stored


def test_legacy_and_current_differ_exactly_where_the_spec_says():
    # nh3 DELETES the class attribute for a tag that is not an allowed_classes
    # key, and emits an empty class="" for one that IS. Adding strong/b/i/u/a to
    # the allowlist in slice 1 therefore moves every such key off the stored
    # value -- the corpus carries 435 nolist, 300 myequation, 201 bold.
    src = '<strong class="yellow_on_gray">x</strong>'
    assert legacy_replay(src, "html") == "<strong>x</strong>"
    assert current_replay(src, "html") == '<strong class="">x</strong>'


def test_value_carries_the_colour_and_differs_from_the_key():
    value, emitted = value_for(RED, "html")
    assert 'class="tc-red"' in value
    assert emitted == 1
    assert value != key_for(RED, "html")


def test_every_carrier_class_produces_a_value_that_DIFFERS_from_its_key():
    # The spec asserts `value != key` per carrier class, and that clause is the whole
    # defence against the span-only no-op: a colouriser that ignored a carrier would
    # emit a value byte-identical to the key, the key would still match, and the run
    # would report ~100% while delivering nothing for that class.
    #
    # One case per row of the spec's carrier table -- span, in-TC_CLASS_TAGS, and
    # outside-TC_CLASS_TAGS -- because they take three different code paths.
    for src in (
        '<span style="color: red;">x</span>',  # span carrier
        '<strong style="color: blue;">x</strong>',  # in TC_CLASS_TAGS
        '<u style="color: red;">x</u>',  # in TC_CLASS_TAGS
        '<p style="color: green;">x</p>',  # outside -- wraps children
        '<li style="color: red;">x</li>',  # outside -- wraps children
        '<figcaption style="color: orange;">x</figcaption>',  # not in ALLOWED_TAGS
    ):
        value, emitted = value_for(src, "html")
        assert emitted == 1, src
        assert "tc-" in value, src
        assert value != key_for(src, "html"), src


def test_value_for_a_non_span_carrier_also_differs_from_the_key():
    src = '<p><strong style="color: blue;">x</strong></p>'
    value, emitted = value_for(src, "html")
    assert value == '<p><strong class="tc-blue">x</strong></p>'
    assert emitted == 1
    assert value != key_for(src, "html")


def test_key_input_never_contains_a_span_tag():
    # The legacy replay uses the live ALLOWED_TAGS, which now CONTAINS span. That
    # is only safe because strip_spans has already removed every one; if a span
    # ever survived, the key would silently gain a <span class=""> the DB does
    # not have. The assertion inside key_for is what makes that loud.
    assert "<span" not in key_for(RED, "html")


def test_current_replay_is_idempotent_on_its_own_output():
    # save() re-sanitises the html shapes and every cell, so a value that is not
    # a fixed point would be rewritten under us and the read-back would fail.
    value, _ = value_for(RED, "html")
    assert current_replay(value, "html") == value
    cell, _ = value_for('<span style="color: red;">x</span>', "cell")
    assert current_replay(cell, "cell") == cell
```

- [ ] **Step 2: Run it to verify it fails**

```bash
uv run pytest tests/test_recolour_replay.py -x -q
```

Expected: `ModuleNotFoundError: No module named 'courses.recolour.replay'`.

- [ ] **Step 3: Parameterise the two sanitisers**

In `courses/sanitize.py`, change `sanitize_html`'s signature and body:

```python
def sanitize_html(value, *, allowed_classes=None):
    """Strip everything outside the safe subset. Idempotent on already-clean input.

    `allowed_classes` is keyword-only and defaults to the live allowlist. The one
    caller that passes it is slice 2's backfill, which replays this sanitiser AS
    IT BEHAVED BEFORE the colour classes existed in order to reconstruct the keys
    the loader actually stored (see LEGACY_ALLOWED_CLASSES above).
    """
    return nh3.clean(
        value or "",
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        allowed_classes=ALLOWED_CLASSES if allowed_classes is None else allowed_classes,
        link_rel=None,  # manage rel ourselves via ALLOWED_ATTRIBUTES
        url_schemes=ALLOWED_URL_SCHEMES,
    )
```

And `sanitize_cell` the same way:

```python
def sanitize_cell(value, *, tags=None, allowed_classes=None):
    """Sanitise one table cell's html to CELL_TAGS, protecting balanced LaTeX
    spans from the HTML tokenizer. Idempotent on already-clean input.

    `tags` and `allowed_classes` are keyword-only and default to the live
    allowlists; see sanitize_html for why the backfill overrides them. `tags` exists
    for the backfill's TEST ORACLE only -- it replays the loader over RAW source, so
    it needs the pre-slice-1 tag set to unwrap spans. The backfill's own key
    generator strips spans before calling this and never passes `tags`."""
    value = value or ""
```

…and inside its `nh3.clean(...)` call make **two** body edits. Replace
`tags=CELL_TAGS,` with:

```python
        tags=CELL_TAGS if tags is None else tags,
```

and replace `allowed_classes=CELL_ALLOWED_CLASSES` with:

```python
        allowed_classes=CELL_ALLOWED_CLASSES
        if allowed_classes is None
        else allowed_classes,
```

**Both edits, not just the second.** A signature that accepts `tags` while the body
still hardcodes `CELL_TAGS` silently ignores the argument, and the only caller that
passes it is Task 4's own test oracle — so spans survive into the oracle's stored
value and `test_table_cell_is_the_cell_shape`,
`test_fill_gate_stem_is_the_stem_segments_shape` and
`test_fillblank_stem_is_the_COMPOSED_shape` all fail against keys that are correct.
That is precisely the misdiagnosis the oracle commentary above warns about.

**Note:** the default must be `None`, not the constant itself —
`LEGACY_CELL_ALLOWED_CLASSES` is the empty dict `{}`, which is falsy, so an
`allowed_classes or CELL_ALLOWED_CLASSES` idiom would silently ignore the legacy
allowlist and produce keys with the *current* behaviour. That is the exact silent
zero-match this module exists to avoid.

In `courses/switchgrid.py`, change `sanitize_stem_segments`:

```python
def sanitize_stem_segments(token_stem: str, *, sanitiser=None) -> str:
    """Sanitize each non-token segment (sanitize_cell) while preserving the tokens.

    Used by the import builder, which bypasses the form's clean()-time sanitize.
    `sanitiser` is keyword-only and defaults to sanitize_cell; slice 2's backfill
    passes the legacy-allowlist variant to rebuild the keys the loader stored."""
    from courses.sanitize import sanitize_cell

    clean = sanitize_cell if sanitiser is None else sanitiser
    parts = _TOKEN_RE.split(token_stem or "")
    # split with one capture group -> [seg, idx, seg, idx, ..., seg]; odd items are
    # the captured index digits, which must be rebuilt back into their sentinel token.
    out = []
    for pos, part in enumerate(parts):
        out.append(_token(int(part)) if pos % 2 else clean(part))
    return "".join(out)
```

- [ ] **Step 4: Write the replay module**

Create `courses/recolour/replay.py`:

```python
"""Replay the import write path for one field, twice.

The KEY replays the sanitiser AS IT BEHAVED AT IMPORT TIME (the frozen LEGACY_*
allowlists), over the source with every <span> unwrapped. The VALUE replays the
CURRENT path over the coloured source. The two differ by construction, and that is
the point: a key that replays the current code yields `<strong class="">x</strong>`
where the DB holds `<strong>x</strong>`, and never matches.

The rule for choosing a composition is "reproduce the full import write path, in
order, including any save()-time sanitiser that runs after the builder's explicit
one" -- NOT "the sanitiser that owns the field", which is ambiguous for exactly the
fields that are sanitised twice.
"""

from functools import partial

from courses.recolour.colouriser import colourise
from courses.recolour.colouriser import strip_spans
from courses.sanitize import LEGACY_ALLOWED_CLASSES
from courses.sanitize import LEGACY_CELL_ALLOWED_CLASSES
from courses.sanitize import sanitize_cell
from courses.sanitize import sanitize_html
from courses.switchgrid import sanitize_stem_segments

# Which sanitiser composition each field shape replays:
#   html     sanitize_html
#            body, success_message, choice/numeric/shorttext stem
#   cell     sanitize_cell
#            table + filltable cells
#   stem     sanitize_stem_segments
#            fill gate, switch gate, guess_number stem
#   composed sanitize_html(sanitize_stem_segments(x))
#            fillblank stem -- the builder sanitises, then QuestionElement.save()
#            sanitises again
SHAPE_HTML = "html"
SHAPE_CELL = "cell"
SHAPE_STEM = "stem"
SHAPE_COMPOSED = "composed"
SHAPES = (SHAPE_HTML, SHAPE_CELL, SHAPE_STEM, SHAPE_COMPOSED)

_legacy_html = partial(sanitize_html, allowed_classes=LEGACY_ALLOWED_CLASSES)
_legacy_cell = partial(sanitize_cell, allowed_classes=LEGACY_CELL_ALLOWED_CLASSES)


def _legacy_stem(value):
    return sanitize_stem_segments(value, sanitiser=_legacy_cell)


_LEGACY = {
    SHAPE_HTML: _legacy_html,
    SHAPE_CELL: _legacy_cell,
    SHAPE_STEM: _legacy_stem,
    SHAPE_COMPOSED: lambda v: _legacy_html(_legacy_stem(v)),
}

_CURRENT = {
    SHAPE_HTML: sanitize_html,
    SHAPE_CELL: sanitize_cell,
    SHAPE_STEM: sanitize_stem_segments,
    SHAPE_COMPOSED: lambda v: sanitize_html(sanitize_stem_segments(v)),
}


def legacy_replay(value, shape):
    """The pre-slice-1 sanitiser composition for `shape`."""
    return _LEGACY[shape](value or "")


def current_replay(value, shape):
    """The post-slice-1 sanitiser composition for `shape`."""
    return _CURRENT[shape](value or "")


def key_for(raw, shape):
    """The exact string the loader stored for this source value."""
    stripped = strip_spans(raw)
    # The legacy replay uses the LIVE tag sets, which now contain `span`. That is
    # only inert because strip_spans has removed every one. A survivor would add a
    # <span class=""> the DB does not have and zero the key with no diagnostic.
    assert "<span" not in stripped, f"strip_spans left a span tag: {stripped[:120]!r}"
    return legacy_replay(stripped, shape)


def value_for(raw, shape):
    """(the coloured string to store, tc-* classes emitted)."""
    coloured, emitted = colourise(raw)
    return current_replay(coloured, shape), emitted
```

- [ ] **Step 5: Run the tests**

```bash
uv run pytest tests/test_recolour_replay.py -q
```

Expected: 12 passed.

If `test_table_cell_is_the_cell_shape` fails on a `source_root`/`source_dir` argument,
note that `build_element` only touches those for image/video/fill_table media cells; a
plain `table` element never reads them, so `""` is safe. A `fill_table` fixture would
need real paths — that is why the table fixture uses `type: "table"`.

- [ ] **Step 6: Falsify — prove the legacy allowlist is load-bearing**

In `replay.py`, change `_legacy_html` to `partial(sanitize_html)` (i.e. drop the
`allowed_classes=LEGACY_ALLOWED_CLASSES` argument). Re-run:

```bash
uv run pytest tests/test_recolour_replay.py -q
```

Expected: RED on `test_legacy_and_current_differ_exactly_where_the_spec_says`. Restore.

Then falsify the composed shape: change `_LEGACY[SHAPE_COMPOSED]` to `_legacy_html`
alone. Expected: RED on `test_fillblank_stem_is_the_COMPOSED_shape`. Restore, confirm
12 passed.

Then falsify the ORACLE itself — the defect this plan shipped in its first draft.
Comment out the four `monkeypatch.setattr` lines in `_patch_loader_to_legacy` and
re-run: expected RED on `test_the_patched_loader_really_is_the_pre_slice_1_loader`
**and** on all five loader-comparison tests, because an unpatched loader stores
`<span>…</span>` where the DB holds bare text. Restore, confirm 12 passed. Paste all
three RED outputs.

- [ ] **Step 7: Confirm the sanitiser change broke nothing**

The two sanitisers are used across the whole app. Run their existing guards:

```bash
uv run pytest courses/tests/test_sanitize_align.py courses/tests/test_sanitize_colour.py courses/tests/test_colour_map.py tests/test_colour_map_drift.py tests/test_transfer_schema.py -q
uv run pytest tests/ courses/tests/ -q -k "sanitize or sanitiz or switchgrid"
```

Expected: all pass **except** `tests/test_richtext_drift.py::test_sanitize_html_call_sites_match_the_registry_baseline`, which Step 7b fixes. A
default-argument change must be behaviour-neutral, so if anything ELSE reddens here,
the default is wrong — but do not reach for the sanitiser signature on account of the
drift guard: that failure is expected and means something different.

Both paths matter. The sanitiser's own guards live in **`courses/tests/`**, not
`tests/` — there is no `tests/test_sanitize_align.py`, and a `-k` sweep restricted to
`tests/` would run none of them while still exiting 0, which reads exactly like
success.

- [ ] **Step 7b: Register the new `sanitize_html` call site with the drift guard**

`tests/test_richtext_drift.py` parses every `courses/**/*.py` (excluding `tests/` and
`sanitize.py`) and asserts the set of `sanitize_html` call sites equals a frozen
baseline. MEASURED: `replay.py`'s `SHAPE_COMPOSED` lambda is a new site, so the guard
fails with

```
AssertionError: The set of sanitize_html() call sites changed.
+ ('recolour/replay.py', '', None): NOT a question form -- courses/richtext.py
  RICH_TEXT_FIELDS needs an entry OR a documented exclusion
```

The guard is asking for one of two things and the **documented exclusion** is the
correct one here: the backfill *replays* the sanitiser to reconstruct stored values,
it does not introduce a new storage location, so `RICH_TEXT_FIELDS` must NOT gain an
entry. Add to `EXPECTED` in `tests/test_richtext_drift.py`, keeping the list sorted:

```python
    # Slice 2's backfill REPLAYS the sanitiser to reconstruct the values the LAL
    # import stored; it is not a storage location, so RICH_TEXT_FIELDS deliberately
    # has no entry for it. Recorded here rather than omitted, so the baseline stays
    # the whole truth.
    ("recolour/replay.py", "", None),
```

Then re-run and confirm it is green:

```bash
uv run pytest tests/test_richtext_drift.py -q
```

Falsify: delete the new `EXPECTED` line, re-run, confirm RED with the message above,
restore.

- [ ] **Step 8: Lint and commit**

```bash
uv run ruff format .
uv run ruff check .
git rev-parse --show-toplevel
git branch --show-current
git add courses/sanitize.py courses/switchgrid.py courses/recolour/replay.py tests/test_recolour_replay.py tests/test_richtext_drift.py
git commit -m "feat(recolour): legacy/current sanitiser replay per field shape"
```
- [ ] **Step L: Record the task in the ledger**

Append to `.superpowers/sdd/progress.md` under `## Tasks`:

```markdown
Task 4: complete (commit <sha>)
  - branch guard: <toplevel> / <branch>
  - <N> passed; falsification RED on <test names>, restored
  - anything surprising, and any decision you had to make that the plan did not cover
```

The ledger is untracked, so this is a file write with **no commit**. It is not
bookkeeping: it is the only record a resumed session has of which tasks are genuinely
done, which is the entire reason Task 0 archives slice 1's ledger rather than appending
to it. Git history shows that a commit happened; the ledger is where you say what was
verified and what surprised you.


---

### Task 5: The source walk and the key map

**Files:**
- Create: `courses/recolour/source.py`
- Test: `tests/test_recolour_source.py`
- Append: `.superpowers/sdd/progress.md` (untracked; no commit)

**Interfaces:**
- Consumes: `colouriser.has_palette_colour`/`roundtrip_is_lossless`, `regions.region_verdict`,
  `replay.key_for`/`value_for` and the four `SHAPE_*` names.
- Produces:
  - `courses.recolour.source.Occurrence` — a `NamedTuple` with fields
    `part: str`, `json_file: str`, `field_path: str`, `shape: str`, `raw: str`.
  - `courses.recolour.source.walk_source(json_dir, excluded_dirs) -> list[Occurrence]`
  - `courses.recolour.source.NOT_UNIT_JSON` — the `{manifest.json, flags.json}` skip
    set, public because Task 7's `--json-dir` validation imports it
  - `courses.recolour.source.KeyMap` — a `NamedTuple` with **seven** fields, in this
    order (construction is positional, so the order is part of the contract):
    `entries: dict[str, str]`, `produced: list[tuple[Occurrence, str]]`,
    `producers: int`, `emitted: int`, `emitted_occurrences: int`,
    `skips: list[tuple[Occurrence, str]]`, `per_part: dict[str, dict]`.
    `emitted_occurrences` is required by Task 7's report and by this task's own
    `test_only_palette_bearing_occurrences_produce_a_key`. `produced` holds the `(occurrence, key)` pairs whose
    key survived into `entries` — the only occurrences that can enter the gate's
    numerator. It exists so the command scores the run without recomputing keys.
  - `courses.recolour.source.build_key_map(occurrences) -> KeyMap`
  - `courses.recolour.source.SKIP_UNCHANGED = "value-equals-key"` (and the other reason constants)

**Traps this task must survive.**
- `out/*/flags.json` is a JSON **list**. Skip `manifest.json` and `flags.json` by name;
  additionally skip any file whose top-level JSON is not a dict.
- The walk must recurse into `spoiler.elements` and `tabs[*].elements`, because
  `build_element` does (`builders.py:90` for spoilers, `:183-185` for tabs). There is no
  second `tabs` level.
- `SwitchGridElement.lines[*].stem` is **out of backfill scope** (2 palette occurrences,
  and it is not an RTE surface). Do not emit it.
- **`flagged` elements and their `raw` key are out of scope, and the spec's stated
  reason for this is measurably wrong.** The spec says the one colour-bearing `raw`
  occurrence (`104_geometria_3_czworokaty/030_wstep.json`) carries "only hex colours —
  neither palette nor in scope". MEASURED: it carries `color: #0000ff`, which
  normalises to `(0, 0, 255)` and **is** the `blue` slot. The real reason is stronger:
  a flagged element is stored as `HtmlElement.html`, which is explicitly **not
  sanitised** (`models.py:662`), so its colour was never lost and there is nothing to
  restore. Recorded here so nobody later "fixes" the walk by adding `raw`.
- `Choice.text`/`Choice.feedback` pass through **none** of the three sanitisers, so MCQ
  option text is outside the feature. Do not emit it.

- [ ] **Step 1: Write the failing test**

Create `tests/test_recolour_source.py`:

```python
"""The source walk and the key map, on a synthetic out/ tree.

The synthetic tree is deliberate: the real corpus is 835 files and asserting against
it would make this a change-detector. Task 1 and Task 8 measure the real corpus.
"""

import json

from courses.recolour.source import SKIP_CONFLICT
from courses.recolour.source import SKIP_FIDELITY
from courses.recolour.source import SKIP_REGION
from courses.recolour.source import SKIP_UNCHANGED
from courses.recolour.source import build_key_map
from courses.recolour.source import walk_source

RED = '<span style="color: red;">a</span>'
BLUE = '<span style="color: blue;">a</span>'


def _tree(tmp_path, files):
    """files: {"<part>/<name>.json": <python object>}"""
    for rel, payload in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload), "utf-8")
    return tmp_path


def test_walk_finds_every_shape(tmp_path):
    root = _tree(
        tmp_path,
        {
            "010_p/010_u.json": {
                "elements": [
                    {"type": "text", "body": RED},
                    {"type": "choice", "stem": RED, "choices": []},
                    {"type": "fill_gate", "stem": RED, "answers": []},
                    {"type": "fillblank", "stem": RED, "blanks": []},
                    {"type": "table", "data": {"cells": [[{"html": RED}]]}},
                ]
            }
        },
    )
    shapes = sorted(o.shape for o in walk_source(root, excluded_dirs=()))
    assert shapes == ["cell", "composed", "html", "html", "stem"]


def test_walk_recurses_into_spoilers_and_tabs(tmp_path):
    root = _tree(
        tmp_path,
        {
            "010_p/010_u.json": {
                "elements": [
                    {
                        "type": "spoiler",
                        "label": "L",
                        "elements": [{"type": "text", "body": RED}],
                    },
                    {
                        "type": "tabs",
                        "tabs": [
                            {
                                "id": "t1",
                                "label": "T",
                                "elements": [{"type": "text", "body": BLUE}],
                            }
                        ],
                    },
                ]
            }
        },
    )
    assert len(walk_source(root, excluded_dirs=())) == 2


def test_walk_skips_manifest_and_the_list_shaped_flags_file(tmp_path):
    # flags.json is a JSON LIST. Without the skip the walk raises
    # AttributeError: 'list' object has no attribute 'get'.
    root = _tree(
        tmp_path,
        {
            "010_p/manifest.json": {"part": {"order": 1}},
            "010_p/flags.json": [{"type": "text", "body": RED}],
            "010_p/010_u.json": {"elements": [{"type": "text", "body": RED}]},
        },
    )
    assert len(walk_source(root, excluded_dirs=())) == 1


def test_walk_honours_the_source_side_exclusion(tmp_path):
    root = _tree(
        tmp_path,
        {
            "001_zbiory_liczbowe/010_u.json": {
                "elements": [{"type": "text", "body": RED}]
            },
            "010_p/010_u.json": {"elements": [{"type": "text", "body": RED}]},
        },
    )
    occ = walk_source(root, excluded_dirs=("001_zbiory_liczbowe",))
    assert [o.part for o in occ] == ["010_p"]


def test_walk_ignores_switchgrid_line_stems_and_choice_option_text(tmp_path):
    # Out of backfill scope: line stems are not an RTE surface, and Choice.text
    # passes through none of the three sanitisers.
    #
    # Asserted on field_paths, NOT on emptiness: walk_source emits every non-empty
    # registry field, and the palette filter lives in build_key_map. The choice
    # element's own `stem` is legitimately walked -- only its option text is not.
    root = _tree(
        tmp_path,
        {
            "010_p/010_u.json": {
                "elements": [
                    {"type": "switch_grid", "prompt": "", "lines": [{"stem": RED}]},
                    {
                        "type": "choice",
                        "stem": "plain",
                        "choices": [{"text": RED, "is_correct": True}],
                    },
                ]
            }
        },
    )
    occ = walk_source(root, excluded_dirs=())
    assert [o.field_path for o in occ] == ["elements[1].stem"]
    assert build_key_map(occ).producers == 0  # neither carries palette colour


def test_only_palette_bearing_occurrences_produce_a_key(tmp_path):
    root = _tree(
        tmp_path,
        {
            "010_p/010_u.json": {
                "elements": [
                    {"type": "text", "body": RED},
                    {"type": "text", "body": '<span style="color: purple;">a</span>'},
                    {"type": "text", "body": "<p>plain</p>"},
                ]
            }
        },
    )
    km = build_key_map(walk_source(root, excluded_dirs=()))
    assert km.producers == 1
    assert len(km.entries) == 1
    assert km.emitted == 1
    assert km.emitted_occurrences == 1


def test_the_key_maps_to_a_DIFFERENT_value():
    from courses.recolour.source import Occurrence

    km = build_key_map([Occurrence("p", "f.json", "elements[0].body", "html", RED)])
    (key, value), = km.entries.items()
    assert key == "a"
    assert value == '<span class="tc-red">a</span>'


def test_a_no_op_colouring_is_named_unchanged_and_never_enters_the_map():
    # The failure mode the gate's `value != key` clause exists for. A span-only
    # colouriser leaves <strong style="color:red"> untouched, the sanitiser strips
    # `style`, and the value comes out byte-identical to the key -- a silent no-op
    # that would otherwise score as a success.
    #
    # The real colouriser does NOT have that bug, so this test constructs the shape
    # directly: a palette colour on a tag both sanitisers delete outright, where
    # key and value are both the empty string no matter what the colouriser does.
    from courses.recolour.source import Occurrence

    raw = '<script style="color: red;">a</script>'
    km = build_key_map([Occurrence("p", "f.json", "x", "html", raw)])
    # It DID carry palette colour, so it counts in the denominator...
    assert km.producers == 1
    # ...but it can never count in the numerator.
    assert km.entries == {}
    assert [r for _o, r in km.skips if r == SKIP_UNCHANGED]


def test_an_ordinary_occurrence_is_not_reported_as_unchanged():
    from courses.recolour.source import Occurrence

    km = build_key_map([Occurrence("p", "f.json", "x", "html", RED)])
    assert not [r for _o, r in km.skips if r == SKIP_UNCHANGED]


def test_two_different_colourings_of_one_key_are_refused():
    from courses.recolour.source import Occurrence

    km = build_key_map(
        [
            Occurrence("p", "f.json", "x", "html", RED),
            Occurrence("p", "g.json", "y", "html", BLUE),
        ]
    )
    assert km.entries == {}
    assert [r for _o, r in km.skips if r == SKIP_CONFLICT]


def test_a_conflict_stays_refused_when_the_first_colouring_recurs():
    # Stickiness. Without the `refused` set the third occurrence re-inserts the
    # key with RED's value and the run writes a colouring two sources disagree on.
    from courses.recolour.source import Occurrence

    km = build_key_map(
        [
            Occurrence("p", "f.json", "x", "html", RED),
            Occurrence("p", "g.json", "y", "html", BLUE),
            Occurrence("p", "h.json", "z", "html", RED),
        ]
    )
    assert km.entries == {}
    assert km.produced == []


def test_the_same_colouring_twice_is_not_a_conflict():
    from courses.recolour.source import Occurrence

    km = build_key_map(
        [
            Occurrence("p", "f.json", "x", "html", RED),
            Occurrence("p", "g.json", "y", "html", RED),
        ]
    )
    assert len(km.entries) == 1
    assert km.producers == 2
    assert not [r for _o, r in km.skips if r == SKIP_CONFLICT]


def test_a_lossy_round_trip_is_skipped_and_named():
    # The one guard between a lossy bs4 round-trip and a corrupted write. MEASURED
    # on the current corpus it never fires (0 of 319), which is exactly why it needs
    # a synthetic case: a branch that never executes in production and has no test
    # is a branch nobody knows is broken.
    #
    # An unclosed tag is the reliable trigger: bs4 closes it on serialisation, so
    # decode_contents() != source. MEASURED: '<p style="color: red;">a' round-trips
    # to '<p style="color: red;">a</p>'.
    from courses.recolour.source import Occurrence

    raw = '<p style="color: red;">a'
    km = build_key_map([Occurrence("p", "f.json", "x", "html", raw)])
    # It carries palette colour, so it counts in the denominator...
    assert km.producers == 1
    # ...but it is never written.
    assert km.entries == {}
    assert [r for _o, r in km.skips if r == SKIP_FIDELITY]


def test_a_region_intersecting_occurrence_is_refused_and_named():
    from courses.recolour.source import Occurrence

    occ = Occurrence(
        "p", "f.json", "x", "html", 'a \\(<span style="color: red;">x</span>+y\\) b'
    )
    km = build_key_map([occ])
    assert km.entries == {}
    # startswith, not ==: the stored reason is prefixed with the specific refusal
    # (`protected-region: colour intersects a maths region`). SKIP_UNCHANGED and
    # SKIP_CONFLICT are stored bare, which is what makes this one easy to miss.
    assert [r for _o, r in km.skips if r.startswith(SKIP_REGION)]


def test_per_part_counters_are_populated():
    from courses.recolour.source import Occurrence

    km = build_key_map(
        [
            Occurrence("010_p", "f.json", "x", "html", RED),
            Occurrence("020_q", "g.json", "y", "html", BLUE),
        ]
    )
    assert km.per_part["010_p"]["producers"] == 1
    assert km.per_part["020_q"]["producers"] == 1
```

- [ ] **Step 2: Run it to verify it fails**

```bash
uv run pytest tests/test_recolour_source.py -x -q
```

Expected: `ModuleNotFoundError: No module named 'courses.recolour.source'`.

- [ ] **Step 3: Implement**

Create `courses/recolour/source.py`:

```python
"""Walk the parser output and build the key -> coloured-value map.

Two stages with different filters, and conflating them is a real source of
confusion. `walk_source` emits one Occurrence per non-empty (json_file, field_path)
registry field -- ALL of them, colour or not. `build_key_map` is what applies the
palette filter: an occurrence carrying no palette colour produces no key and is not
counted, because there is nothing to restore and rewriting the field merely to strip
a gray span would touch content for no gain.
"""

import json
from collections import defaultdict
from pathlib import Path
from typing import NamedTuple

from courses.recolour.colouriser import has_palette_colour
from courses.recolour.colouriser import roundtrip_is_lossless
from courses.recolour.regions import region_verdict
from courses.recolour.replay import SHAPE_CELL
from courses.recolour.replay import SHAPE_COMPOSED
from courses.recolour.replay import SHAPE_HTML
from courses.recolour.replay import SHAPE_STEM
from courses.recolour.replay import key_for
from courses.recolour.replay import value_for

SKIP_REGION = "protected-region"
SKIP_CONFLICT = "conflicting-colouring"
SKIP_UNCHANGED = "value-equals-key"
SKIP_FIDELITY = "bs4-round-trip-lossy"

# Files under a part directory that are not unit payloads. flags.json is a JSON
# LIST, so a walk that does not skip it dies with
# `AttributeError: 'list' object has no attribute 'get'`.
#
# PUBLIC (no leading underscore) because the management command imports it to
# validate --json-dir. Same rule as colouriser.soup(): a cross-module reach for an
# underscore-private name is coupling nobody notices until someone renames it.
NOT_UNIT_JSON = {"manifest.json", "flags.json"}


class Occurrence(NamedTuple):
    part: str
    json_file: str
    field_path: str
    shape: str
    raw: str


class KeyMap(NamedTuple):
    entries: dict  # key -> coloured value
    produced: list  # [(Occurrence, key)] for the keys that survived into entries
    producers: int  # occurrences carrying palette colour (the gate's DENOMINATOR)
    emitted: int  # tc-* classes across DISTINCT keys (what the map would write)
    emitted_occurrences: int  # tc-* classes across ALL producing occurrences
    skips: list  # [(Occurrence, reason)]
    per_part: dict  # part -> {"producers": int, "emitted": int}

# TWO emitted counts, because they answer different questions and the spec's
# source-side expectation is stated per OCCURRENCE. MEASURED on the real corpus with
# the two parts excluded: emitted (distinct keys) = 500, emitted_occurrences = 557.
# The spec predicts 588 palette elements minus the 29 in the excluded parts = 559,
# and the residual 2 are the SwitchGrid line stems, which are out of backfill scope.
# Comparing the distinct-key figure against a per-occurrence expectation is what
# makes the span-only-colouriser diagnostic in Task 8 give no verdict at all.


# The denominator deliberately counts EVERY palette-bearing occurrence, including
# the ones later refused for a protected region or a conflicting colouring. A
# refusal is a real shortfall in delivered colour and should drag the rate down
# where an operator sees it, not be quietly excluded from the arithmetic.


def _emit(out, part, jf, path, shape, raw):
    if isinstance(raw, str) and raw:
        out.append(Occurrence(part, jf, path, shape, raw))


def _walk_element(el, out, part, jf, path):
    if not isinstance(el, dict):
        return
    if el.get("flagged"):
        # builders.py:76 tests `flagged` BEFORE any type dispatch and stores el["raw"]
        # into HtmlElement.html, which is explicitly NOT sanitised (models.py:662).
        # So a flagged element's colour was never lost and there is nothing to restore
        # -- and emitting an occurrence for one would produce a key that can never
        # match, surfacing only as an unattributable dip in the gate rate. MEASURED:
        # the corpus holds exactly ONE flagged element, of type `html`, so this is
        # inert today; it is closed for the same reason the other never-executing
        # branches here are.
        return
    etype = el.get("type")
    # Mirrors builders.py's TYPE DISPATCH (not its flagged branch, handled above).
    # `explanation` is absent
    # because no builder branch writes one; SwitchGridElement.lines[*].stem and
    # Choice.text/feedback are absent because they are out of backfill scope.
    if etype in ("text", "spoiler"):
        _emit(out, part, jf, f"{path}.body", SHAPE_HTML, el.get("body"))
    if etype in ("choice", "numeric", "shorttext"):
        _emit(out, part, jf, f"{path}.stem", SHAPE_HTML, el.get("stem"))
    if etype in ("fill_gate", "switch_gate", "guess_number"):
        _emit(out, part, jf, f"{path}.stem", SHAPE_STEM, el.get("stem"))
    if etype == "guess_number":
        _emit(
            out,
            part,
            jf,
            f"{path}.success_message",
            SHAPE_HTML,
            el.get("success_message"),
        )
    if etype == "fillblank":
        _emit(out, part, jf, f"{path}.stem", SHAPE_COMPOSED, el.get("stem"))
    if etype in ("table", "fill_table"):
        data = el.get("data")
        if isinstance(data, dict):
            for r, row in enumerate(data.get("cells") or []):
                if not isinstance(row, list):
                    continue
                for c, cell in enumerate(row):
                    if isinstance(cell, dict):
                        _emit(
                            out,
                            part,
                            jf,
                            f"{path}.data.cells[{r}][{c}].html",
                            SHAPE_CELL,
                            cell.get("html"),
                        )
    for i, child in enumerate(el.get("elements") or []):
        _walk_element(child, out, part, jf, f"{path}.elements[{i}]")
    for t, tab in enumerate(el.get("tabs") or []):
        if isinstance(tab, dict):
            for i, child in enumerate(tab.get("elements") or []):
                _walk_element(child, out, part, jf, f"{path}.tabs[{t}].elements[{i}]")


def walk_source(json_dir, excluded_dirs):
    """Every field occurrence in every eligible part, in a stable order."""
    excluded = set(excluded_dirs or ())
    out = []
    for jf in sorted(Path(json_dir).glob("*/*.json")):
        if jf.name in NOT_UNIT_JSON or jf.parent.name in excluded:
            continue
        payload = json.loads(jf.read_text("utf-8"))
        if not isinstance(payload, dict):
            continue
        for i, el in enumerate(payload.get("elements") or []):
            _walk_element(el, out, jf.parent.name, str(jf), f"elements[{i}]")
    return out


def build_key_map(occurrences):
    """The key -> value map, plus everything the report and the gate need."""
    entries = {}
    produced = []
    origin = {}  # key -> the first Occurrence that produced it
    refused = set()  # keys retracted for a conflict -- NEVER re-enter the map
    emitted_by_key = {}  # key -> tc-* classes it contributed, for exact retraction
    skips = []
    producers = 0
    emitted = 0
    emitted_occurrences = 0
    per_part = defaultdict(lambda: {"producers": 0, "emitted": 0})

    for occ in occurrences:
        if not has_palette_colour(occ.raw):
            continue
        producers += 1
        per_part[occ.part]["producers"] += 1
        if not roundtrip_is_lossless(occ.raw):
            skips.append((occ, SKIP_FIDELITY))
            continue
        refusal = region_verdict(occ.raw, sentinel_tokens=occ.shape in (SHAPE_STEM, SHAPE_COMPOSED))
        if refusal:
            skips.append((occ, f"{SKIP_REGION}: {refusal}"))
            continue
        key = key_for(occ.raw, occ.shape)
        if key in refused:
            # Stickiness matters: without it a THIRD occurrence carrying the
            # FIRST colouring silently re-inserts a key two occurrences already
            # disagreed about, and the conflict guard becomes a no-op on exactly
            # the shape it exists for. Corpus conflicts are 0 today, so the real
            # run would never expose this.
            skips.append((occ, SKIP_CONFLICT))
            continue
        value, n = value_for(occ.raw, occ.shape)
        if value == key:
            # A colouriser that delivered nothing. The gate's `value != key`
            # clause is what stops this scoring as a success.
            skips.append((occ, SKIP_UNCHANGED))
            continue
        if key in entries and entries[key] != value:
            # The one shape that could colour something WRONG. Refuse both, and
            # retract the entry AND the earlier occurrence's claim on it.
            n_first = emitted_by_key.pop(key, 0)
            skips.append((occ, SKIP_CONFLICT))
            skips.append((origin[key], SKIP_CONFLICT))
            del entries[key]
            refused.add(key)
            produced[:] = [p for p in produced if p[1] != key]
            # Undo the retracted entry's contribution to the tc-* counters. Task 8
            # Step 5 reads `tc-* classes (occurrences)` against ~559 to detect a
            # span-only colouriser, so leaving classes in that will never be written
            # feeds a wrong number into a live diagnostic. Corpus conflicts are 0, so
            # this is inert today -- closed for the same reason as the other
            # never-executing branches in this module.
            # Subtract n_first ONLY. This occurrence's own `n` was never added:
            # `emitted_occurrences += n` sits below the `continue`, so subtracting
            # n_first + n drives the counter NEGATIVE. Measured: -1 on a two-occurrence
            # RED/BLUE conflict.
            emitted -= n_first
            emitted_occurrences -= n_first
            per_part[origin[key].part]["emitted"] -= n_first
            continue
        produced.append((occ, key))
        emitted_occurrences += n
        if key in entries:
            # Same colouring twice -- 0 conflicts measured on the corpus. Both
            # occurrences count towards the numerator, so both are in `produced`.
            # (Post-exclusion: 227 distinct keys across 265 occurrences.)
            continue
        entries[key] = value
        origin[key] = occ
        emitted_by_key[key] = n  # so a later retraction can undo exactly this much
        emitted += n
        per_part[occ.part]["emitted"] += n

    return KeyMap(
        entries, produced, producers, emitted, emitted_occurrences, skips,
        dict(per_part)
    )
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/test_recolour_source.py -q
```

Expected: 15 passed.

- [ ] **Step 5: Falsify — prove the flags.json skip and the conflict guard are real**

Remove `"flags.json"` from `NOT_UNIT_JSON` **and** the `if not isinstance(payload,
dict): continue` guard in `walk_source`, then re-run — expected RED with an
`AttributeError: 'list' object has no attribute 'get'` on
`test_walk_skips_manifest_and_the_list_shaped_flags_file`. Restore both.

**Removing only one of the two leaves the test GREEN**, because they are redundant
guards on the same hazard: the name skip alone, or the isinstance check alone, is
enough to survive `flags.json`. MEASURED. Do not spend time hunting a phantom when
the single-guard removal stays green — that is the expected result, and it is why
this step names both.

Then remove the `if key in entries and entries[key] != value:` branch and re-run —
expected RED on `test_two_different_colourings_of_one_key_are_refused`. Restore.

Then remove the `if key in refused:` block and re-run — expected RED on
`test_a_conflict_stays_refused_when_the_first_colouring_recurs`. Restore.

Then remove the `if not roundtrip_is_lossless(occ.raw):` block and re-run — expected
RED on `test_a_lossy_round_trip_is_skipped_and_named`. Restore, confirm 15 passed.
Paste all four RED outputs.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff format .
uv run ruff check .
git rev-parse --show-toplevel
git branch --show-current
git add courses/recolour/source.py tests/test_recolour_source.py
git commit -m "feat(recolour): source walk and key map with conflict/region refusals"
```
- [ ] **Step L: Record the task in the ledger**

Append to `.superpowers/sdd/progress.md` under `## Tasks`:

```markdown
Task 5: complete (commit <sha>)
  - branch guard: <toplevel> / <branch>
  - <N> passed; falsification RED on <test names>, restored
  - anything surprising, and any decision you had to make that the plan did not cover
```

The ledger is untracked, so this is a file write with **no commit**. It is not
bookkeeping: it is the only record a resumed session has of which tasks are genuinely
done, which is the entire reason Task 0 archives slice 1's ledger rather than appending
to it. Git history shows that a commit happened; the ledger is where you say what was
verified and what surprised you.


---

### Task 6: The DB side — candidates, matching, rewrite with read-back

**Files:**
- Create: `courses/recolour/dbscan.py`
- Test: `tests/test_recolour_dbscan.py` (create)
- Append: `.superpowers/sdd/progress.md` (untracked; no commit)

**Interfaces:**
- Consumes: `courses.models` only. `find_matches` takes a plain `key -> value` dict,
  NOT a `KeyMap` — the command (Task 7) is the only consumer of that type, and
  `dbscan.py` imports nothing from `courses.recolour.source`. Keeping the dependency
  out is what lets Task 6's tests build `entries` as a two-line literal.
- Produces:
  - `courses.recolour.dbscan.HTML_FIELDS` / `CELL_FIELDS` — the `(model, field)` registry.
  - `courses.recolour.dbscan.excluded_node_ids(course, pks) -> set[int]`
  - `courses.recolour.dbscan.find_matches(course, entries, excluded) -> list[Match]`
    where `Match` is a `NamedTuple` with the six REQUIRED fields
    `(model, pk, field, cell, key, value)` — no defaults; `cell` is `(row_index,
    col_index)` for a JSON cell field and `None` for an HTML field, and must be passed
    explicitly either way.
  - `courses.recolour.dbscan.apply_matches(matches) -> int` — writes and reads back;
    raises `ReadBackError` on any byte difference.
  - `courses.recolour.dbscan.MultiOwnerError`, `courses.recolour.dbscan.ReadBackError`.

**Why the base filter is not optional.** `.exclude()` on a reverse relation keeps rows
with **no** `Element` at all, so an orphaned content row would survive both filters.
`.filter(elements__unit__course=course)` first (mirroring `richtext.py:261`) is what
scopes the scan. And that exclusion is only correct because a content row has exactly one
owning `Element` — the caveat recorded on `count_inbound_links` — so the command **fails
closed** if it meets a row reachable from more than one.

- [ ] **Step 1: Write the failing test**

Create `tests/test_recolour_dbscan.py`:

```python
"""Candidate scoping, the fail-closed multi-owner guard, and the read-back."""

import pytest

from courses.models import ContentNode
from courses.models import Element
from courses.models import TableElement
from courses.models import TextElement
from courses.recolour.dbscan import MultiOwnerError
from courses.recolour.dbscan import ReadBackError
from courses.recolour.dbscan import apply_matches
from courses.recolour.dbscan import excluded_node_ids
from courses.recolour.dbscan import find_matches
from tests.factories import CourseFactory

pytestmark = pytest.mark.django_db


def _unit(course, part_title="P"):
    part = ContentNode.objects.create(
        course=course, parent=None, order=0, kind="part", title=part_title
    )
    ch = ContentNode.objects.create(
        course=course, parent=part, order=0, kind="chapter", title="C"
    )
    unit = ContentNode.objects.create(
        course=course, parent=ch, order=0, kind="unit", title="U", unit_type="lesson"
    )
    return part, unit


def _text(unit, body):
    el = TextElement.objects.create(body=body)
    Element.objects.create(unit=unit, content_object=el)
    return el


def test_a_matching_body_is_found():
    course = CourseFactory()
    _part, unit = _unit(course)
    _text(unit, "założenie")
    matches = find_matches(course, {"założenie": '<span class="tc-red">założenie</span>'}, set())
    assert len(matches) == 1
    assert matches[0].field == "body"


def test_a_non_matching_body_is_not_found():
    course = CourseFactory()
    _part, unit = _unit(course)
    _text(unit, "założenie (edited)")
    assert find_matches(course, {"założenie": "x"}, set()) == []


def test_another_courses_content_is_out_of_scope():
    other = CourseFactory(slug="other")
    _part, unit = _unit(other)
    _text(unit, "założenie")
    mine = CourseFactory(slug="mine")
    assert find_matches(mine, {"założenie": "x"}, set()) == []


def test_an_excluded_subtree_is_filtered_out():
    course = CourseFactory()
    part, unit = _unit(course)
    _text(unit, "założenie")
    excluded = excluded_node_ids(course, [part.pk])
    assert unit.pk in excluded  # the DESCENDANT walk is the whole correctness
    assert find_matches(course, {"założenie": "x"}, excluded) == []


def test_an_orphaned_row_with_no_element_is_never_a_candidate():
    # .exclude() on a reverse relation KEEPS rows with no Element at all; the
    # course-scoped base filter is what removes them.
    course = CourseFactory()
    _unit(course)
    TextElement.objects.create(body="założenie")
    assert find_matches(course, {"założenie": "x"}, set()) == []


def test_a_row_owned_by_two_elements_fails_closed():
    course = CourseFactory()
    _part, unit = _unit(course)
    el = _text(unit, "założenie")
    Element.objects.create(unit=unit, content_object=el)  # a second owner
    with pytest.raises(MultiOwnerError):
        find_matches(course, {"założenie": "x"}, set())


def test_a_table_matches_per_cell_and_rewrites_partially():
    course = CourseFactory()
    _part, unit = _unit(course)
    tbl = TableElement.objects.create(
        data=TableElement.normalize_data(
            {"cells": [[{"html": "a"}, {"html": "b"}], [{"html": "c"}, {"html": "d"}]]}
        )
    )
    Element.objects.create(unit=unit, content_object=tbl)
    matches = find_matches(
        course, {"a": '<span class="tc-red">a</span>', "d": '<span class="tc-blue">d</span>'}, set()
    )
    assert sorted(m.cell for m in matches) == [(0, 0), (1, 1)]
    assert apply_matches(matches) == 1  # one CHANGED FIELD, two cells
    tbl.refresh_from_db()
    cells = tbl.data["cells"]
    assert cells[0][0]["html"] == '<span class="tc-red">a</span>'
    assert cells[1][1]["html"] == '<span class="tc-blue">d</span>'
    assert cells[0][1]["html"] == "b"  # untouched
    assert cells[1][0]["html"] == "c"


def test_a_filltable_answer_cell_is_never_matched():
    # FillTableElement._sanitized_data re-sanitises cell["html"] ONLY for cells whose
    # kind is neither `answer` nor `image` (models.py:1120-1134), so a match landing on
    # an answer cell would be written UNSANITISED and the read-back would not notice --
    # it compares against what we wrote. The corpus produces zero fill-table matches,
    # so without this test the guard would ship having never executed.
    #
    # The row is built from RAW data, deliberately NOT through normalize_data. MEASURED:
    # normalize_data DROPS the html key from an answer cell (it emits `answer` instead),
    # so a normalised fixture has no html for find_matches to see and the test would
    # pass with the guard deleted -- vacuous. save() -> _sanitized_data does NOT delete
    # a stray html key, so this shape is what a legacy or hand-edited row looks like,
    # and it is the shape the guard exists for.
    from courses.models import FillTableElement

    course = CourseFactory()
    _part, unit = _unit(course)
    ft = FillTableElement.objects.create(
        data={
            "cells": [
                [
                    {"kind": "static", "html": "a", "halign": "left"},
                    {"kind": "answer", "html": "a", "answer": "a"},
                ]
            ]
        }
    )
    Element.objects.create(unit=unit, content_object=ft)
    ft.refresh_from_db()
    # Precondition: the answer cell really does still carry an html key, or the test
    # below proves nothing.
    assert ft.data["cells"][0][1]["html"] == "a"
    matches = find_matches(course, {"a": '<span class="tc-red">a</span>'}, set())
    ft_matches = [m for m in matches if m.model is FillTableElement]
    assert [m.cell for m in ft_matches] == [(0, 0)]  # the STATIC cell only


def test_apply_reads_every_rewritten_field_back():
    course = CourseFactory()
    _part, unit = _unit(course)
    el = _text(unit, "założenie")
    matches = find_matches(course, {"założenie": '<span class="tc-red">założenie</span>'}, set())
    assert apply_matches(matches) == 1
    el.refresh_from_db()
    assert el.body == '<span class="tc-red">założenie</span>'


def test_titles_are_never_read_or_written():
    course = CourseFactory()
    part, unit = _unit(course)
    _text(unit, "założenie")
    before = dict(ContentNode.objects.values_list("pk", "title"))
    matches = find_matches(course, {"założenie": '<span class="tc-red">założenie</span>'}, set())
    apply_matches(matches)
    assert dict(ContentNode.objects.values_list("pk", "title")) == before


def test_a_field_the_write_path_alters_raises_ReadBackError(monkeypatch):
    # The read-back is the ONLY safety net for the three gate stems, whose save()
    # explicitly declines to touch `stem` (models.py:776-779). Exercising it only
    # inside a falsification step would leave the committed suite with no guard on
    # the one check standing between a mangled write and the database.
    #
    # The mangling is "X", NOT an HTML comment: TextElement.save runs sanitize_html
    # and nh3 defaults to strip_comments=True, so a comment is erased before the row
    # is written, the read-back matches, and the test can never fire. MEASURED.
    course = CourseFactory()
    _part, unit = _unit(course)
    _text(unit, "założenie")
    original = TextElement.save

    def _mangling_save(self, *a, **kw):
        self.body = self.body + "X"
        return original(self, *a, **kw)

    monkeypatch.setattr(TextElement, "save", _mangling_save)
    matches = find_matches(
        course, {"założenie": '<span class="tc-red">założenie</span>'}, set()
    )
    with pytest.raises(ReadBackError):
        apply_matches(matches)


def test_a_read_back_failure_inside_a_transaction_leaves_the_row_untouched(monkeypatch):
    # apply_matches is called inside transaction.atomic() by the command, so the
    # raise must roll the write back rather than leave a half-applied course.
    from django.db import transaction

    course = CourseFactory()
    _part, unit = _unit(course)
    el = _text(unit, "założenie")
    original = TextElement.save

    def _mangling_save(self, *a, **kw):
        self.body = self.body + "X"
        return original(self, *a, **kw)

    monkeypatch.setattr(TextElement, "save", _mangling_save)
    matches = find_matches(
        course, {"założenie": '<span class="tc-red">założenie</span>'}, set()
    )
    with pytest.raises(ReadBackError), transaction.atomic():
        apply_matches(matches)
    el.refresh_from_db()
    assert el.body == "założenie"


def test_a_second_apply_matches_nothing():
    course = CourseFactory()
    _part, unit = _unit(course)
    _text(unit, "założenie")
    entries = {"założenie": '<span class="tc-red">założenie</span>'}
    apply_matches(find_matches(course, entries, set()))
    assert find_matches(course, entries, set()) == []
```

- [ ] **Step 2: Run it to verify it fails**

```bash
uv run pytest tests/test_recolour_dbscan.py -x -q
```

Expected: `ModuleNotFoundError: No module named 'courses.recolour.dbscan'`.

- [ ] **Step 3: Implement**

Create `courses/recolour/dbscan.py`:

```python
"""Find the stored fields whose bytes equal a key, and rewrite them.

The registry is built from what the LAL loader actually writes, not from
courses.richtext.RICH_TEXT_FIELDS: that registry exists for internal links, includes
CalloutElement (which no builder branch creates) and excludes the two JSON cell
fields, which the backfill must cover.
"""

from typing import NamedTuple

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count

from courses.models import ChoiceQuestionElement
from courses.models import ContentNode
from courses.models import Element
from courses.models import FillBlankQuestionElement
from courses.models import FillGateElement
from courses.models import FillTableElement
from courses.models import GuessNumberElement
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from courses.models import SpoilerElement
from courses.models import SwitchGateElement
from courses.models import TableElement
from courses.models import TextElement


class MultiOwnerError(RuntimeError):
    """A content row is reachable from more than one Element -- fail closed."""


class ReadBackError(RuntimeError):
    """A rewritten field did not read back byte-identical to what was written."""


HTML_FIELDS = [
    (TextElement, "body"),
    (SpoilerElement, "body"),
    (ChoiceQuestionElement, "stem"),
    (ShortNumericQuestionElement, "stem"),
    (ShortTextQuestionElement, "stem"),
    (FillBlankQuestionElement, "stem"),
    (FillGateElement, "stem"),
    (SwitchGateElement, "stem"),
    (GuessNumberElement, "stem"),
    (GuessNumberElement, "success_message"),
]
CELL_FIELDS = [(TableElement, "data"), (FillTableElement, "data")]


class Match(NamedTuple):
    model: type
    pk: int
    field: str
    cell: tuple  # (row, col) for a JSON cell field; None for an HTML field
    key: str
    value: str


def excluded_node_ids(course, pks):
    """Every node id in the named subtrees. The DESCENDANT walk is the whole
    correctness of the exclusion: a key built from an eligible part can match text
    that is byte-identical inside an excluded part, and source-side exclusion alone
    cannot prevent that."""
    ids = set()
    for pk in pks:
        node = ContentNode.objects.filter(course=course, pk=pk).first()
        if node is not None:
            ids |= set(node._subtree_node_ids())
    return ids


def _candidates(model, course, excluded):
    qs = model.objects.filter(elements__unit__course=course)
    if excluded:
        qs = qs.exclude(elements__unit_id__in=excluded)
    return qs.distinct()


def _assert_single_owner(model, pks):
    if not pks:
        return
    ct = ContentType.objects.get_for_model(model)
    dupes = (
        Element.objects.filter(content_type=ct, object_id__in=list(pks))
        .values("object_id")
        .annotate(n=Count("pk"))
        .filter(n__gt=1)
        .values_list("object_id", flat=True)
    )
    bad = list(dupes[:5])
    if bad:
        raise MultiOwnerError(
            f"{model.__name__} rows {bad} are owned by more than one Element; "
            "the subtree exclusion cannot be trusted for them"
        )


def find_matches(course, entries, excluded):
    """Every stored field whose bytes equal a key. Never reads ContentNode.title."""
    matches = []
    for model, field in HTML_FIELDS:
        rows = list(_candidates(model, course, excluded).values_list("pk", field))
        _assert_single_owner(model, [pk for pk, _v in rows])
        for pk, stored in rows:
            if stored and stored in entries:
                matches.append(Match(model, pk, field, None, stored, entries[stored]))
    for model, field in CELL_FIELDS:
        rows = list(_candidates(model, course, excluded).values_list("pk", field))
        _assert_single_owner(model, [pk for pk, _v in rows])
        for pk, data in rows:
            if not isinstance(data, dict):
                continue
            for r, row in enumerate(data.get("cells") or []):
                if not isinstance(row, list):
                    continue
                for c, cell in enumerate(row):
                    if not isinstance(cell, dict):
                        continue
                    # FillTableElement._sanitized_data sanitises cell["html"] ONLY for
                    # cells whose kind is neither `answer` nor `image` -- those two keep
                    # their media/answer payload and are never re-sanitised. A match
                    # landing on one would be written UNSANITISED while the read-back
                    # still passed, because the read-back compares against what we
                    # wrote. TableElement cells carry no `kind` at all, so the guard is
                    # a no-op there. The real corpus produces zero fill-table matches,
                    # which is exactly why this branch must be closed rather than left
                    # to ship unexecuted.
                    if cell.get("kind") not in (None, "static"):
                        continue
                    stored = cell.get("html")
                    if stored and stored in entries:
                        matches.append(
                            Match(model, pk, field, (r, c), stored, entries[stored])
                        )
    return matches


def apply_matches(matches):
    """Write every match and read it back. Returns the number of CHANGED FIELDS.

    A table with 3 of 5 cells matching is rewritten partially and counts as ONE
    changed field. The read-back is not optional: the three gate stems have no
    save()-time sanitiser (models.py:776-779), so nothing else would notice a
    value the write path altered under us.
    """
    by_row = {}
    for m in matches:
        by_row.setdefault((m.model, m.pk, m.field), []).append(m)

    for (model, pk, field), group in by_row.items():
        row = model.objects.get(pk=pk)
        if group[0].cell is None:
            setattr(row, field, group[0].value)
        else:
            data = getattr(row, field)
            for m in group:
                data["cells"][m.cell[0]][m.cell[1]]["html"] = m.value
            setattr(row, field, data)
        row.save(update_fields=[field])

        fresh = model.objects.get(pk=pk)
        for m in group:
            if m.cell is None:
                got = getattr(fresh, field)
            else:
                got = getattr(fresh, field)["cells"][m.cell[0]][m.cell[1]]["html"]
            if got != m.value:
                raise ReadBackError(
                    f"{model.__name__}(pk={pk}).{field}"
                    f"{'' if m.cell is None else list(m.cell)} read back as "
                    f"{got[:120]!r}, expected {m.value[:120]!r}"
                )
    return len(by_row)
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/test_recolour_dbscan.py -q
```

Expected: 13 passed.

- [ ] **Step 5: Falsify — prove the base filter and the read-back are real**

Delete the `.filter(elements__unit__course=course)` from `_candidates` (keep only the
`.exclude`) and re-run — expected RED on
`test_an_orphaned_row_with_no_element_is_never_a_candidate` and
`test_another_courses_content_is_out_of_scope`. Restore.

Then prove the read-back actually reads. Corrupt only the **write**, leaving the check
in place: change `setattr(row, field, group[0].value)` to
`setattr(row, field, group[0].value + "X")`. Re-run — expected **three** RED, all from
the same cause (every one of them calls `apply_matches`, so every one now raises):
`test_apply_reads_every_rewritten_field_back`, `test_titles_are_never_read_or_written`
and `test_a_second_apply_matches_nothing`. Three failures is the correct result here,
not an unrelated regression. That proves the check fires on a bad write.

Now, with the corrupt write still in place, also neuter the check by changing
`if got != m.value:` to `if False:` and re-run — again **three** RED, but a different
three: `test_apply_reads_every_rewritten_field_back` (the stored value now ends in `X`
and nothing objected), plus
`test_a_field_the_write_path_alters_raises_ReadBackError` and
`test_a_read_back_failure_inside_a_transaction_leaves_the_row_untouched`, which expect
a `ReadBackError` that no longer comes. That proves the check was the only thing
standing between a bad write and the database. Restore both, confirm 13 passed.

Then falsify the fill-table guard: delete the
`if cell.get("kind") not in (None, "static"): continue` block and re-run — expected RED
on `test_a_filltable_answer_cell_is_never_matched`. Restore.

Paste all four RED outputs.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff format .
uv run ruff check .
git rev-parse --show-toplevel
git branch --show-current
git add courses/recolour/dbscan.py tests/test_recolour_dbscan.py
git commit -m "feat(recolour): DB candidate scan, exclusions, rewrite with read-back"
```
- [ ] **Step L: Record the task in the ledger**

Append to `.superpowers/sdd/progress.md` under `## Tasks`:

```markdown
Task 6: complete (commit <sha>)
  - branch guard: <toplevel> / <branch>
  - <N> passed; falsification RED on <test names>, restored
  - anything surprising, and any decision you had to make that the plan did not cover
```

The ledger is untracked, so this is a file write with **no commit**. It is not
bookkeeping: it is the only record a resumed session has of which tasks are genuinely
done, which is the entire reason Task 0 archives slice 1's ledger rather than appending
to it. Git history shows that a commit happened; the ledger is where you say what was
verified and what surprised you.


---

### Task 7: The `recolour_imported_content` management command

**Files:**
- Create: `courses/management/commands/recolour_imported_content.py`
- Test: `tests/test_recolour_command.py`
- Append: `.superpowers/sdd/progress.md` (untracked; no commit)

**Interfaces:**
- Consumes: everything from Tasks 2-6.
- Produces: the command. No later task imports from it.

**CLI contract:**

```
manage.py recolour_imported_content --course <slug> \
    --exclude <dirname>=<pk> [--exclude <dirname>=<pk> …] \
    [--json-dir scripts/lal_import/out] [--list-matches] [--apply]
```

**Validation rules (each has a test):**
- every pk must exist and belong to `--course`;
- a dirname that does not exist under `--json-dir` is an error — this guards against a
  typo silently disabling the exclusion, which is the failure that recolours hand-edited
  content;
- an **empty** pk (`<dirname>=`) is accepted: it excludes source-side only, for a part
  whose node was deleted from the DB, and the run reports that line explicitly;
- the flag is repeatable with the **same dirname and different pks**, for one source part
  that maps to several nodes after manual restructuring.

**The acceptance gate**, evaluated before any write:
- `rate = numerator / denominator ≥ 0.70`, where the **denominator** is the number of
  source-side occurrences that produced a key and the **numerator** is the subset whose
  key matched at least one DB field. `value != key` is already enforced upstream — an
  occurrence whose value equalled its key never entered `entries`, so it counts in the
  denominator and can never count in the numerator. That is what stops a span-only
  colouriser from scoring ~100% while delivering nothing.
- **no eligible part that produced at least one key matches zero.**
- a denominator of 0 halts too: nothing to do means key construction is broken, not that
  the corpus is clean.
- **Already-applied is not a failure.** After a successful `--apply`, stored values no
  longer equal the keys, so a re-run matches nothing and would halt on the gate. The
  command therefore checks whether the *values* are present in the DB first; if they are
  and no key matches, it reports `already applied — nothing to do` and exits 0.

- [ ] **Step 1: Write the failing test**

Create `tests/test_recolour_command.py`:

```python
"""The command's contract: validation, the gate, dry-run, and the exclusions."""

import json

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from courses.models import ContentNode
from courses.models import Element
from courses.models import TextElement
from tests.factories import CourseFactory

pytestmark = pytest.mark.django_db

RED = '<span style="color: red;">założenie</span>'
STORED = "założenie"
COLOURED = '<span class="tc-red">założenie</span>'


def _out(tmp_path, files):
    for rel, payload in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload), "utf-8")
    return tmp_path


def _course_with(body, part_title="P", slug="mat-pp"):
    course = CourseFactory(slug=slug)
    part = ContentNode.objects.create(
        course=course, parent=None, order=0, kind="part", title=part_title
    )
    ch = ContentNode.objects.create(
        course=course, parent=part, order=0, kind="chapter", title="C"
    )
    unit = ContentNode.objects.create(
        course=course, parent=ch, order=0, kind="unit", title="U", unit_type="lesson"
    )
    el = TextElement.objects.create(body=body)
    Element.objects.create(unit=unit, content_object=el)
    return course, part, el


def _run(tmp_path, **kw):
    args = ["--course", kw.pop("course", "mat-pp"), "--json-dir", str(tmp_path)]
    for pair in kw.pop("exclude", []):
        args += ["--exclude", pair]
    if kw.pop("apply", False):
        args.append("--apply")
    from io import StringIO

    buf = StringIO()
    call_command("recolour_imported_content", *args, stdout=buf)
    return buf.getvalue()


def _simple_tree(tmp_path):
    return _out(tmp_path, {"010_p/010_u.json": {"elements": [{"type": "text", "body": RED}]}})


def test_dry_run_is_the_default_and_writes_nothing(tmp_path):
    _course_with(STORED)
    _simple_tree(tmp_path)
    out = _run(tmp_path)
    assert "DRY RUN" in out
    assert TextElement.objects.get().body == STORED


def test_apply_rewrites_the_matching_field(tmp_path):
    _course_with(STORED)
    _simple_tree(tmp_path)
    _run(tmp_path, apply=True)
    assert TextElement.objects.get().body == COLOURED


def test_an_edited_element_is_skipped(tmp_path):
    _course_with(STORED + " (poprawione)")
    _simple_tree(tmp_path)
    with pytest.raises(CommandError):  # 0 matches -> the gate halts the run
        _run(tmp_path, apply=True)
    assert TextElement.objects.get().body == STORED + " (poprawione)"


def test_every_node_title_is_unchanged(tmp_path):
    _course_with(STORED)
    _simple_tree(tmp_path)
    before = dict(ContentNode.objects.values_list("pk", "title"))
    _run(tmp_path, apply=True)
    assert dict(ContentNode.objects.values_list("pk", "title")) == before


def test_a_second_run_reports_already_applied_and_exits_cleanly(tmp_path):
    _course_with(STORED)
    _simple_tree(tmp_path)
    _run(tmp_path, apply=True)
    out = _run(tmp_path, apply=True)
    assert "already applied" in out.lower()
    assert TextElement.objects.get().body == COLOURED


def test_a_dirname_absent_from_out_is_an_error(tmp_path):
    _course_with(STORED)
    _simple_tree(tmp_path)
    with pytest.raises(CommandError, match="no such part directory"):
        _run(tmp_path, exclude=["999_typo=1"])


def test_a_pk_from_another_course_is_an_error(tmp_path):
    _course_with(STORED)
    other, other_part, _el = _course_with(STORED, slug="other")
    _simple_tree(tmp_path)
    with pytest.raises(CommandError, match="does not belong"):
        _run(tmp_path, exclude=[f"010_p={other_part.pk}"])


def test_a_missing_pk_is_a_source_side_only_exclusion(tmp_path):
    # The part whose node was deleted from the DB.
    _course_with(STORED)
    _out(
        tmp_path,
        {
            "010_p/010_u.json": {"elements": [{"type": "text", "body": RED}]},
            "020_q/010_u.json": {"elements": [{"type": "text", "body": RED}]},
        },
    )
    out = _run(tmp_path, exclude=["020_q="])
    assert "source-side only" in out
    # The exclusion LINE names 020_q; the per-part table must not.
    table = out.split("per part:")[1].split("skipped:")[0]
    assert "010_p" in table
    assert "020_q" not in table


def test_the_exclusion_protects_hand_edited_content_that_matches_a_key(tmp_path):
    # The DB-side failure being blocked: a key built from an ELIGIBLE part can
    # match text that is byte-identical inside an EXCLUDED part.
    course, part, el = _course_with(STORED, part_title="Excluded")
    ch = ContentNode.objects.create(
        course=course, parent=part, order=1, kind="chapter", title="C2"
    )
    unit2 = ContentNode.objects.create(
        course=course, parent=ch, order=0, kind="unit", title="U2", unit_type="lesson"
    )
    twin = TextElement.objects.create(body=STORED)
    Element.objects.create(unit=unit2, content_object=twin)
    _out(
        tmp_path,
        {
            "010_p/010_u.json": {"elements": [{"type": "text", "body": RED}]},
            "001_zbiory_liczbowe/010_u.json": {"elements": []},
        },
    )
    with pytest.raises(CommandError):  # everything excluded -> nothing matches
        _run(tmp_path, exclude=[f"001_zbiory_liczbowe={part.pk}"], apply=True)
    twin.refresh_from_db()
    assert twin.body == STORED


def test_one_dirname_may_be_paired_with_SEVERAL_pks(tmp_path):
    # The spec's "one source part mapping to several nodes after manual
    # restructuring" case. Both named subtrees must be excluded, not just the last
    # pk seen -- an append-style parser that overwrote would silently recolour a
    # hand-edited subtree.
    course, part_a, _el = _course_with(STORED, part_title="A")
    part_b = ContentNode.objects.create(
        course=course, parent=None, order=1, kind="part", title="B"
    )
    ch = ContentNode.objects.create(
        course=course, parent=part_b, order=0, kind="chapter", title="C"
    )
    unit_b = ContentNode.objects.create(
        course=course, parent=ch, order=0, kind="unit", title="U", unit_type="lesson"
    )
    twin = TextElement.objects.create(body=STORED)
    Element.objects.create(unit=unit_b, content_object=twin)
    _simple_tree(tmp_path)
    with pytest.raises(CommandError):  # both subtrees gone -> nothing matches
        _run(
            tmp_path,
            exclude=[f"010_p={part_a.pk}", f"010_p={part_b.pk}"],
            apply=True,
        )
    twin.refresh_from_db()
    assert twin.body == STORED
    assert TextElement.objects.filter(body=STORED).count() == 2


def test_a_region_refusal_is_named_AND_counts_against_the_gate(tmp_path):
    # A refusal is a real shortfall in delivered colour, so it belongs in the
    # denominator where an operator sees it -- here it drops a 2-occurrence run to
    # 50% and halts it. The report is written before the gate raises, so the
    # buffer is still readable.
    from io import StringIO

    _course_with(STORED)
    _out(
        tmp_path,
        {
            "010_p/010_u.json": {
                "elements": [
                    {"type": "text", "body": RED},
                    {
                        "type": "text",
                        "body": 'a \\(<span style="color: red;">x</span>+y\\) b',
                    },
                ]
            }
        },
    )
    buf = StringIO()
    with pytest.raises(CommandError, match="acceptance gate NOT met"):
        call_command(
            "recolour_imported_content",
            "--course",
            "mat-pp",
            "--json-dir",
            str(tmp_path),
            stdout=buf,
        )
    out = buf.getvalue()
    assert "protected-region" in out
    assert "50.0%" in out


def test_the_dry_run_NAMES_each_matched_field(tmp_path):
    # Spec safety property 3 makes the dry-run report the place an operator spots an
    # ACCIDENTAL match -- author-written text that happens to equal an imported key.
    # A report of counts alone cannot do that job, so the listing is load-bearing.
    _course_with(STORED)
    _simple_tree(tmp_path)
    out = _run(tmp_path)
    assert "matches:" in out
    assert "TextElement(" in out
    assert "założenie" in out.split("matches:")[1]


def test_list_matches_is_accepted_and_lists_everything(tmp_path):
    _course_with(STORED)
    _simple_tree(tmp_path)
    from io import StringIO

    buf = StringIO()
    call_command(
        "recolour_imported_content",
        "--course",
        "mat-pp",
        "--json-dir",
        str(tmp_path),
        "--list-matches",
        stdout=buf,
    )
    out = buf.getvalue()
    assert "matches:" in out
    assert "more; pass --list-matches" not in out


def test_both_tc_class_counts_are_reported(tmp_path):
    # Two counts, because the spec's source-side expectation is per OCCURRENCE
    # while the map writes per DISTINCT KEY. Reporting only one makes Task 8's
    # span-only-colouriser diagnostic unverdictable.
    _course_with(STORED)
    _simple_tree(tmp_path)
    out = _run(tmp_path)
    assert "tc-* classes (distinct keys)" in out
    assert "tc-* classes (occurrences)" in out


def test_an_unknown_course_is_an_error(tmp_path):
    _simple_tree(tmp_path)
    with pytest.raises(CommandError):
        _run(tmp_path, course="nope")


def test_a_malformed_exclude_pair_is_an_error(tmp_path):
    _course_with(STORED)
    _simple_tree(tmp_path)
    with pytest.raises(CommandError, match="dirname=pk"):
        _run(tmp_path, exclude=["010_p"])
```

- [ ] **Step 2: Run it to verify it fails**

```bash
uv run pytest tests/test_recolour_command.py -x -q
```

Expected: `CommandError: Unknown command: 'recolour_imported_content'`.

- [ ] **Step 3: Implement**

Create `courses/management/commands/recolour_imported_content.py`:

```python
"""Restore the colour the LAL import dropped, matching on content, never on identity.

Dry-run by default. Run this LOCALLY, before the mat-pp -> prod export, so colour
ships inside the export bundle with no prod-side migration.

Take a dumpdata of the affected models before --apply: a transaction protects
against a PARTIAL write, not against a WRONG one.
"""

from collections import defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import transaction

from courses.lal_loader.builders import LoaderError
from courses.lal_loader.guards import resolve_course
from courses.recolour.dbscan import MultiOwnerError
from courses.recolour.dbscan import ReadBackError
from courses.recolour.dbscan import apply_matches
from courses.recolour.dbscan import excluded_node_ids
from courses.recolour.dbscan import find_matches
from courses.recolour.source import NOT_UNIT_JSON
from courses.recolour.source import build_key_map
from courses.recolour.source import walk_source

GATE_MIN_RATE = 0.70
# How many matches the dry run lists before truncating. The listing exists to
# discharge spec safety property 3; the cap keeps a 270-match run readable.
MATCH_PREVIEW = 40


class Command(BaseCommand):
    help = "Restore imported text colour in a course (dry-run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--course", required=True)
        parser.add_argument("--json-dir", default="scripts/lal_import/out")
        parser.add_argument(
            "--exclude",
            action="append",
            default=[],
            metavar="DIRNAME=PK",
            help=(
                "Exclude a part on BOTH sides: the out/ directory is not read and "
                "the paired node's subtree is filtered out of the candidates. "
                "Repeatable. An empty pk (DIRNAME=) excludes source-side only."
            ),
        )
        parser.add_argument("--apply", action="store_true")
        parser.add_argument(
            "--list-matches",
            action="store_true",
            help=(
                "List every matched field instead of the first "
                f"{MATCH_PREVIEW}. Use this to check for an ACCIDENTAL match: "
                "content-based matching (D6) will recolour author-written text "
                "that happens to be byte-identical to an imported key."
            ),
        )

    def handle(self, *args, **o):
        try:
            self._run(o)
        except (LoaderError, MultiOwnerError, ReadBackError) as e:
            raise CommandError(str(e)) from e

    # -- validation ---------------------------------------------------------

    def _validate_json_dir(self, json_dir):
        """Fail on a wrong --json-dir BEFORE any key work.

        Without this, a mistyped path yields zero occurrences, `producers == 0`, and
        the gate reports "key construction is broken" -- a confidently wrong
        diagnosis of an operator typo, which is exactly the misattribution this
        command works elsewhere to prevent.
        """
        root = Path(json_dir)
        if not root.is_dir():
            raise CommandError(f"--json-dir {json_dir!r} is not a directory")
        if not any(jf.name not in NOT_UNIT_JSON for jf in root.glob("*/*.json")):
            raise CommandError(
                f"--json-dir {json_dir!r} contains no <part>/<unit>.json files; "
                "this is a wrong path, not an empty corpus"
            )

    def _parse_exclusions(self, course, json_dir, raw_pairs):
        """([dirname], [node pk], [dirname reported as source-side only])."""
        from courses.models import ContentNode

        dirnames, pks, source_only = [], [], []
        for pair in raw_pairs:
            if "=" not in pair:
                raise CommandError(
                    f"--exclude {pair!r} must be given as dirname=pk (the pairing is "
                    "stated by the operator, never inferred)"
                )
            dirname, _sep, pk_text = pair.partition("=")
            dirname = dirname.strip()
            pk_text = pk_text.strip()
            if not (Path(json_dir) / dirname).is_dir():
                raise CommandError(
                    f"--exclude {pair!r}: no such part directory under {json_dir} "
                    "(a typo here silently disables the exclusion)"
                )
            dirnames.append(dirname)
            if not pk_text:
                source_only.append(dirname)
                continue
            try:
                pk = int(pk_text)
            except ValueError as e:
                raise CommandError(f"--exclude {pair!r}: pk must be an integer") from e
            node = ContentNode.objects.filter(pk=pk).first()
            if node is None:
                raise CommandError(f"--exclude {pair!r}: no ContentNode with pk {pk}")
            if node.course_id != course.pk:
                raise CommandError(
                    f"--exclude {pair!r}: node {pk} does not belong to course "
                    f"{course.slug!r}"
                )
            pks.append(pk)
        return dirnames, pks, source_only

    # -- run ----------------------------------------------------------------

    def _run(self, o):
        course = resolve_course(o["course"])
        json_dir = o["json_dir"]
        self._validate_json_dir(json_dir)
        dirnames, pks, source_only = self._parse_exclusions(
            course, json_dir, o["exclude"]
        )

        occurrences = walk_source(json_dir, excluded_dirs=dirnames)
        km = build_key_map(occurrences)
        excluded = excluded_node_ids(course, pks)
        matches = find_matches(course, km.entries, excluded)

        numerator, per_part = self._score(km, matches)
        self._report(o, km, matches, numerator, per_part, source_only)

        if numerator == 0 and self._already_applied(course, km, excluded):
            self.stdout.write(
                self.style.SUCCESS(
                    "already applied — every value is present in the database and no "
                    "key matches. Nothing to do."
                )
            )
            return

        self._check_gate(km, numerator, per_part)

        if not o["apply"]:
            self.stdout.write(
                self.style.WARNING(
                    "DRY RUN — nothing was written. Take a dumpdata of the affected "
                    "models, then re-run with --apply."
                )
            )
            return

        with transaction.atomic():
            changed = apply_matches(matches)
        self.stdout.write(self.style.SUCCESS(f"rewrote {changed} field(s)"))

    def _score(self, km, matches):
        """(numerator, per-part counters).

        The numerator counts OCCURRENCES, not distinct keys, and a form appearing in
        two parts must credit both. (Corpus-wide, BEFORE the D7 exclusion, the spec
        measures 257 distinct forms across 306 occurrences; after exclusion this
        command actually operates on 227 distinct keys across 265 occurrences, which
        is what its own report prints.) `km.produced` already excludes
        every occurrence whose value equalled its key, so the spec's `value != key`
        precondition is enforced here by construction -- which is what stops a
        span-only colouriser from scoring ~100% while delivering nothing.
        """
        matched_keys = {m.key for m in matches}
        per_part = defaultdict(
            lambda: {"producers": 0, "matched": 0, "emitted": 0, "rewritten": 0}
        )
        for part, stats in km.per_part.items():
            per_part[part]["producers"] = stats["producers"]
            per_part[part]["emitted"] = stats["emitted"]
        numerator = 0
        for occ, key in km.produced:
            if key in matched_keys:
                numerator += 1
                per_part[occ.part]["matched"] += 1
        # The spec asks for per-part REWRITTEN counts, and `matched` is not that: it
        # counts source occurrences, while a rewrite is one (model, pk, field). One
        # key can match several DB fields and one field can hold several matching
        # cells, so the two numbers legitimately differ.
        fields_by_key = defaultdict(set)
        for m in matches:
            fields_by_key[m.key].add((m.model.__name__, m.pk, m.field))
        # A key occurring in two source parts credits the same (model, pk, field) to
        # BOTH, so this column is "fields reachable from this part" and its sum can
        # exceed the reported total. On the measured run the two agree exactly (191),
        # which is why the overlap would first surface as an unexplained inconsistency
        # in some future report rather than now. Stated here so it is not a surprise.
        rewritten_by_part = defaultdict(set)
        for occ, key in km.produced:
            rewritten_by_part[occ.part] |= fields_by_key.get(key, set())
        for part, fields in rewritten_by_part.items():
            per_part[part]["rewritten"] = len(fields)
        return numerator, per_part

    def _already_applied(self, course, km, excluded):
        """True when the coloured VALUES are already in the database, at the same
        rate the gate demands of the keys.

        Without this the second run of an applied backfill halts on the gate, which
        reads as an error when it is in fact the intended no-op. But "at least one
        value is present" is too weak a predicate: after a hand-edit sweep that left
        one previously-applied value intact and destroyed every other match, it would
        report a clean no-op instead of halting. So the threshold reuses
        GATE_MIN_RATE, which a single survivor cannot satisfy.

        NOT symmetric with the gate, and the difference is worth stating: the gate's
        rate is matched OCCURRENCES over palette-bearing occurrences, while this one
        is distinct VALUES found over distinct values. On this corpus 227 distinct
        keys back 265 occurrences, so the denominators genuinely differ. The shared
        constant is a deliberate reuse of one threshold, not a claim that the two
        ratios measure the same thing.
        """
        if not km.entries:
            return False
        as_keys = {v: v for v in km.entries.values()}
        found = {m.key for m in find_matches(course, as_keys, excluded)}
        rate = len(found) / len(as_keys)
        self.stdout.write(
            f"values already present in the DB: {len(found)}/{len(as_keys)} "
            f"({rate:.1%})"
        )
        return rate >= GATE_MIN_RATE

    def _check_gate(self, km, numerator, per_part):
        if km.producers == 0:
            raise CommandError(
                "the source produced ZERO keys — key construction is broken, not the "
                "corpus. Halting."
            )
        rate = numerator / km.producers
        zero_parts = [
            p for p, s in sorted(per_part.items()) if s["producers"] and not s["matched"]
        ]
        problems = []
        if rate < GATE_MIN_RATE:
            problems.append(
                f"match rate {rate:.1%} is below the {GATE_MIN_RATE:.0%} gate"
            )
        if zero_parts:
            problems.append(
                "these parts produced keys but matched ZERO: " + ", ".join(zero_parts)
            )
        if problems:
            raise CommandError(
                "acceptance gate NOT met, halting without writing:\n  - "
                + "\n  - ".join(problems)
                + "\nA zero-matching part almost always means key construction is "
                "wrong for a field type; a broad shortfall means edits are more "
                "widespread than assumed."
            )

    # -- report -------------------------------------------------------------

    def _report(self, o, km, matches, numerator, per_part, source_only):
        w = self.stdout.write
        list_matches = o["list_matches"]
        w(f"course:        {o['course']}")
        w(f"json-dir:      {o['json_dir']}")
        for dirname in source_only:
            w(f"exclusion:     {dirname} — source-side only (no DB node paired)")
        w("")
        w(f"palette occurrences (denom):  {km.producers}")
        # NOT "produced a key": an occurrence skipped as value-equals-key DID produce
        # one and is excluded here, as is a conflict-retracted one. This counts what
        # entered the map and is therefore eligible for the numerator.
        w(f"  ...entering the key map:    {len(km.produced)}")
        w(f"distinct keys:                {len(km.entries)}")
        w(f"tc-* classes (distinct keys): {km.emitted}")
        w(f"tc-* classes (occurrences):   {km.emitted_occurrences}")
        w(f"matched occurrences:          {numerator}")
        if km.producers:
            w(f"match rate:                   {numerator / km.producers:.1%} "
              f"(gate: >= {GATE_MIN_RATE:.0%})")
        fields = {(m.model, m.pk, m.field) for m in matches}
        w(f"fields that would change:     {len(fields)}")
        w("")
        # Spec safety property 3 assigns the dry run a JOB: author-written content that
        # happens to be byte-identical to a key WILL be recoloured, because matching is
        # content-based by design (D6), and "the dry-run report is where an operator
        # spots it". A report of counts alone cannot discharge that -- nothing in it
        # names a row or shows the text -- so every match is listed, capped unless
        # --list-matches is passed.
        w("matches:")
        shown = sorted(matches, key=lambda m: (m.model.__name__, m.pk, m.field))
        cap = len(shown) if list_matches else MATCH_PREVIEW
        for m in shown[:cap]:
            cell = "" if m.cell is None else f"[{m.cell[0]}][{m.cell[1]}]"
            excerpt = m.key[:70].replace("\n", " ")
            w(f"  {m.model.__name__}({m.pk}).{m.field}{cell}  <- {excerpt!r}")
        if len(shown) > cap:
            w(f"  ... and {len(shown) - cap} more; pass --list-matches for all")
        w("")
        w("per part:")
        # 'occ' not 'keys': this column is per-part OCCURRENCES (km.producers), which
        # sums to the denominator, NOT to the distinct-key total printed above.
        w(f"  {'part':38s} {'occ':>6s} {'matched':>8s} {'fields':>7s} {'tc-*':>6s}")
        for part, s in sorted(per_part.items()):
            flag = "   <== ZERO" if s["producers"] and not s["matched"] else ""
            w(f"  {part:38s} {s['producers']:6d} {s['matched']:8d} "
              f"{s['rewritten']:7d} {s['emitted']:6d}{flag}")
        w("")
        # The spec asks for per-part skip counts; this is a global histogram plus a
        # sample of the first ten, and the divergence is deliberate: the measured skip
        # count on the real corpus is ZERO, so a per-part breakdown would be an empty
        # column on every row. Each skip line names its part, so the information is
        # recoverable if a run ever produces one. Revisit if skips stop being rare.
        reasons = defaultdict(int)
        for _occ, reason in km.skips:
            reasons[reason.split(":")[0]] += 1
        if reasons:
            w("skipped:")
            for reason, n in sorted(reasons.items()):
                w(f"  {reason:24s} {n}")
            for occ, reason in km.skips[:10]:
                name = Path(occ.json_file).name
                w(f"    {occ.part}/{name} {occ.field_path} — {reason}")
        w("")
```

**Method order.** `_score`, `_already_applied`, `_check_gate` and `_report` are all
defined above; `handle` and `_run` come first in the file. Keep that order — it reads
top-down from the entry point.

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/test_recolour_command.py -q
```

Expected: 16 passed.

- [ ] **Step 5: Falsify — prove the gate and the exclusion validation are real**

Falsify the gate **itself**, not the constant it shares. `_check_gate` has TWO
independent halting conditions and they overlap, so which tests go RED depends on
which you remove. All three sets below were MEASURED — do the first two in order:

| mutation | expected RED |
|---|---|
| delete the `if rate < GATE_MIN_RATE:` branch only | **1**: `test_a_region_refusal_is_named_AND_counts_against_the_gate` |
| delete the `if zero_parts:` branch only | **none** — see below |
| delete **both** branches | **3**: the above plus `test_an_edited_element_is_skipped` and `test_the_exclusion_protects_hand_edited_content_that_matches_a_key` |

**A single-branch deletion leaving everything green is the correct result, not a
vacuous test.** The two zero-match tests trip *both* conditions at once (rate 0% AND
a part that produced keys but matched zero), so either surviving branch still halts
the run. Only the region-refusal test isolates the rate branch, because at 50% its
part did match one occurrence and `zero_parts` is therefore empty. Run the
delete-both mutation to see those two go RED. Restore after each.

**Do NOT falsify by setting `GATE_MIN_RATE = 0.0`.** MEASURED: that reds three tests,
and two of them for the WRONG reason — `_already_applied` reuses the same constant, so
at 0.0 it returns True and the command exits 0 with "already applied" before
`_check_gate` is ever reached. The mutation would falsify the shared constant rather
than the gate, and tell you nothing about the branch you meant to test.

Then delete the `if not (Path(json_dir) / dirname).is_dir():` check and re-run —
expected RED on `test_a_dirname_absent_from_out_is_an_error`. Restore, confirm 16 passed.

Paste both RED outputs.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff format .
uv run ruff check .
git rev-parse --show-toplevel
git branch --show-current
git add courses/management/commands/recolour_imported_content.py tests/test_recolour_command.py
git commit -m "feat(recolour): recolour_imported_content management command"
```
- [ ] **Step L: Record the task in the ledger**

Append to `.superpowers/sdd/progress.md` under `## Tasks`:

```markdown
Task 7: complete (commit <sha>)
  - branch guard: <toplevel> / <branch>
  - <N> passed; falsification RED on <test names>, restored
  - anything surprising, and any decision you had to make that the plan did not cover
```

The ledger is untracked, so this is a file write with **no commit**. It is not
bookkeeping: it is the only record a resumed session has of which tasks are genuinely
done, which is the entire reason Task 0 archives slice 1's ledger rather than appending
to it. Git history shows that a commit happened; the ledger is where you say what was
verified and what surprised you.


---

### Task 8: Whole-branch verification and the real dry run

**Files:** none changed except `.superpowers/sdd/progress.md`.

**Interfaces:**
- Consumes: everything.
- Produces: the recorded gate verdict from the **real command against the real database**
  — the number Task 9 is authorised (or not) by.

- [ ] **Step 1: Lint the committed tree**

```bash
uv run ruff format .
uv run ruff check .
git status --porcelain
```

Expected: `All checks passed!` and an empty status. If `ruff format` changed a file, commit
that change and re-run `check` — slice 1 shipped a lint failure on the committed tree
because check ran before format.

- [ ] **Step 2: Run the full non-e2e suite on a FRESH database**

```bash
uv run pytest --create-db -n 4 -q
```

**That is the whole command — run it once.** `-n 4` (xdist, as CI does) is not optional:
a freshly created database running ~4,500 tests sequentially is the slowest
configuration available and the foreground call has a 10-minute ceiling, so the
sequential form would most likely time out and read as a suite failure. Do **not** pass
`--reuse-db`, do **not** background it, and do not run a second invocation alongside it.

Expected: 0 failed and **~4546 passed**. MEASURED by collection on this branch: the
non-e2e suite is **4462** without this slice's files. The tests this plan adds are exactly the six
per-task `Expected: N passed` lines — re-derive the total from them rather than
trusting this sentence: 16 (Task 2) + 12 (Task 3) + 12 (Task 4) + 15 (Task 5) +
13 (Task 6) + 16 (Task 7) = **84**. So 4462 + 84 = **4546**.

**Check the delta, not the absolute number, in BOTH directions.** ~4462 here would mean
all 84 new tests failed to collect — which reads as success and is the opposite. A
count materially *above* 4546 means tests were added that this plan did not specify;
find them before continuing. If the count is short, run the six new files by name and
compare against their stated counts.

If you see ~21 failures with brand-colour/tokens.css or cohort/grouping names, you
used a reused DB — re-run with `--create-db`.

This slice touches `courses/sanitize.py` and `courses/switchgrid.py`, which the whole app
uses, so the full suite is the real check here — not just the five new files.

- [ ] **Step 3: The e2e suite**

```bash
uv run pytest -m e2e -n 4 -q
```

**No path argument at all.** MEASURED collection counts on this branch:

| selector | collected |
|---|---|
| `tests/test_e2e_*.py -m e2e` | 461 — misses 104 |
| `tests/ -m e2e` | 562 — still misses the 3 in `notifications/tests/` |
| `-m e2e` | **565** |

`pytest.mark.e2e` is applied in four `tests/` files that do not match `test_e2e_*.py`
(`test_link_apply.py`, `test_link_dialog_behaviour.py`, `test_table_grid_algebra.py`,
`test_tabs_editor_dnd.py`) **and** in three files under `notifications/tests/`. Step 2's
`addopts = -m 'not e2e'` deselects all of them there, so any path-scoped selector here
runs them in neither step — on a slice that modifies `courses/sanitize.py` and
`courses/switchgrid.py`, which the editor paths those files drive.

`-m e2e` is mandatory or every Playwright test is silently deselected and pytest exits 5,
which looks like success. `-n 4` (xdist, as CI runs it) is needed because the full e2e
suite exceeds the 10-minute per-call ceiling sequentially. **Expected: 565 collected,
0 failed.** Record the collected count in the ledger — a future glob/marker drift is
invisible unless the number is written down.

Slice 2 changes no JS, CSS or template, so a regression here would be surprising — say so
explicitly in your report if one appears rather than assuming it is pre-existing.

- [ ] **Step 4a: Re-verify the two exclusion pks FIRST**

A node may have been deleted or restructured since this plan was written, and every
number Step 4b produces — the per-part table, the gate rate, `fields that would
change` — is computed against whatever exclusion you pass. Getting this wrong does not
fail loudly; it silently measures the wrong thing, and Task 9 Step 1b then tells the
operator to reuse "the pks you validated in Task 8 Step 4a".

```bash
DATABASE_URL="postgres://libli:libli@localhost:5432/libli" uv run python -c "
import os, sys, django
sys.path.insert(0, os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.local'); django.setup()
from courses.models import ContentNode, Course
c = Course.objects.get(slug='mat-pp')
for n in ContentNode.objects.filter(course=c, parent=None).order_by('order')[:2]:
    print(n.pk, n.order, n.title)
"
```

Expected: `109 0 Zbiory liczbowe` and `153 1 Elementy logiki`. **If the pks differ, use
what you measure — never what this plan says** — and write the measured pair into the
ledger, because Task 9 reads it from there.

- [ ] **Step 4b: The real dry run**

Substitute the pks confirmed in Step 4a.

```bash
PYTHONUTF8=1 DATABASE_URL="postgres://libli:libli@localhost:5432/libli" \
  uv run python manage.py recolour_imported_content \
  --course mat-pp \
  --exclude 001_zbiory_liczbowe=<PK1> \
  --exclude 002_elementy_logiki=<PK2>
```

The `DATABASE_URL` prefix is mandatory — `mat-pp` is not in `libli_blcp`.

**`PYTHONUTF8=1` matters for the REPORT, not just for `dumpdata`.** MEASURED on this
machine: without it stdout falls back to the locale codec and Polish text comes back as
`Wyra?enia algebraiczne` instead of `Wyrażenia algebraiczne`. Nothing crashes — which is
the problem. Step 5 asks you to read the matched keys and judge whether any looks like
hand-authored text, and that judgement is being made on strings whose diacritics have
been destroyed.

- [ ] **Step 5: Read the result against the gate, and against Task 1**

- **MEASURED while this plan was written: 265 palette occurrences, 265 matched,
  100.0%, 227 distinct keys, 191 fields would change.** The gate floor is ≥ 70% and no
  eligible part showing `<== ZERO`, but a run at, say, 71% would clear that floor while
  being a large undiagnosed regression from what was actually measured. Treat anything
  materially below 100% as a shortfall to explain, not a pass. The floor exists for the
  case where the corpus or the database has genuinely moved on; it is not the
  expectation.
- Compare `occurrences producing a key` and the per-part table against **Task 1's spike**.
  They should agree closely. A large divergence means the production walk and the spike
  disagree about scope — diagnose before Task 9, because one of them is wrong.
- Compare **`tc-* classes (occurrences)`** — not the distinct-key figure — against the
  spec's source-side expectation, which is stated per occurrence: the corpus holds 588
  palette-coloured elements, 29 of them in the two excluded parts, so **~559** is
  expected, and the residual handful are the SwitchGrid line stems that are out of
  backfill scope. MEASURED while this plan was written: **557 occurrences / 500 distinct
  keys**. A figure near **446** means the non-span carriers are being dropped — the exact
  failure the `value != key` clause exists to expose. Reading the distinct-key figure
  against the ~559 expectation gives no verdict at either end, which is why both counts
  are printed.
- `value-equals-key` in the skip list must be **0**. Any non-zero count is the span-only
  no-op shape and must be diagnosed, not accepted.
- `protected-region` is expected to be **0** (measured: zero contaminated maths spans
  across all 697 colour-bearing elements). A non-zero count is not necessarily a bug —
  the guard is doing its job — but report each one.
- **Read the `matches:` listing for accidental matches. This is the step where spec
  safety property 3 is actually discharged, and it needs a human judgement, not a
  threshold.** Matching is content-based by design (D6), so author-written text that
  happens to be byte-identical to an imported key WILL be recoloured. MEASURED on the
  real database, so you know what normal looks like:

  | | measured |
  |---|---|
  | matches | 270 |
  | distinct keys matched | 227 |
  | keys matching MORE than one field | 28 (43 extra fields) |
  | matched keys ≤ 25 characters | 72 of 227 |

  Multi-field matching is **expected and correct** — the same imported form recurs
  across units and the spec measured 0 conflicting colourings — so a key hitting five
  fields is not by itself a problem. `<strong>Uwaga!</strong>` ("Note!") matches 5,
  `<strong>TAK </strong>` / `<strong>NIE </strong>` match 4 each.

  What deserves a look is the **short generic** end: the matched set includes
  three-letter geometry labels (`EBD`, `ACE`, `DAB`, …) and single letters
  (`<strong>P</strong>`, `<strong>B</strong>`). Those are the shapes an author could
  plausibly have typed by hand in a unit written since the import, and recolouring one
  is a silent, if cosmetic, edit to content nobody asked you to touch. Run
  `--list-matches`, skim the short keys, and if any names a unit you know was authored
  after the import, say so in the ledger before Task 9. Nothing automated can make this
  call — that is precisely why the spec assigns it to the dry run and to a person.
  Re-run with `--list-matches` (keeping the `PYTHONUTF8=1` prefix, or the Polish you are
  judging arrives with its diacritics stripped):

  ```bash
  PYTHONUTF8=1 DATABASE_URL="postgres://libli:libli@localhost:5432/libli" \
    uv run python manage.py recolour_imported_content \
    --course mat-pp \
    --exclude 001_zbiory_liczbowe=<PK1> \
    --exclude 002_elementy_logiki=<PK2> \
    --list-matches
  ```

**If the gate fails, STOP.** Do not proceed to Task 9. Report the numbers and your
diagnosis.

- [ ] **Step 6: Record everything in the ledger and commit**

Append the suite counts, the full dry-run report and your reading of it to
`.superpowers/sdd/progress.md`. The ledger is untracked, so **there is no commit in
this task**; verify instead that the branch is where it should be and the tree is
clean:

```bash
git rev-parse --show-toplevel
git branch --show-current
git status --porcelain   # expected: EMPTY
```

---

### Task 9: The local apply

**This task mutates real local data. Do not start it without the user's explicit
go-ahead**, reported by the controller. Task 8's dry run must have met the gate.

**Every command in this task carries `PYTHONUTF8=1`, and it is not cosmetic.** MEASURED
on this machine: `sys.stdout.encoding` is `cp1250`, and printing a character outside it
raises `UnicodeEncodeError` and **exits 1** — it aborts, it does not degrade. MEASURED
against the real database: 16 `mat-pp` `TextElement.body` values and 3 `TableElement.data`
values contain characters cp1250 cannot encode (`² ▻ ☑ ✔ 🡆 ♠ ✓ ❌`), and one of them is
among the 265 palette-bearing occurrences. Step 5's node-finder samples 5 arbitrary
`tc-`-bearing bodies, so it can abort before writing `shot.json`; the report's 40-match
preview happens to sort safe rows first *today*, which is luck, not design. An abort at
the irreversible step is the wrong place to rediscover this.

**Files:** none changed except `.superpowers/sdd/progress.md`.

- [ ] **Step 1: Take the backup — and prove it is a real one**

```bash
PYTHONUTF8=1 DATABASE_URL="postgres://libli:libli@localhost:5432/libli" \
  uv run python manage.py dumpdata courses --indent 2 \
  -o "<scratchpad>/mat-pp-before-recolour.json"
echo "exit=$?"
ls -l "<scratchpad>/mat-pp-before-recolour.json"
git status --porcelain          # expected: EMPTY -- the dump is outside the repo
```

**`PYTHONUTF8=1` is mandatory, and this is the step where a missing flag costs you the
course.** MEASURED on this machine: without it, `dumpdata` dies with

```
CommandError: Unable to serialize database: 'charmap' codec can't encode
character '▷' in position 2075
```

— Django opens the `-o` file with the locale encoding (cp1250 here) and mat-pp content
contains `▷`. It fails **after** creating the file, leaving a **661-byte truncated stub**.
A "confirm the file is non-empty" check passes on that stub, and you would then run
`--apply` against real data with no way back. With the flag: exit 0 and **11,669,475
bytes**.

So the pass condition is not "non-empty". Verify the dump actually round-trips:

```bash
PYTHONUTF8=1 DATABASE_URL="postgres://libli:libli@localhost:5432/libli" uv run python -c "
import json, os, sys, django
sys.path.insert(0, os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.local'); django.setup()
from courses.models import ContentNode, TextElement
rows = json.load(open(r'<scratchpad>/mat-pp-before-recolour.json', encoding='utf-8'))
kinds = {}
for r in rows: kinds[r['model']] = kinds.get(r['model'], 0) + 1
print('objects in dump:', len(rows))
print('contentnode  dump/db:', kinds.get('courses.contentnode'), ContentNode.objects.count())
print('textelement  dump/db:', kinds.get('courses.textelement'), TextElement.objects.count())
assert kinds.get('courses.contentnode') == ContentNode.objects.count()
assert kinds.get('courses.textelement') == TextElement.objects.count()
print('BACKUP OK')
"
```

Expected: `BACKUP OK`, a dump of roughly 11–12 MB, and the two counts matching. A
`json.load` failure or a count mismatch means the dump is truncated — do not proceed.

**Substitute your real scratchpad path into every occurrence — do not introduce a shell
variable for it.** Two independent reasons a `DUMP=…` variable does not work here:
a bare assignment is not exported to a child process, AND — decisively — **shell state
does not persist between Bash tool calls in this harness**, so even an exported variable
is gone by the next fence. The literal path is what survives. (Task 9 Step 5 relies on
the same fact when it hands values between scripts through a JSON file rather than
through the environment.)

**The restore command, written down before it is needed** (a recovery path that has never
been written down is not a recovery path). To roll back:

```bash
PYTHONUTF8=1 DATABASE_URL="postgres://libli:libli@localhost:5432/libli" \
  uv run python manage.py loaddata "<scratchpad>/mat-pp-before-recolour.json"
```

`loaddata` upserts by primary key: it restores every row the dump contains and does **not**
delete rows created afterwards. That is exactly right here — this backfill only ever
UPDATEs existing rows, so a restore returns every one of them to its pre-apply value.

The dump goes to your **scratchpad**, outside the repo tree. MEASURED: `tmp/` is **not**
in `.gitignore` (`git check-ignore -v tmp/x.json` reports NOT IGNORED), so writing it
there would leave a multi-megabyte untracked file that contradicts this task's own
`git status --porcelain # expected: EMPTY` check in Step 6 — and invite someone to
`git add` it.

A transaction protects against a partial write, not against a wrong one. **Record the
dump's path in the ledger.**

- [ ] **Step 1b: Capture the before-state**

These numbers are the baseline Step 3 compares against, and once you have applied they are
unrecoverable — so capture them **now**, before Step 2. Use the pks you validated in Task
8 Step 4a; do not reuse this plan's `109`/`153` if Task 8 measured anything else.

```bash
DATABASE_URL="postgres://libli:libli@localhost:5432/libli" uv run python -c "
import os, sys, django
sys.path.insert(0, os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.local'); django.setup()
from courses.models import Course, ContentNode, TextElement, TableElement, ChoiceQuestionElement
c = Course.objects.get(slug='mat-pp')
print('NODE_COUNT_BEFORE =', ContentNode.objects.filter(course=c).count())
print('TEXT_TC_BEFORE    =', TextElement.objects.filter(
    elements__unit__course=c, body__contains='tc-').count())
print('TABLE_TC_BEFORE   =', TableElement.objects.filter(
    elements__unit__course=c, data__icontains='tc-').count())
print('CHOICE_TC_BEFORE  =', ChoiceQuestionElement.objects.filter(
    elements__unit__course=c, stem__contains='tc-').count())
excluded = set()
for pk in (<PK1>, <PK2>):
    excluded |= set(ContentNode.objects.get(pk=pk)._subtree_node_ids())
print('LEAK_TEXT_BEFORE  =', TextElement.objects.filter(
    elements__unit_id__in=excluded, body__contains='tc-').count())
print('LEAK_TABLE_BEFORE =', TableElement.objects.filter(
    elements__unit_id__in=excluded, data__icontains='tc-').count())
"
```

Write all six numbers into the ledger. MEASURED on the un-backfilled database,
`LEAK_TABLE_BEFORE` is already **1** — so the leak checks in Step 3 must be
before/after **deltas**, never `== 0`.

- [ ] **Step 2: Apply**

Substitute the pks validated in Task 8 Step 4a — **this is the only irreversible step in
the plan, and the only one where a wrong pk causes real damage**: it would recolour the
hand-edited content D7 exists to protect. Do not paste this block with the literals
below; every other step that names them uses placeholders for exactly this reason.

```bash
PYTHONUTF8=1 DATABASE_URL="postgres://libli:libli@localhost:5432/libli" \
  uv run python manage.py recolour_imported_content \
  --course mat-pp \
  --exclude 001_zbiory_liczbowe=<PK1> \
  --exclude 002_elementy_logiki=<PK2> \
  --apply
```

Expected: the same report as Task 8, then `rewrote N field(s)` — **191 on the measured
run**. The read-back runs inside the transaction, so a `ReadBackError` rolls everything
back and nothing is written.

- [ ] **Step 3: Verify the write took effect, and that nothing else moved**

Substitute the six numbers captured in Step 1b and the pks validated in Task 8 Step 4a.

```bash
DATABASE_URL="postgres://libli:libli@localhost:5432/libli" uv run python -c "
import os, sys, django
sys.path.insert(0, os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.local'); django.setup()
from courses.models import Course, ContentNode, TextElement, TableElement, ChoiceQuestionElement
PK1, PK2 = <PK1>, <PK2>
NODE_COUNT_BEFORE = <NODE_COUNT_BEFORE>
TEXT_TC_BEFORE, TABLE_TC_BEFORE, CHOICE_TC_BEFORE = <TEXT_TC_BEFORE>, <TABLE_TC_BEFORE>, <CHOICE_TC_BEFORE>
LEAK_TEXT_BEFORE, LEAK_TABLE_BEFORE = <LEAK_TEXT_BEFORE>, <LEAK_TABLE_BEFORE>
c = Course.objects.get(slug='mat-pp')
n = TextElement.objects.filter(elements__unit__course=c, body__contains='tc-').count()
t = TableElement.objects.filter(elements__unit__course=c, data__icontains='tc-').count()
q = ChoiceQuestionElement.objects.filter(elements__unit__course=c, stem__contains='tc-').count()
print('TextElement   before/after:', TEXT_TC_BEFORE, n)
print('TableElement  before/after:', TABLE_TC_BEFORE, t)
print('ChoiceElement before/after:', CHOICE_TC_BEFORE, q)
assert n > TEXT_TC_BEFORE,   'the rich-text path wrote nothing'
assert t > TABLE_TC_BEFORE,  'the CELL path wrote nothing'
assert q > CHOICE_TC_BEFORE, 'the question-stem path wrote nothing'
excluded = set()
for pk in (PK1, PK2):
    excluded |= set(ContentNode.objects.get(pk=pk)._subtree_node_ids())
lt = TextElement.objects.filter(elements__unit_id__in=excluded, body__contains='tc-').count()
lb = TableElement.objects.filter(elements__unit_id__in=excluded, data__icontains='tc-').count()
print('LEAK text  before/after (must be EQUAL):', LEAK_TEXT_BEFORE, lt)
print('LEAK table before/after (must be EQUAL):', LEAK_TABLE_BEFORE, lb)
assert lt == LEAK_TEXT_BEFORE and lb == LEAK_TABLE_BEFORE, 'wrote into an EXCLUDED part'
after = ContentNode.objects.filter(course=c).count()
print('nodes before/after (must match):', NODE_COUNT_BEFORE, after)
assert after == NODE_COUNT_BEFORE
"
```

All three write paths are checked, because the measured write distribution is
`TextElement.body` 184, `TableElement` cells 84 (across 5 rows) and
`ChoiceQuestionElement.stem` 2 — a run that silently covered only the first would still
show a large `TextElement` increase.

**The leak check is a DELTA, and its limits are worth stating plainly.** Two reasons it is
not the proof it looks like:

- MEASURED: one `TableElement` inside part 153 **already** carries `tc-`, so a `== 0`
  assertion would fail on a correct run. Hence before/after equality.
- MEASURED: `find_matches` returns **270 matches with the exclusion and 270 without it**
  — no key built from an eligible part matches anything inside the 109/153 subtrees, so
  the DB-side exclusion protects **zero rows on today's data**. An unchanged leak count is
  therefore consistent with `excluded_node_ids` being completely broken. This check
  confirms nothing regressed; it does **not** demonstrate the exclusion works. The tests
  in Task 6 (`test_an_excluded_subtree_is_filtered_out`) and Task 7
  (`test_the_exclusion_protects_hand_edited_content_that_matches_a_key`) are what
  demonstrate that, on data constructed to make it matter.

This is the same honesty the plan applies to the region guard, where measured overlap is
zero "by exclusion, not by the guard" — a future 0 here must not be read as proof either.

A changed leak count means the exclusion failed: **restore using the Step 1 command** and
stop.

- [ ] **Step 4: Re-run and confirm the no-op**

```bash
PYTHONUTF8=1 DATABASE_URL="postgres://libli:libli@localhost:5432/libli" \
  uv run python manage.py recolour_imported_content --course mat-pp \
  --exclude 001_zbiory_liczbowe=<PK1> --exclude 002_elementy_logiki=<PK2>
```

Expected: `already applied — … Nothing to do.` and exit 0.

- [ ] **Step 5: Look at it — light and dark, judged separately**

The sentence the spec quotes (`jeśli ( założenie ) to ( teza )`) lives in
`002_elementy_logiki`, which is **excluded**, so any node that actually changed will do;
`130_kombinatoryka` holds 51% of the corpus colour and is the likeliest to be picked.

**Before starting, confirm `DEBUG` is on.** The whole point of this step is judging colour,
which needs `courses.css`. Under `DEBUG=false` `runserver` serves no static files without
`--insecure`, and the two PNGs would come out unstyled — a failure that reads as "the
palette is wrong" rather than "static is missing":

```bash
grep DJANGO_DEBUG .env          # expected: DJANGO_DEBUG=true
```

First find a node that actually changed, and create the throwaway user, in one go. Write
the results to the scratchpad — the capture script reads them from there, because **shell
variables do not survive between Bash tool calls in this harness**:

```bash
PYTHONUTF8=1 DATABASE_URL="postgres://libli:libli@localhost:5432/libli" uv run python -c "
import os, sys, json, secrets, django
sys.path.insert(0, os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.local'); django.setup()
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from accounts.emails import ensure_verified_primary_email
from courses.models import Course, Element, TextElement
c = Course.objects.get(slug='mat-pp')
# content_type is MANDATORY here. Element is a generic-FK join row, so object_id alone
# is ambiguous across models. MEASURED on this database: for 35 of 50 TextElement pks,
# a .filter(object_id=pk).first() returns a row belonging to a DIFFERENT model -- the
# printed node would then be a unit with no recoloured body, and its screenshot would
# read as 'the apply did not work' at the exact step meant to confirm that it did.
ct = ContentType.objects.get_for_model(TextElement)
out = []
for r in TextElement.objects.filter(elements__unit__course=c, body__contains='tc-')[:5]:
    el = Element.objects.filter(content_type=ct, object_id=r.pk, unit__course=c).first()
    if el:
        out.append(el.unit_id)
        print('node pk', el.unit_id, '-> /courses/n/%d/' % el.unit_id)
        print('   ', r.body[:120])
U = get_user_model()
pw = secrets.token_urlsafe(16)
u, _ = U.objects.get_or_create(username='recolour-check')
u.is_staff = u.is_superuser = True; u.set_password(pw); u.save()
# MANDATORY, and not obvious: config/settings/base.py:103 sets
# ACCOUNT_EMAIL_VERIFICATION = 'mandatory', so a user with no VERIFIED allauth
# EmailAddress cannot log in at all. MEASURED: posting correct credentials for a bare
# user redirects to /accounts/confirm-email/ and leaves is_authenticated False -- the
# screenshots would then capture the login page, i.e. this step would manufacture
# 'the apply did not work' evidence. This is why the repo's own e2e helpers use
# tests.factories.make_verified_user rather than a bare user.
ensure_verified_primary_email(u, 'recolour-check@example.invalid')
json.dump({'node': out[0], 'user': 'recolour-check', 'pw': pw},
          open(r'<scratchpad>/shot.json', 'w'))
print('wrote <scratchpad>/shot.json')
"
```

Substitute your real scratchpad path literally, here and in the capture script below. Do
**not** introduce a `SHOTDIR` variable: shell state does not persist between Bash tool
calls in this harness — which is the very reason `node`/`user`/`pw` are handed over through
`shot.json` rather than through the environment. A variable holding the path to that file
would be lost at exactly the boundary the file exists to cross.

Start the server. `runserver` blocks forever, so it goes in the **background** — that is
consistent with the Global Constraint, which forbids backgrounding *test runs*, not
servers. `--noreload` matters: without it `runserver` forks an autoreloader child and
killing the parent leaves the worker holding the port.

```bash
DATABASE_URL="postgres://libli:libli@localhost:5432/libli" \
  uv run python manage.py runserver 8009 --noreload
```

Run that with the Bash tool's `run_in_background` option, and note the returned task id —
that, not a `$!` shell variable, is how you stop it later. MEASURED: a plain `kill` on the
shell job leaves the `uv`-spawned python grandchild still bound to the port; stopping the
background task does free it.

Confirm static is actually being served before spending a screenshot on it:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8009/static/courses/css/courses.css
```

Expected: `200`. Anything else means the screenshots would be unstyled.

Now capture both themes. This repo has no screenshot helper outside the pytest e2e
harness, and that harness does not drive an external `runserver`, so the script is given
here in full rather than left as prose. It logs in through the real form (CSRF-aware),
flips `user.theme` between shots — **not** the cookie, a recorded trap in this repo — and
writes two PNGs:

```bash
DJANGO_ALLOW_ASYNC_UNSAFE=true PYTHONUTF8=1 \
  DATABASE_URL="postgres://libli:libli@localhost:5432/libli" uv run python -c "
import os, sys, json, django
sys.path.insert(0, os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.local'); django.setup()
from django.contrib.auth import get_user_model
from playwright.sync_api import sync_playwright
cfg = json.load(open(r'<scratchpad>/shot.json'))
U = get_user_model()
base = 'http://127.0.0.1:8009'
with sync_playwright() as pw:
    b = pw.chromium.launch()
    for theme in ('light', 'dark'):
        # DJANGO_ALLOW_ASYNC_UNSAFE=true on the command line above is MANDATORY for
        # exactly this line. Playwright's sync API runs user code inside a greenlet with
        # a live asyncio loop in the same thread, so Django's @async_unsafe guard on
        # connection.cursor() fires and this raises SynchronousOnlyOperation on the FIRST
        # iteration, before any screenshot. MEASURED. Every Playwright caller in this repo
        # sets it -- see tests/capture_help_screenshots.py:33, the closest existing
        # analogue to this script. Do not remove it as noise.
        u = U.objects.get(username=cfg['user']); u.theme = theme
        u.save(update_fields=['theme'])
        page = b.new_page(viewport={'width': 1280, 'height': 900})
        # Selectors copied from the repo's proven helper (tests/test_e2e_builder.py:35-42,
        # tests/test_e2e_auth.py). TWO measured gotchas, both of which this repo has
        # already paid for: login is allauth (config/urls.py:31), so the field is
        # name='login' NOT name='username'; and an UNSCOPED button[type=submit] clicks
        # the header language-switch form first. Scope to the login form and reuse the
        # known-good pattern rather than guessing.
        page.goto(base + '/accounts/login/')
        form = page.locator("form[action*='login']")
        form.locator("input[name='login']").fill(cfg['user'])
        form.locator("input[name='password']").fill(cfg['pw'])
        form.locator("button[type='submit']").click()
        page.wait_for_load_state('networkidle')
        # Fail LOUDLY rather than screenshotting a login page. An unauthenticated
        # /courses/n/<pk>/ 302s to login, so without this assertion an auth
        # regression produces a perfectly valid PNG of the wrong thing -- and this
        # step's entire job is deciding whether the apply worked.
        assert '/accounts/' not in page.url, 'login failed, still at ' + page.url
        page.goto(base + '/courses/n/%d/' % cfg['node'])
        page.wait_for_load_state('networkidle')
        path = r'<scratchpad>/recolour-%s.png' % theme
        page.screenshot(path=path, full_page=True)
        print('wrote', path)
        page.close()
    b.close()
"
```

If the assertion above fires, or a screenshot shows a login form, the two MEASURED
causes are, in order of likelihood:

1. the throwaway user has no **verified** allauth `EmailAddress` — the
   `ensure_verified_primary_email` call was skipped or failed;
2. `DJANGO_ALLOW_ASYNC_UNSAFE=true` is missing, so the script died at the first ORM
   call before reaching the browser at all.

The selectors themselves were verified against the live login page and are exact —
`templates/account/login.html` renders one `input[name='login']`, one
`input[name='password']` and exactly one `button[type='submit']` inside
`form[action*='login']` — so audit them last, not first.

**This whole recipe was rehearsed end-to-end against the TEST database while this plan was
written**, on a synthetic unit carrying the spec's own example sentence
(`jeśli ( założenie ) to ( teza )`). It works: the server binds, static returns 200, the
login assertion passes, both PNGs are written styled, and `getComputedStyle` on the
`.tc-red` span returns `rgb(178, 55, 42)` in light and `rgb(234, 138, 130)` in dark —
exactly the `--tc-red` values from the spec's palette table. **So a failure here is a
signal about the DATA, not about the recipe.**

**Judge the two separately; never infer dark from light.** Confirm the prose colour and any
adjacent `\color{…}` maths now resolve to the same palette, and that nothing else on the
page shifted.

Stop the server with the Bash tool's task-stop on the background task id from above. Then
confirm the port is free:

```bash
curl -s -o /dev/null http://127.0.0.1:8009/ \
  && echo "SERVER STILL UP -- stop the background task before re-running this step" \
  || echo "port free"
```

An orphaned server on 8009 makes any re-run of this step fail with "Address already in
use", which is why the teardown does not rely on shell state.

Delete the throwaway account — this task's whole discipline is "prove nothing else
moved", and a permanent superuser is exactly the kind of residue Step 3's invariants
cannot see and the Step 1 `dumpdata courses` backup cannot remove:

```bash
DATABASE_URL="postgres://libli:libli@localhost:5432/libli" uv run python -c "
import os, sys, django
sys.path.insert(0, os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.local'); django.setup()
from django.contrib.auth import get_user_model
n, _ = get_user_model().objects.filter(username='recolour-check').delete()
print('deleted throwaway user rows:', n)
"
```

Report what you saw, and attach both screenshots. If it looks wrong, the Step 1 restore
command is the way back.

- [ ] **Step 6: Record and commit the ledger**

Append the applied counts and your visual verdict to `.superpowers/sdd/progress.md`.
The ledger is untracked, so **there is no commit in this task** either:

```bash
git rev-parse --show-toplevel
git branch --show-current
git status --porcelain   # expected: EMPTY
```

**Do not push and do not open a PR** — that is outward-facing and the user's call. Report
to the controller that the branch is ready.

---

## Self-review against the spec

| Spec requirement | Task |
|---|---|
| Backfill command CLI, `--course` slug via `resolve_course` | 7 |
| Key = pre-slice-1 sanitiser replay, frozen `LEGACY_*` | 4 |
| Key unwraps EVERY span, not only coloured ones | 2 (`strip_spans`), 4 (`key_for`) |
| Value unwraps non-`tc-*` spans too | 2 (`colourise`) |
| Per-carrier value rule (span / `TC_CLASS_TAGS` / block) | 2 |
| Full import write path replayed in order, incl. the composed `fillblank` stem | 4 |
| D8/D10 region test applied to source values; sentinel not `{{…}}` | 3 |
| Acceptance gate: ≥70%, no zero-matching part, `value != key`, `tc-*` emitted count, matched-but-unchanged as a named skip | 1 (spike), 5 (`SKIP_UNCHANGED`), 7 (gate), 8 (real run) |
| Matching contract: HTML whole-field; JSON cells per cell, partial rewrite, one changed field | 6 |
| Read back every rewritten field (the gate stems have no save-time net) | 6 |
| Safety: titles untouchable; renames/reorders irrelevant; edited content skipped; conflicting key refused | 6, 5, 7 |
| Safety 3's converse — an ACCIDENTAL match is spotted in the dry-run report | 7 (`_report`'s per-match listing + `--list-matches`) |
| Exclusion paired `<dirname>=<pk>`; validation; empty pk; repeatable; descendant walk; base filter; fail closed on multi-owner | 6, 7 |
| `--apply` writes with `update_fields` | 6 (`apply_matches`) |
| Dry-run default; `--apply` in a transaction; dumpdata first; re-run no-ops | 7, 9 |
| Run locally before the mat-pp → prod export | 9 |
| Falsification of every test | every task's falsify step |

**Two deliberate divergences from the spec**, recorded here because the table above
otherwise reads as unqualified coverage:

1. **Gate denominator.** The spec defines it as occurrences that *produce a key*; the
   plan counts every palette-bearing occurrence, including those later refused for a
   protected region, a conflict, or `value == key`. A refusal is a real shortfall in
   delivered colour and should drag the rate down where an operator sees it, rather
   than being quietly excluded from the arithmetic. On the measured corpus the two
   definitions coincide (zero skips), so this changes no number today.
2. **Per-part skip counts.** The spec asks for them per part; the report emits a global
   histogram plus the first ten skip lines, each naming its own part. The measured skip
   count is zero, so a per-part column would be empty on every row. Revisit if skips
   stop being rare.
