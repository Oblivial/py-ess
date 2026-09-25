

from pyess.userid import get_user_id


def test_env_var_takes_precedence(monkeypatch, tmp_path):
    monkeypatch.setenv("PYESS_USER_ID", "explicit-id")
    assert get_user_id() == "explicit-id"


def test_generated_id_has_prefix_and_is_cached(monkeypatch, tmp_path):
    monkeypatch.delenv("PYESS_USER_ID", raising=False)
    monkeypatch.setattr("pyess.userid._config_dir", lambda: tmp_path)

    first = get_user_id()
    assert first.startswith("py-ess-")

    second = get_user_id()
    assert second == first  # cached, stable across calls

    cached_file = tmp_path / "user_id"
    assert cached_file.exists()
    assert cached_file.read_text(encoding="utf-8").strip() == first
