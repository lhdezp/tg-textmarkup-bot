"""Lightweight markup parser: plain user text -> structured segments.

Inline syntax:
    *bold*  _italic_  ||spoiler||  __underline__  ~strike~  `code`
    [text](https://example.com)   \\* -> literal asterisk
Block syntax (whole line):
    ```lang ... ```   code block
    > text            blockquote
    [[Label|value]]   in-text button row; value prefixes:
                      callback:...  copy:...  switch:... (default: url)
"""

import re

from tg_textmarkup_bot.rendering.model import ButtonSpec, ButtonType, Format, Segment
from tg_textmarkup_bot.rendering.render import validate_url

Run = tuple[str, frozenset[Format], str | None]

_BUTTON_ROW_RE = re.compile(r"^\[\[(.+?)\|(.+?)\]\]$")
_LINK_RE = re.compile(r"^\[([^\]]+)\]\(([^)\s]+)\)")

_FORMAT_OPENERS: list[tuple[str, Format]] = [
    ("||", Format.SPOILER),
    ("__", Format.UNDERLINE),
    ("*", Format.BOLD),
    ("_", Format.ITALIC),
    ("~", Format.STRIKE),
]

_BUTTON_TYPE_PREFIXES: tuple[tuple[str, ButtonType], ...] = (
    ("callback:", ButtonType.CALLBACK),
    ("copy:", ButtonType.COPY_TEXT),
    ("switch:", ButtonType.SWITCH_INLINE),
)


def parse(text: str) -> list[Segment]:
    """Parse light markup into structured segments."""
    segments: list[Segment] = []
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()

    i = 0
    while i < len(lines):
        line = lines[i]

        if line.startswith("```"):
            lang = line[3:].strip() or None
            i += 1
            body: list[str] = []
            while i < len(lines) and not lines[i].startswith("```"):
                body.append(lines[i])
                i += 1
            if i < len(lines):
                i += 1
            segments.append(Segment(block="pre", lang=lang, text="\n".join(body)))
            continue

        if line.startswith(">"):
            quote_lines: list[str] = []
            while i < len(lines) and lines[i].startswith(">"):
                quoted = lines[i][1:]
                if quoted.startswith(" "):
                    quoted = quoted[1:]
                quote_lines.append(quoted)
                i += 1
            runs: list[Run] = []
            _parse_inline("\n".join(quote_lines), frozenset(), None, runs)
            segments.extend(_runs_to_segments(runs, block="quote"))
            continue

        match = _BUTTON_ROW_RE.match(line)
        if match:
            segments.append(_button_segment(match.group(1).strip(), match.group(2).strip()))
            i += 1
            continue

        plain: list[str] = []
        while i < len(lines):
            candidate = lines[i]
            if (
                candidate.startswith("```")
                or candidate.startswith(">")
                or _BUTTON_ROW_RE.match(candidate)
            ):
                break
            plain.append(candidate)
            i += 1
        runs = []
        _parse_inline("\n".join(plain), frozenset(), None, runs)
        segments.extend(_runs_to_segments(runs, block="p"))

    while segments and segments[-1].block == "p" and not segments[-1].text and not (
        segments[-1].buttons
    ):
        segments.pop()
    return segments


def _button_segment(label: str, raw: str) -> Segment:
    value = raw
    btype = ButtonType.URL
    for prefix, candidate in _BUTTON_TYPE_PREFIXES:
        if value.startswith(prefix):
            value = value[len(prefix) :]
            btype = candidate
            break
    return Segment(buttons=[ButtonSpec(text=label, type=btype, value=value.strip())])


def parse_button_rows(text: str) -> list[list[ButtonSpec]]:
    """Parse classic under-message buttons.

    One button per line as ``Text | value``; a blank line starts a new row.
    Value prefixes: ``callback:``, ``copy:``, ``switch:`` (default: url).
    Rows longer than 8 buttons are chunked automatically.
    """
    rows: list[list[ButtonSpec]] = []
    for paragraph in text.split("\n\n"):
        if not paragraph.strip():
            continue
        row: list[ButtonSpec] = []
        for line in paragraph.split("\n"):
            line = line.strip()
            if not line:
                continue
            if "|" not in line:
                raise ValueError(f"Falta «|» en el botón: {line!r} (formato: Texto | url)")
            label, _, raw_value = line.partition("|")
            label = label.strip()
            raw_value = raw_value.strip()
            if not label or not raw_value:
                raise ValueError(f"Botón incompleto: {line!r} (formato: Texto | url)")
            value = raw_value
            btype = ButtonType.URL
            for prefix, candidate in _BUTTON_TYPE_PREFIXES:
                if value.startswith(prefix):
                    value = value[len(prefix) :]
                    btype = candidate
                    break
            if btype is ButtonType.URL:
                validate_url(value)
            row.append(ButtonSpec(text=label, type=btype, value=value))
        if row:
            for start in range(0, len(row), 8):
                rows.append(row[start : start + 8])
    return rows


def _runs_to_segments(
    runs: list[Run], block: str, lang: str | None = None
) -> list[Segment]:
    segments: list[Segment] = []
    for text, formats, link_url in runs:
        if not text:
            continue
        if (
            segments
            and segments[-1].formats == set(formats)
            and segments[-1].link_url == link_url
        ):
            segments[-1].text += text
        else:
            segments.append(
                Segment(
                    text=text,
                    formats=set(formats),
                    link_url=link_url,
                    block=block,  # type: ignore[arg-type]
                    lang=lang,
                )
            )
    return segments


def _parse_inline(
    text: str,
    formats: frozenset[Format],
    link_url: str | None,
    out: list[Run],
) -> None:
    i = 0
    n = len(text)
    buf_start = 0

    def flush(end: int) -> None:
        nonlocal buf_start
        if end > buf_start:
            out.append((text[buf_start:end], formats, link_url))
            buf_start = end

    while i < n:
        char = text[i]

        if char == "\\" and i + 1 < n:
            flush(i)
            out.append((text[i + 1], formats, link_url))
            i += 2
            buf_start = i
            continue

        # Emit pending literal text before a construct may append its own runs.
        flush(i)
        consumed = _try_inline_construct(text, i, formats, link_url, out)
        if consumed:
            i += consumed
            buf_start = i
            continue

        i += 1

    flush(n)


def _try_inline_construct(
    text: str,
    i: int,
    formats: frozenset[Format],
    link_url: str | None,
    out: list[Run],
) -> int:
    """Try to consume a markup construct starting at index i.

    Returns the number of consumed characters, or 0 if nothing matched.
    """
    remaining = text[i:]

    if remaining.startswith("[["):
        return 0  # in-text buttons are line-level constructs only

    if remaining.startswith("`") and Format.CODE not in formats:
        close = text.find("`", i + 1)
        if close == -1:
            return 0
        out.append((text[i + 1 : close], formats | {Format.CODE}, link_url))
        return close + 1 - i

    if remaining.startswith("["):
        match = _LINK_RE.match(remaining)
        if match and link_url is None:
            label, url = match.group(1), match.group(2)
            _parse_inline(label, formats, url, out)
            return match.end()
        return 0

    for delimiter, fmt in _FORMAT_OPENERS:
        if remaining.startswith(delimiter):
            if fmt in formats:
                return 0  # no nested same-format; treat as literal
            close = text.find(delimiter, i + len(delimiter))
            if close == -1:
                return 0
            inner = text[i + len(delimiter) : close]
            _parse_inline(inner, formats | {fmt}, link_url, out)
            return close + len(delimiter) - i

    return 0
