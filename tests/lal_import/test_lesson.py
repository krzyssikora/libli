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
