import logging
from datetime import datetime
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from bot.db.models import Event, User
from bot.utils.keyboards import Keyboards
from bot.utils.state import EventCreation


logger = logging.getLogger(__name__)
router_admin_events = Router()


@router_admin_events.callback_query(F.data == "admin_edit_events")
async def goto_edit_events(callback: types.CallbackQuery):
    """Переход в меню управления событиями"""
    await callback.message.edit_text(
        "📅 <b>Управление событиями</b>\n\n"
        "Выберите действие:",
        reply_markup=Keyboards.get_admin_events_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()
# ==========================================
# 1. НАЧАЛО СОЗДАНИЯ СОБЫТИЯ
# ==========================================

@router_admin_events.callback_query(F.data == "admin_add_event")
async def start_create_event(callback: types.CallbackQuery, session: AsyncSession, state: FSMContext):
    """Админ нажал 'Создать событие' → запрашиваем название"""
    
    # Проверка прав
    stmt = select(User).where(User.user_id == callback.from_user.id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user or user.status not in ("admin", "superadmin"):
        await callback.answer("❌ У вас нет прав для этой операции", show_alert=True)
        return
    
    await state.set_state(EventCreation.waiting_for_title)
    
    await callback.message.edit_text(
        "📅 <b>Создание нового события</b>\n\n"
        "📝 <b>Введите название события:</b>\n"
        "<i>Например: «Открытая лекция», «День карьеры», «Хакатон»</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="goto_back")]
        ]),
        parse_mode="HTML"
    )
    await callback.answer()


# ==========================================
# 2. ПОЛУЧЕНИЕ НАЗВАНИЯ СОБЫТИЯ
# ==========================================

@router_admin_events.message(EventCreation.waiting_for_title, F.text)
async def event_title_received(message: types.Message, state: FSMContext, session: AsyncSession):
    """Получили название → запрашиваем дату и время"""
    
    title = message.text.strip()
    
    if len(title) < 3:
        await message.answer("❌ Название слишком короткое (минимум 3 символа)\n\nВведите название события:")
        return
    
    if len(title) > 100:
        await message.answer("❌ Название слишком длинное (максимум 100 символов)\n\nВведите название события:")
        return
    
    # Сохраняем название в FSM
    await state.update_data(title=title)
    await state.set_state(EventCreation.waiting_for_date)
    
    await message.answer(
        f"✅ <b>Название:</b> <code>{title}</code>\n\n"
        "🕒 <b>Введите дату и время события:</b>\n"
        "<i>Формат: ДД.ММ.ГГГГ ЧЧ:ММ</i>\n"
        "<i>Пример: <code>25.12.2024 18:00</code></i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="goto_back")]
        ]),
        parse_mode="HTML"
    )


# ==========================================
# 3. ПОЛУЧЕНИЕ ДАТЫ И ВРЕМЕНИ
# ==========================================

@router_admin_events.message(EventCreation.waiting_for_date, F.text)
async def event_date_received(message: types.Message, state: FSMContext, session: AsyncSession):
    """Получили дату → проверяем и запрашиваем описание"""
    
    date_text = message.text.strip()
    
    # Парсим дату в формате ДД.ММ.ГГГГ ЧЧ:ММ
    try:
        event_date = datetime.strptime(date_text, "%d.%m.%Y %H:%M")
    except ValueError:
        await message.answer(
            "❌ <b>Неверный формат даты!</b>\n\n"
            "Используйте формат: <code>ДД.ММ.ГГГГ ЧЧ:ММ</code>\n"
            "<i>Пример: <code>25.12.2024 18:00</code></i>",
            parse_mode="HTML"
        )
        return
    
    # Проверяем, что дата не в прошлом
    if event_date < datetime.now():
        await message.answer(
            "❌ <b>Дата не может быть в прошлом!</b>\n\n"
            "Введите будущую дату и время:",
            parse_mode="HTML"
        )
        return
    
    # Сохраняем дату в FSM
    await state.update_data(event_date=event_date.isoformat())  # Сохраняем как строку
    await state.set_state(EventCreation.waiting_for_description)
    
    await message.answer(
        f"✅ <b>Дата и время:</b> <code>{event_date.strftime('%d.%m.%Y %H:%M')}</code>\n\n"
        "📝 <b>Введите описание события (опционально):</b>\n"
        "<i>Или напишите <code>пропустить</code>, чтобы оставить пустым</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏭️ Пропустить", callback_data="skip_event_description")]
        ]),
        parse_mode="HTML"
    )


# ==========================================
# 4. ПОЛУЧЕНИЕ ОПИСАНИЯ И СОЗДАНИЕ СОБЫТИЯ
# ==========================================

@router_admin_events.message(EventCreation.waiting_for_description, F.text)
async def event_description_received(message: types.Message, state: FSMContext, session: AsyncSession):
    """Получили описание → создаём событие в БД"""
    
    description = message.text.strip()
    
    # Получаем все данные из FSM
    data = await state.get_data()
    title = data.get("title")
    event_date = datetime.fromisoformat(data.get("event_date"))
    
    # Если описание = "пропустить", оставляем пустым
    if description.lower() == "пропустить":
        description = None
    
    # Получаем ID текущего пользователя
    stmt = select(User).where(User.user_id == message.from_user.id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    
    # Создаём событие в БД
    new_event = Event(
        title=title,
        event_date=event_date,
        description=description,
        created_by=user.id if user else None
    )
    
    session.add(new_event)
    await session.commit()
    await session.refresh(new_event)
    
    # Очищаем состояние
    await state.clear()
    
    logger.info(f"✅ Event created: id={new_event.id}, title={title}, date={event_date}")
    
    await message.answer(
        f"✅ <b>Событие создано!</b>\n\n"
        f"📅 <b>Название:</b> {title}\n"
        f"🕒 <b>Дата и время:</b> {event_date.strftime('%d.%m.%Y %H:%M')}\n"
        f"📝 <b>Описание:</b> {description or 'Нет описания'}\n"
        f"🆔 <b>ID события:</b> {new_event.id}",
        reply_markup=Keyboards.get_admin_main_keyboard(),
        parse_mode="HTML"
    )


# ==========================================
# 5. КНОПКА "ПРОПУСТИТЬ" ОПИСАНИЕ
# ==========================================

@router_admin_events.callback_query(EventCreation.waiting_for_description, F.data == "skip_event_description")
async def skip_event_description(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    """Пропускаем описание → создаём событие без описания"""
    
    data = await state.get_data()
    title = data.get("title")
    event_date = datetime.fromisoformat(data.get("event_date"))
    
    # Получаем ID текущего пользователя
    stmt = select(User).where(User.user_id == callback.from_user.id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    
    # Создаём событие в БД
    new_event = Event(
        title=title,
        event_date=event_date,
        description=None,
        created_by=user.id if user else None
    )
    
    session.add(new_event)
    await session.commit()
    await session.refresh(new_event)
    
    await state.clear()
    
    logger.info(f"✅ Event created (no description): id={new_event.id}, title={title}")
    
    await callback.message.edit_text(
        f"✅ <b>Событие создано!</b>\n\n"
        f"📅 <b>Название:</b> {title}\n"
        f"🕒 <b>Дата и время:</b> {event_date.strftime('%d.%m.%Y %H:%M')}\n"
        f"📝 <b>Описание:</b> Нет описания\n"
        f"🆔 <b>ID события:</b> {new_event.id}",
        reply_markup=Keyboards.get_admin_main_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


# ==========================================
# 6. ОТМЕНА СОЗДАНИЯ СОБЫТИЯ
# ==========================================

@router_admin_events.message(EventCreation.waiting_for_title, F.text.lower() == "отмена")
@router_admin_events.message(EventCreation.waiting_for_date, F.text.lower() == "отмена")
@router_admin_events.message(EventCreation.waiting_for_description, F.text.lower() == "отмена")
async def cancel_event_creation(message: types.Message, state: FSMContext):
    """Отмена создания события"""
    await state.clear()
    
    await message.answer(
        "❌ <b>Создание события отменено</b>",
        reply_markup=Keyboards.get_admin_main_keyboard(),
        parse_mode="HTML"
    )


# ==========================================
# 7. ПРОСМОТР ВСЕХ СОБЫТИЙ (ДЛЯ АДМИНА)
# ==========================================

@router_admin_events.callback_query(F.data == "admin_view_events")
async def view_all_events(callback: types.CallbackQuery, session: AsyncSession):
    """Показывает список всех событий для админа"""
    
    stmt = select(Event).order_by(desc(Event.event_date)).limit(20)
    result = await session.execute(stmt)
    events = result.scalars().all()
    
    if not events:
        await callback.answer("📭 Пока нет событий", show_alert=True)
        return
    
    event_list = "\n".join([
        f"📅 <b>{e.title}</b>\n"
        f"   🕒 {e.event_date.strftime('%d.%m.%Y %H:%M')}\n"
        f"   🆔 ID: <code>{e.id}</code>"
        for e in events[:10]
    ])
    
    keyboard = []
    for e in events[:10]:
        keyboard.append([
            InlineKeyboardButton(
                text=f"🗑️ {e.title[:25]}...",
                callback_data=f"event_delete_{e.id}"  # ✅ УНИКАЛЬНЫЙ ПРЕФИКС
            )
        ])
    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_edit_events")])
    
    await callback.message.edit_text(
        f"📅 <b>Все события</b> (последние {len(events)}):\n\n{event_list}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML"
    )
    await callback.answer()


# ==========================================
# 8. ПОДТВЕРЖДЕНИЕ УДАЛЕНИЯ СОБЫТИЯ
# ==========================================

@router_admin_events.callback_query(F.data.startswith("event_delete_"))
async def confirm_delete_event(callback: types.CallbackQuery, session: AsyncSession):
    """Подтверждение удаления события"""
    event_id = int(callback.data.replace("event_delete_", ""))  # ✅
    
    event = await session.get(Event, event_id)
    
    if not event:
        await callback.answer("❌ Событие не найдено", show_alert=True)
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"event_confirm_delete_{event_id}"),  # ✅
            InlineKeyboardButton(text="❌ Отмена", callback_data="admin_view_events")
        ]
    ])
    
    await callback.message.edit_text(
        f"⚠️ <b>Удалить событие?</b>\n\n"
        f"📅 {event.title}\n"
        f"🕒 {event.event_date.strftime('%d.%m.%Y %H:%M')}\n"
        f"📝 {event.description or 'Без описания'}",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await callback.answer()


# ==========================================
# 9. УДАЛЕНИЕ СОБЫТИЯ
# ==========================================

@router_admin_events.callback_query(F.data.startswith("event_confirm_delete_"))
async def execute_delete_event(callback: types.CallbackQuery, session: AsyncSession):
    """Финальное удаление события"""
    event_id = int(callback.data.replace("event_confirm_delete_", ""))  # ✅
    
    event = await session.get(Event, event_id)
    if not event:
        await callback.answer("❌ Уже удалено", show_alert=True)
        await view_all_events(callback, session)
        return
    
    await session.delete(event)
    await session.commit()
    
    await callback.answer(f"✅ Событие «{event.title}» удалено", show_alert=False)
    await view_all_events(callback, session)
    await callback.message.edit_text(
        "👨‍🏫 <b>Панель старосты:</b>",
        reply_markup=Keyboards.get_admin_main_keyboard(),
        parse_mode="HTML"
    )



# ==========================================
# УДАЛЕНИЕ СОБЫТИЙ (через кнопку "➖ Удалить событие")
# ==========================================

@router_admin_events.callback_query(F.data == "admin_del_event")
async def show_events_for_deletion(callback: types.CallbackQuery, session: AsyncSession):
    """Показывает список событий для удаления"""
    logger.info(f"🔍 admin_del_event clicked by user {callback.from_user.id}")
    
    # Проверка прав
    stmt = select(User).where(User.user_id == callback.from_user.id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user or user.status not in ("admin", "superadmin"):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    
    # Получаем все события
    stmt_events = select(Event).order_by(desc(Event.event_date)).limit(20)
    result_events = await session.execute(stmt_events)
    events = result_events.scalars().all()
    
    logger.info(f"📊 Found {len(events)} events for deletion")
    
    if not events:
        await callback.answer("📭 Нет событий для удаления", show_alert=True)
        return
    
    # Формируем клавиатуру с кнопками удаления
    keyboard = []
    for e in events:
        keyboard.append([
            InlineKeyboardButton(
                text=f"🗑️ {e.title[:30]}{'...' if len(e.title) > 30 else ''} ({e.event_date.strftime('%d.%m')})",
                callback_data=f"event_delete_{e.id}"  # ✅ Уникальный префикс
            )
        ])
    
    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_edit_events")])
    
    await callback.message.edit_text(
        f"📅 <b>Выберите событие для удаления</b> (всего: {len(events)}):\n\n"
        "Нажмите на событие, чтобы удалить его:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML"
    )
    await callback.answer()


# ==========================================
# ПОДТВЕРЖДЕНИЕ УДАЛЕНИЯ СОБЫТИЯ
# ==========================================

@router_admin_events.callback_query(F.data.startswith("event_delete_"))
async def confirm_delete_event(callback: types.CallbackQuery, session: AsyncSession):
    """Подтверждение удаления события"""
    event_id = int(callback.data.replace("event_delete_", ""))  # ✅
    logger.info(f"🔍 Confirm delete event id={event_id}")
    
    event = await session.get(Event, event_id)
    
    if not event:
        await callback.answer("❌ Событие не найдено", show_alert=True)
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"event_confirm_delete_{event_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="admin_del_event")
        ]
    ])
    
    await callback.message.edit_text(
        f"⚠️ <b>Удалить событие?</b>\n\n"
        f"📅 {event.title}\n"
        f"🕒 {event.event_date.strftime('%d.%m.%Y %H:%M')}\n"
        f"📝 {event.description or 'Без описания'}",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await callback.answer()


# ==========================================
# ФИНАЛЬНОЕ УДАЛЕНИЕ СОБЫТИЯ
# ==========================================

@router_admin_events.callback_query(F.data.startswith("event_confirm_delete_"))
async def execute_delete_event(callback: types.CallbackQuery, session: AsyncSession):
    """Финальное удаление события"""
    event_id = int(callback.data.replace("event_confirm_delete_", ""))  # ✅
    logger.info(f"🔍 Execute delete event id={event_id}")
    
    event = await session.get(Event, event_id)
    if not event:
        await callback.answer("❌ Уже удалено", show_alert=True)
        await show_events_for_deletion(callback, session)
        return
    
    await session.delete(event)
    await session.commit()
    
    logger.info(f"✅ Event deleted: id={event_id}, title={event.title}")
    
    await callback.answer(f"✅ Событие «{event.title}» удалено", show_alert=False)
    await show_events_for_deletion(callback, session)  # Возвращаем к списку