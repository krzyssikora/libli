from django import forms
from django.utils.safestring import mark_safe


class CodeTextarea(forms.Textarea):
    """A plain-monospace code field: the standard textarea wrapped in the
    ``.code-field`` shell (header label + line-number gutter) that batch 4's
    JS enhances (gutter sync + Tab-to-indent). No syntax highlighting.

    With JS off it degrades to the styled monospace textarea — the wrapper and
    gutter are inert. The ``data-code-field`` hook is what the JS module targets.
    """

    def __init__(self, attrs=None):
        base = {"spellcheck": "false", "autocomplete": "off", "wrap": "off"}
        if attrs:
            base.update(attrs)
        super().__init__(attrs=base)

    def render(self, name, value, attrs=None, renderer=None):
        textarea = super().render(name, value, attrs=attrs, renderer=renderer)
        return mark_safe(  # noqa: S308
            '<div class="code-field" data-code-field>'
            '<div class="code-field__gutter" aria-hidden="true"></div>'
            f'<div class="code-field__area">{textarea}</div>'
            "</div>"
        )
