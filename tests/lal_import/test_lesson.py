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
    assert any("emptyset" in c.get("body", "") for c in sp["elements"])
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
    # entity preserved, not literal <
    assert any(r"\(a&lt;b\)" in c.get("body", "") for c in sp["elements"])


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
    assert any(r"\(a&lt;b\)" in c.get("body", "") for c in sp["elements"])
    # the summary label must not leak into any child body
    assert not any("obliczenia" in c.get("body", "") for c in sp["elements"])


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
    assert any("x=2" in c.get("body", "") for c in sp["elements"])
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


# --- Group B #9: multi_many -> MultiGrid (shared cols) / per-row MCQ (varying) ---
MULTI_MANY_GRID = r"""
<div id="question20">
  <div class="question_text"><p>Wybierz wszystkie dzielniki.</p></div>
  <div>
    <div class="multi_many_option statement">\(432\)</div>
    <div class="multi_many_ans ks_button">\(2\)</div>
    <div class="multi_many_ans ks_button">\(3\)</div>
    <div class="multi_many_ans ks_button">\(5\)</div>
  </div>
  <div>
    <div class="multi_many_option statement">\(250\)</div>
    <div class="multi_many_ans ks_button">\(2\)</div>
    <div class="multi_many_ans ks_button">\(3\)</div>
    <div class="multi_many_ans ks_button">\(5\)</div>
  </div>
  <div class="confirm_multiple ks_button">potwierdź</div>
  <div class="success hidden">Brawo!</div>
</div>
<script>localStorage.setItem("multiple_many_correct_answers",
JSON.stringify({20: [[1, 1, 0], [1, 0, 1]]}));</script>
"""


def test_multi_many_consistent_becomes_multi_grid():
    elements, flags = parse_lesson(MULTI_MANY_GRID, "x.html")
    assert not any(e.get("flagged") for e in elements)
    grids = [e for e in elements if e["type"] == "multi_grid"]
    assert len(grids) == 1
    assert grids[0]["columns"] == [r"\(2\)", r"\(3\)", r"\(5\)"]
    rows = grids[0]["rows"]
    assert [r["statement"] for r in rows] == [r"\(432\)", r"\(250\)"]
    # correct_columns = the indices where the mask is 1
    assert rows[0]["correct"] == [0, 1]
    assert rows[1]["correct"] == [0, 2]
    # prompt kept, confirm/feedback chrome dropped
    joined = " ".join(str(e) for e in elements)
    assert "Wybierz wszystkie dzielniki" in joined
    assert "Brawo" not in joined and "potwierdź" not in joined


MULTI_MANY_VARYING = r"""
<div id="question30">
  <div class="question_text"><p>Wskaż uproszczoną postać.</p></div>
  <div>
    <div class="multi_many_option statement">\((-3ab)(-2a)\)</div>
    <div class="multi_many_ans ks_button">\(6b\)</div>
    <div class="multi_many_ans ks_button">\(6a^2b\)</div>
  </div>
  <div>
    <div class="multi_many_option statement">\((2ts)^2\)</div>
    <div class="multi_many_ans ks_button">\(4t^2s^2\)</div>
    <div class="multi_many_ans ks_button">\(4ts\)</div>
  </div>
</div>
<script>localStorage.setItem("multiple_many_correct_answers",
JSON.stringify({30: [[0, 1], [1, 0]]}));</script>
"""


def test_multi_many_varying_falls_back_to_per_row_multiselect():
    elements, flags = parse_lesson(MULTI_MANY_VARYING, "x.html")
    assert not any(e["type"] == "multi_grid" for e in elements)
    mcqs = [e for e in elements if e["type"] == "choice"]
    assert len(mcqs) == 2
    # multi_many is a pick-a-set widget -> per-row checkboxes (multiple=True)
    assert all(m["multiple"] for m in mcqs)
    assert [c["is_correct"] for c in mcqs[0]["choices"]] == [False, True]
    assert [c["is_correct"] for c in mcqs[1]["choices"]] == [True, False]


# --- Group B #10: mult_choice -> ChoiceQuestion(multiple) with per-option feedback -
MULT_CHOICE_QUESTION = r"""
<div id="question60">
  <p class="question"></p>
  <p class="question_text">Wskaż równania paraboli.</p>
  <div class="multiple_answers">
    <div class="multiple_option">
      <div class="mult_option inline">\(y=\frac{5}{2}(x+1)^2-2\)</div>
      <div class="inline"><input class="mult_choice" type="checkbox"/></div>
    </div>
    <div class="multiple_option">
      <div class="mult_feedback_incorrect">Ramiona są do góry.</div>
    </div>
    <div class="multiple_option">
      <div class="mult_option inline">\(y=-3(x+2)^2-1\)</div>
      <div class="inline"><input class="mult_choice" type="checkbox"/></div>
    </div>
    <div class="multiple_option">
      <div class="mult_feedback_incorrect"><strong>pod</strong> osią</div>
    </div>
  </div>
  <div class="confirm_feedback_multiple ks_button">potwierdź</div>
  <div class="success hidden">Brawo!</div>
</div>
<script>localStorage.setItem("multiple_many_correct_answers",
JSON.stringify({60: [[1, 0]]}));</script>
"""


def test_mult_choice_becomes_choice_with_per_option_feedback():
    elements, flags = parse_lesson(MULT_CHOICE_QUESTION, "x.html")
    assert not any(e.get("flagged") for e in elements)
    choices = [e for e in elements if e["type"] == "choice"]
    assert len(choices) == 1
    q = choices[0]
    assert q["multiple"] is True  # checkbox widget -> multi-select
    # stem lives on the element (question_text), not a duplicated prompt block
    assert "Wskaż równania paraboli" in q["stem"]
    assert not any(
        e["type"] == "text" and "Wskaż równania paraboli" in e.get("body", "")
        for e in elements
    )
    opts = q["choices"]
    assert [c["is_correct"] for c in opts] == [True, False]
    assert opts[0]["text"] == r"\(y=\frac{5}{2}(x+1)^2-2\)"
    # per-option feedback preserved (formatting flattened to plain text + KaTeX)
    assert "Ramiona są do góry" in opts[0]["feedback"]
    assert "pod osią" in opts[1]["feedback"] and "<strong>" not in opts[1]["feedback"]
    # confirm button + success chrome dropped, no leaks
    joined = " ".join(str(e) for e in elements)
    assert "potwierdź" not in joined and "Brawo" not in joined


MULT_CHOICE_MULTI_Q = r"""
<div id="question10">
  <p class="question_text">Pytanie A?</p>
  <div><div class="multiple_option"><div class="mult_option">tak</div>
    <input class="mult_choice" type="checkbox"/></div>
    <div class="multiple_option"><div class="mult_feedback_incorrect">źle A</div></div>
  </div>
</div>
<div id="question20">
  <p class="question_text">Pytanie B?</p>
  <div><div class="multiple_option"><div class="mult_option">nie</div>
    <input class="mult_choice" type="checkbox"/></div>
    <div class="multiple_option"><div class="mult_feedback_incorrect">źle B</div></div>
  </div>
</div>
<script>localStorage.setItem("multiple_many_correct_answers",
JSON.stringify({10: [[1]], 20: [[0]]}));</script>
"""


def test_mult_choice_multiple_questions_each_become_own_choice():
    elements, flags = parse_lesson(MULT_CHOICE_MULTI_Q, "x.html")
    choices = [e for e in elements if e["type"] == "choice"]
    assert len(choices) == 2
    assert "Pytanie A" in choices[0]["stem"]
    assert "Pytanie B" in choices[1]["stem"]
    assert choices[0]["choices"][0]["is_correct"] is True
    assert choices[1]["choices"][0]["is_correct"] is False


# --- Group B #11: multi_ans -> ChoiceQuestion(multiple) with per-option feedback -
# 140_ciagi shape: a group question wraps math prompts + leaf sub-question MCQs
# that carry no own question_text (the preceding \[..\] math is the prompt).
MULTI_ANS_GROUP = r"""
<div id="question330">
  <div class="question_text"><p>Wskaż monotoniczność ciągów.</p></div>
  \[ a_1=12 \]
  <div id="question335">
    <div>
      <div class="multi_ans ks_button">rosnący</div>
      <div class="multi_ans ks_button">malejący</div>
    </div>
    <div class="multi_feedback_ans ans_warning hidden"></div>
    <div class="confirm_button_feedback ks_button">potwierdź</div>
    <div class="multi_summary_ans success hidden">Brawo!</div>
  </div>
</div>
<script>
localStorage.setItem('multiple_correct_answers', JSON.stringify({335: [[0, 1]]}));
localStorage.setItem('multiple_feedback',
  JSON.stringify({335: [['nie rośnie', 'maleje, dobrze']]}));
</script>
"""


def test_multi_ans_leaf_becomes_choice_with_feedback():
    elements, flags = parse_lesson(MULTI_ANS_GROUP, "x.html")
    assert not any(e.get("flagged") for e in elements)
    choices = [e for e in elements if e["type"] == "choice"]
    assert len(choices) == 1
    q = choices[0]
    assert q["multiple"] is True
    opts = q["choices"]
    assert [c["text"] for c in opts] == ["rosnący", "malejący"]
    assert [c["is_correct"] for c in opts] == [False, True]
    assert opts[0]["feedback"] == "nie rośnie"
    assert opts[1]["feedback"] == "maleje, dobrze"  # comma inside feedback kept
    # the group prompt still renders (as its own text block); math prompt kept
    joined = " ".join(str(e) for e in elements)
    assert "Wskaż monotoniczność" in joined
    assert "a_1=12" in joined
    # confirm + success chrome dropped
    assert "potwierdź" not in joined and "Brawo" not in joined


# geometria_043 shape: a leaf question with its OWN question_text and 2 correct.
MULTI_ANS_OWN_STEM = r"""
<div id="question20">
  <div class="question_text">Które zasady przystawania?</div>
  <div>
    <div class="multi_ans ks_button">KBK</div>
    <div class="multi_ans ks_button">BKB</div>
    <div class="multi_ans ks_button">KKK</div>
  </div>
  <div class="multi_feedback_ans ans_warning hidden"></div>
  <div class="confirm_button_feedback ks_button">potwierdź</div>
</div>
<script>
localStorage.setItem('multiple_correct_answers', JSON.stringify({20: [[1, 1, 0]]}));
localStorage.setItem('multiple_feedback',
  JSON.stringify({20: [['tak', 'tak', 'nie']]}));
</script>
"""


def test_multi_ans_with_own_stem_multi_correct():
    elements, flags = parse_lesson(MULTI_ANS_OWN_STEM, "x.html")
    choices = [e for e in elements if e["type"] == "choice"]
    assert len(choices) == 1
    q = choices[0]
    assert q["multiple"] is True
    assert "Które zasady przystawania" in q["stem"]
    assert [c["is_correct"] for c in q["choices"]] == [True, True, False]
    # stem is on the element, not duplicated as a separate text block
    assert not any(
        e["type"] == "text" and "Które zasady" in e.get("body", "") for e in elements
    )


# --- Image-bearing layout tables unpack to ImageElements (nh3 strips <img> from
# table cells, so a TableElement would drop the diagrams). A label cell directly
# above an image becomes that image's figcaption.
IMAGE_TABLE = r"""
<div class="table_wrapper">
<table class="my_table_noborder">
  <tr><td><strong>1</strong></td><td><strong>2</strong></td></tr>
  <tr><td><img alt="" src="static/tri_1.png"/></td>
      <td><img alt="" src="static/tri_2.png"/></td></tr>
  <tr><td><strong>3</strong></td><td></td></tr>
  <tr><td><img alt="" src="static/tri_3.png"/></td><td></td></tr>
</table>
</div>
"""


def test_image_bearing_table_unpacks_to_captioned_images():
    elements, flags = parse_lesson(IMAGE_TABLE, "x.html")
    assert not any(e["type"] == "table" for e in elements)  # not a TableElement
    imgs = [e for e in elements if e["type"] == "image"]
    assert [e["media_src"] for e in imgs] == [
        "static/tri_1.png",
        "static/tri_2.png",
        "static/tri_3.png",
    ]
    # the label directly above each image becomes its caption
    assert [e.get("figcaption") for e in imgs] == ["1", "2", "3"]
    # those label cells are consumed as captions, not left as stray text blocks
    assert not any(e["type"] == "text" and "1" in e.get("body", "") for e in elements)


# multi_ans/mult_choice whose question_text carries diagrams must render the
# images (descend the prompt) rather than flatten it into the stem (u/229 bug).
MULTI_ANS_IMAGE_STEM = r"""
<div id="question20">
  <div class="question_text">
    <p>Które trójkąty są przystające?</p>
    <div class="table_wrapper"><table class="my_table_noborder">
      <tr><td><strong>1</strong></td><td><strong>2</strong></td></tr>
      <tr><td><img alt="" src="static/t1.png"/></td>
          <td><img alt="" src="static/t2.png"/></td></tr>
    </table></div>
  </div>
  <div>
    <div class="multi_ans ks_button">para 1</div>
    <div class="multi_ans ks_button">para 2</div>
  </div>
  <div class="confirm_button_feedback ks_button">potwierdź</div>
</div>
<script>
localStorage.setItem('multiple_correct_answers', JSON.stringify({20: [[1, 0]]}));
localStorage.setItem('multiple_feedback', JSON.stringify({20: [['tak', 'nie']]}));
</script>
"""


def test_img_alone_in_paragraph_becomes_image_not_empty_text():
    # nh3 strips <img> from TextElement.body, so a <p> holding only an image used
    # to render as an empty paragraph. It must become an ImageElement.
    elements, _ = parse_lesson(
        '<p><img alt="d" src="static/diagram.png"/></p>', "x.html"
    )
    imgs = [e for e in elements if e["type"] == "image"]
    assert [e["media_src"] for e in imgs] == ["static/diagram.png"]
    # no empty/near-empty text block left behind
    assert not any(e["type"] == "text" for e in elements)


def test_img_inside_inline_div_is_extracted():
    elements, _ = parse_lesson(
        '<div style="display:inline-block"><img alt="" src="static/g.gif"/></div>',
        "x.html",
    )
    assert [e["media_src"] for e in elements if e["type"] == "image"] == [
        "static/g.gif"
    ]


def test_text_around_inline_image_keeps_order_and_text():
    elements, _ = parse_lesson(
        '<p>Zobacz <img alt="" src="static/pic.png"/> ten rysunek.</p>', "x.html"
    )
    kinds = [e["type"] for e in elements]
    assert kinds == ["text", "image", "text"]
    assert "Zobacz" in elements[0]["body"]
    assert elements[1]["media_src"] == "static/pic.png"
    assert "rysunek" in elements[2]["body"]


def test_plain_paragraph_without_image_is_single_text_block():
    # regression guard: a normal paragraph is untouched (one TextElement).
    elements, _ = parse_lesson("<p>Zwykły akapit bez obrazka.</p>", "x.html")
    texts = [e for e in elements if e["type"] == "text"]
    assert len(texts) == 1
    assert "Zwykły akapit" in texts[0]["body"]
    assert not any(e["type"] == "image" for e in elements)


def test_multi_ans_image_prompt_renders_images_not_flattened():
    elements, flags = parse_lesson(MULTI_ANS_IMAGE_STEM, "x.html")
    imgs = [e for e in elements if e["type"] == "image"]
    assert [e["media_src"] for e in imgs] == ["static/t1.png", "static/t2.png"]
    assert [e.get("figcaption") for e in imgs] == ["1", "2"]
    # the prompt text renders as its own block
    assert any(
        e["type"] == "text" and "Które trójkąty" in e.get("body", "") for e in elements
    )
    choices = [e for e in elements if e["type"] == "choice"]
    assert len(choices) == 1
    # media prompt descended -> empty stem (no "1 2" label leak)
    assert choices[0]["stem"] == ""
    assert [c["is_correct"] for c in choices[0]["choices"]] == [True, False]


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


# --- Group B #12: truth/false toggles -> ChoiceGrid (tak/nie columns) ---
TRUTH_FALSE = r"""
<div id="question20">
  <p class="question_text">Które z poniższych wielkości są wprost proporcjonalne?</p>
  <ul style="list-style: none;">
    <li>
      <div class="statement">obwód koła do średnicy</div>
      <div class="truth">tak</div>
      <div class="false">nie</div>
    </li>
    <li>
      <div class="statement">pole kwadratu do długości boku</div>
      <div class="truth">tak</div>
      <div class="false">nie</div>
    </li>
  </ul>
  <div class="confirmTF ks_button">potwierdź</div>
  <div class="success hidden">Brawo!</div>
</div>
<script>localStorage.setItem("correct_choices",
JSON.stringify({20: [1, 0]}));</script>
"""


def test_truth_false_becomes_choice_grid():
    elements, flags = parse_lesson(TRUTH_FALSE, "x.html")
    assert not any(e.get("flagged") for e in elements)
    grids = [e for e in elements if e["type"] == "choice_grid"]
    assert len(grids) == 1
    # columns come from the .truth/.false button labels (tak/nie)
    assert grids[0]["columns"] == ["tak", "nie"]
    rows = grids[0]["rows"]
    # correct_choices: 1 (truth) -> column 0, 0 (false) -> column 1
    assert [r["correct"] for r in rows] == [0, 1]
    assert "obwód" in rows[0]["statement"]
    joined = " ".join(str(e) for e in elements)
    assert "wielkości" in joined  # the prompt (question_text) is kept
    # the confirm button + success feedback are dropped as chrome
    assert "Brawo" not in joined and "potwierdź" not in joined


# --- Group B #13: mark_done -> MarkDoneElement self-tracking checklist ---
MARK_DONE = r"""
<div id="question90">
  <div class="question"></div>
  <div class="question_text">Zaznacz, kiedy zrobisz.</div>
  <div><div class="mark_done statement">pierwsze</div><input type="checkbox"/></div>
  <div><div class="mark_done statement">\(y=3x-1\)</div><input type="checkbox"/></div>
  <div><div class="mark_done statement">trzecie</div><input type="checkbox"/></div>
</div>
"""


def test_mark_done_becomes_markdone_checklist():
    elements, flags = parse_lesson(MARK_DONE, "x.html")
    assert not any(e.get("flagged") for e in elements)
    md = [e for e in elements if e["type"] == "mark_done"]
    assert len(md) == 1
    # each .mark_done.statement -> one item (get_text keeps literal \(..\) math)
    assert md[0]["items"] == ["pierwsze", r"\(y=3x-1\)", "trzecie"]
    joined = " ".join(str(e) for e in elements)
    assert "Zaznacz" in joined  # the prompt (question_text) is kept as preceding text


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


# --- Group B #8: fill_show_next -> RevealGate chain + inline FillBlank per step ---
FILL_SHOW_NEXT = r"""
<div id="question10">
  <div class="fill_steps">
    <p>Wstęp do zadania.</p>
    <div class="fill_show_next ks_button">pokaż dalej</div>
    <div class="fill_step"><p>Krok \(1\): <input class="fill_answer"></p></div>
    <div class="fill_show_next ks_button">pokaż dalej</div>
    <div class="fill_step"><p>Krok \(2\): <input class="fill_answer"></p></div>
  </div>
</div>
<script>localStorage.setItem("answers_fill_next",
JSON.stringify({10: [8, 0]}));</script>
"""


def test_fill_show_next_becomes_fill_gate_chain():
    # "Fill in & confirm": each step's blank IS the gate — answering reveals the
    # next step. No plain reveal_gate/fillblank; the fill_show_next buttons drop.
    elements, flags = parse_lesson(FILL_SHOW_NEXT, "x.html")
    assert not any(e.get("flagged") for e in elements)
    gates = [e for e in elements if e["type"] == "fill_gate"]
    assert len(gates) == 2
    assert gates[0]["answers"] == [["8"]]
    assert gates[1]["answers"] == [["0"]]
    assert "￿" in gates[0]["stem"]  # a sentinel blank token in the gate prompt
    assert not any(e["type"] in ("reveal_gate", "fillblank") for e in elements)
    assert any("Wstęp" in e.get("body", "") for e in elements if e["type"] == "text")


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


# --- Sub-spec B3: non-.switch_step content of .switch_steps is now walked ---

# A <figure> before the first .switch_step (104_geometria_3 / 090_wstep shape).
SWITCH_FIGURE_BEFORE = r"""
<div id="question60">
  <div class="switch_steps">
    <figure><img alt="" src="static/fig1.png"/></figure>
    <div class="switch_step">
      <p>Krok pierwszy.</p>
      <div class="switch_line">
        <div class="switch_value">>> wybierz >></div>
        <div class="switch_value">\(a\)</div>
        <div class="switch_value">\(b\)</div>
        <div class="switch_show_next ks_button">zatwierdź</div>
      </div>
    </div>
    <div class="switch_step hidden"><p>Krok drugi.</p></div>
  </div>
</div>
<script>localStorage.setItem("switch_answers", JSON.stringify({60: [1]}));</script>
"""


def test_switch_nonstep_figure_before_steps_emitted():
    elements, flags = parse_lesson(SWITCH_FIGURE_BEFORE, "x.html")
    assert not any(e.get("flagged") for e in elements)
    imgs = [e for e in elements if e["type"] == "image"]
    assert [e["media_src"] for e in imgs] == ["static/fig1.png"]
    # the prompt figure renders BEFORE the first gate, in document order
    order = [e["type"] for e in elements]
    assert order.index("image") < order.index("switch_gate")
    # no empty text blocks from whitespace NavigableStrings between children
    assert all(e.get("body", "").strip() for e in elements if e["type"] == "text")


# An image-TABLE stranded as the first child of switch_steps (330 shape).
SWITCH_IMAGE_TABLE = r"""
<div id="question50">
  <div class="switch_steps">
    <div class="table_wrapper">
      <table class="my_table_noborder">
        <tr><td><img alt="" src="static/k1.png"/></td>
            <td><img alt="" src="static/k2.png"/></td></tr>
      </table>
    </div>
    <div class="switch_step">
      <p>Opis.</p>
      <div class="switch_line">
        <div class="switch_value">>> wybierz >></div>
        <div class="switch_value">\(a\)</div>
        <div class="switch_show_next ks_button">zatwierdź</div>
      </div>
    </div>
    <div class="switch_step hidden"><p>Dalej.</p></div>
  </div>
</div>
<script>localStorage.setItem("switch_answers", JSON.stringify({50: [1]}));</script>
"""


def test_switch_nonstep_image_table_unpacked():
    elements, flags = parse_lesson(SWITCH_IMAGE_TABLE, "x.html")
    assert not any(e.get("flagged") for e in elements)
    assert not any(e["type"] == "table" for e in elements)  # not a TableElement
    imgs = [e for e in elements if e["type"] == "image"]
    # assert on the src SET (robust to _emit_image_table caption-folding)
    assert {e["media_src"] for e in imgs} == {"static/k1.png", "static/k2.png"}
    assert "switch_gate" in [e["type"] for e in elements]


# A bare <img> direct child (090_trygonometria_1 / 080 shape).
SWITCH_BARE_IMG = r"""
<div id="question70">
  <div class="switch_steps">
    <img alt="" src="static/bare.png"/>
    <div class="switch_step"><p>Treść.</p></div>
  </div>
</div>
"""


def test_switch_nonstep_bare_img_emitted():
    elements, _ = parse_lesson(SWITCH_BARE_IMG, "x.html")
    imgs = [e for e in elements if e["type"] == "image"]
    assert [e["media_src"] for e in imgs] == ["static/bare.png"]


# Two gated steps with a figure BETWEEN them; distinct per-gate answers so a
# gate_idx mis-thread flips the second gate's answer.
SWITCH_GATE_CONTINUITY = r"""
<div id="question80">
  <div class="switch_steps">
    <div class="switch_step">
      <p>Krok 1.</p>
      <div class="switch_line">
        <div class="switch_value">>> wybierz >></div>
        <div class="switch_value">\(p\)</div>
        <div class="switch_value">\(q\)</div>
        <div class="switch_value">\(r\)</div>
        <div class="switch_show_next ks_button">zatwierdź</div>
      </div>
    </div>
    <figure><img alt="" src="static/mid.png"/></figure>
    <div class="switch_step hidden">
      <p>Krok 2.</p>
      <div class="switch_line">
        <div class="switch_value">>> wybierz >></div>
        <div class="switch_value">\(p\)</div>
        <div class="switch_value">\(q\)</div>
        <div class="switch_value">\(r\)</div>
        <div class="switch_show_next ks_button">zatwierdź</div>
      </div>
    </div>
  </div>
</div>
<script>localStorage.setItem("switch_answers", JSON.stringify({80: [2, 1]}));</script>
"""


def test_switch_gate_continuity_with_nonstep_between():
    elements, _ = parse_lesson(SWITCH_GATE_CONTINUITY, "x.html")
    gates = [e for e in elements if e["type"] == "switch_gate"]
    assert len(gates) == 2
    # strip_lead_prompt drops the ">> wybierz >>" placeholder and decrements:
    # LAL 2 -> libli 1 (gate 0), LAL 1 -> libli 0 (gate 1). Distinct: a
    # gate_idx mis-thread (both reading answers[0]) would make gate 1 == 1.
    assert gates[0]["answer"] == 1
    assert gates[1]["answer"] == 0
    # the mid figure renders between the two gates
    assert any(e["type"] == "image" for e in elements)  # clear RED msg under master
    order = [e["type"] for e in elements]
    img_i = next(i for i, e in enumerate(elements) if e["type"] == "image")
    assert order.index("switch_gate") < img_i < len(order) - 1
    assert order[img_i + 1 :].count("switch_gate") == 1


# Regression guard for the buffer-and-flush invariant: a show_solution button
# immediately followed by its sibling .question_solution (two adjacent non-step
# children) must pair into ONE solution region, not two unmapped flags.
SWITCH_SIBLING_COUPLED = r"""
<div id="question90">
  <div class="switch_steps">
    <div class="show_solution ks_button">zobacz</div>
    <div class="question_solution hidden"><p>Rozwiązanie.</p></div>
    <div class="switch_step"><p>Krok.</p></div>
  </div>
</div>
"""


def test_switch_nonstep_sibling_coupled_pairs_into_one_region():
    elements, _ = parse_lesson(SWITCH_SIBLING_COUPLED, "x.html")
    # buffer-and-flush walks [button, solution, ...] together so _find_solution
    # pairs them into a single spoiler; per-child walking would emit two flags.
    assert sum(1 for e in elements if e["type"] == "spoiler") == 1
    assert not any(e.get("flagged") for e in elements)


# A bare <div> carrying a cycler but LACKING the switch_step class (280 shape):
# the image is recovered; the cycler renders as static content (not asserted).
SWITCH_BARE_DIV_CYCLER = r"""
<div id="question760">
  <div class="switch_steps">
    <div>
      <img alt="" src="static/wyc.png"/>
      <div class="switch_line">
        <div class="switch_value">>> wybierz >></div>
        <div class="switch_value">\(2\pi r\)</div>
      </div>
    </div>
    <div class="switch_step hidden"><p>Koniec.</p></div>
  </div>
</div>
"""


def test_switch_nonstep_bare_div_with_cycler_recovers_image():
    elements, _ = parse_lesson(SWITCH_BARE_DIV_CYCLER, "x.html")
    imgs = [e for e in elements if e["type"] == "image"]
    assert "static/wyc.png" in [e["media_src"] for e in imgs]


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


# --- Nestable spoiler (Task 5): all three spoiler sources emit nested `elements` ---


def _only_spoiler(elements):
    sp = [e for e in elements if e.get("type") == "spoiler"]
    assert len(sp) == 1, elements
    return sp[0]


def test_details_with_image_becomes_nested_spoiler_with_image_child():
    html = (
        "<body><details><summary>Solution</summary>"
        "<p>see</p><img src='fig.png' alt='f'></details></body>"
    )
    elements, _flags = parse_lesson(html, html)
    sp = _only_spoiler(elements)
    assert "elements" in sp and "body" not in sp
    kinds = [c["type"] for c in sp["elements"]]
    assert "image" in kinds


def test_show_solution_with_image_becomes_nested_spoiler():
    html = (
        "<body>"
        "<div class='show_solution'>zobacz</div>"
        "<div class='question_solution'><p>x</p><img src='a.png'></div>"
        "</body>"
    )
    elements, _flags = parse_lesson(html, html)
    sp = _only_spoiler(elements)
    assert "elements" in sp
    assert any(c["type"] == "image" for c in sp["elements"])


def test_reveal_table_row_becomes_nested_spoiler():
    html = (
        "<body><table><tr>"
        "<td>concept</td>"
        "<td class='question_solution'><p>ans</p><img src='r.png'></td>"
        "</tr></table></body>"
    )
    elements, _flags = parse_lesson(html, html)
    sp = _only_spoiler(elements)
    assert sp["label"] == "concept"
    assert any(c["type"] == "image" for c in sp["elements"])


def test_details_inside_solution_is_inlined_not_nested_spoiler():
    # No-nest-container mode: an inner <details> must NOT emit a nested spoiler dict.
    html = (
        "<body>"
        "<div class='show_solution'>zobacz</div>"
        "<div class='question_solution'>"
        "<p>outer</p><details><summary>inner</summary><p>deep</p></details>"
        "</div></body>"
    )
    elements, _flags = parse_lesson(html, html)
    sp = _only_spoiler(elements)  # exactly ONE spoiler total (no nested one)
    child_types = [c["type"] for c in sp["elements"]]
    assert "spoiler" not in child_types  # inner disclosure inlined
    # inner content is present (heading + deep text among the inlined children)
    assert any(c["type"] == "text" for c in sp["elements"])


def test_show_solution_inside_solution_is_inlined_not_nested_spoiler():
    # A show_solution button + its solution INSIDE a question_solution cell must
    # NOT emit a depth-2 spoiler dict (which the loader guard would abort on).
    html = (
        "<body>"
        "<div class='show_solution'>outer</div>"
        "<div class='question_solution'>"
        "<p>lead</p>"
        "<div class='show_solution'>inner</div>"
        "<div class='question_solution'><p>deep</p></div>"
        "</div></body>"
    )
    elements, _flags = parse_lesson(html, html)
    sp = _only_spoiler(elements)  # exactly ONE spoiler (the inner one inlined)
    assert "spoiler" not in [c["type"] for c in sp["elements"]]
    assert any(c["type"] == "text" for c in sp["elements"])


def test_reveal_table_inside_solution_is_inlined_not_nested_spoiler():
    # A reveal-<table> INSIDE a question_solution cell must inline its rows, not
    # emit nested spoiler dicts.
    html = (
        "<body>"
        "<div class='show_solution'>outer</div>"
        "<div class='question_solution'>"
        "<table><tr><td>row</td>"
        "<td class='question_solution'><p>ans</p></td></tr></table>"
        "</div></body>"
    )
    elements, _flags = parse_lesson(html, html)
    sp = _only_spoiler(elements)  # exactly ONE spoiler total
    assert "spoiler" not in [c["type"] for c in sp["elements"]]


def test_r3_reveal_row_prompt_image_extracted_before_spoiler():
    # B1: the row's visible .question_answer prompt (with an <img>) must be emitted
    # as a visible ImageElement BEFORE the spoiler; the .question_solution image
    # stays inside the spoiler (unchanged).
    html = (
        '<table class="my_table_TL"><tr>'
        '<td><div class="show_solution ks_button">zobacz</div></td>'
        '<td><div class="question_answer"><img src="static/p.png"></div>'
        '<div class="question_solution hidden">sol <img src="static/s.png"></div>'
        "</td></tr></table>"
    )
    elements, _ = parse_lesson(html, "x.html")
    types = [e["type"] for e in elements]
    assert "image" in types and "spoiler" in types
    assert types.index("image") < types.index("spoiler")  # prompt before the reveal
    prompt = next(e for e in elements if e["type"] == "image")
    assert prompt["media_src"] == "static/p.png"
    sp = next(e for e in elements if e["type"] == "spoiler")
    sol_imgs = [
        c for c in sp["elements"] if isinstance(c, dict) and c.get("type") == "image"
    ]
    assert any(c["media_src"] == "static/s.png" for c in sol_imgs)


def test_whitespace_only_block_is_dropped():
    # a whitespace-only <p> (e.g. <p>\n</p>) must NOT become an empty TextElement
    elements, _ = parse_lesson("<p>\n</p><p>Treść.</p>", "x.html")
    texts = [e for e in elements if e["type"] == "text"]
    assert len(texts) == 1
    assert "Treść" in texts[0]["body"]


def test_inline_math_only_block_is_kept():
    # a block whose only content is inline math must survive (regression guard)
    elements, _ = parse_lesson(r"<p>\(a\)</p>", "x.html")
    texts = [e for e in elements if e["type"] == "text"]
    assert len(texts) == 1
    assert "a" in texts[0]["body"]
