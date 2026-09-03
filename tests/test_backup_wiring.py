"""Guards for the backup, restore and image-publishing wiring.

Same rationale and shape as test_deploy_wiring.py: none of these files is
exercised by anything else in the suite -- they are consumed by GitHub Actions
and by a shell on a production host, so the only feedback a mistake produces is
a failed backup nobody notices, or a restore that destroys data before it fails.

Textual, not YAML-parsed: pyyaml is not a dependency.

Each assertion names the mutant that makes it fail. An assertion that cannot go
red is not a guard.
"""

import re
import shutil  # noqa: F401 -- used by guards Tasks 3 and 4 append to this file
import subprocess  # noqa: F401 -- used by guards Tasks 3 and 4 append to this file
from pathlib import Path

import pytest  # noqa: F401 -- used by guards Tasks 3 and 4 append to this file

ROOT = Path(__file__).resolve().parent.parent
DEPLOY_YML = ROOT / ".github/workflows/deploy.yml"
DEPLOY_SH = ROOT / "deploy.sh"
BACKUP_SH = ROOT / "backup.sh"
RESTORE_SH = ROOT / "restore.sh"
COMPOSE = ROOT / "docker-compose.prod.yml"
CADDYFILE = ROOT / "Caddyfile"
RUNBOOK = ROOT / "docs/deployment.md"


def test_publish_job_precedes_the_deploy_step():
    """GitHub Actions runs jobs in parallel by default -- textual order in the
    YAML does not serialize them. `needs: publish` is the only thing that makes
    `deploy` wait for the push to finish, so without it a deploy can start
    before the image exists, telling the box to pull a tag that is not there
    yet -- failing on the host rather than in CI, which is the slowest possible
    place to find out.

    Mutant: delete `needs: publish` from the deploy job (block order and step
    order alone cannot catch this, since GitHub Actions ignores YAML position
    when scheduling jobs).
    """
    text = DEPLOY_YML.read_text(encoding="utf-8")
    push = text.find("docker/build-push-action")
    ssh = text.find("appleboy/ssh-action")
    assert push != -1, "deploy.yml no longer publishes an image"
    assert ssh != -1, "deploy.yml no longer deploys"
    assert push < ssh, "the publish step must precede the deploy step"
    assert re.search(r"^\s*deploy:\s*\n\s*needs:\s*publish\s*$", text, re.MULTILINE), (
        "the deploy job must declare `needs: publish`, or the two jobs race"
    )


def test_deploy_logs_in_before_it_pulls():
    """The GHCR package is private (it contains the application source), so an
    un-authenticated pull fails with an opaque `denied`.

    Mutant: delete the docker login line.
    """
    text = DEPLOY_SH.read_text(encoding="utf-8")
    login = text.find("docker login ghcr.io")
    pull = text.find("compose pull")
    assert login != -1, "deploy.sh no longer logs in to ghcr.io"
    assert pull != -1, "deploy.sh no longer pulls"
    assert login < pull, "the login must precede the pull"


def test_no_build_survives_anywhere():
    """The half-finished image switch presents as a box quietly building from
    source while everything else assumes it pulled.

    Mutant: leave a `--build` in deploy.sh or in the runbook's up blocks.
    """
    assert "--build" not in DEPLOY_SH.read_text(encoding="utf-8")
    assert "--build" not in RUNBOOK.read_text(encoding="utf-8")


def test_compose_pulls_a_pinned_tag_rather_than_building():
    """`build: .` on the app service is what this task removes. The tag is
    guarded with the bare `:?` form the file already uses for every mandatory
    value, so a blank fails at `up` rather than pulling something unintended.

    Mutant: restore `build: .`, or drop the `:?` guard.
    """
    text = COMPOSE.read_text(encoding="utf-8")
    assert not re.search(r"^\s*build:\s*\.\s*$", text, re.MULTILINE), text
    assert "ghcr.io/krzyssikora/libli:${LIBLI_IMAGE_TAG:?}" in text, text


def _volumes_declared_in_compose():
    """The names under the top-level `volumes:` key of the compose file.

    Derived, never restated: a volume added to compose must fail the
    classification guard below until someone decides what happens to it.
    """
    lines = COMPOSE.read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.rstrip() == "volumes:")
    names = []
    for ln in lines[start + 1 :]:
        if ln and not ln[0].isspace():
            break
        match = re.match(r"^\s{2}(\w+):\s*$", ln)
        if match:
            names.append(match.group(1))
    return set(names)


def _volume_class():
    """The VOLUME_CLASS array in backup.sh, as {name: class}."""
    text = BACKUP_SH.read_text(encoding="utf-8")
    block = re.search(r"^VOLUME_CLASS=\((.*?)^\)", text, re.MULTILINE | re.DOTALL)
    assert block, "backup.sh no longer declares VOLUME_CLASS"
    return dict(re.findall(r'"(\w+)=([\w-]+)"', block.group(1)))


def test_every_compose_volume_is_classified():
    """Mutant: add a volume to docker-compose.prod.yml -> RED until classified.

    Teaches the detector rather than trimming a baseline: the expected set comes
    from the compose file itself.
    """
    classified = _volume_class()
    assert _volumes_declared_in_compose() == set(classified)
    allowed = {
        "dumped",
        "mirror-plain",
        "mirror-encrypted",
        "archive-encrypted",
        "excluded",
    }
    assert set(classified.values()) <= allowed, classified


def test_every_classification_carries_a_reason():
    """A class with no reason is a decision nobody recorded.

    Mutant: delete a `# <name>:` comment line above VOLUME_CLASS.
    """
    text = BACKUP_SH.read_text(encoding="utf-8")
    for name in _volume_class():
        assert re.search(rf"^# {name}:", text, re.MULTILINE), f"no reason for {name}"


def _line_index(path, pattern):
    """The first NON-COMMENT line matching pattern.

    Skipping comments is load-bearing, not tidiness. backup.sh's header explains
    pipefail with "without it a pg_dump that dies part-way...", and the
    VOLUME_CLASS block says "pgdata: captured by pg_dump, never mirrored" -- both
    contain the literal `pg_dump` and both sit ABOVE the real invocation.
    Matching those would pin every ordering guard to a line that never moves, so
    test_dump_precedes_the_media_mirror would stay green with the dump step moved
    below the media rsync. An assertion that cannot go red is not a guard.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("#"):
            continue
        if re.search(pattern, ln):
            return i
    raise AssertionError(f"{path.name} has no non-comment line matching {pattern!r}")


def test_dump_precedes_the_media_mirror():
    """Dump at T0, media at T1: a file created in between is a harmless orphan.
    Reversed, a file created in between lands in the DUMP with no bytes in the
    mirror -- a row pointing at nothing, which is a broken restore.

    Mutant: swap the two steps.
    """
    assert _line_index(BACKUP_SH, r"pg_dump") < _line_index(BACKUP_SH, r"rsync.*media")


def test_refs_is_written_before_either_mirror_step():
    """refs/ must describe the database the DUMP captured. Written at the end it
    would be read AFTER the screenshot erasure and could agree with a mirror the
    same run just erased from, while the dump still referenced the file.

    Mutant: move list_referenced_files to the end of the script.
    """
    refs = _line_index(BACKUP_SH, r"list_referenced_files")
    assert _line_index(BACKUP_SH, r"pg_dump") < refs
    assert refs < _line_index(BACKUP_SH, r"rsync.*media")
    # `| remote_rm`, not `remote_rm`: the bare name also matches the function
    # DEFINITION near the top of the script, which precedes refs and would make
    # this assertion fail against a correct script. Piping only ever happens at
    # a call site, and the first call site is the screenshot erasure.
    assert refs < _line_index(BACKUP_SH, r"\|\s*remote_rm")


def test_the_erasure_keep_set_includes_refs():
    """Keeping only the live tree reopens the intra-run race: a screenshot whose
    row is deleted after the dump was spooled would be erased from the mirror and
    omitted from a live-DB reading of refs, so CONFIRM would see no discrepancy
    while the dump still pointed at it.

    Mutant: drop refs from the union.
    """
    text = BACKUP_SH.read_text(encoding="utf-8")
    assert re.search(r"keep_set.*refs|refs.*keep_set", text), text


def test_no_delete_anywhere_in_backup():
    """media/ keeps deleted files on purpose; screenshots/ erases by an explicit
    rm of a computed list. `--delete` against a staging dir holding only tonight's
    new files would delete the ENTIRE screenshot history every night --
    `--ignore-existing` suppresses re-transfer and exempts nothing from deletion.

    Mutant: add `--delete` to either rsync.

    Comment lines are skipped for the same reason _line_index skips them: this
    script's own commentary explains at length why --delete must never appear,
    and a raw substring search over the whole file would be red before anyone
    writes a bug -- so the falsification step could demonstrate nothing.
    """
    offenders = [
        ln
        for ln in BACKUP_SH.read_text(encoding="utf-8").splitlines()
        if "--delete" in ln and not ln.lstrip().startswith("#")
    ]
    assert not offenders, offenders


def test_the_dump_is_verified_before_upload():
    """A truncated -Fc archive fails to list. Without this the truncation is
    found at restore time.

    Mutant: remove the pg_restore --list line.
    """
    dump = _line_index(BACKUP_SH, r"pg_dump")
    verify = _line_index(BACKUP_SH, r"pg_restore --list")
    upload = _line_index(BACKUP_SH, r"age -r")
    assert dump < verify < upload


def test_all_three_scripts_fail_on_the_first_error_and_in_a_pipe():
    """pipefail is load-bearing: without it a pg_dump that dies part-way while
    age exits 0 yields a short, well-formed, encrypted file and a GREEN heartbeat.

    Mutant: drop `pipefail` from any of the three.
    """
    for path in (DEPLOY_SH, BACKUP_SH, RESTORE_SH):
        lines = path.read_text(encoding="utf-8").splitlines()
        # The shebang is checked on the RAW first line. Filtering `#`-prefixed
        # lines first would drop it -- `#!/usr/bin/env bash` starts with `#` --
        # and `body[0].startswith("#!")` could then never be true for any script.
        assert lines[0].startswith("#!"), f"{path.name}: {lines[0]!r}"
        # Then the first line that is neither blank nor a comment. deploy.sh
        # carries a long header comment between its shebang and its `set` line
        # while backup.sh and restore.sh put `set` on line 2, so a positional
        # index cannot treat the three uniformly -- but "first real line" can.
        real = next(
            ln for ln in lines[1:] if ln.strip() and not ln.lstrip().startswith("#")
        )
        assert real == "set -euo pipefail", f"{path.name}: {real!r}"


def test_all_three_scripts_share_one_lock_path():
    """Otherwise the risk table claims a mitigation that does not exist.

    Mutant: give backup.sh its own lock file.
    """
    paths = set()
    for path in (DEPLOY_SH, BACKUP_SH, RESTORE_SH):
        found = re.findall(r"/var/lock/\S+\.lock", path.read_text(encoding="utf-8"))
        assert found, f"{path.name} takes no lock"
        paths |= set(found)
    assert len(paths) == 1, paths


def test_compose_still_declares_the_project_name_vol_path_depends_on():
    """vol_path() resolves `libli_<volume>`; that prefix is Docker's
    <project>_<volume> convention and comes from `name: libli`.

    Mutant: rename or delete the project name.
    """
    assert re.search(
        r"^name: libli$", COMPOSE.read_text(encoding="utf-8"), re.MULTILINE
    )


def test_the_runbook_cron_line_matches_the_script_path():
    """Mutant: move backup.sh without updating §7."""
    runbook = RUNBOOK.read_text(encoding="utf-8")
    assert "/opt/libli/backup.sh" in runbook, "the runbook does not schedule backup.sh"
    assert "15 2 * * *" in runbook, "the cron slot collides with purge_notifications"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not on PATH")
@pytest.mark.parametrize("script", ["deploy.sh", "backup.sh", "restore.sh"])
def test_scripts_parse(script):
    """Mutant: drop a closing brace from any helper."""
    result = subprocess.run(  # noqa: S603 -- fixed argv, repo-relative path
        [shutil.which("bash"), "-n", str(ROOT / script)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_restore_loads_the_database_before_the_app_starts():
    """The entrypoint runs `migrate` on every boot, so bringing the full stack up
    against an empty database creates the schema and the dump then collides.

    Mutant: replace `up -d db` with `up -d`.
    """
    text = RESTORE_SH.read_text(encoding="utf-8")
    db_up = _line_index(RESTORE_SH, r"compose up -d db\b")
    load = _line_index(RESTORE_SH, r"pg_restore")
    assert db_up < load
    head = text.splitlines()[:load]
    assert not [ln for ln in head if re.search(r"compose up -d\s*$", ln)], head


def test_volumes_are_materialised_before_paths_are_resolved():
    """`up -d db` creates only pgdata; media, support_screenshots and caddy_data
    belong to app and caddy, which do not start until later -- so vol_path would
    fail on volumes that do not exist. `compose create` makes them WITH compose's
    labels; `docker volume create` would make unlabelled ones compose then
    refuses to adopt.

    Mutant: delete the compose create line.
    """
    # Anchored on the first CALL, not the definition: vol_path() is defined up
    # with the other helpers in the ENV section, which is before compose create.
    assert _line_index(RESTORE_SH, r"compose create") < _line_index(
        RESTORE_SH, r"vol_path caddy_data"
    )


def test_rotate_secrets_writes_before_it_wipes():
    """POSTGRES_PASSWORD is read by postgres ONLY while it initialises an empty
    data directory. Rotated after the wipe, the database keeps the old password
    while the app uses the new one.

    Mutant: move the generation below `compose down`.
    """
    gen = _line_index(RESTORE_SH, r"rotate_secrets|openssl rand")
    assert gen < _line_index(RESTORE_SH, r"compose down --volumes")


def test_confirm_proves_the_artifacts_exist_before_it_prompts():
    """Otherwise a never-pruned manifest/ lets an operator pick a <ts> whose
    artifacts are gone; it passes every early check and fails at ENV, after the
    confirmation has already been typed.

    Mutant: move the existence check below the read.
    """
    assert _line_index(RESTORE_SH, r"db/\$TS\.dump\.age") < _line_index(
        RESTORE_SH, r"^\s*read "
    )


def test_completeness_is_checked_before_the_wipe():
    """Mutant: move the refs diff after `compose down`."""
    assert _line_index(RESTORE_SH, r"refs/\$TS\.txt") < _line_index(
        RESTORE_SH, r"compose down --volumes"
    )


def test_a_missing_artifact_exits_but_a_refs_gap_does_not():
    """The asymmetry is the point. A refs gap is often LEGITIMATE -- media is
    pruned at 90 days and screenshots are erased on deletion, while dumps are
    kept 13 months -- so refusing on one would make every old-enough <ts>
    unrestorable. The typed slug IS the knowing acceptance.

    Mutant: make a refs gap exit non-zero.
    """
    text = RESTORE_SH.read_text(encoding="utf-8")
    missing_block = re.search(r"missing artefact.*?\n(.*?)\nfi", text, re.DOTALL)
    assert missing_block and "exit 1" in missing_block.group(1), text
    gap_block = re.search(r"refs gap.*?\n(.*?)\nfi", text, re.DOTALL)
    assert gap_block and "exit" not in gap_block.group(1), text


def test_the_checkout_must_match_the_image():
    """The compose file governs the postgres major, the volume names and the
    healthcheck, so a checkout newer than the image can disagree with it.

    Mutant: delete the `if [ "$checkout_tag" != "$target_tag" ]; then ... fi`
    comparison block entirely (`checkout_tag="sha-$(git rev-parse HEAD)"` is an
    assignment that stays behind on its own, so a bare substring match on
    "git rev-parse HEAD" cannot detect that). Or, keep the `if`/`fi` but gut
    the body -- replace the two `echo`s and `exit 1` with a no-op `:` -- which
    a window stretched all the way to the next step marker cannot catch,
    because the migration-containment and postgres-major checks that follow
    inside that wider window carry their own `exit 1`s. The window here is the
    comparison's OWN block only: from the `if` line to ITS matching `fi` (the
    next line that is exactly `fi`, since this script's blocks are flat and
    unnested), not to a step marker.
    """
    lines = RESTORE_SH.read_text(encoding="utf-8").splitlines()
    cmp_idx = next(
        i
        for i, ln in enumerate(lines)
        if re.search(r'\[ "\$checkout_tag" != "\$target_tag" \]', ln)
    )
    fi_idx = next(i for i, ln in enumerate(lines) if i > cmp_idx and ln == "fi")
    block = lines[cmp_idx + 1 : fi_idx]
    assert any(re.search(r"\bexit\b", ln) for ln in block), block


def test_image_tag_is_format_checked():
    """ "Never floating master" in a runbook is an instruction to a human. The
    checkout-sha comparison needs a sha to compare.

    Mutant: widen the enforced pattern (e.g. `grep -Eq '^sha-.*'`), or delete
    the grep entirely while leaving the error text's literal pattern behind --
    a bare substring match on "^sha-[0-9a-f]" cannot tell the enforcing site
    from dead informational text quoting the same pattern. There must be
    exactly ONE enforcing site: a redundant `case` block that only checked the
    prefix has been collapsed into this single grep.
    """
    lines = RESTORE_SH.read_text(encoding="utf-8").splitlines()
    assert any("grep -Eq" in ln and "^sha-[0-9a-f]{7,40}$" in ln for ln in lines), lines


def test_pre_cutover_disables_acme_by_the_scheme():
    """The Caddyfile has NO tls directive -- automatic HTTPS is driven entirely
    by whether {$SITE_ADDRESS} parses as a domain. The http:// scheme plus
    DJANGO_SECURE_SSL_REDIRECT=false is the pair the runbook already documents
    for local smoke runs.

    Mutant: drop the scheme rewrite -> the restore attempts ACME against DNS
    still pointing at the old box, burning the failed-validation budget.
    """
    text = RESTORE_SH.read_text(encoding="utf-8")
    assert "SITE_ADDRESS=http://" in text, text
    assert "DJANGO_SECURE_SSL_REDIRECT=false" in text, text
    assert not re.search(
        r"^\s*tls\b", CADDYFILE.read_text(encoding="utf-8"), re.MULTILINE
    )
