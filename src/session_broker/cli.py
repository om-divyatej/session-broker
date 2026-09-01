from __future__ import annotations

import argparse
import json
import sys
import urllib.request


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(
        prog="session-broker",
        description="Named website sessions for agents. Password never enters the agent.",
    )
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("mcp", help="stdio MCP server (default; starts the daemon if needed)")
    sub.add_parser("serve", help="run the daemon in the foreground")
    sub.add_parser("status", help="ping the daemon")

    args = p.parse_args(argv)
    cmd = args.cmd or "mcp"

    if cmd == "serve":
        import uvicorn
        from session_broker import PORT
        from session_broker.daemon import app

        uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
        return

    if cmd == "status":
        from session_broker import BASE
        from session_broker.ensure import daemon_ok

        if not daemon_ok():
            print("daemon down")
            sys.exit(1)
        with urllib.request.urlopen(f"{BASE}/health") as r:
            print(json.dumps(json.load(r), indent=2))
        return

    from session_broker.mcp_server import run_mcp

    run_mcp()


if __name__ == "__main__":
    main()
