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

A `<meta http-equiv="Content-Security-Policy">` is injected *inside* the srcdoc document. **Critical subtlety:** the framed document has an **opaque origin**, and an opaque origin matches **no** `'self'` — so `'self'` source-expressions silently match nothing. The CSP therefore names the **configured app origin explicitly** (scheme+host, e.g. `https://yourschool.example`) wherever libli-hosted assets must load (KaTeX fonts, author images stored in libli media). The origin is built from a **trusted, non-spoofable configured source** at render time — a settings value / the `Sites` framework entry / an `ALLOWED_HOSTS`-validated host — and **never** from the inbound request's `Host` header. Because this origin is baked into a security control (the CSP allowlist), deriving it from a spoofable `Host` would let an attacker-influenced value redirect KaTeX/image loads. The source must be deterministic per deploy.

```
default-src 'none';
script-src 'unsafe-inline';
style-src 'unsafe-inline';
img-src <APP_ORIGIN> data:;
font-src <APP_ORIGIN> data:;
connect-src 'none'
```

- `'unsafe-inline'` for `script-src`/`style-src` is required — all scripts/styles (author + vendored KaTeX) are inline in the srcdoc.
- `connect-src 'none'` blocks `fetch`/XHR/`sendBeacon` (and WebSocket/EventSource — all `connect-src`-governed APIs), closing IP/timing **exfil to an author-chosen server** (there is nothing sensitive to send, but this removes the beacon channel entirely).
- `img-src <APP_ORIGIN> data:` allows **only** libli-hosted images and data URIs — no external CDNs and **no image-beacon exfil to arbitrary hosts** (an explicit origin, not `https:`, is what closes the beacon vector that `connect-src 'none'` alone would leave open via `<img>`). Consistent with libli's self-hosting stance (self-hosted Inter, vendored KaTeX).
- `font-src <APP_ORIGIN> data:` lets KaTeX's vendored font files load from libli (see §4.3).
- **Referrer** is controlled by the iframe's `referrerpolicy="no-referrer"` attribute (§2.2); the CSP `referrer` directive is deprecated and intentionally omitted (preempts a reviewer adding it).
- **Knob (documented, not built):** `img-src`/`connect-src` could be relaxed per-course later if a real widget needs external media or network. Default is locked-down.

### 2.5 The single parent↔sandbox channel (resize)

Iframes have no intrinsic content height, so libli injects a **resize reporter** into the srcdoc that observes the document with a `ResizeObserver` and `postMessage`s a single height number to the parent. A parent-side listener sets that iframe's height.

**Normative message contract (single source of truth — reporter and listener MUST agree):**

```js
{ type: "libli:htmlel:height", h: <integer px> }
```

The `type` literal is exactly `"libli:htmlel:height"` and the height field is exactly `h`. §4.4 and §8.2 reference this contract; they do not restate it divergently.

Hardening, because the opaque origin makes `event.origin === "null"`:

- **Validate by `event.source` identity** — match each message against each known iframe's `contentWindow` (origin checks are useless for opaque origins).
- Accept **only** the contract shape above: a message whose `type === "libli:htmlel:height"` with a numeric `h`. Anything else is ignored.
- Parse **only** an integer, **clamped** to `[MIN_IFRAME_HEIGHT, MAX_IFRAME_HEIGHT]` = `[0, 20000]` px (normative named constants, asserted by the §8.2 test) to prevent a runaway/hostile height. 20000 px accommodates legitimately tall content while bounding abuse.
- **Never** feed message content into the DOM, `eval`, or any sink. The inbound channel carries a clamped integer and nothing else.

### 2.6 Residual risks (named, accepted/mitigated)

- **Visual mimicry / UI redress:** the sandbox cannot stop author content *looking like* libli chrome (e.g. a fake password prompt). Mitigations: the iframe is a block element confined to its own box in normal flow (cannot overlay app chrome, cannot navigate the tab, cannot post to libli), and libli renders a subtle visual frame/label (e.g. "interactive content") around HTML elements so students can distinguish author content from app UI. Accepted as low-reach given the navigation/form restrictions.
- **Resource abuse (infinite loops):** author's own content; affects only the viewing student's tab. Accepted.
- **Answer keys visible:** per-unit seed JS (answer variables) is delivered to the client and inspectable. This matches the prior openEdX reality and is acceptable for *formative* practice; graded assessment is Phase 2 (server-side marking).

---

## 3. Data model & authoring

### 3.1 New model: `HtmlElement`

Concrete element model mirroring `MathElement`:

- `html = models.TextField(blank=True)` — the element body (raw markup + optional inline `<script>`/LaTeX).
- `elements = GenericRelation(Element)` — cascade join-row, as other element types.
- Added to `ELEMENT_MODELS`; renders via `templates/courses/elements/htmlelement.html` (by `ElementBase.render()` convention).

**No sanitization — and how that opt-out is mechanically guaranteed.** Sanitization in libli is **per-model, not central** (verified against the code): only `TextElement.save()` calls `sanitize_html(self.body)`, and the `{% sanitize %}` template filter is applied only in `textelement.html` (`{{ el.body|sanitize }}`). There is **no shared save hook or serializer** that sanitizes generically. Therefore the opt-out is simply *absence*: `HtmlElement.save()` performs no sanitization, and `htmlelement.html` MUST NOT use the `sanitize` filter (it emits the escaped-`srcdoc` iframe instead). Additionally, the HTML element's editor form/field MUST NOT introduce any tag-stripping `clean_*` — the raw `html` is stored verbatim. (Containment is the iframe per §2, not sanitization.)

### 3.2 Course-wide fields on `Course`

- `html_css = models.TextField(blank=True)`
- `html_js = models.TextField(blank=True)`

Injected into **every** HTML-element iframe in the course. **Propagation:** the assembled `srcdoc` is built at render time, so a course CSS/JS edit takes effect on the next render of each page (no stored/derived copy to invalidate); in the editor the existing "re-render on save" (§6.1) surfaces edits immediately. **Cost:** when several HTML elements appear on one page, each is a full document and (if it contains math) carries its own inline KaTeX copy — accepted; cross-iframe asset dedup is out of scope (§1.3).

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
  <base href="<APP_ORIGIN>/">   <!-- see §4.1 relative-URL note -->
  <style>/* vendored KaTeX CSS — only if math delimiters present */</style>
  <style>/* course_html_css */</style>
</head>
<body>
  {{ element.html }}   <!-- author HTML injected directly into body, no wrapper -->
  <script>/* unit.html_seed_js  — runs first, defines vars        */</script>
  <script>/* course_html_js     — reads vars, wires the DOM       */</script>
  <script>/* vendored KaTeX + auto-render pass — if math present  */</script>
  <script>/* libli resize reporter                               */</script>
</body>
</html>
```

**No body wrapper (decision):** author HTML is injected directly into `<body>`, not inside a `html-el-root` div, so author CSS selectors like `body > *` and JS like `document.body.firstElementChild` behave as in their original flat-body files. The student-facing visual frame/label (§2.6) lives on the **parent side**, around the iframe — not inside it.

**Relative-URL resolution (opaque origin):** a `srcdoc` document's relative URLs have no intrinsic base, so the document injects `<base href="<APP_ORIGIN>/">` (same trusted origin as the CSP, §2.4). This makes author `<img src="/media/…">` and the vendored `katex.min.css`'s relative `fonts/*.woff2` references resolve to the libli origin — which the CSP `img-src`/`font-src <APP_ORIGIN>` entries then permit. (If a `<base>` proves awkward with KaTeX, the fallback is to rewrite the vendored CSS's font URLs to absolute `<APP_ORIGIN>` paths; `<base>` is the default.)

**Order is load-bearing:** seed → course JS → math → resize. The "height is final after typesetting" guarantee does **not** rest on script order alone (KaTeX auto-render and web-font loading can complete asynchronously); the resize reporter re-reports on those events per §4.4, with `ResizeObserver` as the steady-state backstop.

### 4.2 Assembly context (data dependency)

`ElementBase.render(self)` currently receives only the element. `HtmlElement` assembly additionally needs the element's **unit** (`html_seed_js`) and **course** (`html_css`/`html_js`). The `{% render_element %}` template tag is extended to thread `unit` and `course` into HTML-element assembly (both `lesson_unit.html` and `_preview.html` already have `unit`/`course` in context). Implementation may pass them through the tag or resolve via the join-row → unit → course; the spec requires only that assembly has access to course CSS/JS and unit seed at render time.

### 4.3 Math (KaTeX auto-render)

**Decision:** reuse the already-vendored KaTeX and add its **auto-render extension** (`contrib/auto-render.min.js`), configured for **exactly two** delimiter pairs: `\(…\)` inline and `\[…\]` display. **`$$…$$` is NOT supported** (decision — the sampled content never uses it, and `$$` collides with literal-currency prose); the auto-render config and the detection predicate below agree on this.

**Injection-gating predicate (normative, testable).** KaTeX CSS + JS are injected for an HTML element **iff** its raw `html` field contains the substring `\(` **or** the substring `\[` (a naive case-sensitive substring scan of the stored author HTML — *not* a context-aware parse; a delimiter inside `<code>`/`<script>`/an attribute still triggers injection). This is a **new** predicate specific to the HTML element; it does **not** reuse the lesson page's `has_math` (which tests for the *presence of a `MathElement`*, an unrelated mechanism). Over-injection is harmless: auto-render only transforms genuine `\(…\)`/`\[…\]` pairs, and a stray injection just loads unused KaTeX. The §8.1 "iff" test asserts exactly this substring rule.

KaTeX runs with `throwOnError:false` (raw LaTeX left on failure). Vendoring task: add `auto-render.min.js` alongside the existing `katex.min.js`/`katex.min.css`. **KaTeX fonts:** the vendored `katex.min.css` references woff2 font files by URL; these resolve to the libli app origin and are permitted by the CSP `font-src <APP_ORIGIN>` entry (§2.4) — *not* by `'self'`, which is inert under the opaque origin. (Alternative if origin injection proves awkward: ship a data-URI-inlined KaTeX font CSS so fonts need no `font-src` host. Default is the app-origin approach.)

### 4.4 Resize bridge (client)

- **In-sandbox reporter** (injected): `ResizeObserver` on `document.documentElement` (and `body`) posts the §2.5 contract message to `window.parent`. It reports (a) on every observed size change (steady-state backstop), (b) after the KaTeX auto-render pass completes, and (c) on `document.fonts.ready` — because KaTeX typeset and web-font loading can finish *after* the initial layout, a single end-of-script report would otherwise under-measure tall/math content.
- **Parent listener** (new `courses/static/courses/js/html_element.js`): a **single** `window`-level `message` listener **attached once at module load** (never re-bound per fragment swap). On each message it (i) checks the message matches the §2.5 contract, (ii) resolves the sender by enumerating the current `iframe` elements in the DOM (e.g. `document.querySelectorAll("iframe")`) and matching `iframe.contentWindow === event.source` — so iframes created/destroyed by 1b-ii preview swaps are discovered at message time with no re-init race — (iii) clamps `h` to `[MIN_IFRAME_HEIGHT, MAX_IFRAME_HEIGHT]` (§2.5), and (iv) sets that iframe's `style.height`. Messages whose source matches no current iframe are ignored.

---

## 5. Templates & static

- `templates/courses/elements/htmlelement.html` — emits the escaped-`srcdoc` iframe (+ the §2.6 visual frame/label).
- `courses/static/courses/js/html_element.js` — parent-side resize listener (loaded on both the lesson page and the editor page).
- `courses/static/courses/vendor/katex/contrib/auto-render.min.js` — newly vendored.
- `templates/courses/manage/editor/_edit_html.html` — the 6th element editor (HTML body textarea) on the 1b-ii editor page.
- Course settings surface gains the two course-wide code textareas; the unit editor gains the per-unit seed textarea.
- CSS: a small **parent-side** `.html-el` container style around the iframe (the §2.6 visual frame/label affordance + no-JS fallback min-height + `overflow:auto` on the iframe). This wrapper lives in the lesson/editor page, *not* inside the iframe document (§4.1).

---

## 6. Integration

### 6.1 Preview parity

`render_element` emits the iframe in both `lesson_unit.html` and `_preview.html`. 1b-ii's "re-render on save" rebuilds the preview iframe with a fresh `srcdoc`, so the author sees exactly the student result (JS running, math typeset). `html_element.js` is loaded on the editor page too.

### 6.2 Progress "seen"

Unchanged. The lesson wraps each element in `<section data-element-id>`; the IntersectionObserver watches the **wrapper**, not iframe internals. HTML elements auto-complete like any other element.

### 6.3 No-JS fallback

With browser JS fully disabled: the iframe still renders static HTML+CSS; author JS and the resize bridge don't run, so the iframe falls back to a fixed min-height with internal scroll (`overflow:auto`). The lesson's plain "Mark as done" POST form is unaffected.

**Lazy-load interaction (accepted):** the iframe carries `loading="lazy"` (§2.2), so a far-down HTML element does not load until near the viewport; its first height report therefore arrives only on that near-viewport load, and it shows the fallback min-height until then. This is acceptable and intended.

### 6.4 One-iframe-per-element behavior note

Each HTML element is its own document, so course JS scans only that element's content. Splitting a multi-question file into several HTML elements resets per-iframe numbering and prevents cross-element coordination. **Authoring guidance:** keep content that must coordinate (shared numbering, cross-question logic) inside a *single* HTML element. Expected and documented, not a defect.

---

## 7. Error handling

- Malformed author HTML/JS cannot affect libli (isolated); script errors stay in the iframe console.
- **Per-block failure isolation (accepted):** the seed, course JS, and KaTeX/resize scripts are separate `<script>` tags, so a syntax/runtime error in one block aborts only that block — e.g. a broken seed leaves the course JS to run against undefined variables. This is intended (independent failure aids authoring debuggability); libli does not defensively wrap author blocks. Authors see the failing block's error in the iframe console.
- Empty `html_css`/`html_js`/`html_seed_js` → those blocks are omitted from the assembled document.
- KaTeX failures leave raw LaTeX (`throwOnError:false`).
- Resize messages from unknown `event.source` or wrong shape are ignored; height is clamped.

---

## 8. Testing & Definition of Done

### 8.1 Unit tests
- Emitted iframe has **exactly** `sandbox="allow-scripts"` and **no** `allow-same-origin`; carries `referrerpolicy="no-referrer"`.
- `srcdoc` is attribute-escaped: `"`, `&`, `<` in author content cannot break out of the attribute.
- Course CSS/JS + unit seed are injected, in the correct order (seed before course JS).
- KaTeX CSS/JS injected **iff** the raw `html` contains `\(` or `\[` (the §4.3 substring predicate); absent otherwise — including a case where `\(` appears (injected) and a case with `$$` only (NOT injected, since `$$` is unsupported).
- Empty fields omit their blocks.
- In-sandbox CSP meta present with `connect-src 'none'` and an explicit app-origin (not `'self'`) for `img-src`/`font-src`.
- `<base href="<APP_ORIGIN>/">` present in the assembled head.
- **Cascade delete:** deleting an `HtmlElement` (via the element machinery) removes its `Element` join-row — no orphaned join-rows (guards the GenericRelation foot-gun).

### 8.2 JS / resize handler tests
- Listener ignores messages from unknown sources and wrong-shaped messages.
- Height is clamped to the allowed range.

### 8.3 Playwright e2e
- Author an HTML element with a per-unit seed + a button that uses a seeded variable → renders and runs in both the editor preview and the lesson page; iframe resizes to content.
- Two HTML elements on one page size independently.
- **Runtime containment** (asserts the opaque-origin effect, not just the attribute): script inside the iframe attempting `localStorage`/`document.cookie` access throws / yields no parent data, and the parent DOM is unreachable. (§8.1 checks the *attributes* that produce isolation; this checks the browser-*enforced* effect. If reliably asserting cross-origin throws in Playwright proves flaky, downgrade to documenting that enforcement is browser-guaranteed by the §8.1 attribute set.)

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
- **Protected media inside the sandbox:** opaque-origin iframes send no cookies, so any libli media referenced from author HTML (resolved via `<base href="<APP_ORIGIN>/">`, §4.1) must be reachable without session auth (a plain GET to the app origin permitted by `img-src <APP_ORIGIN>`). Confirm against the media-serving model when protected media is needed.
