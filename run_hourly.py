"""
run_hourly.py — часовое обновление таблицы (запускается кроном Railway).

Пересчитывает вчера и сегодня по Бишкеку. Вчера — потому что сделки
и статусы дописываются задним числом. Прошлые дни не трогает: их
дозаливают вручную (python write_to_sheets.py 2026-09-01 2026-09-23).

При ошибке API день, на котором она случилась, в таблицу не пишется
(день собирается целиком до записи), нули поверх данных не попадают.
В Telegram уходит уведомление, процесс завершается с кодом 1, и Railway
показывает запуск красным. Следующий запуск через час повторит всё заново.
"""

import logging
import sys
from datetime import datetime, timedelta, timezone

from alerts import mask_secrets, send_alert
from amo_client import TZ_OFFSET_HOURS
from write_to_sheets import today_bishkek, write_days

logger = logging.getLogger("jarvis_sheet.hourly")


def main() -> int:
    logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s",
                        level=logging.INFO)
    today = today_bishkek()
    try:
        write_days(today - timedelta(days=1), today)
    except Exception as e:
        now = datetime.now(timezone(timedelta(hours=TZ_OFFSET_HOURS)))
        logger.error("Часовое обновление не выполнено: %s", mask_secrets(f"{type(e).__name__}: {e}"))
        send_alert(
            f"⚠️ Сквозная аналитика: таблица не обновлена ({now:%d.%m.%Y %H:%M} Бишкек)\n\n"
            f"{type(e).__name__}: {e}\n\n"
            f"Следующая попытка — через час. Если ошибка повторяется, "
            f"проверьте токены AmoCRM и Meta и доступ к таблице.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
