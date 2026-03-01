import logging
from datetime import datetime, timedelta
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func
from bot.db.models import User, Dispatchers
from bot.db.database import get_session
from bot.utils.reminder_service import get_reminder_service, Reminder
from bot.utils.state import ReminderState



logger = logging.getLogger(__name__)
router_reminder_admin = Router()

# ==========================================
# ПРОВЕРКА ПРАВ АДМИНА
# ==========================================
async def is_admin(user_id: int) -> bool:
    """
    Проверяет, является ли пользователь админом/диспетчером.
    """
    async with get_session() as session:
        # Проверка по таблице диспетчеров
        result = await session.execute(
            select(Dispatchers).where(Dispatchers.username == str(user_id))
        )
        if result.scalar_one_or_none():
            return True
        
        # Проверка по таблице пользователей
        result = await session.execute(
            select(User).where(User.user_id == user_id)
        )
        user = result.scalar_one_or_none()
        if user and user.status == "admin":
            return True
            
    return False


# ==========================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================================
def parse_date(date_str: str) -> datetime | None:
    """
    Парсит дату в различных форматах:
    - ДД.ММ.ГГГГ (15.12.2024)
    - ДД.ММ (15.12) - текущий год
    - ГГГГ-ММ-ДД (2024-12-15)
    """
    formats = [
        "%d.%m.%Y",
        "%d.%m",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d/%m",
    ]
    
    for fmt in formats:
        try:
            parsed = datetime.strptime(date_str.strip(), fmt)
            # Если год не указан, подставляем текущий
            if parsed.year == 1900:
                parsed = parsed.replace(year=datetime.now().year)
            return parsed
        except ValueError:
            continue
    return None


def parse_time(time_str: str) -> tuple[int, int] | None:
    """Парсит время в формате ЧЧ:ММ"""
    try:
        parts = time_str.strip().split(':')
        if len(parts) != 2:
            return None
        hour, minute = map(int, parts)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return (hour, minute)
    except ValueError:
        pass
    return None


# ==========================================
# ХЕНДЛЕРЫ
# ==========================================

@router_reminder_admin.callback_query(F.data == "admin_add_reminder")
async def start_add_reminder(callback: types.CallbackQuery, state: FSMContext):
    """Начало процесса создания напоминания"""
    if not await is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет прав для выполнения этой операции!", show_alert=True)
        logger.warning(f"User {callback.from_user.id} tried to add reminder without permissions")
        return

    await callback.message.edit_text(
        "🔔 Создание напоминания\n\n"
        "Введите username пользователя,\n"
        "которому нужно отправить сообщение:\n\n"
        "Пример: `@ivanov` или `ivanov`"
    )
    await state.set_state(ReminderState.waiting_for_username)
    await callback.answer()


@router_reminder_admin.message(ReminderState.waiting_for_username)
async def process_username(message: types.Message, state: FSMContext):
    """Обработка ввода username и поиск Telegram ID в БД"""
    username_input = (message.text or "").strip()
    if not username_input:
        await message.answer(
            "❌ **Ошибка:** username не может быть пустым.\n\n"
            "Пожалуйста, введите username пользователя:"
        )
        return

    normalized_username = username_input.lstrip("@").strip()
    if not normalized_username:
        await message.answer("❌ **Ошибка:** некорректный username. Пример: `@ivanov`")
        return

    async with get_session() as session:
        result = await session.execute(
            select(User).where(func.lower(User.username) == normalized_username.lower())
        )
        target_user = result.scalar_one_or_none()

    if not target_user:
        await message.answer(
            "❌ Пользователь не зарегистрирован в боте.\n\n"
            "Проверьте username и попробуйте снова."
        )
        return

    await state.update_data(
        target_user_id=target_user.user_id,
        target_username=target_user.username or normalized_username,
    )
    await state.set_state(ReminderState.waiting_for_date)
    
    today = datetime.now().strftime("%d.%m.%Y")
    await message.answer(
        f"✅ Пользователь найден: `@{target_user.username or normalized_username}`\n"
        f"🆔 Telegram ID: `{target_user.user_id}`\n\n"
        "📅 **Введите дату отправки** в одном из форматов:\n"
        "• `ДД.ММ.ГГГГ` (например: `15.12.2024`)\n"
        "• `ДД.ММ` (например: `15.12` — текущий год)\n"
        "• `ГГГГ-ММ-ДД` (например: `2024-12-15`)\n\n"
        f"📌 _Сегодня: {today}_"
    )


@router_reminder_admin.message(ReminderState.waiting_for_date)
async def process_date(message: types.Message, state: FSMContext):
    """Обработка ввода даты"""
    parsed_date = parse_date(message.text)
    
    if not parsed_date:
        await message.answer(
            "❌ **Ошибка формата даты.**\n\n"
            "Используйте один из форматов:\n"
            "• `ДД.ММ.ГГГГ` (15.12.2024)\n"
            "• `ДД.ММ` (15.12)\n"
            "• `ГГГГ-ММ-ДД` (2024-12-15)"
        )
        return


    if parsed_date.date() < datetime.now().date():
        await message.answer("❌ **Дата не может быть в прошлом.**\n\nПожалуйста, введите сегодняшнюю или будущую дату:")
        return


    await state.update_data(send_date=parsed_date)
    await state.set_state(ReminderState.waiting_for_time)
    
    await message.answer(
        f"✅ Дата установлена: **{parsed_date.strftime('%d.%m.%Y')}**\n\n"
        "🕒 **Введите время отправки** в формате **ЧЧ:ММ**\n"
        "Пример: `15:30`"
    )


@router_reminder_admin.message(ReminderState.waiting_for_time)
async def process_time(message: types.Message, state: FSMContext):
    """Обработка ввода времени"""
    time_result = parse_time(message.text)
    
    if not time_result:
        await message.answer(
            "❌ **Ошибка формата времени.**\n\n"
            "Используйте формат **ЧЧ:ММ** (например: `15:30`)"
        )
        return

    hour, minute = time_result
    data = await state.get_data()
    send_date = data['send_date']
    
    # Объединяем дату и время
    send_datetime = send_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
    
    # Проверка: время не должно быть в прошлом (если дата сегодня)
    now = datetime.now()
    if send_datetime <= now:
        await message.answer(
            "❌ **Указанное время уже прошло.**\n\n"
            "Пожалуйста, выберите время в будущем:"
        )
        return

    await state.update_data(send_time=send_datetime)
    await state.set_state(ReminderState.waiting_for_text)
    
    await message.answer(
        f"✅ Время установлено: **{send_datetime.strftime('%d.%m.%Y %H:%M')}**\n\n"
        "📝 **Введите текст напоминания:**"
    )


@router_reminder_admin.message(ReminderState.waiting_for_text)
async def process_text(message: types.Message, state: FSMContext):
    """Обработка текста и создание напоминания"""
    if not message.text or len(message.text.strip()) == 0:
        await message.answer("❌ Текст напоминания не может быть пустым.")
        return

    data = await state.get_data()
    target_id = data['target_user_id']
    target_username = data.get('target_username')
    send_datetime = data['send_time']
    text = message.text.strip()

    try:
        # Получаем ID создателя из БД
        creator_db_id = None
        async with get_session() as session:
            result = await session.execute(
                select(User).where(User.user_id == message.from_user.id)
            )
            user = result.scalar_one_or_none()
            if user:
                creator_db_id = user.id

        # Создаем напоминание через сервис

        service = get_reminder_service() 

        reminder = await service.create_reminder(
            target_user_id=target_id,
            text=text,
            send_at=send_datetime,
            created_by_id=creator_db_id
        )

        await state.clear()
        
        await message.answer(
            "✅ **Напоминание успешно создано!**\n\n"
            f"👤 Получатель: `@{target_username}`\n"
            f"🆔 Telegram ID: `{target_id}`\n"
            f"⏰ Дата и время: `{send_datetime.strftime('%d.%m.%Y %H:%M')}`\n"
            f"📄 Текст: {text[:100]}{'...' if len(text) > 100 else ''}\n\n"
            f"🆔 ID напоминания: `{reminder.id}`"
        )
        
        logger.info(f"Reminder created: {reminder.id} for user {target_id} at {send_datetime}")
        
    except Exception as e:
        logger.error(f"Failed to create reminder: {e}")
        await message.answer(
            "❌ **Произошла ошибка при создании напоминания.**\n\n"
            "Попробуйте позже или обратитесь к разработчику."
        )
        await state.clear()


@router_reminder_admin.callback_query(F.data == "admin_reminders_list")
async def show_reminders_list(callback: types.CallbackQuery, page: int = 1):
    """Показать список активных напоминаний с пагинацией"""
    if not await is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return

    PER_PAGE = 10
    
    async with get_session() as session:
        #Считаем общее количество
        count_result = await session.execute(
            select(func.count(Reminder.id)).where(Reminder.status == 0)
        )
        total_count = count_result.scalar_one()
        
      
        result = await session.execute(
            select(Reminder)
            .where(Reminder.status == 0)
            .order_by(Reminder.send_at.asc())
            .offset((page - 1) * PER_PAGE)
            .limit(PER_PAGE)
        )
        reminders = result.scalars().all()
        
        
        creator_ids = [r.created_by for r in reminders if r.created_by]
        creators_map = {}
        if creator_ids:
            creators_result = await session.execute(
                select(User.id, User.username).where(User.id.in_(creator_ids))
            )
            for uid, uname in creators_result.all():
                creators_map[uid] = uname


    if not reminders:
        await callback.message.edit_text(
            "📭 Нет активных напоминаний\n\n"
            "Все запланированные напоминания уже отправлены.\n"
            "Создайте новое через меню администратора."
        )
        await callback.answer()
        return

    text = f"🔔 Активные напоминания (стр. {page})\n\n"
    keyboard = []  
    for i, reminder in enumerate(reminders, start=(page - 1) * PER_PAGE + 1):
        creator_name = creators_map.get(reminder.created_by) or "—"
        
        text += (
            f"{i}. 🆔 `{reminder.id}`\n"
            f"   👤 Получатель: `{reminder.target_user_id}`\n"
            f"   ⏰ {reminder.send_at.strftime('%d.%m.%Y %H:%M')}\n"
            f"   📝 {reminder.text[:50]}{'...' if len(reminder.text) > 50 else ''}\n"
            f"   👨‍💻 Создал: {creator_name}\n\n"
        )
        

        keyboard.append([
            types.InlineKeyboardButton(
                text=f"❌ Отменить {reminder.id[:8]}...",
                callback_data=f"admin_cancel_reminder_id_{reminder.id}"
            )
        ])


    total_pages = (total_count + PER_PAGE - 1) // PER_PAGE
    pagination_row = []
    
    if page > 1:
        pagination_row.append(types.InlineKeyboardButton(
            text="⬅️", 
            callback_data=f"admin_reminders_list_page_{page - 1}"
        ))
    
    pagination_row.append(types.InlineKeyboardButton(
        text=f"📄 {page}/{total_pages}", 
        callback_data="ignore"
    ))
    
    if page < total_pages:
        pagination_row.append(types.InlineKeyboardButton(
            text="➡️", 
            callback_data=f"admin_reminders_list_page_{page + 1}"
        ))
    
    keyboard.append(pagination_row)  # ← Добавляем ряд пагинации
    keyboard.append([types.InlineKeyboardButton(
        text="🔙 В меню", 
        callback_data="goto_back"
    )])
    
    reply_markup = types.InlineKeyboardMarkup(inline_keyboard=keyboard)

    await callback.message.edit_text(
        text, 
        reply_markup=reply_markup,
        parse_mode="HTML"
    )
    await callback.answer()


@router_reminder_admin.callback_query(F.data == "admin_cancel_reminder")
async def cancel_reminder_flow(callback: types.CallbackQuery, state: FSMContext):
    """Отмена процесса создания напоминания"""
    await state.clear()
    await callback.message.edit_text("❌ Создание напоминания отменено.")
    await callback.answer()


@router_reminder_admin.callback_query(F.data.regexp(r"^admin_cancel_reminder_id_(.+)$"))
async def cancel_specific_reminder(callback: types.CallbackQuery):
    """
    Отмена конкретного напоминания по ID.
    callback_data формат: admin_cancel_reminder_id_{reminder_id}
    """

    if not await is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return

    try:
        reminder_id = callback.data.split("_")[-1]
        logger.debug(f"🗑️ Attempting to cancel reminder: {reminder_id}")
    except (IndexError, ValueError) as e:
        logger.error(f"❌ Failed to parse reminder_id from {callback.data}: {e}")
        await callback.answer("⚠️ Ошибка обработки запроса", show_alert=True)
        return

    async with get_session() as session:
        result = await session.execute(
            select(Reminder).where(
                Reminder.id == reminder_id,
                Reminder.status == 0  
            )
        )
        reminder = result.scalar_one_or_none()
        
        if not reminder:
            await callback.answer("⚠️ Напоминание не найдено или уже обработано", show_alert=True)
            await show_reminders_list(callback, page=1)
            return
        
        reminder.status = 2
        await session.commit()
        logger.info(f"✅ Reminder {reminder_id} marked as cancelled in DB")


    try:
        service = get_reminder_service()
        job_id = f"reminder_{reminder_id}"
        
        if service.scheduler.get_job(job_id):
            service.scheduler.remove_job(job_id)
            logger.debug(f"🗑️ Removed job {job_id} from APScheduler")
        else:
            logger.debug(f"⚠️ Job {job_id} not found in scheduler (maybe already executed?)")
    except Exception as e:
        logger.error(f"❌ Failed to remove job from scheduler: {e}")
       

    await callback.answer("✅ Напоминание отменено", show_alert=True)
    
    await show_reminders_list(callback, page=1)


@router_reminder_admin.callback_query(F.data == "admin_cancel_all_reminders")
async def cancel_all_reminders(callback: types.CallbackQuery):
    """Отмена всех активных напоминаний (с подтверждением)"""
    if not await is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return

    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(
                text="✅ Да, отменить все",
                callback_data="admin_cancel_all_reminders_confirm"
            ),
            types.InlineKeyboardButton(
                text="❌ Нет",
                callback_data="admin_reminders_list"
            )
        ]
    ])
    
    await callback.message.edit_text(
        "⚠️ Подтвердите действие\n\n"
        "Вы действительно хотите отменить **все активные напоминания**?\n"
        "Это действие нельзя отменить.",
        reply_markup=keyboard
    )
    await callback.answer()


@router_reminder_admin.callback_query(F.data == "admin_cancel_all_reminders_confirm")
async def confirm_cancel_all_reminders(callback: types.CallbackQuery):
    """Фактическая отмена всех напоминаний"""
    if not await is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return

    cancelled_count = 0
    service = get_reminder_service()
    
    async with get_session() as session:
        result = await session.execute(
            select(Reminder).where(Reminder.status == 0)
        )
        reminders = result.scalars().all()
        
        for reminder in reminders:
            reminder.status = 2  
            job_id = f"reminder_{reminder.id}"
            if service.scheduler.get_job(job_id):
                service.scheduler.remove_job(job_id)
            cancelled_count += 1
        
        await session.commit()
    
    await callback.answer(f"✅ Отменено напоминаний: {cancelled_count}", show_alert=True)
    await callback.message.edit_text(
        f"🗑️ Готово!\n\n"
        f"Отменено напоминаний: **{cancelled_count}**\n"
        "Все задачи удалены из планировщика."
    )
