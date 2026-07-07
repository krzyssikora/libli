from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse

from courses.access import can_access_course
from courses.access import get_node_or_404
from courses.models import Course
from courses.views import full_lesson_render_context
from notes import services
from notes.forms import NoteForm
from notes.models import Note
from tags import services as tag_services


def _wants_fragment(request):
    return request.headers.get("X-Requested-With") == "fetch"


def _lesson_url(unit):
    return reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )


@login_required
def overview(request):
    note_counts = services.note_counts_by_course(request.user)  # {course_id: count}
    tags_by_course = tag_services.tags_by_course(request.user)  # {Course: [Tag]}
    by_pk = {c.pk: c for c in tags_by_course}
    note_only_ids = [cid for cid in note_counts if cid not in by_pk]
    by_pk.update(Course.objects.in_bulk(note_only_ids))  # one batched query, no N+1
    cards = [
        {
            "course": course,
            "note_count": note_counts.get(course.pk, 0),
            "tags": tags_by_course.get(course, []),
        }
        for course in by_pk.values()
    ]
    # case-insensitive, matches convention
    cards.sort(key=lambda c: c["course"].title.lower())
    return render(
        request, "notes/overview.html", {"cards": cards, "hub_tab": "by_course"}
    )


@login_required
def course_notes(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not can_access_course(request.user, course):
        raise PermissionDenied
    return render(
        request,
        "notes/course_notes.html",
        {"course": course, "units": services.course_notes(request.user, course)},
    )


@login_required
def note_edit(request, note_pk):
    note = get_object_or_404(Note, pk=note_pk, author=request.user)
    unit = note.unit
    has_access = can_access_course(request.user, unit.course)
    if request.method == "GET":
        return render(
            request,
            "notes/edit_page.html",
            {
                "note": note,
                "unit": unit,
                "course": unit.course,
                "body_value": note.body,
                "has_access": has_access,
            },
        )
    form = NoteForm(request.POST)
    if form.is_valid():
        services.update_note(request.user, note.pk, form.cleaned_data["body"])
        if _wants_fragment(request):
            note.refresh_from_db()
            return render(
                request,
                "notes/_note_card.html",
                {"note": note, "course": unit.course},
            )
        if has_access:
            return redirect(f"{_lesson_url(unit)}?notes=1#note-{note.pk}")
        return redirect(reverse("notes:result") + "?action=saved")
    body_error = form.errors.get("body", [""])[0]
    body_value = request.POST.get("body", "")
    if _wants_fragment(request):
        return render(
            request,
            "notes/_composer.html",
            {
                "unit": unit,
                "course": unit.course,
                "body_value": body_value,
                "body_error": body_error,
                "edit_pk": note.pk,
            },
            status=422,
        )
    # No-JS edit failure: the lesson page has no inline edit form (edit is a link
    # to this standalone page), so re-render the standalone edit page for BOTH the
    # has-access and access-lost cases — the rejected text + error surface here.
    return render(
        request,
        "notes/edit_page.html",
        {
            "note": note,
            "unit": unit,
            "course": unit.course,
            "body_value": body_value,
            "body_error": body_error,
            "has_access": has_access,
        },
        status=422,
    )


@login_required
def note_delete(request, note_pk):
    note = get_object_or_404(Note, pk=note_pk, author=request.user)
    unit = note.unit
    has_access = can_access_course(request.user, unit.course)
    if request.method == "GET":
        return render(
            request,
            "notes/confirm_delete.html",
            {
                "note": note,
                "unit": unit,
                "course": unit.course,
                "has_access": has_access,
            },
        )
    if request.method != "POST":
        return HttpResponseNotAllowed(["GET", "POST"])
    services.delete_note(request.user, note.pk)
    if has_access:
        return redirect(f"{_lesson_url(unit)}?notes=1")
    return redirect(reverse("notes:result") + "?action=deleted")


@login_required
def note_result(request):
    action = request.GET.get("action")
    return render(request, "notes/result_page.html", {"action": action})


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
