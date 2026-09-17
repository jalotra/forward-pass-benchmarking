// Latency: single VU, fixed shape — best-case E2E latency (pairs with
// server-side TTFT/TPOT histograms scraped by the in-container telemetry).
import { Options } from "k6/options";
import { chatOnce, env } from "./lib/client";

export const options: Options = {
  vus: env().scenario.vus as number,
  iterations: env().scenario.iterations as number,
};

export default function (): void {
  chatOnce(env(), __VU, __ITER);
}
