"""Template tags and filters rendering content elements and question inputs."""

from decimal import Decimal

from django import template
from django.urls import reverse
from django.utils.html import format_html
from django.utils.html import format_html_join
from django.utils.html import strip_tags
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _

from courses import guessnumber
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
    return mark_safe(  # noqa: S308 — each element template escapes its own fields
        obj.render(
            element=element,
            state=context.get("element_state"),
            slug=context.get("slug"),
            node_pk=context.get("node_pk"),
        )
    )


@register.filter
def sanitize(value):
    """PRESERVED from the existing file — DO NOT drop it: `textelement.html` uses
    `{{ el.body|sanitize }}`. Re-sanitises stored rich text at render
    (defense-in-depth)."""
    return mark_safe(sanitize_html(value))  # noqa: S308 — output is sanitised


@register.simple_tag
def render_fill_blanks(el, submitted_values=None, locked=False):
    """Render a fill-blank stem: text segments (sanitized HTML) interleaved with
    server-built <input name="blank"> elements (escaped values). `locked=True`
    renders the read-only answered state (restore path). See courses.fillblank."""
    from courses import fillblank

    return fillblank.render_inputs(el.stem, submitted_values, locked=locked)


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
def render_multigrid(el, submitted_values=None):
    """Render a multi-select grid: a <table> whose header lists the column labels
    and whose body has one row per statement carrying a checkbox group
    (name="row_<rowpk>", value="<colpk>"), each checked when its col pk is in that
    row's positional chosen-pk list. See courses.models.MultiGridQuestionElement."""
    cols = list(el.columns.all())
    rows = list(el.rows.all())
    sv = submitted_values or []
    head = format_html_join("", "<th>{}</th>", ((c.label,) for c in cols))
    body = format_html_join(
        "",
        '<tr><td class="multigrid__stmt">{}</td>{}</tr>',
        (
            (
                row.statement,
                _multigrid_row_cells(row, cols, sv[i] if i < len(sv) else []),
            )
            for i, row in enumerate(rows)
        ),
    )
    return format_html(
        '<table class="multigrid"><thead><tr><th></th>{}</tr></thead>'
        "<tbody>{}</tbody></table>",
        head,
        body,
    )


def _multigrid_row_cells(row, cols, chosen):
    # chosen is a list of chosen col-pks (Task 2). Branch between two format_html
    # templates so `checked` is a literal, not a value arg — no mark_safe, no escape.
    chosen_set = set(chosen or [])
    cells = []
    for c in cols:
        if c.pk in chosen_set:
            cells.append(
                format_html(
                    "<td><label>"
                    '<input type="checkbox" name="row_{}" value="{}" checked>'
                    "</label></td>",
                    row.pk,
                    c.pk,
                )
            )
        else:
            cells.append(
                format_html(
                    '<td><label><input type="checkbox" name="row_{}" value="{}">'
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
def render_switch_gate(el, eid, mine=None, mine_json="{}", save_url=""):
    """Render the "Choose & confirm" cycler. When mine.open (restore path), the
    correct option is shown, the cycler disabled, Confirm omitted, and
    switchgate--done added -- the server half of the answered appearance
    (switchgate.js typesets its math on boot). mine_json is passed pre-serialized
    from the template (courses_extras.py has no json import). See courses.switchgate."""
    check_url = reverse("courses:switchgate_check", args=[eid])
    is_open = bool((mine or {}).get("open"))  # null-safe: mine may be None
    answer = el.answer
    # Bounds-safe: un-hide the option where k == answer; an out-of-range answer
    # (a transfer/import could persist one) leaves ALL options hidden, never an
    # IndexError. NEVER index options[answer].
    option_spans = format_html_join(
        "",
        '<span class="switchgate__option"{}>{}</span>',
        (
            (
                "" if (is_open and k == answer) else mark_safe(" hidden"),
                mark_safe(o),  # noqa: S308 — options sanitized at save()
            )
            for k, o in enumerate(el.options or [])
        ),
    )
    hint_id = f"sg-hint-{eid}"
    cycler_disabled = mark_safe(" disabled") if is_open else ""
    ph_hidden = mark_safe(" hidden") if is_open else ""
    confirm_html = (
        ""
        if is_open
        else format_html(
            '<button type="button" class="switchgate__confirm" hidden>{}</button>',
            _("Confirm"),
        )
    )
    widget = format_html(
        '<button type="button" class="switchgate__cycler" data-switchgate-cycler '
        'aria-describedby="{hint}"{disabled}>'
        '<span class="switchgate__placeholder"{ph}>{placeholder}</span>{options}'
        "</button>"
        '<span id="{hint}" class="visually-hidden">{describe}</span>'
        "{confirm}"
        '<span class="switchgate__feedback" data-switchgate-feedback hidden>'
        "{tryagain}</span>",
        hint=hint_id,
        disabled=cycler_disabled,
        ph=ph_hidden,
        placeholder=_("Choose ▾"),
        options=option_spans,
        describe=_("Choose an option"),
        confirm=confirm_html,
        tryagain=_("Try again"),
    )
    body = _switchgate.render_stem(el.stem, widget)
    done = mark_safe(" switchgate--done") if is_open else ""
    return format_html(
        '<div class="switchgate{done}" data-reveal-gate data-switchgate '
        'data-element-pk="{pk}" data-check-url="{url}" '
        'data-state="{state}" data-state-url="{save_url}">{body}</div>',
        done=done,
        pk=eid,
        url=check_url,
        state=mine_json,
        save_url=save_url,
        body=body,
    )


@register.simple_tag
def render_guess_number(el, eid, mine=None, mine_json="{}", save_url=""):
    """Render the numeric input spliced into the stem at its U+FFFF-delimited token.

    NO <form>: implicit submission cannot be suppressed without JS, and a stray
    Enter reload would wipe reveal.js's in-memory cascade state (it persists
    nothing), re-hiding a gated element. Enter comes from a keydown listener
    instead. The <div> WRAPS the stem; only inline markup is spliced, because
    the parser hoists block elements out of an enclosing <p>.

    mine_json is passed pre-serialized from the template (courses_extras.py has
    no json import). When mine.done (restore path), the input shows
    el.canonical_target readonly + is-correct, Check is omitted entirely, and
    the success block is un-hidden -- reproducing guessnumber.js's correct-
    branch appearance server-side (its boot skip-arm does not re-run this).
    See courses.guessnumber."""
    check_url = reverse("courses:guessnumber_check", args=[eid])
    is_done = bool((mine or {}).get("done"))
    if is_done:
        widget = format_html(
            '<input data-guess-input type="text" inputmode="decimal" '
            'aria-label="{}" value="{}" readonly class="is-correct">',
            _("Your answer"),
            el.canonical_target,
        )
    else:
        widget = format_html(
            '<input data-guess-input type="text" inputmode="decimal" '
            'aria-label="{}"><button data-guess-check type="button" hidden>{}</button>',
            _("Your answer"),
            _("Check"),
        )
    body = guessnumber.render_stem(el.stem, widget)
    msg = el.success_message or ""
    has_text = bool(strip_tags(msg).strip())
    success = mark_safe(msg) if has_text else format_html("{}", _("Correct!"))  # noqa: S308 — sanitized at save()
    done_class = mark_safe(" guessnumber--done") if is_done else ""
    success_hidden = "" if is_done else mark_safe(" hidden")
    return format_html(
        '<div class="guessnumber{}" data-guessnumber data-element-pk="{}" '
        'data-check-url="{}" data-msg-high="{}" data-msg-low="{}" '
        'data-state="{}" data-state-url="{}">{}'
        '<div data-guess-live aria-live="polite">'
        "<p data-guess-hint hidden></p>"
        "<div data-guess-success{}>{}</div></div></div>",
        done_class,
        eid,
        check_url,
        _("The number is too big, try again."),
        _("The number is too small, try again."),
        mine_json,
        save_url,
        body,
        success_hidden,
        success,
    )


@register.simple_tag
def render_switch_grid(el, eid, mine=None, mine_json="{}", save_url=""):
    """Render the switch-grid self-check widget: one container per line (static
    lines included), cyclers spliced into each line's token stem.

    mine_json is passed pre-serialized from the template (courses_extras.py has no
    json import). When mine.done (restore path), each cycler shows its correct
    option -- BOUNDS-SAFE: compared by index equality, never options[answer]
    indexing, so an out-of-range author-set answer (a stray transfer/import) un-
    hides nothing rather than 500ing -- carries switchgrid--locked + disabled;
    the Confirm button is omitted; and the summary <p> is un-hidden with
    switchgrid--success and the success text, reproducing lock()+summarize(root,
    true). See courses.switchgrid."""
    from courses import switchgrid as _switchgrid

    check_url = reverse("courses:switchgrid_check", args=[eid])
    is_done = bool((mine or {}).get("done"))
    line_html = []
    for i, line in enumerate(el.lines or []):
        widgets = {}
        for j, cyc in enumerate(line.get("cyclers", []) or []):
            options = cyc.get("options", []) or []
            answer = cyc.get("answer")
            valid_answer = (
                isinstance(answer, int)
                and not isinstance(answer, bool)
                and 0 <= answer < len(options)
            )
            shown = (answer if valid_answer else -1) if is_done else 0
            option_spans = format_html_join(
                "",
                '<span class="switchgrid__option{}"{}>{}</span>',
                (
                    (
                        " switchgrid__option--current" if k == shown else "",
                        "" if k == shown else mark_safe(" hidden"),
                        mark_safe(o),  # noqa: S308 — options sanitized at save()
                    )
                    for k, o in enumerate(options)
                ),
            )
            cyc_locked = " switchgrid--locked" if is_done else ""
            cyc_disabled = mark_safe(" disabled") if is_done else ""
            widgets[j] = format_html(
                '<button type="button" class="switchgrid__cycler{locked}" '
                'data-switchgrid-cycler data-cycler="{j}" '
                'aria-label="{label}"{disabled}>{opts}</button>',
                locked=cyc_locked,
                j=j,
                label=_("Cycle options"),
                disabled=cyc_disabled,
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
    confirm_html = (
        ""
        if is_done
        else format_html(
            '<button type="button" class="switchgrid__confirm">{}</button>',
            _("Check"),
        )
    )
    summary_class = mark_safe(" switchgrid--success") if is_done else ""
    summary_hidden = "" if is_done else mark_safe(" hidden")
    summary_text = _("Great!") if is_done else ""
    return format_html(
        '<div class="switchgrid" data-switchgrid data-element-pk="{pk}" '
        'data-check-url="{url}" data-state="{state}" data-state-url="{save_url}">'
        "{prompt}{lines}"
        "{confirm}"
        '<p class="switchgrid__summary{summary_class}" data-switchgrid-summary '
        'data-success-msg="{ok}" data-retry-msg="{retry}"{summary_hidden}>'
        "{summary_text}</p>"
        "</div>",
        pk=eid,
        url=check_url,
        state=mine_json,
        save_url=save_url,
        prompt=prompt_html,
        lines=lines_joined,
        confirm=confirm_html,
        summary_class=summary_class,
        ok=_("Great!"),
        retry=_("Try again"),
        summary_hidden=summary_hidden,
        summary_text=summary_text,
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
