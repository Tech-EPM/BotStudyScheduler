import logging
import uuid
from pathlib import Path
import aiofiles  

BASE_DIR = Path(__file__).resolve().parent.parent.parent
FILES_DIR = BASE_DIR / "storage" / "files"
ALLOWED_EXTENSIONS = {
    # Документы
    'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
    'txt', 'rtf', 'odt', 'ods', 'odp', 'csv',
    # Изображения
    'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg',
    # Архивы
    'zip', 'rar', '7z', 'tar', 'gz', 'bz2',
    # Код
    'py', 'js', 'java', 'cpp', 'c', 'h', 'hpp', 'cs', 'go', 'rs',
    'sql', 'sh', 'bash', 'ps1', 'md', 'json', 'xml', 'yaml', 'yml',
}


def allowed_file(filename: str) -> bool:
    """
    Проверка расширения файла (регистронезависимая).
    Возвращает True, если расширение в ALLOWED_EXTENSIONS.
    """
    if not filename or '.' not in filename:
        return False
    
    # Получаем расширение и приводим к нижнему регистру
    ext = filename.rsplit('.', 1)[1].lower()
    return ext in ALLOWED_EXTENSIONS


def get_file_extension(filename: str) -> str:
    """Получить расширение файла в нижнем регистре"""
    if not filename or '.' not in filename:
        return ''
    return filename.rsplit('.', 1)[1].lower()


async def save_file(file_bytes: bytes, original_filename: str, category: str) -> str:
    """Асинхронное сохранение через aiofiles"""
    ext = get_file_extension(original_filename)
    unique_name = f"{uuid.uuid4().hex}.{ext}"
    
    category_dir = FILES_DIR / category
    category_dir.mkdir(parents=True, exist_ok=True)  # mkdir синхронный, но быстрый
    
    file_path = category_dir / unique_name
    
    # Асинхронная запись!
    async with aiofiles.open(file_path, "wb") as f:
        await f.write(file_bytes)
    
    return str(file_path.relative_to(BASE_DIR))


async def save_session_file(file_bytes: bytes, original_filename: str, category: str) -> str:
    SESSION_FILES_DIR = BASE_DIR / "storage" / "session_files"
    ext = get_file_extension(original_filename)
    unique_name = f"{uuid.uuid4().hex}.{ext}"
    
    category_dir = SESSION_FILES_DIR / category
    category_dir.mkdir(parents=True, exist_ok=True)
    
    file_path = category_dir / unique_name
    async with aiofiles.open(file_path, "wb") as f:
        await f.write(file_bytes)
    
    return str(file_path.relative_to(BASE_DIR))


def get_file_full_path(relative_path: str) -> Path:
    return BASE_DIR / relative_path


async def delete_file_async(relative_path: str) -> bool:
    """Асинхронное удаление — используйте в async-коде"""
    try:
        file_path = BASE_DIR / relative_path
        if file_path.exists():
            file_path.unlink()
            category_dir = file_path.parent
            if not any(category_dir.iterdir()):
                category_dir.rmdir()
            return True
    except Exception as e:
        logging.error(f"Delete error: {e}")
    return False


def delete_file(relative_path: str) -> bool:
    """Синхронное удаление — ТОЛЬКО для sync-кода!"""
    try:
        file_path = BASE_DIR / relative_path
        if file_path.exists():
            file_path.unlink()
            category_dir = file_path.parent
            if not any(category_dir.iterdir()):
                category_dir.rmdir()
            return True
    except Exception:
        pass
    return False