import logging
import asyncio
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from sqlalchemy import select
from bot.db.models import Reminder, SeminarTask
from bot.db.database import async_session_maker  # 👈 Используем ваш factory

logger = logging.getLogger(__name__)


class ReminderService:
    def __init__(self, bot):
        self.bot = bot
        self.scheduler = AsyncIOScheduler(
            event_loop=asyncio.get_running_loop())

    async def start(self):
        """Запуск планировщика и загрузка задач из БД"""
        self.scheduler.start()
        self.scheduler.add_job(
            self._cleanup_expired_seminar_tasks,
            trigger="interval",
            hours=1,
            id="cleanup_expired_seminar_tasks",
            replace_existing=True,
        )
        await self._load_pending_reminders()
        logger.info("Reminder service started")

    async def _load_pending_reminders(self):
        """Загружает все активные напоминания из БД при старте"""
        async with async_session_maker() as session:
            result = await session.execute(
                select(Reminder).where(Reminder.status == 0)
            )
            reminders = result.scalars().all()

        count = 0
        for reminder in reminders:
            if reminder.send_at > datetime.now():
                self._schedule_job(reminder)
                count += 1
            else:
                await self._mark_as_sent(reminder.id)

        logger.info(f"📥 Loaded {count} pending reminders from database")

    def _schedule_job(self, reminder: Reminder):
        """Добавляет задачу в планировщик"""
        self.scheduler.add_job(
            self._send_reminder,
            trigger=DateTrigger(run_date=reminder.send_at),
            args=[reminder.id, reminder.target_user_id, reminder.text],
            id=f"reminder_{reminder.id}",
            replace_existing=True,
            misfire_grace_time=60  # Допуск 60 секунд, если бот был перезагружен
        )
        logger.debug(
            f"📅 Scheduled reminder {reminder.id} for {reminder.send_at}")

    async def _send_reminder(self, reminder_id: str, user_id: int, text: str):
        """Функция отправки (вызывается планировщиком)"""
        try:
            await self.bot.send_message(
                chat_id=user_id,
                text=f"🔔 <b>Напоминание</b>:\n\n{text}",
                parse_mode="HTML"
            )
            await self._mark_as_sent(reminder_id)
            logger.info(f"✅ Reminder {reminder_id} sent to {user_id}")
        except Exception as e:
            logger.error(f"❌ Failed to send reminder {reminder_id}: {e}")
            # Можно добавить логику повторной отправки или уведомления админа

    async def _mark_as_sent(self, reminder_id: str):
        """Помечает напоминание как отправленное в БД"""
        async with async_session_maker() as session:
            result = await session.execute(
                select(Reminder).where(Reminder.id == reminder_id)
            )
            reminder = result.scalar_one_or_none()
            if reminder:
                reminder.status = 1  # 1 = отправлено
                await session.commit()
                logger.debug(f"🗂️ Reminder {reminder_id} marked as sent")

    async def create_reminder(self, target_user_id: int, text: str, send_at: datetime, created_by_id: int = None):
        """Создает напоминание в БД и планирует его"""
        send_at = send_at - timedelta(hours=3)

        reminder = Reminder(
            target_user_id=target_user_id,
            text=text,
            send_at=send_at,
            created_by=created_by_id
        )

        async with async_session_maker() as session:
            session.add(reminder)
            await session.commit()
            await session.refresh(reminder)

        self._schedule_job(reminder)
        logger.info(f"✨ Created reminder {reminder.id}")
        return reminder

    async def _cleanup_expired_seminar_tasks(self):
        """Удаляет задания, у которых прошли сутки после дедлайна."""
        cutoff = datetime.now().date() - timedelta(days=1)
        async with async_session_maker() as session:
            result = await session.execute(
                select(SeminarTask).where(
                    SeminarTask.due_date.is_not(None),
                    SeminarTask.due_date < cutoff,
                )
            )
            expired_tasks = result.scalars().all()

            if not expired_tasks:
                return

            for task in expired_tasks:
                await session.delete(task)
            await session.commit()
            logger.info(f"🧹 Deleted expired seminar tasks: {len(expired_tasks)}")

    async def stop(self):
        """Корректная остановка планировщика"""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=True)
            logger.info("🛑 Scheduler shutdown complete")


reminder_service: ReminderService | None = None


# Глобальная переменная
reminder_service: ReminderService | None = None


async def init_reminder_service(bot):
    """Инициализация сервиса — вызывается при старте бота"""
    global reminder_service
    if reminder_service is None:
        reminder_service = ReminderService(bot)
        await reminder_service.start()
        logger.info("✅ ReminderService initialized and started")
    return reminder_service


async def shutdown_reminder_service():
    """Остановка сервиса при выключении бота"""
    global reminder_service
    if reminder_service:
        await reminder_service.stop()
        reminder_service = None
        logger.info("🛑 ReminderService stopped")


def get_reminder_service() -> ReminderService:
    """Фабричная функция для получения сервиса в хэндлерах"""
    if reminder_service is None:
        raise RuntimeError(
            "ReminderService not initialized! "
            "Call await init_reminder_service(bot) during bot startup."
        )
    return reminder_service
