// Thin runner: k6/config.yaml -> k6 -e flags -> `k6 run dist/<scenario>.js`.
// k6 itself can't read yaml; this keeps the project's config-in-yaml rule.
// Usage: node run.mjs <smoke|latency|sweep> [--env BASE_URL=...]
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { parse } from "yaml";

const scenario = process.argv[2];
if (!scenario) {
  console.error("usage: node run.mjs <smoke|latency|sweep> [--env K=V ...]");
  process.exit(2);
}

const cfg = parse(readFileSync("config.yaml", "utf8"));
const sc = cfg.scenarios[scenario];
if (!sc) {
  console.error(`unknown scenario '${scenario}' in config.yaml`);
  process.exit(2);
}

// Extra --env K=V pairs override yaml (e.g. BASE_URL from `make urls`).
const overrides = Object.fromEntries(
  process.argv.slice(3).map((kv) => kv.split("=", 2))
);

const env = {
  BASE_URL: cfg.endpoint.base_url,
  API_PATH: cfg.endpoint.path,
  MODEL: cfg.model,
  MAX_TOKENS: String(cfg.request.max_tokens),
  TEMPERATURE: String(cfg.request.temperature),
  REQ_TIMEOUT_S: String(cfg.request.timeout_s),
  SCENARIO: JSON.stringify(sc),
  ...overrides,
};

if (!env.BASE_URL) {
  console.error("endpoint.base_url is empty — set it in config.yaml or --env BASE_URL=...");
  process.exit(2);
}

const args = ["run", "--summary-export", `results/${scenario}-${Date.now()}.json`];
for (const [k, v] of Object.entries(env)) args.push("-e", `${k}=${v}`);
args.push(`dist/${scenario}.js`);

execFileSync("mkdir", ["-p", "results"]);
execFileSync("k6", args, { stdio: "inherit" });
