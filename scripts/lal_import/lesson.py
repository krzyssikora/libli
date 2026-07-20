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

from scripts.lal_import.answers import extract_int_map
from scripts.lal_import.mathsafe import escape_math_delimited
from scripts.lal_import.switch import switch_line_stem_cyclers

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
# Containers whose children are always descended into in place (R1) — but only
# if they actually contain block-level content; a container holding only
# inline content (text, span, br, strong, a, ...) is emitted whole as text (F1).
_ALWAYS_DESCEND_TAGS = {"html", "body"}
# JS-only presentation chrome: success/failure feedback (start `hidden`, revealed
# on a correct answer), inline warnings, and the GeoGebra no-JS fallback / email
# report boxes. None of it is lesson content — drop it silently (no flag).
_CHROME_CLASSES = {
    "success",
    "failure",
    "ans_warning",
    "inline_warning",
    "iframe_small",
    "iframe_telemetry",
    "info_iframe",
    "iframe_zonk",
    "mailto_tag",
}
_BLOCK_CHILD_TAGS = {
    "p",
    "div",
    "table",
    "figure",
    "video",
    "iframe",
    "ul",
    "ol",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "details",
    "blockquote",
    "pre",
}


# Rule 7: classes that mark a LAL interactive widget. Until Group B maps each to
# its native libli element, the whole widget container collapses to ONE flagged
# placeholder (loaded with --allow-html) rather than fragmenting into dozens of
# broken text blocks. Detection is by any marker in the node's subtree.
_INTERACTIVE_MARKERS = {
    # NB: switch_* are NOT markers — switch_options -> SwitchGrid (Group B #3),
    # switch_steps -> SwitchGate chain (Group B #2); both containers descend.
    # one-choice-in-a-line
    "one_choice",
    "confirm_choice",
    # multi-select grid (all-or-nothing rows)
    "multi_many_ans",
    "multi_many_option",
    "confirm_multiple",
    # MCQ with per-option feedback
    "mult_choice",
    "mult_option",
    "confirm_feedback_multiple",
    "mult_feedback_incorrect",
    # MCQ many lines with feedback
    "multi_ans",
    "confirm_button_feedback",
    "multi_feedback_ans",
    "multi_summary_ans",
    # true/false toggles
    "truth",
    "false",
    "confirmTF",
    # fill-in table / fill show-next
    "table_input",
    "table_input_30",
    "table_input_50",
    "fill_show_next",
    "fill_step",
    "fill_answer",
    # NB: show_next/show_step are NOT markers — they map natively to a RevealGate
    # chain (Group B #1), so their container must descend, not be placeholdered.
    # guess higher/lower
    "more_less_input",
    "more_less_big",
    "more_less_small",
    "more_less_equal",
    # mark-done, slideshow, tabs
    "mark_done",
    "show_slides",
    "slide_show",
    "ks_tabs",
    "user_input_enter",
}
_BINARY_ATTRS = ("data-binary-choose", "data-binary-choices-id")


def _marker_classes(node):
    """Every interactive-marker class found in node's subtree (incl. node)."""
    found = set()
    for el in [node] + node.find_all(True):
        for c in el.get("class") or []:
            if c in _INTERACTIVE_MARKERS:
                found.add(c)
        if any(el.get(a) for a in _BINARY_ATTRS):
            found.add("binary_choice")
    return found


def _contains_marker(node):
    return bool(_marker_classes(node))


def _is_structural_container(node):
    """Containers that must be DESCENDED (so their prompt renders and only their
    widget children are placeholdered), never collapsed wholesale: <html>/<body>
    and a question wrapper (div[id^=question] or div.question_text)."""
    if node.name in _ALWAYS_DESCEND_TAGS:
        return True
    if node.name == "div":
        if (node.get("id") or "").startswith("question"):
            return True
        if "question_text" in (node.get("class") or []):
            return True
    return False


def _has_block_child(node):
    """True if any DIRECT child of node is a block-level tag (F1). A container
    with no block-level children holds only inline content and must be emitted
    whole as text, not descended into (descending would expose bare inline
    children — text nodes, span, br, strong, a, ... — each of which would
    otherwise need its own top-level handling/flag)."""
    return any(
        isinstance(c, Tag) and c.name in _BLOCK_CHILD_TAGS for c in node.children
    )


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
        if href.startswith("#"):
            continue  # in-page anchor (tab/toc target), not a dropped external link
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
    state = {
        "h2_skipped": False,  # shared across recursive _walk calls (I2)
        # answer keys live in the RAW file's inline setItem scripts (pre-escape).
        "switch_answers": extract_int_map(html, "switch_answers"),
    }
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
                    # F2: bare inline text (e.g. "Zbiór \(A\) i \(B\)") -> TextElement.
                    # str(node) is a NavigableString: parsing already DECODED entities
                    # to literal `<`/`>`, so re-escape math spans before wrapping in
                    # the sanitized body field.
                    body = escape_math_delimited(str(node).strip())
                    elements.append({"type": "text", "body": f"<p>{body}</p>"})
            continue
        if not isinstance(node, Tag) or node.name in _IGNORE_TAGS:
            continue
        name = node.name

        classes_here = node.get("class") or []
        if any(c in _CHROME_CLASSES for c in classes_here):
            continue  # Rule 2: JS-only feedback/iframe chrome -> drop silently

        if "show_next" in classes_here:
            # Group B #1: a "pokaż dalej" progressive-reveal trigger -> RevealGate.
            # The following .show_step's content becomes the revealed siblings
            # (the client cascade reveals up to the next gate).
            elements.append(
                {
                    "type": "reveal_gate",
                    "label": node.get_text(strip=True) or "pokaż dalej",
                }
            )
            step = _next_show_step(nodes, i, consumed)
            if step is not None:
                consumed.add(id(step))
                _walk(list(step.children), elements, flags, consumed, state)
            continue
        if "show_step" in classes_here:
            # Consumed by its gate above (skipped via `consumed`); an orphan one
            # with no preceding gate still descends its content in place.
            _walk(list(node.children), elements, flags, consumed, state)
            continue
        if "switch_steps" in classes_here:
            # Group B #2: cycler-gated progressive reveal -> SwitchGate chain.
            _emit_switch_gate_chain(node, elements, flags, consumed, state)
            continue
        if "switch_options" in classes_here:
            # Group B #3: a confirmed switch grid -> SwitchGridElement.
            _emit_switch_grid(node, elements, state)
            continue

        if _contains_marker(node) and not _is_structural_container(node):
            # Rule 7: a not-yet-native interactive widget -> single placeholder,
            # coalescing consecutive widget siblings into one block.
            _emit_widget_placeholder(nodes, i, elements, flags, consumed)
            continue

        node_classes = node.get("class") or []
        if "question" in node_classes or "example" in node_classes:
            # Rule 8: an exercise label. Its source content is empty — script.js
            # rewrites it to "Zadanie N"/"Przykład N" — so emit a real label
            # instead of a blank styled paragraph.
            label = "Przykład" if "example" in node_classes else "Zadanie"
            elements.append(
                {"type": "text", "body": f"<p><strong>{label}</strong></p>"}
            )
            continue

        if name == "hr":
            continue  # R6: skipped silently

        if name == "h2" and not state["h2_skipped"]:
            state["h2_skipped"] = True  # first <h2> is the unit title, not body
            continue

        if name == "br":
            continue  # F3: inline line-break, no content -> skipped silently

        if name == "span":
            # F3: a top-level <span> (one that survived F1's inline-div text
            # emit, e.g. a span at a level with block siblings) -> TextElement.
            _flag_relative_hrefs(node, flags)
            elements.append({"type": "text", "body": str(node)})  # already escaped
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
            sol = _find_solution(nodes, i, consumed)
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
                # R2/Rule 1: the prompt. If it holds block content (a GeoGebra
                # <figure>, a table, multiple <p>), descend so _emit_figure runs
                # and tables/paragraphs map natively — emitting it wholesale via
                # decode_contents() would let nh3 strip the <iframe> and leak the
                # fallback chrome text. An inline-only prompt still -> one TextElement.
                if _has_block_child(node):
                    _walk(list(node.children), elements, flags, consumed, state)
                else:
                    _flag_relative_hrefs(node, flags)
                    elements.append({"type": "text", "body": node.decode_contents()})
                continue
            if "question_solution" not in classes:
                # R1: descend into any other container div (table_wrapper,
                # id="question...", or any other bare div) in place — but only
                # if it has block-level content to descend into (F1); an
                # inline-only div (bare text, span, br, strong, ...) is
                # emitted whole as a single TextElement instead.
                if _has_block_child(node):
                    _walk(list(node.children), elements, flags, consumed, state)
                else:
                    _flag_relative_hrefs(node, flags)
                    elements.append({"type": "text", "body": node.decode_contents()})
                continue
            # A .question_solution that a LATER show_solution button will claim
            # (R4 reverse order) must be skipped now, not emitted as unmapped —
            # the button consumes it via _find_solution's backward scan.
            if "question_solution" in classes and _followed_by_show_solution(
                nodes, i, consumed
            ):
                continue
            # else: an orphan question_solution div (not consumed by a preceding
            # show_solution button) falls through to the unmapped catch-all below.

        if name in _ALWAYS_DESCEND_TAGS:
            # R1/F1: <html>/<body> wrappers descend into their children in
            # place, unless they hold only inline content (rare, but keep the
            # same block-vs-inline check for consistency).
            if _has_block_child(node):
                _walk(list(node.children), elements, flags, consumed, state)
            else:
                _flag_relative_hrefs(node, flags)
                elements.append({"type": "text", "body": node.decode_contents()})
            continue

        _unmapped(f"unmapped <{name}> in lesson body", node, elements, flags)


def _enclosing_qid(node):
    """The integer id of the nearest div[id^=question] ancestor (for answer-key
    lookup), or None."""
    anc = node.find_parent(id=lambda x: x and x.startswith("question"))
    if anc is None:
        return None
    m = re.search(r"\d+", anc.get("id", ""))
    return int(m.group()) if m else None


def _is_switch_gate_line(node):
    """A .switch_line that carries a switch_show_next confirm button — i.e. the
    cycler that gates the reveal of the next step."""
    return (
        isinstance(node, Tag)
        and "switch_line" in (node.get("class") or [])
        and node.find(class_="switch_show_next") is not None
    )


def _emit_switch_gate_chain(container, elements, flags, consumed, state):
    """Group B #2: a .switch_steps block -> [step0 content][SwitchGate][step1
    content][SwitchGate]... Each .switch_step's trailing cycler line becomes a
    SwitchGate whose correct choice reveals the following siblings (the next
    step's content), mirroring the show_next RevealGate chain."""
    answers = state.get("switch_answers", {}).get(_enclosing_qid(container), [])
    gate_idx = 0
    for step in container.find_all(class_="switch_step", recursive=False):
        content = []
        for child in step.children:
            if _is_switch_gate_line(child):
                _walk(content, elements, flags, consumed, state)
                content = []
                stem, cyclers = switch_line_stem_cyclers(child)
                options = cyclers[0]["options"] if cyclers else []
                answer = answers[gate_idx] if gate_idx < len(answers) else 0
                elements.append(
                    {
                        "type": "switch_gate",
                        "stem": stem,
                        "options": options,
                        "answer": answer,
                    }
                )
                gate_idx += 1
            else:
                content.append(child)
        _walk(content, elements, flags, consumed, state)


def _emit_switch_grid(container, elements, state):
    """Group B #3: a .switch_options block -> one SwitchGridElement. Each
    .switch_line is one grid line with a single cycler; its correct index is
    switch_answers[qid][line_index]. The confirm button + success chrome are
    dropped (switch_line_stem_cyclers skips the button; the summary is chrome)."""
    answers = state.get("switch_answers", {}).get(_enclosing_qid(container), [])
    lines = []
    for i, line in enumerate(container.find_all(class_="switch_line")):
        stem, cyclers = switch_line_stem_cyclers(line)
        ans = answers[i] if i < len(answers) else 0
        for cyc in cyclers:
            cyc["answer"] = ans  # one cycler per line
        lines.append({"stem": stem, "cyclers": cyclers})
    elements.append({"type": "switch_grid", "prompt": "", "lines": lines})


def _next_show_step(nodes, start, consumed):
    """The .show_step revealed by the show_next gate at `start` — the next
    unconsumed sibling, but never past the following gate."""
    for j in range(start + 1, len(nodes)):
        n = nodes[j]
        if not isinstance(n, Tag):
            continue
        cls = n.get("class") or []
        if "show_step" in cls and id(n) not in consumed:
            return n
        if "show_next" in cls:
            return None  # the next gate begins before any step
    return None


def _emit_widget_placeholder(nodes, start, elements, flags, consumed):
    """Rule 7: collect the run of consecutive interactive-widget siblings starting
    at `start` (absorbing whitespace + dropping chrome between them) and emit ONE
    flagged html placeholder. Chrome descendants (success/failure praise) are
    stripped from the serialized HTML so no answer/feedback leaks."""
    parts, kinds = [], set()
    j = start
    while j < len(nodes):
        n = nodes[j]
        if isinstance(n, NavigableString):
            if n.strip() == "":
                j += 1
                continue  # whitespace between widget siblings -> absorb
            break  # real prose ends the widget run
        if not isinstance(n, Tag):
            j += 1
            continue
        cls = n.get("class") or []
        if any(c in _CHROME_CLASSES for c in cls):
            consumed.add(id(n))
            j += 1
            continue  # drop chrome sitting between widgets
        if _contains_marker(n) and not _is_structural_container(n):
            for chrome in n.find_all(
                lambda t: (
                    isinstance(t, Tag)
                    and any(c in _CHROME_CLASSES for c in (t.get("class") or []))
                )
            ):
                chrome.decompose()  # strip leaked feedback from the placeholder HTML
            kinds |= _marker_classes(n)
            parts.append(str(n))
            consumed.add(id(n))
            j += 1
            continue
        break  # non-widget, non-chrome content ends the run
    reason = "interactive_widget (Group B): " + (
        ",".join(sorted(kinds)) or "unclassified"
    )
    elements.append(
        {"type": "html", "flagged": True, "raw": "\n".join(parts), "reason": reason}
    )
    flags.append(_flag(reason, nodes[start]))


def _is_question_solution(n):
    return isinstance(n, Tag) and "question_solution" in (n.get("class") or [])


def _find_solution(nodes, button_i, consumed):
    """R4: pair a show_solution button with the nearest unconsumed
    .question_solution — forward first (the common case), then backward (some
    units place the solution BEFORE its button)."""
    order = list(range(button_i + 1, len(nodes))) + list(range(button_i - 1, -1, -1))
    for j in order:
        n = nodes[j]
        if id(n) not in consumed and _is_question_solution(n):
            return n
    return None


def _followed_by_show_solution(nodes, i, consumed):
    """True if an unconsumed show_solution button appears after index i — meaning
    a preceding .question_solution at i will be claimed by it (R4 reverse order),
    so it must not be emitted as unmapped now."""
    return any(
        _is_show_solution_button(nodes[j]) and id(nodes[j]) not in consumed
        for j in range(i + 1, len(nodes))
    )


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
