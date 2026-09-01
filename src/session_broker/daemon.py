"""Long-lived Playwright owner. Named sessions live in ~/.session-broker/profiles."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from playwright.async_api import BrowserContext, Playwright, async_playwright
from pydantic import BaseModel

from session_broker import HOME, ensure_home

NAME_RE = re.compile(r"^[a-zA-Z0-9._-]{1,64}$")
META_PATH = HOME / "meta.json"

pw: Playwright | None = None
# live persistent context per session (headed or headless — never both)
live: dict[str, BrowserContext] = {}
headed: set[str] = set()


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


async def _close(name: str) -> None:
    ctx = live.pop(name, None)
    headed.discard(name)
    if ctx:
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


async def _open(name: str, *, headless: bool) -> BrowserContext:
    if not pw:
        raise HTTPException(503, "playwright not started")
    existing = live.get(name)
    want_headed = not headless
    if existing and ((name in headed) == want_headed):
        return existing
    await _close(name)
    ctx = await pw.chromium.launch_persistent_context(
        str(_profile(name)),
        headless=headless,
        viewport={"width": 1280, "height": 860},
    )
    live[name] = ctx
    if want_headed:
        headed.add(name)
    return ctx


app = FastAPI()


@app.on_event("startup")
async def _startup():
    global pw
    ensure_home()
    _ensure_chromium()
    pw = await async_playwright().start()


@app.on_event("shutdown")
async def _shutdown():
    for name in list(live):
        await _close(name)
    if pw:
        await pw.stop()


@app.get("/health")
async def health():
    return {"ok": True, "sessions": list(_meta()), "open": list(live), "signing_in": list(headed)}


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
    ctx = await _open(name, headless=False)
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    await page.goto(body.url, wait_until="domcontentloaded", timeout=45000)
    _touch(name, body.url)
    return {
        "ok": True,
        "message": (
            f"Browser opened for session '{name}' at {body.url}. "
            "Tell the user to log in in that window, then call complete_sign_in. "
            "Never ask for their password."
        ),
    }


@app.post("/sessions/{name}/complete")
async def complete(name: str):
    name = _check_name(name)
    if name not in live:
        raise HTTPException(400, "no browser is open for this session; call sign_in first")
    ctx = live[name]
    cookies = await ctx.cookies()
    await _close(name)
    _touch(name)
    hosts = sorted({c.get("domain", "") for c in cookies})
    return {
        "ok": True,
        "cookie_count": len(cookies),
        "domains": hosts,
        "message": (
            f"Captured {len(cookies)} cookies for '{name}'. "
            "The headed window is closed; browse will reuse this profile."
        ),
    }


@app.post("/sessions/{name}/browse")
async def browse(name: str, body: BrowseIn):
    name = _check_name(name)
    meta = _meta()
    url = body.url or (meta.get(name) or {}).get("url")
    if not url:
        raise HTTPException(400, "pass url, or sign_in first so a default url is stored")
    # reuse headed window if user is still in it; else headless on the same profile
    if name in live:
        ctx = live[name]
    else:
        ctx = await _open(name, headless=True)
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
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
    shutil.rmtree(_profile(name), ignore_errors=True)
    return {"ok": True, "message": f"revoked '{name}'"}
