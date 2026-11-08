from tg_textmarkup_bot.rendering.model import ButtonSpec, ButtonType, Draft, Segment
from tg_textmarkup_bot.rendering.placeholders import (
    find_placeholders,
    placeholder_in_photo,
    substitute,
)
from tg_textmarkup_bot.rendering.render import render_html


def test_find_placeholders_in_text():
    draft = Draft(segments=[Segment(text="Hola {nombre}, bienvenido a {sitio}")])
    assert find_placeholders(draft) == ["nombre", "sitio"]


def test_find_placeholders_dedupes_and_keeps_order():
    draft = Draft(segments=[Segment(text="{b} {a} {b}")])
    assert find_placeholders(draft) == ["b", "a"]


def test_find_placeholders_scans_buttons_and_photo():
    draft = Draft(
        segments=[Segment(text="x", buttons=[ButtonSpec(text="Ir a {lugar}", value="https://e.com/{lugar}")])],
        photo="https://img.com/{id}.jpg",
        inline_buttons=[[ButtonSpec(text="Click", value="callback:{accion}")]],
    )
    names = find_placeholders(draft)
    assert "lugar" in names
    assert "id" in names
    assert "accion" in names


def test_find_placeholders_ignores_non_placeholder_braces():
    draft = Draft(segments=[Segment(text="usa {123} y {con espacios}")])
    assert find_placeholders(draft) == []


def test_substitute_replaces_values():
    draft = Draft(segments=[Segment(text="Hola {nombre}")])
    result = substitute(draft, {"nombre": "Ana"})
    assert result.segments[0].text == "Hola Ana"
    # original untouched
    assert draft.segments[0].text == "Hola {nombre}"


def test_substitute_leaves_unknown_placeholders():
    draft = Draft(segments=[Segment(text="{a} y {b}")])
    result = substitute(draft, {"a": "1"})
    assert result.segments[0].text == "1 y {b}"


def test_substitute_in_photo_and_inline_buttons():
    draft = Draft(
        photo="https://img.com/{id}.jpg",
        inline_buttons=[[ButtonSpec(text="Ir", value="https://x.com/{id}")]],
    )
    result = substitute(draft, {"id": "42"})
    assert result.photo == "https://img.com/42.jpg"
    assert result.inline_buttons[0][0].value == "https://x.com/42"


def test_placeholder_in_photo():
    assert placeholder_in_photo("https://img.com/{id}.jpg", "id")
    assert not placeholder_in_photo("https://img.com/1.jpg", "id")
    assert not placeholder_in_photo(None, "id")


def test_substituted_markup_is_escaped_by_renderer():
    # injection safety: value with <b> or quotes must come out escaped
    draft = Draft(segments=[Segment(text="Hola {nombre}")])
    result = substitute(draft, {"nombre": '<b>hacked</b> & "x"'})
    html_out = render_html(result)
    assert "<b>hacked" not in html_out
    assert "&lt;b&gt;hacked&lt;/b&gt; &amp; &quot;x&quot;" in html_out
