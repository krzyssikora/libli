import pytest
from django.core.exceptions import ValidationError

from courses import validators as v


class _FakeUpload:
    """Stand-in for a new (uncommitted) upload: has .name and .size, no _committed."""

    def __init__(self, name, size):
        self.name = name
        self.size = size


class _FakeCommitted(_FakeUpload):
    _committed = True


def _cfg(monkeypatch, **over):
    cfg = {
        "allowed_image_extensions": list(v.SAFE_IMAGE_EXTENSIONS),
        "allowed_video_extensions": list(v.SAFE_VIDEO_EXTENSIONS),
        "max_image_mib": v.MAX_IMAGE_MIB_CEILING,
        "max_video_mib": v.MAX_VIDEO_MIB_CEILING,
    }
    cfg.update(over)
    monkeypatch.setattr(v, "_site_config", lambda: cfg)


def test_defaults_are_fresh_lists():
    a, b = v.default_image_extensions(), v.default_image_extensions()
    assert a == list(v.SAFE_IMAGE_EXTENSIONS) and a is not b  # not a shared mutable


def test_effective_extensions_default_is_full_safe_set(monkeypatch):
    _cfg(monkeypatch)
    assert v.effective_image_extensions() == list(v.SAFE_IMAGE_EXTENSIONS)


def test_effective_extensions_narrows(monkeypatch):
    _cfg(monkeypatch, allowed_image_extensions=["png", "jpg"])
    assert v.effective_image_extensions() == ["png", "jpg"]


def test_effective_extensions_intersects_away_forged_values(monkeypatch):
    _cfg(monkeypatch, allowed_image_extensions=["png", "svg", "exe"])
    assert v.effective_image_extensions() == ["png"]  # svg/exe not in safe set


def test_effective_extensions_empty_stored_is_fail_closed(monkeypatch):
    _cfg(monkeypatch, allowed_image_extensions=[])
    assert v.effective_image_extensions() == []


def test_effective_extensions_missing_key_falls_back_to_safe(monkeypatch):
    monkeypatch.setattr(v, "_site_config", lambda: {})  # institution-absent path
    assert v.effective_image_extensions() == list(v.SAFE_IMAGE_EXTENSIONS)


def test_effective_max_bytes_respects_ceiling(monkeypatch):
    _cfg(monkeypatch, max_image_mib=999)  # tampered above ceiling
    assert v.effective_max_image_bytes() == v.MAX_IMAGE_MIB_CEILING * 1024 * 1024


def test_effective_max_bytes_honours_narrower(monkeypatch):
    _cfg(monkeypatch, max_image_mib=1)
    assert v.effective_max_image_bytes() == 1 * 1024 * 1024


def test_validate_image_file_rejects_disabled_extension(monkeypatch):
    _cfg(monkeypatch, allowed_image_extensions=["png"])
    with pytest.raises(ValidationError):
        v.validate_image_file(_FakeUpload("clip.gif", 10))


def test_validate_image_file_rejects_oversize(monkeypatch):
    _cfg(monkeypatch, max_image_mib=1)
    with pytest.raises(ValidationError):
        v.validate_image_file(_FakeUpload("ok.png", 2 * 1024 * 1024))


def test_validate_image_file_accepts_within_limits(monkeypatch):
    _cfg(monkeypatch)
    v.validate_image_file(_FakeUpload("ok.png", 10))  # no raise


def test_validate_image_file_skips_committed(monkeypatch):
    # Narrow so gif is disabled AND cap is tiny; a committed file must STILL pass
    # (no retroactive rejection, no storage .size read).
    _cfg(monkeypatch, allowed_image_extensions=["png"], max_image_mib=1)
    v.validate_image_file(_FakeCommitted("old.gif", 9_999_999))  # no raise
