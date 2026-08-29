import pytest

from core.public_pages import PAGES
from core.public_pages import normalize_lang
from core.public_pages import render_markdown
from core.public_pages import substitute_tokens


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("en", "en"),
        ("pl", "pl"),
        ("pl-PL", "pl"),
        ("PL-pl", "PL"),
        ("", "en"),
        (None, "en"),
    ],
)
def test_normalize_lang(raw, expected):
    assert normalize_lang(raw) == expected


def test_pages_registry_shape():
    assert set(PAGES) == {"privacy", "getting-started"}
    assert PAGES["privacy"].path == "public/privacy.md"
    assert PAGES["getting-started"].path == "public/getting-started.md"
    for page in PAGES.values():
        assert str(page.title)
        assert str(page.description)


def test_table_survives_sanitisation():
    html = render_markdown("| a | b |\n| --- | --- |\n| 1 | 2 |\n")
    assert "<table>" in html
    assert "<td>1</td>" in html


def test_deep_heading_survives():
    assert "<h5>Deep</h5>" in render_markdown("##### Deep\n")


def test_two_space_line_break_survives():
    assert "<br" in render_markdown("a  \nb\n")


def test_script_is_stripped():
    html = render_markdown("<script>alert(1)</script>ok\n")
    assert "<script" not in html
    assert "alert(1)" not in html


def test_ftp_href_is_stripped_but_anchor_remains():
    # nh3 with a restricted url_schemes drops the href ATTRIBUTE and keeps the
    # element. Asserting `"<a" not in html` would be red on a correct build.
    html = render_markdown("[y](ftp://h/f)\n")
    assert "ftp:" not in html
    assert "<a" in html
    assert ">y</a>" in html


def test_javascript_href_does_not_survive():
    # Regression only: nh3 blocks javascript: by DEFAULT, so this passes with or
    # without PUBLIC_PAGE_URL_SCHEMES. Kept knowingly; the ftp test is the one
    # that actually kills the mutant.
    assert "javascript:" not in render_markdown("[j](javascript:alert(1))\n")


def test_image_is_excluded_on_purpose():
    assert "<img" not in render_markdown("![alt](https://example.com/a.png)\n")


def test_sanitiser_does_not_raise_on_a_link():
    # Guards the pinned attribute set: including "rel" raises ValueError on EVERY
    # call, because nh3 sets link_rel by default.
    html = render_markdown("[y](https://example.com)\n")
    assert 'rel="noopener noreferrer"' in html


BASE_CFG = {
    "name": "Greenfield School",
    "controller_name": "",
    "controller_address": "",
    "contact_email": "",
    "supervisory_authority": "",
    "notification_retention_days": 90,
    "demo_instance": False,
}


def cfg(**over):
    return {**BASE_CFG, **over}


def render(source, **over):
    return substitute_tokens(render_markdown(source), cfg(**over))


def test_delimiters_are_re_emitted():
    # As-pinned-wrongly this yields "<pHello Greenfield School/p>".
    out = render("Hello {libli:site_name}\n")
    assert out == "<p>Hello Greenfield School</p>"


def test_controller_name_falls_back_to_site_name():
    assert "Greenfield School" in render("{libli:controller_name}\n")


def test_controller_name_is_escaped():
    out = render("{libli:controller_name}\n", controller_name="A <b>B</b>")
    assert "<b>" not in out
    assert "&lt;b&gt;" in out


def test_backslash_group_reference_does_not_raise():
    # A string replacement would raise re.error or emit a capture group here.
    out = render("{libli:controller_name}\n", controller_name=r"A\1B")
    assert r"A\1B" in out


def test_unknown_token_renders_literally():
    assert "{libli:nope}" in render("{libli:nope}\n")


def test_retention_phrase_at_default_and_zero():
    assert "after 90 days" in render("{libli:retention_phrase}\n")
    assert "only when the item they refer to is removed" in render(
        "{libli:retention_phrase}\n", notification_retention_days=0
    )


def test_supervisory_authority_fallback():
    assert "your national data protection authority" in render(
        "{libli:supervisory_authority}\n"
    )
    assert "UODO" in render(
        "{libli:supervisory_authority}\n", supervisory_authority="UODO"
    )


def test_contact_email_fallback():
    assert "the person who runs this site" in render("{libli:contact_email}\n")
    assert "dpo@x.pl" in render("{libli:contact_email}\n", contact_email="dpo@x.pl")


def test_embed_domains_normalised_and_deduped(settings):
    settings.ALLOWED_EMBED_DOMAINS = ["www.youtube.com", "youtube.com", "youtu.be"]
    out = render("{libli:embed_domains}\n")
    assert "youtube.com" in out
    assert "www.youtube.com" not in out
    assert out.count("youtube.com") == 1


def test_embed_domains_empty_renders_a_phrase(settings):
    settings.ALLOWED_EMBED_DOMAINS = []
    assert "no embed providers are enabled" in render("{libli:embed_domains}\n")


def test_demo_notice_block_present_and_absent():
    on = render("a\n\n{libli:demo_notice}\n\nb\n", demo_instance=True)
    assert "public-page__notice" in on
    off = render("a\n\n{libli:demo_notice}\n\nb\n", demo_instance=False)
    assert "public-page__notice" not in off
    assert "<p></p>" not in off  # the WHOLE paragraph goes, not just the token
    assert "{libli:demo_notice}" not in off


def test_controller_address_block_set_and_blank():
    on = render(
        "{libli:controller_address}\n",
        controller_address="Ul. Kwiatowa 1\r\n00-001 Warszawa",
    )
    assert "<p>Ul. Kwiatowa 1<br>00-001 Warszawa</p>" in on
    assert "\r" not in on  # CRLF normalised BEFORE nl2br
    off = render("x\n\n{libli:controller_address}\n\ny\n")
    assert "<p></p>" not in off
    assert "{libli:controller_address}" not in off


def test_block_pass_uses_a_function_replacement():
    # The block pass builds its replacement with `lambda m, v=value: v`. A string
    # replacement there would interpret \\1 in an admin-entered address. Only a
    # backslash-group in controller_address distinguishes the two.
    out = render("{libli:controller_address}\n", controller_address=r"Ul. A\\1 B")
    assert r"Ul. A\\1 B" in out


def test_block_tokens_are_not_in_the_inline_map():
    # A misplaced block token must fall to the UNKNOWN branch (literal text),
    # not be substituted with escaped markup.
    out = render("- {libli:demo_notice}\n", demo_instance=True)
    assert "{libli:demo_notice}" in out
    assert "&lt;p" not in out


def test_token_in_an_href_is_left_literal():
    out = render("[mail](mailto:{libli:contact_email})\n", contact_email="dpo@x.pl")
    assert "mailto:{libli:contact_email}" in out
    assert "mailto:dpo@x.pl" not in out


def test_token_after_a_raw_gt_in_a_title_IS_substituted():
    # Documented, accepted residual risk: nh3 leaves a raw > unescaped inside an
    # attribute, which ends the >...< run early. The value is still escaped, so
    # it cannot break out of the quotes. Asserting the opposite would be RED.
    out = render(
        '[x](https://e.com "a > {libli:contact_email}")\n',
        contact_email="dpo@x.pl",
    )
    assert "dpo@x.pl" in out
