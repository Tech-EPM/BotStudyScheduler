from aiogram import Router, F, types
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
import logging

from bot.db.models import FileDocument
from bot.utils.keyboards import Keyboards
from bot.utils.file_storage import get_file_full_path


logger = logging.getLogger(__name__)
router_files_student = Router()


# ==========================================
# 1. ОТКРЫТИЕ ИЗ ГЛАВНОГО МЕНЮ (Reply Keyboard)
# ==========================================

@router_files_student.message(F.text == "📚 Обычные файлы")
@router_files_student.message(Command('view_file'))
async def open_files_from_menu(message: types.Message, session: AsyncSession):
    """Студент нажал кнопку '📚 Обычные файлы' в главном меню"""
    
    stmt = select(FileDocument.category).distinct()
    result = await session.execute(stmt)
    categories = [cat for cat in result.scalars().all() if cat]
    
    if not categories:
        await message.answer(
            "📭 <b>Пока нет файлов</b>\n\n"
            "Файлы появятся здесь, когда администратор их добавит.",
            reply_markup=Keyboards.get_student_menu(),
            parse_mode="HTML"
        )
        return
    
   
    await message.answer(
        "📚 <b>Обычные файлы</b> (База знаний)\n\n"
        "📂 <b>Доступные категории:</b>\n\n" +
        "\n".join(f"• <code>{cat}</code>" for cat in sorted(set(categories))),
        reply_markup=Keyboards.get_categories_keyboard(sorted(set(categories)), prefix="files_in_"),
        parse_mode="HTML"
    )


# ==========================================
# 2. ПРОСМОТР КАТЕГОРИЙ (Inline Callback)
# ==========================================

@router_files_student.callback_query(F.data == "view_common_files") 
async def show_common_categories(callback: types.CallbackQuery, session: AsyncSession):
    """Показывает категории обычных файлов через inline-кнопку"""
    
    stmt = select(FileDocument.category).distinct()
    result = await session.execute(stmt)
    categories = [cat for cat in result.scalars().all() if cat]
    
    if not categories:
        await callback.answer("📭 Пока нет файлов", show_alert=True)
        return
    
    await callback.message.edit_text(
        "📚 <b>Обычные файлы</b> (База знаний)\n\n"
        "📂 <b>Доступные категории:</b>\n\n" +
        "\n".join(f"• <code>{cat}</code>" for cat in sorted(set(categories))),
        reply_markup=Keyboards.get_categories_keyboard(sorted(set(categories)), prefix="files_in_"),
        parse_mode="HTML"
    )
    await callback.answer()


# ==========================================
# 3. ФАЙЛЫ В КАТЕГОРИИ
# ==========================================

@router_files_student.callback_query(F.data.startswith("files_in_"))
async def show_files_in_category(callback: types.CallbackQuery, session: AsyncSession):
    """Показывает файлы из FileDocument в выбранной категории"""
    
    category = callback.data.replace("files_in_", "")
    
    stmt = select(FileDocument).where(
        FileDocument.category == category
    ).order_by(desc(FileDocument.uploaded_at)).limit(20)
    
    result = await session.execute(stmt)
    files = result.scalars().all()
    
    if not files:
        await callback.answer("📭 В этой категории пока пусто", show_alert=True)
        return
    
    # Формируем список файлов (первые 10)
    file_list = "\n".join([
        f"📄 <b>{f.file_name}</b>\n"
        f"   <i>💾 {f.file_size / 1024:.1f} КБ • {f.uploaded_at.strftime('%d.%m.%Y') if f.uploaded_at else 'N/A'}</i>"
        for f in files[:10]
    ])
    
    # Клавиатура со скачиванием
    keyboard = []
    for f in files[:10]:
        short_name = f.file_name[:25] + "..." if len(f.file_name) > 25 else f.file_name
        keyboard.append([
            InlineKeyboardButton(
                text=f"📥 {short_name}",
                callback_data=f"download_file_{f.id}"  # ✅ Префикс для обычных файлов
            )
        ])
    

    keyboard.append([InlineKeyboardButton(text="🔙 К категориям", callback_data="view_common_files")])
    
    await callback.message.edit_text(
        f"📂 <b>Категория:</b> <code>{category}</code>\n\n{file_list}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML"
    )
    await callback.answer()


# ==========================================
# 4. СКАЧИВАНИЕ ФАЙЛА
# ==========================================
@router_files_student.callback_query(F.data.startswith("download_file_"))
async def download_file(callback: types.CallbackQuery, session: AsyncSession):
    import logging
    from aiogram.exceptions import TelegramBadRequest
    
    file_id = callback.data.replace("download_file_", "")
    
    try:
        doc = await session.get(FileDocument, file_id)
        if not doc:
            try:
                await callback.answer("❌ Файл не найден", show_alert=True)
            except TelegramBadRequest:
                await callback.message.answer("❌ Файл не найден")
            return
    

        file_path = get_file_full_path(doc.file_path)
        if not file_path.exists():
            try:
                await callback.answer("❌ Файл не найден на диске", show_alert=True)
            except TelegramBadRequest:
                await callback.message.answer("❌ Файл не найден на диске")
            return
        
        
        await callback.message.answer_document(
            document=types.FSInputFile(str(file_path)),
            caption=f"📄 {doc.file_name}\n📂 Категория: {doc.category}",
            parse_mode="HTML"
        )
        
        
        try:
            await callback.answer("✅ Файл отправлен!", show_alert=False)
        except TelegramBadRequest as e:
            
            logging.info(f"⚠️ Callback query expired (нормально): {e}")
            
            
    except Exception as e:
        logging.error(f"Download error: {e}")
        try:
            await callback.answer("❌ Ошибка отправки файла", show_alert=True)
        except TelegramBadRequest:
            await callback.message.answer("❌ Ошибка отправки файла")

# ==========================================
# 5. ОТПРАВКА ПО ID (для прямых ссылок)
# ==========================================

@router_files_student.message(F.text.regexp(r"^/file_(\d+)$"))
async def send_file_by_id(message: types.Message, session: AsyncSession):
    """Отправляет файл по прямому ID (например, из другого чата)"""
    
    file_id = int(message.text.split("_")[1])
    
    doc = await session.get(FileDocument, file_id)
    
    if not doc:
        await message.answer("❌ Файл не найден")
        return
    
    file_path = get_file_full_path(doc.file_path)
    
    if not file_path.exists():
        await message.answer("⚠️ Файл был удалён с сервера")
        return
    
    caption = f"📎 {doc.file_name}\n📂 {doc.category}\n💾 {doc.file_size / 1024:.1f} КБ"
    
    try:
        ext = doc.file_extension.lower()
        if ext in ['png', 'jpg', 'jpeg', 'gif', 'webp']:
            await message.answer_photo(
                photo=FSInputFile(str(file_path)),
                caption=caption
            )
        else:
            await message.answer_document(
                document=FSInputFile(str(file_path)),
                caption=caption,
                file_name=doc.file_name
            )
    except Exception as e:
        logger.error(f"Error sending file by ID {file_id}: {e}")
        await message.answer("❌ Ошибка отправки файла")