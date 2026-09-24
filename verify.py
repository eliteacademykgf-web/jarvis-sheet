"""
verify.py — ручная проверка данных для таблицы.

python verify.py [YYYY-MM-DD]
    Один день (по умолчанию вчера): build_meta_rows и build_crm_row
    друг под другом. Meta — строка на объявление, CRM — одна сводка
    на день (разбивка по объявлениям недоступна).

python verify.py --month
    Сверка compute_daily_metrics за прошлый календарный месяц: каждый
    день по всей воронке, сумма за месяц и для справки расчёт одним
    периодом за весь месяц (в боте «Воронка продаж» считается именно
    так, а сумма по дням может быть больше, см. README).
"""

import logging
import sys
from datetime import date, datetime, timedelta, timezone
from calendar import monthrange

from amo_client import TZ_OFFSET_HOURS, month_bounds
from build_daily_source import build_meta_rows, build_crm_row
from meta_client import MetaAPIError
from metrics import compute_daily_metrics, compute_metrics_range

KEYS = ["new_request", "lead", "qualified", "consult_scheduled",
        "consult_done", "sale", "revenue"]
LABELS = {
    "new_request":       "Заявки",
    "lead":              "Лиды",
    "qualified":         "Квал. лиды",
    "consult_scheduled": "Конс. назначены",
    "consult_done":      "Встречи (конс. проведены)",
    "sale":              "Продажи",
    "revenue":           "Выручка",
}


def prev_month_bishkek() -> tuple:
    today = datetime.now(timezone(timedelta(hours=TZ_OFFSET_HOURS))).date()
    return (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)


def verify_day(d: date):
    print(f"День {d.isoformat()}. Meta — по часовому поясу рекламного аккаунта, "
          f"CRM — по Бишкеку (UTC+{TZ_OFFSET_HOURS})\n")

    print("META — строка на объявление (build_meta_rows)")
    try:
        rows = build_meta_rows(d)
    except (MetaAPIError, RuntimeError) as e:
        rows = None
        print(f"  ОШИБКА: {e}")
    if rows is not None:
        print(f"  {'ad_id':<20}{'объявление':<32}{'расход':>10}{'показы':>9}"
              f"{'клики':>7}{'dm_leads':>10}{'site_leads':>12}")
        for r in sorted(rows, key=lambda r: -r["spend"]):
            print(f"  {str(r['ad_id']):<20}{str(r['ad_name'])[:30]:<32}"
                  f"{r['spend']:>10.2f}{r['impressions']:>9}{r['clicks']:>7}"
                  f"{r['dm_leads']:>10}{r['site_leads']:>12}")
        print(f"  {'итого, объявлений: ' + str(len(rows)):<52}"
              f"{sum(r['spend'] for r in rows):>10.2f}"
              f"{sum(r['impressions'] for r in rows):>9}"
              f"{sum(r['clicks'] for r in rows):>7}"
              f"{sum(r['dm_leads'] for r in rows):>10}"
              f"{sum(r['site_leads'] for r in rows):>12}")

    print("\nCRM — одна строка на день (build_crm_row)")
    crm = build_crm_row(d)
    for k in KEYS:
        print(f"  {LABELS[k]:<27} {crm[k]:>10,}".replace(",", " "))
    print(f"  note: {crm['note']}")


def verify_month():
    year, month = prev_month_bishkek()
    print(f"Период: {month:02d}.{year}, воронка «Отдел продаж»\n")
    print("дата        " + " ".join(f"{k[:8]:>9}" for k in KEYS))

    total = {k: 0 for k in KEYS}
    for day in range(1, monthrange(year, month)[1] + 1):
        d = date(year, month, day)
        m = compute_daily_metrics(d)
        for k in KEYS:
            total[k] += m[k]
        print(f"{d.isoformat()}  " + " ".join(f"{m[k]:>9}" for k in KEYS), flush=True)

    print("\nИТОГО за месяц (сумма по дням):")
    for k in KEYS:
        print(f"  {LABELS[k]:<27} {total[k]:>10,}".replace(",", " "))

    df, dt = month_bounds(year, month)
    whole = compute_metrics_range(df, dt)
    print("\nДля справки — расчёт одним периодом за весь месяц:")
    for k in KEYS:
        print(f"  {LABELS[k]:<27} {whole[k]:>10,}".replace(",", " "))


def main():
    logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s",
                        level=logging.WARNING)
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    if arg == "--month":
        verify_month()
    elif arg:
        verify_day(date.fromisoformat(arg))
    else:
        today = datetime.now(timezone(timedelta(hours=TZ_OFFSET_HOURS))).date()
        verify_day(today - timedelta(days=1))


if __name__ == "__main__":
    main()
