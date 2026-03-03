from datetime import datetime

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Config
from bot.db.models import User
from bot.utils.keyboards import Keyboards
from bot.utils.state import TeacherTaskState


router_teacher = Router()


async def _is_teacher(session: AsyncSession, telegram_user_id: int) -> bool:
    result = await session.execute(select(User).where(User.user_id == telegram_user_id))
    user = result.scalar_one_or_none()
    return bool(user and user.status == "teacher")


@router_teacher.message(F.text == "📤 Отправить задание")
async def teacher_send_task_start(message: types.Message, state: FSMContext, session: AsyncSession):
    if not await _is_teacher(session, message.from_user.id):
        return

    await state.set_state(TeacherTaskState.waiting_for_message)
    await message.answer(
        "Отправьте задание одним сообщением.\n"
        "Можно текст, фото или документ.\n"
        "Для отмены напишите: отмена"
    )


@router_teacher.message(
    StateFilter(TeacherTaskState.waiting_for_message),
    F.text | F.photo | F.document,
)
async def teacher_send_task_finish(message: types.Message, state: FSMContext, session: AsyncSession):
    if not await _is_teacher(session, message.from_user.id):
        await state.clear()
        return

    if (message.text or "").strip().lower() == "отмена":
        await state.clear()
        await message.answer("❌ Отправка отменена.", reply_markup=Keyboards.get_teacher_menu())
        return

    sender = message.from_user
    sender_name = sender.full_name
    sender_username = f"@{sender.username}" if sender.username else "без username"
    header = (
        "📥 <b>Новое задание от преподавателя</b>\n"
        f"👤 {sender_name} ({sender_username})\n"
        f"🆔 <code>{sender.id}</code>\n"
        f"🕒 {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    )

    delivered = 0
    for admin_id in Config.ADMIN_IDS:
        try:
            if message.text:
                await message.bot.send_message(
                    admin_id,
                    f"{header}\n\n📝 <b>Сообщение:</b>\n{message.text}",
                    parse_mode="HTML",
                )
            else:
                await message.bot.send_message(admin_id, header, parse_mode="HTML")
                await message.copy_to(admin_id)
            delivered += 1
        except Exception:
            continue

    await state.clear()
    if delivered:
        await message.answer("✅ Задание отправлено администратору.", reply_markup=Keyboards.get_teacher_menu())
    else:
        await message.answer("❌ Не удалось отправить задание администратору.", reply_markup=Keyboards.get_teacher_menu())
