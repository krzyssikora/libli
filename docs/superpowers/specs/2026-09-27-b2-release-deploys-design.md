# Release deploys to school boxes — design

Sub-project **B2** of the school hosting model. Decided 2026-09-27 in brainstorming.
B1 (backups + restore, `docs/superpowers/specs/2026-09-03-school-backups-and-restore-design.md`)
is built and rehearsed; this is the next step before a first school goes live.

## Why this exists

Today there is exactly one host. `deploy.yml` builds and publishes an image on every merge
to `master`, then SSHes into the host named by the `SSH_HOST` secret and runs `deploy.sh`,
which resets `/opt/libli` to `origin/master` and pulls `sha-<commit>`. That is the right
behaviour for libli.pl — it is the **canary**, and it should run every merge — and the
wrong one for a school: a school must not receive a version nobody chose, at a moment
nobody chose, that libli.pl has not survived first.

The hosting model (one box per school, operated by Krzysztof) already settled that schools
run **release tags** and libli.pl runs `master`. This work builds that: cutting a release,
deploying a release to one school or all of them, and rolling a school back.

## Goals

1. A school changes version **only** when Krzysztof deploys a named version to it.
2. A school can only ever receive a commit libli.pl has already run green.
3. Rolling a school back is the same action as deploying it, with an older version — and a
   rollback that the database schema cannot survive is refused before anything is touched.
4. One school's failure neither blocks nor hides another's, and a failure is noticed.
5. Works unchanged whether the repo is public or private, and on any GitHub plan.
6. libli.pl's deploy keeps its trigger and target. Three deliberate behaviour changes: per
   D9, `deploy.yml` passes `LIBLI_DEPLOY_EXPECT_SHA=${{ github.sha }}` and a run whose
   commit is no longer master's tip refuses (red) instead of deploying a different commit;
   and two in `deploy.sh` (§3): `LIBLI_IMAGE_TAG` is persisted just before `up` instead of
   before the pull (the pull reads it from the shell), and a failure before `up` restores
   the checkout. Three further additions are no-ops on an ordinary libli.pl run: the
   `unset` of an inherited `LIBLI_IMAGE_TAG`, the `HUP INT TERM` trap, and the `EXIT`
   trap's stderr messages (it prints nothing on success).

## Non-goals

- Automatic fan-out of a release to schools, per-school "hold" flags, staged waves.
- `:vX.Y.Z` **image** tags. A school pulls the `sha-<commit>` image libli.pl already ran;
  the release is a git tag only. (The only use for an image tag would be surviving a GHCR
  retention policy, and none exists.)
- GitHub Environments, per-school SSH keys, per-school healthchecks.
- Making the repo private. B2 only makes the machinery ready for it (§Going private).
- Provisioning automation. A school box is still provisioned by the runbook, by hand.

## Owner decisions (2026-09-27) — verbatim, do not re-open in review

| # | Question | Decision |
|---|---|---|
| D1 | What does pushing a release tag do? | **Nothing by itself.** A school updates only when Krzysztof runs *Deploy release* with a school code (or `all`) and a version. Rollback is the same button with an older version. |
| D2 | May a release be made of a commit libli.pl has not run? | **No — enforced.** The commit must be on `master` and its libli.pl deploy must have finished green; otherwise the release is refused with nothing touched. Hotfix path: merge, let libli.pl deploy, then tag. |
| D3 | Rollback across a database migration? | **Refused, pointing to restore.** If the target version is older and any migration file differs between the two versions, the deploy stops before touching the box and names the files and `docs/backup-and-restore.md`. No override. |
| D4 | How are schools named in GitHub? | **Opaque codes** (`school-01`, `school-02`, …). The code → school mapping stays private with Krzysztof. Nothing in the repo, run logs or UI names a customer. |
| D5 | Where does the school inventory live? | **One repo secret**, not GitHub Environments, so it works on any plan and on a private repo. (Krzysztof expects to have Pro; moving to Environments later is a separate, small change.) |
| D6 | How does a box get the files that go with the image? | **A git checkout on every box, at the release tag** (approach 1 of 3). Keeps B1's backup manifest (`git rev-parse HEAD`) and `restore.sh`'s checkout-matches-image check working unchanged. Each box needs its own read-only deploy key once the repo is private. |
| D7 | Version numbering | **`vX.Y.Z`**, validated by *Cut release*. The first release is **`v1.0.0`**. |
| D8 | Proof B2 is done | A **rehearsal on a throwaway box** (`school-00`) — Krzysztof provides the box and a DNS name. |
| D9 (2026-09-27, after spec-review round 14) | `deploy.yml` deploys whatever master is when its job starts, so a green `deploy` job for commit X does not prove libli.pl ran X (a later merge, or "Re-run failed jobs" after one, deploys Y under X's run). What should libli.pl do? | **Option A: libli.pl's deploy refuses when master has moved on.** `deploy.yml` passes `LIBLI_DEPLOY_EXPECT_SHA=<the run's own commit>`; a run whose commit is no longer master's tip fails red instead of deploying another commit, and the newer run deploys the newer commit. Accepted cost: when merges land close together the older run goes red and the deploy alert fires once, clearing when the newer run goes green. Rejected: deploying the run's own commit (a re-run could roll libli.pl back across migrations) and a timestamp-comparing guard. |

## Design

### Overview

```
merge to master ──► deploy.yml (UNCHANGED) ──► libli.pl on sha-<commit>     (the canary)

Cut release     (button: commit, version) ──► canary guard ──► push git tag vX.Y.Z

Deploy release  (button: school|all, version)
   └─ per school, in parallel, fail-fast off:
        canary guard on the tag ─► read box's LIBLI_IMAGE_TAG ─► migration guard
        ─► ssh: fetch tag, checkout, LIBLI_DEPLOY_REF=vX.Y.Z bash deploy.sh
   └─ summary table + one healthchecks.io ping for the whole run
```

### 1. `cut-release.yml` (new, `workflow_dispatch`)

Inputs: `version` (required), `commit` (optional; default = current tip of `master`).

Checkout with `fetch-depth: 0` (the ancestry and containment checks below need full history
and tags; the default depth-1 clone makes `merge-base --is-ancestor` misreport).

1. Validate `version` against `^v[0-9]+\.[0-9]+\.[0-9]+$` and that the tag does not already
   exist. Resolve `commit` (passed via `env:`, never `${{ }}` in `run:`) with
   `git rev-parse --verify "$COMMIT^{commit}"` and use only the resulting 40-hex sha from
   here on — a short sha or `master~1` would otherwise never match a run's `head_sha` and be
   refused with a misleading message. Refuse otherwise.
2. Run the **canary guard** (§4) on `commit`. It returns the id of the `deploy.yml` run that
   proves the commit.
3. **B2-containment check** — refuse a commit whose `deploy.sh` predates B2. Tested on the
   property itself, not a proxy: `git grep -q LIBLI_DEPLOY_REF <commit> -- deploy.sh`, the
   same for `LIBLI_DEPLOY_EXPECT_SHA`, **and**
   `git cat-file -e <commit>:scripts/release/migration_guard.sh` (the by-hand path runs the
   guard copy at every tag it touches, §3). A tag
   on an older commit would check out a `deploy.sh` that ignores `LIBLI_DEPLOY_REF` and
   resets the school to `master` — so every tag must be deployable by this machinery.
4. Set a tagger identity (`github-actions[bot]` /
   `41898282+github-actions[bot]@users.noreply.github.com`) — a fresh runner has none and
   `git tag -a` would die after every guard passed. Create an annotated tag `version` on
   `commit` whose message carries one line `canary-run: <run-id>`, and push it. `permissions: contents: write, actions: read`.
   A tag pushed with `GITHUB_TOKEN` triggers no workflow, which is exactly D1.

A tag pushed by hand, bypassing this workflow, is still caught: *Deploy release* re-runs the
canary guard and the B2-containment check on every deploy; a **lightweight** tag
(`git cat-file -t refs/tags/<v>` ≠ `tag`) is refused with its own message before any
parsing — reading `%(contents)` of a lightweight tag returns the commit's message — and an
annotated tag with no `canary-run:` line is refused. One guard, two callers.

### 2. `deploy-release.yml` (new, `workflow_dispatch`)

Inputs: `school` (a code, or `all`), `version` (a tag).

**Master-only.** Every job in both new workflows carries
`if: github.ref == 'refs/heads/master'`, as `deploy.yml` does. `workflow_dispatch` can run a
workflow file from any branch, and the guard scripts come from that branch's checkout — so
without this, a branch with a weakened guard could deploy to schools with `SCHOOLS_SSH_KEY`.

**Job `plan`** (checkout with `fetch-depth: 0`, for the same reason as `cut-release`): reads
`SCHOOL_HOSTS`, validates its shape, resolves `school` into a list of codes (`all` = every
key; a single code must be a key — an unknown code is refused, never auto-created; an
empty resolved list is refused), and emits it as the matrix. **Validates `version`
before any use**: the regex `^v[0-9]+\.[0-9]+\.[0-9]+$` runs before any step that uses the
value (including the checkout); right after the checkout, and before any other use, it
must resolve as a tag (`git rev-parse --verify refs/tags/<version>`) — a sha or `master~3` is refused, and
since the value is later spliced into a root shell on the box, nothing unvalidated may
reach step 6. Then peels the tag to its commit
(`git rev-parse <version>^{commit}` — an annotated tag's own object sha is not a commit and
matches no workflow run), and runs the canary guard (§4, using the tag's `canary-run:` id)
and the B2-containment check once, before any school job starts.

**Job `deploy`** (matrix over codes, `fail-fast: false`,
`concurrency: deploy-school-<code>`, `cancel-in-progress: false` — same reasoning as
`deploy.yml`: a deploy interrupted mid-migrate is worse than one that finishes late):

1. Check out the repo with full history and tags (`fetch-depth: 0`) — the migration guard
   needs both commits. The target sha is `plan`'s output `target_sha` (the peeled tag);
   legs use it and do not re-peel.
2. **Read this leg's entry**: the matrix carries only codes, and GitHub will not pass
   masked values through job outputs, so each leg reads `SCHOOL_HOSTS` through
   `inventory.sh` for its own code. The extraction prints nothing. **Steps 2 and 3 are one
   workflow step**: the `::add-mask::` lines are emitted before anything is written to
   `$GITHUB_ENV` / `$GITHUB_OUTPUT`. A value handed to a *later* step through either
   appears in that step's collapsed `env:` header, which GitHub prints before the step's
   own commands run — so a mask registered in a separate later step would come too late.
3. **Mask first, before any command that could print them:** `::add-mask::` the entry's
   `host` and `domain`. Values extracted *from* a JSON secret are not auto-masked by GitHub,
   and `deploy.sh`'s output (the `/healthz/` curl, `caddy validate`, compose) streams back
   into the log and names the school's domain — D4 depends on this mask. Then write
   `SCHOOLS_SSH_KEY` to a key file and `known_hosts` as one line `<host> <host_key>`
   (port 22 assumed; the inventory has no port field).
4. **Pre-flight over SSH.** `.env.production` holds every box secret (`DJANGO_SECRET_KEY`,
   the DB password, `LIBLI_GHCR_TOKEN`, SMTP credentials), so **the file is parsed on the
   box and never copied**: `scripts/release/preflight.sh`, sent over `ssh` on stdin
   (`bash -s`), with `<version>` and `<target_sha>` as **positional arguments** (as for
   `remote_deploy.sh`), applies both read rules there and prints exactly two lines —
   `image_tag=<validated value>` and `channel=release` — or one line `refuse: <reason>`
   naming the field, exiting non-zero. The workflow step and the fixture tests share that
   interface. A `--read-only` mode prints only the `image_tag=` line (or `refuse:`) and
   skips the fetch; step 7's `now_on` read uses it. Refusal messages never echo a line of the file. Read the
   box's current version from `LIBLI_IMAGE_TAG` in
   `/opt/libli/.env.production` (see §3 — it names the newest code that may have run against
   this database, which git `HEAD` does not); read `LIBLI_DEPLOY_CHANNEL` from the same file
   **with the same detection rule `deploy.sh` uses** (§3's anchored, `export`-aware regex;
   no shared sourced helper — `deploy.sh` runs from a temp file at the target version and
   would source the *current* checkout's copy — so a test feeds both implementations the
   same fixtures) and **refuse unless it is exactly `release`** — a school box with the line missing or
   mistyped would otherwise silently lose the channel catch and the embedded guard on every
   by-hand run while the workflow path kept deploying green. Then fetch the tag
   **forced** (`git fetch origin '+refs/tags/<version>:refs/tags/<version>'`, with the same
   3-attempt / 5 s retry as `deploy.yml`, because of the documented anonymous-401 flake)
   and **refuse unless the box's `git rev-parse '<version>^{commit}'` equals `plan`'s
   `target_sha`**. A tag deleted and re-cut under the same name would otherwise leave the
   box resolving `<version>` to a commit `plan` never canary-checked (a non-forced fetch
   refuses to clobber a local tag). A box that still cannot fetch fails
   here — site untouched — with a message naming both causes: a transient GitHub refusal
   (re-run) or a missing/broken deploy key (runbook §9).
5. **Migration guard** (§5) with the box's version as *current* and the peeled tag as *target*.
6. **Deploy over SSH.** `bash` must parse the `deploy.sh` the target version ships (as with
   `deploy.yml`'s bootstrap), but the bootstrap must **not** move the checkout: anything that
   moves `HEAD` outside `deploy.sh`'s lock can race `backup.sh`, which reads `HEAD` and
   `LIBLI_IMAGE_TAG` under that lock, and a refusal inside `deploy.sh` would then leave
   `HEAD` ahead of the image. So the bootstrap extracts the target's script and runs it,
   and only `deploy.sh` touches the checkout. The bootstrap lives in
   `scripts/release/remote_deploy.sh` (sent over `ssh` on stdin, so it is testable) and:
   Requirements (the plan writes the shell; these are what the tests pin):
   1. `set -e`, `cd /opt/libli`; the validated `<version>` and `<target_sha>` arrive as
      **positional arguments** to `remote_deploy.sh`, never spliced into nested quoting.
      Extract `refs/tags/<version>:deploy.sh` to a `mktemp` file; choose unique status and
      pid file paths under `/var/lib/libli-deploy/` (step 4); **create the log file in the session before starting the run**
      (`/var/log/libli-deploy/<utc>-<version>.log`, directory created if missing).
   2. Start the run **detached** (§3 *A dropped SSH session*) under `setsid nohup`, handing
      the script path, status path, ref and expected sha to the detached wrapper as
      **positional arguments** (or exported variables) — a single-quoted `bash -c` body
      cannot see the session's unexported variables. The wrapper is started with
      **`</dev/null >>"$log" 2>&1`** — no fd shared with the session. `remote_deploy.sh`
      itself arrives on the ssh channel's stdin (`bash -s`), so an inherited stdin lets any
      child swallow the rest of the script; `setsid nohup` redirects neither stdin nor a
      non-terminal stdout, and an inherited stdout/stderr both keeps sshd's session open
      after the run and brings back the `SIGPIPE` death when the session drops. The wrapper
      runs `deploy.sh` with
      `LIBLI_DEPLOY_REF`, `LIBLI_DEPLOY_EXPECT_SHA` and `LIBLI_DEPLOY_SKIP_FETCH=1`, writes
      its exit status to the status file, and removes the temp script — never a trap in the
      session, which could delete it while the detached run still needs it.
   3. **The followed pid is the wrapper's own**, which the wrapper writes (`$$`) to a pid
      file the session waits for (**at most 30 s**; if it has not appeared the session exits
      1 with "the detached run has not reported its pid after 30 s — it may still start;
      check the box's `LIBLI_IMAGE_TAG` and the deploy log", the same reading as a
      timed-out leg: the wrapper was launched and may merely be late) and reads — never `$!` of `setsid`, which forks when its
      caller leads a process group and so can name a process that exits at once. The
      wrapper writes the status file as its **last** act and exits immediately. The session
      follows the log from its first line until that pid exits
      (`tail -n +1 --pid=<pid> -f` on the pre-created file — plain `tail -f` starts at the
      last 10 lines and exits at once on a not-yet-created file), then exits with the
      recorded status and removes the status and pid files. An absent status file → exit 1.
   4. **Leftovers:** `remote_deploy.sh` creates `/var/lib/libli-deploy/` and
      `/var/log/libli-deploy/` if missing (`mkdir -p`, mode 700) — neither exists on a
      freshly provisioned box. Status and pid files are created in the first; each
      `remote_deploy.sh` run deletes any it finds there older than 1 hour at start (left by
      a session that dropped). Deploy logs name the school's domain, so they are an
      unmasked copy on the box: at start, **before** creating its own log,
      `remote_deploy.sh` deletes all but the newest 19 in `/var/log/libli-deploy/`, so with
      the new one at most 20 exist. Nothing lingers in the
      wrapper, so the session returns as soon as `deploy.sh` finishes.
   `deploy.sh` re-checks the peeled ref against `LIBLI_DEPLOY_EXPECT_SHA` under its lock
   and refuses on a mismatch.
   **The `remote_deploy.sh` → `deploy.sh` interface is a frozen cross-version contract**,
   like the guard's: `remote_deploy.sh` always comes from master while the `deploy.sh` it
   runs comes from the target tag, often an older release. The three names
   `LIBLI_DEPLOY_REF`, `LIBLI_DEPLOY_EXPECT_SHA`, `LIBLI_DEPLOY_SKIP_FETCH` and their
   meanings never change; a rename means adding a new name while keeping the old one. Any
   **new** safety variable a future `remote_deploy.sh` passes is unenforced on a rollback to
   a release that predates it — so `remote_deploy.sh` refuses when the target `deploy.sh`
   does not mention a variable it requires (the same `git grep` technique as
   B2-containment), and B2-containment itself requires `LIBLI_DEPLOY_EXPECT_SHA` as well as
   `LIBLI_DEPLOY_REF`. `<version>` is interpolated only after `plan` validated it
   (§2 `plan`), and single-quoted. `mktemp`, not a fixed path, because this runs outside
   the lock and a concurrent run could overwrite a shared file mid-read. `deploy.sh`
   already `cd`s to the absolute `APP_DIR`, so running it from a temp file is safe.
7. Record the outcome: write `outcome-<code>.json` (`code`, `run_attempt`, `from` =
   pre-flight's reading
   or `unknown` if pre-flight did not produce one, `to`, `result`, `now_on` = the box's
   `LIBLI_IMAGE_TAG` read after the deploy via `preflight.sh --read-only` — the same on-box
   read rule, never a `grep`/`cat` of the file — or `unknown` on any refusal). The `now_on` ssh
   read happens **only if the mask step (3) succeeded**; otherwise `now_on` is `unknown`
   with no connection attempted — an ssh with no mask in place would print the host in its
   connection errors (D4)
   and upload it as a per-leg artifact with `overwrite: true` — "Re-run failed jobs" uploads
   the same name again within the run, and without it the upload fails and `report` reads a
   stale result. `result` is `success` iff the deploy step's (step 6) `outcome == 'success'`,
   and `failure` otherwise, including when an earlier step (mask, pre-flight, guard) failed
   and step 6 was skipped. Matrix legs cannot publish distinct job outputs, so artifacts are
   the mechanism. The step runs `if: always()`.

Plain `ssh` rather than `appleboy/ssh-action`: two of the steps need the remote's output,
and a script in `scripts/release/` is testable where an action's inputs are not. `set -e` is
the first remote line, for the reason documented in `deploy.yml`. Every `ssh` call passes
`-o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=30 -o ServerAliveCountMax=4
-o StrictHostKeyChecking=yes -o UserKnownHostsFile=<the file written in step 3>` — the
last two are what make §6's pinned `host_key` actually enforced (never `accept-new` or
`no`)
(a key-auth failure or dead box fails fast and legibly instead of hanging), and the
`deploy` job has `timeout-minutes: 45` — `deploy.yml`'s `command_timeout: 30m` for the
deploy itself, plus headroom for the checkout, the pre-flight retries and `deploy.sh`
waiting on `flock` behind a running `backup.sh` (it waits by design). Without a timeout a
hung pull holds the runner and the school's concurrency group for GitHub's 6-hour default.
A timed-out leg is not proof of a failed deploy — the run is detached and may finish on
the box; runbook §9 says to read the box's `LIBLI_IMAGE_TAG` and the deploy log.

**Permissions, least privilege, per job:** `plan` — `contents: read, actions: read` (the
canary guard reads runs and jobs); `deploy` — `contents: read`; `report` —
`contents: read, actions: read` (artifact download). The workflow sets `permissions: {}` at
the top so nothing inherits the repo default.

**Job `report`** (`needs: [plan, deploy]`,
`if: always() && github.ref == 'refs/heads/master'` — one expression: a job has exactly one
`if:`, the master gate alone reintroduces the implicit `success()` and skips `report`
precisely when `plan` refused or a leg failed, and two `if:` keys are a duplicate YAML key
that a parser silently collapses to the last): downloads every `outcome-*` (a download
that finds **zero** artifacts — a `plan` refusal, or every leg dead before step 7 — must
not fail the job, since those are exactly the cases whose `/fail` ping matters most)
artifact and writes a step-summary table — one row per code from the `plan` matrix, ✅/❌,
from, to, now on — a row whose artifact carries an earlier `run_attempt` is marked
"(attempt N)". "Re-run failed jobs" legitimately relies on earlier attempts' ✅ artifacts;
after "Re-run all jobs" a leg cancelled in the new attempt shows its earlier row so
marked, and the runbook says a marked row is not this attempt's result. **A marked row
never counts toward the plain-URL ping** — only ✅ artifacts whose `run_attempt` equals the
current attempt do. So after "Re-run failed jobs" the ping is `/fail` even though every
row may be ✅; the runbook says that is expected, and that dispatching a fresh
*Deploy release* (a same-version pass for schools already on it) gives a clean ping. A
code with **no**
artifact (leg cancelled or crashed before writing) is a
❌ row reading "no result". It pings `HEALTHCHECKS_SCHOOL_DEPLOY_URL`: the plain URL **only
if** `needs.plan.result == 'success'`, the plan holds at least one code, and every planned
code has a ✅ artifact; `/fail` in every other case — in particular a `plan` refusal (canary,
containment, bad version, bad inventory), which has no matrix and would otherwise make
"every planned code succeeded" vacuously true. On a `plan` refusal the guard scripts' own
refusal line is written by `plan` to its step summary; `report` adds one row, "plan refused
— see the plan job", and no per-school rows.

GitHub keeps only **one pending** run per concurrency group: a third dispatch touching the
same code cancels the one still waiting, whose leg then reports "no result". The runbook
says so — a "no result" ❌ can mean "superseded by a later dispatch". Same rules as `deploy.yml`'s reporter:
unset secret → one line, exit 0; a failed ping never fails the run. Values reach the shell
via `env:`, never `${{ }}` inside `run:`.

### 3. `deploy.sh` — one new input, and `LIBLI_IMAGE_TAG` persisted later

- `LIBLI_DEPLOY_REF` (env). Unset → today's sync exactly: fetch (unless
  `LIBLI_DEPLOY_SKIP_FETCH`), `git reset --hard origin/master`. Set → fetch that ref (unless
  skip; the existing `fetch_master` retry loop is generalised to fetch any ref, same
  attempts and delay), `git checkout --force --detach <ref>`, `git reset --hard <ref>`.
  Exact fetch forms: `git fetch origin '+refs/tags/<ref>:refs/tags/<ref>'` for a tag
  (forced, so a re-cut tag replaces a stale local one; a bare `git fetch origin <tag>`
  writes only `FETCH_HEAD` and the checkout that follows can fail), `git fetch origin <sha>`
  for a sha. Tags are peeled (`<ref>^{commit}`) before any comparison.
  The unset-ref path keeps today's `git checkout master` before its reset, which is also
  what re-attaches a libli.pl checkout left detached by a by-hand `LIBLI_DEPLOY_REF=<sha>`
  run — so libli.pl's next ordinary deploy returns it to `master`.
- **Environment hygiene:** `deploy.sh` `unset`s any inherited `LIBLI_IMAGE_TAG` at the top
  and sets it only per command for the pull. Otherwise an exported value left in root's
  shell (from a manual first boot, say) would override the freshly written file at `up` —
  by the same shell-over-env-file precedence the pull relies on — and the box would run an
  image that disagrees with both the persisted tag and `HEAD`.
- **A dropped SSH session does not stop the deploy.** A non-pty `ssh host cmd` whose client
  dies (job timeout, manual cancel) sends the remote command no signal; the command runs on
  with closed output and dies of `SIGPIPE` at its next write — mid-pull or mid-`up`, with no
  `EXIT` trap. So the §2 step 6 bootstrap starts `deploy.sh` **detached** from the session;
  the log path, pid hand-off, status file and `tail` form are defined there, once. If the
  session drops, the deploy completes on the box exactly as if it had not —
  the behaviour `deploy.yml` already documents for a severed appleboy session ("the host
  carries on"); the leg reports ❌, and the next run's pre-flight reads the true outcome from
  `LIBLI_IMAGE_TAG`. `deploy.sh` additionally traps `HUP INT TERM` into a non-zero exit for
  a by-hand run killed at a terminal, and every message the `EXIT` trap prints goes to
  stderr with write errors ignored, so the trap itself cannot die of a closed pipe.
- **`LIBLI_IMAGE_TAG` is written to `.env.production` only immediately before `compose up`,
  not before the pull as today.** The pull runs with the new tag in the shell environment
  (`LIBLI_IMAGE_TAG=<new> compose pull` — compose interpolation prefers the shell over
  `--env-file`). This gives the persisted value one meaning on every box: **the newest code
  that may have run against this database** (once `up` starts, the new image's entrypoint
  may run `migrate`). The migration guard reads it as *current* (§2 step 4); B1's
  `backup.sh` already records it as the manifest's image.
- **Any exit before `up`** — a refusal (channel catch, ref format, embedded migration
  guard), a failed fetch/checkout/reset, Caddyfile validation, the missing-`LIBLI_GHCR_TOKEN`
  `exit 1`, GHCR login, pull — now also puts the checkout back to the commit named by the
  persisted `LIBLI_IMAGE_TAG`. Mechanism: an **`EXIT` trap** installed right after
  `flock` and the `LIBLI_IMAGE_TAG` read (§5), keyed on a `reached_up` flag set just before `compose up`; on a non-zero exit with
  the flag unset it restores — **only if `HEAD` differs from the restore target**, so an
  early refusal (channel, ref format, embedded guard) that never moved `HEAD` does not
  force-checkout and wipe a hand-edited tracked file (e.g. a Caddyfile patched during an
  incident); "nothing on the box has changed" then holds. Not an `ERR` trap: without `set -E` an `ERR` trap does not
  fire inside functions (`compose pull` runs inside `compose()`), and it never fires on an
  explicit `exit 1`. Restore form: `git reset --hard <sha>` when `HEAD` is on a branch
  (libli.pl's `master`), `git checkout --force --detach <sha>` when detached (a
  release-channel box). Without the restore the site runs the old image while `HEAD` names
  the new commit, so the next nightly backup would record a `git_sha` that disagrees with
  its own image — the mismatch `restore.sh` refuses. On a box with no persisted tag (never
  deployed — libli.pl before this change first runs; a school box is first-booted by hand,
  §9) the trap only reports. This changes libli.pl's behaviour on those failures
  (checkout restored instead of left ahead); everything else on libli.pl is unchanged.
  Known and **not** fixed here: `deploy.yml` still resets libli.pl's checkout before
  `deploy.sh` takes the lock, so a libli.pl deploy landing mid-backup can race `backup.sh`'s
  two reads. Pre-existing, libli.pl only (school boxes use the §2 step 6 bootstrap, which
  does not move the checkout); a separate follow-up.
- **Channel safety catch:** if `.env.production` contains `LIBLI_DEPLOY_CHANNEL=release` and
  `LIBLI_DEPLOY_REF` is unset, refuse before the fetch — nothing on the box has changed.
  "Present" is detected by a line matching `^\s*(export\s+)?LIBLI_DEPLOY_CHANNEL\s*=` —
  not by the existing `env_value`, which returns an empty string for a missing line, an
  empty value, and an indented or `export`-prefixed line alike. A present line whose value
  is not exactly `release` (empty, `relase`, `Release`, trailing space, or an unanchored
  form) is refused outright; only an **absent** line means "libli.pl". A commented line
  mentioning the key (`^\s*#.*LIBLI_DEPLOY_CHANNEL`, e.g. disabled during an incident)
  counts as present-but-invalid, not absent — otherwise a by-hand run would silently reset
  the school to `master`.
  Without this, running `bash deploy.sh` by hand on a school box — the natural
  manual-rollback reflex — would silently move the school onto `master`. libli.pl has no
  channel line and is unaffected.
- **Accepted refs.** On a `release`-channel box: only `^v[0-9]+\.[0-9]+\.[0-9]+$` tags, and
  `deploy.sh` itself runs the migration guard with the persisted tag as *current* and the
  peeled ref as *target* — so D3 holds on the by-hand path too. It runs **both** copies —
  `git show <current>:scripts/release/migration_guard.sh` and the same at `<target>`, each
  executed with `bash` — and refuses if either refuses. On a downgrade the target is the
  older release, whose guard lacks any check added since; running only the target's copy
  would drop exactly the newest protections from the rollback they exist to stop. (The
  workflow path runs master's copy, which is newer than both.) Every tag contains the guard
  (B2-containment, which checks the guard file's presence too), so both copies always
  exist. The box's clone holds the full history both commits need.
  **The guard's interface is a frozen cross-version contract**, because future `deploy.sh`
  versions run old guard copies and vice versa: `migration_guard.sh <current-sha>
  <target-sha>`, exit 0 = pass, non-zero = refuse, reasons on stderr; self-contained — it
  sources nothing and needs only `bash`, `git` and coreutils (no `jq`). Changing any of that
  needs a new script name, never an edit — and `scripts/release/migration_guard.sh` itself
  stays present and runnable under that name in every future commit (checks may be added,
  the file is never removed), because `deploy.sh` runs it at old commits. A missing copy at
  either commit refuses.
- **The whole body is one function, called as `main "$@"; exit` on the file's last
  line.** bash reads a script file as it executes, and the by-hand path's checkout rewrites
  `/opt/libli/deploy.sh` under the running process — cross-version by-hand runs (a school
  rollback, libli.pl's new §8 recipe) are now documented, so this is no longer latent.
  A function is parsed completely before it runs, and `exit` sits on the same line as the
  call, so nothing is read from the file after the checkout. (The workflow path already
  runs a `mktemp` copy; `deploy.yml` resets before invoking.) The logic that runs on the
  by-hand path is therefore the *current* checkout's `deploy.sh`, which is acceptable: it
  runs both guard copies, and the compose file and Caddyfile it uses are read after the
  checkout.
- **Fixed order inside `deploy.sh`:** `flock` → channel line parsed (absent / exactly
  `release` / present-but-invalid; the refusal itself stays at the channel catch) →
  `LIBLI_IMAGE_TAG` read rule (§5; a present-but-invalid channel line uses the
  release-channel column — safe either way, since the channel catch refuses it before any
  fetch) → `EXIT` trap installed → channel catch →
  ref-format check → fetch (unless `LIBLI_DEPLOY_SKIP_FETCH`) → peel target →
  expected-sha check (when `LIBLI_DEPLOY_EXPECT_SHA` is set: on the ref path against the
  peeled ref, on the unset-ref libli.pl path against the local `origin/master` ref **as it
  stands, whether or not this run fetched** — `deploy.yml` always passes
  `LIBLI_DEPLOY_SKIP_FETCH=1`, so on libli.pl the ref is the one its bootstrap fetched, and
  a check placed inside the fetch branch would never run there. Per D9 a mismatch means
  master moved on, and the run refuses with "superseded by <sha>; the newer run deploys
  it") → embedded migration guard
  (release channel) → checkout/reset → Caddyfile → GHCR token + login →
  pull (tag in the shell env) → **write `LIBLI_IMAGE_TAG` to `.env.production`, then set
  `reached_up`, then `compose up`**, with nothing that can fail between setting the flag and
  `up`. The guard must come after the fetch — on the by-hand path the target tag may not be
  in the clone until then — and before the checkout, which would already have moved `HEAD`.
  The write precedes the flag because a write that fails with the flag unset is a pre-`up`
  exit and restores correctly, while a flag set before a failed write would leave `HEAD`
  ahead of the tag with no restore. The by-hand path does **not** re-run the canary guard (the box has no
  GitHub API access); D2 holds there because a tag is only created through *Cut release*,
  and the runbook says so. On a box with no channel line (libli.pl): a `vX.Y.Z` tag or a
  full 40-hex sha, unguarded — today's by-hand rollback, unchanged in spirit. Anything else
  is refused.

### 4. Canary guard — `scripts/release/canary_guard.sh <commit> [<run-id>]`

`<commit>` is always a commit sha — callers peel tags (`<tag>^{commit}`) before calling.

**What "libli.pl ran X" is measured by:** a `deploy.yml` run for X whose `deploy` job
succeeded. That is only sound because of D9 — `deploy.yml` passes
`LIBLI_DEPLOY_EXPECT_SHA=${{ github.sha }}` and `deploy.sh` refuses when `origin/master`
is not that commit.

**How the value crosses SSH.** libli.pl deploys through `appleboy/ssh-action`'s `script:`,
where a step-level `env:` value reaches the remote only if also listed in the action's
`envs:` — so `env:` alone would leave it unset on the box and D9 silently off. The
remote script therefore carries it **inline**: `export
LIBLI_DEPLOY_EXPECT_SHA='${{ github.sha }}'` (a 40-hex value Actions controls, so the
usual "never `${{ }}` in a script" rule, which exists for secrets and untrusted input,
does not apply), followed by a fail-closed check
(`[[ $LIBLI_DEPLOY_EXPECT_SHA =~ ^[0-9a-f]{40}$ ]] || exit 1`) before `bash deploy.sh`,
which inherits the export. Given that, so a green `deploy` job can only have deployed its own `head_sha`
(including on "Re-run failed jobs" after a later merge, which now refuses). The guard
relies on that `deploy.yml` change; a wiring test pins it.

Passes only when **all** hold for the `deploy.yml` run that proves it:
- `<commit>` is an ancestor of (or equal to) `origin/master`;
- the run's `path` is `.github/workflows/deploy.yml` — checked on the by-id path too, not
  only implied by the listing URL. `deploy-release.yml` also has a job named `deploy` that
  runs as a master `workflow_dispatch` with `head_sha` = the tip at dispatch, so without
  this a hand-pushed tag citing a *Deploy release* run id would pass on a commit libli.pl
  failed to deploy;
- the run has `head_sha == <commit>`, `head_branch == master`, and `event` is `push` or
  `workflow_dispatch`;
- that run's **`deploy` job** has `conclusion == success`. The jobs API reports a job by its
  display name, which is the job id `deploy` only while the job has no `name:` — a wiring
  test pins that, so a rename fails CI rather than every future release. The run's own conclusion is not
  enough: a dispatch on a feature branch skips every job (`if: github.ref == master`) and a
  run whose jobs were all skipped concludes `success` — and if that branch commit later
  becomes an ancestor of master, a run-level check would pass a commit libli.pl never ran.

Finding the run: *Cut release* (no `<run-id>`) lists
`repos/{repo}/actions/workflows/deploy.yml/runs?head_sha=<commit>` and takes the newest run
meeting the conditions, printing its id. **Both lookup paths apply the same job check**:
jobs read with `?filter=all`, passing if any attempt's `deploy` job succeeded. *Deploy release* passes the id from the tag's
`canary-run:` line and fetches that run directly (`runs/<id>` and
`runs/<id>/jobs?filter=all`; the job condition passes if **any attempt's** `deploy` job
succeeded — D2 asks whether libli.pl ran the commit green, which a later failed re-run of
that same run does not undo, and `filter=latest` would let such a re-run block every
future deploy of the release, rollbacks included) — a
lookup by id does not depend on the run still appearing in a filtered listing, so rolling
back to an old release keeps working.

Refusals name the reason: "not on master", "libli.pl has no successful deploy of <sha>"
(including the case of a commit that was part of a multi-commit push and never got its own
run — tag the tip instead), "run <id> is not a master deploy of <sha>", "tag has no
canary-run line", "canary run <id> no longer exists" (the by-id fetch returns 404).

That last case blocks every deploy of the release, including an emergency rollback, so the
runbook (§9) says: **never delete a `deploy.yml` run that a release tag cites.** If one is
gone anyway, the recovery is to cut a new release on a later commit libli.pl deployed green.
Runs with `actions: read`; every step that calls `canary_guard.sh` sets
`GH_TOKEN: ${{ github.token }}` in its `env:` — `gh` does not pick up `GITHUB_TOKEN` by
itself, and the stubbed tests cannot notice a missing token.

### 5. Migration guard — `scripts/release/migration_guard.sh <current> <target>`

Both arguments are commit shas (callers strip `sha-` from `LIBLI_IMAGE_TAG` and peel tags).
**One read rule for `LIBLI_IMAGE_TAG`**, used by pre-flight and `deploy.sh` and pinned by
shared fixtures like the channel rule: exactly one line matching `^LIBLI_IMAGE_TAG=`, and
no `export`-prefixed or indented variant (`^\s*(export\s+)?LIBLI_IMAGE_TAG\s*=` matching
more lines than the anchored form) — otherwise refuse. The existing writer replaces only
`^LIBLI_IMAGE_TAG=` lines, `env_value` takes the first match and compose the last, so a
duplicate or variant would let each see a different "current". §9's first boot says the
line is written in exactly that form.
`deploy.sh` applies the rule **once, right after `flock`** (before the `EXIT` trap is
installed, since the trap needs the value), and its three outcomes differ by path:

| Outcome | Release-channel box | libli.pl (no channel line) |
|---|---|---|
| valid (one anchored line, `^sha-[0-9a-f]{40}$`) | used as *current* and as the restore target | used as the restore target |
| absent | refuse (the guard has no *current*; first boot is by hand, §9) | deploy proceeds; the trap only reports ("no restore target") — today's first-deploy behaviour |
| malformed / duplicate / variant | refuse | deploy proceeds with a warning; the trap reports "cannot restore: LIBLI_IMAGE_TAG unreadable" — libli.pl's canary is never blocked by this rule, so Goal 6 is unchanged |
A `LIBLI_IMAGE_TAG` read from a box must match `^sha-[0-9a-f]{40}$` exactly (trailing CR or
whitespace, a short sha, or `sha-v1.0.0` all fail) — checked in pre-flight and in
`deploy.sh` before the value is used as a git revision by the guard or the restore;
anything else refuses with a message naming the field, never the host.

- `target == current` → pass (a re-deploy of the same version).
- `current` is an ancestor of `target` → an upgrade → pass. Migrations are cumulative and
  `migrate` runs on every boot.
- `target` is an ancestor of `current` (a downgrade): list
  `git diff --name-only <target> <current> -- '*/migrations/*.py' uv.lock`. Empty → pass.
  Non-empty → **refuse**, printing each file and pointing to `docs/backup-and-restore.md`
  (restore from a backup taken before the newer version). `uv.lock` is in the list because
  Django contrib and allauth migrations live in the venv, not the repo (as `restore.sh`
  already documents): a dependency bump can migrate the schema with no repo migration file
  changing. This is deliberately conservative — a lockfile change with no new third-party
  migration is also refused — the alternative (comparing the two images' migration lists,
  as `restore.sh` does) needs both images pulled on the runner, and D3 prefers a false
  refusal to a silent schema mismatch.
- **Order of checks:** same-version pass → both commits exist in the clone (else refuse,
  "current commit unknown" / "target commit unknown") → postgres rule → ancestry rules.
- **In both directions** (checked right after the `target == current` pass, before the
  ancestry rules — a same-version re-deploy is §7's recovery path and must never be blocked
  by an unparseable image line): compare the
  `postgres:` image line of `docker-compose.prod.yml` at the two commits. If the major
  version differs → **refuse**, pointing out that a postgres major change is a manual
  dump-and-restore procedure outside B2. On a downgrade the `pgdata` volume was initialised
  by the newer major and an older postgres refuses to start on it; on an upgrade the newer
  postgres refuses the older data directory. Either way the site would go down after `up`,
  and on an upgrade the obvious recovery (redeploy the previous version) would then be
  refused as a downgrade. libli.pl passing the canary proves nothing here, because its own
  major bump needs the same manual procedure. Extraction is pinned: the line matching
  `^\s*image:\s*postgres:` (never a bare `postgres:`, which also matches
  `DATABASE_URL: postgres://…`); the major is the tag's leading digits (`16`, `16-alpine`,
  `16.4` → `16`). No match, several matches, or a tag without leading digits (e.g. a
  digest-only pin) at either commit → **refuse**.
- Neither is an ancestor of the other (diverged — e.g. a box once set by hand to a sha off
  master) → **refuse**: `current` may hold migrations `target` lacks, and "not a downgrade"
  is not the same as "an upgrade".
- `current` unknown to the clone (a commit that is not in the repo), or no persisted
  `LIBLI_IMAGE_TAG` on the box → refuse.

### 6. School inventory — secrets

- `SCHOOL_HOSTS`: JSON object,
  `{"school-01": {"host": "<ip-or-name>", "host_key": "ssh-ed25519 AAAA…",
  "domain": "<the box's DJANGO_SITE_DOMAIN>"}, …}`.
  Keys must match `^school-[0-9]{2}$`; all three fields are required and non-empty;
  `host` and `domain` must match a hostname/IP pattern (`^[A-Za-z0-9][A-Za-z0-9.:-]*$` — no
  whitespace, comma or leading `-`, which `ssh` would parse as an option) and `host_key`
  must match `^(ssh-ed25519|ecdsa-sha2-nistp(256|384|521)|ssh-rsa) [A-Za-z0-9+/]+={0,2}$`,
  so a typo fails legibly here rather than as an opaque host-key mismatch.
  `host_key` is the key-type-and-key part only (as printed by `ssh-keyscan`, minus the host);
  the workflow composes the `known_hosts` line. It pins the box's SSH host key: the runner is
  ephemeral, so `StrictHostKeyChecking accept-new` would trust whatever answers on every run.
  `domain` exists only to be masked (§2 step 3) — a school supplies its own hostname, which
  usually names it. GitHub masks substrings, and `deploy.sh` prints `SITE_ADDRESS` (a
  comma-separated list for `caddy validate`) as well as `DJANGO_SITE_DOMAIN`, so `domain`
  is the **registrable domain** (e.g. `szkola.pl`), and §9's provisioning rule is that
  every name in the box's `SITE_ADDRESS` and its `DJANGO_SITE_DOMAIN` contains it.
  `scripts/release/inventory.sh` parses and validates it; a malformed secret fails the `plan`
  job with nothing touched. **Its errors never print a field value** — only the code and
  the field name ("school-03: host is empty"), and for non-JSON only "not valid JSON". GitHub
  masks the whole secret string, not substrings, and the `plan` job runs before any
  `::add-mask::`, so an echoed value would reach the public-or-private log unmasked (D4).
  On success `plan` `::add-mask::`s every `host` and `domain` before emitting the matrix.
- `SCHOOLS_SSH_KEY`: one private key for every school box, **distinct from** libli.pl's
  `SSH_KEY`, so no misconfiguration can aim a school deploy at libli.pl or the reverse.
- `HEALTHCHECKS_SCHOOL_DEPLOY_URL`: the new check *libli school deploys*. Unlike libli.pl's
  check, school deploys are rare and manual (D1), so a short period would alarm on every
  quiet month. Its period is set to healthchecks.io's **maximum**; the alert that matters is
  the `/fail` ping, which fires immediately regardless of period. The absence alert is only
  a yearly-scale liveness check on the channel itself.
- Deploy user is `root`, as on libli.pl.

### 7. Failure table

| Failure | Stops at | Site |
|---|---|---|
| Bad version format / tag exists (cut) | before tagging | untouched |
| Canary guard or B2-containment refuses | before SSH | untouched |
| Unknown code / malformed `SCHOOL_HOSTS` | `plan` job | untouched |
| Workflow dispatched from a non-master branch | every job skipped | untouched |
| libli.pl run superseded (D9: `origin/master` moved past the run's own commit) | inside `deploy.sh`, before any docker call | untouched — the trap restores the checkout the bootstrap reset; red but benign, the newer run deploys. Nothing to do. |
| Host key mismatch / SSH unreachable | pre-flight | untouched |
| Box's `LIBLI_DEPLOY_CHANNEL` is not exactly `release` | pre-flight | untouched — fix `.env.production` (runbook §9) |
| Box's tag resolves to a commit other than `target_sha` | pre-flight (and again inside `deploy.sh`) | untouched |
| Box cannot fetch the tag (401 flake after retries, or deploy key) | pre-flight | untouched |
| Migration guard refuses | before deploy SSH | untouched |
| Any refusal or failure inside `deploy.sh` before `up` (embedded guard, ref check, fetch, Caddyfile, token, login, pull) | inside `deploy.sh`, before `up` | untouched — site on the old image; the `EXIT` trap restores the checkout, so `LIBLI_IMAGE_TAG` and `HEAD` still agree. Re-run the same version once the cause is fixed. |
| `up --wait` / `/healthz/` fails | inside `deploy.sh`, after `up` | **down**. `LIBLI_IMAGE_TAG` now names the new version (its `migrate` may have run). Recovery: fix the cause and re-deploy **the same version** (target == current passes). Deploying the previous version passes only if no migration lies between them; otherwise the guard refuses and the path is a restore (D3) — deliberately, since the schema may be ahead. |
| `docker image prune` (after `/healthz/` passed) fails | inside `deploy.sh`, after verify | **up on the new version** — the leg shows ❌ and `/fail` fires, but the site is healthy. Re-deploy the same version to clear it, or ignore. |
| Leg timed out / session dropped / pid not reported within 30 s | anywhere in step 6 | **unknown** — the detached run may have finished, failed or not started. Read the box's `LIBLI_IMAGE_TAG` and `/var/log/libli-deploy/`, then re-deploy the intended version. |
| Box's `LIBLI_IMAGE_TAG` absent or malformed | pre-flight | untouched — fix the line per §9 (exactly one `LIBLI_IMAGE_TAG=sha-<40 hex>`). |

### 8. Going private — order of operations

B2 ships the runbook text and the pre-flight check; the steps are Krzysztof's actions.
1. libli.pl gets its read-only deploy key and switches its fetch to SSH (the existing
   *Fetching over SSH* section of `docs/deployment.md` §8) — **before** the flip, or its
   first post-flip deploy fails at the fetch (site untouched, but stuck).
2. Every school box gets its own deploy key at provisioning (GitHub does not reuse a deploy
   key across boxes).
3. Flip the repo to private, whenever chosen. GHCR is already private and every box already
   logs in, so the image path is unaffected.

### 9. Runbook changes (`docs/deployment.md`)

- §9 also gives the **in-place restore on an existing school box** (D3's refusal path):
  `docs/backup-and-restore.md` Step 0 assumes a fresh clone, but a school box already has
  a detached, release-channel checkout. The sequence: `git fetch origin
  '+refs/tags/*:refs/tags/*'`, `git checkout --force --detach <manifest git_sha>`, then
  `restore.sh` — no `deploy.sh` and no *Deploy release* involved. `restore.sh` writes the
  restored image into `LIBLI_IMAGE_TAG` (and the backup's `.env.production` keeps the
  channel line), so the next *Deploy release* treats the restored version as *current*.
- New §9 *Schools*: provisioning a school box (§1–§3 with: checkout at a release tag, not
  `master`; `LIBLI_DEPLOY_CHANNEL=release` in `.env.production`; the box's deploy key;
  capturing `host_key`; adding the entry to `SCHOOL_HOSTS`; the runner's public key in
  `authorized_keys`), cutting a release, deploying, rolling back, and what each refusal means.
  §9 also states the **first-boot procedure**, which deliberately does not use `deploy.sh`
  (on a release-channel box the no-ref path is refused by the channel catch and the ref
  path by the `LIBLI_IMAGE_TAG` read rule right after `flock`, which refuses a
  release-channel box with no persisted tag before any fetch or guard): `git checkout
  --detach <tag>`; set `LIBLI_IMAGE_TAG=sha-<tag's peeled 40-hex sha>` in `.env.production`
  by hand, exactly as today's §3 already has the operator do; the existing §3 `up -d` and
  §4 checks; **then** add `LIBLI_DEPLOY_CHANNEL=release`; then *Deploy release* the same
  tag (a same-version pass) to prove the box is reachable from the workflow. That order is
  the only one in which no step resets the school to `master`; tags are created only
  through *Cut release*, because the by-hand `deploy.sh` path cannot re-check D2; and the
  failure table's recovery column (§7 above).
- §8 *When a deploy goes red* gains the D9 signature: a red run ending in "superseded by
  <sha>; the newer run deploys it" is benign — master moved on while it waited; the
  bootstrap had reset the checkout to the newer commit and the `EXIT` trap put it back to
  the persisted `LIBLI_IMAGE_TAG`'s commit, no container was touched (the site stays on
  its previous version until the newer run deploys), and
  the deploy alert clears when that newer run goes green. Nothing to do.
- §8 *When a deploy goes red* gains the pointer that a school recovers through
  *Deploy release*, not `git reset` by hand. Its libli.pl recipe
  (`git reset --hard <sha>` + `compose up`) is replaced by
  `LIBLI_DEPLOY_REF=<sha> bash deploy.sh`: a bare `compose up` after a reset starts whatever
  `LIBLI_IMAGE_TAG` already says in `.env.production`, not the reset commit's image.
- The *Known constraints* entry about single-host CD is replaced.

## Testing

All runnable locally; no GitHub calls. Pattern follows `tests/test_deploy_wiring.py`
(extract or invoke the real shell, stub external commands on `PATH`).

- **Migration guard** — a throwaway git repo per test with real commits, tags and
  `app/migrations/000N_*.py` files: upgrade passes; downgrade with no migration between
  passes; downgrade across a migration is refused and names the file; a downgrade across a
  **`uv.lock`-only change** is refused; a downgrade across a **`postgres:` major change** in
  `docker-compose.prod.yml` is refused, and so is an **upgrade** across one (a
  non-postgres compose change is not; `16` → `16-alpine` is not a major change; the
  `DATABASE_URL: postgres://` line is not mistaken for the image; a missing image line
  refuses); same version passes, **even when its postgres line is unparseable** (the
  same-version pass precedes the postgres rule);
  **diverged history** (a side branch holding a migration) is refused; unknown current
  commit is refused **with "current commit unknown"**, not a postgres-line message.
- **Canary guard** — stub `gh` returning canned run/job JSON: a push run on master whose
  `deploy` job succeeded passes; red run, no run, a commit not on master, and a
  **skipped-jobs "success" run from a feature-branch dispatch** are each refused with their
  own message; lookup by run id passes for a matching run and refuses a run whose `head_sha`
  differs; an **annotated tag** is peeled by the caller and resolves to the right commit;
  a by-id lookup of a run from **another workflow** (e.g. `deploy-release.yml`) with a
  successful `deploy` job, matching sha and master branch, is refused (the mutant: the
  `path` check removed); a 404 on the by-id fetch refuses with "canary run <id> no longer
  exists"; a run whose first attempt's `deploy` job succeeded and a later re-run failed
  still passes (the jobs are read with `filter=all`) — on **both** the by-id path and the
  *Cut release* listing path.
- **Remote bootstrap** (`remote_deploy.sh` run under **real `bash`, `setsid` and
  `nohup`**; only `git` and the deployed script are faked — faking `bash` would leave the
  wrapper's quoting unparsed, and faking `setsid`/`nohup` would remove the very detachment
  under test. Skipped where `setsid` is absent, e.g. Git Bash on Windows; CI runs it) — the
  deployed script receives the ref, expected sha and skip-fetch (mutant: the
  argument/export hand-off dropped → RED); killing the following session leaves the
  detached run to finish and write its status (mutant: `deploy.sh` run in the foreground
  → RED); the session returns within seconds of the deployed script finishing; the
  followed pid is the wrapper's, read from the pid file; a recorded non-zero status
  becomes the session's exit code; an absent status file exits 1; the temp script is
  removed by the wrapper, not by the session; a run that writes more than 10 lines before
  `tail` attaches shows all of them; a slow-starting run whose first write comes late is
  still followed (log pre-created); with 25 old logs present, 19 old ones plus the new
  one survive; status/pid files older than 1 hour are removed at start; a wrapper that has
  not written its pid file after 30 s makes the session exit 1 with the "may still start"
  message; a target `deploy.sh` that does not mention a variable `remote_deploy.sh`
  requires is refused before starting; a box with neither `/var/lib/libli-deploy/` nor
  `/var/log/libli-deploy/` gets both created; **the detached run holds no fd of the
  session** —
  the test closes the session's stdout pipe early and the run still finishes and writes
  its status, and a child reading stdin gets EOF rather than the rest of the script
  (mutant: the `</dev/null >>log 2>&1` redirect dropped → RED).
- **B2-containment** — a commit whose `deploy.sh` lacks `LIBLI_DEPLOY_REF` is refused, and
  so is one that has it but lacks `LIBLI_DEPLOY_EXPECT_SHA`, and one that has both but
  lacks `scripts/release/migration_guard.sh`.
- **`LIBLI_IMAGE_TAG` read rule** — one set of fixtures (single anchored line; duplicate
  lines; `export`-prefixed; indented; CR-terminated; short sha) gets the same verdict from
  pre-flight and from `deploy.sh`; on the **libli.pl path** an absent line lets the deploy
  proceed with "no restore target" and a malformed line lets it proceed with the "cannot
  restore" warning, while on a release-channel box both refuse.
- **Pre-flight secrecy** — a fixture `.env.production` holding a sentinel secret next to a
  malformed `LIBLI_IMAGE_TAG` line: the pre-flight output (refusal included) never
  contains the sentinel, and the pre-flight wiring never copies the file off the box.
- **Inventory characters** — a `host` with whitespace or a leading `-`, a `domain` with a
  comma, and a `host_key` that is not `<type> <base64>` are each refused, naming only the
  code and field.
- **Guard contract** — `migration_guard.sh` contains no `source`/`.` of another file and no
  `jq`; it takes exactly two arguments.
- **Pre-flight** — `preflight.sh` prints exactly `image_tag=…` and `channel=release` on
  success, one `refuse: …` line otherwise, and `--read-only` prints only `image_tag=…`;
  an early refusal in `deploy.sh` (channel catch) leaves a hand-modified tracked file
  untouched because `HEAD` never moved; a box with the channel line missing or mistyped is refused; one set of
  channel fixtures (absent, `release`, `export LIBLI_DEPLOY_CHANNEL=release`, indented,
  empty, `relase`) gets the same verdict from pre-flight and from `deploy.sh`; a **stale
  local tag** (the box's `<version>` pointing at an older commit, re-cut on origin) is
  replaced by the forced fetch and the sha check passes, while a box whose tag still
  resolves elsewhere is refused.
- **Tag shape** — a lightweight tag is refused with its own message even when its commit
  message contains a `canary-run:` line; an annotated tag without the line is refused.
- **Inventory** — valid JSON resolves `all` and a single code; unknown code, bad key shape,
  missing `host`/`host_key`/`domain`, and non-JSON are each refused; **no error output
  contains any host or domain value** from the fixture.
- **`deploy.sh`** — a by-hand run whose checkout replaces `deploy.sh` with a **different**
  version (the fixture's target `deploy.sh` has extra/shifted lines) completes with the
  starting script's behaviour and nothing from the new file executed (mutant: the
  `main "$@"; exit` wrapper removed → RED); channel `release` + a ref on a box with **no persisted
  `LIBLI_IMAGE_TAG`** is refused by the read rule right after `flock`, before any fetch or
  guard call, with "LIBLI_IMAGE_TAG absent" (the reason §9's first boot is by hand); a
  commented `#LIBLI_DEPLOY_CHANNEL=release` line is refused as present-but-invalid;
  channel `release` + no ref is refused before any fetch or docker call;
  channel `release` + a sha ref is refused; channel `release` + a downgrade across a
  migration is refused by the embedded guard; a ref checks out that tag and
  `LIBLI_IMAGE_TAG` follows it; `LIBLI_IMAGE_TAG` in `.env.production` is unchanged and
  `HEAD` is restored to it after **each** pre-`up` exit path — a failure inside `compose()`
  (pull), the missing-`LIBLI_GHCR_TOKEN` `exit 1`, and a refusal by the embedded migration
  guard — with the restore form matching branch vs detached `HEAD`; **a failure of
  `compose up --wait` does NOT restore**: `HEAD` stays at the new commit and
  `LIBLI_IMAGE_TAG` names the new version (the mutant it must turn RED: a trap that ignores
  `reached_up` and always restores); on the by-hand path a tag present **only after the
  fetch** is guarded and deployed correctly; a by-hand downgrade where **only the newer
  (current) guard copy refuses** is refused (the mutant: run only the target's copy);
  `LIBLI_IMAGE_TAG` in `.env.production` already names the new version when `compose up` is
  invoked (fake docker records the file's contents at `up`); an exported bogus
  `LIBLI_IMAGE_TAG` does not reach `up`; a `HUP` delivered before `up` restores the
  checkout; a present channel line whose value is empty, `export`-prefixed, indented or
  other than `release` is refused; a
  `LIBLI_DEPLOY_EXPECT_SHA` mismatch is refused; a by-hand `LIBLI_DEPLOY_REF=<sha>` run on
  libli.pl followed by an ordinary run leaves `HEAD` on `master`; the ref fetch retries
  like the master fetch and uses the forced `+refs/tags/…` form; a malformed ref is refused; **no channel line and no
  ref behaves exactly as today** apart from the changes listed in Goal 6 (the later
  `LIBLI_IMAGE_TAG` write and the pre-`up` restore; the unset, signal trap and `EXIT`-trap
  messages are no-ops on a successful run and must not change its output) (the libli.pl
  regression guard, reusing the existing fake-docker harness).
- **D9 (libli.pl superseded run)** — wiring: `deploy.yml`'s `script:` exports
  `LIBLI_DEPLOY_EXPECT_SHA` from `${{ github.sha }}` inline and fails closed on a
  non-40-hex value before invoking `deploy.sh` (mutants: the export removed, or the value
  moved to a step `env:` only → RED; the extracted remote script run with an empty value
  exits non-zero). `deploy.sh` with `LIBLI_DEPLOY_SKIP_FETCH=1`, the fixture's `HEAD`
  already at the newer `origin/master` (the bootstrap's state) and the expected sha older:
  refuses before any docker call, `LIBLI_IMAGE_TAG` unchanged, and `HEAD` **restored to
  the persisted tag's commit** by the trap; with them equal it proceeds exactly as today
  (mutants: the check skipped on the unset-ref path, or placed inside the fetch branch →
  RED).
- **Wiring** — both new workflows call `scripts/release/*` rather than inlining their logic;
  every job is gated on `github.ref == 'refs/heads/master'`, parsed from each job's single
  `if:` (a test fed a job with a duplicate `if:` key must fail, not collapse), and
  `report`'s one expression contains both `always()` and the ref check — each part's
  removal turns a test RED; every `ssh` call carries `StrictHostKeyChecking=yes` and
  `UserKnownHostsFile=` pointing at the written file, and none carries `accept-new` or
  `StrictHostKeyChecking=no` (each removal/addition → RED); `report`'s artifact download
  tolerates zero matches, and a `plan` refusal still yields the summary row and a `/fail`
  ping; `ssh` calls carry `BatchMode`/`ConnectTimeout`/`ServerAlive*`
  and `deploy` has `timeout-minutes: 45`; `cut-release` sets a tagger identity before
  `git tag -a`; every step calling `canary_guard.sh` sets `GH_TOKEN` in `env:`; the
  top-level `permissions: {}` and each job's block
  match §2; every checkout that runs a
  guard uses `fetch-depth: 0`; `fail-fast: false`; per-code concurrency with
  `cancel-in-progress: false`; `host` and `domain` are masked **before the first `ssh`**;
  the pre-flight fetch retries; `set -e` is the first remote line; the deploy bootstrap
  extracts `deploy.sh` with `git show` and contains no `git checkout`/`reset`; `plan`
  checks `version`'s regex before any step that uses it and `refs/tags/` right after its
  checkout, and a malformed or non-tag version is refused; the deploy leg's inventory
  extraction and its `::add-mask::` are one step, with no earlier step carrying host or
  domain in its `env:`; the outcome step runs `if: always()`, derives `result` from
  the deploy step's `outcome`, and uploads with `overwrite: true`; `report` treats a
  missing artifact as ❌ and pings the plain URL only when every planned code has a ✅ from
  the current `run_attempt` (an earlier-attempt ✅ yields `/fail`); the bootstrap uses `mktemp`; `cut-release` resolves `commit` with
  `rev-parse --verify` via `env:`; `report` pings `/fail` when `plan` failed or planned zero codes;
  `deploy.yml`'s `deploy` job has no `name:`; `deploy.yml` does not
  reference any school secret and `deploy-release.yml` does not reference
  `SSH_HOST`/`SSH_KEY`.
- **Falsification** — every guard test is shown RED against a mutant (condition removed or
  inverted) before it counts. The mutant is chosen from the failure mode it must catch.

## Rehearsal (definition of done)

On a throwaway box `school-00` with a DNS name such as `rehearsal.libli.pl`, both provided
by Krzysztof. libli.pl is never touched.

1. Cut `v1.0.0`; provision `school-00` per the new §9 **at `v1.0.0`** (its manual first
   boot writes `LIBLI_IMAGE_TAG`); then *Deploy release* `school-00` / `v1.0.0` → green, site
   up. This proves the workflow end to end on a same-version re-deploy (target == current).
2. Cut a later version on a commit chosen so that the rollback in step 3 is allowed:
   `git diff --name-only v1.0.0 <commit> -- '*/migrations/*.py' uv.lock` is empty and the
   `image: postgres:` line is unchanged, **and** `deploy.sh` differs
   (`git diff --quiet v1.0.0 <commit> -- deploy.sh` exits 1 — otherwise step 5's by-hand
   runs never rewrite the running script and the wrapper goes unexercised). Check before
   cutting. Deploy it → green.
3. Roll back to `v1.0.0` with no migration between → green.
4. On the box, `bash /opt/libli/deploy.sh` with no ref → refused.
5. *Deploy release* `all` / `v1.0.0` (a same-version pass) → green, summary lists every
   code. Then, on the box, a by-hand `LIBLI_DEPLOY_REF=<step 2's tag> bash deploy.sh`
   followed by `LIBLI_DEPLOY_REF=v1.0.0 bash deploy.sh` → both green — the only place the
   embedded two-copy guard and the `main "$@"; exit` wrapper are seen on a real box.
6. Purge the box, remove `school-00` from `SCHOOL_HOSTS`.
7. **The migration refusal, as its own short rehearsal.** It needs a REAL migration between
   two releases. Never manufacture one: every tag must be a commit libli.pl ran (D2), so a
   scratch migration would land in production. Once a release containing a real migration
   exists, provision a fresh `school-00` at the release before it, deploy the
   migration-bearing release, then *Deploy release* the older one → refused before SSH,
   naming the files. Steps 1–6 do not wait for this; B2 is not **done** until it has been
   seen refusing on a real box.

## Rollout

1. Merge B2. The first `deploy.yml` run after the merge is the libli.pl regression check.
2. Krzysztof adds libli.pl's deploy key (§8 *Fetching over SSH*) — before going private.
3. Rehearsal (above).
4. First real school.
