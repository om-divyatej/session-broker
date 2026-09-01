"""Pick the Chromium-based browser the user actually uses (existing logins)."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class InstalledBrowser:
    name: str
    executable: Path
    user_data_dir: Path


def _first_existing(paths: list[Path]) -> Path | None:
    for p in paths:
        if p.exists():
            return p
    return None


def _home() -> Path:
    return Path.home()


def _local_app() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(_home() / "AppData/Local")))


# (name, mac_app_binary, mac_support_dir, linux_bins, linux_config, win_bins, win_user_data)
def _catalog() -> list[InstalledBrowser]:
    found: list[InstalledBrowser] = []
    if sys.platform == "darwin":
        specs = [
            ("chrome", "Google Chrome.app/Contents/MacOS/Google Chrome", "Google/Chrome"),
            ("chrome-canary", "Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary", "Google/Chrome Canary"),
            ("brave", "Brave Browser.app/Contents/MacOS/Brave Browser", "BraveSoftware/Brave-Browser"),
            ("msedge", "Microsoft Edge.app/Contents/MacOS/Microsoft Edge", "Microsoft Edge"),
            ("arc", "Arc.app/Contents/MacOS/Arc", "Arc/User Data"),
            ("vivaldi", "Vivaldi.app/Contents/MacOS/Vivaldi", "Vivaldi"),
            ("opera", "Opera.app/Contents/MacOS/Opera", "com.operasoftware.Opera"),
            ("chromium", "Chromium.app/Contents/MacOS/Chromium", "Chromium"),
            ("dia", "Dia.app/Contents/MacOS/Dia", "Dia"),
        ]
        for name, exe, support in specs:
            binary = Path("/Applications") / exe
            if binary.exists():
                found.append(
                    InstalledBrowser(name, binary, _home() / "Library/Application Support" / support)
                )
        return found

    if sys.platform == "win32":
        local = _local_app()
        pf = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
        pf86 = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
        specs = [
            ("chrome", [pf / "Google/Chrome/Application/chrome.exe", local / "Google/Chrome/Application/chrome.exe"], local / "Google/Chrome/User Data"),
            ("brave", [pf / "BraveSoftware/Brave-Browser/Application/brave.exe", pf86 / "BraveSoftware/Brave-Browser/Application/brave.exe", local / "BraveSoftware/Brave-Browser/Application/brave.exe"], local / "BraveSoftware/Brave-Browser/User Data"),
            ("msedge", [pf86 / "Microsoft/Edge/Application/msedge.exe", pf / "Microsoft/Edge/Application/msedge.exe"], local / "Microsoft/Edge/User Data"),
            ("vivaldi", [local / "Vivaldi/Application/vivaldi.exe"], local / "Vivaldi/User Data"),
            ("opera", [local / "Programs/Opera/opera.exe"], local / "Opera Software/Opera Stable"),
        ]
        for name, bins, data in specs:
            exe = _first_existing(bins)
            if exe:
                found.append(InstalledBrowser(name, exe, data))
        return found

    specs = [
        ("chrome", ["/usr/bin/google-chrome-stable", "/usr/bin/google-chrome"], ".config/google-chrome"),
        ("brave", ["/usr/bin/brave-browser", "/usr/bin/brave-browser-stable", "/usr/bin/brave", "/snap/bin/brave"], ".config/BraveSoftware/Brave-Browser"),
        ("msedge", ["/usr/bin/microsoft-edge", "/usr/bin/microsoft-edge-stable"], ".config/microsoft-edge"),
        ("chromium", ["/usr/bin/chromium", "/usr/bin/chromium-browser", "/snap/bin/chromium"], ".config/chromium"),
        ("vivaldi", ["/usr/bin/vivaldi", "/usr/bin/vivaldi-stable"], ".config/vivaldi"),
        ("opera", ["/usr/bin/opera"], ".config/opera"),
    ]
    for name, bins, cfg in specs:
        exe = _first_existing([Path(b) for b in bins])
        if exe:
            found.append(InstalledBrowser(name, exe, _home() / cfg))
    return found


def _cookie_mtime(browser: InstalledBrowser) -> float:
    roots = [
        browser.user_data_dir / "Default" / "Network" / "Cookies",
        browser.user_data_dir / "Default" / "Cookies",
        browser.user_data_dir / "Cookies",
    ]
    times = [p.stat().st_mtime for p in roots if p.exists()]
    if times:
        return max(times)
    if browser.user_data_dir.exists():
        return browser.user_data_dir.stat().st_mtime
    return 0.0


def _os_default_name() -> str | None:
    """Best-effort default browser name, used only as a tie-break."""
    try:
        if sys.platform == "darwin":
            r = subprocess.run(
                [
                    "osascript",
                    "-l",
                    "JavaScript",
                    "-e",
                    'ObjC.import("CoreServices"); ObjC.unwrap($.LSCopyDefaultHandlerForURLScheme($("http")))',
                ],
                capture_output=True,
                text=True,
                timeout=2,
            )
            bid = (r.stdout or "").strip().lower()
            mapping = {
                "com.google.chrome": "chrome",
                "com.brave.browser": "brave",
                "com.microsoft.edgemac": "msedge",
                "company.thebrowser.browser": "arc",
                "com.apple.safari": None,  # Playwright cannot drive Safari
                "org.mozilla.firefox": None,
            }
            for prefix, name in mapping.items():
                if prefix in bid:
                    return name
            if "chrome" in bid:
                return "chrome"
            if "brave" in bid:
                return "brave"
            if "edge" in bid:
                return "msedge"
            if "arc" in bid:
                return "arc"
            return None
        if sys.platform.startswith("linux"):
            r = subprocess.run(
                ["xdg-settings", "get", "default-web-browser"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            desk = (r.stdout or "").lower()
            for name in ("brave", "chrome", "chromium", "msedge", "vivaldi", "opera"):
                if name in desk:
                    return "msedge" if name == "msedge" else name
            if "microsoft-edge" in desk:
                return "msedge"
            if "google-chrome" in desk:
                return "chrome"
    except Exception:
        return None
    return None


def installed() -> list[InstalledBrowser]:
    return _catalog()


def pick_browser() -> InstalledBrowser | None:
    want = os.environ.get("SESSION_BROKER_BROWSER", "").strip().lower()
    all_found = installed()
    if want:
        for b in all_found:
            if b.name == want:
                return b
        return None
    if not all_found:
        return None
    default = _os_default_name()
    # The one they actually use: freshest cookie jar, OS default as a boost.
    def score(b: InstalledBrowser) -> tuple:
        return (_cookie_mtime(b) + (10_000_000 if b.name == default else 0), b.name)

    return max(all_found, key=score)
