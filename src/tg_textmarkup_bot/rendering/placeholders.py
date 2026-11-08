"""Detect and substitute ``{placeholder}`` values in drafts.

Substitution happens on plain-text fields only; the renderer escapes
everything afterwards, so user-provided values can never inject markup.
"""

import re

from tg_textmarkup_bot.rendering.model import Draft

PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def find_placeholders(draft: Draft) -> list[str]:
    """Return placeholder names in order of first appearance, without duplicates."""
    names: list[str] = []

    def scan(value: str | None) -> None:
        if not value:
            return
        for match in PLACEHOLDER_RE.finditer(value):
            name = match.group(1)
            if name not in names:
                names.append(name)

    for segment in draft.segments:
        scan(segment.text)
        scan(segment.link_url)
        for button in segment.buttons:
            scan(button.text)
            scan(button.value)
    scan(draft.photo)
    for row in draft.inline_buttons:
        for button in row:
            scan(button.text)
            scan(button.value)
    return names


def substitute(draft: Draft, values: dict[str, str]) -> Draft:
    """Return a copy of the draft with placeholders replaced by plain values."""
    result = draft.model_copy(deep=True)

    def replace(value: str) -> str:
        return PLACEHOLDER_RE.sub(lambda m: values.get(m.group(1), m.group(0)), value)

    for segment in result.segments:
        segment.text = replace(segment.text)
        if segment.link_url is not None:
            segment.link_url = replace(segment.link_url)
        for button in segment.buttons:
            button.text = replace(button.text)
            button.value = replace(button.value)
    if result.photo is not None:
        result.photo = replace(result.photo)
    for row in result.inline_buttons:
        for button in row:
            button.text = replace(button.text)
            button.value = replace(button.value)
    return result


def placeholder_in_photo(photo: str | None, name: str) -> bool:
    """True when the placeholder name occurs inside the photo field."""
    return bool(photo and f"{{{name}}}" in photo)
