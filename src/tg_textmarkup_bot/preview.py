"""Preview rendering: keep one live preview message in sync with the draft."""

from typing import Literal

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputRichMessage,
    InputRichMessageMedia,
    LinkPreviewOptions,
    Message,
    ParseMode,
)

from tg_textmarkup_bot.keyboards import editor_keyboard, formats_keyboard, start_compose_keyboard
from tg_textmarkup_bot.rendering.model import Draft
from tg_textmarkup_bot.rendering.render import render_html
from tg_textmarkup_bot.states import Compose

SendMode = Literal["text", "photo", "rich"]

PHOTO_MEDIA_ID = "m1"
DISABLED_PREVIEW = LinkPreviewOptions(is_disabled=True)


def compute_mode(draft: Draft) -> SendMode:
    """Pick the send path for a draft.

    Classic text/photo paths are preferred (better client compatibility);
    rich messages are used for in-text buttons and for oversized content
    (caption limit 1024, text limit 4096).
    """
    html_length = len(render_html(draft))
    if draft.is_rich or html_length > 4000:
        return "rich"
    if draft.photo:
        return "rich" if html_length > 1000 else "photo"
    return "text"


def _rich_input(draft: Draft, html: str) -> InputRichMessage:
    media = None
    if draft.photo:
        media = [
            InputRichMessageMedia(
                id=PHOTO_MEDIA_ID,
                media=InputMediaPhoto(media=draft.photo),
            )
        ]
    return InputRichMessage(html=html, media=media)


async def send_draft(
    bot: Bot,
    chat_id: int,
    draft: Draft,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Message:
    mode = compute_mode(draft)
    photo_id = PHOTO_MEDIA_ID if mode == "rich" and draft.photo else None
    html = render_html(draft, photo_id=photo_id)
    if mode == "photo":
        return await bot.send_photo(
            chat_id,
            photo=draft.photo,  # type: ignore[arg-type]
            caption=html or None,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )
    if mode == "rich":
        return await bot.send_rich_message(
            chat_id=chat_id,
            rich_message=_rich_input(draft, html),
            reply_markup=reply_markup,
        )
    return await bot.send_message(
        chat_id,
        text=html,
        parse_mode=ParseMode.HTML,
        link_preview_options=DISABLED_PREVIEW,
        reply_markup=reply_markup,
    )


async def show_preview(bot: Bot, chat_id: int, state: FSMContext) -> None:
    """Create or update the live preview message for the current draft."""
    data = await state.get_data()
    draft = Draft.model_validate(data["draft"])

    if not draft.has_content:
        prev_id = data.get("preview_msg_id")
        if prev_id:
            await _try_delete(bot, chat_id, prev_id)
        await state.update_data(preview_msg_id=None, preview_mode=None)
        prompt_id = data.get("prompt_msg_id")
        if prompt_id:
            try:
                await bot.edit_message_reply_markup(
                    chat_id=chat_id,
                    message_id=prompt_id,
                    reply_markup=start_compose_keyboard(),
                )
            except TelegramBadRequest:
                pass
        return

    kb = await _keyboard_for_state(state, data, draft)
    mode = compute_mode(draft)
    photo_id = PHOTO_MEDIA_ID if mode == "rich" and draft.photo else None
    html = render_html(draft, photo_id=photo_id)
    prev_id = data.get("preview_msg_id")

    if prev_id and data.get("preview_mode") == mode:
        try:
            if mode == "photo":
                await bot.edit_message_media(
                    chat_id=chat_id,
                    message_id=prev_id,
                    media=InputMediaPhoto(
                        media=draft.photo,  # type: ignore[arg-type]
                        caption=html or None,
                        parse_mode=ParseMode.HTML,
                    ),
                    reply_markup=kb,
                )
            elif mode == "rich":
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=prev_id,
                    rich_message=_rich_input(draft, html),
                    reply_markup=kb,
                )
            else:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=prev_id,
                    text=html,
                    parse_mode=ParseMode.HTML,
                    link_preview_options=DISABLED_PREVIEW,
                    reply_markup=kb,
                )
            return
        except TelegramBadRequest as exc:
            if "not modified" in str(exc).lower():
                return
            # Shape changed in a way Telegram rejects; fall through to resend.

    if prev_id:
        await _try_delete(bot, chat_id, prev_id)
    message = await send_draft(bot, chat_id, draft, reply_markup=kb)
    await state.update_data(preview_msg_id=message.message_id, preview_mode=mode)


async def set_keyboard(
    bot: Bot, state: FSMContext, reply_markup: InlineKeyboardMarkup
) -> None:
    """Swap the keyboard on the preview (or prompt) without touching content."""
    data = await state.get_data()
    target = data.get("preview_msg_id") or data.get("prompt_msg_id")
    if not target:
        return
    try:
        await bot.edit_message_reply_markup(
            chat_id=data["chat_id"],
            message_id=target,
            reply_markup=reply_markup,
        )
    except TelegramBadRequest:
        pass


async def _keyboard_for_state(
    state: FSMContext, data: dict, draft: Draft
) -> InlineKeyboardMarkup:
    if await state.get_state() == Compose.segment_formats.state and draft.segments:
        idx = data.get("seg_idx", 0)
        if 0 <= idx < len(draft.segments):
            return formats_keyboard(draft, idx)
    return editor_keyboard(draft)


async def _try_delete(bot: Bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramBadRequest:
        pass
