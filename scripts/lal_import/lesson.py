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
# included: the FIRST h2 is consumed as the unit title, later ones (and h1,
# which is never the title) are body.
_TEXT_TAGS = {
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "p",
    "ul",
    "ol",
    "blockquote",
    "pre",
    "small",
}
_INLINE_TAGS = {"strong", "em", "b", "i", "u", "code", "a"}
_IGNORE_TAGS = {"script", "link", "style"}
_OK_SCHEMES = {"http", "https", "mailto"}
# A block whose entire content is one \[...\] display span -> MathElement.
_DISPLAY_MATH = re.compile(r"^\\\[(.*)\\\]$", re.DOTALL)
# Containers whose children are always descended into in place (R1).
_ALWAYS_DESCEND_TAGS = {"html", "body"}


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


def _is_reveal_table(table):
    """A table whose descendants include a show_solution button or a
    question_solution body is a reveal-table (per-row Spoilers), not a data table."""
    return (
        table.find(class_="show_solution") is not None
        or table.find(class_="question_solution") is not None
    )


def _reveal_table_spoilers(table):
    """R3: one Spoiler per <tr> that has a .question_solution cell. label = the
    row's first <td> text (the concept cell); the empty .question_answer cell and
    the .show_solution button cell are ignored."""
    elements, flags = [], []
    for tr in table.find_all("tr"):
        sol = tr.find(class_="question_solution")
        if sol is None:
            continue  # skip rows with no solution
        first_td = tr.find("td")
        label = first_td.get_text(strip=True) if first_td is not None else ""
        _flag_relative_hrefs(sol, flags)  # spoiler body is nh3-sanitized too
        elements.append(
            {
                "type": "spoiler",
                "label": label,
                "body": sol.decode_contents(),  # re-escapes entities on serialize
            }
        )
    return elements, flags


def parse_lesson(html, source_html):
    # Escape math <,> on the RAW string BEFORE parsing (Global Constraints / C1),
    # so BeautifulSoup builds a correct DOM. Never re-escape below.
    soup = BeautifulSoup(escape_math_delimited(html), "html.parser")
    root = soup.body or soup
    elements, flags = [], []
    consumed = set()  # ids of nodes already folded into a Spoiler (I2)
    state = {"h2_skipped": False}  # shared across recursive _walk calls (I2)
    _walk(list(root.children), elements, flags, consumed, state)
    return elements, flags


def _walk(nodes, elements, flags, consumed, state):
    for i, node in enumerate(nodes):
        if id(node) in consumed:
            continue
        if isinstance(node, Comment):
            continue  # HTML comments carry no content (Comment ⊂ NavigableString)
        if isinstance(node, NavigableString):
            text = node.strip()
            if text:
                m = _DISPLAY_MATH.match(text)  # R5: bare \[...\] text -> MathElement
                if m is not None:
                    elements.append({"type": "math", "latex": m.group(1)})
                else:
                    _unmapped("bare text node in lesson body", node, elements, flags)
            continue
        if not isinstance(node, Tag) or node.name in _IGNORE_TAGS:
            continue
        name = node.name

        if name == "hr":
            continue  # R6: skipped silently

        if name == "h2" and not state["h2_skipped"]:
            state["h2_skipped"] = True  # first <h2> is the unit title, not body
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
        if name == "details":
            _emit_details(node, elements, flags)
            continue
        if _is_show_solution_button(node):
            sol = _next_solution(nodes, i + 1)
            if sol is not None:
                consumed.add(id(sol))  # so the loop does not re-flag it (I2)
                _flag_relative_hrefs(sol, flags)  # spoiler body is nh3-sanitized too
                body = sol.decode_contents()  # re-escapes entities on serialize
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
            if _is_reveal_table(node):
                sp_elements, sp_flags = _reveal_table_spoilers(node)
                elements.extend(sp_elements)
                flags.extend(sp_flags)
            else:
                from scripts.lal_import.tables import table_element

                el, tflags = table_element(node)
                elements.append(el)
                flags.extend(tflags)
                _flag_relative_hrefs(node, flags)  # table cells are nh3-sanitized too
            continue

        if name == "div":
            classes = node.get("class") or []
            if "question_text" in classes:
                # R2: the prompt text itself -> TextElement
                _flag_relative_hrefs(node, flags)
                elements.append({"type": "text", "body": node.decode_contents()})
                continue
            if "question_solution" not in classes:
                # R1: descend into any other container div (table_wrapper,
                # id="question...", or any other bare div) in place.
                _walk(list(node.children), elements, flags, consumed, state)
                continue
            # else: an orphan question_solution div (not consumed by a preceding
            # show_solution button) falls through to the unmapped catch-all below.

        if name in _ALWAYS_DESCEND_TAGS:
            # R1: <html>/<body> wrappers descend into their children in place.
            _walk(list(node.children), elements, flags, consumed, state)
            continue

        _unmapped(f"unmapped <{name}> in lesson body", node, elements, flags)


def _next_solution(nodes, start):
    for j in range(start, len(nodes)):
        n = nodes[j]
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
        iframe = fig.find("iframe")
        if iframe is not None:
            # R7: no video/img but an iframe -> IframeElement; any
            # .iframe_small.hidden no-JS fallback in the figure is dropped.
            elements.append(
                {"type": "iframe", "url": iframe.get("src", ""), "title": ""}
            )
        else:
            _unmapped("figure without video, img, or iframe", fig, elements, flags)


def _emit_video(video, elements, flags):
    source = video.find("source")
    src = (source.get("src") if source else "") or video.get("src", "")
    if not src:
        _unmapped("video without a source src", video, elements, flags)
        return
    elements.append({"type": "video", "media_src": src})


def _emit_details(details, elements, flags):
    """R4: <details><summary>LABEL</summary>BODY</details> -> Spoiler."""
    summary = details.find("summary")
    label = summary.get_text(strip=True) if summary is not None else ""
    if summary is not None:
        summary.extract()  # so decode_contents() below yields BODY only
    _flag_relative_hrefs(details, flags)  # spoiler body is nh3-sanitized too
    elements.append(
        {
            "type": "spoiler",
            "label": label,
            "body": details.decode_contents(),  # re-escapes entities on serialize
        }
    )
