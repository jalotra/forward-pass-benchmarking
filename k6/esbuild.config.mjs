// Bundle each scenario .ts -> dist/.js for k6's goja runtime.
// k6 modules ("k6", "k6/*") are runtime-provided — keep them external.
import { build } from "esbuild";
import { readdirSync } from "node:fs";

const scenarios = readdirSync("src")
  .filter((f) => f.endsWith(".ts") && !f.startsWith("lib/"))
  .map((f) => `src/${f}`);

await build({
  entryPoints: scenarios,
  outdir: "dist",
  bundle: true,
  format: "esm",
  platform: "neutral",
  target: "es2020",
  external: ["k6", "k6/*"],
  logLevel: "info",
});
