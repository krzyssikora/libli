# School-facing page and editable pricing — design

**Date:** 2026-09-06
**Status:** approved in brainstorming, not yet planned
**Supersedes:** the "school-facing page" section of the B1 backups/restore notes, which
settled the content but not the mechanism.

## Why now

B1 is done: libli.pl backs up nightly, encrypted, with a pinned host key, and a restore has
been rehearsed twice against real data. That is what makes the page's central claim
truthful, and it was the blocker. A school is expected within weeks.

Two defects in what ships today:

1. `docs/public/getting-started.md` opens *"libli is a learning platform a school runs for
   itself"*, and `docs/public/getting-started.pl.md` opens with the exact Polish equivalent
   ("libli to platforma edukacyjna, którą szkoła prowadzi u siebie"). That premise is false
   under the hosting model — Krzysztof hosts, one box per school. **Both files** are live and
   anonymous and both must be rewritten.
2. There is no page that tells a school what libli costs.

## Scope

**In:** a new `/for-schools/` public page; a `PricingPlan` model and a Pricing settings tab;
**three block tokens and no new inline token** (see the Tokens section); a trimmed `/getting-started/`; EN + PL for both.

**Out:** self-service signup, online payment, invoicing, contracts, a currency converter,
per-school usage metering, and the annual school statement (planned vs actual). The
allowance is advisory and reconciled at renewal by hand, as already decided.

## Decisions taken in brainstorming

### Pricing is a few plans, not a calculator

Rejected: a calculator taking the five contract numbers and returning a zloty figure.
It asserts the price is *derivable* from those inputs, but support load — the real variable
cost — is not mechanically derivable from them, so a returned figure reads as a quote the
school will hold us to. It would also put the coefficients in public client-side JS on an
anonymous page.

Rejected: a single "from X" headline. It is the shape that generates the most quote
conversations, because a school cannot tell which end of the range it sits at — and that
spends the one resource established as scarce, Krzysztof's time. Plans do the qualifying
before he is involved.

### Plans key on pupils and bound the cost drivers separately

Pupils drive no cost but are what a school understands and can verify from its own roll.
Creators and courses drive support load, which is the actual cost. So: **price on the pupil
band, and state explicit bounds on support hours, courses and video** in each plan.

**The five contract numbers**, agreed at signup and named on the page (they are recorded
here because this spec supersedes the note that held them):

1. pupil band
2. courses planned
3. videos per course
4. typical video length
5. number of people authoring content

⚠️ Qualitative bands ("video-heavy") are **not contractible** — a school will rightly argue
that 100 videos across 500 units is not heavy. **Teachers are deliberately not an input**:
an input implies a price, and we do not want to price teachers.

### The numbers are not decided here

Every figure is an editable field, set in the Pricing settings tab. Nothing in this spec
commits to an amount. See "Shipped state" below for what the page shows before they are set.

### Measured inputs (prod, 2026-09-06)

Against the mat-pp corpus, which the earlier notes required be **measured, never guessed**.

**Provenance.** Run on libli.pl, in the app container, iterating `MediaAsset` rows and
summing `a.file.size`, classifying by extension:

    ssh libli
    docker compose -f docker-compose.prod.yml --env-file .env.production exec -T app \
      /app/.venv/bin/python manage.py shell -c "<sum MediaAsset.file.size by extension>"

| | Size (GB, decimal) | Share | Files | Avg |
|---|---|---|---|---|
| Video | 4.048 GB | **98.4%** | 256 | 15.8 MB |
| Images | 0.064 GB | 1.6% | 970 | 0.066 MB |
| Total | 4.111 GB (3.83 GiB) | 100% | 1226 | — |

⚠️ Every cell derives from the raw byte counts, not from its neighbours — do not recompute a
share by dividing two rounded cells and conclude the table is wrong. Shares are computed on
the GiB figures (3.77 / 3.83 = 98.4%).

mat-pp is 889 units — a full three-year maths course — in **4.11 GB**, about **€2.81/year**
to store at €0.057/GB/mo.

⚠️ **Three caveats on this measurement, all of which must survive into any restatement:**

- **Originals only.** `thumb` and `web` derivatives are separate `FileField`s on the *same*
  `MediaAsset` row (`courses/models.py:808,811` — the `thumb` and `web` declarations), so summing `a.file.size` excludes them.
  The image figure is therefore an *under*-count; applying the ~2.5× image multiplier gives
  ~0.15 GB against video's 4.05, which strengthens rather than weakens the conclusion.
- **The 2.5× multiplier is not documented in the repo.** It comes from a prior working note.
  Do not cite it as documented; treat it as an estimate that only ever makes images smaller
  relative to video.
- **An earlier note recorded ~9 GB for 232 video assets** locally, against 4.05 GB for 256
  here. That discrepancy is **unreconciled** — it may be local-only content, a different
  corpus state, or a `du`-vs-row-sum difference (`MediaAsset` rows can share one `file.name`,
  so a per-row sum double-counts a shared file while `du` does not). The conclusion below is
  robust to it: even at 9 GB the storage cost is ~€6/year.

Two consequences, both load-bearing for the page:

- **Video is the entire storage story; images are noise.**
- **Storage cannot be a pricing lever.** A 50 GB allowance is ~12 courses like mat-pp for
  ~€34/year. State it generously so it never becomes friction; the price rides on support.

## Mechanism

### Model

New `PricingPlan` (app: `institution`), three rows seeded by migration:

| Field | Definition |
|---|---|
| `order` | `PositiveSmallIntegerField`, unique — the row key for `get_or_create` |
| `pupils_min` | `PositiveIntegerField`. **Stored explicitly, not derived** from the previous row's max: derivation is unstated cleverness that silently produces nonsense on non-monotonic input |
| `pupils_max` | `PositiveIntegerField`, not null. The open-ended top tier is emitted by the renderer, not stored |
| `annual_price` | `DecimalField(max_digits=9, decimal_places=2, null=True, blank=True)` — both arguments are mandatory — Django's system checks reject a `DecimalField` missing either (`fields.E132` for `max_digits`, `fields.E130` for `decimal_places`). Null ⇒ "by arrangement" |
| `support_hours_per_term` | `PositiveSmallIntegerField` |
| `courses_included` | `PositiveSmallIntegerField` |
| `video_hours_included` | `PositiveSmallIntegerField` |

`class Meta: ordering = ["order"]`, **and** an explicit `.order_by("order")` where the rows
are read. Without it an updated tuple can change physical order, so saving band 2 moves it
above band 1 on the public page.

⚠️ **`PricingPlan` deliberately has NO `Institution` foreign key**, unlike `BrandColor`
(`institution = ForeignKey(..., related_name="brand_colors")`, reached by `_build()` through
`prefetch_related`). libli is single-tenant per box, so a FK would buy nothing. The
consequence is that `_build()` cannot reach the rows through the `Institution` instance and
must query them separately — see the early-return trap below.

Four fields on `Institution` (the natural home: the tab is an `Institution` ModelForm).
⚠️ These were dropped by an earlier revision of this spec while `_build()` was still told to
read them — a schema migration adds them alongside `CreateModel(PricingPlan)`:

| Field | Definition |
|---|---|
| `currency` | `CharField(max_length=3, default="PLN")` — an ISO 4217 code, free text not choices, so a non-PLN school needs no migration |
| `vat_note_en` | `TextField(blank=True, default="")` |
| `vat_note_pl` | `TextField(blank=True, default="")` |
| `storage_allowance_gb` | `PositiveIntegerField(null=True, blank=True)` — null ⇒ the allowance sentence is omitted entirely |

⚠️ **`vat_note` is per-language, and this is forced by the spec's own argument.** The reason
plans carry no name is that only language-neutral values may be stored once. A VAT note is
prose; a single field would print a Polish tax statement on the English page while the
numeric parity test stayed green.

#### Validation lives in the form and the database, not in `PricingPlan.clean()`

⚠️ **Django never calls `full_clean()` on `save()`**, and neither of this spec's two write
paths would invoke it: the migration uses the historical model (which has no `clean()` at
all) and the settings form is an `Institution` ModelForm that writes plan rows by field
assignment. A `PricingPlan.clean()` would be dead code, and the test asserting bands are
rejected would have nothing rejecting them. `Institution` and `BrandColor` set the
precedent — neither defines `clean()`; `BrandColor` uses field `validators`.

So:

- **`Meta.constraints`** gets `CheckConstraint(condition=Q(pupils_min__lt=F("pupils_max")),
  name="pricingplan_band_is_ordered")` — holds at the database on every write path.
  ⚠️ **`condition=`, not `check=`**: this project runs Django 5.2 and `CheckConstraint.check`
  **emits** `RemovedInDjango60Warning` on every model import — noise on every test session
  (it does not fail: `pyproject.toml` sets no `filterwarnings = ["error"]`) — and stops
  working in Django 6.0.
- **The pricing form's `clean()`** rejects bands that overlap, leave a gap, or run
  non-monotonically across the three blocks — a cross-row rule no single instance can see,
  and the form is the only place all three are visible at once. ⚠️ **It must ALSO enforce
  `pupils_min < pupils_max` per row.** A submission like `(1,150), (151,400), (401,300)` has
  no gap and no overlap *between consecutive rows*, so a clean() that checks only the cross-row
  rules passes it — and `save()` then hits the `CheckConstraint`, raising `IntegrityError` out
  of `form.save()` inside `_action`, which has no handler. An admin who types two numbers the
  wrong way round gets a **500**, not a field error. The constraint is a backstop for
  out-of-band writes, never the admin-facing check.

### Vendor gating — a NEW flag, not `demo_instance`

`/for-schools/` is gated on a new Django setting **`VENDOR_INSTANCE`**, read from the
environment variable **`LIBLI_VENDOR_INSTANCE`**, default `False`.

⚠️ Two names, deliberately, following the existing convention: the env var carries the
`LIBLI_` prefix and the setting drops it, as `ALLOW_HTTP_IMAGE_FETCH` and
`GEOGEBRA_API_LOOKUP` already do in `config/settings/base.py`.

⚠️ **It must NOT be `demo_instance`.** That field's help text is *"Adds a warning to the
public pages telling visitors not to enter real pupil data"* (`Institution.demo_instance`)
— a content-warning flag with one existing meaning, consumed by `core/public_pages.py`'s
demo notice and by `_page_overrides()`'s per-row `missing_demo_notice` flag. Gating on it would (a) stamp "this is
a demonstration site — do not enter real pupil data" across our own sales page, (b) publish
our price list on any school pilot box that has the flag on — the exact failure the gate
exists to prevent — and (c) silently delete the page from libli.pl the day the flag is turned
off, which is correct for libli.pl now that it holds the real mat-pp corpus.

A **setting**, not an `Institution` field, because it is a deployment fact rather than a
school-editable preference: a school admin must not be able to toggle it, and it must not
appear in the settings UI.

**Gate behaviour:** a non-vendor box returns **404** from the view. The flag is read from
`django.conf.settings`, so no cache or query is involved. (⚠️ Do not read `Institution.load()`
on a GET render path: it is `get_or_create`, a write, which `core/services.py` forbids there.)

⚠️ **PIN `VENDOR_INSTANCE = False` IN `config/settings/test.py`.** `base.py` calls
`env.read_env(BASE_DIR/".env")`, which copies the developer's local `.env` into
`os.environ`, and `test.py` does `from base import *`. The implementer building this page
will set `LIBLI_VENDOR_INSTANCE=true` in their own `.env` to see `/for-schools/` on
`runserver` — and that flips the flag for the **entire test run**, turning Testing 15's
hard-coded `== 4` into 6 and reddening every gate-off assertion (Testing 3, 16, 20) for a
reason unrelated to the code. This repo has been bitten by exactly this leak before:
`tests/test_transfer_caps_env.py`'s docstring records a developer's `.env` reddening a
defaults test, and `test.py` already pins `GEOGEBRA_API_LOOKUP = False`,
`ALLOWED_IMAGE_FETCH_DOMAINS` and `CACHES` for the same reason. Use the same comment shape:
tests that exercise the vendor page opt back in with `override_settings(VENDOR_INSTANCE=True)`
— **never** through the environment.

**Operator paperwork:** an entry in `.env.production.example` (which documents every
operator-set variable; `docker-compose.prod.yml` uses a bare `env_file:` so no compose edit
is needed) and a line in `docs/deployment.md`, since turning the page on is by design a
deploy step rather than a settings toggle.

#### Delivering the flag to templates

⚠️ **Django templates cannot read `settings.VENDOR_INSTANCE`.** The only bundle they see is
`core.context_processors.institution_branding`, which returns `{"site": cfg, "institution":
cfg}` — and the flag is deliberately *not* in `cfg`. `landing.html` is rendered by the
landing view; `_public_footer.html` by both `public_page.html` and
`allauth/layouts/entrance.html`; there is no shared view to hang a per-view context key on.

**Resolution:** `institution_branding` gains a `vendor_instance` key, reading
`settings.VENDOR_INSTANCE` directly (not through `cfg`, which must stay the never-writes ORM
bundle). One edit, and every template that already has the processor gets the flag.

**The footers and landing page gain a conditional "For schools" link** — this is a
requirement, not merely a test. Files edited: `core/context_processors.py`,
`templates/core/_public_footer.html`, `templates/core/landing.html`.

### Configuration flow — the plan data reaches the renderer through `cfg`

⚠️ `substitute_tokens(html, cfg, lang)` takes its inputs as arguments, and
`core/services.py` documents the bundle as the injectable single source of truth that
**never writes**. The renderer must do **no ORM query of its own** — a query there would also
run on every render of `/privacy/` and `/getting-started/`.

- `core/services._build()` gains: `pricing_plans` (a list of plain dicts, already ordered),
  `currency`, `vat_note_en`, `vat_note_pl`, `storage_allowance_gb`.
  ⚠️ **The bundle carries `Decimal | None` for `annual_price`, NOT a pre-formatted string.**
  Formatting stays in the renderer, which is the layer the parity test reads. (An earlier
  draft said "serialised to primitives" while also putting `quantize` in the renderer — those
  contradict; this is the resolution.)
- **`_DEFAULTS` gains matching keys** with fresh-install values: `[]`, `"PLN"`, `""`, `""`,
  `None`. ⚠️ `_build()` returns `dict(_DEFAULTS)` early when there is no `Institution` row,
  and `tests/test_public_pages_config.py::test_bundle_carries_every_new_key_with_NO_institution_row`
  exists to lock exactly that parity. Extend that test's `NEW_KEYS`. ⚠️ **`NEW_KEYS` only strengthens the key-parity
  assertions.** The *values* are checked by
  `test_defaults_carry_every_new_key_with_the_right_values` against a separate hard-coded
  tuple, so `currency == "PLN"`, `pricing_plans == []` and `storage_allowance_gb is None` must
  be added there too — and `vat_note_en` / `vat_note_pl` slot straight into that test's
  existing `for key in (...)` loop asserting `== ""`, so **all five** new keys end up pinned — otherwise a `currency` default of `""` ships green and prints
  "Annual price ()" as the column header.
- ⚠️⚠️ **The `PricingPlan` query MUST run BEFORE the `inst is None` early return.** Plans have
  no FK to `Institution` (above), so on a box where the migration has seeded three plans but
  nothing has yet created the `Institution` row, the early return would hand back
  `pricing_plans: []` with the rows sitting unread in the database — and the page would show
  the no-prices fallback while priced plans exist. Query plans first, then merge into either
  branch.
- **`PricingPlan` is added to the `post_save`/`post_delete` tuple in `core/apps.py`** that
  currently connects `invalidate_site_config` for `(Institution, BrandColor)`. Without it a
  price edit is invisible for up to `CACHE_TTL = 300` seconds.

### Tokens

| Token | Kind | Value |
|---|---|---|
| `{libli:pricing_plans}` | **block** | the plans table (or the no-prices fallback), including the storage-allowance sentence |
| `{libli:vat_note}` | **block** | the resolved language's note, `_nl2br`'d; empty string when blank |
| `{libli:for_schools_link}` | **block** | the cross-pointer on `/getting-started/`; empty string off-vendor |

⚠️ **`for_schools_link` needs the vendor flag, which is deliberately not in `cfg`.** The
context processor delivers it to *templates*, not to `substitute_tokens`. Resolution:
**`substitute_tokens` reads `settings.VENDOR_INSTANCE` directly** for this one token. That is
a deliberate exception to "cfg is the injectable single source of truth for tokens", and it
has a concrete cost: the eight existing `substitute_tokens(...)` call sites can no longer
steer this token through `cfg(**over)` and need `override_settings` instead. Accepted, because
putting a deploy-time flag into the ORM bundle would be worse. The anchor is built with
**`reverse("core:for_schools")`** and `format_html`, never a hardcoded `/for-schools/` — a
hardcoded path would also escape `test_every_root_relative_link_resolves`.

⚠️ **There is NO new inline token.** An earlier draft had `{libli:storage_allowance}` while
also stating the allowance sentence is emitted inside the `pricing_plans` block — which
cancel out, leaving a token no markdown ever contains and a guard proving nothing. Resolved
in favour of the block: **the renderer interpolates the allowance directly**, and
`INLINE_TOKENS` is untouched. When `storage_allowance_gb` is null the sentence is omitted.

⚠️ **Every block value is either `""`, or ONE OR MORE complete block elements — never bare
inline content.** (Siblings are allowed and needed: in the priced branch `pricing_plans` is
the scroller `<div>` **plus** the optional storage-allowance `<p>`.) `_block_re(name)`
substitutes the token *together with its enclosing `<p>`*, which is why `controller_address`
builds `"<p>" + _nl2br(escape(...)) + "</p>"` and `_demo_notice_html()` returns a full
`<p class="...">...</p>`. So: `vat_note` → `<p>…</p>`; `for_schools_link` →
`<p><a href="…">…</a></p>`; `pricing_plans` → the `<div class="public-page__scroll">…</div>` **plus the optional
allowance `<p>`**, or the fallback `<p>…</p>`. ⚠️ Nothing in the existing guards catches a bare string — both
`test_no_empty_paragraph_when_blocks_are_off` and the heading guard stay green while
unwrapped inline content lands between block elements.

⚠️ **Block, not inline, and the two sets must not overlap.** A block token is replaced
*together with its enclosing `<p>`*; substituting a table inline would nest a `<table>`
inside a paragraph. Block tokens are absent from the inline map precisely so a misplaced one
renders literally instead of as escaped markup.

⚠️ `substitute_tokens` asserts `set(block_values) == set(BLOCK_TOKENS)` before iterating, so
adding to the frozenset alone is an `AssertionError` on `/privacy/` too. All three new
entries go in **both** `BLOCK_TOKENS` and the `block_values` map.

⚠️ While here, add the **missing symmetric assert** `set(_inline_values(cfg)) ==
INLINE_TOKENS`. The block pass has one; the inline pass does not, so a half-done edit there
is a `KeyError` rather than a clear failure. This is prophylactic — this spec adds no inline
token — but it is the cheapest possible moment to close it.

`vat_note` is a **block** token, not inline, for the reason `controller_address` is: the
inline pass escapes into a text run with no `_nl2br`, so a two-line note would render as one
run-on line.

⚠️ **It is `_nl2br(html_lib.escape(str(note)))`, exactly as `controller_address` is — the
escape is not optional.** Block values are inserted *after* nh3, so they reach the browser
unsanitised, and this is the one value on the page that is free admin-authored text. A guard
asserts that a stored `<b>` renders as escaped text, not as markup.

#### Language selection

⚠️ **`substitute_tokens` currently takes no language, and the obvious fix is wrong.**
`translation.get_language()` is **not** the same as the page's resolved language:
`core/help.localized_doc_path` falls back to the English base when a `.pl.md` file is absent,
so `resolved == "en"` while the active language is still `pl`. Using `get_language()` would
put the Polish VAT note and Polish column headers on a page whose prose is English.

**Resolution:** `render_public_page` threads its computed `resolved` into
`substitute_tokens(html, cfg, lang)` as a new argument.

⚠️ **Threading `lang` is not by itself enough.** Selecting `vat_note_en`/`vat_note_pl` is a
dict lookup and works, but `gettext` resolves under the *active thread* language, not a
passed argument. The column headers, the "by arrangement" cells and the fallback paragraph
need an explicit **`with translation.override(lang):`**, scoped to **the new block values
only** — wrapping the whole of `substitute_tokens` would also change `_demo_notice_html()`
and `_inline_values()`'s `retention_phrase` on any page that fell back to English, a
behaviour change to `/privacy/` this spec does not intend.

⚠️ **`core/public_pages.py` imports `gettext_lazy as _`.** A lazy proxy resolves when it is
coerced to `str`, which for `format_html` happens at format time — so it picks up `lang` only
if the forcing happens inside the override, and silently picks up the ambient language
otherwise. That is the exact failure this section exists to prevent, reintroduced by the
module's own import alias. **Use eager `gettext` for the new strings**, inside the override, imported
**unaliased**: `from django.utils.translation import gettext`. ⚠️ Writing
`from django.utils.translation import gettext as _` satisfies that sentence literally and
silently freezes every `PAGES` title and meta description to the language active at import
time — `_` must stay bound to `gettext_lazy`, because `PAGES` resolves it at module import.

⚠️ **`lang` is positional-required, not defaulted.** A `lang="en"` default would keep all
eight existing call sites green while silently pinning English into the content guards. The
call sites are `core/public_pages.py`, `tests/test_public_pages.py`'s shared `render()`
helper, and **six in `tests/test_public_pages_content.py`** — all must be edited, and they
belong in the "existing tests that break" inventory.

### Rendering the table

Built with `format_html`, following `_demo_notice_html()` — substitution runs **after**
`nh3`, so this value reaches the browser unsanitised.

**Row labels** are `pupils_min`–`pupils_max`, both numbers, hence identical in both
languages. **Plans carry no name**, which is what makes the parity guard achievable.

**The fourth "by arrangement" tier is emitted by the renderer** as a final `<tr>` with **no
database row**. ⚠️ **Its first cell interpolates the last band's ceiling** —
`gettext("%(above)s and above") % {"above": plans[-1]["pupils_max"] + 1}` — not a static phrase:
a static "Larger schools" leaves a visible gap above the last band that a school will notice.
Named interpolation, and the placeholder must survive into both `.po` files. The remaining
cells are `gettext` literals. ⚠️ It cannot be prose in the markdown:
the token substitutes a complete `<table>` for its enclosing `<p>`, and markdown outside it
can only produce a sibling paragraph, never a `<tr>` inside the generated table.

**Column headers** come from eager, unaliased `gettext`, resolved under the threaded
language. ⚠️ Never `_(...)` in this module — see Language selection; `_` is `gettext_lazy`. ⚠️ The currency
header is **dynamic** — `currency` is an editable field — so it needs *named* interpolation,
not concatenation: `gettext("Annual price (%(currency)s)") % {"currency": cfg["currency"]}`. The
placeholder must survive into both `.po` files.

**Amount formatting:** `f"{d.quantize(Decimal('0.01')):,f}".replace(",", " ")` — ⚠️
`Decimal.quantize` takes an exponent Decimal, not `2`, and `str(Decimal)` emits **no**
thousands separator, so it must be inserted deliberately. The separator is **U+00A0**
(non-breaking), not U+0020, so an amount never wraps mid-number. **No currency symbol beside
each amount** — the currency lives in the column header, so the cells are bare numerals and
the parity test compares exactly those. No `floatformat`,
no `intcomma`, no locale-dependent formatting — the numeric strings must be byte-identical
across EN and PL for the parity test to be a real comparison rather than a formatting
assertion.

**Mobile:** the `format_html` output wraps the table in `<div class="public-page__scroll">`.
⚠️ **`overflow-x: auto` on the wrapper is NOT sufficient on its own.** `.public-page table`
is `width: 100%` inside a 46rem column, so the table shrinks to the wrapper and the scroller
never engages — every column wraps to one or two characters instead. The rule must be
`.public-page__scroll { overflow-x: auto }` plus
`.public-page__scroll table { width: max-content; min-width: 100% }`.
⚠️ **`.public-page table` and `.public-page__scroll table` are BOTH (0,1,1) — a specificity
TIE, decided by source order.** The new block must be inserted *after* `.public-page table`
in `app.css`; placed above it the block is completely inert while reading exactly like the
design. This repo has shipped that failure before. Confirm with an **A/B** (render with and
without the rule), never by measuring the built page — measuring with the rule present
proves nothing. ⚠️ Fixable only in the
renderer: `PUBLIC_PAGE_TAGS` has no `div`, so a markdown-authored wrapper is stripped by nh3
— but the token value is inserted *after* nh3. The privacy notice's existing tables stay
unwrapped; that inconsistency is accepted (they are narrow and already fit).

### Shipped state — no prices yet

⚠️ On merge, every `annual_price` is null. A page of four "by arrangement" rows does not
meet this spec's own stated purpose.

So: when **no** plan has an `annual_price`, `{libli:pricing_plans}` renders **not the table**
but a fallback paragraph. ⚠️ **An EMPTY `pricing_plans` list renders the same fallback**, and
this must be stated rather than left to follow vacuously: `_DEFAULTS` and `BASE_CFG` both
carry `[]`, so it is the state every direct `substitute_tokens` unit test runs under. The
readings it rules out — a lone renderer-emitted "by arrangement" row, or a header-only empty
`<table>` — are all reachable from the prose otherwise. Its full composition, because this is the state the branch actually
ships in and therefore the one most worth pinning:

- the "prices for your school on request" sentence;
- the contact address — ⚠️ **reusing `_inline_values`' existing fallback**
  (`_("the person who runs this site")`) when `cfg["contact_email"]` is blank, rather than
  inventing a second fallback string for the same question;
- a pointer to the five contract numbers **in the markdown above it** — ⚠️ the fallback does
  NOT re-emit them. Content item 8 owns that list; emitting it here too would print it twice
  in the shipped state and once in the priced state, so the two layers would disagree;
- the storage-allowance sentence **when `storage_allowance_gb` is set** — it is independent
  of price, and ⚠️ **absent in the shipped state**, since the field defaults to null. The
  screenshot in Testing 14 must match that.

⚠️ **The VAT note is NOT controlled from here.** The allowance sentence is emitted *inside*
the `pricing_plans` block, so the fallback branch genuinely owns it; `{libli:vat_note}` is a
**separate block token** placed independently in the markdown, and the fallback has no way to
suppress it. An earlier draft said a VAT note is withheld when no plan is priced — that is
unimplementable as stated. It renders whenever the note is non-blank, and in the shipped
state it is blank, so the question is moot in practice.

Filling the prices is a release step, not a code change.

### Page registration

| | |
|---|---|
| slug | `for-schools` |
| markdown | `public/for-schools.md`, `public/for-schools.pl.md` (the base-dot-code convention) |
| `PAGES` entry | title + meta description, both `gettext_lazy` |
| URL | `core/urls.py`, `path("for-schools/", views_public.for_schools, name="for_schools")` |

⚠️ **Three existing tests break by construction and must be edited, not worked around:**

1. `tests/test_public_pages.py::test_pages_registry_shape` asserts
   `set(PAGES) == {"privacy", "getting-started"}` — exact equality, not a subset. It becomes
   `== {"privacy", "getting-started", "for-schools"}` plus the matching `PAGES[...].path`
   assertion the file already has for the other two.
2. `tests/test_public_pages_content.py` holds a hard-coded `SHIPPED` list of four files.
   ⚠️ **Seven guards are parametrised over it, not six**, and
   `test_every_root_relative_link_resolves` is **not** among them — it sweeps `SHIPPED`
   internally by design, so it picks the new files up automatically. The parametrised seven
   include `test_shipped_file_exists_and_is_utf8` and
   `test_no_block_token_has_a_heading_immediately_above_it`, both of which an earlier draft
   of this spec omitted.
   One of them, `test_demo_notice_is_placed_where_the_block_regex_matches`, asserts
   `"{libli:demo_notice}" in source` — and `for-schools.md` deliberately carries no such
   token. **Resolution: add both new files to `SHIPPED`, and re-parametrise that guard IN FULL**
   over the `DEMO_NOTICE_SLUGS`-derived subset. ⚠️ It cannot be "split": all three of its
   assertions (`"{libli:demo_notice}" in source`, `"public-page__notice" in html`,
   `"{libli:demo_notice}" not in html`) are false for a page that deliberately carries no
   token, so there is no half that can keep the full sweep. The other six parametrised guards
   do keep it. Not adding the files would leave the new page — the one that hardcodes
   `/privacy/`-style links — with zero coverage from the guard that checks exactly that.
   ⚠️ **`test_no_block_token_has_a_heading_immediately_above_it` hard-codes its trigger**
   (`if "{libli:demo_notice}" in line or "{libli:controller_address}" in line`), so it is
   blind to all three new block tokens. **Drive it off `BLOCK_TOKENS`** instead. This matters
   concretely: `{libli:for_schools_link}` renders as an *empty string* off-vendor, which is
   precisely the orphaned-heading failure the guard exists to catch.
3. `tests/test_public_pages_settings.py::test_panel_uses_the_coalesced_language_list_not_the_stored_one`
   asserts `body.count('name="override-') == len(PAGES) * 2`. Filtering the gated page out of
   the panel (below) makes that `(len(PAGES) - 1) * 2` with the flag off. **Rewrite the
   expression against the `_page_overrides()`-derived length, or parametrise over the flag.**
   ⚠️ Do NOT relax it to `<=`, which destroys the guard it exists to be.

⚠️ `_page_overrides()` iterates **all** of `PAGES` and is reused as the *write* loop's
iteration set, so a school admin would otherwise see an editable "For schools" box for a
route that 404s on their box. **The overrides panel filters out the gated page when
`VENDOR_INSTANCE` is false**, and `for-schools.md` carries no `{libli:demo_notice}`.
⚠️ **Exempt `for-schools` from the `missing_demo_notice` computation.**
⚠️ The exemption set must be defined **once, in production code**: `DEMO_NOTICE_SLUGS =
{"privacy", "getting-started"}` in `core/public_pages.py` beside `PAGES`. It cannot be shared
with the content guard's subset directly — `SHIPPED` holds markdown *paths*
(`"public/privacy.md"`) while `_page_overrides()` iterates *slugs*, and production code cannot
import from `tests/`. The guard derives its file-path subset from the slug set
(`PAGES[slug].path` plus the `.pl.md` sibling). Otherwise, on a box where
the vendor flag is on *and* `demo_instance` is true, any `for-schools` override is labelled
"no demonstration warning" for a page that deliberately has none.
⚠️ `_page_overrides()`'s docstring says "Takes no argument: everything comes from
`get_site_config()` and `PublicPage.objects`" — reading `django.conf.settings` there makes
that false, so the docstring is updated in the same edit — and so is
`_settings_context`'s. ⚠️ **Its counts are already wrong before this change**: it opens
"Assemble the seven-form context" while the function already returns eight forms and
`settings.html` already renders eight panels (`public_pages` was added without updating them),
and it says "the four institution forms seeded from `inst`" where there are already five. So
correct them to the real post-change numbers — nine forms, nine panels, six institution forms
— rather than incrementing the stale ones.

### Settings tab

One more `_action` call — that helper already carries the #307 non-POST contract, so the
Pricing form **must be an `Institution` ModelForm** whose `save()` also writes the plan rows.

⚠️ **The Pricing tab is itself gated on `VENDOR_INSTANCE`.** The argument the overrides
panel already makes applies verbatim and more strongly here: on a school's box the flag is
false, `/for-schools/` 404s, and a school admin would otherwise get a "Pricing" tab editing
**our** pupil bands, support hours and annual prices — pre-seeded with our structural
placeholders. Gate it in all four places: `TABS`, `_tabs.html`, `settings.html`, and a 404 from
`settings_pricing` when the flag is false.
⚠️ **The flag must be consulted PER REQUEST.** `TABS` is a module-level tuple read by
`_active_tab()`; appending `("pricing",)` conditionally at module scope is evaluated once at
import, so `override_settings(VENDOR_INSTANCE=True)` never reaches it — while the two template
halves *do* re-evaluate per request through the `vendor_instance` context key. The result is a
half-working gate: the tab link renders, `?tab=pricing` falls back to `branding`, and the panel
never opens. Make `TABS` a small `_tabs()` function (or have `_active_tab()` take the extra
tab). This is the same import-time trap the spec flags for `gettext as _`. ⚠️ Testing 12's
`ACTION_URL_NAMES` entry therefore needs the flag ON.

**Seven wiring points, all easy to miss:**

1. the view function in `views_manage.py`
2. `path("manage/settings/pricing/", views_manage.settings_pricing, name="settings_pricing")`
   in `institution/urls.py`
3. the `TABS` tuple
4. the `_settings_context` keyword — ⚠️ the ctx_key must be a valid Python identifier
   (`pricing`) because `_action` splats `**{ctx_key: form}`; `settings_public_pages`
   documents this trap for the `public-pages` tab
5. the `_tabs.html` include
6. a new `_pricing_tab.html` partial, its form `action` pointing at
   `institution:settings_pricing`, and its panel div in `settings.html`
7. permission `institution.change_institution`

**Form shape.** `BrandingForm` is the precedent but declares only three non-model fields (`primary`, `accent`, `public_hostname`); this
needs **3 rows x 6 fields = 18**, plus the four `Institution` fields above.

⚠️ **Six per row, not five.** The editable set is `pupils_min`, `pupils_max`, `annual_price`,
`support_hours_per_term`, `courses_included`, `video_hours_included`; `order` is the row key,
not an input. The cross-row `clean()` needs both bounds submitted, so none may be dropped —
and an implementer following a "five fields" count would most plausibly omit `pupils_min`,
which the Model section explicitly forbids deriving.

- **Naming:** `plan_<order>_<field>`, e.g. `plan_1_pupils_min`, so the cross-row `clean()`
  can iterate rather than hard-code.
- **Declared** in `__init__` by looping over the rows, not as eighteen class attributes.
- **`initial`** seeded from `PricingPlan.objects.order_by("order")` via
  `self.initial.setdefault`, mirroring `BrandingForm.__init__`. ⚠️ `_settings_context`
  constructs *every* form unbound on *every* settings render, so this query runs on all nine
  tabs (eight today plus Pricing) — keep it to one `order_by`, no per-row queries.
- **`annual_price` is `required=False`** so the shipped null state can be re-saved without
  inventing a price.
- **`save()`** is wrapped in **`with transaction.atomic():`**, mirroring
  `BrandingForm.save()`, which wraps `super().save()` and its `BrandColor` writes for exactly
  this reason. ⚠️ Load-bearing here: the band rules are a **cross-row** invariant that the
  per-row `CheckConstraint` cannot restore, so a failure between row 1 and row 2 would commit
  an overlapping or gapped band set that the form had validated as a whole.
- **`save()`** writes with **`.get(order=N)`**, not `get_or_create`. ⚠️ Because the field set
  is derived from the rows that already exist, every `N` in `save()` names an existing row —
  the create branch is unreachable, and a bare `get_or_create` would hit the same
  missing-`defaults=` `IntegrityError` the migration section flags if it ever were reached.

⚠️ **The three-row invariant.** The form iterates `PricingPlan.objects.order_by("order")`,
not `range(1, 4)`. A fourth row created out-of-band (shell, a future migration) would
otherwise render on the public page while the settings tab silently ignored it, and the
form's gap/overlap `clean()` would validate a band set that is not the one rendered.
`PricingPlan` is **not** registered in the Django admin, so there is no second write path.

### Migration

⚠️ **These rows exist in every test database** — no `--nomigrations` in `addopts` — so test
fixtures must UPDATE them, never create (see Testing 0).

**One migration, operations in this order:** `CreateModel(PricingPlan)`, the four
`AddField`s on `Institution`, `AddConstraint(...)`, then `RunPython(seed, RunPython.noop)`.
⚠️ The autodetector pops `constraints` out of the model options and emits a **separate**
`AddConstraint` operation — it does not live inside `CreateModel`, so a generated migration
that looks different from a naive reading of this line is correct. The load-bearing point is
that `RunPython` is **last** — the data step must follow the schema steps in the same
`operations` list. `RunPython.noop` because irreversible data migrations cannot be tested.
Target the current graph head (`institution/0011` at time of writing; verify).

⚠️ **`get_or_create(order=N)` MUST carry `defaults={...}`.** Five fields are non-nullable
with no default, so a bare `get_or_create` raises `IntegrityError` on a fresh database.
`get_or_create` and never `update_or_create`, so a re-run can never overwrite a school's
edited prices.

⚠️ **The seed therefore commits to bands and bounds** — only `annual_price` is genuinely
deferrable, since it is nullable and the fallback paragraph covers it. These are structural
placeholders, editable in the settings tab, and they must themselves be gap-free,
non-overlapping and monotonic or the settings tab rejects the shipped state on first save:

| order | pupils_min | pupils_max | annual_price | support h/term | courses | video h |
|---|---|---|---|---|---|---|
| 1 | 1 | 150 | `NULL` | 6 | 3 | 10 |
| 2 | 151 | 400 | `NULL` | 8 | 6 | 20 |
| 3 | 401 | 800 | `NULL` | 12 | 12 | 40 |

## Content

### `/for-schools/` (new, vendor-only)

1. **What you get** — the product description currently stranded in getting-started's
   "Evaluating libli?" section. It moves here rather than being rewritten.
2. **What we need from you** — the DNS ask bundled into one email: A record plus SPF and
   DKIM, same person, same day.
3. **What we do NOT need** — no server, no hardware, no procurement, no software on pupil
   devices. The trust half, and the reason this section exists.
4. **The two DNS traps** — a `CAA` record that omits `letsencrypt.org`, and a stale `AAAA`.
5. **Where the data lives** — Hetzner, Germany; nightly encrypted backups; the retention
   figures. ⚠️ **Reuse the privacy notices' exact retention sentences**, EN and PL, so the
   existing f-string guard patterns extend unchanged (see Testing 9).
6. **What happens if you leave** — handover is a key **rotation** under a key the school
   generates, never disclosure of the shared age key.
7. **Timeline.**
8. **Plans** — the table, the storage allowance, the VAT note, and the five contract numbers
   presented as *what we agree at signup*, never as calculator inputs. This section **owns**
   the list of five (the fallback paragraph only points at it).
   ⚠️ **Prose must sit between the "Plans" heading and each of `{libli:pricing_plans}` and
   `{libli:vat_note}`.** Once both new files are in `SHIPPED` and the heading-adjacency guard
   is driven off `BLOCK_TOKENS`, a token as the first non-blank line under a heading fails it
   — the same countermeasure the getting-started trim needs, and it applies here by
   construction, not by accident.

⚠️ **The timeline does NOT carry a port-25 month.** The earlier note listed it as a standard
step; that is wrong. The settled default is a transactional provider over **port 587, which
Hetzner has never blocked**. Exchange Direct Send is the documented exception. Port 25
appears only as a conditional branch for a school that insists on Direct Send — and even
then the gate is 30 days of account age, not a fee.

### `/getting-started/`, both language files, trimmed

Each keeps the sign-in help verbatim — it is correct, and it is what the footer's "Help" link
should reach. Each loses the product pitch to `/for-schools/`. Each gets an opening that is
true on a school's own box: their school's platform, not one they run themselves. Each adds
the `{libli:for_schools_link}` block, empty off-vendor.

⚠️ **`{libli:demo_notice}` currently sits INSIDE the "Evaluating libli?" section being cut**,
along with the contact and privacy-notice paragraphs.
`test_no_block_token_has_a_heading_immediately_above_it` fails if the trim leaves the token as
the first non-blank content under a heading. State where the notice and those two paragraphs
land in the trimmed file, and place every block token with prose above it.

⚠️ **The `/privacy/` link lives in the paragraph being moved**, and
`test_every_root_relative_link_resolves` asserts
`{"/privacy/", "/accounts/password/reset/"} <= set(found)` as an explicit non-vacuity check
across the whole `SHIPPED` sweep. A root-relative `/privacy/` link **must survive in at least
one `SHIPPED` file** after the trim — name which file carries it, or that assert goes red for
a reason unrelated to this change.

## Testing

Load-bearing first.

0. ⚠️ **A PRICED-PLAN FIXTURE is a precondition for items 1, 5, 7, 14, 18 and 19.** In the shipped state
   every `annual_price` is null, so the token renders the fallback paragraph and there is **no
   table at all**. A parity or ordering test written against the shipped state regexes an
   empty match set in both languages and passes vacuously — the exact shape this section warns
   about. ⚠️ **The fixture UPDATES, it does not create.** `pyproject.toml`'s `addopts` sets no
   `--nomigrations`, so `RunPython(seed, ...)` runs against every test database and orders
   1/2/3 already exist — `PricingPlan.objects.create(order=1, ...)` raises `IntegrityError` on
   the unique `order`. The plausible workaround (creating orders 4/5/6) silently produces a
   six-row, gapped, non-monotonic band set that breaks the three-row invariant, changes
   `plans[-1]["pupils_max"] + 1`, and makes every table test measure a page nobody ships. The
   fixture therefore sets `annual_price` on `PricingPlan.objects.order_by("order")`, and for
   item 5 nulls one of them.
   The fixture makes three plans *priced*, and every test that reads the table asserts
   **non-vacuity** (at least three amounts extracted) before comparing anything. ⚠️ Item 5
   needs a **mixed** fixture — at least one priced plan AND one null-priced plan — since
   "renders by arrangement" is only reachable when some other plan carries a price; with all
   prices null there is no table and the assertion would be written against the fallback and
   pass vacuously.
1. **EN and PL render identical figures.** ⚠️ **Assert `resolved_lang == "pl"` first.**
   `localized_doc_path` falls back to the English base silently when `for-schools.pl.md` is
   absent, so a naive version compares English against English and is green with no Polish
   page at all — the exact "guard that asserts the adjacent thing" shape. Extract amounts
   with an explicit regex over the rendered table and compare the **strings**, which the
   formatting rule above makes legitimate.
2. **`pricing_plans`, `vat_note`, `for_schools_link` in `BLOCK_TOKENS` and NOT in
   `INLINE_TOKENS`**, and the new `set(_inline_values(cfg)) == INLINE_TOKENS` assert.
   ⚠️ "present in `block_values`" is **not directly assertable** — it is a dict local to
   `substitute_tokens`. Either assert it observably (a `substitute_tokens` call with a
   `BASE_CFG` bundle must not raise the existing block-parity assert), or extract
   `_block_values(cfg, lang)` as a module-level helper mirroring `_inline_values` so it can be
   inspected. Prefer the extraction.
3. **Vendor gating driven both ways, over every surface.** ⚠️ There are **two** footers:
   `templates/core/_public_footer.html` (included by `public_page.html` and
   `allauth/layouts/entrance.html`) and a **duplicated link block in
   `templates/core/landing.html`** — `tests/test_public_pages_footer.py` already asserts them
   separately for this reason. Parametrise over the route, both footers and the entrance page.
4. **Fresh install:** the page renders with no `Institution` row. ⚠️ **This test MUST set at
   least one `annual_price` first, or it cannot detect the bug it exists for.** With all
   prices null, `pricing_plans == []` and three seeded rows produce **byte-identical** output
   (both take the fallback branch) — so the early-return bug is invisible. With one price set,
   the populated build renders a table and the broken build renders the fallback, which is a
   real discriminator.
5. **A plan with `annual_price=None`** renders "by arrangement". ⚠️ **Scope the assertion to
   that plan's own `<tr>`** — locate the row by its `pupils_min`–`pupils_max` label, then
   assert the phrase inside it, and assert the *priced* rows in the same fixture carry
   numerals instead. A bare `"by arrangement" in html` is green on a build where the null
   price renders blank, `None` or `0.00`, because the renderer-emitted fourth tier puts that
   phrase on every table unconditionally. **All prices null** renders the fallback paragraph,
   including the blank-`contact_email` case.
6. **A price edit is visible immediately** — the `core/apps.py` signal, tested by saving a
   plan and re-rendering, not by asserting the signal is connected. ⚠️ **PRIME THE CACHE
   FIRST.** `tests/conftest.py`'s autouse `_clear_site_cache` calls `cache.clear()` before
   every test, so a test that edits and *then* renders finds an empty cache, rebuilds from the
   database, and sees the new price **whether or not `PricingPlan` is in the signal tuple** —
   the mutant survives. Render (or call `get_site_config()`) BEFORE the edit, so the
   stale-cache path is the one under test.
7. **Row order survives an edit** — save the middle band, assert the rendered order. ⚠️ Name
   the mutant honestly: with `Meta.ordering` present every queryset is already ordered, so
   dropping the explicit `.order_by` leaves this test green. It kills only the build that has
   **neither**. Pin the belt-and-braces `.order_by` with a source assertion instead, the way
   `test_demo_instance_is_a_bare_read_not_a_coalesced_one` pins its rule.
8. **Band validation, named by layer:** the `CheckConstraint` rejects
   `pupils_min >= pupils_max` at the database; the **form** rejects overlapping, gapped and
   non-monotonic band sets — **and the per-row `pupils_min < pupils_max` rule too.** ⚠️ That
   last case is the one the Model section added to stop a 500 and is the easiest to leave
   unguarded: POST `(1,150), (151,400), (401,300)` to `settings_pricing` **under
   `override_settings(VENDOR_INSTANCE=True)`** — without it the view 404s and the assertion is
   unreachable — and assert a **200 with a form error** — not a 302, not a 500, not an escaping `IntegrityError`. The mutant it
   kills is "a `clean()` carrying only the cross-row rules", which passes every other
   assertion in this item while still 500ing on an admin typo. The three cross-row cases
   (overlap, gap, non-monotonic) are **form unit tests** and need no flag; only the view-level
   POST above does.
9. **Retention figures guarded against the code**, in the style of
   `tests/test_public_pages_guards.py::test_backup_retention_matches_the_stated_periods`.
   ⚠️ That guard works only because it asserts f-strings embedding each constant *inside the
   surrounding prose* — a bare `"30" in notice` is worthless, as its own docstring says. This
   is why Content 5 requires reusing the privacy notices' exact sentences.
   ⚠️ **Name the subset.** That guard asserts eight patterns against `PRIVACY`/`PRIVACY_PL`:
   three period sentences per language plus a derived "about 13 months" consequence sentence
   per language. `/for-schools/` carries **the three period sentences in each language, not
   the 13-month consequence** — that one reads as compliance boilerplate in a "where the data
   lives" section. The new guard asserts those six patterns against `FOR_SCHOOLS` /
   `FOR_SCHOOLS_PL`; it does not reuse the full eight-pattern loop. A dropped pattern is an
   unguarded claim, so the subset is stated here rather than left to the implementer.
10. Anonymous access to `/privacy/`, `/getting-started/` and `/for-schools/` (the last with
    the gate **on**; the gate-off case is item 3), both languages; `PublicPage` overrides
    still win.
11. `"{#" not in body` — the Django single-line-comment trap, shipped five times. ⚠️ **Name
    the surfaces; `/for-schools/` is nearly the wrong one.** Its body is markdown inserted as a
    variable, so a `{#` there is inert text, not a template comment. The templates this change
    creates or edits are `_pricing_tab.html` (NEW, and by far the largest — 18 plan fields plus
    four `Institution` fields, in a repo that comments templates densely), `_tabs.html`,
    `settings.html` and `landing.html`; of those, `/for-schools/` renders none. Assert on **the
    settings page with `VENDOR_INSTANCE=True` and `?tab=pricing`**, the landing page, and
    `/for-schools/`.
12. **Insert the new settings URL name into `ACTION_URL_NAMES` in
    `tests/test_settings_action_method_guard.py`**, not a fresh test. ⚠️ Insert it **inside
    the `_action` group** (the list is ordered, and the comment above it says "The first five
    share the `_action` helper") and update that comment to six. That file's
    `NON_POST_METHODS` deliberately excludes GET — "including it would let the test pass on
    the broken build" — and a separately written test would almost certainly re-test GET and
    be weaker.
13. ⚠️ **`BASE_CFG` in `tests/test_public_pages.py` is a hand-built literal dict**, not
    derived from `_DEFAULTS`, and is imported by `test_public_pages_content.py` and
    `test_public_pages_render.py`. It must gain the five new keys or roughly every token test
    raises `KeyError` — reading as an unrelated mass failure. Prefer rebuilding it from
    `core.services._DEFAULTS` so this class of breakage cannot recur.
14. **Screenshots**, at phone width, both themes: one of the **fallback paragraph** (the state
    the branch actually ships in) and one of the **table**, which requires a fixture seeding
    three priced plans. ⚠️ Both need `VENDOR_INSTANCE` true, in a **NEW** capture test — follow the
    design-verification precedent (`tests/capture_tabs_panel_rule_screenshots.py` and its
    siblings): `@pytest.mark.e2e`, `live_server`, `@override_settings(...)`, writing to
    `docs/superpowers/screenshots/`.
    ⚠️ **Do NOT put `VENDOR_INSTANCE=True` on `tests/capture_help_screenshots.py`.** That
    script hardcodes a 1280x800 light-only viewport (so it cannot produce phone width in both
    themes anyway) and writes to `core/static/core/img/help/` — the *shipped help
    documentation*. Its `branding`, `sso`, `integrations` and `notifications` captures all clip
    `section.settings`, which contains `nav.settings__tabs`, so enabling the flag there would
    regenerate every committed help image showing schools a "Pricing" tab they do not have.

15. **The overrides-panel filter, both directions.** With the flag **on**, the panel renders
    `len(PAGES) * 2` textareas and a posted `override-for-schools-en` persists (⚠️
    `_page_overrides()` doubles as the *write* loop's iteration set, so the filter silently
    gates saving too). With it **off**, neither the textarea nor the write path exists.
    ⚠️ `test_panel_renders_one_textarea_per_page_per_language`'s hard-coded `== 4` now has a
    hidden dependency on the flag defaulting False — note it there.
16. **The content guards parametrise over the vendor flag as well as `demo_instance`.**
    `{libli:for_schools_link}` makes the vendor flag a *second* configuration axis for the
    shipped files, and with it defaulting False the link-emitting branch is never swept for
    unresolved tokens, tokens-in-attributes or empty paragraphs.
17. **The `CheckConstraint` test wraps its save in `transaction.atomic()`** inside
    `pytest.raises(IntegrityError)`, and asserts nothing afterwards outside a fresh atomic
    block. ⚠️ An `IntegrityError` leaves the surrounding pytest-django transaction unusable, so
    any later ORM call raises `TransactionManagementError` and reads as an unrelated failure.
    There is no existing `CheckConstraint` in this repo for an implementer to copy.
18. **The storage-allowance sentence, both branches:** absent when `storage_allowance_gb` is
    null (which is the shipped default), present with its GB figure when set — in both the
    fallback and table renderings.
19. ⚠️ **resolved-language vs active-language, the mutant that kills `get_language()`.**
    Every other item runs where resolved == active, so a build that ignores the new `lang`
    argument and calls `translation.get_language()` inside `substitute_tokens` passes all of
    them — the spec's longest mechanism section would have zero discriminating coverage. Call
    `substitute_tokens(html, cfg, "en")` inside `with translation.override("pl")` and assert
    the column headers and fourth-tier label come out **English**; then the converse pairing.
    ⚠️ Both strings exist only in the **table** branch, so this needs the priced fixture — or
    else assert on the fallback paragraph's language, which resolves inside the same override.
20. **The Pricing tab gate, both directions.** With `VENDOR_INSTANCE` false, `settings_pricing`
    returns 404 to a POST from a permitted admin and the settings body contains neither
    `?tab=pricing` nor a `plan_1_pupils_min` input; with it true, both are present. ⚠️ Without
    this item nothing guards the spec's strongest gating argument: Testing 12 runs with the
    flag ON, Testing 3 enumerates only public surfaces, and Testing 15 is about
    `_page_overrides()` — so all three stay green on a build where the four tab edits were
    forgotten.
21. **The eight `substitute_tokens` call sites** are updated for the new required `lang`
    argument: `core/public_pages.py`, `tests/test_public_pages.py`'s `render()` helper, and
    six in `tests/test_public_pages_content.py`.

⚠️ Falsify each guard before trusting it: for every test, name the production edit that
keeps it green, and check that edit is not the bug. A 302-shaped assertion on the settings
view would pass on a broken build — #307 proved exactly that.

**i18n:** the `gettext` column headers and fallback strings need `makemessages` +
`compilemessages`. ⚠️ Check each new msgid for a `#, fuzzy` flag (fuzzy is ignored at runtime
and renders English), confirm the `%(currency)s` placeholder survives into both `.po` files,
and regenerate the `.mo` before the PR to avoid a binary conflict on a long-lived branch.

## Risks

- **Publishing a price anchors it.** Raising a published figure is harder than raising a
  quote. Mitigated only by the numbers being editable and by there being no signed school
  yet; accepted deliberately.
- **The page states commercial terms.** Factual claims about hosting, backups and retention
  are verifiable against code; the *legal adequacy* of the terms is not, and needs a human —
  the same caveat #279 attached to the privacy notice. `vat_note_*` in particular is free
  text that nothing validates, which is the point: an incorrect tax position must be fixable
  without a migration.
- **`VENDOR_INSTANCE` is a deploy-time setting**, so turning the page on is a deploy, not a
  settings toggle. Accepted: it is the property that keeps a school from publishing our price
  list.
- **The seeded bands are guesses.** They ship priceless, so they mislead nobody, but they are
  the first thing to revisit when a real school's roll is known.
