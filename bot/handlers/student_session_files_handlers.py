import logging

from aiogram import Router, F, types
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

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
    """Показывает категории из таблицы SessionFile"""
    
    # Получаем уникальные категории
    stmt = select(SessionFile.category).where(SessionFile.category.isnot(None)).distinct()
    result = await session.execute(stmt)
    categories = [cat for cat in result.scalars().all() if cat]
    
    if not categories:
        await callback.answer("📭 Пока нет файлов сессий", show_alert=True)
        return
    
    # Формируем список для отображения
    cat_list = "\n".join(f"• <code>{cat}</code>" for cat in sorted(set(categories)))
    
    # Клавиатура с категориями
    keyboard = []
    for cat in sorted(set(categories)):
        keyboard.append([
            InlineKeyboardButton(text=f"📁 {cat}", callback_data=f"session_files_in_{cat}")
        ])
    
    await callback.message.edit_text(
        f"🎓 <b>Файлы учебных сессий</b>\n\n"
        f"📂 Доступные категории:\n{cat_list}\n\n"
        f"<i>Выберите категорию для просмотра файлов</i>",
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
    
    stmt = select(SessionFile.category).where(SessionFile.category.isnot(None)).distinct()
    result = await session.execute(stmt)
    categories = [cat for cat in result.scalars().all() if cat]
    

    if not categories:
        await message.answer(
            "📭 <b>Пока нет файлов сессий</b>\n\n"
            "Файлы появятся здесь, когда администратор их добавит.",
            reply_markup=Keyboards.get_student_menu(),
            parse_mode="HTML"
        )
        return
    
    # Клавиатура с категориями
    keyboard = []
    for cat in sorted(set(categories)):
        keyboard.append([
            InlineKeyboardButton(text=f"📁 {cat}", callback_data=f"session_files_in_{cat}")
        ])
    
    await message.answer(
        "🎓 <b>Файлы учебных сессий</b>\n\n"
        "📂 <b>Доступные категории:</b>\n\n" +
        "\n".join(f"• <code>{cat}</code>" for cat in sorted(set(categories))),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML"
    )


# ==========================================
# 2. ПОКАЗАТЬ ФАЙЛЫ В КАТЕГОРИИ СЕССИЙ
# ==========================================

@router_session_files_student.callback_query(F.data.startswith("session_files_in_"))
async def show_session_files_in_category(callback: types.CallbackQuery, session: AsyncSession):
    """Показывает файлы из SessionFile в выбранной категории"""
    
    category = callback.data.replace("session_files_in_", "")
    
    # Запрос файлов
    stmt = select(SessionFile).where(
        SessionFile.category == category
    ).order_by(desc(SessionFile.created_at)).limit(20)
    
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
    
    keyboard.append([InlineKeyboardButton(text="🔙 К категориям", callback_data="view_session_files")])
    
    await callback.message.edit_text(
        f"📂 <b>Категория:</b> <code>{category}</code> (файлы сессий)\n\n{file_list}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML"
    )
    await callback.answer()


# ==========================================
# 3. СКАЧИВАНИЕ ФАЙЛА СЕССИИ
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