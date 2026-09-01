#!/usr/bin/env node
"use strict";

// npx entry point. Python runs the actual server, so this bootstraps uv
// (Astral's Python runner) if it is missing, then hands off to it. The point
// is that `npx github:om-divyatej/session-broker` just works with nothing
// preinstalled — no manual uv step.

const { spawnSync } = require("child_process");
const os = require("os");
const path = require("path");
const fs = require("fs");

const FROM = "git+https://github.com/om-divyatej/session-broker";
const isWin = process.platform === "win32";

function binDirs() {
  const home = os.homedir();
  return [
    path.join(home, ".local", "bin"),
    path.join(home, ".cargo", "bin"),
  ];
}

function findUvx() {
  const probe = spawnSync(isWin ? "where" : "which", ["uvx"], { encoding: "utf8" });
  if (probe.status === 0) {
    const hit = (probe.stdout || "").split(/\r?\n/)[0].trim();
    if (hit) return hit;
  }
  for (const dir of binDirs()) {
    const cand = path.join(dir, isWin ? "uvx.exe" : "uvx");
    if (fs.existsSync(cand)) return cand;
  }
  return null;
}

function installUv() {
  process.stderr.write("session-broker: installing uv (one-time, no sudo)...\n");
  // Keep child output on stderr so the MCP stdout stream stays clean.
  if (isWin) {
    return spawnSync(
      'powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"',
      { shell: true, stdio: ["ignore", 2, 2] },
    );
  }
  return spawnSync("sh", ["-c", "curl -LsSf https://astral.sh/uv/install.sh | sh"], {
    stdio: ["ignore", 2, 2],
  });
}

let uvx = findUvx();
if (!uvx) {
  const r = installUv();
  if (r.status !== 0) {
    process.stderr.write(
      "session-broker: could not install uv automatically. Install it once from https://docs.astral.sh/uv/ and retry.\n",
    );
    process.exit(1);
  }
  uvx = findUvx();
}
if (!uvx) {
  process.stderr.write("session-broker: uv installed but uvx was not found. Open a new shell and retry.\n");
  process.exit(1);
}

const env = { ...process.env };
env.PATH = binDirs().join(path.delimiter) + path.delimiter + (env.PATH || "");

const result = spawnSync(uvx, ["--from", FROM, "session-broker", ...process.argv.slice(2)], {
  stdio: "inherit",
  env,
});
process.exit(result.status === null ? 1 : result.status);
