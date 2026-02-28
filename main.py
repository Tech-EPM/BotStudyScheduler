import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import Config
from bot.handlers import routes
from bot.db.database import init_db, async_session_maker
from bot.middlewares.database import DatabaseMiddleware

from aiogram.client.session.aiohttp import AiohttpSession

from bot.utils.reminder_service import (
    init_reminder_service,
    shutdown_reminder_service
)


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

storage = MemoryStorage()
session = AiohttpSession(timeout=60)
bot = Bot(
    token=Config.TELEGRAM_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=storage)

# 🔧 Подключаем middleware для БД
dp.update.middleware(DatabaseMiddleware(async_session_maker))


async def on_startup():
    """Выполняется при запуске бота"""
    await init_reminder_service(bot)
    logging.info("✅ Reminder service started via init function")


async def on_shutdown():
    """Выполняется при остановке бота"""
    await shutdown_reminder_service()
    logging.info("✅ Reminder service stopped")


async def main():
    try:
        await init_db()
        logging.info("✅ Таблицы БД созданы/проверены")

        for router in routes:
            dp.include_router(router)
            logging.info(f'Router - {router}, connected')

        dp.startup.register(on_startup)
        dp.shutdown.register(on_shutdown)

        logging.info("🚀 Бот запущен")
        await dp.start_polling(bot, skip_updates=True)

    except Exception as e:
        logging.error(f"❌ Ошибка запуска бота: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())