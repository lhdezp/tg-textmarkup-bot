import pytest

from tg_textmarkup_bot.rendering.model import ButtonSpec, ButtonType, Draft, Format, Segment
from tg_textmarkup_bot.rendering.render import (
    InvalidUrlError,
    render_html,
    truncate_bytes,
    validate_url,
)


def draft(*segments: Segment) -> Draft:
    return Draft(segments=list(segments))


def test_plain_text_is_escaped():
    html_out = render_html(draft(Segment(text="a < b & c")))
    assert html_out == "a &lt; b &amp; c"


def test_bold_tags():
    html_out = render_html(draft(Segment(text="hola", formats={Format.BOLD})))
    assert html_out == "<b>hola</b>"


def test_nested_format_order_stable():
    seg = Segment(text="x", formats={Format.SPOILER, Format.BOLD})
    html_out = render_html(draft(seg))
    assert html_out == "<tg-spoiler><b>x</b></tg-spoiler>"


def test_inline_code_ignores_other_formats():
    seg = Segment(text="*literal*", formats={Format.CODE, Format.BOLD})
    html_out = render_html(draft(seg))
    assert html_out == "<code>*literal*</code>"


def test_link_rendered_and_validated():
    seg = Segment(text="click", link_url="https://example.com/a?b=1")
    html_out = render_html(draft(seg))
    assert html_out == '<a href="https://example.com/a?b=1">click</a>'


def test_link_rejects_bad_scheme():
    seg = Segment(text="x", link_url="javascript:alert(1)")
    with pytest.raises(InvalidUrlError):
        render_html(draft(seg))


def test_pre_with_lang():
    seg = Segment(block="pre", lang="python", text="x = 1")
    html_out = render_html(draft(seg))
    assert html_out == '<pre><code class="language-python">x = 1</code></pre>'


def test_pre_lang_is_sanitized():
    seg = Segment(block="pre", lang='py" onload="x', text="x")
    html_out = render_html(draft(seg))
    assert "onload" not in html_out
    assert html_out.startswith("<pre><code>")


def test_quote_block():
    seg = Segment(block="quote", text="cita")
    assert render_html(draft(seg)) == "<blockquote>cita</blockquote>"


def test_render_with_photo_id_emits_img():
    html_out = render_html(draft(Segment(text="hola")), photo_id="m1")
    assert html_out.startswith('<img src="tg://photo?id=m1"/>')
    assert "hola" in html_out


def test_url_button():
    seg = Segment(buttons=[ButtonSpec(text="Ir", value="https://example.com")])
    html_out = render_html(draft(seg))
    assert html_out == '<tg-button-row><tg-button type="url" url="https://example.com">Ir</tg-button></tg-button-row>'


def test_callback_button_truncated_to_60_bytes():
    seg = Segment(buttons=[ButtonSpec(text="B", type=ButtonType.CALLBACK, value="x" * 100)])
    html_out = render_html(draft(seg))
    assert "x" * 60 in html_out
    assert "x" * 61 not in html_out


def test_copy_text_button():
    seg = Segment(buttons=[ButtonSpec(text="Copiar", type=ButtonType.COPY_TEXT, value="hola")])
    html_out = render_html(draft(seg))
    assert 'type="copy_text"' in html_out
    assert 'text="hola"' in html_out


def test_switch_inline_button():
    seg = Segment(buttons=[ButtonSpec(text="Share", type=ButtonType.SWITCH_INLINE, value="q")])
    html_out = render_html(draft(seg))
    assert 'type="switch_inline_query"' in html_out


def test_validate_url_accepts_allowed_schemes():
    for url in ("https://a.b", "http://a.b", "tg://resolve?domain=x", "mailto:a@b.c", "tel:+123"):
        assert validate_url(url) == url


def test_validate_url_requires_netloc_for_http():
    with pytest.raises(InvalidUrlError):
        validate_url("https://")


def test_truncate_bytes_keeps_short_values():
    assert truncate_bytes("hola", 10) == "hola"


def test_truncate_bytes_cuts_multibyte_safely():
    result = truncate_bytes("ñññññ", 4)  # each ñ is 2 bytes
    assert result == "ññ"
