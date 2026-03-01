import datetime as dt
import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

from bot.utils.keyboards import Keyboards, DAYS
from bot.db.database import async_session_maker
from sqlalchemy import select, or_
from bot.db.models import Schedule, ScheduleWeek


router_student = Router()


def _week_filter(week_id: int):
    return or_(
        Schedule.week_id == week_id,
        Schedule.week_type == str(week_id),
        Schedule.week_type == f"week{week_id}",
    )


async def _get_current_week() -> ScheduleWeek | None:
    today = dt.date.today()
    async with async_session_maker() as session:
        result = await session.execute(
            select(ScheduleWeek)
            .where(
                ScheduleWeek.is_active == 1,
                ScheduleWeek.start_date <= today,
                ScheduleWeek.end_date >= today,
            )
            .order_by(ScheduleWeek.start_date.desc())
        )
        return result.scalars().first()


def _week_label(week: ScheduleWeek) -> str:
    return f"{week.title} ({week.start_date.strftime('%d.%m')} - {week.end_date.strftime('%d.%m')})"


async def _build_week_schedule_text(week: ScheduleWeek) -> str:
    async with async_session_maker() as session:
        result = await session.execute(
            select(Schedule)
            .where(_week_filter(week.id))
            .order_by(Schedule.day_of_week, Schedule.lesson_number)
        )
        lessons = result.scalars().all()

    by_day: dict[str, list[Schedule]] = {day: [] for day in DAYS.keys()}
    for lesson in lessons:
        by_day.setdefault(lesson.day_of_week, []).append(lesson)

    lines = [f"📆 <b>{_week_label(week)}</b>"]
    for day_id in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday"):
        lines.append(f"\n<b>{DAYS[day_id]}</b>")
        day_lessons = sorted(by_day.get(day_id, []), key=lambda l: l.lesson_number)
        if not day_lessons:
            lines.append("• Пар нет")
            continue

        for lesson in day_lessons:
            row = f"• {lesson.lesson_number}. {lesson.time_start}-{lesson.time_end} {lesson.subject}"
            extra = []
            if lesson.classroom:
                extra.append(f"ауд. {lesson.classroom}")
            if lesson.teacher:
                extra.append(lesson.teacher)
            if extra:
                row += f" ({', '.join(extra)})"
            lines.append(row)

    return "\n".join(lines)


@router_student.message(F.text == "📅 Расписание")
@router_student.message(Command("schedule"))
async def cmd_schedule(message: Message):
    week = await _get_current_week()
    if not week:
        await message.answer("📭 Актуальная неделя не настроена. Попросите администратора добавить даты недели.")
        return

    await message.answer(
        f"📆 <b>Актуальная неделя:</b> {week.title}\n"
        f"<i>{week.start_date.strftime('%d.%m.%Y')} - {week.end_date.strftime('%d.%m.%Y')}</i>\n\n"
        "Выберите день недели:",
        reply_markup=Keyboards.get_student_days_keyboard(
            action="view",
            from_menu="current",
            week_type=str(week.id),
            full_schedule_callback=f"student_week_full_{week.id}",
            include_week_select=False,
        ),
        parse_mode="HTML",
    )


@router_student.callback_query(F.data.startswith("day_"))
async def show_day_schedule(callback: CallbackQuery):
    try:
        day_part, from_menu, week_raw = callback.data.split("|")
        day_id = day_part.replace("day_", "")
        week_id = int(week_raw)
    except ValueError:
        await callback.answer("Некорректные данные", show_alert=True)
        return

    day_name = DAYS.get(day_id, day_id)

    async with async_session_maker() as session:
        week = await session.get(ScheduleWeek, week_id)
        result = await session.execute(
            select(Schedule)
            .where(Schedule.day_of_week == day_id, _week_filter(week_id))
            .order_by(Schedule.lesson_number)
        )
        lessons = result.scalars().all()

    week_name = _week_label(week) if week else f"Неделя {week_id}"
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

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад к дням", callback_data=f"back_to_days_current|{week_id}")],
            [InlineKeyboardButton(text="📋 Полное расписание", callback_data=f"student_week_full_{week_id}")],
        ]
    )

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
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


@router_student.callback_query(F.data.startswith("student_week_full_"))
async def student_full_week(callback: CallbackQuery):
    week_id = int(callback.data.replace("student_week_full_", ""))
    async with async_session_maker() as session:
        week = await session.get(ScheduleWeek, week_id)

    if not week:
        await callback.answer("Неделя не найдена", show_alert=True)
        return

    text = await _build_week_schedule_text(week)
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer("Полное расписание отправлено")


@router_student.callback_query(F.data.startswith("back_to_days_"))
async def back_to_days(callback: CallbackQuery):
    payload = callback.data.replace("back_to_days_", "")
    parts = payload.split("|")
    week_id = int(parts[1] if len(parts) > 1 else 1)

    async with async_session_maker() as session:
        week = await session.get(ScheduleWeek, week_id)

    if not week:
        await callback.answer("Неделя не найдена", show_alert=True)
        return

    try:
        await callback.message.edit_text(
            f"📆 <b>{_week_label(week)}</b>\n\nВыберите день недели:",
            reply_markup=Keyboards.get_student_days_keyboard(
                action="view",
                from_menu="current",
                week_type=str(week.id),
                full_schedule_callback=f"student_week_full_{week.id}",
                include_week_select=False,
            ),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        await callback.answer()
        return

    await callback.answer()


@router_student.message(F.text == "🆘 Помощь")
@router_student.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "🆘 <b>Доступные команды:</b>\n\n"
        "/start - Регистрация\n"
        "/schedule - Моё расписание\n"
        "/view_file - Просмотр файлов\n"
        "/help - Эта справка",
        parse_mode="HTML",
    )
