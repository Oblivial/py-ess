"""Resolve the ESS ``userId`` query parameter from explicit configuration."""

from __future__ import annotations

import os

_ENV_VAR = "PYESS_USER_ID"


def get_user_id() -> str:
    """Return the configured ESS user ID or explain how to obtain one."""
    env_value = os.environ.get(_ENV_VAR)
    if env_value:
        return env_value.strip()

    raise ValueError(
        "An ESS user ID is required. Get yours at https://ess.sikt.no/en/api "
        "and pass it as user_id=... or set PYESS_USER_ID."
    )
