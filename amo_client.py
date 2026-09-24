"""
amo_client.py — низкоуровневые запросы к AmoCRM.

Перенесено из jarvis-amo/main.py БЕЗ ИЗМЕНЕНИЯ ПОВЕДЕНИЯ (логика скопирована).
Отличия от оригинала:
  - FIELD_CODE_WORD исправлен на 1145111 (см. комментарий у константы);
  - убраны threading.Lock у кэшей: они защищали общее состояние между
    хендлерами Telegram-бота, в однопоточном скрипте не нужны.
"""

import logging
import re
import time
from datetime import datetime, timedelta
from calendar import monthrange
from typing import Dict, Optional, List

import requests

from config import AMO_DOMAIN, AMO_TOKEN

logger = logging.getLogger("jarvis_sheet")

# ================================================================
# НАСТРОЙКА — заполнено по данным Диагностики от 26.05.2026
# ================================================================

# Воронки, по которым считаем аналитику метрик 1-24.
#
# По словам владельца: продажа (статус 142) ВСЕГДА закрывается внутри
# «Отдела продаж». Профильные отделы (США/Италия/Семинар) — процессные,
# их «успешно реализовано» НЕ считается продажей в метрике №6.
# Поэтому считаем строго по одной воронке.
#
# Если позже окажется, что часть продаж закрывается в других воронках —
# допишите их id через запятую. Пустой список [] = все воронки аккаунта.
PIPELINE_IDS: List[int] = [
    9612890,   # Отдел продаж
    8422926,   # Отдел США
    10160626,  # отдел Италии
    10601254,  # Отдел Австрии Польши Германии
    10902482,  # Отдел Малайзии Северного Кипры
]

# Воронка(и) входа — где лиды рождаются (только Отдел продаж).
# Метрики 1-7 (заявки, лиды, квал и т.д.) считаются ТОЛЬКО здесь,
# чтобы не задваивать — лид рождается в одном месте, а продажа
# может закрыться в любом профильном отделе.
ENTRY_PIPELINE_IDS: List[int] = [9612890]   # Отдел продаж

# Часовой пояс бизнеса (Бишкек = UTC+6). Нужно чтобы границы месяца
# совпадали с местным временем, а не с UTC сервера.
TZ_OFFSET_HOURS: int = 6

# ── Привязка этапов к метрикам (воронка «Отдел продаж» 9612890) ──
STAGE_MAP: Dict[str, List[int]] = {
    # Метрика 1 — новые заявки
    "new_request":       [76732730,   # Неразобранное
                          76732734],  # новая заявка

    # Метрика 2 — лиды (взяты в работу)
    "lead":              [81574482,   # Лиды с теста
                          80021038,   # Обработан ии
                          76732738,   # взят в работу
                          76732866],  # вышли на связь/перезвон

    # Метрика 3 — квалифицированные лиды
    "qualified":         [76732870],  # квалифицирован

    # Метрика 4 — консультации назначены
    "consult_scheduled": [76732874],  # консультация назначена

    # Метрика 5 — консультации проведены
    "consult_done":      [76732878,   # консультация проведена
                          76732882],  # в АКТИВНом дожиме

    # Метрика 7 — НДЗ (не дозвонились)
    "ndz":               [76732742],  # ндз

    # Метрика 17 — получена предоплата (учитывается в выручке)
    "predoplata":        [76732886],  # получена предоплата
}
# Метрика 6  — продажа    = status_id 142 (стандарт AmoCRM, «Успешно реализовано»)
# Метрика 8  — нереализ.  = status_id 143 (стандарт AmoCRM)

# ── Кастомные поля ───────────────────────────────────────────────
# Метрика 10 — кодовое слово (поле хранится в КОНТАКТЕ, а не в лиде).
# ИСПРАВЛЕНИЕ БАГА (найдено при разведке API): в jarvis-amo здесь стоял
# 1139561 — это поле «Источник», в нём канал связи, а не кодовое слово.
# Кодовое слово лежит в поле контакта 1145111 «Кодовое слово» [text].
FIELD_CODE_WORD:   Optional[int] = 1145111  # «Кодовое слово» [text] — в контакте
FIELD_CODE_WORD_2: Optional[int] = None     # utm_source отсутствует в данных

# Эвристика поиска кастомных полей по названию
CF_NAME_HINTS = {
    "code_word": ["кодов", "кодовое слово", "источник", "utm", "промокод"],
    "country":   ["стран", "country"],
    "region":   ["регион", "город", "область", "region", "city"],
}

WON_STATUS   = 142
LOST_STATUS  = 143
PREPAY_STATUS_ID = 76732886  # «получена предоплата» = тоже продажа


AMO_HEADERS = {"Authorization": f"Bearer {AMO_TOKEN}", "Content-Type": "application/json"}

# ============================================================
# КЭШ (в памяти процесса)
# ============================================================
_cache: dict = {}


def _cache_ttl(df: int) -> int:
    """
    TTL кэша зависит от того, прошлый это месяц или текущий.
    Прошлые месяцы: 24 часа (данные не меняются).
    Текущий месяц: 5 минут (данные обновляются часто).
    """
    now = datetime.now()
    start_of_month = datetime(now.year, now.month, 1).timestamp()
    if df < start_of_month:
        return 86400  # 24 часа для прошлых месяцев
    return 300  # 5 минут для текущего месяца


def cache_get(key: str):
    e = _cache.get(key)
    if e and time.time() < e[1]:
        return e[0]
    return None


def cache_set(key: str, value, ttl: int = 300):
    _cache[key] = (value, time.time() + ttl)


# ============================================================
# AMOCRM — HTTP
# ============================================================
def _amo_get(path: str, params=None) -> dict:
    url = f"https://{AMO_DOMAIN}/api/v4/{path}"
    try:
        r = requests.get(url, headers=AMO_HEADERS, params=params or {}, timeout=30)
        if r.status_code == 401:
            return {"_error": "Токен AmoCRM истёк или неверный"}
        if r.status_code == 429:
            time.sleep(3)
            r = requests.get(url, headers=AMO_HEADERS, params=params or {}, timeout=30)
        if r.status_code == 204:
            return {}
        if r.status_code == 200:
            return r.json()
        logger.warning(f"AmoCRM {r.status_code} /{path}: {r.text[:200]}")
        return {}
    except Exception as e:
        logger.error(f"AmoCRM /{path}: {e}")
        return {}


def _amo_get_all(path: str, params=None, limit: int = 250) -> list:
    items, page = [], 1
    MAX_PAGES = 200  # safety: до 50 000 записей
    while page <= MAX_PAGES:
        p = dict(params or {})
        p["limit"], p["page"] = limit, page
        data = _amo_get(path, p)
        if not data or "_error" in data:
            break
        embedded = next(
            (v for v in data.get("_embedded", {}).values() if isinstance(v, list)), []
        )
        if not embedded:
            break
        items.extend(embedded)
        if len(embedded) < limit:
            break
        page += 1
        # Пауза только каждые 5 страниц чтобы не перегружать API
        if page % 5 == 0:
            time.sleep(0.1)
    return items


# ============================================================
# ВОРОНКИ / ЭТАПЫ
# ============================================================
def amo_get_pipelines() -> list:
    ck = "pipelines"
    c  = cache_get(ck)
    if c:
        return c
    data = _amo_get("leads/pipelines", {"with": "statuses"})
    raw  = data.get("_embedded", {}).get("pipelines", [])
    result = []
    for p in raw:
        statuses = sorted(
            [{"id": s["id"], "name": s["name"], "sort": s.get("sort", 0)}
             for s in p.get("_embedded", {}).get("statuses", [])],
            key=lambda x: x["sort"],
        )
        result.append({"id": p["id"], "name": p["name"], "statuses": statuses})
    cache_set(ck, result, 600)
    return result


def _pipeline(pid: int) -> dict:
    return next((p for p in amo_get_pipelines() if p["id"] == pid), {})


def _statuses(pid: int) -> Dict[int, str]:
    return {s["id"]: s["name"] for s in _pipeline(pid).get("statuses", [])}


def _target_pipeline_ids() -> list:
    return PIPELINE_IDS if PIPELINE_IDS else [p["id"] for p in amo_get_pipelines()]


def _entry_pipeline_ids() -> list:
    """Воронки, где лиды рождаются — для счёта заявок/лидов без задвоения."""
    if ENTRY_PIPELINE_IDS:
        return ENTRY_PIPELINE_IDS
    return _target_pipeline_ids()



# ============================================================
# ЛИДЫ
# ============================================================
def amo_get_leads(pid: int, df: int, dt: int) -> list:
    """Лиды воронки, созданные в периоде [df, dt] — для этапов 1-7."""
    ck = f"leads_cf3_{pid}_{df}_{dt}"
    c  = cache_get(ck)
    if c is not None:
        return c
    params = {
        "filter[pipeline_id]":       pid,
        "filter[created_at][from]":  df,
        "filter[created_at][to]":    dt,
        "with":  "contacts",
        "limit": 250,
    }
    leads = _amo_get_all("leads", params)
    leads = _enrich_leads_with_contacts(leads)
    cache_set(ck, leads, _cache_ttl(df))
    return leads


def _enrich_leads_with_contacts(leads: list) -> list:
    """
    Догружает кастомные поля контактов и копирует их в лид под ключом
    _contact_custom_fields — чтобы _cf_value мог читать поля контакта.
    Пакетный запрос: все контакты за один вызов API.
    """
    # Собираем все уникальные ID контактов
    contact_ids = []
    for l in leads:
        for c in (l.get("_embedded") or {}).get("contacts") or []:
            cid = c.get("id")
            if cid and cid not in contact_ids:
                contact_ids.append(cid)

    if not contact_ids:
        return leads

    # Загружаем контакты пакетами по 200
    contacts_map: Dict[int, dict] = {}
    for i in range(0, len(contact_ids), 200):
        chunk = contact_ids[i:i + 200]
        params: dict = {"with": "custom_fields", "limit": 200}
        for j, cid in enumerate(chunk):
            params[f"filter[id][{j}]"] = cid
        for contact in _amo_get_all("contacts", params):
            contacts_map[contact["id"]] = contact
        if i + 200 < len(contact_ids):
            time.sleep(0.1)

    # Прикрепляем поля контакта к лиду
    for l in leads:
        contacts_in_lead = (l.get("_embedded") or {}).get("contacts") or []
        merged_cfs = []
        for c in contacts_in_lead:
            full = contacts_map.get(c.get("id"))
            if full:
                merged_cfs.extend(full.get("custom_fields_values") or [])
        if merged_cfs:
            l["_contact_custom_fields"] = merged_cfs

    return leads


def amo_get_leads_by_ids(ids: List[int]) -> Dict[int, dict]:
    """Догружает полные карточки лидов по списку id (пакетами по 50)."""
    result: Dict[int, dict] = {}
    ids = list(ids)
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        params: dict = {"with": "contacts"}
        for j, lid in enumerate(chunk):
            params[f"filter[id][{j}]"] = lid
        batch = _amo_get_all("leads", params)
        batch = _enrich_leads_with_contacts(batch)
        for l in batch:
            result[l["id"]] = l
        time.sleep(0.15)
    return result


# Глобальный кэш батчевых событий: ключ = (df, dt), значение = {pid: {lid: ts}}
_events_batch_cache: Dict[tuple, dict] = {}


def _load_won_events_batch(df: int, dt: int) -> dict:
    """
    ОДИН проход по /events за период — захватывает WON (142) и LOST (143)
    сразу для ВСЕХ воронок. Кэш 10 минут — повторные вызовы мгновенны.

    Возвращает:
      {
        "won":  {pipeline_id: {lead_id: ts}},
        "lost": {pipeline_id: {lead_id: ts}},
      }
    """
    key = (df, dt)
    cached = _events_batch_cache.get(key)
    if cached and time.time() < cached["_expires"]:
        return cached["data"]

    won:  Dict[int, Dict[int, int]] = {}
    lost: Dict[int, Dict[int, int]] = {}
    page = 1
    MAX_PAGES = 200  # защита от зацикливания (200×100 = 20 000 событий)
    while page <= MAX_PAGES:
        data = _amo_get("events", {
            "filter[type]":             "lead_status_changed",
            "filter[entity]":           "lead",
            "filter[created_at][from]": df,
            "filter[created_at][to]":   dt,
            "limit": 100, "page": page,
        })
        if not data or "_error" in data:
            break
        evs = data.get("_embedded", {}).get("events", [])
        if not evs:
            break
        for e in evs:
            lid = e.get("entity_id")
            ts  = e.get("created_at") or 0
            for v in (e.get("value_after") or []):
                ls   = (v or {}).get("lead_status") or {}
                sid  = ls.get("id")
                p_id = ls.get("pipeline_id")
                if not p_id or lid is None:
                    continue
                if sid in (WON_STATUS, PREPAY_STATUS_ID):
                    b = won.setdefault(p_id, {})
                    if ts >= b.get(lid, 0):
                        b[lid] = ts
                elif sid == LOST_STATUS:
                    b = lost.setdefault(p_id, {})
                    if ts >= b.get(lid, 0):
                        b[lid] = ts
        if len(evs) < 100:
            break
        page += 1
        if page % 5 == 0:
            time.sleep(0.1)

    result = {"won": won, "lost": lost}
    _events_batch_cache[key] = {"data": result, "_expires": time.time() + _cache_ttl(df)}
    return result


def amo_get_won_events(pid: int, df: int, dt: int) -> dict:
    """{lead_id: won_at} для конкретной воронки — из батчевого кэша."""
    return _load_won_events_batch(df, dt)["won"].get(pid, {})


def amo_get_lost_count_batch(pids: list, df: int, dt: int) -> int:
    """Уникальные лиды перешедшие в 143 в периоде по всем pids — без доп. запросов."""
    lost_all = _load_won_events_batch(df, dt)["lost"]
    seen: set = set()
    total = 0
    for pid in pids:
        for lid in lost_all.get(pid, {}):
            if lid not in seen:
                seen.add(lid)
                total += 1
    return total


def amo_get_closed_leads(pid: int, df: int, dt: int) -> list:
    """
    Лиды, ставшие ПРОДАЖЕЙ (перешедшие в статус 142) в периоде [df, dt].

    Дата продажи берётся из событий (точный момент перехода в 142), затем
    догружаются полные карточки этих лидов — ради price (выручка) и
    created_at (цикл сделки). Если лид сейчас уже не в 142 (откатили после
    продажи) — он всё равно считается продажей этого месяца, т.к. переход был.

    В каждый лид кладём _won_at = дату перехода в 142, чтобы цикл сделки
    считался как (дата_продажи − дата_создания), а не по неверному closed_at.
    """
    ck = f"won_ev_{pid}_{df}_{dt}"
    c  = cache_get(ck)
    if c is not None:
        return c

    won_map = amo_get_won_events(pid, df, dt)
    if not won_map:
        cache_set(ck, [], 600)
        return []

    leads_map = amo_get_leads_by_ids(list(won_map.keys()))
    leads = []
    for lid, won_at in won_map.items():
        l = leads_map.get(lid)
        if l:
            l["_won_in_period"] = True
            l["_won_at"] = won_at
            leads.append(l)
    cache_set(ck, leads, _cache_ttl(df))
    return leads


def _cf_value(lead: dict, field_id: Optional[int], hint_key: str) -> Optional[str]:
    """
    Значение кастомного поля: сначала ищем в лиде, потом в контакте (_contact_custom_fields).
    Для select/multiselect — берём enum_value (текст), не числовой ID.
    """
    def _extract(cf) -> Optional[str]:
        vals = cf.get("values") or []
        if not vals:
            return None
        v = vals[0]
        result = str(v.get("enum_value") or "").strip()
        if result:
            return result
        val = v.get("value")
        if val is not None:
            s = str(val).strip()
            if s and not s.isdigit():
                return s
        return None

    def _search_in(cfs) -> Optional[str]:
        if not cfs:
            return None
        # 1) точный ID
        if field_id:
            for cf in cfs:
                if cf.get("field_id") == field_id:
                    return _extract(cf)
        # 2) эвристика по названию
        hints = CF_NAME_HINTS.get(hint_key, [])
        if hints:
            for cf in cfs:
                fn = (cf.get("field_name") or "").lower()
                if any(h in fn for h in hints):
                    return _extract(cf)
        return None

    # Сначала поля лида, потом поля контакта
    result = _search_in(lead.get("custom_fields_values") or [])
    if result:
        return result
    return _search_in(lead.get("_contact_custom_fields") or [])


# ============================================================
# ДЕДУПЛИКАЦИЯ ЛИДОВ ПО ТЕЛЕФОНУ
# ============================================================
_PHONE_FIELD_IDS = [1136409, 1138851, 1137601]


def _extract_phone(lead: dict) -> Optional[str]:
    """Телефон из кастомных полей лида (нормализованный, 10 цифр)."""
    for fid in _PHONE_FIELD_IDS:
        raw = _cf_value(lead, fid, None)
        if raw:
            digits = re.sub(r"\D", "", str(raw))
            if len(digits) >= 7:
                return digits[-10:]
    return None


def _main_contact_id(lead: dict) -> Optional[int]:
    """ID главного контакта лида (поле is_main=True в _embedded.contacts)."""
    contacts = (lead.get("_embedded") or {}).get("contacts") or []
    for c in contacts:
        if c.get("is_main"):
            return c.get("id")
    if contacts:
        return contacts[0].get("id")
    return None


def dedup_leads(leads: list) -> list:
    """
    Убирает дубли: один человек пришёл из Instagram + WhatsApp = один лид.
    Ключи: contact_id (главный контакт) → телефон из кастомных полей.
    Оставляем самый ранний лид по created_at.
    """
    seen_contact: Dict[int, dict] = {}
    seen_phone:   Dict[str, dict] = {}
    no_key: list = []

    for l in sorted(leads, key=lambda x: x.get("created_at", 0)):
        cid   = _main_contact_id(l)
        phone = _extract_phone(l)

        if cid and cid in seen_contact:
            continue
        if phone and phone in seen_phone:
            continue

        if cid:
            seen_contact[cid] = l
        if phone:
            seen_phone[phone] = l
        if not cid and not phone:
            no_key.append(l)

    unique = list({id(v): v for v in list(seen_contact.values()) + list(seen_phone.values())}.values())
    return unique + no_key


# ============================================================
# ПЕРИОДЫ
# ============================================================
def month_bounds(year: int, month: int) -> tuple:
    """Границы месяца в UNIX-времени с поправкой на TZ_OFFSET_HOURS.

    datetime(...).timestamp() использует таймзону СЕРВЕРА. Если сервер в UTC,
    а бизнес в Бишкеке (UTC+6), границы месяца съезжают на 6 часов и сделки
    у стыка месяца теряются/задваиваются. Считаем границы вручную в UTC.
    """
    from datetime import timezone
    last  = monthrange(year, month)[1]
    # локальная полночь 1-го числа = UTC-полночь минус смещение
    tz = timezone(timedelta(hours=TZ_OFFSET_HOURS))
    start = datetime(year, month, 1, 0, 0, 0, tzinfo=tz)
    end   = datetime(year, month, last, 23, 59, 59, tzinfo=tz)
    return int(start.timestamp()), int(end.timestamp())



def today_bounds() -> tuple:
    """Сегодня 00:00 — 23:59 по Бишкеку."""
    from datetime import timezone
    tz = timezone(timedelta(hours=TZ_OFFSET_HOURS))
    n  = datetime.now(tz)
    start = datetime(n.year, n.month, n.day, 0, 0, 0, tzinfo=tz)
    end   = datetime(n.year, n.month, n.day, 23, 59, 59, tzinfo=tz)
    return int(start.timestamp()), int(end.timestamp())


def yesterday_bounds() -> tuple:
    from datetime import timezone
    tz  = timezone(timedelta(hours=TZ_OFFSET_HOURS))
    n   = datetime.now(tz) - timedelta(days=1)
    start = datetime(n.year, n.month, n.day, 0, 0, 0, tzinfo=tz)
    end   = datetime(n.year, n.month, n.day, 23, 59, 59, tzinfo=tz)
    return int(start.timestamp()), int(end.timestamp())


def week_bounds() -> tuple:
    """Последние 7 дней."""
    from datetime import timezone
    tz  = timezone(timedelta(hours=TZ_OFFSET_HOURS))
    n   = datetime.now(tz)
    end   = datetime(n.year, n.month, n.day, 23, 59, 59, tzinfo=tz)
    start = end - timedelta(days=6)
    return int(start.timestamp()), int(end.timestamp())

