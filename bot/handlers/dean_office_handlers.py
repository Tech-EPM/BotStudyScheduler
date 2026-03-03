from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import User, DeanOfficeFolder, DeanOfficeEntry
from bot.utils.keyboards import Keyboards
from bot.utils.state import DeanOfficeState
from bot.utils.file_storage import (
    save_file,
    allowed_file,
    get_file_full_path,
    sanitize_path_component,
)


router_dean_office = Router()


async def _get_user(session: AsyncSession, telegram_user_id: int) -> User | None:
    result = await session.execute(select(User).where(User.user_id == telegram_user_id))
    return result.scalar_one_or_none()


def _menu_by_status(status: str):
    if status == "admin":
        return Keyboards.get_admin_menu()
    if status == "teacher":
        return Keyboards.get_teacher_menu()
    return Keyboards.get_student_menu()


def _entry_button_title(entry: DeanOfficeEntry) -> str:
    title = entry.title or "Без названия"
    return title if len(title) <= 40 else f"{title[:37]}..."


async def _render_folders_text(session: AsyncSession):
    rows = await session.execute(select(DeanOfficeFolder).order_by(DeanOfficeFolder.name))
    folders = rows.scalars().all()

    keyboard = []
    for folder in folders:
        keyboard.append([InlineKeyboardButton(text=f"📁 {folder.name}", callback_data=f"dean_folder_{folder.id}")])

    text = "🏛 <b>Деканат</b>\n\nВыберите папку:"
    if not folders:
        text = "🏛 <b>Деканат</b>\n\nПока нет папок."

    reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard) if keyboard else None
    return text, reply_markup


@router_dean_office.message(F.text == "🏛 Деканат")
async def open_dean_office(message: types.Message, session: AsyncSession):
    user = await _get_user(session, message.from_user.id)
    if not user:
        await message.answer("❌ Сначала выполните /start")
        return

    text, keyboard = await _render_folders_text(session)
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router_dean_office.callback_query(F.data == "admin_edit_dean_office")
async def open_dean_office_admin_editor(callback: types.CallbackQuery, session: AsyncSession):
    user = await _get_user(session, callback.from_user.id)
    if not user or user.status != "admin":
        await callback.answer("Нет доступа", show_alert=True)
        return

    await callback.message.edit_text(
        "🏛 <b>Редактирование деканата</b>\n\nВыберите действие:",
        reply_markup=Keyboards.get_admin_dean_office_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router_dean_office.callback_query(F.data == "dean_add_folder")
async def dean_add_folder_start(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    user = await _get_user(session, callback.from_user.id)
    if not user or user.status != "admin":
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.set_state(DeanOfficeState.waiting_for_folder_name)
    await callback.message.edit_text(
        "Введите название папки на русском:\n\n"
        "Пример: <code>Справки и заявления</code>",
        parse_mode="HTML",
    )
    await callback.answer()


@router_dean_office.message(StateFilter(DeanOfficeState.waiting_for_folder_name), F.text)
async def dean_add_folder_finish(message: types.Message, state: FSMContext, session: AsyncSession):
    folder_name = (message.text or "").strip()
    if len(folder_name) < 2:
        await message.answer("❌ Название папки слишком короткое.")
        return

    exists_res = await session.execute(
        select(DeanOfficeFolder).where(func.lower(DeanOfficeFolder.name) == folder_name.lower())
    )
    if exists_res.scalar_one_or_none():
        await message.answer("❌ Такая папка уже существует.")
        return

    folder = DeanOfficeFolder(name=folder_name)
    session.add(folder)
    await session.commit()

    await state.clear()
    await message.answer("✅ Папка создана.", reply_markup=Keyboards.get_admin_dean_office_keyboard())


@router_dean_office.callback_query(F.data == "dean_add_entry")
async def dean_add_entry_pick_folder(callback: types.CallbackQuery, session: AsyncSession):
    user = await _get_user(session, callback.from_user.id)
    if not user or user.status != "admin":
        await callback.answer("Нет доступа", show_alert=True)
        return

    rows = await session.execute(select(DeanOfficeFolder).order_by(DeanOfficeFolder.name))
    folders = rows.scalars().all()
    if not folders:
        await callback.answer("Сначала создайте папку", show_alert=True)
        return

    keyboard = [
        [InlineKeyboardButton(text=f"📁 {folder.name}", callback_data=f"dean_pick_folder_{folder.id}")]
        for folder in folders
    ]
    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_edit_dean_office")])

    await callback.message.edit_text(
        "Выберите папку для новой записи:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
    )
    await callback.answer()


@router_dean_office.callback_query(F.data == "dean_rename_folder_menu")
async def dean_rename_folder_menu(callback: types.CallbackQuery, session: AsyncSession):
    user = await _get_user(session, callback.from_user.id)
    if not user or user.status != "admin":
        await callback.answer("Нет доступа", show_alert=True)
        return

    rows = await session.execute(select(DeanOfficeFolder).order_by(DeanOfficeFolder.name))
    folders = rows.scalars().all()
    if not folders:
        await callback.answer("Нет папок для изменения", show_alert=True)
        return

    keyboard = [
        [InlineKeyboardButton(text=f"📁 {folder.name}", callback_data=f"dean_rename_folder_{folder.id}")]
        for folder in folders
    ]
    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_edit_dean_office")])
    await callback.message.edit_text(
        "Выберите папку для переименования:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
    )
    await callback.answer()


@router_dean_office.callback_query(F.data.startswith("dean_rename_folder_"))
async def dean_rename_folder_start(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    user = await _get_user(session, callback.from_user.id)
    if not user or user.status != "admin":
        await callback.answer("Нет доступа", show_alert=True)
        return

    folder_id = int(callback.data.replace("dean_rename_folder_", ""))
    folder = await session.get(DeanOfficeFolder, folder_id)
    if not folder:
        await callback.answer("Папка не найдена", show_alert=True)
        return

    await state.update_data(dean_rename_folder_id=folder.id)
    await state.set_state(DeanOfficeState.waiting_for_folder_new_name)
    await callback.message.edit_text(
        f"Текущее название: <b>{folder.name}</b>\n\nВведите новое название папки:",
        parse_mode="HTML",
    )
    await callback.answer()


@router_dean_office.message(StateFilter(DeanOfficeState.waiting_for_folder_new_name), F.text)
async def dean_rename_folder_finish(message: types.Message, state: FSMContext, session: AsyncSession):
    new_name = (message.text or "").strip()
    if len(new_name) < 2:
        await message.answer("❌ Название слишком короткое.")
        return

    data = await state.get_data()
    folder_id = data.get("dean_rename_folder_id")
    folder = await session.get(DeanOfficeFolder, folder_id)
    if not folder:
        await state.clear()
        await message.answer("❌ Папка не найдена.")
        return

    exists_res = await session.execute(
        select(DeanOfficeFolder).where(
            func.lower(DeanOfficeFolder.name) == new_name.lower(),
            DeanOfficeFolder.id != folder.id,
        )
    )
    if exists_res.scalar_one_or_none():
        await message.answer("❌ Папка с таким названием уже существует.")
        return

    folder.name = new_name
    await session.commit()
    await state.clear()
    await message.answer("✅ Папка переименована.", reply_markup=Keyboards.get_admin_dean_office_keyboard())


@router_dean_office.callback_query(F.data == "dean_delete_folder_menu")
async def dean_delete_folder_menu(callback: types.CallbackQuery, session: AsyncSession):
    user = await _get_user(session, callback.from_user.id)
    if not user or user.status != "admin":
        await callback.answer("Нет доступа", show_alert=True)
        return

    rows = await session.execute(select(DeanOfficeFolder).order_by(DeanOfficeFolder.name))
    folders = rows.scalars().all()
    if not folders:
        await callback.answer("Нет папок для удаления", show_alert=True)
        return

    keyboard = [
        [InlineKeyboardButton(text=f"🗑 {folder.name}", callback_data=f"dean_confirm_delete_folder_{folder.id}")]
        for folder in folders
    ]
    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_edit_dean_office")])
    await callback.message.edit_text(
        "Выберите папку для удаления:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
    )
    await callback.answer()


@router_dean_office.callback_query(F.data.startswith("dean_confirm_delete_folder_"))
async def dean_delete_folder_confirm(callback: types.CallbackQuery, session: AsyncSession):
    user = await _get_user(session, callback.from_user.id)
    if not user or user.status != "admin":
        await callback.answer("Нет доступа", show_alert=True)
        return

    folder_id = int(callback.data.replace("dean_confirm_delete_folder_", ""))
    folder = await session.get(DeanOfficeFolder, folder_id)
    if not folder:
        await callback.answer("Папка не найдена", show_alert=True)
        return

    await session.delete(folder)
    await session.commit()
    await callback.answer("Папка удалена")
    await open_dean_office_admin_editor(callback, session)


@router_dean_office.callback_query(F.data == "dean_edit_entry_pick_folder")
async def dean_edit_entry_pick_folder(callback: types.CallbackQuery, session: AsyncSession):
    user = await _get_user(session, callback.from_user.id)
    if not user or user.status != "admin":
        await callback.answer("Нет доступа", show_alert=True)
        return

    rows = await session.execute(select(DeanOfficeFolder).order_by(DeanOfficeFolder.name))
    folders = rows.scalars().all()
    if not folders:
        await callback.answer("Нет папок", show_alert=True)
        return

    keyboard = [
        [InlineKeyboardButton(text=f"📁 {folder.name}", callback_data=f"dean_edit_entry_folder_{folder.id}")]
        for folder in folders
    ]
    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_edit_dean_office")])
    await callback.message.edit_text(
        "Выберите папку с записью для редактирования:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
    )
    await callback.answer()


@router_dean_office.callback_query(F.data.startswith("dean_edit_entry_folder_"))
async def dean_edit_entry_list(callback: types.CallbackQuery, session: AsyncSession):
    user = await _get_user(session, callback.from_user.id)
    if not user or user.status != "admin":
        await callback.answer("Нет доступа", show_alert=True)
        return

    folder_id = int(callback.data.replace("dean_edit_entry_folder_", ""))
    folder = await session.get(DeanOfficeFolder, folder_id)
    if not folder:
        await callback.answer("Папка не найдена", show_alert=True)
        return

    rows = await session.execute(
        select(DeanOfficeEntry)
        .where(DeanOfficeEntry.folder_id == folder_id)
        .order_by(DeanOfficeEntry.created_at.desc())
    )
    entries = rows.scalars().all()
    if not entries:
        await callback.answer("В папке нет записей", show_alert=True)
        return

    keyboard = [
        [
            InlineKeyboardButton(
                text=f"✏️ {_entry_button_title(entry)}",
                callback_data=f"dean_edit_entry_item_{entry.id}",
            )
        ]
        for entry in entries
    ]
    keyboard.append([InlineKeyboardButton(text="🔙 К папкам", callback_data="dean_edit_entry_pick_folder")])
    await callback.message.edit_text(
        f"📁 <b>{folder.name}</b>\n\nВыберите запись для редактирования:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML",
    )
    await callback.answer()


@router_dean_office.callback_query(F.data.startswith("dean_edit_entry_item_"))
async def dean_edit_entry_start(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    user = await _get_user(session, callback.from_user.id)
    if not user or user.status != "admin":
        await callback.answer("Нет доступа", show_alert=True)
        return

    entry_id = int(callback.data.replace("dean_edit_entry_item_", ""))
    entry = await session.get(DeanOfficeEntry, entry_id)
    if not entry:
        await callback.answer("Запись не найдена", show_alert=True)
        return

    await state.update_data(dean_edit_entry_id=entry.id)
    await state.set_state(DeanOfficeState.waiting_for_entry_new_text)
    await callback.message.edit_text(
        f"Название: <b>{entry.title or 'Без названия'}</b>\n\n"
        "Введите новый текст записи:\n\n"
        f"Текущий текст:\n{entry.text[:500]}",
        parse_mode="HTML",
    )
    await callback.answer()


@router_dean_office.message(StateFilter(DeanOfficeState.waiting_for_entry_new_text), F.text)
async def dean_edit_entry_finish(message: types.Message, state: FSMContext, session: AsyncSession):
    new_text = (message.text or "").strip()
    if len(new_text) < 2:
        await message.answer("❌ Текст слишком короткий.")
        return

    data = await state.get_data()
    entry_id = data.get("dean_edit_entry_id")
    entry = await session.get(DeanOfficeEntry, entry_id)
    if not entry:
        await state.clear()
        await message.answer("❌ Запись не найдена.")
        return

    entry.text = new_text
    await session.commit()
    await state.clear()
    await message.answer("✅ Запись обновлена.", reply_markup=Keyboards.get_admin_dean_office_keyboard())


@router_dean_office.callback_query(F.data == "dean_delete_entry_pick_folder")
async def dean_delete_entry_pick_folder(callback: types.CallbackQuery, session: AsyncSession):
    user = await _get_user(session, callback.from_user.id)
    if not user or user.status != "admin":
        await callback.answer("Нет доступа", show_alert=True)
        return

    rows = await session.execute(select(DeanOfficeFolder).order_by(DeanOfficeFolder.name))
    folders = rows.scalars().all()
    if not folders:
        await callback.answer("Нет папок", show_alert=True)
        return

    keyboard = [
        [InlineKeyboardButton(text=f"📁 {folder.name}", callback_data=f"dean_delete_entry_folder_{folder.id}")]
        for folder in folders
    ]
    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_edit_dean_office")])
    await callback.message.edit_text(
        "Выберите папку с записью для удаления:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
    )
    await callback.answer()


@router_dean_office.callback_query(F.data.startswith("dean_delete_entry_folder_"))
async def dean_delete_entry_list(callback: types.CallbackQuery, session: AsyncSession):
    user = await _get_user(session, callback.from_user.id)
    if not user or user.status != "admin":
        await callback.answer("Нет доступа", show_alert=True)
        return

    folder_id = int(callback.data.replace("dean_delete_entry_folder_", ""))
    folder = await session.get(DeanOfficeFolder, folder_id)
    if not folder:
        await callback.answer("Папка не найдена", show_alert=True)
        return

    rows = await session.execute(
        select(DeanOfficeEntry)
        .where(DeanOfficeEntry.folder_id == folder_id)
        .order_by(DeanOfficeEntry.created_at.desc())
    )
    entries = rows.scalars().all()
    if not entries:
        await callback.answer("В папке нет записей", show_alert=True)
        return

    keyboard = [
        [
            InlineKeyboardButton(
                text=f"🗑 {_entry_button_title(entry)}",
                callback_data=f"dean_confirm_delete_entry_{entry.id}",
            )
        ]
        for entry in entries
    ]
    keyboard.append([InlineKeyboardButton(text="🔙 К папкам", callback_data="dean_delete_entry_pick_folder")])
    await callback.message.edit_text(
        f"📁 <b>{folder.name}</b>\n\nВыберите запись для удаления:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML",
    )
    await callback.answer()


@router_dean_office.callback_query(F.data.startswith("dean_confirm_delete_entry_"))
async def dean_delete_entry_confirm(callback: types.CallbackQuery, session: AsyncSession):
    user = await _get_user(session, callback.from_user.id)
    if not user or user.status != "admin":
        await callback.answer("Нет доступа", show_alert=True)
        return

    entry_id = int(callback.data.replace("dean_confirm_delete_entry_", ""))
    entry = await session.get(DeanOfficeEntry, entry_id)
    if not entry:
        await callback.answer("Запись не найдена", show_alert=True)
        return

    folder_id = entry.folder_id
    await session.delete(entry)
    await session.commit()
    await callback.answer("Запись удалена")

    folder = await session.get(DeanOfficeFolder, folder_id)
    folder_name = folder.name if folder else "Папка"
    await callback.message.edit_text(
        f"✅ Запись удалена из папки <b>{folder_name}</b>.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 В редактирование", callback_data="admin_edit_dean_office")]]
        ),
    )


@router_dean_office.callback_query(F.data.startswith("dean_pick_folder_"))
async def dean_add_entry_start(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    user = await _get_user(session, callback.from_user.id)
    if not user or user.status != "admin":
        await callback.answer("Нет доступа", show_alert=True)
        return

    folder_id = int(callback.data.replace("dean_pick_folder_", ""))
    folder = await session.get(DeanOfficeFolder, folder_id)
    if not folder:
        await callback.answer("Папка не найдена", show_alert=True)
        return

    await state.update_data(dean_folder_id=folder.id)
    await state.set_state(DeanOfficeState.waiting_for_entry_title)

    await callback.message.edit_text(
        f"📁 <b>{folder.name}</b>\n\nВведите название заметки:",
        parse_mode="HTML",
    )
    await callback.answer()


@router_dean_office.message(StateFilter(DeanOfficeState.waiting_for_entry_title), F.text)
async def dean_add_entry_title(message: types.Message, state: FSMContext):
    title = (message.text or "").strip()
    if len(title) < 2:
        await message.answer("❌ Название заметки слишком короткое.")
        return
    await state.update_data(dean_entry_title=title)
    await state.set_state(DeanOfficeState.waiting_for_entry_text)
    await message.answer("Введите текст заметки:")


@router_dean_office.message(StateFilter(DeanOfficeState.waiting_for_entry_text), F.text)
async def dean_add_entry_text(message: types.Message, state: FSMContext, session: AsyncSession):
    text = (message.text or "").strip()
    if len(text) < 2:
        await message.answer("❌ Текст слишком короткий.")
        return

    data = await state.get_data()
    folder_id = data.get("dean_folder_id")
    folder = await session.get(DeanOfficeFolder, folder_id)
    if not folder:
        await state.clear()
        await message.answer("❌ Папка не найдена.")
        return

    await state.update_data(dean_entry_text=text)
    await state.set_state(DeanOfficeState.waiting_for_entry_file)
    await message.answer(
        "Пришлите файл к заметке (документ или фото), либо нажмите «Пропустить».",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⏭️ Пропустить", callback_data="dean_skip_entry_file")]]
        ),
    )


async def _create_dean_entry_from_state(
    state: FSMContext,
    session: AsyncSession,
    telegram_user_id: int,
    file_name: str | None = None,
    file_path: str | None = None,
):
    data = await state.get_data()
    folder_id = data.get("dean_folder_id")
    folder = await session.get(DeanOfficeFolder, folder_id)
    if not folder:
        await state.clear()
        return False

    user = await _get_user(session, telegram_user_id)
    entry = DeanOfficeEntry(
        folder_id=folder.id,
        title=data.get("dean_entry_title", "Без названия"),
        text=data.get("dean_entry_text", ""),
        file_name=file_name,
        file_path=file_path,
        created_by=user.id if user else None,
    )
    session.add(entry)
    await session.commit()
    await state.clear()
    return True


@router_dean_office.callback_query(StateFilter(DeanOfficeState.waiting_for_entry_file), F.data == "dean_skip_entry_file")
async def dean_skip_entry_file(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    ok = await _create_dean_entry_from_state(state, session, callback.from_user.id)
    if not ok:
        await callback.message.edit_text("❌ Папка не найдена.")
    else:
        await callback.message.edit_text(
            "✅ Заметка добавлена в деканат.",
            reply_markup=Keyboards.get_admin_dean_office_keyboard(),
        )
    await callback.answer()


@router_dean_office.message(StateFilter(DeanOfficeState.waiting_for_entry_file), F.photo | F.document)
async def dean_add_entry_file(message: types.Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    folder_id = data.get("dean_folder_id")
    folder = await session.get(DeanOfficeFolder, folder_id)
    if not folder:
        await state.clear()
        await message.answer("❌ Папка не найдена.")
        return

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

    folder_dir = sanitize_path_component(folder.name)
    relative_path = await save_file(file_bytes, original_name, f"dean_office/{folder_dir}")

    ok = await _create_dean_entry_from_state(
        state,
        session,
        message.from_user.id,
        file_name=original_name,
        file_path=relative_path,
    )
    if not ok:
        await message.answer("❌ Папка не найдена.")
        return
    await message.answer("✅ Заметка с файлом добавлена.", reply_markup=Keyboards.get_admin_dean_office_keyboard())


@router_dean_office.message(StateFilter(DeanOfficeState.waiting_for_entry_file), F.text)
async def dean_add_entry_file_text(message: types.Message, state: FSMContext, session: AsyncSession):
    if (message.text or "").strip().lower() in {"пропустить", "skip"}:
        ok = await _create_dean_entry_from_state(state, session, message.from_user.id)
        if not ok:
            await message.answer("❌ Папка не найдена.")
            return
        await message.answer("✅ Заметка добавлена в деканат.", reply_markup=Keyboards.get_admin_dean_office_keyboard())
        return

    await message.answer("Отправьте файл или нажмите «Пропустить».")


@router_dean_office.callback_query(F.data.startswith("dean_folder_"))
async def dean_show_folder(callback: types.CallbackQuery, session: AsyncSession):
    folder_id = int(callback.data.replace("dean_folder_", ""))
    folder = await session.get(DeanOfficeFolder, folder_id)
    if not folder:
        await callback.answer("Папка не найдена", show_alert=True)
        return

    rows = await session.execute(
        select(DeanOfficeEntry)
        .where(DeanOfficeEntry.folder_id == folder_id)
        .order_by(DeanOfficeEntry.created_at.desc())
    )
    entries = rows.scalars().all()

    keyboard = [
        [
            InlineKeyboardButton(
                text=f"📝 {_entry_button_title(entry)}",
                callback_data=f"dean_entry_{entry.id}",
            )
        ]
        for entry in entries
    ]
    keyboard.append([InlineKeyboardButton(text="🔙 К папкам", callback_data="dean_back")])

    await callback.message.edit_text(
        f"📁 <b>{folder.name}</b>\n\nВыберите запись:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML",
    )
    await callback.answer()


@router_dean_office.callback_query(F.data.startswith("dean_entry_download_"))
async def dean_entry_download(callback: types.CallbackQuery, session: AsyncSession):
    entry_id = int(callback.data.replace("dean_entry_download_", ""))
    entry = await session.get(DeanOfficeEntry, entry_id)
    if not entry or not entry.file_path:
        await callback.answer("Файл не найден", show_alert=True)
        return

    file_path = get_file_full_path(entry.file_path)
    if not file_path.exists():
        await callback.answer("Файл отсутствует на диске", show_alert=True)
        return

    await callback.message.answer_document(
        types.FSInputFile(str(file_path)),
        caption=f"📎 {entry.file_name or (entry.title or 'Файл заметки')}",
    )
    await callback.answer("Файл отправлен")


@router_dean_office.callback_query(F.data.regexp(r"^dean_entry_\d+$"))
async def dean_show_entry(callback: types.CallbackQuery, session: AsyncSession):
    entry_id = int(callback.data.replace("dean_entry_", ""))
    entry = await session.get(DeanOfficeEntry, entry_id)
    if not entry:
        await callback.answer("Запись не найдена", show_alert=True)
        return

    folder = await session.get(DeanOfficeFolder, entry.folder_id)
    folder_name = folder.name if folder else "Папка"

    keyboard = []
    if entry.file_path:
        keyboard.append([InlineKeyboardButton(text="📎 Скачать файл", callback_data=f"dean_entry_download_{entry.id}")])
    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"dean_folder_{entry.folder_id}")])

    await callback.message.edit_text(
        f"📁 <b>{folder_name}</b>\n"
        f"📝 <b>{entry.title or 'Без названия'}</b>\n"
        f"🕒 {entry.created_at.strftime('%d.%m.%Y %H:%M') if entry.created_at else '-'}\n\n"
        f"{entry.text}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML",
    )
    await callback.answer()


@router_dean_office.callback_query(F.data == "dean_back")
async def dean_back(callback: types.CallbackQuery, session: AsyncSession):
    user = await _get_user(session, callback.from_user.id)
    if not user:
        await callback.answer("Сначала выполните /start", show_alert=True)
        return

    text, keyboard = await _render_folders_text(session)
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@router_dean_office.message(
    StateFilter(
        DeanOfficeState.waiting_for_folder_name,
        DeanOfficeState.waiting_for_entry_title,
        DeanOfficeState.waiting_for_entry_text,
        DeanOfficeState.waiting_for_entry_file,
        DeanOfficeState.waiting_for_folder_new_name,
        DeanOfficeState.waiting_for_entry_new_text,
    ),
    F.text.lower() == "отмена",
)
async def dean_cancel(message: types.Message, state: FSMContext, session: AsyncSession):
    await state.clear()
    user = await _get_user(session, message.from_user.id)
    status = user.status if user else "student"
    await message.answer("❌ Действие отменено.", reply_markup=_menu_by_status(status))
