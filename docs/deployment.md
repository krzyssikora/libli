# Deploying libli

A single-host containerised install: `caddy` (TLS + media), `app` (gunicorn), `db`
(PostgreSQL 16). Everything below has been executed end to end against the real stack;
where a step exists to catch a specific failure, that failure is named.

**Scope.** One host, one `app` container. That constraint is what makes `migrate` in the
entrypoint safe and lets `TRANSFER_STAGING_DIR` be a local volume. Do not scale `app`.

---

## 1. Provision

Any VPS with **50 GB disk minimum**. Peak usage during a large course import is ~17 GB
(the archive exists three times concurrently — see §6); steady state is ~9 GB. RAM is not
the constraint: uploads are chunked and nothing holds the archive in memory. 2 GB works;
4 vCPU / 8 GB is the cheapest Contabo tier and is ample.

Ubuntu 24.04. Order early if using Contabo — new accounts sometimes sit in manual review.

### Harden SSH first — before DNS points at the box

Contabo emails a root password rather than taking a key at order time. A public IP with
password authentication is being brute-forced within hours.

From your own machine:

```bash
ssh-copy-id root@<ip>
ssh root@<ip>
```

Then on the VPS:

```bash
sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#\?PermitRootLogin .*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
systemctl restart ssh
```

**Open a second terminal and confirm you can still log in before closing the first.**

A `~/.ssh/config` entry saves typing for everything below:

```
Host libli
    HostName <ip>
    User root
    IdentityFile ~/.ssh/libli_deploy
```

### No firewall is required

The compose file publishes only 80/443, via `caddy`. `app` uses `expose`, so gunicorn is
reachable only on the compose network, and `db` publishes nothing at all.

Note that `ufw` would not help regardless: Docker writes its own iptables rules and
bypasses it, so a green `ufw status` proves nothing about a published port.

### Install Docker

```bash
apt-get update && apt-get install -y ca-certificates curl git
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
```

Stay on an Ubuntu LTS the Docker repo actually publishes for. A release newer than the
repo's coverage fails at `apt-get install docker-ce` with no obvious cause.

---

## 2. DNS

An `A` record per hostname, pointing at the VPS, resolving **before** first boot — Caddy
requests a certificate on startup.

Forward DNS lives at your registrar, not at the VPS provider (the provider's panel
manages *reverse* DNS, which only matters for outbound mail).

Two things that silently break issuance:

- **A `CAA` record that omits `letsencrypt.org`.** If the zone lists only another CA,
  Let's Encrypt refuses to issue and Caddy retries forever with an error that points at
  the domain rather than the DNS. Check before you boot.
- **A stale `AAAA`** for the same name. Browsers prefer IPv6 and will reach the old host.

If the zone has an existing parking `A` record, **edit** it rather than adding a second —
two records round-robin between your box and the placeholder.

Verify from the VPS:

```bash
getent hosts <host>       # must return the VPS address
```

---

## 3. Configure and boot

```bash
git clone <repo-url> /opt/libli && cd /opt/libli
cp .env.production.example .env.production
python3 -c "import secrets; print(secrets.token_urlsafe(64))"   # DJANGO_SECRET_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # POSTGRES_PASSWORD
nano .env.production      # fill every blank AND replace every example hostname
chmod 600 .env.production
```

**Save all three secrets in a password manager as you generate them** —
`DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD` and the `INIT_ADMIN_PASSWORD` you choose.
`.env.production` is the working store, but it exists only on this host: lose the host and
you have nothing. What each costs you if lost:

- **`INIT_ADMIN_PASSWORD`** is your login. Recoverable with `manage.py changepassword`, but
  only if you still have shell access.
- **`POSTGRES_PASSWORD` is the awkward one.** Postgres uses it *only* when it initialises an
  empty data directory — the very first `up`. After that it is baked into the `pgdata`
  volume. Putting a new value in `.env.production` later does **not** change the database's
  password; the app simply stops connecting, and the failure reads as a config error rather
  than a forgotten credential. Recovery is `exec`ing into the `db` container and running
  `ALTER USER <user> WITH PASSWORD '…'`.
- **`DJANGO_SECRET_KEY`** is the least critical. Regenerating logs everyone out and
  invalidates outstanding password-reset and invitation links, but nothing is unrecoverable.

**Four keys ship with a placeholder hostname rather than a blank**, so "fill every blank"
misses them, and compose's `:?` guards do not fire on a non-empty wrong value. A stale
`DJANGO_ALLOWED_HOSTS` makes the healthcheck return 400 → the app never becomes healthy →
Caddy never starts → the site is simply unreachable. A stale `DJANGO_CSRF_TRUSTED_ORIGINS`
403s every wizard POST instead.

```bash
grep -nE '^(SITE_ADDRESS|DJANGO_SITE_DOMAIN|DJANGO_ALLOWED_HOSTS|DJANGO_CSRF_TRUSTED_ORIGINS)=.*example\.(org|com)' .env.production
# MUST return nothing before you boot
```

`DJANGO_SITE_DOMAIN` is the **apex only** — a single host, not a list. It is what gets
baked into invitation and password-reset links. `SITE_ADDRESS` may be a comma-separated
list; every name in it must also appear in `DJANGO_ALLOWED_HOSTS`.

Validate the proxy config before starting anything — `caddy` has no healthcheck, so a
Caddyfile syntax error produces a crash loop that `docker compose ps` reports as
`running`:

```bash
docker run --rm -v "$(pwd)/Caddyfile:/etc/caddy/Caddyfile:ro" \
  -e SITE_ADDRESS=<host> caddy:2-alpine caddy validate --config /etc/caddy/Caddyfile
# expect: Valid configuration, and no warnings
```

Then — this is the **only** time you run this by hand; every later deploy is §8:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
docker compose -f docker-compose.prod.yml --env-file .env.production logs -f app
```

The log must show, **in this order**:

```
==> waiting for the database
==> migrate
==> setup_roles
==> set_site_domain
==> init_platform            (or "init_platform skipped" — see below)
==> gunicorn
```

They scroll past fast. `logs app | grep '==>'` shows just these six.

`setup_roles` is the one that matters and the one no test can catch: permissions live as
constants in `institution/roles.py` but are only *assigned* by `seed_roles()`, and the
test suite calls it itself so it passes either way.

`==> init_platform skipped` is **expected** if you left `INIT_ADMIN_*` unset — that is the
recommended route, and §5 creates the admin interactively instead. It only indicates a
problem if you meant to set those three and one is missing.

If the container crash-loops here, the usual cause is an `INIT_ADMIN_PASSWORD` that fails
Django's validators — `logs app | grep '==> init_platform'`.

---

## 4. Verify

Run all of these before going further.

```bash
# a media file to range-test (matematyka is not loaded yet)
docker compose -f docker-compose.prod.yml --env-file .env.production exec -T app \
  sh -c 'mkdir -p /app/media/smoke && head -c 1048576 /dev/urandom > /app/media/smoke/probe.bin'

curl -sI https://<host>/healthz/                          # 200
curl -sI https://<host>/                                  # 200 — landing page over TLS
curl -sI http://<host>/ | head -3                         # 301/308 to https

# Video seeking. A GET with the body discarded, NOT a HEAD: Range-on-HEAD is a
# file-server implementation detail, whereas a <video> element issues a GET.
curl -s -o /dev/null -D - -r 0-100 https://<host>/media/smoke/probe.bin | head -5
# MUST show 206 Partial Content, Accept-Ranges: bytes, Content-Range: bytes 0-100/1048576
```

**A 200 on that Range check is the failure mode to fear.** The page looks perfect and only
a student trying to replay a passage discovers that video cannot be seeked. Django
implements no HTTP Range handling anywhere; the fix (`core/media_serve.py`) is DEBUG-only,
so on a deployment it is Caddy's `file_server` doing the work.

```bash
# Static: resolve a HASHED name first. The un-hashed path returns 200 even with a
# broken manifest, so checking it proves nothing.
MANIFEST=/app/staticfiles/staticfiles.json
HASHED=$(docker compose -f docker-compose.prod.yml --env-file .env.production exec -T app \
  /app/.venv/bin/python -c "import json; print(json.load(open('$MANIFEST'))['paths']['admin/css/base.css'])" \
  | tr -d '\r')
curl -sI "https://<host>/static/$HASHED"                  # 200

# Staging directories must be unreachable — by request, not by reading the Caddyfile.
curl -so /dev/null -w '%{http_code}\n' https://<host>/transfer_staging/
curl -so /dev/null -w '%{http_code}\n' https://<host>/support_screenshots/
# both MUST be 404 or 403 — never 200, never a directory listing

# The upload spill directory is applied, not merely present in the environment.
docker compose -f docker-compose.prod.yml --env-file .env.production exec -T app \
  /app/.venv/bin/python -c "from django.conf import settings; print(settings.FILE_UPLOAD_TEMP_DIR)"
# MUST print /app/upload_tmp

# The Site record was actually written. "==> set_site_domain" is an unconditional
# echo — it prints whether the command wrote, no-op'd, or abstained.
docker compose -f docker-compose.prod.yml --env-file .env.production exec -T app \
  /app/.venv/bin/python -c "import django; django.setup(); from django.contrib.sites.models import Site; s=Site.objects.get_current(); print(s.domain, s.name)"
# MUST NOT be example.com

df -h /                                                   # ≥17 GB free before importing
```

Then delete the probe: `exec -T app rm -rf /app/media/smoke`.

---

## 5. Create the Platform Admin, then the first-run wizard

If you left `INIT_ADMIN_*` **unset** in `.env.production` — the recommended route, since it
keeps the password out of any file, out of `docker inspect`, and out of shell history —
the entrypoint printed `==> init_platform skipped` and no admin exists yet. Create one now,
interactively:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production exec app   /app/.venv/bin/python manage.py init_platform
```

It prompts for username, email and password; the password is read with `getpass`, so it is
not echoed and never touches disk. Expect `Created Platform Admin '<username>'.`

**No `-T`** — the TTY is what enables the prompts. (§7's cron entry uses `-T` for the
opposite reason: cron has no TTY.) Run this **after** the stack is healthy, since it needs a
migrated database and a running container.

The command is idempotent and its reconcile is deliberately non-destructive: on an existing
user it fixes only the superuser flags and group membership, and **never overwrites the
password**. So a password you later change through the UI survives restarts.

Verify:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production exec -T app   /app/.venv/bin/python -c "import django; django.setup(); from accounts.models import User; u=User.objects.get(username='<username>'); print(u.is_superuser, [g.name for g in u.groups.all()])"
# expect: True ['Platform Admin']
```

If instead you set `INIT_ADMIN_*` in `.env.production`, the entrypoint already created the
admin on first boot — **delete those three lines now** and `up -d` to recreate the container
without them. `env_file` values become container environment variables, visible via
`docker inspect` to anyone in the `docker` group.

### The wizard

Sign in as the admin you just created and walk `https://<host>/manage/setup/` — note the path is
`manage/setup/`, not `/setup/`.

Five steps: Welcome → Identity → Access → Team → SSO. This is the non-developer surface;
walk it as a school admin would, without a shell open.

- **Identity** shows a **Public hostname** field, pre-filled with the value the entrypoint
  set. It fixes email links only — `ALLOWED_HOSTS` is a setting and cannot change at
  runtime, which is fine, because you reached the wizard over that hostname already.
- **Access**: leave the signup policy on **invite**. This is a public box with a real DNS
  name; "open" means strangers can self-register.

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production exec -T app \
  /app/.venv/bin/python -c "import django; django.setup(); from institution.models import Institution; print(Institution.load().signup_policy)"
# MUST print: invite
```

After **any** settings or branding change, `restart app`. There is no `CACHES` setting, so
Django's default LocMemCache is per-process, and `core/services.py` caches the site-config
bundle for 300 s — with more than one gunicorn worker, refreshes alternate between old and
new values for up to five minutes. `SITE_CACHE` is per-process for the same reason.

---

## 6. Load a large course

This is a multi-GB upload over your own connection. Budget ~25 minutes of sustained
transfer and do it on a link you can leave alone.

### 6a. Raise the caps on the server

Uncomment **all four** `LIBLI_TRANSFER_MAX_*` overrides and `CADDY_MAX_BODY` in
`.env.production`, then:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up -d
df -h /                      # MUST show ≥17 GB free
```

The element cap is the one people miss. It is enforced on **import only**, never on
export, so an un-raised value builds the archive happily and rejects it *after* the whole
upload has finished. `CADDY_MAX_BODY` must **exceed** the Django compressed cap, not match
it — the limit covers the whole multipart body, not just the file.

### 6b. Export locally

With the local dev server running, open the course builder and use **Export course**.
Expect roughly the size of `media/`, since mp4 does not compress.

**Free ~8 GB on the drive holding your system temp dir first.** The export builds the
entire archive into a spooled temp file *before* the response emits its first byte, so it
exists twice locally: once in temp, once as the download. Expect several minutes with no
browser progress at all — that is not a hang.

### 6c. Import on the server

Open `https://<host>/manage/courses/import/` and upload the archive.

This is a **two-request flow**: the upload is staged and a preview rendered, then a
separate confirm POST performs the import. Both must reach the same container — they do
here, because there is one `app` service and the staging dir is a local volume. Do not
close the tab between them.

Success looks like: the preview lists the course title and its node/media counts; after
confirm you land on the imported course's builder.

Watch progress — a stalled upload and a working one look identical from the browser:

```bash
watch -n 10 'docker compose -f docker-compose.prod.yml --env-file .env.production \
  exec -T app sh -c "ls -l /app/transfer_staging /app/upload_tmp"'
```

**On failure there is no resume** — the staged file is discarded and 6c starts over. If it
fails twice, stop retrying: copy the archive up with `scp`/`rsync` and import it
server-side with a short command wrapping `courses.transfer.importer.import_course()`.
That is a ~20-line job and strictly better than a third upload.

Afterwards, delete the staged archive rather than waiting out the 6-hour sweep, then
**lower the caps back** and `up -d` again so the box does not sit with a multi-GB ceiling:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production exec app \
  sh -c 'rm -f /app/transfer_staging/*.zip'
```

### 6d. Sanity-check the import

The importer assigns the slug; it is not guaranteed to match the source.

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production exec app \
  /app/.venv/bin/python manage.py shell -c "
from courses.models import ContentNode, Course, MediaAsset
for c in Course.objects.all():
    print(c.pk, repr(c.slug), c.title,
          '| nodes:', ContentNode.objects.filter(course=c).count(),
          '| media:', MediaAsset.objects.filter(course=c).count())
"
```

A materially lower media count than the source means a truncated archive — re-import
rather than proceeding. Note that only *referenced* assets are exported, so a small
shortfall against the source's `MediaAsset` row count is normal.

Re-run the Range check from §4 against a **real** `.mp4` now that media exists.

---

## 7. Second course and scheduled jobs

`seed_demo_course` is idempotent and gives you a small second course with an enrolled
student:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production exec app \
  /app/.venv/bin/python manage.py seed_demo_course
```

Notifications are never auto-deleted without a scheduler. Install with `sudo crontab -e`
— **one physical line**, because a crontab command field ends at the newline and a
trailing backslash is not a continuation:

```cron
30 3 * * * cd /opt/libli && docker compose -f docker-compose.prod.yml --env-file .env.production exec -T app /app/.venv/bin/python manage.py purge_notifications
```

`exec -T` is required: cron has no TTY. Test once by hand with `--dry-run` first.

If you use `/etc/crontab` instead, that file takes an extra **user** field between the
schedule and the command.

---

## 8. Continuous deployment

Everything above is the **first** install. After it, a merge to `master` deploys on its
own — `.github/workflows/deploy.yml` SSHes in and runs `deploy.sh` from this repo, which
resets the checkout to `origin/master`, validates the Caddyfile, rebuilds, and waits for
the stack to become healthy. Nothing is left for you to do on the box.

The container entrypoint is what makes that safe: `migrate`, `setup_roles` and
`set_site_domain` run on every boot (§3), so a recreate applies schema changes and
re-seeds role permissions by itself. A deploy job that only moved code would still be
correct.

### There is no test job — that is deliberate

`ci.yml` runs on the pull request, and branch protection requires its three jobs before
the PR can merge. So `master` only ever holds a commit that already went green, and
re-running the suite on the merge commit would be a second copy of the same result.

**Branch protection is therefore load-bearing, not hygiene.** With it off — or bypassed
by an admin push straight to `master` — the merge deploys code nothing has tested. If you
ever turn it off, put a test job back into `deploy.yml`.

### One-time setup

A key for the runner, on your own machine:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/libli_github_actions -C "github-actions-libli" -N ""
ssh-copy-id -i ~/.ssh/libli_github_actions.pub root@<ip>
ssh -i ~/.ssh/libli_github_actions root@<ip> 'echo ok'   # must print ok before going on
```

Then the three secrets the workflow reads — the same three names bonnot and fijit use:

```bash
gh secret set SSH_HOST     --repo krzyssikora/libli --body "<ip-or-hostname>"
gh secret set SSH_USERNAME --repo krzyssikora/libli --body "root"
gh secret set SSH_KEY      --repo krzyssikora/libli < ~/.ssh/libli_github_actions
```

`SSH_KEY` is the **private** key. Nothing else needs seeding on the host: the first
automated deploy runs the `deploy.sh` the initial `git clone` already placed there. It
needs no execute bit either -- the workflow invokes it as `bash /opt/libli/deploy.sh`,
which is deliberate, because git on Windows does not record one.

And branch protection:

```bash
gh api -X PUT repos/krzyssikora/libli/branches/master/protection \
  -H "Accept: application/vnd.github+json" \
  -f 'required_status_checks[strict]=false' \
  -f 'required_status_checks[contexts][]=lint' \
  -f 'required_status_checks[contexts][]=unit' \
  -f 'required_status_checks[contexts][]=e2e' \
  -F 'enforce_admins=false' \
  -F 'required_pull_request_reviews[required_approving_review_count]=0' \
  -F 'restrictions=null'
```

`strict=false` is on purpose: `strict` would require every PR to be rebased onto the tip
before merging, which re-runs CI on each intervening merge — reintroducing the
duplication this arrangement exists to remove.

### Deploying without a commit

```bash
gh workflow run deploy.yml --repo krzyssikora/libli
```

Use this after editing `.env.production` on the host, which no commit can trigger.

### When a deploy goes red

`deploy.sh` fails loudly at four points, in order: the Caddyfile does not parse, the build
fails, the app container never reports healthy (`--wait`), or the public URL does not
answer `/healthz/`. The first leaves the running site untouched. The other three do not:
the old container is already gone, so a red run means the site is **down**, not merely
un-updated.

There is no automatic rollback. Recovery is manual and takes one rebuild:

```bash
ssh root@<ip>
cd /opt/libli
git reset --hard <last-good-sha>
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build --wait
```

A migration that fails part-way is the case that needs care — the schema may be ahead of
the code you just reset to. Read `logs app | grep '==>'` before assuming a rebuild fixes it.

### Two things about `deploy.sh` worth knowing

- **A change to `deploy.sh` takes effect on the deploy _after_ the one that pulls it in.**
  Bash has already parsed the running script into memory before the `git reset` inside it
  rewrites the file. Test a change to it by merging, then triggering a second, empty
  deploy with `gh workflow run`.
- **It resets, it does not pull.** `.env.production` is untracked, so the reset cannot
  destroy the host's only copy of the secrets — but any *tracked* file edited on the box
  is discarded without warning. Edit files here, not there.

`tests/test_deploy_wiring.py` guards the parts of this that no other test touches: the
paths agreeing across `deploy.yml`, `deploy.sh` and this document; `--wait` still being
passed; `ci.yml` not regrowing a `master` trigger.

---

## Known constraints

- **One `app` container.** `migrate` runs in the entrypoint; the staging dir is a local
  volume.
- **No backups.** No `pg_dump` cron, no snapshot policy.
- **Every deploy is ~1-2 minutes of 502s.** `up -d --build` rebuilds the image on the
  serving box and recreates the app container; Caddy stays up and answers 502 until the
  new container passes its healthcheck. Accepted for a demo.
- **No rollback.** A build or migration that fails leaves the site down, not merely
  un-updated -- the previous container is already gone. Recovery is a manual reset and
  rebuild on the host; see §8.
- **The container runs as root.** Accepted for now: the four named volumes are created
  root-owned on first `up`, so adding a non-root `USER` without also fixing volume
  ownership produces a container that cannot write `media/`. Revisit before this carries
  anything beyond demo data.
- **`TRANSFER_STAGING_DIR` and `SUPPORT_SCREENSHOT_DIR` must never be web-served.** Staged
  archives are raw unvalidated uploads; screenshots may carry another student's grades.
- **`DJANGO_SITE_NAME` applies on first boot only.** The entrypoint passes
  `--only-if-placeholder`, so once the domain is set the env var is ignored. To change it
  later, re-save the wizard's Identity step with the hostname filled in — that writes both.
- **Peak disk during import is ~17 GB**, including the `FILE_UPLOAD_TEMP_DIR` copy.
- **Analytics on an imported course will be empty.** The demo-activity seeder is separate,
  unbuilt work; `seed_demo_course` provides one enrolled student on its own course so the
  analytics surfaces are reachable.

## Testing this stack locally

`docker-compose.local-smoke.yml` remaps the published port for a local run and changes
nothing else. Bring the stack up with `SITE_ADDRESS=http://localhost` and
`DJANGO_SECURE_SSL_REDIRECT=false`; Caddy then serves plain HTTP and skips ACME entirely.

Leave `DJANGO_ALLOWED_HOSTS` at its shipped value. Rewriting it locally is precisely how a
broken healthcheck passes a smoke test.

On Windows, two obstacles that do not affect the VPS: port 80 is reserved by winnat (hence
the override), and Git Bash rewrites container-absolute paths — prefix any
`docker … exec`/`run` naming a container path with `MSYS_NO_PATHCONV=1`.
