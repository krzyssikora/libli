# Editor twin-drift guard

`table_editor.js` and `filltable_editor.js` carry 163 lines of code-identical duplication across 20
functions. This adds a source-level test that makes drift between those twins fail loudly, instead of
extracting them into a shared module.

## Purpose

The two WYSIWYG table editors grew in parallel. Twenty of their functions are byte-identical once
comments are ignored — 11 at file scope, 9 nested inside `wire()` — totalling 163 lines. Nothing
enforces that they stay in step, so the realistic failure is silent: someone fixes a selection bug in
`table_editor.js`, misses the twin in `filltable_editor.js`, and the fill-table editor keeps the bug.
The tests would stay green, because each editor's tests exercise only its own file.

**Extraction was considered and rejected**, and the reasoning belongs here so nobody re-opens it
casually. The nine nested twins are closures over `wire()`'s locals, and two properties make lifting
them expensive:

- They **mutate** selection state — `clearRange` assigns `rangeEnd = null`. A JS closure variable
  cannot be shared across a module boundary, so extraction requires a state object
  (`sel.focusCell` / `sel.rangeAnchor` / `sel.rangeEnd`) and every existing reference in *both*
  `wire()` bodies must be rewritten to use it.
- The identical helpers **call the divergent ones**: `clearRange` and `paintRange` call
  `refreshToolbarState`; `absorbedNonEmpty` calls `cellIsNonEmpty`. Those must become injected
  callbacks.

Removing 163 duplicated lines therefore means touching both `wire()` bodies in full — 487 raw lines
in `table_editor.js` and 693 in `filltable_editor.js`, about 1,180 together — in editors that shipped
days ago, with the e2e suite as the only safety net. (Raw file lines here, not the normalised 368/528
quoted in the divergence table below; the two measures differ by blank and comment lines.) The cost is not worth it
*yet*. This guard is the cheaper move that addresses the actual risk — and if these editors keep
growing until extraction does pay, the guard becomes the safety net for performing it.

The guard therefore does **not** reduce duplication. It makes duplication that drifts impossible to
merge quietly. That is the whole claim, and the spec should not be read as promising more.

## Architecture and components

One new file, `tests/test_editor_twin_drift.py`. No production code changes, no runtime behaviour
change of any kind.

### The contract is a classification, not a list

Every function name present in **both** editors is declared in exactly one of two module-level lists:

- **`TWINS`** — the 20 that must stay code-identical.
- **`DIVERGENT`** — the 7 that differ deliberately, each with a one-line reason.

The completeness check runs in **both directions**, and both are load-bearing:

- **Forward** — a function common to both files and absent from both lists fails the test. This stops
  the guard rotting: adding a new shared helper forces a decision, rather than silently creating a
  21st unguarded twin. A bare `TWINS` list without it would decay the first time someone added a
  helper to both files.
- **Backward** — every name in `TWINS ∪ DIVERGENT` must still exist as a function in *both* files.
  Without this, deleting or renaming a twin leaves a dead entry that nothing notices, and the failure
  mode is worse than clutter: if a later, unrelated function reuses that orphaned name, it inherits
  the stale classification and the forward check never fires, because the name is already
  (spuriously) classified. A twin could then be introduced pre-excused.

A stale entry must fail loudly and name itself, the same way an unclassified one does.

### The two scopes

Functions are extracted at two scopes, because the duplication lives at both:

- **file scope** — 11 twins: `colCount`, `colCtl`, `dataCells`, `dataRows`, `ensureRowControls`,
  `handleBtn`, `newCell`, `rebuildColControls`, `refreshControlState`, `rowCtl`, `tableContainer`.
- **nested inside `wire()`** — 9 twins: `absorbedNonEmpty`, `clearRange`, `headerLocked`, `msg`,
  `paintRange`, `refreshAlignButtons`, `refreshHeaderButton`, `say`, `tooBig`.

Neither file defines the same function name twice, so a name-keyed extractor is unambiguous. That is
a property of the current files, not a language guarantee — see Error handling.

### The seven deliberate divergences

Each carries its reason in the `DIVERGENT` list, so a reader learns *why* rather than just *that*:

| Function | Why it differs |
|---|---|
| `label` | closes over a different editor root attribute (`[data-table-editor]` vs `[data-filltable-editor]`) |
| `wire` | the container itself; its nested helpers are classified individually, so comparing the two bodies (368 vs 528 lines *after normalisation*) would be meaningless |
| `serialize` | two differences: fill-table emits three cell kinds (static / answer / image) where the plain table emits one, and its payload carries two extra document-level fields, `case_sensitive` and `prompt`, which the plain table has no equivalent for |
| `refreshToolbarState` | fill-table adds an `if (!focusCell) return` gate *after* the merge/split/header block, so the kind-specific refresh (disabling `[data-cmd]` on answer/image cells, the answer-toggle state, hiding the alt input) is skipped when nothing is focused; that gate also moves its `refreshAlignButtons()` call behind it |
| `toggleHeaderCell` | two differences: fill-table re-keys the live `cellStash` Map from old node to new, and focuses the cell's answer input rather than the cell — `.focus()` is a no-op on a `<td data-answer>`, which would strand the Alt+Shift+Arrow chord |
| `cellIsNonEmpty` | **both** files are image-aware, by different mechanisms: the plain table queries for a nested `<img>`, fill-table checks the `data-image` attribute. Fill-table additionally treats answer cells as always non-empty |
| `afterStructuralEdit` | fill-table additionally calls `cellStash.clear()` first, so a stashed cell cannot be restored into the wrong node after the grid is reshaped |

### Normalisation: comments are stripped before comparison

This is load-bearing, not a convenience. Three functions — `newCell`, `rebuildColControls` and
`dataCells` — have byte-identical code and differ **only** in that one file carries an extra
explanatory comment. A raw-text comparison would classify all three as "deliberately divergent",
parking 29 lines of genuine twin code in the list that means *nobody checks these*. The guard would
then be actively misleading: it would assert completeness while excusing exactly the code most likely
to drift.

So comparison strips, per line: leading and trailing whitespace, blank lines, whole-line `//`
comments, and trailing `//` comments. What remains is code tokens. Indentation therefore does not
matter either, which is necessary anyway — the file-scope twins sit at two-space indent and the
nested ones at four.

**A `//` inside a string literal would break this, and it fails worse than the brace hazard.** A
naive stripper truncates `var u = "http://x"` at the `//`, discarding the rest of the line. Unlike a
broken extractor, which finds fewer functions and is caught by the count assertion, this failure
makes two genuinely *different* lines normalise to the same prefix and compare **equal** — the guard
reports success while missing real drift, and nothing else notices.

Neither file contains such a line today. Every `//` in both files is a real comment; the ones that
look risky merely *follow* a string on the same line, like
`if (!window.confirm(msg("merge-confirm"))) return;   // cancel: no change`, where stripping is
correct. There are likewise no template literals — every backtick in either file sits inside prose
comment text, which is discarded before any scanning.

Rather than write a JS-aware tokeniser for a case that does not exist, the guard carries a
**tripwire**: before comparing, it fails loudly if either file contains a line where `//` is preceded
by an odd number of unescaped `"` or `'` on that line (i.e. the `//` is inside an open string), or if
any backtick survives comment-stripping (a template literal, which per-line scanning cannot handle
safely). Either condition means the normalisation assumption has been invalidated and the stripper
must be made quote-aware before the guard can be trusted. This mirrors the treatment of the
brace-counting hazard: the assumption is stated, checked, and fails loudly rather than silently.

Comments diverging freely is the accepted trade: each editor should be able to explain itself in its
own terms.

## Data flow

Pure static analysis of two files; no database, no browser, no fixtures.

Read `table_editor.js` and `filltable_editor.js` → extract every function body at file scope and
every function body nested directly inside `wire()` → normalise each body → for each name common to
both files, look it up in `TWINS` / `DIVERGENT` → assert twins match, and assert every common name is
classified.

## Error handling

The extractor is hand-rolled, and a hand-rolled extractor that silently finds nothing is worse than
no guard at all — it reports success while checking a void. Three hazards, each handled explicitly:

1. **Vacuous extraction.** If a regex stops matching (a reformat, a style change, a rename), the
   extractor returns fewer functions and every remaining comparison trivially passes. The guard
   therefore asserts the **exact expected count** of twins found, so a broken extractor fails loudly
   rather than passing empty-handed.
2. **Brace counting.** Bodies are delimited by counting `{` and `}`, which is not a JS parser: a brace
   inside a string literal, a regex literal or a template string would miscount and swallow the rest
   of the file. No such line exists in either editor today; the count assertion in (1) is what
   detects it if one is ever introduced, since a swallowed body makes the function count collapse.
3. **Duplicate names.** A name-keyed map assumes each file defines a name once. That holds today
   (28 and 36 definitions, no repeats). If it ever stops holding, the extractor must not silently keep
   the last definition and compare the wrong pair — it fails instead, naming the duplicated function.

When a twin has drifted, the failure names the function, both files, and the first differing
normalised line, so the fix is immediate rather than a hunt.

## Testing

The guard is the deliverable, so proving it *can fail* is the substance of the work, not a formality.
Five falsifications, each reverted afterwards — one per independent check, so no check ships
unproven:

1. **A twin drifts** — change one line inside `paintRange` in `filltable_editor.js` only. The guard
   must fail, naming `paintRange` and the differing line.
2. **A new twin goes unclassified** — add a trivial identical function to both files without listing
   it. The guard must fail, naming it and saying it must be classified as twin or divergent.
3. **A comment-only change does NOT fail** — add a comment to one copy of `newCell`. The guard must
   stay green. This is the mirror-image proof: without it, the normalisation rule is unverified, and
   the three comment-only cases that motivated it would be indistinguishable from real drift.
4. **The extractor is not vacuous** — the count assertion from Error handling (1) must itself go red
   when the function-matching regex is broken.
5. **A stale classification is caught** — rename one twin (say `tooBig`) in one file only, leaving its
   name in `TWINS`. The guard must fail, naming the entry that no longer exists in both files. This
   proves the *backward* completeness check fires; falsifications 1–4 exercise twin equality, the
   forward check and the count assertion, and would all still pass with the backward check deleted
   entirely — which is exactly the silent-orphan hole it was added to close.

Falsification 3 matters as much as 1. A guard that fires on comment edits would be reverted within a
week by whoever gets tired of it, which is a slower path to the same unguarded state.

The full non-e2e suite must pass, and both `uv run ruff check .` and `uv run ruff format --check .`
must be clean; CI gates on them separately.

## Out of scope

- Extracting the duplication into a shared module — deliberately rejected above.
- Any change to `table_editor.js`, `filltable_editor.js`, or any other production file.
- Asserting that the seven divergent functions *stay* divergent. If someone later converges one
  legitimately, that should be free; they move it to `TWINS`.
- Guarding the eight fill-table-only helpers — `answerPlaceholder`, `setImageCell`, `stashFor` and
  `toggleAnswerCell` (nested in `wire()`), plus the submit-guard block `isBlankAnswer`,
  `clearAnswerError`, `showAnswerError` and `onSubmit` (file scope) — or either file's `init*` entry
  point. They exist in one file only, so they have no twin to drift from and need no classification
  in either direction.
