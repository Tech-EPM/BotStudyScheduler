from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup


DAYS = {
    "monday": "Понедельник",
    "tuesday": "Вторник",
    "wednesday": "Среда",
    "thursday": "Четверг",
    "friday": "Пятница",
    "saturday": "Суббота",
    "sunday": "Воскресенье",
}

SCHEDULE_DAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
)

class Keyboards:

    # ==========================================
    # ГЛАВНЫЕ МЕНЮ (ReplyKeyboard)
    # ==========================================

    @staticmethod
    def get_admin_menu() -> ReplyKeyboardMarkup:
        keyboard = [
            [KeyboardButton(text="👨‍🏫 Админ-панель"), KeyboardButton(text="📅 Расписание")],
            [
                KeyboardButton(text="📚 Учебные материалы"),
                KeyboardButton(text="🎓 Файлы сессий"),
                KeyboardButton(text="✨ События"),
            ],
            [KeyboardButton(text="🆘 Помощь")],
        ]
        return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

    @staticmethod
    def get_student_menu() -> ReplyKeyboardMarkup:
        keyboard = [
            [KeyboardButton(text="📅 Расписание")],
            [
                KeyboardButton(text="📚 Учебные материалы"),
                KeyboardButton(text="🎓 Файлы сессий"),
                KeyboardButton(text="✨ События"),  # ✅ NEW
            ],
            [KeyboardButton(text="🆘 Помощь")],
        ]
        return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

    # ==========================================
    # АДМИН-ПАНЕЛЬ (InlineKeyboard)
    # ==========================================

    @staticmethod
    def get_admin_main_keyboard() -> InlineKeyboardMarkup:
        keyboard = [
            [InlineKeyboardButton(text="⏰ Редактировать расписание", callback_data="admin_edit_schedule")],
            [InlineKeyboardButton(text="📚 Редактировать учебные материалы", callback_data="admin_edit_common_files")],
            [InlineKeyboardButton(text="📝 Редактировать материалы для сессии", callback_data="admin_edit_session_files")],
            [InlineKeyboardButton(text="⏳ Редактировать напоминания", callback_data="admin_edit_reminders")],
            [InlineKeyboardButton(text="✨ Редактировать события", callback_data="admin_edit_events")],
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def get_admin_schedule_keyboard() -> InlineKeyboardMarkup:
        keyboard = [
            [InlineKeyboardButton(text="➕ Добавить пару", callback_data="admin_add_select_week")],
            [InlineKeyboardButton(text="➖ Удалить пару", callback_data="admin_del_select_week")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="goto_back")],
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def get_admin_common_edit_files_keyboard() -> InlineKeyboardMarkup:
        keyboard = [
            [InlineKeyboardButton(text="➕ Добавить файлы", callback_data="admin_add_common_files")],
            [InlineKeyboardButton(text="➖ Удалить файлы", callback_data="admin_del_common_files")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="goto_back")],
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def get_admin_session_edit_files_keyboard() -> InlineKeyboardMarkup:
        keyboard = [
            [InlineKeyboardButton(text="➕ Добавить файлы", callback_data="admin_add_session_files")],
            [InlineKeyboardButton(text="➖ Удалить файлы", callback_data="admin_del_session_files")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="goto_back")],
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def get_admin_reminders_keyboard() -> InlineKeyboardMarkup:
        # ✅ FIX: Исправлены callback_data (были от файлов, теперь заглушки или свои)
        keyboard = [
            [InlineKeyboardButton(text="➕ Добавить напоминание", callback_data="admin_add_reminder")],
            [InlineKeyboardButton(text="📋 Редактировать напоминания", callback_data="admin_reminders_list")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="goto_back")],
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
    

    @staticmethod
    def get_admin_events_keyboard() -> InlineKeyboardMarkup:
        # ✅ FIX: Исправлены callback_data (были от файлов, теперь заглушки или свои)
        keyboard = [
            [InlineKeyboardButton(text="➕ Добавить событие", callback_data="admin_add_event")],
            [InlineKeyboardButton(text="➖ Удалить событие", callback_data="admin_del_event")],
            [InlineKeyboardButton(text="📋 Показать все события", callback_data="admin_view_events")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="goto_back")],
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    # ==========================================
    # ДНИ НЕДЕЛИ
    # ==========================================

    @staticmethod
    def get_admin_weeks_keyboard(
        weeks: list[str],
        action: str = "view",
        from_menu: str = "main",
        include_add_button: bool = False
    ) -> InlineKeyboardMarkup:
        keyboard = []
        for week_id in weeks:
            week_name = f"{week_id} неделя"
            if action == "add":
                cb_data = f"admin_add_week_{week_id}|{from_menu}"
            elif action == "del":
                cb_data = f"admin_del_week_{week_id}|{from_menu}"
            else:
                cb_data = f"week_{week_id}|{from_menu}"

            keyboard.append([InlineKeyboardButton(text=week_name, callback_data=cb_data)])

        if include_add_button and action == "add":
            keyboard.append([InlineKeyboardButton(text="➕ Другая неделя", callback_data="admin_add_custom_week")])

        keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="goto_back")])
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def get_admin_days_keyboard(
        action: str = "view",
        from_menu: str = "main",
        week_type: str = "1"
    ) -> InlineKeyboardMarkup:
        keyboard = []
        for day_id in SCHEDULE_DAYS:
            day_name = DAYS[day_id]
            if action == "view":
                cb_data = f"day_{day_id}|{from_menu}|{week_type}"
            elif action == "add":
                cb_data = f"add_{day_id}|{from_menu}|{week_type}"
            elif action == "del":
                cb_data = f"del_{day_id}|{from_menu}|{week_type}"
            else:
                cb_data = f"day_{day_id}|{from_menu}|{week_type}"
            
            keyboard.append([InlineKeyboardButton(text=day_name, callback_data=cb_data)])
        
        keyboard.append([InlineKeyboardButton(text="📆 Выбрать неделю", callback_data=f"admin_back_to_weeks_{from_menu}")])
        keyboard.append([InlineKeyboardButton(text="🔙 Отмена", callback_data="goto_back")])
        return InlineKeyboardMarkup(inline_keyboard=keyboard)


    @staticmethod
    def get_student_main_keyboard() -> InlineKeyboardMarkup:
        keyboard = [
            [InlineKeyboardButton(text="⏰ Смотреть расписание", callback_data="admin_edit_schedule")],
            [InlineKeyboardButton(text="📚 Смотреть общие материалы", callback_data="admin_edit_common_files")],
            [InlineKeyboardButton(text="📝 Смотреть материалы для сессии", callback_data="admin_edit_session_files")],
            [InlineKeyboardButton(text="⏳ Смотреть напоминания", callback_data="admin_edit_reminders")],
            [InlineKeyboardButton(text="✨ Смотреть события", callback_data="admin_edit_events")],
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)


    @staticmethod
    def get_student_weeks_keyboard(weeks: list[str], from_menu: str = "main") -> InlineKeyboardMarkup:
        keyboard = [
            [InlineKeyboardButton(text=f"{week_id} неделя", callback_data=f"week_{week_id}|{from_menu}")]
            for week_id in weeks
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def get_student_days_keyboard(
        action: str = "view",
        from_menu: str = "main",
        week_type: str = "1"
    ) -> InlineKeyboardMarkup:
        keyboard = []
        for day_id in SCHEDULE_DAYS:
            day_name = DAYS[day_id]
            if action == "view":
                cb_data = f"day_{day_id}|{from_menu}|{week_type}"
            elif action == "add":
                cb_data = f"add_{day_id}|{from_menu}|{week_type}"
            elif action == "del":
                cb_data = f"del_{day_id}|{from_menu}|{week_type}"
            else:
                cb_data = f"day_{day_id}|{from_menu}|{week_type}"
            
            keyboard.append([InlineKeyboardButton(text=day_name, callback_data=cb_data)])
        keyboard.append([InlineKeyboardButton(text="📆 Выбрать неделю", callback_data=f"back_to_weeks_{from_menu}")])
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    # ==========================================
    # КАТЕГОРИИ ФАЙЛОВ (Загрузка)
    # ==========================================

    @staticmethod
    def get_file_categories() -> InlineKeyboardMarkup:
        """Клавиатура с категориями для ОБЩИХ файлов (База знаний)"""
        keyboard = [
            [
                InlineKeyboardButton(text="📐 Математика", callback_data="category_math"),
                InlineKeyboardButton(text="💻 Программирование", callback_data="category_programming"),
            ],
            [
                InlineKeyboardButton(text="⚛️ Физика", callback_data="category_physics"),
                InlineKeyboardButton(text="📦 Другое", callback_data="category_other"),
            ],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_upload")],
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def get_session_file_categories() -> InlineKeyboardMarkup:
        """Клавиатура с подкатегориями для ФАЙЛОВ СЕССИИ"""
        keyboard = [
            [
                InlineKeyboardButton(text="🎫 Билеты", callback_data="category_tickets"),
                InlineKeyboardButton(text="📝 Ответы", callback_data="category_answers"),
            ],
            [
                InlineKeyboardButton(text="📚 Методички", callback_data="category_materials"),
                InlineKeyboardButton(text="📦 Другое", callback_data="category_other"),
            ],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_upload")],
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    # ==========================================
    # ПРОСМОТР ФАЙЛОВ (Студент)
    # ==========================================

    @staticmethod
    def get_categories_keyboard(categories: list[str], prefix: str = "files_in_") -> InlineKeyboardMarkup:
        """
        Универсальная клавиатура категорий.
        :param categories: список названий категорий
        :param prefix: префикс для callback_data
                       - "files_in_" для обычных файлов
                       - "session_files_in_" для файлов сессий
        """
        keyboard = []
        for cat in categories:
            keyboard.append([
                InlineKeyboardButton(text=f"📁 {cat}", callback_data=f"{prefix}{cat}")
            ])
        # keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="get_student_main_keyboard")])
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def get_session_categories_view() -> InlineKeyboardMarkup:
        """Готовая клавиатура с предустановленными категориями для просмотра файлов сессий"""
        categories = [
            ("🎫 Билеты", "tickets"),
            ("📝 Ответы", "answers"),
            ("📚 Методички", "materials"),
            ("📦 Другое", "other"),
        ]
        keyboard = [
            [InlineKeyboardButton(text=name, callback_data=f"session_files_in_{cat}")]
            for name, cat in categories
        ]
        keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="get_student_main_keyboard")])
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    # ==========================================
    # НАВИГАЦИЯ
    # ==========================================

    @staticmethod
    def get_files_back_keyboard(return_to: str = "view_files") -> InlineKeyboardMarkup:
        """Кнопка возврата к списку категорий"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 К категориям", callback_data=return_to)]
        ])

    @staticmethod
    def get_student_main_navigation() -> InlineKeyboardMarkup:
        """Навигация в главном меню студента (для inline-режима)"""
        keyboard = [
            [
                InlineKeyboardButton(text="📚 Учебные материалы", callback_data="view_common_files"),
                InlineKeyboardButton(text="🎓 Файлы сессий", callback_data="view_session_files"),
            ],
            [InlineKeyboardButton(text="📅 Расписание", callback_data="view_schedule")],
            [InlineKeyboardButton(text="🆘 Помощь", callback_data="show_help")],
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
