from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
import datetime as dt

from bot.db.models import SeminarTask
from bot.utils.state import SeminarTaskState
from bot.utils.keyboards import Keyboards
from bot.utils.file_storage import (
    save_file,
    allowed_file,
    get_file_full_path,
    delete_file_async,
    sanitize_path_component,
)


router_admin_seminars = Router()


def _parse_due_date(value: str) -> dt.date | None:
    value = (value or "").strip()
    try:
        return dt.datetime.strptime(value, "%d.%m.%Y").date()
    except ValueError:
        return None


def _admin_seminar_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить задание", callback_data="admin_seminar_add")],
            [InlineKeyboardButton(text="✏️ Редактировать задание", callback_data="admin_seminar_edit")],
            [InlineKeyboardButton(text="➖ Удалить задание", callback_data="admin_seminar_delete")],
            [InlineKeyboardButton(text="📋 Список заданий", callback_data="admin_seminar_list")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="goto_back")],
        ]
    )


async def _show_subjects(callback: types.CallbackQuery, session: AsyncSession, mode: str):
    rows = await session.execute(
        select(func.min(SeminarTask.id), SeminarTask.subject)
        .group_by(SeminarTask.subject)
        .order_by(SeminarTask.subject)
    )
    subjects = [(rep_id, subject) for rep_id, subject in rows.all() if subject]

    if not subjects:
        await callback.answer("Заданий пока нет", show_alert=True)
        return

    keyboard = [
        [InlineKeyboardButton(text=f"📘 {subject}", callback_data=f"admin_seminar_subject_{mode}_{rep_id}")]
        for rep_id, subject in subjects
    ]
    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_edit_seminar_tasks")])

    await callback.message.edit_text(
        "Выберите предмет:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
    )
    await callback.answer()


@router_admin_seminars.callback_query(F.data == "admin_edit_seminar_tasks")
async def seminar_admin_menu(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "📝 <b>Редактирование заданий к семинарам</b>",
        reply_markup=_admin_seminar_menu(),
        parse_mode="HTML",
    )
    await callback.answer()


@router_admin_seminars.callback_query(F.data == "admin_seminar_add")
async def seminar_add_start(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    await state.clear()
    await state.set_state(SeminarTaskState.waiting_for_subject)

    rows = await session.execute(
        select(func.min(SeminarTask.id), SeminarTask.subject)
        .group_by(SeminarTask.subject)
        .order_by(SeminarTask.subject)
    )
    subjects = [(rep_id, subject) for rep_id, subject in rows.all() if subject]

    keyboard = [
        [InlineKeyboardButton(text=f"📘 {subject}", callback_data=f"admin_seminar_pick_subject_{rep_id}")]
        for rep_id, subject in subjects[:20]
    ]
    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_edit_seminar_tasks")])

    await callback.message.edit_text(
        "Введите предмет (на русском) или выберите существующий:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
    )
    await callback.answer()


@router_admin_seminars.message(StateFilter(SeminarTaskState.waiting_for_subject), F.text)
async def seminar_add_subject(message: types.Message, state: FSMContext):
    subject = message.text.strip()
    if len(subject) < 2:
        await message.answer("❌ Слишком короткое название предмета")
        return
    await state.update_data(subject=subject)
    await state.set_state(SeminarTaskState.waiting_for_title)
    await message.answer("Введите заголовок задания:")


@router_admin_seminars.callback_query(
    StateFilter(SeminarTaskState.waiting_for_subject),
    F.data.startswith("admin_seminar_pick_subject_"),
)
async def seminar_add_subject_from_existing(
    callback: types.CallbackQuery, state: FSMContext, session: AsyncSession
):
    rep_id = int(callback.data.replace("admin_seminar_pick_subject_", ""))
    rep = await session.get(SeminarTask, rep_id)
    if not rep or not rep.subject:
        await callback.answer("❌ Предмет не найден", show_alert=True)
        return

    await state.update_data(subject=rep.subject)
    await state.set_state(SeminarTaskState.waiting_for_title)
    await callback.message.edit_text(f"📘 Предмет: <b>{rep.subject}</b>\n\nВведите заголовок задания:", parse_mode="HTML")
    await callback.answer()


@router_admin_seminars.message(StateFilter(SeminarTaskState.waiting_for_title), F.text)
async def seminar_add_title(message: types.Message, state: FSMContext):
    title = message.text.strip()
    if len(title) < 2:
        await message.answer("❌ Слишком короткий заголовок")
        return
    await state.update_data(title=title)
    await state.set_state(SeminarTaskState.waiting_for_description)
    await message.answer("Введите описание задания (или напишите 'пропустить'):")


@router_admin_seminars.message(StateFilter(SeminarTaskState.waiting_for_description), F.text)
async def seminar_add_description(message: types.Message, state: FSMContext):
    description = None if message.text.strip().lower() == "пропустить" else message.text.strip()
    await state.update_data(description=description)
    await state.set_state(SeminarTaskState.waiting_for_due_date)
    await message.answer(
        "Введите дедлайн задания в формате <code>ДД.ММ.ГГГГ</code>\n"
        "Например: <code>25.03.2026</code>\n\n"
        "Или напишите <code>пропустить</code> без даты.",
        parse_mode="HTML",
    )


@router_admin_seminars.message(StateFilter(SeminarTaskState.waiting_for_due_date), F.text)
async def seminar_add_due_date(message: types.Message, state: FSMContext):
    raw_value = (message.text or "").strip()
    due_date = None
    if raw_value.lower() != "пропустить":
        due_date = _parse_due_date(raw_value)
        if not due_date:
            await message.answer("❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ или 'пропустить'.")
            return

    await state.update_data(due_date=due_date.isoformat() if due_date else None)
    await state.set_state(SeminarTaskState.waiting_for_file)
    await message.answer(
        "Пришлите файл задания (опционально), либо нажмите 'Пропустить':",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⏭️ Пропустить", callback_data="admin_seminar_skip_file")]]
        ),
    )


@router_admin_seminars.message(StateFilter(SeminarTaskState.waiting_for_file), F.photo | F.document)
async def seminar_add_file(message: types.Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()

    if message.photo:
        photo = message.photo[-1]
        file_info = await message.bot.get_file(photo.file_id)
        file_io = await message.bot.download_file(file_info.file_path)
        file_bytes = file_io.read()
        original_name = f"photo_{photo.file_id[:8]}.jpg"
    else:
        doc = message.document
        if doc.file_size > 20 * 1024 * 1024:
            await message.answer("❌ Файл слишком большой (макс. 20 МБ)")
            return
        if not allowed_file(doc.file_name):
            await message.answer("❌ Тип файла не поддерживается")
            return
        file_info = await message.bot.get_file(doc.file_id)
        file_io = await message.bot.download_file(file_info.file_path)
        file_bytes = file_io.read()
        original_name = doc.file_name

    if data.get("edit_mode") == "replace_file":
        task = await session.get(SeminarTask, int(data["edit_task_id"]))
        if not task:
            await state.clear()
            await message.answer("❌ Задание не найдено")
            return
        subject_dir = sanitize_path_component(task.subject or "seminar")
        relative_path = await save_file(file_bytes, original_name, f"seminar_tasks/{subject_dir}")
        if task.file_path:
            await delete_file_async(task.file_path)
        task.file_name = original_name
        task.file_path = relative_path
        await session.commit()
        await state.clear()
        await message.answer("✅ Файл задания обновлен", reply_markup=_admin_seminar_menu())
        return

    subject_dir = sanitize_path_component(data.get("subject", "seminar"))
    relative_path = await save_file(file_bytes, original_name, f"seminar_tasks/{subject_dir}")

    task = SeminarTask(
        subject=data["subject"],
        title=data["title"],
        description=data.get("description"),
        due_date=dt.date.fromisoformat(data["due_date"]) if data.get("due_date") else None,
        file_name=original_name,
        file_path=relative_path,
    )
    session.add(task)
    await session.commit()

    await state.clear()
    await message.answer("✅ Задание добавлено", reply_markup=_admin_seminar_menu())


@router_admin_seminars.callback_query(StateFilter(SeminarTaskState.waiting_for_file), F.data == "admin_seminar_skip_file")
async def seminar_skip_file(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    if data.get("edit_mode") == "replace_file":
        await state.clear()
        await callback.message.edit_text("❌ Замена файла отменена", reply_markup=_admin_seminar_menu())
        await callback.answer()
        return

    task = SeminarTask(
        subject=data["subject"],
        title=data["title"],
        description=data.get("description"),
        due_date=dt.date.fromisoformat(data["due_date"]) if data.get("due_date") else None,
    )
    session.add(task)
    await session.commit()

    await state.clear()
    await callback.message.edit_text("✅ Задание добавлено", reply_markup=_admin_seminar_menu())
    await callback.answer()


@router_admin_seminars.callback_query(F.data == "admin_seminar_list")
async def seminar_list_subjects(callback: types.CallbackQuery, session: AsyncSession):
    await _show_subjects(callback, session, mode="list")


@router_admin_seminars.callback_query(F.data == "admin_seminar_edit")
async def seminar_edit_subjects(callback: types.CallbackQuery, session: AsyncSession):
    await _show_subjects(callback, session, mode="edit")


@router_admin_seminars.callback_query(F.data == "admin_seminar_delete")
async def seminar_delete_subjects(callback: types.CallbackQuery, session: AsyncSession):
    await _show_subjects(callback, session, mode="delete")


@router_admin_seminars.callback_query(F.data.startswith("admin_seminar_subject_"))
async def seminar_subject_actions(callback: types.CallbackQuery, session: AsyncSession):
    payload = callback.data.replace("admin_seminar_subject_", "")
    mode, rep_id_raw = payload.split("_", 1)
    rep_id = int(rep_id_raw)

    rep = await session.get(SeminarTask, rep_id)
    if not rep:
        await callback.answer("Предмет не найден", show_alert=True)
        return

    result = await session.execute(
        select(SeminarTask)
        .where(SeminarTask.subject == rep.subject)
        .order_by(desc(SeminarTask.created_at))
    )
    tasks = result.scalars().all()

    keyboard = []
    for task in tasks:
        prefix = "admin_seminar_show"
        if mode == "edit":
            prefix = "admin_seminar_pick_edit"
        elif mode == "delete":
            prefix = "admin_seminar_pick_delete"
        keyboard.append([InlineKeyboardButton(text=f"📝 {task.title}", callback_data=f"{prefix}_{task.id}")])

    keyboard.append([InlineKeyboardButton(text="🔙 К предметам", callback_data=f"admin_seminar_{mode}")])
    await callback.message.edit_text(
        f"📘 <b>{rep.subject}</b>\n\nВыберите задание:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML",
    )
    await callback.answer()


@router_admin_seminars.callback_query(F.data.startswith("admin_seminar_show_"))
async def seminar_show_task(callback: types.CallbackQuery, session: AsyncSession):
    task_id = int(callback.data.replace("admin_seminar_show_", ""))
    task = await session.get(SeminarTask, task_id)
    if not task:
        await callback.answer("Задание не найдено", show_alert=True)
        return

    text = (
        f"📘 <b>{task.subject}</b>\n"
        f"📝 <b>{task.title}</b>\n\n"
        f"📅 <b>Дедлайн:</b> {task.due_date.strftime('%d.%m.%Y') if task.due_date else 'не указан'}\n\n"
        f"{task.description or 'Описание отсутствует'}"
    )
    keyboard = [[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_seminar_list")]]
    if task.file_path:
        keyboard.insert(0, [InlineKeyboardButton(text="📎 Скачать файл", callback_data=f"admin_seminar_download_{task.id}")])

    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard), parse_mode="HTML")
    await callback.answer()


@router_admin_seminars.callback_query(F.data.startswith("admin_seminar_download_"))
async def seminar_download(callback: types.CallbackQuery, session: AsyncSession):
    task_id = int(callback.data.replace("admin_seminar_download_", ""))
    task = await session.get(SeminarTask, task_id)
    if not task or not task.file_path:
        await callback.answer("Файл не найден", show_alert=True)
        return

    file_path = get_file_full_path(task.file_path)
    if not file_path.exists():
        await callback.answer("Файл отсутствует на диске", show_alert=True)
        return

    await callback.message.answer_document(types.FSInputFile(str(file_path)), caption=f"📎 {task.file_name or task.title}")
    await callback.answer("Файл отправлен")


@router_admin_seminars.callback_query(F.data.startswith("admin_seminar_pick_delete_"))
async def seminar_delete_task(callback: types.CallbackQuery, session: AsyncSession):
    task_id = int(callback.data.replace("admin_seminar_pick_delete_", ""))
    task = await session.get(SeminarTask, task_id)
    if not task:
        await callback.answer("Задание не найдено", show_alert=True)
        return

    await session.delete(task)
    await session.commit()

    await callback.message.edit_text("✅ Задание удалено", reply_markup=_admin_seminar_menu())
    await callback.answer()


@router_admin_seminars.callback_query(F.data.startswith("admin_seminar_pick_edit_"))
async def seminar_edit_task_menu(callback: types.CallbackQuery):
    task_id = int(callback.data.replace("admin_seminar_pick_edit_", ""))
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Изменить предмет", callback_data=f"admin_seminar_edit_subject_{task_id}")],
            [InlineKeyboardButton(text="✏️ Изменить заголовок", callback_data=f"admin_seminar_edit_title_{task_id}")],
            [InlineKeyboardButton(text="✏️ Изменить описание", callback_data=f"admin_seminar_edit_description_{task_id}")],
            [InlineKeyboardButton(text="📎 Заменить файл", callback_data=f"admin_seminar_replace_file_{task_id}")],
            [InlineKeyboardButton(text="🗑 Удалить файл", callback_data=f"admin_seminar_remove_file_{task_id}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_seminar_edit")],
        ]
    )
    await callback.message.edit_text("Что редактируем?", reply_markup=keyboard)
    await callback.answer()


@router_admin_seminars.callback_query(F.data.startswith("admin_seminar_remove_file_"))
async def seminar_remove_file(callback: types.CallbackQuery, session: AsyncSession):
    task_id = int(callback.data.replace("admin_seminar_remove_file_", ""))
    task = await session.get(SeminarTask, task_id)
    if not task:
        await callback.answer("Задание не найдено", show_alert=True)
        return

    if task.file_path:
        await delete_file_async(task.file_path)
    task.file_path = None
    task.file_name = None
    await session.commit()

    await callback.message.edit_text("✅ Файл удален", reply_markup=_admin_seminar_menu())
    await callback.answer()


@router_admin_seminars.callback_query(F.data.startswith("admin_seminar_replace_file_"))
async def seminar_replace_file_start(callback: types.CallbackQuery, state: FSMContext):
    task_id = int(callback.data.replace("admin_seminar_replace_file_", ""))
    await state.set_state(SeminarTaskState.waiting_for_file)
    await state.update_data(edit_mode="replace_file", edit_task_id=task_id)
    await callback.message.edit_text("Отправьте новый файл для задания (документ или изображение):")
    await callback.answer()


@router_admin_seminars.callback_query(
    F.data.startswith("admin_seminar_edit_subject_") | F.data.startswith("admin_seminar_edit_title_") | F.data.startswith("admin_seminar_edit_description_")
)
async def seminar_edit_field_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.data.startswith("admin_seminar_edit_subject_"):
        field = "subject"
        task_id = int(callback.data.replace("admin_seminar_edit_subject_", ""))
        prompt = "Введите новый предмет:"
    elif callback.data.startswith("admin_seminar_edit_title_"):
        field = "title"
        task_id = int(callback.data.replace("admin_seminar_edit_title_", ""))
        prompt = "Введите новый заголовок:"
    else:
        field = "description"
        task_id = int(callback.data.replace("admin_seminar_edit_description_", ""))
        prompt = "Введите новое описание (или 'пропустить' чтобы очистить):"

    await state.set_state(SeminarTaskState.waiting_for_edit_value)
    await state.update_data(edit_task_id=task_id, edit_field=field)
    await callback.message.edit_text(prompt)
    await callback.answer()


@router_admin_seminars.message(StateFilter(SeminarTaskState.waiting_for_edit_value), F.text)
async def seminar_edit_field_finish(message: types.Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    task = await session.get(SeminarTask, int(data["edit_task_id"]))
    if not task:
        await state.clear()
        await message.answer("❌ Задание не найдено")
        return

    field = data["edit_field"]
    value = message.text.strip()
    if field == "description" and value.lower() == "пропустить":
        value = None

    setattr(task, field, value)
    await session.commit()

    await state.clear()
    await message.answer("✅ Изменения сохранены", reply_markup=Keyboards.get_admin_main_keyboard())


@router_admin_seminars.message(
    StateFilter(
        SeminarTaskState.waiting_for_subject,
        SeminarTaskState.waiting_for_title,
        SeminarTaskState.waiting_for_description,
        SeminarTaskState.waiting_for_due_date,
        SeminarTaskState.waiting_for_file,
        SeminarTaskState.waiting_for_edit_value,
    ),
    F.text.lower() == "отмена",
)
@router_admin_seminars.callback_query(
    StateFilter(
        SeminarTaskState.waiting_for_subject,
        SeminarTaskState.waiting_for_title,
        SeminarTaskState.waiting_for_description,
        SeminarTaskState.waiting_for_due_date,
        SeminarTaskState.waiting_for_file,
        SeminarTaskState.waiting_for_edit_value,
    ),
    F.data == "cancel_upload",
)
async def seminar_cancel(event: types.Message | types.CallbackQuery, state: FSMContext):
    await state.clear()
    if isinstance(event, types.CallbackQuery):
        await event.message.edit_text("❌ Действие отменено", reply_markup=_admin_seminar_menu())
        await event.answer()
    else:
        await event.answer("❌ Действие отменено", reply_markup=Keyboards.get_admin_main_keyboard())
