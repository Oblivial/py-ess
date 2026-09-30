import os
from pathlib import Path


def _load_local_env() -> None:
    env_path = Path(__file__).parents[1] / ".env"
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        value = value.strip().strip("\"'")
        if name.strip() and value and name.strip() not in os.environ:
            os.environ[name.strip()] = value


_load_local_env()