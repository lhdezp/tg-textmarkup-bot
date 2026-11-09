from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from tg_textmarkup_bot.handlers import compose, templates
from tg_textmarkup_bot.handlers import help as help_handlers


def create_bot(token: str) -> Bot:
    return Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def create_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(help_handlers.router)
    dispatcher.include_router(templates.router)
    dispatcher.include_router(compose.router)
    return dispatcher
