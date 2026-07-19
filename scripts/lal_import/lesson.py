"""Walk a lesson's DOM top-to-bottom, emitting ordered libli element dicts.

The stub HTML head (bootstrap link, script tags, MathJax/H5P resizer) is ignored;
only body-level content elements map. Anything unrecognized is flagged, never
silently dropped.
"""

import re

from bs4 import BeautifulSoup
from bs4 import Comment
from bs4 import NavigableString
from bs4 import Tag

from scripts.lal_import.mathsafe import escape_math_delimited

# Tags whose inner HTML is valid TextElement body content (survive nh3). h2 is
# included: the FIRST h2 is consumed as the unit title, later ones are body.
_TEXT_TAGS = {"h2", "h3", "h4", "p", "ul", "ol", "blockquote", "pre"}
_INLINE_TAGS = {"strong", "em", "b", "i", "u", "code", "a"}
_IGNORE_TAGS = {"script", "link", "style"}
_OK_SCHEMES = {"http", "https", "mailto"}
# A block whose entire content is one \[...\] display span -> MathElement.
_DISPLAY_MATH = re.compile(r"^\\\[(.*)\\\]$", re.DOTALL)


def _flag(reason, node):
    return {
        "kind": "unmapped_pattern",
        "reason": reason,
        "raw_excerpt": str(node)[:300],
    }


def _sole_block_math_latex(node):
    """If node's whole content is a single \\[...\\] display span (no child tags),
    return the inner LaTeX. get_text() decodes entities, so `<` comes back literal —
    exactly what the autoescaped [data-katex] MathElement template needs."""
    if node.name not in {"p", "div"} or node.find(True) is not None:
        return None
    m = _DISPLAY_MATH.match(node.get_text().strip())
    return m.group(1) if m else None


def _flag_relative_hrefs(node, flags):
    """nh3 drops non-http/https/mailto <a href> silently; flag them (spec §5)."""
    anchors = ([node] if getattr(node, "name", None) == "a" else []) + (
        node.find_all("a", href=True) if isinstance(node, Tag) else []
    )
    for a in anchors:
        href = a.get("href", "")
        scheme = href.split(":", 1)[0].lower() if ":" in href else ""
        if scheme not in _OK_SCHEMES:
            flags.append(
                {
                    "kind": "relative_href",
                    "reason": f"relative/local <a href> dropped by nh3: {href}",
                    "raw_excerpt": str(a)[:300],
                }
            )


def _unmapped(reason, node, elements, flags):
    """Content-loss: emit a flagged html ELEMENT (so the loader gate fails loud)
    AND a flag record (spec §4.1 / I5) — never a flag record alone."""
    elements.append(
        {"type": "html", "flagged": True, "raw": str(node), "reason": reason}
    )
    flags.append(_flag(reason, node))


def _is_show_solution_button(node):
    return (
        isinstance(node, Tag)
        and node.name == "div"
        and "show_solution" in (node.get("class") or [])
    )


def parse_lesson(html, source_html):
    # Escape math <,> on the RAW string BEFORE parsing (Global Constraints / C1),
    # so BeautifulSoup builds a correct DOM. Never re-escape below.
    soup = BeautifulSoup(escape_math_delimited(html), "html.parser")
    root = soup.body or soup
    elements, flags = [], []
    h2_skipped = False
    children = list(root.children)
    consumed = set()  # ids of nodes already folded into a Spoiler (I2)
    for i, node in enumerate(children):
        if id(node) in consumed:
            continue
        if isinstance(node, Comment):
            continue  # HTML comments carry no content (Comment ⊂ NavigableString)
        if isinstance(node, NavigableString):
            if node.strip():
                _unmapped("bare text node in lesson body", node, elements, flags)
            continue
        if not isinstance(node, Tag) or node.name in _IGNORE_TAGS:
            continue
        name = node.name

        if name == "h2" and not h2_skipped:
            h2_skipped = True  # first <h2> is the unit title, not body
            continue

        if name in _TEXT_TAGS or name in _INLINE_TAGS:
            latex = _sole_block_math_latex(node)
            if latex is not None:
                elements.append({"type": "math", "latex": latex})  # display math
            else:
                _flag_relative_hrefs(node, flags)  # warn on nh3-dropped hrefs (I2)
                elements.append({"type": "text", "body": str(node)})  # already escaped
            continue

        if name == "figure":
            _emit_figure(node, elements, flags)
            continue
        if name == "video":
            _emit_video(node, elements, flags)
            continue
        if name == "img":
            elements.append(_image_dict(node))
            continue
        if name == "iframe":
            src = node.get("src", "")
            elements.append(
                {"type": "iframe", "url": src, "title": node.get("title", "")}
            )
            continue
        if _is_show_solution_button(node):
            sol = _next_solution(children, i + 1)
            if sol is not None:
                consumed.add(id(sol))  # so the loop does not re-flag it (I2)
                _flag_relative_hrefs(sol, flags)  # spoiler body is nh3-sanitized too
                body = "".join(str(c) for c in sol.children)  # already escaped
                elements.append(
                    {
                        "type": "spoiler",
                        "label": node.get_text(strip=True) or "zobacz",
                        "body": body,
                    }
                )
                continue
            _unmapped("show_solution button without solution", node, elements, flags)
            continue
        if name == "table":
            from scripts.lal_import.tables import table_element

            el, tflags = table_element(node)
            elements.append(el)
            flags.extend(tflags)
            _flag_relative_hrefs(node, flags)  # table cells are nh3-sanitized too
            continue

        _unmapped(f"unmapped <{name}> in lesson body", node, elements, flags)
    return elements, flags


def _next_solution(children, start):
    for j in range(start, len(children)):
        n = children[j]
        if isinstance(n, Tag) and "question_solution" in (n.get("class") or []):
            return n
    return None


def _image_dict(img):
    return {
        "type": "image",
        "media_src": img.get("src", ""),
        "alt": img.get("alt", ""),
        "figcaption": "",
    }


def _emit_figure(fig, elements, flags):
    video = fig.find("video")
    img = fig.find("img")
    cap = fig.find("figcaption")
    caption = cap.get_text(strip=True) if cap else ""
    if video is not None:
        _emit_video(video, elements, flags)
    elif img is not None:
        d = _image_dict(img)
        d["figcaption"] = caption
        elements.append(d)
    else:
        _unmapped("figure without video or img", fig, elements, flags)


def _emit_video(video, elements, flags):
    source = video.find("source")
    src = (source.get("src") if source else "") or video.get("src", "")
    if not src:
        _unmapped("video without a source src", video, elements, flags)
        return
    elements.append({"type": "video", "media_src": src})
