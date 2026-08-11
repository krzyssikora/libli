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

Three element models hold a `PROTECT` foreign key to `MediaAsset`:

| Model | Location |
|---|---|
| `ImageElement.media` | `courses/models.py:743-745` |
| `VideoElement.media` | `courses/models.py:755+` |
| `DragToImageQuestionElement.media` | `courses/models.py:2630-2632` |

They are the single source of truth for "what can use an asset" — `courses/media.py:20-24` lists
exactly these three, and usage counts, the manager's annotations and the "where used" list all
derive from that tuple.

Crucially, **every one of them references `MediaAsset.pk`, never `MediaAsset.file`**. Rendering
reaches the bytes only by traversing the FK. So mutating `file` on the row changes what every
consuming unit displays, with no unit edits, no re-pointing, and no data migration. The entire
feature is one row update plus the disk hygiene that update implies.

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

### The three things that are not free

**1. Deleting the old file is not automatic.** `courses/signals.py:10-32` purges an asset's file from
storage, but it is a `post_delete` receiver on `MediaAsset` — it fires when a *row* dies. A replace
keeps the row alive, so the old file would be orphaned unless the service deletes it explicitly.

That receiver also keys on `file.name` with no check for other rows using the same name, so two
`MediaAsset` rows sharing a name share a lifetime. In production this cannot arise (`create_asset`,
the LAL loader and this design all let storage assign a fresh unique name), but it has arisen from
test fixtures constructing rows with a literal `file="courses/media/x.png"` — see
`courses/tests/test_image_size_render.py:14-19` and three siblings. The replace path therefore
carries the guard the signal lacks.

**2. Kind cannot change.** `ImageElement.media` and `DragToImageQuestionElement.media` both carry
`limit_choices_to={"kind": "image"}`, and `MediaAsset.clean()` (`courses/models.py:716-727`) picks
its validator by `self.kind`. An image asset must stay an image asset.

**3. Drag-to-image drop zones are stored as fractions of the image.** `DragZone.x/y/w/h` are
`FloatField`s documented as "fraction 0..1 of image width/height"
(`courses/models.py:2666-2669`). Replacing a drag-to-image background with a file of a different
aspect ratio leaves the numbers valid but the zones visually misplaced. This is the one way a
replace can silently degrade content.

## Scope

**In scope**

- A replace action on every asset cell in the media manager, for both `image` and `video` assets.
- Same-kind replacement only.
- Immediate deletion of the superseded file, guarded against a shared filename.
- An inline confirm step that names the chosen file and warns when drop zones are at risk.

**Out of scope, deliberately**

- **Changing `courses/signals.py`.** The `post_delete` receiver's missing shared-name guard is a
  real latent hazard, but widening delete semantics is a separate decision with its own tests. This
  design adds the guard to the new code path only.
- **Retro-cleaning already-orphaned files.** Files stranded by the current workaround stay stranded;
  reclaiming them is a management command, not a UI action.
- **A replace affordance inside the element editor's media picker.** The picker chooses *which*
  asset an element uses; replace changes what an asset *is*. Different concern, different surface.
- **Cross-kind replacement** (image ⇄ video), which the FK constraints forbid.
- **Recomputing `content_hash`.** See "Rejected alternatives".
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
    asset.full_clean()
    asset.save(update_fields=["file", "original_filename", "content_hash"])
    _delete_file_if_unshared(old_name, old_storage, exclude_pk=asset.pk)
    return asset
```

Five properties fall out of that ordering, each load-bearing:

- **`kind` is never assigned, so the kind lock is structural rather than a check.**
  `full_clean()` calls `MediaAsset.clean()`, which branches on the *unchanged* `self.kind` and runs
  `validate_image_file` or `validate_video_file` accordingly (`courses/validators.py:98-115`).
  Uploading an `.mp4` onto an image asset therefore fails the existing image-extension validator and
  surfaces the existing message. No new validation code, and no way for the two to drift apart.
- **Size limits come along for free**, from the same admin-configured effective limits the upload
  path uses.
- **`old_name`/`old_storage` are captured before the assignment**, because assigning to `asset.file`
  replaces the `FieldFile` that would otherwise answer for them.
- **The new file is written under a fresh, unique storage name.** `FileField.pre_save` calls
  `get_available_name`, which never returns a name already on disk — so the new file cannot collide
  with the old one, and because the URL changes, no browser or CDN can serve stale bytes for the new
  content. `file` is in `update_fields`, which is what makes that `pre_save` run at all.
- **Validation precedes persistence**, so a rejected file leaves the DB row and the old file
  untouched. The in-memory `asset` is left mutated, which is safe only because the view discards it
  on the error path (it renders `_op_error.html`, never the cell).

`name` is deliberately absent from `update_fields`: an author's custom display name survives a
replace, while `original_filename` follows the new file. `display_name` is
`self.name or self.original_filename` (`courses/models.py:709-711`), so a cell with no custom name
retitles itself to the new filename — correct, since it is now a different file.

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

### 3. View + URL

`media_replace(request, slug, pk)` in `courses/views_media.py`, shaped exactly like `media_upload`:

1. `course = _require_manage(request, slug)`.
2. `asset = get_object_or_404(MediaAsset, pk=pk, course=course)` — the `course=course` filter is what
   makes a cross-course pk a 404 rather than a cross-tenant write.
3. Reject a request with no uploaded file as a 422 (`request.FILES` empty), matching how
   `MediaAssetForm` treats a missing file on upload.
4. `media_svc.replace_asset(asset, request.FILES["file"])`, catching `ValidationError` and rendering
   `courses/manage/_op_error.html` with status 422 and the joined messages.
5. On success, `media_svc.attach_usage(asset)` then render
   `courses/manage/media/_asset_cell.html`.
6. Non-fragment requests redirect to `courses:manage_media` on both paths, like every sibling op.

`MediaAssetForm` is **not** reused: its fields are `["kind", "file"]` and `kind` is precisely what a
replace must not accept from the client. Presence is checked directly; content validation belongs to
`full_clean()` either way.

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

Inside the existing `{% with uses=... %}` block, the `.asset-foot` gains a replace control beside
the delete form:

- a `<button type="button" class="iconbtn" data-replace-asset="{{ asset.pk }}">` carrying the glyph,
  an `aria-label` and a `title`;
- a sibling `<input type="file" hidden data-replace-input accept="image/*">` (or `video/*`, chosen
  by `asset.kind`) scoped to this cell;
- `data-replace-url="{% url 'courses:manage_media_replace' slug=course.slug pk=asset.pk %}"` and
  `data-di-uses="{{ asset.di_uses|default:0 }}"` on the `.asset-cell` root, alongside the existing
  `data-asset-id` / `data-kind` / `data-url` / `data-name`.

The button is **not** disabled when the asset is in use — unlike delete, replace is *for* in-use
assets.

**Glyph choice.** A text glyph (`⇄`), not an SVG. The repo's icon convention is monochrome SVG using
`currentColor`, but the two controls this one sits between are the text glyphs `✎` and `🗑`, and a
lone SVG among them would read as a mistake. Converting all three is a cosmetic change outside this
design's scope.

**No no-JS path.** Replace is a JS-only affordance, matching the rename pencil, which is also
JS-only. The endpoint still accepts an ordinary multipart POST, which is what the view tests drive.

### 5. JS — `courses/static/courses/js/media_picker.js`

A fourth op inside `wireManager`, delegated from `root` like the delete and rename handlers:

1. **Click** on `[data-replace-asset]` → `input.click()` on that cell's `[data-replace-input]`.
2. **`change`** on the input (a cancelled OS file dialog fires nothing, so there is no dismissal to
   handle) → replace the cell's `.asset-foot` contents with an inline confirm strip built from:
   - `msg(root, "replace-confirm", "Replace with {file}?")` with `{file}` substituted for the chosen
     filename, inserted via `textContent` so a crafted filename cannot inject markup;
   - `msg(root, "replace-drag-warning", …)` appended only when the cell's `data-di-uses` is greater
     than zero;
   - a **Replace** and a **Cancel** button.
3. **Cancel** → restore the saved `.asset-foot` node and clear `input.value` (so re-choosing the
   same file fires `change` again).
4. **Replace** → `POST` the cell's `data-replace-url` with a `FormData` carrying `file`, the
   `X-CSRFToken` header and `X-Requested-With: fetch`, exactly as `uploadFile` does
   (`media_picker.js:240-249`). 200 → swap the whole `.asset-cell` for the returned HTML (the rename
   handler's `cell.replaceWith(fresh)` pattern). 422 → restore the foot and `flash` the server's
   message. Network failure → restore the foot and flash, so the cell can never wedge.

A `done` re-entrancy flag guards the commit path, as the rename handler's does
(`media_picker.js:330-334`).

Translatable strings reach JS the way the existing conflict message does: as `data-msg-*` attributes
rendered with `{% trans %}` on the `.media-manager` root (`manager.html:6-10`), read back through
`msg(host, key, fallback)` (`media_picker.js:234`).

The drag caution reads: *"Used by a drag-to-image question. Drop zones are stored as fractions of the
image, so a file with a different shape will move them."* It warns and never blocks — the affected
units are already enumerated one line above, in the existing "in use ×N" `<details>` list.

## Data flow

**Happy path.** Click ⇄ → OS file dialog → `change` → confirm strip → Replace → `POST
…/media/<pk>/replace/` → `replace_asset` validates against the unchanged `kind`, writes the new file
under a fresh storage name, updates three columns, and registers the old file's deletion for commit
→ view re-renders the cell → JS swaps it in. The old file leaves disk after the transaction commits.
Every `ImageElement` / `VideoElement` / `DragToImageQuestionElement` row is byte-for-byte unchanged;
their next render resolves the FK and serves the new bytes.

**Rejected file.** Wrong extension for the asset's kind, or over the size limit → `full_clean()`
raises → the transaction rolls back → 422 with the validator's message → JS restores the foot. The
row, the old file and every consuming element are untouched.

**Cancel.** No request is made; the foot is restored and the file input cleared.

## Error handling

| Condition | Response |
|---|---|
| Not a course manager | `PermissionDenied` from `_require_manage`, as every sibling op |
| `pk` belongs to another course | 404 from `get_object_or_404(..., course=course)` |
| No file in `request.FILES` | 422, `_op_error.html` |
| Wrong extension for the asset's kind | 422, the existing per-kind extension message |
| File over the effective size limit | 422, the existing "too large (max N MiB)" message |
| Old file already missing from storage | No-op — `_delete_file_if_unshared` checks `storage.exists` |
| Another row shares the old `file` name | Old file kept; only the row moves on |
| Non-fragment (no-JS) request | Redirect to `courses:manage_media`, as every sibling op |

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
(`courses/models.py:698-699`).

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
attribute (JS): the button's `aria-label`/`title`, the confirm question, the drag caution, the
Replace and Cancel labels, and the failure flash. Polish translations are added to
`locale/pl/LC_MESSAGES/django.po` and the catalog recompiled, with any `#, fuzzy` pre-fill on a new
entry cleared rather than accepted.

## Testing

**Service (`tests/test_media_model.py` or a new `tests/test_media_replace.py`)**

- A replace preserves `pk`, `kind` and a custom `name`; updates `original_filename`; clears
  `content_hash`; and leaves `ImageElement.media_id` unchanged, with the element still resolving to
  the new file.
- The superseded file is gone from storage after the transaction commits.
- When a second `MediaAsset` row points at the same `file` name, the superseded file **stays** on
  disk.
- An `.mp4` onto an image asset raises `ValidationError`; the row's `file`, `original_filename` and
  `content_hash` are unchanged and the old file is still on disk.
- A file over the effective limit raises `ValidationError`, with the same untouched-row assertions.
- A missing old file on disk does not raise.

**View (`tests/test_media_manager.py`)**

- Non-manager → denied. A `pk` from another course → 404.
- No file posted → 422.
- A valid replace returns the re-rendered cell with the new `original_filename` and the preserved
  display name.
- A rejected file returns 422 carrying the validator's message.
- A non-fragment POST redirects to `courses:manage_media`.

**E2e (`tests/test_e2e_media_picker.py`)**

- In the manager, replace an image that an `ImageElement` in a unit uses: the confirm strip appears
  naming the chosen file, Replace swaps the cell, the cell shows the new filename, and the unit page
  then renders an `<img>` whose `src` is the new file. Files are supplied with `set_input_files` on
  the hidden input, which Playwright permits without the input being visible.
- Cancel leaves the cell and the asset unchanged, and makes no request.
- For an asset backing a drag-to-image question, the confirm strip additionally shows the caution;
  for one that does not, it does not.

Per the repo's testing convention, each new test is falsified against a deliberately broken variant
before being trusted — in particular the shared-filename guard (which passes trivially if the delete
never runs at all) and the "unchanged on rejection" assertions (which pass trivially if the view
short-circuits earlier than intended).
