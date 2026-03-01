from aiogram import Router, F, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc

from bot.db.models import SeminarTask
from bot.utils.keyboards import Keyboards
from bot.utils.file_storage import get_file_full_path


router_student_seminars = Router()


async def _show_subjects(target: types.Message | types.CallbackQuery, session: AsyncSession):
    rows = await session.execute(
        select(func.min(SeminarTask.id), SeminarTask.subject)
        .group_by(SeminarTask.subject)
        .order_by(SeminarTask.subject)
    )
    subjects = [(rep_id, subject) for rep_id, subject in rows.all() if subject]

    if not subjects:
        text = "📭 Пока нет заданий к семинарам"
        if isinstance(target, types.CallbackQuery):
            await target.answer(text, show_alert=True)
        else:
            await target.answer(text, reply_markup=Keyboards.get_student_menu())
        return

    keyboard = [
        [InlineKeyboardButton(text=f"📘 {subject}", callback_data=f"seminar_subject_{rep_id}")]
        for rep_id, subject in subjects
    ]

    text = "📝 <b>Задания к семинарам</b>\n\nВыберите предмет:"
    if isinstance(target, types.CallbackQuery):
        await target.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard), parse_mode="HTML")
        await target.answer()
    else:
        await target.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard), parse_mode="HTML")


@router_student_seminars.message(F.text == "📝 Задания к семинарам")
async def open_seminars_from_menu(message: types.Message, session: AsyncSession):
    await _show_subjects(message, session)


@router_student_seminars.callback_query(F.data == "view_seminar_tasks")
async def view_seminars_inline(callback: types.CallbackQuery, session: AsyncSession):
    await _show_subjects(callback, session)


@router_student_seminars.callback_query(F.data.startswith("seminar_subject_"))
async def show_tasks_in_subject(callback: types.CallbackQuery, session: AsyncSession):
    rep_id = int(callback.data.replace("seminar_subject_", ""))
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

    if not tasks:
        await callback.answer("В этом предмете пока нет заданий", show_alert=True)
        return

    keyboard = [
        [InlineKeyboardButton(text=f"📝 {task.title}", callback_data=f"seminar_task_{task.id}")]
        for task in tasks
    ]
    keyboard.append([InlineKeyboardButton(text="🔙 К предметам", callback_data="view_seminar_tasks")])

    await callback.message.edit_text(
        f"📘 <b>{rep.subject}</b>\n\nВыберите задание:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML",
    )
    await callback.answer()


@router_student_seminars.callback_query(F.data.startswith("seminar_task_"))
async def show_seminar_task(callback: types.CallbackQuery, session: AsyncSession):
    task_id = int(callback.data.replace("seminar_task_", ""))
    task = await session.get(SeminarTask, task_id)
    if not task:
        await callback.answer("Задание не найдено", show_alert=True)
        return

    text = (
        f"📘 <b>{task.subject}</b>\n"
        f"📝 <b>{task.title}</b>\n\n"
        f"{task.description or 'Описание отсутствует'}"
    )

    keyboard = []
    if task.file_path:
        keyboard.append([InlineKeyboardButton(text="📎 Скачать файл", callback_data=f"seminar_task_download_{task.id}")])
    keyboard.append([InlineKeyboardButton(text="🔙 Назад к предмету", callback_data=f"seminar_subject_{task.id}")])
    keyboard.append([InlineKeyboardButton(text="📚 Все предметы", callback_data="view_seminar_tasks")])

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML",
    )
    await callback.answer()


@router_student_seminars.callback_query(F.data.startswith("seminar_task_download_"))
async def download_seminar_task_file(callback: types.CallbackQuery, session: AsyncSession):
    task_id = int(callback.data.replace("seminar_task_download_", ""))
    task = await session.get(SeminarTask, task_id)
    if not task or not task.file_path:
        await callback.answer("Файл не найден", show_alert=True)
        return

    file_path = get_file_full_path(task.file_path)
    if not file_path.exists():
        await callback.answer("Файл отсутствует на диске", show_alert=True)
        return

    await callback.message.answer_document(
        types.FSInputFile(str(file_path)),
        caption=f"📎 {task.file_name or task.title}",
    )
    await callback.answer("Файл отправлен")
