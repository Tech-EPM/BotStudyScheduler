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
        "📝 Введите сообщение для администратора.\n"
        "Для отмены нажмите «❌ Отмена».",
        reply_markup=Keyboards.get_teacher_task_cancel_keyboard(),
    )


@router_teacher.message(
    StateFilter(TeacherTaskState.waiting_for_message),
    F.text,
)
async def teacher_send_task_save_message(message: types.Message, state: FSMContext, session: AsyncSession):
    if not await _is_teacher(session, message.from_user.id):
        await state.clear()
        return

    text = (message.text or "").strip()
    if text.lower() in {"отмена", "❌ отмена"}:
        await state.clear()
        await message.answer("❌ Отправка отменена.", reply_markup=Keyboards.get_teacher_menu())
        return

    if not text:
        await message.answer("❌ Сообщение не может быть пустым.")
        return

    await state.update_data(task_text=text)
    await state.set_state(TeacherTaskState.waiting_for_attachment)
    await message.answer(
        "📎 Добавьте файл или фото.\n"
        "Если вложение не нужно, нажмите «⏭ Пропустить».",
        reply_markup=Keyboards.get_teacher_task_attachment_keyboard(),
    )


@router_teacher.message(StateFilter(TeacherTaskState.waiting_for_message))
async def teacher_send_task_invalid_first_step(message: types.Message):
    await message.answer(
        "❌ Сначала отправьте текстовое сообщение задания.",
        reply_markup=Keyboards.get_teacher_task_cancel_keyboard(),
    )


@router_teacher.message(
    StateFilter(TeacherTaskState.waiting_for_attachment),
    F.text | F.photo | F.document,
)
async def teacher_send_task_finish(message: types.Message, state: FSMContext, session: AsyncSession):
    if not await _is_teacher(session, message.from_user.id):
        await state.clear()
        return

    text = (message.text or "").strip().lower()
    if text in {"отмена", "❌ отмена"}:
        await state.clear()
        await message.answer("❌ Отправка отменена.", reply_markup=Keyboards.get_teacher_menu())
        return

    data = await state.get_data()
    task_text = data.get("task_text", "").strip()
    if not task_text:
        await state.clear()
        await message.answer("❌ Сессия отправки сброшена. Начните заново.", reply_markup=Keyboards.get_teacher_menu())
        return

    attachment = None
    if message.photo:
        attachment = "photo"
    elif message.document:
        attachment = "document"
    elif text == "⏭ пропустить":
        attachment = None
    elif message.text:
        await message.answer(
            "❌ Пришлите файл/фото или нажмите «⏭ Пропустить».",
            reply_markup=Keyboards.get_teacher_task_attachment_keyboard(),
        )
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
            await message.bot.send_message(
                admin_id,
                f"{header}\n\n📝 <b>Сообщение:</b>\n{task_text}",
                parse_mode="HTML",
            )
            if attachment:
                await message.copy_to(admin_id)
            delivered += 1
        except Exception:
            continue

    await state.clear()
    if delivered:
        await message.answer("✅ Задание отправлено администратору.", reply_markup=Keyboards.get_teacher_menu())
    else:
        await message.answer("❌ Не удалось отправить задание администратору.", reply_markup=Keyboards.get_teacher_menu())
