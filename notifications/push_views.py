"""PWA C2 push endpoints and the push tap target (spec §3, §4)."""

import json

from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.db import transaction
from django.http import Http404
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from notifications.models import Notification
from notifications.models import PushSubscription
from notifications.push import MAX_ENDPOINT_LENGTH
from notifications.push import MAX_SUBSCRIPTIONS_PER_USER
from notifications.push import clean_subscription
from notifications.push import push_configured
from notifications.push import remembered_from_data
from notifications.services import notification_url

FORBIDDEN = {"ok": False}


@login_required
def open_notification(request, pk):
    """GET with a side effect, deliberately: the worker cannot send a CSRF token, and
    the only effect is marking the viewer's OWN notification read. Not gated on
    push_configured(): a notification outlives blanked keys in the tray. A missing
    and a foreign pk get the same redirect, so there is no oracle."""
    n = Notification.objects.filter(pk=pk, recipient=request.user).first()
    if n is None:
        return redirect("notifications:list")
    if n.read_at is None:
        n.read_at = timezone.now()
        n.save(update_fields=["read_at"])
    return redirect(notification_url(n) or reverse("notifications:list"))


def _gate(request, *, subscribe=False):
    """Spec §4 order (after CSRF): 404, anonymous 403, then non-remembered 403."""
    if not push_configured():
        raise Http404
    if not request.user.is_authenticated:
        return JsonResponse(FORBIDDEN, status=403)
    if subscribe and not remembered_from_data(request.session):
        return JsonResponse(FORBIDDEN, status=403)
    return None


def _json(request):
    try:
        return json.loads(request.body or b"null")
    except (ValueError, UnicodeDecodeError, RecursionError):
        return None


def _endpoint_only(body):
    endpoint = body.get("endpoint") if isinstance(body, dict) else None
    if not isinstance(endpoint, str) or not endpoint:
        return None
    if len(endpoint) > MAX_ENDPOINT_LENGTH:
        return None
    return endpoint


def _session_key(request):
    if not request.session.session_key:
        request.session.save()
    return request.session.session_key


@require_POST
def push_subscribe(request):
    refused = _gate(request, subscribe=True)
    if refused:
        return refused
    cleaned = clean_subscription(_json(request))
    if cleaned is None:
        return JsonResponse(FORBIDDEN, status=400)
    endpoint, p256dh, auth = cleaned
    values = {
        "user": request.user,
        "p256dh": p256dh,
        "auth": auth,
        "user_agent": request.META.get("HTTP_USER_AGENT", "")[:200],
        "subscribed_at": timezone.now(),
        "session_key": _session_key(request),
    }
    try:
        with transaction.atomic():
            PushSubscription.objects.update_or_create(
                endpoint=endpoint, defaults=values
            )
    except IntegrityError:  # a concurrent insert of the same endpoint won the race
        PushSubscription.objects.filter(endpoint=endpoint).update(**values)
    keep = list(
        PushSubscription.objects.filter(user=request.user)
        .exclude(endpoint=endpoint)
        .order_by("-subscribed_at", "-pk")
        .values_list("pk", flat=True)[: MAX_SUBSCRIPTIONS_PER_USER - 1]
    )
    PushSubscription.objects.filter(user=request.user).exclude(
        endpoint=endpoint
    ).exclude(pk__in=keep).delete()
    request.session["push_endpoint"] = endpoint
    return JsonResponse({"ok": True})


@require_POST
def push_unsubscribe(request):
    refused = _gate(request)
    if refused:
        return refused
    endpoint = _endpoint_only(_json(request))
    if endpoint is None:
        return JsonResponse(FORBIDDEN, status=400)
    PushSubscription.objects.filter(endpoint=endpoint, user=request.user).delete()
    if request.session.get("push_endpoint") == endpoint:
        del request.session["push_endpoint"]
    return JsonResponse({"ok": True})


@require_POST
def push_claim(request):
    refused = _gate(request)
    if refused:
        return refused
    endpoint = _endpoint_only(_json(request))
    if endpoint is None:
        return JsonResponse(FORBIDDEN, status=400)
    row = PushSubscription.objects.filter(endpoint=endpoint).first()
    if row and row.user_id == request.user.pk and remembered_from_data(request.session):
        row.session_key = _session_key(request)
        row.save(update_fields=["session_key"])
        request.session["push_endpoint"] = endpoint
        return JsonResponse({"mine": True})
    # Not this user's, or a not-remembered login (D8): the browser is about to
    # unsubscribe it, so the row can never deliver again -- for anyone.
    PushSubscription.objects.filter(endpoint=endpoint).delete()
    if request.session.get("push_endpoint") == endpoint:
        del request.session["push_endpoint"]
    return JsonResponse({"mine": False})
