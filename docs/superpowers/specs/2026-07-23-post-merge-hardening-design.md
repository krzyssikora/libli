# Post-merge hardening: course-scoped image resolution and a PL catalog-health guard

Two independent defects surfaced by the final whole-feature review of the spanning-table editor
(PR #166, merged to `master` at `5ecff90`). Neither is large enough to justify its own pull request;
they are bundled here because they share a moment, not a mechanism. **They have no shared code and no
ordering dependency** — the plan may implement them in either order, and a reviewer should read them
as two separate changes that happen to travel together.

## Purpose

### Issue B — a rejected save can render another course's image

**This defect exists in two places, and both are in scope.** They are the same bug with the same
mechanism, and fixing only one would ship a PR claiming the leak is closed while a live copy remains.

**B1 — the fill-table editor.** `FillTableElementForm.resolved_grid_cells` resolves image primary keys
with an **unscoped** `MediaAsset.objects.in_bulk(ids)`. It is fed `grid_data`, which on a bound-invalid
form is the *submitted* payload rather than the stored one. Since `clean_data` is precisely what
rejects out-of-course media, a save carrying a foreign pk reliably lands in that branch — and the
re-rendered editor emits the foreign asset's URL through `{{ cell.media.file.url }}`.

**B2 — the gallery editor.** `GalleryElementForm.editor_rows` does the same thing: on `self.is_bound`
it resolves ids from `self._raw_data_json()` — the submitted payload — through the same unscoped
`MediaAsset.objects.in_bulk(ids)`, and `templates/courses/manage/editor/_edit_gallery.html:30` renders
the result as `<img src="{{ row.thumb_url }}">`. `GalleryElementForm.clean_data` rejects
out-of-course and wrong-kind media with the same course+kind filter as the fill-table's, so a rejected
gallery save carrying a foreign pk lands in exactly this branch. The fill-table form's own docstring
already notes that its `clean_data` "mirrors GalleryElementForm — the same author-submitted-pk risk",
so the shared risk was known; only the resolver half was left unscoped in both.

The leak is real rather than theoretical. `config/urls.py` serves media via
`static(settings.MEDIA_URL, ...)` with no authentication gate, and `static()` no-ops under
`DEBUG=False`, so in production the web server serves `/media/` directly. A disclosed URL is a
fetchable file. Teacher access is course-scoped through `accessible_courses`, so this crosses a real
boundary.

Severity is bounded and should be stated honestly: the actor must already be staff with edit rights on
some course, and each foreign pk must be known or guessed. But the disclosure is **not** one asset at a
time — a single submission carries a whole grid (up to `MAX_ROWS × MAX_COLS`, i.e. 50 × 20) or a whole
gallery, and the resolver resolves every id in one pass, so one rejected save can surface many foreign
assets from many courses at once. It remains a cross-course read leak, not privilege escalation.

**A second, related mismatch is fixed at the same time.** `clean_data` requires that an asset be *an
image in this course*; the resolver filters on **neither** course nor kind. So today an in-course
**video** pk is rejected at save yet still resolves on re-render, and the template emits a video's URL
inside an `<img>`. Scoping on both conditions makes validation and rendering agree.

### Issue C — nothing detects an untranslated Polish string

During the spanning-table i18n sweep, `makemessages` extracted a msgid that had never been swept
before (the nested-spoiler editor hint, `templates/courses/manage/editor/_element_row.html:171`) and
it shipped with a **blank Polish `msgstr`**. It carried no `#, fuzzy` flag, so it fell outside the
fuzzy review; and the existing catalog assertions cover only `#, fuzzy` and `#~`. A Polish-locale
administrator saw the hint in English. It was caught by human review and fixed in `7b27fb3`, but
nothing prevents a recurrence.

The guard belongs in one owned place. The existing `test_po_catalog_clean` is duplicated **verbatim**
in `tests/test_i18n_auth.py` and `tests/test_i18n_notes.py` — two copies of a three-line assertion
about global files that belong to neither module. That orphaned ownership is the direct cause of the
gap: nobody extends an assertion that is nobody's.

## Architecture and components

### Issue B

One optional parameter, threaded from the only callers that know a course.

**B1 — fill-table:**

- **`FillTableElement.resolve_image_cells(cells, course=None)`** — when `course` is not `None`, the
  bare `in_bulk(ids)` becomes a scoped lookup filtering on `course=course`, `kind="image"` and
  `pk__in=ids`. When `course` is `None`, behaviour is exactly as today.
- **`FillTableElementForm.resolved_grid_cells`** passes `self.course`.
- **`FillTableElement.resolved_cells`** (student render) passes nothing and must remain
  byte-identical to today.

**B2 — gallery:**

- **`GalleryElementForm.editor_rows`** scopes its own `in_bulk(ids)` the same way, on `self.course`
  plus `kind="image"`. It needs no new parameter: unlike the fill-table's resolver, `editor_rows` is a
  form property with no student-render twin to keep in step, so the scoping goes directly in it.
- Gallery's existing fallback is **"unresolved ids are dropped"** (the row is omitted entirely), which
  differs from the fill-table's degrade-to-empty-static. That difference is pre-existing and must be
  **preserved**, not harmonised — an out-of-scope pk simply becomes an unresolved id and takes gallery's
  existing drop path.

**Two different things are called `kind`, and the implementer must not conflate them.** A fill-table
*cell* carries `kind` meaning `static | answer | image` — that is what selects which cells to resolve
and build `ids` from. `MediaAsset.kind` is a property of the *asset* and is what the new lookup filters
on. They coincidentally share the string `"image"`; they are different fields on different objects.

The asymmetry is deliberate and worth recording. `FillTableElement.render` (`courses/models.py:1141`)
has the signature `render(self, *, element=None, state=None, slug=None, node_pk=None)`, matching the
contract inherited from `ElementBase.render` (`courses/models.py:371`). **No course and no unit is
passed at any point in the render chain**, and the element owns no course field — so `resolved_cells`,
a no-arg property, has nothing to scope against.

To be precise rather than sweeping: a course is not strictly *unreachable* from the model —
`FillTableElement` carries `elements = GenericRelation(Element)` (`courses/models.py:990`), and an
`Element` join row reaches `unit.course` — so read-time scoping could in principle be derived. It is
simply not exposed through the existing signature, and threading it through would change the
`ElementBase.render` contract shared by every element type, plus add a query per render. That cost is
why the student-path guarantee stays **validated-at-write**: stored data passed `clean_data`, which
enforces course and kind at save time. Either way the instruction is unchanged — `resolved_cells`
passes no course and stays byte-identical.

`course=None` preserving unscoped behaviour is not an oversight either — it mirrors `clean_data`,
which already skips its own check with `if img_ids and self.course is not None`. A form without a
course validates nothing, and now resolves nothing extra.

**Hard constraint: one fallback shape.** `resolve_image_cells` is deliberately shared between the
student render and the editor. Its docstring states that the two callers "must not diverge on this
fallback" — a decision made in cleanup commit `8ddd349`, *after* the two copies had already diverged
on whether to drop spans. An out-of-scope pk must therefore fall into the **existing** unresolved
branch — degrading to an empty static cell, dropping `colspan`/`rowspan`/`header` — and must not
introduce a new branch or a second fallback shape.

### Issue C

A new file, `tests/test_i18n_po_health.py`, owning every catalog-wide health assertion:

- `test_no_fuzzy_entries` — both `locale/en` and `locale/pl`
- `test_no_obsolete_entries` — both catalogs, no `#~`
- `test_pl_has_no_untranslated_msgid` — **Polish only**

The English catalog is exempt from the untranslated check, and the exemption must be commented in the
file rather than left as folklore: English `msgstr`s are intentionally empty so gettext falls back to
the msgid, which is why `locale/en` legitimately carries hundreds of blanks. A guard covering English
would be permanently red. (No test pins that count, and none should — it drifts with every string
added or removed.)

The two duplicated `test_po_catalog_clean` functions are **deleted** from `tests/test_i18n_auth.py`
and `tests/test_i18n_notes.py`, leaving catalog health as one file's responsibility. In
`tests/test_i18n_notes.py` the module-level `PO` constant is used **only** by the function being
deleted, so it must be removed too — `ruff` does not flag an unused module-level name, so leaving it
would be dead code the linter never catches. `test_i18n_auth.py`'s `POFILE` constant is used by other
tests in that file and must stay.

`tests/test_i18n_catalog.py` is a **name trap** — it tests the course *catalog page's* translation and
has nothing to do with `.po` catalogs. It must not be modified and must not host the guard.

## Data flow

**Issue B1**, on a rejected save: browser POSTs a grid → `clean_data` raises (foreign or wrong-kind
media) → the form is bound-invalid → the template asks for `resolved_grid_cells` → `grid_data` returns
the sanitised submitted payload → `resolve_image_cells(cells, course=self.course)` looks up only
assets that are images in this course → the foreign pk resolves to nothing → the existing unresolved
branch degrades that cell to empty static → the template renders no `<img>` and no URL.

**Issue B2** is the same shape one form over: POST → `clean_data` raises → bound-invalid → template
asks for `editor_rows` → `_raw_data_json()` yields the submitted ids → the now-scoped lookup returns
nothing for the foreign pk → `asset is None` → gallery's existing drop path omits the row → no `<img>`.

On the student path nothing changes: `resolved_cells` → `resolve_image_cells(cells)` with no course →
identical query, identical output. Gallery has no student-render twin of `editor_rows` to change.

**Issue C** is a static analysis of two files on disk. `_entries(path)` parses a `.po` into entries;
all three tests consume that **same** list. No database, no request cycle.

The per-entry shape must be pinned, because two of the tests need opposite things from obsolete
entries. Each entry carries at least:

```
{msgid: str, msgstrs: list[str], fuzzy: bool, obsolete: bool}
```

`msgstrs` holds one string for a singular entry and `nplurals` strings for a plural one, so emptiness
is judged uniformly across both. Crucially, `_entries()` **retains** obsolete entries and marks them
`obsolete=True` rather than dropping them at parse time: `test_no_obsolete_entries` needs to see them
in order to flag them, while `test_pl_has_no_untranslated_msgid` filters them out. A parse-time drop
would leave the obsolete test asserting over a list from which its own subject had already been
removed — passing vacuously.

## Error handling

**Issue B1 (fill-table).** `course=None` is the documented no-scoping path on
`resolve_image_cells`, not an error — it is what the student-render caller passes. An unresolvable pk
— whether dangling, foreign, or of the wrong kind — is not an exception: it degrades to an empty
static cell, exactly as a dangling pk already does.

**Issue B2 (gallery).** The fallback is different and stays different: an unresolvable pk leaves
`asset is None`, and `editor_rows` **omits the row entirely**.

`editor_rows` gains no `course=None` path and needs no `None` carve-out. `GalleryElementForm.clean_data`
already filters `course=self.course, kind="image", pk__in=ids` **unconditionally** — it has no
`self.course is not None` guard (that guard exists only on the fill-table side, `element_forms.py:1543`).
So scoping `editor_rows` unconditionally on `self.course` makes the resolver agree exactly with the
validator in the same form, which is the whole point of the fix. Do not invent a `None` branch here to
mirror the fill-table's; the two forms genuinely differ, and gallery's own validator is the right
reference.

In both cases the author still sees the real `clean_data` validation error explaining what was
actually wrong; the missing image is not the only feedback they get.

**Issue C.** The parser must fail loudly rather than silently under-report, since a guard that misses
entries is worse than no guard. Four parsing hazards must be handled explicitly:

1. the header entry (`msgid ""`) is skipped, not reported as untranslated;
2. multi-line concatenated quoted strings are joined before emptiness is judged;
3. **plurals** — the Polish catalog carries 81 `msgstr[N]` lines and declares `nplurals=3`. An entry
   counts as untranslated if **any** required form is empty, with `nplurals` read from the
   `Plural-Forms` header rather than assumed (English declares 2, so a hardcoded count would be wrong
   for one catalog or the other);
4. **obsolete entries** — `.po` marks these by prefixing *every* line with `#~`, including
   `#~ msgid "..."`. A line-scanner that matches `msgid` without anchoring to a line start free of
   `#` will either report an obsolete msgid as untranslated or swallow it into a live entry's
   continuation. Obsolete entries must be recognised and excluded from the untranslated scan
   entirely; they are not live translations. This is covered by its own test, in addition to the two
   required red-proofs below.

Failure messages list the offending msgids so a failure points at its fix instead of starting a hunt.
Truncation is pinned rather than left to taste: each msgid is truncated to **80 characters** with a
trailing ellipsis, and the list is capped at **20 entries** followed by an "and N more" line. No
`polib` dependency is added; the parser is hand-rolled and kept small.

## Testing

Every task is test-first: write the failing test, confirm it fails **for the stated reason**,
implement, confirm green.

**Issue B1 (fill-table).** A test that a rejected save carrying another course's image pk re-renders
that cell with no `<img>` and no URL. Falsified by dropping the `course` argument — it must go red. The
existing `test_unresolvable_image_cell_drops_spans_in_both_render_and_editor` must stay green **and
unmodified**, which is what proves the shared fallback was not forked. A second test is **required**,
not optional: an in-course asset of the **wrong kind** (a video pk) must degrade identically. The
kind half of the fix carries equal weight to the course half in the architecture above, and untested
it would ship on inspection alone.

**Issue B2 (gallery).** The same pair, against `GalleryElementForm.editor_rows`: a rejected gallery
save carrying a foreign course's image pk renders no `<img>` for it, and one carrying an in-course
video pk does the same. Each falsified by unscoping the lookup. Assert on gallery's **own** fallback —
the row is dropped entirely — not on the fill-table's degrade-to-static, since the two forms
deliberately differ here.

**Issue C.** The hand-rolled parser is itself the risk, so it must be proven against **three** scenarios,
each as concrete as the others — two proving it fires, one proving it does not:

- blank a real Polish `msgstr` → the untranslated check fails, naming that msgid;
- blank **one form** of a plural entry → it also fails (a single scalar falsification would leave the
  plural path, the subtlest branch, unproven);
- an obsolete entry with an empty translation (`#~ msgid "..."` / `#~ msgstr ""`) → it must **not**
  fire. This is the false-positive direction, and without it "excluded from the untranslated scan"
  could be satisfied by a shallow assertion that never exercises an obsolete entry carrying a blank
  `msgstr` at all.

**These three scenarios must never mutate the real catalogs.** CI runs `uv run python -m pytest -n auto`
(`.github/workflows/ci.yml:49`), so tests are distributed across parallel xdist workers; editing
`locale/pl/LC_MESSAGES/django.po` in place — even with a revert — would let a concurrently-running test
(including this file's own three permanent guards) observe a transiently corrupted catalog, and a crash
or failed assertion mid-test would leave a real translation file damaged on disk.

`_entries(path)` already takes a path, so each scenario builds a **`tmp_path` fixture**: the real
catalog's content, or a representative excerpt, plus the one injected mutation, written to a temporary
file and parsed from there. Nothing is reverted because nothing real is touched. The three permanent
guards continue to read the real catalogs, but read-only.

The full non-e2e suite must pass, and both `uv run ruff check .` and `uv run ruff format --check .`
must be clean; CI gates on them separately.

## Out of scope

- Any change to the student render path's behaviour.
- Giving `FillTableElement` a course of its own (a model change well beyond this fix).
- Authenticating `/media/` — a broader deployment concern, not this defect.
- Extending the untranslated-msgstr guard to English.
- Any migration. Neither issue needs one.
