from datetime import date, timedelta

import alerts
import build_daily_source
import meta_client
import run_hourly
from amo_client import AmoAPIError


def test_success_updates_yesterday_and_today(monkeypatch):
    calls, sent = [], []
    monkeypatch.setattr(run_hourly, "today_bishkek", lambda: date(2026, 10, 1))
    monkeypatch.setattr(run_hourly, "write_days", lambda a, b: calls.append((a, b)))
    monkeypatch.setattr(run_hourly, "send_alert", sent.append)
    assert run_hourly.main() == 0
    assert calls == [(date(2026, 9, 30), date(2026, 10, 1))]
    assert sent == []


def test_failure_sends_alert_and_exits_nonzero(monkeypatch):
    sent = []

    def boom(a, b):
        raise AmoAPIError("Токен AmoCRM истёк или неверный (HTTP 401)")

    monkeypatch.setattr(run_hourly, "write_days", boom)
    monkeypatch.setattr(run_hourly, "send_alert", sent.append)
    assert run_hourly.main() == 1
    assert len(sent) == 1 and "HTTP 401" in sent[0] and "не обновлена" in sent[0]


def test_mask_secrets(monkeypatch):
    monkeypatch.setattr(alerts, "AMO_TOKEN", "amo-secret-123456")
    assert alerts.mask_secrets("Bearer amo-secret-123456 failed") == "Bearer *** failed"


def test_alerts_disabled_without_config(monkeypatch):
    monkeypatch.setattr(alerts, "ALERT_BOT_TOKEN", "")
    assert alerts.send_alert("test") is False


def test_alert_sent_to_every_chat(monkeypatch):
    posted = []

    class Ok:
        status_code = 200
        text = ""

    monkeypatch.setattr(alerts, "ALERT_BOT_TOKEN", "123:abc-token")
    monkeypatch.setattr(alerts, "ALERT_CHAT_IDS", ["1", "2"])
    monkeypatch.setattr(alerts.requests, "post",
                        lambda url, json, timeout: posted.append(json["chat_id"]) or Ok())
    assert alerts.send_alert("сбой") is True
    assert posted == ["1", "2"]


def test_meta_day_not_started_in_account_tz_is_skipped(monkeypatch):
    """Ночью по Бишкеку «сегодня» для московского аккаунта ещё не наступило."""
    monkeypatch.setattr(build_daily_source, "META_TOKEN", "t")
    monkeypatch.setattr(build_daily_source, "AD_ACCOUNT_ID", "1")
    monkeypatch.setattr(build_daily_source, "get_account_today", lambda acc, tok: date(2026, 9, 24))

    def must_not_call(*a):
        raise AssertionError("insights за будущий день запрашиваться не должны")

    monkeypatch.setattr(build_daily_source, "get_daily_ad_stats", must_not_call)
    assert build_daily_source.build_meta_rows(date(2026, 9, 25)) == []


def test_account_today_uses_account_offset(monkeypatch):
    monkeypatch.setattr(meta_client, "_get", lambda url, params, token: {"timezone_offset_hours_utc": 3})
    today = meta_client.get_account_today("act_1", "t")
    assert isinstance(today, date)
    assert abs((today - date.today()).days) <= 1 or today - date.today() == timedelta(0)
