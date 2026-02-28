# bot/db/models.py
import uuid
from sqlalchemy import Column, Integer, String, DateTime, func, ForeignKey, BigInteger, event
from sqlalchemy.orm import relationship, declarative_base
from bot.db.database import Base
from bot.utils.file_storage import delete_file


# ==========================================
# 1. МОДЕЛЬ СЕССИИ (Учебная сессия)
# ==========================================
class Session(Base):
    __tablename__ = "sessions"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(100), nullable=True)
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    is_completed = Column(Integer, default=0)
    created_at = Column(DateTime, default=func.now())

    files = relationship("SessionFile", back_populates="session", cascade="all, delete-orphan")
    user = relationship("User", back_populates="sessions")

    def __repr__(self):
        return f"<Session(id={self.id}, user_id={self.user_id}, completed={self.is_completed})>"


# ==========================================
# 2. ПОЛЬЗОВАТЕЛЬ (Студент)
# ==========================================
class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, unique=True, nullable=False)  # Telegram ID
    username = Column(String, nullable=True)
    created_at = Column(DateTime, default=func.now())
    status = Column(String, nullable=True)
    
    uploaded_files = relationship("FileDocument", back_populates="uploader", lazy="select")
    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")

    # ❌ УДАЛИЛ: reminders_created (вызывал ошибку связи)

    def __init__(self, user_id: int, username: str, status: str):
        self.user_id = user_id
        self.username = username
        self.status = status

    def __repr__(self):
        return f"<User(telegram_id={self.user_id})>"


# ==========================================
# 3. ФАЙЛ СЕССИИ (Материалы к сессии)
# ==========================================
class SessionFile(Base):
    __tablename__ = "session_files"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True, index=True)
    original_filename = Column(String(255), nullable=False)
    stored_path = Column(String(500), nullable=False)
    file_size = Column(BigInteger, default=0)
    mime_type = Column(String(100), nullable=True)
    category = Column(String(50), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    session = relationship("Session", back_populates="files")

    def __repr__(self):
        return f"<SessionFile(id={self.id}, filename={self.original_filename})>"


# ==========================================
# 4. БАЗА ЗНАНИЙ (Общие файлы)
# ==========================================
class FileDocument(Base):
    __tablename__ = 'file_documents'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    file_name = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    file_extension = Column(String, nullable=False)
    category = Column(String, nullable=False, index=True)
    uploaded_by = Column(Integer, ForeignKey('users.id'), nullable=False)
    uploaded_at = Column(DateTime, default=func.now())
    file_size = Column(Integer, nullable=False)
    
    uploader = relationship("User", back_populates="uploaded_files")
    
    def __repr__(self):
        return f"<FileDocument(name={self.file_name}, category={self.category})>"


# ==========================================
# 5. ОСТАЛЬНЫЕ МОДЕЛИ
# ==========================================
class Schedule(Base):
    __tablename__ = 'schedule'
    id = Column(Integer, primary_key=True, autoincrement=True)
    day_of_week = Column(String, nullable=False)
    lesson_number = Column(Integer, nullable=False)
    subject = Column(String, nullable=False)
    time_start = Column(String, nullable=False)
    time_end = Column(String, nullable=False)
    classroom = Column(String, nullable=True)
    teacher = Column(String, nullable=True)


class Dispatchers(Base):
    __tablename__ = "dispatchers"
    id = Column(Integer, primary_key=True)
    username = Column(String, nullable=False, unique=True)
    
    def __init__(self, username: str):
        self.username = username


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    event_date = Column(DateTime, nullable=False)
    description = Column(String(1000), nullable=True)
    created_at = Column(DateTime, default=func.now())
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    def __repr__(self):
        return f"<Event(id={self.id}, title={self.title}, date={self.event_date})>"


# ==========================================
# 6. АВТО-УДАЛЕНИЕ ФАЙЛОВ (Хук)
# ==========================================
@event.listens_for(SessionFile, "before_delete")
def receive_before_delete(mapper, connection, target):
    """Удаляет физический файл с диска перед удалением записи из БД"""
    try:
        delete_file(target.stored_path)
    except Exception as e:
        print(f"Error deleting file {target.stored_path}: {e}")


# ==========================================
# 7. НАПОМИНАНИЯ (Исправленная модель)
# ==========================================
class Reminder(Base):
    __tablename__ = "reminders"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    target_user_id = Column(BigInteger, nullable=False, index=True)
    text = Column(String(1000), nullable=False)
    send_at = Column(DateTime, nullable=False, index=True)
    status = Column(Integer, default=0)  # 0=ожидает, 1=отправлено, 2=отменено
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)  # ✅ FK на users.id
    created_at = Column(DateTime, default=func.now())

    # ❌ УДАЛИЛ: creator relationship (вызывал ошибку)

    def __repr__(self):
        return f"<Reminder(id={self.id}, target={self.target_user_id}, time={self.send_at})>"