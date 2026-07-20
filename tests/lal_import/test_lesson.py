from scripts.lal_import.lesson import parse_lesson

VIDEO_LESSON = """
<h2>Zbiory - pojęcia podstawowe</h2>
<p>Obejrzyj nagrania.</p>
<h3>Sekcja</h3>
<figure><video controls><source src="static/zbiory.mp4" type="video/mp4"/>
</video></figure>
"""


def test_h2_title_is_skipped_and_paragraph_kept():
    elements, flags = parse_lesson(VIDEO_LESSON, "005_zbiory.html")
    types = [e["type"] for e in elements]
    assert "video" in types
    # The <h2> is the unit title, not body; the <h3> + <p> survive as text.
    text_bodies = " ".join(e["body"] for e in elements if e["type"] == "text")
    assert "Zbiory - pojęcia podstawowe" not in text_bodies
    assert "Obejrzyj nagrania." in text_bodies


def test_video_media_src_extracted():
    elements, _ = parse_lesson(VIDEO_LESSON, "005_zbiory.html")
    vid = next(e for e in elements if e["type"] == "video")
    assert vid["media_src"] == "static/zbiory.mp4"


def test_inline_math_is_escaped_and_body_wellformed():
    # Exact-equality (not substring): a substring check would pass on corrupted
    # output. The <p> must be intact and the math span escaped.
    elements, _ = parse_lesson(r"<p>gdy \(y<z\)</p>", "x.html")
    body = next(e["body"] for e in elements if e["type"] == "text")
    assert body == r"<p>gdy \(y&lt;z\)</p>"


def test_second_h2_becomes_text_not_flag():
    # Only the FIRST <h2> is the unit title; later ones are body headings (spec §5).
    elements, flags = parse_lesson("<h2>Title</h2><p>a</p><h2>Sekcja 2</h2>", "x.html")
    text = " ".join(e["body"] for e in elements if e["type"] == "text")
    assert "Sekcja 2" in text
    assert "Title" not in text
    assert flags == []


def test_spoiler_from_show_solution():
    html = (
        '<div class="show_solution ks_button">zobacz</div>'
        '<div class="question_solution hidden">Zbiór pusty \\(\\emptyset\\).</div>'
    )
    elements, flags = parse_lesson(html, "x.html")
    sp = next(e for e in elements if e["type"] == "spoiler")
    assert sp["label"] == "zobacz"
    assert "emptyset" in sp["body"]
    # The consumed solution div must NOT be re-emitted as an "unmapped div" flag.
    assert flags == []


def test_image_with_figcaption():
    html = (
        '<figure><img src="static/wykres.png" alt="wykres"/>'
        "<figcaption>Rys 1</figcaption></figure>"
    )
    elements, _ = parse_lesson(html, "x.html")
    img = next(e for e in elements if e["type"] == "image")
    assert img["media_src"] == "static/wykres.png"
    assert img["alt"] == "wykres"
    assert img["figcaption"] == "Rys 1"


def test_iframe_url_kept():
    html = '<iframe src="https://www.geogebra.org/material/iframe/id/abc"></iframe>'
    elements, _ = parse_lesson(html, "x.html")
    frame = next(e for e in elements if e["type"] == "iframe")
    assert "geogebra.org" in frame["url"]


def test_sole_block_display_math_becomes_mathelement():
    elements, _ = parse_lesson(r"<p>\[a<b\]</p>", "x.html")
    assert elements[0]["type"] == "math"
    assert elements[0]["latex"] == r"a<b"  # literal, for [data-katex]


def test_mid_paragraph_display_math_stays_text():
    elements, _ = parse_lesson(r"<p>Wynik: \[x\] gotowe</p>", "x.html")
    assert elements[0]["type"] == "text"  # not a sole \[...\] block


def test_relative_href_is_flagged():
    elements, flags = parse_lesson('<p>zob. <a href="040_x.html">tu</a></p>', "x.html")
    assert any(f["kind"] == "relative_href" for f in flags)
    assert elements[0]["type"] == "text"  # text still emitted (warning only)


def test_absolute_href_not_flagged():
    _, flags = parse_lesson('<p><a href="https://x.example">t</a></p>', "x.html")
    assert not any(f["kind"] == "relative_href" for f in flags)


def test_relative_href_inside_spoiler_is_flagged():
    html = (
        '<div class="show_solution ks_button">zobacz</div>'
        '<div class="question_solution hidden">zob. <a href="050_x.html">tu</a></div>'
    )
    _, flags = parse_lesson(html, "x.html")
    assert any(f["kind"] == "relative_href" for f in flags)


def test_html_comment_is_ignored():
    elements, flags = parse_lesson("<!-- editor note --><p>a</p>", "x.html")
    assert flags == []
    assert [e["type"] for e in elements] == ["text"]


def test_spoiler_body_preserves_escaped_math():
    html = (
        '<div class="show_solution ks_button">zobacz</div>'
        r'<div class="question_solution hidden">gdy \(a<b\) to</div>'
    )
    elements, _ = parse_lesson(html, "x.html")
    sp = next(e for e in elements if e["type"] == "spoiler")
    assert r"\(a&lt;b\)" in sp["body"]  # entity preserved, not literal <


def test_r1_generic_question_div_descends_into_children():
    html = r'<div id="question10"><p>hi \(x<y\)</p></div>'
    elements, flags = parse_lesson(html, "x.html")
    assert [e["type"] for e in elements] == ["text"]
    assert flags == []


def test_r2_question_text_div_becomes_text_element():
    html = r'<div class="question_text">Jak obliczyć \(a<b\)?</div>'
    elements, _ = parse_lesson(html, "x.html")
    text = next(e for e in elements if e["type"] == "text")
    assert r"\(a&lt;b\)" in text["body"]


def test_r3_reveal_table_becomes_spoilers_per_row():
    html = (
        '<table class="my_table_TL">'
        "<tr><td>Suma zbiorów</td>"
        '<td class="question_answer"></td>'
        '<td><div class="show_solution ks_button">zobacz</div></td>'
        '<td><div class="question_solution hidden">A ∪ B</div></td></tr>'
        "<tr><td>Iloczyn zbiorów</td>"
        '<td class="question_answer"></td>'
        '<td><div class="show_solution ks_button">zobacz</div></td>'
        '<td><div class="question_solution hidden">A ∩ B</div></td></tr>'
        "</table>"
    )
    elements, _ = parse_lesson(html, "x.html")
    spoilers = [e for e in elements if e["type"] == "spoiler"]
    assert len(spoilers) == 2
    assert spoilers[0]["label"] == "Suma zbiorów"
    assert spoilers[1]["label"] == "Iloczyn zbiorów"


def test_r3_plain_data_table_still_maps_to_table_element():
    html = "<table><tr><td>a</td><td>b</td></tr><tr><td>c</td><td>d</td></tr></table>"
    elements, _ = parse_lesson(html, "x.html")
    assert [e["type"] for e in elements] == ["table"]


def test_r4_details_becomes_spoiler():
    html = r"<details><summary>obliczenia</summary><p>\(a<b\)</p></details>"
    elements, _ = parse_lesson(html, "x.html")
    sp = next(e for e in elements if e["type"] == "spoiler")
    assert sp["label"] == "obliczenia"
    assert r"\(a&lt;b\)" in sp["body"]
    assert "obliczenia" not in sp["body"]


def test_r5_bare_display_math_text_node_becomes_math_element():
    html = r"<p>a</p>\[p\Rightarrow q\]<p>b</p>"
    elements, _ = parse_lesson(html, "x.html")
    math_els = [e for e in elements if e["type"] == "math"]
    assert len(math_els) == 1
    assert math_els[0]["latex"] == r"p\Rightarrow q"


def test_r6_h1_small_h5_become_text_and_hr_is_skipped():
    elements, flags = parse_lesson('<h1 class="heading">T</h1>', "x.html")
    assert flags == []
    text = next(e for e in elements if e["type"] == "text")
    assert "T" in text["body"]

    elements, flags = parse_lesson("<hr/>", "x.html")
    assert elements == []
    assert flags == []


def test_r7_figure_with_iframe_becomes_iframe_element():
    html = '<figure><iframe src="https://www.geogebra.org/x"></iframe></figure>'
    elements, flags = parse_lesson(html, "x.html")
    assert [e["type"] for e in elements] == ["iframe"]
    assert flags == []


def test_f1_inline_only_div_becomes_single_text_element():
    html = r"<div>Zbiór \(A<B\) i \(C\)</div>"
    elements, flags = parse_lesson(html, "x.html")
    assert [e["type"] for e in elements] == ["text"]
    body = elements[0]["body"]
    assert r"\(A&lt;B\)" in body
    assert r"\(C\)" in body
    assert flags == []


def test_f1_div_with_block_child_still_descends():
    html = "<div><p>a</p><table><tr><td>x</td></tr></table></div>"
    elements, flags = parse_lesson(html, "x.html")
    types = [e["type"] for e in elements]
    assert "text" in types
    assert "table" in types
    assert flags == []


def test_f2_bare_text_node_becomes_text_element_not_flag():
    html = r"<p>a</p>\(A\)<p>b</p>"
    elements, flags = parse_lesson(html, "x.html")
    text_bodies = [e["body"] for e in elements if e["type"] == "text"]
    assert any(r"\(A\)" in b for b in text_bodies)
    assert flags == []


def test_f3_top_level_span_becomes_text_not_flag():
    html = "<p>a</p><span>x</span><p>b</p>"
    elements, flags = parse_lesson(html, "x.html")
    text_bodies = [e["body"] for e in elements if e["type"] == "text"]
    assert any("x" in b for b in text_bodies)
    assert flags == []


def test_f3_top_level_br_is_skipped_silently():
    html = "<p>a</p><br/><p>b</p>"
    elements, flags = parse_lesson(html, "x.html")
    assert [e["type"] for e in elements] == ["text", "text"]
    assert flags == []


# --- Group A (2026-07-20): render-correctness fixes ---

# The real GeoGebra "Sprawdź się!" shape (001_zbiory_liczbowe/032_zbiory.html):
# the applet lives inside a .question_text div, wrapped in a <figure> alongside
# .iframe_small (no-JS fallback chrome) and a details.info_iframe (email chrome).
GEOGEBRA_QUESTION = r"""
<div id="question10">
  <p class="question"></p>
  <div class="question_text">
    <p>Klikaj na obszary oznaczone \(A\cap B\).</p>
    <div>
      <figure>
        <div class="iframe_small hidden">
          <small>Jeśli poniższy aplet nie wygląda dobrze...</small>
        </div>
        <iframe src="https://www.geogebra.org/material/iframe/id/abc"></iframe>
        <details class="info_iframe">
          <summary>aplet nie działa poprawnie?</summary>
          <a class="mailto_tag" href="mailto:x@y">wyślij</a>
        </details>
      </figure>
    </div>
  </div>
</div>
"""


def test_geogebra_question_emits_one_iframe_and_drops_chrome():
    elements, flags = parse_lesson(GEOGEBRA_QUESTION, "032_zbiory.html")
    iframes = [e for e in elements if e["type"] == "iframe"]
    assert len(iframes) == 1
    assert "geogebra.org/material/iframe/id/abc" in iframes[0]["url"]
    # No fallback/email chrome may leak as visible content.
    all_text = " ".join(
        e.get("body", "") for e in elements if e["type"] in ("text", "spoiler")
    )
    assert "aplet" not in all_text.lower()
    assert "Jeśli poniższy" not in all_text
    assert "wyślij" not in all_text
    # The real prompt survives.
    assert "Klikaj na obszary" in all_text


def test_success_and_failure_feedback_chrome_is_dropped():
    html = (
        '<div class="question_text"><p>Wybierz.</p></div>'
        '<div class="switch_summary success hidden">Świetnie!</div>'
        '<div class="failure hidden">Zastanów się jeszcze.</div>'
    )
    elements, flags = parse_lesson(html, "x.html")
    all_text = " ".join(e.get("body", "") for e in elements)
    assert "Świetnie" not in all_text
    assert "Zastanów się" not in all_text
    assert "Wybierz." in all_text


def test_reverse_order_show_solution_finds_preceding_solution():
    # Some units place the .question_solution BEFORE its show_solution button;
    # _next_solution scanned forward only and flagged them as unmapped.
    html = (
        '<div class="question_solution hidden">Odp: \\(x=2\\).</div>'
        '<div class="show_solution ks_button">zobacz rozwiązanie</div>'
    )
    elements, flags = parse_lesson(html, "x.html")
    sp = next(e for e in elements if e["type"] == "spoiler")
    assert sp["label"] == "zobacz rozwiązanie"
    assert "x=2" in sp["body"]
    assert flags == []
    # The solution div must not also leak as a standalone text element.
    assert not any(e["type"] == "text" and "x=2" in e.get("body", "") for e in elements)


def test_fragment_anchor_href_is_not_flagged():
    # In-page anchors (tab targets, toc links) start with '#'; they are intentional
    # fragments, not dropped external links, so they must not raise relative_href.
    elements, flags = parse_lesson(
        '<p>zob. <a href="#tabcontent-1-1">tu</a></p>', "x.html"
    )
    assert not any(f["kind"] == "relative_href" for f in flags)


# Rule 7: interactive widgets that aren't native-mapped yet (Group B) collapse to
# ONE flagged placeholder block instead of fragmenting; prompt/feedback handled.
MULTI_MANY_QUESTION = r"""
<div id="question20">
  <div class="question_text"><p>Wybierz wszystkie dzielniki.</p></div>
  <div>
    <div class="multi_many_option statement">\(432\)</div>
    <div class="multi_many_ans ks_button">\(2\)</div>
    <div class="multi_many_ans ks_button">\(3\)</div>
  </div>
  <div class="confirm_multiple ks_button">potwierdź</div>
  <div class="success hidden">Brawo!</div>
</div>
"""


def test_multi_many_widget_collapses_and_prompt_kept():
    elements, flags = parse_lesson(MULTI_MANY_QUESTION, "x.html")
    placeholders = [e for e in elements if e.get("flagged")]
    # The option rows + confirm coalesce into ONE placeholder (not 4+ fragments).
    assert len(placeholders) == 1
    text = " ".join(e.get("body", "") for e in elements if e["type"] == "text")
    assert "Wybierz wszystkie dzielniki" in text
    assert not any(
        e["type"] == "text" and r"\(2\)" in e.get("body", "") for e in elements
    )
    assert "Brawo" not in placeholders[0]["raw"]


def test_plain_lesson_has_no_widget_placeholder():
    # A non-interactive lesson must not trip the widget detector.
    html = "<h2>T</h2><p>Zwykły tekst.</p><figure><img src='a.png' alt='x'/></figure>"
    elements, flags = parse_lesson(html, "x.html")
    assert not any(e.get("flagged") for e in elements)


def test_empty_question_label_becomes_zadanie_heading():
    # <p class="question"> is emptied in source; JS rewrites it to "Zadanie N".
    # Emit a real label instead of a blank styled paragraph.
    html = '<p class="question"></p><div class="question_text"><p>Oblicz.</p></div>'
    elements, flags = parse_lesson(html, "x.html")
    bodies = [e["body"] for e in elements if e["type"] == "text"]
    assert any("Zadanie" in b for b in bodies)
    # The blank <p class="question"> placeholder text is gone.
    assert not any(b.strip() in ("<p></p>", '<p class="question"></p>') for b in bodies)


def test_example_label_becomes_przyklad_heading():
    html = '<p class="example"></p><p>Rozwiązanie.</p>'
    elements, _ = parse_lesson(html, "x.html")
    bodies = [e["body"] for e in elements if e["type"] == "text"]
    assert any("Przykład" in b for b in bodies)


# --- Group B #7: one_choice -> ChoiceGrid (consistent) / per-row MCQ (varying) ---
ONE_CHOICE_GRID = r"""
<div id="question20">
  <div class="question_text"><p>Odpowiedz na każde pytanie.</p></div>
  <ul>
    <li><div class="statement">Czy \(1\) jest pierwsza?</div>
        <div class="one_choice">tak</div><div class="one_choice">nie</div></li>
    <li><div class="statement">Czy \(2\) jest pierwsza?</div>
        <div class="one_choice">tak</div><div class="one_choice">nie</div></li>
  </ul>
  <div class="confirm_choice ks_button">potwierdź</div>
  <div class="success hidden">Brawo!</div>
</div>
<script>localStorage.setItem("correct_choices",
JSON.stringify({20: [2, 1]}));</script>
"""


def test_one_choice_consistent_becomes_choice_grid():
    elements, flags = parse_lesson(ONE_CHOICE_GRID, "x.html")
    assert not any(e.get("flagged") for e in elements)
    grids = [e for e in elements if e["type"] == "choice_grid"]
    assert len(grids) == 1
    assert grids[0]["columns"] == ["tak", "nie"]
    rows = grids[0]["rows"]
    assert [r["correct"] for r in rows] == [1, 0]  # correct_choices 1-based -> 0-based
    assert "Czy" in rows[0]["statement"]
    # prompt kept, confirm/feedback chrome dropped
    joined = " ".join(str(e) for e in elements)
    assert "Odpowiedz" in joined
    assert "Brawo" not in joined and "potwierdź" not in joined


ONE_CHOICE_VARYING = r"""
<div id="question30">
  <ul>
    <li><div class="statement">A?</div>
        <div class="one_choice">tak</div><div class="one_choice">nie</div></li>
    <li><div class="statement">Ile?</div>
        <div class="one_choice">\(4\)</div><div class="one_choice">\(5\)</div></li>
  </ul>
</div>
<script>localStorage.setItem("correct_choices",
JSON.stringify({30: [1, 2]}));</script>
"""


def test_one_choice_varying_falls_back_to_per_row_mcq():
    elements, flags = parse_lesson(ONE_CHOICE_VARYING, "x.html")
    assert not any(e["type"] == "choice_grid" for e in elements)
    mcqs = [e for e in elements if e["type"] == "choice"]
    assert len(mcqs) == 2
    # row 0 correct index 0 ("tak"), row 1 correct index 1 ("\(5\)")
    assert [c["is_correct"] for c in mcqs[0]["choices"]] == [True, False]
    assert [c["is_correct"] for c in mcqs[1]["choices"]] == [False, True]


# --- Group B #6: ks_tabs -> TabsElement (nested children) ---
KS_TABS = r"""
<div class="ks_tabs">
  <ul>
    <li><a id="tab-1-1" href="#tabcontent-1-1">Sposób I</a></li>
    <li><a id="tab-1-2" href="#tabcontent-1-2">Sposób II</a></li>
  </ul>
  <div id="tabcontent-1-1" class="visible"><p>Pierwszy: \(1\%\).</p></div>
  <div id="tabcontent-1-2"><p>Drugi sposób.</p><p>Wynik \(240\).</p></div>
</div>
"""


def test_ks_tabs_becomes_tabs_with_nested_children():
    elements, flags = parse_lesson(KS_TABS, "x.html")
    assert not any(e.get("flagged") for e in elements)
    tabs = [e for e in elements if e["type"] == "tabs"]
    assert len(tabs) == 1
    t = tabs[0]["tabs"]
    assert [x["label"] for x in t] == ["Sposób I", "Sposób II"]
    # ids are the conforming t[0-9a-f]{6} form and unique
    assert t[0]["id"] == "t000000" and t[1]["id"] == "t000001"
    # tab 1 content is nested (native text with escaped math), not flattened out
    assert [e["type"] for e in t[0]["elements"]] == ["text"]
    assert r"\(1\%\)" in t[0]["elements"][0]["body"]
    # tab 2 has both paragraphs
    assert len(t[1]["elements"]) == 2
    # the tab bodies must NOT also leak as top-level siblings
    top_text = " ".join(e.get("body", "") for e in elements if e["type"] == "text")
    assert "Pierwszy" not in top_text


DETAILS_WRAPPING_TABS = r"""
<details>
  <summary>Zobacz rozwiązanie</summary>
  <p>Wstęp do zadania.</p>
  <div class="ks_tabs">
    <ul><li><a href="#tabcontent-1-1">A</a></li>
        <li><a href="#tabcontent-1-2">B</a></li></ul>
    <div id="tabcontent-1-1"><p>Panel A.</p></div>
    <div id="tabcontent-1-2"><p>Panel B.</p></div>
  </div>
</details>
"""


def test_details_wrapping_tabs_emits_native_tabs_no_spoiler():
    elements, flags = parse_lesson(DETAILS_WRAPPING_TABS, "x.html")
    # the <details> collapse is dropped -> no spoiler, a native tabs instead
    assert not any(e["type"] == "spoiler" for e in elements)
    tabs = [e for e in elements if e["type"] == "tabs"]
    assert len(tabs) == 1
    assert [t["label"] for t in tabs[0]["tabs"]] == ["A", "B"]
    joined = " ".join(e.get("body", "") for e in elements if e["type"] == "text")
    assert "Zobacz rozwiązanie" in joined  # summary kept as a heading
    assert "Wstęp do zadania" in joined  # intro before the tabs kept


def test_plain_details_still_becomes_spoiler():
    html = r"<details><summary>obliczenia</summary><p>\(a<b\)</p></details>"
    elements, _ = parse_lesson(html, "x.html")
    assert any(e["type"] == "spoiler" for e in elements)


def test_ks_tabs_with_wrong_tab_count_falls_back_to_placeholder():
    html = (
        '<div class="ks_tabs"><ul><li><a href="#tabcontent-1-1">Only</a></li></ul>'
        '<div id="tabcontent-1-1"><p>one</p></div></div>'
    )
    elements, flags = parse_lesson(html, "x.html")
    # a single tab is out of TabsElement bounds (min 2) -> placeholder, not tabs
    assert not any(e["type"] == "tabs" for e in elements)
    assert any(e.get("flagged") for e in elements)


# --- Group B #5: inline table_input (not in a table) -> FillBlank self-check ---
INLINE_FILL = r"""
<div id="question20">
  <p>Czy Bartek pomylił się bardziej niż Artur?</p>
  <p><input class="table_input" placeholder="wpisz"></p>
</div>
<script>localStorage.setItem("table_answers",
JSON.stringify({20: ["nie"]}));</script>
"""


def test_inline_input_becomes_fillblank_not_empty():
    elements, flags = parse_lesson(INLINE_FILL, "x.html")
    assert not any(e.get("flagged") for e in elements)
    # no empty text element leaks from the stripped <input>
    assert not any(
        e["type"] == "text" and e["body"].strip() in ("<p></p>", "<p>\n\n</p>")
        for e in elements
    )
    fbs = [e for e in elements if e["type"] == "fillblank"]
    assert len(fbs) == 1
    assert fbs[0]["blanks"] == [["nie"]]
    assert "￿" in fbs[0]["stem"]  # a sentinel blank token is present
    # the question text is preserved
    assert any("Bartek" in e.get("body", "") for e in elements if e["type"] == "text")


def test_inline_input_decimal_gets_comma_alternative():
    html = (
        '<div id="question5"><p>Wynik: <input class="table_input"></p></div>'
        '<script>localStorage.setItem("table_answers",'
        "JSON.stringify({5: [0.5]}));</script>"
    )
    elements, _ = parse_lesson(html, "x.html")
    fb = next(e for e in elements if e["type"] == "fillblank")
    assert fb["blanks"] == [["0.5", "0,5"]]


# --- Group B #4: table_input -> FillTableElement ---
TABLE_INPUT = r"""
<div id="question10">
  <div class="question_text"><p>Uzupełnij tabelę.</p></div>
  <table class="my_table_border">
    <tr><th>wymiar</th><th>błąd</th></tr>
    <tr><td>\(50,5\)</td><td><input class="table_input" placeholder="wpisz"></td></tr>
    <tr><td>\(90,5\)</td><td><input class="table_input" placeholder="wpisz"></td></tr>
  </table>
</div>
<script>localStorage.setItem("table_answers",
JSON.stringify({10: [0.5, 0.7]}));</script>
"""


def test_table_input_becomes_fill_table():
    elements, flags = parse_lesson(TABLE_INPUT, "x.html")
    fills = [e for e in elements if e["type"] == "fill_table"]
    assert len(fills) == 1
    assert not any(e.get("flagged") for e in elements)
    cells = fills[0]["data"]["cells"]
    assert fills[0]["data"]["header_row"] is True
    # header row is static
    assert cells[0][0]["kind"] == "static" and "wymiar" in cells[0][0]["html"]
    # the input cell is an answer cell; the decimal accepts dot- and comma-forms
    ans = cells[1][1]
    assert ans["kind"] == "answer"
    assert ans["answer"] == "0.5|0,5"
    assert cells[2][1]["answer"] == "0.7|0,7"
    # static math cell keeps its escaped body
    assert cells[1][0]["kind"] == "static"
    # prompt rendered as native text
    joined = " ".join(str(e) for e in elements)
    assert "Uzupełnij tabelę" in joined


# --- Group B #3: switch_confirm -> SwitchGrid ---
SWITCH_CONFIRM = r"""
<div id="question10">
  <div class="question_text"><p>Uzupełnij działania na zbiorach.</p></div>
  <div class="switch_options">
    <div class="switch_line">
      <div class="switch_around">\(A\)</div>
      <div class="switch_value">\(\cup\)</div>
      <div class="switch_value">\(\cap\)</div>
      <div class="switch_value">\(\setminus\)</div>
      <div class="switch_around">\(B\)</div>
    </div>
    <div class="switch_line">
      <div class="switch_around">\(A\)</div>
      <div class="switch_value">\(\cup\)</div>
      <div class="switch_value">\(\cap\)</div>
      <div class="switch_value">\(\setminus\)</div>
      <div class="switch_around">\(C\)</div>
    </div>
    <div class="switch_confirm ks_button">zatwierdź</div>
    <div class="switch_summary success hidden">Świetnie!</div>
  </div>
</div>
<script>localStorage.setItem("switch_answers", JSON.stringify({10: [2, 1]}));</script>
"""


def test_switch_confirm_becomes_switch_grid():
    elements, flags = parse_lesson(SWITCH_CONFIRM, "x.html")
    grids = [e for e in elements if e["type"] == "switch_grid"]
    assert len(grids) == 1
    lines = grids[0]["lines"]
    assert len(lines) == 2
    assert lines[0]["cyclers"][0]["options"] == [
        r"\(\cup\)",
        r"\(\cap\)",
        r"\(\setminus\)",
    ]
    assert lines[0]["cyclers"][0]["answer"] == 2
    assert lines[1]["cyclers"][0]["answer"] == 1
    # prompt renders as native text; feedback praise never leaks.
    joined = " ".join(str(e) for e in elements)
    assert "Uzupełnij działania" in joined
    assert "Świetnie" not in joined
    assert not any(e.get("flagged") for e in elements)


# --- Group B #1: show_next progressive reveal -> RevealGate chain ---
SHOW_NEXT_WIDGET = r"""
<div class="steps">
  <div class="show_next ks_button">pokaż dalej</div>
  <div class="show_step"><p>Krok \(1\): rozłóż.</p></div>
  <div class="show_next ks_button">pokaż dalej</div>
  <div class="show_step"><p>Krok \(2\): policz.</p></div>
</div>
"""


def test_show_next_becomes_reveal_gate_chain():
    elements, flags = parse_lesson(SHOW_NEXT_WIDGET, "x.html")
    types = [e["type"] for e in elements]
    # gate, step1 content, gate, step2 content — in order.
    assert types == ["reveal_gate", "text", "reveal_gate", "text"]
    gates = [e for e in elements if e["type"] == "reveal_gate"]
    assert all(g["label"] == "pokaż dalej" for g in gates)
    # Step content survives as native text (not a placeholder), math escaped.
    bodies = [e["body"] for e in elements if e["type"] == "text"]
    assert any("Krok" in b and r"\(1\)" in b for b in bodies)
    assert not any(e.get("flagged") for e in elements)
    assert flags == []


# --- Group B #2: switch_show_next progressive reveal -> SwitchGate chain ---
SWITCH_SHOW_NEXT = r"""
<div id="question13">
  <div class="question_text"><p>Policz wartości funkcji.</p></div>
  <div class="switch_steps">
    <div class="switch_step">
      <p>Dla \(x=4\):</p>
      <div class="switch_line">
        <div class="switch_value">>> wybierz >></div>
        <div class="switch_value">\(-1\)</div>
        <div class="switch_value">\(0\)</div>
        <div class="switch_show_next ks_button">zatwierdź</div>
      </div>
    </div>
    <div class="switch_step hidden">
      <p>Dobrze, \(f(4)=0\).</p>
    </div>
  </div>
</div>
<script>localStorage.setItem("switch_answers", JSON.stringify({13: [2]}));</script>
"""


def test_switch_show_next_becomes_switch_gate_chain():
    elements, flags = parse_lesson(SWITCH_SHOW_NEXT, "x.html")
    types = [e["type"] for e in elements]
    assert "switch_gate" in types
    assert not any(e.get("flagged") for e in elements)
    gate = next(e for e in elements if e["type"] == "switch_gate")
    # the ">> wybierz >>" prompt is dropped (libli cycler supplies its own) and
    # the answer index shifts down: LAL 2 ("0") -> libli 1.
    assert gate["options"] == [r"\(-1\)", r"\(0\)"]
    assert gate["answer"] == 1
    # Step content (before and after the gate) survives as native text.
    bodies = " ".join(e.get("body", "") for e in elements if e["type"] == "text")
    assert "Policz wartości" in bodies
    assert "Dla" in bodies and "Dobrze" in bodies
    # The gate sits between its own step's content and the next step's content.
    order = [e["type"] for e in elements]
    assert order.index("switch_gate") < len(order) - 1


def test_show_next_step_with_block_math_kept_as_math_element():
    html = (
        '<div class="steps">'
        '<div class="show_next ks_button">dalej</div>'
        r'<div class="show_step"><p>Stąd:</p>\[a=b\]</div>'
        "</div>"
    )
    elements, _ = parse_lesson(html, "x.html")
    types = [e["type"] for e in elements]
    assert types[0] == "reveal_gate"
    assert "math" in types  # the \[...\] display block becomes a MathElement
