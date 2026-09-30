"""Helpers for the PWA e2e module (tests/test_e2e_pwa.py).

Findings (2026-09-30, Playwright 1.60.0, bundled Chromium, via pytest-playwright;
spike file tests/test_e2e_pwa_spike.py, run with and without the env var, then
deleted):

- Making the WORKER's own fetch reject: ``context.route(<origin>/**, abort)``
  works. The handler IS called for the worker's inner fetch of a navigation the
  worker handles (``route.request.service_worker`` is set, resource type
  ``fetch``); the worker's ``fetch(request).catch(offlinePage)`` then shows the
  cached offline page for /getting-started/, a page never visited before. The
  filter is the live-server ORIGIN only (``f"{origin}/**"``), never a path and
  never ``is_navigation_request()``, so any page is covered.
- ``context.set_offline(True)`` ALONE also makes the worker's fetch reject, and
  ``set_offline(False)`` fires ``online`` (the offline page's listener reloads
  it). CDP (a browser session, non-flat ``Target.attachToTarget`` to the
  service_worker target, ``Network.emulateNetworkConditions`` offline) also
  works but is not needed and is not used. Stopping the live server
  (``httpd.shutdown()`` + ``server_close()``) does NOT: the next navigation still
  rendered the real page, and it would kill the session-scoped server anyway.
- ``PW_EXPERIMENTAL_SERVICE_WORKER_NETWORK_EVENTS`` is NOT needed: every result
  above was identical with it unset and set to 1. ``PWA_ENV`` is empty, and the
  PWA module runs in the ordinary ``pytest -m e2e -n 2`` invocation (no CI split).
- ``fires_online``: a route outage leaves ``navigator.onLine`` alone, so its exit
  (``unroute``) fires no ``online`` event -- PROVEN with an init script counting
  ``online`` events: the count stayed 0 across the unroute (and a successful
  fetch after it), while the same counter reads 1 after a ``set_offline``
  True/False toggle (positive control). So ``fires_online=False`` is the route
  alone; ``fires_online=True`` adds a ``set_offline(True)`` on entry and
  ``set_offline(False)`` on exit, which fires the real ``online`` event (the
  offline page's own listener reloaded /getting-started/ with no click).
- The export download (``.../export/?confirm=1`` under ``page.expect_download()``,
  ``page.goto`` raising "Download is starting") IS observable with
  ``context.on("response")``: on the correct worker there is exactly one
  response, ``from_service_worker`` False and ``request.service_worker`` None.
  With the rule-0 mutant ``url.pathname + url.search`` (verified by hand in the
  spike) there are TWO: the page's response with ``from_service_worker`` True,
  and the worker's own fetch (``request.service_worker`` set). The observer
  counts either as ``served_by_worker``. ``context.on("request")`` sees the same
  and needs no env var either.
"""

from contextlib import contextmanager
from dataclasses import dataclass

PWA_ENV: dict[str, str] = {}


def enable_pwa(settings) -> None:
    settings.PWA_ENABLED = True
    settings.PWA_KILL_SWITCH = False
    settings.PWA_CACHE_UNHASHED_STATIC = True


def wait_controlled(page) -> None:
    """Wait until the page is controlled by the worker. The first load that
    registers the worker is not controlled until the worker claims it; if it
    is still uncontrolled once the worker is ready, reload once."""
    page.evaluate("async () => { await navigator.serviceWorker.ready; }")
    if not page.evaluate("() => !!navigator.serviceWorker.controller"):
        page.reload()
    page.wait_for_function("() => !!navigator.serviceWorker.controller")


def _origin(page) -> str:
    return page.evaluate("() => location.origin")


@contextmanager
def outage(context, page, *, fires_online: bool):
    """Inside: every same-origin request -- including the worker's own fetch --
    is aborted, whatever its path. On exit the network is back; the ``online``
    event fires iff ``fires_online`` (see the module Findings)."""
    pattern = f"{_origin(page)}/**"
    context.route(pattern, lambda route: route.abort())
    if fires_online:
        context.set_offline(True)
    try:
        yield
    finally:
        context.unroute(pattern)
        if fires_online:
            context.set_offline(False)


@dataclass(frozen=True)
class ExportObservation:
    url: str
    status: int
    served_by_worker: bool


def export_observer(context) -> list:
    """Record every response whose path ends with /export/ (query ignored). An
    item is ``served_by_worker`` if the worker answered it or fetched it."""
    seen: list[ExportObservation] = []

    def on_response(response):
        path = response.url.split("?", 1)[0].split("#", 1)[0]
        if not path.endswith("/export/"):
            return
        seen.append(
            ExportObservation(
                url=response.url,
                status=response.status,
                served_by_worker=bool(
                    response.from_service_worker
                    or response.request.service_worker is not None
                ),
            )
        )

    context.on("response", on_response)
    return seen
