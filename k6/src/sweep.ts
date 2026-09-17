// Sweep: ramp VUs through config stages (1->2->4->8->16->32 by default) to
// find the throughput knee and watch latency degrade under concurrency.
import { Options } from "k6/options";
import { chatOnce, env } from "./lib/client";

const sc = env().scenario;
const stageVus = (sc.stage_vus as number[]) ?? [1, 2, 4, 8, 16, 32];
const stageSec = (sc.stage_duration_s as number) ?? 60;
const stopSec = (sc.graceful_stop_s as number) ?? 30;

export const options: Options = {
  scenarios: {
    sweep: {
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
