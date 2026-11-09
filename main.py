import asyncio
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

from tg_textmarkup_bot.bot import create_bot, create_dispatcher
from tg_textmarkup_bot.config import get_settings
from tg_textmarkup_bot.db.engine import dispose_database, setup_database


def _run_migrations() -> None:
    alembic_ini = Path(__file__).resolve().parent / "alembic.ini"
    if not alembic_ini.exists():
        logging.getLogger(__name__).warning("alembic.ini no encontrado; migraciones omitidas")
        return
    command.upgrade(Config(str(alembic_ini)), "head")


async def _run() -> None:
    settings = get_settings()
    setup_database(settings.database_url)
    bot = create_bot(settings.bot_token)
    dispatcher = create_dispatcher()
    try:
        await dispatcher.start_polling(
            bot, allowed_updates=dispatcher.resolve_used_update_types()
        )
    finally:
        await bot.session.close()
        await dispose_database()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    _run_migrations()
    asyncio.run(_run())


if __name__ == "__main__":
    main()
