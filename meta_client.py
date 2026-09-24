"""
meta_client.py — клиент Meta Marketing API: статистика по объявлениям по дням.

В jarvis-meta/main.py не работали три вещи, здесь они сделаны:
  - level=ad (статистика по объявлениям, а не по группам);
  - time_increment=1 (разбивка по дням);
  - пагинация по paging.next.
Ошибки Meta не глотаются: поднимается MetaAPIError с message и code.
"""

import json
import logging
import time

import requests

logger = logging.getLogger("jarvis_sheet.meta")

# Graph API v26.0 — последняя версия на 24.09.2026 (вышла 29.07.2026).
# В jarvis-meta захардкожена v18.0: она истекла 26.01.2026, и Meta молча
# обрабатывает такие запросы как самую старую живую версию (заголовок
# facebook-api-version: v25.0), так что поведение может поменяться без
# предупреждения. https://developers.facebook.com/docs/graph-api/changelog/versions
GRAPH_API_VERSION = "v26.0"
GRAPH_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

TIMEOUT = 30
RATE_LIMIT_DEFAULT_WAIT = 5  # сек, если в 429 нет Retry-After
MAX_PAGES = 500              # защита от зацикливания пагинации

INSIGHTS_FIELDS = ",".join([
    "ad_id", "ad_name", "campaign_name", "adset_name",
    "spend", "impressions", "clicks", "ctr", "cpm", "actions",
])


class MetaAPIError(Exception):
    """Ошибка Meta API: текст готов для уведомления (message, code, HTTP-статус)."""

    def __init__(self, message: str, code=None, subcode=None, http_status=None):
        super().__init__(message)
        self.code = code
        self.subcode = subcode
        self.http_status = http_status


def _raise_for_error(r: requests.Response) -> dict:
    """JSON ответа или исключение, если в нём error / ответ не JSON."""
    try:
        data = r.json()
    except ValueError:
        raise MetaAPIError(
            f"Meta API: HTTP {r.status_code}, ответ не JSON: {r.text[:200]}",
            http_status=r.status_code,
        )
    if isinstance(data, dict) and "error" in data:
        err = data["error"] or {}
        raise MetaAPIError(
            f"Meta API error {err.get('code')}"
            f"{'/' + str(err['error_subcode']) if err.get('error_subcode') else ''}: "
            f"{err.get('message')} (HTTP {r.status_code}, "
            f"type {err.get('type')}, fbtrace_id {err.get('fbtrace_id')})",
            code=err.get("code"), subcode=err.get("error_subcode"),
            http_status=r.status_code,
        )
    if r.status_code >= 400:
        raise MetaAPIError(f"Meta API: HTTP {r.status_code}: {r.text[:200]}",
                           http_status=r.status_code)
    return data


def _get(url: str, params: dict = None) -> dict:
    """
    GET с timeout=30 и одним retry:
      - сетевая ошибка или 5xx — повтор сразу;
      - 429 — повтор после Retry-After (или 5 сек);
      - прочие 4xx — без повтора, сразу исключение.
    """
    for attempt in (1, 2):
        last = attempt == 2
        try:
            r = requests.get(url, params=params, timeout=TIMEOUT)
        except requests.RequestException as e:
            if last:
                raise MetaAPIError(f"Meta API: сетевая ошибка: {e}")
            logger.warning(f"Meta API: сетевая ошибка, повтор: {e}")
            continue
        if r.status_code >= 500 and not last:
            logger.warning(f"Meta API: HTTP {r.status_code}, повтор")
            continue
        if r.status_code == 429 and not last:
            try:
                wait = float(r.headers.get("Retry-After") or RATE_LIMIT_DEFAULT_WAIT)
            except ValueError:
                wait = RATE_LIMIT_DEFAULT_WAIT
            logger.warning(f"Meta API: 429, жду {wait} сек")
            time.sleep(wait)
            continue
        return _raise_for_error(r)


def get_ad_insights(ad_account_id: str, date_from: str, date_to: str,
                    access_token: str) -> list:
    """
    Статистика по каждому объявлению с разбивкой по дням за [date_from, date_to]
    (даты 'YYYY-MM-DD', в часовом поясе рекламного аккаунта).
    Проходит все страницы paging.next и возвращает их одним списком.
    """
    acc = ad_account_id if str(ad_account_id).startswith("act_") else f"act_{ad_account_id}"
    params = {
        "access_token":   access_token,
        "level":          "ad",
        "time_increment": 1,
        "time_range":     json.dumps({"since": date_from, "until": date_to}),
        "fields":         INSIGHTS_FIELDS,
        "limit":          500,
    }
    url, rows = f"{GRAPH_URL}/{acc}/insights", []
    for _ in range(MAX_PAGES):
        data = _get(url, params)
        rows.extend(data.get("data") or [])
        url = (data.get("paging") or {}).get("next")
        if not url:
            return rows
        params = None  # в paging.next уже все параметры
    raise MetaAPIError(f"Meta API: больше {MAX_PAGES} страниц insights, прервано")
