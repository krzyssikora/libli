"""Platform-admin settings surface: Branding / Access / Uploads tabs."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import permission_required
from django.shortcuts import redirect
from django.shortcuts import render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from institution.forms import AccessForm
from institution.forms import BrandingForm
from institution.forms import UploadsForm
from institution.models import Institution

TABS = ("branding", "access", "uploads")


def _active_tab(request):
    tab = request.GET.get("tab", "branding")
    return tab if tab in TABS else "branding"


def _settings_context(inst, active_tab, *, branding=None, access=None, uploads=None):
    """Assemble the three-form context. Any form passed in (an errored bound form)
    is used as-is; the rest are unbound, seeded from `inst`. Single source of truth
    for the GET index and every action-view error re-render."""
    return {
        "active_tab": active_tab,
        "branding": branding or BrandingForm(instance=inst),
        "access": access or AccessForm(instance=inst),
        "uploads": uploads or UploadsForm(instance=inst),
    }


@login_required
@permission_required("institution.change_institution", raise_exception=True)
def settings(request):
    inst = Institution.load()
    ctx = _settings_context(inst, _active_tab(request))
    return render(request, "institution/manage/settings.html", ctx)


def _save_tab(request, form_cls, ctx_key, active_tab, success_msg):
    inst = Institution.load()
    form = form_cls(request.POST, request.FILES, instance=inst)
    if form.is_valid():
        form.save()  # fires post_save -> invalidate_site_config
        messages.success(request, success_msg)
        return redirect(
            f"{request.path_info}".replace(active_tab + "/", "").rstrip("/")
        )
    ctx = _settings_context(inst, active_tab, **{ctx_key: form})
    return render(request, "institution/manage/settings.html", ctx)


@require_POST
@login_required
@permission_required("institution.change_institution", raise_exception=True)
def settings_branding(request):
    return _save_tab(
        request, BrandingForm, "branding", "branding", _("Branding saved.")
    )


@require_POST
@login_required
@permission_required("institution.change_institution", raise_exception=True)
def settings_access(request):
    return _save_tab(
        request, AccessForm, "access", "access", _("Access settings saved.")
    )


@require_POST
@login_required
@permission_required("institution.change_institution", raise_exception=True)
def settings_uploads(request):
    return _save_tab(
        request, UploadsForm, "uploads", "uploads", _("Upload settings saved.")
    )
