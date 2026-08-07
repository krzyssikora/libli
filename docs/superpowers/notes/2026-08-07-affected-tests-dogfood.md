# Affected-tests dogfood run

**Commit measured:** `f87afd72` (`feat/affected-tests`)
**`--base` used:** `origin/master` (merge-base `00f1e03b021f4d8d7e06c7f04746869656478f5c`)
**Date:** 2026-08-07

## Step 1 — verbatim tool output

```
$ uv run python scripts/affected_tests.py --base origin/master
4 changed path(s) against origin/master (00f1e03b)

unit: 11 file(s)
    # exit code 5 means "nothing selected", not "green"
    uv run pytest tests/test_affected_tests.py tests/test_auth_login.py tests/test_auth_pages.py tests/test_auth_styles.py tests/test_consumption_css.py tests/test_editor_view_toggle.py tests/test_error_page_styles.py tests/test_error_pages.py tests/test_gallery_manage.py tests/test_i18n_error_pages.py tests/test_link_dialog_behaviour.py

e2e: 7 file(s)
    # exit code 5 means "nothing selected", not "green"
    uv run pytest tests/test_affected_tests.py tests/test_e2e_builder_tree_layout.py tests/test_e2e_image_size.py tests/test_e2e_review.py tests/test_e2e_subjects.py tests/test_e2e_unit_nav.py tests/test_link_dialog_behaviour.py -m e2e

unmapped (no rule matched -- check these by hand):
    docs/development/testing.md
    docs/superpowers/plans/2026-08-07-affected-tests-workflow.md
```

## Step 2 — hand-check against the rules

| Input path | Expected | Actual |
|---|---|---|
| `tests/test_affected_tests.py` | test file → unit *and* e2e | present in both lists — confirmed |
| `scripts/affected_tests.py` | Python module → import path + public symbols searched | drove the union that produced both lists |
| `docs/development/testing.md` | `.md` → unmapped | listed under `unmapped` — confirmed |
| `docs/superpowers/plans/2026-08-07-affected-tests-workflow.md` | `.md` → unmapped | listed under `unmapped` — confirmed |

**Outcome: not capped.** unit = 11 files, e2e = 7 files — matches the brief's measured
expectation ("roughly 11 unit / 7 e2e") exactly. `unit_reason`/`e2e_reason` were not
`CAPPED`; both selections rendered as concrete file lists, not a full-run block.

## Step 3 — timing

```
$ uv run python -c "import subprocess,time; t=time.perf_counter(); p=subprocess.run(['uv','run','python','scripts/affected_tests.py'],capture_output=True,text=True); print(f'{time.perf_counter()-t:.1f}s exit={p.returncode}'); print(p.stderr if p.returncode else '')"
1.1s exit=0
```

**1.1 s, well within the 8 s budget**, exit 0 (no crash). Consistent with the brief's
prediction that the work itself is ~0.3 s and the budget is mostly interpreter startup.

## Step 4 — running the emitted commands

Neither selection was a full-run block (`GLOBAL`/`CAPPED`), so guard 1 did not apply to
either command.

**e2e command — collect-only only, per guard 2 (never execute the real e2e run):**

```
$ uv run pytest tests/test_affected_tests.py tests/test_e2e_builder_tree_layout.py tests/test_e2e_image_size.py tests/test_e2e_review.py tests/test_e2e_subjects.py tests/test_e2e_unit_nav.py tests/test_link_dialog_behaviour.py -m e2e --collect-only --verbosity=0
```
Result: **78/166 tests collected (88 deselected)**, **exit 0**. Matches the brief's
measured "78 real e2e tests across 6 browser modules" exactly. This command was
deliberately *not* run for real — only collected.

**unit command — executed for real, per guard 3 (concrete file list, test DB up):**

```
$ uv run pytest tests/test_affected_tests.py tests/test_auth_login.py tests/test_auth_pages.py tests/test_auth_styles.py tests/test_consumption_css.py tests/test_editor_view_toggle.py tests/test_error_page_styles.py tests/test_error_pages.py tests/test_gallery_manage.py tests/test_i18n_error_pages.py tests/test_link_dialog_behaviour.py -q
```
Result: **exit 0**, all tests passed (no `F` in the output), wall clock **~52 s** —
well under the 2-minute budget. The test DB container (`libli-test-db`) was already up
and healthy; no start-up was needed.

Both emitted commands pasted into the shell without a syntax error, so no
`render_commands` defect surfaced — no fix was required this run.

## Step 5 — named test file

```
$ uv run pytest tests/test_affected_tests.py -v
...
88 passed in 13.28s
```

Exactly 88, as expected (no new test was added, since no defect surfaced).

## Step 6 — lint

```
$ uv run ruff check scripts/affected_tests.py tests/test_affected_tests.py
All checks passed!
$ uv run ruff format --check scripts/affected_tests.py tests/test_affected_tests.py
2 files already formatted
```

## False-positive check

The `main`-driven false positives showed up as predicted: the union of candidate files
(15, per the brief's pre-measurement) is dominated by files matching only the bare word
`main`, and `classify` still split that union into the expected ~11 unit / 7 e2e rather
than tripping the cap — confirming the symbol search is noisy-but-still-useful at this
corpus size, exactly as designed.

## Summary

No defect surfaced in Steps 1–4. Tool output matched the brief's pre-measured
expectations on every axis: selection sizes, cap status, e2e collection count, unit
exit code, and timing.
