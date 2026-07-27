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
   default. The one deliberate exception is `templates/500.html`, which carries no icon at all — see
   "Render surfaces".

The override rides the branding path that already exists for `Institution.logo` — same singleton
model, same form, same cached `get_site_config()` bundle, same cache invalidation — so it adds a
field and a few render surfaces rather than a subsystem.

### Non-goals

- **No service worker / offline support.** The manifest makes libli installable and gives iOS and
  Android a real home-screen icon; it does not make libli work offline. No service worker is added.
- **No SVG uploads.** See "Error handling" for why this is a deliberate refusal, not an omission.
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

**Geometry constants** — a 512×512 canvas, all values in canvas units. The artwork bounding box is
**168 × 254**, centred by construction: x 172→340 (margins 172/172), y 129→383 (margins 129/129).

| element | shape | value |
|---|---|---|
| tile | rounded rect | full-bleed 0,0–512,512; corner radius 112 |
| stem | rounded rect | x 172→236 (width 64), y 129→383 (height 254); corner radius 32 |
| dot | circle | radius 42, centre (298, 341) — so its right edge is x=340 and its bottom edge y=383, sharing the stem's baseline |

The dot's left edge (256) clears the stem's right edge (236) by 20 units.

The generator **asserts** the artwork bounding box is centred (left margin == right margin, top ==
bottom) so the centring is enforced rather than implied — this is arithmetic, not optical
compensation, and a future geometry tweak that breaks it should fail the build.

Fill colours are literals in the generator, **not** reads of `BrandColor` — the default mark is a
fixed libli asset, and a PA who wants their own colours uploads their own icon. Both fills are the
documented defaults (`core.services.PRIMARY_DEFAULT`, `ACCENT_DEFAULT`); the generator asserts this
equality at build time so a future default-palette change is caught rather than silently diverging.

### 2. `scripts/build_favicons.py` — single source of geometry

Pillow (a dependency already; `pyproject.toml` declares `pillow>=12.2.0`) cannot rasterize SVG, so
rather than add a renderer dependency, the geometry above lives **once** as module-level constants and
the script emits both the vector and the rasters from them. Every shape used is expressible in both
media (`<rect rx>`/`<circle>` in SVG; `ImageDraw.rounded_rectangle`/`ellipse` in Pillow), so the two
can't drift.

Rasters are drawn at **4× supersample and downsampled with `Image.LANCZOS`** — Pillow's `ImageDraw`
does not antialias (verified: a filled ellipse yields exactly two distinct colours), and an aliased
32 px icon looks broken.

The script takes an **output directory** — `--out`, defaulting to the committed
`core/static/core/img/favicon/`. This is load-bearing for the tests: they render into `tmp_path` and
compare, so a test run never writes into the working tree and never races another `pytest-xdist`
worker on the same files.

Outputs, all committed to `core/static/core/img/favicon/`:

| file | size(s) | variant geometry |
|---|---|---|
| `favicon.svg` | vector | the geometry table above, verbatim |
| `favicon.ico` | 16, 32, 48 | same geometry; see the frame mechanism below |
| `apple-touch-icon.png` | 180×180 | **corner radius 0** (squared, full-bleed tile) and **opaque** — iOS applies its own corner mask and composites transparency onto black, so a pre-rounded tile would show background wedges inside the mask. Artwork scale 1.0, unchanged and centred; no inset (the artwork's half-diagonal, 152.3 units, sits well inside iOS's mask). |
| `icon-192.png` | 192×192 | the geometry table above, verbatim |
| `icon-512.png` | 512×512 | the geometry table above, verbatim |
| `icon-maskable-512.png` | 512×512 | **corner radius 0** (tile colour bled to all four edges), artwork **scale 1.0**, centred — no translation. The maskable safe zone is the *inscribed circle* of radius 0.4 × 512 = 204.8 centred on the canvas; the artwork's half-diagonal is √(84² + 127²) = 152.3 < 204.8, so it already fits at full scale. The generator asserts this inequality. |

**ICO frame mechanism** (the committed bytes must be reproducible from this spec): each of the three
frames is drawn **independently** at 4× its own size and downsampled, then written with
`frames[0].save(..., format="ICO", sizes=[(48,48),(32,32),(16,16)], append_images=frames[1:])`.
Verified in this project's environment: `append_images` is honoured, all three frames land, and the
result is **not** byte-identical to handing Pillow a single source image with `sizes=` (which resizes
internally) — so naming the mechanism is what makes the output reproducible.

The script is idempotent — two runs from the same source produce byte-identical output — and is the
documented way to regenerate the assets. It is not run at request time or at deploy time.

### 3. `Institution.favicon` — the override field

```python
favicon = models.ImageField(
    upload_to="branding/", blank=True, null=True,
    verbose_name=_("Favicon"), help_text=_(...),  # copy in "Error handling"
)
```

Migration `institution/0008_institution_favicon.py`.

`models.ImageField` performs **no** content validation — the Pillow-backed check lives in
`forms.ImageField`, so it applies to `BrandingForm` (and the admin form) but is bypassed by a direct
shell assignment, a data migration, or a fixture load. The security properties described under "Error
handling" are therefore **form-level**; that is stated here rather than implied.

### 4. Form surface — `BrandingForm`

`favicon` joins `Meta.fields` immediately after `logo`, with an explicit `labels` / `help_texts` entry
(see below), the shared styled clearable-file widget, and `clean_favicon()` enforcing the rules in
"Error handling".

**Both surfaces render it.** `templates/institution/manage/_branding_fields.html` renders each field
in a hand-written block — adding a name to `Meta.fields` renders nothing on its own — so the favicon
needs its own block in that partial, mirroring the logo block. That partial is `{% include %}`d by
**`templates/institution/setup/identity.html`** (the first-run wizard's Identity step, which drives
the same `BrandingForm` through `institution/views_setup.py::_modelform_step`), so the field appears
there too. That is the intended scope: the field is optional, the wizard step already has a Skip
button, and a visibility guard would mean two divergent renderings of one partial. Tests cover the
wizard step saving a favicon.

**i18n of the label and help text is explicit, not auto-derived.** `BrandingForm` has no
`labels`/`help_texts` dict today, and this repo has already been bitten by that: auto-derived
ModelForm labels carry no `_()`, appear in no catalogue, and render in English under a Polish UI.
So `favicon` gets `gettext_lazy` label and help text (on the model field per §3, and mirrored in the
form's `labels`/`help_texts` if the form needs to override), with the help-text copy written out in
"Error handling" — that string is the only place a PA learns the constraints before uploading.

**Targeted refactor this pulls in.** `LogoClearableFileInput` and
`templates/institution/manage/widgets/logo_clearable.html` are logo-specific in three ways, all of
which must be parameterized before a second field can share them:

1. **JS hooks.** The template hardcodes `data-logo-field/-input/-thumb/-filename/-remove`, and the
   branding tab's inline script queries those four as global selectors. Rename
   `LogoClearableFileInput` → `BrandingFileInput`, template →
   `institution/manage/widgets/branding_file.html`; the wrapper carries `data-file-field="<name>"` and
   the inner hooks become `data-file-input` / `data-file-thumb` / `data-file-filename` /
   `data-file-remove`, queried **within** each wrapper. The inline script loops over
   `form.querySelectorAll("[data-file-field]")`. Keep the `_render()` override that forces
   `TemplatesSetting` — its reason (`BoundField.as_widget()` passes a renderer that only searches
   Django's built-in templates dir) is unchanged. Django's native clear-checkbox name
   (`<field>-clear`) is untouched, so `value_from_datadict`'s clear logic keeps working for both.
2. **Copy.** The template hardcodes five translatable strings — `Current logo`, `No logo yet`,
   `Replace logo`, `Upload logo`, `Remove logo`. Shared verbatim, the favicon field would read
   "Upload logo". The widget therefore takes five lazy strings as constructor kwargs
   (`current_label`, `empty_label`, `replace_label`, `upload_label`, `remove_label`), defaulted to the
   existing logo copy so the logo field's rendering and msgids are unchanged, with favicon variants
   passed at construction. **Catalogue consequence:** the five new favicon msgids are additions; the
   five logo msgids must be left byte-identical, or they become obsolete `#~` entries that this
   project's catalogue-health tests reject.
3. **CSS.** `institution/static/institution/settings.css` pins `.logo-field__thumb { height: 64px;
   width: 120px; }` — a landscape box that would squash a square icon. The `.logo-field*` block is
   renamed to `.branding-file*` (touching `settings.css`, the widget template, and
   `_branding_tab.html`, which is the only other file referencing those class names; no test does),
   and the widget emits a `thumb_variant` modifier class. The favicon field uses
   `.branding-file__thumb--icon` — a 48 px square box — so the PA sees the upload roughly as a tab
   would show it. This is scoped CSS work, not an afterthought: the project's rule is that every view
   ships styled.

The brand-preview signature (`[data-preview-logo]`) stays wired to the **logo** field only — a favicon
in the identity signature would misrepresent what that preview shows.

### 5. `get_site_config()` — `favicon_url`, `favicon_size`, `favicon_mime`

`core/services.py` gains three keys, all `None` in `_DEFAULTS`:

- `favicon_url` — `inst.favicon.url if inst.favicon else None` (the `if` guard is required: `.url` on
  an empty `ImageField` raises `ValueError`, the same guard `logo_url` already uses).
- `favicon_size` — `"<W>x<H>"`, read from `inst.favicon.width/height`. This opens the stored file, so
  it happens **inside `_build()`** — i.e. once per cache rebuild (300 s TTL), never per render. Wrapped
  in `try/except (OSError, ValueError)` → `None`, so a missing or unreadable media file degrades the
  manifest entry rather than 500-ing the page.
- `favicon_mime` — `"image/png"` or `"image/x-icon"`, derived from the stored filename's extension
  (the upload is already constrained to those two by validation).

`favicon_size` exists because the manifest needs a real `sizes` value: `"any"` is the vector
convention, and installability heuristics look for a raster icon with a declared pixel size, so
emitting `"any"` for a PNG risks making libli non-installable exactly when a school has branded it.
No new model columns (no `width_field`/`height_field`) are needed for this — the cached read is
enough.

No new cache plumbing: the bundle is already invalidated on `Institution` `post_save`/`post_delete` in
`core/apps.py`.

### 6. Render surfaces

**`{% favicon_links %}`** — a new `simple_tag` in the existing `core/templatetags/branding.py`
(alongside `brand_vars`; both are branding-head emitters). It reads `get_site_config()` and returns
the head block:

- *No override:* `<link rel="icon" href="…/favicon.svg" type="image/svg+xml">`,
  `<link rel="icon" href="…/favicon.ico" sizes="32x32">`,
  `<link rel="apple-touch-icon" href="…/apple-touch-icon.png">`,
  `<link rel="manifest" href="{% url 'core:webmanifest' %}">`,
  `<meta name="theme-color" content="<effective primary>">`.
- *Override set:* the three icon links collapse to two pointing at the uploaded file —
  `<link rel="icon" href="{{ favicon_url }}">` and
  `<link rel="apple-touch-icon" href="{{ favicon_url }}">` — with the manifest link and `theme-color`
  unchanged.

**Escaping is `format_html`, not `mark_safe`.** A `simple_tag` returning a plain string is
auto-escaped in full, so the markup would render as visible text; the only working options are
`format_html` / `format_html_join` / `render_to_string`. Its neighbour `brand_vars` uses `mark_safe`
on an f-string (with a `# noqa: S308`), and copying that pattern here would inject an unescaped,
**filename-bearing** media URL into an `href` attribute. `format_html` escapes each interpolated URL
as an attribute value, which is exactly the property needed. `theme-color` is emitted only after
`is_valid_css_color()` passes, matching `brand_vars`' defense-in-depth, and falls back to
`PRIMARY_DEFAULT` otherwise. Static URLs come from `django.templatetags.static.static()` so
WhiteNoise's `CompressedManifestStaticFilesStorage` hashing applies in production.

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
  "background_color": "#ffffff",
  "theme_color": "<effective primary, or PRIMARY_DEFAULT>",
  "icons": [ ... ]
}
```

`short_name` rule, fully specified because its boundary is where this kind of thing breaks: take
`name`; if it is ≤ 12 characters use it as-is; otherwise truncate at the last word boundary at or
before 12 characters; **if that yields an empty string** (the first word is itself longer than 12
characters — "Międzynarodowe", "Gesamtschule") hard-truncate to exactly 12 characters. `name` itself
is never empty — `get_site_config()` already falls back to `_DEFAULTS["name"]`.

`icons` is the 192/512/maskable trio by default, each with `"type": "image/png"` and its `sizes`; the
maskable entry additionally carries `"purpose": "maskable"`. With an override it is a **single** entry
`{"src": favicon_url, "sizes": favicon_size or "any", "type": favicon_mime, "purpose": "any"}` — an
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
bundle with `favicon_url`/`favicon_size`/`favicon_mime` set → `{% favicon_links %}` emits
`/media/branding/<file>` → served by the `/media/` route.

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
`getattr(value, "image", None)` is set, and every rule below reads `value.image.format` and
`value.image.size` rather than re-opening the file.

Rules, **checked in this order** (cheapest first, so a fixture violating two rules reports
deterministically and "one test per refusal" is writable):

| # | rule | limit | why |
|---|---|---|---|
| 1 | size | **≤ 256 KB** (`MAX_FAVICON_BYTES`, defined next to `MAX_LOGO_BYTES` in `institution/forms.py`) | An icon fetched by every visitor has no legitimate reason to be larger. The logo's separate 2 MB cap is unchanged. |
| 2 | filename extension | **`.png` or `.ico`** | `upload_to="branding/"` preserves the uploaded **filename**, so a file whose bytes decode as PNG but whose name is `mark.svg` or `mark.html` would be stored and served same-origin under that extension. Checking format alone does not close that; both checks are deliberate. |
| 3 | decoded format | **PNG or ICO only** | Read from `value.image.format`, never from the extension. JPEG has no transparency; GIF/BMP/WEBP are needless surface. |
| 4 | square | **width == height** | Every consumer renders in a square box; a non-square upload is squashed. "Crop it square first" beats silently distorting a school's logo. |
| 5 | dimensions | **32–512 px** | Below 32 it is blurry in every slot. The ceiling is 512 because that is the largest slot libli emits, and it keeps rules 1 and 5 describing a *non-empty* intersection — a 1024 px PNG routinely exceeds 256 KB, which would have made the two rules mutually contradictory. |

**SVG is rejected** by rules 2 and 3 together. The reason is worth stating: an uploaded SVG served
same-origin from `/media/` is a stored-XSS vector, and nothing in this codebase sanitizes SVG. As §3
notes, this is a **form-level** guarantee — a shell/fixture write bypasses it.

**Alpha channel is accepted, with a stated cost.** A transparent PNG is fine on a browser tab but iOS
composites transparency onto black on the home screen, and flattening it server-side is an explicit
non-goal. Transparent uploads are therefore accepted and still emitted as `apple-touch-icon`; the
help text warns about it.

**Help text copy** (the only place a PA learns the constraints before uploading; `gettext_lazy`, EN
and PL):

> Square PNG or ICO, 32–512 px, up to 256 KB. Replaces the libli icon in browser tabs and on home
> screens. Transparent areas show as black on iOS home screens — use a solid background for best
> results.

Each failure is a field-level `ValidationError`, so the settings form re-renders at HTTP 200 with the
message next to the field. The existing PRG behaviour in `institution/views_manage.py` (valid POST →
save + 302 `?tab=`; invalid → full re-render 200) is unchanged, as is the wizard's
`_modelform_step`.

Validation is **fail-closed on unreadable input**: if Pillow cannot determine the format or
dimensions, the upload is rejected rather than accepted-and-hoped-for.

### Render-time robustness

- `favicon_url` dereferences `.url` only behind an `if inst.favicon` guard.
- `favicon_size` swallows `OSError`/`ValueError` (deleted or unreadable media file) → `None` → the
  manifest entry falls back to `"sizes": "any"` rather than raising.
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

**Generator (`scripts/build_favicons.py`)** — all tests render into `tmp_path` via `--out`; none write
into the working tree.

- **Idempotence:** two runs into two different `tmp_path` directories produce byte-identical files.
  (This is durable across Pillow releases, because both runs use the same Pillow.)
- **Structural assertions against the committed assets** — deliberately *not* byte-comparison with a
  fresh run, because `pyproject.toml` declares `pillow>=12.2.0` (a floor, not a pin) and PNG/ICO
  encoder output is not contracted across releases; a routine lock bump would otherwise turn this
  test RED with no code change. Assert instead: every declared file exists; each raster's pixel
  dimensions match the table; `favicon.ico` contains exactly the frames 16/32/48; and sampled pixels
  at known coordinates carry the expected colours (tile centre-left = primary, dot centre = accent,
  stem interior = white).
- The centred-bounding-box assertion fires when the geometry is nudged off-centre.
- The `PRIMARY_DEFAULT`/`ACCENT_DEFAULT` equality assertion fires when they diverge.
- `apple-touch-icon.png` and `icon-maskable-512.png` have **opaque corner pixels** (radius 0), while
  `icon-512.png` does not — the one assertion that actually distinguishes the variants.

**Config bundle**
- `favicon_url` is `None` with no upload, the media URL with one, and `None` again after a clear.
- `favicon_size` is `"WxH"` for a real upload and `None` when the underlying file is missing.
- The bundle is invalidated on `Institution.save()` (the existing signal covers it; this proves it
  covers the new keys too).

**Form validation** — one test per refusal, each asserting the *field-scoped* error, plus the accept
and clear paths: too-large file, `.svg`-named PNG bytes, JPEG, non-square, 16 px, 1024 px, valid
square PNG accepted, valid ICO accepted, `favicon-clear` empties the field. Plus the value-type
guard: **saving the Branding form without touching the favicon does not raise** (the `FieldFile`
path), and a clear (`False`) short-circuits before any Pillow access. That pair is the regression
test for the 500 described above.

**Head render**
- `base.html` with no override contains the SVG/ICO/apple-touch/manifest links and a `theme-color`.
- With an override, the icon links point at the media URL and the static default icons are *absent*
  (not merely present-alongside).
- A media filename containing HTML-special characters is escaped in the `href` — the falsification for
  choosing `format_html` over `mark_safe`.
- `theme-color` equals `PRIMARY_DEFAULT` when the stored primary is `None`, and again when it is
  malformed; same for the manifest's `theme_color`. Both must go RED with the fallback removed.
- `500.html` renders standalone under an empty `Context()` and contains **no** `/static/` reference
  and no `favicon` link. Falsification: adding `{% load branding %}{% favicon_links %}` (or any
  `{% static %}` link) to that file turns it RED.

**Routes**
- `/site.webmanifest` returns 200, `application/manifest+json`, valid JSON, the institution's name,
  and the default icon trio with `type`, `sizes`, and the maskable `purpose`.
- `short_name` at its boundaries: a ≤12-char name passes through; a long multi-word name truncates at
  the word boundary; a name whose **first word exceeds 12 characters** hard-truncates to exactly 12
  and is never empty.
- With an override, the manifest has a single icon entry carrying `favicon_size` (or `"any"` when the
  file is unreadable) and the right `type`.
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
inferred from one another), plus the generated mark rendered at 16/32/180 px and actually looked at
before shipping.
