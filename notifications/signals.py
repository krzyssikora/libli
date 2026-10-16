"""Push housekeeping receivers (PWA C2 spec §3, §4). Connected by
NotificationsConfig.ready()."""

from django.contrib.auth.signals import user_logged_out
from django.core.signals import request_started
from django.dispatch import receiver

from notifications.push import reset_push_budget


@receiver(request_started)
def reset_push_budget_on_request(sender, **kwargs):
    reset_push_budget()


@receiver(user_logged_out)
def delete_push_subscription_on_logout(sender, request, user, **kwargs):
    """NOT gated on push_configured(): a row must not outlive a logout made while
    push was off. Django sends this before flushing the session."""
    if user is None or request is None or not hasattr(request, "session"):
        return
    endpoint = request.session.get("push_endpoint")
    if not endpoint:
        return
    from notifications.models import PushSubscription

    PushSubscription.objects.filter(endpoint=endpoint, user=user).delete()
