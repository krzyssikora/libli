import csv

from django.http import HttpResponse
from django.utils.text import slugify
from django.utils.translation import gettext as _

_DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _sanitize_text_cell(value):
    """Neutralise CSV/XLSX formula injection: prefix a ' when a text token starts
    with a formula trigger. Numeric cells never pass through here."""
    text = "" if value is None else str(value)
    if text and text[0] in _DANGEROUS_PREFIXES:
        return "'" + text
    return text


def build_filename(slug, shape, mode, numbers_only, today, ext):
    """{slug}-{shape}-{mode? matrix only}-{numbers? quiz+numbers_only}-{ISO date}.{ext}.

    Filename shape: matrix mode is only appended for "matrix" shape; the
    "numbers" marker is only appended for "quiz" shape with numbers_only set.
    """
    parts = [slugify(slug) or "export", shape]
    if shape == "matrix":
        parts.append(mode)
    if shape == "quiz" and numbers_only:
        parts.append("numbers")
    parts.append(today.isoformat())
    return f"{'-'.join(parts)}.{ext}"


def _fmt_cell(value, kind):
    """Format a data/summary value by column kind for text output (CSV/HTML)."""
    if value is None:
        return ""
    if kind == "percent":
        return f"{value}%"
    if isinstance(value, str):  # a marker (—/…/R) — our own constant, safe
        return value
    return str(value)  # Decimal / int score


def to_csv(table, filename):
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    resp.write(chr(0xFEFF))  # UTF-8 BOM for Excel (unambiguous — no invisible glyph)
    writer = csv.writer(resp)
    cols = table["columns"]
    tk = table["total_kind"]

    writer.writerow([_sanitize_text_cell(table["title"])])
    writer.writerow([_sanitize_text_cell(table["subtitle"])])
    writer.writerow([])
    writer.writerow(
        [_("Name"), _("Username")]
        + [_sanitize_text_cell(c["label"]) for c in cols]
        + [_sanitize_text_cell(table["total_label"])]
    )
    meta = table["meta_row"]
    if meta:
        writer.writerow(
            [
                _sanitize_text_cell(meta["label"]),
                "",
            ]  # label in Name col, Username blank
            + [
                _fmt_cell(v, c["kind"])
                for v, c in zip(meta["values"], cols, strict=True)
            ]
            + [_fmt_cell(meta["total"], tk)]
        )
    for row in table["rows"]:
        writer.writerow(
            [_sanitize_text_cell(row["name"]), _sanitize_text_cell(row["username"])]
            + [_fmt_cell(v, c["kind"]) for v, c in zip(row["cells"], cols, strict=True)]
            + [_fmt_cell(row["total"], tk)]
        )
    for frow in table["footer"]:
        writer.writerow(
            [_sanitize_text_cell(frow["label"]), ""]
            + [
                _fmt_cell(v, c["kind"])
                for v, c in zip(frow["values"], cols, strict=True)
            ]
            + [_fmt_cell(frow["total"], tk)]
        )
    return resp
