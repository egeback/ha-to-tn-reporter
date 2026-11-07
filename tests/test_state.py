import json

import pytest

from reporter import state


@pytest.fixture(autouse=True)
def reset_counters():
    state.health_status["lifetime_success_count"] = 0
    state.health_status["lifetime_error_count"] = 0
    yield
    state.health_status["lifetime_success_count"] = 0
    state.health_status["lifetime_error_count"] = 0


def test_default_state_file_is_on_the_data_volume(monkeypatch):
    monkeypatch.delenv("REPORTER_STATE_FILE", raising=False)
    assert state.state_file() == "/data/state.json"


def test_save_and_load_use_reporter_state_file(tmp_path, monkeypatch):
    path = tmp_path / "sub" / "state.json"
    monkeypatch.setenv("REPORTER_STATE_FILE", str(path))
    state.health_status["lifetime_success_count"] = 42
    state.health_status["lifetime_error_count"] = 3

    state.save_state()

    assert json.loads(path.read_text()) == {"lifetime_success_count": 42, "lifetime_error_count": 3}
    state.health_status["lifetime_success_count"] = 0
    state.health_status["lifetime_error_count"] = 0
    state.load_state()
    assert state.health_status["lifetime_success_count"] == 42
    assert state.health_status["lifetime_error_count"] == 3


def test_load_migrates_legacy_state_from_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state.json").write_text(json.dumps({"lifetime_success_count": 7, "lifetime_error_count": 1}))
    new_path = tmp_path / "data" / "state.json"
    monkeypatch.setenv("REPORTER_STATE_FILE", str(new_path))

    state.load_state()
    assert state.health_status["lifetime_success_count"] == 7

    state.save_state()
    assert json.loads(new_path.read_text())["lifetime_success_count"] == 7


def test_new_state_file_wins_over_legacy(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state.json").write_text(json.dumps({"lifetime_success_count": 7}))
    new_path = tmp_path / "state-new.json"
    new_path.write_text(json.dumps({"lifetime_success_count": 99}))
    monkeypatch.setenv("REPORTER_STATE_FILE", str(new_path))

    state.load_state()
    assert state.health_status["lifetime_success_count"] == 99
