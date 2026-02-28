class Messages:
    WELCOME_MESSAGE = "Добро пожаловать!"

    ERROR_CREATE_USER = "Ошибка создания пользователя"
    ERROR_USER_NOT_FOUND = "Пользователь не найден."
    ERROR_WRONG_PHONE_NUMBER = "Неверный формат номера телефона. Попробуйте снова."
    ERROR_WRONG_DATA = "Неверные данные"

    BUTTON_AUTHORIZE = "Авторизоваться"
    BUTTON_SELECT = "Выбрать"
    BUTTON_OK = "ОК"
    BUTTON_CANCEL = "Отмена"

    UNKNOWN_COMMAND = "Извините, я не понимаю"

    @staticmethod
    def hello_message(NAME_CHANNEL = 'YOUR_CHANNEL'):
        text = (
            f"Добро пожаловать в {NAME_CHANNEL} предназначенный для учебы ."
        )
        return text