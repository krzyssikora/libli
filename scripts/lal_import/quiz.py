"""Parse OpenEdX-style quiz DSL (bare text lines between <p> stems) into questions."""

import re

from bs4 import BeautifulSoup
from bs4 import Comment
from bs4 import NavigableString
from bs4 import Tag

from scripts.lal_import.mathsafe import escape_math_delimited
from scripts.lal_import.numbers import normalize_numeric

_OPTION = re.compile(r"^\s*([\[(])\s*([ xX]?)\s*[\])]\s*(.*)$")
_HINT = re.compile(r"\{\{\s*(\w+)\s*:\s*(.*?)\s*\}\}\s*$", re.DOTALL)
_POINTS = re.compile(r"^\(\s*(\d+(?:[.,]\d+)?)\s*\)$")
_STEM_STRIP_TAGS = {"img", "table", "iframe", "h2"}
_DISPLAY_OPEN, _DISPLAY_CLOSE = "\\[", "\\]"


def _logical_lines(text):
    """Split `text` into lines, but keep a multi-line \\[...\\] display-math block as
    ONE logical line. A bare-text intro often writes display math across physical
    lines; without this each line would be wrapped in its own <p> (splitting \\[
    from \\]), which KaTeX cannot render."""
    buf = None
    for line in text.splitlines():
        if buf is not None:
            buf.append(line)
            if _DISPLAY_CLOSE in line:
                yield "\n".join(buf)
                buf = None
            continue
        if _DISPLAY_OPEN in line and _DISPLAY_CLOSE not in line:
            buf = [line]
            continue
        yield line
    if buf is not None:  # unterminated \\[ -> yield what we accumulated
        yield "\n".join(buf)


def _flag(kind, reason, excerpt=""):
    return {"kind": kind, "reason": reason, "raw_excerpt": excerpt[:300]}


def _flag_element(reason, raw):
    return {"type": "html", "flagged": True, "raw": raw, "reason": reason}


def _split_hint(text):
    m = _HINT.search(text)
    if not m:
        return text.strip(), None, None
    return text[: m.start()].strip(), m.group(1), m.group(2)


def parse_quiz(html):
    # Escape math <,> on the RAW string before parsing (C1); never re-escape below.
    soup = BeautifulSoup(escape_math_delimited(html), "html.parser")
    root = soup.body or soup
    questions, flags = [], []
    cur = _new_q()

    def flush(cur):
        el, qflags = _finish(cur)
        if el is not None:
            questions.append(el)
        flags.extend(qflags)
        return _new_q()

    for node in root.children:
        if isinstance(node, Comment):
            # <!-- Zadanie N --> is an authoritative question boundary (spec §6).
            # bs4 stringifies a Comment to its inner text (no markers), so it MUST
            # be caught here structurally, never string-matched in _consume_line.
            cur = flush(cur)
            continue
        if isinstance(node, Tag):
            if node.name == "figure":
                # A standalone diagram: emit a native ImageElement (nh3 would strip
                # the <img> from a sanitized stem). Flush any pending intro first so
                # the figure keeps its document position.
                img = node.find("img")
                if img is not None:
                    cap = node.find("figcaption")
                    cur = flush(cur)
                    questions.append(
                        {
                            "type": "image",
                            "media_src": img.get("src", ""),
                            "alt": img.get("alt", ""),
                            "figcaption": cap.get_text(strip=True) if cap else "",
                        }
                    )
                continue
            if node.name in _STEM_STRIP_TAGS:
                # content-loss: emit a flagged element AND a flag record (I5)
                questions.append(
                    _flag_element(
                        f"<{node.name}> media cannot live in a sanitized stem",
                        str(node),
                    )
                )
                flags.append(
                    _flag(
                        "quiz_stem_media",
                        f"<{node.name}> cannot live in a sanitized stem",
                        str(node),
                    )
                )
                continue
            if node.name in {"p", "div"}:
                if cur["answers_seen"]:  # boundary: stem after answers
                    cur = flush(cur)
                cur["stem_html"].append(str(node))  # already escaped
            continue
        if not isinstance(node, NavigableString):
            continue
        for line in _logical_lines(str(node)):
            if not line.strip():
                continue
            cur = _consume_line(line, cur, flags, flush)
    flush(cur)
    return questions, flags


def _new_q():
    return {
        "stem_html": [],
        "options": [],
        "answers": [],
        "answers_seen": False,
        "bracket": None,
        "points": None,
    }


def _consume_line(line, cur, flags, flush):
    pm = _POINTS.match(line.strip())
    if pm:
        cur["points"] = pm.group(1).replace(",", ".")
        return cur
    m = _OPTION.match(line)
    if m:
        cur["answers_seen"] = True
        bracket = "[" if m.group(1) == "[" else "("
        cur["bracket"] = cur["bracket"] or bracket
        is_correct = m.group(2).lower() == "x"
        text, hint_key, hint_val = _split_hint(m.group(3))
        feedback = ""
        if hint_key is not None:
            if hint_key == "selected":
                feedback = hint_val
            else:
                flags.append(
                    _flag(
                        "unknown_hint",
                        f"hint form {{{{{hint_key}:}}}} not mapped",
                        line,
                    )
                )
        cur["options"].append(
            {"text": text, "is_correct": is_correct, "feedback": feedback}
        )
        return cur
    if line.lstrip().startswith("="):
        cur["answers_seen"] = True
        cur["answers"].append(line.lstrip()[1:].strip())
        return cur
    # Comments are handled structurally in parse_quiz (bs4 Comment nodes), never here.
    # Any other bare-text line is stem prose (Q1), not an unmatched-DSL error. A
    # bare NavigableString line has entities DECODED (literal '<'); the |safe stem
    # needs the entity form, so re-escape before folding it in.
    if cur["answers_seen"]:  # boundary: stem after answers, mirrors <p>/<div>
        cur = flush(cur)
    cur["stem_html"].append("<p>" + escape_math_delimited(line.strip()) + "</p>")
    return cur


def _with_points(d, cur):
    if cur["points"] is not None:
        d["points"] = cur["points"]
    return d


def _finish(cur):
    stem = "".join(cur["stem_html"])  # already math-escaped at parse_quiz entry
    has_choice = bool(cur["options"])
    has_fill = bool(cur["answers"])
    if has_choice and has_fill:
        # content-loss: emit a flagged element AND a flag record (I5)
        return (
            _flag_element("question has both an option group and a = answer", stem),
            [
                _flag(
                    "mixed_zadanie",
                    "question has both an option group and a = answer",
                    stem,
                )
            ],
        )
    flags = []
    for opt in cur["options"]:
        if len(opt["text"]) > 500 or len(opt["feedback"]) > 500:
            flags.append(
                _flag(
                    "choice_over_500",
                    "choice text/feedback exceeds 500 chars",
                    opt["text"],
                )
            )
    if has_choice:
        multiple = cur["bracket"] == "["
        return (
            _with_points(
                {
                    "type": "choice",
                    "stem": stem,
                    "multiple": multiple,
                    "choices": cur["options"],
                },
                cur,
            ),
            flags,
        )
    if has_fill:
        num = normalize_numeric(cur["answers"][0])
        if num is not None and len(cur["answers"]) == 1:
            return (
                _with_points(
                    {"type": "numeric", "stem": stem, "value": num, "tolerance": "0"},
                    cur,
                ),
                flags,
            )
        return (
            _with_points(
                {
                    "type": "shorttext",
                    "stem": stem,
                    "accepted": cur["answers"],
                    "case_sensitive": False,
                },
                cur,
            ),
            flags,
        )
    if stem.strip():
        # A stem with no answer DSL is INTRODUCTORY content (a shared "Wprowadzenie"
        # before a group of questions), not a malformed question. Emit it as a
        # TextElement so it renders in the quiz flow (the quiz page renders every
        # element, and KaTeX typesets any \[...\]/\(...\) in the body) rather than
        # a flagged HtmlElement.
        return ({"type": "text", "body": stem}, [])
    return None, []
