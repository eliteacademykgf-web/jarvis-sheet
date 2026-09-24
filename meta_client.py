"""
meta_client.py — клиент Meta Marketing API: статистика по объявлениям по дням.

В jarvis-meta/main.py не работали три вещи, здесь они сделаны:
  - level=ad (статистика по объявлениям, а не по группам);
  - time_increment=1 (разбивка по дням);
  - пагинация по paging.next.
Ошибки Meta не глотаются: поднимается MetaAPIError с message и code.

Токен никогда не попадает в URL: он передаётся заголовком Authorization,
поэтому его нет ни в paging.next, ни в текстах исключений requests,
ни в DEBUG-логе urllib3. Все тексты ошибок и логов дополнительно
проходят через _mask().
"""

import json
import logging
import re
import time
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

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


_TOKEN_IN_TEXT = re.compile(r"(access_token=)[^&\s\"']+")


def _mask(text, token: str = "") -> str:
    """Убирает токен из текста: и сам токен, и любой access_token=... в URL."""
    text = str(text)
    if token:
        text = text.replace(token, "***")
    return _TOKEN_IN_TEXT.sub(r"\1***", text)


def _strip_token(url: str) -> str:
    """Удаляет access_token из query URL (на случай, если Meta его туда вернёт)."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if k != "access_token"]
    return urlunsplit(parts._replace(query=urlencode(query)))


class MetaAPIError(Exception):
    """Ошибка Meta API: текст готов для уведомления (message, code, HTTP-статус)."""

    def __init__(self, message: str, code=None, subcode=None, http_status=None,
                 token: str = ""):
        super().__init__(_mask(message, token))
        self.code = code
        self.subcode = subcode
        self.http_status = http_status


def _raise_for_error(r: requests.Response, token: str) -> dict:
    """JSON ответа или исключение, если в нём error / ответ не JSON."""
    try:
        data = r.json()
    except ValueError:
        raise MetaAPIError(
            f"Meta API: HTTP {r.status_code}, ответ не JSON: {r.text[:200]}",
            http_status=r.status_code, token=token,
        ) from None
    if isinstance(data, dict) and "error" in data:
        err = data["error"] or {}
        raise MetaAPIError(
            f"Meta API error {err.get('code')}"
            f"{'/' + str(err['error_subcode']) if err.get('error_subcode') else ''}: "
            f"{err.get('message')} (HTTP {r.status_code}, "
            f"type {err.get('type')}, fbtrace_id {err.get('fbtrace_id')})",
            code=err.get("code"), subcode=err.get("error_subcode"),
            http_status=r.status_code, token=token,
        )
    if r.status_code >= 400:
        raise MetaAPIError(f"Meta API: HTTP {r.status_code}: {r.text[:200]}",
                           http_status=r.status_code, token=token)
    return data


def _get(url: str, params: dict, token: str) -> dict:
    """
    GET с timeout=30 и одним retry:
      - сетевая ошибка или 5xx — повтор сразу;
      - 429 — повтор после Retry-After (или 5 сек);
      - прочие 4xx — без повтора, сразу исключение.
    Исходное исключение requests не прикрепляется: в его тексте
    и traceback мог бы оказаться URL.
    """
    headers = {"Authorization": f"Bearer {token}"}
    for attempt in (1, 2):
        last = attempt == 2
        net_error = None
        try:
            r = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
        except requests.RequestException as e:
            net_error = _mask(f"{type(e).__name__}: {e}", token)
        if net_error:
            # raise вне except: у MetaAPIError не будет __context__
            # с исходным исключением requests
            if last:
                raise MetaAPIError(f"Meta API: сетевая ошибка: {net_error}")
            logger.warning(f"Meta API: сетевая ошибка, повтор: {net_error}")
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
        return _raise_for_error(r, token)


def get_ad_insights(ad_account_id: str, date_from: str, date_to: str,
                    access_token: str) -> list:
    """
    Статистика по каждому объявлению с разбивкой по дням за [date_from, date_to]
    (даты 'YYYY-MM-DD', в часовом поясе рекламного аккаунта).
    Проходит все страницы paging.next и возвращает их одним списком.
    """
    acc = ad_account_id if str(ad_account_id).startswith("act_") else f"act_{ad_account_id}"
    params = {
        "level":          "ad",
        "time_increment": 1,
        "time_range":     json.dumps({"since": date_from, "until": date_to}),
        "fields":         INSIGHTS_FIELDS,
        "limit":          500,
    }
    url, rows = f"{GRAPH_URL}/{acc}/insights", []
    for _ in range(MAX_PAGES):
        data = _get(url, params, access_token)
        rows.extend(data.get("data") or [])
        url = (data.get("paging") or {}).get("next")
        if not url:
            return rows
        url = _strip_token(url)
        params = None  # в paging.next уже все параметры
    raise MetaAPIError(f"Meta API: больше {MAX_PAGES} страниц insights, прервано")


# ============================================================
# ЗАЯВКИ ИЗ actions — перенос из jarvis-meta/main.py как есть.
# DM-заявки и заявки с сайта держим раздельно (dm_leads / site_leads):
# объединять ли их в «Заявки с FB» — открытый вопрос ТЗ №5.
# ============================================================
def extract_leads(item):
    """Лиды-переписки (Instagram DM / Messenger)"""
    return sum(
        int(a.get("value", 0)) for a in item.get("actions", [])
        if "messaging_conversation" in a.get("action_type", "")
    )


def extract_site_leads(item):
    """Лиды с сайта (через пиксель на Тильде)"""
    SITE_LEAD_TYPES = {
        "offsite_conversion.fb_pixel_lead",
        "offsite_conversion.fb_pixel_complete_registration",
        "lead",
        "onsite_web_lead",
    }
    return sum(
        int(a.get("value", 0)) for a in item.get("actions", [])
        if a.get("action_type") in SITE_LEAD_TYPES
    )
