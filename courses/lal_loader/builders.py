"""Turn a parsed element dict into a concrete libli element attached to a unit."""

from decimal import Decimal

from courses.geogebra import canonicalize_geogebra_url
from courses.lal_loader.media import get_or_create_asset
from courses.lal_loader.media import resolve_source
from courses.models import Blank
from courses.models import Choice
from courses.models import ChoiceQuestionElement
from courses.models import Element
from courses.models import FillBlankQuestionElement
from courses.models import FillTableElement
from courses.models import HtmlElement
from courses.models import IframeElement
from courses.models import ImageElement
from courses.models import MathElement
from courses.models import RevealGateElement
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from courses.models import SpoilerElement
from courses.models import SwitchGateElement
from courses.models import SwitchGridElement
from courses.models import TableElement
from courses.models import TabsElement
from courses.models import TextElement
from courses.models import VideoElement


class LoaderError(Exception):
    pass


def build_element(
    course, unit, el, *, source_root, source_dir, allow_html, parent=None, tab_id=""
):
    # A local _attach that injects this call's parent/tab_id, so every branch's
    # `_attach(unit, obj)` places a top-level element by default but a nested
    # TabsElement child (parent + tab_id set) when built recursively.
    def _attach(u, obj):
        return _attach_row(u, obj, parent=parent, tab_id=tab_id)

    etype = el.get("type")
    if el.get("flagged"):
        if not allow_html:
            raise LoaderError(
                f"flagged element ({el.get('reason', 'unmapped')}) in unit "
                f"{unit.pk}; fix the JSON or pass --allow-html"
            )
        obj = HtmlElement.objects.create(html=el.get("raw", ""))
        return _attach(unit, obj)

    if etype == "text":
        return _attach(unit, TextElement.objects.create(body=el["body"]))
    if etype == "math":
        return _attach(unit, MathElement.objects.create(latex=el["latex"]))
    if etype == "spoiler":
        return _attach(
            unit,
            SpoilerElement.objects.create(label=el.get("label", ""), body=el["body"]),
        )
    if etype == "reveal_gate":
        # Group B #1: a "show more" gate. The step content it reveals is emitted
        # as the following sibling elements (the client cascade reveals up to the
        # next gate); this builds only the gate divider itself.
        return _attach(
            unit, RevealGateElement.objects.create(label=el.get("label", "")[:120])
        )
    if etype == "tabs":
        # Group B #6: a tabbed container. Build the tabs join row first, then
        # recurse each tab's children under it (parent=join, tab_id=tab's id).
        tabs_meta = [{"id": t["id"], "label": t["label"]} for t in el["tabs"]]
        obj = TabsElement.objects.create(
            data=TabsElement.normalize_labels_and_ids({"tabs": tabs_meta})
        )
        join = Element.objects.create(
            unit=unit, parent=parent, tab_id=tab_id, content_object=obj
        )
        for t in el["tabs"]:
            for child in t.get("elements", []):
                build_element(
                    course,
                    unit,
                    child,
                    source_root=source_root,
                    source_dir=source_dir,
                    allow_html=allow_html,
                    parent=join,
                    tab_id=t["id"],
                )
        return obj
    if etype == "fillblank":
        # Group B #5: an inline fill-in-the-blank self-check. The stem keeps its
        # sentinel blank tokens; non-token segments are sanitized here.
        from courses.switchgrid import sanitize_stem_segments

        q = FillBlankQuestionElement.objects.create(
            stem=sanitize_stem_segments(el.get("stem", ""))
        )
        for i, alts in enumerate(el.get("blanks", [])):
            Blank.objects.create(question=q, accepted="\n".join(alts), order=i)
        return _attach(unit, q)
    if etype == "fill_table":
        # Group B #4: a fill-in-the-blanks self-check table (input cells ->
        # accepted-answer cells). normalize_data sanitizes static cells.
        return _attach(
            unit,
            FillTableElement.objects.create(
                data=FillTableElement.normalize_data(el["data"])
            ),
        )
    if etype == "switch_gate":
        # Group B #2: a cycler-triggered reveal gate. The stem's sentinel token
        # marks the cycler position; segments are sanitized here (the form's
        # clean()-time sanitize is bypassed by the import).
        from courses.switchgrid import sanitize_stem_segments

        return _attach(
            unit,
            SwitchGateElement.objects.create(
                stem=sanitize_stem_segments(el.get("stem", "")),
                options=el.get("options", []),
                answer=int(el.get("answer", 0)),
            ),
        )
    if etype == "switch_grid":
        # Group B #3: a confirmed switch grid. Sanitize each line's stem segments
        # (cycler options are sanitized by SwitchGridElement.save).
        from courses.switchgrid import sanitize_stem_segments

        lines = [
            {
                "stem": sanitize_stem_segments(ln.get("stem", "")),
                "cyclers": ln.get("cyclers", []),
            }
            for ln in el.get("lines", [])
        ]
        return _attach(
            unit,
            SwitchGridElement.objects.create(prompt=el.get("prompt", ""), lines=lines),
        )
    if etype == "iframe":
        url = canonicalize_geogebra_url(el["url"])
        return _attach(
            unit, IframeElement.objects.create(url=url, title=el.get("title", ""))
        )
    if etype == "image":
        path = resolve_source(source_root, source_dir, el["media_src"])
        asset = get_or_create_asset(course, "image", path)
        return _attach(
            unit,
            ImageElement.objects.create(
                media=asset,
                alt=el.get("alt", ""),
                figcaption=el.get("figcaption", ""),
            ),
        )
    if etype == "video":
        path = resolve_source(source_root, source_dir, el["media_src"])
        asset = get_or_create_asset(course, "video", path)
        return _attach(unit, VideoElement.objects.create(media=asset))
    if etype == "table":
        return _attach(
            unit,
            TableElement.objects.create(data=TableElement.normalize_data(el["data"])),
        )
    if etype == "choice":
        # Validate lengths BEFORE any create, so we fail loud with LoaderError
        # (not a mid-transaction DB DataError) and leave no orphan question.
        for c in el["choices"]:
            if len(c["text"]) > 500 or len(c.get("feedback", "")) > 500:
                raise LoaderError(
                    f"choice text/feedback exceeds 500 chars in unit {unit.pk}; "
                    "shorten or split the option (Choice fields are varchar(500))"
                )
        q = ChoiceQuestionElement.objects.create(
            stem=el["stem"],
            multiple=bool(el.get("multiple")),
            **_max_marks_kwargs(el),
        )
        for c in el["choices"]:
            Choice.objects.create(
                question=q,
                text=c["text"],
                is_correct=bool(c.get("is_correct")),
                feedback=c.get("feedback", ""),
            )
        return _attach(unit, q)
    if etype == "numeric":
        return _attach(
            unit,
            ShortNumericQuestionElement.objects.create(
                stem=el["stem"],
                value=Decimal(el["value"]),
                tolerance=Decimal(el.get("tolerance", "0")),
                **_max_marks_kwargs(el),
            ),
        )
    if etype == "shorttext":
        return _attach(
            unit,
            ShortTextQuestionElement.objects.create(
                stem=el["stem"],
                accepted="\n".join(el["accepted"]),
                case_sensitive=bool(el.get("case_sensitive")),
                **_max_marks_kwargs(el),
            ),
        )
    raise LoaderError(f"unknown element type {etype!r} in unit {unit.pk}")


def _max_marks_kwargs(el):
    # "points" (from the quiz `(N)` DSL) sets max_marks; absent -> model default.
    points = el.get("points")
    if points is None:
        return {}
    return {"max_marks": Decimal(points)}


def _attach_row(unit, obj, *, parent=None, tab_id=""):
    Element.objects.create(unit=unit, parent=parent, tab_id=tab_id, content_object=obj)
    return obj
