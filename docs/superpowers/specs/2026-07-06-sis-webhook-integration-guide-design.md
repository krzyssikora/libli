# SIS Webhook Integration Guide — Design

**Date:** 2026-07-06
**Status:** Approved (brainstorm) — ready for implementation plan
**Slice:** 1 of 4 in the documentation initiative (SIS webhook guide → user manuals → developer onboarding → docstring/.env gaps). This spec covers **only** Slice 1.

## Context

The `integrations` app ships a well-built **outbound** grade-sync webhook: when a
quiz result is finalized, `emit_result_finalized` enqueues one `WebhookDelivery`
per (student, course, group, unit), and `flush_webhooks` (cron) POSTs each to the
single configured endpoint, HMAC-signed, with exponential-backoff retries and
dead-lettering.

The problem is entirely on the **receiver** side. A school's student-information-
system / e-register vendor — who typically has **no repository access and no
account on the platform** — currently has no way to learn the contract. The
Integrations settings tab (`_integrations_tab.html`) exposes only three fields
(Enable / Endpoint URL / Signing secret) and **zero** explanatory text. The only
prose that fully describes the payload, headers, signature scheme, ack contract,
and idempotency rules is an internal engineering design doc under
`docs/superpowers/specs/`, which is not published to anyone outside the codebase.

Result: an external developer cannot build a working receiver without being handed
the source. This slice fixes that.

## Goals

- Publish a **receiver-facing integration guide** at a stable, shareable, **public
  (no-login)** URL that a vendor can be emailed.
- Keep the guide content in **version control** (markdown), rendered natively so it
  matches the app's look.
- Give the configuring platform admin **inline orientation** in the settings tab,
  with a prominent link to the full guide.
- Let a receiver developer exercise a **live, signed delivery on demand** (a "Send
  test event" button) instead of waiting for a real student to finalize a result.

## Non-goals

- No change to the real webhook wire contract, delivery pipeline, retry logic, or
  outbox. (The **only** payload change anywhere is the `"test": true` marker, which
  appears exclusively on test-fire events — never on real deliveries.)
- No general in-app help/documentation system. That is **Slice 2**; this slice
  deliberately builds a minimal, single-document renderer that Slice 2 can later
  generalize. We do not build a docs index, navigation, or multi-page routing here.
- No syntax highlighting of code blocks (styled `<pre>` is sufficient; highlighting
  can be added later without touching the contract).
- No authentication/authorization on the guide page — it is a public reference with
  no sensitive data.

## Design

### A. Public guide page (markdown → rendered)

**Content source.** A new markdown file `docs/integrations/sis-webhook.md` holds the
entire guide (outline in section D). It is trusted, repo-authored content — not user
input — so no HTML sanitization is required.

**Renderer util.** A new `integrations/docs.py` exposes
`render_markdown_doc(path) -> str` (returns rendered HTML). It uses the
**Python-Markdown** library (new dependency, added via `uv`) with the `fenced_code`
and `tables` extensions enabled (the guide relies on fenced code blocks and header
tables). The util resolves the path relative to a fixed docs root inside the repo;
it does **not** accept a path from the request (no traversal surface).

**View + route.** A new `integrations/views.py` provides a single view that renders
the guide file into a minimal styled template and returns it. A new
`integrations/urls.py` (with `app_name = "integrations"`) is included at the project
root via `path("", include("integrations.urls"))` — so, matching the other apps'
root-mounted includes, the pattern string **inside** `integrations/urls.py` carries
the full path (`path("integrations/webhook/", views.webhook_guide, name="webhook_guide")`),
not a bare `webhook/`. Resulting route:

```
GET /integrations/webhook/   name="integrations:webhook_guide"   (public, no login)
```

**Missing/failed render.** The guide markdown is a required repo asset shipped with
the code. If the file is absent or fails to render, `render_markdown_doc` **raises**
(fail-loud → 500) rather than serving an empty page — a missing static asset is a
packaging/deploy bug, not a runtime condition to paper over. This is asserted by a test
(see DoD).

**Template.** `templates/integrations/webhook_guide.html` wraps the rendered HTML in
a lightweight public shell that pulls in the existing design tokens/CSS so the page
reads as native (not raw markdown). Code blocks render as styled `<pre><code>`.
The template is a thin content frame — it does not require login and does not depend
on the authenticated app chrome.

**Reuse note.** `render_markdown_doc` + this view/template are intentionally the
**seed** for the Slice 2 help system; Slice 2 will generalize the same approach to a
multi-document, role-aware help section.

### B. "Send test event" feature

**Trigger.** A **Send test event** button rendered in `_integrations_tab.html`,
inside the Integrations tab (platform-admin only — same surface that owns the
config). The button is a POST form targeting a new action route.

**"Configured" gate (deliberately independent of `enabled`).** The button is
**enabled whenever a non-empty URL AND a non-empty signing secret are stored** — it
does **not** require the `enabled` flag. This is the whole point of a test: an admin
verifies the receiver works *before* flipping on real emission, so gating the test on
`enabled` would force them to turn on production deliveries to an unverified endpoint
first (the opposite of the goal). A non-empty secret is required because
`send_test_event` must sign with it for the guide's "verify the signature end-to-end"
promise to hold (signing with a blank secret would produce a signature the receiver
cannot meaningfully verify). When URL or secret is missing, the button is disabled and
the tab explains why. The template disables the button on a **server-computed
`webhook_configured` boolean** (`bool(endpoint.url and endpoint.secret)`) passed via the
settings context — it must **not** try to read the secret value, which is a masked /
write-only form field (`PasswordInput(render_value=False)`) not exposed to the template.

**Route + view.** A new PA-gated action in `institution/views_manage.py`,
`settings_integrations_test`, following the exact pattern of the existing
`settings_integrations` action:

```
POST /manage/settings/integrations/test/   name="institution:settings_integrations_test"
```

- `@login_required` + `@permission_required("institution.change_institution", raise_exception=True)`.
- GET → `redirect(_index_url("integrations"))` (actions are POST targets), mirroring
  the existing `settings_integrations` action exactly (not a hand-written query string).
- On POST: obtain the singleton via `WebhookEndpoint.load()` (get_or_create on pk=1, as
  the existing `settings_integrations` action does) so a never-configured state returns a
  row with blank url/secret rather than `None`; if URL or secret is missing (per the gate
  above),
  `messages.error(_("Set an endpoint URL and signing secret before sending a test event."))`
  and redirect back. Otherwise call `integrations.delivery.send_test_event(endpoint)`,
  translate its outcome into a `messages.success` (interpolating the actual status
  code, e.g. `_("Test event delivered — endpoint returned %(code)s.") % {"code": status}`
  — any 2xx is success, not only 200) or a `messages.error`
  (`_("Test event failed: %(reason)s")`), and redirect back to the integrations tab via
  `_index_url("integrations")`.

**Sender.** A new `send_test_event(endpoint)` in `integrations/delivery.py`,
**separate** from `deliver_one` (which is outbox-coupled: it mutates and reschedules
a `WebhookDelivery` row). `send_test_event`:

- Builds a **sample payload** identical in shape to a real one (see the sample in
  section D.9), with a top-level **`"test": true`** and clearly-marked sample
  identifiers (e.g. `external_id: "SAMPLE-COURSE"`), including a populated `group`
  block so the vendor sees the group shape.
- Signs it with the real `endpoint.secret` via the existing `sign()` (so signature
  verification can be exercised end-to-end).
- POSTs **synchronously** using the existing `_build_opener()` (no-redirect) and
  `TIMEOUT_SECONDS`, with headers `Content-Type: application/json`,
  `X-Libli-Event: result_finalized`, `X-Libli-Delivery: test`, and
  `X-Libli-Signature: sha256=…`.
- **Persists nothing** — no `WebhookDelivery` row, no retry scheduling. It returns a
  three-element result `(ok: bool, status: int | None, detail: str)`: on success
  `ok=True`, `status` is the HTTP status code returned (any 2xx), `detail` empty; on
  failure `ok=False`, `status` is the HTTP code if one was received (else `None` for a
  timeout/connection error), and `detail` is a short human-readable reason. The view
  reads `status` for the success message's `%(code)s` and `detail` for the failure
  message's `%(reason)s`.

**Discriminators for the receiver (two, redundant):** the body field `"test": true`
**and** the header `X-Libli-Delivery: test` (real deliveries carry an integer pk).
Both are documented so a receiver can discard test events safely. Real payloads
never include a `"test"` key — backward-compatible with any already-deployed
receiver.

**Safety.** The button only ever POSTs to the admin's own already-configured URL, so
it introduces no new SSRF surface beyond configuring the endpoint (already a PA
power). It is PA-gated and POST-only (CSRF-protected by Django's default).

### C. Settings-tab help text

A concise oriented block added to `_integrations_tab.html` above/around the existing
form: one short paragraph on **what** is POSTed and **when**, the three headers named,
the "**return 2xx to acknowledge**" rule, and a prominent **link to the full guide**
(`{% url 'integrations:webhook_guide' %}`). It orients the configuring admin without
duplicating the guide. All strings are translatable (`gettext`), consistent with the
rest of the tab.

### D. Guide content outline

`docs/integrations/sis-webhook.md`, in this order:

1. **Overview** — what fires the webhook (a finalized quiz result); granularity: one
   event per (student, course, group, unit); delivery is asynchronous (cron-driven),
   not real-time.
2. **Transport** — HTTP `POST`, `Content-Type: application/json`, to the endpoint URL
   the platform admin configures; TLS strongly recommended (HMAC provides integrity/
   authenticity, **not** confidentiality — over plain `http`, grades transit in
   cleartext).
3. **Headers** (table) — `X-Libli-Event` (`result_finalized`), `X-Libli-Delivery`
   (delivery id; the literal `test` for test events), `X-Libli-Signature`
   (`sha256=<hex>`).
4. **Payload** — a **canonical real-delivery example** (below) + a field-reference
   table. The example is distinct from the test sample in D.9 — it has **no `test`
   key** and uses realistic ids — so an implementer never accidentally ships
   `"test": true`/sentinel ids in the canonical-payload section. Show both the
   `group: null` and the populated-`group` variants. Explicitly call out the **traps**:
   - **Student identity:** the `student` block has **no numeric id** — the only student
     key is `external_id` (see D.8). `student.external_id` and `student.email` **may
     both be empty strings**; `name` (`display_name` or `username`) is display-only,
     neither unique nor stable. Grade sync therefore requires `external_id` to be
     populated (see the admin note in D.10).
   - `score.earned` / `score.max` are decimal **strings** (e.g. `"8.00"`).
     `score.percent` is a **number that varies by type**: a 2-dp **float** normally
     (e.g. `80.0`, `66.67`) but the JSON **integer `0`** when `max` is 0 — receivers
     should parse it as a general number and not assume float. (A zero-max unit sends
     `"score": { "earned": "0.00", "max": "0.00", "percent": 0 }`.)
   - `group` is `null` **or** the event **fans out — one delivery per group** (each
     otherwise identical, differing only in the `group` block). `group.external_id`
     may be empty; the stable group key is the numeric `group.id` (see D.8).
   - `course.external_id` is always present (it gates emission); `unit.id` and
     `group.id` are stable numeric pks.
   - `finalized_at` is ISO-8601 UTC, but its **fractional-seconds component is
     variable-width and may be absent entirely** (Python's `isoformat()` omits
     microseconds when they are exactly zero — so the field may arrive as
     `2026-07-06T10:15:30.482170+00:00` or, rarely, `2026-07-06T10:15:30+00:00`).
     Receivers must use a **tolerant ISO-8601 parser**, must not assume fixed microsecond
     precision, and should treat it as the ordering/authority key at whatever resolution
     is present (see idempotency).

   Canonical real-delivery example (populated-group variant; the no-group variant is
   identical with `"group": null`):

   ```json
   {
     "event": "result_finalized",
     "finalized_at": "2026-07-06T10:15:30.482170+00:00",
     "student": { "external_id": "S-2024-0912", "email": "ada.k@example.edu", "name": "Ada Kowalska" },
     "course":  { "external_id": "MATH-101", "slug": "algebra-i", "title": "Algebra I" },
     "group":   { "id": 42, "external_id": "3B", "name": "Class 3B" },
     "unit":    { "id": 318, "title": "Quadratic Equations" },
     "score":   { "earned": "8.00", "max": "10.00", "percent": 80.0 }
   }
   ```
5. **Verifying the signature** — the algorithm (recompute
   `HMAC-SHA256(secret, raw_request_body)`, hex, compare to the header value after the
   `sha256=` prefix, using a constant-time compare) followed by concrete snippets in
   **Python**, **Node.js**, and **PHP**, plus a language-agnostic step list and a
   `curl` illustration. **Critical footgun to call out prominently:** the signature is
   computed over the **exact raw bytes on the wire**, which are compact (`json.dumps`
   default separators, `ensure_ascii=True`) — *not* the pretty-printed JSON shown in
   this guide. Receivers must HMAC the **raw received body bytes** and must never
   parse-then-re-serialize before hashing (re-encoding changes the bytes and the
   signature will not match). Each snippet must read the raw body, not a re-encoded copy.
6. **Responding** — return HTTP **2xx** to acknowledge. Any non-2xx, timeout, or
   connection error is treated as failure and retried.
7. **Retries & delivery semantics** — up to **8 attempts**; backoff schedule
   `[1, 5, 15, 60, 180, 360, 720]` minutes; **10s** timeout per attempt; after the 8th
   failure the delivery is dead-lettered. Redirects are refused. Delivery is driven by
   a periodic cron flush, so expect delivery **shortly after** finalization, not
   instantly.
8. **Idempotency & corrections** *(prominent — the contract most likely to be gotten
   wrong)* — `X-Libli-Delivery` dedupes **retries of a single delivery only**. A later
   score **correction is a new delivery** with a new id. Receivers **must upsert** a
   result row and treat **`finalized_at` as authoritative** — ignore an incoming event
   whose `finalized_at` is older than what is already stored.

   The upsert key must be pinned to **stable** fields, not the blankable ones:
   - **student** → `student.external_id`. This is the *only* student identifier in the
     payload (there is no numeric student id), so grade sync is only usable when
     external_id is populated; a receiver cannot reliably key a student whose
     external_id (and email) are blank. The guide must state this plainly and direct
     admins to populate student external_ids (D.10).
   - **course** → `course.external_id` (always present).
   - **group** → the numeric **`group.id`** (a stable pk), **not** `group.external_id`.
     This mirrors the internal `dedupe_key`, which deliberately uses `Group.pk` "NOT
     the blankable external_id — two unmapped groups must not collide." A receiver that
     keys on `group.external_id` will collapse distinct unmapped groups into one row.
   - **unit** → the numeric **`unit.id`**.

   So the concrete upsert key is `(student.external_id, course.external_id, group.id,
   unit.id)` — with the group segment absent for the `group: null` (no-group) delivery.
9. **Testing your endpoint** — the platform admin's **Send test event** button; test
   events carry `"test": true` **and** `X-Libli-Delivery: test` and use sample data (the
   `id: 0` group/unit values are obvious placeholders, not real pks) — receivers should
   verify the signature but **not** ingest them as real grades. A representative sample
   payload:

   ```json
   {
     "test": true,
     "event": "result_finalized",
     "finalized_at": "2026-07-06T10:15:30.123456+00:00",
     "student": { "external_id": "SAMPLE-STUDENT", "email": "sample.student@example.edu", "name": "Sample Student" },
     "course":  { "external_id": "SAMPLE-COURSE", "slug": "sample-course", "title": "Sample Course" },
     "group":   { "id": 0, "external_id": "SAMPLE-GROUP", "name": "Sample Group" },
     "unit":    { "id": 0, "title": "Sample Unit" },
     "score":   { "earned": "8.00", "max": "10.00", "percent": 80.0 }
   }
   ```
10. **For the platform admin** — where to configure the endpoint URL and signing
    secret (Manage → Settings → Integrations); that the same secret must be shared with
    the receiver to verify signatures; and that **every student whose results are synced
    must have an `external_id` set**, because it is the only student key in the payload
    (results for a student with no external_id cannot be mapped by the receiver).
    *Hardening follow-up (noted, out of scope for this slice): emission does not
    currently gate on `student.external_id`, so such events are still sent — a later
    slice should either gate emission on it or add a stable numeric `student.id` to the
    payload.*

## Wire-contract reference (canonical facts, sourced from code)

For the implementer — these must match the source exactly:

- Payload construction: `integrations/services.py::build_payload` (real events; **no**
  `test` key).
- Headers + signing: `integrations/delivery.py::deliver_one` / `sign`
  (`sha256=<hmac_sha256(secret, body).hexdigest()>`, signed over the exact bytes sent).
- Retry/ack constants: `integrations/delivery.py` — `MAX_ATTEMPTS = 8`,
  `BACKOFF = [1, 5, 15, 60, 180, 360, 720]`, `TIMEOUT_SECONDS = 10`; 2xx = success.
- Fan-out + gating: `integrations/services.py::emit_result_finalized`
  (one delivery per non-archived group, or a single no-group delivery; requires an
  enabled endpoint **and** a course `external_id`).

## Security considerations

- Guide page is public by design and contains no secrets or per-institution data
  (the sample payload is static, fictitious data).
- `render_markdown_doc` never takes a request-supplied path (fixed docs root) — no
  path traversal.
- Test-fire is PA-gated, POST/CSRF-protected, and targets only the pre-configured
  endpoint URL — no new SSRF surface.
- Markdown is repo-authored/trusted; we render it as-is and do not feed user input
  through the renderer.

## Testing strategy / Definition of done

- **Renderer:** unit test that `render_markdown_doc` renders fenced code and tables to
  the expected HTML for a small fixture, and that it **raises** on a missing/unreadable
  file (fail-loud contract).
- **Guide view:** test `GET /integrations/webhook/` returns 200 **while
  unauthenticated** and contains anchor content (e.g. the "Verifying the signature"
  heading and a code block).
- **Test-fire sender:** test `send_test_event` (a) signs with the endpoint secret so
  the signature validates, (b) sets `"test": true` in the body and
  `X-Libli-Delivery: test` header, (c) creates **no** `WebhookDelivery` rows, and
  (d) reports success on a stubbed 2xx and failure on a stubbed non-2xx/timeout.
- **Test-fire view:** PA can POST and gets a success message on a stubbed 2xx; a
  **disabled-but-configured** endpoint (`enabled=False`, URL + secret set) **still
  sends** successfully (the enabled-independent gate); a non-PA is rejected; GET
  redirects; an **unconfigured** endpoint (missing URL or secret) yields an error
  message and no send.
- **Settings tab:** the integrations tab renders the help block and a link to the
  guide; the Send-test button is disabled when unconfigured.
- **i18n:** new user-facing strings are marked translatable; run the catalog tests /
  `makemessages` check per repo convention (no obsolete `#~` entries).
- Full suite green; ruff clean; new dependency recorded in `pyproject.toml`/`uv.lock`.

## Dependencies

- Adds **Python-Markdown** (`markdown`) via `uv`. First markdown-rendering dependency
  in the project; justified here and reused by Slice 2.

## Follow-on slices (out of scope here)

2. In-app help system + user manuals (PA/CA/Author) — generalizes this renderer.
3. Developer onboarding (README, setup, conventions, app-dependency map).
4. Docstring + `.env.example` gaps.
