

import pytest

from pyess.userid import get_user_id


def test_env_var_takes_precedence(monkeypatch, tmp_path):
    monkeypatch.setenv("PYESS_USER_ID", "explicit-id")
    assert get_user_id() == "explicit-id"


def test_missing_user_id_explains_how_to_configure_it(monkeypatch):
    monkeypatch.delenv("PYESS_USER_ID", raising=False)
    with pytest.raises(ValueError, match=r"https://ess\.sikt\.no/en/api"):
        get_user_id()
