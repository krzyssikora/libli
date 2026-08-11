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
| `DragToImageQuestionElement` | `media` | `courses/models.py:2683-2685` |

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

`courses/views_media.py` holds five views. **Upload and rename** are the two replace should imitate:
`_require_manage(request, slug)` for authorisation, a `ValidationError` rendered as
`courses/manage/_op_error.html` with status **422**, and a success path that re-renders a single
`courses/manage/media/_asset_cell.html` after `media_svc.attach_usage(asset)`. **Delete diverges** —
its error status is **409** and its success renders `_empty.html`, not a cell
(`views_media.py:127,131`) — so "like the siblings" below always means upload/rename.

What *all* the mutating ops share is the `_wants_fragment(request)` check (`X-Requested-With: fetch`,
`courses/views_manage.py:1330-1331`), re-tested **inside every branch**
(`views_media.py:33-37`, `:48-52`, `:75-82`, `:121-128`), never once at the end, so a no-JS POST
redirects to `courses:manage_media` no matter which branch it lands in.

`courses/static/courses/js/media_picker.js` progressively enhances three of them in `wireManager`:
upload (`:266-278`), delete (`:302-317`) and inline rename (`:319-357`). Replace becomes the fourth,
and reuses their conventions rather than inventing new ones.

### The five things that are not free

**1. Deleting the old file is not automatic.** `courses/signals.py:10-32` purges an asset's file from
storage, but it is a `post_delete` receiver on `MediaAsset` — it fires when a *row* dies. A replace
keeps the row alive, so the old file would be orphaned unless the service deletes it explicitly.

That receiver also keys on `file.name` with no check for other rows using the same name, so two
`MediaAsset` rows sharing a name share a lifetime. In production this cannot arise (`create_asset`,
the LAL loader and this design all let storage assign a name), but it arises readily from test
fixtures constructing rows with a literal `file="courses/media/x.png"` — that exact literal appears
in several fixtures across the suite, including
`courses/tests/test_image_size_render.py:13-19` and `tests/test_e2e_media_picker.py:64`. The replace
path therefore carries the guard the signal lacks.

**2. Deleting the old file can delete the *new* one.** `Storage.get_available_name` only avoids names
that currently exist on disk. If the old file is already **missing** from storage — a row whose bytes
were lost, or any fixture row built with a literal `file=` and no bytes — then an upload sharing that
basename is written to the *same* name, and a naive "delete the old name after saving" would destroy
the file just written. The service must therefore compare names, not assume they differ.

**3. `full_clean()` on an existing row validates fields the replace never touches.**
`MediaAsset.uploaded_by` is declared `null=True` **without** `blank=True`
(`courses/models.py:709-711`), so `Model.clean_fields()` raises `"This field cannot be blank."` for
any row whose uploader is `NULL`. That is every asset created by the LAL importer
(`courses/lal_loader/media.py:35-47` never sets `uploaded_by`) plus every asset whose uploader
account was later deleted — the FK is `SET_NULL` precisely so that happens. `create_asset` never hit
this because `media_upload` is `@login_required` and always passes a real user; replace is the first
path to validate an *existing* row, and an unscoped `full_clean()` there would 422 the entire
imported catalogue with a meaningless message.

**4. Model validation does not reject an empty file; the upload form does.** `media_upload` runs
`MediaAssetForm.is_valid()` first, and Django's `forms.FileField.to_python` raises *"The submitted
file is empty."* when `allow_empty_file` is false and the size is zero. `MediaAsset.clean()` reaches
`_validate_file` (`courses/validators.py:83-95`), which checks the extension and an **upper** size
bound only — there is no lower bound. A replace that relied on model validation alone would accept a
0-byte `.png`, commit it, delete the old file, and (with undo out of scope) permanently destroy the
bytes behind every consuming element. The service must reject an empty upload itself.

**5. Drag-to-image drop zones are stored as fractions of the image.** `DragZone.x/y/w/h` are
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
- The stylesheet rules that confirm step needs.

**Out of scope, deliberately**

- **Changing `courses/signals.py`.** The `post_delete` receiver's missing shared-name guard is a
  real latent hazard, but widening delete semantics is a separate decision with its own tests. This
  design adds the guard to the new code path only.
- **Extending usage tracking to the JSON-pk consumers**, per the Background note above.
- **Retro-cleaning already-orphaned files.** Files stranded by the current workaround stay stranded;
  reclaiming them is a management command, not a UI action.
- **A replace affordance inside the element editor's media picker.** The picker chooses *which*
  asset an element uses; replace changes what an asset *is*. Different concern, different surface.
  (`_asset_cell.html` is included only by `_asset_grid.html`, so the picker is untouched by
  construction.)
- **Cross-kind replacement** (image ⇄ video), which the FK constraints forbid.
- **Recomputing `content_hash`.** See "Rejected alternatives" for the accepted consequence.
- **A per-replace audit trail.** See the `uploaded_by` / `created` decision below.
- **Cache-busting for overwrite-style storage backends.** See the note under Data flow.
- **Undo.** The superseded bytes are gone once the replace commits.

## Architecture

### 1. `courses/media.py::replace_asset(asset, uploaded_file)`

A new service beside `create_asset`/`rename_asset`/`delete_asset`, wrapped in
`@transaction.atomic`. `courses/media.py` gains one import,
`from django.core.exceptions import ValidationError`:

```python
@transaction.atomic
def replace_asset(asset, uploaded_file):
    """Swap the bytes behind an existing asset, preserving pk, kind and name so every
    element referencing it is untouched. The superseded file is removed from storage.

    `uploaded_file` MUST be an uncommitted upload (an InMemory/TemporaryUploadedFile).
    _validate_file short-circuits on a committed FieldFile, so passing one would skip
    BOTH the extension and the size check.
    """
    if not uploaded_file.size:
        # MediaAsset.clean() has no lower size bound; only the upload FORM rejects an
        # empty file. Without this, a 0-byte upload would destroy the old bytes.
        raise ValidationError("The submitted file is empty.")
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
    # Storage hands back the SAME name when the old file was already missing, in
    # which case the "old" file IS the one just written.
    if asset.file.name != old_name:
        _delete_file_if_unshared(old_name, old_storage)
    return asset
```

Properties that fall out of that ordering, each load-bearing:

- **`kind` is never assigned, so the kind lock is structural rather than a check.**
  `full_clean()` calls `MediaAsset.clean()` (`courses/models.py:721-732`), which branches on the
  *unchanged* `self.kind` and runs `validate_image_file` or `validate_video_file` accordingly
  (`courses/validators.py:98-115`). Uploading an `.mp4` onto an image asset therefore fails the
  existing image-extension validator and surfaces the existing message — **provided the file is an
  uncommitted upload**, per the docstring.
- **Upper size limits come along for free**, from the same admin-configured effective limits the
  upload path uses. The *lower* bound is this service's own guard, above.
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

### 2. `courses/media.py::_delete_file_if_unshared(name, storage)`

```python
def _delete_file_if_unshared(name, storage):
    """Drop a superseded file from storage, unless another MediaAsset row still points
    at the same name (see the post_delete receiver's missing guard in courses/signals.py)."""
    if not name:
        return
    if MediaAsset.objects.filter(file=name).exists():
        return

    def _remove():
        if storage.exists(name):
            storage.delete(name)

    transaction.on_commit(_remove)
```

No `exclude_pk` parameter: the only caller runs *after* `asset.save()` and only when the name
actually changed, so the asset's own row already stores the new name and cannot match `file=name`. A
pk-exclusion clause would be dead in every reachable call — and therefore untestable — so it is
omitted rather than written as decoration.

`transaction.on_commit` mirrors the signal's deferral for the same reason: a rolled-back replace
must not strand a live row whose file has already been deleted. Registered inside the enclosing
`atomic`, it fires after the outermost commit.

The identity check that protects against deleting the newly written file lives in the **caller**
(above), not here, because only the caller knows the asset's post-save name.

### 3. View + URL

`media_replace(request, slug, pk)` in `courses/views_media.py`, decorated in this order — matching
the precedent at `courses/views.py:830-831`, and chosen so a non-POST is a 405 regardless of
authentication:

```python
@require_POST      # django.views.decorators.http
@login_required
def media_replace(request, slug, pk):
```

Body, following `media_upload`'s shape:

1. `course = _require_manage(request, slug)`.
2. `asset = get_object_or_404(MediaAsset, pk=pk, course=course)` — the `course=course` filter is what
   makes a cross-course pk a 404 rather than a cross-tenant write.
3. `if "file" not in request.FILES:` → the error response, with message
   `"No file was submitted."`. The guard tests **the key**, not `request.FILES` emptiness: a
   multipart POST carrying some other field name would otherwise pass an emptiness check and then
   raise `MultiValueDictKeyError` (a 500) on the access below. The wire field name is `file`,
   matching `MediaAssetForm` and `uploadFile`.
4. `media_svc.replace_asset(asset, request.FILES["file"])`, catching `ValidationError` and producing
   the error response with the joined messages.
5. On success, `media_svc.attach_usage(asset)` then render
   `courses/manage/media/_asset_cell.html`.

**The error response, in both error branches**, follows upload/rename: check
`_wants_fragment(request)` *inside the branch* — if false, `redirect("courses:manage_media",
slug=course.slug)`; if true, render `courses/manage/_op_error.html` with status **422**. Both error
branches use 422; replace never returns delete's 409, which signals a different condition
(refused-because-in-use) that replace does not have. The success path carries its own fragment check
too. There is no single trailing check, because a no-JS POST must redirect no matter which branch it
lands in.

Error message strings are plain Python literals, **not** wrapped in `gettext` — matching the sibling
ops (`views_media.py:80`, `:126`), which ship untranslated English for the same class of message.
This is a deliberate consistency choice, not an oversight; translating these is a separate sweep
across all four ops.

`MediaAssetForm` is **not** reused: its fields are `["kind", "file"]` and `kind` is precisely what a
replace must not accept from the client. A test pins this (see Testing), because the whole reason for
hand-rolling the view is otherwise invisible to a future refactor.

Not reusing the form does mean this path diverges from upload in two places beyond `kind`. Both are
handled explicitly: the empty-file check is re-implemented in the service (above), and the form's
`max_length=100` check on the *stored* name is not reproduced — `models.FileField` attaches no
`MaxLengthValidator`, so storage silently truncates instead of 422-ing. The shared authority between
the two paths is therefore **extension and size**, not "all validation".

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
- `data-di-uses="{{ asset.di_uses|default:0 }}"` (populated by both `attach_usage` and
  `assets_with_usage`, so every render path has it)

It gains one **direct child**, deliberately *outside* `.asset-foot`:

```html
<input type="file" name="file" hidden data-replace-input
       accept="{% if asset.kind == 'image' %}image/*{% else %}video/*{% endif %}">
```

Keeping the input outside the foot matters: the confirm strip is added and removed inside the cell,
and an input that lived in a region the JS manipulates could be detached while a reference to it is
still held (making `input.value = ""` a no-op on the live DOM).

**The foot's three controls.** `.asset-foot` is `display: flex; justify-content: space-between` with
exactly two children today: the uses summary and the `display: contents` delete form
(`editor.css:724,732`). Adding a third child would redistribute the row inside a ~128px grid cell, so
the replace button and the delete form are wrapped together:

```html
<div class="asset-actions">
  <button type="button" class="iconbtn" data-replace-asset="{{ asset.pk }}"
          aria-label="{% trans 'Replace file' %}" title="{% trans 'Replace file' %}">⇄</button>
  <form class="asset-del" …>…</form>
</div>
```

The foot keeps two flex children, so `space-between` still pins the uses summary left and the actions
right; replace sits immediately left of the trash. The button is **not** disabled when the asset is
in use — unlike delete, replace is *for* in-use assets.

**`accept` is a hint, not the authority.** `effective_image_extensions()`
(`courses/validators.py:65`) lets an admin narrow the accepted set, so the OS dialog may offer a file
the server then rejects with a 422. That is acceptable: the 422 carries the real message, and
rendering the effective list into the attribute would duplicate the admin-configured limits into the
template for no correctness gain.

**Glyph choice.** A text glyph (`⇄`), not an SVG. The repo's icon convention is monochrome SVG using
`currentColor`, but the two controls this one sits between are the text glyphs `✎` and `🗑`, and a
lone SVG among them would read as a mistake. Converting all three is a cosmetic change outside this
design's scope.

**No no-JS path, accepted with its cost.** Replace is a JS-only affordance, like the rename pencil.
The precedent is weaker than it looks and the difference is stated rather than glossed: the pencil is
`opacity: 0` until `.asset-cell:hover` (`editor.css:725-726`), so a no-JS author rarely meets it,
whereas ⇄ is a permanently visible `.iconbtn` sitting beside a trash button that *does* work without
JS. A no-JS author therefore sees one dead control next to a live one. That is accepted: hiding ⇄
behind hover would bury a brand-new affordance for every author to protect a configuration the
manager already does not support (filter, drag-drop upload and rename are all JS-only). The endpoint
still accepts an ordinary multipart POST, which is what the view tests drive.

### 5. The confirm strip — DOM contract

Every later section (JS, CSS, tests) selects these, so they are named once here. The strip is built
by JS and appended to `.asset-cell` after `.asset-foot`:

```html
<div class="asset-replace-confirm" data-replace-strip role="group"
     aria-label="…replace-aria…">
  <span class="asset-replace-confirm__label">…replace-confirm…</span>
  <span class="asset-replace-confirm__file" data-replace-filename>…filename…</span>
  <span class="asset-replace-confirm__warn">…replace-drag-warning…</span>   <!-- only when di-uses > 0 -->
  <div class="asset-replace-confirm__actions">
    <button type="button" class="btn btn--small" data-replace-commit>…replace-commit…</button>
    <button type="button" class="btn btn--small btn--ghost" data-replace-cancel>…replace-cancel…</button>
  </div>
</div>
```

Every text node is set with `textContent`, never `innerHTML`. The `aria-label` is **not** a literal:
the strip is built entirely in JS, so there is no template in which `{% trans %}` could reach it, and
it takes its text from the `replace-aria` key like every other string here. It is the one string that
is an *attribute* rather than a text node, which is exactly why it is easy to leave hardcoded while
`makemessages` still reports the catalog complete.

### 6. JS — `courses/static/courses/js/media_picker.js`

A fourth op inside `wireManager`. **Two binding styles, deliberately:**

- The **⇄ click** and the **input `change`** are delegated from `root`, because those elements arrive
  and depart with server-rendered cells (`cell.replaceWith(fresh)`, and the filter's whole-grid swap).
- The **strip's own buttons are bound directly, at build time**, inside the closure that built that
  strip. This is not a stylistic choice: it is what makes the `done` re-entrancy flag work. The
  rename handler's `done` is declared inside its per-click listener (`media_picker.js:330`), so it is
  a fresh closure per interaction. A commit handler delegated from `root` has no such closure, and a
  `done` hoisted to `wireManager` scope would be set by the *first* replace and then silently swallow
  every replace afterwards — no error, no flash, nothing. Per-strip closures keep the rename
  precedent exact.

1. **Click** on `[data-replace-asset]` → locate any open strip with a **live DOM query**
   (`root.querySelector("[data-replace-strip]")`), never a retained reference, and close it (remove
   the node; clear that cell's input). At most one strip is open at a time. A click on a cell whose
   own strip is already open is ignored. The live query matters because the debounced filter does
   `oldGrid.replaceWith(newGrid)` (`media_picker.js:373-376`), destroying every cell without
   notification — a retained reference would point at a detached node, and clearing its input would
   be a no-op on the live DOM. A filter/grid swap is therefore an implicit cancel, with no request in
   flight and nothing to clean up.
   Then `input.click()` on this cell's `[data-replace-input]`.
2. **`change`** on the input → **first, return early if `!input.files || !input.files.length`**,
   matching the guards the file already uses at `:169` and `:270`. A cancelled OS dialog normally
   fires nothing at all, but that is browser-dependent rationale, not a defence; without the guard an
   empty `FileList` builds a strip whose filename reads `undefined` and whose commit posts nothing.
   Then build and **append** the strip of §5 to `.asset-cell`, after `.asset-foot`. The foot is
   neither replaced nor emptied, so the existing "in use ×N" summary and its expandable unit list
   stay on screen while the author decides — which is what makes a non-blocking warning defensible.
   The `__warn` span is included only when the cell's `data-di-uses` is greater than zero.
   **Focus moves to `[data-replace-commit]`** so a keyboard or screen-reader user is taken to the new
   content rather than left silently behind it.
3. **Cancel** (`[data-replace-cancel]`) → remove the strip node, set `input.value = ""` on the cell's
   persistent input so re-choosing the same file fires `change` again, and **return focus to the
   `[data-replace-asset]` button**.
4. **Replace** (`[data-replace-commit]`) → set the closure's `done` flag and **disable both the
   commit and the cancel button** for the duration of the request, then `POST` the cell's
   `data-replace-url` with a `FormData` carrying `file`, the `X-CSRFToken` header and
   `X-Requested-With: fetch`, exactly as `uploadFile` does (`media_picker.js:240-249`).

   Disabling cancel is the point, not politeness: the POST is unabortable server-side, so a cancel
   accepted mid-flight would remove the strip, tell the author nothing happened, and then land a 200
   that swaps in the replaced file anyway.

   Exactly three response branches, and the third is a catch-all:

   - **200** → swap the whole `.asset-cell` for the returned HTML (the rename handler's
     `cell.replaceWith(fresh)` pattern). The strip and the input go with the old node. **Move focus to
     the fresh cell's `[data-replace-asset]` button**, since the element that had focus was just
     destroyed.
   - **422** → remove the strip, clear the input, **return focus to `[data-replace-asset]`**, then
     flash the server's message. The body is an `_op_error.html` fragment, not a bare string, so it is
     parsed by assigning the response text to a detached element's `innerHTML`, reading
     `querySelector(".op-error")`'s `textContent`, and passing that **string** to `flash()`. `flash`
     sets `textContent` (`media_picker.js:6-9`), so nothing server-echoed is ever inserted as markup.
     If the fragment has no `.op-error`, fall back to `msg(root, "replace-failed", …)`.
   - **Any other status, and any rejected promise** → the same cleanup as 422 (remove strip, clear
     input, restore focus) with the canned `replace-failed` message. This branch is mandatory, not
     defensive padding: a 403 from a rotated CSRF token, a 404 from an asset deleted in another tab, a
     405, a 500 and a dropped connection are none of them 200, 422 or necessarily a thrown error, and
     an `if/else if` pair plus a `.catch` would leave every one of them with the strip open, no
     message, and a wedged cell. Both siblings in this file already have catch-alls
     (`media_picker.js:314-316`, `:341`).

**All six JS-rendered strings** reach the script the way the existing conflict message does: as
`data-msg-*` attributes rendered with `{% trans %}` on the `.media-manager` root
(`manager.html:6-10`), read back through `msg(host, key, fallback)` (`media_picker.js:234`).

| Key | Fallback |
|---|---|
| `replace-confirm` | `Replace with:` |
| `replace-drag-warning` | `Used by a drag-to-image question. Drop zones are stored as fractions of the image, so a file with a different shape will move them.` |
| `replace-commit` | `Replace` |
| `replace-cancel` | `Cancel` |
| `replace-failed` | `Could not replace the file.` |
| `replace-aria` | `Confirm file replacement` |

### 7. CSS — `courses/static/courses/css/editor.css`

The strip lands inside an `8rem`-minimum grid cell (`.asset-grid`, `editor.css:349-352`), so it must
stack rather than sit on one line, and the filename must truncate the way `.asset-fname` already does
(`editor.css:721-722`). Rules go beside the other `.asset-*` rules:

- `.asset-actions` — `display: flex; gap: var(--space-1);` so the foot keeps two children.
- `.asset-replace-confirm` — column flex, small gap, `margin-top`/`padding-top` plus a
  `1px solid var(--border-default)` top rule to separate it from the foot, `font-size: .78rem`,
  `text-align: left`.
- `.asset-replace-confirm__file` — `overflow: hidden; text-overflow: ellipsis; white-space: nowrap;`
  and a heavier weight, mirroring `.asset-fname`.
- `.asset-replace-confirm__warn` — `color: var(--text-secondary)`. Not `--text-tertiary`, which
  fails AA at body size.
- `.asset-replace-confirm__actions` — row flex with a small gap.

**The strip grows its whole grid row.** `.asset-grid` is CSS Grid with the default
`align-items: stretch`, so appending the strip to one cell makes that grid *row* taller and stretches
every neighbouring cell with it — a visible reflow when the strip opens and again when it closes.
This is **accepted** rather than mitigated: the obvious fix, `align-self: start` on `.asset-cell`,
would stop every cell in the grid stretching to equal height, changing the manager's existing look
for all authors to smooth a transient in one cell. The screenshot check must therefore include a
**multi-cell row with one strip open**, so the reflow is seen and judged rather than discovered later.

All colours come from existing tokens, so dark mode follows automatically — but the strip is checked
in **both** themes with screenshots, and the dark rendering is judged on its own rather than assumed
from the light one.

## Data flow

**Happy path.** Click ⇄ → OS file dialog → `change` → confirm strip appears below the still-visible
foot, focus on Replace → Replace → `POST …/media/<pk>/replace/` → `replace_asset` rejects an empty
file, validates against the unchanged `kind`, writes the new file, updates three columns, and (unless
the storage name is unchanged) registers the old file's deletion for commit → view re-renders the
cell → JS swaps it in. The old file leaves disk after the transaction commits. Every `ImageElement` /
`VideoElement` / `DragToImageQuestionElement` row is byte-for-byte unchanged, and every
`TableElement` / `FillTableElement` / `GalleryElement` JSON blob is untouched; their next render
resolves the pk and serves the new bytes.

**Why no stale cache, on this project's storage.** The new bytes are visible immediately because
`FileSystemStorage.get_available_name` assigns a *different* name whenever the old file is present —
so every rendered `asset.file.url` changes. The name is reused only when the old file was **absent**,
and of the two ways that happens (§"five things" item 2) one is entirely safe: a row that never had
bytes at that name was never served from that URL, so there is nothing cached to go stale. The other
— a row whose bytes existed, were served, and were later lost — can leave a browser holding a cached
thumbnail at the reused URL until a hard refresh. That is a pathological edge (the file was already
missing before the replace began) and is accepted, not solved. An overwrite-style backend would break
the reasoning generally and need explicit cache-busting; the project does not use one, and supporting
it is out of scope.

**Rejected file.** Empty, wrong extension for the asset's kind, or over the size limit → the service
raises → the transaction rolls back → 422 with the message → JS removes the strip and flashes. The
row, the old file and every consuming element are untouched.

**Cancel.** No request is made; the strip is removed, the file input cleared, focus returned.

## Error handling

| Condition | Response |
|---|---|
| GET (or any non-POST), **anonymous or not** | 405 from `@require_POST`, before authentication |
| Anonymous POST | 302 to the login page from `@login_required` — not a 403 |
| Authenticated non-manager POST | `PermissionDenied` from `_require_manage`, as every sibling op |
| `pk` belongs to another course | 404 from `get_object_or_404(..., course=course)` |
| No `file` key in `request.FILES` | 422 `_op_error.html` (fragment) / redirect (no-JS) |
| Zero-byte file | 422, `"The submitted file is empty."` |
| Wrong extension for the asset's kind | 422, the existing per-kind extension message |
| File over the effective size limit | 422, the existing "too large (max N MiB)" message |
| Asset row with `uploaded_by = NULL` | Replaces normally — `uploaded_by` is excluded from validation |
| Storage returns the same name as the old file | Deletion skipped; the row keeps the file just written |
| Old file already missing from storage | No-op — `_delete_file_if_unshared` checks `storage.exists` |
| Another row shares the old `file` name | Old file kept; only the row moves on |
| Non-fragment (no-JS) POST, any branch | Redirect to `courses:manage_media`, as every sibling op |

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
durable dedup key: `get_or_create_asset` returns an existing row only on a `(course, content_hash)`
match (`courses/lal_loader/media.py:35-41`). Leaving a *stale* hash is clearly wrong — a later import
would hand back an asset whose bytes no longer match. Clearing is safe (the filter is on a real
digest, so `""` can never false-match) but is **not** free, and the cost is stated rather than
waved away: **a replaced asset leaves the dedup index permanently.** A subsequent LAL import of the
same course will not reuse that row; it will create a second asset. If the source content still ships
the original bytes, that reintroduces the superseded file as a new asset and points newly built
elements at it.

This is accepted. Recomputing would not actually help in that scenario — the source file still
carries the old digest, so it would miss the recomputed hash too — and it would require reading the
upload twice with a `seek(0)` in between, an ordering footgun that silently writes a zero-byte file
if forgotten. Clearing is what the manager's own `create_asset` already produces, and the field is
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

The ⇄ button's `aria-label`/`title` live in `_asset_cell.html` and are wrapped in `{% trans %}`. All
**six** JS-rendered strings — including the strip's `aria-label`, which JS builds and so no template
can reach — are rendered into `data-msg-*` attributes with `{% trans %}` on `.media-manager`. **No
string carries an interpolation placeholder** — the filename is a separate DOM node — so no
translation, fuzzy pre-fill included, can break the strip by dropping a token.

The view's error messages are the documented exception: plain literals, untranslated, matching the
sibling ops (see §3).

Polish translations for the new entries are added to `locale/pl/LC_MESSAGES/django.po` and the
catalog recompiled, with any `#, fuzzy` pre-fill on a new entry cleared rather than accepted.

## Testing

**Shared mechanics — these are what keep the assertions falsifiable.**

- **Real bytes.** Every test that asserts on a file being deleted or kept builds its asset with
  `make_image_asset` (`tests/factories.py:150`), which writes an actual PNG. The bare
  `MediaAssetFactory` defaults `file` to a `courses/media/test-N.png` *name with no bytes behind it*
  (`tests/factories.py:122-129`); built that way, `storage.exists(old_name)` is already `False`, so
  "gone after commit" passes on a build where the deletion never runs — and the code would take the
  identical-name branch instead of the delete branch, so the test would not exercise what it names.
  The **identical storage name** test is the single, deliberate exception that uses a byte-less row.
- **`MEDIA_ROOT` redirection to `tmp_path`** before any asset is created, in **service, view and e2e**
  tests alike. These are the first tests in the repo whose subject is a file *deletion*; without the
  redirect a stray run deletes from the working tree's real `media/` directory.
  `tests/conftest.py:379-385` and `tests/test_e2e_image_size.py:58-65` establish the pattern, and the
  "before any asset exists" ordering is load-bearing because `live_server`'s media handler reads
  `MEDIA_ROOT` per request.
- **`django_capture_on_commit_callbacks(execute=True)`** around any assertion about a file being gone,
  since `_delete_file_if_unshared` defers through `transaction.on_commit` and those callbacks never
  fire under the plain `db` fixture (`tests/test_media_model.py:28,51`). The shared-filename test runs
  *inside* the same capture block, or it passes for the wrong reason.
- **Re-fetch, don't re-read.** Assertions that a row is unchanged run against a freshly fetched
  `MediaAsset.objects.get(pk=…)`, never the instance the service just mutated in memory.
- **Header discipline.** Every 422 assertion posts with `HTTP_X_REQUESTED_WITH="fetch"`; the redirect
  test posts *without* it. Getting this backwards turns every 422 test into a 302.

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
- **Both JSON-pk resolvers:** a `GalleryElement` (`resolved_images`) **and** a `TableElement` image
  cell (`resolved_cells`) referencing the asset by pk each resolve to the new file after a replace.
  These are separate code paths; one does not cover the other.
- **Drag-to-image survives:** a `DragToImageQuestionElement` with at least one `DragZone` keeps its
  `media_id` and all its zone rows (count and `x/y/w/h` values) after a replace. This is the consumer
  the design devotes a hazard section and a whole warning string to; leaving it unasserted would mean
  the one model whose content the feature can degrade is the one model no test touches.
- **Video:** replacing a video asset preserves `kind="video"` and `VideoElement.media_id`, and swaps
  the file.
- **Rejections**, each asserting the re-fetched row's `file`, `original_filename` and `content_hash`
  are unchanged and the old file is still on disk: a **0-byte** file; an `.mp4` onto an image asset; a
  `.png` onto a video asset; a file over the effective size limit.
- A missing old file on disk does not raise. Built with `make_image_asset` and then **unlinking the
  file from `MEDIA_ROOT`** before replacing — not with a byte-less factory row, which would collide
  with the "real bytes" rule above and silently become a second identical-name test.

**View (`tests/test_media_manager.py`)**

- **An anonymous GET returns 405, not a login redirect.** A *logged-in* GET returns 405 under either
  decorator order, so it cannot falsify the ordering the design specifies; only the anonymous case
  can. An anonymous POST returns a 302 to login.
- Authenticated non-manager → denied. A `pk` from another course → 404.
- **The ⇄ button is enabled on an in-use asset.** Render a cell for an asset with at least one
  `ImageElement` reference and assert `[data-replace-asset]` is present and **not** disabled while the
  delete button *is*. The two buttons live in the same `{% with uses=… %}` block, and the trash's
  markup is `{% if uses %}disabled …{% endif %}` (`_asset_cell.html:35-36`) — copying that adjacent
  line is the single most likely implementation slip, and it would disable replace on precisely the
  assets the feature exists for.
- `data-di-uses` renders the correct count on the cell for an asset backing a drag-to-image question,
  and `0` for one that is not.
- No `file` key posted → 422, **including** a multipart POST whose file is under a different key,
  which must be a 422 and not a 500.
- A 0-byte upload → 422.
- A valid replace returns the re-rendered cell with the new `original_filename` and the preserved
  display name.
- **A POST carrying `kind=video` alongside a valid image file, against a `kind="image"` asset,
  returns 200 and leaves `asset.kind == "image"` after `refresh_from_db()`** — the test that keeps a
  future refactor from reintroducing `MediaAssetForm` and with it a client-controlled `kind`.
- A rejected file returns 422 carrying the validator's message.
- A non-fragment POST redirects to `courses:manage_media`.

**E2e (`tests/test_e2e_media_picker.py`)**

The module's existing `_setup` helper builds its asset as
`MediaAssetFactory(course=course, kind="image", file="courses/media/x.png")` (`:64`) with no bytes and
no `MEDIA_ROOT` override. The replace tests must **not** reuse it as-is: with the old file absent,
storage reuses the name, `asset.file.url` never changes, and "the `<img>` src is the new file" would
pass identically on a build that replaced nothing. They use a setup that redirects `MEDIA_ROOT` to
`tmp_path` first and builds the asset with `make_image_asset`.

- Replace an image that an `ImageElement` in a unit uses: the strip (`[data-replace-strip]`) appears
  naming the chosen file in `[data-replace-filename]` **while the "in use ×N" summary remains
  visible**; `[data-replace-commit]` swaps the cell; the cell shows the new filename; and the unit
  page then renders an `<img>` whose `src` **differs from the recorded original** and resolves to the
  new file. Files are supplied with `set_input_files` on the hidden input, which Playwright permits
  without the input being visible.
- Cancel leaves the cell and the asset unchanged and issues no request. The negative is asserted, not
  slept on: register `page.on("request")` filtered to the replace URL *before* clicking, then — after
  a condition that provably post-dates any request the handler could have made (the strip's removal
  from the DOM) — assert the recorded list is empty.
- **Two consecutive replaces on the same cell both succeed.** This is the regression test for the
  `done` flag's scope (§6): a flag hoisted out of the per-strip closure makes the second replace a
  silent no-op, with no error and no flash, which every other test in this list would still pass.
- For an asset backing a drag-to-image question the strip shows `.asset-replace-confirm__warn`; for
  one that does not, it is absent.
- Both themes are screenshotted and the dark rendering judged on its own, and the shot includes a
  multi-cell grid row with one strip open so the row-height reflow (§7) is seen.

Per the repo's testing convention, each new test is falsified against a deliberately broken variant
before being trusted — in particular the shared-filename guard and the identical-name guard (both of
which pass trivially if the deletion never runs at all), the e2e `src` assertion (which passes
trivially against a byte-less fixture), and the "unchanged on rejection" assertions (which pass
trivially if the view short-circuits earlier than intended).
