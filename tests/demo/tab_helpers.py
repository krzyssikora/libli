"""Shared helpers for the PR 3 demo-tab tests."""

import time
from importlib import import_module

from bs4 import BeautifulSoup
from django.conf import settings as django_settings
from django.urls import reverse

from demo.constants import DEFAULT_DAYS
from demo.constants import MIN_PUPILS


def demo_tab_url(show_all=False):
    url = reverse("institution:settings") + "?tab=demo"
    return f"{url}&all=1" if show_all else url


def soup(response):
    return BeautifulSoup(response.content, "html.parser")


def row_ids(response):
    """Kit pks of the list rows, in page order. Located by the data-demo-kit hook,
    never by an id substring — course, group and user pks share the page."""
    return [
        int(tr["data-demo-kit"]) for tr in soup(response).select("tr[data-demo-kit]")
    ]


def session_store(client):
    """A SEPARATE store on the client's session row — the way another tab's
    request would see it."""
    engine = import_module(django_settings.SESSION_ENGINE)
    return engine.SessionStore(session_key=client.session.session_key)


def stored_session(client):
    """What the database holds right now for this client's session."""
    return dict(session_store(client).load())


def write_stored_session(client, **items):
    store = session_store(client)
    for key, value in items.items():
        store[key] = value
    store.save()


def pending_entry(kit, *, age_seconds=0, warnings=None):
    """A spec §4.3 entry for a REAL kit (an entry whose kit is missing or closed
    becomes a "closed before" notice, never a card). Distinctive fake passwords, so
    a substring check cannot collide with anything else on the page."""
    return {
        "kit_id": kit.pk,
        "label": kit.label,
        "teacher_username": f"teacher-of-{kit.pk}",
        "teacher_password": f"TeacherPw{kit.pk}x",
        "student_username": f"student-of-{kit.pk}",
        "student_password": f"StudentPw{kit.pk}x",
        "expires_at": kit.expires_at.isoformat(),
        "stored_at": time.time() - age_seconds,
        "warnings": warnings or {},
    }


def add_pending(client, *entries):
    store = session_store(client)
    store["demo_kit_results"] = [*store.get("demo_kit_results", []), *entries]
    store.save()


def create_url():
    return reverse("institution:settings_demo_create")


def create_data(course, **overrides):
    """Tab-driven creates post MIN_PUPILS: the form's initial is DEFAULT_PUPILS
    (20), and each extra pupil costs ~137 queries."""
    data = {
        "course": course.pk,
        "label": "SP 12",
        "days": DEFAULT_DAYS,
        "pupils": MIN_PUPILS,
    }
    data.update(overrides)
    return data


def seed_the_view(monkeypatch, *, seed=4242, before_return=None):
    """The view passes no seed, so the service would draw one from `secrets`.
    Wrap the name the view resolves; `before_return(result)` runs after the real
    provision, standing in for whatever else happens while a kit is being built."""
    from institution import views_manage

    real = views_manage.provision_kit

    def seeded(*args, **kwargs):
        result = real(*args, seed=seed, **kwargs)
        if before_return is not None:
            before_return(result)
        return result

    monkeypatch.setattr(views_manage, "provision_kit", seeded)
