#!/usr/bin/env node
"use strict";

const { spawnSync } = require("child_process");

const FROM = "git+https://github.com/om-divyatej/session-broker";

function has(cmd) {
  const r = spawnSync(cmd, ["--version"], { encoding: "utf8" });
  return r.status === 0;
}

if (!has("uvx") && !has("uv")) {
  console.error("session-broker needs uv (https://docs.astral.sh/uv/)");
  console.error("  curl -LsSf https://astral.sh/uv/install.sh | sh");
  process.exit(1);
}

const args = process.argv.slice(2);
const result = spawnSync(
  "uvx",
  ["--from", FROM, "session-broker", ...args],
  { stdio: "inherit" },
);
process.exit(result.status === null ? 1 : result.status);
