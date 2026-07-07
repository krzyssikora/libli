"""Staff-facing help pages rendered from trusted repo markdown (core.help)."""

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render
from django.utils import translation

from core.help import get_topic
from core.help import localized_doc_path
from core.help import render_markdown_doc
from core.help import topics_for


@login_required
def help_index(request):
    return render(request, "help/index.html", {"groups": topics_for(request.user)})


@login_required
def help_topic(request, slug):
    topic = get_topic(slug)
    # 404 (not 403) on unknown slug OR missing marker perm — never reveal existence.
    if topic is None or not request.user.has_perm(topic.perm):
        raise Http404("No such help topic")
    rel_path = localized_doc_path(topic.path, translation.get_language())
    html = render_markdown_doc(rel_path)
    # Sidebar = the perm-filtered sibling list for this topic's role group.
    groups = topics_for(request.user)
    siblings = next((g["topics"] for g in groups if g["role"] == topic.role), [])
    return render(
        request,
        "help/doc.html",
        {"content": html, "topic": topic, "siblings": siblings},
    )
