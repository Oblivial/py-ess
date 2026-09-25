"""Generation and persistence of the ``userId`` query parameter.

The ESS API requires a ``userId`` query parameter on every request. Per the API
docs this is **not** used for authentication - it is only used for usage
statistics - so instead of forcing every caller to register for an account and
paste a UUID around, ``py-ess`` follows the common "client identifier" pattern
used by many SDKs (e.g. npm, pip, Homebrew analytics):

* A stable, anonymous, per-installation identifier is generated once
  (``uuid4``) and cached on disk under the user's standard config directory.
* The identifier is prefixed with ``py-ess-`` so that request logs on the
  server side clearly show which client/library produced the traffic, while
  the suffix (a random UUID4) keeps individual installations distinguishable
  without leaking any personal information (no hostname, username, or IP is
  embedded).

Callers can always override this behavior by passing an explicit ``user_id``
to :class:`pyess.client.ESS`, or by setting the ``PYESS_USER_ID`` environment
variable, which takes precedence over the cached/generated value.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

try:
    from platformdirs import user_config_dir
except ImportError:  # pragma: no cover - fallback if platformdirs is missing
    def user_config_dir(appname: str) -> str:
        base = os.environ.get("APPDATA") or os.path.expanduser("~/.config")
        return str(Path(base) / appname)

_ENV_VAR = "PYESS_USER_ID"
_APP_NAME = "py-ess"
_ID_FILENAME = "user_id"
_PREFIX = "py-ess"


def _config_dir() -> Path:
    return Path(user_config_dir(_APP_NAME))


def _id_file() -> Path:
    return _config_dir() / _ID_FILENAME


def _generate_suffix() -> str:
    return str(uuid.uuid4())


def get_user_id(cache: bool = True) -> str:
    """Return a stable, anonymous identifier to send as the ``userId`` param.

    Resolution order:

    1. The ``PYESS_USER_ID`` environment variable, if set.
    2. A previously cached identifier on disk (``<config_dir>/py-ess/user_id``).
    3. A freshly generated ``py-ess-<uuid4>`` identifier, cached to disk for
       reuse on subsequent calls (unless ``cache=False``).
    """
    env_value = os.environ.get(_ENV_VAR)
    if env_value:
        return env_value

    id_file = _id_file()
    if id_file.exists():
        cached = id_file.read_text(encoding="utf-8").strip()
        if cached:
            return cached

    generated = f"{_PREFIX}-{_generate_suffix()}"

    if cache:
        try:
            id_file.parent.mkdir(parents=True, exist_ok=True)
            id_file.write_text(generated, encoding="utf-8")
        except OSError:
            # Non-fatal: fall back to an in-memory-only identifier.
            pass

    return generated
