"""Shared fixtures for the B2 release-deploy tests.

Real git everywhere: history, tags and ancestry ARE what these scripts judge,
so a stubbed git would test nothing. Files are written with write_bytes so a
Windows checkout cannot smuggle CRLF into a bash script, and every fixture repo
sets core.autocrlf=false for the same reason.
"""

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASH = shutil.which("bash")

COMPOSE_TMPL = (
    "services:\n"
    "  db:\n"
    "    image: postgres:{pg}\n"
    "  app:\n"
    "    image: ghcr.io/krzyssikora/libli:${{LIBLI_IMAGE_TAG:?}}\n"
    "    environment:\n"
    "      DATABASE_URL: postgres://u:p@db:5432/libli\n"
)


def posix(path):
    return str(path).replace("\\", "/")


def write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def git(cwd, *args):
    result = subprocess.run(  # noqa: S603 -- fixed argv
        ["git", *args],  # noqa: S607 -- git on PATH
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout.strip()


def init_repo(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "master")
    for key, value in (
        ("user.name", "test"),
        ("user.email", "test@example.com"),
        ("core.autocrlf", "false"),
        ("commit.gpgsign", "false"),
        ("tag.gpgsign", "false"),
    ):
        git(path, "config", key, value)
    return path


def commit_all(repo, msg):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


# ---- the box: an origin, a working repo that authors commits, and the clone
# at <tmp>/app that deploy.sh runs in. deploy.sh is committed with its box
# paths rewritten to the fixture -- the shipped script carries no test hooks.


# deploy.sh only needs the GHCR token to be non-empty.
TOKEN_LINE = "LIBLI_GHCR_TOKEN=" + "x" * 8


def deploy_sh_for(app, lock, source=None):
    text = (
        source
        if source is not None
        else (ROOT / "deploy.sh").read_text(encoding="utf-8")
    )
    assert "APP_DIR=/opt/libli" in text and "/var/lock/libli-deploy.lock" in text
    return text.replace("APP_DIR=/opt/libli", f"APP_DIR={posix(app)}").replace(
        "/var/lock/libli-deploy.lock", posix(lock)
    )


class Box:
    def __init__(self, tmp):
        self.tmp = Path(tmp)
        self.work = init_repo(self.tmp / "work")
        self.origin = self.tmp / "origin.git"
        git(self.tmp, "init", "-q", "--bare", "-b", "master", posix(self.origin))
        git(self.work, "remote", "add", "origin", posix(self.origin))
        self.app = self.tmp / "app"
        self.log = self.tmp / "calls"
        write(self.log, "")

    def commit(
        self, *, pg="16", migrations=(), extra=None, deploy_sh=None, guard=None, msg="c"
    ):
        """One release-shaped commit, pushed to origin/master."""
        write(
            self.work / "deploy.sh",
            deploy_sh_for(self.app, self.tmp / "deploy.lock", deploy_sh),
        )
        write(self.work / "docker-compose.prod.yml", COMPOSE_TMPL.format(pg=pg))
        write(self.work / "Caddyfile", "{$SITE_ADDRESS} {\n}\n")
        write(self.work / "uv.lock", "lock\n")
        guard_text = (
            guard
            if guard is not None
            else (ROOT / "scripts/release/migration_guard.sh").read_text(
                encoding="utf-8"
            )
        )
        write(self.work / "scripts/release/migration_guard.sh", guard_text)
        for name in migrations:
            write(self.work / f"courses/migrations/{name}.py", f"# {name}\n")
        for rel, text in (extra or {}).items():
            write(self.work / rel, text)
        sha = commit_all(self.work, msg)
        git(self.work, "push", "-q", "origin", "master")
        return sha

    def tag(self, name, sha, run_id="1", force=False):
        git(
            self.work,
            "tag",
            *(["-f"] if force else []),
            "-a",
            name,
            sha,
            "-m",
            f"Release {name}",
            "-m",
            f"canary-run: {run_id}",
        )
        git(
            self.work,
            "push",
            "-q",
            *(["-f"] if force else []),
            "origin",
            f"refs/tags/{name}",
        )

    def clone(self, sha, *, detached, image_tag, channel_line=None, extra_env=""):
        """The box as provisioned: a clone at `sha` plus .env.production.
        image_tag=None writes no LIBLI_IMAGE_TAG line at all."""
        # `clone -c` writes the setting into the new repo BEFORE the initial
        # checkout. Setting it afterwards is too late: on a machine with
        # core.autocrlf=true in the system/global config, the clone would
        # already have written deploy.sh with CRLF, and a later checkout never
        # rewrites a stat-clean, byte-identical file.
        git(
            self.tmp,
            "clone",
            "-q",
            "-c",
            "core.autocrlf=false",
            posix(self.origin),
            posix(self.app),
        )
        assert b"\r" not in (self.app / "deploy.sh").read_bytes(), (
            "fixture clone got CRLF"
        )
        if detached:
            git(self.app, "checkout", "-q", "--detach", sha)
        else:
            git(self.app, "reset", "-q", "--hard", sha)
        lines = [
            # Built at runtime and neutrally named below: GitGuardian scans this
            # repo and has failed a PR over a secret-SHAPED literal before.
            TOKEN_LINE,
            "SITE_ADDRESS=school.example",
            "DJANGO_SITE_DOMAIN=school.example",
            "SENTINEL_LINE=SENTINEL-LINE-0f9e",
        ]
        if image_tag is not None:
            lines.append(f"LIBLI_IMAGE_TAG={image_tag}")
        if channel_line is not None:
            lines.append(channel_line)
        write(self.app / ".env.production", "\n".join(lines) + "\n" + extra_env)

    def bootstrap_to(self, sha):
        """What deploy.yml's own script does before invoking deploy.sh."""
        git(self.app, "fetch", "-q", "origin", "master")
        git(self.app, "reset", "-q", "--hard", sha)


def _prelude(log):
    """docker, curl, flock and sleep as EXPORTED bash functions: a function
    shadows a PATH lookup on every platform, and `export -f` carries it into
    the `bash deploy.sh` child. FAIL_AT=pull|up|hup makes that step fail
    (hup: SIGHUP to the deploy shell itself, as a terminal hang-up would)."""
    log = posix(log)
    return f"""
docker() {{
  echo "docker $*" >> "{log}"
  case "$*" in
    *" pull"*)
      echo "pull-tag=${{LIBLI_IMAGE_TAG:-<unset>}}" >> "{log}"
      [ "${{FAIL_AT:-}}" = pull ] && return 1
      [ "${{FAIL_AT:-}}" = hup ] && kill -HUP $$
      ;;
    *" up "*)
      cp .env.production "{log}.env-at-up"
      echo "up-shell-tag=${{LIBLI_IMAGE_TAG:-<unset>}}" >> "{log}"
      [ "${{FAIL_AT:-}}" = up ] && return 1
      ;;
    login*) cat > /dev/null ;;
    run*)
      # REWRITE_TARGET/REWRITE_WITH: overwrite the running deploy.sh IN PLACE
      # (same inode), mid-run -- see
      # test_an_in_place_rewrite_of_the_running_script_changes_nothing.
      if [ -n "${{REWRITE_TARGET:-}}" ]; then
        cat "$REWRITE_WITH" > "$REWRITE_TARGET"
      fi
      ;;
  esac
  return 0
}}
curl() {{ echo "curl $*" >> "{log}"; echo '{{"status": "ok"}}'; }}
flock() {{ echo "flock $*" >> "{log}"; }}
sleep() {{ :; }}
# FAIL_FETCHES=N: the first N `git fetch` calls exit 128 (the anonymous-401
# flake); everything else is the real git. The count lands in <log>.fetches.
git() {{
  if [ "$1" = fetch ] && [ -n "${{FAIL_FETCHES:-}}" ]; then
    local n
    n=$(( $(cat "{log}.fetches" 2>/dev/null || echo 0) + 1 ))
    echo "$n" > "{log}.fetches"
    if [ "$n" -le "$FAIL_FETCHES" ]; then return 128; fi
  fi
  command git "$@"
}}
export -f docker curl flock sleep git
"""


def run_deploy(box, env=None, script=None):
    """Run the box's deploy.sh (or `script`) the way a host would: `bash <file>`."""
    import os

    clean = {k: v for k, v in os.environ.items() if not k.startswith("LIBLI_")}
    clean.pop("FAIL_AT", None)
    clean.update(env or {})
    target = posix(script or box.app / "deploy.sh")
    return subprocess.run(  # noqa: S603 -- fixed argv, generated script
        [BASH, "-c", _prelude(box.log) + f'\nbash "{target}"'],
        capture_output=True,
        text=True,
        env=clean,
        timeout=120,
        # Never inherit a terminal: git for Windows prompts on stdin when it
        # cannot unlink an open file, which would hang the suite.
        stdin=subprocess.DEVNULL,
    )


def calls(box):
    return box.log.read_text(encoding="utf-8")


def env_at_up(box):
    path = Path(f"{box.log}.env-at-up")
    return path.read_text(encoding="utf-8") if path.exists() else ""


def head(box):
    return git(box.app, "rev-parse", "HEAD")


def on_branch(box):
    result = subprocess.run(  # noqa: S603 -- fixed argv
        ["git", "symbolic-ref", "-q", "HEAD"],  # noqa: S607 -- git on PATH
        cwd=box.app,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0
