"""
write_to_sheets.py — запись данных за день в Google Sheets.

Собирает build_meta_rows и build_crm_row и пишет upsert'ом на листы
meta_daily и crm_daily. Повторный запуск за тот же день обновляет
строки на месте, а не дописывает дубли.

Запуск:
  python write_to_sheets.py              # вчера (по Бишкеку)
  python write_to_sheets.py 2026-09-20   # конкретный день
"""

import logging
import sys
from datetime import date, datetime, timedelta, timezone

from amo_client import TZ_OFFSET_HOURS
from build_daily_source import build_meta_rows, build_crm_row
from sheets_client import (META_SHEET, CRM_SHEET, get_client, open_spreadsheet,
                           write_meta_rows, write_crm_row)


def yesterday_bishkek() -> date:
    return datetime.now(timezone(timedelta(hours=TZ_OFFSET_HOURS))).date() - timedelta(days=1)


def main():
    logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s",
                        level=logging.WARNING)
    d = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else yesterday_bishkek()
    print(f"День {d.isoformat()}")

    meta_rows = build_meta_rows(d)
    crm_row = build_crm_row(d)

    client = get_client()
    spreadsheet = open_spreadsheet(client)
    m_ins, m_upd = write_meta_rows(meta_rows, spreadsheet)
    c_ins, c_upd = write_crm_row(crm_row, spreadsheet)

    print(f"{META_SHEET}: добавлено {m_ins}, обновлено {m_upd} (из Meta пришло строк: {len(meta_rows)})")
    print(f"{CRM_SHEET}: добавлено {c_ins}, обновлено {c_upd}")
    print(f"Запросов к Google API: {client.request_count}")


if __name__ == "__main__":
    main()
