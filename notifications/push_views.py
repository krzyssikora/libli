"""PWA C2 push endpoints and the push tap target (spec §3, §4)."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone

from notifications.models import Notification
from notifications.services import notification_url


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
