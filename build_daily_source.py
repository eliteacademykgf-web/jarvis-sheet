"""
build_daily_source.py — плоские данные за день для записи в таблицу.

Два источника разного уровня детализации, намеренно НЕ склеены:
  build_meta_rows(date) -> list[dict]  по строке на объявление (Meta)
  build_crm_row(date)   -> dict        одна сводка CRM на весь день

CRM нельзя разнести по объявлениям: поле кодового слова в CRM не
заполняется. Склейка будет на уровне таблицы (Google Sheets).
"""

from datetime import date as date_cls

from config import META_TOKEN, AD_ACCOUNT_ID
from meta_client import get_daily_ad_stats
from metrics import compute_daily_metrics

# Не для формул: чтобы при экспорте/отладке было видно, почему цифра общая.
CRM_NOTE = "Разбивка по объявлениям недоступна: поле кодового слова в CRM не заполняется"


def build_meta_rows(date: date_cls) -> list:
    """
    Строки объявление × день из Meta (get_daily_ad_stats как есть).
    День — в часовом поясе рекламного аккаунта.
    """
    if not META_TOKEN or not AD_ACCOUNT_ID:
        raise RuntimeError("Нужны META_TOKEN и AD_ACCOUNT_ID в .env или окружении")
    return get_daily_ad_stats(AD_ACCOUNT_ID, date, META_TOKEN)


def build_crm_row(date: date_cls) -> dict:
    """
    Одна строка CRM-показателей за день (Бишкек) по всей воронке
    «Отдел продаж»: {date, new_request, lead, qualified,
    consult_scheduled, consult_done, sale, revenue, note}.
    note — пояснение происхождения цифр (CRM_NOTE).
    """
    return {
        "date": date.isoformat(),
        **compute_daily_metrics(date),
        "note": CRM_NOTE,
    }
