from aiogram.filters import BaseFilter
from aiogram.types import Message
from sqlalchemy import select
from bot.db.database import async_session_maker
from bot.db.models import User


class IsAdmin(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        user_id = message.from_user.id
        async with async_session_maker() as session:
            result = await session.execute(select(User).where(User.user_id == user_id))
            user = result.scalar_one_or_none()
            return user.status == "admin" if user else False

class IsStudent(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        user_id = message.from_user.id
        async with async_session_maker() as session:
            result = await session.execute(select(User).where(User.user_id == user_id))
            user = result.scalar_one_or_none()
            return user.status == "student" if user else False