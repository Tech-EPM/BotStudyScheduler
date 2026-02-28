from aiogram.fsm.state import StatesGroup, State

class RequestState(StatesGroup):
    email = State()
    number = State()

class SignUp(StatesGroup):
    get_name = State()
    get_surname = State()
    get_email = State()
    get_number = State()

class AdminState(StatesGroup):
    admin = State()
    wait_username_add = State()
    wait_username_del = State()


class ScheduleAdd(StatesGroup):
    lesson_number = State()
    subject = State()
    time_start = State()
    time_end = State()
    classroom = State()
    teacher = State()


class FileUpload(StatesGroup):
    waiting_for_category = State()
    waiting_for_file = State()
    waiting_for_filename = State()


class SessionFileUpload(StatesGroup):
    waiting_for_category = State()
    waiting_for_file = State()  # ← Это ДРУГОЕ состояние, несмотря на одинаковое имя!
    waiting_for_filename = State()


class EventCreation(StatesGroup):
    waiting_for_title = State()       # Ввод названия
    waiting_for_date = State()        # Ввод даты
    waiting_for_description = State() # Ввод описания (опционально)


class ReminderState(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_date = State()      
    waiting_for_time = State()
    waiting_for_text = State()