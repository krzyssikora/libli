from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def home(request):
    """Placeholder post-login page; the real adaptive dashboard is Phase 0d-2."""
    return render(request, "core/home.html")
