"""Start the daemon in the background if it is not already up."""

from __future__ import annotations

import subprocess
import sys
import time
import urllib.error
import urllib.request

from session_broker import BASE, HOME, ensure_home


def daemon_ok() -> bool:
    try:
        with urllib.request.urlopen(f"{BASE}/health", timeout=0.6) as r:
            return r.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def ensure_daemon() -> None:
    if daemon_ok():
        return
    ensure_home()
    log = open(HOME / "daemon.log", "a", buffering=1)
    subprocess.Popen(
        [sys.executable, "-m", "session_broker", "serve"],
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    # first run may download Chromium
    for _ in range(180):
        time.sleep(0.5)
        if daemon_ok():
            return
    raise SystemExit(
        f"session-broker daemon failed to start. See {HOME / 'daemon.log'}"
    )
