# session-broker

MCP tools so an agent can sign into a website **without seeing your password**.

You log in in a real browser window. Cookies stay in a local Chrome profile (`~/.session-broker`). The model only gets tools: `sign_in`, `complete_sign_in`, `browse`, `list_sessions`, `revoke`.

Local only. Not a cloud vault.

## Install

Needs [uv](https://docs.astral.sh/uv/) (one-time):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Cursor

Add to `~/.cursor/mcp.json` (merge with your existing servers):

```json
{
  "mcpServers": {
    "session-broker": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/om-divyatej/session-broker",
        "session-broker"
      ]
    }
  }
}
```

Same thing via npx (still runs uvx under the hood):

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
claude mcp add session-broker -- uvx --from git+https://github.com/om-divyatej/session-broker session-broker
```

## Try it

Ask the agent:

> Use session-broker. Sign into https://example.com/login as session `demo`, then tell me what you see.

1. A Chromium window opens.
2. You log in there. Do not paste the password in chat.
3. Tell the agent you are signed in.
4. It calls `complete_sign_in`, then `browse`. Later chats reuse that session.

## CLI

```bash
uvx --from git+https://github.com/om-divyatej/session-broker session-broker status
uvx --from git+https://github.com/om-divyatej/session-broker session-broker serve
```

`mcp` is the default command (what Cursor/Claude spawn). First run downloads Chromium into the Playwright cache; give it a minute.

## How it is shaped

- **Daemon** on `127.0.0.1:19876` owns Playwright and named profiles.
- **MCP stdio** is a thin client. If the daemon is down, it starts one.

Sessions live in `~/.session-broker/`. Delete a site with `revoke`, or rm that folder.

## Limits

This is session-sharing with your consent. Sites that bind logins to device/IP (Google, banks, some shops) may reject the headless replay. Device-bound cookies cannot be copied off the machine by design.
