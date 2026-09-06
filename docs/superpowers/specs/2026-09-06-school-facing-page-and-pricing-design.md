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
  `MediaAsset` row (`courses/models.py:809,812`), so summing `a.file.size` excludes them.
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
| `annual_price` | `DecimalField(max_digits=9, decimal_places=2, null=True, blank=True)` — both arguments are mandatory or Django raises `fields.E132`. Null ⇒ "by arrangement" |
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

#### Validation lives in the form and the database, not in `PricingPlan.clean()`

⚠️ **Django never calls `full_clean()` on `save()`**, and neither of this spec's two write
paths would invoke it: the migration uses the historical model (which has no `clean()` at
all) and the settings form is an `Institution` ModelForm that writes plan rows by field
assignment. A `PricingPlan.clean()` would be dead code, and the test asserting bands are
rejected would have nothing rejecting them. `Institution` and `BrandColor` set the
precedent — neither defines `clean()`; `BrandColor` uses field `validators`.

So:

- **`Meta.constraints`** gets `CheckConstraint(check=Q(pupils_min__lt=F("pupils_max")),
  name="pricingplan_band_is_ordered")` — holds at the database on every write path.
- **The pricing form's `clean()`** rejects bands that overlap, leave a gap, or run
  non-monotonically across the three blocks. That is a cross-row rule no single instance can
  see, and the form is the only place all three are visible at once.

### Vendor gating — a NEW flag, not `demo_instance`

`/for-schools/` is gated on a new Django setting **`VENDOR_INSTANCE`**, read from the
environment variable **`LIBLI_VENDOR_INSTANCE`**, default `False`.

⚠️ Two names, deliberately, following the existing convention: the env var carries the
`LIBLI_` prefix and the setting drops it, as `ALLOW_HTTP_IMAGE_FETCH` and
`GEOGEBRA_API_LOOKUP` already do in `config/settings/base.py`.

⚠️ **It must NOT be `demo_instance`.** That field's help text is *"Adds a warning to the
public pages telling visitors not to enter real pupil data"* (`Institution.demo_instance`)
— a content-warning flag with one existing meaning, consumed by `core/public_pages.py`'s
demo notice and by `views_manage.missing_demo_notice`. Gating on it would (a) stamp "this is
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

- `core/services._build()` gains: `pricing_plans` (a list of plain dicts, already ordered,
  already serialised to primitives), `currency`, `vat_note_en`, `vat_note_pl`,
  `storage_allowance_gb`.
- **`_DEFAULTS` gains matching keys** with fresh-install values: `[]`, `"PLN"`, `""`, `""`,
  `None`. ⚠️ `_build()` returns `dict(_DEFAULTS)` early when there is no `Institution` row,
  and `tests/test_public_pages_config.py::test_bundle_carries_every_new_key_with_NO_institution_row`
  exists to lock exactly that parity. Extend that test's `NEW_KEYS`.
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

⚠️ **There is NO new inline token.** An earlier draft had `{libli:storage_allowance}` while
also stating the allowance sentence is emitted inside the `pricing_plans` block — which
cancel out, leaving a token no markdown ever contains and a guard proving nothing. Resolved
in favour of the block: **the renderer interpolates the allowance directly**, and
`INLINE_TOKENS` is untouched. When `storage_allowance_gb` is null the sentence is omitted.

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
run-on line. It gets the same `_nl2br` (CRLF-normalised) treatment.

#### Language selection

⚠️ **`substitute_tokens` currently takes no language, and the obvious fix is wrong.**
`translation.get_language()` is **not** the same as the page's resolved language:
`core/help.localized_doc_path` falls back to the English base when a `.pl.md` file is absent,
so `resolved == "en"` while the active language is still `pl`. Using `get_language()` would
put the Polish VAT note and Polish column headers on a page whose prose is English.

**Resolution:** `render_public_page` threads its computed `resolved` into
`substitute_tokens(html, cfg, lang)` as a new argument, and both the `vat_note_*` selection
and the `gettext` column headers resolve under that language. This is a signature change to
an existing function; every call site must be updated.

### Rendering the table

Built with `format_html`, following `_demo_notice_html()` — substitution runs **after**
`nh3`, so this value reaches the browser unsanitised.

**Row labels** are `pupils_min`–`pupils_max`, both numbers, hence identical in both
languages. **Plans carry no name**, which is what makes the parity guard achievable.

**The fourth "by arrangement" tier is emitted by the renderer** as a final `<tr>` whose
cells come from `gettext`, with **no database row**. ⚠️ It cannot be prose in the markdown:
the token substitutes a complete `<table>` for its enclosing `<p>`, and markdown outside it
can only produce a sibling paragraph, never a `<tr>` inside the generated table.

**Column headers** come from `gettext`, resolved under the threaded language. ⚠️ The currency
header is **dynamic** — `currency` is an editable field — so it needs *named* interpolation,
not concatenation: `_("Annual price (%(currency)s)") % {"currency": cfg["currency"]}`. The
placeholder must survive into both `.po` files.

**Amount formatting:** `str(Decimal.quantize(2))` with a plain space as the thousands
separator, and the currency in the header rather than beside each amount. No `floatformat`,
no `intcomma`, no locale-dependent formatting — the numeric strings must be byte-identical
across EN and PL for the parity test to be a real comparison rather than a formatting
assertion.

**Mobile:** the `format_html` output wraps the table in `<div class="public-page__scroll">`.
⚠️ **`overflow-x: auto` on the wrapper is NOT sufficient on its own.** `.public-page table`
is `width: 100%` inside a 46rem column, so the table shrinks to the wrapper and the scroller
never engages — every column wraps to one or two characters instead. The rule must be
`.public-page__scroll { overflow-x: auto }` plus
`.public-page__scroll table { width: max-content; min-width: 100% }`. ⚠️ Fixable only in the
renderer: `PUBLIC_PAGE_TAGS` has no `div`, so a markdown-authored wrapper is stripped by nh3
— but the token value is inserted *after* nh3. The privacy notice's existing tables stay
unwrapped; that inconsistency is accepted (they are narrow and already fit).

### Shipped state — no prices yet

⚠️ On merge, every `annual_price` is null. A page of four "by arrangement" rows does not
meet this spec's own stated purpose.

So: when **no** plan has an `annual_price`, `{libli:pricing_plans}` renders **not the table**
but a fallback paragraph. Its full composition, because this is the state the branch actually
ships in and therefore the one most worth pinning:

- the "prices for your school on request" sentence;
- the contact address — ⚠️ **reusing `_inline_values`' existing fallback**
  (`_("the person who runs this site")`) when `cfg["contact_email"]` is blank, rather than
  inventing a second fallback string for the same question;
- the five contract numbers;
- the storage-allowance sentence **is** included (it is independent of price);
- the VAT note **is not** — a tax statement without a price is noise.

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
2. `tests/test_public_pages_content.py` holds a hard-coded `SHIPPED` list of four files and
   parametrises six guards over it. One is
   `test_demo_notice_is_placed_where_the_block_regex_matches`, which asserts
   `"{libli:demo_notice}" in source` — and `for-schools.md` deliberately carries no such
   token. **Resolution: add both new files to `SHIPPED`, and split that one guard** so the
   token-present half runs over a `DEMO_NOTICE_PAGES` subset while the other five
   (unresolved-token, token-in-attribute, empty-paragraph, exactly-one-h1,
   root-relative-link) keep the full sweep. Not adding the files would leave the new page —
   the one that hardcodes `/privacy/`-style links — with zero coverage from the guard that
   checks exactly that.
3. `tests/test_public_pages_settings.py::test_panel_uses_the_coalesced_language_list_not_the_stored_one`
   asserts `body.count('name="override-') == len(PAGES) * 2`. Filtering the gated page out of
   the panel (below) makes that `(len(PAGES) - 1) * 2` with the flag off. **Rewrite the
   expression against the `_page_overrides()`-derived length, or parametrise over the flag.**
   ⚠️ Do NOT relax it to `<=`, which destroys the guard it exists to be.

⚠️ `_page_overrides()` iterates **all** of `PAGES` and is reused as the *write* loop's
iteration set, so a school admin would otherwise see an editable "For schools" box for a
route that 404s on their box. **The overrides panel filters out the gated page when
`VENDOR_INSTANCE` is false**, and `for-schools.md` carries no `{libli:demo_notice}`.

### Settings tab

One more `_action` call — that helper already carries the #307 non-POST contract, so the
Pricing form **must be an `Institution` ModelForm** whose `save()` also writes the plan rows.

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

**Form shape.** `BrandingForm` is the precedent but declares only two extra fields; this
needs 3 rows x 5 fields = 15.

- **Naming:** `plan_<order>_<field>`, e.g. `plan_1_pupils_min`, so the cross-row `clean()`
  can iterate rather than hard-code.
- **Declared** in `__init__` by looping over the rows, not as fifteen class attributes.
- **`initial`** seeded from `PricingPlan.objects.order_by("order")` via
  `self.initial.setdefault`, mirroring `BrandingForm.__init__`. ⚠️ `_settings_context`
  constructs *every* form unbound on *every* settings render, so this query runs on all eight
  tabs — keep it to one `order_by`, no per-row queries.
- **`annual_price` is `required=False`** so the shipped null state can be re-saved without
  inventing a price.
- **`save()`** writes with `get_or_create(order=N)` then field assignment.

⚠️ **The three-row invariant.** The form iterates `PricingPlan.objects.order_by("order")`,
not `range(1, 4)`. A fourth row created out-of-band (shell, a future migration) would
otherwise render on the public page while the settings tab silently ignored it, and the
form's gap/overlap `clean()` would validate a band set that is not the one rendered.
`PricingPlan` is **not** registered in the Django admin, so there is no second write path.

### Migration

`RunPython(seed, RunPython.noop)` — irreversible data migrations cannot be tested. Target the
current graph head (`institution/0011` at time of writing; verify).

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
   presented as *what we agree at signup*, never as calculator inputs.

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
land in the trimmed file, and place the token with prose above it.

## Testing

Load-bearing first.

1. **EN and PL render identical figures.** ⚠️ **Assert `resolved_lang == "pl"` first.**
   `localized_doc_path` falls back to the English base silently when `for-schools.pl.md` is
   absent, so a naive version compares English against English and is green with no Polish
   page at all — the exact "guard that asserts the adjacent thing" shape. Extract amounts
   with an explicit regex over the rendered table and compare the **strings**, which the
   formatting rule above makes legitimate.
2. **`pricing_plans`, `vat_note`, `for_schools_link` in `BLOCK_TOKENS` and NOT in
   `INLINE_TOKENS`**, present in `block_values`, and the new
   `set(_inline_values(cfg)) == INLINE_TOKENS` assert.
3. **Vendor gating driven both ways, over every surface.** ⚠️ There are **two** footers:
   `templates/core/_public_footer.html` (included by `public_page.html` and
   `allauth/layouts/entrance.html`) and a **duplicated link block in
   `templates/core/landing.html`** — `tests/test_public_pages_footer.py` already asserts them
   separately for this reason. Parametrise over the route, both footers and the entrance page.
4. **Fresh install:** the page renders with no `Institution` row — and ⚠️ **asserts the seeded
   plan content is present**, not merely a 200. A 200-only assertion stays green through the
   early-return bug this spec exists to prevent.
5. **A plan with `annual_price=None`** renders "by arrangement". **All prices null** renders
   the fallback paragraph, including the blank-`contact_email` case.
6. **A price edit is visible immediately** — the `core/apps.py` signal, tested by saving a
   plan and re-rendering, not by asserting the signal is connected.
7. **Row order survives an edit** — save the middle band, assert the rendered order.
8. **Band validation, named by layer:** the `CheckConstraint` rejects
   `pupils_min >= pupils_max` at the database; the **form** rejects overlapping, gapped and
   non-monotonic band sets.
9. **Retention figures guarded against the code**, in the style of
   `tests/test_public_pages_guards.py::test_backup_retention_matches_the_stated_periods`.
   ⚠️ That guard works only because it asserts f-strings embedding each constant *inside the
   surrounding prose* — a bare `"30" in notice` is worthless, as its own docstring says. This
   is why Content 5 requires reusing the privacy notices' exact sentences: the existing
   patterns then extend to both new files unchanged.
10. Anonymous access to `/privacy/`, `/getting-started/` and `/for-schools/` (the last with
    the gate **on**; the gate-off case is item 3), both languages; `PublicPage` overrides
    still win.
11. `"{#" not in` the rendered page — the Django single-line-comment trap, shipped five times.
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
    three priced plans. ⚠️ Both need `VENDOR_INSTANCE` true — state whether the capture uses
    `tests/capture_*.py` under `override_settings` or a `live_server` e2e test, since the two
    enable a Django setting differently.

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
