# jarvis-sheet

CRM-логика для таблицы сквозной аналитики: метрики за день по AmoCRM.
Здесь нет Telegram, Meta и Google Sheets, только AmoCRM.

## Файлы

- `config.py`: переменные окружения (`AMO_DOMAIN`, `AMO_TOKEN`).
- `amo_client.py`: запросы к AmoCRM. Перенесено из `jarvis-amo/main.py` без изменения поведения.
- `metrics.py`: `compute_daily_metrics(date, pipeline_id, code_word=None)`.
- `verify.py`: суммы за прошлый календарный месяц для ручной сверки с ботом.

## Запуск локально

```bash
cd jarvis-sheet
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # заполнить AMO_DOMAIN и AMO_TOKEN
python verify.py
```

Можно без `.env`: переменные окружения тоже подхватываются
(`AMO_DOMAIN=... AMO_TOKEN=... python verify.py`).
