import pytest
import requests

import amo_client
from amo_client import AmoAPIError, _amo_get, _amo_get_all


class FakeResponse:
    def __init__(self, status, payload=None, headers=None, text=""):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


@pytest.fixture
def http(monkeypatch):
    """Очередь ответов для requests.get; sleep не ждёт по-настоящему."""
    state = {"queue": [], "calls": 0, "sleeps": []}

    def fake_get(url, **kwargs):
        state["calls"] += 1
        item = state["queue"].pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(amo_client.requests, "get", fake_get)
    monkeypatch.setattr(amo_client.time, "sleep", lambda s: state["sleeps"].append(s))
    return state


def test_ok_returns_json(http):
    http["queue"] = [FakeResponse(200, {"a": 1})]
    assert _amo_get("leads") == {"a": 1}


def test_204_means_no_data(http):
    http["queue"] = [FakeResponse(204)]
    assert _amo_get("leads") == {}


def test_401_raises_without_retry(http):
    http["queue"] = [FakeResponse(401)]
    with pytest.raises(AmoAPIError, match="401"):
        _amo_get("leads")
    assert http["calls"] == 1


def test_other_4xx_raises_without_retry(http):
    http["queue"] = [FakeResponse(400, text="More params given than allowed")]
    with pytest.raises(AmoAPIError, match="400"):
        _amo_get("events")
    assert http["calls"] == 1


def test_429_retried_with_retry_after(http):
    http["queue"] = [FakeResponse(429, headers={"Retry-After": "10"}), FakeResponse(200, {"ok": 1})]
    assert _amo_get("leads") == {"ok": 1}
    assert http["sleeps"] == [10]


def test_network_error_then_success(http):
    http["queue"] = [requests.ConnectionError("boom"), FakeResponse(200, {"ok": 1})]
    assert _amo_get("leads") == {"ok": 1}


def test_5xx_gives_up_after_all_attempts(http):
    http["queue"] = [FakeResponse(502) for _ in range(amo_client.AMO_ATTEMPTS)]
    with pytest.raises(AmoAPIError, match="502"):
        _amo_get("leads")
    assert http["calls"] == amo_client.AMO_ATTEMPTS
    assert http["sleeps"] == [3, 6, 12]


def test_get_all_error_mid_pagination_is_not_swallowed(http):
    """Раньше ошибка на 2-й странице давала неполный список без предупреждения."""
    page1 = FakeResponse(200, {"_embedded": {"leads": [{"id": i} for i in range(250)]}})
    http["queue"] = [page1] + [FakeResponse(500) for _ in range(amo_client.AMO_ATTEMPTS)]
    with pytest.raises(AmoAPIError):
        _amo_get_all("leads")


def test_get_all_stops_on_short_page(http):
    http["queue"] = [FakeResponse(200, {"_embedded": {"leads": [{"id": 1}, {"id": 2}]}})]
    assert [l["id"] for l in _amo_get_all("leads")] == [1, 2]
