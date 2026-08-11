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
| `GalleryElement` | `resolved_images()` — a **method**, not a property | `courses/models.py:1546-1557` |

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
`MediaAsset` rows sharing a name share a lifetime. **Shared names are reachable in real data, not
only in fixtures.** The three paths that *create* assets today — `create_asset`, the LAL loader and
this design — all let storage assign the name, so none of them can collide. But
`courses/migrations/0008_migrate_files_to_assets.py:32-37` populated `MediaAsset` by copying the
*storage reference* off each `ImageElement.image` ("Copy the storage REFERENCE … never the bytes"),
so any two image elements that pointed at one stored file produced two rows sharing a name on every
database that ran 0008. Fixtures reach the same state more casually, via a literal
`file="courses/media/x.png"` — that exact literal appears in several fixtures across the suite,
including `courses/tests/test_image_size_render.py:13-19` and `tests/test_e2e_media_picker.py:64`.
The replace path therefore carries the guard the signal lacks, and the guard is not dead code.

**2. Deleting the old file can delete the *new* one.** `Storage.get_available_name` only avoids names
that currently exist on disk. If the old file is already **missing** from storage — a row whose bytes
were lost, or any fixture row built with a literal `file=` and no bytes — then an upload sharing that
basename is written to the *same* name, and a naive "delete the old name after saving" would destroy
the file just written. The service must therefore compare names, not assume they differ.

**3. `full_clean()` on an existing row validates fields the replace never touches.**
`MediaAsset.uploaded_by` is declared `null=True` **without** `blank=True`
(`courses/models.py:709-711`), so `Model.clean_fields()` raises `"This field cannot be blank."` for
any row whose uploader is `NULL`. Four populations have one: every asset created by the LAL importer
(`courses/lal_loader/media.py:35-47` never sets `uploaded_by`), every row migration
`0008_migrate_files_to_assets.py:32-37` created, everything the demo seeder makes
(`seed_demo_course.py:236`), and every asset whose uploader account was later deleted — the FK is
`SET_NULL` precisely so that happens. `create_asset` never hit
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
- **Cross-kind replacement** (image ⇄ video). Note *what* prevents it: **not** the FKs.
  `limit_choices_to` is a form-field queryset hint that produces no database constraint and no
  model-level check, so nothing at the FK layer would notice an asset whose `kind` flipped. The real
  guarantee is structural and lives in `replace_asset`: `kind` is never assigned, so
  `MediaAsset.clean()` branches on the unchanged value and the per-kind extension validator rejects
  the file (see §Architecture 1). Recording the false version here would invite a later refactor to
  treat the database as the backstop and drop the one that actually works.
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
        # Translated (media.py already imports gettext_lazy as _): this is a SERVICE
        # message, so the untranslated-view-literal exception in §i18n does not cover
        # it, and the same condition already speaks Polish via the upload form.
        raise ValidationError(_("The submitted file is empty."))
    old_name = asset.file.name
    old_storage = asset.file.storage
    asset.file = uploaded_file
    asset.original_filename = truncate_filename(uploaded_file.name)
    asset.content_hash = ""
    # Validate exactly the fields this operation writes. `uploaded_by` is the one
    # exclusion that is load-bearing: it is null=True WITHOUT blank=True, so
    # clean_fields() raises "This field cannot be blank." on a NULL uploader and a
    # bare full_clean() would reject every LAL-imported asset. course/kind/name would
    # pass anyway and are listed to express the rule, not to prevent a known failure.
    # `created` is deliberately NOT listed: auto_now_add makes it editable=False, so
    # Field.validate() early-returns and excluding it would be a no-op that reads as
    # load-bearing. clean() runs regardless of `exclude`, and still branches on the
    # untouched self.kind — which is where the per-kind file validation lives.
    asset.full_clean(exclude=["course", "kind", "name", "uploaded_by"])
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
`max_length=100` check on the *submitted* filename is not reproduced — `forms.FileField.to_python`
compares `len(data.name)` on the client-supplied name and 422s, whereas `models.FileField` attaches no
`MaxLengthValidator` and instead lets storage truncate the *stored* name (a different string, carrying
the `courses/media/` prefix and any uniquifying suffix). The shared authority between the two paths is
therefore **extension and size**, not "all validation".

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
  Both delegations filter on their own attribute — `e.target.closest("[data-replace-asset]")` and
  `e.target.closest("[data-replace-input]")` — and return early when the enclosing `.asset-cell` is
  absent. The second selector is not optional tidiness: `root` is `.media-manager`, which also
  contains the upload form's `<input type="file" name="file">` (`manager.html:20`), and `change`
  bubbles. A looser filter (`e.target.type === "file"`) would make choosing an *upload* file try to
  build a confirm strip on a cell that does not exist.
- The **strip's own buttons are bound directly, at build time**, inside the closure that built that
  strip. This is not a stylistic choice: it is what makes the `done` re-entrancy flag work. The
  rename handler's `done` is declared inside its per-click listener (`media_picker.js:330`), so it is
  a fresh closure per interaction. A commit handler delegated from `root` has no such closure, and a
  `done` hoisted to `wireManager` scope would be set by the *first* replace and then silently swallow
  every replace afterwards — no error, no flash, nothing. Per-strip closures keep the rename
  precedent exact.

1. **Click** on `[data-replace-asset]` → **if a replace POST is in flight anywhere, return
   immediately** (see the in-flight flag in step 4). Otherwise just `input.click()` on this cell's
   `[data-replace-input]`, and **tear nothing down yet**.

   Teardown of any already-open strip belongs to the `change` handler, not here. Doing it on click
   would destroy the author's pending strip *before* the OS dialog opens, so dismissing that dialog —
   which fires no `change` at all — would silently discard their previous selection with no way back.
   Deferring means a dismissed dialog leaves everything exactly as it was. This is also what makes
   re-clicking ⇄ on a cell whose *own* strip is open a sensible "wrong file, let me pick another"
   rather than a dead click.

   At most one strip is open at a time; step 2 enforces that by removing whatever it finds with a
   **live DOM query** (`root.querySelector("[data-replace-strip]")`), never a retained reference. The
   live query matters because the debounced filter does `oldGrid.replaceWith(newGrid)`
   (`media_picker.js:373-376`), destroying every cell without notification — a retained reference
   would point at a detached node, and clearing its input would be a no-op on the live DOM. A
   filter/grid swap before commit is therefore an implicit cancel, with no request in flight and
   nothing to clean up. (For a swap *during* commit, see step 4's detached-strip rule.)
2. **`change`** on the input → **first, return early if `!input.files || !input.files.length`**,
   matching the guards the file already uses at `:169` and `:270`. A cancelled OS dialog normally
   fires nothing at all, but that is browser-dependent rationale, not a defence; without the guard an
   empty `FileList` builds a strip whose filename reads `undefined` and whose commit posts nothing.

   **Then capture the `File` object — `var file = input.files[0]` — before touching anything else,
   and use that captured object for both `[data-replace-filename]` and the commit's `FormData`.
   Never re-read `input.files` later.** This ordering is load-bearing. Teardown comes next, and in
   the re-pick flow step 1 advertises, the open strip belongs to *this* cell — so a blanket "clear
   that cell's input" would run `input.value = ""` on the very input that just received the new
   selection, wiping `input.files` before the strip is built. `input.files` cannot be restored
   programmatically, so the result would be a `TypeError` and no strip at all, or a commit that posts
   no file. For the same reason the clear-the-input rule applies **only to a different cell's**
   input; this cell's input is left alone until cancel or a response branch.

   Then **remove whatever `root.querySelector("[data-replace-strip]")` finds** — any open strip,
   whether on this cell or another — and build and
   **append** the strip of §5 to `.asset-cell`, after `.asset-foot`. The foot is
   neither replaced nor emptied, so the existing "in use ×N" summary and its expandable unit list
   stay on screen while the author decides — which is what makes a non-blocking warning defensible.
   The `__warn` span is included only when
   `Number(cell.getAttribute("data-di-uses") || 0) > 0`. Spelled out because the attribute is a
   **string**: the tempting `if (cell.dataset.diUses)` is truthy for `"0"` and would show the
   drag-to-image caution on every asset in the library.
   **Focus moves to `[data-replace-commit]`** so a keyboard or screen-reader user is taken to the new
   content rather than left silently behind it.
3. **Cancel** (`[data-replace-cancel]`) → remove the strip node, set `input.value = ""` on the cell's
   persistent input so re-choosing the same file fires `change` again, and **return focus to the
   `[data-replace-asset]` button**.
4. **Replace** (`[data-replace-commit]`) → **`if (done) return;` first**, then set `done`, raise the
   shared in-flight flag read by step 1, and **disable both the commit and the cancel button** for the
   duration of the request; then `POST` the cell's `data-replace-url` with a `FormData` carrying
   `file`, the `X-CSRFToken` header and `X-Requested-With: fetch`, exactly as `uploadFile` does
   (`media_picker.js:240-249`).

   The `if (done) return;` read is the guard — setting the flag without reading it, which is easy to
   do, would leave the hoisting bug §6's preamble describes undetectable and its regression test
   vacuous. Disabling the buttons is the visible complement, not the mechanism.

   **The two flags have deliberately different scopes, and the second must be cleared.** `done` is
   per-strip, declared in the closure that built that strip. The **in-flight flag is the opposite**:
   it is declared once in `wireManager` scope, because its whole job is to stop a ⇄ click on *another*
   cell, and per-strip state cannot see across cells. The hoisting objection raised against `done`
   does not apply to it — `done` must not be shared because sharing it swallows later replaces, while
   this flag must be shared because that is the coordination it exists to provide.

   It is **lowered in every exit**: the 200 branch, the 422 branch, the catch-all, and the rejected
   promise — a `finally`-equivalent, not just the success path — and it is lowered even when the
   branch's own strip is already detached and the rest of its cleanup no-ops. Raise-without-lower is
   the one bug that would make the whole feature work exactly once per page load: step 1 would return
   immediately for every subsequent ⇄ click, silently, anywhere in the manager.

   Disabling cancel is the point, not politeness: the POST is unabortable server-side, so a cancel
   accepted mid-flight would remove the strip, tell the author nothing happened, and then land a 200
   that swaps in the replaced file anyway. The in-flight flag closes the same hole from the other
   side: without it, clicking ⇄ on a *different* cell mid-flight would sail past the disabled buttons
   (the ⇄ handler is delegated and knows nothing about them), tear down the pending strip, and then
   have the arriving response yank focus out of the newly opened one. As a second line of defence,
   **every response branch below skips its cleanup and focus move if its own strip is no longer
   attached to the live DOM** (it still lowers the in-flight flag).

   One case reaches that rule for real: the debounced **filter can fire during** an in-flight replace
   — the in-flight flag guards ⇄ clicks, not the search box — and its grid swap detaches the strip.
   The replace has already committed server-side, but the refetched grid was rendered from a
   pre-commit read, so a plain no-op would leave the author looking at the old thumbnail and filename
   with nothing to say it worked. So the **200 branch, on finding its strip detached, re-queries
   `root.querySelector('.asset-cell[data-asset-id="<pk>"]')` and swaps *that* node** instead, moving
   no focus. If even that is gone (filtered out of the current view), it no-ops — the asset is not on
   screen to be stale about.

   **Query from `root`, not from `wireManager`'s `grid` local.** That variable is captured once at
   wire time (`media_picker.js:237`) while the filter's `oldGrid.replaceWith(newGrid)` (`:373-376`)
   swaps in a *new* grid node — and a filter swap is the only way this branch is reached at all, so
   `grid` is guaranteed stale exactly here. Using it would find the detached cell and `replaceWith`
   inside a detached tree: precisely the silent no-op this rule exists to prevent, reintroduced by
   the one variable already in scope at that line.

   Exactly three response branches, and the third is a catch-all:

   - **200 *with* a parseable `.asset-cell` in the body** → swap the whole `.asset-cell` for the
     returned HTML (the rename handler's `cell.replaceWith(fresh)` pattern, including its `if (fresh)`
     check at `media_picker.js:343-344`). The strip and the input go with the old node. **Move focus
     to the fresh cell's `[data-replace-asset]` button**, since the element that had focus was just
     destroyed.
   - **422** → remove the strip, clear the input, **return focus to `[data-replace-asset]`**, then
     flash the server's message. The body is an `_op_error.html` fragment, not a bare string, so it is
     parsed by assigning the response text to a detached element's `innerHTML`, reading
     `querySelector(".op-error")`'s `textContent`, and passing that **string** to `flash()`. `flash`
     sets `textContent` (`media_picker.js:6-9`), so nothing server-echoed is ever inserted as markup.
     If the fragment has no `.op-error`, fall back to `msg(root, "replace-failed", …)`.
   - **Anything else** — any other status, **a 200 whose body yields no `.asset-cell`**, and any
     rejected promise → the same cleanup as 422 (remove strip, clear input, restore focus) with the
     canned `replace-failed` message.

   That catch-all is mandatory, and the "200 with no cell" case is why it cannot be an afterthought.
   `fetch` follows redirects by default, so a POST made after the session expires — logged out in
   another tab, or a timeout — silently follows the `@login_required` 302 and resolves as **status
   200 carrying the login page**. It is not 422, not an error status, and not a rejected promise, so a
   naive `200 / 422 / else` split would take the success branch, find no cell, do nothing, and leave a
   strip whose buttons this very step just disabled — unrecoverable without a page reload. The
   ordinary failures (a 403 from a rotated CSRF token, a 404 from an asset deleted in another tab, a
   405, a 500, a dropped connection) land here too. Both siblings in this file already have catch-alls
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

**One change to `flash()`.** It builds a bare `div.op-error` and `prepend`s it to `.media-manager`
(`media_picker.js:6-9`), so on the 422 path the message appears at the top of a possibly scrolled
grid while focus has just been returned to a ⇄ button far below it — and unlike the server's
`_op_error.html`, the flashed div carries no `role="alert"`, so it is not announced either. Add
`role="alert"`, and **insert the empty div first, then set its `textContent`**: today the function
sets the text before prepending, and a live region that arrives already populated is the case screen
readers announce least reliably. Both changes are two lines, they benefit the upload and delete
flashes equally, and without them the replace path's careful focus management ends in silence.

### 7. CSS — `courses/static/courses/css/editor.css`

The strip lands inside an `8rem`-minimum grid cell (`.asset-grid`, `editor.css:349-352`), so it must
stack rather than sit on one line, and the filename must truncate the way `.asset-fname` already does
(`editor.css:721-722`). Rules go beside the other `.asset-*` rules:

- `.asset-actions` — `display: flex; gap: var(--space-1);` so the foot keeps two children. The
  `display: contents` comment on `.asset-del` (`editor.css:729-732`) says the form's button "sits
  directly in that flex row" of `.asset-foot`; after this wrapper that flex parent is
  `.asset-actions`, so the comment is updated to say so rather than left describing a structure that
  no longer exists.
- **The foot's first child must be allowed to shrink.** Without this the foot overflows at the grid's
  minimum column: two `.iconbtn`s (`min-width: 1.9rem` ≈ 32px each, plus borders) with the
  `.asset-actions` and `.asset-foot` gaps come to roughly 77px, against the ~110px an `8rem` column
  leaves after `.asset-cell`'s `var(--space-2)` padding — so about 33px remains for a label that
  needs more. Flex items default to `min-width: auto` and refuse to shrink, so they push out of the
  cell instead. Today, with one icon button, the sum just fits; adding the third control is what
  breaks it, which is why the rule belongs to this change.

  It must cover **both** branches of `_asset_cell.html:31`. When `uses` is falsy the left child is a
  bare `<span class="muted">unused</span>` — `.85rem` (`core/css/app.css:375`), and the Polish
  `nieużywane` is a single unbreakable ~65px word, so an *unused* cell overflows exactly as an in-use
  one would, and unused cells are the majority.

  The rule is **`.asset-foot > :first-child:not([open]) { min-width: 0 }`**, and the `:not([open])`
  is load-bearing in both directions. It matches the unused `<span>` (spans carry no `open`
  attribute) and a *closed* `<details>`, which is what needs to shrink. It deliberately does **not**
  match an **open** `<details>`: with the list expanded, max-content includes the unit titles, so an
  unfloored item would be squeezed to whatever `.asset-actions` leaves — roughly 30px at the 8rem
  minimum — and `.asset-uses-list` is a single-column grid (`editor.css:372-373`), so every title
  would wrap to a few characters per line. Leaving the open state at its min-content floor keeps
  today's behaviour: the foot overflows while expanded, and the list stays readable. Shrinking it
  would re-create, by a different mechanism, exactly the regression the next bullet exists to prevent.

- **Truncation must cover both branches too.** `overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap` (the trio `.asset-fname` already uses, `editor.css:721-722`) goes on **both**
  `.asset-uses` — the summary — **and `.asset-foot > .muted`**. `min-width: 0` alone only lets a box
  shrink; with overflow visible the glyphs are still painted at full width, so an unused cell would
  render ~35px of `nieużywane` straight across the ⇄ and 🗑 buttons. Shrink without clipping is not a
  fix, it is a worse-looking bug.

  The triple must **not** go on `.asset-uses-detail`: that is the `<details>` box, so
  `white-space: nowrap` would inherit into every `<li>` of `.asset-uses-list` while `overflow: hidden`
  hard-clips them at ~110px — and `text-overflow` does not inherit, so there would not even be an
  ellipsis. That would gut the expandable unit list §6 step 2 explicitly leans on. Belt and braces:
  set `white-space: normal` on `.asset-uses-list`.
- `.asset-replace-confirm` — column flex, small gap, `margin-top`/`padding-top` plus a
  `1px solid var(--border-default)` top rule to separate it from the foot, `font-size: .78rem`,
  `text-align: left`.
- `.asset-replace-confirm__file` — `overflow: hidden; text-overflow: ellipsis; white-space: nowrap;`
  and a heavier weight, mirroring `.asset-fname`.
- `.asset-replace-confirm__warn` — `color: var(--text-secondary)`. Not `--text-tertiary`, which
  fails AA at body size. Also `overflow-wrap: anywhere`: it carries the longest string in the strip
  (a full sentence) into a ~110px column, and a long unbroken Polish compound would otherwise push
  the cell wider rather than wrap. Expect four or more lines at the minimum column width — that is
  the baseline the screenshot check judges against, not a defect.
- `.asset-replace-confirm__actions` — row flex with a small gap, **plus `flex-wrap: wrap` and
  `flex: 1 1 auto` on the two buttons**. Without that they overflow: `.btn--small` is
  `padding: var(--space-1) var(--space-3); font-size: .875rem` (`core/css/app.css:50`,
  `--space-3: 12px`), so "Replace" and "Cancel" side by side need roughly 160px against the ~112px of
  content a minimum-width 8rem cell offers once `.asset-cell`'s `var(--space-2)` padding is taken
  off — and the Polish labels are no shorter. Wrapping lets them stack at the narrow end and sit on
  one line where there is room.

**Four states must appear in the screenshot check at the minimum column width**, because the foot's
geometry differs in each and only one of them involves the strip:

1. an **unused** cell — the majority case, and the one the truncation rule above exists for;
2. an in-use cell with its `<details>` **closed** — the default state of every in-use cell, and the
   only state the `:not([open])` shrink rule actually targets. Watch the disclosure affordance: the
   summary's marker is a trailing `::after { content: " ▸" }` (`editor.css:370`), i.e. generated
   inline content at the end of the line box, which is exactly what `text-overflow: ellipsis` eats
   first. At `.7rem`, "in use ×1 ▸" runs ~55px against the ~33px available, so at the minimum column
   the triangle is clipped and the summary reads "in u…" with nothing signalling that it expands.
   That is the accepted cost of truncation, not a defect to fix in CSS — but it must be *seen* and
   judged here rather than discovered after merge;
3. an in-use cell with its `<details>` **open** — the state deliberately left at its min-content
   floor;
4. a cell with the confirm strip open.

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

**Accepted limitation — a filter response that lands after a replace.** §6 handles the ordering where
the grid swap happens *during* the POST. The mirror ordering is not handled: if a filter GET is issued
and rendered before the replace commits but its response arrives *after* the 200 has already swapped
in the fresh cell, `oldGrid.replaceWith(newGrid)` (`media_picker.js:373-376`) reverts that cell to the
pre-replace render. The filter's `seq` counter drops stale filter-vs-filter responses only; it knows
nothing about replaces. The window is narrow, the row and the file on disk are both correct, and the
display self-heals on the next keystroke or reload — so this is accepted rather than guarded, in
preference to teaching `runFilter` about replace state.

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

- **Real bytes for the asset under replacement.** Every test that asserts on a file being deleted or
  kept builds *that* asset with `make_image_asset` (`tests/factories.py:150`), which writes an actual
  PNG. The bare `MediaAssetFactory` defaults `file` to a `courses/media/test-N.png` *name with no
  bytes behind it* (`tests/factories.py:122-129`); built that way, `storage.exists(old_name)` is
  already `False`, so "gone after commit" passes on a build where the deletion never runs — and the
  code would take the identical-name branch instead of the delete branch, so the test would not
  exercise what it names.

  Two tests need a byte-less or absent file **by necessity**, and the rule above is about the
  replaced asset, not every row in the fixture:
  - the **identical storage name** test, whose whole subject is a row whose file is missing;
  - the **shared filename** test's *decoy* row. `make_image_asset` always saves through storage, so
    `get_available_name` guarantees it a unique name — two rows sharing a name are unconstructible
    that way. The decoy must be a literal `MediaAssetFactory(file=<first>.file.name)`. The asset being
    replaced in that test is still built with real bytes.
- **`MEDIA_ROOT` redirection to `tmp_path`** before any asset is created, in **service, view and e2e**
  tests alike. These are the first tests in the repo whose subject is a file *deletion*; without the
  redirect a stray run deletes from the working tree's real `media/` directory.
  `tests/conftest.py:379-385` and `tests/test_e2e_image_size.py:58-65` establish the pattern, and the
  "before any asset exists" ordering is load-bearing because `live_server`'s media handler reads
  `MEDIA_ROOT` per request.
- **`django_capture_on_commit_callbacks(execute=True)`** around the **`replace_asset` call**, with the
  file assertions *after* the block — not around the assertion, which would capture nothing. The
  callback is registered during the service call, so the context manager has to enclose that call;
  `tests/test_media_model.py:28,51` is the precedent. This applies equally to the shared-filename
  test: if its replace runs outside the block, "the file stayed" passes because no deletion ever ran.
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
- **Both JSON-pk resolvers:** a `GalleryElement` **and** a `TableElement` image cell referencing the
  asset by pk each resolve to the new file after a replace. These are separate code paths; one does
  not cover the other. Mind the asymmetry: `TableElement.resolved_cells` is a `@property` but
  `GalleryElement.resolved_images` is a **method** — writing `el.resolved_images` without `()` yields
  a truthy bound method, so the assertion must call it and index into the returned list, or it is an
  assertion that cannot fail.
- **Drag-to-image survives:** a `DragToImageQuestionElement` with at least one `DragZone` keeps its
  `media_id` and all its zone rows (count and `x/y/w/h` values) after a replace. This is the consumer
  the design devotes a hazard section and a whole warning string to; leaving it unasserted would mean
  the one model whose content the feature can degrade is the one model no test touches.
- **Video:** replacing a video asset preserves `kind="video"` and `VideoElement.media_id`, and swaps
  the file. `make_image_asset` cannot build this fixture — it hard-codes a PNG and splats `**kw` into
  `create()` — and a bare `MediaAssetFactory(kind="video")` would still name its file
  `courses/media/test-N.png` with no bytes. Build it inline with real bytes, as
  `MediaAsset.objects.create(course=…, kind="video", file=SimpleUploadedFile("v.mp4", b"…"),
  original_filename="v.mp4")`, keeping the "real bytes for the replaced asset" rule intact rather
  than adding a third exception to it.
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
- **All six `data-msg-*` attributes are present on the `.media-manager` element, with non-empty
  values.** This assertion is not bookkeeping — it is the *only* thing that can fail if they are
  never added. `msg(host, key, fallback)` returns the English fallback whenever an attribute is
  missing, and the suite runs in English, so every other test in this spec — the drag-warning e2e,
  the 422 flash, the strip's `aria-label` — passes byte-identically against a `manager.html` that was
  never touched. The Polish translations would ship dead and nothing would notice.
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

**E2e — a new `tests/test_e2e_media_manager.py`**

These do **not** go in `tests/test_e2e_media_picker.py`. That module is scoped to the in-editor
"Choose media" picker: every helper ends on the editor page
(`page.goto(.../build/unit/<pk>/edit/)`, `wait_for_selector('[data-scope="editor"]')`, `:66-70`), it
has no `MEDIA_ROOT` fixture, and its `_setup` builds the asset as
`MediaAssetFactory(course=course, kind="image", file="courses/media/x.png")` (`:64`) — no bytes.
Reusing that helper would break the central assertion twice over: with the old file absent storage
reuses the name, so `asset.file.url` never changes and "the `<img>` src is the new file" passes
identically on a build that replaced nothing; and without the redirect the run would write into, and
delete from, the working tree's real `media/` directory. There is no existing e2e anywhere in
`tests/` that visits the media manager, so the setup is new, not adapted.

The new module's setup — a module-level `@pytest.fixture(autouse=True)` taking `settings` and
`tmp_path`, exactly mirroring `_isolated_media` in `tests/test_e2e_image_size.py:56-66`. Autouse is
right here, not risky: a fixture defined inside a test module is scoped to that module by
construction and cannot leak elsewhere, whereas making the redirect opt-in would let any future test
in this module forget it and then **delete** from the working tree's real `media/` — the one hazard
this feature uniquely creates.

- redirect `settings.MEDIA_ROOT` to `tmp_path` **before any asset is created** — `live_server`'s
  `_MediaFilesHandler` reads it per request, so this ordering is what makes a freshly written fixture
  image resolve at all;
- build the asset with `make_image_asset` so it has real bytes and a storage-assigned name;
- attach it to an `ImageElement` on a unit, so the cell reports "in use ×1" and there is a unit page
  to re-render;
- `page.goto(f"{live_server.url}/manage/courses/{course.slug}/media/")`, then
  `wait_for_selector(".asset-cell")` as the readiness signal.

Tests:

- Replace an image that an `ImageElement` in a unit uses: the strip (`[data-replace-strip]`) appears
  naming the chosen file in `[data-replace-filename]` **while the "in use ×N" summary remains
  visible**; `[data-replace-commit]` swaps the cell; the cell shows the new filename; and the
  **editor page for that unit** (`/manage/courses/<slug>/build/unit/<pk>/edit/`, ready on
  `[data-scope="editor"]`, the same target the existing picker e2es use) then renders an `<img>`
  whose `src` **differs from the recorded original** and resolves to the new file. The editor page,
  not the student unit view, because a course owner hits enrolment/preview gating there and the
  assertion is about the rendered `src`, not about student access.

**Two ways to supply a file, and which to use when.** Tests that do *not* exercise step 1 call
`set_input_files` directly on `[data-replace-input]` — Playwright permits that on a hidden input.
Tests that **click ⇄** must account for the file chooser step 1's `input.click()` raises:
`with page.expect_file_chooser() as fc: page.click("[data-replace-asset]")` then
`fc.value.set_files(...)`. Leaving it unintercepted hangs or dangles the chooser — the same class of
Playwright trap this design cites when rejecting `window.confirm()`.
- Cancel leaves the cell and the asset unchanged and issues no request. The negative is asserted, not
  slept on: register `page.on("request")` filtered to the replace URL *before* clicking, then — after
  a condition that provably post-dates any request the handler could have made (the strip's removal
  from the DOM) — assert the recorded list is empty.
- **Two consecutive replaces on the same cell both succeed, and the second one goes through the ⇄
  click.** This carries two regressions at once, and the click is what makes the second one testable:
  - the `done` flag's scope (§6) — hoisted out of the per-strip closure, the second replace becomes a
    silent no-op with no error and no flash, which every other test here still passes;
  - **the in-flight flag's lowering.** That flag is read in exactly one place: step 1's ⇄ handler. A
    test that reaches the strip only via `set_input_files` fires `change` directly and never executes
    step 1, so a flag that is raised and never lowered — the bug §6 calls "works exactly once per
    page load" — would pass this and every other listed test. Clicking ⇄ on the second pass is the
    single thing that falsifies it, and it also covers step 1's early return and the re-click path.
- **A real 422 flashes the validator's message, not raw HTML.** Drive an `.mp4` onto an image asset
  and assert the flashed text **contains** the extension error, that no markup leaked into the bar,
  that the flashed `.op-error` carries `role="alert"`, and that the strip is gone and the input
  cleared. **Containment, not equality:** `_op_error.html` renders
  `{% trans "Couldn't apply that change:" %} {{ message }}`, so the extracted `textContent` always
  carries that prefix — an equality assertion would be red against a correct build, and the repo's
  existing `.op-error` e2es (`tests/test_e2e_builder.py:148-150`,
  `tests/test_e2e_editor.py:242-244`) already use containment. The prefix is expected; nobody should
  "fix" it by stripping it in JS. Without this test the fragment-parsing path of §6 — the one the
  design argues hardest for — ships entirely unexercised, and flashing `undefined` or a chunk of HTML
  would go unnoticed.
- **The catch-all branch fires.** Force a non-200/non-422 outcome with `page.route(...)` (abort, or
  fulfil with status 500) and assert the strip is removed, the input cleared, focus back on ⇄, and
  `replace-failed` flashed. Every other test in this list passes with the catch-all deleted.
- **A filter swap mid-flight still updates the cell.** Hold the replace POST with `page.route`, type
  into `[data-filter-q]` to force the grid swap, release the response, and assert the **re-queried**
  cell shows the new filename and that focus did not move. Then the negative case: filter the asset
  *out* of the view and assert nothing happens and nothing throws. Without this the detached-strip
  re-query branch ships unexercised — the same standard this spec applied to the catch-all.
- For an asset backing a drag-to-image question the strip shows `.asset-replace-confirm__warn`; for
  one that does not, it is absent.
- Both themes are screenshotted and the dark rendering judged on its own, and the shot includes a
  multi-cell grid row with one strip open so the row-height reflow (§7) is seen.

Per the repo's testing convention, each new test is falsified against a deliberately broken variant
before being trusted — in particular the shared-filename guard and the identical-name guard (both of
which pass trivially if the deletion never runs at all), the e2e `src` assertion (which passes
trivially against a byte-less fixture), and the "unchanged on rejection" assertions (which pass
trivially if the view short-circuits earlier than intended).
