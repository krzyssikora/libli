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
one block token and two inline tokens; a trimmed `/getting-started/`; EN + PL for both.

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

Three priced rows plus a fourth "by arrangement" row that is **prose in the markdown, not a
database row** — it has no numbers to store.

### The numbers are not decided here

Every figure is an editable field, set in the Pricing settings tab. The plan seeds ship with
prices left unset, rendering "by arrangement" until Krzysztof fills them in. Nothing in this
spec commits to an amount.

### Measured inputs (prod, 2026-09-06)

Against the mat-pp corpus, which the earlier notes required be **measured, never guessed**:

| | Bytes | Files | Avg |
|---|---|---|---|
| Video | **3.77 GiB (98.4%)** | 256 | 15.1 MiB |
| Images | 0.06 GiB (1.6%) | 970 | 0.06 MiB |
| Total | 3.83 GiB | 1226 | — |

mat-pp is 889 units — a full three-year maths course — in **3.83 GiB**, about **€2.62/year**
to store at €0.057/GB/mo.

Two consequences, both load-bearing for the page:

- **Video is the entire storage story; images are noise.** Even at the documented 2.5×
  derivative multiplier images reach 0.15 GiB against video's 3.77. So the page asks about
  video and folds images into the per-course baseline, exactly as the earlier note
  predicted — now confirmed rather than assumed.
- **Storage cannot be a pricing lever.** A 50 GB allowance is ~13 courses like mat-pp for
  ~€34/year. State it generously so it never becomes friction; the price rides on support.

## Mechanism

### Model

New `PricingPlan` (app: `institution`), three rows seeded by migration:

| Field | Notes |
|---|---|
| `order` | small int, unique; the row key for `update_or_create` |
| `pupils_max` | int, **not null** — the open-ended top band is prose, not a row, so there is no null case to model |
| `annual_price` | `DecimalField`, **null allowed** ⇒ renders "by arrangement". This is the seeded state: the rows ship priceless and the page reads correctly until Krzysztof fills them in |
| `support_hours_per_term` | int |
| `courses_included` | int |
| `video_hours_included` | int |

Three fields on `Institution`, beside #279's `controller_name` group: `currency` (short
code, default `PLN`), `vat_note` (free text — deliberately not a boolean or a rate, so the
tax position can be stated correctly without a migration), `storage_allowance_gb`.

**Plans carry no name.** The row label is the pupil bound, which is a number and therefore
identical in both languages. This removes the need for `name_en`/`name_pl` and is what makes
the EN/PL parity guard below achievable at all.

### Editing surface

A new **Pricing** tab in the institution settings panel. The form declares three fixed
blocks of plan fields and writes them with `update_or_create(order=N)` — the exact pattern
`BrandingForm` already uses for `BrandColor` rows (`institution/forms.py:273`). No formset;
there is none anywhere in `institution/` and this is not the place to introduce one.

⚠️ The new view MUST use `if request.method != "POST"`, not `== "GET"` — see PR #307. Every
other action view in that module now does.

### Rendering

One **block** token, `{libli:pricing_plans}`, and two inline tokens,
`{libli:storage_allowance}` and `{libli:vat_note}`.

⚠️ **Block, not inline, and the two sets must not overlap.** `core/public_pages.py` replaces
a block token *together with its enclosing `<p>`*; substituting a table inline would nest a
`<table>` inside a paragraph. The existing note is explicit that block tokens are absent
from the inline map precisely so a misplaced one renders literally instead of as escaped
markup — so `pricing_plans` goes in `BLOCK_TOKENS` only, and a test asserts it is not in
`INLINE_TOKENS`.

Column headers come from `gettext` in the renderer, not from the markdown, so the table
structure cannot drift between languages. Substitution runs **after** `nh3`, so the table
HTML must be built with `format_html`, following `_demo_notice_html()` — it is reaching the
browser unsanitised.

### Route gating

`/for-schools/` and its footer link are gated on `Institution.demo_instance`.

⚠️ This codebase ships to a school's own box. Without the gate, every school we host
publishes our price list on their own domain. The flag already exists from #279.

## Content

### `/for-schools/` (new)

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
   generates, never disclosure of the shared age key.
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
school's own box: their school's platform, not one they run themselves. Adds one pointer
across, itself gated on `demo_instance`.

## Testing

Load-bearing first:

1. **EN and PL render identical figures.** Render both, extract the numbers, assert equality.
   This is the guard that justifies the token approach, and it goes RED the moment anyone
   reintroduces a price as prose in one language.
2. **`pricing_plans` ∈ `BLOCK_TOKENS` and ∉ `INLINE_TOKENS`.** Asserted explicitly, because
   the separation is what makes a misplaced token fail visibly.
3. **`demo_instance` gating driven both ways** — the route AND the footer link, present when
   on and absent when off. Drive the surfaces, not the flag.
4. A plan with `annual_price=None` renders "by arrangement" — never `None`, never a blank
   cell.
5. Anonymous access to both pages, both languages; `PublicPage` overrides still win.
6. `"{#" not in` the rendered page — the Django single-line-comment trap, shipped five times.
7. The new settings view refuses a non-POST (the #307 contract).

⚠️ Falsify each guard before trusting it: for every test, name the production edit that
keeps it green, and check that edit is not the bug. A 302-shaped assertion on the settings
view would pass on a broken build — #307 proved exactly that.

## Risks

- **Publishing a price anchors it.** Raising a published figure is harder than raising a
  quote. Mitigated only by the numbers being editable and by there being no signed school
  yet; accepted deliberately.
- **The page states commercial terms.** Factual claims about hosting, backups and retention
  are verifiable against code; the *legal adequacy* of the terms is not, and needs a human —
  the same caveat #279 attached to the privacy notice.
- **`vat_note` is free text.** That is the point: an incorrect tax position must be fixable
  without a migration. It also means nothing validates it.
