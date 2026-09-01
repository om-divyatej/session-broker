"""Long-lived Playwright owner. Uses the user's real browser profile so existing logins apply."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright
from pydantic import BaseModel

from session_broker import HOME, ensure_home
from session_broker.browsers import pick_browser

NAME_RE = re.compile(r"^[a-zA-Z0-9._-]{1,64}$")
META_PATH = HOME / "meta.json"
ISOLATED = os.environ.get("SESSION_BROKER_ISOLATED", "").strip() in ("1", "true", "yes")

pw: Playwright | None = None
live: dict[str, BrowserContext] = {}
headed: set[str] = set()
active_channel: str = "unknown"
# one shared context when using the user's real browser profile
system_ctx: BrowserContext | None = None
cdp_browser: Browser | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _meta() -> dict:
    ensure_home()
    if META_PATH.exists():
        return json.loads(META_PATH.read_text())
    return {}


def _save_meta(data: dict) -> None:
    ensure_home()
    META_PATH.write_text(json.dumps(data, indent=2))


def _check_name(name: str) -> str:
    if not NAME_RE.match(name):
        raise HTTPException(400, "name must be 1-64 chars: letters, digits, . _ -")
    return name


def _profile(name: str) -> Path:
    return ensure_home() / "profiles" / name


def _touch(name: str, url: str | None = None) -> dict:
    data = _meta()
    row = data.get(name, {"created": _now()})
    if url:
        row["url"] = url
    row["last_used"] = _now()
    data[name] = row
    _save_meta(data)
    return row


def _lock_error(err: Exception) -> bool:
    s = str(err).lower()
    return any(
        x in s
        for x in ("singleton", "user data directory is already in use", "process is already running", "lock")
    )


async def _close(name: str) -> None:
    ctx = live.pop(name, None)
    headed.discard(name)
    if ctx and ctx is not system_ctx:
        try:
            await ctx.close()
        except Exception:
            pass


def _ensure_chromium() -> None:
    marker = ensure_home() / ".chromium"
    if marker.exists():
        return
    subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        check=True,
    )
    marker.write_text("ok\n")


async def _launch_isolated(path: Path, *, headless: bool) -> BrowserContext:
    global active_channel
    if not pw:
        raise HTTPException(503, "playwright not started")
    env = os.environ.get("SESSION_BROKER_CHANNEL", "").strip()
    channels: list[str | None]
    if env in ("chromium", "bundled"):
        channels = [None]
    elif env:
        channels = [env]
    else:
        channels = ["chrome", "msedge", None]
    errors: list[str] = []
    for ch in channels:
        kwargs: dict = {"headless": headless, "viewport": {"width": 1280, "height": 860}}
        if ch:
            kwargs["channel"] = ch
        else:
            _ensure_chromium()
        try:
            ctx = await pw.chromium.launch_persistent_context(str(path), **kwargs)
            active_channel = ch or "chromium"
            return ctx
        except Exception as e:
            errors.append(f"{ch or 'chromium'}: {e}")
    raise HTTPException(500, "No browser available. " + " | ".join(errors[-3:]))


async def _launch_system() -> BrowserContext:
    """Open the user's everyday Chromium browser so existing logins are present."""
    global active_channel, system_ctx, cdp_browser
    if not pw:
        raise HTTPException(503, "playwright not started")
    if system_ctx:
        return system_ctx

    cdp = os.environ.get("SESSION_BROKER_CDP", "").strip()
    if cdp:
        cdp_browser = await pw.chromium.connect_over_cdp(cdp)
        system_ctx = cdp_browser.contexts[0] if cdp_browser.contexts else await cdp_browser.new_context()
        active_channel = "cdp"
        return system_ctx

    found = pick_browser()
    if not found:
        return await _launch_isolated(_profile("_default"), headless=False)

    try:
        system_ctx = await pw.chromium.launch_persistent_context(
            str(found.user_data_dir),
            executable_path=str(found.executable),
            headless=False,
            viewport={"width": 1280, "height": 860},
        )
        active_channel = found.name
        return system_ctx
    except Exception as e:
        if _lock_error(e):
            raise HTTPException(
                409,
                f"{found.name} is already open and its profile is locked. "
                f"Quit {found.name} completely, then try again — we reopen YOUR {found.name} "
                "so you are already logged in. Leave it closed while the agent works, "
                "or start it with --remote-debugging-port=9222 and set SESSION_BROKER_CDP.",
            ) from e
        raise HTTPException(500, f"Failed to open {found.name}: {e}") from e


async def _ctx_for(name: str, *, headless: bool) -> BrowserContext:
    if not ISOLATED:
        ctx = await _launch_system()
        live[name] = ctx
        headed.add(name)
        return ctx
    existing = live.get(name)
    want_headed = not headless
    if existing and ((name in headed) == want_headed):
        return existing
    await _close(name)
    ctx = await _launch_isolated(_profile(name), headless=headless)
    live[name] = ctx
    if want_headed:
        headed.add(name)
    return ctx


app = FastAPI()


@app.on_event("startup")
async def _startup():
    global pw
    ensure_home()
    pw = await async_playwright().start()


@app.on_event("shutdown")
async def _shutdown():
    global system_ctx, cdp_browser
    if ISOLATED:
        for name in list(live):
            await _close(name)
    elif system_ctx and not cdp_browser:
        try:
            await system_ctx.close()
        except Exception:
            pass
    system_ctx = None
    cdp_browser = None
    if pw:
        await pw.stop()


@app.get("/health")
async def health():
    found = pick_browser()
    return {
        "ok": True,
        "browser": active_channel,
        "isolated": ISOLATED,
        "detected": found.name if found else None,
        "sessions": list(_meta()),
        "open": list(live),
        "signing_in": list(headed),
    }


class SignInIn(BaseModel):
    url: str


class BrowseIn(BaseModel):
    url: str | None = None


@app.get("/sessions")
async def list_sessions():
    data = _meta()
    return {
        "sessions": [
            {
                "name": n,
                **row,
                "open": n in live,
                "signing_in": n in headed,
            }
            for n, row in data.items()
        ]
    }


@app.post("/sessions/{name}/sign-in")
async def sign_in(name: str, body: SignInIn):
    name = _check_name(name)
    ctx = await _ctx_for(name, headless=False)
    page = await ctx.new_page() if not ISOLATED else (ctx.pages[0] if ctx.pages else await ctx.new_page())
    await page.goto(body.url, wait_until="domcontentloaded", timeout=45000)
    _touch(name, body.url)
    found = pick_browser()
    which = found.name if found and not ISOLATED else active_channel
    extra = ""
    if not ISOLATED:
        extra = (
            f" This is your real {which} profile — if you were already logged in, you are done. "
            f"If {which} was already running, quit it and retry."
        )
    return {
        "ok": True,
        "message": (
            f"Opened {which} for '{name}' at {body.url}.{extra} "
            "When the page is signed in, call complete_sign_in. Never ask for their password."
        ),
    }


@app.post("/sessions/{name}/complete")
async def complete(name: str):
    name = _check_name(name)
    if name not in live and system_ctx is None:
        raise HTTPException(400, "no browser is open for this session; call sign_in first")
    ctx = live.get(name) or system_ctx
    if ctx is None:
        raise HTTPException(400, "no browser is open for this session; call sign_in first")
    cookies = await ctx.cookies()
    if ISOLATED:
        await _close(name)
        reuse = "The window is closed; browse will reopen this isolated profile."
    else:
        headed.discard(name)
        reuse = "Your browser stays open so follow-up browse uses the same logged-in profile."
    _touch(name)
    hosts = sorted({c.get("domain", "") for c in cookies})
    return {
        "ok": True,
        "cookie_count": len(cookies),
        "domains": hosts,
        "message": f"Session '{name}' ready ({len(cookies)} cookies). {reuse}",
    }


@app.post("/sessions/{name}/browse")
async def browse(name: str, body: BrowseIn):
    name = _check_name(name)
    meta = _meta()
    url = body.url or (meta.get(name) or {}).get("url")
    if not url:
        raise HTTPException(400, "pass url, or sign_in first so a default url is stored")
    if name in live:
        ctx = live[name]
    elif system_ctx is not None:
        ctx = system_ctx
    else:
        ctx = await _ctx_for(name, headless=ISOLATED)
    page = await ctx.new_page() if not ISOLATED else (ctx.pages[0] if ctx.pages else await ctx.new_page())
    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    await asyncio.sleep(4)
    _touch(name, url)
    if "/sign-in" in page.url or "/login" in page.url:
        return {
            "ok": False,
            "login_required": True,
            "url": page.url,
            "text": (
                f"LOGIN_REQUIRED at {page.url}. Call sign_in for '{name}', "
                "wait for the user to finish, then complete_sign_in."
            ),
        }
    text = await page.inner_text("body")
    return {"ok": True, "url": page.url, "text": text[:12000]}


@app.delete("/sessions/{name}")
async def revoke(name: str):
    name = _check_name(name)
    await _close(name)
    data = _meta()
    data.pop(name, None)
    _save_meta(data)
    if ISOLATED:
        shutil.rmtree(_profile(name), ignore_errors=True)
    return {"ok": True, "message": f"revoked '{name}'"}
