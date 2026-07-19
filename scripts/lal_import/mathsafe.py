"""Escape <,> inside \\(...\\) and \\[...\\] math spans so nh3 doesn't eat them.

nh3 is an HTML parser; a fragment like \\(y<z\\) reads as a stray tag and is
deleted. Escaping to entities inside math spans keeps the span intact through
sanitization; the browser decodes the entities and KaTeX typesets correctly.
"""

import re

# Non-greedy match of \( ... \) or \[ ... \]; DOTALL so multi-line display math works.
_MATH_SPAN = re.compile(r"\\\((.*?)\\\)|\\\[(.*?)\\\]", re.DOTALL)


def _escape(s):
    return s.replace("<", "&lt;").replace(">", "&gt;")


def escape_math_delimited(text):
    def repl(m):
        if m.group(1) is not None:
            return r"\(" + _escape(m.group(1)) + r"\)"
        return r"\[" + _escape(m.group(2)) + r"\]"

    return _MATH_SPAN.sub(repl, text)
