"""
run_loop.py — часовое обновление на офисном ПК (замена крона Railway).

Запускает run_hourly.py сразу при старте, дальше каждый час в :05 по часам
ПК. Каждый прогон — отдельный процесс: так после update-sheet.bat новый
код подхватывается без перезапуска окна, а кэши AmoCRM не копятся днями.

Второй экземпляр не стартует (два цикла писали бы в таблицу одновременно
и плодили дубли строк). Вывод пишется и в окно, и в logs/sheet.log.

Запуск: start-sheet.bat (или python run_loop.py).
"""

import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(HERE, "logs")
LOG_FILE = os.path.join(LOG_DIR, "sheet.log")
LOG_MAX_BYTES = 5 * 1024 * 1024
RUN_AT_MINUTE = 5
RUN_TIMEOUT = 50 * 60          # прогон дольше 50 минут — завис, прерываем
LOCK_PORT = 47831              # занятый порт = цикл уже запущен


def log(text: str):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {text}"
    print(line, flush=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > LOG_MAX_BYTES:
        os.replace(LOG_FILE, LOG_FILE + ".old")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def single_instance() -> socket.socket:
    """Держит порт на 127.0.0.1 до конца процесса; Windows освободит его сам при падении."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", LOCK_PORT))
    except OSError:
        print("Обновление таблицы уже запущено в другом окне. Это окно можно закрыть.")
        time.sleep(15)
        sys.exit(0)
    return s


def next_run(now: datetime) -> datetime:
    at = now.replace(minute=RUN_AT_MINUTE, second=0, microsecond=0)
    return at if at > now else at + timedelta(hours=1)


def run_once():
    log("Обновляю таблицу (вчера и сегодня)...")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    try:
        p = subprocess.run([sys.executable, os.path.join(HERE, "run_hourly.py")],
                           cwd=HERE, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=RUN_TIMEOUT)
    except subprocess.TimeoutExpired:
        log(f"ОШИБКА: прогон не уложился в {RUN_TIMEOUT // 60} минут и прерван")
        return
    for stream in (p.stdout, p.stderr):
        for line in stream.splitlines():
            if line.strip():
                log("  " + line)
    log("Готово." if p.returncode == 0 else
        f"ОШИБКА (код {p.returncode}). Уведомление в Telegram отправлено, если настроено.")


def main():
    with single_instance():                  # порт занят, пока работает цикл
        log("Сквозная аналитика: запуск цикла. Окно не закрывать, можно свернуть.")
        run_once()
        while True:
            at = next_run(datetime.now())
            log(f"Следующее обновление в {at:%H:%M}")
            # спим по минуте: после сна ПК или перевода часов не проспим час
            while datetime.now() < at:
                time.sleep(min(60, max(1, (at - datetime.now()).total_seconds())))
            run_once()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
