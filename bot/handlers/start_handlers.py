from aiogram import types, Router, F
from aiogram.types import Message
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext

from bot.utils.keyboards import Keyboards
from bot.utils.messages import Messages
from bot.utils.state import SignUp

from bot.config import Config

from bot.db.database import async_session_maker
from bot.db.models import User

from sqlalchemy import select


router_start = Router()


router_start.message.filter(lambda msg: msg.from_user.id)


def _menu_by_status(status: str):
    if status == "admin":
        return Keyboards.get_admin_menu()
    if status == "teacher":
        return Keyboards.get_teacher_menu()
    return Keyboards.get_student_menu()


@router_start.message(Command('start'))
@router_start.message(F.text == "main_menu")
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    username = message.from_user.username

    initial_status = "admin" if user_id in Config.ADMIN_IDS else "student"

    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one_or_none()

        if not user:
            user = User(user_id=user_id, username=username,
                        status=initial_status)
            session.add(user)
            await session.commit()

            role_text = "старостой 🎓" if initial_status == "admin" else "студентом 📚"
            await message.answer(f"👋 Привет! Я записал тебя {role_text}.")
        else:
            if user.username != username:
                user.username = username
                await session.commit()
            await message.answer(f"👋 С возвращением, {message.from_user.first_name}!")

        await message.answer("📋 Главное меню:", reply_markup=_menu_by_status(user.status or "student"))


@router_start.message(F.text == "🆘 Помощь")
@router_start.message(Command('help'))
async def cmd_help(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id

    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one_or_none()

    status = user.status if user and user.status else ("admin" if user_id in Config.ADMIN_IDS else "student")
    if status == "admin":
        await message.answer(
            "🆘 <b>Доступные команды:</b>\n\n"
            "/start - Меню\n"
            "/schedule - Расписание\n"
            "/view_file - Просмотр файлов\n"
            "/admin - Панель старосты",
            parse_mode="HTML"
        )
    elif status == "teacher":
        await message.answer(
            "🆘 <b>Меню преподавателя:</b>\n\n"
            "📅 Расписание\n"
            "✨ События\n"
            "📝 Задания к семинарам\n"
            "📤 Отправить задание",
            parse_mode="HTML",
        )
    else:
        await message.answer(
            "🆘 <b>Доступные команды:</b>\n\n"
            "/start - Меню\n"
            "/view_file - Просмотр файлов\n"
            "/schedule - Расписание\n",
            parse_mode="HTML"
        )
