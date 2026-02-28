import importlib
import os

from aiogram import Router
from .start_handlers import router_start
from .admin_handlers import router_admin
from .student_handlers import router_student
from .admin_files_handlers import router_files_admin
from .student_files_handlers import router_files_student
from .admin_session_files_handlers import router_session_files_admin
from .student_session_files_handlers import router_session_files_student
from .admin_event_handler import router_admin_events
from .student_event_handler import router_student_events 
from .admin_reminders import router_reminder_admin


routes = [
    router_start,
    router_admin,
    router_student,
    router_files_admin,
    router_files_student,
    router_session_files_admin,
    router_session_files_student,
    router_admin_events,
    router_student_events,
    router_reminder_admin
]


def setup_handlers(dp: Router):
    handlers_dir = os.path.dirname(__file__)
    for file in os.listdir(handlers_dir):
        if file.endswith("_handler.py") or file.endswith("_handlers.py"):
            module_name = file[:-3] 
            try:
                module = importlib.import_module(f"bot.handlers.{module_name}")
                if hasattr(module, "register_handlers"):
                    module.register_handlers(dp)
            except Exception as e:
                print(f"[ERROR] Не удалось загрузить {module_name}: {e}")
                