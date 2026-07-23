# Post-merge hardening: course-scoped image resolution and a PL catalog-health guard

Two independent defects surfaced by the final whole-feature review of the spanning-table editor
(PR #166, merged to `master` at `5ecff90`). Neither is large enough to justify its own pull request;
they are bundled here because they share a moment, not a mechanism. **They have no shared code and no
ordering dependency** — the plan may implement them in either order, and a reviewer should read them
as two separate changes that happen to travel together.

## Purpose

### Issue B — a rejected save can render another course's image

`FillTableElementForm.resolved_grid_cells` resolves image primary keys with an **unscoped**
`MediaAsset.objects.in_bulk(ids)`. It is fed `grid_data`, which on a bound-invalid form is the
*submitted* payload rather than the stored one. Since `clean_data` is precisely what rejects
out-of-course media, a save carrying a foreign pk reliably lands in that branch — and the re-rendered
editor emits the foreign asset's URL through `{{ cell.media.file.url }}`.

The leak is real rather than theoretical. `config/urls.py` serves media via
`static(settings.MEDIA_URL, ...)` with no authentication gate, and `static()` no-ops under
`DEBUG=False`, so in production the web server serves `/media/` directly. A disclosed URL is a
fetchable file. Teacher access is course-scoped through `accessible_courses`, so this crosses a real
boundary.

Severity is bounded and should be stated honestly: the actor must already be staff with edit rights
on some course, the foreign pk must be known or guessed, and the disclosure is of one asset at a
time. It is a narrow cross-course leak, not privilege escalation.

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

One optional parameter, threaded from the only caller that knows a course.

- **`FillTableElement.resolve_image_cells(cells, course=None)`** — when `course` is not `None`, the
  bare `in_bulk(ids)` becomes a scoped lookup filtering on `course=course`, `kind="image"` and
  `pk__in=ids`. When `course` is `None`, behaviour is exactly as today.
- **`FillTableElementForm.resolved_grid_cells`** passes `self.course`.
- **`FillTableElement.resolved_cells`** (student render) passes nothing and must remain
  byte-identical to today.

The asymmetry is deliberate and worth recording. `FillTableElement.render(self, unit, course, ...)`
receives its course as an *argument*; the element does not own one, so `resolved_cells` — a no-arg
property — has no course to scope against. Read-time scoping is therefore impossible on the student
path. The guarantee there is **validated-at-write**: stored data passed `clean_data`, which enforces
course and kind at save time.

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
the msgid, which is why `locale/en` legitimately carries roughly 1236 blanks. A guard covering English
would be permanently red.

The two duplicated `test_po_catalog_clean` functions are **deleted** from `tests/test_i18n_auth.py`
and `tests/test_i18n_notes.py`, leaving catalog health as one file's responsibility.

`tests/test_i18n_catalog.py` is a **name trap** — it tests the course *catalog page's* translation and
has nothing to do with `.po` catalogs. It must not be modified and must not host the guard.

## Data flow

**Issue B**, on a rejected save: browser POSTs a grid → `clean_data` raises (foreign or wrong-kind
media) → the form is bound-invalid → the template asks for `resolved_grid_cells` → `grid_data` returns
the sanitised submitted payload → `resolve_image_cells(cells, course=self.course)` looks up only
assets that are images in this course → the foreign pk resolves to nothing → the existing unresolved
branch degrades that cell to empty static → the template renders no `<img>` and no URL.

On the student path nothing changes: `resolved_cells` → `resolve_image_cells(cells)` with no course →
identical query, identical output.

**Issue C** is a static analysis of two files on disk. `_entries(path)` parses a `.po` into entries;
each test asserts a property over them. No database, no request cycle.

## Error handling

**Issue B.** `course=None` is the documented no-scoping path, not an error. An unresolvable pk —
whether dangling, foreign, or of the wrong kind — is not an exception: it degrades to an empty static
cell, exactly as a dangling pk already does. The author still sees the real `clean_data` validation
error explaining what was actually wrong; the blank cell is not the only feedback they get.

**Issue C.** The parser must fail loudly rather than silently under-report, since a guard that misses
entries is worse than no guard. Three parsing hazards must be handled explicitly:

1. the header entry (`msgid ""`) is skipped, not reported as untranslated;
2. multi-line concatenated quoted strings are joined before emptiness is judged;
3. **plurals** — the Polish catalog carries 81 `msgstr[N]` lines. An entry counts as untranslated if
   **any** required form is empty, with `nplurals` read from the `Plural-Forms` header rather than
   assumed.

Failure messages list the offending msgids, truncating long ones, so a failure points at its fix
instead of starting a hunt. No `polib` dependency is added; the parser is hand-rolled and kept small.

## Testing

Every task is test-first: write the failing test, confirm it fails **for the stated reason**,
implement, confirm green.

**Issue B.** A test that a rejected save carrying another course's image pk re-renders that cell with
no `<img>` and no URL. Falsified by dropping the `course` argument — it must go red. The existing
`test_unresolvable_image_cell_drops_spans_in_both_render_and_editor` must stay green **and
unmodified**, which is what proves the shared fallback was not forked. Worth covering too: an
in-course asset of the wrong kind (a video pk) degrades identically, since that is the half of the fix
that goes beyond the original review finding.

**Issue C.** The hand-rolled parser is itself the risk, so it must be proven red **twice**, not once:

- blank a real Polish `msgstr` → the guard fails, naming that msgid;
- blank **one form** of a plural entry → the guard also fails.

Both falsifications are reverted afterwards. A single scalar falsification would leave the plural path
— the subtlest branch — unproven.

The full non-e2e suite must pass, and both `uv run ruff check .` and `uv run ruff format --check .`
must be clean; CI gates on them separately.

## Out of scope

- Any change to the student render path's behaviour.
- Giving `FillTableElement` a course of its own (a model change well beyond this fix).
- Authenticating `/media/` — a broader deployment concern, not this defect.
- Extending the untranslated-msgstr guard to English.
- Any migration. Neither issue needs one.
