# Callout: a fifth kind — Task / Zadanie

## Purpose

`CalloutElement` currently offers four kinds — Example, Note, Tip and Important — each
rendering as a "textbook category marker": a tinted icon chip, an uppercase tracked eyebrow
heading, and a left spine, all driven from one `--callout-accent` per kind.

Course authors need a fifth category for **a problem set for the reader to work on**, distinct
from Example (a worked solution shown *to* the reader) and from the interactive question
elements (which are marked and stateful). The new kind is purely a visual/semantic category:
it changes nothing about how the callout behaves, nests, or persists.

The kind is author-facing in English as **Task** and in Polish as **Zadanie**.

### Non-goals

- No behaviour. The callout stays zero-JS with no server endpoint; the static render is the
  behaviour. Nothing about marking, state, or progress is introduced.
- No change to callout nesting, the container registry, the element palette, or the icon
  sprite. A *kind* is not an element type; `CalloutElement` remains a single palette card.
- No re-litigation of the existing `warning` value / "Important" label mismatch. That mismatch
  is deliberate and load-bearing (existing rows, `.callout--warning`, exported archives); this
  change neither depends on it nor repeats it.

## Decisions and rationale

**D1 — the stored value is `"task"`, matching its label.** The existing fourth kind stores
`"warning"` while displaying "Important", a mismatch that now needs a comment in the model to
stop a future contributor "fixing" it with a data migration. That mismatch exists only because
the relabel came after the data. Here there is no data and no constraint, so value and label
agree from the start rather than introducing a second such trap. `Kind.TASK = "task"`, CSS
class `.callout--task`, transfer payload `{"kind": "task"}`.

**D2 — `FORMAT_VERSION` is NOT bumped; it stays at 9.**

An earlier draft of this spec proposed bumping 9 → 10 so that an older build would reject a
Task-bearing archive with an honest "exported from a newer version" message instead of
`_val_callout`'s "unknown callout kind". That reasoning was wrong on two counts, both verified
against the code:

1. **The version gate is archive-wide, not element-wise.** `_validate_manifest`
   (`courses/transfer/importer.py:190`) rejects on `version > FORMAT_VERSION` for the whole
   archive regardless of its contents. Bumping would make **every** export from this build
   unimportable into any not-yet-upgraded instance — including the overwhelming majority that
   contain no Task callout and import fine today. That converts successes into failures; it is
   a new rejection, not a better-worded one.
2. **The repo has already decided this, and encoded the decision in a test.**
   `courses/tests/test_beforeafter_transfer.py::test_format_version_is_unchanged` carries the
   rule as its docstring: *"A new element TYPE has never bumped it; the version rises only when
   an EXISTING payload shape changes. Not bumping also sidesteps the silent-merge hazard (two
   branches setting the same new number do not conflict in git)."* A new *kind* is strictly
   weaker than a new *type* — the callout payload shape is unchanged at `{kind, heading, body}`,
   only the accepted value domain of one field widens. A new element type is likewise rejected
   by older builds (`payloads.py`'s unknown-type error) and has never bumped the version.

**Live consequence that makes this more than academic:** the mat-pp PROD cutover is still
outstanding, and its sanctioned flow is to export mat-pp from the local instance and import it
into PROD. A bump would break that import outright until PROD is upgraded — a real cost paid
for a cosmetic improvement to an error message.

**Accepted cost of not bumping:** an older build importing an archive that *does* contain a
Task callout fails at that element with "Element 'x' has an unknown callout kind" rather than
naming the version as the cause. This is the same degradation a new element type already
produces, it is scoped to archives that actually use the feature, and it leaves every other
archive importable. It also inherits the docstring's second benefit: no version constant is
touched, so the concurrent-branch hazard (two branches setting the identical new number, which
git merges with no conflict and a green suite) cannot arise from this branch at all.

**No test file's version assertion is touched.** In particular `test_format_version_is_unchanged`
(beforeafter), `test_format_version_is_bumped` (image size) and
`test_format_version_is_bumped_for_cell_images` (table) are feature-scoped claims whose names
and docstrings would be falsified by a mechanical rewrite; they stay at 9, still true, still
guarding their own features.

**D3 — accent and icon were chosen against rendered mockups**, both themes, alongside the
existing four at real size (3px spine, 18px chip), using the project's own stylesheets. Magenta
was selected over violet, teal and rose: teal sits between the existing blue and green and reads
as a shade of Tip; rose reads as severity next to the amber Important. The mockup was a
throwaway scratch file, not a committed artifact — **DoD 7's screenshot is the durable
evidence**, and a reviewer wanting to re-run the comparison should reproduce it there rather
than look for a checked-in mockup.

*Known collision, accepted:* `_element_row.html` uses a pencil glyph (`✎`) for its per-row Edit
button, so inside the editor a Task callout's pencil chip sits near a column of pencil edit
buttons. The pencil was nonetheless chosen deliberately from a rendered side-by-side against
five alternatives (clipboard-list, puzzle, target, checklist, square-sigma), judged on the
**student-facing** render where no Edit affordance exists and the pencil is the conventional
textbook "work this" marker. Do not silently substitute another glyph.

## Architecture / components

### 1. Model — `courses/models.py`

Append one member to the nested `CalloutElement.Kind` TextChoices:

```python
TASK = "task", _("Task")
```

Constraints already satisfied, verified against the current field definition:

- `kind = models.CharField(max_length=12, ...)` — `"task"` is 4 characters, well inside the
  bound. No field-width change.
- `KIND_DEFAULT_HEADING` is built at module level as
  `{k.value: k.label for k in CalloutElement.Kind}` *after* the class body, so the new default
  heading ("Task" / "Zadanie") is picked up with no edit. `display_heading` needs no change.
- `save()`'s defensive coercion (`if self.kind not in self.Kind.values: self.kind = EXAMPLE`)
  needs no change — `"task"` is now a member, so it survives the check.

**Stale "four kinds" prose and counts to update in the same change.** The enumeration recurs
across the tree; this list is the known set, not a proof of exhaustiveness — grep for `four`
near `callout` before finishing. Each entry gives the target wording, because "update" alone
has repeatedly produced a stale count somewhere else:

- the `CalloutElement` class docstring — "(Example/Note/Tip/Important)" becomes
  "(Example/Note/Tip/Important/Task)";
- `courses/tests/test_callout_render.py:22` — "The four kinds emit four distinct icon markers"
  becomes "The five kinds emit five distinct icon markers"; the comment sits directly beside
  where the new icon test goes;
- `tests/test_text_colour_css.py:3` (module docstring) — "which is ten surfaces, not two"
  becomes "eleven surfaces";
- `tests/test_text_colour_css.py:20-21` — "recomputes the four callout grounds from
  courses.css" becomes "the five callout grounds";
- `tests/test_callout_css.py:15-18` — the existing class list
  `[".callout--example", ".callout--note", ".callout--tip", ".callout--warning"]` gains
  `".callout--task"`. **Additive only.** Appending here is *not* a substitute for the two
  anchored regexes in Testing rows 1-2: this list is exactly the bare-substring form those rows
  exist to replace, and appending to it alone leaves the light rule unguarded.
- `docs/superpowers/specs/2026-07-14-callout-element-design.md:18` — **leave alone**, it is a
  historical record of that feature's design, not live documentation.

### 2. Migration

`0056_alter_calloutelement_kind` — an `AlterField` on `CalloutElement.kind`.

The SQL is a no-op: Django never emits a PG CHECK for `choices`, so `sqlmigrate` prints
`-- (no-op)`. The migration is nonetheless **required**, because `choices` is part of the
field's deconstruction: without it the migration state drifts and the next unrelated
`makemigrations` silently absorbs this `AlterField` into itself. This is the exact failure
mode that shipped in #203 and prompted the CI guard; `.github/workflows/ci.yml` now runs
`makemigrations --check --dry-run` in the `unit` job, so a missing migration fails CI.

Migration number `0056` assumes `0055_beforeafterelement_alter_element_content_type` (from the
before/after element, merged as #227) is the current head. Confirm that by **listing
`courses/migrations/`** — not with `showmigrations`, which reports *applied* state and needs a
live database connection, and so can disagree with the on-disk head that actually determines
the next number. In practice `makemigrations` assigns the number itself; the listing is just
the sanity check.

### 3. Student render

`templates/courses/elements/_callout_icon.html` is an `{% if %}` / `{% elif %}` chain over
`el.kind`, terminating in an `{% else %}` that emits the Example book-open icon as the
fallback. Add a branch **before** that `{% else %}`:

```
{% elif el.kind == "task" %}
  <svg class="callout__icon" ...>…pencil…</svg>
```

The icon is the Lucide **pencil**, matching the house convention for this set: a monochrome
line SVG on a `0 0 24 24` viewBox, `fill="none"`, `stroke="currentColor"`, `stroke-width="2"`,
round caps and joins, `aria-hidden="true"`, `focusable="false"`. Paths:

```
<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/>
<path d="m15 5 4 4"/>
```

`calloutelement.html` itself needs no change: it emits
`class="callout callout--{{ el.kind }}"` and `{{ el.display_heading }}`, both already generic.

### 4. Styling — `courses/static/courses/css/courses.css`

Two declarations, appended to the existing per-kind blocks at `courses.css:1849-1857` and
**column-aligned to match them**:

```css
.callout--example { --callout-accent: #2563c9; }
.callout--note    { --callout-accent: #55606b; }
.callout--tip     { --callout-accent: #1f8a52; }
.callout--warning { --callout-accent: #b06f0f; }
.callout--task    { --callout-accent: #a8318f; }

[data-theme="dark"] .callout--example { --callout-accent: #7db0f7; }
[data-theme="dark"] .callout--note    { --callout-accent: #aabac8; }
[data-theme="dark"] .callout--tip     { --callout-accent: #5cd193; }
[data-theme="dark"] .callout--warning { --callout-accent: #e8b761; }
[data-theme="dark"] .callout--task    { --callout-accent: #ee9fd8; }
```

Everything else derives from that single custom property, exactly as the other four kinds do:
the 3px left spine, the 6%-accent-over-`--surface-raised` container tint, the 14%-accent icon
chip, and the eyebrow colour.

**Contrast, computed against the tinted callout background** (`color-mix(accent 6%, surface)`,
which resolves to `#FAF3F8` light and `#383030` dark under the project's own mixing):

| Theme | Accent | Background | Ratio |
|---|---|---|---|
| Light | `#a8318f` | `#FAF3F8` | ~5.5:1 |
| Dark | `#ee9fd8` | `#383030` | ~6.5:1 |

Both clear WCAG AA for normal text, so the 0.75rem/700 eyebrow is safe with margin. These two
ground colours are **also** the values §5 registers in the normative surface list, which is what
gives the table above an automated drift guard.

**The icon sits on a different, more saturated ground** and is not covered by the table above:
`courses.css:1807-1808` puts it on `color-mix(accent 14%, transparent)` layered over the 6%
tint — `#EFD8E9` light, `#514048` dark. As a non-text graphic the applicable threshold is 3:1,
and it measures **4.48:1 light / 4.86:1 dark**. Comfortable; nothing to change. Recorded so the
table above is not misread as covering the whole component.

### 5. The normative text-colour surface list — `tests/test_text_colour_css.py`

This file is not incidental test housekeeping; its header states *"The surface list is the
specification"*. It holds `LIGHT_SURFACES` / `DARK_SURFACES` dicts with one `callout-<kind>`
ground per kind, and two loops over them:

- `test_every_slot_clears_aa_on_every_surface` — measures the four author-selectable `--tc-*`
  text colours against **every** listed ground;
- `test_surface_literals_still_match_the_css` — recomputes each `.callout--<kind>` accent out of
  `courses.css` and compares, so a hex edit in one file reddens the suite.

A fifth kind is a **new ground that rich text can sit on**, so both must learn about it:

- add `"callout-task": "#FAF3F8"` to `LIGHT_SURFACES` and `"callout-task": "#383030"` to
  `DARK_SURFACES`;
- add `"task"` to the hardcoded kind tuple at `tests/test_text_colour_css.py:126`
  (currently `("example", "note", "tip", "warning")`), or the drift loop skips the new accent
  entirely.

Both count statements in that file also become false and are listed as update sites in §1.

Omitting this is silent: the new ground simply escapes the AA guard, and the two new hexes get
no drift guard at all. **The magenta is safe on both grounds, with the margin stated rather
than asserted:** the binding case across the four `--tc-*` slots is `--tc-red` `#EA8A82` on the
dark ground `#383030` at **~5.17:1**, against the 4.5:1 AA threshold. So the new grounds are not
the constraining surface in either theme — this is a coverage gap to close, not a colour to
change, and adding them will not redden the suite.

### 6. Editor — no template change, but it is the only author-facing surface

`templates/courses/manage/editor/_edit_callout.html` renders the kind picker by iterating
`form.fields.kind.choices`, with the selected-state comparison
`form.kind.value|stringformat:"s" == value|stringformat:"s"`. `CalloutElementForm` is a plain
`ModelForm`, so a new enum member appears in the dropdown automatically and round-trips its
selected state with no template edit.

**But no existing test iterates `CalloutElement.Kind` or the form's choices** — the authoring
tests hardcode `"warning"` (`test_callout_authoring.py:64,73,82`). So "data-driven, therefore
covered" is false: without a new test, the one surface through which an author can reach this
feature at all has zero coverage. §9 adds one.

`_element_row.html`'s callout branch is kind-agnostic (it shows the type label and either the
element title or `element_summary`), so the editor list itself needs nothing.

### 7. Transfer — no change at all

- `_ser_callout` emits `{kind, heading, body}` straight off the model — generic.
- `_val_callout` checks `data["kind"] not in CalloutElement.Kind.values` — data-driven, so it
  accepts `"task"` the moment the enum gains it.
- `_build_callout` goes through `_clean_save` — generic.
- `FORMAT_VERSION` stays at 9 per D2, so **no test file's version assertion is edited**.

The only transfer work is a round-trip test proving `kind="task"` survives export and import.

### 8. i18n and the help manual

`Task` is a new msgid, translated **`Zadanie`** in Polish.

**There are two catalogs, not one.** `tests/test_i18n_po_health.py:22` reads
`CATALOGS = {"pl": PL_PO, "en": EN_PO}`, so `locale/en/LC_MESSAGES/django.po` also gains
`msgid "Task"` — with a **deliberately empty msgstr**, which is the established convention for
the English catalog and is why `test_pl_has_no_untranslated_msgid` is scoped to `pl` alone. A
branch that touches only `pl` ships an inconsistent pair and no guard fires; a branch that runs
extraction without expecting the `en` diff may revert it as noise. Extract both explicitly:

```
uv run python manage.py makemessages -l pl -l en --no-obsolete
uv run python manage.py compilemessages
```

This is precisely the shape that triggers the known `makemessages` fuzzy trap: `msgmerge`
pre-fills a new short msgid from a similar existing one and marks it `#, fuzzy` with a `#|
msgid` reference line. Clearing it is **two** deletions — the `#, fuzzy` flag line *and* the
`#| msgid` line — not one.

The trap's failure mode is a **wrong but non-empty** msgstr, which `test_i18n_po_health.py`
does not catch: it guards fuzzy, obsolete and *blank* entries, none of which fire once the flag
is cleared off a wrong translation. Testing row 9 therefore pins the string itself — and it
reads the compiled `.mo`, so `compilemessages` must run **before** the test selection (see
DoD 3).

Help manual — both editions list the kinds inline and must gain the fifth. Quote the target
result in each so the initial values are pinned:

- `docs/help/course-admin/content-editors.md:116` — "Choose a **Kind** (Example, Note, Tip, or
  Important — …" becomes "(Example, Note, Tip, Important, or Task — …".
- `docs/help/course-admin/content-editors.pl.md:125-126` — "Wybierz **Rodzaj** (Przykład,
  Notatka, Wskazówka lub Ważne — …" becomes "Wybierz **Rodzaj** (Przykład, Notatka, Wskazówka,
  Ważne lub Zadanie — …". The final item must match the `Zadanie` msgstr exactly.

**Residual risk, stated rather than denied:** quoting the target text pins the *initial* commit
only. No test in this repo reads `docs/help/` at all, so nothing prevents the Polish help
sentence and the `Zadanie` msgstr drifting apart later. Testing row 9 guards the catalog; the
help prose is **unguarded by design** — adding the repo's first docs-prose test to close a
drift no one has yet observed is not worth the brittleness it introduces here.

## Data flow

**Authoring.** The editor form offers the kind via `Kind.choices`; the POST stores
`kind="task"`; `save()` sanitises the body and leaves the kind alone. No new request path.

**Student render.** `calloutelement.html` interpolates the kind into `callout--task`, the icon
partial's new branch emits the pencil, and `display_heading` yields the translated "Task" /
"Zadanie" unless the author supplied a heading override. CSS resolves `--callout-accent` from
the class. There is no JS on this path.

**Export.** `_ser_callout` writes `{"kind": "task", …}`; the manifest carries the unchanged
`format_version: 9`.

**Import into a build that has this feature.** `_val_callout` accepts `"task"` because it is in
`Kind.values`; `_build_callout` saves it.

**Import into an older build.** The manifest gate passes (version 9 is not newer), and the
archive fails at the Task element with "unknown callout kind" — the accepted cost stated in D2.
Archives without a Task callout are unaffected.

**Math.** No change is needed. `_element_has_math` dispatches on the *element type*
(`CalloutElement` → heading + body + recursive children), never on the kind, so a Task callout
arms KaTeX under exactly the same conditions as any other callout.

## Error handling

- **Unknown kind from a tampered import or a stale row** — unchanged: `save()` coerces
  anything outside `Kind.values` to `example`, and `display_heading` falls back through
  `KIND_DEFAULT_HEADING.get(self.kind, KIND_DEFAULT_HEADING["example"])` using the **string**
  key (a bare `Kind.EXAMPLE` there would raise `NameError`, since `Kind` is a nested class
  resolved against module globals at method scope).
- **Unknown kind in an import payload** — unchanged: `_val_callout` raises a `TransferError`
  with a translated, user-facing message. Adding a member widens what is accepted; it does not
  weaken the rejection.
- **A missing icon branch** — the `{% else %}` fallback means a typo in the branch condition
  degrades to the Example book-open icon rather than rendering nothing. Silent, hence the
  explicit icon test below.
- **A wrong Polish translation** — silent by construction (see §8), hence the pinned string test.

## Testing

Every test below names the mutant that must turn it **red**. A test that passes both with and
without the change it guards is worthless, and roughly a third of the catches in the last
callout branch were exactly that.

| # | Test | Location | Mutant that must fail it |
|---|---|---|---|
| 1 | the **light** `.callout--task` rule carries `#a8318f` | `tests/test_callout_css.py` | delete the light rule |
| 2 | the **dark** `[data-theme="dark"] .callout--task` rule carries `#ee9fd8` | same file | delete the dark override |
| 3 | `display_heading` for `kind="task"` is "Task" — extend the existing `test_display_heading_falls_back_to_kind_default` (`test_callout_model.py:41-44`) with a fifth line rather than adding a function | `courses/tests/test_callout_model.py` | remove the `TASK` enum member |
| 4 | a **persisted** task callout renders `callout--task`: `CalloutElement.objects.create(kind="task")` then `.render()` | `courses/tests/test_callout_render.py` | remove the `TASK` enum member — `save()` then coerces the kind to `example` and the class becomes `callout--example` |
| 5 | render emits the pencil path `m15 5 4 4` for `task`, and that path is **absent** from an `example` render | same file | delete the `{% elif el.kind == "task" %}` branch — it then falls through to book-open, and both halves move together |
| 6 | the editor form offers the kind: GET `manage_element_form` for a callout, assert an `<option value="task">` labelled "Task" is present | `courses/tests/test_callout_authoring.py` | remove the `TASK` enum member |
| 7 | authoring persists it: POST `kind="task"`, assert the saved `content_object.kind == "task"` | same file | as above |
| 8 | a `kind="task"` callout survives an export/import round trip | `courses/tests/test_callout_transfer.py` | revert the enum, so `_val_callout` rejects the payload |
| 9 | the pl catalog renders `Task` as "Zadanie": `with translation.override("pl"): assert str(CalloutElement(kind="task").display_heading) == "Zadanie"` | new `tests/test_i18n_callout_task.py`, per the house per-feature convention | leave the `msgmerge` fuzzy pre-fill in place |
| 10 | the new callout grounds are in the normative surface list and match the CSS | `tests/test_text_colour_css.py` (extend, don't add a file) | change either accent hex without updating the literal |

**Assertion form — this is where the last branch bled.** Tests 1 and 2 scan stylesheet source
text, and a bare `assert ".callout--task" in css` **cannot fail its own mutant**: the dark rule
`[data-theme="dark"] .callout--task { … }` contains that substring, so deleting the light rule
leaves it green. Both assertions must therefore be anchored regexes that also capture the hex
the contrast table depends on, and must tolerate the block's column alignment:

- light: `re.search(r"^\.callout--task\s*\{\s*--callout-accent:\s*#a8318f", css, re.M)`
- dark: `re.search(r'^\[data-theme="dark"\]\s+\.callout--task\s*\{\s*--callout-accent:\s*#ee9fd8', css, re.M)`

The `^` anchor is what stops the light pattern matching inside the dark selector.

**Two further test-authoring hazards, both previously shipped in this repo:**

- **Row 4 must persist the instance.** `calloutelement.html:2` is
  `<aside class="callout callout--{{ el.kind }}">`, a bare interpolation, so an *unsaved*
  `CalloutElement(kind="task").render()` emits `callout--task` even with the enum member,
  the icon branch and the CSS all absent — it passes against a completely unimplemented
  feature. Only `objects.create()` routes through `save()`'s coercion, which is what makes the
  mutant bite. The neighbouring tests in that file use the unsaved form (`:9`), so the house
  pattern is the trap here.
- **Row 9 must use `translation.override("pl")`, never a bare `activate("pl")`.** `activate`
  is process-global and is not undone at test exit, so every later test in that xdist worker
  runs under the Polish catalog; under `-n 2` the failures land on unrelated tests and vary by
  shard. Wrap the lazy label in `str()`, matching `test_callout_model.py:44`.

**Layer.** All of this is falsifiable at the unit/template level. Nothing here is behavioural,
so **no e2e test is warranted** — the existing callout e2e coverage exercises the container
mechanics, which this change does not touch.

## Definition of done

1. `uv run python manage.py makemigrations --check --dry-run` clean (the migration exists).
2. `uv run python manage.py check` clean.
3. The affected selection green. **Two prerequisites, in this order, or the run misleads you:**
   start the containerised test DB
   (`docker compose -p libli-test -f docker-compose.test.yml up -d --wait`) or the run looks
   hung for ~4m21s before erroring; and run `compilemessages` (DoD 6) **first**, because row 9
   resolves through the compiled `django.mo`, not the `.po` — running the suite before it is
   compiled gives a red test 9 that is not a defect. Explicit paths, rather than a prose
   category:

   ```
   uv run pytest courses/tests/test_callout_model.py courses/tests/test_callout_render.py \
     courses/tests/test_callout_form.py courses/tests/test_callout_authoring.py \
     courses/tests/test_callout_transfer.py tests/test_callout_css.py \
     tests/test_text_colour_css.py tests/test_i18n_po_health.py \
     tests/test_i18n_callout_task.py
   ```

   `scripts/affected_tests.py` may be used to widen this from the diff, but the list above is
   the floor. A whole-repo sweep is a branch gate, not a per-task step.
4. Each new test verified **red** against its named mutant, not merely observed green.
5. `uv run ruff check .` and `uv run ruff format --check .` clean — the format check is a real
   CI gate; run `ruff format .` **last**, after every other edit.
6. **Both catalogs**, extracted with the §8 command. `pl` at **0 fuzzy / 0 obsolete /
   0 untranslated** (`test_i18n_po_health.py`'s three guards, including
   `test_pl_has_no_untranslated_msgid`); `en` gains `msgid "Task"` with an empty msgstr and stays
   at 0 fuzzy / 0 obsolete. Both `.mo` files regenerated via `compilemessages` — **before** DoD 3.
7. Light + dark screenshot of all five kinds together. No existing page renders them side by
   side (`seed_demo_course._callout` creates a single `kind="tip"` callout), so the mechanism is:
   author a scratch lesson unit holding one callout of each kind in a local course, then capture
   it with Playwright.

   **The dark shot has a specific trap.** `base.html:4` bakes `data-theme` from the server, and
   for an authenticated user the stored `User.theme` is what wins — a cookie or an OS preference
   does not deterministically drive it. Set `user.theme = "dark"` and save before navigating, the
   pattern `tests/test_e2e_html_element.py:358` and `test_e2e_link_dialog.py:318` already use.
   Then **verify the capture actually is dark** — assert
   `page.locator("html[data-theme='dark']").count() == 1` (as `test_e2e_auth.py:69` does) before
   trusting the image. Without that assertion a light-rendered page passes as "the dark
   screenshot", which would make DoD 7 unfalsifiable — and D3 stakes the whole
   magenta-over-violet/teal/rose decision on this evidence. Judge the dark shot on its own
   merits; do not infer it from the light one.
