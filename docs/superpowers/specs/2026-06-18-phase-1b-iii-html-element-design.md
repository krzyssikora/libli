# Phase 1b-iii — HTML element (sandboxed author HTML/CSS/JS) — Design

**Status:** spec (brainstormed 2026-06-18)
**Slice:** Phase 1b-iii — the deferred HTML-element slice (course-wide CSS/JS + per-unit JS + LaTeX), renders into 1b-ii's preview pane.
**Predecessors:** 1a (content model, element renderers, vendored KaTeX), 1b-i (course builder), 1b-ii (per-unit editor｜preview page, MediaAsset, 5 element editors).

---

## 1. Purpose & scope

### 1.1 What this slice is

A new **HTML element** type that lets a course author embed self-contained interactive content authored as raw **HTML + CSS + JavaScript**, rendered safely. It is the one element type that *deliberately executes author-supplied JavaScript*, so its entire reason to exist as a separate spec is **containment**.

Three authoring inputs, exactly as `differences.md` ("Lesson element- HTML") anticipated:

- **course-wide CSS** — one stylesheet per course, applied to every HTML element in the course.
- **course-wide JS** — one script per course, applied to every HTML element in the course (e.g. a shared library that scans the DOM and wires up interactions).
- **per-unit JS seed** — one short script per unit whose job is to assign initial values to variables (e.g. answer keys) so the course-wide JS works for that unit. This *replaces* the `localStorage` data-bus pattern used in the author's prior openEdX content.
- **per-element HTML** — the body markup of one HTML element, which may contain inline `<script>` and inline/block LaTeX.

### 1.2 What this slice is NOT (scope boundaries)

The author's existing interactive content (≈921 HTML units, ≈361 interactive) uses ~a dozen patterns that split into three buckets. This slice handles only the third:

- **Self-check question types** (true/false, single/multi choice, fill-in, numeric "more/less", switch-to-make-correct) → these are **Phase 2 quiz elements**, reused formatively in lessons (unrecorded, per `differences.md` §"Unit": "if quiz elements are used, the performance/results are not recorded"). **Not in 1b-iii.**
- **Presentation widgets** (tabs, "show next" reveals, slideshow, reveal-solution, gated reveal, decision tree, mark-done) → candidates to be **promoted to native, form-authored, no-JS lesson elements** in a later slice. Until then they work *inside* the HTML element sandbox. **Not built natively in 1b-iii.**
- **Bespoke / custom** (custom visualizations, sliders, animations, novel manipulatives; GeoGebra is already the existing iframe element) → **this is what the HTML element is for.**

**Design rationale (recorded decision):** one sandbox is a *bounded, finite* security artifact — designed and audited once. "Natively support every interaction" is an *unbounded, growing* commitment with no escape hatch for the unforeseen. So 1b-iii ships the sandbox as the permanent escape hatch; friendly no-JS tools arrive incrementally (question types via Phase 2; presentation widgets later). The sandbox path does not foreclose building native components forever.

### 1.3 Non-goals

- No `localStorage`/`sessionStorage` persistence inside the sandbox (the opaque-origin sandbox blocks it by design; the per-unit JS seed supersedes it).
- No MathJax (KaTeX auto-render covers the sampled content; MathJax is a possible later per-course escape hatch, out of scope here).
- No file-upload UI for CSS/JS (text fields instead — see §3).
- No cross-iframe coordination between separate HTML elements in the same unit (each element is its own document — see §6.4).
- No app-wide Content-Security-Policy rollout (a related, broader hardening; this spec sets CSP only *inside* the sandbox document). Noted as a follow-up.
- No quiz/marking behavior (Phase 2).

---

## 2. Security model (the core)

### 2.1 Threat model

Authors are course owners (Course Admins) and Platform Admins — *trusted staff* in a single-tenant deploy. The design is **defense-in-depth against author mistakes and against blast-radius to students**, not protection against a fully hostile insider. The asset to protect is the **student's authenticated session** (cookies, CSRF context, same-origin authenticated requests) and the integrity of the libli page chrome. The danger is that author JS, viewed by a logged-in student, could otherwise act as that student (session theft, CSRF, defacement) — the openEdX same-origin model, which libli explicitly rejects.

### 2.2 The boundary is the iframe origin, not sanitization

Because the HTML element must run author `<script>`, **HTML sanitization (nh3) is not applied** to its body — sanitizing would defeat the feature. Containment is provided by an **iframe with an opaque origin**:

```
<iframe sandbox="allow-scripts"
        srcdoc="…escaped assembled document…"
        referrerpolicy="no-referrer"
        loading="lazy"></iframe>
```

`sandbox="allow-scripts"` **without `allow-same-origin`** gives the framed document a **unique opaque origin**. Browser-enforced consequences:

- no access to `document.cookie`, `localStorage`, `sessionStorage` (they throw);
- no access to the parent DOM or `window.parent` properties;
- no same-origin requests to libli (any `fetch` is cross-origin and cookieless);
- combined with the omitted `allow-*` flags below: cannot navigate the student's tab, open popups, submit forms to libli, or take pointer-lock/fullscreen/downloads.

This is enforced by the browser regardless of author trust.

### 2.3 Exact sandbox flags

- **Set:** `allow-scripts` (and nothing else).
- **Never set:** `allow-same-origin` (this omission *is* the guarantee), `allow-forms`, `allow-popups`, `allow-popups-to-escape-sandbox`, `allow-top-navigation`, `allow-top-navigation-by-user-activation`, `allow-modals`, `allow-pointer-lock`, `allow-downloads`, `allow-presentation`.
- Acceptable consequences: `alert/confirm/prompt` are no-ops; native form submission does nothing (author widgets call `preventDefault`); links cannot change the top frame.

### 2.4 In-sandbox CSP (defense in depth)

A `<meta http-equiv="Content-Security-Policy">` is injected *inside* the srcdoc document. **Critical subtlety:** the framed document has an **opaque origin**, and an opaque origin matches **no** `'self'` — so `'self'` source-expressions silently match nothing. The CSP therefore names the **configured app origin explicitly** (scheme+host, e.g. `https://yourschool.example`) wherever libli-hosted assets must load (KaTeX fonts, author images stored in libli media). The origin is built from the request/configured site at render time (not hard-coded), since it varies per deploy.

```
default-src 'none';
script-src 'unsafe-inline';
style-src 'unsafe-inline';
img-src <APP_ORIGIN> data:;
font-src <APP_ORIGIN> data:;
connect-src 'none'
```

- `'unsafe-inline'` for `script-src`/`style-src` is required — all scripts/styles (author + vendored KaTeX) are inline in the srcdoc.
- `connect-src 'none'` blocks `fetch`/XHR/`sendBeacon`, closing IP/timing **exfil to an author-chosen server** (there is nothing sensitive to send, but this removes the beacon channel entirely).
- `img-src <APP_ORIGIN> data:` allows **only** libli-hosted images and data URIs — no external CDNs and **no image-beacon exfil to arbitrary hosts** (an explicit origin, not `https:`, is what closes the beacon vector that `connect-src 'none'` alone would leave open via `<img>`). Consistent with libli's self-hosting stance (self-hosted Inter, vendored KaTeX).
- `font-src <APP_ORIGIN> data:` lets KaTeX's vendored font files load from libli (see §4.3).
- **Knob (documented, not built):** `img-src`/`connect-src` could be relaxed per-course later if a real widget needs external media or network. Default is locked-down.

### 2.5 The single parent↔sandbox channel (resize)

Iframes have no intrinsic content height, so libli injects a **resize reporter** into the srcdoc that observes the document with a `ResizeObserver` and `postMessage`s a single height number to the parent. A parent-side listener sets that iframe's height. Hardening, because the opaque origin makes `event.origin === "null"`:

- **Validate by `event.source` identity** — match each message against each known iframe's `contentWindow` (origin checks are useless for opaque origins).
- Accept **only** a known message shape (a fixed `type` discriminator + a numeric height).
- Parse **only** an integer, **clamped** to a sane range (e.g. `0`–`5000` px) to prevent a runaway/hostile height.
- **Never** feed message content into the DOM, `eval`, or any sink. The inbound channel carries a clamped integer and nothing else.

### 2.6 Residual risks (named, accepted/mitigated)

- **Visual mimicry / UI redress:** the sandbox cannot stop author content *looking like* libli chrome (e.g. a fake password prompt). Mitigations: the iframe is a block element confined to its own box in normal flow (cannot overlay app chrome, cannot navigate the tab, cannot post to libli), and libli renders a subtle visual frame/label (e.g. "interactive content") around HTML elements so students can distinguish author content from app UI. Accepted as low-reach given the navigation/form restrictions.
- **Resource abuse (infinite loops):** author's own content; affects only the viewing student's tab. Accepted.
- **Answer keys visible:** per-unit seed JS (answer variables) is delivered to the client and inspectable. This matches the prior openEdX reality and is acceptable for *formative* practice; graded assessment is Phase 2 (server-side marking).

---

## 3. Data model & authoring

### 3.1 New model: `HtmlElement`

Concrete element model mirroring `MathElement`:

- `html = models.TextField(blank=True)` — the element body (raw markup + optional inline `<script>`/LaTeX). **No nh3 on save.**
- `elements = GenericRelation(Element)` — cascade join-row, as other element types.
- Added to `ELEMENT_MODELS`; renders via `templates/courses/elements/htmlelement.html` (by `ElementBase.render()` convention).

### 3.2 Course-wide fields on `Course`

- `html_css = models.TextField(blank=True)`
- `html_js = models.TextField(blank=True)`

Injected into **every** HTML-element iframe in the course.

### 3.3 Per-unit field on `ContentNode`

- `html_seed_js = models.TextField(blank=True)` — meaningful only for units (`kind="unit"`); ignored for other kinds. Injected into the iframes of HTML elements **in that unit**, before course JS.

### 3.4 Migration

One migration: add `HtmlElement` + `Course.html_css` + `Course.html_js` + `ContentNode.html_seed_js`. All fields `blank=True`/empty default — no data backfill.

### 3.5 Authoring UX — text fields (code textareas)

**Decision:** CSS/JS/seed are edited as **monospace `<textarea>` code fields** stored as `TextField`s on the row (not uploaded files). Rationale: simplest, versioned with the course/unit, no file-storage/extension/MIME attack surface, consistent with 1b-ii's existing in-page editing.

- **Course-wide CSS/JS:** two code textareas on the course settings/builder surface (alongside existing course fields). PA/owner-gated by the established manage predicate (`owner OR has_perm("courses.change_course")`).
- **Per-unit seed JS:** a code textarea in the unit editor page (the 1b-ii editor｜preview surface), saved with the unit. Reuses 1b-ii's optimistic `updated`-token concurrency contract (editing the seed bumps the unit's `updated`).
- **HTML element body:** a code textarea, added as the 6th element editor on the 1b-ii editor page (add/edit/reorder/delete via the existing element machinery; element op bumps the parent unit's `updated`, 409-before-422, exactly as the other element types).

---

## 4. Rendering pipeline

### 4.1 Document assembly

`HtmlElement` rendering builds **one complete HTML document string** and emits a single `<iframe>` whose `srcdoc` is that document, **HTML-attribute-escaped** via Django escaping (the browser un-escapes the attribute, then parses the iframe document — escaping the assembled string is the correct, safe move; over-escaping inside an attribute is harmless).

Document skeleton (blocks omitted when their source field is empty):

```html
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="…§2.4…">
  <style>/* vendored KaTeX CSS — only if math delimiters present */</style>
  <style>/* course_html_css */</style>
</head>
<body>
  <div class="html-el-root">{{ element.html }}</div>
  <script>/* unit.html_seed_js  — runs first, defines vars        */</script>
  <script>/* course_html_js     — reads vars, wires the DOM       */</script>
  <script>/* vendored KaTeX + auto-render pass — if math present  */</script>
  <script>/* libli resize reporter                               */</script>
</body>
</html>
```

**Order is load-bearing:** seed → course JS → math → resize (so reported height is final after typesetting).

### 4.2 Assembly context (data dependency)

`ElementBase.render(self)` currently receives only the element. `HtmlElement` assembly additionally needs the element's **unit** (`html_seed_js`) and **course** (`html_css`/`html_js`). The `{% render_element %}` template tag is extended to thread `unit` and `course` into HTML-element assembly (both `lesson_unit.html` and `_preview.html` already have `unit`/`course` in context). Implementation may pass them through the tag or resolve via the join-row → unit → course; the spec requires only that assembly has access to course CSS/JS and unit seed at render time.

### 4.3 Math (KaTeX auto-render)

**Decision:** reuse the already-vendored KaTeX and add its **auto-render extension** (`contrib/auto-render.min.js`), configured for the author's delimiters: `\(…\)` inline and `\[…\]` display (optionally `$$…$$` display). KaTeX runs with `throwOnError:false` (raw LaTeX left on failure). KaTeX CSS + JS are injected **only when** the element body contains math delimiters (mirrors the lesson page's existing `has_math` gating) so non-math widgets stay light. Vendoring task: add `auto-render.min.js` alongside the existing `katex.min.js`/`katex.min.css`. **KaTeX fonts:** the vendored `katex.min.css` references woff2 font files by URL; these resolve to the libli app origin and are permitted by the CSP `font-src <APP_ORIGIN>` entry (§2.4) — *not* by `'self'`, which is inert under the opaque origin. (Alternative if origin injection proves awkward: ship a data-URI-inlined KaTeX font CSS so fonts need no `font-src` host. Default is the app-origin approach.)

### 4.4 Resize bridge (client)

- **In-sandbox reporter** (injected): `ResizeObserver` on `document.documentElement` (and `body`), `postMessage({type:"libli:htmlel:height", h:<int>}, "*")` to `window.parent` on change and after KaTeX typeset.
- **Parent listener** (new `courses/static/courses/js/html_element.js`): a single `window`-level `message` listener using **delegation with per-iframe `event.source` matching**, so it survives 1b-ii fragment swaps without re-init races. Validates source identity + message shape, clamps `h`, sets `iframe.style.height`.

---

## 5. Templates & static

- `templates/courses/elements/htmlelement.html` — emits the escaped-`srcdoc` iframe (+ the §2.6 visual frame/label).
- `courses/static/courses/js/html_element.js` — parent-side resize listener (loaded on both the lesson page and the editor page).
- `courses/static/courses/vendor/katex/contrib/auto-render.min.js` — newly vendored.
- `templates/courses/manage/editor/_edit_html.html` — the 6th element editor (HTML body textarea) on the 1b-ii editor page.
- Course settings surface gains the two course-wide code textareas; the unit editor gains the per-unit seed textarea.
- CSS: a small `.html-el` wrapper/frame style (visual affordance + no-JS fallback min-height + `overflow:auto`).

---

## 6. Integration

### 6.1 Preview parity

`render_element` emits the iframe in both `lesson_unit.html` and `_preview.html`. 1b-ii's "re-render on save" rebuilds the preview iframe with a fresh `srcdoc`, so the author sees exactly the student result (JS running, math typeset). `html_element.js` is loaded on the editor page too.

### 6.2 Progress "seen"

Unchanged. The lesson wraps each element in `<section data-element-id>`; the IntersectionObserver watches the **wrapper**, not iframe internals. HTML elements auto-complete like any other element.

### 6.3 No-JS fallback

With browser JS fully disabled: the iframe still renders static HTML+CSS; author JS and the resize bridge don't run, so the iframe falls back to a fixed min-height with internal scroll (`overflow:auto`). The lesson's plain "Mark as done" POST form is unaffected.

### 6.4 One-iframe-per-element behavior note

Each HTML element is its own document, so course JS scans only that element's content. Splitting a multi-question file into several HTML elements resets per-iframe numbering and prevents cross-element coordination. **Authoring guidance:** keep content that must coordinate (shared numbering, cross-question logic) inside a *single* HTML element. Expected and documented, not a defect.

---

## 7. Error handling

- Malformed author HTML/JS cannot affect libli (isolated); script errors stay in the iframe console.
- Empty `html_css`/`html_js`/`html_seed_js` → those blocks are omitted from the assembled document.
- KaTeX failures leave raw LaTeX (`throwOnError:false`).
- Resize messages from unknown `event.source` or wrong shape are ignored; height is clamped.

---

## 8. Testing & Definition of Done

### 8.1 Unit tests
- Emitted iframe has **exactly** `sandbox="allow-scripts"` and **no** `allow-same-origin`; carries `referrerpolicy="no-referrer"`.
- `srcdoc` is attribute-escaped: `"`, `&`, `<` in author content cannot break out of the attribute.
- Course CSS/JS + unit seed are injected, in the correct order (seed before course JS).
- KaTeX CSS/JS injected **iff** math delimiters present; absent otherwise.
- Empty fields omit their blocks.
- In-sandbox CSP meta present with `connect-src 'none'` and an explicit app-origin (not `'self'`) for `img-src`/`font-src`.

### 8.2 JS / resize handler tests
- Listener ignores messages from unknown sources and wrong-shaped messages.
- Height is clamped to the allowed range.

### 8.3 Playwright e2e
- Author an HTML element with a per-unit seed + a button that uses a seeded variable → renders and runs in both the editor preview and the lesson page; iframe resizes to content.
- Two HTML elements on one page size independently.

### 8.4 i18n
- New authoring labels (course CSS/JS, per-unit seed, HTML body) extracted + Polish translated/compiled.

### 8.5 Security DoD checklist
- [ ] `allow-same-origin` never set on the iframe.
- [ ] `srcdoc` attribute-escaped.
- [ ] postMessage handler validates `event.source` identity + message shape, clamps integer height, never sinks message content.
- [ ] In-sandbox CSP meta injected (`default-src 'none'; … connect-src 'none'`).
- [ ] `referrerpolicy="no-referrer"` on the iframe.
- [ ] No nh3 on `HtmlElement.html` — documented as intentional (sandbox is the boundary).

### 8.6 Standard gate
- `pytest -q` (+ e2e), `ruff check`/`format --check`, `manage.py check`, `makemigrations --check` (the one new migration applied), `collectstatic`, `compilemessages -l pl` — all clean.

---

## 9. Open questions / future work

- **App-wide CSP:** a broader hardening (CSP on the main app, with `frame-src`/`sandbox` directives) is worth doing but is out of scope here; this spec only sets CSP inside the sandbox document.
- **MathJax escape hatch:** add as an opt-in per-course engine choice only if KaTeX coverage proves insufficient.
- **Promote presentation widgets to native no-JS elements:** tabs, show-next reveal, slideshow, etc., as a later slice — reduces how often non-technical authors must touch the sandbox.
- **External media/network knob:** per-course relaxation of `img-src`/`connect-src` if a real widget needs it.
- **Protected media inside the sandbox:** opaque-origin iframes send no cookies, so any libli media referenced from author HTML must be reachable without session auth (public/`'self'` GET). Confirm against the media-serving model when external/protected media is needed.
