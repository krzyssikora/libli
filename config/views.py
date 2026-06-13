from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def home(request):
    """Placeholder post-login page. Deliberate 0b stop-gap: it lives in config/
    only because 0b has no UI app yet. Plan 0d relocates it into the core/web app
    (spec §Components) as the real adaptive dashboard shell."""
    return render(request, "home.html")
