import asyncio
import logging

from tg_textmarkup_bot.bot import create_bot, create_dispatcher
from tg_textmarkup_bot.config import get_settings
from tg_textmarkup_bot.db.engine import dispose_database, setup_database


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
    asyncio.run(_run())


if __name__ == "__main__":
    main()
