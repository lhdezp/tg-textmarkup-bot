"""Bot UI keyboards: editor screens and the message's own buttons."""

from aiogram.types import CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup

from tg_textmarkup_bot.callbacks import EditorCB
from tg_textmarkup_bot.rendering.model import ButtonSpec, ButtonType, Draft, Format
from tg_textmarkup_bot.rendering.render import truncate_bytes, validate_url

DEMO_CALLBACK_PREFIX = "demo:"


def _btn(text: str, action: str, idx: int = -1, arg: str = "") -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=EditorCB(action=action, idx=idx, arg=arg).pack())


def start_compose_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("✍️ Escribir con sintaxis", "syntax"), _btn("🎛 Por fragmentos", "add_text")],
            [_btn("🖼 Foto", "photo"), _btn("⌨️ Botones", "buttons")],
            [_btn("❓ Ayuda", "help"), _btn("✖ Cancelar", "cancel")],
        ]
    )


def editor_keyboard(draft: Draft) -> InlineKeyboardMarkup:
    photo_btn = (
        _btn("🗑 Quitar foto", "photo_del") if draft.photo else _btn("🖼 Foto", "photo")
    )
    buttons_btn = (
        _btn("🗑 Quitar botones", "buttons_del")
        if draft.inline_buttons
        else _btn("⌨️ Botones", "buttons")
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("➕ Fragmento", "add_text"), _btn("✍️ Sintaxis", "syntax")],
            [photo_btn, buttons_btn],
            [_btn("🗂 Fragmentos", "fragments"), _btn("💾 Guardar", "save")],
            [
                _btn("✅ Enviar", "send"),
                _btn("❓ Ayuda", "help"),
                _btn("✖ Cancelar", "cancel"),
            ],
        ]
    )


def formats_keyboard(draft: Draft, idx: int) -> InlineKeyboardMarkup:
    segment = draft.segments[idx]
    total = len(draft.segments)

    def toggle(fmt: Format, label: str) -> InlineKeyboardButton:
        mark = "✅" if fmt in segment.formats else "⬜"
        return _btn(f"{mark}{label}", "toggle", idx, fmt.value)

    if segment.block == "pre":
        block_btn = _btn("🚫 Código (pre)", "block", idx)
    elif segment.block == "quote":
        block_btn = _btn("📝 Párrafo", "block", idx)
    else:
        block_btn = _btn("📋 Cita", "block", idx)

    summary = segment.text.replace("\n", " ").strip()
    if segment.buttons:
        summary = segment.buttons[0].text
    header = f"✏️ Fragmento {idx + 1}/{total}"
    if summary:
        header += f": {summary[:24]}"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn(header, "noop", idx)],
            [
                toggle(Format.BOLD, "Negrita"),
                toggle(Format.ITALIC, "Cursiva"),
                toggle(Format.SPOILER, "Spoiler"),
            ],
            [
                toggle(Format.UNDERLINE, "Subrayado"),
                toggle(Format.STRIKE, "Tachado"),
                toggle(Format.CODE, "Código"),
            ],
            [_btn("🔗 Enlace", "link", idx), block_btn],
            [
                _btn("⬆️", "up", idx),
                _btn("⬇️", "down", idx),
                _btn("🗑", "del", idx),
            ],
            [_btn("📝 Texto", "text", idx), _btn("↩️ Listo", "back")],
        ]
    )


def fragments_keyboard(draft: Draft) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for idx, segment in enumerate(draft.segments):
        if segment.buttons:
            summary = segment.buttons[0].text
        else:
            summary = segment.text.replace("\n", " ").strip()
        label = f"{idx + 1}. {summary[:22] or '…'}"
        rows.append([_btn(label, "open", idx)])
    rows.append([_btn("➕ Agregar", "add_text"), _btn("↩️ Volver", "back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_message_keyboard(draft: Draft) -> InlineKeyboardMarkup | None:
    """Build the real inline keyboard that ships with the composed message."""
    if not draft.inline_buttons:
        return None
    rows: list[list[InlineKeyboardButton]] = []
    for row in draft.inline_buttons:
        buttons = [_to_message_button(spec) for spec in row]
        if buttons:
            rows.append(buttons)
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def _to_message_button(spec: ButtonSpec) -> InlineKeyboardButton:
    if spec.type is ButtonType.URL:
        return InlineKeyboardButton(text=spec.text, url=validate_url(spec.value))
    if spec.type is ButtonType.CALLBACK:
        data = DEMO_CALLBACK_PREFIX + truncate_bytes(spec.value, 58)
        return InlineKeyboardButton(text=spec.text, callback_data=data)
    if spec.type is ButtonType.COPY_TEXT:
        return InlineKeyboardButton(text=spec.text, copy_text=CopyTextButton(text=spec.value))
    return InlineKeyboardButton(text=spec.text, switch_inline_query=spec.value)
