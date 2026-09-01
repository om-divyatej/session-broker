"""Stdio MCP process. Auto-starts the daemon, then proxies tools to it."""

from __future__ import annotations

import httpx

from session_broker import BASE
from session_broker.ensure import ensure_daemon

from mcp.server import MCPServer

mcp = MCPServer("session-broker")
http = httpx.Client(base_url=BASE, timeout=120.0)


def _err(e: httpx.HTTPStatusError) -> str:
    try:
        d = e.response.json()
        return d.get("detail") or d.get("message") or e.response.text
    except Exception:
        return e.response.text


@mcp.tool()
def sign_in(name: str, url: str) -> str:
    """Open the user's real installed browser (Chrome, Brave, Arc, Edge, …) with
    their existing profile so they are already logged in. `name` is just a label.
    Chromium locks the profile: if that browser is already running, ask them to
    quit it, then retry. After the signed-in page is visible, call complete_sign_in.
    Never ask for a password. Safari cannot be driven this way.
    """
    try:
        r = http.post(f"/sessions/{name}/sign-in", json={"url": url})
        r.raise_for_status()
        return r.json()["message"]
    except httpx.HTTPStatusError as e:
        return f"Error: {_err(e)}"


@mcp.tool()
def complete_sign_in(name: str) -> str:
    """Call after the user says they finished logging in. Saves the session
    (cookies stay in a local browser profile) and closes the login window.
    """
    try:
        r = http.post(f"/sessions/{name}/complete")
        r.raise_for_status()
        return r.json()["message"]
    except httpx.HTTPStatusError as e:
        return f"Error: {_err(e)}"


@mcp.tool()
def browse(name: str, url: str | None = None) -> str:
    """Read a page using a named session. Omit url to reuse the sign_in url.

    If the result is LOGIN_REQUIRED, call sign_in, wait, complete_sign_in, retry.
    """
    try:
        r = http.post(f"/sessions/{name}/browse", json={"url": url})
        r.raise_for_status()
        data = r.json()
        if data.get("login_required"):
            return data["text"]
        return f"URL: {data['url']}\n\n{data['text']}"
    except httpx.HTTPStatusError as e:
        return f"Error: {_err(e)}"


@mcp.tool()
def list_sessions() -> str:
    """List saved website sessions and whether a login window is open."""
    try:
        r = http.get("/sessions")
        r.raise_for_status()
        rows = r.json()["sessions"]
        if not rows:
            return "No sessions yet."
        lines = []
        for s in rows:
            flags = []
            if s.get("signing_in"):
                flags.append("signing-in")
            elif s.get("open"):
                flags.append("open")
            flag = f" ({', '.join(flags)})" if flags else ""
            lines.append(f"- {s['name']}: {s.get('url', '')}{flag}")
        return "\n".join(lines)
    except httpx.HTTPStatusError as e:
        return f"Error: {_err(e)}"


@mcp.tool()
def revoke(name: str) -> str:
    """Delete a named session and its local browser profile."""
    try:
        r = http.delete(f"/sessions/{name}")
        r.raise_for_status()
        return r.json()["message"]
    except httpx.HTTPStatusError as e:
        return f"Error: {_err(e)}"


def run_mcp() -> None:
    ensure_daemon()
    mcp.run()
