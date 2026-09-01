from __future__ import annotations

import os
from pathlib import Path

HOME = Path(os.environ.get("SESSION_BROKER_HOME", Path.home() / ".session-broker"))
PORT = int(os.environ.get("SESSION_BROKER_PORT", "19876"))
BASE = f"http://127.0.0.1:{PORT}"


def ensure_home() -> Path:
    HOME.mkdir(parents=True, exist_ok=True)
    (HOME / "profiles").mkdir(exist_ok=True)
    return HOME
