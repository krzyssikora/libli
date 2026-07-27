# Favicon: a libli default mark, and a PA-replaceable school favicon

## Purpose

libli ships no favicon today. `templates/base.html`'s `<head>` contains no icon link of any kind, so
every browser tab shows a blank/generic page glyph and every page load triggers an unanswered
`GET /favicon.ico` that lands in the logs as a 404.

This delivers two things:

1. **A default libli mark** — a designed icon shipped as a full PWA asset set (SVG, ICO, apple-touch,
   manifest icons, `site.webmanifest`), wired into the app shell.
2. **A PA-configurable override** — a Platform Administrator can upload their school's icon in
   `/manage/settings/` → Branding, and it replaces the libli mark everywhere: browser tab, iOS home
   screen, installed-app icon, and the bare `/favicon.ico` request. Clearing the upload restores the
   libli default.

The override rides the branding path that already exists for `Institution.logo` — same singleton
model, same form, same cached `get_site_config()` bundle, same cache invalidation — so it adds a
field and a few render surfaces rather than a subsystem.

### Non-goals

- **No service worker / offline support.** The manifest makes libli installable and gives iOS and
  Android a real home-screen icon; it does not make libli work offline. No service worker is added.
- **No SVG uploads.** See "Error handling" for why this is a deliberate refusal, not an omission.
- **No server-side derivation of sizes** from the PA's upload. One uploaded file fills every slot.
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

**Geometry constants (a 512×512 canvas, all values in canvas units):**

| element | shape | value |
|---|---|---|
| tile | rounded rect | full-bleed 0,0–512,512; corner radius 112 |
| stem | rounded rect | width 64, from y=118 to y=372, left edge x=196; corner radius 32 |
| dot | circle | radius 42, centre (322, 330) |

Fill colours are literals in the generator, **not** reads of `BrandColor` — the default mark is a
fixed libli asset, and a PA who wants their own colours uploads their own icon. Both fills are the
documented defaults (`core.services.PRIMARY_DEFAULT`, `ACCENT_DEFAULT`); the generator asserts this
equality at build time so a future default-palette change is caught rather than silently diverging.

### 2. `scripts/build_favicons.py` — single source of geometry

Pillow (already a dependency; `Pillow 12.2.0`) cannot rasterize SVG, so rather than add a renderer
dependency, the geometry above lives **once** as module-level constants and the script emits both the
vector and the rasters from them. Every shape used is expressible in both media (`<rect rx>`/`<circle>`
in SVG; `ImageDraw.rounded_rectangle`/`ellipse` in Pillow), so the two can't drift.

Rasters are drawn at **4× supersample and downsampled with `Image.LANCZOS`** — Pillow's `ImageDraw`
does not antialias, and an aliased 32px icon looks broken.

Outputs, all committed to `core/static/core/img/favicon/`:

| file | size(s) | notes |
|---|---|---|
| `favicon.svg` | vector | modern browsers |
| `favicon.ico` | 16, 32, 48 | legacy + the bare `/favicon.ico` request |
| `apple-touch-icon.png` | 180×180 | opaque (iOS composites transparency onto black); artwork inset ~10% since iOS masks the corners itself |
| `icon-192.png` | 192×192 | manifest, `purpose: "any"` |
| `icon-512.png` | 512×512 | manifest, `purpose: "any"` |
| `icon-maskable-512.png` | 512×512 | manifest, `purpose: "maskable"`; artwork scaled into the inner 80% safe zone, tile colour bled to the edges |

The script is idempotent (same inputs → byte-identical outputs) and is the documented way to
regenerate the assets; it is not run at request time or at deploy time.

### 3. `Institution.favicon` — the override field

```python
favicon = models.ImageField(upload_to="branding/", blank=True, null=True)
```

Migration `institution/0008_institution_favicon.py`. `ImageField` (not `FileField`) is load-bearing:
its Pillow-backed validation is what rejects a `.svg` masquerading as an image, which is the security
property described under "Error handling".

### 4. Form surface — `BrandingForm`

`favicon` joins `Meta.fields` immediately after `logo`, using the same styled clearable-file widget,
and `clean_favicon()` enforces the rules in "Error handling".

**Targeted refactor this pulls in.** `LogoClearableFileInput` and
`templates/institution/manage/widgets/logo_clearable.html` hardcode `data-logo-input`,
`data-logo-thumb`, `data-logo-filename`, `data-logo-remove` JS hooks, and the branding tab's inline
script queries those four selectors directly. Adding a second file field must not clone that block.
The widget is therefore generalized:

- Rename `LogoClearableFileInput` → `BrandingFileInput`; template
  `institution/manage/widgets/branding_file.html`. Keep the `_render()` override that forces
  `TemplatesSetting` (the reason it exists — `BoundField.as_widget()` passes a renderer that only
  searches Django's built-in templates dir — is unchanged and still applies).
- Hooks become field-scoped: the wrapper element carries `data-file-field="<name>"` and the inner
  hooks become `data-file-input` / `data-file-thumb` / `data-file-filename` / `data-file-remove`,
  queried **within** each wrapper. The inline script loops over
  `form.querySelectorAll("[data-file-field]")` instead of querying four global selectors.
- Django's native clear-checkbox name (`<field>-clear`) is untouched, so `value_from_datadict`'s clear
  logic keeps working for both fields.
- The brand-preview signature (`[data-preview-logo]`) stays wired to the **logo** field only; the
  favicon gets its own small 32px preview chip inside its field (label: the icon as a tab would show
  it), because a favicon in the identity signature would misrepresent what the signature previews.

### 5. `get_site_config()` — `favicon_url`

`core/services.py` gains `"favicon_url"` in `_DEFAULTS` (value `None`) and in `_build()`
(`inst.favicon.url if inst.favicon else None`, guarding the `ValueError` that dereferencing `.url` on
an empty `ImageField` raises — the same guard `logo_url` already uses). No new cache plumbing: the
bundle is already invalidated on `Institution` `post_save`/`post_delete` in `core/apps.py`.

### 6. Render surfaces

**`{% favicon_links %}`** — a new `simple_tag` in the existing `core/templatetags/branding.py`
(alongside `brand_vars`; both are branding-head emitters, so they belong together). It reads
`get_site_config()` and returns the head block:

- *No override:* `<link rel="icon" href="…/favicon.svg" type="image/svg+xml">`,
  `<link rel="icon" href="…/favicon.ico" sizes="32x32">`,
  `<link rel="apple-touch-icon" href="…/apple-touch-icon.png">`,
  `<link rel="manifest" href="{% url 'core:webmanifest' %}">`,
  `<meta name="theme-color" content="<effective primary>">`.
- *Override set:* the three icon links collapse to two pointing at the uploaded file —
  `<link rel="icon" href="{{ favicon_url }}">` and `<link rel="apple-touch-icon" href="{{ favicon_url }}">`
  — with the manifest link and `theme-color` unchanged.

The tag renders through Django's template escaping for the URL (a media URL contains a
user-influenced filename); `theme-color` is emitted only after `is_valid_css_color()` passes, matching
`brand_vars`' defense-in-depth. Static URLs come from `django.templatetags.static.static()` so
WhiteNoise's `CompressedManifestStaticFilesStorage` hashing applies in production.

`base.html` gains one line, `{% favicon_links %}`, in `<head>`.

**`templates/500.html` is deliberately excluded.** It is a standalone document (no `{% extends %}`)
rendered when the database may be unreachable; `{% favicon_links %}` calls `get_site_config()`, which
can hit the DB on a cold cache. It instead gets a hardcoded static `<link rel="icon">` to
`favicon.ico` with a literal `/static/…` path — 500.html already hardcodes rather than using
`{% static %}` for the same no-app-context reason. An override does not appear on the 500 page; that
is the correct trade.

**`core/views.py::webmanifest`** — served at `/site.webmanifest`, name `core:webmanifest`, public (no
global login-required middleware exists, and the manifest must be fetchable by the browser
regardless). Returns `JsonResponse` with `content_type="application/manifest+json"`:

```json
{
  "name": "<institution name>",
  "short_name": "<institution name, truncated to 12 chars on a word boundary>",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#ffffff",
  "theme_color": "<effective primary>",
  "icons": [ ... ]
}
```

`icons` is the 192/512/maskable trio by default, or a single entry pointing at the uploaded file
(`"sizes": "any"`, `"purpose": "any"`) when an override is set. It must be a **view** rather than a
static file precisely because both `name` and `icons` depend on institution state.

**`core/views.py::favicon_ico`** — `/favicon.ico`, a 302 to the effective icon URL (override if set,
else the static `favicon.ico`). Browsers request this path unprompted regardless of the `<link>` tags;
a static file at that path could not honour the override, and no route at all means a logged 404 on
every cold visit. `Cache-Control: max-age=3600` on the redirect keeps the extra hop cheap. Both routes
are registered in `core/urls.py` (already `include`d at the root prefix, so no `config/urls.py`
change).

## Data flow

**Default render (no override), any page extending `base.html`:**

`institution_branding` context processor → `get_site_config()` (cache hit, or one query on miss) →
`{% favicon_links %}` reads `favicon_url = None` → emits the three static icon links + manifest link +
`theme-color` → browser fetches the static assets through WhiteNoise.

**Override render:** PA uploads in Branding → `BrandingForm.clean_favicon()` validates → `save()`
writes the file under `MEDIA_ROOT/branding/` and the field on the singleton → `post_save` fires
`invalidate_site_config` → next request rebuilds the bundle with `favicon_url` set → `{% favicon_links %}`
emits `/media/branding/<file>` → served by the `/media/` route.

**Manifest:** browser fetches `/site.webmanifest` after parsing the head → view reads the same cached
bundle → JSON reflects institution name + effective icons.

**Bare `/favicon.ico`:** browser requests it unprompted → `favicon_ico` view reads the bundle →
302 → static `favicon.ico` or the uploaded media file.

**Clear:** PA ticks Remove → `favicon-clear` → `ImageField` cleared → cache invalidated → next render
is back to the libli default. (Note: the file itself is left on disk by Django's default behaviour;
this matches how `logo` already behaves and is not changed here.)

## Error handling

### Upload validation (`BrandingForm.clean_favicon`)

Mirrors `clean_logo`'s shape (per-field size cap, `ValidationError` with a translatable message).
Rules, each with the reason it exists:

| rule | limit | why |
|---|---|---|
| format | **PNG or ICO only** | JPEG has no transparency; GIF/BMP/WEBP are needless surface. Format is read from the Pillow-verified image, not from the filename extension. |
| SVG | **rejected** | An uploaded SVG served same-origin from `/media/` is a stored-XSS vector, and nothing in this codebase sanitizes SVG. `ImageField`'s Pillow validation already rejects it; the explicit format check makes the refusal intentional and gives a clear message instead of Django's generic "not a valid image". |
| square | **width == height** | Every consumer (tab, home screen, installed icon) renders in a square box; a non-square upload is squashed. Rejecting with "crop it square first" beats silently distorting the school's logo. |
| dimensions | **32–1024 px** | Below 32 it is blurry in every slot; above 1024 is pointless payload for an icon. |
| size | **≤ 256 KB** (`MAX_FAVICON_BYTES`) | An icon this small has no legitimate reason to be larger; the logo's own 2 MB cap is separate and unchanged. |

Each failure is a field-level `ValidationError`, so the settings form re-renders at HTTP 200 with the
message next to the field — the existing PRG behaviour in `institution/views_manage.py` (valid POST →
save + 302 `?tab=`; invalid → full re-render 200) is unchanged.

Validation is **fail-closed on unreadable input**: if Pillow cannot determine the format or
dimensions, the upload is rejected rather than accepted-and-hoped-for.

### Render-time robustness

- `favicon_url` dereferences `.url` only behind an `if inst.favicon` guard (an empty `ImageField`
  raises `ValueError` on `.url`).
- `theme-color` and the manifest's `theme_color` fall back to `PRIMARY_DEFAULT` when the stored brand
  colour is absent or fails `is_valid_css_color()` — a malformed stored colour must not emit a
  malformed meta tag or invalid JSON.
- The manifest view never 500s on a missing institution row: `get_site_config()` already returns
  `_DEFAULTS` when `Institution.objects.filter(pk=1).first()` is `None`.
- A stale `favicon_url` pointing at a deleted media file degrades to a broken icon, not an error page.
  No extra existence check is added — that would mean a filesystem stat on every render.

## Testing

Per the project's standing rule, every test below is **falsified before it is trusted**: delete or
invert the behaviour it guards and confirm it goes RED, rather than accepting a green run as evidence.

**Generator (`scripts/build_favicons.py`)**
- Re-running the script produces byte-identical outputs (idempotence), so the committed assets are
  verifiable rather than mystery binaries.
- Every declared output file exists, and each raster's pixel dimensions match the table above.
- `favicon.ico` genuinely contains all three sizes (16/32/48), not just the largest.
- The build-time assertion that the literal fills equal `PRIMARY_DEFAULT` / `ACCENT_DEFAULT` fires when
  they diverge.

**Config bundle**
- `get_site_config()["favicon_url"]` is `None` with no upload, is the media URL with one, and returns
  to `None` after a clear.
- The bundle is invalidated on `Institution.save()` (the existing signal covers it; the test proves it
  covers the new key too).

**Form validation** — one test per refusal, each asserting the *field-scoped* error, plus the accept
and clear paths: non-square rejected, JPEG rejected, SVG rejected, 16px rejected, 2048px rejected,
300 KB PNG rejected, valid square PNG accepted, valid ICO accepted, `favicon-clear` empties the field.

**Head render**
- `base.html` with no override contains the SVG/ICO/apple-touch/manifest links and a `theme-color`.
- With an override, the icon links point at the media URL and the static default icons are *absent*
  (not merely present-alongside).
- `500.html` renders standalone with a static icon link and **no** `get_site_config()` call —
  asserted by patching the service and requiring it was never called, which is what actually protects
  the DB-down path.

**Routes**
- `/site.webmanifest` returns 200, `application/manifest+json`, valid JSON, the institution's name,
  and the default icon trio; with an override, a single icon entry pointing at the media URL.
- The manifest is reachable **anonymously**.
- `/favicon.ico` 302s to the static asset by default and to the media URL with an override.

**e2e** (`-m e2e`, driving the real UI rather than `page.evaluate`)
- A PA opens `/manage/settings/` → Branding, uploads a PNG through the real file input, saves, and the
  head's `rel="icon"` href moves to `/media/`; then ticks Remove, saves, and it moves back to the
  static default.
- The generalized widget did not break the **logo** field: uploading a logo still previews and still
  clears.

**i18n** — EN/PL for the new field label, help text, and every validation message, with zero fuzzy and
zero obsolete entries in either catalogue and `.mo` files recompiled.

**Visual verification** — the Branding field screenshotted in light *and* dark (judged separately, not
inferred from one another), plus the generated mark rendered at 16/32/180 px and actually looked at
before shipping.
