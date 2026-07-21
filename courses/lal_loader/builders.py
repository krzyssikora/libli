"""Turn a parsed element dict into a concrete libli element attached to a unit."""

from decimal import Decimal

from courses.geogebra import canonicalize_geogebra_url
from courses.lal_loader.media import get_or_create_asset
from courses.lal_loader.media import resolve_source
from courses.models import Blank
from courses.models import Choice
from courses.models import ChoiceGridQuestionElement
from courses.models import ChoiceQuestionElement
from courses.models import Element
from courses.models import FillBlankQuestionElement
from courses.models import FillGateElement
from courses.models import FillTableElement
from courses.models import GridColumn
from courses.models import GridRow
from courses.models import HtmlElement
from courses.models import IframeElement
from courses.models import ImageElement
from courses.models import MathElement
from courses.models import MultiGridColumn
from courses.models import MultiGridQuestionElement
from courses.models import MultiGridRow
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


# The LAL parser emits "fillblank"; the canonical/transfer key is "fill_blank".
# Every other interactive/static parser type key already equals its canonical key.
_PARSER_TO_CANONICAL = {"fillblank": "fill_blank"}


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
        if "elements" in el:  # nested path — key presence, NOT truthiness
            obj = SpoilerElement.objects.create(label=el.get("label", "")[:120])
            join = Element.objects.create(
                unit=unit, parent=parent, tab_id=tab_id, content_object=obj
            )
            from courses.builder import SPOILER_CHILD_TYPES

            for child in el["elements"]:
                ctype = child.get("type")
                # Enforce the same allowlist resolve_scope() (the editor path)
                # enforces: permits static leaves AND interactive leaves (reveal/
                # fill/switch gate, switch grid, fill blank -- normalized to their
                # canonical key via _PARSER_TO_CANONICAL), rejects NATIVE containers
                # (tabs/two_column/nested spoiler) and question types the parser's
                # no-nest-container mode never emits but malformed JSON could carry.
                # A FLAGGED child is exempt: it follows build_element's own flagged
                # branch below, which honours --allow-html (HtmlElement under the
                # flag, LoaderError without) exactly as a top-level flagged element
                # does — so an unmappable block inside a spoiler isn't newly
                # hard-blocked relative to the top level.
                canonical = _PARSER_TO_CANONICAL.get(ctype, ctype)
                if not child.get("flagged") and canonical not in SPOILER_CHILD_TYPES:
                    raise LoaderError(
                        f"child ({ctype}) not allowed inside a spoiler in unit "
                        f"{unit.pk}; spoilers hold only leaf types "
                        f"({', '.join(sorted(SPOILER_CHILD_TYPES))})"
                    )
                build_element(
                    course,
                    unit,
                    child,
                    source_root=source_root,
                    source_dir=source_dir,
                    allow_html=allow_html,
                    parent=join,
                    tab_id=SpoilerElement.SLOT_ID,
                )
            return obj
        return _attach(
            unit,
            SpoilerElement.objects.create(
                label=el.get("label", "")[:120],  # varchar(120); parser labels uncapped
                body=el["body"],
            ),
        )
    if etype == "reveal_gate":
        # Group B #1: a "show more" gate. The step content it reveals is emitted
        # as the following sibling elements (the client cascade reveals up to the
        # next gate); this builds only the gate divider itself.
        return _attach(
            unit, RevealGateElement.objects.create(label=el.get("label", "")[:120])
        )
    if etype == "choice_grid":
        # Group B #7: matrix single-choice. Columns are saved first so each row's
        # correct_column FK resolves (mirrors the transfer importer).
        q = ChoiceGridQuestionElement.objects.create()
        cols = [
            GridColumn.objects.create(question=q, label=c[:500]) for c in el["columns"]
        ]
        for r in el["rows"]:
            idx = r["correct"] if 0 <= r["correct"] < len(cols) else 0
            GridRow.objects.create(
                question=q, statement=r["statement"][:500], correct_column=cols[idx]
            )
        return _attach(unit, q)
    if etype == "multi_grid":
        # Group B #9: multi-select grid. Columns are saved first so each row's
        # correct_columns M2M can reference them; correct is a *set* of column
        # indices (all-or-nothing per row).
        q = MultiGridQuestionElement.objects.create()
        cols = [
            MultiGridColumn.objects.create(question=q, label=c[:500])
            for c in el["columns"]
        ]
        for r in el["rows"]:
            row = MultiGridRow.objects.create(
                question=q, statement=r["statement"][:500]
            )
            row.correct_columns.set(
                [cols[i] for i in r["correct"] if 0 <= i < len(cols)]
            )
        return _attach(unit, q)
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
    if etype == "fill_gate":
        # Group B #8: "Fill in & confirm" gate. Stem keeps its sentinel blank
        # token(s); a correct answer reveals the following sibling elements.
        from courses.switchgrid import sanitize_stem_segments

        return _attach(
            unit,
            FillGateElement.objects.create(
                stem=sanitize_stem_segments(el.get("stem", "")),
                answers=el.get("answers", []),
            ),
        )
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
        # accepted-answer cells). Image cells (Task 4's parser output) carry a
        # media_src path that must be resolved to a MediaAsset pk before
        # normalize_data (which only accepts an already-resolved int `media`
        # and otherwise degrades the cell to empty static) sanitizes the rest.
        data = el["data"]
        rows = data.get("cells") if isinstance(data.get("cells"), list) else []
        resolved_rows = []
        for row in rows:
            resolved_row = []
            for cell in row if isinstance(row, list) else []:
                if isinstance(cell, dict) and cell.get("kind") == "image":
                    path = resolve_source(source_root, source_dir, cell["media_src"])
                    asset = get_or_create_asset(course, "image", path)
                    resolved_row.append(
                        {
                            "kind": "image",
                            "media": asset.pk,
                            "alt": cell.get("alt", ""),
                            **{k: cell[k] for k in ("halign", "valign") if k in cell},
                        }
                    )
                else:
                    resolved_row.append(cell)
            resolved_rows.append(resolved_row)
        resolved_data = {**data, "cells": resolved_rows}
        return _attach(
            unit,
            FillTableElement.objects.create(
                data=FillTableElement.normalize_data(resolved_data)
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
