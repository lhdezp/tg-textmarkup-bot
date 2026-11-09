"""Per-user templates: list, use (with placeholder prompts), delete."""

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import select

from tg_textmarkup_bot.callbacks import EditorCB, TemplateCB
from tg_textmarkup_bot.db.engine import get_session_factory
from tg_textmarkup_bot.db.models import Template
from tg_textmarkup_bot.preview import drop_user_message, edit_or_send, show_preview
from tg_textmarkup_bot.rendering.model import ButtonSpec, Draft, Segment
from tg_textmarkup_bot.rendering.placeholders import find_placeholders, substitute
from tg_textmarkup_bot.rendering.render import InvalidUrlError
from tg_textmarkup_bot.states import Compose, TemplateUse

router = Router(name="templates")

LIST_EMPTY_TEXT = (
    "No tenés plantillas todavía.\n"
    "Armá un mensaje con /nuevo y tocá 💾 Guardar para crear una."
)


async def _load_owned(user_id: int, template_id: int) -> Template | None:
    factory = get_session_factory()
    async with factory() as session:
        template = await session.get(Template, template_id)
        if template is None or template.owner_id != user_id:
            return None
        return template


def _draft_from_template(template: Template) -> Draft:
    return Draft(
        segments=[Segment.model_validate(item) for item in template.segments],
        photo=template.photo,
        inline_buttons=(
            [
                [ButtonSpec.model_validate(item) for item in row]
                for row in template.inline_buttons
            ]
            if template.inline_buttons
            else []
        ),
    )


async def _list_content(user_id: int) -> tuple[str, InlineKeyboardMarkup | None]:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.scalars(
            select(Template)
            .where(Template.owner_id == user_id)
            .order_by(Template.name)
            .limit(30)
        )
        templates = list(result)
    if not templates:
        return LIST_EMPTY_TEXT, None
    rows = [
        [
            InlineKeyboardButton(
                text=template.name[:22],
                callback_data=TemplateCB(action="use", idx=template.id).pack(),
            ),
            InlineKeyboardButton(
                text="🗑",
                callback_data=TemplateCB(action="del", idx=template.id).pack(),
            ),
        ]
        for template in templates
    ]
    return "📚 Tus plantillas:", InlineKeyboardMarkup(inline_keyboard=rows)


async def _clear_compose_messages(bot: Bot, state: FSMContext) -> None:
    data = await state.get_data()
    chat_id = data.get("chat_id")
    if chat_id:
        for key in ("prompt_msg_id", "preview_msg_id", "instr_msg_id", "question_msg_id"):
            message_id = data.get(key)
            if message_id:
                try:
                    await bot.delete_message(chat_id, message_id)
                except TelegramBadRequest:
                    pass
    await state.update_data(
        prompt_msg_id=None,
        preview_msg_id=None,
        preview_mode=None,
        instr_msg_id=None,
        question_msg_id=None,
    )


async def _delete_message(bot: Bot, chat_id: int, message_id: int | None) -> None:
    if not message_id:
        return
    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramBadRequest:
        pass


async def _ask_question(bot: Bot, state: FSMContext, chat_id: int, text: str) -> None:
    """Ask the next placeholder value by editing the persistent question message."""
    data = await state.get_data()
    message_id = await edit_or_send(bot, chat_id, data.get("question_msg_id"), text)
    await state.update_data(question_msg_id=message_id)


async def _ask(bot: Bot, state: FSMContext, chat_id: int, text: str) -> None:
    data = await state.get_data()
    message_id = await edit_or_send(bot, chat_id, data.get("instr_msg_id"), text)
    await state.update_data(instr_msg_id=message_id)


async def _load_into_compose(
    bot: Bot, state: FSMContext, chat_id: int, draft: Draft, name: str
) -> None:
    await state.set_state(Compose.editing)
    await state.update_data(
        draft=draft.model_dump(mode="json"),
        chat_id=chat_id,
        prompt_msg_id=None,
        preview_msg_id=None,
        preview_mode=None,
        instr_msg_id=None,
        question_msg_id=None,
        seg_idx=-1,
        tpl_draft=None,
        tpl_names=None,
        tpl_values=None,
        tpl_total=None,
        tpl_name=None,
    )
    try:
        await show_preview(bot, chat_id, state)
    except (InvalidUrlError, TelegramBadRequest) as exc:
        await bot.send_message(chat_id, f"⚠️ {exc}", parse_mode=None)
        return
    await _ask(
        bot,
        state,
        chat_id,
        f"✅ Plantilla «{name}» lista — tocá ✅ Enviar o seguí editando.",
    )


@router.message(Command("plantillas"))
async def cmd_templates(message: Message, bot: Bot) -> None:
    text, keyboard = await _list_content(message.from_user.id)
    await message.answer(text, reply_markup=keyboard, parse_mode=None)


@router.callback_query(EditorCB.filter(F.action == "menu_templates"))
async def on_menu_templates(cb: CallbackQuery, bot: Bot) -> None:
    await cb.answer()
    if cb.message is None:
        return
    text, keyboard = await _list_content(cb.from_user.id)
    await bot.send_message(
        cb.message.chat.id, text, reply_markup=keyboard, parse_mode=None
    )


@router.callback_query(TemplateCB.filter(F.action == "use"))
async def on_template_use(
    cb: CallbackQuery, callback_data: TemplateCB, state: FSMContext, bot: Bot
) -> None:
    template = await _load_owned(cb.from_user.id, callback_data.idx)
    if template is None:
        await cb.answer("La plantilla no existe", show_alert=True)
        return
    if cb.message is None:
        await cb.answer()
        return
    chat_id = cb.message.chat.id
    draft = _draft_from_template(template)
    names = find_placeholders(draft)

    await _clear_compose_messages(bot, state)

    if not names:
        await cb.answer("Plantilla cargada")
        await _load_into_compose(bot, state, chat_id, draft, template.name)
        return

    await cb.answer()
    await state.set_state(TemplateUse.placeholder_value)
    await state.update_data(
        tpl_draft=draft.model_dump(mode="json"),
        tpl_names=names,
        tpl_values={},
        tpl_total=len(names),
        tpl_name=template.name,
        chat_id=chat_id,
        question_msg_id=None,
    )
    message = await bot.send_message(
        chat_id,
        f"Plantilla «{template.name}» — reemplaza el mensaje en curso.\n"
        f"Valor para {{{names[0]}}} (1/{len(names)}):",
        parse_mode=None,
    )
    await state.update_data(question_msg_id=message.message_id)


@router.message(TemplateUse.placeholder_value, F.text | F.photo)
async def on_placeholder_value(
    message: Message, state: FSMContext, bot: Bot
) -> None:
    data = await state.get_data()
    chat_id = data["chat_id"]
    names: list[str] = list(data["tpl_names"])
    values: dict[str, str] = dict(data.get("tpl_values") or {})
    total: int = data.get("tpl_total", len(names))
    current = names[0]
    photo_field = (data.get("tpl_draft") or {}).get("photo") or ""

    if message.photo:
        if f"{{{current}}}" in photo_field:
            values[current] = message.photo[-1].file_id
        else:
            await _ask_question(
                bot,
                state,
                chat_id,
                f"⚠️ {{{current}}} va en el texto, no es una foto. Mandame el valor:",
            )
            return
    elif message.text:
        values[current] = message.text
    else:
        await _ask_question(
            bot,
            state,
            chat_id,
            f"⚠️ Esperaba un texto para {{{current}}}:",
        )
        return

    await drop_user_message(bot, message)
    names = names[1:]
    if names:
        answered = total - len(names)
        await state.update_data(tpl_names=names, tpl_values=values)
        await _ask_question(
            bot,
            state,
            chat_id,
            f"Valor para {{{names[0]}}} ({answered + 1}/{total}):",
        )
        return

    await _delete_message(bot, chat_id, data.get("question_msg_id"))
    await state.update_data(question_msg_id=None)
    draft = substitute(Draft.model_validate(data["tpl_draft"]), values)
    await _load_into_compose(bot, state, chat_id, draft, data.get("tpl_name", "plantilla"))


@router.callback_query(TemplateCB.filter(F.action == "del"))
async def on_template_del(
    cb: CallbackQuery, callback_data: TemplateCB, state: FSMContext, bot: Bot
) -> None:
    template = await _load_owned(cb.from_user.id, callback_data.idx)
    if template is None:
        await cb.answer("La plantilla no existe", show_alert=True)
        return
    await cb.answer()
    if cb.message is None:
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🗑 Confirmar borrado",
                    callback_data=TemplateCB(action="confirm_del", idx=template.id).pack(),
                ),
                InlineKeyboardButton(
                    text="↩️",
                    callback_data=TemplateCB(action="back").pack(),
                ),
            ]
        ]
    )
    try:
        await cb.message.edit_text(
            f"Borrar la plantilla «{template.name}»?", reply_markup=keyboard
        )
    except TelegramBadRequest:
        pass


@router.callback_query(TemplateCB.filter(F.action == "confirm_del"))
async def on_template_confirm_del(
    cb: CallbackQuery, callback_data: TemplateCB, state: FSMContext, bot: Bot
) -> None:
    template = await _load_owned(cb.from_user.id, callback_data.idx)
    if template is None:
        await cb.answer("La plantilla no existe", show_alert=True)
        return
    factory = get_session_factory()
    async with factory() as session:
        await session.delete(template)
        await session.commit()
    await cb.answer("🗑 Borrada")
    if cb.message is None:
        return
    text, keyboard = await _list_content(cb.from_user.id)
    try:
        await cb.message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest:
        pass


@router.callback_query(TemplateCB.filter(F.action == "back"))
async def on_template_back(cb: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await cb.answer()
    if cb.message is None:
        return
    text, keyboard = await _list_content(cb.from_user.id)
    try:
        await cb.message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest:
        pass
