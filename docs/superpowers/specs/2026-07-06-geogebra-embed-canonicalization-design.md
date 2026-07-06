# GeoGebra embed canonicalization — design

**Date:** 2026-07-06
**Status:** Approved (ready for implementation planning)

## Problem

Authors add GeoGebra worksheets via the **Embed / iframe element** (field
labelled "URL or embed code"), whose parser is `courses/embed.py :: extract_embed_url`.
That parser extracts a single `<iframe>` `src` (or accepts a plain URL) and
validates it against the embed allow-list — but it does **no provider
canonicalization**. GeoGebra publishes a material under several URL shapes, and
only one of them renders *just the worksheet*:

| Input (what an author pastes) | Current result | Problem |
|---|---|---|
| `https://www.geogebra.org/m/egZJdjsC` (share short link) | passes through unchanged | renders the **full GeoGebra page** (title, chrome, related), not the worksheet |
| `https://www.geogebra.org/material/show/id/egZJdjsC` (classic share) | passes through unchanged | renders the full page |
| full `<iframe … src="…/material/iframe/id/egZJdjsC/width/1600/height/763/border/…">` | `src` extracted, keeps all `/width/1600/height/763/…` cruft | works, but not the clean canonical form |
| `https://www.geogebra.org/material/iframe/id/egZJdjsC` (minimal) | passes through unchanged | already correct — this is the target shape |

All four are currently *accepted* (`geogebra.org` is on the allow-list), so the
report that "the full embed is not accepted" was a misread — the real defect is
that the sharing forms are not rewritten to the worksheet-only URL.

The user-confirmed URL that shows **only the worksheet** is:

```
https://www.geogebra.org/material/iframe/id/<ID>
```

The consumption template (`templates/courses/elements/iframeelement.html`) wraps
the iframe in a responsive `.embed-16x9` container with **no width/height on the
`<iframe>`** — libli controls sizing via CSS — so stripping the URL's
`/width/…/height/…` tail is safe and correct.

## Goals

1. Canonicalize **every** GeoGebra input form (share link, classic share, full
   embed `<iframe>`, minimal URL) to `https://www.geogebra.org/material/iframe/id/<ID>`.
2. Confirm that pasting a full `<iframe>` for *other* embed providers already
   works (it does) and keep it working — canonicalization is an additive,
   GeoGebra-only post-extraction step.

## Non-goals

- No change to the **Video element** or `courses/video_url.py`. GeoGebra is
  routed through the Embed/iframe element (confirmed with the user).
- No canonicalization of GeoGebra *app* links (`/classic/…`, `/graphing/…`,
  `/calculator/…`, `/geometry/…`) — their trailing segment is not reliably a
  material ID. They pass through unchanged.
- No new provider beyond GeoGebra (the code is structured so one could be added
  later, but none is built now).

## Approach

A small, dedicated GeoGebra canonicalizer that slots into the existing embed
pipeline, mirroring the `video_url.py` precedent: recognize the provider →
extract the ID → **rebuild the URL from scratch**, dropping all cruft.

New pure function `canonicalize_embed_url(url)` in a new module
`courses/geogebra.py`. It rewrites recognized GeoGebra material URLs and passes
everything else through untouched. It is wired into `extract_embed_url` on each
success path (the plain-URL and iframe-`src` branches), just before the
allow-list gate.

Rejected alternatives:
- **Unify the video + embed parsers into one shared pipeline** — more consistent
  long-term but touches the video element unnecessarily; bigger blast radius,
  higher risk. (YAGNI.)
- **Inline regex special-case inside `extract_embed_url`** — buries provider
  logic in the dispatcher and is harder to test in isolation.

## Canonicalization rules

**Input parsing:** the URL is split with `urlsplit`; the host is `hostname`
(lowercased, port/userinfo stripped). Only inputs already using the `https`
scheme are canonicalized — a non-`https` GeoGebra input (`http://…`, or a
scheme-relative `//…` iframe `src`) is **not** recognized and passes through
unchanged, so `validate_embed_url` still rejects it. This keeps the
no-regression promise: canonicalization never upgrades a scheme that would
otherwise be rejected.

**Host recognition:** the host equals exactly `geogebra.org` or
`www.geogebra.org`. Other `*.geogebra.org` subdomains are **not** recognized —
they pass through unchanged (the allow-list still governs their acceptance),
because we cannot assume a subdomain serves the same worksheet from the `www`
material namespace we rewrite to.

**ID extraction** from the path segments (leading empty segment dropped):

| Path shape | ID source |
|---|---|
| `/m/<ID>` | segment immediately after `m` |
| `/material/iframe/id/<ID>/width/…/height/…` | segment immediately after the first `id` (rest dropped) |
| `/material/show/id/<ID>` | segment immediately after the first `id` |
| `/material/iframe/id/<ID>` | segment immediately after the first `id` (idempotent) |

Implementation note: the two families reduce to two ordered checks — (a) the
**first** path segment **equals** `m` → take the next segment; else (b) `id`
appears in the segments → take the segment immediately following the first `id`.
Check (a) is tried first; a `/material/...` path (first segment `material`, not
`m`) only matches (b). Query string and fragment are ignored.

**ID validation:** the extracted candidate must match `^[A-Za-z0-9]+$`. When
`m` or `id` is the final path segment with nothing after it, the candidate is
empty, fails this check, and the input is returned unchanged.

**Output:** always `https://www.geogebra.org/material/iframe/id/<ID>` (always
`https`, always the `www` host, always the `material/iframe` endpoint).

**Not recognized → return the input URL unchanged.** This covers: non-GeoGebra
hosts, GeoGebra app links, and a GeoGebra material URL whose ID is absent or
malformed. This is the safe, no-regression choice — the allow-list still governs
acceptance, and the worst case is exactly today's behavior. (Chosen over raising
a friendly "no material ID" error, to avoid falsely rejecting GeoGebra URLs we
don't recognize.)

`canonicalize_embed_url` **never raises** — validation stays entirely in
`validate_embed_url`.

## Pipeline wiring

In `courses/embed.py :: extract_embed_url`, both branches run the resolved URL
through `canonicalize_embed_url()` **before** `validate_embed_url()`:

- Plain-URL branch: `url = canonicalize_embed_url(text)` → `validate_embed_url(url)` → return `url`.
- Iframe-`src` branch: after extracting `src`, `url = canonicalize_embed_url(src)` → `validate_embed_url(url)` → return `url`.

The existing first-match-wins error precedence (malformed-parse → multi-iframe →
no-iframe → missing-src → non-whitelisted-domain) is unchanged; canonicalization
is inserted only on the success path, just before the allow-list gate.

## Shared call site: course import

`extract_embed_url` is not authoring-only — it is also the iframe canonicalizer
for the course import/transfer path (`courses/transfer/payloads.py :: _val_iframe`,
via `_canonical_embed(data["url"], elid, extract_embed_url)`). Adding
canonicalization therefore also normalizes iframe URLs **on course import**. This
is intended and benign: it is the same GeoGebra normalization, idempotent for
already-canonical URLs.

Consequences to record:

- `tests/test_transfer_validation.py :: test_iframe_happy_path_canonicalizes_via_both_validate_calls`
  asserts `https://www.geogebra.org/m/abc` is stored **unchanged** on import; it
  must be updated to expect `https://www.geogebra.org/material/iframe/id/abc`.
- The export→import round-trip test in `tests/test_transfer_import.py` uses
  `https://www.geogebra.org/embed/abc`, which is **not** a recognized form (no
  `/m/` prefix, no `id` segment), so it passes through unchanged and the
  round-trip is unaffected.

## Testing

TDD throughout. New `tests/test_geogebra.py` unit tests for
`canonicalize_embed_url`:

- each input form (`/m/<ID>`, `/material/show/id/<ID>`, full embed with
  `/width/…/height/…` tail, minimal `/material/iframe/id/<ID>`) → canonical URL;
- idempotency (canonical URL in → same URL out);
- `*.geogebra.org` subdomain (e.g. `beta.geogebra.org/m/<ID>`) NOT recognized →
  passes through unchanged;
- a non-`https` GeoGebra input (`http://…/m/<ID>`) NOT recognized → passes
  through unchanged;
- non-GeoGebra host passed through unchanged;
- GeoGebra app link (`/classic/…`) passed through unchanged;
- GeoGebra host with no extractable / malformed ID passed through unchanged.

Plus end-to-end coverage via `extract_embed_url` and `IframeElementForm` (paste
`/m/<ID>` and a full embed `<iframe>` → stored URL is the canonical worksheet
form).

**Existing tests whose expectations change intentionally (not regressions):**

- `test_plain_https_whitelisted_url_passes_through` (`tests/test_embed.py`):
  `https://www.geogebra.org/m/abc` now canonicalizes to
  `https://www.geogebra.org/material/iframe/id/abc`. The name no longer describes
  the behavior — rename it (e.g. `test_geogebra_share_url_is_canonicalized`)
  alongside the expectation change.
- `test_valid_snippet_extracts_src` (`tests/test_embed.py`): the
  `.../id/abc123/width/800/height/600` fixture now yields `.../id/abc123`.
- `test_iframe_form_stores_only_src` (`tests/test_embed.py`): same fixture →
  stored URL is `.../id/abc123`.
- `test_iframe_happy_path_canonicalizes_via_both_validate_calls`
  (`tests/test_transfer_validation.py`): the imported `/m/abc` URL now becomes
  `.../material/iframe/id/abc` (see "Shared call site: course import" above).

`test_wrapper_div_with_single_iframe_is_valid` still passes (asserts only the
`geogebra.org` prefix).
