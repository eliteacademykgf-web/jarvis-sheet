"""
config.py — переменные окружения jarvis-sheet.

Только AmoCRM: без Telegram, Meta и Google Sheets.
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
