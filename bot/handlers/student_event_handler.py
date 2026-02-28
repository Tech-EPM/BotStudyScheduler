import logging
from datetime import datetime
from aiogram import Router, F, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.db.models import Event
from bot.utils.keyboards import Keyboards

logger = logging.getLogger(__name__)
router_student_events = Router()


# ==========================================
# 1. ПРОСМОТР СОБЫТИЙ ИЗ ГЛАВНОГО МЕНЮ
# ==========================================

@router_student_events.message(F.text == "✨ События")
async def show_events_from_menu(message: types.Message, session: AsyncSession):
    """Студент нажал кнопку '📅 Афиша событий' в главном меню"""
    logger.info(f"🔍 User {message.from_user.id} opened events list")
    
    # Получаем все будущие события (или все, если хочешь показывать и прошлые)
    stmt = select(Event).where(Event.event_date >= datetime.now()).order_by(Event.event_date.asc()).limit(20)
    result = await session.execute(stmt)
    events = result.scalars().all()
    
    if not events:
        await message.answer(
            "📭 <b>Пока нет запланированных событий</b>\n\n"
            "Заходите позже — мы обязательно что-нибудь придумаем! 😊",
            reply_markup=Keyboards.get_student_menu(),
            parse_mode="HTML"
        )
        return
    
    # Формируем список событий
    event_list = []
    for i, e in enumerate(events[:10], 1):
        # Вычисляем сколько дней осталось
        days_left = (e.event_date - datetime.now()).days
        
        if days_left == 0:
            time_marker = "🔥 СЕГОДНЯ!"
        elif days_left == 1:
            time_marker = "⏰ ЗАВТРА!"
        elif days_left <= 7:
            time_marker = f"🗓️ Через {days_left} дн."
        else:
            time_marker = f"📅 {e.event_date.strftime('%d.%m.%Y')}"
        
        event_text = (
            f"{i}. <b>{e.title}</b>\n"
            f"   {time_marker} в <code>{e.event_date.strftime('%H:%M')}</code>\n"
        )
        
        if e.description:
            # Обрезаем описание, если слишком длинное
            desc = e.description[:100] + "..." if len(e.description) > 100 else e.description
            event_text += f"   <i>{desc}</i>\n"
        
        event_list.append(event_text)
    
    await message.answer(
        "📅 <b>Афиша ближайших событий</b>\n\n" +
        "\n".join(event_list) +
        f"\n<i>Всего событий: {len(events)}</i>",
        reply_markup=Keyboards.get_student_menu(),
        parse_mode="HTML"
    )


# ==========================================
# 2. ПРОСМОТР СОБЫТИЙ ЧЕРЕЗ INLINE (опционально)
# ==========================================

@router_student_events.callback_query(F.data == "view_student_events")
async def show_events_inline(callback: types.CallbackQuery, session: AsyncSession):
    """Показ событий через inline-кнопку (если нужно)"""
    
    stmt = select(Event).where(Event.event_date >= datetime.now()).order_by(Event.event_date.asc()).limit(20)
    result = await session.execute(stmt)
    events = result.scalars().all()
    
    if not events:
        await callback.answer("📭 Пока нет событий", show_alert=True)
        return
    
    event_list = "\n".join([
        f"📅 <b>{e.title}</b>\n"
        f"   🕒 {e.event_date.strftime('%d.%m.%Y %H:%M')}"
        for e in events[:10]
    ])
    
    await callback.message.edit_text(
        f"📅 <b>Афиша событий</b>\n\n{event_list}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 В меню", callback_data="get_student_main_keyboard")]
        ]),
        parse_mode="HTML"
    )
    await callback.answer()