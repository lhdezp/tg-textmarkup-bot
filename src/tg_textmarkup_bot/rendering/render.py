"""Render structured drafts to Telegram HTML (classic path) or rich HTML."""

import html
import re
from urllib.parse import urlparse

from tg_textmarkup_bot.rendering.model import ButtonSpec, ButtonType, Draft, Format, Segment

_ALLOWED_SCHEMES = {"http", "https", "tg", "mailto", "tel"}
_LANG_RE = re.compile(r"[A-Za-z0-9_+#.-]+")
_FORMAT_ORDER = (Format.BOLD, Format.ITALIC, Format.UNDERLINE, Format.STRIKE, Format.SPOILER)

_FORMAT_TAGS: dict[Format, str] = {
    Format.BOLD: "b",
    Format.ITALIC: "i",
    Format.UNDERLINE: "u",
    Format.STRIKE: "s",
    Format.SPOILER: "tg-spoiler",
}


class InvalidUrlError(ValueError):
    pass


def validate_url(url: str) -> str:
    cleaned = url.strip()
    parsed = urlparse(cleaned)
    scheme = parsed.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise InvalidUrlError(
            f"URL no válida: {cleaned!r}. Usá http://, https://, tg://, mailto: o tel:"
        )
    if scheme in ("http", "https", "tg") and not parsed.netloc:
        raise InvalidUrlError(f"URL no válida: {cleaned!r} (falta el dominio)")
    return cleaned


def truncate_bytes(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def render_html(draft: Draft, *, photo_id: str | None = None) -> str:
    """Render the draft to HTML.

    ``photo_id`` is only used on the rich path: when set, an ``<img>`` block
    referencing ``tg://photo?id=<photo_id>`` is emitted as the first block.
    """
    parts: list[str] = []
    if photo_id:
        parts.append(f'<img src="tg://photo?id={photo_id}"/>')
    for segment in draft.segments:
        parts.append(_render_segment(segment))
    return "".join(parts)


def _render_segment(segment: Segment) -> str:
    if segment.buttons:
        inner = "".join(_render_tg_button(button) for button in segment.buttons)
        return f"<tg-button-row>{inner}</tg-button-row>"

    text = html.escape(segment.text)

    if segment.block == "pre":
        cls = ""
        if segment.lang and _LANG_RE.fullmatch(segment.lang):
            cls = f' class="language-{segment.lang}"'
        return f"<pre><code{cls}>{text}</code></pre>"

    if Format.CODE in segment.formats:
        # Telegram does not allow code to nest (or be nested in) other entities.
        inner = f"<code>{text}</code>"
    else:
        inner = text
        if segment.link_url:
            href = html.escape(validate_url(segment.link_url), quote=True)
            inner = f'<a href="{href}">{inner}</a>'
        for fmt in _FORMAT_ORDER:
            if fmt in segment.formats:
                inner = f"<{_FORMAT_TAGS[fmt]}>{inner}</{_FORMAT_TAGS[fmt]}>"

    if segment.block == "quote":
        return f"<blockquote>{inner}</blockquote>"
    return inner


def _render_tg_button(button: ButtonSpec) -> str:
    label = html.escape(button.text)
    if button.type == ButtonType.URL:
        url = html.escape(validate_url(button.value), quote=True)
        return f'<tg-button type="url" url="{url}">{label}</tg-button>'
    if button.type == ButtonType.CALLBACK:
        data = html.escape(truncate_bytes(button.value, 60), quote=True)
        return f'<tg-button type="callback_data" data="{data}">{label}</tg-button>'
    if button.type == ButtonType.COPY_TEXT:
        value = html.escape(truncate_bytes(button.value, 200), quote=True)
        return f'<tg-button type="copy_text" text="{value}">{label}</tg-button>'
    query = html.escape(truncate_bytes(button.value, 60), quote=True)
    return f'<tg-button type="switch_inline_query" query="{query}">{label}</tg-button>'
