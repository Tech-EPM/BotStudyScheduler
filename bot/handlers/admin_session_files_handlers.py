import os
import re
import logging
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.exc import SQLAlchemyError

import asyncio
from functools import partial
import shutil 

# Импорт моделей
from bot.db.models import SessionFile, User
# Импорт утилит
from bot.utils.file_storage import (
    allowed_file,
    get_file_full_path,
    delete_file_async,
    save_session_file,
    sanitize_path_component,
)
from bot.utils.keyboards import Keyboards
from bot.utils.state import SessionFileUpload

logger = logging.getLogger(__name__)
router_session_files_admin = Router()


# ==========================================
# 1. НАЧАЛО ЗАГРУЗКИ: СРАЗУ ВЫБОР КАТЕГОРИИ
# ==========================================

@router_session_files_admin.callback_query(F.data == "admin_add_session_files")
async def start_session_file_upload(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    """Админ нажал 'Добавить файлы для сессии' → сразу спрашиваем категорию"""
    await state.clear()
    # Проверка прав
    stmt = select(User).where(User.user_id == callback.from_user.id)
    result = await session.execute(stmt)
    current_user = result.scalar_one_or_none()

    if not current_user or current_user.status not in ("admin", "superadmin"):
        await callback.answer("❌ У вас нет прав для этой операции", show_alert=True)
        return

    rows = await session.execute(
        select(func.min(SessionFile.id), SessionFile.session_group)
        .where(SessionFile.session_group.isnot(None))
        .group_by(SessionFile.session_group)
        .order_by(SessionFile.session_group)
    )
    keyboard = []
    for rep_id, group_name in rows.all():
        if not group_name:
            continue
        keyboard.append([InlineKeyboardButton(text=f"🗂 {group_name}", callback_data=f"sess_group_pick_{rep_id}")])
    keyboard.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_upload")])

    await callback.message.edit_text(
        "🗂 <b>Введите название сессии</b>\n"
        "(например: <code>Сессия 1</code>)\n\n"
        "Или выберите существующую:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML"
    )
    await callback.answer()
    await state.set_state(SessionFileUpload.waiting_for_session_group)


@router_session_files_admin.callback_query(SessionFileUpload.waiting_for_session_group, F.data.startswith("sess_group_pick_"))
async def session_group_selected(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    file_id = callback.data.replace("sess_group_pick_", "")
    doc = await session.get(SessionFile, file_id)
    if not doc or not doc.session_group:
        await callback.answer("❌ Раздел сессии не найден", show_alert=True)
        return
    await state.update_data(session_group=doc.session_group)
    await state.set_state(SessionFileUpload.waiting_for_subject)
    await callback.message.edit_text(
        "📘 Введите предмет (на русском):",
        parse_mode="HTML"
    )
    await callback.answer()


@router_session_files_admin.message(SessionFileUpload.waiting_for_session_group, F.text)
async def session_group_text_received(message: types.Message, state: FSMContext):
    session_group = message.text.strip()
    if len(session_group) < 2:
        await message.answer("❌ Название слишком короткое.")
        return
    await state.update_data(session_group=session_group)
    await state.set_state(SessionFileUpload.waiting_for_subject)
    await message.answer("📘 Введите предмет (на русском):")


@router_session_files_admin.message(SessionFileUpload.waiting_for_subject, F.text)
async def session_subject_text_received(message: types.Message, state: FSMContext):
    subject = message.text.strip()
    if len(subject) < 2:
        await message.answer("❌ Название предмета слишком короткое.")
        return
    await state.update_data(subject=subject)
    await state.set_state(SessionFileUpload.waiting_for_category)
    await message.answer(
        "📂 <b>Выберите подкатегорию для файла сессии:</b>\n\n"
        "• <code>tickets</code> — Билеты\n"
        "• <code>answers</code> — Ответы/Шпаргалки\n"
        "• <code>materials</code> — Методички\n"
        "• <code>other</code> — Другое\n\n"
        "Или напишите свою категорию латиницей:",
        reply_markup=Keyboards.get_session_file_categories(),
        parse_mode="HTML"
    )


# ==========================================
# 2. ВЫБОР КАТЕГОРИИ -> ОЖИДАНИЕ ФАЙЛА
# ==========================================

@router_session_files_admin.callback_query(SessionFileUpload.waiting_for_category, F.data.startswith("category_"))
async def session_category_selected(callback: types.CallbackQuery, state: FSMContext):
    """Пользователь выбрал категорию → ждём файл"""
    category = callback.data.replace("category_", "")
    
    # Сохраняем категорию в FSM
    await state.update_data(category=category)
    await state.set_state(SessionFileUpload.waiting_for_file)
    
    await callback.message.edit_text(
        f"📎 <b>Категория:</b> <code>{category}</code>\n\n"
        "📤 <b>Отправьте файл:</b>\n"
        "📄 Документы, изображения, архивы\n"
        "📏 Макс. размер: 20 МБ\n\n",
        # f"📁 Файл будет сохранён в: <code>storage/files/session_files/{category}/</code>",
        parse_mode="HTML"
    )
    await callback.answer()



@router_session_files_admin.message(SessionFileUpload.waiting_for_category, F.text)
async def sesseion_category_text_received(message: types.Message, state: FSMContext):
    """Обработчик, когда пользователь пишет название категории текстом"""
    import re
    
    category = message.text.strip().lower()
    
    # Валидация: только латиница, цифры, подчёркивание, дефис (без пробелов!)
    if not re.match(r'^[a-z0-9_-]+$', category):
        await message.answer(
            "❌ Категория должна содержать только латинские буквы, цифры, _ или -\n"
            "Пример: <code>math_exams</code>, <code>prog2024</code>",
            parse_mode="HTML"
        )
        return
    
    # Сохраняем категорию и переходим к ожиданию файла
    await state.update_data(category=category)
    await state.set_state(SessionFileUpload.waiting_for_file)
    
    await message.answer(
        f"📎 <b>Категория:</b> <code>{category}</code>\n\n"
        "📤 <b>Отправьте файл:</b>\n"
        "📄 Документы, изображения, архивы\n"
        "📏 Макс. размер: 20 МБ",
        parse_mode="HTML"
    )


# ==========================================
# 3. ПОЛУЧЕНИЕ ФАЙЛА -> ПЕРЕИМЕНОВАНИЕ
# ==========================================

@router_session_files_admin.message(SessionFileUpload.waiting_for_file, F.photo | F.document)
async def session_file_received(message: types.Message, state: FSMContext, session: AsyncSession):
    """Получаем файл, сохраняем на диск с учётом подкатегории"""
    
    # --- 1. Извлечение данных файла ---
    if message.photo:
        photo = message.photo[-1]
        file_info = await message.bot.get_file(photo.file_id)
        file_bytes = await message.bot.download_file(file_info.file_path)
        file_bytes = file_bytes.read()
        original_name = f"photo_{photo.file_id[:8]}.jpg"
        file_size = photo.file_size
        file_ext = "jpg"
    elif message.document:
        doc = message.document
        if doc.file_size > 20 * 1024 * 1024:
            await message.answer("❌ Файл слишком большой (макс. 20 МБ)")
            return
        if not allowed_file(doc.file_name):
            await message.answer("❌ Тип файла не поддерживается")
            return
            
        file_info = await message.bot.get_file(doc.file_id)
        file_bytes = await message.bot.download_file(file_info.file_path)
        file_bytes = file_bytes.read()
        original_name = doc.file_name
        file_size = doc.file_size
        file_ext = original_name.split(".")[-1].lower() if "." in original_name else ""
    else:
        return

    # --- 2. Сохранение на диск с подкатегорией ---

    data = await state.get_data()
    category = data.get("category", "other")
    session_group = data.get("session_group", "Сессия")
    subject = data.get("subject", "Без предмета")

    storage_path = (
        f"{sanitize_path_component(session_group)}/"
        f"{sanitize_path_component(subject)}/"
        f"{sanitize_path_component(category)}"
    )


    logger.info(f"🔍 About to save file with storage_path: {storage_path}")

    try:
        relative_path = await save_session_file(file_bytes, original_name, storage_path)
    except Exception as e:
        logger.error(f"File save error: {e}")
        await message.answer("❌ Ошибка при сохранении файла на сервер")
        return
   

    # --- 3. Сохраняем метаданные в FSM ---
    await state.update_data(
        original_name=original_name,
        file_size=file_size,
        file_ext=file_ext,
        relative_path=relative_path,
        category=category,
        session_group=session_group,
        subject=subject,
    )
    await state.set_state(SessionFileUpload.waiting_for_filename)

    await message.answer(
        f"✅ <b>Файл получен!</b>\n\n"
        f"🗂 Сессия: <b>{session_group}</b>\n"
        f"📘 Предмет: <b>{subject}</b>\n"
        f"📄 Имя: <code>{original_name}</code>\n"
        f"💾 Размер: {file_size / 1024:.1f} КБ\n"
        f"📁 Папка: <code>session_files/{category}/</code>\n\n"
        "✏️ <b>Введите новое имя для файла</b> (опционально):\n"
        "Напишите <code>пропустить</code>, чтобы оставить как есть.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏭️ Пропустить", callback_data="skip_filename")]
        ])
    )


# ==========================================
# 4. ФИНАЛИЗАЦИЯ: ЗАПИСЬ В БД (БЕЗ SESSION_ID)
# ==========================================

@router_session_files_admin.message(SessionFileUpload.waiting_for_filename, F.text)
async def session_filename_received(message: types.Message, state: FSMContext, session: AsyncSession):
    """Пользователь ввел имя (или пропустил) → Создаем запись SessionFile"""
    
    custom_name = message.text.strip()
    data = await state.get_data()
    
    original_name = data.get("original_name")
    file_ext = data.get("file_ext", "")
    relative_path = data.get("relative_path")
    category = data.get("category", "other")
    session_group = data.get("session_group", "Сессия")
    subject = data.get("subject", "Без предмета")
    file_size = data.get("file_size")
    
    # Логика переименования файла на диске
    final_filename = original_name
    if custom_name.lower() != "пропустить":
        safe_name = "".join(c for c in custom_name if c.isalnum() or c in "._- ").strip()
        if safe_name:
            new_filename = f"{safe_name}.{file_ext}"
            
            old_abs_path = get_file_full_path(relative_path)
            new_rel_path = relative_path.replace(original_name, new_filename)
            new_abs_path = get_file_full_path(new_rel_path)
            
            loop = asyncio.get_event_loop()
            try:
                await loop.run_in_executor(None, partial(shutil.move, str(old_abs_path), str(new_abs_path)))
                relative_path = new_rel_path
                final_filename = new_filename
            except Exception as e:
                logger.error(f"Rename error: {e}")
                await message.answer("⚠️ Файл сохранён, но переименовать не удалось")



    new_db_file = SessionFile(
        session_id=None, 
        original_filename=final_filename,
        stored_path=relative_path,
        file_size=file_size,
        category=category,
        session_group=session_group,
        subject=subject,
    )
    
    
    try:
        session.add(new_db_file)
        await session.commit()
    except SQLAlchemyError as e:
        logging.error(f"Database error: {e}")
        await session.rollback()
        await message.answer("❌ Ошибка базы данных")
        return


    await state.clear()
    
    await message.answer(
        f"✅ <b>Файл загружен!</b>\n\n"
        f"🗂 Сессия: {session_group}\n"
        f"📘 Предмет: {subject}\n"
        f"📄 {final_filename}\n"
        f"📂 Категория: {category}\n"
        f"📁 Путь: {relative_path}",
        parse_mode="HTML",
        reply_markup=Keyboards.get_admin_main_keyboard()
    )


@router_session_files_admin.callback_query(SessionFileUpload.waiting_for_filename, F.data == "skip_filename")
async def session_skip_filename(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    """Обработчик кнопки 'Пропустить'"""
    data = await state.get_data()
    
    new_db_file = SessionFile(
        session_id=None, 
        original_filename=data.get("original_name"),
        stored_path=data.get("relative_path"),
        file_size=data.get("file_size"),
        category=data.get("category", "other"),
        session_group=data.get("session_group", "Сессия"),
        subject=data.get("subject", "Без предмета"),
    )
    
    session.add(new_db_file)
    await session.commit()
    await state.clear()
    
    await callback.message.edit_text(
        f"✅ <b>Файл добавлен!</b>\n\n"
        f"🗂 {data.get('session_group')}\n"
        f"📘 {data.get('subject')}\n"
        f"📄 {data.get('original_name')}\n"
        f"📂 Категория: {data.get('category')}\n"
        f"📁 Путь: {data.get('relative_path')}",
        reply_markup=Keyboards.get_admin_main_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


# ==========================================
# 5. ОТМЕНА ЗАГРУЗКИ (CLEANUP)
# ==========================================

@router_session_files_admin.callback_query(F.data == "cancel_upload")
async def session_cancel_upload(callback: types.CallbackQuery, state: FSMContext):
    """Отмена загрузки с удалением временного файла с диска"""
    logger.info(f"🔍 Cancel upload triggered by user {callback.from_user.id}")
    
    # Получаем данные из FSM (если есть)
    data = await state.get_data()
    
    # Если файл уже сохранён на диск — удаляем его
    if data.get("relative_path"):
        try:
            await delete_file_async(data.get("relative_path"))
            logger.info(f"✅ Deleted temp file: {data.get('relative_path')}")
        except Exception as e:
            logger.error(f"❌ Error deleting temp file: {e}")
    
    # Очищаем состояние
    await state.clear()
    
    # Отвечаем на callback (обязательно!)
    await callback.answer("❌ Загрузка отменена", show_alert=False)
    
    # Пытаемся отредактировать сообщение
    try:
        await callback.message.edit_text(
            "❌ <b>Загрузка отменена</b>\n\n"
            "Вы вернулись в главное меню администратора.",
            reply_markup=Keyboards.get_admin_main_keyboard(),
            parse_mode="HTML"
        )
    except Exception as e:
        # Если сообщение нельзя отредактировать (старое или уже изменено)
        logger.warning(f"Could not edit message: {e}")
        await callback.message.answer(
            "❌ <b>Загрузка отменена</b>\n\n"
            "Вы вернулись в главное меню администратора.",
            reply_markup=Keyboards.get_admin_main_keyboard(),
            parse_mode="HTML"
        )

# ==========================================
# 6. УДАЛЕНИЕ ФАЙЛОВ СЕССИИ (ADMIN DELETE)
# ==========================================

@router_session_files_admin.callback_query(F.data == "admin_del_session_files")
async def show_session_files_for_delete(callback: types.CallbackQuery, session: AsyncSession):
    """Показывает ВСЕ файлы из таблицы session_files для удаления"""
    
    # Проверка прав
    stmt = select(User).where(User.user_id == callback.from_user.id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user or user.status not in ("admin"):
        await callback.answer("❌ Нет прав", show_alert=True)
        return


    stmt_files = select(SessionFile).order_by(SessionFile.created_at.desc()).limit(50)
    result_files = await session.execute(stmt_files)
    files = result_files.scalars().all()
    
    
    if not files:
        await callback.answer("📭 Нет файлов для удаления", show_alert=True)
        return
    
    # Формируем клавиатуру
    keyboard = []
    for f in files:
        # Показываем категорию в кнопке
        cat = f.category or "other"
        btn_text = f"🗑️ {f.original_filename} [{f.session_group or 'Сессия'} / {f.subject or 'Без предмета'} / {cat}]"
        keyboard.append([InlineKeyboardButton(text=btn_text, callback_data=f"sess_admin_del{f.id}")])
    
    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="goto_back")])
    
    await callback.message.edit_text(
        f"📂 <b>Файлы сессий</b> (последние {len(files)}):\n\n"
        "Нажмите для удаления:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML"
    )
    await callback.answer()


@router_session_files_admin.callback_query(F.data.startswith("sess_admin_del"))
async def confirm_delete_session_file(callback: types.CallbackQuery, session: AsyncSession):
    """Подтверждение удаления"""
    file_id = callback.data.replace("sess_admin_del", "")
    
    file_to_delete = await session.get(SessionFile, file_id)
    
    if not file_to_delete:
        await callback.answer("❌ Файл не найден", show_alert=True)
        return
        
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"confirm_del_sess_{file_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="admin_del_session_files")
        ]
    ])
    
    await callback.message.edit_text(
        f"⚠️ <b>Удалить файл?</b>\n\n"
        f"📄 {file_to_delete.original_filename}\n"
        f"🗂 Сессия: {file_to_delete.session_group or '-'}\n"
        f"📘 Предмет: {file_to_delete.subject or '-'}\n"
        f"📂 Категория: {file_to_delete.category or 'other'}\n"
        f"📁 Путь: {file_to_delete.stored_path}\n\n"
        "Файл будет удален из БД и с диска.",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await callback.answer()


@router_session_files_admin.callback_query(F.data.startswith("confirm_del_sess_"))
async def execute_delete_session_file(callback: types.CallbackQuery, session: AsyncSession):
    """Финальное удаление: БД + Диск → возврат к списку"""
    file_id = callback.data.replace("confirm_del_sess_", "")
    
    file_to_delete = await session.get(SessionFile, file_id)
    if not file_to_delete:
        await callback.answer("❌ Уже удалено", show_alert=True)
        await show_session_files_for_delete(callback, session)
        return
    

    await delete_file_async(file_to_delete.stored_path)
    

    await session.delete(file_to_delete)
    await session.commit()
    

    await callback.answer(f"✅ {file_to_delete.original_filename} удалён", show_alert=False)
    await show_session_files_for_delete(callback, session)
    await callback.message.answer(
        "👩‍🏫 <b>Панель старосты:</b>",
        reply_markup=Keyboards.get_admin_main_keyboard(),
        parse_mode="HTML"
    )
