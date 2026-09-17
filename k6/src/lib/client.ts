// Shared k6 helpers: config from -e env, chat-completion POST, custom metrics.
import http from "k6/http";
import { Trend, Counter, Rate } from "k6/metrics";

export const e2eMs = new Trend("e2e_ms", true);
export const outputTokens = new Counter("output_tokens");
export const tokPerSec = new Trend("completion_tps", true);
export const failed = new Rate("request_failed");
export const respByStatus = new Counter("responses_by_status");

export interface BenchEnv {
  baseUrl: string;
  path: string;
  model: string;
  maxTokens: number;
  temperature: number;
  timeoutS: number;
  scenario: Record<string, unknown>;
}

export function env(): BenchEnv {
  return {
    baseUrl: (__ENV.BASE_URL || "").replace(/\/$/, ""),
    path: __ENV.API_PATH || "/v1/chat/completions",
    model: __ENV.MODEL,
    maxTokens: Number(__ENV.MAX_TOKENS || "256"),
    temperature: Number(__ENV.TEMPERATURE || "0"),
    timeoutS: Number(__ENV.REQ_TIMEOUT_S || "120"),
    scenario: JSON.parse(__ENV.SCENARIO || "{}"),
  };
}

const PROMPTS = [
  "Explain the difference between TCP and UDP to a junior engineer.",
  "Write a haiku about GPU memory bandwidth.",
  "Summarize the CAP theorem in three sentences.",
  "What is tail latency and why does p99 matter for inference servers?",
  "Give me a bullet-point comparison of batching strategies in LLM serving.",
];

export function chatOnce(e: BenchEnv, vu: number, iter: number): void {
  const prompt = PROMPTS[(vu + iter) % PROMPTS.length];
  const body = JSON.stringify({
    model: e.model,
    messages: [{ role: "user", content: prompt }],
    max_tokens: e.maxTokens,
    temperature: e.temperature,
    stream: false,
  });

  const res = http.post(`${e.baseUrl}${e.path}`, body, {
    headers: { "Content-Type": "application/json" },
    timeout: e.timeoutS * 1000,
  });

  const ok = res.status === 200;
  failed.add(!ok, { status: String(res.status) });
  respByStatus.add(1, { status: String(res.status) });
  if (!ok) return;

  const ms = res.timings.duration;
  e2eMs.add(ms);

  let completion = 0;
  try {
    const parsed = res.json() as { usage?: { completion_tokens?: number } };
    completion = parsed.usage?.completion_tokens ?? 0;
  } catch {
    // usage missing — skip token accounting for this request
  }
  if (completion > 0) {
    outputTokens.add(completion);
    tokPerSec.add(completion / (ms / 1000));
  }
}
