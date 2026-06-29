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
- **Fully disabling a media kind** (zero allowed image *or* video extensions) —
  the `≥ 1 enabled per kind` rule deliberately prevents it; a dedicated per-kind
  on/off toggle is a possible later follow-up, not this slice.
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

All four fields use **module-level callable defaults** (e.g.
`default_image_extensions()` / `default_video_extensions()` returning the safe
set as a fresh list), mirroring the existing `default_languages` precedent in
`institution/models.py`. A literal list/tuple default on a `JSONField` is a
shared-mutable, non-migration-serializable default and MUST NOT be used.

**Code constants (the safety ceiling).** `courses/validators.py` is refactored so
the current hard-coded lists/sizes become named module constants:

- `SAFE_IMAGE_EXTENSIONS = ("png", "jpg", "jpeg", "gif", "webp")`
- `SAFE_VIDEO_EXTENSIONS = ("mp4", "webm", "ogg", "mov")`
- `MAX_IMAGE_MIB_CEILING = 5`, `MAX_VIDEO_MIB_CEILING = 200`

The *effective* allowed extensions and size cap are computed at validation time as
`stored ∩ safe` and `min(stored_cap, ceiling)`. An admin can therefore only ever
narrow; a forged/garbage value in the JSON can never widen past the code set.

**Empty-list semantics (pinned — not an open question).** `effective_*_extensions()`
returns `stored ∩ safe` *literally*, so a stored empty list yields an **empty**
effective set — **fail-closed** (nothing of that kind uploads). The migration
default is the full safe set (via the callable above), and `UploadsForm.clean`
requires **≥ 1 enabled extension per kind**, so a PA cannot reach the empty state
through the UI. The fail-closed branch exists only to guard forged/garbage stored
values. (Fully disabling a media kind from the UI is intentionally unsupported —
see Non-goals.)

**Dynamic validation.** `MediaAsset.clean()` (`courses/models.py`) currently
iterates the class-level `IMAGE_VALIDATORS` / `VIDEO_VALIDATORS` lists
(`FileExtensionValidator` + the `validate_image_size` / `validate_video_size`
size validators). These become functions that read the effective set/cap from the
**cached site config** (`core/services.get_site_config()`), which already caches
the institution row and is invalidated on `Institution` save via the existing
`core/apps.py` signal. So:
- the new upload fields are added to **both** `_DEFAULTS` **and** the `_build()`
  dict in `core/services.py` (so the institution-absent path — `_build()` returns
  `dict(_DEFAULTS)` when no `Institution` row exists — still carries the upload
  keys); additionally every `effective_*()` reader uses `cfg.get(key, <safe
  default>)` so a missing key can never `KeyError` and falls back to the full safe
  set / ceiling;
- `courses/validators.py` exposes `effective_image_extensions()`,
  `effective_video_extensions()`, `effective_max_image_bytes()`,
  `effective_max_video_bytes()` that read from the cached config and intersect
  with the ceilings;
- the extension check is performed by a Django `FileExtensionValidator(
  allowed_extensions=<effective set>)` **constructed at validation time** — not a
  hand-rolled membership test — so suffix extraction, case-folding (`.PNG`),
  multi-dot names (`clip.tar.gz`), and the raised message/`code` all match today's
  behavior exactly (avoiding silent accept/reject drift);
- the dynamic size readers **retain the existing `getattr(file, "_committed",
  False)` short-circuit** (today's `validate_image_size` / `validate_video_size`
  skip already-committed `FieldFile`s to avoid `FileNotFoundError` on storage
  reads); a regression test covers a committed file;
- the size-cap error message **interpolates the effective cap** (not a hard-coded
  "max 5 MiB"), so it reports the real, possibly-narrowed limit;
- `MediaAsset.clean()` calls these at validation time.

`courses/validators.py` is imported at model-load time (it backs `MediaAsset`), so
`get_site_config()` MUST be imported **inside** the `effective_*()` function bodies
(function-scope), never at the validators module top level — a top-level
`from core.services import …` risks an import cycle (`core` ↔ `courses`).

**Brand colours** continue to live in `BrandColor` rows. The branding form does
`get_or_create(institution=inst, key="primary")` /
`get_or_create(institution=inst, key="accent")` and updates `value` — the
institution scope is included (not `key`-only) to match the per-institution model,
even under the singleton. The existing cache-invalidation signal already covers `BrandColor` and
`Institution` saves, so colour and upload changes take effect on the next request
without extra wiring.

## The page — `/manage/settings/`

A new `institution/views_manage.py` (mirrors `courses/views_manage.py` /
`accounts/views_manage.py`). `institution/urls.py` is mounted in the project
URLconf so paths are `/manage/settings/...`. Every view is PA-gated with
`@login_required` + `@permission_required("institution.change_institution", raise_exception=True)`
(already part of `PLATFORM_ADMIN_PERMS` — no new grant).

One page, three tabs (tab pattern reused from 5b's People page). A single
**index/GET view** (`settings`) renders the full page — all three tabs, each with
its own **unbound** form populated from the current `Institution` instance /
`initial` (unbound, so first paint never shows validation errors) — and is the
canonical `/manage/settings/` URL. Each tab is its own `<form>` POSTing to its own action
view (`settings_branding` / `settings_access` / `settings_uploads`); a save on one
tab leaves the others untouched.

**POST flow & error handling.** Active-tab transport is the **`?tab=` query
parameter** (server-readable and testable; the canonical mechanism — not a
`#anchor`). On a **valid** POST, the action view saves and redirects (PRG) back to
the index with the relevant tab active (e.g. `/manage/settings/?tab=uploads`). On
an **invalid** POST, the action view re-renders the **full index page** with the
invalid form carrying its errors and the other two tabs showing their current (DB)
values, with the errored tab active. The index template reads `?tab=` (default:
`branding`) to set the initial visible tab.

**HTTP methods.** The index view is **GET-only**; each action view is
**POST-only** (a GET to an action URL redirects to the index with its `?tab=`).
A test asserts the method contract.

**Shared context.** The three-form context (one bound-or-errored form + the other
two seeded from current state, including the colour seed from `BrandColor`) is
assembled by **one shared helper** (e.g. `_settings_context(active_tab,
override_form=None)`) that the index view and all three action-view error branches
call — so the assembly lives in a single place and the tabs can't drift across the
four render paths.

**Logo on re-render.** A file input can't be repopulated: if a Branding POST fails
validation on another field, the previously chosen `logo` file is **not** retained
(the PA must re-select it), and the existing `logo` on the instance is left
untouched unless a new valid file is submitted. This is standard Django behavior,
noted so it isn't mistaken for a bug in testing.

**Tab 1 — Branding** (`settings_branding`):
- institution `name` (existing)
- `logo` upload (existing, ≤ 2 MB)
- **primary** and **accent** colour controls — a native `<input type="color">`
  paired with a hex text field, plus a small live-preview swatch and a sample
  button so the PA sees the colour applied before saving. These two fields are
  constrained to **6-digit `#rrggbb` hex** (the only form `<input type="color">`
  emits and can display), so the picker and text field always stay in sync; the
  broader `validate_css_color` formats (`#rgb`, `rgb()/rgba()/hsl()`) are not
  offered here even though the underlying `BrandColor.value` could store them.
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
  with the ceiling shown as help text). Because each ceiling equals today's hard
  limit (5 / 200 MiB), size control is **lower-only by design** — a PA can shrink
  the limit below the current cap but never raise it above the code ceiling. (If
  raising limits is ever wanted, the ceiling constant must be raised in code
  first; out of scope here.)

**Redirect & nav:** `/settings/institution/` → **302** redirect to
`/manage/settings/` (302, not 301 — a 301 is aggressively browser-cached and hard
to undo if the path is ever reused). The redirect test asserts the 302 status.
**Keep the `core:institution_settings` URL *name* bound** (to a `RedirectView` /
redirect view at the old path) rather than deleting it, so existing
`{% url 'core:institution_settings' %}` / `reverse()` references stay valid and
don't raise `NoReverseMatch`. At least `templates/core/home.html` (the PA
shortcut) and `templates/base.html` reverse it today — **grep the whole repo
(templates + Python, not just tests) for `institution_settings` and
`settings/institution` and repoint every nav-facing reference** to the new page;
the redirect view is the safety net for any missed one. The base-template nav link
for Platform Admins is updated to point under the `/manage/` group. (See the parked [nav admin-grouping TODO] —
collapsing PA-only links into one "Admin" dropdown is a separate future pass, not
this slice.)

## Forms & validation

Three focused forms in `institution/forms.py` (the existing
`InstitutionSettingsForm` is split into these and retired):

- **`BrandingForm`** — `name`, `logo`, `enabled_languages`, `default_language`,
  `default_theme`, plus `primary` / `accent` hex fields (not model fields on
  `Institution`; persisted to `BrandColor` rows in the view/form `save`).
  - On GET, the `primary` / `accent` fields are **seeded from the current
    `BrandColor` rows** (falling back to the `_DEFAULTS` brand colours when a row
    is absent) so they never render blank.
  - **Non-6-digit stored values:** a `BrandColor.value` may already hold a
    non-`#rrggbb` form (e.g. `#fff` or `rgb(...)`) set via Django admin. On seed,
    normalize it to 6-digit hex — expand `#rgb`→`#rrggbb`; for a value that can't
    be coerced to hex (`rgb()/hsl()`), seed the `_DEFAULTS` hex instead — so the
    field never starts in a state that rejects an unrelated save and soft-bricks
    the whole Branding tab. Unit test: an existing `#fff` row seeds, and saving
    (even just `name`) still succeeds.
  - Reuses existing clean rules: logo ≤ 2 MB; `enabled_languages` non-empty;
    `default_language` ∈ `enabled_languages`.
  - Colour fields validated against **6-digit `#rrggbb` hex** (a stricter subset
    of `validate_css_color`, matching the `<input type="color">` constraint).
  - **Widget/source-of-truth:** each colour is **one** `CharField` (the hex text
    field) that is the actual bound form field; the `<input type="color">` picker
    is a JS-mirrored sibling that writes into that text field (and vice-versa).
    Only the text field is submitted/validated — there are not two competing
    fields per colour.
- **`AccessForm`** — `signup_policy`, `allowed_email_domains`.
  - **Widget:** `allowed_email_domains` is a model `JSONField`; the form must
    **override** its default `forms.JSONField`/`Textarea` (which would demand
    literal JSON like `["a.com"]`) with a custom `CharField` + `Textarea` (one
    domain per line, or a chip widget) whose `clean()` splits lines and returns a
    plain list — exactly mirroring the `UploadsForm` extension-widget pin.
  - Domains normalized on clean: lowercased, leading `@` and whitespace stripped,
    blanks dropped, de-duplicated (order-stable). Each entry is validated as a
    **full host of one-or-more dot-separated labels + TLD** — i.e. subdomains like
    `mail.example.com` are accepted, because enforcement compares against the full
    host `provisioning.email_domain()` returns (`mail.example.com` for
    `a@mail.example.com`); a two-label-only rule would make subdomained hosts
    unmatchable. Stored as a clean JSON list.
- **`UploadsForm`** — `allowed_image_extensions`, `allowed_video_extensions`,
  `max_image_mib`, `max_video_mib`.
  - **Widget:** the two extension fields are `forms.MultipleChoiceField` with
    `widget=CheckboxSelectMultiple` and `choices` = the safe set (NOT the
    `JSONField`'s default `Textarea`); `clean` returns a plain list and enforces
    `chosen ⊆ safe` **and** `len(chosen) ≥ 1` per kind.
  - Size caps: integer, `1 ≤ n ≤ ceiling`; ceiling enforced server-side even if
    the input is tampered.

**Invite warning (5b touch).** In the `accounts` invitation-send view
(`accounts/views_manage.py`), after a successful invite, the view reads the
allowlist from `Institution.load().allowed_email_domains` (the field is **not**
in `get_site_config()`, so don't read it from the cached config). It computes the
invited domain with `provisioning.email_domain(email)` and compares against the
**same normalized form** the enforcement path uses (each stored entry lowercased,
whitespace- and leading-`@`-stripped — exactly the set comprehension in
`evaluate_sso_provisioning`). If the allowlist is non-empty and the invited domain
is not in it, attach a **non-blocking warning-level message** alongside the
success message (e.g. "Invitation sent. Note: example.com is not in your allowed
email domains." — plain text, no backticks; Django messages render verbatim). The invite is still created and sent. No change to
`evaluate_sso_provisioning` or to enforcement. (Factor the normalization so the
warning and the SSO gate cannot drift.)

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
  works; a stored value outside the safe set is intersected away; **a stored empty
  list ⇒ empty effective (fail-closed)**; the migration default ⇒ full safe set;
  a missing config key (institution-absent path) ⇒ full safe set, no `KeyError`.
- `effective_max_*_bytes()` — respects ceiling even when stored cap is larger;
  honors a smaller stored cap.
- `MediaAsset.clean()` rejects an extension the admin disabled; rejects a file
  over the admin's (narrowed) size cap; accepts one within limits. **These
  size/extension-rejection tests must use a fresh (uncommitted) file** — an
  already-committed `FieldFile` is skipped by the `_committed` short-circuit and
  would pass vacuously. The `_committed` regression test asserts the complementary
  *skip* path, so the two don't accidentally exercise the same branch.
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

**Existing-test migration (required for a green DoD).** Retiring
`InstitutionSettingsForm` / `institution_settings` and redirecting
`/settings/institution/` breaks live tests that reference them —
`tests/test_settings_forms.py`, `tests/test_e2e_settings.py`,
`tests/test_settings_styles.py`, `tests/test_surfaces.py`, `tests/test_i18n_ws4.py`.
A dedicated task must re-point these at `/manage/settings/` + the three new forms
(or delete the genuinely obsolete cases). The plan must not declare "full suite
green" without accounting for them. (Grep for `institution_settings`,
`InstitutionSettingsForm`, and `settings/institution` to find the full set before
building — the list above is from a round-1 review, not an exhaustive grep.)

Tests use the standard PA helper (`seed_roles()` + `make_verified_user` + add
`PLATFORM_ADMIN` group + clear perm caches + `force_login`) and
`tests.factories.TEST_PASSWORD` — never a hardcoded password literal (GitGuardian
CI).

## Open checks to confirm during planning (not blockers)

- Lift the exact safe-set extensions and ceilings **verbatim** from today's
  `courses/validators.py` so defaults match current behavior byte-for-byte.
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
- `core/views.py` / `core/urls.py` — redirect view at old path; keep
  `core:institution_settings` URL name bound (no `NoReverseMatch`).
- `core/services.py` — add upload keys to `_DEFAULTS` (alongside `_build()`).
- `templates/core/home.html` — PA shortcut reverses `core:institution_settings`;
  repoint to the new page (grep templates + Python for all references).
- `accounts/views_manage.py` — invite-domain non-blocking warning.
- **Existing tests to migrate/retire:** `tests/test_settings_forms.py`,
  `tests/test_e2e_settings.py`, `tests/test_settings_styles.py`,
  `tests/test_surfaces.py`, `tests/test_i18n_ws4.py` (re-point at
  `/manage/settings/`; grep first for the complete set).
- `templates/institution/settings*.html` *(new)*, `templates/base.html` (nav
  link), `static/.../settings.css` *(new)*.
- `locale/**` — EN/PL messages + compiled `.mo`.
- Tests across `tests/` + an e2e harness.
