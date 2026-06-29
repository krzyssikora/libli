# Phase 5c — Branding & Platform-Settings Completion

*Brainstormed 2026-06-29. A focused slice carved out of the broad "Phase 5 —
Platform admin polish" roadmap bundle, scoped to the **branding & platform
settings** strand — surfacing and completing settings that already exist on the
`Institution` singleton but are only editable via Django admin (or not at all).*

## Context

Phase 5's goal is "a non-technical Platform Admin can fully run the institution
without Django admin." The strands shipped so far:

- **Cohort management** — Phase 3a (`/manage/cohorts/`)
- **Subjects management** — Phase 5a (`/manage/subjects/`)
- **User & Role management** — Phase 5b (`/manage/people/`, PR #56, merged)

Remaining strands:

- **5c — Branding & platform-settings completion** *(this slice)*
- 5d — SSO configuration UI (bespoke allauth `SocialApp` create/edit)
- 5e — First-run setup wizard + persistent dashboard checklist (capstone)

Today the branding/settings substrate **already exists** from Phase 0, but is
incompletely surfaced:

- The `Institution` singleton (`institution/models.py`) holds `name`, `logo`,
  `enabled_languages`, `default_language`, `default_theme`, `signup_policy`, and
  `allowed_email_domains`.
- `BrandColor` rows (key/value per institution) feed `--brand-primary` /
  `--brand-accent` into the design system via the `{% brand_vars %}` template tag
  (`core/templatetags/branding.py`) and the cached `get_site_config()`
  (`core/services.py`). Only **primary** and **accent** are wired through.
- A web settings page **already exists** at `/settings/institution/`
  (`core/views.py:institution_settings` + `institution/forms.py:InstitutionSettingsForm`),
  covering `name`, `logo`, `enabled_languages`, `default_language`,
  `default_theme`, `signup_policy`. It does **not** cover brand colours, the
  email-domain allowlist, or any upload limits.
- **Upload validation is hard-coded** in `courses/validators.py` /
  `courses/models.py:MediaAsset` (image: png/jpg/jpeg/gif/webp @ 5 MiB; video:
  mp4/webm/ogg/mov @ 200 MiB). There is no admin control over allowed file types
  or size caps.
- The **email-domain allowlist** (`Institution.allowed_email_domains`) is enforced
  only at SSO/JIT provisioning time (`accounts/provisioning.py:evaluate_sso_provisioning`),
  and there is no UI to edit it.

This slice closes those gaps on **one bespoke `/manage/settings/` surface** and
retires the old `/settings/institution/` page.

## Goals

1. A Platform Admin can edit **branding** — institution name, logo, and the
   **primary + accent** brand colours — from a bespoke UI, with a live preview,
   and see the change applied immediately.
2. A Platform Admin can edit **access policy** — signup policy and the
   **email-domain allowlist** — from the same surface.
3. A Platform Admin can control **uploads** — enable/disable file extensions
   within a fixed safe set, and adjust max image/video sizes — and those limits
   take effect for real media uploads.
4. When a PA invites an address whose domain is **outside** a configured
   allowlist, they see a **non-blocking warning** (the invite still succeeds).
5. The settings surface lives under the `/manage/` umbrella, consistent with
   People / Courses / Subjects, and the old `/settings/institution/` URL
   redirects to it.

## Non-goals (explicitly deferred)

- **A full palette editor.** Only `primary` and `accent` are editable — the two
  colours actually wired through the design system. Backgrounds, text, borders,
  and semantic colours stay token-driven (carefully tuned for light/dark
  contrast); exposing them risks unreadable themes and is a large design-system
  change.
- **Free-form / arbitrary upload extensions.** The admin can only **narrow**
  within a code-level safe set, never widen it. The hard-coded list remains a
  permanent security ceiling.
- **Blocking invites by domain.** A pending invitation already overrides the
  allowlist by design (`provisioning.py:33-34` — an explicit invite is the
  deliberate override path). 5c adds a *warning only*; it does not change
  enforcement semantics for invites or SSO.
- **New models.** Everything lands on the existing `Institution` singleton and
  the existing `BrandColor` rows.
- **Per-storage-backend / quota settings, virus scanning, EXIF stripping** — out
  of scope; uploads control is extensions + size caps only.
- SSO config UI (5d) and the first-run wizard (5e).

## Design decisions (from the brainstorm)

| Decision | Choice | Rationale |
|---|---|---|
| Slicing | One combined slice | All three parts are small and mostly surface existing fields; three specs/plans would be more ceremony than the work. Peel out uploads only if its modeling balloons during planning. |
| Location | `/manage/settings/`, tabbed; redirect old URL | Fixes the nav split (everything else admin is `/manage/`); reuses the 5b single-page/multi-tab pattern. |
| Palette scope | Primary + accent + logo only | The only colours wired through `{% brand_vars %}` today; safe from contrast regressions. |
| Upload control | Toggle within safe set + size caps | Real control without security risk; hard-coded list stays the ceiling. |
| Email domains | Editable + non-blocking invite warning | Keeps existing enforcement (invite overrides allowlist); a soft warning informs the PA without blocking a deliberate invite. |
| Form structure | Per-tab forms | Each tab saves independently; smaller, isolated, independently testable forms; matches `/manage/` per-action precedent. |

## Architecture & data model

**No new models.** New fields on the `Institution` singleton (one migration,
`AddField` with defaults that backfill the existing pk=1 row):

| Field | Type | Default | Constraint at use |
|---|---|---|---|
| `allowed_image_extensions` | `JSONField` (list) | full safe image set | effective set = stored ∩ `SAFE_IMAGE_EXTENSIONS` |
| `allowed_video_extensions` | `JSONField` (list) | full safe video set | effective set = stored ∩ `SAFE_VIDEO_EXTENSIONS` |
| `max_image_mib` | `PositiveIntegerField` | 5 | `1 ≤ n ≤ MAX_IMAGE_MIB_CEILING` |
| `max_video_mib` | `PositiveIntegerField` | 200 | `1 ≤ n ≤ MAX_VIDEO_MIB_CEILING` |

**Code constants (the safety ceiling).** `courses/validators.py` is refactored so
the current hard-coded lists/sizes become named module constants:

- `SAFE_IMAGE_EXTENSIONS = ("png", "jpg", "jpeg", "gif", "webp")`
- `SAFE_VIDEO_EXTENSIONS = ("mp4", "webm", "ogg", "mov")`
- `MAX_IMAGE_MIB_CEILING = 5`, `MAX_VIDEO_MIB_CEILING = 200`

The *effective* allowed extensions and size cap are computed at validation time as
`stored ∩ safe` and `min(stored_cap, ceiling)`. An admin can therefore only ever
narrow; a forged/garbage value in the JSON can never widen past the code set.

**Dynamic validation.** `MediaAsset.clean()` (`courses/models.py`) currently uses
module-level `FileExtensionValidator` + size-validator constants. These become
functions that read the effective set/cap from the **cached site config**
(`core/services.get_site_config()`), which already caches the institution row and
is invalidated on `Institution` save via the existing `core/apps.py` signal. So:
- the new upload fields are added to the `_build()` dict in `core/services.py`;
- `courses/validators.py` exposes `effective_image_extensions()`,
  `effective_video_extensions()`, `effective_max_image_bytes()`,
  `effective_max_video_bytes()` that read from the cached config and intersect
  with the ceilings;
- `MediaAsset.clean()` calls these at validation time.

**Brand colours** continue to live in `BrandColor` rows. The branding form does
`get_or_create(key="primary")` / `get_or_create(key="accent")` and updates
`value`. The existing cache-invalidation signal already covers `BrandColor` and
`Institution` saves, so colour and upload changes take effect on the next request
without extra wiring.

## The page — `/manage/settings/`

A new `institution/views_manage.py` (mirrors `courses/views_manage.py` /
`accounts/views_manage.py`). `institution/urls.py` is mounted in the project
URLconf so paths are `/manage/settings/...`. Every view is PA-gated with
`@login_required` + `@permission_required("institution.change_institution", raise_exception=True)`
(already part of `PLATFORM_ADMIN_PERMS` — no new grant).

One page, three tabs (tab pattern reused from 5b's People page). Each tab is its
own `<form>` posting to its own action view; a save on one tab leaves the others
untouched.

**Tab 1 — Branding** (`settings_branding`):
- institution `name` (existing)
- `logo` upload (existing, ≤ 2 MB)
- **primary** and **accent** colour controls — a native `<input type="color">`
  paired with a hex text field, plus a small live-preview swatch and a sample
  button so the PA sees the colour applied before saving.
- The general display settings `enabled_languages`, `default_language`,
  `default_theme` (existing) live here too, grouped under a "General" subsection,
  so the old `/settings/institution/` page is fully superseded.

**Tab 2 — Access** (`settings_access`):
- `signup_policy` (existing: invite / open)
- **email-domain allowlist** editor — a textarea (one domain per line) or chip
  list bound to `allowed_email_domains`.

**Tab 3 — Uploads** (`settings_uploads`):
- checkbox group to enable/disable each extension within `SAFE_IMAGE_EXTENSIONS`
  and `SAFE_VIDEO_EXTENSIONS`
- `max_image_mib` / `max_video_mib` number inputs (each bounded by its ceiling,
  with the ceiling shown as help text).

**Redirect & nav:** `/settings/institution/` → permanent-ish redirect to
`/manage/settings/`. The base-template nav link for Platform Admins is updated to
point under the `/manage/` group. (See the parked [nav admin-grouping TODO] —
collapsing PA-only links into one "Admin" dropdown is a separate future pass, not
this slice.)

## Forms & validation

Three focused forms in `institution/forms.py` (the existing
`InstitutionSettingsForm` is split into these and retired):

- **`BrandingForm`** — `name`, `logo`, `enabled_languages`, `default_language`,
  `default_theme`, plus `primary` / `accent` hex fields (not model fields on
  `Institution`; persisted to `BrandColor` rows in the view/form `save`).
  - Reuses existing clean rules: logo ≤ 2 MB; `enabled_languages` non-empty;
    `default_language` ∈ `enabled_languages`.
  - Colour fields validated with the existing `validate_css_color` /
    `is_valid_css_color`.
- **`AccessForm`** — `signup_policy`, `allowed_email_domains`.
  - Domains normalized on clean: lowercased, leading `@` and whitespace stripped,
    blanks dropped, de-duplicated (order-stable), each checked for a basic
    `label.tld` shape. Stored as a clean JSON list.
- **`UploadsForm`** — `allowed_image_extensions`, `allowed_video_extensions`,
  `max_image_mib`, `max_video_mib`.
  - Extension multi-selects offer **only** the safe-set members; clean enforces
    `chosen ⊆ safe`.
  - Size caps: integer, `1 ≤ n ≤ ceiling`; ceiling enforced server-side even if
    the input is tampered.

**Invite warning (5b touch).** In the `accounts` invitation-send view
(`accounts/views_manage.py`), after a successful invite, if
`allowed_email_domains` is non-empty and the invited address's domain is not in
it, attach a **non-blocking warning-level message** alongside the success
message (e.g. "Invitation sent. Note: `example.com` is not in your allowed email
domains."). The invite is still created and sent. No change to
`evaluate_sso_provisioning` or to enforcement.

## Styling & i18n

- New `settings.css` (per-page `<link>`), tabbed layout reusing the 5b tab
  pattern and the shared `.btn` / `.badge` / form-input tokens.
- Verify light/dark + mobile via throwaway Playwright screenshots
  (delete-after-review), per the project's "verify UI with screenshots" rule.
  Watch the dark-mode form-input border token (`--border-strong`) so colour/text
  fields aren't invisible on dark cards.
- All new strings marked translatable EN + PL; `.mo` compiled. Watch the
  makemessages **fuzzy-flag** gotcha (clear stale fuzzy flags; verify new msgids
  by grep, especially auto-mis-guessed translations).
- Module-level translatable label dicts (e.g. extension labels) MUST use
  `gettext_lazy`, never eager `gettext` (eager freezes labels to the activation
  language — a shipped-3× footgun).

## Testing

**Unit:**
- `effective_image_extensions()` / `effective_video_extensions()` — narrowing
  works; a stored value outside the safe set is intersected away; empty stored ⇒
  empty effective (nothing allowed) vs default ⇒ full safe set (decide & assert).
- `effective_max_*_bytes()` — respects ceiling even when stored cap is larger;
  honors a smaller stored cap.
- `MediaAsset.clean()` rejects an extension the admin disabled; rejects a file
  over the admin's (narrowed) size cap; accepts one within limits.
- `AccessForm` domain normalization (case, `@`/whitespace stripping, dedupe,
  shape rejection).
- `BrandingForm` colour persistence via `get_or_create` on `BrandColor`;
  invalid hex rejected.
- `UploadsForm` rejects an out-of-safe-set extension and an over-ceiling cap.

**Integration / views:**
- Each tab view saves independently (POST to one leaves the others' fields
  unchanged).
- Non-PA gets 403 on every settings view; PA gets 200.
- `/settings/institution/` redirects to `/manage/settings/`.
- Cache invalidation: after saving a colour, the next request's
  `get_site_config()` / `{% brand_vars %}` reflects it; after narrowing uploads,
  `MediaAsset` validation reflects it.

**e2e (mirrors `tests/test_e2e_subjects.py`):**
- PA changes the primary brand colour and the rendered `--brand-primary` updates.
- PA disables an image extension; uploading that type in the media manager is
  rejected with the expected message.
- PA sets an allowlist, then invites an out-of-domain address and sees the
  non-blocking warning.

Tests use the standard PA helper (`seed_roles()` + `make_verified_user` + add
`PLATFORM_ADMIN` group + clear perm caches + `force_login`) and
`tests.factories.TEST_PASSWORD` — never a hardcoded password literal (GitGuardian
CI).

## Open checks to confirm during planning (not blockers)

- Lift the exact safe-set extensions and ceilings **verbatim** from today's
  `courses/validators.py` so defaults match current behavior byte-for-byte.
- Decide the **empty-list semantics** for the extension fields: does an empty
  `allowed_image_extensions` mean "none allowed" or "fall back to full safe set"?
  Recommendation: treat the default as the full safe set and require ≥ 1 enabled
  extension per kind in `UploadsForm.clean` (so a PA can't accidentally disable
  all image uploads); assert this in tests.
- Confirm whether `enabled_languages` / `default_language` / `default_theme` read
  best under "Branding › General" or warrant a small fourth "General" tab —
  cosmetic, decide at build.

## Affected files (anticipated)

- `institution/models.py` — 4 new `Institution` fields + migration.
- `institution/forms.py` — `BrandingForm`, `AccessForm`, `UploadsForm`; retire
  `InstitutionSettingsForm`.
- `institution/views_manage.py` *(new)*, `institution/urls.py` *(new mount under
  `/manage/settings/`)*, project URLconf.
- `courses/validators.py` — safe-set constants + `effective_*` readers.
- `courses/models.py` — `MediaAsset.clean()` uses dynamic validators.
- `core/services.py` — `_build()` includes the new upload fields.
- `core/views.py` / `core/urls.py` — retire/redirect old `institution_settings`.
- `accounts/views_manage.py` — invite-domain non-blocking warning.
- `templates/institution/settings*.html` *(new)*, `templates/base.html` (nav
  link), `static/.../settings.css` *(new)*.
- `locale/**` — EN/PL messages + compiled `.mo`.
- Tests across `tests/` + an e2e harness.
