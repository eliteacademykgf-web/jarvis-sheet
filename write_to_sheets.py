"""
write_to_sheets.py — запись данных за день (или диапазон дней) в Google Sheets.

Собирает build_meta_rows и build_crm_row, пишет upsert'ом на листы
meta_daily и crm_daily, затем пересобирает лист «Сквозная аналитика
<Месяц>» за каждый затронутый месяц (sheet_builder.rebuild_month_sheet).
Повторный запуск за тот же день обновляет строки на месте.

Запуск:
  python write_to_sheets.py                         # вчера (по Бишкеку)
  python write_to_sheets.py 2026-09-20              # конкретный день
  python write_to_sheets.py 2026-09-01 2026-09-23   # диапазон (дозаливка)
"""

import logging
import sys
from datetime import date, datetime, timedelta, timezone

from amo_client import TZ_OFFSET_HOURS
from build_daily_source import build_meta_rows, build_crm_row
from sheet_builder import rebuild_month_sheet
from sheets_client import (META_SHEET, CRM_SHEET, get_client, open_spreadsheet,
                           write_meta_rows, write_crm_row)


def yesterday_bishkek() -> date:
    return datetime.now(timezone(timedelta(hours=TZ_OFFSET_HOURS))).date() - timedelta(days=1)


def main():
    logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s",
                        level=logging.WARNING)
    args = sys.argv[1:]
    d_from = date.fromisoformat(args[0]) if args else yesterday_bishkek()
    d_to = date.fromisoformat(args[1]) if len(args) > 1 else d_from

    client = get_client()
    spreadsheet = open_spreadsheet(client)

    months = []
    d = d_from
    while d <= d_to:
        meta_rows = build_meta_rows(d)
        crm_row = build_crm_row(d)
        m_ins, m_upd = write_meta_rows(meta_rows, spreadsheet)
        c_ins, c_upd = write_crm_row(crm_row, spreadsheet)
        print(f"{d.isoformat()}  {META_SHEET}: +{m_ins} / обновлено {m_upd} "
              f"(из Meta {len(meta_rows)});  {CRM_SHEET}: +{c_ins} / обновлено {c_upd}",
              flush=True)
        if (d.year, d.month) not in months:
            months.append((d.year, d.month))
        d += timedelta(days=1)

    for year, month in months:
        info = rebuild_month_sheet(year, month, spreadsheet)
        print(f"Лист «{info['title']}» пересобран: дней {info['days']}, "
              f"строк объявлений {info['ad_rows']}, всего строк {info['rows']}")
    print(f"Запросов к Google API: {client.request_count}")


if __name__ == "__main__":
    main()
