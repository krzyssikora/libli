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

Then:

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
==> init_platform
==> gunicorn
```

`setup_roles` is the one that matters and the one no test can catch: permissions live as
constants in `institution/roles.py` but are only *assigned* by `seed_roles()`, and the
test suite calls it itself so it passes either way. If `init_platform` reports *skipped*,
one of the three `INIT_ADMIN_*` values is missing.

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

## 5. First-run wizard

Sign in as `INIT_ADMIN_USERNAME` and walk `https://<host>/manage/setup/` — note the path is
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

## Known constraints

- **One `app` container.** `migrate` runs in the entrypoint; the staging dir is a local
  volume.
- **No backups.** No `pg_dump` cron, no snapshot policy.
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
