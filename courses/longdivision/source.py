"""Selecting convertible tables out of the legacy LAL lesson HTML."""

from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup

from courses.longdivision.convert import is_long_division
from courses.longdivision.convert import table_to_array
from courses.longdivision.convert import text_key


@dataclass(frozen=True)
class SourceTable:
    """One convertible table in the legacy course.

    `index` counts EVERY <table> in the file, not just the selected ones, so
    `f"{file}#{index}"` names the same table a human counting tables in that
    file would land on.
    """

    file: str
    index: int
    key: str
    latex: str

    @property
    def ident(self):
        return "%s#%d" % (self.file, self.index)  # noqa: UP031 - clearer than nested braces here


def scan(source_dir):
    """Every convertible table under `source_dir`, in file then document order."""
    out = []
    for path in sorted(Path(source_dir).glob("*.html")):
        soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
        for index, table in enumerate(soup.find_all("table")):
            if not is_long_division(table):
                continue
            out.append(
                SourceTable(path.stem, index, text_key(table), table_to_array(table))
            )
    return out
