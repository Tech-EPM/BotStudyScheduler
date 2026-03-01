from aiogram import Router, F
from aiogram.filters import Command 
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

from aiogram.fsm.context import FSMContext

from bot.utils.filters import IsStudent
from bot.utils.keyboards import Keyboards, DAYS
from bot.db.database import async_session_maker
from sqlalchemy import select, or_
from bot.db.models import Schedule

import logging


router_student = Router()


def _normalize_week_value(raw_value: str | None) -> str:
    if raw_value is None:
        return "1"
    value = str(raw_value).strip().lower()
    if value.startswith("week") and value[4:].isdigit():
        value = value[4:]
    if value.isdigit():
        return str(int(value))
    return value


def _week_title(week_value: str) -> str:
    return f"{week_value} неделя"


def _week_sort_key(value: str):
    return (0, int(value)) if value.isdigit() else (1, value)


def _week_filter(week_value: str):
    conditions = [
        Schedule.week_type == week_value,
        Schedule.week_type == f"week{week_value}",
    ]
    if week_value == "1":
        conditions.append(Schedule.week_type.is_(None))
    return or_(*conditions)


async def _get_available_weeks() -> list[str]:
    async with async_session_maker() as session:
        result = await session.execute(select(Schedule.week_type).distinct())
        raw_weeks = result.scalars().all()

    weeks = {_normalize_week_value(value) for value in raw_weeks}
    weeks.discard("")
    if not weeks:
        return []
    return sorted(weeks, key=_week_sort_key)


@router_student.message(F.text == "📅 Расписание")
@router_student.message(Command('schedule'))
async def cmd_schedule(message: Message):
    weeks = await _get_available_weeks()
    if not weeks:
        await message.answer("📭 Расписание пока не добавлено.")
        return
    await message.answer(
        "📆 <b>Выберите неделю:</b>",
        reply_markup=Keyboards.get_student_weeks_keyboard(weeks=weeks, from_menu="main"),
        parse_mode="HTML"
    )


@router_student.callback_query(F.data.startswith("week_"))
async def show_week_days(callback: CallbackQuery):
    try:
        week_part, from_menu = callback.data.split("|")
        week_type = _normalize_week_value(week_part.replace("week_", ""))
    except ValueError:
        week_type = _normalize_week_value(callback.data.replace("week_", ""))
        from_menu = "main"

    await callback.message.edit_text(
        f"📆 <b>{_week_title(week_type)}</b>\n\nВыберите день недели:",
        reply_markup=Keyboards.get_student_days_keyboard(
            action="view",
            from_menu=from_menu,
            week_type=week_type
        ),
        parse_mode="HTML"
    )
    await callback.answer()


@router_student.callback_query(F.data.startswith("day_"))
async def show_day_schedule(callback: CallbackQuery):
    try:
        day_part, from_menu, week_type = callback.data.split("|")
        day_id = day_part.replace("day_", "")
        week_type = _normalize_week_value(week_type)
    except ValueError:
        parts = callback.data.split("|")
        day_id = parts[0].replace("day_", "")
        from_menu = "main"
        week_type = "1"
    
    day_name = DAYS.get(day_id, day_id)
    week_name = _week_title(week_type)
    

    async with async_session_maker() as session:
        result = await session.execute(
            select(Schedule)
            .where(
                Schedule.day_of_week == day_id,
                _week_filter(week_type)
            )
            .order_by(Schedule.lesson_number)
        )
        lessons = result.scalars().all()


    if not lessons:
        text = f"📭 <b>{week_name}</b> • <b>{day_name}</b>\n\nНа этот день пар нет."
    else:
        text = f"📆 <b>{week_name}</b>\n📅 <b>{day_name}</b>\n\n"
        for lesson in lessons:
            text += f"<b>{lesson.lesson_number}.</b> {lesson.time_start}-{lesson.time_end}\n"
            text += f"   📚 {lesson.subject}\n"
            if lesson.classroom:
                text += f"   🚪 Ауд. {lesson.classroom}\n"
            if lesson.teacher:
                text += f"   👨‍🏫 {lesson.teacher}\n"
            text += "\n"


    keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад к дням", callback_data=f"back_to_days_{from_menu}|{week_type}")],
            [InlineKeyboardButton(text="📆 Выбрать неделю", callback_data=f"back_to_weeks_{from_menu}")],
        ])


    try:
        await callback.message.edit_text(
            text, 
            reply_markup=keyboard, 
            parse_mode="HTML"
        )
    except TelegramBadRequest:
        await callback.answer()
        return
    
    try:
        await callback.answer()
    except TelegramBadRequest as e:
        if "query is too old" in str(e) or "query ID is invalid" in str(e):
            logger = logging.getLogger(__name__)
            logger.warning(f"⚠️ Old callback query from user {callback.from_user.id}")
        else:
            raise



@router_student.callback_query(F.data == "goto_back_student")
async def goto_admin_panel(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "👨‍🏫 <b>Панель студента:</b>\n",
        reply_markup=Keyboards.get_student_main_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


# Возврат назад
@router_student.callback_query(F.data.startswith("back_to_"))
async def back_handler(callback: CallbackQuery):
    if callback.data.startswith("back_to_weeks_"):
        from_menu = callback.data.replace("back_to_weeks_", "")
        weeks = await _get_available_weeks()
        if not weeks:
            await callback.message.edit_text("📭 Расписание пока не добавлено.")
            await callback.answer()
            return
        try:
            await callback.message.edit_text(
                "📆 <b>Выберите неделю:</b>",
                reply_markup=Keyboards.get_student_weeks_keyboard(weeks=weeks, from_menu=from_menu),
                parse_mode="HTML"
            )
        except TelegramBadRequest:
            await callback.answer()
            return
        await callback.answer()
        return

    if callback.data.startswith("back_to_days_"):
        payload = callback.data.replace("back_to_days_", "")
        parts = payload.split("|")
        from_menu = parts[0] if parts else "main"
        week_type = _normalize_week_value(parts[1] if len(parts) > 1 else "1")

        try:
            await callback.message.edit_text(
                f"📆 <b>{_week_title(week_type)}</b>\n\nВыберите день недели:",
                reply_markup=Keyboards.get_student_days_keyboard(
                    action="view",
                    from_menu=from_menu,
                    week_type=week_type
                ),
                parse_mode="HTML"
            )
        except TelegramBadRequest:
            await callback.answer()
            return

        await callback.answer()
        return


@router_student.message(F.text == "🆘 Помощь")
@router_student.message(Command('help'))
async def cmd_help(message: Message):
    await message.answer(
        "🆘 <b>Доступные команды:</b>\n\n"
        "/start - Регистрация\n"
        "/schedule - Моё расписание\n"
        "/view_file - Просмотр файлов\n"
        "/help - Эта справка",
        parse_mode="HTML"
    )
