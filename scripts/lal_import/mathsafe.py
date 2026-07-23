"""Escape <,> inside \\(...\\) and \\[...\\] math spans so nh3 doesn't eat them.

nh3 is an HTML parser; a fragment like \\(y<z\\) reads as a stray tag and is
deleted. Escaping to entities inside math spans keeps the span intact through
sanitization; the browser decodes the entities and KaTeX typesets correctly.
"""

import re

# Non-greedy match of \( ... \) or \[ ... \]; DOTALL so multi-line display math works.
_MATH_SPAN = re.compile(r"\\\((.*?)\\\)|\\\[(.*?)\\\]", re.DOTALL)


# An {align} environment typesets only in DISPLAY mode: KaTeX fails an inline
# \(\begin{align*}...\end{align*}\) with "{align*} can be used only in display
# mode" and renders the source as a red error block. A few sources use that form
# (MathJax, used by the original site, was lenient), so promote them to \[...\].
_INLINE_ALIGN = re.compile(
    r"\\\(\s*(\\begin\{align\*?\}.*?\\end\{align\*?\})\s*\\\)", re.DOTALL
)


def promote_display_math(text):
    """Rewrite an inline \\(...\\) span whose whole content is an {align}
    environment into a display \\[...\\] span, so KaTeX typesets it instead of
    erroring. Ordinary inline/display math is returned unchanged."""
    return _INLINE_ALIGN.sub(lambda m: r"\[" + m.group(1) + r"\]", text)


def _escape(s):
    return s.replace("<", "&lt;").replace(">", "&gt;")


def escape_math_delimited(text):
    def repl(m):
        if m.group(1) is not None:
            return r"\(" + _escape(m.group(1)) + r"\)"
        return r"\[" + _escape(m.group(2)) + r"\]"

    return _MATH_SPAN.sub(repl, text)
