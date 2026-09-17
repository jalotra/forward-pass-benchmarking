// Smoke: 1 VU x few iterations — correctness only, run before every bench run.
import { Options } from "k6/options";
import { chatOnce, env } from "./lib/client";

export const options: Options = {
  vus: env().scenario.vus as number,
  iterations: env().scenario.iterations as number,
};

export default function (): void {
  chatOnce(env(), __VU, __ITER);
}
