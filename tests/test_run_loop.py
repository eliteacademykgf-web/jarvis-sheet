import importlib
import os
from datetime import datetime

import run_loop


def test_next_run_is_the_coming_05():
    assert run_loop.next_run(datetime(2026, 9, 25, 14, 3)) == datetime(2026, 9, 25, 14, 5)
    assert run_loop.next_run(datetime(2026, 9, 25, 14, 5)) == datetime(2026, 9, 25, 15, 5)
    assert run_loop.next_run(datetime(2026, 9, 25, 23, 40)) == datetime(2026, 9, 26, 0, 5)


def test_relative_key_path_resolves_next_to_config(monkeypatch):
    import config
    try:
        monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", "google-key.json")
        importlib.reload(config)
        assert config.GOOGLE_SERVICE_ACCOUNT_JSON == os.path.join(config.HERE, "google-key.json")

        monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", ' {"type": "service_account"}')
        importlib.reload(config)
        assert config.GOOGLE_SERVICE_ACCOUNT_JSON.startswith("{")
    finally:
        monkeypatch.undo()
        importlib.reload(config)
