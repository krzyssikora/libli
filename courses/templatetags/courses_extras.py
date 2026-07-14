"""Template tags and filters rendering content elements and question inputs."""

from decimal import Decimal

from django import template
from django.urls import reverse
from django.utils.html import format_html
from django.utils.html import format_html_join
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _

from courses import switchgate as _switchgate
from courses.models import HtmlElement
from courses.models import QuestionElement
from courses.sanitize import sanitize_html

register = template.Library()


@register.simple_tag(takes_context=True)
def render_element(
    context,
    element,
    feedback_for_pk=None,
    selected_ids=frozenset(),
    submitted_values=None,
    mark_result=None,
    mode="lesson",
    action_url=None,
    feedback_partial="courses/elements/_question_feedback.html",
    quiz_submitted=False,
    locked=False,
    attempts_left=None,
    feedback_html="",
):
    obj = element.content_object
    if obj is None:
        return ""
    if isinstance(obj, HtmlElement):
        pref = context.get("theme_pref")
        theme = context.get("data_theme") if pref in ("light", "dark") else None
        return mark_safe(  # noqa: S308
            obj.render(unit=element.unit, course=element.unit.course, theme=theme)
        )
    if isinstance(obj, QuestionElement):
        return mark_safe(  # noqa: S308 — templates escape user text; correctness never leaks
            obj.render(
                element=element,
                feedback_for_pk=feedback_for_pk,
                selected_ids=selected_ids,
                submitted_values=submitted_values,
                mark_result=mark_result,
                mode=mode,
                action_url=action_url,
                feedback_partial=feedback_partial,
                quiz_submitted=quiz_submitted,
                locked=locked,
                attempts_left=attempts_left,
                feedback_html=feedback_html,
            )
        )
    return mark_safe(obj.render())  # noqa: S308 — each element template escapes its own fields


@register.filter
def sanitize(value):
    """PRESERVED from the existing file — DO NOT drop it: `textelement.html` uses
    `{{ el.body|sanitize }}`. Re-sanitises stored rich text at render
    (defense-in-depth)."""
    return mark_safe(sanitize_html(value))  # noqa: S308 — output is sanitised


@register.simple_tag
def render_fill_blanks(el, submitted_values=None):
    """Render a fill-blank stem: text segments (sanitized HTML) interleaved with
    server-built <input name="blank"> elements (escaped values).

    See courses.fillblank."""
    from courses import fillblank

    return fillblank.render_inputs(el.stem, submitted_values)


@register.simple_tag
def render_drag_selects(el, submitted_values=None):
    """Render a drag-fill stem: text segments interleaved with server-built
    <select name="slot"> elements (escaped). See courses.dnd."""
    from courses import dnd

    return dnd.render_selects(el.stem, dnd.build_pool(el), submitted_values)


@register.simple_tag
def render_match_pairs(el, submitted_values=None):
    """Render a match-pairs widget: an <ol> of (left label, <select name="slot">)
    rows. See courses.dnd."""
    from courses import dnd

    return dnd.render_match_rows(
        list(el.pairs.all()), dnd.build_pool(el), submitted_values
    )


@register.simple_tag
def render_choice_grid(el, submitted_values=None):
    """Render a matrix single-choice widget: a <table> whose header row lists the
    column labels and whose body has one row per statement carrying a radio group
    (name="row_<rowpk>", value="<colpk>"), checked per the positional
    submitted_values list. See courses.models.ChoiceGridQuestionElement."""
    cols = list(el.columns.all())
    rows = list(el.rows.all())
    sv = submitted_values or []
    head = format_html_join("", "<th>{}</th>", ((c.label,) for c in cols))
    body = format_html_join(
        "",
        '<tr><td class="choicegrid__stmt">{}</td>{}</tr>',
        (
            (row.statement, _grid_row_cells(row, cols, sv[i] if i < len(sv) else ""))
            for i, row in enumerate(rows)
        ),
    )
    return format_html(
        '<table class="choicegrid"><thead><tr><th></th>{}</tr></thead>'
        "<tbody>{}</tbody></table>",
        head,
        body,
    )


def _grid_row_cells(row, cols, chosen):
    # chosen is an int col-pk or "" (Task 2). Branch between two format_html templates
    # so `checked` is a literal in the template, not a value arg — NO mark_safe (avoids
    # ruff S308) and NO escape import. Each SafeString cell is spliced into the row
    # template above without re-escaping.
    cells = []
    for c in cols:
        if chosen != "" and chosen == c.pk:
            cells.append(
                format_html(
                    '<td><label><input type="radio" name="row_{}" value="{}" checked>'
                    "</label></td>",
                    row.pk,
                    c.pk,
                )
            )
        else:
            cells.append(
                format_html(
                    '<td><label><input type="radio" name="row_{}" value="{}">'
                    "</label></td>",
                    row.pk,
                    c.pk,
                )
            )
    return format_html_join("", "{}", ((cell,) for cell in cells))


@register.simple_tag
def render_image_selects(el, submitted_values=None):
    """Render the drag-to-image no-JS select list: an <ol> of (badge number,
    <select name="slot">) rows. The pool is built here (mirroring the render_match_pairs
    tag, whose helper render_match_rows this one is modeled on). See courses.dnd."""
    from courses import dnd

    return dnd.render_zone_selects(
        list(el.zones.all()), dnd.build_pool(el), submitted_values
    )


@register.simple_tag
def render_switch_gate(el, eid):
    """Render the inline cycler widget spliced into the stem at its ￿0￿ token.

    See courses.switchgate."""
    check_url = reverse("courses:switchgate_check", args=[eid])
    options_html = format_html_join(
        "",
        '<span class="switchgate__option" hidden>{}</span>',
        ((mark_safe(o),) for o in (el.options or [])),  # noqa: S308 — options sanitized at save()
    )
    hint_id = f"sg-hint-{eid}"
    widget = format_html(
        '<button type="button" class="switchgate__cycler" data-switchgate-cycler '
        'aria-describedby="{hint}">'
        '<span class="switchgate__placeholder">{placeholder}</span>{options}</button>'
        '<span id="{hint}" class="visually-hidden">{describe}</span>'
        '<button type="button" class="switchgate__confirm" hidden>{confirm}</button>'
        '<span class="switchgate__feedback" data-switchgate-feedback hidden>'
        "{tryagain}</span>",
        hint=hint_id,
        placeholder=_("Choose ▾"),
        options=options_html,
        describe=_("Choose an option"),
        confirm=_("Confirm"),
        tryagain=_("Try again"),
    )
    body = _switchgate.render_stem(el.stem, widget)
    return format_html(
        '<div class="switchgate" data-reveal-gate data-switchgate '
        'data-element-pk="{pk}" data-check-url="{url}">{body}</div>',
        pk=eid,
        url=check_url,
        body=body,
    )


@register.simple_tag
def render_switch_grid(el, eid):
    """Render the switch-grid self-check widget: one container per line (static
    lines included), cyclers spliced into each line's token stem.

    See courses.switchgrid."""
    from courses import switchgrid as _switchgrid

    check_url = reverse("courses:switchgrid_check", args=[eid])
    line_html = []
    for i, line in enumerate(el.lines or []):
        widgets = {}
        for j, cyc in enumerate(line.get("cyclers", []) or []):
            options = cyc.get("options", []) or []
            option_spans = format_html_join(
                "",
                '<span class="switchgrid__option{}"{}>{}</span>',
                (
                    (
                        " switchgrid__option--current" if k == 0 else "",
                        "" if k == 0 else mark_safe(" hidden"),
                        mark_safe(o),  # noqa: S308 — options sanitized at save()
                    )
                    for k, o in enumerate(options)
                ),
            )
            widgets[j] = format_html(
                '<button type="button" class="switchgrid__cycler" '
                'data-switchgrid-cycler data-cycler="{j}" '
                'aria-label="{label}">{opts}</button>',
                j=j,
                label=_("Cycle options"),
                opts=option_spans,
            )
        body = _switchgrid.render_stem_multi(line.get("stem", ""), widgets)
        line_html.append(
            format_html(
                '<div class="switchgrid__line" data-line="{i}">{body}</div>',
                i=i,
                body=body,
            )
        )
    lines_joined = mark_safe("".join(line_html))  # noqa: S308 — built from format_html above
    prompt_html = (
        format_html('<p class="switchgrid__prompt">{}</p>', el.prompt)
        if el.prompt
        else ""
    )
    return format_html(
        '<div class="switchgrid" data-switchgrid data-element-pk="{pk}" '
        'data-check-url="{url}">'
        "{prompt}{lines}"
        '<button type="button" class="switchgrid__confirm">{confirm}</button>'
        '<p class="switchgrid__summary" data-switchgrid-summary '
        'data-success-msg="{ok}" data-retry-msg="{retry}" hidden></p>'
        "</div>",
        pk=eid,
        url=check_url,
        prompt=prompt_html,
        lines=lines_joined,
        confirm=_("Check"),
        ok=_("Great!"),
        retry=_("Try again"),
    )


@register.filter(name="marks")
def marks_filter(value):
    """Format a marks Decimal for display: 2dp, trailing zeros + trailing '.' trimmed.

    NOT Decimal.normalize() — that yields scientific notation for whole tens
    (Decimal("10.00").normalize() == Decimal("1E+1")).
    """
    if value is None:
        return "—"
    s = f"{Decimal(value).quantize(Decimal('0.01')):f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


@register.filter
def dictkey(d, key):
    """Look up d[key] in a template (responses keyed by element pk)."""
    return (d or {}).get(key)


@register.filter
def quiz_answer_url(element):
    return reverse(
        "courses:quiz_answer",
        kwargs={
            "slug": element.unit.course.slug,
            "node_pk": element.unit_id,
            "element_pk": element.pk,
        },
    )
