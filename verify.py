"""
verify.py — сверка compute_daily_metrics за прошлый календарный месяц.

Считает каждый день месяца без code_word, печатает цифры по дням и
сумму за месяц. Для справки печатает и расчёт одним периодом за весь
месяц: в боте «Воронка продаж» считается именно так, а сумма по дням
может быть больше (см. README).

Запуск: python verify.py
"""

import logging
from datetime import date, datetime, timedelta, timezone
from calendar import monthrange

from amo_client import TZ_OFFSET_HOURS, month_bounds
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


def main():
    logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s",
                        level=logging.WARNING)
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


if __name__ == "__main__":
    main()
