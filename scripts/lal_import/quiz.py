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
_STEM_STRIP_TAGS = {"img", "table", "figure", "iframe", "h2"}


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

    def flush():
        nonlocal cur
        el, qflags = _finish(cur)
        if el is not None:
            questions.append(el)
        flags.extend(qflags)
        cur = _new_q()

    for node in root.children:
        if isinstance(node, Comment):
            # <!-- Zadanie N --> is an authoritative question boundary (spec §6).
            # bs4 stringifies a Comment to its inner text (no markers), so it MUST
            # be caught here structurally, never string-matched in _consume_line.
            flush()
            continue
        if isinstance(node, Tag):
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
                    flush()
                cur["stem_html"].append(str(node))  # already escaped
            continue
        if not isinstance(node, NavigableString):
            continue
        for line in str(node).splitlines():
            if not line.strip():
                continue
            _consume_line(line, cur, flags)
    flush()
    return questions, flags


def _new_q():
    return {
        "stem_html": [],
        "options": [],
        "answers": [],
        "answers_seen": False,
        "bracket": None,
    }


def _consume_line(line, cur, flags):
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
        return
    if line.lstrip().startswith("="):
        cur["answers_seen"] = True
        cur["answers"].append(line.lstrip()[1:].strip())
        return
    # Comments are handled structurally in parse_quiz (bs4 Comment nodes), never here.
    flags.append(_flag("unmatched_dsl", "line matched no DSL shape", line))


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
            {
                "type": "choice",
                "stem": stem,
                "multiple": multiple,
                "choices": cur["options"],
            },
            flags,
        )
    if has_fill:
        num = normalize_numeric(cur["answers"][0])
        if num is not None and len(cur["answers"]) == 1:
            return (
                {"type": "numeric", "stem": stem, "value": num, "tolerance": "0"},
                flags,
            )
        return (
            {
                "type": "shorttext",
                "stem": stem,
                "accepted": cur["answers"],
                "case_sensitive": False,
            },
            flags,
        )
    if stem.strip():
        return (
            _flag_element("stem had no answer DSL", stem),
            [_flag("stem_without_answer", "stem had no answer DSL", stem)],
        )
    return None, []
