# courses/htmlsandbox.py
"""Assemble the sandboxed srcdoc for HtmlElement.

Containment is the iframe's opaque origin (sandbox="allow-scripts", NO
allow-same-origin) — not sanitization. See the 1b-iii design spec. The string
returned here is the raw document; the element template attribute-escapes it
into srcdoc="{{ doc }}".
"""

import base64
import re
from functools import lru_cache
from pathlib import Path

from django.contrib.staticfiles import finders

MIN_IFRAME_HEIGHT = 40
MAX_IFRAME_HEIGHT = 20000

# Baseline surface for the sandbox: an explicit light background + dark text so
# light-designed author content is never rendered dark-on-dark when the app is in
# dark mode (the iframe is otherwise transparent). Author CSS can override it.
_BASE_STYLE = "html,body{background:#fff;color:#111}"

# Colour tokens only: everything in tokens.css that is NOT one of these is a colour.
_NON_COLOUR_TOKEN_PREFIXES = ("--radius-", "--shadow-", "--font-", "--space-")
_NON_COLOUR_TOKEN_NAMES = ("--heading-letter-spacing",)

# Sets documentElement's data-theme from a parent postMessage.
# Sibling of _RESIZE_REPORTER.
_THEME_LISTENER = (
    "window.addEventListener('message',function(e){"
    "var d=e.data;"
    "if(d&&d.type==='libli:htmlel:theme'&&(d.theme==='light'||d.theme==='dark')){"
    "document.documentElement.setAttribute('data-theme',d.theme);}});"
)


def _colour_decls(block):
    # Strip CSS comments FIRST. tokens.css introduces each group with a comment on
    # the line above its first token; without this, that comment + the first token
    # land in one ";"-segment that fails the "--" check and the token is dropped
    # (would silently lose --brand-primary, --primary, --surface-base, --success, ...).
    block = re.sub(r"/\*.*?\*/", "", block, flags=re.S)
    out = []
    for decl in block.split(";"):
        decl = decl.strip()
        if not decl.startswith("--"):
            continue
        name = decl.split(":", 1)[0].strip()
        if (
            name.startswith(_NON_COLOUR_TOKEN_PREFIXES)
            or name in _NON_COLOUR_TOKEN_NAMES
        ):
            continue
        value = decl.split(":", 1)[1].strip()  # normalize post-colon whitespace so the
        out.append(f"{name}:{value};")  # emitted block matches "name:value" checks
    return "".join(out)


@lru_cache(maxsize=1)
def _theme_tokens():
    """Emit the app's colour tokens (from tokens.css) in the four-part theme pattern.

    Read-once/​memoised, mirroring _katex_assets. Single source of truth =
    tokens.css, so the sandbox palette can never drift from the app. tokens.css
    declares light on :root and dark on [data-theme="dark"]; brand inputs live
    only on :root, so the dark arms simply omit them and they inherit their
    light value (exactly as the app does)."""
    css = Path(finders.find("core/css/tokens.css")).read_text(encoding="utf-8")

    def _block(selector_re):
        m = re.search(selector_re + r"\s*\{([^}]*)\}", css)
        return m.group(1) if m else ""

    light = _colour_decls(_block(r":root"))
    dark = _colour_decls(_block(r'\[data-theme="dark"\]'))
    return (
        f":root{{{light}}}"
        f"@media(prefers-color-scheme:dark){{:root{{{dark}}}}}"
        f':root[data-theme="dark"]{{{dark}}}'
        f':root[data-theme="light"]{{{light}}}'
    )


# KaTeX auto-render: \(..\) inline, \[..\] display. The doubled backslashes here
# emit the JS-string literal "\\(" (a JS string containing the two chars \( ).
_AUTORENDER_CALL = (
    "renderMathInElement(document.body,{delimiters:["
    '{left:"\\\\(",right:"\\\\)",display:false},'
    '{left:"\\\\[",right:"\\\\]",display:true}],throwOnError:false});'
)

# In-sandbox reporter: posts the height contract upward. Measures body (not
# documentElement, which would feed back from the applied iframe height).
# The message listener answers the parent's height *request*, closing the
# load-order race where the parent's (bottom-of-body) listener registers after
# our one-shot load/RO/fonts posts have already fired and been dropped.
_RESIZE_REPORTER = (
    "(function(){"
    "function r(){var b=document.body;if(!b)return;"
    "var h=Math.max(b.scrollHeight,Math.ceil(b.getBoundingClientRect().height));"
    'parent.postMessage({type:"libli:htmlel:height",h:h},"*");}'
    'window.addEventListener("message",function(e){'
    'if(e.data&&e.data.type==="libli:htmlel:req")r();});'
    "if(window.ResizeObserver){new ResizeObserver(r).observe(document.body);}"
    "window.addEventListener('load',r);"
    "if(document.fonts&&document.fonts.ready){document.fonts.ready.then(r);}"
    "r();})();"
)


def has_math_delimiters(html):
    """True iff the raw html contains an inline \\( or a display \\[ delimiter."""
    html = html or ""
    return ("\\(" in html) or ("\\[" in html)


def _csp(origin):
    return (
        "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
        f"img-src {origin} data:; font-src {origin} data:; connect-src 'none'"
    )


@lru_cache(maxsize=1)
def _katex_assets():
    """Read + cache vendored KaTeX (read-once via lazy memoization, satisfying the
    spec's "read once, never per render" intent).

    Fonts are INLINED as data: URIs rather than referenced by URL. The sandbox iframe
    is sandbox="allow-scripts" (NO allow-same-origin), so its document has an opaque
    NULL origin; a font fetch from there to ANY http(s) URL — even the sandbox origin
    itself — is cross-origin, and the browser CORS-blocks it because Django static
    serves no Access-Control-Allow-Origin header. (Previously these were rewritten to
    absolute origin URLs, which 404-dodged the <base> but then CORS-failed at runtime,
    breaking all in-sandbox math fonts.) data: URIs sidestep CORS entirely and are
    permitted by the CSP's `font-src ... data:`.

    Only the woff2 face is inlined — every browser that runs the sandbox supports it —
    and the woff/ttf fallbacks are dropped, keeping the inlined payload (~0.3 MB) as
    small as possible. The result is origin-independent, so the cache holds one
    entry."""
    css = Path(finders.find("courses/vendor/katex/katex.min.css")).read_text(
        encoding="utf-8"
    )
    katex_js = Path(finders.find("courses/vendor/katex/katex.min.js")).read_text(
        encoding="utf-8"
    )
    autorender_js = Path(
        finders.find("courses/vendor/katex/contrib/auto-render.min.js")
    ).read_text(encoding="utf-8")

    # Drop the woff + ttf fallbacks, leaving only the woff2 url() in each src list.
    css = re.sub(
        r',url\(fonts/[^)]+\.woff\) format\("woff"\),'
        r'url\(fonts/[^)]+\.ttf\) format\("truetype"\)',
        "",
        css,
    )

    def _inline(m):
        data = Path(
            finders.find("courses/vendor/katex/fonts/" + m.group(1))
        ).read_bytes()
        b64 = base64.b64encode(data).decode("ascii")
        return f"url(data:font/woff2;base64,{b64})"

    css = re.sub(r"url\(fonts/([^)]+\.woff2)\)", _inline, css)
    return css, katex_js, autorender_js


def build_srcdoc(html, css, js, seed, *, origin, theme=None):
    html = html or ""
    seed = (seed or "").strip()  # a JS object literal -> exposed as window.SEED
    math = has_math_delimiters(html)
    html_open = (
        f'<html data-theme="{theme}">' if theme in ("light", "dark") else "<html>"
    )
    parts = [
        "<!doctype html>" + html_open + "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f'<meta http-equiv="Content-Security-Policy" content="{_csp(origin)}">',
        f'<base href="{origin}/">',
        f"<style>{_theme_tokens()}</style>",  # tokens: after <base>, before base style
        f"<style>{_BASE_STYLE}</style>",
    ]
    if math:
        katex_css, katex_js, autorender_js = _katex_assets()
        parts.append(f"<style>{katex_css}</style>")
    if css:
        parts.append(f"<style>{css}</style>")
    parts.append("</head><body>")
    parts.append(html)
    if seed:
        # seed first: a JS object literal exposed as window.SEED for the course JS.
        parts.append(f"<script>window.SEED = ({seed});</script>")
    if js:
        parts.append(f"<script>{js}</script>")  # course JS: reads vars
    if math:
        parts.append(f"<script>{katex_js}</script>")
        parts.append(f"<script>{autorender_js}</script>")
        parts.append(f"<script>{_AUTORENDER_CALL}</script>")
    parts.append(f"<script>{_THEME_LISTENER}</script>")
    parts.append(f"<script>{_RESIZE_REPORTER}</script>")
    parts.append("</body></html>")
    return "".join(parts)
