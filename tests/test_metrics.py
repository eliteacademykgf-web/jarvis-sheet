from datetime import date

import pytest

import metrics
from amo_client import LOST_STATUS, PREPAY_STATUS_ID, WON_STATUS

P = metrics.SALES_DEPT_PIPELINE_ID

# sort статусов «Отдела продаж» (как в docstring metrics.py)
STATUSES = [
    (76732730, 10), (76732734, 10),                      # новая заявка
    (80021038, 20), (76732738, 30), (76732742, 40), (76732866, 50),   # лид
    (76732870, 60),                                      # квалифицирован
    (76732874, 70),                                      # конс. назначена
    (76732878, 80), (76732882, 90),                      # конс. проведена / дожим
    (PREPAY_STATUS_ID, 100),
    (WON_STATUS, 10000), (LOST_STATUS, 11000),
]
SORT = {sid: s for sid, s in STATUSES}


def test_normalize_code_word():
    assert metrics.normalize_code_word("ГЕРМАНИЯ  🤍") == "германия"
    assert metrics.normalize_code_word("  ИТАЛИЯ 🔥 ") == "италия"
    assert metrics.normalize_code_word("➕➕➕") == "➕➕➕"
    assert metrics.normalize_code_word(None) == ""


def test_open_lead_uses_current_status():
    lead = {"status_id": 76732870}
    assert metrics._max_reached_sort(lead, P, SORT, None) == 60


def test_lost_lead_uses_history_not_lost_sort():
    lead = {"status_id": LOST_STATUS}
    history = [(1, [(76732870, P)], [(76732878, P)]),     # квал → проведена
               (2, [(76732878, P)], [(LOST_STATUS, P)])]  # → отказ
    assert metrics._max_reached_sort(lead, P, SORT, history) == 80


def test_won_lead_is_past_all_stages():
    assert metrics._max_reached_sort({"status_id": WON_STATUS}, P, SORT, []) == 10000


def test_first_sale_ts_takes_earliest_prepay_or_won():
    history = [(50, [], [(PREPAY_STATUS_ID, P)]), (90, [], [(WON_STATUS, P)]),
               (10, [], [(76732870, P)])]
    assert metrics._first_sale_ts(history) == 50
    assert metrics._first_sale_ts([]) is None


@pytest.fixture
def amo(monkeypatch):
    """Подменённый AmoCRM: когорта, история переходов и продажи дня."""
    state = {"cohort": [], "history": {}, "won": []}
    monkeypatch.setattr(metrics, "_pipeline", lambda pid: {
        "statuses": [{"id": sid, "sort": s} for sid, s in STATUSES]})
    monkeypatch.setattr(metrics, "amo_get_leads", lambda pid, df, dt: list(state["cohort"]))
    monkeypatch.setattr(metrics, "dedup_leads", lambda leads: leads)
    monkeypatch.setattr(metrics, "amo_get_status_history",
                        lambda ids: {i: state["history"].get(i, []) for i in ids})
    monkeypatch.setattr(metrics, "amo_get_closed_leads",
                        lambda pid, df, dt: list(state["won"]) if pid == P else [])
    return state


def test_daily_metrics_are_cumulative(amo):
    df, _ = metrics.day_bounds(date(2026, 9, 20))
    amo["cohort"] = [
        {"id": 1, "status_id": 76732734},                  # новая заявка
        {"id": 2, "status_id": 76732738},                  # взят в работу
        {"id": 3, "status_id": 76732870},                  # квалифицирован
        {"id": 4, "status_id": 76732882},                  # в дожиме (после встречи)
        {"id": 5, "status_id": LOST_STATUS},               # отказ после встречи
        {"id": 6, "status_id": WON_STATUS},                # продажа
    ]
    amo["history"] = {5: [(df + 10, [(76732870, P)], [(76732878, P)]),
                          (df + 20, [(76732878, P)], [(LOST_STATUS, P)])]}
    m = metrics.compute_daily_metrics(date(2026, 9, 20))
    assert m["new_request"] == 6
    assert m["lead"] == 5
    assert m["qualified"] == 4
    assert m["consult_scheduled"] == 3
    assert m["consult_done"] == 3      # 4 (дожим), 5 (отказ после встречи), 6 (продажа)


def test_sale_counted_once_on_first_event(amo):
    day = date(2026, 9, 20)
    df, _ = metrics.day_bounds(day)
    amo["won"] = [
        {"id": 10, "price": 1000},    # предоплата была раньше — продажа не этого дня
        {"id": 11, "price": 500},     # первая продажа сегодня
    ]
    amo["history"] = {
        10: [(df - 86400 * 5, [], [(PREPAY_STATUS_ID, P)]), (df + 100, [], [(WON_STATUS, P)])],
        11: [(df + 100, [], [(PREPAY_STATUS_ID, P)])],
    }
    m = metrics.compute_daily_metrics(day)
    assert m["sale"] == 1
    assert m["revenue"] == 500
