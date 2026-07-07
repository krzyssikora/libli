"""In-app help system: trusted-markdown renderer + role-aware topic registry.

Content is repo-authored (fixed paths only), never user input, so the renderer
applies no sanitization. A missing file is a packaging/deploy bug — fail loud."""

from dataclasses import dataclass
from pathlib import Path

import markdown
from django.utils.translation import gettext_lazy as _

from institution.roles import COURSE_ADMIN
from institution.roles import PLATFORM_ADMIN
from institution.roles import TEACHER

# core/help.py -> parent is the app dir; its parent is the repo root, which
# holds docs/.
DOCS_ROOT = Path(__file__).resolve().parent.parent / "docs"


def render_markdown_doc(rel_path):
    text = (DOCS_ROOT / rel_path).read_text(encoding="utf-8")
    return markdown.markdown(text, extensions=["fenced_code", "tables"])


def localized_doc_path(base, lang):
    """Return the localized markdown path for `base` under language `lang`.

    Coalesces a falsy lang to English (get_language() can return None), normalizes
    a regional code (pl-PL -> pl), and — if the code is not English — returns the
    `<name>.<code>.md` sibling iff it exists on disk, else the English base.
    Uses removesuffix/slicing (NOT Path.stem, which would drop the help/<role>/
    directory prefix and make the existence check always miss)."""
    code = (lang or "en").split("-")[0]
    if code == "en":
        return base
    candidate = base.removesuffix(".md") + f".{code}.md"
    if (DOCS_ROOT / candidate).exists():
        return candidate
    return base


@dataclass(frozen=True)
class Topic:
    slug: str  # globally unique URL segment (e.g. "builder")
    role: str  # storage constant from institution.roles (grouping key)
    perm: str  # representative marker permission gating visibility
    title: object  # gettext_lazy display title
    path: str  # base markdown rel path, e.g. "help/course-admin/builder.md"


# Fixed display order of role groups on the index/sidebar (spec §Components).
ROLE_GROUP_ORDER = [PLATFORM_ADMIN, COURSE_ADMIN, TEACHER]

# The docs/ folder each role's topics live under (folder<->role invariant).
ROLE_FOLDER = {
    PLATFORM_ADMIN: "help/platform-admin/",
    COURSE_ADMIN: "help/course-admin/",
    TEACHER: "help/teacher/",
}

# Registry. A Topic is listed ONLY once its English .md file exists (unwritten
# topics are simply absent — that is the scaffold-remainder contract). Marker
# perms per the spec's gating table.
TOPICS = [
    Topic(
        "users-roles",
        PLATFORM_ADMIN,
        "accounts.view_user",
        _("Users & roles"),
        "help/platform-admin/users-roles.md",
    ),
    Topic(
        "builder",
        COURSE_ADMIN,
        "grouping.change_group",
        _("Building a course"),
        "help/course-admin/builder.md",
    ),
    Topic(
        "analytics",
        TEACHER,
        "grouping.view_collection",
        _("The analytics matrix"),
        "help/teacher/analytics.md",
    ),
]

# Fail loud at import on a duplicate slug. Explicit raise (NOT assert, which
# `python -O` strips) so an optimized deploy still refuses to boot on drift.
_slugs = [t.slug for t in TOPICS]
if len(set(_slugs)) != len(_slugs):
    raise ValueError(f"Duplicate help topic slug(s) in TOPICS: {_slugs}")

_BY_SLUG = {t.slug: t for t in TOPICS}


def get_topic(slug):
    return _BY_SLUG.get(slug)
