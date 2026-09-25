import pytest

import sheets_client as sc


class FakeWorksheet:
    title = "crm_daily"

    def __init__(self, values):
        self.values = values
        self.row_count = 1000
        self.updates = []

    def get_all_values(self):
        return self.values

    def add_rows(self, n):
        self.row_count += n

    def batch_update(self, data, value_input_option=None):
        self.updates.extend(data)


HEADERS = ["date", "value"]


def test_upsert_updates_existing_and_appends_new():
    ws = FakeWorksheet([HEADERS, ["2026-09-19", "1"], ["2026-09-20", "2"]])
    inserted, updated = sc._upsert(ws, HEADERS, ["date"], [
        {"date": "2026-09-20", "value": 5},
        {"date": "2026-09-21", "value": 7},
    ])
    assert (inserted, updated) == (1, 1)
    assert {"range": "A3:B3", "values": [["2026-09-20", 5]]} in ws.updates
    assert {"range": "A4:B4", "values": [["2026-09-21", 7]]} in ws.updates


def test_upsert_refuses_foreign_header():
    ws = FakeWorksheet([["что-то", "другое"]])
    with pytest.raises(RuntimeError, match="первая строка"):
        sc._upsert(ws, HEADERS, ["date"], [{"date": "2026-09-20", "value": 1}])
    assert ws.updates == []


def test_credentials_required():
    with pytest.raises(RuntimeError, match="GOOGLE_SERVICE_ACCOUNT_JSON"):
        sc._credentials("")


def test_credentials_bad_json_content():
    with pytest.raises(RuntimeError, match="не читается как JSON"):
        sc._credentials("{не json")


def test_credentials_from_content_and_from_path(monkeypatch):
    calls = []
    monkeypatch.setattr(sc.Credentials, "from_service_account_info",
                        lambda info, scopes: calls.append(("info", info["type"])))
    monkeypatch.setattr(sc.Credentials, "from_service_account_file",
                        lambda path, scopes: calls.append(("file", path)))
    sc._credentials('  {"type": "service_account"}  ')
    sc._credentials("/keys/sa.json")
    assert calls == [("info", "service_account"), ("file", "/keys/sa.json")]
