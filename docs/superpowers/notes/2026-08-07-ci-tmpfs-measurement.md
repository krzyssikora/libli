# CI tmpfs — measured before/after

**Date:** 2026-08-07
**Change measured:** commit `398a2c16`, adding
`--tmpfs /var/lib/postgresql/data:rw,size=2g,mode=1777` to the `postgres`
service `options:` of **both** the `unit` and `e2e` jobs in
`.github/workflows/ci.yml`.
**Plan:** `docs/superpowers/plans/2026-08-07-tuned-test-database.md`, Task 6.

CI does **not** get the durability flags (`fsync=off` etc.) — GitHub Actions
service containers accept no `command:` key — so this captures only the tmpfs
part of the 37× measured locally. The design predicted "roughly neutral".

## Method

Before = median of the last three green `master` runs, per job.
After = median of three attempts of run `31169855551` on branch
`test-suite-speed` (PR #223), taken via `gh run rerun` and read per-attempt
through `/actions/runs/{id}/attempts/{n}/jobs`.

`gh run rerun` creates an *attempt*, not a new run record, so `gh run list`
still reports one run; the per-attempt API is the only way to get three points.

## Results

| job | before draws | before median | after draws | after median | ratio |
|---|---|---|---|---|---|
| `unit` | 121, 122, 134 | **122 s** | 121, 123, 124 | **123 s** | 1.01× |
| `e2e` | 511, 518, 555 | **518 s** | 471, 480, 987 | **480 s** | 0.93× |

Rule: keep if `median_after <= median_before * 1.05`.

- `unit`: 123 ≤ 128.1 → **KEEP**
- `e2e`: 480 ≤ 543.9 → **KEEP**

Both kept; no revert performed. Postgres started cleanly on tmpfs in every
attempt — the PGDATA permissions/init edge case the plan warned about did not
occur.

## The honest reading

**This measurement did not detect an effect, and it could not have.** The
noise dwarfs anything the change could plausibly do:

- The `e2e` after-draws span **471 s to 987 s — a 2.1× spread** on byte-identical
  content, same commit, same workflow.
- Before the tmpfs commit even landed, PR #223's own `e2e` run took **686 s**
  against a master median of 518 s — **32% slower for content CI runs
  identically**. That is pure runner-allocation variance.

So `e2e`'s apparent 7% median improvement is not evidence of a gain, and the
987 s outlier is not evidence of harm. Both sit inside the runner's normal
range. `unit` at 1.01× is as close to "no change" as the instrument can
report.

**Both jobs are kept on the grounds that the change is harmless, not that it
helped.** That is what the 5% tolerance in the decision rule exists to express:
it lets a neutral-but-cheap change stay without requiring proof of benefit.

If a future question needs a real answer here, three draws per arm is too few
against a 2× spread — it would need many more runs, or a lower-variance runner.

## Not measured here

The local speedup (2,881 ms → 78.5 ms per truncate; 1.70× on the 69-test e2e
sample) is a separate result and is unaffected by any of the above — it was
measured on a tuned local server that *does* get the durability flags.
