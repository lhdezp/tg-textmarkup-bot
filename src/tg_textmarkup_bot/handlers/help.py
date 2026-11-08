from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.types import InlineKeyboardButton

from tg_textmarkup_bot.callbacks import EditorCB

router = Router(name="help")

GUIDE_TEXT = "\n".join(
    [
        "📖 GUÍA DE FORMATOS",
        "",
        "✍️ RUTA A — escribir con sintaxis:",
        "",
        "*negrita*   _cursiva_   ||spoiler||",
        "__subrayado__   ~tachado~   `código`",
        "",
        "Bloque de código: línea ``` al inicio y ``` al final",
        "(opcionalmente ```python para resaltar)",
        "",
        "[texto del enlace](https://ejemplo.com)",
        "> cita (cada línea empieza con >)",
        "",
        "[[Texto del botón|https://url]]  ← botón dentro del texto",
        "  prefijos del valor: callback:aviso · copy:texto · switch:consulta",
        "",
        "\\* ← asterisco literal (igual con \\_ \\~ \\[ \\] \\` \\|)",
        "",
        "🎛 RUTA B — editar por botones:",
        "",
        "1. ➕ Fragmento → envías un texto",
        "2. Se abren los formatos de ESE texto:",
        "   ✅Negrita ✅Cursiva ✅Spoiler ✅Subrayado ✅Tachado ✅Código",
        "   Tocás para activar/desactivar (se ve al instante en el preview)",
        "3. 🔗 Enlace pide la URL · 📋 Cita lo convierte en cita",
        "4. 🗂 Fragmentos reordena (⬆️⬇️) o borra (🗑)",
        "5. 📝 Texto reescribe ese fragmento · ↩️ Listo vuelve al editor",
        "",
        "⌨️ BOTONES DEBAJO DEL MENSAJE:",
        "",
        "Una línea por botón:  Texto | https://url",
        "Doble salto de línea = nueva fila",
        "Tipos: callback:aviso · copy:texto a copiar · switch:consulta",
        "",
        "🖼 FOTO: tocá 🖼 Foto y envíala (o pegá una URL directa)",
        "",
        "💾 PLANTILLAS: con 💾 Guardar guardás el mensaje;",
        "al usarla (/plantillas) el bot te pide cada {placeholder}",
        "en orden — también si está en la foto o en los botones.",
    ]
)

START_TEXT = (
    "Hola 👋 Soy un bot para armar mensajes con el formato de Telegram.\n"
    "\n"
    "• Escribí con sintaxis simple (*negrita*, ||spoiler||, …)\n"
    "• O armalo fragmento por fragmento con botones\n"
    "• Sumale foto, botones abajo o botones dentro del texto\n"
    "• Guardá plantillas con {placeholders} y reutilizalas\n"
    "\n"
    "Empezá con /nuevo (o simplemente escribí tu mensaje)."
)

PROMPT_TEXT = "\n".join(
    [
        "🧵 Armá tu mensaje — elegí cómo empezar:",
        "",
        "✍️ Escribí directamente con la sintaxis (o tocá el botón):",
        "",
        "*negrita*  _cursiva_  ||spoiler||",
        "__subrayado__  ~tachado~  `código`",
        "[texto](https://url)  [[Botón|https://url]]",
        "> cita  ·  ```bloque de código```",
        "",
        "escapá con \\* si querés un asterisco literal",
        "❓ Ayuda = guía completa",
    ]
)


def _main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Nuevo mensaje", callback_data=EditorCB(action="menu_new").pack())],
            [
                InlineKeyboardButton(text="📚 Plantillas", callback_data=EditorCB(action="menu_templates").pack()),
                InlineKeyboardButton(text="❓ Ayuda", callback_data=EditorCB(action="help").pack()),
            ],
        ]
    )


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(START_TEXT, reply_markup=_main_menu_keyboard())


@router.message(Command("ayuda"))
async def cmd_help(message: Message) -> None:
    await message.answer(GUIDE_TEXT)


@router.callback_query(EditorCB.filter(action="help"))
async def on_help_callback(cb: CallbackQuery) -> None:
    await cb.answer()
    await cb.message.answer(GUIDE_TEXT)  # type: ignore[union-attr]
