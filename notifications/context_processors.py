"""Push client context (PWA C2 spec §6): push_available plus the meta values."""


def push_client(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    from django.conf import settings

    from notifications.models import PushSubscription
    from notifications.push import push_configured
    from notifications.push import remembered_from_data

    if not push_configured():
        return {}
    session = request.session
    endpoint = session.get("push_endpoint", "")
    # Rendered only when THIS session's current key owns the row: after a key
    # rotation (login, password change) it is empty, so push.js claims and re-keys.
    if (
        endpoint
        and not PushSubscription.objects.filter(
            endpoint=endpoint, user=user, session_key=session.session_key
        ).exists()
    ):
        endpoint = ""
    return {
        "push_available": True,
        "push_vapid_key": settings.PUSH_VAPID_PUBLIC_KEY,
        "push_session_endpoint": endpoint,
        "push_remembered": remembered_from_data(session),
    }
