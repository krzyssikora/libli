import pytest
from django.template.loader import render_to_string

from courses.element_forms import FORM_FOR_TYPE
from courses.models import FillTableElement

pytestmark = pytest.mark.django_db

S = "\uffff"


def _render(instance):
    form = FORM_FOR_TYPE["filltable"](instance=instance)
    return render_to_string(
        "courses/manage/editor/_edit_filltable.html",
        {"form": form, "type_key": "filltable"},
    )


def test_stored_gaps_shown_as_markers_in_td_and_th():
    el = FillTableElement(
        data={
            "cells": [
                [
                    {
                        "kind": "static",
                        "html": f"{S}0{S} x",
                        "gaps": [["9", "9,0"]],
                        "header": True,
                    },
                    {"kind": "static", "html": f"{S}0{S}", "gaps": [["a<b"]]},
                ]
            ]
        }
    )
    html = _render(el)
    assert "{{9|9,0}} x</th>" in html
    assert "{{a&lt;b}}</td>" in html
    assert S not in html


def test_hint_and_no_answer_message_keep_literal_braces():
    html = _render(FillTableElement())
    assert "Type {{answer}} in a cell" in html
    assert (
        'data-msg-no-answer="Add at least one answer — mark an answer cell, '
        'or type {{answer}} in a cell."'
    ) in html
