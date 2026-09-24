"""
metrics.py — расчёт CRM-метрик за день.

Этапы (заявки → лиды → квал. лиды → конс. назначены → конс. проведены)
считаются НАКОПИТЕЛЬНО: «дошёл до этапа или дальше». В jarvis-amo
classify() относит лид только к одному этапу, по текущему статусу.
Это риск 1 из ТЗ: сделка, ушедшая из «квалифицирован» в предоплату
или отказ, выпадает из квал. лидов.

Порядок этапов берётся из sort статусов воронки (/leads/pipelines).
Для «Отдела продаж» 9612890:
  10 Неразобранное / новая заявка   → new_request
  20 Обработан ии, 30 взят в работу, 40 ндз, 50 перезвон → lead
  60 квалифицирован                 → qualified
  70 консультация назначена         → consult_scheduled
  80 проведена, 90 в дожиме         → consult_done
  100 предоплата, 142 won           → дальше всех этапов
  143 lost                          → не этап; путь смотрим по истории
"""

import re
from datetime import date as date_cls, datetime, timedelta, timezone
from typing import Dict, List, Optional

from amo_client import (
    STAGE_MAP, PIPELINE_IDS, WON_STATUS, LOST_STATUS, PREPAY_STATUS_ID,
    TZ_OFFSET_HOURS,
    FIELD_CODE_WORD, _pipeline, _cf_value, amo_get_leads, amo_get_closed_leads,
    amo_get_status_history, dedup_leads,
)

SALES_DEPT_PIPELINE_ID = 9612890  # «Отдел продаж» — воронка входа

FUNNEL_STAGES = ["new_request", "lead", "qualified",
                 "consult_scheduled", "consult_done"]


def day_bounds(d: date_cls) -> tuple:
    """Границы календарного дня по Бишкеку (UTC+6), как month_bounds."""
    tz = timezone(timedelta(hours=TZ_OFFSET_HOURS))
    start = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=tz)
    end   = datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=tz)
    return int(start.timestamp()), int(end.timestamp())


def normalize_code_word(word: Optional[str]) -> str:
    """
    Ключ сравнения кодовых слов: без регистра, без эмодзи и знаков,
    пробелы схлопнуты. «ГЕРМАНИЯ  🤍» и «германия 🔥» → «германия».
    Если букв и цифр нет совсем («➕➕➕»), сравниваем всю строку
    (обрезка, схлопывание пробелов, без регистра), иначе такие слова
    совпадали бы с любым пустым значением.
    """
    raw = re.sub(r"\s+", " ", (word or "")).strip().casefold()
    letters = "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in raw)
    letters = re.sub(r"\s+", " ", letters).strip()
    return letters or raw


def lead_code_word(lead: dict) -> Optional[str]:
    """
    Кодовое слово из контакта лида. Читается строго по FIELD_CODE_WORD
    (hint_key=None отключает эвристику по названию, чтобы не подхватить
    поле «Источник»).
    """
    return _cf_value(lead, FIELD_CODE_WORD, None)


def _match_code_word(lead: dict, key: str) -> bool:
    cw = lead_code_word(lead)
    return bool(cw) and normalize_code_word(cw) == key


def _sort_by_status(pipeline_id: int) -> Dict[int, int]:
    return {s["id"]: s["sort"] for s in _pipeline(pipeline_id).get("statuses", [])}


def _stage_thresholds(sort_by_id: Dict[int, int]) -> Dict[str, int]:
    """
    Минимальный sort этапа = порог «дошёл до этапа».
    Id из STAGE_MAP, которых уже нет в воронке (81574482 «Лиды с теста»),
    пропускаются.
    """
    th = {}
    for stage in FUNNEL_STAGES:
        sorts = [sort_by_id[sid] for sid in STAGE_MAP[stage] if sid in sort_by_id]
        if not sorts:
            raise RuntimeError(f"Этап {stage}: ни один статус из STAGE_MAP не найден в воронке")
        th[stage] = min(sorts)
    return th


def _max_reached_sort(lead: dict, pipeline_id: int, sort_by_id: Dict[int, int],
                      history: Optional[list]) -> int:
    """
    Максимальный sort, до которого дошёл лид в воронке pipeline_id.

    Открытый лид: sort текущего статуса. Лид ещё не прошёл дальше,
    поэтому текущего статуса достаточно.
    Закрытый (142/143): текущий статус ничего не говорит о пройденном пути.
    Берём максимум по всем статусам из истории переходов (value_before и
    value_after) в этой воронке. LOST (143) не учитываем: sort у него
    11000, и тогда любой отказ считался бы дошедшим до всех этапов.
    WON (142) учитываем как «дальше всех этапов».
    """
    sid = lead.get("status_id")
    if sid not in (WON_STATUS, LOST_STATUS):
        return sort_by_id.get(sid, 0)

    best = sort_by_id.get(WON_STATUS, 0) if sid == WON_STATUS else 0
    for _ts, before, after in history or []:
        for st_id, st_pid in before + after:
            if st_id == LOST_STATUS:
                continue
            if st_id == WON_STATUS or st_pid == pipeline_id:
                best = max(best, sort_by_id.get(st_id, 0))
    return best


def _first_sale_ts(history: Optional[list]) -> Optional[int]:
    """
    Момент первой продажи: самое раннее событие перехода в 142 или
    в «получена предоплата» (в любой воронке, как _load_won_events_batch).
    """
    ts_list = [ts for ts, _before, after in history or []
               if any(st_id in (WON_STATUS, PREPAY_STATUS_ID) for st_id, _ in after)]
    return min(ts_list) if ts_list else None


def compute_metrics_range(df: int, dt: int,
                          pipeline_id: int = SALES_DEPT_PIPELINE_ID,
                          code_word: Optional[str] = None,
                          sales_pipeline_ids: Optional[List[int]] = None) -> dict:
    """
    Метрики за произвольный период [df, dt] (UNIX, границы включительно).

    Этапы: когорта лидов, СОЗДАННЫХ в периоде в воронке pipeline_id
    (как amo_get_leads в боте), с дедупликацией dedup_leads, накопительно.
    Продажи/выручка: события перехода в 142 или в предоплату в периоде
    (amo_get_closed_leads), по воронкам sales_pipeline_ids (по умолчанию
    PIPELINE_IDS). В отличие от бота, продажа засчитывается один раз —
    в периоде ПЕРВОГО такого события: сделка с предоплатой 3-го и 142
    20-го — продажа 3-го, а не двух дней. Иначе сумма по дням больше
    месячной цифры.

    code_word: если передан, считаются только лиды (и продажи), у контакта
    которых кодовое слово совпадает после normalize_code_word. Разнесение
    по объявлениям при одинаковых словах здесь не делается.
    """
    sales_pids = sales_pipeline_ids if sales_pipeline_ids is not None else PIPELINE_IDS
    sort_by_id = _sort_by_status(pipeline_id)
    th = _stage_thresholds(sort_by_id)

    # ── Этапы: когорта по дате создания ─────────────────────────────────
    cohort = dedup_leads(amo_get_leads(pipeline_id, df, dt))
    key = normalize_code_word(code_word) if code_word else None
    if key:
        cohort = [l for l in cohort if _match_code_word(l, key)]
    closed_ids = [l["id"] for l in cohort
                  if l.get("status_id") in (WON_STATUS, LOST_STATUS)]
    history = amo_get_status_history(closed_ids) if closed_ids else {}

    counts = {stage: 0 for stage in FUNNEL_STAGES}
    for l in cohort:
        reached = _max_reached_sort(l, pipeline_id, sort_by_id, history.get(l["id"]))
        for stage in FUNNEL_STAGES:
            if reached >= th[stage]:
                counts[stage] += 1
    # Заявка = любой лид, созданный в периоде, даже если его статус
    # не распознан (например, удалённый этап без истории).
    counts["new_request"] = len(cohort)

    # ── Продажи: события перехода в 142 / предоплату в периоде ──────────
    won_by_id: Dict[int, dict] = {}
    for pid in sales_pids:
        for l in amo_get_closed_leads(pid, df, dt):
            won_by_id.setdefault(l["id"], l)   # одна сделка в двух воронках — одна продажа
    sale_history = amo_get_status_history(list(won_by_id)) if won_by_id else {}
    won_leads = []
    for lid, l in won_by_id.items():
        first = _first_sale_ts(sale_history.get(lid))
        # first is None — история не загрузилась: считаем продажей, как бот
        if first is None or first >= df:
            won_leads.append(l)
    if key:
        won_leads = [l for l in won_leads if _match_code_word(l, key)]
    revenue = sum(float(l.get("price") or 0) for l in won_leads)

    return {
        **counts,
        "sale":    len(won_leads),
        "revenue": round(revenue),
    }


def compute_daily_metrics(date: date_cls,
                          pipeline_id: int = SALES_DEPT_PIPELINE_ID,
                          code_word: Optional[str] = None) -> dict:
    """
    Метрики за один календарный день (Бишкек).
    {new_request, lead, qualified, consult_scheduled, consult_done, sale, revenue}
    Без code_word — по всей воронке.
    """
    df, dt = day_bounds(date)
    return compute_metrics_range(df, dt, pipeline_id, code_word)
