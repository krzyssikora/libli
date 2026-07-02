from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from notifications import services
from notifications.models import Notification

PAGE_SIZE = 25


@login_required
def notification_list(request):
    qs = Notification.objects.filter(recipient=request.user)
    page = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))
    for n in page.object_list:
        n.url = services.notification_url(n)
    return render(request, "notifications/list.html", {"page": page})


def _redirect_to_list(request):
    url = reverse("notifications:list")
    page = request.GET.get("page") or request.POST.get("page")
    if page:
        url = f"{url}?page={page}"
    return redirect(url)


@login_required
@require_POST
def mark_read(request, pk):
    n = get_object_or_404(Notification, pk=pk, recipient=request.user)
    if n.read_at is None:
        n.read_at = timezone.now()
        n.save(update_fields=["read_at"])
    return _redirect_to_list(request)


@login_required
@require_POST
def mark_all_read(request):
    Notification.objects.filter(recipient=request.user, read_at__isnull=True).update(
        read_at=timezone.now()
    )
    return _redirect_to_list(request)
