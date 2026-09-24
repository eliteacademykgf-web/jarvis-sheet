"""
sheets_client.py — запись сырых данных в Google Sheets.

Работает только со своими листами (meta_daily, crm_daily): создаёт их,
если нет, и пишет в них. Существующие листы таблицы никогда не удаляет,
не переименовывает и не меняет.

Авторизация — сервисный аккаунт, JSON-ключ по пути
GOOGLE_SERVICE_ACCOUNT_JSON (файл лежит вне репозитория).
"""

from typing import List

import gspread
from google.oauth2.service_account import Credentials

from config import GOOGLE_SERVICE_ACCOUNT_JSON

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_client() -> gspread.Client:
    """
    Авторизованный gspread.Client от имени сервисного аккаунта.
    client.request_count — число HTTP-запросов к Google API через этого
    клиента (для контроля квоты).
    """
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        raise RuntimeError("Нужен GOOGLE_SERVICE_ACCOUNT_JSON в .env или окружении")
    creds = Credentials.from_service_account_file(GOOGLE_SERVICE_ACCOUNT_JSON, scopes=SCOPES)
    client = gspread.authorize(creds)

    client.request_count = 0

    def _count(response, *args, **kwargs):
        client.request_count += 1
    client.http_client.session.hooks["response"].append(_count)
    return client


def get_or_create_worksheet(spreadsheet: gspread.Spreadsheet, title: str,
                            headers: List[str]) -> gspread.Worksheet:
    """
    Лист с названием title. Если есть — возвращается как есть, без изменений.
    Если нет — создаётся и в первую строку пишутся headers.
    """
    try:
        return spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        pass
    ws = spreadsheet.add_worksheet(title=title, rows=1000, cols=len(headers))
    ws.update([headers], "A1", value_input_option="RAW")
    return ws
