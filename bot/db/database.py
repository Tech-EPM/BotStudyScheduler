from sqlalchemy import event, inspect, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from bot.config import Config

Base = declarative_base()


def get_db_url():
    # Если используется sqlite
    return Config.DB_URL

def get_base():
    return Base

# Создание движка и фабрики сессий
engine = create_async_engine(
    url=get_db_url(),
    echo=Config.DEBUG == False,  # Включает логирование SQL-запросов (для отладки)
    pool_pre_ping=True  # Проверяет соединение перед использованием
)



async_session_maker = async_sessionmaker(
    engine, 
    class_=AsyncSession,  # Используем класс по умолчанию
    expire_on_commit=False, 
    autoflush=False,
    autocommit=False
)


# Настройка колляции NOCASE при подключении к базе данных
@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """
    Настройка подключения к SQLite.
    """
    # Устанавливаем необходимые PRAGMA
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA encoding = 'UTF-8';")
    cursor.execute("PRAGMA case_sensitive_like = OFF;")  # Для регистронезависимого LIKE
    cursor.close()


async def init_db():
    """Создает таблицы в БД"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_schedule_week_type_column)
        await conn.run_sync(_ensure_file_documents_subject_column)
        await conn.run_sync(_ensure_session_files_extra_columns)
        await conn.run_sync(_ensure_schedule_week_id_column)
        await conn.run_sync(_ensure_seminar_due_date_column)
        await conn.run_sync(_ensure_dean_office_entry_extra_columns)


def _ensure_schedule_week_type_column(sync_conn):
    """Добавляет week_type в таблицу schedule для старых БД без миграций."""
    inspector = inspect(sync_conn)
    if "schedule" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("schedule")}
    if "week_type" in columns:
        return

    sync_conn.execute(
        text("ALTER TABLE schedule ADD COLUMN week_type VARCHAR NOT NULL DEFAULT '1'")
    )


def _ensure_file_documents_subject_column(sync_conn):
    inspector = inspect(sync_conn)
    if "file_documents" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("file_documents")}
    if "subject" not in columns:
        sync_conn.execute(
            text("ALTER TABLE file_documents ADD COLUMN subject VARCHAR(120)")
        )


def _ensure_session_files_extra_columns(sync_conn):
    inspector = inspect(sync_conn)
    if "session_files" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("session_files")}
    if "session_group" not in columns:
        sync_conn.execute(
            text("ALTER TABLE session_files ADD COLUMN session_group VARCHAR(120)")
        )
    if "subject" not in columns:
        sync_conn.execute(
            text("ALTER TABLE session_files ADD COLUMN subject VARCHAR(120)")
        )


def _ensure_schedule_week_id_column(sync_conn):
    inspector = inspect(sync_conn)
    if "schedule" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("schedule")}
    if "week_id" not in columns:
        sync_conn.execute(
            text("ALTER TABLE schedule ADD COLUMN week_id INTEGER")
        )


def _ensure_seminar_due_date_column(sync_conn):
    inspector = inspect(sync_conn)
    if "seminar_tasks" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("seminar_tasks")}
    if "due_date" not in columns:
        sync_conn.execute(
            text("ALTER TABLE seminar_tasks ADD COLUMN due_date DATE")
        )


def _ensure_dean_office_entry_extra_columns(sync_conn):
    inspector = inspect(sync_conn)
    if "dean_office_entries" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("dean_office_entries")}
    if "title" not in columns:
        sync_conn.execute(
            text("ALTER TABLE dean_office_entries ADD COLUMN title VARCHAR(255) NOT NULL DEFAULT 'Без названия'")
        )
    if "file_name" not in columns:
        sync_conn.execute(
            text("ALTER TABLE dean_office_entries ADD COLUMN file_name VARCHAR(255)")
        )
    if "file_path" not in columns:
        sync_conn.execute(
            text("ALTER TABLE dean_office_entries ADD COLUMN file_path VARCHAR(500)")
        )

def get_session():
    """Генератор сессий (если понадобится для зависимостей)"""
    return async_session_maker()
