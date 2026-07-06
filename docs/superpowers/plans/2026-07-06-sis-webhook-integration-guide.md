# SIS Webhook Integration Guide — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a receiver-facing SIS-webhook integration guide at a public URL (markdown rendered by a small view), and add a synchronous "Send test event" button to the Integrations settings tab so a school's developer can build and verify a working endpoint.

**Architecture:** A tiny trusted-markdown renderer (`integrations/docs.py`) feeds a public, no-login Django view that renders `docs/integrations/sis-webhook.md` inside the normal app shell. A new `send_test_event(endpoint)` in `integrations/delivery.py` reuses the existing `sign()`/`_build_opener()` to POST one signed sample payload synchronously (persisting nothing) and returns `(ok, status, detail)`, surfaced by a PA-gated `settings_integrations_test` action. The Integrations tab gains a help block, a link to the guide, and a separate (sibling) Send-test form.

**Tech Stack:** Python 3.13, Django 5.2, Python-Markdown (new dep), uv, pytest / pytest-django, ruff.

## Global Constraints

- Python `>=3.13`; Django `>=5.2,<5.3`. Dependencies are uv-managed — add with `uv add <pkg>` (updates `pyproject.toml` + `uv.lock`); never hand-edit the lock.
- All shell commands run under `uv run` (e.g. `uv run pytest ...`, `uv run ruff ...`) — bare `pytest`/`ruff`/`python` are NOT on PATH.
- Ruff lint selects `E,F,I,UP,B,S` (bandit). isort is `force-single-line = true` — one import per line. Use `# noqa: S310` on the `urllib.request.Request` call (as `delivery.py` already does — the URL is admin-configured, not request-supplied).
- Tests are pytest with `pytestmark = pytest.mark.django_db`; e2e is excluded by default (`-m 'not e2e'`). Use `tests.factories` helpers: `make_pa(client, name)`, `make_login(client, name)`, `TEST_PASSWORD`. Never introduce a new password literal (GitGuardian CI flags it).
- urllib normalizes request header keys to `.capitalize()` form — assert `req.headers["X-libli-signature"]`, `["X-libli-delivery"]`, `["X-libli-event"]` (lower after the first segment), mirroring `integrations/tests/test_delivery.py`.
- All new user-facing strings are translatable via `gettext`/`{% trans %}`. The guide markdown itself is a single **English** document — intentionally NOT localized (deferred to Slice 2).
- The **only** payload change anywhere is the top-level `"test": true` key, which appears **only** on test-fire events — never on real deliveries. Do not touch `services.build_payload`, the outbox, or retry logic.
- The guide page is **public / no login**. The guide markdown is trusted repo content (no HTML sanitization needed); `render_markdown_doc` never takes a request-supplied path.

## File Structure

- `integrations/docs.py` — **create.** Trusted-markdown renderer: `DOCS_ROOT` + `render_markdown_doc(rel_path)`.
- `integrations/views.py` — **create.** Public `webhook_guide` view.
- `integrations/urls.py` — **create.** `app_name="integrations"`; the `/integrations/webhook/` route.
- `config/urls.py` — **modify.** Include `integrations.urls` at root.
- `templates/integrations/webhook_guide.html` — **create.** Public doc shell extending `base.html`.
- `docs/integrations/sis-webhook.md` — **create.** The full guide content.
- `integrations/delivery.py` — **modify.** Add `SAMPLE_PAYLOAD` + `send_test_event(endpoint)`.
- `institution/views_manage.py` — **modify.** Add `settings_integrations_test` action; add `webhook_configured` to `_settings_context`.
- `institution/urls.py` — **modify.** Route for the test action.
- `templates/institution/manage/_integrations_tab.html` — **modify.** Help block + guide link + Send-test sibling form.
- `integrations/tests/test_docs.py` (T1), `test_guide_content.py` (T2), `test_guide_view.py` (T3), `test_test_fire_sender.py` (T4), `test_test_fire_view.py` (T5), `test_tab_ui.py` (T6) — **create.** Tests per task.

---

### Task 1: Markdown renderer util

**Files:**
- Create: `integrations/docs.py`
- Test: `integrations/tests/test_docs.py`
- Modify: `pyproject.toml` (via `uv add markdown`)

**Interfaces:**
- Produces: `integrations.docs.DOCS_ROOT` (a `pathlib.Path` to the repo `docs/` dir); `integrations.docs.render_markdown_doc(rel_path: str) -> str` (returns rendered HTML; raises `FileNotFoundError` on a missing file).

- [ ] **Step 1: Add the dependency**

Run: `uv add markdown`
Expected: `pyproject.toml` `dependencies` gains a `markdown>=...` entry and `uv.lock` updates.

- [ ] **Step 2: Write the failing test**

```python
# integrations/tests/test_docs.py
import pytest

from integrations import docs


def test_renders_fenced_code_and_tables(tmp_path, monkeypatch):
    doc = tmp_path / "sample.md"
    doc.write_text(
        "# Title\n\n```python\nx = 1\n```\n\n"
        "| A | B |\n|---|---|\n| 1 | 2 |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(docs, "DOCS_ROOT", tmp_path)
    html = docs.render_markdown_doc("sample.md")
    assert "<pre>" in html and "<code" in html
    assert "<table>" in html and "<th>A</th>" in html


def test_missing_file_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(docs, "DOCS_ROOT", tmp_path)
    with pytest.raises(FileNotFoundError):
        docs.render_markdown_doc("nope.md")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest integrations/tests/test_docs.py -v`
Expected: FAIL — `ModuleNotFoundError: integrations.docs` (or `AttributeError`).

- [ ] **Step 4: Write minimal implementation**

```python
# integrations/docs.py
"""Render a trusted, repo-authored markdown doc to HTML. Content is NOT user
input (fixed paths only), so no sanitization is applied. Fail-loud on a missing
file: a missing static asset is a packaging/deploy bug, not a runtime condition."""

from pathlib import Path

import markdown

# integrations/docs.py -> parent is the app dir; its parent is the repo root,
# which holds docs/.
DOCS_ROOT = Path(__file__).resolve().parent.parent / "docs"


def render_markdown_doc(rel_path):
    text = (DOCS_ROOT / rel_path).read_text(encoding="utf-8")
    return markdown.markdown(text, extensions=["fenced_code", "tables"])
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest integrations/tests/test_docs.py -v`
Expected: PASS (both tests).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock integrations/docs.py integrations/tests/test_docs.py
git commit -m "feat(integrations): trusted-markdown renderer for doc pages"
```

---

### Task 2: Author the SIS webhook guide

**Files:**
- Create: `docs/integrations/sis-webhook.md`
- Test: `integrations/tests/test_guide_content.py`

**Interfaces:**
- Produces: the file `docs/integrations/sis-webhook.md` (rendered by Task 3). This task's own `test_guide_content.py` asserts the anchor headings `## Verifying the signature` and `## Idempotency & corrections` (Task 3's view test separately checks the rendered "Verifying the signature" text).

- [ ] **Step 1: Write the failing structural test**

```python
# integrations/tests/test_guide_content.py
from integrations.docs import DOCS_ROOT


def test_guide_has_required_content():
    text = (DOCS_ROOT / "integrations/sis-webhook.md").read_text(encoding="utf-8")
    for anchor in [
        "## Verifying the signature",
        "## Idempotency & corrections",
        "X-Libli-Signature",
        "```python",
        "```javascript",
        "```php",
    ]:
        assert anchor in text, anchor
    # Both a canonical (real) example and the test sample exist.
    assert '"test": true' in text  # the test sample
    assert text.count('"event": "result_finalized"') >= 2  # canonical + test
    # UTF-8 key + lowercase-hex verification guidance is present.
    assert "UTF-8" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest integrations/tests/test_guide_content.py -v`
Expected: FAIL — `FileNotFoundError`.

- [ ] **Step 3: Create the guide file with this exact content**

Create `docs/integrations/sis-webhook.md`:

````markdown
# Libli SIS Webhook Integration Guide

Libli can push finalized quiz results to your student-information system (SIS)
or e-register over an HTTP webhook. This guide is everything a developer needs
to build the **receiving** endpoint.

## Overview

- Libli sends a webhook when a student's quiz result is **finalized**.
- One event is sent per **(student, course, group, unit)**. A student who
  belongs to several groups in a course receives **one event per group** (the
  payloads are identical except for the `group` block). A student in no group
  receives a single event with `"group": null`.
- Delivery is **asynchronous** — driven by a periodic background flush, so
  expect an event shortly after finalization, not in real time.

## Transport

- HTTP **POST** to the endpoint URL your Libli platform admin configures.
- `Content-Type: application/json`.
- **Use HTTPS.** The signature (below) proves integrity and authenticity but
  does **not** encrypt — over plain `http`, grades travel in cleartext.

## Headers

| Header | Value |
|---|---|
| `X-Libli-Event` | `result_finalized` |
| `X-Libli-Delivery` | The delivery id (an integer, as a string). For **test** events this is the literal `test`. |
| `X-Libli-Signature` | `sha256=<hex>` — HMAC-SHA256 of the raw body (see *Verifying the signature*). |

## Payload

A **real** delivery looks like this (populated-group variant; a student in no
group sends the same shape with `"group": null`):

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

Field notes — read these carefully; they are where integrations usually go wrong:

- **Student identity.** The `student` block has **no numeric id**. The only
  student key is `external_id`. Both `student.external_id` and `student.email`
  **may be empty strings**; `name` is display-only and is neither unique nor
  stable. Grade sync is only usable when `external_id` is populated — see
  *Idempotency & corrections* for the receiver rule.
- **Scores are strings.** `score.earned` and `score.max` are decimal
  **strings** with 2 decimal places (e.g. `"8.00"`). Parse them as exact
  decimals, not floats.
- **`score.percent` varies by type.** It is normally a 2-dp **float** (e.g.
  `80.0`, `66.67`) but is the JSON **integer `0`** when `max` is 0. Parse it as
  a general number. Example zero-max score block:
  `"score": { "earned": "0.00", "max": "0.00", "percent": 0 }`.
- **`group`.** `null`, or an object; `group.external_id` may be empty. The
  stable group key is the numeric **`group.id`**.
- **`course.external_id`** is always present (Libli only sends events for
  courses that have it). `unit.id` and `group.id` are stable numeric ids.
- **`finalized_at`** is ISO-8601 UTC, but its fractional-seconds part is
  **variable-width and may be absent** — the same field can arrive as
  `2026-07-06T10:15:30.482170+00:00` or `2026-07-06T10:15:30+00:00`. Use a
  tolerant ISO-8601 parser and do not assume microsecond precision.

## Verifying the signature

Every request carries `X-Libli-Signature: sha256=<hex>`. To verify:

1. Take the **raw request body bytes** — exactly as received. Do **not** parse
   the JSON and re-serialize it; re-encoding (even a whitespace change) changes
   the bytes and the signature will not match. The wire body is single-line JSON
   with default spacing (a space after each `:` and `,`), not the pretty-printed
   JSON shown above.
2. Compute `HMAC-SHA256` with the **key = your shared signing secret encoded as
   UTF-8 bytes** and the message = those raw body bytes.
3. Take the **lowercase** hex digest and prefix it with `sha256=`.
4. Compare it to the header value using a **constant-time**, case-sensitive
   compare. The header hex is lowercase — do not upper-case or normalize before
   comparing.

Python (Flask):

```python
import hashlib
import hmac
import json

SECRET = b"your-shared-secret"  # UTF-8 bytes


def receive(request):
    raw = request.get_data()  # raw bytes — NOT request.json then re-dumped
    got = request.headers.get("X-Libli-Signature", "")
    expected = "sha256=" + hmac.new(SECRET, raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(got, expected):
        return ("", 401)
    event = json.loads(raw)
    if event.get("test"):
        return ("", 200)  # verify, but never ingest a test event
    # ... upsert (see Idempotency & corrections) ...
    return ("", 200)
```

Node.js (Express):

```javascript
const crypto = require("crypto");
const SECRET = "your-shared-secret"; // utf-8

// Capture the RAW body so the signature is computed over the exact bytes:
app.use("/libli-webhook", express.raw({ type: "application/json" }));

app.post("/libli-webhook", (req, res) => {
  const raw = req.body; // Buffer of raw bytes
  const got = req.get("X-Libli-Signature") || "";
  const expected =
    "sha256=" + crypto.createHmac("sha256", SECRET).update(raw).digest("hex");
  const ok =
    got.length === expected.length &&
    crypto.timingSafeEqual(Buffer.from(got), Buffer.from(expected));
  if (!ok) return res.sendStatus(401);
  const event = JSON.parse(raw.toString("utf8"));
  if (event.test) return res.sendStatus(200); // do not ingest test events
  // ... upsert (see Idempotency & corrections) ...
  res.sendStatus(200);
});
```

PHP:

```php
<?php
$secret = 'your-shared-secret'; // utf-8
$raw = file_get_contents('php://input'); // raw bytes
$got = $_SERVER['HTTP_X_LIBLI_SIGNATURE'] ?? '';
$expected = 'sha256=' . hash_hmac('sha256', $raw, $secret);
if (!hash_equals($expected, $got)) {
    http_response_code(401);
    exit;
}
$event = json_decode($raw, true);
if (!empty($event['test'])) {
    http_response_code(200); // verify, do not ingest test events
    exit;
}
// ... upsert (see Idempotency & corrections) ...
http_response_code(200);
```

To sanity-check your verifier against a saved body, recompute the digest with
`openssl` over the byte-exact saved body (do not let the shell strip a trailing
newline):

```bash
openssl dgst -sha256 -hmac "your-shared-secret" < body.json
```

## Responding

Return HTTP **2xx** to acknowledge. Any other status, a timeout, or a
connection error is treated as a failure and the event is retried.

## Retries & delivery semantics

- Up to **8 attempts** per delivery.
- Backoff between attempts: **1, 5, 15, 60, 180, 360, 720 minutes**.
- **10-second** timeout per attempt.
- After the 8th failed attempt the delivery is dead-lettered (dropped).
- Redirects are **not** followed — respond directly, do not 3xx.

## Idempotency & corrections

This is the contract most integrations get wrong — read it fully.

- `X-Libli-Delivery` dedupes **retries of a single delivery** only.
- A later **score correction is a new delivery** with a new id — *not* a retry.
- **Upsert** a result row and treat **`finalized_at` as authoritative**: ignore
  an incoming event whose `finalized_at` is older than what you already stored.

Pin your upsert key to **stable** fields:

- **student** → `student.external_id` (the only student identifier).
- **course** → `course.external_id`.
- **group** → the numeric **`group.id`** (not the blankable `external_id`;
  two unmapped groups both have an empty `external_id` and would collide).
- **unit** → the numeric **`unit.id`**.

So the key is `(student.external_id, course.external_id, group.id, unit.id)`,
with the group segment omitted for a `"group": null` event.

**Receiver rule for a blank student.** An event whose `student.external_id` is
empty **cannot be mapped** to a student — **reject/skip it and log**, rather than
upsert on a blank key (which would collapse all such students into one row). Ask
your Libli platform admin to ensure every synced student has an `external_id`.

## Testing your endpoint

Your Libli platform admin can click **Send test event** on the Integrations
settings page. It POSTs one signed sample to your endpoint so you can develop
against a live, verifiable delivery.

Test events are marked two ways — a top-level `"test": true` **and**
`X-Libli-Delivery: test`. **Verify the signature** (to prove your secret is
right) but **do not ingest** them as real grades. The numeric ids in the sample
below (`0`) are obvious placeholders, not real ids:

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

## For the platform admin

Configure the endpoint under **Manage → Settings → Integrations**: set the
**Endpoint URL** and a **Signing secret**, then enable result sync. Share the
same secret with the receiving developer so they can verify signatures. The
**Send test event** button fires against the **saved** URL and secret, so save
your settings before testing.

**Every student whose results are synced must have an `external_id`** — it is
the only student key in the payload, and results for a student without one
cannot be mapped by the receiver.
````

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest integrations/tests/test_guide_content.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/integrations/sis-webhook.md integrations/tests/test_guide_content.py
git commit -m "docs(integrations): SIS webhook receiver integration guide"
```

---

### Task 3: Public guide view, route, and template

**Files:**
- Create: `integrations/views.py`, `integrations/urls.py`, `templates/integrations/webhook_guide.html`
- Modify: `config/urls.py`
- Test: `integrations/tests/test_guide_view.py`

**Interfaces:**
- Consumes: `integrations.docs.render_markdown_doc` (Task 1); the guide file (Task 2).
- Produces: URL name `integrations:webhook_guide` at `GET /integrations/webhook/` (public, no login).

- [ ] **Step 1: Write the failing test**

```python
# integrations/tests/test_guide_view.py
from django.urls import reverse


def test_guide_is_public_and_renders(client):
    resp = client.get(reverse("integrations:webhook_guide"))
    assert resp.status_code == 200  # no login required
    body = resp.content.decode()
    assert "Verifying the signature" in body
    assert "<pre>" in body  # a rendered fenced code block
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest integrations/tests/test_guide_view.py -v`
Expected: FAIL — `NoReverseMatch: 'integrations'`.

- [ ] **Step 3: Create the view**

```python
# integrations/views.py
"""Public, no-login integration docs rendered from trusted repo markdown."""

from django.shortcuts import render

from integrations.docs import render_markdown_doc


def webhook_guide(request):
    html = render_markdown_doc("integrations/sis-webhook.md")
    return render(request, "integrations/webhook_guide.html", {"content": html})
```

- [ ] **Step 4: Create the urlconf**

```python
# integrations/urls.py
from django.urls import path

from integrations import views

app_name = "integrations"

urlpatterns = [
    # Included at the project root, so the pattern carries the full path.
    path("integrations/webhook/", views.webhook_guide, name="webhook_guide"),
]
```

- [ ] **Step 5: Wire it into the root urlconf**

In `config/urls.py`, add to `urlpatterns` (next to the other app includes):

```python
    path("", include("integrations.urls")),
```

- [ ] **Step 6: Create the template**

```html
{% extends "base.html" %}
{% load i18n %}
{% block head_title %}{% trans "SIS webhook integration guide" %} · libli{% endblock %}
{% block extra_css %}
<style>
  .doc-page { max-width: 52rem; margin: 0 auto; padding: 1rem 0 4rem; }
  .doc-page h2 { margin-top: 2.25rem; border-bottom: 1px solid var(--border-default);
    padding-bottom: .25rem; }
  .doc-page pre { background: var(--surface-2, rgba(127,127,127,.12));
    padding: 1rem; border-radius: .5rem; overflow-x: auto; }
  .doc-page code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
  .doc-page table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
  .doc-page th, .doc-page td { border: 1px solid var(--border-default);
    padding: .4rem .6rem; text-align: left; }
</style>
{% endblock %}
{% block content %}
<article class="doc-page">{{ content|safe }}</article>
{% endblock %}
```

- [ ] **Step 7: Run test to verify it passes**

Run: `uv run pytest integrations/tests/test_guide_view.py -v`
Expected: PASS.

- [ ] **Step 8: Verify the page visually (light + dark)**

Run the app and screenshot `/integrations/webhook/` in light and dark themes; confirm headings, tables, and code blocks are readable. (Per repo convention for styled views.)

- [ ] **Step 9: Commit**

```bash
git add integrations/views.py integrations/urls.py config/urls.py templates/integrations/webhook_guide.html integrations/tests/test_guide_view.py
git commit -m "feat(integrations): public SIS webhook guide page"
```

---

### Task 4: `send_test_event` sender

**Files:**
- Modify: `integrations/delivery.py`
- Test: `integrations/tests/test_test_fire_sender.py`

**Interfaces:**
- Consumes: `integrations.delivery.sign`, `_build_opener`, `TIMEOUT_SECONDS` (existing).
- Produces: `integrations.delivery.SAMPLE_PAYLOAD` (dict) and `integrations.delivery.send_test_event(endpoint) -> tuple[bool, int | None, str]` — `(ok, status, detail)`. Never raises; persists nothing.

- [ ] **Step 1: Write the failing tests**

```python
# integrations/tests/test_test_fire_sender.py
import json
import urllib.error
from unittest import mock

import pytest

from integrations import delivery
from integrations.models import WebhookDelivery
from integrations.models import WebhookEndpoint
from tests.factories import TEST_PASSWORD

pytestmark = pytest.mark.django_db


def _endpoint():
    ep = WebhookEndpoint.load()
    ep.enabled, ep.url, ep.secret = False, "https://r.example/hook", TEST_PASSWORD
    ep.save()
    return ep


def _ok_resp(status):
    resp = mock.MagicMock()
    resp.status = status
    resp.__enter__ = lambda s: resp
    resp.__exit__ = lambda *a: False
    return resp


def test_success_signs_marks_test_and_persists_nothing():
    ep = _endpoint()
    opener = mock.MagicMock()
    opener.open.return_value = _ok_resp(202)
    with mock.patch.object(delivery, "_build_opener", return_value=opener):
        ok, status, detail = delivery.send_test_event(ep)
    assert ok is True and status == 202
    sent = opener.open.call_args.args[0]
    body = sent.data
    assert sent.headers["X-libli-signature"] == delivery.sign(ep.secret, body)
    assert sent.headers["X-libli-delivery"] == "test"
    assert sent.headers["X-libli-event"] == "result_finalized"
    assert json.loads(body)["test"] is True
    assert WebhookDelivery.objects.count() == 0


def test_http_error_reports_code():
    ep = _endpoint()
    opener = mock.MagicMock()
    opener.open.side_effect = urllib.error.HTTPError(ep.url, 500, "err", None, None)
    with mock.patch.object(delivery, "_build_opener", return_value=opener):
        ok, status, detail = delivery.send_test_event(ep)
    assert ok is False and status == 500


def test_timeout_reports_none_status():
    ep = _endpoint()
    opener = mock.MagicMock()
    opener.open.side_effect = urllib.error.URLError("down")
    with mock.patch.object(delivery, "_build_opener", return_value=opener):
        ok, status, detail = delivery.send_test_event(ep)
    assert ok is False and status is None


def test_sample_payload_sentinels():
    p = delivery.SAMPLE_PAYLOAD
    assert p["test"] is True
    assert p["event"] == "result_finalized"
    assert p["student"]["external_id"] == "SAMPLE-STUDENT"
    assert p["group"]["id"] == 0 and p["unit"]["id"] == 0
    assert p["score"] == {"earned": "8.00", "max": "10.00", "percent": 80.0}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest integrations/tests/test_test_fire_sender.py -v`
Expected: FAIL — `AttributeError: module 'integrations.delivery' has no attribute 'send_test_event'`.

- [ ] **Step 3: Add the implementation**

Append to `integrations/delivery.py` (module already imports `json`, `urllib.error`, `urllib.request`):

```python
# Sample body for the "Send test event" button. Shape-identical to a real
# delivery, but marked "test": true (and X-Libli-Delivery: test) and using
# obvious placeholder ids so a receiver can verify the signature without
# ingesting it. finalized_at is a fixed literal (matches the guide's sample).
SAMPLE_PAYLOAD = {
    "test": True,
    "event": "result_finalized",
    "finalized_at": "2026-07-06T10:15:30.123456+00:00",
    "student": {
        "external_id": "SAMPLE-STUDENT",
        "email": "sample.student@example.edu",
        "name": "Sample Student",
    },
    "course": {
        "external_id": "SAMPLE-COURSE",
        "slug": "sample-course",
        "title": "Sample Course",
    },
    "group": {"id": 0, "external_id": "SAMPLE-GROUP", "name": "Sample Group"},
    "unit": {"id": 0, "title": "Sample Unit"},
    "score": {"earned": "8.00", "max": "10.00", "percent": 80.0},
}


def send_test_event(endpoint):
    """Synchronously POST one signed SAMPLE_PAYLOAD to the endpoint. Reuses
    sign()/_build_opener(), persists nothing, and never raises: returns
    (ok, status, detail) so the view always gets a tuple and never 500s."""
    body = json.dumps(SAMPLE_PAYLOAD).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310
        endpoint.url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Libli-Event": "result_finalized",
            "X-Libli-Delivery": "test",
            "X-Libli-Signature": sign(endpoint.secret, body),
        },
    )
    try:
        opener = _build_opener()
        with opener.open(req, timeout=TIMEOUT_SECONDS) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
        if 200 <= status < 300:
            return (True, status, "")
        # Defensive no-op: _build_opener() keeps HTTPErrorProcessor, so a non-2xx
        # normally raises HTTPError (caught below) before reaching here — mirrors
        # deliver_one's handling.
        return (False, status, f"HTTP {status}")
    except urllib.error.HTTPError as exc:
        return (False, exc.code, f"HTTP {exc.code}")
    except (TimeoutError, urllib.error.URLError) as exc:
        return (False, None, f"{type(exc).__name__}: {exc}")
    except Exception as exc:  # e.g. a malformed URL urllib rejects pre-flight
        return (False, None, f"{type(exc).__name__}: {exc}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest integrations/tests/test_test_fire_sender.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Lint**

Run: `uv run ruff check integrations/delivery.py`
Expected: no errors (the `# noqa: S310` covers the Request call).

- [ ] **Step 6: Commit**

```bash
git add integrations/delivery.py integrations/tests/test_test_fire_sender.py
git commit -m "feat(integrations): synchronous send_test_event for the settings tab"
```

---

### Task 5: Test-fire view, route, and `webhook_configured` context

**Files:**
- Modify: `institution/views_manage.py`, `institution/urls.py`
- Test: `integrations/tests/test_test_fire_view.py`

**Interfaces:**
- Consumes: `integrations.delivery.send_test_event` (Task 4); `WebhookEndpoint.load()`; `_index_url` (existing).
- Produces: URL name `institution:settings_integrations_test` at `POST /manage/settings/integrations/test/`; adds `webhook_configured: bool` to the settings context (consumed by Task 6).

- [ ] **Step 1: Write the failing tests**

```python
# integrations/tests/test_test_fire_view.py
from unittest import mock

import pytest
from django.urls import reverse

from integrations.models import WebhookEndpoint
from tests.factories import TEST_PASSWORD
from tests.factories import make_login
from tests.factories import make_pa

pytestmark = pytest.mark.django_db

URL = "institution:settings_integrations_test"


def _configure(enabled=False):
    ep = WebhookEndpoint.load()
    ep.enabled, ep.url, ep.secret = enabled, "https://r.example/hook", TEST_PASSWORD
    ep.save()


def test_pa_test_fire_success(client):
    make_pa(client, "pa")
    _configure(enabled=False)  # disabled but configured → must still send
    with mock.patch(
        "institution.views_manage.send_test_event", return_value=(True, 200, "")
    ) as m:
        resp = client.post(reverse(URL))
    assert resp.status_code == 302
    assert m.called  # enabled flag is NOT required to test


def test_unconfigured_does_not_send(client):
    make_pa(client, "pa")  # no endpoint saved → blank url/secret
    with mock.patch("institution.views_manage.send_test_event") as m:
        resp = client.post(reverse(URL))
    assert resp.status_code == 302
    assert not m.called


def test_non_pa_rejected(client):
    make_login(client, "joe")
    _configure()
    with mock.patch("institution.views_manage.send_test_event") as m:
        resp = client.post(reverse(URL))
    assert resp.status_code in (302, 403)
    assert not m.called


def test_get_redirects(client):
    make_pa(client, "pa")
    resp = client.get(reverse(URL))
    assert resp.status_code == 302
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest integrations/tests/test_test_fire_view.py -v`
Expected: FAIL — `NoReverseMatch` for `settings_integrations_test`.

- [ ] **Step 3: Add the imports and view**

In `institution/views_manage.py`, add near the other integrations imports:

```python
from integrations.delivery import send_test_event
```

Add this view (place it after `settings_integrations`):

```python
@login_required
@permission_required("institution.change_institution", raise_exception=True)
def settings_integrations_test(request):
    if request.method == "GET":
        return redirect(_index_url("integrations"))  # actions are POST targets
    endpoint = WebhookEndpoint.load()
    if not (endpoint.url and endpoint.secret):
        messages.error(
            request,
            _("Set an endpoint URL and signing secret before sending a test event."),
        )
        return redirect(_index_url("integrations"))
    ok, status, detail = send_test_event(endpoint)
    if ok:
        messages.success(
            request,
            _("Test event delivered — endpoint returned %(code)s.") % {"code": status},
        )
    else:
        messages.error(
            request, _("Test event failed: %(reason)s") % {"reason": detail}
        )
    return redirect(_index_url("integrations"))
```

- [ ] **Step 4: Add `webhook_configured` to the settings context**

In `_settings_context` (`institution/views_manage.py`), the returned dict currently
contains this four-line integrations entry:

```python
        "integrations": integrations
        or IntegrationsForm(
            instance=WebhookEndpoint.objects.filter(pk=1).first() or WebhookEndpoint()
        ),
```

Insert an `endpoint_ro` local immediately **above** the `return {` line, then reuse it
for both the form and the new boolean. The integrations entry becomes:

```python
    endpoint_ro = WebhookEndpoint.objects.filter(pk=1).first() or WebhookEndpoint()
    # ... inside the returned dict:
        "integrations": integrations or IntegrationsForm(instance=endpoint_ro),
        "webhook_configured": bool(endpoint_ro.url and endpoint_ro.secret),
```

Do **not** use `WebhookEndpoint.load()` here — its `get_or_create` would write a
pk=1 row on a plain GET of any settings tab.

- [ ] **Step 5: Add the route**

In `institution/urls.py`, add after the `settings_integrations` path:

```python
    path(
        "manage/settings/integrations/test/",
        views_manage.settings_integrations_test,
        name="settings_integrations_test",
    ),
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest integrations/tests/test_test_fire_view.py -v`
Expected: PASS (4 tests).

- [ ] **Step 7: Commit**

```bash
git add institution/views_manage.py institution/urls.py integrations/tests/test_test_fire_view.py
git commit -m "feat(institution): PA test-fire action + webhook_configured context"
```

---

### Task 6: Settings-tab UI — help block, guide link, Send-test form

**Files:**
- Modify: `templates/institution/manage/_integrations_tab.html`
- Test: `integrations/tests/test_tab_ui.py`

**Interfaces:**
- Consumes: `webhook_configured` (Task 5); URL names `integrations:webhook_guide`, `institution:settings_integrations_test`.

- [ ] **Step 1: Write the failing tests**

```python
# integrations/tests/test_tab_ui.py
import pytest
from django.urls import reverse

from integrations.models import WebhookEndpoint
from tests.factories import TEST_PASSWORD
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def _tab(client):
    return client.get(reverse("institution:settings") + "?tab=integrations")


def test_tab_shows_guide_link_and_test_form(client):
    make_pa(client, "pa")
    body = _tab(client).content.decode()
    assert reverse("integrations:webhook_guide") in body
    assert reverse("institution:settings_integrations_test") in body


def test_test_button_disabled_when_unconfigured(client):
    make_pa(client, "pa")  # nothing saved
    body = _tab(client).content.decode()
    assert "data-test-fire" in body
    i = body.index("data-test-fire")
    snippet = body[i - 120 : i + 120]
    assert "disabled" in snippet


def test_test_button_enabled_when_configured(client):
    make_pa(client, "pa")
    ep = WebhookEndpoint.load()
    ep.url, ep.secret = "https://r.example/h", TEST_PASSWORD
    ep.save()
    body = _tab(client).content.decode()
    # the test-fire button is present without a disabled attribute
    assert "data-test-fire" in body
    marker = 'data-test-fire'
    snippet = body[body.index(marker) - 120 : body.index(marker) + 20]
    assert "disabled" not in snippet
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest integrations/tests/test_tab_ui.py -v`
Expected: FAIL — assertions on missing markup.

- [ ] **Step 3: Edit the template**

In `templates/institution/manage/_integrations_tab.html`, insert this block
**between** the closing `</form>` of the settings form (line 26) and the
"Recent deliveries" `<div>` — it is a **sibling** of the settings form, never
nested inside it:

```html
<div class="settings__section">
  <h2 class="settings__section-title">{% trans "Receiver integration" %}</h2>
  <p class="settings__help">
    {% trans "Libli POSTs finalized results as JSON to your endpoint, signed with X-Libli-Signature (HMAC-SHA256) and headed by X-Libli-Event and X-Libli-Delivery. Your endpoint must return a 2xx status to acknowledge." %}
    <a href="{% url 'integrations:webhook_guide' %}" target="_blank" rel="noopener">{% trans "Read the full integration guide" %}</a>.
  </p>
  <p class="settings__help">
    {% trans "The test below fires against the saved URL and secret — save your settings first." %}
  </p>
  <form method="post" action="{% url 'institution:settings_integrations_test' %}">
    {% csrf_token %}
    <button class="btn" type="submit" data-test-fire
      {% if not webhook_configured %}disabled title="{% trans 'Set a URL and signing secret first' %}"{% endif %}>
      {% trans "Send test event" %}
    </button>
  </form>
</div>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest integrations/tests/test_tab_ui.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Verify the tab visually (light + dark)**

Screenshot `/manage/settings/?tab=integrations` as a PA in light and dark; confirm the help block, guide link, and Send-test button read cleanly and the button is visibly disabled when unconfigured.

- [ ] **Step 6: Commit**

```bash
git add templates/institution/manage/_integrations_tab.html integrations/tests/test_tab_ui.py
git commit -m "feat(institution): integrations tab help block + guide link + test-fire button"
```

---

### Task 7: i18n catalog + full-suite verification

**Files:**
- Modify: `locale/**/LC_MESSAGES/django.po` (regenerated)

**Interfaces:** none (verification task).

- [ ] **Step 1: Regenerate message catalogs**

Run: `uv run python manage.py makemessages -a`
Expected: the new `{% trans %}`/`gettext` strings from Tasks 3, 5–6 (the guide page title, test-fire messages, tab help, button labels) appear in `locale/*/LC_MESSAGES/django.po`. Review the diff; do not leave fuzzy (`#, fuzzy`) flags on the new entries, and confirm no obsolete `#~` lines were introduced.

- [ ] **Step 2: Compile catalogs**

Run: `uv run python manage.py compilemessages`
Expected: success, no errors.

- [ ] **Step 3: Run the i18n catalog tests**

Run: `uv run pytest -k "i18n or catalog or messages" -q`
Expected: PASS (guards against obsolete/duplicate catalog entries — the known trap when strings change).

- [ ] **Step 4: Run the full (non-e2e) suite**

Run: `uv run pytest -q`
Expected: PASS — the full suite green (~1800+ tests).

- [ ] **Step 5: Lint the whole change**

Run: `uv run ruff check .`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add locale
git commit -m "chore(i18n): message catalogs for SIS webhook guide + test-fire"
```

---

## Notes for the executor

- Task order matters: 1 → 2 → 3 (docs before the view that renders them); 4 → 5 → 6 (sender before the view before the template). Task 7 is last.
- The public guide route is reachable while logged out — the `test_guide_is_public_and_renders` test uses a bare `client` with no login, which is the point.
- Do not gate the test-fire on `endpoint.enabled` — only on a non-empty URL **and** secret. The `test_pa_test_fire_success` test configures a **disabled** endpoint on purpose.
- `send_test_event` must never raise — it always returns a tuple so the admin page never 500s.
