import pytest

from tg_textmarkup_bot.rendering.model import ButtonType, Format
from tg_textmarkup_bot.rendering.render import InvalidUrlError
from tg_textmarkup_bot.rendering.syntax import parse, parse_button_rows


def texts(segments):
    return [s.text for s in segments if not s.buttons]


def test_plain_text():
    segments = parse("hola mundo")
    assert len(segments) == 1
    assert segments[0].text == "hola mundo"
    assert segments[0].formats == set()
    assert segments[0].block == "p"


def test_bold_and_italic():
    segments = parse("*negrita* y _cursiva_")
    bold, space, italic = segments
    assert bold.text == "negrita"
    assert bold.formats == {Format.BOLD}
    assert space.text == " y "
    assert italic.text == "cursiva"
    assert italic.formats == {Format.ITALIC}


def test_nested_formats():
    segments = parse("*negrita con _cursiva_ adentro*")
    assert segments[0].formats == {Format.BOLD}
    assert segments[1].formats == {Format.BOLD, Format.ITALIC}
    assert segments[1].text == "cursiva"


def test_spoiler_underline_strike():
    segments = parse("||oculto|| __sub__ ~tach~")
    assert segments[0].formats == {Format.SPOILER}
    assert segments[2].formats == {Format.UNDERLINE}
    assert segments[4].formats == {Format.STRIKE}


def test_inline_code():
    segments = parse("usa `x = 1` acá")
    assert segments[1].formats == {Format.CODE}
    assert segments[1].text == "x = 1"


def test_code_drops_other_formats():
    # code wins: parser attaches only CODE when written inside backticks
    segments = parse("`*no negrita*`")
    assert segments[0].formats == {Format.CODE}
    assert segments[0].text == "*no negrita*"


def test_link():
    segments = parse("[click](https://example.com)")
    assert segments[0].link_url == "https://example.com"
    assert segments[0].text == "click"


def test_link_label_keeps_formats():
    segments = parse("*[importante](https://example.com)*")
    assert segments[0].link_url == "https://example.com"
    assert Format.BOLD in segments[0].formats


def test_escaped_asterisk_is_literal():
    segments = parse("\\*no es negrita\\*")
    assert "".join(texts(segments)) == "*no es negrita*"
    assert all(Format.BOLD not in s.formats for s in segments)


def test_blockquote():
    segments = parse("> una cita\n> dos líneas")
    assert all(s.block == "quote" for s in segments)
    assert "".join(texts(segments)) == "una cita\ndos líneas"


def test_code_fence_with_lang():
    segments = parse("```python\nx = 1\n```")
    assert segments[0].block == "pre"
    assert segments[0].lang == "python"
    assert segments[0].text == "x = 1"


def test_code_fence_without_lang():
    segments = parse("```\nsin lenguaje\n```")
    assert segments[0].lang is None


def test_mixed_blocks():
    segments = parse("párrafo\n```js\nlet a = 1\n```\n> cita")
    blocks = [s.block for s in segments]
    assert "p" in blocks
    assert "pre" in blocks
    assert "quote" in blocks


def test_in_text_button_default_is_url():
    segments = parse("[[Sitio web|https://example.com]]")
    assert len(segments) == 1
    button = segments[0].buttons[0]
    assert button.text == "Sitio web"
    assert button.type == ButtonType.URL
    assert button.value == "https://example.com"


def test_in_text_button_prefixes():
    segments = parse("[[A|callback:ping]]\n[[B|copy:hola]]\n[[C|switch:query]]")
    types = [s.buttons[0].type for s in segments]
    values = [s.buttons[0].value for s in segments]
    assert types == [ButtonType.CALLBACK, ButtonType.COPY_TEXT, ButtonType.SWITCH_INLINE]
    assert values == ["ping", "hola", "query"]


def test_in_text_button_requires_whole_line():
    # line-level construct only: mid-line [[..|..]] stays literal text
    segments = parse("texto [[btn|x]] resto")
    assert not any(s.buttons for s in segments)
    assert "[[btn|x]] resto" in "".join(texts(segments))


def test_button_rows_basic():
    rows = parse_button_rows("Sitio | https://example.com")
    assert len(rows) == 1
    assert rows[0][0].text == "Sitio"
    assert rows[0][0].type == ButtonType.URL


def test_button_rows_blank_line_starts_new_row():
    rows = parse_button_rows("A | https://a.com\n\nB | https://b.com")
    assert len(rows) == 2


def test_button_rows_chunked_at_eight():
    lines = "\n".join(f"B{i} | https://example.com/{i}" for i in range(10))
    rows = parse_button_rows(lines)
    assert [len(r) for r in rows] == [8, 2]


def test_button_rows_callback_prefix():
    rows = parse_button_rows("Ping | callback:ping")
    assert rows[0][0].type == ButtonType.CALLBACK
    assert rows[0][0].value == "ping"


def test_button_rows_missing_pipe_raises():
    with pytest.raises(ValueError, match="Falta"):
        parse_button_rows("sin separador")


def test_button_rows_empty_value_raises():
    with pytest.raises(ValueError, match="incompleto"):
        parse_button_rows("Texto | ")


def test_button_rows_invalid_url_raises():
    with pytest.raises(InvalidUrlError):
        parse_button_rows("Malo | javascript:alert(1)")
