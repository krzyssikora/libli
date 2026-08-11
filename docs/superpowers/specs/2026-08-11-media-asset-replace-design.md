# Replace a media asset's file in place

## Purpose

An author who wants to swap the picture behind an already-used media asset — a redrawn diagram, a
re-exported figure, a compressed version of an oversized photo — has no way to do it. The media
manager offers **rename** (the pencil) and **delete** (the trash), and delete is refused outright
while the asset is in use (`courses/media.py:127-134`).

So the only route today is: upload the new file as a *second* asset, open every unit that uses the
old one, re-point each element by hand, and only then delete the original. That is laborious in
proportion to how widely the asset is used, and because the last step is the one nobody gets to, the
superseded files accumulate on disk indefinitely.

This design adds a third action to the asset cell — **replace** — that swaps the bytes behind an
existing `MediaAsset` row while leaving the row's primary key alone. Every element that references
it keeps working, untouched, because none of them reference the file.

## Background — why this is cheap

**Every consumer of a media asset addresses it by primary key. None of them store the file path.**
That is the single fact the whole feature rests on, and it holds across two different reference
mechanisms.

**FK-tracked consumers** — three element models hold a `PROTECT` foreign key to `MediaAsset`:

| Model | Field | Location |
|---|---|---|
| `ImageElement` | `media` | `courses/models.py:748-750` |
| `VideoElement` | `media` (`null=True`) | `courses/models.py:762-768` |
| `DragToImageQuestionElement` | `media` | `courses/models.py:2683-2684` |

`courses/media.py:20-24` (`_MEDIA_REF_MODELS`) lists exactly these three. It is the source of truth
for the manager's *usage tracking* — `usage_count`, the grid's count annotations and the "where
used" list all derive from that tuple.

**JSON-pk consumers** — three further element models store `MediaAsset` **primary keys inside their
JSON `data`** and resolve them at render time through `MediaAsset.objects.in_bulk`:

| Model | Resolver | Location |
|---|---|---|
| `TableElement` | `resolved_cells` | `courses/models.py:1259-1266` |
| `FillTableElement` | `resolved_cells` | `courses/models.py:1485-1493` |
| `GalleryElement` | `resolved_images` | `courses/models.py:1546-1557` |

These have no FK, so they appear in neither `_MEDIA_REF_MODELS` nor any usage count.

**For replace, the distinction does not matter and the design is safe either way:** both mechanisms
resolve a pk to a row and read `row.file` at render time, so swapping the row's file updates all six
consumers with no edits to any of them.

**For the author's information, the distinction does matter, and this design does not fix it.** An
asset used *only* by a gallery or a table image cell already displays as "unused" in the manager,
because the usage machinery cannot see JSON references. That author therefore gets no impact
indication before replacing it — exactly as they get no warning before *deleting* it today
(`usage_count` returns 0, so `delete_asset` permits it; the resolvers are written to degrade to a
skipped image rather than 500 a lesson). Extending usage tracking to JSON references is a
pre-existing gap and is **out of scope**; this spec records it so the limitation is a known one
rather than a surprise.

### What the manager already does

`courses/views_media.py` implements four operations against `courses/media.py` services, all
following one shape: `_require_manage(request, slug)` for authorisation, a `ValidationError` rendered
as `courses/manage/_op_error.html` with status 422, a success path that re-renders a single
`courses/manage/media/_asset_cell.html` after `media_svc.attach_usage(asset)`, and a
`_wants_fragment(request)` check (`X-Requested-With: fetch`,
`courses/views_manage.py:1330-1331`) that redirects to `courses:manage_media` for the no-JS path.

`courses/static/courses/js/media_picker.js` progressively enhances three of them in `wireManager`:
upload (`:266-278`), delete (`:302-317`) and inline rename (`:319-355`). Replace becomes the fourth,
and reuses their conventions rather than inventing new ones.

### The four things that are not free

**1. Deleting the old file is not automatic.** `courses/signals.py:10-32` purges an asset's file from
storage, but it is a `post_delete` receiver on `MediaAsset` — it fires when a *row* dies. A replace
keeps the row alive, so the old file would be orphaned unless the service deletes it explicitly.

That receiver also keys on `file.name` with no check for other rows using the same name, so two
`MediaAsset` rows sharing a name share a lifetime. In production this cannot arise (`create_asset`,
the LAL loader and this design all let storage assign a name), but it has arisen from test fixtures
constructing rows with a literal `file="courses/media/x.png"` — see
`courses/tests/test_image_size_render.py:14-19` and three siblings. The replace path therefore
carries the guard the signal lacks.

**2. Deleting the old file can delete the *new* one.** `Storage.get_available_name` only avoids names
that currently exist on disk. If the old file is already **missing** from storage — a row whose bytes
were lost, or any fixture row built with a literal `file=` and no bytes — then an upload sharing that
basename is written to the *same* name, and a naive "delete the old name after saving" would destroy
the file just written. The same holds on any overwrite-style storage backend. The service must
therefore compare names, not assume they differ.

**3. `full_clean()` on an existing row validates fields the replace never touches.**
`MediaAsset.uploaded_by` is declared `null=True` **without** `blank=True`
(`courses/models.py:709-711`), so `Model.clean_fields()` raises `"This field cannot be blank."` for
any row whose uploader is `NULL`. That is every asset created by the LAL importer
(`courses/lal_loader/media.py:35-47` never sets `uploaded_by`) plus every asset whose uploader
account was later deleted — the FK is `SET_NULL` precisely so that happens. `create_asset` never hit
this because `media_upload` is `@login_required` and always passes a real user; replace is the first
path to validate an *existing* row, and an unscoped `full_clean()` there would 422 the entire
imported catalogue with a meaningless message.

**4. Drag-to-image drop zones are stored as fractions of the image.** `DragZone.x/y/w/h` are
`FloatField`s documented as "fraction 0..1 of image width/height"
(`courses/models.py:2719-2722`). Replacing a drag-to-image background with a file of a different
aspect ratio leaves the numbers valid but the zones visually misplaced. This is the one way a
replace can silently degrade content.

## Scope

**In scope**

- A replace action on every asset cell in the media manager, for both `image` and `video` assets.
- Same-kind replacement only.
- Immediate deletion of the superseded file, guarded against a shared filename and against the
  old and new names being identical.
- An inline confirm step that names the chosen file and warns when drop zones are at risk.

**Out of scope, deliberately**

- **Changing `courses/signals.py`.** The `post_delete` receiver's missing shared-name guard is a
  real latent hazard, but widening delete semantics is a separate decision with its own tests. This
  design adds the guard to the new code path only.
- **Extending usage tracking to the JSON-pk consumers**, per the Background note above.
- **Retro-cleaning already-orphaned files.** Files stranded by the current workaround stay stranded;
  reclaiming them is a management command, not a UI action.
- **A replace affordance inside the element editor's media picker.** The picker chooses *which*
  asset an element uses; replace changes what an asset *is*. Different concern, different surface.
- **Cross-kind replacement** (image ⇄ video), which the FK constraints forbid.
- **Recomputing `content_hash`.** See "Rejected alternatives".
- **A per-replace audit trail.** See the `uploaded_by` / `created` decision below.
- **Undo.** The superseded bytes are gone once the replace commits.

## Architecture

### 1. `courses/media.py::replace_asset(asset, uploaded_file)`

A new service beside `create_asset`/`rename_asset`/`delete_asset`, wrapped in
`@transaction.atomic`:

```python
@transaction.atomic
def replace_asset(asset, uploaded_file):
    """Swap the bytes behind an existing asset, preserving pk, kind and name so every
    element referencing it is untouched. The superseded file is removed from storage."""
    old_name = asset.file.name
    old_storage = asset.file.storage
    asset.file = uploaded_file
    asset.original_filename = truncate_filename(uploaded_file.name)
    asset.content_hash = ""
    # Validate exactly the fields this operation writes. A bare full_clean() would
    # reject every LAL-imported asset: uploaded_by is null=True WITHOUT blank=True,
    # so clean_fields() raises "This field cannot be blank." on a NULL uploader.
    # clean() runs regardless of `exclude`, and still branches on the untouched
    # self.kind — which is where the per-kind file validation lives.
    asset.full_clean(exclude=["course", "kind", "name", "uploaded_by", "created"])
    asset.save(update_fields=["file", "original_filename", "content_hash"])
    # Storage may hand back the SAME name when the old file was already missing (or
    # on an overwrite-style backend), in which case the "old" file IS the new one.
    if asset.file.name != old_name:
        _delete_file_if_unshared(old_name, old_storage, exclude_pk=asset.pk)
    return asset
```

Properties that fall out of that ordering, each load-bearing:

- **`kind` is never assigned, so the kind lock is structural rather than a check.**
  `full_clean()` calls `MediaAsset.clean()` (`courses/models.py:721-732`), which branches on the
  *unchanged* `self.kind` and runs `validate_image_file` or `validate_video_file` accordingly
  (`courses/validators.py:98-115`). Uploading an `.mp4` onto an image asset therefore fails the
  existing image-extension validator and surfaces the existing message. No new validation code, and
  no way for the two to drift apart.
- **Size limits come along for free**, from the same admin-configured effective limits the upload
  path uses.
- **`old_name`/`old_storage` are captured before the assignment**, because assigning to `asset.file`
  replaces the `FieldFile` that would otherwise answer for them.
- **`file` must be in `update_fields`** — that is what makes `FileField.pre_save` run and commit the
  upload to storage at all.
- **Validation precedes persistence**, so a rejected file leaves the DB row and the old file
  untouched. The in-memory `asset` is left mutated, which is safe only because the view discards it
  on the error path (it renders `_op_error.html`, never the cell) — and which is why the tests
  re-fetch the row rather than assert on that instance.

**Fields deliberately not updated.**

- `name` — an author's custom display name survives a replace, while `original_filename` follows the
  new file. `display_name` is `self.name or self.original_filename`
  (`courses/models.py:714-716`), so a cell with no custom name retitles itself to the new filename,
  which is correct: it *is* a different file now.
- `uploaded_by` — records who created the row, not who last changed its bytes. Keeping it avoids
  implying an audit trail the model cannot actually keep (there is one column, not a history), and a
  per-replace audit trail is out of scope.
- `created` — likewise records the row's creation. Note the visible consequence:
  `assets_with_usage` orders by `-created` (`courses/media.py:85`), so a replaced asset keeps its
  position in the grid rather than jumping to the front. That is intended — the grid is ordered by
  when the *asset* was added, and an author who just replaced a file is already looking at its cell.

### 2. `courses/media.py::_delete_file_if_unshared(name, storage, exclude_pk)`

```python
def _delete_file_if_unshared(name, storage, exclude_pk):
    """Drop a superseded file from storage, unless another MediaAsset row still points
    at the same name (see the post_delete receiver's missing guard in courses/signals.py)."""
    if not name:
        return
    if MediaAsset.objects.filter(file=name).exclude(pk=exclude_pk).exists():
        return

    def _remove():
        if storage.exists(name):
            storage.delete(name)

    transaction.on_commit(_remove)
```

`transaction.on_commit` mirrors the signal's deferral for the same reason: a rolled-back replace
must not strand a live row whose file has already been deleted. Registered inside the enclosing
`atomic`, it fires after the outermost commit.

The identity check that protects against deleting the newly written file lives in the **caller**
(above), not here, because only the caller knows the asset's post-save name.

### 3. View + URL

`media_replace(request, slug, pk)` in `courses/views_media.py`, decorated `@login_required` and
`@require_POST` (`django.views.decorators.http`, already used at `courses/views.py:830` and
elsewhere), then shaped like `media_upload`:

1. `course = _require_manage(request, slug)`.
2. `asset = get_object_or_404(MediaAsset, pk=pk, course=course)` — the `course=course` filter is what
   makes a cross-course pk a 404 rather than a cross-tenant write.
3. `if "file" not in request.FILES:` → 422. The guard tests **the key**, not
   `request.FILES` emptiness: a multipart POST carrying some other field name would otherwise pass an
   emptiness check and then raise `MultiValueDictKeyError` (a 500) on the access below. The wire
   field name is `file`, matching `MediaAssetForm` and `uploadFile`.
4. `media_svc.replace_asset(asset, request.FILES["file"])`, catching `ValidationError` and rendering
   `courses/manage/_op_error.html` with status 422 and the joined messages.
5. On success, `media_svc.attach_usage(asset)` then render
   `courses/manage/media/_asset_cell.html`.
6. Non-fragment requests redirect to `courses:manage_media` on both paths, like every sibling op.

`@require_POST` is a deliberate divergence from the sibling ops, which have no method guard: a GET to
a mutating endpoint should be a 405, and there is no reason to inherit that gap into new code.

`MediaAssetForm` is **not** reused: its fields are `["kind", "file"]` and `kind` is precisely what a
replace must not accept from the client. Presence is checked directly; content validation belongs to
`full_clean()` either way. A test pins this (see Testing), because the whole reason for hand-rolling
the view is otherwise invisible to a future refactor.

URL, appended to the media block at `courses/urls.py:271-296`:

```python
path(
    "manage/courses/<slug:slug>/media/<int:pk>/replace/",
    views_media.media_replace,
    name="manage_media_replace",
),
```

`<int:pk>/replace/` matches `manage_media_delete`'s shape rather than `manage_media_rename`'s
POST-body id, because replace, like delete, addresses one asset.

### 4. Template — `templates/courses/manage/media/_asset_cell.html`

The `.asset-cell` root gains two data attributes beside the existing
`data-asset-id` / `data-kind` / `data-url` / `data-name`:

- `data-replace-url="{% url 'courses:manage_media_replace' slug=course.slug pk=asset.pk %}"`
- `data-di-uses="{{ asset.di_uses|default:0 }}"`

It gains one **direct child**, deliberately *outside* `.asset-foot`:

```html
<input type="file" name="file" hidden data-replace-input
       accept="{% if asset.kind == 'image' %}image/*{% else %}video/*{% endif %}">
```

Keeping the input outside the foot matters: the confirm strip is added and removed inside the cell,
and an input that lived in a region the JS manipulates could be detached while a reference to it is
still held (making `input.value = ""` a no-op on the live DOM).

Inside `.asset-foot`, next to the delete form, a replace control:

```html
<button type="button" class="iconbtn" data-replace-asset="{{ asset.pk }}"
        aria-label="{% trans 'Replace file' %}" title="{% trans 'Replace file' %}">⇄</button>
```

The button is **not** disabled when the asset is in use — unlike delete, replace is *for* in-use
assets.

**`accept` is a hint, not the authority.** `effective_image_extensions()`
(`courses/validators.py:65`) lets an admin narrow the accepted set, so the OS dialog may offer a file
the server then rejects with a 422. That is acceptable: the 422 carries the real message, and
rendering the effective list into the attribute would duplicate the admin-configured limits into the
template for no correctness gain.

**Glyph choice.** A text glyph (`⇄`), not an SVG. The repo's icon convention is monochrome SVG using
`currentColor`, but the two controls this one sits between are the text glyphs `✎` and `🗑`, and a
lone SVG among them would read as a mistake. Converting all three is a cosmetic change outside this
design's scope.

**No no-JS path.** Replace is a JS-only affordance, matching the rename pencil, which is also
JS-only. The endpoint still accepts an ordinary multipart POST, which is what the view tests drive.

### 5. JS — `courses/static/courses/js/media_picker.js`

A fourth op inside `wireManager`, delegated from `root` like the delete and rename handlers.

1. **Click** on `[data-replace-asset]` → if any confirm strip is currently open anywhere in the grid,
   close it first (cancel semantics: strip removed, its input cleared); then `input.click()` on this
   cell's `[data-replace-input]`. At most one strip is open at a time. A click on a cell whose own
   strip is already open is ignored.
2. **`change`** on the input (a cancelled OS file dialog fires nothing, so there is no dismissal to
   handle) → **append** a confirm strip to `.asset-cell`, *after* `.asset-foot`. The foot is neither
   replaced nor emptied, so the existing "in use ×N" summary and its expandable unit list stay on
   screen while the author decides — which is what makes a non-blocking warning defensible.

   The strip contains:
   - a label from `msg(root, "replace-confirm", "Replace with:")` — no interpolation token;
   - the chosen filename in its **own** element, set via `textContent`, so a crafted filename cannot
     inject markup and no translated string can lose a placeholder;
   - `msg(root, "replace-drag-warning", …)`, appended only when the cell's `data-di-uses` is greater
     than zero;
   - a **Replace** and a **Cancel** button.
3. **Cancel** → remove the strip node and set `input.value = ""` on the cell's persistent input, so
   re-choosing the same file fires `change` again.
4. **Replace** → `POST` the cell's `data-replace-url` with a `FormData` carrying `file`, the
   `X-CSRFToken` header and `X-Requested-With: fetch`, exactly as `uploadFile` does
   (`media_picker.js:240-249`).
   - **200** → swap the whole `.asset-cell` for the returned HTML (the rename handler's
     `cell.replaceWith(fresh)` pattern). The strip and the input go with the old node.
   - **422** → remove the strip, clear the input, and flash the server's message. The body is an
     `_op_error.html` fragment, not a bare string, so it is parsed by assigning the response text to a
     detached element's `innerHTML`, reading `querySelector(".op-error")`'s `textContent`, and passing
     that **string** to `flash()`. `flash` sets `textContent` (`media_picker.js:6-9`), so nothing
     server-echoed is ever inserted as markup. If the fragment has no `.op-error`, fall back to
     `msg(root, "replace-failed", "Could not replace the file.")`.
   - **Network failure** → same as 422 with the canned fallback message, so the cell can never wedge.

A `done` re-entrancy flag guards the commit path, as the rename handler's does
(`media_picker.js:330-334`).

Translatable strings reach JS the way the existing conflict message does: as `data-msg-*` attributes
rendered with `{% trans %}` on the `.media-manager` root (`manager.html:6-10`), read back through
`msg(host, key, fallback)` (`media_picker.js:234`).

The drag caution reads: *"Used by a drag-to-image question. Drop zones are stored as fractions of the
image, so a file with a different shape will move them."*

## Data flow

**Happy path.** Click ⇄ → OS file dialog → `change` → confirm strip appears below the still-visible
foot → Replace → `POST …/media/<pk>/replace/` → `replace_asset` validates against the unchanged
`kind`, writes the new file, updates three columns, and (unless the storage name is unchanged)
registers the old file's deletion for commit → view re-renders the cell → JS swaps it in. The old
file leaves disk after the transaction commits. Every `ImageElement` / `VideoElement` /
`DragToImageQuestionElement` row is byte-for-byte unchanged, and every `TableElement` /
`FillTableElement` / `GalleryElement` JSON blob is untouched; their next render resolves the pk and
serves the new bytes.

**Rejected file.** Wrong extension for the asset's kind, or over the size limit → `full_clean()`
raises → the transaction rolls back → 422 with the validator's message → JS removes the strip and
flashes. The row, the old file and every consuming element are untouched.

**Cancel.** No request is made; the strip is removed and the file input cleared.

## Error handling

| Condition | Response |
|---|---|
| GET (or any non-POST) | 405 from `@require_POST` |
| Not a course manager | `PermissionDenied` from `_require_manage`, as every sibling op |
| `pk` belongs to another course | 404 from `get_object_or_404(..., course=course)` |
| No `file` key in `request.FILES` | 422, `_op_error.html` |
| Wrong extension for the asset's kind | 422, the existing per-kind extension message |
| File over the effective size limit | 422, the existing "too large (max N MiB)" message |
| Asset row with `uploaded_by = NULL` | Replaces normally — `uploaded_by` is excluded from validation |
| Storage returns the same name as the old file | Deletion skipped; the row keeps the file just written |
| Old file already missing from storage | No-op — `_delete_file_if_unshared` checks `storage.exists` |
| Another row shares the old `file` name | Old file kept; only the row moves on |
| Non-fragment (no-JS) POST | Redirect to `courses:manage_media`, as every sibling op |

**Accepted limitation — orphaned bytes on rollback.** If the transaction rolls back *after*
`save()` has written the new file, that file is left on disk with no row pointing at it. This is
exactly `create_asset`'s existing behaviour (Django commits `FileField` writes to storage outside
transactional control), so replace inherits a known property rather than introducing one.

**Accepted limitation — concurrent replace.** Two managers replacing the same asset simultaneously
resolve last-write-wins on the row. Each transaction deletes only the old name *it* observed, and the
loser's uploaded file is left orphaned. The consequence is one stranded file, never a broken
reference or a deleted live file, and the manager is a single-author surface; serialising with
`select_for_update` is not worth the added lock.

## Rejected alternatives

**Recompute `content_hash` instead of clearing it.** The stored SHA-256 is the LAL importer's
durable dedup key: `get_or_create_asset` returns any existing row whose `(course, content_hash)`
matches (`courses/lal_loader/media.py:35-47`). Leaving a stale hash would make a later import hand
back an asset whose bytes no longer match, so the field must not simply be left alone. Recomputing
is defensible, but `_sha256` lives in `courses/lal_loader/media.py:31-32`, and importing it into
`courses/media.py` inverts the dependency (the loader is a consumer of the services, not a provider).
Clearing costs nothing, is what the manager's own `create_asset` already produces, and the field is
explicitly documented as "Blank on assets created before/without hashing"
(`courses/models.py:703-704`).

**Block replacement on drag-to-image assets.** Rejected as over-strict: the common case — the same
diagram, redrawn or re-exported at the same proportions — is entirely safe, and a blanket ban would
force the author back into the manual re-pointing this feature exists to remove.

**Detect the aspect-ratio change and warn only when it differs.** More precise, but it means reading
image dimensions server-side and choosing a tolerance, for a warning that is cheap to show
unconditionally and that an author can act on with the information already in the cell.

**A `window.confirm()` dialog.** Fewer lines, but unstyleable, a new pattern for this file, and
Playwright auto-dismisses `confirm()` unless a `dialog` listener is registered — a trap that makes
e2e tests fail against correct code.

## i18n

Every new user-facing string is wrapped in `{% trans %}` (template) or rendered into a `data-msg-*`
attribute (JS): the button's `aria-label`/`title`, the confirm label, the drag caution, the Replace
and Cancel labels, and the failure fallback. **No string carries an interpolation placeholder** — the
filename is a separate DOM node — so no translation, fuzzy pre-fill included, can break the strip by
dropping a token. Polish translations are added to `locale/pl/LC_MESSAGES/django.po` and the catalog
recompiled, with any `#, fuzzy` pre-fill on a new entry cleared rather than accepted.

## Testing

**Shared mechanics for every service/view test that touches storage.** Redirect
`settings.MEDIA_ROOT` to `tmp_path` before any asset is created — these are the first tests in the
repo whose *subject* is a file deletion, and without the redirect a stray run operates on the working
tree's real `media/` directory. `tests/conftest.py:379-385` already establishes this pattern. Any
assertion about a file being gone must run inside
`django_capture_on_commit_callbacks(execute=True)`, since `_delete_file_if_unshared` defers through
`transaction.on_commit` and those callbacks never fire under the plain `db` fixture —
`tests/test_media_model.py:28,51` is the model to follow. The shared-filename test must run inside
the same capture block, or it passes for the wrong reason (nothing ran at all). Assertions about a
row being *unchanged* run against a freshly fetched `MediaAsset.objects.get(pk=…)`, never against the
instance the service just mutated in memory.

**Service (new `tests/test_media_replace.py`)**

- A replace preserves `pk`, `kind` and a custom `name`; updates `original_filename`; clears
  `content_hash`; leaves `uploaded_by` and `created` unchanged; and leaves `ImageElement.media_id`
  unchanged, with the element still resolving to the new file.
- The superseded file is gone from storage after commit.
- **`uploaded_by = NULL`** (the LAL-import shape) replaces successfully — the regression test for the
  `full_clean` exclusion.
- When a second `MediaAsset` row points at the same `file` name, the superseded file **stays** on
  disk.
- **Identical storage name:** an asset whose file is *absent* from storage, replaced by an upload with
  the same basename, ends with its file present on disk.
- A `GalleryElement` (or `TableElement` image cell) referencing the asset by JSON pk resolves to the
  new file after a replace.
- **Video:** replacing a video asset preserves `kind="video"` and `VideoElement.media_id`, and swaps
  the file.
- **Rejections**, each asserting the re-fetched row's `file`, `original_filename` and `content_hash`
  are unchanged and the old file is still on disk: an `.mp4` onto an image asset; a `.png` onto a
  video asset; a file over the effective size limit.
- A missing old file on disk does not raise.

**View (`tests/test_media_manager.py`)**

- GET → 405. Non-manager → denied. A `pk` from another course → 404.
- No `file` key posted → 422 (including a multipart POST whose file is under a *different* key, which
  must be a 422 and not a 500).
- A valid replace returns the re-rendered cell with the new `original_filename` and the preserved
  display name.
- **A POST carrying `kind=video` alongside a valid image file, against a `kind="image"` asset,
  returns 200 and leaves `asset.kind == "image"` after `refresh_from_db()`** — the test that keeps a
  future refactor from reintroducing `MediaAssetForm` and with it a client-controlled `kind`.
- A rejected file returns 422 carrying the validator's message.
- A non-fragment POST redirects to `courses:manage_media`.

**E2e (`tests/test_e2e_media_picker.py`)**

- In the manager, replace an image that an `ImageElement` in a unit uses: the confirm strip appears
  naming the chosen file **while the "in use ×N" summary remains visible**, Replace swaps the cell,
  the cell shows the new filename, and the unit page then renders an `<img>` whose `src` is the new
  file. Files are supplied with `set_input_files` on the hidden input, which Playwright permits
  without the input being visible.
- Cancel leaves the cell and the asset unchanged and issues no request. The negative is asserted, not
  slept on: register `page.on("request")` filtered to the replace URL *before* clicking, then — after
  a condition that provably post-dates any request the handler could have made (the strip's removal
  from the DOM) — assert the recorded list is empty.
- For an asset backing a drag-to-image question, the confirm strip additionally shows the caution;
  for one that does not, it does not.

Per the repo's testing convention, each new test is falsified against a deliberately broken variant
before being trusted — in particular the shared-filename guard and the identical-name guard (both of
which pass trivially if the deletion never runs at all), and the "unchanged on rejection" assertions
(which pass trivially if the view short-circuits earlier than intended).
