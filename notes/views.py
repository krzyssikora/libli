from django.http import HttpResponseNotAllowed


def note_add(request, slug, node_pk):  # replaced in Task 6
    return HttpResponseNotAllowed(["POST"])


def note_edit(request, note_pk):  # replaced in Task 7
    return HttpResponseNotAllowed(["GET", "POST"])


def note_delete(request, note_pk):  # replaced in Task 7
    return HttpResponseNotAllowed(["GET", "POST"])
