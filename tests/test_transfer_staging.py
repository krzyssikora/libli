import os
import time

import pytest
from django.contrib.sessions.backends.db import SessionStore
from django.core.files.uploadedfile import SimpleUploadedFile

from courses.transfer import staging


@pytest.fixture(autouse=True)
def _staging_dir(settings, tmp_path):
    settings.TRANSFER_STAGING_DIR = tmp_path
    return tmp_path


@pytest.fixture
def session(db):
    return SessionStore()


def _upload(content=b"zip-bytes"):
    return SimpleUploadedFile("course.zip", content, content_type="application/zip")


@pytest.mark.django_db
def test_stage_then_claim_returns_claimed_path_and_clears_slot(session):
    token, path = staging.stage(session, staging.SLOT_COURSE, _upload())
    assert path.exists()
    assert path.read_bytes() == b"zip-bytes"

    claimed = staging.claim(session, staging.SLOT_COURSE, token)

    assert claimed is not None
    assert claimed.exists()
    assert claimed.name.endswith(".claimed.zip")
    assert not path.exists()  # renamed away
    assert staging.SLOT_COURSE not in staging._slots(session)


@pytest.mark.django_db
def test_second_claim_with_same_token_returns_none(session):
    token, path = staging.stage(session, staging.SLOT_COURSE, _upload())
    first = staging.claim(session, staging.SLOT_COURSE, token)
    assert first is not None

    second = staging.claim(session, staging.SLOT_COURSE, token)
    assert second is None


@pytest.mark.django_db
def test_claim_with_wrong_token_returns_none(session):
    token, path = staging.stage(session, staging.SLOT_COURSE, _upload())
    result = staging.claim(session, staging.SLOT_COURSE, "not-the-real-token")
    assert result is None
    # slot is untouched, staged file still there
    assert path.exists()
    assert staging.SLOT_COURSE in staging._slots(session)


@pytest.mark.django_db
def test_claim_with_missing_slot_returns_none(session):
    result = staging.claim(session, staging.SLOT_COURSE, "whatever")
    assert result is None


@pytest.mark.django_db
def test_subtree_course_pk_mismatch_returns_none(session):
    token, path = staging.stage(session, staging.SLOT_SUBTREE, _upload(), course_pk=42)
    result = staging.claim(session, staging.SLOT_SUBTREE, token, course_pk=99)
    assert result is None
    assert path.exists()


@pytest.mark.django_db
def test_subtree_course_pk_match_succeeds(session):
    token, path = staging.stage(session, staging.SLOT_SUBTREE, _upload(), course_pk=42)
    result = staging.claim(session, staging.SLOT_SUBTREE, token, course_pk=42)
    assert result is not None


@pytest.mark.django_db
def test_stage_supersedes_previous_upload_deleting_its_file(session):
    token1, path1 = staging.stage(session, staging.SLOT_COURSE, _upload(b"first"))
    assert path1.exists()

    token2, path2 = staging.stage(session, staging.SLOT_COURSE, _upload(b"second"))

    assert not path1.exists()  # superseded file was deleted
    assert path2.exists()
    assert token1 != token2

    # old token no longer claims anything
    assert staging.claim(session, staging.SLOT_COURSE, token1) is None
    # new token claims the new file
    claimed = staging.claim(session, staging.SLOT_COURSE, token2)
    assert claimed is not None
    assert claimed.read_bytes() == b"second"


@pytest.mark.django_db
def test_discard_with_matching_token_deletes_file_and_clears_slot(session):
    token, path = staging.stage(session, staging.SLOT_COURSE, _upload())
    staging.discard(session, staging.SLOT_COURSE, token)
    assert not path.exists()
    assert staging.SLOT_COURSE not in staging._slots(session)


@pytest.mark.django_db
def test_discard_with_stale_token_is_a_noop(session):
    token1, path1 = staging.stage(session, staging.SLOT_COURSE, _upload(b"first"))
    token2, path2 = staging.stage(session, staging.SLOT_COURSE, _upload(b"second"))

    # a stale tab tries to cancel using the old (now-superseded) token
    staging.discard(session, staging.SLOT_COURSE, token1)

    # newer upload survives untouched
    assert path2.exists()
    assert staging.SLOT_COURSE in staging._slots(session)


@pytest.mark.django_db
def test_discard_with_missing_slot_is_a_noop(session):
    # should not raise
    staging.discard(session, staging.SLOT_COURSE, "whatever")


def test_sweep_removes_only_old_files(_staging_dir):
    old_file = _staging_dir / "old.zip"
    old_file.write_bytes(b"old")
    fresh_file = _staging_dir / "fresh.zip"
    fresh_file.write_bytes(b"fresh")

    old_time = time.time() - (7 * 3600)  # older than the 6h max age
    os.utime(old_file, (old_time, old_time))

    staging.sweep()

    assert not old_file.exists()
    assert fresh_file.exists()


def test_sweep_also_removes_old_claimed_files(_staging_dir):
    old_claimed = _staging_dir / "abc.claimed.zip"
    old_claimed.write_bytes(b"old")
    old_time = time.time() - (7 * 3600)
    os.utime(old_claimed, (old_time, old_time))

    staging.sweep()

    assert not old_claimed.exists()


def test_sweep_tolerates_missing_directory(settings, tmp_path):
    missing = tmp_path / "does-not-exist-yet"
    settings.TRANSFER_STAGING_DIR = missing
    # should not raise even though the dir was never created
    staging.sweep()


def test_sweep_tolerates_a_file_that_disappears_mid_sweep(_staging_dir, monkeypatch):
    old_file = _staging_dir / "old.zip"
    old_file.write_bytes(b"old")
    old_time = time.time() - (7 * 3600)
    os.utime(old_file, (old_time, old_time))

    real_unlink = os.unlink

    def flaky_unlink(path, *a, **kw):
        # simulate the file having vanished already (e.g. a race)
        raise OSError("gone")

    monkeypatch.setattr(os, "unlink", flaky_unlink)
    try:
        staging.sweep()  # must not raise
    finally:
        monkeypatch.setattr(os, "unlink", real_unlink)
    # file is still there since our stub prevented deletion
    assert old_file.exists()


@pytest.mark.django_db
def test_claimed_file_has_fresh_mtime(session):
    token, path = staging.stage(session, staging.SLOT_COURSE, _upload())
    old_time = time.time() - (5 * 3600)
    os.utime(path, (old_time, old_time))

    before = time.time()
    claimed = staging.claim(session, staging.SLOT_COURSE, token)

    assert claimed is not None
    assert claimed.stat().st_mtime >= before - 1


@pytest.mark.django_db
def test_cross_session_isolation_claim_returns_none(session, db):
    """Session B cannot claim a token staged by session A."""
    token, path = staging.stage(session, staging.SLOT_COURSE, _upload())
    assert path.exists()

    # Create a new, distinct session (session B)
    session_b = SessionStore()

    # B tries to claim A's token — should fail
    result = staging.claim(session_b, staging.SLOT_COURSE, token)
    assert result is None

    # A's file still exists; A can still claim it
    assert path.exists()
    claimed = staging.claim(session, staging.SLOT_COURSE, token)
    assert claimed is not None


@pytest.mark.django_db
def test_cross_session_isolation_discard_is_noop(session, db):
    """Session B cannot discard a token staged by session A."""
    token, path = staging.stage(session, staging.SLOT_COURSE, _upload())
    assert path.exists()

    # Create a new, distinct session (session B)
    session_b = SessionStore()

    # B tries to discard A's token — should be a no-op
    staging.discard(session_b, staging.SLOT_COURSE, token)

    # A's file still exists and slot is intact
    assert path.exists()
    assert staging.SLOT_COURSE in staging._slots(session)


@pytest.mark.django_db
def test_claim_with_path_traversal_token_returns_none(session):
    """Malicious tokens (path traversal, null bytes) do not match via equality."""
    token, path = staging.stage(session, staging.SLOT_COURSE, _upload())
    assert path.exists()

    # Try various malicious token shapes; none should match the real token
    malicious_tokens = [
        "../../etc/passwd",
        "/etc/passwd",
        "token\x00injected",
    ]
    for bad_token in malicious_tokens:
        result = staging.claim(session, staging.SLOT_COURSE, bad_token)
        assert result is None, f"claim with {bad_token!r} should return None"
        # Original file untouched
        assert path.exists()


@pytest.mark.django_db
def test_discard_with_path_traversal_token_is_noop(session):
    """Malicious tokens (path traversal, null bytes) do not match in discard."""
    token, path = staging.stage(session, staging.SLOT_COURSE, _upload())
    assert path.exists()

    # Try various malicious token shapes; none should match the real token
    malicious_tokens = [
        "../../etc/passwd",
        "/etc/passwd",
        "token\x00injected",
    ]
    for bad_token in malicious_tokens:
        staging.discard(session, staging.SLOT_COURSE, bad_token)
        # Original file untouched
        assert path.exists()
        assert staging.SLOT_COURSE in staging._slots(session)
