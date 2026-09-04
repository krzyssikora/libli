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
apt-get update && apt-get install -y ca-certificates curl git age rsync
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
```

```bash
docker login ghcr.io -u krzyssikora    # paste a CLASSIC PAT with read:packages
```

Stay on an Ubuntu LTS the Docker repo actually publishes for. A release newer than the
repo's coverage fails at `apt-get install docker-ce` with no obvious cause.

`rsync` is in that first `apt-get install` because both `backup.sh` and `restore.sh` depend
on it — it is how they list, mirror and fetch from the Storage Box — and Ubuntu's minimal
cloud images do not ship it. Missing, the first nightly backup fails at its first `rsync`.

Set the host clock to UTC:

```bash
timedatectl set-timezone UTC
```

Cron's `15 2 * * *` slot for `backup.sh` (§7), the `<ts>` it stamps on every artifact, and
the `taken_at` field in each night's manifest must all be readings of the **same** clock —
otherwise "restore to last Tuesday's 02:15 run" requires converting between the box's local
time and the UTC the artifact is actually named in.

Place the Storage Box restore key this box will use for its own nightly uploads (this is
the box's **write** credential, `LIBLI_BACKUP_SSH_KEY_PATH` — not the separate restore-only
credential a *recovery* uses, which never lives on a server; see
[docs/backup-and-restore.md](backup-and-restore.md)):

```bash
install -m 600 /dev/null /root/.ssh/libli_backup
nano /root/.ssh/libli_backup      # paste the private key, save
```

`.env.production` (§3) then points `LIBLI_BACKUP_SSH_KEY_PATH` at this path — a path, not
the key material inline: `env_value()` reads one line, and a multi-line PEM would be
silently truncated to its `-----BEGIN…` header.

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

Set `LIBLI_IMAGE_TAG` to the `sha-<full-sha>` tag you intend to run before this; every later
deploy writes it for you.

Then — this is the **only** time you run this by hand; every later deploy is §8:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up -d
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

And the nightly backup — **one physical line**, same as above:

```cron
15 2 * * * bash /opt/libli/backup.sh >> /var/log/libli-backup.log 2>&1
```

`15 2`, deliberately not `30 3`: a dump competing with the retention purge for the
same container and disk is avoidable. The host clock is UTC, so this, the artifact
timestamps and `taken_at` are all the same clock.

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

Backups and restores are in [docs/backup-and-restore.md](backup-and-restore.md).

### There is no test job — that is deliberate

`ci.yml` runs on the pull request, and branch protection requires its three jobs before
the PR can merge. So `master` only ever holds a commit that already went green, and
re-running the suite on the merge commit would be a second copy of the same result.

**Branch protection is therefore load-bearing, not hygiene.** With it off — or bypassed
by an admin push straight to `master` — the merge deploys code nothing has tested. If you
ever turn it off, put a test job back into `deploy.yml`.

### One-time setup

**§8 involves two different SSH keys, in opposite directions.** This one lets the Actions
runner into the host. The other — in *Fetching over SSH* below, and optional — lets the host
into GitHub. They share nothing: different files, different machines, different install
commands. Mixing them up is the likeliest mistake in this section:

| | this one | *Fetching over SSH* |
|---|---|---|
| direction | runner **→** host | host **→** github.com |
| file | `~/.ssh/libli_github_actions` | `~/.ssh/libli_repo` |
| generated on | your own machine | the host |
| the PUBLIC half goes to | the host's `authorized_keys`, via `ssh-copy-id` | the repo's deploy keys, via `gh repo deploy-key add` |
| the PRIVATE half lives in | the `SSH_KEY` repo secret | the host, and nowhere else |

`ssh-copy-id` appears only in this row. It installs a key into a remote *host's*
`authorized_keys`, and GitHub deploy keys are not `authorized_keys` — they are repo
settings, reachable only through the API or the web UI.

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

`SSH_KEY` is the **private** key.

Nothing else needs seeding on the host, including on a box whose checkout predates CD:
`deploy.yml` resets to `origin/master` itself before invoking `deploy.sh`, precisely so
the script that fetches the repo does not have to already be in the repo it fetches.
`deploy.sh` needs no execute bit either -- the workflow invokes it as
`bash /opt/libli/deploy.sh`, which is deliberate, because git on Windows records none.

And branch protection (**already applied 2026-08-28**; kept here for a rebuild):

```bash
gh api -X PUT repos/krzyssikora/libli/branches/master/protection --input - <<'JSON'
{
  "required_status_checks": {"strict": false, "contexts": ["lint", "unit", "e2e"]},
  "enforce_admins": false,
  "required_pull_request_reviews": {"required_approving_review_count": 0},
  "restrictions": null
}
JSON
```

A JSON body, not `-f key[sub]=value`: this endpoint rejects the bracket form with
`"required_pull_request_reviews", "required_status_checks" weren't supplied` (422).
`restrictions: null` is required and must be present even though it is empty.

`strict=false` is on purpose: `strict` would require every PR to be rebased onto the tip
before merging, which re-runs CI on each intervening merge — reintroducing the
duplication this arrangement exists to remove.

### Alerting on a failed deploy

A red deploy notifies nobody by default. #295 and #296 both failed and production sat about
30 hours behind master until #297's deploy happened to succeed. `deploy.yml`'s last step
reports every outcome to a [healthchecks.io](https://healthchecks.io) check — the plain ping
URL on success, `URL/fail` otherwise — and the check's own alert is the notification.

One-time, on healthchecks.io (free tier):

1. Create a check named `libli deploy`.
2. Set **period 30 days, grace 3 days**. This is deliberately far longer than any deploy
   cadence: the period is not there to watch for deploys, it is a liveness check on the
   ALERTING ITSELF. If pings stop arriving entirely — a broken step, a revoked URL, a
   forgotten secret — the dead-man's-switch fires on its own. The cost is one "no ping"
   alert if you ever go a month without deploying, which is the channel proving it works.
3. Copy the ping URL (`https://hc-ping.com/<uuid>`).

Then, from your own machine:

```bash
gh secret set HEALTHCHECKS_DEPLOY_URL --repo krzyssikora/libli --body "https://hc-ping.com/<uuid>"
```

**The ping URL is a credential — never commit it.** Anyone holding it can mark your deploys
healthy. It lives in the repo secret and nowhere else; GitGuardian scans every commit.

Two behaviours worth knowing before you rely on it:

- **Until the secret exists, the step prints one line and exits 0.** Merging the step before
  creating the check cannot redden a deploy.
- **A failed ping does not fail the deploy.** A healthchecks.io outage must not turn a
  working deploy red — the site is up either way. That is exactly what the long period
  above is the backstop for.

A failed deploy leaves the check DOWN until the next successful one pings it up, so the
dashboard answers "is production running master?" and not merely "did the last run go red".

### Fetching over SSH (removes the anonymous-fetch failures)

Optional, and worth doing only if the 401 above recurs despite the retry. The host fetches
`https://github.com/krzyssikora/libli` **anonymously** — the repo is public, so no
credential is involved — and GitHub throttles anonymous git per IP. An authenticated fetch
is not subject to those limits.

A read-only **deploy key** is the way to authenticate: scoped to this one repo, no expiry to
diarise, and it cannot push. It is NOT the key from *One-time setup* and is not installed
with `ssh-copy-id` — see the table there if the two have run together.

The three blocks below run on **two different machines**, and the middle one is the switch.

**On the host** — generate the key, and print its public half:

```bash
ssh root@<ip>
ssh-keygen -t ed25519 -f ~/.ssh/libli_repo -C "libli-prod-fetch" -N ""
cat ~/.ssh/libli_repo.pub          # copy this line
```

**On your own machine** — register that public half as a deploy key. Paste the printed line
into a local file first; `gh` reads a file, and the host has no `gh`. Leave write access
unchecked, which is the default:

```bash
gh repo deploy-key add thatfile.pub --repo krzyssikora/libli --title "libli prod host (read-only)"
gh repo deploy-key list --repo krzyssikora/libli     # confirm it is there, and read-only
```

The public half is public: pasting it between machines costs nothing. The private
`~/.ssh/libli_repo` never leaves the host.

**Back on the host** — **`ssh-keyscan` first**:

```bash
ssh-keyscan github.com >> ~/.ssh/known_hosts
cat >> ~/.ssh/config <<'EOF'
Host github.com
    User git
    IdentityFile ~/.ssh/libli_repo
    IdentitiesOnly yes
EOF
chmod 600 ~/.ssh/config
cd /opt/libli
git remote set-url origin git@github.com:krzyssikora/libli.git
```

**The `ssh-keyscan` line is the trap.** Without it github.com's host key is unknown, and the
first connection asks whether to trust it. Yours will not: an interactive `ssh -T` prompts
you and you accept. The *deploy* has no tty, so it fails with `Host key verification failed`
— the fault appears one deploy later, with nobody watching, and looks nothing like its cause.

Verify before relying on it — **on the host**, in that same session. Three separate
commands, never chained with `&&`:

```bash
ssh -T git@github.com
git remote -v                          # MUST show git@github.com:... FIRST
git fetch origin master                # only now does this test anything
```

**The order of those last two is not cosmetic.** Against a remote still on the `https://`
URL, `git fetch` succeeds anonymously exactly as it always did — a green result that says
nothing whatever about SSH, on the one command you are relying on to prove the change
worked. Confirm what the remote IS before testing what it does.

**`ssh -T git@github.com` exits 1 even when it succeeds**, because GitHub has no shell to
hand you. Chaining it with `&&` therefore stops the run dead after a *successful* auth, and
a working setup reads as a broken one. Judge it by the greeting, not the exit code:

- `Hi krzyssikora/libli! You've successfully authenticated…` — the DEPLOY KEY answered. The
  repo name is what tells you so, and it is what you want.
- `Hi krzyssikora! …` — your PERSONAL key answered instead (an agent, or another
  `IdentityFile`). Interactive fetches would work and the deploy would still fail, because
  it runs without your agent. Fix `~/.ssh/config` before going on; `IdentitiesOnly yes` is
  what stops a loaded agent key being offered first.

Verifying from your own machine proves nothing here: it would exercise your key, not the
host's, and the host is the only machine whose fetch is changing.

If either command fails, revert and investigate before the next merge:

```bash
git remote set-url origin https://github.com/krzyssikora/libli.git
```

**Do this when no deploy is in flight, and not in the same window as a merge.** A mistake
here breaks the *next* deploy at its first command, so it wants to be the only change in
play when that deploy runs.

Nothing in the test suite guards any of this: the remote is state on the host, not in the
repo. `tests/test_deploy_wiring.py` can prove `deploy.sh` retries a failed fetch; only that
`git fetch` above can prove the host can fetch at all.

### Deploying without a commit

```bash
gh workflow run deploy.yml --repo krzyssikora/libli
```

Use this after editing `.env.production` on the host, which no commit can trigger.

### When a deploy goes red

**Before any of the below: check whether it even got past the fetch.**

```
fatal: could not read Username for 'https://github.com': No such device or address
```

That is GitHub answering an **anonymous** fetch of this (public) repo with a 401 challenge,
which git cannot satisfy without a tty. It is not a credential problem — a public fetch
needs none. It killed the #293, #295 and #296 deploys; in #296 the fetch 440 ms earlier had
*succeeded*, so treat it as throttling of the host's IP rather than anything on the box.
Both fetches now retry three times, five seconds apart, which absorbs it. If a red run
still shows this after three attempts, **the site is untouched** — nothing had been rebuilt
yet — so re-run the workflow rather than reaching for the recovery below.

The retry absorbs it; it does not remove it. **Fetching over SSH** below is the durable
fix, and is worth applying if this signature shows up again.

Past that point `deploy.sh` fails loudly at four places, in order: the Caddyfile does not
parse, **the GHCR login or the pull fails**, the app container never reports healthy
(`--wait`), or the public URL does not answer `/healthz/`. The first leaves the running site
untouched. The other three do not: the old container is already gone, so a red run means the
site is **down**, not merely un-updated.

(The second point used to be "the build fails". The box no longer builds — it pulls a
published image — so a failure there is now a registry or credential problem, not a
compilation one.)

There is no automatic rollback. Recovery is manual and takes one pull:

```bash
ssh root@<ip>
cd /opt/libli
git reset --hard <last-good-sha>
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --wait
```

`git reset --hard <sha>` still does what it always did — `deploy.sh` derives
`LIBLI_IMAGE_TAG` from the checkout, so moving the checkout moves the image.

A migration that fails part-way is the case that needs care — the schema may be ahead of
the code you just reset to. Read `logs app | grep '==>'` before assuming a rebuild fixes it.

### Two things about `deploy.sh` worth knowing

- **The reset happens twice, on purpose — the fetch no longer does.** `deploy.yml` resets
  the checkout before it runs `deploy.sh`, and `deploy.sh` resets again. The workflow copy
  bootstraps a host that has no `deploy.sh` yet and guarantees bash parses the version this
  commit ships; the script copy is what makes running `bash deploy.sh` by hand -- the
  rollback path below -- correct on its own. Deleting either one breaks a case the other
  does not cover. The **fetch** is a different matter: two requests to github.com inside a
  second is what tripped #296, so `deploy.yml` sets `LIBLI_DEPLOY_SKIP_FETCH=1` and
  `deploy.sh` resets to the ref CI just fetched. Run by hand the variable is unset, so the
  fetch happens — which is exactly what the rollback path needs.
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
- **Every deploy is a short window of 502s.** `up -d` pulls the new image and recreates the
  app container; Caddy stays up and answers 502 until the new container passes its
  healthcheck. Shorter than it was when the box built its own image, because the pull is
  the only work done here and the build already happened on the runner.
- **Rollback is one pull.** `git reset --hard <last-good-sha>` then `bash deploy.sh`: the
  tag follows the checkout, so the previous image is pulled rather than rebuilt. What this
  cannot undo is an **already-applied migration** — the schema stays ahead of the code, and
  that case needs a restore from `docs/backup-and-restore.md`, not a rollback.
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
