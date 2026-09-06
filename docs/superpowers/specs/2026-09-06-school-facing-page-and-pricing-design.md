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
   itself"*. That premise is false under the hosting model — Krzysztof hosts, one box per
   school. The page is live and anonymous.
2. There is no page that tells a school what libli costs.

## Scope

**In:** a new `/for-schools/` public page; a `PricingPlan` model and a Pricing settings tab;
three block tokens and one inline token; a trimmed `/getting-started/`; EN + PL for both.

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

| | Size (GB, decimal) | Files | Avg |
|---|---|---|---|
| Video | **4.05 GB (98.4%)** | 256 | 15.8 MB |
| Images | 0.06 GB (1.6%) | 970 | 0.07 MB |
| Total | 4.11 GB (3.83 GiB) | 1226 | — |

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

`PricingPlan.clean()` rejects `pupils_min >= pupils_max`; the **form** additionally rejects
bands that overlap or leave a gap across the three blocks, since that is a cross-row rule no
single model instance can see.

Four fields on `Institution`, beside #279's `controller_name` group:

| Field | Definition |
|---|---|
| `currency` | `CharField(max_length=3, default="PLN")` — an ISO 4217 code, free text not choices, so a non-PLN school needs no migration |
| `vat_note_en` | `TextField(blank=True)` |
| `vat_note_pl` | `TextField(blank=True)` |
| `storage_allowance_gb` | `PositiveIntegerField(null=True, blank=True)` — null ⇒ the allowance sentence is suppressed entirely |

⚠️ **`vat_note` is per-language, and this is forced by the spec's own argument.** The reason
plans carry no name is that only language-neutral values may be stored once. A VAT note is
prose; a single field would print a Polish tax statement on the English page, and the
numeric parity test would stay green while it shipped.

### Vendor gating — a NEW flag, not `demo_instance`

`/for-schools/` is gated on a new Django setting **`LIBLI_VENDOR_INSTANCE`** (env-driven,
default `False`).

⚠️ **It must NOT be `demo_instance`.** That field's help text is *"Adds a warning to the
public pages telling visitors not to enter real pupil data"* (`institution/models.py:131`)
— it is a content-warning flag with one existing meaning, consumed by
`core/public_pages.py`'s demo notice and by `institution/views_manage.py:366`'s
override warning. Gating on it would (a) stamp "this is a demonstration site — do not enter
real pupil data" across our own sales page, (b) publish our price list on any school pilot
box that has the flag on — the exact failure the gate exists to prevent — and (c) silently
delete the page from libli.pl the day the flag is turned off, which is correct for libli.pl
now that it holds the real mat-pp corpus.

A **setting**, not an `Institution` field, because it is a deployment fact rather than a
school-editable preference: a school admin must not be able to toggle it, and it must not
appear in the settings UI.

**Gate behaviour:** a non-vendor box returns **404** from the view — the page genuinely does
not exist there. The flag is read from `django.conf.settings`, so no cache or query is
involved. (⚠️ Do not read `Institution.load()` on a GET render path: it is `get_or_create`,
a write, which `core/services.py` forbids there.)

### Configuration flow — the plan data reaches the renderer through `cfg`

⚠️ `substitute_tokens(html, cfg)` takes exactly one input, and `core/services.py` documents
the bundle as the injectable single source of truth that **never writes**. The renderer must
therefore do **no ORM query of its own** — a query there would also run on every render of
`/privacy/` and `/getting-started/`.

- `core/services._build()` gains: `pricing_plans` (a list of plain dicts, already ordered,
  already serialised to primitives), `currency`, `vat_note_en`, `vat_note_pl`,
  `storage_allowance_gb`.
- **`_DEFAULTS` gains matching keys** with fresh-install values: `[]`, `"PLN"`, `""`, `""`,
  `None`. ⚠️ `_build()` returns `dict(_DEFAULTS)` early when there is no `Institution` row,
  and `tests/test_public_pages_config.py::test_bundle_carries_every_new_key_with_NO_institution_row`
  exists to lock exactly that parity. Extend that test's `NEW_KEYS`.
- **`PricingPlan` is added to the `post_save`/`post_delete` tuple in `core/apps.py`** that
  currently connects `invalidate_site_config` for `(Institution, BrandColor)`. Without it a
  price edit is invisible for up to `CACHE_TTL = 300` seconds — Institution-field edits
  invalidate via the ModelForm save, but plan rows written with `get_or_create`/`save` do not.

### Tokens

| Token | Kind | Value |
|---|---|---|
| `{libli:pricing_plans}` | **block** | the plans table, or the no-prices fallback |
| `{libli:vat_note}` | **block** | the active language's note, `_nl2br`'d; empty string when blank |
| `{libli:for_schools_link}` | **block** | the cross-pointer on `/getting-started/`; empty string off-vendor |
| `{libli:storage_allowance}` | inline | e.g. `50 GB`; see fallback below |

⚠️ **Block, not inline, and the two sets must not overlap.** A block token is replaced
*together with its enclosing `<p>`*; substituting a table inline would nest a `<table>`
inside a paragraph. Block tokens are absent from the inline map precisely so a misplaced one
renders literally instead of as escaped markup.

⚠️ **Both registries must be updated together, or every public page 500s:**

- `substitute_tokens` asserts `set(block_values) == set(BLOCK_TOKENS)` before iterating, so
  adding to the frozenset alone is an `AssertionError` on `/privacy/` too. The three new
  block entries go in **both** `BLOCK_TOKENS` and the `block_values` map.
- The inline pass has **no such assert** — `replace_one` does `values[name]` for any name in
  `INLINE_TOKENS`, so a half-done edit is a `KeyError`. Add `storage_allowance` to
  `INLINE_TOKENS` **and** `_inline_values` (whose docstring says "The six inline token
  values" and must be updated), **and add the missing symmetric assert**
  `set(_inline_values(cfg)) == INLINE_TOKENS` so the next person cannot repeat this.

`vat_note` is a **block** token, not inline, for the reason `controller_address` is: the
inline pass escapes into a text run with no `_nl2br`, so a two-line note would render as one
run-on line. It gets the same `_nl2br` (CRLF-normalised) treatment.

**Degenerate cases**, following the convention that every existing inline token resolves its
empty case explicitly:

- `storage_allowance` with `storage_allowance_gb = None` → the whole sentence is suppressed
  by putting it inside the `pricing_plans` block rather than loose in markdown. The unit
  ("GB") is part of the **token value**, not the surrounding markdown, so Polish word order
  stays in the renderer's control.
- `vat_note_*` blank → empty string, and the block substitution removes the enclosing `<p>`.

### Rendering the table

Built with `format_html`, following `_demo_notice_html()` — substitution runs **after**
`nh3`, so this value reaches the browser unsanitised.

Column headers come from `gettext` in the renderer, not from the markdown, so the table
structure cannot drift between languages.

**Row labels** are `pupils_min`–`pupils_max`, both numbers, hence identical in both
languages. **Plans carry no name**, which is what makes the parity guard achievable.

**The fourth "by arrangement" tier is emitted by the renderer** as a final `<tr>` whose
cells come from `gettext`, with **no database row**. ⚠️ It cannot be prose in the markdown:
the token substitutes a complete `<table>` for its enclosing `<p>`, and markdown outside it
can only produce a sibling paragraph, never a `<tr>` inside the generated table.

**Amount formatting:** `str(quantize(Decimal, 2))` with a plain space as the thousands
separator, and the **currency code in the `gettext` column header**, not beside each amount.
No `floatformat`, no `intcomma`, no locale-dependent formatting — the numeric strings must
be byte-identical across EN and PL for the parity test to be a real comparison rather than a
formatting assertion.

**Mobile:** the `format_html` output wraps the table in a `<div class="public-page__scroll">`
with `overflow-x: auto`, plus a CSS rule. ⚠️ This is only fixable in the renderer:
`core/static/core/css/app.css` styles `.public-page table` at `width: 100%` with no wrapper
inside a 46rem prose column, and `PUBLIC_PAGE_TAGS` has no `div`, so a markdown-authored
wrapper is stripped by nh3 — but the token value is inserted *after* nh3 and can carry one.

### Shipped state — no prices yet

⚠️ On merge, every `annual_price` is null. A page of four "by arrangement" rows does not
meet this spec's own stated purpose.

So: when **no** plan has an `annual_price`, `{libli:pricing_plans}` renders **not the table**
but a short paragraph — "prices for your school on request", with the contact address and
the five contract numbers. The page is honest in both states, and filling the prices is a
release step, not a code change.

### Page registration

| | |
|---|---|
| slug | `for-schools` |
| markdown | `public/for-schools.md`, `public/for-schools.pl.md` (the `<base>.<code>.md` convention) |
| `PAGES` entry | title + `<meta name="description">`, both `gettext_lazy` |
| URL | `core/urls.py`, `path("for-schools/", views_public.for_schools, name="for_schools")` |

⚠️ `_page_overrides()` (`institution/views_manage.py:324`) iterates **all** of `PAGES`, so a
school admin would otherwise see an editable "For schools" box for a route that 404s on their
box — and `missing_demo_notice` would warn that their override lacks `{libli:demo_notice}`.
**The overrides panel filters out the gated page when `LIBLI_VENDOR_INSTANCE` is false**, and
`for-schools.md` deliberately carries **no** `{libli:demo_notice}` token.

### Settings tab

One more `_action` call — that helper already carries the #307 non-POST contract, so the
Pricing form **must be an `Institution` ModelForm** whose `save()` also writes the plan rows
with `get_or_create(order=N)` then field assignment. That is exactly `BrandingForm`'s shape
for `BrandColor` (`institution/forms.py:273`). No formset; there is none anywhere in
`institution/` and this is not the place to introduce one.

Five wiring points, all easy to miss:

1. the `TABS` tuple
2. the `_settings_context` keyword — ⚠️ the ctx_key must be a valid Python identifier
   (`pricing`) because `_action` splats `**{ctx_key: form}`; `settings_public_pages`
   documents this trap for the `public-pages` tab
3. the `_tabs.html` include
4. a new `_pricing_tab.html` partial and its panel div in `settings.html`
5. permission `institution.change_institution`

### Migration

`RunPython(seed, RunPython.noop)` — irreversible data migrations cannot be tested. Seed with
**`get_or_create` keyed on `order`**, never `update_or_create`, so a re-run can never
overwrite a school's edited prices. Target the current migration graph head.

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
   figures already published in both privacy notices.
6. **What happens if you leave** — handover is a key **rotation** under a key the school
   generates, never disclosure of the shared age key (`docs/backup-and-restore.md:305`).
7. **Timeline.**
8. **Plans** — the table, the storage allowance, the VAT note, and the five contract numbers
   presented as *what we agree at signup*, never as calculator inputs.

⚠️ **The timeline does NOT carry a port-25 month.** The earlier note listed it as a standard
step; that is wrong. The settled default is a transactional provider over **port 587, which
Hetzner has never blocked**. Exchange Direct Send is the documented exception. Port 25
appears only as a conditional branch for a school that insists on Direct Send — and even
then the gate is 30 days of account age, not a fee.

### `/getting-started/` (trimmed)

Keeps the sign-in help verbatim — it is correct, and it is what the footer's "Help" link
should reach. Loses the product pitch to `/for-schools/`. Gets an opening that is true on a
school's own box: their school's platform, not one they run themselves. Adds the
`{libli:for_schools_link}` block, which is empty off-vendor.

## Testing

Load-bearing first.

1. **EN and PL render identical figures.** ⚠️ **Assert `resolved_lang == "pl"` first.**
   `core/help.localized_doc_path` falls back to the English base silently when
   `for-schools.pl.md` is absent, so a naive version of this test compares English against
   English and is green with no Polish page at all — the exact "guard that asserts the
   adjacent thing" shape. Extract amounts with an explicit regex over the rendered table and
   compare the **strings**, which the formatting rule above makes legitimate.
2. **`pricing_plans`, `vat_note`, `for_schools_link` ∈ `BLOCK_TOKENS` and ∉ `INLINE_TOKENS`**;
   `storage_allowance` the reverse. Plus the new
   `set(_inline_values(cfg)) == INLINE_TOKENS` assert, and the existing `block_values`
   assert exercised.
3. **Vendor gating driven both ways, over every surface.** ⚠️ There are **two** footers:
   `templates/core/_public_footer.html` (included by `public_page.html` and
   `allauth/layouts/entrance.html`) and a **duplicated link block in
   `templates/core/landing.html:31-32`** — `tests/test_public_pages_footer.py` already
   asserts them separately for this reason. Parametrise over the route, both footers and the
   entrance page; an implementer who edits "the footer" will otherwise miss the landing page,
   which is where an anonymous school visitor actually arrives.
4. **Fresh install:** the page renders with no `Institution` row (the `_DEFAULTS` path).
5. **A plan with `annual_price=None`** renders "by arrangement" — never `None`, never blank.
   **All prices null** renders the fallback paragraph, not an empty table.
6. **A price edit is visible immediately** — the `core/apps.py` signal, tested by saving a
   plan and re-rendering, not by asserting the signal is connected.
7. **Row order survives an edit** — save the middle band, assert the rendered order.
8. **Band validation** — overlapping, gapped and non-increasing bands are all rejected.
9. **Retention figures are guarded against the code**, in the style of
   `tests/test_public_pages_guards.py`: the figures in `for-schools.md` **and**
   `for-schools.pl.md` match `backup.sh`'s `RETAIN_DAILY_DAYS` / `RETAIN_MONTHLY_MONTHS` /
   `MIRROR_PRUNE_DAYS`. Without it, editing `backup.sh` silently turns a commercial page into
   a false statement.
10. Anonymous access to `/privacy/`, `/getting-started/` and `/for-schools/` (the last with
    the gate **on**; the gate-off case is item 3), both languages; `PublicPage` overrides
    still win.
11. `"{#" not in` the rendered page — the Django single-line-comment trap, shipped five times.
12. **The new settings URL name is appended to `ACTION_URL_NAMES` in
    `tests/test_settings_action_method_guard.py`**, not given a fresh test. ⚠️ That file's
    `NON_POST_METHODS` deliberately excludes GET — "including it would let the test pass on
    the broken build" — and a separately written test would almost certainly re-test GET and
    be weaker.
13. A phone-width screenshot of the plans table, checked in both themes.

⚠️ Falsify each guard before trusting it: for every test, name the production edit that
keeps it green, and check that edit is not the bug. A 302-shaped assertion on the settings
view would pass on a broken build — #307 proved exactly that.

**i18n:** the `gettext` column headers and the fallback strings need `makemessages` +
`compilemessages`. ⚠️ Check each new msgid for a `#, fuzzy` flag (fuzzy is ignored at
runtime and renders English), and regenerate the `.mo` before the PR to avoid a binary
conflict on a long-lived branch.

## Risks

- **Publishing a price anchors it.** Raising a published figure is harder than raising a
  quote. Mitigated only by the numbers being editable and by there being no signed school
  yet; accepted deliberately.
- **The page states commercial terms.** Factual claims about hosting, backups and retention
  are verifiable against code; the *legal adequacy* of the terms is not, and needs a human —
  the same caveat #279 attached to the privacy notice. `vat_note_*` in particular is free
  text that nothing validates, which is the point: an incorrect tax position must be fixable
  without a migration.
- **`LIBLI_VENDOR_INSTANCE` is a deploy-time setting**, so turning the page on is a deploy,
  not a settings toggle. Accepted: it is the property that keeps a school from publishing our
  price list.
