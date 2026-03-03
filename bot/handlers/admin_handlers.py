import datetime as dt
import re

from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from sqlalchemy import select, or_, func

from bot.utils.filters import IsAdmin
from bot.utils.keyboards import Keyboards, DAYS
from bot.utils.state import ScheduleAdd, TeacherAdminState
from bot.db.database import async_session_maker
from bot.db.models import Schedule, ScheduleWeek, User


router_admin = Router()


def _format_week_label(week: ScheduleWeek) -> str:
    return f"{week.title} ({week.start_date.strftime('%d.%m')} - {week.end_date.strftime('%d.%m')})"


def _parse_date(value: str) -> dt.date | None:
    value = value.strip()
    for fmt in ("%d.%m.%Y", "%d.%m.%y"):
        try:
            return dt.datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _parse_time_range(value: str) -> tuple[str, str] | None:
    match = re.fullmatch(r"\s*(\d{1,2}:\d{2})\s*[-–—]\s*(\d{1,2}:\d{2})\s*", value or "")
    if not match:
        return None
    start_raw, end_raw = match.groups()
    try:
        start_time = dt.datetime.strptime(start_raw, "%H:%M").time()
        end_time = dt.datetime.strptime(end_raw, "%H:%M").time()
    except ValueError:
        return None
    if start_time >= end_time:
        return None
    return start_time.strftime("%H:%M"), end_time.strftime("%H:%M")


def _lesson_created_keyboard(lesson_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔁 Дублировать пару", callback_data=f"admin_duplicate_lesson_{lesson_id}")],
            [InlineKeyboardButton(text="🔙 В расписание", callback_data="admin_edit_schedule")],
        ]
    )


async def _get_weeks() -> list[ScheduleWeek]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(ScheduleWeek)
            .where(ScheduleWeek.is_active == 1)
            .order_by(ScheduleWeek.start_date)
        )
        return result.scalars().all()


async def _get_week_by_id(week_id: int) -> ScheduleWeek | None:
    async with async_session_maker() as session:
        return await session.get(ScheduleWeek, week_id)


def _week_filter(week_id: int):
    return or_(
        Schedule.week_id == week_id,
        Schedule.week_type == str(week_id),
        Schedule.week_type == f"week{week_id}",
    )


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

    lines = [f"📆 <b>{_format_week_label(week)}</b>"]
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


@router_admin.message(F.text == "👩‍🏫 Админ-панель")
@router_admin.message(F.text == "👨‍🏫 Админ-панель")
@router_admin.message(Command("admin"))
async def cmd_admin_panel(message: Message):
    if not await IsAdmin()(message):
        await message.answer("❌ У вас нет доступа к админ-панели.")
        return
    await message.answer(
        "👩‍🏫 <b>Панель старосты:</b>",
        reply_markup=Keyboards.get_admin_main_keyboard(),
        parse_mode="HTML",
    )


@router_admin.callback_query(F.data == "admin_edit_schedule")
async def goto_edit_schedule(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "⏰ <b>Редактирование расписания</b>",
        reply_markup=Keyboards.get_admin_schedule_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router_admin.callback_query(F.data == "admin_edit_common_files")
async def goto_edit_files(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "📚<b>Редактирование учебных материалов</b>",
        reply_markup=Keyboards.get_admin_common_edit_files_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router_admin.callback_query(F.data == "admin_edit_session_files")
async def goto_edit_session_files(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "🎓<b>Редактирование материалов для сессий</b>",
        reply_markup=Keyboards.get_admin_session_edit_files_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router_admin.callback_query(F.data == "admin_edit_reminders")
async def goto_edit_reminders(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "⏳<b>Редактирование напоминаний для преподавателей</b>",
        reply_markup=Keyboards.get_admin_reminders_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router_admin.callback_query(F.data == "admin_edit_events")
async def goto_edit_events(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "✨<b>Редактирование событий</b>",
        reply_markup=Keyboards.get_admin_events_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router_admin.callback_query(F.data == "goto_back")
async def goto_admin_panel(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "👩‍🏫 <b>Панель старосты:</b>",
        reply_markup=Keyboards.get_admin_main_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router_admin.callback_query(F.data == "admin_manage_teachers")
async def admin_manage_teachers(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "👨‍🏫 <b>Управление преподавателями</b>",
        reply_markup=Keyboards.get_admin_teachers_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router_admin.callback_query(F.data == "admin_add_teacher")
async def admin_add_teacher_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(TeacherAdminState.waiting_for_username)
    await callback.message.edit_text(
        "Введите username преподавателя (пример: <code>@ivanov</code>):\n\n"
        "Пользователь должен быть уже зарегистрирован в боте.",
        parse_mode="HTML",
    )
    await callback.answer()


@router_admin.message(StateFilter(TeacherAdminState.waiting_for_username), F.text)
async def admin_add_teacher_finish(message: Message, state: FSMContext):
    username = (message.text or "").strip().lstrip("@")
    if not username:
        await message.answer("❌ Username пустой. Введите username вида @example.")
        return

    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(func.lower(User.username) == username.lower())
        )
        user = result.scalar_one_or_none()
        if not user:
            await message.answer("❌ Пользователь с таким username не найден в БД.")
            return

        user.status = "teacher"
        await session.commit()
        teacher_telegram_id = user.user_id

    await state.clear()
    await message.answer(
        f"✅ Пользователь @{username} получил статус преподавателя.",
        reply_markup=Keyboards.get_admin_main_keyboard(),
    )

    try:
        await message.bot.send_message(
            teacher_telegram_id,
            "✅ Вам назначен статус преподавателя.\n\nДоступно отдельное меню:",
            reply_markup=Keyboards.get_teacher_menu(),
        )
    except Exception:
        await message.answer("⚠️ Не удалось отправить уведомление преподавателю в Telegram.")


@router_admin.callback_query(F.data == "admin_list_teachers")
async def admin_list_teachers(callback: CallbackQuery):
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.status == "teacher").order_by(User.username)
        )
        teachers = result.scalars().all()

    if not teachers:
        await callback.answer("Преподаватели не добавлены", show_alert=True)
        return

    lines = []
    for teacher in teachers:
        username = f"@{teacher.username}" if teacher.username else "без username"
        lines.append(f"• {username} (id: <code>{teacher.user_id}</code>)")

    await callback.message.edit_text(
        "👨‍🏫 <b>Список преподавателей:</b>\n\n" + "\n".join(lines),
        reply_markup=Keyboards.get_admin_teachers_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router_admin.callback_query(F.data == "admin_manage_weeks")
async def admin_manage_weeks(callback: CallbackQuery):
    weeks = await _get_weeks()
    keyboard = [
        [InlineKeyboardButton(text="➕ Добавить неделю", callback_data="admin_week_create")],
        [InlineKeyboardButton(text="✏️ Редактировать неделю", callback_data="admin_week_edit_menu")],
        [InlineKeyboardButton(text="➖ Удалить неделю", callback_data="admin_week_delete_menu")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_edit_schedule")],
    ]
    text = "🗓️ <b>Управление неделями</b>\n\n"
    if weeks:
        text += "Текущие недели:\n" + "\n".join(f"• {_format_week_label(w)}" for w in weeks)
    else:
        text += "Пока нет созданных недель."

    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard), parse_mode="HTML")
    await callback.answer()


@router_admin.callback_query(F.data == "admin_week_create")
@router_admin.callback_query(F.data == "admin_add_custom_week")
async def admin_week_create(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.update_data(week_edit_mode="create")
    await state.set_state(ScheduleAdd.week_title)
    await callback.message.edit_text(
        "Введите название недели (пример: <b>Неделя 01.03-07.03</b>):",
        parse_mode="HTML",
    )
    await callback.answer()


@router_admin.callback_query(F.data == "admin_week_edit_menu")
async def admin_week_edit_menu(callback: CallbackQuery):
    weeks = await _get_weeks()
    if not weeks:
        await callback.answer("Нет недель для редактирования", show_alert=True)
        return

    keyboard = [
        [InlineKeyboardButton(text=f"✏️ {_format_week_label(w)}", callback_data=f"admin_week_edit_{w.id}")]
        for w in weeks
    ]
    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_manage_weeks")])

    await callback.message.edit_text(
        "Выберите неделю для редактирования:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
    )
    await callback.answer()


@router_admin.callback_query(F.data.startswith("admin_week_edit_"))
async def admin_week_edit_pick(callback: CallbackQuery, state: FSMContext):
    week_id = int(callback.data.replace("admin_week_edit_", ""))
    week = await _get_week_by_id(week_id)
    if not week:
        await callback.answer("Неделя не найдена", show_alert=True)
        return

    await state.clear()
    await state.update_data(week_edit_mode="edit", edit_week_id=week.id)
    await state.set_state(ScheduleAdd.week_title)
    await callback.message.edit_text(
        f"Текущая неделя: <b>{_format_week_label(week)}</b>\n\n"
        "Введите новое название:",
        parse_mode="HTML",
    )
    await callback.answer()


@router_admin.callback_query(F.data == "admin_week_delete_menu")
async def admin_week_delete_menu(callback: CallbackQuery):
    weeks = await _get_weeks()
    if not weeks:
        await callback.answer("Нет недель для удаления", show_alert=True)
        return

    keyboard = [
        [InlineKeyboardButton(text=f"🗑 {_format_week_label(w)}", callback_data=f"admin_week_delete_{w.id}")]
        for w in weeks
    ]
    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_manage_weeks")])

    await callback.message.edit_text(
        "Выберите неделю для удаления:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
    )
    await callback.answer()


@router_admin.callback_query(F.data.startswith("admin_week_delete_"))
async def admin_week_delete(callback: CallbackQuery):
    week_id = int(callback.data.replace("admin_week_delete_", ""))
    async with async_session_maker() as session:
        week = await session.get(ScheduleWeek, week_id)
        if not week:
            await callback.answer("Неделя не найдена", show_alert=True)
            return

        lessons_res = await session.execute(select(Schedule).where(Schedule.week_id == week_id))
        for lesson in lessons_res.scalars().all():
            await session.delete(lesson)
        await session.delete(week)
        await session.commit()

    await callback.answer("Неделя удалена", show_alert=False)
    await admin_manage_weeks(callback)


@router_admin.message(StateFilter(ScheduleAdd.week_title))
async def week_title_received(message: Message, state: FSMContext):
    title = message.text.strip()
    if len(title) < 3:
        await message.answer("❌ Название слишком короткое.")
        return
    await state.update_data(week_title=title)
    await state.set_state(ScheduleAdd.week_start_date)
    await message.answer("Введите дату начала недели в формате ДД.ММ.ГГГГ (пример: 01.03.2026):")


@router_admin.message(StateFilter(ScheduleAdd.week_start_date))
async def week_start_date_received(message: Message, state: FSMContext):
    start_date = _parse_date(message.text)
    if not start_date:
        await message.answer("❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ.")
        return
    await state.update_data(week_start_date=start_date.isoformat())
    await state.set_state(ScheduleAdd.week_end_date)
    await message.answer("Введите дату конца недели в формате ДД.ММ.ГГГГ:")


@router_admin.message(StateFilter(ScheduleAdd.week_end_date))
async def week_end_date_received(message: Message, state: FSMContext):
    end_date = _parse_date(message.text)
    if not end_date:
        await message.answer("❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ.")
        return

    data = await state.get_data()
    start_date = dt.date.fromisoformat(data["week_start_date"])
    if end_date < start_date:
        await message.answer("❌ Дата конца не может быть раньше даты начала.")
        return

    async with async_session_maker() as session:
        mode = data.get("week_edit_mode", "create")
        if mode == "edit":
            week = await session.get(ScheduleWeek, int(data["edit_week_id"]))
            if not week:
                await message.answer("❌ Неделя не найдена.")
                await state.clear()
                return
            week.title = data["week_title"]
            week.start_date = start_date
            week.end_date = end_date
            action = "обновлена"
        else:
            week = ScheduleWeek(
                title=data["week_title"],
                start_date=start_date,
                end_date=end_date,
                is_active=1,
            )
            session.add(week)
            action = "создана"

        await session.commit()

    await state.clear()
    await message.answer(
        f"✅ Неделя {action}: <b>{data['week_title']}</b>",
        parse_mode="HTML",
        reply_markup=Keyboards.get_admin_schedule_keyboard(),
    )


@router_admin.callback_query(F.data == "admin_add_select_week")
async def goto_add_select_week(callback: CallbackQuery, state: FSMContext):
    weeks = await _get_weeks()
    if not weeks:
        await callback.message.edit_text(
            "Сначала создайте неделю с датами.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="➕ Создать неделю", callback_data="admin_week_create")],
                    [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_edit_schedule")],
                ]
            ),
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        "Выберите неделю для добавления пары:",
        reply_markup=Keyboards.get_admin_weeks_keyboard(
            weeks=[(w.id, _format_week_label(w)) for w in weeks],
            action="add",
            include_add_button=True,
        ),
    )
    await callback.answer()


@router_admin.callback_query(F.data.startswith("admin_add_week_"))
async def goto_add_select_day(callback: CallbackQuery, state: FSMContext):
    payload = callback.data.replace("admin_add_week_", "", 1)
    week_id = int(payload.split("|")[0])
    week = await _get_week_by_id(week_id)
    if not week:
        await callback.answer("Неделя не найдена", show_alert=True)
        return

    await callback.message.edit_text(
        f"📆 Неделя: <b>{_format_week_label(week)}</b>\n\nВыберите день для добавления пары:",
        reply_markup=Keyboards.get_admin_days_keyboard(
            action="add",
            from_menu="admin_add",
            week_type=str(week.id),
            full_schedule_callback=f"admin_week_full_{week.id}",
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router_admin.callback_query(F.data == "admin_del_select_week")
async def goto_del_select_week(callback: CallbackQuery, state: FSMContext):
    weeks = await _get_weeks()
    if not weeks:
        await callback.message.edit_text(
            "📭 В расписании пока нет недель.",
            reply_markup=Keyboards.get_admin_schedule_keyboard(),
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        "Выберите неделю для удаления пары:",
        reply_markup=Keyboards.get_admin_weeks_keyboard(
            weeks=[(w.id, _format_week_label(w)) for w in weeks],
            action="del",
        ),
    )
    await callback.answer()


@router_admin.callback_query(F.data.startswith("admin_del_week_"))
async def goto_del_select_day(callback: CallbackQuery, state: FSMContext):
    payload = callback.data.replace("admin_del_week_", "", 1)
    week_id = int(payload.split("|")[0])
    week = await _get_week_by_id(week_id)
    if not week:
        await callback.answer("Неделя не найдена", show_alert=True)
        return

    await callback.message.edit_text(
        f"📆 Неделя: <b>{_format_week_label(week)}</b>\n\nВыберите день для удаления пары:",
        reply_markup=Keyboards.get_admin_days_keyboard(
            action="del",
            from_menu="admin_del",
            week_type=str(week.id),
            full_schedule_callback=f"admin_week_full_{week.id}",
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router_admin.callback_query(F.data.startswith("admin_back_to_weeks_"))
async def back_to_weeks(callback: CallbackQuery):
    from_menu = callback.data.replace("admin_back_to_weeks_", "")
    weeks = await _get_weeks()

    if from_menu == "admin_add":
        await callback.message.edit_text(
            "Выберите неделю для добавления пары:",
            reply_markup=Keyboards.get_admin_weeks_keyboard(
                weeks=[(w.id, _format_week_label(w)) for w in weeks],
                action="add",
                include_add_button=True,
            ),
        )
    elif from_menu == "admin_del":
        await callback.message.edit_text(
            "Выберите неделю для удаления пары:",
            reply_markup=Keyboards.get_admin_weeks_keyboard(
                weeks=[(w.id, _format_week_label(w)) for w in weeks],
                action="del",
            ),
        )
    await callback.answer()


@router_admin.callback_query(F.data.startswith("admin_week_full_"))
async def admin_show_full_week(callback: CallbackQuery):
    week_id = int(callback.data.replace("admin_week_full_", ""))
    week = await _get_week_by_id(week_id)
    if not week:
        await callback.answer("Неделя не найдена", show_alert=True)
        return

    text = await _build_week_schedule_text(week)
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer("Полное расписание отправлено")


@router_admin.callback_query(F.data.startswith("add_"))
async def add_lesson_select_day(callback: CallbackQuery, state: FSMContext):
    payload = callback.data.replace("add_", "", 1)
    payload_parts = payload.split("|")
    day_id = payload_parts[0]
    week_id = int(payload_parts[2] if len(payload_parts) > 2 else "1")
    await state.update_data(day=day_id, week_id=week_id)

    week = await _get_week_by_id(week_id)
    week_name = _format_week_label(week) if week else f"Неделя {week_id}"

    try:
        await callback.message.edit_text(
            f"📆 Неделя: <b>{week_name}</b>\n"
            f"📅 День: <b>{DAYS[day_id]}</b>\n\n"
            "Введите номер пары (1, 2, 3...):",
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        await callback.answer()
        return

    await state.set_state(ScheduleAdd.lesson_number)
    await callback.answer()


@router_admin.message(StateFilter(ScheduleAdd.lesson_number))
async def add_lesson_number(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Введите число!")
        return
    await state.update_data(lesson_number=int(message.text))
    await message.answer("📚 Введите название предмета:")
    await state.set_state(ScheduleAdd.subject)


@router_admin.message(StateFilter(ScheduleAdd.subject))
async def add_lesson_subject(message: Message, state: FSMContext):
    await state.update_data(subject=message.text)
    await message.answer(
        "⏰ Введите время пары одним сообщением через тире.\n"
        "Пример: <code>09:00-10:30</code>",
        parse_mode="HTML",
    )
    await state.set_state(ScheduleAdd.time_start)


@router_admin.message(StateFilter(ScheduleAdd.time_start))
async def add_lesson_time_start(message: Message, state: FSMContext):
    parsed = _parse_time_range(message.text or "")
    if not parsed:
        await message.answer(
            "❌ Неверный формат времени.\n"
            "Отправьте в формате <code>HH:MM-HH:MM</code>, например <code>09:00-10:30</code>.",
            parse_mode="HTML",
        )
        return

    time_start, time_end = parsed
    data = await state.get_data()
    duplicate_template = data.get("duplicate_template")

    if duplicate_template:
        async with async_session_maker() as session:
            new_lesson = Schedule(
                week_id=duplicate_template["week_id"],
                week_type=str(duplicate_template["week_id"]),
                day_of_week=duplicate_template["day_of_week"],
                lesson_number=duplicate_template["lesson_number"],
                subject=duplicate_template["subject"],
                time_start=time_start,
                time_end=time_end,
                classroom=duplicate_template.get("classroom"),
                teacher=duplicate_template.get("teacher"),
            )
            session.add(new_lesson)
            await session.commit()
            await session.refresh(new_lesson)

        await message.answer(
            "✅ <b>Пара продублирована.</b>\n"
            f"Номер пары: <b>{duplicate_template['lesson_number']}</b>\n"
            f"Время: <b>{time_start}-{time_end}</b>",
            parse_mode="HTML",
            reply_markup=_lesson_created_keyboard(new_lesson.id),
        )
        await state.clear()
        return

    await state.update_data(time_start=time_start, time_end=time_end)
    await message.answer("🚪 Аудитория (или 'пропустить'):")
    await state.set_state(ScheduleAdd.classroom)


@router_admin.message(StateFilter(ScheduleAdd.classroom))
async def add_lesson_classroom(message: Message, state: FSMContext):
    await state.update_data(classroom=message.text if message.text != "пропустить" else None)
    await message.answer("👨‍🏫 Преподаватель (или 'пропустить'):")
    await state.set_state(ScheduleAdd.teacher)


@router_admin.message(StateFilter(ScheduleAdd.teacher))
async def add_lesson_finish(message: Message, state: FSMContext):
    data = await state.get_data()
    teacher = message.text if message.text != "пропустить" else None

    async with async_session_maker() as session:
        week_id = int(data.get("week_id", 1))
        new_lesson = Schedule(
            week_id=week_id,
            week_type=str(week_id),
            day_of_week=data["day"],
            lesson_number=data["lesson_number"],
            subject=data["subject"],
            time_start=data["time_start"],
            time_end=data["time_end"],
            classroom=data.get("classroom"),
            teacher=teacher,
        )
        session.add(new_lesson)
        await session.commit()
        await session.refresh(new_lesson)

    await message.answer(
        "✅ <b>Пара добавлена!</b>",
        parse_mode="HTML",
        reply_markup=_lesson_created_keyboard(new_lesson.id),
    )
    await state.clear()


@router_admin.callback_query(F.data.startswith("admin_duplicate_lesson_"))
async def duplicate_lesson_start(callback: CallbackQuery, state: FSMContext):
    lesson_id = int(callback.data.replace("admin_duplicate_lesson_", ""))
    async with async_session_maker() as session:
        lesson = await session.get(Schedule, lesson_id)
        if not lesson:
            await callback.answer("Пара не найдена", show_alert=True)
            return

        duplicate_template = {
            "week_id": lesson.week_id or 1,
            "day_of_week": lesson.day_of_week,
            "lesson_number": lesson.lesson_number + 1,
            "subject": lesson.subject,
            "classroom": lesson.classroom,
            "teacher": lesson.teacher,
        }

    await state.clear()
    await state.update_data(duplicate_template=duplicate_template)
    await state.set_state(ScheduleAdd.time_start)

    await callback.message.answer(
        "🔁 Дублирование пары\n"
        f"Предмет: <b>{duplicate_template['subject']}</b>\n"
        f"Номер пары для дубликата: <b>{duplicate_template['lesson_number']}</b>\n\n"
        "Введите время одним сообщением через тире.\n"
        "Пример: <code>10:40-12:10</code>",
        parse_mode="HTML",
    )
    await callback.answer()


@router_admin.callback_query(F.data.startswith("del_"))
async def delete_lesson_select_day(callback: CallbackQuery, state: FSMContext):
    payload = callback.data.replace("del_", "", 1)
    payload_parts = payload.split("|")
    day_id = payload_parts[0]
    week_id = int(payload_parts[2] if len(payload_parts) > 2 else "1")

    await state.update_data(day=day_id, week_id=week_id)

    async with async_session_maker() as session:
        result = await session.execute(
            select(Schedule)
            .where(
                Schedule.day_of_week == day_id,
                _week_filter(week_id),
            )
            .order_by(Schedule.lesson_number)
        )
        lessons = result.scalars().all()

    keyboard_empty = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад к дням", callback_data=f"admin_del_week_{week_id}|admin_del")]
        ]
    )

    if not lessons:
        try:
            await callback.message.edit_text("📭 На этот день пар нет.", reply_markup=keyboard_empty)
        except TelegramBadRequest:
            await callback.answer("📭 На этот день пар нет.", show_alert=True)
        return

    week = await _get_week_by_id(week_id)
    week_name = _format_week_label(week) if week else f"Неделя {week_id}"

    text = f"📆 {week_name}\n📅 {DAYS[day_id]}\n\nВыберите пару для удаления:\n"
    keyboard = []
    for lesson in lessons:
        keyboard.append(
            [InlineKeyboardButton(text=f"{lesson.lesson_number}. {lesson.subject}", callback_data=f"admin_del_confirm_{lesson.id}")]
        )
    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"admin_del_week_{week_id}|admin_del")])

    try:
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        await callback.answer()
        return

    await callback.answer()


@router_admin.callback_query(F.data.startswith("admin_del_confirm_"))
async def confirm_delete(callback: CallbackQuery, state: FSMContext):
    lesson_id_str = callback.data.split("_")[-1]
    if not lesson_id_str.isdigit():
        await callback.answer("❌ Неверный ID", show_alert=True)
        return

    lesson_id = int(lesson_id_str)

    async with async_session_maker() as session:
        result = await session.execute(select(Schedule).where(Schedule.id == lesson_id))
        lesson = result.scalar_one_or_none()

        if not lesson:
            await callback.answer("⚠️ Пара не найдена", show_alert=True)
            return

        lesson_subject = lesson.subject
        await session.delete(lesson)
        await session.commit()

    try:
        await callback.message.edit_text(
            f"✅ <b>{lesson_subject}</b> удалена!",
            reply_markup=Keyboards.get_admin_schedule_keyboard(),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        await callback.message.answer(
            f"✅ <b>{lesson_subject}</b> удалена!",
            reply_markup=Keyboards.get_admin_schedule_keyboard(),
            parse_mode="HTML",
        )

    await callback.answer()
    await state.clear()
