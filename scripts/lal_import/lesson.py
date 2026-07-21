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
from scripts.lal_import.answers import extract_nested_int_map
from scripts.lal_import.answers import extract_nested_str_map
from scripts.lal_import.answers import extract_str_map
from scripts.lal_import.mathsafe import escape_math_delimited
from scripts.lal_import.switch import strip_lead_prompt
from scripts.lal_import.switch import switch_line_stem_cyclers
from scripts.lal_import.switch import token as _blank_token

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
    # widget confirm buttons whose native element supplies its own Check button:
    "confirm_choice",  # one_choice grid (Group B #7)
    "confirm_multiple",  # multi_many grid (Group B #9)
    "confirm_feedback_multiple",  # mult_choice MCQ (Group B #10)
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
    # NB: one_choice/confirm_choice are NOT markers — one_choice maps to a native
    # ChoiceGrid / per-row MCQ (Group B #7); confirm_choice is dropped as chrome.
    # NB: multi_many_* are NOT markers — a multi-select grid maps to a native
    # MultiGrid / per-row multi-select MCQ (Group B #9); confirm_multiple is chrome.
    # NB: mult_choice/mult_option/mult_feedback_incorrect are NOT markers — a
    # checkbox MCQ with per-option feedback maps to a native ChoiceQuestion
    # (Group B #10); confirm_feedback_multiple is dropped as chrome.
    # NB: multi_ans/confirm_button_feedback/multi_feedback_ans/multi_summary_ans
    # are NOT markers — a multi-select button MCQ with per-option feedback maps
    # to a native ChoiceQuestion (Group B #11); the whole leaf question div is
    # intercepted so its confirm/summary chrome is dropped.
    # true/false toggles
    "truth",
    "false",
    "confirmTF",
    # NB: table_input* / fill_answer / fill_show_next / fill_step are NOT markers —
    # table_input -> FillTable/FillBlank (Group B #4/#5), and fill_show_next is a
    # RevealGate chain with an inline FillBlank per step (Group B #8).
    # NB: show_next/show_step are NOT markers — they map natively to a RevealGate
    # chain (Group B #1), so their container must descend, not be placeholdered.
    # guess higher/lower
    "more_less_input",
    "more_less_big",
    "more_less_small",
    "more_less_equal",
    # NB: ks_tabs is NOT a marker — it maps to a native TabsElement with nested
    # children (Group B #6), so the container is handled, not placeholdered.
    # mark-done, slideshow
    "mark_done",
    "show_slides",
    "slide_show",
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


def _reveal_table_spoilers(table, consumed, state):
    """One nested Spoiler per <tr> with a .question_solution cell (or inlined rows,
    inside a spoiler). label = the row's first <td> text."""
    elements, flags = [], []
    for tr in table.find_all("tr"):
        sol = tr.find(class_="question_solution")
        if sol is None:
            continue
        # B1: the row's .question_answer div is the always-VISIBLE prompt (often a
        # figure/diagram <img>); emit it as visible siblings BEFORE the spoiler so
        # its image survives (walking the children routes each <img>/<figure>/text
        # through the image-aware path). question_answer and question_solution are
        # disjoint siblings, so this never re-walks the (hidden) solution.
        ans = tr.find(class_="question_answer")
        if ans is not None:
            _walk(list(ans.children), elements, flags, consumed, state)
        first_td = tr.find("td")
        label = first_td.get_text(strip=True) if first_td is not None else ""
        _flag_relative_hrefs(sol, flags)
        _emit_solution_region(
            label, list(sol.children), elements, flags, consumed, state
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
        "table_answers": extract_str_map(html, "table_answers"),
        "answers_fill_next": extract_str_map(html, "answers_fill_next"),
        "correct_choices": extract_int_map(html, "correct_choices"),
        "multiple_many_correct_answers": extract_nested_int_map(
            html, "multiple_many_correct_answers"
        ),
        "multiple_correct_answers": extract_nested_int_map(
            html, "multiple_correct_answers"
        ),
        "multiple_feedback": extract_nested_str_map(html, "multiple_feedback"),
    }
    # Precompute each fill input's accepted answer BEFORE the walk mutates the tree
    # (a block's inputs are replace_with()'d by tokens; a later block's positional
    # index would otherwise shift). Keyed by the input node's id().
    state["fill_answer_of"] = _fill_answer_map(soup, state)
    _walk(list(root.children), elements, flags, consumed, state)
    return elements, flags


def _emit_solution_region(label, content_nodes, elements, flags, consumed, state):
    """A labelled disclosure region (from <details>, show_solution, or a reveal-
    table row). At TOP LEVEL -> a nested SpoilerElement dict whose children are the
    walked content (images/tables/math survive as their own children). INSIDE a
    spoiler (no-nest-container mode) -> inlined in place (label -> heading child,
    content walked inline), never a nested container dict, keeping depth at 1."""
    if state.get("in_spoiler"):
        if label:
            elements.append({"type": "text", "body": f"<h4>{label}</h4>"})
        _walk(content_nodes, elements, flags, consumed, state)
    else:
        child_elements = []
        prev = state.get("in_spoiler", False)  # always False here, but be explicit
        state["in_spoiler"] = True
        try:
            _walk(content_nodes, child_elements, flags, consumed, state)
        finally:
            state["in_spoiler"] = prev
        elements.append({"type": "spoiler", "label": label, "elements": child_elements})


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
            # The following .show_step content becomes the revealed siblings.
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
        if "fill_show_next" in classes_here:
            continue  # Group B #8: the fill_step's FillGate supplies the reveal
        if "fill_step" in classes_here:
            # Group B #8: "Fill in & confirm" — the step's blank IS the gate;
            # a correct answer reveals the following siblings (the next step).
            d = _fillblank_from_block(node, state)
            if d["blanks"]:
                elements.append(
                    {"type": "fill_gate", "stem": d["stem"], "answers": d["blanks"]}
                )
            else:  # a fill_step with no input -> just reveal-only content
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
        if (
            not _is_structural_container(node)
            and node.find(class_="one_choice") is not None
        ):
            # Group B #7: a pick-one-per-line one_choice widget -> ChoiceGrid
            # (shared columns) or per-row single-choice MCQ (varying columns).
            elements.extend(_emit_one_choice(node, state))
            continue
        if (
            not _is_structural_container(node)
            and node.find(class_="multi_many_option") is not None
        ):
            # Group B #9: a multi-select grid row -> gather the run of sibling row
            # divs into one MultiGrid (shared columns) or per-row multi-select MCQ.
            _emit_multi_many(nodes, i, elements, flags, consumed, state)
            continue
        if (node.get("id") or "").startswith("question") and node.find(
            class_="mult_option"
        ) is not None:
            # Group B #10: a checkbox MCQ with per-option feedback -> one
            # ChoiceQuestion(multiple=True). Intercept the whole question div (its
            # .mult_option/.mult_feedback_incorrect layout varies — wrapped or bare
            # children) so the confirm button + success/failure chrome inside are
            # dropped, not descended.
            _emit_mult_choice(node, elements, flags, consumed, state)
            continue
        if (
            (node.get("id") or "").startswith("question")
            and node.find(class_="multi_ans") is not None
            and node.find("div", id=lambda x: x and x.startswith("question")) is None
        ):
            # Group B #11: a multi-select button MCQ with per-option feedback ->
            # one ChoiceQuestion(multiple=True). Only the LEAF question div (no
            # nested question) is intercepted; a parent group div still descends
            # so its prompt text + interleaved \[..\] math render before each MCQ.
            _emit_multi_ans(node, elements, flags, consumed, state)
            continue
        if "ks_tabs" in classes_here:
            if state.get("in_spoiler"):
                # No-nest-container mode: a ks_tabs inside a spoiler can't become a
                # nested Tabs (depth-1), so flatten it inline.
                _flatten_tabs_inline(node, elements, flags, consumed, state)
            else:
                # Group B #6: a tabbed container -> TabsElement with nested children.
                tabs_el = _emit_tabs(node, flags, consumed, state)
                if tabs_el is not None:
                    elements.append(tabs_el)
                else:
                    _unmapped(
                        "ks_tabs outside TabsElement's 2..10 tab bounds",
                        node,
                        elements,
                        flags,
                    )
            continue

        if name != "table" and not _has_block_child(node) and _has_fill_input(node):
            # Group B #5/#8: an inline text block holding table_input/fill_answer
            # input(s) NOT inside a <table> -> a FillBlank self-check (else nh3
            # strips the <input> and the block renders as an empty paragraph).
            # Block containers descend first (a real fill TABLE reaches the table
            # branch, a fill_step reaches the show-next handler).
            elements.append(_fillblank_from_block(node, state))
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
            _emit_text_or_images(node, str(node), elements, flags)  # already escaped
            continue

        if name in _TEXT_TAGS or name in _INLINE_TAGS:
            latex = _sole_block_math_latex(node)
            if latex is not None:
                elements.append({"type": "math", "latex": latex})  # display math
            else:
                _flag_relative_hrefs(node, flags)  # warn on nh3-dropped hrefs (I2)
                _emit_text_or_images(
                    node, str(node), elements, flags
                )  # already escaped
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
            if node.find(class_="ks_tabs") is not None:
                # A <details> wrapping a tab group: drop the collapse wrapper and
                # emit its content (summary -> heading). At top level the inner
                # ks_tabs becomes a native TabsElement; inside a spoiler the ks_tabs
                # branch below flattens it (in_spoiler propagates via `state`).
                summary = node.find("summary")
                if summary is not None:
                    label = summary.decode_contents().strip()
                    if label:
                        elements.append({"type": "text", "body": f"<h4>{label}</h4>"})
                    summary.extract()
                _walk(list(node.children), elements, flags, consumed, state)
            else:
                _emit_details(node, elements, flags, consumed, state)
            continue
        if _is_show_solution_button(node):
            sol = _find_solution(nodes, i, consumed)
            if sol is not None:
                consumed.add(id(sol))  # so the loop does not re-flag it (I2)
                _flag_relative_hrefs(sol, flags)
                _emit_solution_region(
                    node.get_text(strip=True) or "zobacz",
                    list(sol.children),
                    elements,
                    flags,
                    consumed,
                    state,
                )
                continue
            _unmapped("show_solution button without solution", node, elements, flags)
            continue
        if name == "table":
            if node.find(class_="table_input") is not None:
                # Group B #4: a fill-in table -> FillTableElement.
                from scripts.lal_import.tables import fill_table_element

                el, tflags = fill_table_element(node, _table_answer_map(node, state))
                elements.append(el)
                flags.extend(tflags)
                _flag_relative_hrefs(node, flags)
            elif _is_reveal_table(node):
                sp_elements, sp_flags = _reveal_table_spoilers(node, consumed, state)
                elements.extend(sp_elements)
                flags.extend(sp_flags)
            elif node.find("img") is not None:
                # A plain (non-fill, non-reveal) table that arranges diagrams:
                # nh3 strips <img> from cell HTML, so a TableElement would lose
                # them. Unpack it into a linear sequence of native ImageElements
                # (+ label captions). This is the fallback for what would else be
                # a plain TableElement, so real fill/reveal tables keep their type.
                _emit_image_table(node, elements, flags)
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
                    _emit_text_or_images(node, node.decode_contents(), elements, flags)
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
                    _emit_text_or_images(node, node.decode_contents(), elements, flags)
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
                _emit_text_or_images(node, node.decode_contents(), elements, flags)
            continue

        _unmapped(f"unmapped <{name}> in lesson body", node, elements, flags)


def _answer_alt_list(raw):
    """Accepted-answer alternatives for a fill blank: a decimal accepts both dot
    and Polish-comma forms; a fraction/integer/string is kept verbatim."""
    if "." in raw and "/" not in raw:
        return [raw, raw.replace(".", ",")]
    return [raw]


# inline fill-in input classes and the localStorage key holding their answers.
_FILL_INPUTS = (("table_input", "table_answers"), ("fill_answer", "answers_fill_next"))


def _has_fill_input(node):
    return any(node.find(class_=cls) is not None for cls, _ in _FILL_INPUTS)


def _fill_answer_map(soup, state):
    """Map every fill input node's id() to its accepted answer, indexed per input
    class within its enclosing question (the JS numbers table_input/fill_answer
    per-question). Built once, before the walk mutates the tree."""
    out = {}
    for qnode in soup.find_all(id=lambda x: x and x.startswith("question")):
        m = re.search(r"\d+", qnode.get("id", ""))
        qid = int(m.group()) if m else None
        for cls, key in _FILL_INPUTS:
            answers = state.get(key, {}).get(qid, [])
            for i, inp in enumerate(qnode.find_all(class_=cls)):
                out[id(inp)] = answers[i] if i < len(answers) else ""
    return out


def _fillblank_from_block(node, state):
    """Group B #5/#8: turn a text block holding inline table_input/fill_answer
    input(s) into a {type:fillblank} dict — the block content becomes the stem
    with each input replaced by a sentinel blank token; accepted answers come from
    the precomputed state["fill_answer_of"] map (see _fill_answer_map)."""
    answer_of = state.get("fill_answer_of", {})
    blanks = []
    for inp in node.find_all(class_=[cls for cls, _ in _FILL_INPUTS]):
        blanks.append(_answer_alt_list(answer_of.get(id(inp), "")))
        inp.replace_with(NavigableString(_blank_token(len(blanks) - 1)))
    return {"type": "fillblank", "stem": node.decode_contents(), "blanks": blanks}


def _table_answer_map(table, state):
    """Map each table_input node (by id) in `table` to its accepted answer,
    matched positionally against table_answers[qid] over ALL inputs in the
    enclosing question (the JS numbers them per-question, not per-table)."""
    qid = _enclosing_qid(table)
    answers = state.get("table_answers", {}).get(qid, [])
    qnode = table.find_parent(id=lambda x: x and x.startswith("question")) or table
    out = {}
    for i, inp in enumerate(qnode.find_all(class_="table_input")):
        if i < len(answers):
            out[id(inp)] = answers[i]
    return out


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
        gate_idx = _emit_switch_step(
            step, elements, flags, consumed, state, answers, gate_idx
        )


def _emit_switch_step(step, elements, flags, consumed, state, answers, gate_idx):
    """Emit one .switch_step's content, splitting on its gate line(s): content
    before a gate line -> native siblings; the gate line -> a switch_gate dict
    (answer looked up positionally in `answers` by `gate_idx`). Returns the
    updated gate_idx so the caller threads it across steps."""
    content = []
    for child in step.children:
        if _is_switch_gate_line(child):
            _walk(content, elements, flags, consumed, state)
            content = []
            stem, cyclers = switch_line_stem_cyclers(child)
            options = cyclers[0]["options"] if cyclers else []
            raw = answers[gate_idx] if gate_idx < len(answers) else 0
            options, answer = strip_lead_prompt(options, raw)
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
    return gate_idx


def _one_choice_rows(node):
    """Group a container's .one_choice options by their parent (JS groups by
    parentElement) into ordered rows of {statement, options}. Text is decoded
    (literal <) — ChoiceGrid labels/statements are auto-escaped by format_html."""
    groups, order = {}, []
    for oc in node.find_all(class_="one_choice"):
        pid = id(oc.parent)
        if pid not in groups:
            groups[pid] = {"parent": oc.parent, "options": []}
            order.append(pid)
        groups[pid]["options"].append(oc.get_text(" ", strip=True))
    rows = []
    for pid in order:
        parent = groups[pid]["parent"]
        stmt = parent.find(class_="statement")
        statement = (stmt or parent).get_text(" ", strip=True)
        rows.append({"statement": statement, "options": groups[pid]["options"]})
    return rows


def _emit_one_choice(node, state):
    """Group B #7: build a ChoiceGrid when every row shares the same option set,
    else one single-choice MCQ per row. correct_choices[qid] is 1-based (elt_id+1)."""
    answers = state.get("correct_choices", {}).get(_enclosing_qid(node), [])
    rows = _one_choice_rows(node)
    for i, r in enumerate(rows):
        r["correct"] = (answers[i] - 1) if i < len(answers) else 0
    if rows and len({tuple(r["options"]) for r in rows}) == 1:
        return [
            {
                "type": "choice_grid",
                "columns": rows[0]["options"],
                "rows": [
                    {"statement": r["statement"], "correct": r["correct"]} for r in rows
                ],
            }
        ]
    # varying columns -> a single-choice MCQ per row (stem is a sanitized field).
    return [
        {
            "type": "choice",
            "stem": f"<p>{escape_math_delimited(r['statement'])}</p>",
            "multiple": False,
            "choices": [
                {"text": o, "is_correct": (j == r["correct"])}
                for j, o in enumerate(r["options"])
            ],
        }
        for r in rows
    ]


def _emit_multi_many(nodes, start, elements, flags, consumed, state):
    """Group B #9: consecutive sibling row divs (each a .multi_many_option
    statement + its .multi_many_ans column buttons) -> one MultiGrid when every
    row shares the same column labels, else one per-row multi-select MCQ. The 0/1
    correct mask per row is multiple_many_correct_answers[qid][row_index]."""
    run = []
    for j in range(start, len(nodes)):
        n = nodes[j]
        if isinstance(n, NavigableString):
            if n.strip():
                break
            continue  # whitespace between row divs
        if not isinstance(n, Tag):
            break
        if id(n) in consumed or n.find(class_="multi_many_option") is None:
            break
        run.append(n)
    for n in run[1:]:  # nodes[start] is the current node; the rest are consumed
        consumed.add(id(n))
    masks = state.get("multiple_many_correct_answers", {}).get(
        _enclosing_qid(run[0]), []
    )
    rows = []
    for k, row_div in enumerate(run):
        opt = row_div.find(class_="multi_many_option")
        statement = opt.get_text(" ", strip=True) if opt else ""
        options = [
            a.get_text(" ", strip=True)
            for a in row_div.find_all(class_="multi_many_ans")
        ]
        mask = masks[k] if k < len(masks) else []
        correct = [idx for idx, v in enumerate(mask) if idx < len(options) and v]
        rows.append({"statement": statement, "options": options, "correct": correct})
    if rows and len({tuple(r["options"]) for r in rows}) == 1:
        elements.append(
            {
                "type": "multi_grid",
                "columns": rows[0]["options"],
                "rows": [
                    {"statement": r["statement"], "correct": r["correct"]} for r in rows
                ],
            }
        )
        return
    # varying columns -> a per-row multi-select MCQ (multiple=True; multi_many is
    # a pick-a-set widget). The stem is a sanitized field, so re-escape math.
    for r in rows:
        elements.append(
            {
                "type": "choice",
                "stem": f"<p>{escape_math_delimited(r['statement'])}</p>",
                "multiple": True,
                "choices": [
                    {"text": o, "is_correct": (j in r["correct"])}
                    for j, o in enumerate(r["options"])
                ],
            }
        )


_MEDIA_TAGS = ["img", "figure", "iframe", "video"]


def _mcq_stem(question, elements, flags, consumed, state):
    """The stem for an intercepted MCQ. If .question_text carries media (a
    diagram / figure), descend it so images render as native ImageElements and
    return "" (an empty stem); otherwise flatten the prompt text into the stem (a
    sanitized field, so re-escape math)."""
    qt = question.find(class_="question_text")
    if qt is None:
        return ""
    if qt.find(_MEDIA_TAGS) is not None:
        _walk(list(qt.children), elements, flags, consumed, state)
        return ""
    text = qt.get_text(" ", strip=True)
    return f"<p>{escape_math_delimited(text)}</p>" if text else ""


def _emit_mult_choice(question, elements, flags, consumed, state):
    """Group B #10: a checkbox MCQ with per-option feedback -> one
    ChoiceQuestion(multiple=True). `question` is the whole div[id^=question]; its
    .mult_option (option text) and .mult_feedback_incorrect (its hint) blocks are
    paired in document order. is_correct comes from
    multiple_many_correct_answers[qid][0] (a single 0/1 mask row)."""
    m = re.search(r"\d+", question.get("id", ""))
    qid = int(m.group()) if m else None
    stem = _mcq_stem(question, elements, flags, consumed, state)
    mask = state.get("multiple_many_correct_answers", {}).get(qid, [])
    mask = mask[0] if mask else []
    options = question.find_all(class_="mult_option")
    feedbacks = question.find_all(class_="mult_feedback_incorrect")
    choices = []
    for i, opt in enumerate(options):
        fb = feedbacks[i] if i < len(feedbacks) else None
        choices.append(
            {
                "text": opt.get_text(" ", strip=True),
                "is_correct": bool(mask[i]) if i < len(mask) else False,
                "feedback": fb.get_text(" ", strip=True) if fb is not None else "",
            }
        )
    elements.append(
        {"type": "choice", "stem": stem, "multiple": True, "choices": choices}
    )


def _emit_multi_ans(question, elements, flags, consumed, state):
    """Group B #11: a multi-select button MCQ with per-option feedback -> one
    ChoiceQuestion(multiple=True). `question` is the leaf div[id^=question]; its
    .multi_ans buttons are the options. is_correct comes from
    multiple_correct_answers[qid][0] and each option's feedback from
    multiple_feedback[qid][0] (both a single row). The stem is this question's own
    .question_text (empty if absent — a preceding \\[..\\] math block or the group
    prompt is the context)."""
    m = re.search(r"\d+", question.get("id", ""))
    qid = int(m.group()) if m else None
    stem = _mcq_stem(question, elements, flags, consumed, state)
    correct = state.get("multiple_correct_answers", {}).get(qid, [])
    mask = correct[0] if correct else []
    fb_rows = state.get("multiple_feedback", {}).get(qid, [])
    fbs = fb_rows[0] if fb_rows else []
    choices = []
    for i, opt in enumerate(question.find_all(class_="multi_ans")):
        choices.append(
            {
                "text": opt.get_text(" ", strip=True),
                "is_correct": bool(mask[i]) if i < len(mask) else False,
                "feedback": fbs[i] if i < len(fbs) else "",
            }
        )
    elements.append(
        {"type": "choice", "stem": stem, "multiple": True, "choices": choices}
    )


def _emit_tabs(ks_tabs, flags, consumed, state):
    """Group B #6: a .ks_tabs container -> a {type:tabs} dict with nested child
    elements per panel. Returns None (caller placeholders) if the tab count is
    out of TabsElement's 2..10 bounds. Each <a id=tab-S-P href=#tabcontent-S-P>
    is a tab label; its panel div's children recurse via _walk into that tab's
    child elements."""
    links = ks_tabs.select("ul li a")
    if not (2 <= len(links) <= 10):
        return None
    tabs = []
    for i, a in enumerate(links):
        href = a.get("href", "")
        panel = ks_tabs.find(id=href[1:]) if href.startswith("#") else None
        child_elements = []
        if panel is not None:
            _walk(list(panel.children), child_elements, flags, consumed, state)
        tabs.append(
            {
                "id": f"t{i:06d}",
                "label": a.get_text(strip=True) or f"Tab {i + 1}",
                "elements": child_elements,
            }
        )
    return {"type": "tabs", "tabs": tabs}


def _flatten_tabs_inline(node, elements, flags, consumed, state):
    """No-nest-container mode: reuse _emit_tabs to parse the tab group, then splice
    it inline -- each tab label -> a heading text child, each tab's parsed content
    appended as sibling children. _emit_tabs's internal walk sees state['in_spoiler']
    too, so any deeper container inside a panel is likewise flattened."""
    tabs_el = _emit_tabs(node, flags, consumed, state)
    if tabs_el is None:
        _unmapped(
            "ks_tabs inside spoiler outside 2..10 tab bounds", node, elements, flags
        )
        return
    for tab in tabs_el["tabs"]:
        if tab.get("label"):
            elements.append({"type": "text", "body": f"<h4>{tab['label']}</h4>"})
        elements.extend(tab.get("elements", []))


def _emit_switch_grid(container, elements, state):
    """Group B #3: a .switch_options block -> one SwitchGridElement. Each
    .switch_line is one grid line with a single cycler; its correct index is
    switch_answers[qid][line_index]. The confirm button + success chrome are
    dropped (switch_line_stem_cyclers skips the button; the summary is chrome)."""
    answers = state.get("switch_answers", {}).get(_enclosing_qid(container), [])
    lines = []
    for i, line in enumerate(container.find_all(class_="switch_line")):
        stem, cyclers = switch_line_stem_cyclers(line)
        raw = answers[i] if i < len(answers) else 0
        for cyc in cyclers:  # one cycler per line
            cyc["options"], cyc["answer"] = strip_lead_prompt(cyc["options"], raw)
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


def _emit_text_with_images(node, elements, flags):
    """Emit a text-destined block that contains <img>: nh3 strips <img> from a
    sanitized TextElement.body, so pull each image out as its own ImageElement and
    coalesce the surrounding content into TextElements, preserving reading order.
    NavigableStrings are math-escaped like the F2 bare-text rule; child tags are
    already re-escaped by str()."""
    buf = []

    def flush():
        html = "".join(buf).strip()
        buf.clear()
        if html and BeautifulSoup(html, "html.parser").get_text(strip=True):
            elements.append({"type": "text", "body": f"<p>{html}</p>"})

    for child in list(node.children):
        if isinstance(child, NavigableString):
            buf.append(escape_math_delimited(str(child)))
        elif getattr(child, "name", None) == "img":
            flush()
            elements.append(_image_dict(child))
        elif isinstance(child, Tag) and child.find("img") is not None:
            flush()
            _emit_text_with_images(child, elements, flags)
        else:
            buf.append(str(child))
    flush()


def _emit_text_or_images(node, body, elements, flags):
    """Emit `node` as a single TextElement, unless it holds an <img> (which nh3
    would strip from the sanitized body) — then split it into text + images."""
    if isinstance(node, Tag) and node.find("img") is not None:
        _emit_text_with_images(node, elements, flags)
    else:
        elements.append({"type": "text", "body": body})


def _emit_image_table(table, elements, flags):
    """Unpack a layout table that arranges diagrams (nh3 strips <img> from cell
    HTML, so a TableElement would drop them). Emit its cells in reading order:
    an image cell -> ImageElement, a text cell -> a label TextElement. When a
    text label sits directly ABOVE an image (same column, previous row) it is
    consumed as that image's figcaption instead (e.g. "1" over the first
    diagram), so numbered diagram grids read as captioned images."""
    grid = [tr.find_all(["td", "th"], recursive=False) for tr in table.find_all("tr")]

    def _cell(r, c):
        return grid[r][c] if 0 <= r < len(grid) and 0 <= c < len(grid[r]) else None

    def _text(cell):
        return cell.get_text(" ", strip=True) if cell is not None else ""

    # label cells consumed as the caption of the image directly below them
    caption_cells = set()
    for r, row in enumerate(grid):
        for c, cell in enumerate(row):
            if cell.find("img") is None and _text(cell):
                below = _cell(r + 1, c)
                if below is not None and below.find("img") is not None:
                    caption_cells.add((r, c))
    for r, row in enumerate(grid):
        for c, cell in enumerate(row):
            if (r, c) in caption_cells:
                continue
            imgs = cell.find_all("img")
            if imgs:
                above = _cell(r - 1, c)
                cap = _text(above) if (r - 1, c) in caption_cells else ""
                for k, img in enumerate(imgs):
                    d = _image_dict(img)
                    if cap and k == 0:
                        d["figcaption"] = cap[:255]
                    elements.append(d)
            elif _text(cell):
                elements.append(
                    {"type": "text", "body": f"<p>{cell.decode_contents().strip()}</p>"}
                )
    _flag_relative_hrefs(table, flags)


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


def _emit_details(details, elements, flags, consumed, state):
    """<details><summary>LABEL</summary>BODY</details> -> nested SpoilerElement
    (or inlined, inside a spoiler). BODY is walked into child element dicts."""
    summary = details.find("summary")
    label = summary.get_text(strip=True) if summary is not None else ""
    if summary is not None:
        summary.extract()
    _flag_relative_hrefs(details, flags)  # spoiler children are nh3-sanitized too
    _emit_solution_region(
        label, list(details.children), elements, flags, consumed, state
    )
