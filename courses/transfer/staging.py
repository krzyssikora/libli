"""Staging between import preview and confirm (§4.3). Session-token slots; the
staging dir is NOT web-served and shared across hosts in multi-host deployments."""

import os
import secrets
import time
from pathlib import Path

from django.conf import settings

SESSION_KEY = "transfer_staging"
SLOT_COURSE = "course"
SLOT_SUBTREE = "subtree"


def _dir():
    p = Path(settings.TRANSFER_STAGING_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p


def sweep():
    cutoff = time.time() - settings.TRANSFER_STAGING_MAX_AGE_HOURS * 3600
    try:
        entries = list(_dir().iterdir())
    except OSError:
        return
    for f in entries:
        try:
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            continue  # best-effort per file; never propagate (§4.3)


def _slots(session):
    return session.get(SESSION_KEY, {})


def stage(session, slot, uploaded_file, course_pk=None):
    sweep()
    slots = _slots(session)
    old = slots.get(slot)
    if old:  # supersede: previous upload's file + token die now
        try:
            os.unlink(old["path"])
        except OSError:
            pass
    token = secrets.token_urlsafe(32)
    path = _dir() / f"{token}.zip"
    with open(path, "wb") as out:
        for chunk in uploaded_file.chunks():
            out.write(chunk)
    slots[slot] = {"token": token, "path": str(path), "course_pk": course_pk}
    session[SESSION_KEY] = slots
    session.modified = True
    return token, path


def claim(session, slot, token, course_pk=None):
    slots = _slots(session)
    entry = slots.get(slot)
    if not entry or not token or entry["token"] != token:
        return None
    if entry.get("course_pk") != course_pk:
        return None
    src = Path(entry["path"])
    dst = src.with_suffix(".claimed.zip")
    slots.pop(slot, None)
    session[SESSION_KEY] = slots
    session.modified = True
    try:
        os.rename(src, dst)  # atomic claim: exactly one confirm wins
        os.utime(dst, None)  # fresh sweep window for the in-flight import
    except OSError:
        return None
    return dst


def discard(session, slot, token):
    slots = _slots(session)
    entry = slots.get(slot)
    if not entry or not token or entry["token"] != token:
        return  # stale tab's Cancel must not delete a newer upload
    slots.pop(slot, None)
    session[SESSION_KEY] = slots
    session.modified = True
    try:
        os.unlink(entry["path"])
    except OSError:
        pass
