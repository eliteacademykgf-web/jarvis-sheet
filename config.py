"""
config.py — переменные окружения jarvis-sheet.

AmoCRM, Meta Marketing API, Google Sheets и (необязательно) бот для
уведомлений о сбоях.
Локально значения можно положить в .env рядом со скриптом (см. .env.example).
"""

import os

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

AMO_DOMAIN = os.environ.get("AMO_DOMAIN", "")
AMO_TOKEN  = os.environ.get("AMO_TOKEN", "")   # долгосрочный токен AmoCRM

META_TOKEN    = os.environ.get("META_TOKEN", "")      # токен Meta Marketing API
AD_ACCOUNT_ID = os.environ.get("AD_ACCOUNT_ID", "")   # id рекламного аккаунта (с act_ или без)

SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "")   # id Google-таблицы (из URL)
# Путь к JSON-ключу сервисного аккаунта (файл держать ВНЕ репозитория)
# или содержимое ключа целиком — так на Railway.
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")

# Уведомления о сбоях часового запуска (необязательно).
# ALERT_CHAT_IDS — chat_id через запятую; каждый получатель должен
# сначала написать боту /start, иначе Telegram не даст ему писать.
ALERT_BOT_TOKEN = os.environ.get("ALERT_BOT_TOKEN", "")
ALERT_CHAT_IDS  = [c.strip() for c in os.environ.get("ALERT_CHAT_IDS", "").split(",")
                   if c.strip()]
