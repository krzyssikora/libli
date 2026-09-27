"""The runbook facts an operator acts on for B2 (spec §9)."""

import re

from tests.release_harness import ROOT

RUNBOOK = ROOT / "docs/deployment.md"


def _text():
    return RUNBOOK.read_text(encoding="utf-8")


def _section(title):
    text = _text()
    start = text.index(title)
    nxt = re.search(r"^## ", text[start + len(title) :], re.MULTILINE)
    return text[start : start + len(title) + (nxt.start() if nxt else len(text))]


def test_the_schools_section_exists_and_names_the_secrets():
    s = _section("## 9. Schools")
    for fact in (
        "SCHOOL_HOSTS",
        "SCHOOLS_SSH_KEY",
        "HEALTHCHECKS_SCHOOL_DEPLOY_URL",
        "cut-release",
        "deploy-release",
        "registrable domain",
    ):
        assert fact in s, fact


def test_first_boot_adds_the_channel_line_only_after_up():
    """The only order in which no step resets a school to master."""
    s = _section("## 9. Schools")
    assert s.index("up -d") < s.index("LIBLI_DEPLOY_CHANNEL=release")


def test_provisioning_includes_the_admin_and_the_backup_cron():
    """Mutant: drop the §5/§7 sentence -- a box built by §9 alone has no
    admin and no backups, so D3's restore path has nothing to restore."""
    s = _section("## 9. Schools")
    assert "**§5**" in s and "**§7**" in s and "nightly backup" in s


def test_the_cited_canary_run_must_never_be_deleted():
    assert "never delete a `deploy.yml` run" in _section("## 9. Schools").lower()


def test_the_in_place_restore_is_documented():
    s = _section("## 9. Schools")
    assert "git checkout --force --detach <manifest git_sha>" in s
    assert "restore.sh" in s


def test_the_d9_red_run_is_explained():
    assert "superseded by" in _section("## 8. Continuous deployment")


def test_section_8_no_longer_says_a_pull_failure_takes_the_site_down():
    """After B2 a login or pull failure is pre-`up`: site up, checkout restored."""
    s = _section("## 8. Continuous deployment")
    assert "The first two happen before" in s
    assert "The other three do not" not in s
    assert "the\n  rollback path below" not in s
    assert "the rollback path below" not in s


def test_the_libli_rollback_recipe_uses_deploy_sh_with_a_ref():
    """A bare `compose up` after a reset starts whatever LIBLI_IMAGE_TAG
    already says; `bash deploy.sh` with no ref resets straight back to master.
    """
    text = _text()
    assert "LIBLI_DEPLOY_REF=<last-good-sha> bash deploy.sh" in text
    assert "git reset --hard <last-good-sha>\ndocker compose" not in text
    assert "`git reset --hard <last-good-sha>` then `bash deploy.sh`" not in text
