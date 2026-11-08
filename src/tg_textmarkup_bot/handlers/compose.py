"""Message composition: light-syntax path, segment editor, preview, send."""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.exc import IntegrityError

from tg_textmarkup_bot.callbacks import EditorCB
from tg_textmarkup_bot.db.engine import get_session_factory
from tg_textmarkup_bot.db.models import Template
from tg_textmarkup_bot.handlers.help import PROMPT_TEXT
from tg_textmarkup_bot.keyboards import (
    DEMO_CALLBACK_PREFIX,
    build_message_keyboard,
    editor_keyboard,
    formats_keyboard,
    fragments_keyboard,
    start_compose_keyboard,
)
from tg_textmarkup_bot.preview import send_draft, set_keyboard, show_preview
from tg_textmarkup_bot.rendering.model import Draft, Format, Segment
from tg_textmarkup_bot.rendering.render import InvalidUrlError, validate_url
from tg_textmarkup_bot.rendering.syntax import parse, parse_button_rows
from tg_textmarkup_bot.states import Compose

router = Router(name="compose")

SYNTAX_ASK_TEXT = (
    "✍️ Escribí tu mensaje con la sintaxis:\n\n"
    "*negrita*  _cursiva_  ||spoiler||\n"
    "__subrayado__  ~tachado~  `código`\n"
    "[texto](https://url)  [[Botón|https://url]]\n"
    "> cita  ·  ```bloque```\n\n"
    "Escapá especiales con \\* · ❓ Ayuda tiene la guía completa"
)

SEGMENT_ASK_TEXT = (
    "Envíame el texto de este fragmento "
    "(sin formato — los formatos los elegís después)."
)

BUTTONS_ASK_TEXT = (
    "⌨️ Escribí los botones — una línea por botón:\n\n"
    "Texto | https://url\n"
    "Otro | https://url\n\n"
    "Doble salto de línea = nueva fila.\n"
    "Tipos: callback:aviso · copy:texto · switch:consulta"
)

PHOTO_ASK_TEXT = "Envíame una foto 📷 o pegá una URL directa (https://...)."

LINK_ASK_TEXT = "Pasame la URL del enlace:\nhttps://ejemplo.com"

TEMPLATE_NAME_ASK_TEXT = "Ponle un nombre a la plantilla (máx. 64 caracteres):"

FORMATS_HINT_TEXT = "Elegí los formatos para ese fragmento en el teclado del preview 👆"


def _draft_from(data: dict[str, Any]) -> Draft | None:
    raw = data.get("draft")
    return Draft.model_validate(raw) if raw is not None else None


async def _save_draft(state: FSMContext, draft: Draft) -> None:
    await state.update_data(draft=draft.model_dump(mode="json"))


async def _try_delete(bot: Bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramBadRequest:
        pass


async def _ask(bot: Bot, state: FSMContext, chat_id: int, text: str) -> None:
    data = await state.get_data()
    old = data.get("instr_msg_id")
    if old:
        await _try_delete(bot, chat_id, old)
    message = await bot.send_message(chat_id, text, parse_mode=None)
    await state.update_data(instr_msg_id=message.message_id)


async def _drop_instr(bot: Bot, state: FSMContext) -> None:
    data = await state.get_data()
    chat_id = data.get("chat_id")
    old = data.get("instr_msg_id")
    if old and chat_id:
        await _try_delete(bot, chat_id, old)
    await state.update_data(instr_msg_id=None)


async def _refresh_preview(bot: Bot, state: FSMContext) -> None:
    data = await state.get_data()
    chat_id = data.get("chat_id")
    if chat_id is None:
        return
    try:
        await show_preview(bot, chat_id, state)
    except InvalidUrlError as exc:
        await bot.send_message(chat_id, f"⚠️ {exc}", parse_mode=None)
        return
    except TelegramBadRequest as exc:
        await bot.send_message(
            chat_id, f"⚠️ Telegram rechazó el mensaje: {exc}", parse_mode=None
        )
        return
    data = await state.get_data()
    if data.get("prompt_msg_id") is None and data.get("preview_msg_id") is None:
        draft = _draft_from(data)
        if draft is None or not draft.has_content:
            message = await bot.send_message(
                chat_id,
                PROMPT_TEXT,
                reply_markup=start_compose_keyboard(),
                parse_mode=None,
            )
            await state.update_data(prompt_msg_id=message.message_id)


async def _cleanup_session(
    bot: Bot, state: FSMContext, *, keep_preview: bool = False
) -> None:
    data = await state.get_data()
    chat_id = data.get("chat_id")
    if chat_id is None:
        return
    keys = ["prompt_msg_id", "instr_msg_id"]
    if not keep_preview:
        keys.append("preview_msg_id")
    for key in keys:
        message_id = data.get(key)
        if message_id:
            await _try_delete(bot, chat_id, message_id)
    updates: dict[str, Any] = {"prompt_msg_id": None, "instr_msg_id": None}
    if not keep_preview:
        updates["preview_msg_id"] = None
        updates["preview_mode"] = None
    await state.update_data(**updates)


async def _start_new(bot: Bot, state: FSMContext, chat_id: int) -> None:
    await _cleanup_session(bot, state)
    await state.set_state(Compose.editing)
    draft = Draft()
    await state.update_data(
        draft=draft.model_dump(mode="json"),
        chat_id=chat_id,
        seg_idx=-1,
    )
    message = await bot.send_message(
        chat_id,
        PROMPT_TEXT,
        reply_markup=start_compose_keyboard(),
        parse_mode=None,
    )
    await state.update_data(prompt_msg_id=message.message_id)


async def _begin_draft(
    state: FSMContext, chat_id: int, draft: Draft
) -> None:
    await state.set_state(Compose.editing)
    await state.update_data(
        draft=draft.model_dump(mode="json"),
        chat_id=chat_id,
        prompt_msg_id=None,
        preview_msg_id=None,
        preview_mode=None,
        instr_msg_id=None,
        seg_idx=-1,
    )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@router.message(Command("nuevo"))
async def cmd_new(message: Message, state: FSMContext, bot: Bot) -> None:
    await _start_new(bot, state, message.chat.id)


@router.message(Command("cancelar"))
async def cmd_cancel(message: Message, state: FSMContext, bot: Bot) -> None:
    await _cleanup_session(bot, state)
    await state.clear()
    await message.answer(
        "✖ Cancelado. Escribí /nuevo para empezar de nuevo.", parse_mode=None
    )


# ---------------------------------------------------------------------------
# Input handlers (state-driven)
# ---------------------------------------------------------------------------


@router.message(Compose.syntax_text, F.text)
async def on_syntax_text(message: Message, state: FSMContext, bot: Bot) -> None:
    await _drop_instr(bot, state)
    data = await state.get_data()
    draft = _draft_from(data) or Draft()
    segments = parse(message.text or "")
    if not segments and draft.photo is None:
        await message.answer(
            "No reconocí contenido — escribí algo con la sintaxis.", parse_mode=None
        )
        return
    draft.segments = segments
    await _save_draft(state, draft)
    await state.set_state(Compose.editing)
    await state.update_data(seg_idx=-1)
    await _refresh_preview(bot, state)


@router.message(Compose.segment_text, F.text)
async def on_segment_text(message: Message, state: FSMContext, bot: Bot) -> None:
    await _drop_instr(bot, state)
    data = await state.get_data()
    chat_id = data["chat_id"]
    draft = _draft_from(data)
    if draft is None:
        await _start_new(bot, state, chat_id)
        return
    draft.segments.append(Segment(text=message.text or ""))
    idx = len(draft.segments) - 1
    await _save_draft(state, draft)
    await state.set_state(Compose.segment_formats)
    await state.update_data(seg_idx=idx)
    await _refresh_preview(bot, state)
    await _ask(bot, state, chat_id, FORMATS_HINT_TEXT)


@router.message(Compose.segment_edit_text, F.text)
async def on_segment_edit_text(message: Message, state: FSMContext, bot: Bot) -> None:
    await _drop_instr(bot, state)
    data = await state.get_data()
    chat_id = data["chat_id"]
    draft = _draft_from(data)
    idx = data.get("seg_idx", -1)
    if draft is None or not (0 <= idx < len(draft.segments)):
        await state.set_state(Compose.editing)
        await _refresh_preview(bot, state)
        return
    draft.segments[idx].text = message.text or ""
    await _save_draft(state, draft)
    await state.set_state(Compose.segment_formats)
    await _refresh_preview(bot, state)
    await _ask(bot, state, chat_id, "Listo — seguís en los formatos del fragmento.")


@router.message(Compose.link_url, F.text)
async def on_link_url(message: Message, state: FSMContext, bot: Bot) -> None:
    await _drop_instr(bot, state)
    data = await state.get_data()
    chat_id = data["chat_id"]
    draft = _draft_from(data)
    idx = data.get("seg_idx", -1)
    if draft is None or not (0 <= idx < len(draft.segments)):
        await state.set_state(Compose.editing)
        await _refresh_preview(bot, state)
        return
    url = (message.text or "").strip()
    try:
        validate_url(url)
    except InvalidUrlError as exc:
        await _ask(bot, state, chat_id, f"⚠️ {exc}\nPasame una URL válida:")
        return
    draft.segments[idx].link_url = url
    await _save_draft(state, draft)
    await state.set_state(Compose.segment_formats)
    await _refresh_preview(bot, state)
    await _ask(bot, state, chat_id, "Enlace aplicado — volvés a los formatos.")


@router.message(Compose.photo, F.photo)
async def on_photo_uploaded(message: Message, state: FSMContext, bot: Bot) -> None:
    await _drop_instr(bot, state)
    data = await state.get_data()
    draft = _draft_from(data) or Draft()
    draft.photo = message.photo[-1].file_id
    await _save_draft(state, draft)
    await state.set_state(Compose.editing)
    await _refresh_preview(bot, state)


@router.message(Compose.photo, F.text)
async def on_photo_url(message: Message, state: FSMContext, bot: Bot) -> None:
    await _drop_instr(bot, state)
    data = await state.get_data()
    chat_id = data["chat_id"]
    url = (message.text or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        await _ask(
            bot,
            state,
            chat_id,
            "⚠️ La URL de la foto debe empezar con http:// o https://. "
            "O enviame la foto directamente.",
        )
        return
    draft = _draft_from(data) or Draft()
    draft.photo = url
    await _save_draft(state, draft)
    await state.set_state(Compose.editing)
    await _refresh_preview(bot, state)


@router.message(Compose.inline_buttons, F.text)
async def on_inline_buttons(message: Message, state: FSMContext, bot: Bot) -> None:
    await _drop_instr(bot, state)
    data = await state.get_data()
    chat_id = data["chat_id"]
    try:
        rows = parse_button_rows(message.text or "")
    except ValueError as exc:
        await _ask(bot, state, chat_id, f"⚠️ {exc}\nProbá de nuevo con el formato:")
        return
    draft = _draft_from(data) or Draft()
    draft.inline_buttons = rows
    await _save_draft(state, draft)
    await state.set_state(Compose.editing)
    await _refresh_preview(bot, state)


@router.message(Compose.template_name, F.text)
async def on_template_name(message: Message, state: FSMContext, bot: Bot) -> None:
    await _drop_instr(bot, state)
    data = await state.get_data()
    chat_id = data["chat_id"]
    name = (message.text or "").strip()[:64]
    if not name:
        await _ask(bot, state, chat_id, "⚠️ El nombre no puede estar vacío. Probá otro:")
        return
    draft = _draft_from(data)
    if draft is None or not draft.has_content:
        await state.set_state(Compose.editing)
        await _refresh_preview(bot, state)
        return
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            Template(
                owner_id=message.from_user.id,
                name=name,
                segments=[s.model_dump(mode="json") for s in draft.segments],
                photo=draft.photo,
                inline_buttons=(
                    [
                        [b.model_dump(mode="json") for b in row]
                        for row in draft.inline_buttons
                    ]
                    if draft.inline_buttons
                    else None
                ),
            )
        )
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            await _ask(
                bot,
                state,
                chat_id,
                f"⚠️ Ya tenés una plantilla llamada «{name}». Probá con otro nombre:",
            )
            return
    await state.set_state(Compose.editing)
    await message.answer(
        f"💾 Plantilla «{name}» guardada. Usala con /plantillas.", parse_mode=None
    )


# ---------------------------------------------------------------------------
# Free-text / free-photo quick start (no FSM state)
# ---------------------------------------------------------------------------


@router.message(F.photo, state=None)
async def on_free_photo(message: Message, state: FSMContext, bot: Bot) -> None:
    draft = Draft(photo=message.photo[-1].file_id)
    await _begin_draft(state, message.chat.id, draft)
    await _refresh_preview(bot, state)


@router.message(F.text, state=None)
async def on_free_text(message: Message, state: FSMContext, bot: Bot) -> None:
    draft = Draft(segments=parse(message.text or ""))
    await _begin_draft(state, message.chat.id, draft)
    await _refresh_preview(bot, state)


# ---------------------------------------------------------------------------
# Editor callbacks
# ---------------------------------------------------------------------------

ActionFn = Callable[[CallbackQuery, EditorCB, FSMContext, Bot], Awaitable[None]]


async def _require_draft(
    cb: CallbackQuery, state: FSMContext
) -> tuple[dict[str, Any], Draft] | None:
    data = await state.get_data()
    draft = _draft_from(data)
    if draft is None:
        await cb.answer("No hay mensaje en curso — usá /nuevo", show_alert=True)
        return None
    return data, draft


async def _action_menu_new(
    cb: CallbackQuery, _: EditorCB, state: FSMContext, bot: Bot
) -> None:
    if cb.message is None:
        await cb.answer()
        return
    chat_id = cb.message.chat.id
    await cb.answer()
    await _start_new(bot, state, chat_id)


async def _action_syntax(
    cb: CallbackQuery, _: EditorCB, state: FSMContext, bot: Bot
) -> None:
    data = await state.get_data()
    chat_id = data.get("chat_id") or (cb.message.chat.id if cb.message else None)
    if chat_id is None:
        await cb.answer()
        return
    await cb.answer()
    await state.set_state(Compose.syntax_text)
    await _ask(bot, state, chat_id, SYNTAX_ASK_TEXT)


async def _action_add_text(
    cb: CallbackQuery, _: EditorCB, state: FSMContext, bot: Bot
) -> None:
    data = await state.get_data()
    chat_id = data.get("chat_id") or (cb.message.chat.id if cb.message else None)
    if chat_id is None:
        await cb.answer()
        return
    await cb.answer()
    await state.set_state(Compose.segment_text)
    await _ask(bot, state, chat_id, SEGMENT_ASK_TEXT)


async def _action_back(
    cb: CallbackQuery, _: EditorCB, state: FSMContext, bot: Bot
) -> None:
    ctx = await _require_draft(cb, state)
    if ctx is None:
        return
    _, draft = ctx
    await state.set_state(Compose.editing)
    await state.update_data(seg_idx=-1)
    await set_keyboard(bot, state, editor_keyboard(draft))


async def _action_fragments(
    cb: CallbackQuery, _: EditorCB, state: FSMContext, bot: Bot
) -> None:
    ctx = await _require_draft(cb, state)
    if ctx is None:
        return
    _, draft = ctx
    await state.set_state(Compose.editing)
    await set_keyboard(bot, state, fragments_keyboard(draft))


async def _action_open(
    cb: CallbackQuery, data_cb: EditorCB, state: FSMContext, bot: Bot
) -> None:
    ctx = await _require_draft(cb, state)
    if ctx is None:
        return
    _, draft = ctx
    if not (0 <= data_cb.idx < len(draft.segments)):
        await cb.answer("Fragmento no encontrado", show_alert=True)
        return
    await cb.answer()
    await state.set_state(Compose.segment_formats)
    await state.update_data(seg_idx=data_cb.idx)
    await set_keyboard(bot, state, formats_keyboard(draft, data_cb.idx))


async def _action_toggle(
    cb: CallbackQuery, data_cb: EditorCB, state: FSMContext, bot: Bot
) -> None:
    ctx = await _require_draft(cb, state)
    if ctx is None:
        return
    _, draft = ctx
    idx = data_cb.idx
    if not (0 <= idx < len(draft.segments)):
        await cb.answer("Fragmento no encontrado", show_alert=True)
        return
    try:
        fmt = Format(data_cb.arg)
    except ValueError:
        await cb.answer()
        return
    segment = draft.segments[idx]
    if fmt in segment.formats:
        segment.formats.discard(fmt)
    elif fmt is Format.CODE:
        segment.formats = {Format.CODE}
        segment.link_url = None
    else:
        segment.formats.discard(Format.CODE)
        segment.formats.add(fmt)
    await _save_draft(state, draft)
    await state.set_state(Compose.segment_formats)
    await state.update_data(seg_idx=idx)
    mark = "✅" if fmt in segment.formats else "⬜"
    await cb.answer(f"{mark} {fmt.value}")
    await _refresh_preview(bot, state)


async def _action_block(
    cb: CallbackQuery, data_cb: EditorCB, state: FSMContext, bot: Bot
) -> None:
    ctx = await _require_draft(cb, state)
    if ctx is None:
        return
    _, draft = ctx
    idx = data_cb.idx
    if not (0 <= idx < len(draft.segments)):
        await cb.answer("Fragmento no encontrado", show_alert=True)
        return
    segment = draft.segments[idx]
    if segment.block == "pre":
        await cb.answer(
            "Los bloques ``` se crean con la sintaxis, no con botones", show_alert=True
        )
        return
    segment.block = "p" if segment.block == "quote" else "quote"
    await _save_draft(state, draft)
    await state.set_state(Compose.segment_formats)
    await state.update_data(seg_idx=idx)
    await cb.answer("📋 Cita" if segment.block == "quote" else "📝 Párrafo")
    await _refresh_preview(bot, state)


async def _action_link(
    cb: CallbackQuery, data_cb: EditorCB, state: FSMContext, bot: Bot
) -> None:
    ctx = await _require_draft(cb, state)
    if ctx is None:
        return
    data, draft = ctx
    idx = data_cb.idx
    if not (0 <= idx < len(draft.segments)):
        await cb.answer("Fragmento no encontrado", show_alert=True)
        return
    chat_id = data["chat_id"]
    await cb.answer()
    await state.set_state(Compose.link_url)
    await state.update_data(seg_idx=idx)
    await _ask(bot, state, chat_id, LINK_ASK_TEXT)


async def _action_text(
    cb: CallbackQuery, data_cb: EditorCB, state: FSMContext, bot: Bot
) -> None:
    ctx = await _require_draft(cb, state)
    if ctx is None:
        return
    data, draft = ctx
    idx = data_cb.idx
    if not (0 <= idx < len(draft.segments)):
        await cb.answer("Fragmento no encontrado", show_alert=True)
        return
    chat_id = data["chat_id"]
    await cb.answer()
    await state.set_state(Compose.segment_edit_text)
    await state.update_data(seg_idx=idx)
    await _ask(
        bot,
        state,
        chat_id,
        f"Nuevo texto del fragmento {idx + 1} (se conservan sus formatos):",
    )


async def _action_up(
    cb: CallbackQuery, data_cb: EditorCB, state: FSMContext, bot: Bot
) -> None:
    ctx = await _require_draft(cb, state)
    if ctx is None:
        return
    _, draft = ctx
    idx = data_cb.idx
    if idx <= 0 or idx >= len(draft.segments):
        await cb.answer("Ya está al inicio", show_alert=True)
        return
    draft.segments[idx - 1], draft.segments[idx] = draft.segments[idx], draft.segments[idx - 1]
    await _save_draft(state, draft)
    await state.set_state(Compose.segment_formats)
    await state.update_data(seg_idx=idx - 1)
    await cb.answer("⬆️ Movido arriba")
    await _refresh_preview(bot, state)


async def _action_down(
    cb: CallbackQuery, data_cb: EditorCB, state: FSMContext, bot: Bot
) -> None:
    ctx = await _require_draft(cb, state)
    if ctx is None:
        return
    _, draft = ctx
    idx = data_cb.idx
    if idx < 0 or idx >= len(draft.segments) - 1:
        await cb.answer("Ya está al final", show_alert=True)
        return
    draft.segments[idx + 1], draft.segments[idx] = draft.segments[idx], draft.segments[idx + 1]
    await _save_draft(state, draft)
    await state.set_state(Compose.segment_formats)
    await state.update_data(seg_idx=idx + 1)
    await cb.answer("⬇️ Movido abajo")
    await _refresh_preview(bot, state)


async def _action_del(
    cb: CallbackQuery, data_cb: EditorCB, state: FSMContext, bot: Bot
) -> None:
    ctx = await _require_draft(cb, state)
    if ctx is None:
        return
    _, draft = ctx
    idx = data_cb.idx
    if not (0 <= idx < len(draft.segments)):
        await cb.answer("Fragmento no encontrado", show_alert=True)
        return
    draft.segments.pop(idx)
    await _save_draft(state, draft)
    await cb.answer("🗑 Borrado")
    await state.set_state(Compose.editing)
    await state.update_data(seg_idx=-1)
    await _refresh_preview(bot, state)
    if draft.has_content:
        await set_keyboard(bot, state, fragments_keyboard(draft))


async def _action_photo(
    cb: CallbackQuery, _: EditorCB, state: FSMContext, bot: Bot
) -> None:
    data = await state.get_data()
    chat_id = data.get("chat_id") or (cb.message.chat.id if cb.message else None)
    if chat_id is None:
        await cb.answer()
        return
    await cb.answer()
    await state.set_state(Compose.photo)
    await _ask(bot, state, chat_id, PHOTO_ASK_TEXT)


async def _action_photo_del(
    cb: CallbackQuery, _: EditorCB, state: FSMContext, bot: Bot
) -> None:
    ctx = await _require_draft(cb, state)
    if ctx is None:
        return
    _, draft = ctx
    draft.photo = None
    await _save_draft(state, draft)
    await cb.answer("📷 Foto quitada")
    await state.set_state(Compose.editing)
    await _refresh_preview(bot, state)


async def _action_buttons(
    cb: CallbackQuery, _: EditorCB, state: FSMContext, bot: Bot
) -> None:
    data = await state.get_data()
    chat_id = data.get("chat_id") or (cb.message.chat.id if cb.message else None)
    if chat_id is None:
        await cb.answer()
        return
    await cb.answer()
    await state.set_state(Compose.inline_buttons)
    await _ask(bot, state, chat_id, BUTTONS_ASK_TEXT)


async def _action_buttons_del(
    cb: CallbackQuery, _: EditorCB, state: FSMContext, bot: Bot
) -> None:
    ctx = await _require_draft(cb, state)
    if ctx is None:
        return
    _, draft = ctx
    draft.inline_buttons = []
    await _save_draft(state, draft)
    await cb.answer("⌨️ Botones quitados")
    await state.set_state(Compose.editing)
    await _refresh_preview(bot, state)


async def _action_save(
    cb: CallbackQuery, _: EditorCB, state: FSMContext, bot: Bot
) -> None:
    ctx = await _require_draft(cb, state)
    if ctx is None:
        return
    data, draft = ctx
    if not draft.has_content:
        await cb.answer("No hay nada para guardar", show_alert=True)
        return
    chat_id = data["chat_id"]
    await cb.answer()
    await state.set_state(Compose.template_name)
    await _ask(bot, state, chat_id, TEMPLATE_NAME_ASK_TEXT)


async def _action_send(
    cb: CallbackQuery, _: EditorCB, state: FSMContext, bot: Bot
) -> None:
    ctx = await _require_draft(cb, state)
    if ctx is None:
        return
    data, draft = ctx
    if not draft.has_content:
        await cb.answer("No hay nada para enviar", show_alert=True)
        return
    chat_id = data["chat_id"]
    try:
        keyboard = build_message_keyboard(draft)
    except InvalidUrlError as exc:
        await cb.answer(f"⚠️ {exc}"[:180], show_alert=True)
        return

    prev_id = data.get("preview_msg_id")
    sent = False
    if prev_id:
        try:
            await bot.edit_message_reply_markup(
                chat_id=chat_id, message_id=prev_id, reply_markup=keyboard
            )
            sent = True
        except TelegramBadRequest:
            sent = False
    if not sent:
        if prev_id:
            await _try_delete(bot, chat_id, prev_id)
        try:
            await send_draft(bot, chat_id, draft, reply_markup=keyboard)
        except (TelegramBadRequest, InvalidUrlError) as exc:
            await cb.answer(f"⚠️ {exc}"[:180], show_alert=True)
            return

    await _cleanup_session(bot, state, keep_preview=True)
    await state.clear()
    await cb.answer("✅ Listo — el mensaje está arriba. Reenvialo a donde quieras.")


async def _action_cancel(
    cb: CallbackQuery, _: EditorCB, state: FSMContext, bot: Bot
) -> None:
    await cb.answer("✖ Cancelado")
    await _cleanup_session(bot, state)
    await state.clear()


async def _action_noop(
    cb: CallbackQuery, data_cb: EditorCB, state: FSMContext, _: Bot
) -> None:
    data = await state.get_data()
    draft = _draft_from(data)
    if draft is not None and 0 <= data_cb.idx < len(draft.segments):
        segment = draft.segments[data_cb.idx]
        text = segment.text.replace("\n", " ").strip()
        if not text and segment.buttons:
            text = segment.buttons[0].text
        await cb.answer(text[:180] or "Fragmento")
    else:
        await cb.answer()


_ACTIONS: dict[str, ActionFn] = {
    "menu_new": _action_menu_new,
    "syntax": _action_syntax,
    "add_text": _action_add_text,
    "back": _action_back,
    "fragments": _action_fragments,
    "open": _action_open,
    "toggle": _action_toggle,
    "block": _action_block,
    "link": _action_link,
    "text": _action_text,
    "up": _action_up,
    "down": _action_down,
    "del": _action_del,
    "photo": _action_photo,
    "photo_del": _action_photo_del,
    "buttons": _action_buttons,
    "buttons_del": _action_buttons_del,
    "save": _action_save,
    "send": _action_send,
    "cancel": _action_cancel,
    "noop": _action_noop,
}


@router.callback_query(EditorCB.filter())
async def on_editor(
    cb: CallbackQuery, callback_data: EditorCB, state: FSMContext, bot: Bot
) -> None:
    handler = _ACTIONS.get(callback_data.action)
    if handler is None:
        await cb.answer()
        return
    await handler(cb, callback_data, state, bot)


# ---------------------------------------------------------------------------
# Buttons shipped with the composed message (demo callbacks)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith(DEMO_CALLBACK_PREFIX))
async def on_demo_callback(cb: CallbackQuery) -> None:
    value = cb.data[len(DEMO_CALLBACK_PREFIX) :].strip()
    await cb.answer(value[:180] or "Botón de ejemplo", show_alert=True)


# ---------------------------------------------------------------------------
# Fallback for any other content while a state is active
# ---------------------------------------------------------------------------


@router.message()
async def on_unhandled(message: Message, state: FSMContext) -> None:
    if await state.get_state() is not None:
        await message.answer(
            "Esperaba texto o una foto. Usá los botones del teclado o /cancelar.",
            parse_mode=None,
        )
