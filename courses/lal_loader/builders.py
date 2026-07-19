"""Turn a parsed element dict into a concrete libli element attached to a unit."""

from decimal import Decimal

from courses.geogebra import canonicalize_geogebra_url
from courses.lal_loader.media import get_or_create_asset
from courses.lal_loader.media import resolve_source
from courses.models import Choice
from courses.models import ChoiceQuestionElement
from courses.models import Element
from courses.models import HtmlElement
from courses.models import IframeElement
from courses.models import ImageElement
from courses.models import MathElement
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from courses.models import SpoilerElement
from courses.models import TableElement
from courses.models import TextElement
from courses.models import VideoElement


class LoaderError(Exception):
    pass


def build_element(course, unit, el, *, source_root, source_dir, allow_html):
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


def _attach(unit, obj):
    Element.objects.create(unit=unit, content_object=obj)
    return obj
