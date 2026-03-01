import logging

from aiogram import Router, F, types
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func

from bot.db.models import SessionFile
from bot.utils.keyboards import Keyboards
from bot.utils.file_storage import get_file_full_path


from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiohttp import ClientConnectorError, ClientConnectionError, ClientError
import asyncio
import time

router_session_files_student = Router()

# ==========================================
# 1. ПОКАЗАТЬ КАТЕГОРИИ ФАЙЛОВ СЕССИЙ
# ==========================================

@router_session_files_student.callback_query(F.data == "view_session_files")
async def show_session_categories(callback: types.CallbackQuery, session: AsyncSession):
    """Показывает разделы сессий из таблицы SessionFile"""

    stmt = (
        select(func.min(SessionFile.id), func.coalesce(SessionFile.session_group, "Сессия"))
        .group_by(func.coalesce(SessionFile.session_group, "Сессия"))
        .order_by(func.coalesce(SessionFile.session_group, "Сессия"))
    )
    result = await session.execute(stmt)
    groups = [(file_id, name) for file_id, name in result.all() if name]

    if not groups:
        await callback.answer("📭 Пока нет файлов сессий", show_alert=True)
        return

    keyboard = [
        [InlineKeyboardButton(text=f"🗂 {name}", callback_data=f"session_group_{file_id}")]
        for file_id, name in groups
    ]
    
    await callback.message.edit_text(
        f"🎓 <b>Файлы учебных сессий</b>\n\n"
        f"<i>Выберите сессию</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML"
    )
    await callback.answer()


# ==========================================
# 0. ОТКРЫТИЕ ИЗ ГЛАВНОГО МЕНЮ (Reply Keyboard)
# ==========================================

@router_session_files_student.message(F.text == "🎓 Файлы сессий")
async def open_session_files_from_menu(message: types.Message, session: AsyncSession):
    """Студент нажал кнопку '🎓 Файлы сессий' в главном меню"""
    
    result = await session.execute(
        select(func.min(SessionFile.id), func.coalesce(SessionFile.session_group, "Сессия"))
        .group_by(func.coalesce(SessionFile.session_group, "Сессия"))
        .order_by(func.coalesce(SessionFile.session_group, "Сессия"))
    )
    groups = [(file_id, name) for file_id, name in result.all() if name]
    

    if not groups:
        await message.answer(
            "📭 <b>Пока нет файлов сессий</b>\n\n"
            "Файлы появятся здесь, когда администратор их добавит.",
            reply_markup=Keyboards.get_student_menu(),
            parse_mode="HTML"
        )
        return
    
    keyboard = [
        [InlineKeyboardButton(text=f"🗂 {name}", callback_data=f"session_group_{file_id}")]
        for file_id, name in groups
    ]
    
    await message.answer(
        "🎓 <b>Файлы учебных сессий</b>\n\n"
        "Выберите сессию:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML"
    )


# ==========================================
# 2. ВЫБОР ПРЕДМЕТА В СЕССИИ
# ==========================================
@router_session_files_student.callback_query(F.data.startswith("session_group_"))
async def show_session_subjects(callback: types.CallbackQuery, session: AsyncSession):
    file_id = callback.data.replace("session_group_", "")
    doc = await session.get(SessionFile, file_id)
    if not doc:
        await callback.answer("❌ Раздел сессии не найден", show_alert=True)
        return

    group_name = doc.session_group or "Сессия"
    group_filter = SessionFile.session_group.is_(None) if doc.session_group is None else (SessionFile.session_group == doc.session_group)

    rows = await session.execute(
        select(func.min(SessionFile.id), SessionFile.subject)
        .where(group_filter)
        .group_by(SessionFile.subject)
        .order_by(SessionFile.subject)
    )
    subjects = [(rep_id, subject or "Без предмета") for rep_id, subject in rows.all()]
    if not subjects:
        await callback.answer("📭 В этой сессии пока нет предметов", show_alert=True)
        return

    keyboard = [
        [InlineKeyboardButton(text=f"📘 {subject}", callback_data=f"session_subject_{rep_id}")]
        for rep_id, subject in subjects
    ]
    keyboard.append([InlineKeyboardButton(text="🔙 К сессиям", callback_data="view_session_files")])

    await callback.message.edit_text(
        f"🗂 <b>{group_name}</b>\n\nВыберите предмет:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML"
    )
    await callback.answer()


# ==========================================
# 3. ВЫБОР КАТЕГОРИИ В ПРЕДМЕТЕ
# ==========================================
@router_session_files_student.callback_query(F.data.startswith("session_subject_"))
async def show_session_categories_in_subject(callback: types.CallbackQuery, session: AsyncSession):
    file_id = callback.data.replace("session_subject_", "")
    doc = await session.get(SessionFile, file_id)
    if not doc:
        await callback.answer("❌ Предмет не найден", show_alert=True)
        return

    group_name = doc.session_group or "Сессия"
    subject_name = doc.subject or "Без предмета"
    group_filter = SessionFile.session_group.is_(None) if doc.session_group is None else (SessionFile.session_group == doc.session_group)
    subject_filter = SessionFile.subject.is_(None) if doc.subject is None else (SessionFile.subject == doc.subject)

    rows = await session.execute(
        select(func.min(SessionFile.id), SessionFile.category)
        .where(group_filter, subject_filter)
        .group_by(SessionFile.category)
        .order_by(SessionFile.category)
    )
    categories = [(rep_id, cat) for rep_id, cat in rows.all() if cat]
    if not categories:
        await callback.answer("📭 В этом предмете пока нет категорий", show_alert=True)
        return

    keyboard = [
        [InlineKeyboardButton(text=f"📁 {cat}", callback_data=f"session_cat_{rep_id}")]
        for rep_id, cat in categories
    ]
    keyboard.append([InlineKeyboardButton(text="🔙 К предметам", callback_data=f"session_group_{file_id}")])

    await callback.message.edit_text(
        f"🗂 <b>{group_name}</b>\n📘 <b>{subject_name}</b>\n\nВыберите категорию:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML"
    )
    await callback.answer()


# ==========================================
# 4. ПОКАЗАТЬ ФАЙЛЫ В КАТЕГОРИИ СЕССИЙ
# ==========================================

@router_session_files_student.callback_query(F.data.startswith("session_cat_"))
async def show_session_files_by_cat_id(callback: types.CallbackQuery, session: AsyncSession):
    rep_id = callback.data.replace("session_cat_", "")
    rep = await session.get(SessionFile, rep_id)
    if not rep:
        await callback.answer("❌ Категория не найдена", show_alert=True)
        return

    stmt = select(SessionFile).where(
        (SessionFile.session_group.is_(None) if rep.session_group is None else (SessionFile.session_group == rep.session_group)),
        (SessionFile.subject.is_(None) if rep.subject is None else (SessionFile.subject == rep.subject)),
        SessionFile.category == rep.category,
    ).order_by(desc(SessionFile.created_at)).limit(20)

    result = await session.execute(stmt)
    files = result.scalars().all()
    if not files:
        await callback.answer("📭 В этой категории пока пусто", show_alert=True)
        return

    file_list = "\n".join([
        f"📄 <b>{f.original_filename}</b>\n"
        f"   <i>💾 {f.file_size / 1024:.1f} КБ • {f.created_at.strftime('%d.%m.%Y') if f.created_at else 'N/A'}</i>"
        for f in files[:10]
    ])

    keyboard = []
    for f in files[:10]:
        short_name = f.original_filename[:25] + "..." if len(f.original_filename) > 25 else f.original_filename
        keyboard.append([InlineKeyboardButton(text=f"📥 {short_name}", callback_data=f"download_session_file_{f.id}")])
    keyboard.append([InlineKeyboardButton(text="🔙 К разделам", callback_data="view_session_files")])

    await callback.message.edit_text(
        f"🗂 <b>{rep.session_group or 'Сессия'}</b>\n📘 <b>{rep.subject or 'Без предмета'}</b>\n📂 <b>{rep.category}</b>\n\n{file_list}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML",
    )
    await callback.answer()


@router_session_files_student.callback_query(F.data.startswith("session_files_in_"))
async def show_session_files_in_category(callback: types.CallbackQuery, session: AsyncSession):
    """Показывает файлы из SessionFile в выбранной категории"""

    payload = callback.data.replace("session_files_in_", "")
    if "|" in payload:
        group, subject, category = payload.split("|", 2)
        stmt = select(SessionFile).where(
            SessionFile.session_group == group,
            SessionFile.subject == subject,
            SessionFile.category == category,
        ).order_by(desc(SessionFile.created_at)).limit(20)
        back_text = "🔙 К предметам"
        back_callback = "view_session_files"
        header = f"🗂 <b>{group}</b>\n📘 <b>{subject}</b>\n📂 <b>{category}</b>"
    else:
        category = payload
        stmt = select(SessionFile).where(SessionFile.category == category).order_by(desc(SessionFile.created_at)).limit(20)
        back_text = "🔙 К разделам"
        back_callback = "view_session_files"
        header = f"📂 <b>{category}</b>"
    
    result = await session.execute(stmt)
    files = result.scalars().all()
    
    if not files:
        await callback.answer("📭 В этой категории пока пусто", show_alert=True)
        return
    
    # Формируем список файлов
    file_list = "\n".join([
        f"📄 <b>{f.original_filename}</b>\n"
        f"   <i>💾 {f.file_size / 1024:.1f} КБ • {f.created_at.strftime('%d.%m.%Y') if f.created_at else 'N/A'}</i>"
        for f in files[:10]
    ])
    
    # Клавиатура со скачиванием
    keyboard = []
    for f in files[:10]:
        short_name = f.original_filename[:25] + "..." if len(f.original_filename) > 25 else f.original_filename
        keyboard.append([
            InlineKeyboardButton(
                text=f"📥 {short_name}",
                callback_data=f"download_session_file_{f.id}"
            )
        ])
    
    keyboard.append([InlineKeyboardButton(text=back_text, callback_data=back_callback)])
    
    await callback.message.edit_text(
        f"{header}\n\n{file_list}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML"
    )
    await callback.answer()


# ==========================================
# 5. СКАЧИВАНИЕ ФАЙЛА СЕССИИ
# ==========================================

@router_session_files_student.callback_query(F.data.startswith("download_session_file_"))
async def download_session_file(callback: types.CallbackQuery, session: AsyncSession):
    """Отправляет файл из SessionFile пользователю"""
    
    
    logger = logging.getLogger(__name__)
    start_time = time.time()
    
    file_id = callback.data.replace("download_session_file_", "")
    
 
    try:
        await callback.answer("⏳ Загружаю файл...", show_alert=False)
    except TelegramBadRequest:
        pass 
    

    doc = await session.get(SessionFile, file_id)
    
    if not doc:
        logger.warning(f"File not found in DB: {file_id}")
        try:
            await callback.message.answer("❌ Файл не найден")
        except TelegramBadRequest:
            pass
        return
    

    file_path = get_file_full_path(doc.stored_path)
    
    if not file_path.exists():
        logger.warning(f"File not found on disk: {doc.stored_path}")
        try:
            await callback.message.answer("⚠️ Файл был удалён с сервера")
        except TelegramBadRequest:
            pass
        return
    

    try:
        file_size = file_path.stat().st_size
        if file_size > 50 * 1024 * 1024:
            logger.error(f"File too large: {file_size} bytes, {doc.original_filename}")
            try:
                await callback.message.answer("❌ Файл слишком большой (макс. 50 МБ)")
            except TelegramBadRequest:
                pass
            return
    except Exception as e:
        logger.error(f"Error getting file size: {e}")
    

    caption = f"📎 {doc.original_filename}\n📂 {doc.category or 'other'}\n💾 {doc.file_size / 1024:.1f} КБ"
    

    try:
        ext = doc.original_filename.split(".")[-1].lower() if "." in doc.original_filename else ""
        
        logger.info(f"📤 Starting send: {doc.original_filename} ({file_size / 1024:.1f} KB)")
        
        if ext in ['png', 'jpg', 'jpeg', 'gif', 'webp']:
            await callback.message.answer_photo(
                photo=FSInputFile(str(file_path)),
                caption=caption
            )
        else:
            await callback.message.answer_document(
                document=FSInputFile(str(file_path)),
                caption=caption,
                file_name=doc.original_filename
            )
        
        
        logger.info(f"✅ File sent successfully: {doc.original_filename}")
        
    except TelegramNetworkError as e:
        error_msg = str(e).lower()
       

        if "timeout" in error_msg:
            logger.warning(f"⚠️ TIMEOUT sending {doc.original_filename} — file was PROBABLY delivered")
            
           
            try:
                await callback.message.answer(
                    "📤 Файл отправлен!\n\n",
                    parse_mode="HTML"
                )
            except TelegramBadRequest:
                pass
            # ❗ ВАЖНО: break/return, чтобы НЕ делать повторную отправку!
            return
        
        # Другие сетевые ошибки — можно попробовать ещё 1 раз
        else:
            logger.warning(f"⚠️ Network error (not timeout), retrying once: {e}")
            try:
                await asyncio.sleep(1)
                # Повторная попытка отправки
                if ext in ['png', 'jpg', 'jpeg', 'gif', 'webp']:
                    await callback.message.answer_photo(
                        photo=FSInputFile(str(file_path)),
                        caption=caption
                    )
                else:
                    await callback.message.answer_document(
                        document=FSInputFile(str(file_path)),
                        caption=caption,
                        file_name=doc.original_filename
                    )
                logger.info(f"✅ File sent on retry: {doc.original_filename}")
            except Exception as retry_e:
                logger.error(f"❌ Retry also failed: {retry_e}")
                try:
                    await callback.message.answer("❌ Не удалось отправить файл. Попробуйте позже.")
                except TelegramBadRequest:
                    pass
                return
                
    except (ClientConnectorError, ClientConnectionError, ClientError, ConnectionError) as e:
       
        logger.warning(f"⚠️ Connection error, retrying once: {e}")
        try:
            await asyncio.sleep(1)
            if ext in ['png', 'jpg', 'jpeg', 'gif', 'webp']:
                await callback.message.answer_photo(
                    photo=FSInputFile(str(file_path)),
                    caption=caption
                )
            else:
                await callback.message.answer_document(
                    document=FSInputFile(str(file_path)),
                    caption=caption,
                    file_name=doc.original_filename
                )
            logger.info(f"✅ File sent on retry: {doc.original_filename}")
        except Exception as retry_e:
            logger.error(f"❌ Retry also failed: {retry_e}")
            try:
                await callback.message.answer("❌ Ошибка соединения")
            except TelegramBadRequest:
                pass
            return
            
    except Exception as e:
        logger.error(f"❌ Unexpected error: {type(e).__name__}: {e}")
        try:
            await callback.message.answer("❌ Произошла ошибка при отправке")
        except TelegramBadRequest:
            pass
        return


    category = doc.category or "other"
    from sqlalchemy import desc
    stmt = select(SessionFile).where(
        SessionFile.category == category
    ).order_by(desc(SessionFile.created_at)).limit(20)
    
    result = await session.execute(stmt)
    files = result.scalars().all()
    
    file_list = "\n".join([
        f"📄 <b>{f.original_filename}</b>\n"
        f"   <i>💾 {f.file_size / 1024:.1f} КБ</i>"
        for f in files[:10]
    ])
    
    keyboard = []
    for f in files[:10]:
        short_name = f.original_filename[:25] + "..." if len(f.original_filename) > 25 else f.original_filename
        keyboard.append([
            InlineKeyboardButton(text=f"📥 {short_name}", callback_data=f"download_session_file_{f.id}")
        ])
    keyboard.append([InlineKeyboardButton(text="🔙 К категориям", callback_data="view_session_files")])
    
    try:
        await callback.message.edit_text(
            f"📂 <b>Категория:</b> <code>{category}</code>\n\n{file_list}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )
    except TelegramBadRequest:
        pass
    except Exception as e:
        logger.warning(f"Could not update file list: {e}")
    
 
    elapsed = time.time() - start_time
    logger.info(f"⏱ Download handler completed in {elapsed:.2f}s")
