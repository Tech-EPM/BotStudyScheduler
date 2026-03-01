import json
import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Загрузка переменных окружения
if os.path.exists(os.path.join(BASE_DIR, '.env.local')):
    load_dotenv(os.path.join(BASE_DIR, '.env.local'))
else:
    load_dotenv(os.path.join(BASE_DIR, '.env'))


class Config:
    TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
    DB_URL = f"sqlite+aiosqlite:///{BASE_DIR}/bot/db/{os.getenv('DB_NAME')}"
    ADMIN_IDS = json.loads(os.getenv('ADMIN_IDS', '[]'))
    LOG_ROTATE_DAYS = int(os.getenv('LOG_ROTATE_DAYS', 15))
    DEBUG = os.getenv('DEBUG', 'False').lower() in ('true', '1', 'yes', 'on')

    PROVIDER_TOKEN = os.getenv('PROVIDER_TOKEN') 


    GOOGLE_CREDENTIALS_FILE = os.getenv('GOOGLE_CREDENTIALS_FILE')
    SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')

    CHANNEL_ID = os.getenv('CHANNEL_ID')
    LINK_CHANNEL = os.getenv('LINK_CHANNEL')

    LINK_BOT = os.getenv('LINK_BOT')

    # GROUP_ID = os.getenv("GROUP_ID")