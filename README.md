# session-broker

MCP tools so an agent can sign into a website **without seeing your password**.

You stay in the browser you already use. We open that app with your existing profile (cookies and all) so a fresh Chromium does not force a new login. Tools: `sign_in`, `complete_sign_in`, `browse`, `list_sessions`, `revoke`.

Local only. Not a cloud vault.

## Install

Needs [Node](https://nodejs.org) (for `npx`). Nothing else — the first run installs its Python runtime by itself.

### Cursor

Add to `~/.cursor/mcp.json` (merge with your existing servers):

```json
{
  "mcpServers": {
    "session-broker": {
      "command": "npx",
      "args": ["-y", "github:om-divyatej/session-broker"]
    }
  }
}
```

Reload MCP / restart Cursor. You should see `sign_in`, `complete_sign_in`, `browse`.

### Claude Code

```bash
claude mcp add session-broker -- npx -y github:om-divyatej/session-broker
```

First launch takes a minute: it installs `uv` (a Python runner) if you don't have it, then fetches the server. After that it's instant.

## Try it

Ask the agent:

> Use session-broker. Sign into https://example.com/login as session `demo`, then tell me what you see.

1. **Quit the browser if it is already running** (one process per profile).
2. We pick the Chromium-based browser you actually use (freshest cookies: Chrome, Brave, Arc, Edge, Vivaldi, Opera, …) and open **that** profile — you should already be logged in.
3. Only sign in if that site still asks. Do not paste the password in chat.
4. Tell the agent you are signed in.
5. It calls `complete_sign_in`, then `browse`. Leave that window alone while the agent works.

Safari (and Firefox) are not in this path — Playwright cannot reuse Safari's profile. If Safari is your only browser, install Chrome/Brave/Edge or set `SESSION_BROKER_ISOLATED=1` (empty profile, you log in once).

Force a browser with `SESSION_BROKER_BROWSER=chrome|brave|arc|msedge|…`. Isolated empty profiles: `SESSION_BROKER_ISOLATED=1`. Attach to a browser started with remote debugging: `SESSION_BROKER_CDP=http://127.0.0.1:9222`.

## How it is shaped

- **Daemon** on `127.0.0.1:19876` owns Playwright and named profiles.
- **MCP stdio** is a thin client. If the daemon is down, it starts one.

`mcp` is the default command. We open whatever Chromium browser you already live in; we only download Playwright Chromium if none is installed. Sessions live in `~/.session-broker/`. Delete a site with `revoke`, or rm that folder.

## Already have uv?

Skip Node and run the Python entry point directly:

```json
{
  "mcpServers": {
    "session-broker": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/om-divyatej/session-broker", "session-broker"]
    }
  }
}
```

CLI checks:

```bash
npx -y github:om-divyatej/session-broker status
npx -y github:om-divyatej/session-broker serve
```

## Limits

This is session-sharing with your consent. Sites that bind logins to device/IP (Google, banks, some shops) may reject the headless replay. Device-bound cookies cannot be copied off the machine by design.
