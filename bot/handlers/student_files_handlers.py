from aiogram import Router, F, types
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
import logging

from bot.db.models import FileDocument, User
from bot.utils.keyboards import Keyboards
from bot.utils.file_storage import get_file_full_path


logger = logging.getLogger(__name__)
router_files_student = Router()


async def _menu_for_user(session: AsyncSession, telegram_user_id: int):
    result = await session.execute(select(User).where(User.user_id == telegram_user_id))
    user = result.scalar_one_or_none()
    if user and user.status == "admin":
        return Keyboards.get_admin_menu()
    if user and user.status == "teacher":
        return Keyboards.get_teacher_menu()
    return Keyboards.get_student_menu()


# ==========================================
# 1. ОТКРЫТИЕ ИЗ ГЛАВНОГО МЕНЮ (Reply Keyboard)
# ==========================================

@router_files_student.message(F.text == "📚 Учебные материалы")
@router_files_student.message(Command('view_file'))
async def open_files_from_menu(message: types.Message, session: AsyncSession):
    """Студент нажал кнопку '📚 Учебные материалы' в главном меню"""

    subject_rows = await session.execute(
        select(func.min(FileDocument.id), func.coalesce(FileDocument.subject, "Без предмета"))
        .group_by(func.coalesce(FileDocument.subject, "Без предмета"))
        .order_by(func.coalesce(FileDocument.subject, "Без предмета"))
    )
    subjects = [(file_id, subject) for file_id, subject in subject_rows.all() if subject]

    if not subjects:
        menu = await _menu_for_user(session, message.from_user.id)
        await message.answer(
            "📭 <b>Пока нет файлов</b>\n\n"
            "Файлы появятся здесь, когда администратор их добавит.",
            reply_markup=menu,
            parse_mode="HTML"
        )
        return
    
    keyboard = [
        [InlineKeyboardButton(text=f"📘 {subject}", callback_data=f"files_subject_{file_id}")]
        for file_id, subject in subjects
    ]

    await message.answer(
        "📚 <b>Учебные материалы</b>\n\n"
        "Выберите предмет:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML"
    )


# ==========================================
# 2. ПРОСМОТР КАТЕГОРИЙ (Inline Callback)
# ==========================================

@router_files_student.callback_query(F.data == "view_common_files") 
async def show_common_categories(callback: types.CallbackQuery, session: AsyncSession):
    """Показывает категории обычных файлов через inline-кнопку"""

    subject_rows = await session.execute(
        select(func.min(FileDocument.id), func.coalesce(FileDocument.subject, "Без предмета"))
        .group_by(func.coalesce(FileDocument.subject, "Без предмета"))
        .order_by(func.coalesce(FileDocument.subject, "Без предмета"))
    )
    subjects = [(file_id, subject) for file_id, subject in subject_rows.all() if subject]

    if not subjects:
        await callback.answer("📭 Пока нет файлов", show_alert=True)
        return

    keyboard = [
        [InlineKeyboardButton(text=f"📘 {subject}", callback_data=f"files_subject_{file_id}")]
        for file_id, subject in subjects
    ]

    await callback.message.edit_text(
        "📚 <b>Учебные материалы</b>\n\n"
        "Выберите предмет:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML"
    )
    await callback.answer()


# ==========================================
# 3. КАТЕГОРИИ В ПРЕДМЕТЕ
# ==========================================
@router_files_student.callback_query(F.data.startswith("files_subject_"))
async def show_subject_categories(callback: types.CallbackQuery, session: AsyncSession):
    file_id = int(callback.data.replace("files_subject_", ""))
    doc = await session.get(FileDocument, file_id)
    if not doc:
        await callback.answer("❌ Предмет не найден", show_alert=True)
        return

    subject_name = doc.subject or "Без предмета"
    subject_filter = FileDocument.subject.is_(None) if doc.subject is None else (FileDocument.subject == doc.subject)

    category_rows = await session.execute(
        select(func.min(FileDocument.id), FileDocument.category)
        .where(subject_filter)
        .group_by(FileDocument.category)
        .order_by(FileDocument.category)
    )
    categories = [(rep_id, cat) for rep_id, cat in category_rows.all() if cat]
    if not categories:
        await callback.answer("📭 В этом предмете пока нет файлов", show_alert=True)
        return

    keyboard = [
        [InlineKeyboardButton(text=f"📁 {cat}", callback_data=f"files_cat_{rep_id}")]
        for rep_id, cat in categories
    ]
    keyboard.append([InlineKeyboardButton(text="🔙 К предметам", callback_data="view_common_files")])

    await callback.message.edit_text(
        f"📘 <b>Предмет:</b> {subject_name}\n\nВыберите категорию:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML"
    )
    await callback.answer()


# ==========================================
# 4. ФАЙЛЫ В КАТЕГОРИИ
# ==========================================

@router_files_student.callback_query(F.data.startswith("files_cat_"))
async def show_files_by_category_id(callback: types.CallbackQuery, session: AsyncSession):
    rep_id = int(callback.data.replace("files_cat_", ""))
    rep = await session.get(FileDocument, rep_id)
    if not rep:
        await callback.answer("❌ Категория не найдена", show_alert=True)
        return

    stmt = select(FileDocument).where(
        (FileDocument.subject.is_(None) if rep.subject is None else (FileDocument.subject == rep.subject)),
        FileDocument.category == rep.category,
    ).order_by(desc(FileDocument.uploaded_at)).limit(20)

    result = await session.execute(stmt)
    files = result.scalars().all()
    if not files:
        await callback.answer("📭 В этой категории пока пусто", show_alert=True)
        return

    file_list = "\n".join([
        f"📄 <b>{f.file_name}</b>\n"
        f"   <i>💾 {f.file_size / 1024:.1f} КБ • {f.uploaded_at.strftime('%d.%m.%Y') if f.uploaded_at else 'N/A'}</i>"
        for f in files[:10]
    ])

    keyboard = []
    for f in files[:10]:
        short_name = f.file_name[:25] + "..." if len(f.file_name) > 25 else f.file_name
        keyboard.append([InlineKeyboardButton(text=f"📥 {short_name}", callback_data=f"download_file_{f.id}")])
    keyboard.append([InlineKeyboardButton(text="🔙 К предметам", callback_data="view_common_files")])

    await callback.message.edit_text(
        f"📘 <b>{rep.subject or 'Без предмета'}</b>\n📂 <b>{rep.category}</b>\n\n{file_list}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML"
    )
    await callback.answer()


@router_files_student.callback_query(F.data.startswith("files_in_"))
async def show_files_in_category(callback: types.CallbackQuery, session: AsyncSession):
    """Показывает файлы из FileDocument в выбранной категории"""

    payload = callback.data.replace("files_in_", "")
    if "|" in payload:
        subject, category = payload.split("|", 1)
        stmt = select(FileDocument).where(
            FileDocument.subject == subject,
            FileDocument.category == category,
        ).order_by(desc(FileDocument.uploaded_at)).limit(20)
        back_cb = "view_common_files"
        header = f"📘 <b>{subject}</b>\n📂 <b>Категория:</b> <code>{category}</code>"
    else:
        category = payload
        stmt = select(FileDocument).where(
            FileDocument.category == category
        ).order_by(desc(FileDocument.uploaded_at)).limit(20)
        back_cb = "view_common_files"
        header = f"📂 <b>Категория:</b> <code>{category}</code>"
    
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
    

    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data=back_cb)])
    
    await callback.message.edit_text(
        f"{header}\n\n{file_list}",
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
