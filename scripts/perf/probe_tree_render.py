"""Time the builder tree render for one course. Usage:

    SLUG=mat-pp OPEN=all uv run python manage.py shell -c \
      "exec(open('scripts/perf/probe_tree_render.py').read())"

Prints warm render time, byte size, element count and query count. `OPEN` may
be set to "all" (default), "" or a comma-separated pk list.
"""

import os
import re
import time
from collections import Counter

from django.conf import settings
from django.db import connection
from django.db import reset_queries
from django.template.loader import render_to_string

from courses.models import ContentNode
from courses.models import Course
from courses.models import QuizSubmission
from courses.views_manage import _children_map

# The REAL helper, not a local copy like _containers/_descendants below. Those
# two are copies so the probe can run on PRE-Task-1 code to capture a baseline;
# _fold_flag_counts ships in the same commit as this line, so there is no
# earlier code for it to have to run against -- and a copy could drift from the
# original, which is the one thing TREE4 exists to prevent.
from courses.views_manage import _fold_flag_counts

SLUG = os.environ.get("SLUG", "mat-pp")
OPEN = os.environ.get("OPEN", "all")
Q = os.environ.get("Q", "")


def _containers(cmap):
    """Local copy, so this probe runs BEFORE courses.builder_open exists.

    Task 0 has to capture the baseline on today's code; importing helpers that
    Tasks 1 and 4 create would make the BEFORE run impossible.
    """
    return {
        n.pk for kids in cmap.values() for n in kids if n.kind != ContentNode.Kind.UNIT
    }


def _descendants(cmap, ids):
    """Local copy of _open_descendants, same reason."""
    out = {}

    def walk(pk):
        if pk in out:
            return out[pk]
        acc = set()
        for child in cmap.get(pk, []):
            if child.kind == ContentNode.Kind.UNIT:
                continue
            if child.pk in ids:
                acc.add(child.pk)
            acc |= walk(child.pk)
        out[pk] = acc
        return acc

    for pk in ids:
        walk(pk)
    return out


def _run():
    course = Course.objects.get(slug=SLUG)  # outside the measured window
    settings.DEBUG = True
    reset_queries()
    cmap = _children_map(course)
    containers = _containers(cmap)
    ids = (
        containers
        if OPEN == "all"
        else {int(t) for t in OPEN.split(",") if t.strip().isdigit()}
    )
    # open_ids must be supplied: after Task 3 the template branches on it, and
    # Django's smartif swallows the resulting TypeError (verified: `{% if 5 in
    # nothing %}` renders the else-branch), so omitting it renders SILENTLY
    # COLLAPSED rather than failing loudly -- which would make every "after"
    # number look like a huge win for the wrong reason.
    render_map = cmap
    q_on = False
    if Q:
        # Imported HERE, not at the top. `_containers` (:28-33) and `_descendants`
        # (:39) are deliberate local copies so the probe RUNS ON TODAY'S CODE --
        # their docstrings say so in as many words ("so this probe runs BEFORE
        # courses.builder_open exists"). A module-level import executes
        # unconditionally and would destroy exactly that property, making the
        # BEFORE half of every comparison impossible on a clean checkout. Inside
        # the `if Q:` block the import only runs when the caller asked for a
        # filtered measurement, which by definition is an AFTER run.
        from courses.builder_filter import filtered_map

        restricted, chains, shown, total, q_on = filtered_map(cmap, Q)
        # Gate on the RETURNED q_active, not on bool(Q). A below-floor Q (say
        # `Q=a`) yields chains=set() and q_active=False -- so `ids = chains` would
        # hand the render an EMPTY open set over the full map and time a silently
        # COLLAPSED tree. That is exactly the failure the probe's own comment at
        # :72-76 exists to prevent ("would make every 'after' number look like a
        # huge win for the wrong reason"), and it is invisible in the output.
        if q_on:
            render_map = restricted
            ids = chains
            print(f"filtered: shown={shown} total={total}")
        else:
            print(f"Q={Q!r} is below the floor; measuring UNFILTERED")

    ctx = {
        "nodes": render_map.get(None, []),
        "children_map": render_map,  # RESTRICTED only when q_on
        "open_ids": ids,
        "open_joined": ",".join(str(p) for p in sorted(ids)),
        "open_descendants": _descendants(cmap, ids),  # the FULL map, always
        "q": Q,  # the RAW value, active or not -- the template
        # emits it either way, as the page does
        "filtered": q_on,  # the FLAG, not bool(Q) -- see above
        "scope_id": "top",
        "scope_updated": course.updated.isoformat(),
        "parent_kind": None,
        "course": course,
        "builder_url": f"/manage/courses/{course.slug}/build/",
        # Task 13 made these HARD requirements of _tree_node.html, and only
        # _tree_context supplied them -- so without them the probe dies on the
        # FIRST container row. `string_if_invalid` is unset (defaults to ""), so
        # `flag_counts|get_item:node.pk` calls get_item("", pk) ->
        # AttributeError: 'str' object has no attribute 'get'. On mat-pp the top
        # level is 21 Parts, so it fires on row one. A published quiz row is a
        # parallel TypeError on `node.pk in quizzes_with_submissions`, which
        # Django's IfNode does NOT swallow (it catches only
        # VariableDoesNotExist). The probe is the tool spec 4's own cost analysis
        # points a future profiler at; it has to work.
        #
        # Fold `cmap`, NEVER `render_map`. Under an active filter render_map is
        # the RESTRICTED map, and folding that makes a container claim "3 units"
        # when its subtree holds 40 -- TREE4's mutant exactly. The probe already
        # keeps that distinction for open_descendants above.
        "flag_counts": _fold_flag_counts(cmap),
        # One course-wide query, matching _tree_context: per-row this would be
        # an N+1 across every quiz in a 2,866-node tree, which would show up in
        # the probe's own query count and be blamed on the render.
        "quizzes_with_submissions": set(
            QuizSubmission.objects.filter(unit__course=course).values_list(
                "unit_id", flat=True
            )
        ),
        # Not required to render, but the flag controls emit it into every
        # container row's href -- omitting it understates the byte size this
        # branch actually added, which is half of what the probe reports.
        "flag_url": f"/manage/courses/{course.slug}/build/node/flag/",
    }
    render_to_string("courses/manage/_scope.html", ctx)  # warm the template
    t0 = time.perf_counter()
    html = render_to_string("courses/manage/_scope.html", ctx)
    dt = (time.perf_counter() - t0) * 1000
    tags = Counter(t.lower() for t in re.findall(r"<([a-zA-Z][a-zA-Z0-9-]*)", html))
    print(f"slug={SLUG} open={OPEN} q={Q!r} q_active={q_on}")
    print(f"  nodes in course : {sum(len(v) for v in cmap.values())}")
    print(f"  open scopes     : {len(ids)}")
    print(f"  warm render     : {dt:.1f} ms")
    print(f"  bytes           : {len(html)} ({len(html) / 1048576:.2f} MB)")
    print(f"  open tags       : {sum(tags.values())}")
    print(f"  rows            : {tags.get('li', 0)}")
    print(f"  queries         : {len(connection.queries)}")


_run()
