"""§7's gate-detection query must stay ContentType-free.

A runtime query-count test cannot guard this and should not be re-added: the
mutant's extra get_for_model(FillTableElement) is gated on has_fill_table, not
on `gate`, so an A/B between a gated and an ungated fill-table unit pays
identical cost in both arms and the delta is 0 in every configuration.
ContentType.objects.clear_cache() does not rescue it either --
build_lesson_context's prefetch_related("content_object") re-warms the cache
in-request, and Django's _add_to_cache populates the (app_label, model) key
alongside the id key. tests/test_html_element.py does not guard it either: its
fixtures hold only HtmlElements, so has_fill_table is False and the term
short-circuits before the mutant is reached.
"""

from pathlib import Path

SRC = Path("courses/views.py").read_text(encoding="utf-8")


def _gate_term(src):
    start = src.index("has_filltable_gate = ")
    return src[start : src.index("has_reveal_gate = ", start)]


def test_gate_query_uses_the_object_id_shape():
    term = _gate_term(SRC)
    assert "object_id" in term
    assert "pk__in" in term
    assert "data__gate=True" in term


def test_gate_query_does_not_use_a_reverse_generic_relation():
    assert "elements__unit=" not in _gate_term(SRC)


def test_has_fill_table_is_assigned_exactly_once():
    # Step 4(a) MOVES has_fill_table above has_filltable_gate; a forgotten
    # deletion at the old site leaves it assigned twice. Nothing else in the
    # repo can see that: it is valid Python, ruff's F811 does not cover plain
    # variable reassignment, the recomputed value is identical so every context
    # test stays green, and test_html_element.py's len(q3) == len(q1) is a
    # RELATIVE A/B that pays the duplicate query in both arms.
    # `"has_fill_table": has_fill_table,` in the return dict does not match --
    # no ` = ` -- and `has_filltable_gate = ` differs in the underscore.
    assert SRC.count("has_fill_table = ") == 1
