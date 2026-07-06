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

Configure the endpoint under **Admin → Institution settings → Integrations**: set the
**Endpoint URL** and a **Signing secret**, then enable result sync. Share the
same secret with the receiving developer so they can verify signatures. The
**Send test event** button fires against the **saved** URL and secret, so save
your settings before testing.

**Every student whose results are synced must have an `external_id`** — it is
the only student key in the payload, and results for a student without one
cannot be mapped by the receiver.
