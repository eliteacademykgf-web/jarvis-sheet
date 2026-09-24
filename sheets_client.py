"""
sheets_client.py — запись сырых данных в Google Sheets.

Работает только со своими листами (meta_daily, crm_daily): создаёт их,
если нет, и пишет в них. Существующие листы таблицы никогда не удаляет,
не переименовывает и не меняет.

Авторизация — сервисный аккаунт, JSON-ключ по пути
GOOGLE_SERVICE_ACCOUNT_JSON (файл лежит вне репозитория).
"""

from contextlib import contextmanager
from http import HTTPStatus
from typing import List, Optional, Tuple

import gspread
from gspread.utils import ValueInputOption, rowcol_to_a1
from google.oauth2.service_account import Credentials

from config import GOOGLE_SERVICE_ACCOUNT_JSON, SPREADSHEET_ID

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


class SheetsAccessError(RuntimeError):
    """Сервисный аккаунт не видит таблицу или не может в неё писать."""


@contextmanager
def _access_errors():
    """
    404 / 403 от Google (SpreadsheetNotFound, PermissionError, APIError) ->
    SheetsAccessError с понятным текстом; исходная ошибка в __cause__.
    Остальные APIError (429, 5xx) пробрасываются как есть.
    """
    msg = (f"Нет доступа к таблице {SPREADSHEET_ID} — проверь, что сервисный "
           f"аккаунт добавлен как редактор")
    try:
        yield
    except (gspread.SpreadsheetNotFound, PermissionError) as e:
        raise SheetsAccessError(msg) from e
    except gspread.exceptions.APIError as e:
        if e.response.status_code in (HTTPStatus.FORBIDDEN, HTTPStatus.NOT_FOUND):
            raise SheetsAccessError(f"{msg} (Google: {e})") from e
        raise


META_SHEET = "meta_daily"
META_HEADERS = ["date", "ad_id", "ad_name", "campaign_name", "adset_name",
                "spend", "impressions", "clicks", "ctr", "cpm",
                "dm_leads", "site_leads"]

CRM_SHEET = "crm_daily"
CRM_HEADERS = ["date", "new_request", "lead", "qualified", "consult_scheduled",
               "consult_done", "sale", "revenue", "note"]


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


def open_spreadsheet(client: Optional[gspread.Client] = None) -> gspread.Spreadsheet:
    """Таблица SPREADSHEET_ID."""
    if not SPREADSHEET_ID:
        raise RuntimeError("Нужен SPREADSHEET_ID в .env или окружении")
    client = client or get_client()
    with _access_errors():
        return client.open_by_key(SPREADSHEET_ID)


# ============================================================
# UPSERT
# ============================================================
def _cell(value):
    return "" if value is None else value


def _upsert(ws: gspread.Worksheet, headers: List[str], key_fields: List[str],
            rows: List[dict]) -> Tuple[int, int]:
    """
    Upsert rows на лист ws по ключу key_fields. Возвращает (добавлено, обновлено).

    Запросы: одно чтение листа и один batch_update на все строки (плюс
    add_rows, если в сетке листа не хватает строк). Пишем RAW: date и
    ad_id остаются текстом, иначе Sheets превратит дату в число по локали,
    а 18-значный ad_id округлит до 1.2E+17, и ключи перестанут совпадать.
    """
    values = ws.get_all_values()
    if not values or values[0][:len(headers)] != headers:
        raise RuntimeError(
            f"Лист «{ws.title}»: первая строка не совпадает с {headers}. "
            f"Не пишу, чтобы не испортить данные на листе")

    key_idx = [headers.index(k) for k in key_fields]
    existing = {}
    for n, r in enumerate(values[1:], start=2):
        r = r + [""] * (len(headers) - len(r))
        existing.setdefault(tuple(r[i] for i in key_idx), n)

    last_col = rowcol_to_a1(1, len(headers)).rstrip("0123456789")
    to_update, to_insert = {}, {}   # key -> значения; повтор ключа во входе: последний wins
    for row in rows:
        key = tuple(str(_cell(row.get(k))) for k in key_fields)
        vals = [_cell(row.get(h)) for h in headers]
        (to_update if key in existing else to_insert)[key] = vals

    data = [{"range": f"A{existing[k]}:{last_col}{existing[k]}", "values": [v]}
            for k, v in to_update.items()]
    next_row = len(values) + 1
    if to_insert:
        end_row = next_row + len(to_insert) - 1
        if end_row > ws.row_count:
            ws.add_rows(end_row - ws.row_count)
        data.append({"range": f"A{next_row}:{last_col}{end_row}",
                     "values": list(to_insert.values())})
    if data:
        ws.batch_update(data, value_input_option=ValueInputOption.raw)
    return len(to_insert), len(to_update)


def write_meta_rows(rows: List[dict],
                    spreadsheet: Optional[gspread.Spreadsheet] = None) -> Tuple[int, int]:
    """Upsert строк Meta на лист meta_daily по (date, ad_id). -> (добавлено, обновлено)"""
    spreadsheet = spreadsheet or open_spreadsheet()
    with _access_errors():
        ws = get_or_create_worksheet(spreadsheet, META_SHEET, META_HEADERS)
        return _upsert(ws, META_HEADERS, ["date", "ad_id"], rows)


def write_crm_row(row: dict,
                  spreadsheet: Optional[gspread.Spreadsheet] = None) -> Tuple[int, int]:
    """Upsert строки CRM на лист crm_daily по date. -> (добавлено, обновлено)"""
    spreadsheet = spreadsheet or open_spreadsheet()
    with _access_errors():
        ws = get_or_create_worksheet(spreadsheet, CRM_SHEET, CRM_HEADERS)
        return _upsert(ws, CRM_HEADERS, ["date"], [row])
