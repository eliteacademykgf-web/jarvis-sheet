"""
build_daily_source.py — плоские данные за день для записи в таблицу.

Источники разного уровня детализации, намеренно НЕ склеены:
  build_meta_rows(date) -> list[dict]      по строке на объявление (Meta)
  build_crm(date)       -> (dict, list)    сводка CRM на день и она же
                                           по кодовым словам

CRM связывается с объявлениями только через кодовое слово (поле контакта
в AmoCRM, объявления — через лист ads_manual). Склейка — на уровне
листа месяца (sheet_builder).
"""

from datetime import date as date_cls

from config import META_TOKEN, AD_ACCOUNT_ID
from meta_client import get_account_today, get_daily_ad_stats
from metrics import compute_daily_breakdown


def build_meta_rows(date: date_cls) -> list:
    """
    Строки объявление × день из Meta (get_daily_ad_stats как есть).
    День — в часовом поясе рекламного аккаунта. День, который для аккаунта
    ещё не начался (ночью по Бишкеку), даёт пустой список без запроса insights.
    """
    if not META_TOKEN or not AD_ACCOUNT_ID:
        raise RuntimeError("Нужны META_TOKEN и AD_ACCOUNT_ID в .env или окружении")
    if date > get_account_today(AD_ACCOUNT_ID, META_TOKEN):
        return []
    return get_daily_ad_stats(AD_ACCOUNT_ID, date, META_TOKEN)


def _note(total: dict, by_code: dict) -> str:
    """Сколько заявок дня с кодовым словом — видно, заполняют ли поле в CRM."""
    with_word = total["new_request"] - by_code.get("", {}).get("new_request", 0)
    return f"С кодовым словом: {with_word} из {total['new_request']} заявок"


def build_crm(date: date_cls) -> tuple:
    """
    CRM за день (Бишкек), воронка «Отдел продаж»:
      crm_row   — {date, new_request, lead, qualified, consult_scheduled,
                   consult_done, sale, revenue, note}
      code_rows — те же показатели по кодовым словам:
                  [{date, code_key, code_word, new_request, …}],
                  code_key "" — заявки без кодового слова.
    """
    total, by_code = compute_daily_breakdown(date)
    day = date.isoformat()
    crm_row = {"date": day, **total, "note": _note(total, by_code)}
    code_rows = [{"date": day, "code_key": key, **m} for key, m in sorted(by_code.items())]
    return crm_row, code_rows


def build_crm_row(date: date_cls) -> dict:
    """Только сводка CRM за день (для verify.py)."""
    return build_crm(date)[0]
