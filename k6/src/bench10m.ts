// bench10m: the canonical 10-minute benchmark run. Ramps VUs through the
// config's stage list (6 x 100s = exactly 600s of load by default), holding
// each concurrency level to expose the throughput knee + latency degradation.
import { Options } from "k6/options";
import { chatOnce, env } from "./lib/client";

const sc = env().scenario;
const stageVus = (sc.stage_vus as number[]) ?? [1, 2, 4, 8, 16, 32];
const stageSec = (sc.stage_duration_s as number) ?? 100;
const stopSec = (sc.graceful_stop_s as number) ?? 10;

export const options: Options = {
  scenarios: {
    bench10m: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: stageVus.map((vus) => ({
        target: vus,
        duration: `${stageSec}s`,
      })),
      gracefulStop: `${stopSec}s`,
    },
  },
};

export default function (): void {
  chatOnce(env(), __VU, __ITER);
}
