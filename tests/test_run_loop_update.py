import subprocess

import pytest

import run_loop


class Git:
    """Подменённый git: ответы по первой команде; HEAD меняется после pull."""

    def __init__(self, pull_rc=0, changed="", new_head="bbbbbbb"):
        self.pull_rc, self.changed, self.new_head = pull_rc, changed, new_head
        self.head = "aaaaaaa"
        self.calls = []

    def __call__(self, *args, timeout=120):
        self.calls.append(args)
        cmd = args[0]
        out, rc = "", 0
        if cmd == "rev-parse" and args[1] == "HEAD":
            out = self.head
        elif cmd == "pull":
            rc = self.pull_rc
            if rc == 0:
                self.head = self.new_head
            else:
                out = "fatal: could not read Username"
        elif cmd == "diff":
            out = self.changed
        return subprocess.CompletedProcess(args, rc, stdout=out, stderr="")


@pytest.fixture
def logs(monkeypatch):
    lines = []
    monkeypatch.setattr(run_loop, "log", lines.append)
    return lines


def test_no_changes_no_restart(monkeypatch, logs):
    git = Git(new_head="aaaaaaa")
    monkeypatch.setattr(run_loop, "_git", git)
    assert run_loop.update_code() is False
    assert logs == []


def test_code_change_without_restart(monkeypatch, logs):
    monkeypatch.setattr(run_loop, "_git", Git(changed="metrics.py\nsheet_builder.py"))
    assert run_loop.update_code() is False
    assert "aaaaaaa -> bbbbbbb" in logs[0]


def test_loop_change_requests_restart(monkeypatch, logs):
    monkeypatch.setattr(run_loop, "_git", Git(changed="run_loop.py\nREADME.md"))
    assert run_loop.update_code() is True


def test_pull_failure_keeps_working(monkeypatch, logs):
    monkeypatch.setattr(run_loop, "_git", Git(pull_rc=1))
    assert run_loop.update_code() is False
    assert "could not read Username" in logs[0]


def test_no_git_installed(monkeypatch, logs):
    def missing(*a, **k):
        raise FileNotFoundError("git")
    monkeypatch.setattr(run_loop, "_git", missing)
    assert run_loop.update_code() is False
    assert "пропущено" in logs[0]


def test_restart_exits_with_code_3(monkeypatch, logs):
    monkeypatch.setattr(run_loop, "update_code", lambda: True)
    monkeypatch.setattr(run_loop, "run_once", lambda: pytest.fail("прогон на старом коде"))
    with pytest.raises(SystemExit) as e:
        run_loop.update_and_run()
    assert e.value.code == run_loop.RESTART_CODE
