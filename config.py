"""
config.py — переменные окружения jarvis-sheet.

AmoCRM и Meta Marketing API, без Telegram и Google Sheets.
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
