# Favicon: a libli default mark, and a PA-replaceable school favicon

## Purpose

libli ships no favicon today. `templates/base.html`'s `<head>` contains no icon link of any kind, so
every browser tab shows a blank/generic page glyph, iOS home-screen bookmarks get a page screenshot
instead of an icon, and any context that has no `<link rel="icon">` in scope — a bookmark manager, a
crawler, a direct hit on a `/media/` file or a JSON endpoint — falls back to a bare `GET /favicon.ico`
that this app answers with a 404.

This delivers two things:

1. **A default libli mark** — a designed icon shipped as a full PWA asset set (SVG, ICO, apple-touch,
   manifest icons, `site.webmanifest`), wired into the app shell.
2. **A PA-configurable override** — a Platform Administrator can upload their school's icon in
   `/manage/settings/` → Branding (and in the first-run wizard's Identity step, which shares the same
   form and template), and it replaces the libli mark on the browser tab, the iOS home screen, the
   installed-app icon, and the bare `/favicon.ico` request. Clearing the upload restores the libli
   default. The one deliberate exception among app-shell pages is `templates/500.html`, which carries
   no icon at all — see "Render surfaces". (`403.html` and `404.html` do extend `base.html`, so they
   are covered. `templates/courses/manage/gradebook_print.html` is a second standalone document with
   its own `<head>`; it is a print view and is left alone.)

The override rides the branding path that already exists for `Institution.logo` — same singleton
model, same form, same cached `get_site_config()` bundle, same cache invalidation — so it adds a
field and a few render surfaces rather than a subsystem.

### Non-goals

- **No service worker / offline support.** The manifest makes libli installable and gives iOS and
  Android a real home-screen icon; it does not make libli work offline. No service worker is added.
- **No SVG uploads, and no ICO uploads.** See "Error handling" for why each is refused.
- **No server-side derivation of sizes**, and no flattening of transparency, from the PA's upload.
  One uploaded file fills every slot; see the alpha-channel trade in "Error handling".
- **No per-course or per-group icons.** The override is institution-wide, like every other branding
  setting.

## Architecture / components

### 1. The mark

A rounded-square tile in the brand primary `#147E78`, carrying a white lowercase `l` stem with the
accent-amber `#C77B2A` dot at its baseline right — the header wordmark `libli.` (see `app.css`:
`.brand__dot { color: var(--accent); }`) reduced to its two identifying parts. One letterform plus one
dot is the most that survives 16×16.

The tile is **solid**, not transparent-on-white: a filled teal square reads against both light and
dark browser chrome, which removes any need for a `prefers-color-scheme` variant inside the SVG.
(Browser support for media queries inside SVG favicons is inconsistent; not depending on it is the
point.)

**Geometry constants** — a 512×512 canvas, all values in canvas units, expressed as **half-open
extents** (`x 172→236` means "starts at 172, spans 64, ends before 236"). The artwork bounding box is
**168 × 254**, centred by construction: x 172→340 (margins 172/172), y 129→383 (margins 129/129).

| element | shape | value |
|---|---|---|
| tile | rounded rect | full-bleed 0→512, 0→512; corner radius 112 |
| stem | rounded rect | x 172→236 (width 64), y 129→383 (height 254); corner radius 32 |
| dot | circle | radius 42, centre (298, 341) — right edge x=340, bottom edge y=383, sharing the stem's baseline |

The dot's left edge (256) clears the stem's right edge (236) by 20 units.

**Coordinate convention — the two media do not agree, and this is where they would silently drift.**
SVG's `<rect x="172" width="64">` covers exactly 64 units; Pillow's `ImageDraw.rounded_rectangle` and
`ellipse` take **endpoint-inclusive** boxes (measured in this project's `.venv` with Pillow 12.2.0:
`ellipse([(0,0),(10,10)])` fills 11 px). Transcribed literally into Pillow at 1:1, the table would
therefore produce a 65×255 stem and an 85 px dot — one canvas unit fat in each axis, and a different
corner-radius clamp.

**Every Pillow call passes `(x0·s, y0·s, x1·s − 1, y1·s − 1)`, where `s = 4 · size / 512` is the
_supersampled_ scale** — the 4× factor is *inside* `s`, so the `− 1` removes exactly one supersample
pixel (a quarter of a canvas unit at `size = 512`), which is the correct correction for an
endpoint-inclusive box. Subtracting one *final* pixel instead would subtract 4 supersample pixels
where 1 is correct — over-trimming by 3, i.e. a 0.75 canvas-unit error on the stem width (measured:
`x1 = 236·4 − 4 = 940` against the correct `943`, giving 63.25 instead of 64.0) — and subtracting one
*canvas unit* would over-trim by 4×. Worked
example, `icon-512.png` (`size = 512`, `s = 4`, supersample canvas 2048×2048): the stem box is
`(688, 516, 943, 1531)`. The SVG has no such correction — it emits the half-open extents verbatim.

**Everything is passed unrounded, as floats.** Box endpoints and radii alike go to Pillow as computed
— no `int()`, no `round()`. This matters beyond `size = 512`: at `icon-192.png` (`s = 1.5`) the stem's
`y0` is `193.5` supersample px, and at `apple-touch-icon.png` (`s = 1.40625`) every coordinate is
fractional, so a rounding choice would change the supersampled raster and therefore the committed
bytes that §2 requires be reproducible from this spec.

**Two generator assertions live in `build()` itself** (so `build(tmp_path)` exercises them on every
call, including from the tests) and are **re-run against the committed rasters** in
`tests/test_favicon_build.py`: the centred-bounding-box check and the pixel-measured stem-extent
check. Both homes are intentional — in `build()` they stop a bad render being written at all; in the
tests they also verify what is committed.

**Radii scale but are never decremented.** Every corner radius is passed as `r · s`, unrounded, in
supersample pixels — the `− 1` correction applies to *box endpoints only*, never to a radius. (At
`size = 512` the three readings `112`, `112·s`, `112·s − 1` differ by a factor of four; only `r · s`
is right.) Note that Pillow clamps a radius to half the shorter box side, and the stem's radius 32 is
exactly half its 64-unit width — so the stem renders as a **capsule** with fully rounded ends. That is
the intended letterform, not a clamp artefact. On the SVG side the same constants are emitted verbatim
as attributes: `rx="112"` on the tile rect and `rx="32"` on the stem rect.

Two generator assertions enforce this rather than trusting it:

- the artwork bounding box is centred (left margin == right margin, top == bottom) — computed from
  the constants, catching an off-centre geometry edit;
- the **rendered stem** extent, measured in pixels from the produced raster (not from the constants),
  matches the table — this is the one that catches the endpoint convention being got wrong, which the
  constants-only assertion cannot see. It needs a stated classification predicate and a stated size
  range to be writable at all; see "Testing".

  **Stem only, deliberately.** The dot is *not* extent-measured: both shapes go through the same
  `− 1` box transform, so a convention error shifts both identically and the stem catches it — and a
  dot predicate would have to separate accent `#C77B2A` from the tile, where the obvious
  all-channels threshold fails outright (accent's R is 199, one below the stem predicate's 200). The
  dot is covered by its exact centre-pixel colour sample instead.

Fill colours are literals in the generator, **not** reads of `BrandColor` — the default mark is a
fixed libli asset, and a PA who wants their own colours uploads their own icon. The tile and dot fills
are the documented defaults (`core.services.PRIMARY_DEFAULT`, `ACCENT_DEFAULT`); the generator asserts
this equality at build time so a future default-palette change is caught rather than silently
diverging. The stem fill is the literal **`#FFFFFF`** — pinned in that exact spelling, since `#fff` /
`white` would render identically but change the byte-compared SVG.

### 2. `scripts/build_favicons.py` — single source of geometry

Pillow (a dependency already; `pyproject.toml` declares `pillow>=12.2.0`) cannot rasterize SVG, so
rather than add a renderer dependency, the geometry above lives **once** as module-level constants and
the script emits both the vector and the rasters from them.

The module exposes **`build(out_dir)`**, which `main()` wraps behind a `--out` argument defaulting to
the committed `core/static/core/img/favicon/`. Tests call `build(tmp_path)` **directly** via
`from scripts.build_favicons import build` — the same namespace-package route
`tests/lal_import/test_answers.py` already uses for `scripts.lal_import.*`, so no `__init__.py` is
needed; a `subprocess.run([sys.executable, ...])` invocation would trip ruff's `S603`/`S607` and need
a `noqa`. Rendering into `tmp_path` is also what keeps a test run from writing into the working tree or
racing another `pytest-xdist` worker.

**`build(out_dir)` contract:** creates `out_dir` if missing, overwrites unconditionally, and **returns
the list of written paths** — the drift-guard tests iterate that return value rather than re-deriving
the filename list, so a newly added output cannot silently escape them. Each returned path is matched
to its committed twin by `Path.name` under `core/static/core/img/favicon/`, and the comparison
**dispatches on suffix**: `.svg` → byte-compare; `.png` → dimensions, mode, corner alpha, sample set,
extent scans; `.ico` → the same, **iterated over `ico.sizes()` frame by frame**. That last part is not
incidental: `Image.open("favicon.ico")` yields only the 48 px frame, so a naive comparison would leave
the independently-drawn 16 and 32 px frames — the two a browser tab actually shows — outside the drift
guard entirely.

**The frame *reader* is named too**, for the same reason the writer is: the idiomatic multi-frame
route silently re-creates that escape. Measured in this environment, `IcoImageFile` has **no
`n_frames`**, `ImageSequence.Iterator` yields `[(48,48)]` and nothing more *without raising*, and
`seek(1)` raises `EOFError`. Use `im = Image.open(path); im.size = (16, 16)` (verified in Pillow
12.2.0, no deprecation warning) or `Image.open(path).ico.getimage((16, 16))`. **Do not use
`ImageSequence` or `seek()` here.** An unrecognised suffix **fails the test** rather than being skipped — that is what keeps
the "no new output escapes" property true for a future output type.

That covers additions but not removals, so it is paired with a **set-equality** assertion: the file
names present under `core/static/core/img/favicon/` equal the names `build(tmp_path)` returns.
Without it, a renamed output (say `icon-192.png` → `icon-192x192.png`) leaves the stale file committed
and still collected and served, with every test green.

**The SVG's byte encoding is pinned**, because it is byte-compared and this repo has no
`.gitattributes` while development is on Windows and CI on Linux. `build()` writes it with
`path.write_bytes(svg.encode("utf-8"))` — never text mode, which would emit CRLF on Windows and LF on
Linux — using `\n` line endings and exactly one trailing newline. A `.gitattributes` entry
`*.svg -text` ships with this build so git never converts the committed bytes either. Without both,
the drift guard goes RED on a platform change with no code change — the same failure mode the raster
byte-compare was rejected for.

**Canvas mode and supersampling.** All rasters are **`RGBA`**. Each is drawn at **4× its final size**
and downsampled with `Image.LANCZOS` — Pillow's `ImageDraw` does not antialias (verified: a filled
ellipse yields exactly two distinct colours), and an aliased 32 px icon looks broken.

Outputs, all committed to `core/static/core/img/favicon/`:

| file | size(s) | variant geometry |
|---|---|---|
| `favicon.svg` | vector | the geometry table above, verbatim. Root element: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">` — the `viewBox` is required for it to scale into a tab, the namespace for it to render when served standalone. |
| `favicon.ico` | 16, 32, 48 | same geometry; corners outside the radius-112 tile are fully transparent `(0,0,0,0)`. See the frame mechanism below. |
| `apple-touch-icon.png` | 180×180 | **corner radius 0** (squared, full-bleed tile) and **fully opaque — every pixel alpha 255**. iOS applies its own corner mask and composites transparency onto black, so a pre-rounded tile would show background wedges inside the mask. Artwork scale 1.0, unchanged and centred; no inset (the artwork's half-diagonal, 152.3 units, sits well inside iOS's mask). |
| `icon-192.png` | 192×192 | the geometry table above, verbatim; corners `(0,0,0,0)`. |
| `icon-512.png` | 512×512 | the geometry table above, verbatim; corners `(0,0,0,0)`. |
| `icon-maskable-512.png` | 512×512 | **corner radius 0**, tile colour bled to all four edges, **every pixel alpha 255**; artwork **scale 1.0**, centred, no translation. The maskable safe zone is the *inscribed circle* of radius 0.4 × 512 = 204.8 centred on the canvas; the artwork's half-diagonal is √(84² + 127²) = 152.3 < 204.8, so it already fits at full scale. The generator asserts this inequality. |

**ICO frame mechanism** — the committed bytes must be reproducible from this spec, and the frame order
is load-bearing, not stylistic. Each of the three frames is drawn **independently** at 4× its own size
and downsampled, and the list is ordered **largest-first (48, 32, 16)**, then written with
`frames[0].save(..., format="ICO", sizes=[(48,48),(32,32),(16,16)], append_images=frames[1:])`.

`IcoImagePlugin._save` reads its ceiling from `frames[0].size` and silently **drops every requested
size larger than the base image**. Measured in this environment: frames built ascending (16, 32, 48)
yield an ICO containing only `[(16,16)]`; built descending, all three land. The `sizes=` argument is
consumed as `sorted(set(sizes))`, so its own order is irrelevant — only `frames[0]` matters. Verified
separately: the result is **not** byte-identical to handing Pillow one source image with `sizes=`
(which resizes internally), so naming the mechanism is what makes the output reproducible.

The script is the way to regenerate the assets; it is not run at request time or at deploy time.
"Documented" means two concrete artefacts this build must produce: a module docstring in
`scripts/build_favicons.py` stating the invocation and when to re-run it (any geometry or palette
change), and one line in `docs/development/conventions.md` pointing at it. (There is no `docs/dev/` —
this repo's dev-onboarding docs are `docs/development/{architecture,conventions,setup}.md`.)

**All three URL-emitting surfaces build static URLs through `django.templatetags.static.static()`** —
the `{% favicon_links %}` tag, the manifest view's `icons[].src`, and the `/favicon.ico` redirect
target. Production runs `whitenoise.storage.CompressedManifestStaticFilesStorage`
(`config/settings/base.py`), under which a hardcoded `/static/core/img/favicon/icon-192.png` 404s.
This cannot be caught by a test: `config/settings/test.py` deliberately swaps in plain
`StaticFilesStorage`, so a hardcoded path stays green in the suite and breaks only in production. It
is therefore a review-enforced invariant, stated here so the reviewer knows to look.

### 3. `Institution.favicon` — the override field

```python
favicon = models.ImageField(
    upload_to="branding/", blank=True, null=True,
    verbose_name=_("Favicon"), help_text=_(...),  # copy in "Error handling"
)
```

Migration `institution/0008_institution_favicon_alter_institution_logo.py` — two operations, an
`AddField(favicon)` and an `AlterField(logo)` (see the `verbose_name` note below). The name carries
both so `git log` does not hide half the migration.

`models.ImageField` performs **no** content validation — the Pillow-backed check lives in
`forms.ImageField`, so it is bypassed entirely by a direct shell assignment, a data migration, or a
fixture load. The security properties described under "Error handling" are therefore **form-level**;
that is stated here rather than implied.

**The Django admin is a third path, and it enforces almost none of them.** `InstitutionAdmin` declares
no `fields`/`fieldsets`, so `favicon` appears in `/admin/` on an auto-generated ModelForm that has no
`clean_favicon` — the size cap, extension allowlist, square check and 192–512 bounds are all absent
there; only `forms.ImageField`'s "is this an image at all" check applies. This is **accepted**: the
admin is a superuser-only surface and the rules protect against PA mistakes, not superuser intent. It
is written down so it is a decision rather than a surprise. (Excluding `favicon` from
`InstitutionAdmin` is the alternative if that judgment changes.)

`Institution.logo` gains `verbose_name=_("Logo")` in the same migration. It has none today, so without
this the Branding tab would render one field with a catalogued, translated label directly beside one
with an auto-derived, uncatalogued one — the exact bug §4 names. It is invisible only because "Logo"
happens to be the same word in Polish, and relying on that is luck, not a design.

### 4. Form surface — `BrandingForm`

`favicon` joins `Meta.fields` immediately after `logo`, rendered by the shared styled clearable-file
widget, with `clean_favicon()` enforcing the rules in "Error handling" and its label/help text coming
from the model field (see below).

`Meta.widgets` today reads `{"logo": LogoClearableFileInput()}`. After the change it is:

```python
widgets = {
    "logo": BrandingFileInput(),                      # all six kwargs defaulted -> unchanged output
    "favicon": BrandingFileInput(
        current_label=FAVICON_CURRENT, empty_label=FAVICON_EMPTY,
        replace_label=FAVICON_REPLACE, upload_label=FAVICON_UPLOAD,
        remove_label=FAVICON_REMOVE, icon_variant=True,
    ),
}
```

The five `FAVICON_*` values are **module-level `gettext_lazy` constants in `institution/forms.py`**,
not inline literals — that is where the spec's predicted `#:` catalogue churn points, so their home
has to be fixed rather than incidental.

**Both surfaces render it.** `templates/institution/manage/_branding_fields.html` renders each field
in a hand-written block — adding a name to `Meta.fields` renders nothing on its own — so the favicon
needs its own block in that partial, mirroring the logo block. That partial is `{% include %}`d by
**`templates/institution/setup/identity.html`** (the first-run wizard's Identity step, which drives
the same `BrandingForm` through `institution/views_setup.py::_modelform_step`), so the field appears
there too. That is the intended scope: the field is optional, the wizard step already has a Skip
button, and a visibility guard would mean two divergent renderings of one partial. Tests cover the
wizard step saving a favicon.

**The wizard's lead sentence stays as-is.** `identity.html` reads *"Name your institution, add a logo,
and choose your brand colours."* — a summary of the step, not an inventory of its fields. Rewording it
to mention the favicon would retire an existing msgid (an obsolete `#~` entry this project's
catalogue-health tests reject) in exchange for nothing.

**i18n of the label and help text is explicit, not auto-derived.** `BrandingForm` has no
`labels`/`help_texts` dict today, and this repo has already been bitten by that: auto-derived
ModelForm labels carry no `_()`, appear in no catalogue, and render in English under a Polish UI.

**One source of truth: the model field.** `favicon`'s `gettext_lazy` `verbose_name` and `help_text`
live on the model (§3), and nowhere else — a ModelForm derives `form.favicon.label` /
`.help_text` from them, which is exactly what `_branding_fields.html` renders. No `labels` /
`help_texts` dict is added to `BrandingForm`; duplicating the strings in both places would be two
msgids for one label. The help-text copy is written out in "Error handling" — that string is the only
place a PA learns the constraints before uploading.

**Targeted refactor this pulls in.** `LogoClearableFileInput` and
`templates/institution/manage/widgets/logo_clearable.html` are logo-specific in three ways, all of
which must be parameterized before a second field can share them:

1. **JS hooks.** The widget template hardcodes `data-logo-field/-input/-thumb/-filename/-remove`, and
   the inline script that drives the live preview — which lives at the bottom of
   **`_branding_fields.html`**, not in `_branding_tab.html` — queries four of those as *global*
   selectors (`$("[data-logo-input]")` and siblings). Rename `LogoClearableFileInput` →
   `BrandingFileInput`, template → `institution/manage/widgets/branding_file.html`; the wrapper
   carries `data-file-field="<name>"` and the inner hooks become `data-file-input` / `data-file-thumb`
   / `data-file-filename` / `data-file-remove`, queried **within** each wrapper. The inline script
   loops over `form.querySelectorAll("[data-file-field]")`. Keep the `_render()` override that forces
   `TemplatesSetting` — its reason (`BoundField.as_widget()` passes a renderer that only searches
   Django's built-in templates dir) is unchanged. Django's native clear-checkbox name
   (`<field>-clear`) is untouched, so `value_from_datadict`'s clear logic keeps working for both.
   `_branding_tab.html` needs **only a comment fix** (its lines 6–8 describe the `data-logo-*` hooks);
   it contains no `.logo-field*` class name and no script.
2. **Copy.** The widget template hardcodes five translatable strings — `Current logo`, `No logo yet`,
   `Replace logo`, `Upload logo`, `Remove logo`. Shared verbatim, the favicon field would read
   "Upload logo". `BrandingFileInput` therefore takes **six** constructor kwargs — five lazy strings
   (`current_label`, `empty_label`, `replace_label`, `upload_label`, `remove_label`) plus
   the boolean `icon_variant` (see item 3) — and overrides **`get_context()`** to inject all six under
   `context["widget"]`, since constructor kwargs are otherwise invisible to the template. The five
   strings default to the existing logo copy and `icon_variant` defaults to `False`, so the logo
   field's markup and msgids are unchanged. The favicon field's five strings are
   written out here so they are neither invented at implementation time nor drifting from the PL
   screenshots:

   | kwarg | EN | PL |
   |---|---|---|
   | `current_label` | Current favicon | Bieżąca ikona strony |
   | `empty_label` | No favicon yet | Brak ikony strony |
   | `replace_label` | Replace favicon | Zmień ikonę strony |
   | `upload_label` | Upload favicon | Prześlij ikonę strony |
   | `remove_label` | Remove favicon | Usuń ikonę strony |

   **Catalogue consequences:** the five
   favicon msgids are additions; the five logo msgids must stay byte-identical or they become obsolete
   `#~` entries; and their `#:` source references move from the `.html` template to
   `institution/forms.py`, which is expected churn, not a regression.
3. **CSS.** `institution/static/institution/settings.css` pins `.logo-field__thumb { height: 64px;
   width: 120px; }` — a landscape box that would squash a square icon. The `.logo-field*` block is
   renamed to `.branding-file*` (touching `settings.css` and the widget template; no other file and no
   test references those class names). **`icon_variant` is the single discriminator** for both the CSS
   and the markup fork: when true the template adds `branding-file__thumb--icon` — a **48 px square**
   box — in **both** branches (the empty `<div>` and the filled `<img>`; otherwise the filled state
   would letterbox a square icon inside the 120×64 landscape box under `object-fit: contain`) *and*
   takes the empty-state branch below. Only the no-text/`role="img"` treatment is specific to the
   empty branch. It is a boolean rather than a CSS-class string
   precisely because it forks accessibility markup, not just styling; keying an `aria` decision off a
   class name would let the two drift.

   Because ~32 px of content box cannot hold a wrapped "No favicon yet" / "Brak ikony strony" label,
   the **icon variant's empty state renders no text inside the tile**: a dashed 48 px square carrying
   `role="img"` **and** `aria-label="{{ empty_label }}"`. The `role` is not optional — the tile is a
   `<div>`, whose implicit `generic` role makes `aria-label` alone unannounced, so without it the
   stated mitigation silently does nothing. The logo variant's centred-text empty state is unchanged.
   This is scoped CSS work, not an afterthought: the project's rule is that every view ships styled.
4. **Empty-state preview.** Today's script swaps the thumb only under
   `if (thumb && thumb.tagName === "IMG")`, and the template renders the thumb as a `<div>` whenever
   `widget.is_initial` is false — so on an empty field, picking a file updates the filename echo and
   nothing else. That is *every* first favicon upload. Fix it in the shared script: on pick, if the
   thumb element is not an `<img>`, **replace it with an `<img>`** carrying the same
   `data-file-thumb` hook, then set its `src`. Precisely: the new `<img>` copies the old element's
   `className` **minus `branding-file__thumb--empty`** — which carries `--icon` over automatically,
   with no second discriminator in the script — and **does not** carry `role="img"` or `aria-label`,
   since an `<img>` has an image role already and an `aria-label` would compete with `alt`. Those two
   attributes exist only on the empty `<div>` and leave with it.

   **The handler must re-bind its thumb reference after the swap**, or only the *first* pick ever
   previews. The existing script caches the thumb outside the change handler
   (`var logoThumb = $("[data-logo-thumb]")`), and the natural per-wrapper translation caches it at
   loop top — after `replaceWith` that variable points at a **detached** node and every subsequent
   pick updates nothing. Either assign the new `<img>` back to the loop-scoped variable or re-query
   `wrapper.querySelector("[data-file-thumb]")` inside the handler. The e2e and visual checks
   therefore pick a file **twice** on the same field; a single pick would ship this green.

   **`alt` needs a carrier**, because the swap happens in the shared loop at the bottom of
   `_branding_fields.html`, which has no access to per-widget constructor kwargs. So `get_context()`
   also emits **`data-file-current-label`** on the `[data-file-field]` wrapper, and the script reads
   `alt` from it. With `aria-label` forbidden on the new `<img>`, `alt` is its only accessible name —
   leaving its value to be invented at implementation time is exactly what §4 otherwise prevents.

   This repairs the logo field's identical thumb gap at the same time. **Scope:** the thumb only. The
   identity-signature preview (`[data-preview-logo]`) is rendered as a `<span>` when no logo is set and
   is guarded by the same `tagName === "IMG"` test, so it stays dead on a fresh install — a
   pre-existing gap on a different element, deliberately left alone here. The e2e assertion names the
   element it checks (`[data-file-thumb]`), so it cannot pass on one while the other is broken.

The brand-preview signature (`[data-preview-logo]`, `[data-preview-name]`) stays wired to the **logo**
field only — a favicon in the identity signature would misrepresent what that preview shows. The
discriminator is explicit, since the script is now a per-wrapper loop: each iteration reads
`wrapper.dataset.fileField`, and the `previewLogo` branches (including the remove-checkbox →
`previewLogo.hidden` toggle) run **only** when it equals `"logo"`. Everything else — thumb swap,
filename echo, resetting the remove checkbox on a new pick — is per-wrapper and field-agnostic.

### 5. `get_site_config()` — `favicon_url` and `favicon_size`

`core/services.py` gains two keys, both `None` in `_DEFAULTS`:

- `favicon_url` — `inst.favicon.url if inst.favicon else None` (the `if` guard is required: `.url` on
  an empty `ImageField` raises `ValueError`, the same guard `logo_url` already uses).
- `favicon_size` — `"<W>x<H>"`, read from `inst.favicon.width/height`. This opens the stored file, so
  it happens **inside `_build()`** — i.e. once per cache rebuild (300 s TTL), never per render.
  Two failure modes, both handled: a missing file raises → `try/except (OSError, ValueError)` → `None`;
  a file whose **image header is unreadable** makes `django.core.files.images.get_image_dimensions`
  return `(None, None)` *without raising*, so an explicit `if width and height` guard is required too —
  otherwise the manifest ships the literal string `"NonexNone"`.

  **"Unreadable header", not "truncated".** Measured: a PNG truncated to half its bytes still reports
  `256×256`, because PNG dimensions live in the IHDR chunk at the very start. `(None, None)` needs
  content that is not a decodable image header at all — the fixture is non-image bytes
  (`b"not an image"`) written to `MEDIA_ROOT/branding/x.png`. A truncation-based fixture would return
  a real size and fail the test for a reason unrelated to the code under test.

No `favicon_mime` key: uploads are PNG-only (see "Error handling"), so the manifest's `type` is always
`"image/png"`.

`favicon_size` exists because the manifest needs a real `sizes` value: `"any"` is the vector
convention, and installability heuristics look for a raster icon with a declared pixel size, so
emitting `"any"` for a PNG risks making libli non-installable exactly when a school has branded it.
The **192 px validation floor** (see "Error handling") is what makes this honest — an accepted upload
is always large enough to be the installed-app icon, so the manifest can hand it over as the sole
icon without a size-based fallback branch. No new model columns (`width_field`/`height_field`) are
needed: the cached read is enough.

No new cache plumbing: the bundle is already invalidated on `Institution` `post_save`/`post_delete` in
`core/apps.py`.

### 6. Render surfaces

**`{% favicon_links %}`** — a new `simple_tag` in the existing `core/templatetags/branding.py`
(alongside `brand_vars`; both are branding-head emitters). It reads `get_site_config()` and returns
the head block:

- *No override:* `<link rel="icon" href="…/favicon.ico" sizes="16x16 32x32 48x48">` **first**
  (declaring what that file actually contains, since this spec argues elsewhere for accurate `sizes`),
  then `<link rel="icon" href="…/favicon.svg" type="image/svg+xml" sizes="any">` **last** — the SVG
  must come last or the browser never fetches it; see the ordering paragraph below,
  `<link rel="apple-touch-icon" href="…/apple-touch-icon.png">`,
  `<link rel="manifest" href="{% url 'core:webmanifest' %}">`,
  `<meta name="theme-color" content="<effective primary>">`.
- *Override set:* the three icon links collapse to two pointing at the uploaded file —
  `<link rel="icon" href="{{ favicon_url }}" type="image/png" sizes="{{ favicon_size }}">` and
  `<link rel="apple-touch-icon" href="{{ favicon_url }}">` — with the manifest link and `theme-color`
  unchanged. The `type`/`sizes` are emitted for the same reason the manifest carries them and the ICO
  link declares its frames: the bundle already knows both, and an accurate declaration lets the
  browser skip a fetch. Both links are safe because the upload is PNG-only: an ICO in
  `apple-touch-icon` would be ignored by iOS and silently fall back to a page screenshot.

**Escaping is `format_html`, not `mark_safe`.** A `simple_tag` returning a plain string is
auto-escaped in full, so the markup would render as visible text; the only working options are
`format_html` / `format_html_join` / `render_to_string`. Its neighbour `brand_vars` uses `mark_safe`
on an f-string (with a `# noqa: S308`), and copying that pattern here would inject an unescaped,
**filename-bearing** media URL into an `href` attribute. `format_html` escapes each interpolated URL
as an attribute value, which is exactly the property needed. Static URLs come from
`django.templatetags.static.static()` so WhiteNoise's `CompressedManifestStaticFilesStorage` hashing
applies in production.

**Which icon link wins matters, and the two default links compete.** **Expected outcome: a modern
browser renders the SVG; the ICO is the legacy fallback.** That is a checkable claim, so the
visual-verification step checks it rather than assuming it.

> **Corrected in build (Task 13) — this section's original mechanism was false.** It claimed
> selection turns on declared `sizes`, and prescribed `sizes="any"` on the SVG plus **SVG-first**
> ordering. Measured against a real server with headed Chromium 148 and real Google Chrome (verdict
> read from the server access log — a favicon is fetched by the browser *process* for the tab chrome,
> so headless `page.on("request")` sees nothing, and Playwright route interception skews the result):
> **`sizes` is inert for selection.** It changed nothing when placed on the SVG, on the ICO, on both,
> or on neither. **Document order decides — Chromium prefers the *last* `<link rel="icon">` among
> equals.** SVG-first + ICO-second meant the ICO was fetched and the SVG *never* was, i.e. the
> prescribed arrangement produced exactly the dead-weight vector it was meant to prevent.
> Hence the shipped order is **ICO first, SVG last**. `sizes` is kept accurate on both links because
> it is truthful metadata, not because it drives the choice.

**`theme-color` is always emitted**; its value is `cfg["primary"]` when that passes
`is_valid_css_color()`, else `PRIMARY_DEFAULT`. (The meta tag is never omitted — an earlier phrasing
implied both behaviours.)

`base.html` gains one line, `{% favicon_links %}`, in `<head>`.

**`templates/500.html` gets no icon at all.** It is a standalone document rendered with an empty
`Context()`, and its existing comment states the invariant plainly: it "must not depend on collected
static, which can itself be the cause of a 500." A hardcoded `/static/…/favicon.ico` link would be
that page's first external asset dependency — precisely what the invariant forbids — and
`{% favicon_links %}` is doubly impossible there (it calls `get_site_config()`, which can hit the DB
on a cold cache). The 500 page therefore shows the browser's default glyph. That is the correct trade
and is stated here so it is not "fixed" later by someone who reads it as an oversight.

**`core/views.py::webmanifest`** — served at `/site.webmanifest`, name `core:webmanifest`, public (no
global login-required middleware exists, and the manifest must be fetchable by the browser
regardless). Returns `JsonResponse` with `content_type="application/manifest+json"`:

```json
{
  "name": "<institution name>",
  "short_name": "<see the rule below>",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#F4F1EA",
  "theme_color": "<effective primary, or PRIMARY_DEFAULT>",
  "icons": [ ... ]
}
```

`background_color` is the app's light surface (the same literal `500.html` already hardcodes), not
white — the splash screen should repaint into the app, not flash white first.

`start_url` is `/`, deliberately: `core.views.landing` bounces authenticated users to `home`, so an
installed PWA opens on the dashboard for the logged-in user it belongs to, while an anonymous launch
still gets the landing page with its SSO entry point. Pointing `start_url` at `/home/` would trade
that for a login redirect.

`short_name` rule, fully specified because its boundary is where this kind of thing breaks. `name` is
`.strip()`ed first; if it is ≤ 12 characters use it as-is; otherwise `name[:12].rsplit(" ", 1)[0]`
then `.rstrip()` — the boundary character is the **ASCII space only** (not hyphens, not other
whitespace), so `Jan-Kochanowski Liceum` truncates inside the hyphenated word and a double space
collapses harmlessly under `rstrip`.

**There is no empty-result branch**, and an earlier draft's hard-truncate fallback was removed as dead
code. For any stripped non-empty name, `name[:12].rsplit(" ", 1)[0]` is never empty — a fuzz over
200k space/letter strings found zero cases — because with no space in the first 12 characters
`rsplit` returns the whole slice. A long first word simply takes the main path:
`"Międzynarodowe Liceum"` → `"Międzynarodo"`. Keeping the branch would have meant shipping a test that
still passes with the branch deleted.

The name can nonetheless be **whitespace-only**: `_build()` uses `inst.name or _DEFAULTS["name"]`, and
`"   "` is truthy. Both the Branding form and the admin strip through `CharField(strip=True)`, so this
is reachable only by a shell/fixture/data-migration write — the same bypass class §3 documents for the
upload rules. Handle it where it arises: if the stripped name is empty, fall back to
`_DEFAULTS["name"]` and run the rule on that, so neither `name` nor `short_name` can be `""`.

`icons` is the 192/512/maskable trio by default, each with `"type": "image/png"` and its `sizes`; the
maskable entry additionally carries `"purpose": "maskable"`. With an override it is a **single** entry
`{"src": favicon_url, "sizes": favicon_size, "type": "image/png", "purpose": "any"}` — an
override therefore forgoes the maskable variant, so Android may crop the uploaded icon under an
adaptive-icon mask — **and it also drops the 512 px entry**, so a small-but-valid 192 px upload yields
a lower-resolution splash icon than the default trio would. Both are accepted trades (deriving either
variant would mean server-side image generation, an explicit non-goal), stated rather than silent.

**When `favicon_size` is `None`** (unreadable stored file), both surfaces behave the same way: the
head link omits its `sizes` attribute and the manifest entry omits its `sizes` key. Not `"any"` — §5's
own argument is that `"any"` on a raster is the declaration that risks non-installability, so
substituting it on the one path where the size is unknown would be the worst of both. Omission lets
the browser measure the file itself.

The manifest must be a **view** rather than a static file precisely because both `name` and `icons`
depend on institution state.

**`core/views.py::favicon_ico`** — `/favicon.ico`, name `core:favicon_ico`, a 302 to the effective
icon URL (override if set, else the static `favicon.ico`). It is named for symmetry with
`core:webmanifest` and so its tests can `reverse()` rather than hardcode the path, even though nothing
in a template reverses it. A browser that has parsed an HTML page declaring `<link rel="icon">`
uses that and does *not* additionally fetch `/favicon.ico`; the unprompted fetch happens in the
contexts where no icon link is in scope — a direct hit on a `/media/` file or a JSON/PDF response, a
bookmark manager, an installer, some crawlers. A static file at that path could not honour the
override, and no route at all makes each of those a logged 404.

**No `Cache-Control` is set on the redirect** (it inherits the default, i.e. no explicit caching). A
long-lived cached 302 would outlive a PA changing or clearing the favicon — clients would keep
following the stale redirect for the cache lifetime — which directly contradicts the "clearing
restores the default" promise. The extra hop is one cheap redirect on a rare path.

Both routes are registered in `core/urls.py` (already `include`d at the root prefix, so no
`config/urls.py` change).

## Data flow

**Default render (no override), any page extending `base.html`:**

`{% favicon_links %}` → `get_site_config()` (cache hit, or one query on miss) → reads
`favicon_url = None` → emits the three static icon links + manifest link + `theme-color` → browser
fetches the static assets through WhiteNoise. (The tag calls the service directly; the
`institution_branding` context processor is not in this path — which is exactly why the 500 page,
which has no context processors *and* loads no tag library, is unaffected.)

**Override render:** PA uploads in Branding (or in the wizard's Identity step) →
`BrandingForm.clean_favicon()` validates → `save()` writes the file under `MEDIA_ROOT/branding/` and
the field on the singleton → `post_save` fires `invalidate_site_config` → next request rebuilds the
bundle with `favicon_url`/`favicon_size` set → `{% favicon_links %}` emits `/media/branding/<file>` →
served by the `/media/` route.

**Manifest:** browser fetches `/site.webmanifest` after parsing the head → view reads the same cached
bundle → JSON reflects institution name + effective icons.

**Bare `/favicon.ico`:** a context with no icon link requests it → `favicon_ico` view reads the
bundle → 302 → static `favicon.ico` or the uploaded media file.

**Clear:** PA ticks Remove → `favicon-clear` → `ImageField` cleared → cache invalidated → next render
is back to the libli default. (The file itself is left on disk by Django's default behaviour; this
matches how `logo` already behaves and is not changed here.)

## Error handling

### Upload validation (`BrandingForm.clean_favicon`)

**Value-type guard first — this is where a naive `clean_favicon` 500s.** `FileField.clean(data,
initial)` puts three different things in `cleaned_data`:

- a freshly uploaded file — Django's `forms.ImageField.to_python` has set `.image` (the verified
  Pillow object) and `.content_type` on it;
- the sentinel `False` when the clear checkbox was ticked;
- the **existing `FieldFile`** when the PA saves the Branding form without touching the favicon.

Only the first carries `.image`. A `FieldFile` has `.size` but no `.image`, so any
`value.image.format` access on a plain "save the other branding fields" POST raises `AttributeError`
→ HTTP 500 on every subsequent Branding save. (`clean_logo` survives today only because `.size`
happens to exist on `FieldFile`.) So: `clean_favicon` returns the value unchanged unless
`getattr(value, "image", None)` is set.

Rules, **checked in this order** (cheapest first, so a fixture violating two rules reports
deterministically and "one test per refusal" is writable):

| # | rule | limit | reads | why |
|---|---|---|---|---|
| 1 | size | **≤ 256 KB** (`MAX_FAVICON_BYTES`, defined next to `MAX_LOGO_BYTES` in `institution/forms.py`) | `getattr(value, "size", 0)` — the byte count, mirroring `clean_logo`. **Not** `value.image.size`, which is a `(width, height)` tuple. | An icon fetched by every visitor has no legitimate reason to be larger. The logo's separate 2 MB cap is unchanged. |
| 2 | filename extension | **`.png`** | `os.path.splitext(value.name)[1].lower()` — case-folded, so `SCHOOL.PNG` is accepted | Narrows the extension to one. `upload_to="branding/"` preserves the uploaded **filename**, so a PNG named `mark.gif` would be stored and served same-origin under that extension. Only the **last** extension is inspected — `mark.svg.png` passes — which is correct here because every serving layer in the path (`core/media_serve.py`, and a real deployment's web server) also types the response off the last extension. |
| 3 | decoded format | **PNG** | `value.image.format` | Never trust the extension for content. |
| 4 | square | **width == height** | `value.image.size` | Every consumer renders in a square box; a non-square upload is squashed. "Crop it square first" beats silently distorting a school's logo. |
| 5 | dimensions | **192–512 px, both bounds inclusive** — `if not (192 <= w <= 512)` | `value.image.size` | The floor is 192 because the upload also becomes the manifest's sole icon and the iOS home-screen icon; below ~192 an installed app gets a blurry or rejected icon. The ceiling is 512 — the largest slot libli emits — which also keeps rules 1 and 5 describing a *non-empty* intersection (a 1024 px PNG routinely exceeds 256 KB). **Inclusive matters**: 512 is both the largest slot libli emits and the size of the generated default, so an exclusive comparison would reject the recommended upload. |

**The five refusal messages are written out here**, in both languages, for the same reason the widget
copy and help text are: they are the strings a PA actually sees, they carry the same numbers as the
help text, and inventing them at implementation time is how the two drift apart.

| rule | EN | PL |
|---|---|---|
| 1 | The favicon must be 256 KB or smaller. | Ikona strony może mieć najwyżej 256 KB. |
| 2 | The favicon must be a .png file. | Ikona strony musi być plikiem .png. | <!-- reachable for .gif/.bmp/.webp/.pdf; .svg/.html are caught earlier by Django -->
| 3 | The favicon must be a PNG image. | Ikona strony musi być obrazem PNG. |
| 4 | The favicon must be square — crop it to equal width and height first. | Ikona strony musi być kwadratowa — najpierw przytnij ją do równej szerokości i wysokości. |
| 5 | The favicon must be between 192 and 512 pixels. | Ikona strony musi mieć od 192 do 512 pikseli. |

Rules 2 and 3 read near-identically to a PA, which is deliberate: they are the disguised-extension and
the wrong-content cases, and collapsing them into one message would hide which check fired.

**ICO is not accepted**, though the generated default asset is one. An uploaded ICO would flow into
`<link rel="apple-touch-icon">`, where iOS ignores it and falls back to a page screenshot — one of the
four surfaces this feature promises, silently unbranded. PNG-only also makes the manifest `type`
constant and drops a bundle key.

**Two Django checks run *before* rule 1, and they own the cases this spec used to attribute to
rules 2 and 3.** Both were measured:

- `forms.ImageField.to_python` cannot open a genuine SVG with Pillow and raises
  `ValidationError("invalid_image")`, after which Django skips `clean_<field>` entirely. The PA sees
  the stock *"Upload a valid image…"*.
- `forms.ImageField.default_validators` includes `validate_image_file_extension`, which runs in
  `Field.clean()` — again **before** `clean_favicon`. So PNG bytes named `mark.svg` or `mark.html`
  error with Django's stock *"File extension “svg” is not allowed…"*, and rule 2's message is never
  produced for them.

Rule 2 is therefore reachable only for extensions **Pillow registers but this feature disallows** —
measured reachable: `mark.gif`, `mark.bmp`, `mark.webp`, `mark.pdf`. That is its real job: narrowing
Django's broad image-extension allowlist to one. The `.svg`/`.html` cases are still refused, just one
layer earlier and with a different message.

The reason all three layers matter: an uploaded SVG served same-origin from `/media/` is a stored-XSS
vector, and nothing in this codebase sanitizes SVG. As §3 notes, this is a **form-level** guarantee —
a shell/fixture write bypasses every one of them.

**Alpha channel is accepted, with a stated cost.** A transparent PNG is fine on a browser tab but iOS
composites transparency onto black on the home screen, and flattening it server-side is an explicit
non-goal. Transparent uploads are therefore accepted and still emitted as `apple-touch-icon`; the
help text warns about it.

**Label and help-text copy** (the only place a PA learns the constraints before uploading;
`gettext_lazy`). Written out in both languages for the same reason as the widget and refusal strings —
neither msgid exists in `locale/pl` today, and leaving them to the implementer is how copy drifts from
the PL screenshots.

| | EN | PL |
|---|---|---|
| label | Favicon | Ikona strony (favicon) |
| help text | Square PNG, 192–512 px, up to 256 KB. Replaces the libli icon in browser tabs and on home screens. Transparent areas show as black on iOS home screens — use a solid background for best results. | Kwadratowy plik PNG, 192–512 px, do 256 KB. Zastępuje ikonę libli w kartach przeglądarki i na ekranach głównych. Przezroczyste obszary wyświetlają się na czarno na ekranie głównym iOS — dla najlepszego efektu użyj jednolitego tła. |

Each failure is a field-level `ValidationError`, so the settings form re-renders at HTTP 200 with the
message next to the field. The existing PRG behaviour in `institution/views_manage.py` (valid POST →
save + 302 `?tab=`; invalid → full re-render 200) is unchanged, as is the wizard's
`_modelform_step`.

Validation is **fail-closed on unreadable input**: if Pillow cannot determine the format or
dimensions, the upload is rejected rather than accepted-and-hoped-for.

### Render-time robustness

- `favicon_url` dereferences `.url` only behind an `if inst.favicon` guard.
- `favicon_size` handles both a raising failure (`OSError`/`ValueError`, deleted file) and a
  non-raising one (`get_image_dimensions` returning `(None, None)` on a corrupt file) → `None`, on
  which both surfaces **omit** their size declaration (§6) rather than raising, emitting
  `"NonexNone"`, or substituting `"any"`.
- `theme-color` and the manifest's `theme_color` fall back to `PRIMARY_DEFAULT` when the stored brand
  colour is absent or fails `is_valid_css_color()`. This is reachable on a plain install:
  `_build()` returns `_safe_color(colors.get("primary"))`, i.e. `None`, whenever the `BrandColor` row
  is missing.
- The manifest view never 500s on a missing institution row: `get_site_config()` already returns
  `_DEFAULTS` when `Institution.objects.filter(pk=1).first()` is `None`.
- A stale `favicon_url` pointing at a deleted media file degrades to a broken icon, not an error page.
  No per-render existence check is added — that would be a filesystem stat on every request.

## Testing

Per the project's standing rule, every test below is **falsified before it is trusted**: delete or
invert the behaviour it guards and confirm it goes RED, rather than accepting a green run as evidence.

**Files**, named here because every other structural decision in this spec names one:

- `tests/test_favicon_build.py` — generator (new file).
- `tests/test_favicon_render.py` — bundle keys, head render, manifest and redirect routes (new file).
- `tests/test_settings_5c_forms.py` — the form-validation cases. This is where the existing
  branding-form tests already live (`test_branding_form_logo_clear_removes_logo`,
  `test_branding_form_logo_renders_thumbnail_and_remove_when_logo_set`) along with the `_branding_data`
  helper the new cases reuse. Do **not** create a `test_institution_settings.py` — there is no such
  file, and adding one would strand the new cases away from those fixtures.

  **`_png_file` must be generalized first.** It is currently a fixed `Image.new("RGB", (4, 4))` with
  only a `name` parameter, so it can build **none** of the eleven form-validation fixtures: at 4×4 the
  "valid PNG accepted", "exactly 192" and "exactly 512" cases all fail rule 5, and the `.gif`-named,
  `.png`-named ICO/JPEG, non-square, 1024-flat and 512-noise cases need other sizes, modes and
  formats. Add `size`, `mode` and `format` parameters (defaulted so every existing caller is
  unchanged). As-is it stays usable only for the model-level `inst.favicon.save(...)` paths — the
  clear test and the render tests — which bypass form validation entirely.
- `tests/test_setup_wizard.py` — the wizard Identity-step favicon case, beside the existing
  wizard-step tests.
- `tests/test_e2e_favicon.py` — e2e (`-m e2e` is mandatory or the whole group is silently deselected).

**Generator (`scripts/build_favicons.py`)** — all tests call `build(tmp_path)`; none write into the
working tree.

Each bullet states which artefact it opens — the **committed** file under
`core/static/core/img/favicon/`, or a **fresh** `build(tmp_path)` render — because that choice decides
whether the bullet is a correctness check or a drift guard.

- **SVG drift guard** (committed vs fresh): the committed `favicon.svg` is **byte-compared** against a
  fresh render. The SVG is pure string formatting with no Pillow involvement, so unlike the rasters
  this comparison is durable across Pillow releases — and it is the assertion that catches a geometry
  constant changing without the committed assets being regenerated.
- **SVG correctness** (committed) — separate from the drift guard, which cannot see it. Both sides of
  a byte-compare come out of the same formatter, so an SVG that emits `width="236"` instead of
  `width="64"`, drops an `rx`, or writes the dot's bounding box where its centre belongs is *stably*
  wrong and ships green. Since §1 makes SVG-vs-raster divergence the central hazard, and the only
  geometric measurement in the plan (the extent scan) runs exclusively on the PNG, parse the emitted
  SVG and assert the two `<rect>`s and the `<circle>` carry `x`/`y`/`width`/`height`/`rx` and
  `cx`/`cy`/`r` equal to the geometry table's **half-open** extents, plus `viewBox="0 0 512 512"` and
  the `xmlns`. This is the assertion that pins "the SVG emits half-open extents verbatim; the raster
  applies `− 1`" — the vector is the file most browsers actually render.
- **Raster drift guard** (committed vs fresh): the fresh render's per-file **dimensions, mode, corner
  alpha, sample set, *both extent scans*, and the maskable bounding box** must equal the committed
  files'. It replaces a naive "two fresh runs are byte-identical" idempotence check, which is
  **vacuous** — nothing in the generator could make two consecutive runs differ short of deliberately
  adding a timestamp.

  **The extent scans and maskable bbox are in this comparison deliberately**, because the weaker
  version (dimensions + mode + corner alpha + samples only) was measured to be nearly blind: mutating
  `STEM_Y`, `STEM_R`, `TILE_R`, or `DOT_R` and leaving the committed assets stale left it **green**,
  and only `STEM_X` reddened it — incidentally, via the 48 px ICO sample. So do **not** credit this
  guard with catching unregenerated geometry edits in general; the **SVG byte-compare** is what
  actually does that, and it is credited separately above.

  **Exactly what the strengthened guard was measured to catch**, mutation by mutation, so nobody
  later mistakes its coverage: `STEM_Y1 383→370` RED, `STEM_X +8` RED, `DOT_R 42→36` RED (via the
  maskable bbox), `DOT_CY 341→330` RED (48 px ICO sample), `TILE_R 112→96` RED (16/32 px ICO corner
  alpha) — but **`TILE_R 112→128` GREEN and `STEM_R 32→16` GREEN**. Those last two are the corner
  probes' job alone, which is why the probes are not redundant with this bullet and must not be
  dropped as such.
- Byte-comparing committed *rasters* against a fresh run is deliberately **not** done:
  `pyproject.toml` declares `pillow>=12.2.0` (a floor, not a pin) and PNG/ICO encoder output is not
  contracted across releases, so a routine lock bump would turn it RED with no code change.
- **Existence and dimensions** (committed): every declared file exists and its pixel dimensions match
  the output table.
- **ICO frame set** (committed): `Image.open(path).ico.sizes()` returns exactly
  `{(16,16), (32,32), (48,48)}`. The API matters because `.size` reports only the **largest** frame,
  so it cannot distinguish `{48}` from `{16,32,48}` and would sail past a dropped middle frame.
  (It would *not* miss the full ascending-order collapse — measured, `.size` is `(16,16)` there — but
  a set assertion is what actually pins the contract.)
- **Sampled pixels** (committed), in canvas units scaled per output as `round(u × size / 512)`:
  `(100, 256)` = primary (inside the tile, outside the artwork), `(204, 256)` = white (stem interior
  centre line), `(298, 341)` = accent (dot centre).

  **Exact equality holds only at outputs ≥ 48 px** — measured exact at 512/192/180/48 for all three
  points. It does **not** hold at the two small ICO frames: measured, the 32 px dot-centre sample is
  `(194,123,44)` against an expected `(199,123,42)`, and at 16 px the tile sample is `(24,128,122)`
  and the dot-centre sample `(148,125,66)` — nowhere near accent. The cause is that a margin expressed
  in *canvas* units is meaningless at small outputs (10 canvas units is 0.31 px at 16 px, while a 4×
  LANCZOS reduction draws from roughly ±96 canvas units, and the 64-unit stem is 2 px wide). **So:
  sample only outputs ≥ 48 px.**

  The margin rule is scoped to *new* sample points: any point added later must sit **at least 60% of
  the way from the feature's edge to its centre line**. Expressing it as an absolute pixel floor, or
  as "≥ half the feature width", does not work — half the width is the distance *at* the centre line,
  the maximum attainable, so such a rule admits only that one line and on a pixel grid often not even
  that. The three points above sit exactly on their centre lines and are grandfathered on measurement
  regardless.
- **16/32 px ICO frame content** (committed). Those two frames are drawn independently, so they have
  an independent failure mode — blank, transparent, or tile-only — that the frame-set and dimension
  assertions all pass on. They are excluded from colour sampling, not from checking, so assert a weak
  but non-vacuous set: each frame has **≥ 3 distinct RGBA values** (not uniform), its **centre pixel
  is fully opaque**, and the pixel at the scaled dot centre is **channel-wise closer to accent than to
  primary** by **Euclidean RGB distance** (measured at 16 px: `(148,125,66)`, ≈ 56 to accent vs ≈ 139
  to primary — the margin is comfortable). Note the metric differs from the maskable bullet's
  max-per-channel one deliberately; under max-per-channel the same pixel reads 51 vs 128. Measure and
  pin the exact values when implementing; the spec fixes the form of the assertion, not invented
  numbers.
- **Rendered-extent assertion** (committed), the guard for the endpoint-inclusive convention. It needs
  a classification predicate, and the obvious ones disagree: on the 512 render, scanning for *exactly*
  white gives x 173–234, while a threshold scan gives 172–235. **Predicate: a pixel belongs to the
  stem iff all three RGB channels are ≥ 200.** Under it, both expected ranges are **pinned as measured
  literals**, not derived by scaling at test time — a derived expectation lands on `.5`/`.125`
  fractions where round-vs-floor changes the answer and a ±1 tolerance is exactly saturated:
  - `icon-512.png`: **x 172–235, y 129–382**, exact equality.
  - `icon-192.png`: **x 65–87, y 49–142**, exact equality.

  Run it **only on those two outputs** — the boundary is set by which sizes have measured literals,
  not by a property of 180 px (where the stem is a perfectly measurable 22.5 output px wide). The
  separate 16 px arithmetic below is about the ICO frames' colour sampling, not this assertion.

  **The `≥ 200` predicate alone does not catch a missing `− 1`, and this was measured.** Rendering the
  mark with the correction and without it (the naive half-open transcription — exactly "the endpoint
  convention got wrong") produces *identical* results under that predicate at both sizes, and
  identical results for every colour sample, the corner probe, and the 16 px frame checks. The rasters
  really do differ (the stem is 0.25 canvas units fat) but nothing in the plan would have gone RED,
  and raster byte-comparison is deliberately excluded — so the most heavily argued mechanism in §1
  would have shipped unguarded. The asymmetry: `≥ 200` *does* catch **over**-correction (subtracting a
  whole final pixel gives `172–234, 129–381`), which is what made it look sufficient.

  So pin **both predicates** on `icon-512.png`:

  - `≥ 200` in all channels → **x 172–235, y 129–382** (catches over-correction);
  - **exactly white** (`255,255,255`) → **x 173–234, y 130–381** (catches the *missing* correction,
    which shifts this scan to `173–235, 130–382`).

  And pin the maskable bounding box as **exact measured literals** rather than the ±2 tolerance:
  x 172–339, y 129–382 (a missing `− 1` moves it to x 172–340, y 129–383, which the tolerance would
  have absorbed). Keep the half-diagonal < 204.8 check as a separate safe-zone assertion.

  **Falsification for this guard is deleting the `− 1` itself**, not editing a geometry constant — a
  constant edit reddens the centring and SVG assertions instead and proves nothing about the
  convention.
- **Corner-radius probes** (committed). What is unguarded is specifically the **raster-side `r · s`
  scaling** — the SVG-correctness bullet already pins `rx="112"` and `rx="32"` on the vector side,
  while on the raster side the corner-alpha assertion at `(0,0)` reads `(0,0,0,0)` for any radius above
  ~2 and no sample point sits near a corner.

  **The two probe points must bracket the arc tightly enough to be bidirectionally discriminating,
  while avoiding the arc itself.** Along the diagonal the boundary sits at `R(1 − 1/√2) ≈ 0.293·R`,
  i.e. `d ≈ 32.8` for `R = 112`. Two failure modes, both measured:

  - **Too loose:** `(30,30)` transparent and `(40,40)` tile both hold when `TILE_R` moves 112 → 128
    (boundary 37.5), so that pair stays green on a radius increase.
  - **Too tight:** `d = 32` is *not* transparent — it reads `(15,120,120,17)`, a pixel sitting
    directly on the arc (supersample distance 449.7 vs radius 448, so ~1 of 16 subpixels covered).
    It is the single most resampling-fragile point on the tile, exactly the kind of value the
    "pin as literals" discipline must not be applied to.

  **Use `d = 30` and `d = 34`**, both fully saturated and bidirectionally discriminating: measured,
  `(30,30)` is `(0,0,0,0)` at `R = 112` and `(20,126,120,255)` at `R = 96`; `(34,34)` is
  `(20,126,120,255)` at `R = 112` and `(0,0,0,0)` at `R = 128`. Derive the stem-cap probe the same
  way — bracket its arc with saturated pixels, never a straddling one.

  Add a **second probe on the stem's cap** for the same reason: `STEM_R 32 → 16` was measured to
  redden nothing in the entire raster set, so the tile probe alone leaves the stem's radius scaling
  unguarded.
- The centred-bounding-box assertion fires when the geometry is nudged off-centre; the
  `PRIMARY_DEFAULT`/`ACCENT_DEFAULT` equality assertion fires when the palette diverges.
- **Maskable safe zone, measured from the render** (committed), not computed from the constants. The
  §2 inequality (152.3 < 204.8) is derived from the same constants used to draw, so as an assertion it
  is a tautology — it can only fail if someone edits the geometry table, and cannot catch a bug in the
  maskable *rendering* path (a stray offset, a wrong `s`, an accidental inset), which is the one thing
  that variant is uniquely exposed to. So: scan `icon-maskable-512.png` for the bounding box of pixels
  whose **maximum absolute per-channel difference** from the tile colour exceeds 24 — exact RGBA
  inequality would sweep in every anti-aliasing and ringing pixel, the same reason the stem assertion
  uses a threshold rather than exact white. Assert the box's **exact measured extents (x 172–339,
  y 129–382)** and that its half-diagonal is < 204.8. The exact literals replace an earlier ±2 px
  centring tolerance, which was measured to absorb a missing `− 1` (it moves the box to x 172–340,
  y 129–383) — the same distinction the extent assertion makes between constants and pixels.
- **Mode and corners** (committed): every raster is `RGBA`; `icon-512.png` and `favicon.ico`'s 48 px
  frame have corner pixel `(0,0,0,0)`, while `apple-touch-icon.png` and `icon-maskable-512.png` have
  alpha 255 at all four corners — the assertion that actually distinguishes the variants.

**Config bundle**
- `favicon_url` is `None` with no upload, the media URL with one, and `None` again after a clear.
- `favicon_size` is `"WxH"` for a real upload, `None` when the file is **missing**, and `None` when
  the file is **present with an unreadable image header** (the `(None, None)` path — not the same
  test; the fixture is `b"not an image"`, not a truncated PNG, per §5).
- The bundle is invalidated on `Institution.save()` (the existing signal covers it; this proves it
  covers the new keys too).

**Form validation** — one test per refusal. Each asserts the **exact written-out message** for the
rule it targets, not merely that the field errored: rules 2 and 3 read near-identically to a PA, and
message equality is the only thing that proves which check fired.

Three fixtures need pinning or they trip the wrong rule:

- **The rule-2 fixture is PNG bytes named `mark.gif`**, not `mark.svg`. Django's
  `validate_image_file_extension` runs before `clean_favicon` and rejects `.svg`/`.html` with its own
  stock message, so a `.svg`-named fixture never reaches rule 2 and its message assertion goes RED.
  `.gif` is in Django's allowlist but not in this feature's, which is precisely the gap rule 2 exists
  to close.
- **Rule 3 fixtures carry a `.png` filename.** Rule 2 runs first, so a plain `.ico`/`.jpg` upload
  fails on the extension and yields message 2 — leaving rule 3 untested. The rule-3 cases are ICO
  bytes and JPEG bytes *named* `mark.png`.
- **The over-the-ceiling fixture is a 1024×1024 flat-colour PNG.** Rule 1 runs first and, as rule 5's
  own justification says, a 1024 px PNG routinely exceeds 256 KB — so a photographic fixture yields
  message 1. Flat colour compresses to a few KB and reaches rule 5. Conversely the too-large fixture
  is a 512 px **noise** PNG, which is what reliably exceeds 256 KB while staying inside the ceiling.

The cases, with message equality asserted except where noted: too-large; `.gif`-named PNG bytes;
`.png`-named ICO; `.png`-named JPEG; non-square; 32 px (under the floor); 1024 px flat-colour (over
the ceiling); **exactly 192 px accepted**; **exactly 512 px accepted**; valid square PNG accepted;
**uppercase `.PNG` accepted**. Two cases assert only *that the field errors*, never the wording,
because Django owns those messages and they are not `clean_favicon`'s: a **genuine SVG**
(`invalid_image`) and **`.svg`-named PNG bytes** (`validate_image_file_extension`). Plus
`favicon-clear` empties the field. Plus the value-type guard: **saving the Branding form without
touching the favicon does not raise** (the `FieldFile` path), and a clear (`False`) short-circuits
before any Pillow access. That pair is the regression test for the 500 described above.

**Head render**
- `base.html` with no override contains the SVG/ICO/apple-touch/manifest links and a `theme-color`.
- **Link order is asserted, not left to the manual check.** The ICO `<link>`'s index in the response
  body precedes the SVG `<link>`'s (order is what decides selection — see §6), and each link's
  `sizes` is asserted **per element**: `16x16 32x32 48x48` on the ICO, `any` on the SVG. Swapping the
  emission order must turn this RED — otherwise the exact configuration that makes Chromium ignore
  the SVG could be reintroduced and ship green.
  A whole-body `'sizes="any"' in body` containment assertion is **not** sufficient: it is true
  wherever the attribute sits, and it shipped green on the broken markup. Resolve the individual
  `<link>` element and assert on that.
- With an override, the icon links point at the media URL and the static default icons are *absent*
  (not merely present-alongside).
- A media filename containing HTML-special characters is escaped in the `href` — the falsification for
  choosing `format_html` over `mark_safe`. **It must be built by patching `favicon_url` in the cached
  bundle** — the same construction the malformed-colour case uses — and by no other route. Two
  plausible alternatives are both measurably vacuous:
  - *uploading* such a filename: `get_valid_filename` strips exactly those characters
    (`sch"ool<x>&.png` → `schoolx.png`);
  - setting `inst.favicon.name` directly: `FileSystemStorage.url()` runs `filepath_to_uri`, yielding
    `/media/branding/sch%22ool%3Cx%3E%26.png` — percent-encoded, containing none of `" < > &`.

  Under either, `format_html` and `mark_safe` produce byte-identical output and the test passes with
  the fix reverted. Only the patched bundle discriminates (measured: `sch&quot;ool&lt;x&gt;&amp;.png`
  versus the raw string).
- With an override whose `favicon_size` is `None`, the head link **omits** its `sizes` attribute
  (the counterpart of the manifest assertion below).
- `theme-color` equals `PRIMARY_DEFAULT` when the stored primary is `None`, and again when it is
  malformed; same for the manifest's `theme_color`. Both must go RED with the fallback removed. The
  `None` case is reachable on a plain install; the **malformed** case is not — `_build()` already runs
  `_safe_color()`, so `cfg["primary"]` is only ever a valid string or `None` — and is therefore
  constructed by patching the cached bundle. It is still worth having: it falsifies the tag's own
  defense-in-depth, which is the layer that would survive a future change to `_safe_color`.
- A **404 response body** contains the `rel="icon"` link. `403.html`/`404.html` extend `base.html`, but
  they render through Django's error handlers rather than a normal view, so that coverage is a premise
  worth measuring rather than inferring.
- `500.html` renders standalone under an empty `Context()` and contains **no** `/static/` reference
  and no `favicon` link. Falsification: adding `{% load branding %}{% favicon_links %}` (or any
  `{% static %}` link) to that file turns it RED.

**Routes**
- `/site.webmanifest` returns 200, `application/manifest+json`, valid JSON, the institution's name,
  and the default icon trio with `type`, `sizes`, and the maskable `purpose`.
- `short_name` at its boundaries: a ≤12-char name passes through; a long multi-word name truncates at
  the word boundary **with no trailing space** (assert the exact string); a name whose first word
  exceeds 12 characters yields the exact string `"Międzynarodo"` (the main path — there is no
  hard-truncate branch to test); a whitespace-only name falls back to the default; and the
  **default install**
  case, `"My Institution"` (14 chars) → `"My"`. That last one is the short name every unconfigured
  install ships, so it is asserted rather than discovered — it is the correct output of the rule, not
  an oversight.
- With an override, the manifest has a single icon entry carrying `favicon_size` and
  `"type": "image/png"`; when `favicon_size` is `None` the entry **omits the `sizes` key entirely**
  (not `"any"` — see §6).
- The manifest is reachable **anonymously**.
- `/favicon.ico` 302s to the static asset by default and to the media URL with an override, and sets
  **no** `Cache-Control` header.

**e2e** (`-m e2e`, driving the real UI rather than `page.evaluate`)
- A PA opens `/manage/settings/` → Branding, uploads a PNG through the real file input, saves, and the
  head's `rel="icon"` href moves to `/media/`; then ticks Remove, saves, and it moves back to the
  static default.
- The generalized widget did not break the **logo** field: uploading a logo still previews and still
  clears, and the two fields' hooks do not cross-fire (uploading a favicon must not change the logo
  thumb).
- The first-run wizard's Identity step accepts a favicon upload and persists it.

**i18n** — EN/PL for the new field label, the help-text copy above, the five widget strings, the five
validation messages, **and the newly-catalogued `logo` `verbose_name`**. That last one is easy to
miss and reddens the suite: `msgid "Logo"` does not exist in `locale/pl` today, and
`tests/test_i18n_po_health.py::test_pl_has_no_untranslated_msgid` fails on any PL entry with an empty
`msgstr`, so `_("Logo")` must ship with `msgstr "Logo"`. The five existing logo *widget* msgids must
remain byte-identical; zero fuzzy and zero obsolete entries in either catalogue; `.mo` files
recompiled.

**Visual verification** — the Branding field screenshotted in light *and* dark (judged separately, not
inferred from one another), including the icon variant's **empty state** and its filled state, plus
the generated mark rendered at 16/32/180 px and actually looked at before shipping. Three things a
screenshot alone cannot settle, checked explicitly:

- the empty tile gets an **accessibility snapshot** — a screenshot cannot show whether `role="img"` +
  `aria-label` produced an accessible name;
- picking a file on an **empty** favicon field shows a preview (the `<div>`→`<img>` swap in §4 item 4);
- the browser renders the **SVG**, not the ICO, in a modern engine — the expected outcome of the
  ICO-first / SVG-last link ordering in §6. Measure it from a **server access log** with a **headed**
  browser: headless fetches no favicon at all, and Playwright route interception skews the result.

## Docs

Adding a field to the Branding tab makes the PA help topic and its shipped screenshots wrong, and this
repo has an existing mechanism for both:

- `docs/help/platform-admin/branding-settings.md` and its `.pl.md` twin enumerate the tab field by
  field ("Set the institution **name** and **logo** (2 MB max), the **primary** and **accent**
  colours…"). Both get the favicon and its constraints.
- That topic embeds `static:core/img/help/branding.en.png`, regenerated by
  `tests/capture_help_screenshots.py` (shot `"branding"` → topic `branding-settings`). Both
  `branding.en.png` and `branding.pl.png` are re-captured through that script rather than by hand.
- `docs/help/platform-admin/first-run-wizard.md` and its `.pl.md` twin enumerate the wizard's Identity
  step ("your institution's name, logo, colours and languages"), which §4 changes. Both get the
  favicon. Their `wizard` shot photographs the **Welcome** step, not Identity, so no screenshot needs
  re-capturing there.
