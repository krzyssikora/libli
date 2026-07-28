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
endpoint-inclusive box. Subtracting one *final* pixel instead would over-trim by 4 supersample pixels
(a 0.75 px error on the stem width), and subtracting one *canvas unit* would over-trim by 4×. Worked
example, `icon-512.png` (`size = 512`, `s = 4`, supersample canvas 2048×2048): the stem box is
`(688, 516, 943, 1531)`. The SVG has no such correction — it emits the half-open extents verbatim.

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
- the **rendered** stem and dot extents, measured in pixels from the produced raster (not from the
  constants), match the table — this is the one that catches the endpoint convention being got wrong,
  which the constants-only assertion cannot see. It needs a stated classification predicate and a
  stated size range to be writable at all; see "Testing".

Fill colours are literals in the generator, **not** reads of `BrandColor` — the default mark is a
fixed libli asset, and a PA who wants their own colours uploads their own icon. Both fills are the
documented defaults (`core.services.PRIMARY_DEFAULT`, `ACCENT_DEFAULT`); the generator asserts this
equality at build time so a future default-palette change is caught rather than silently diverging.

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
the filename list, so a newly added output cannot silently escape them.

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
change), and one line in the dev-onboarding docs (`docs/dev/`) pointing at it.

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

Migration `institution/0008_institution_favicon.py`.

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
   box — *and* takes the empty-state branch below. It is a boolean rather than a CSS-class string
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
   `data-file-thumb` hook and thumb classes, then set its `src`. This repairs the logo field's
   identical latent gap at the same time.

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
  a **truncated or corrupt** file makes `django.core.files.images.get_image_dimensions` return
  `(None, None)` *without raising*, so an explicit `if width and height` guard is required too —
  otherwise the manifest ships the literal string `"NonexNone"`.

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

- *No override:* `<link rel="icon" href="…/favicon.svg" type="image/svg+xml" sizes="any">` **first**,
  then `<link rel="icon" href="…/favicon.ico" sizes="16x16 32x32 48x48">` (declaring what that file
  actually contains, since this spec argues elsewhere for accurate `sizes`),
  `<link rel="apple-touch-icon" href="…/apple-touch-icon.png">`,
  `<link rel="manifest" href="{% url 'core:webmanifest' %}">`,
  `<meta name="theme-color" content="<effective primary>">`.
- *Override set:* the three icon links collapse to two pointing at the uploaded file —
  `<link rel="icon" href="{{ favicon_url }}" type="image/png" sizes="{{ favicon_size }}">` (the
  `sizes` attribute omitted entirely when `favicon_size` is `None`) and
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

**Which icon link wins matters, and the two default links compete.** Two `rel="icon"` links are
selected between partly by declared `sizes`, and a vector link with *no* `sizes` against an ICO
declaring exactly the 16/32 a tab wants is the combination that has historically made Chromium ignore
the SVG entirely — which would make the vector dead weight. Hence `sizes="any"` on the SVG link (the
accurate declaration for a vector) and SVG-first ordering. **Expected outcome: a modern browser renders
the SVG; the ICO is the legacy fallback.** That is a checkable claim, so the visual-verification step
checks it rather than assuming it.

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

`short_name` rule, fully specified because its boundary is where this kind of thing breaks: take
`name`; if it is ≤ 12 characters use it as-is; otherwise truncate at the last word boundary at or
before 12 characters **and right-strip the result**; if that yields an empty string (the first word is
itself longer than 12 characters — "Międzynarodowe", "Gesamtschule") hard-truncate to exactly 12
characters. `name` itself is never empty — `get_site_config()` already falls back to
`_DEFAULTS["name"]`.

`icons` is the 192/512/maskable trio by default, each with `"type": "image/png"` and its `sizes`; the
maskable entry additionally carries `"purpose": "maskable"`. With an override it is a **single** entry
`{"src": favicon_url, "sizes": favicon_size or "any", "type": "image/png", "purpose": "any"}` — an
override therefore forgoes the maskable variant, so Android may crop the uploaded icon under an
adaptive-icon mask. That is an accepted trade (deriving a maskable variant would mean server-side
image generation, an explicit non-goal), stated rather than silent.

The manifest must be a **view** rather than a static file precisely because both `name` and `icons`
depend on institution state.

**`core/views.py::favicon_ico`** — `/favicon.ico`, a 302 to the effective icon URL (override if set,
else the static `favicon.ico`). A browser that has parsed an HTML page declaring `<link rel="icon">`
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
| 2 | filename extension | **`.png`** | `os.path.splitext(value.name)[1].lower()` — case-folded, so `SCHOOL.PNG` is accepted | `upload_to="branding/"` preserves the uploaded **filename**, so a file whose bytes decode as PNG but whose name is `mark.svg` or `mark.html` would be stored and served same-origin under that extension. Checking format alone does not close that; both checks are deliberate. Only the **last** extension is inspected — `mark.svg.png` passes — which is correct here because every serving layer in the path (`core/media_serve.py`, and a real deployment's web server) also types the response off the last extension. |
| 3 | decoded format | **PNG** | `value.image.format` | Never trust the extension for content. |
| 4 | square | **width == height** | `value.image.size` | Every consumer renders in a square box; a non-square upload is squashed. "Crop it square first" beats silently distorting a school's logo. |
| 5 | dimensions | **192–512 px** | `value.image.size` | The floor is 192 because the upload also becomes the manifest's sole icon and the iOS home-screen icon; below ~192 an installed app gets a blurry or rejected icon. The ceiling is 512 — the largest slot libli emits — which also keeps rules 1 and 5 describing a *non-empty* intersection (a 1024 px PNG routinely exceeds 256 KB). |

**The five refusal messages are written out here**, in both languages, for the same reason the widget
copy and help text are: they are the strings a PA actually sees, they carry the same numbers as the
help text, and inventing them at implementation time is how the two drift apart.

| rule | EN | PL |
|---|---|---|
| 1 | The favicon must be 256 KB or smaller. | Ikona strony może mieć najwyżej 256 KB. |
| 2 | The favicon must be a .png file. | Ikona strony musi być plikiem .png. |
| 3 | The favicon must be a PNG image. | Ikona strony musi być obrazem PNG. |
| 4 | The favicon must be square — crop it to equal width and height first. | Ikona strony musi być kwadratowa — najpierw przytnij ją do równej szerokości i wysokości. |
| 5 | The favicon must be between 192 and 512 pixels. | Ikona strony musi mieć od 192 do 512 pikseli. |

Rules 2 and 3 read near-identically to a PA, which is deliberate: they are the disguised-extension and
the wrong-content cases, and collapsing them into one message would hide which check fired.

**ICO is not accepted**, though the generated default asset is one. An uploaded ICO would flow into
`<link rel="apple-touch-icon">`, where iOS ignores it and falls back to a page screenshot — one of the
four surfaces this feature promises, silently unbranded. PNG-only also makes the manifest `type`
constant and drops a bundle key.

**SVG is rejected, but not by these rules — and the distinction matters for the error message.** A
genuine SVG never reaches `clean_favicon` at all: `forms.ImageField.to_python` cannot open it with
Pillow and raises `ValidationError("invalid_image")` first, after which Django skips the field's
`clean_<field>` entirely. The PA therefore sees Django's stock *"Upload a valid image. The file you
uploaded was either not an image or a corrupted image."* Rules 2 and 3 exist for the **disguised**
case — PNG bytes named `mark.svg`. The reason both paths matter: an uploaded SVG served same-origin
from `/media/` is a stored-XSS vector, and nothing in this codebase sanitizes SVG. As §3 notes, this
is a **form-level** guarantee — a shell/fixture write bypasses it.

**Alpha channel is accepted, with a stated cost.** A transparent PNG is fine on a browser tab but iOS
composites transparency onto black on the home screen, and flattening it server-side is an explicit
non-goal. Transparent uploads are therefore accepted and still emitted as `apple-touch-icon`; the
help text warns about it.

**Help text copy** (the only place a PA learns the constraints before uploading; `gettext_lazy`, EN
and PL):

> Square PNG, 192–512 px, up to 256 KB. Replaces the libli icon in browser tabs and on home screens.
> Transparent areas show as black on iOS home screens — use a solid background for best results.

Each failure is a field-level `ValidationError`, so the settings form re-renders at HTTP 200 with the
message next to the field. The existing PRG behaviour in `institution/views_manage.py` (valid POST →
save + 302 `?tab=`; invalid → full re-render 200) is unchanged, as is the wizard's
`_modelform_step`.

Validation is **fail-closed on unreadable input**: if Pillow cannot determine the format or
dimensions, the upload is rejected rather than accepted-and-hoped-for.

### Render-time robustness

- `favicon_url` dereferences `.url` only behind an `if inst.favicon` guard.
- `favicon_size` handles both a raising failure (`OSError`/`ValueError`, deleted file) and a
  non-raising one (`get_image_dimensions` returning `(None, None)` on a corrupt file) → `None` → the
  manifest entry falls back to `"sizes": "any"` rather than raising or emitting `"NonexNone"`.
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
`tests/test_favicon_build.py` (generator), `tests/test_favicon_render.py` (bundle keys, head render,
manifest and redirect routes), `tests/test_institution_settings.py` (the form-validation cases, beside
the existing branding-form tests), and `tests/test_e2e_favicon.py` (e2e — `-m e2e` is mandatory or the
whole group is silently deselected).

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
  alpha, and sample set** must equal the committed files'. This replaces a naive "two fresh runs are
  byte-identical" idempotence check, which is **vacuous** — nothing in the generator could make two
  consecutive runs differ short of deliberately adding a timestamp, so there is nothing to delete that
  turns it RED. This version has a deletable guard: change a geometry constant without regenerating
  and it goes RED.
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

  The margin rule is stated in output pixels and scoped to *new* sample points: any point added later
  must sit **≥ half the narrowest feature it is sampling** from that feature's edge. The three points
  above are grandfathered on measurement, not on the rule — at 48 px the stem is 6 output px wide
  (3 px of margin) and the dot's radius is 3.9 output px, so a flat "≥ 4 output px" rule would have
  excluded the very samples that are verified exact.
- **16/32 px ICO frame content** (committed). Those two frames are drawn independently, so they have
  an independent failure mode — blank, transparent, or tile-only — that the frame-set and dimension
  assertions all pass on. They are excluded from colour sampling, not from checking, so assert a weak
  but non-vacuous set: each frame has **≥ 3 distinct RGBA values** (not uniform), its **centre pixel
  is fully opaque**, and the pixel at the scaled dot centre is **channel-wise closer to accent than to
  primary** (measured at 16 px: `(148,125,66)`, distance ≈ 56 to accent vs ≈ 139 to primary — the
  margin is comfortable). Measure and pin the exact values when implementing; the spec fixes the form
  of the assertion, not invented numbers.
- **Rendered-extent assertion** (committed), the guard for the endpoint-inclusive convention. It needs
  a classification predicate, and the obvious ones disagree: on the 512 render, scanning for *exactly*
  white gives x 173–234, while a threshold scan gives 172–235. **Predicate: a pixel belongs to the
  stem iff all three RGB channels are ≥ 200.** Under it, both expected ranges are **pinned as measured
  literals**, not derived by scaling at test time — a derived expectation lands on `.5`/`.125`
  fractions where round-vs-floor changes the answer and a ±1 tolerance is exactly saturated:
  - `icon-512.png`: **x 172–235, y 129–382**, exact equality.
  - `icon-192.png`: **x 65–87, y 49–142**, exact equality.

  Do not run this at 180 px or below — at 16 px the stem is 2 px wide and a ±1 px classification error
  is a 50% error. The 512 assertion is the load-bearing one: getting the endpoint convention wrong
  shifts it to 172–236, which exact equality catches and a tolerance would mask.
- **Corner-radius probe** (committed): the radius constants are otherwise unguarded — the corner-alpha
  assertion at `(0,0)` reads `(0,0,0,0)` for any radius above ~2, the extent predicate only measures
  the white stem, and no sample point sits near a corner. So: on `icon-512.png`, assert one pixel just
  *inside* the radius-112 arc is the tile colour and one just *outside* it is transparent. Measure both
  coordinates when implementing and pin them as literals.
- The centred-bounding-box assertion fires when the geometry is nudged off-centre; the
  `PRIMARY_DEFAULT`/`ACCENT_DEFAULT` equality assertion fires when the palette diverges.
- **Maskable safe zone, measured from the render** (committed), not computed from the constants. The
  §2 inequality (152.3 < 204.8) is derived from the same constants used to draw, so as an assertion it
  is a tautology — it can only fail if someone edits the geometry table, and cannot catch a bug in the
  maskable *rendering* path (a stray offset, a wrong `s`, an accidental inset), which is the one thing
  that variant is uniquely exposed to. So: scan `icon-maskable-512.png` for the bounding box of pixels
  that are **not** the tile colour, and assert that box's half-diagonal is < 204.8 and that it is
  centred. Same distinction the extent assertion already makes between constants and pixels.
- **Mode and corners** (committed): every raster is `RGBA`; `icon-512.png` and `favicon.ico`'s 48 px
  frame have corner pixel `(0,0,0,0)`, while `apple-touch-icon.png` and `icon-maskable-512.png` have
  alpha 255 at all four corners — the assertion that actually distinguishes the variants.

**Config bundle**
- `favicon_url` is `None` with no upload, the media URL with one, and `None` again after a clear.
- `favicon_size` is `"WxH"` for a real upload, `None` when the file is **missing**, and `None` when
  the file is **present but corrupt** (the `(None, None)` path — not the same test).
- The bundle is invalidated on `Institution.save()` (the existing signal covers it; this proves it
  covers the new keys too).

**Form validation** — one test per refusal, each asserting the *field-scoped* error, plus the accept
and clear paths: too-large file, `.svg`-named PNG bytes, a **genuine SVG** (asserting only that the
field errors, not the message wording — that path is `forms.ImageField`'s stock `invalid_image`, not
`clean_favicon`), ICO, JPEG, non-square, 32 px (under the
floor), 1024 px (over the ceiling), valid square PNG accepted, **uppercase `.PNG` accepted**,
`favicon-clear` empties the field. Plus the value-type guard: **saving the Branding form without
touching the favicon does not raise** (the `FieldFile` path), and a clear (`False`) short-circuits
before any Pillow access. That pair is the regression test for the 500 described above.

**Head render**
- `base.html` with no override contains the SVG/ICO/apple-touch/manifest links and a `theme-color`.
- With an override, the icon links point at the media URL and the static default icons are *absent*
  (not merely present-alongside).
- A media filename containing HTML-special characters is escaped in the `href` — the falsification for
  choosing `format_html` over `mark_safe`.
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
  exceeds 12 characters hard-truncates to exactly 12 and is never empty; and the **default install**
  case, `"My Institution"` (14 chars) → `"My"`. That last one is the short name every unconfigured
  install ships, so it is asserted rather than discovered — it is the correct output of the rule, not
  an oversight.
- With an override, the manifest has a single icon entry carrying `favicon_size` (or `"any"` when the
  file is unreadable) and `"type": "image/png"`.
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

**i18n** — EN/PL for the new field label, the help-text copy above, the five widget strings, and every
validation message; the five existing logo msgids must remain byte-identical; zero fuzzy and zero
obsolete entries in either catalogue; `.mo` files recompiled.

**Visual verification** — the Branding field screenshotted in light *and* dark (judged separately, not
inferred from one another), including the icon variant's **empty state** and its filled state, plus
the generated mark rendered at 16/32/180 px and actually looked at before shipping. Three things a
screenshot alone cannot settle, checked explicitly:

- the empty tile gets an **accessibility snapshot** — a screenshot cannot show whether `role="img"` +
  `aria-label` produced an accessible name;
- picking a file on an **empty** favicon field shows a preview (the `<div>`→`<img>` swap in §4 item 4);
- the browser renders the **SVG**, not the ICO, in a modern engine — the expected outcome of the
  `sizes="any"` + link-order choice in §6.

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
