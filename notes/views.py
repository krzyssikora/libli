from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.http import HttpResponseNotAllowed
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse

from courses.access import can_access_course
from courses.access import get_node_or_404
from courses.views import full_lesson_render_context
from notes import services
from notes.forms import NoteForm


def _wants_fragment(request):
    return request.headers.get("X-Requested-With") == "fetch"


def note_edit(request, note_pk):  # replaced in Task 7
    return HttpResponseNotAllowed(["GET", "POST"])


def note_delete(request, note_pk):  # replaced in Task 7
    return HttpResponseNotAllowed(["GET", "POST"])


@login_required
def note_add(request, slug, node_pk):
    if request.method != "POST":
        raise Http404  # hide the endpoint before any gate runs
    unit = get_node_or_404(node_pk, slug, require_unit=True, require_lesson=True)
    if not can_access_course(request.user, unit.course):
        raise PermissionDenied
    element_pk = request.POST.get("element") or None
    form = NoteForm(request.POST)
    if form.is_valid():
        note = services.create_note(
            request.user, unit, element_pk, form.cleaned_data["body"]
        )
        if _wants_fragment(request):
            return render(
                request,
                "notes/_note_card.html",
                {"note": note, "course": unit.course},
                status=201,
            )
        url = reverse("courses:lesson_unit", kwargs={"slug": slug, "node_pk": node_pk})
        return redirect(f"{url}?notes=1#note-{note.pk}")
    # invalid
    body_error = form.errors.get("body", [""])[0]
    if _wants_fragment(request):
        return render(
            request,
            "notes/_composer.html",
            {
                "element_pk": element_pk,
                "unit": unit,
                "course": unit.course,
                "body_value": request.POST.get("body", ""),
                "body_error": body_error,
            },
            status=422,
        )
    ctx = full_lesson_render_context(unit, request.user, notes_show=True)
    ctx["note_error"] = {
        "element_pk": element_pk,
        "body": request.POST.get("body", ""),
        "message": body_error,
    }
    return render(request, "courses/lesson_unit.html", ctx, status=422)
