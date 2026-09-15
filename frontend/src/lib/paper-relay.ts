import { createHash, timingSafeEqual } from "node:crypto";
import { isStale, parsePaperStatus, type PaperStatus } from "./paper-status";

type Environment = Record<string, string | undefined>;
type Dependencies = { env?: Environment; fetch?: typeof fetch; now?: () => number };
type Store = { url: string; token: string; runId: string; key: string };

const BODY_LIMIT = 32 * 1024;
const RESPONSE_LIMIT = 64 * 1024;
const IO_TIMEOUT_MS = 4000;
const responseHeaders = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };

// One atomic operation prevents delayed requests, concurrent invocations or
// retries from replacing a newer report. Run identity also stays immutable.
// This key deliberately has no TTL: stale evidence must stay visibly stale.
export const UPDATE_STATUS_SCRIPT = `
local old = redis.call('HMGET', KEYS[1], 'observed_ms', 'status', 'protocol_sha256', 'registered_at')
if redis.call('EXISTS', KEYS[1]) == 1 then
  if not old[1] or not tonumber(old[1]) or not old[2] or not old[3] or not old[4] then return -1 end
  if old[3] ~= ARGV[3] or old[4] ~= ARGV[4] then return -1 end
  if tonumber(ARGV[1]) < tonumber(old[1]) then return 0 end
  if tonumber(ARGV[1]) == tonumber(old[1]) then
    if old[2] == ARGV[2] then return 2 else return 0 end
  end
end
redis.call('HSET', KEYS[1], 'observed_ms', ARGV[1], 'status', ARGV[2], 'protocol_sha256', ARGV[3], 'registered_at', ARGV[4])
return 1
`;

function json(body: unknown, status = 200) {
  return Response.json(body, { status, headers: responseHeaders });
}

function unavailable() {
  return json({ connection_status: "unavailable", message: "The paper worker report could not be verified. No current account or connection status can be inferred." }, 503);
}

function notConnected() {
  return json({ connection_status: "not_connected", message: "The continuous paper worker is not reporting to this view. Its current account and feed status are unavailable here." });
}

function expectedRun(env: Environment) {
  const run = env.TAJARI_PAPER_RUN_ID;
  if (!run || !/^[a-zA-Z0-9_-]{1,160}$/.test(run)) throw new Error("Run not configured");
  return run;
}

function storeConfig(env: Environment): Store | null {
  const direct = !!(env.UPSTASH_REDIS_REST_URL || env.UPSTASH_REDIS_REST_TOKEN);
  const url = direct ? env.UPSTASH_REDIS_REST_URL : env.KV_REST_API_URL;
  const token = direct ? env.UPSTASH_REDIS_REST_TOKEN : env.KV_REST_API_TOKEN;
  if (!url && !token) return null;
  if (!url || !token) throw new Error("Store not configured");
  const parsed = new URL(url);
  if (parsed.protocol !== "https:" || parsed.username || parsed.password || parsed.search || parsed.hash || parsed.pathname !== "/")
    throw new Error("Invalid store endpoint");
  const runId = expectedRun(env);
  return { url: parsed.href, token, runId, key: `tajari:paper-status:v1:${runId}` };
}

function authorized(request: Request, expected: string) {
  const header = request.headers.get("authorization") || "";
  if (header.length > 2048 || !/^Bearer /i.test(header)) return false;
  // Compare fixed-size digests so different token lengths never need an early
  // comparison branch. The application token is independent of Redis access.
  const digest = (value: string) => createHash("sha256").update(value).digest();
  return timingSafeEqual(digest(header.slice(7)), digest(expected));
}

class BodyError extends Error {
  status: number;
  constructor(status: number) { super("Invalid body"); this.status = status; }
}

async function boundedJson(message: Request | Response, limit: number): Promise<unknown> {
  const length = message.headers.get("content-length");
  if (length !== null && (!/^\d+$/.test(length) || Number(length) > limit)) throw new BodyError(413);
  if (!message.body) throw new BodyError(400);
  const reader = message.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new BodyError(408)), IO_TIMEOUT_MS); });
  try {
    while (true) {
      const chunk = await Promise.race([reader.read(), timeout]);
      if (chunk.done) break;
      size += chunk.value.byteLength;
      if (size > limit) throw new BodyError(413);
      chunks.push(chunk.value);
    }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } finally {
    clearTimeout(timer);
    // Do not wait indefinitely for a malicious or disconnected sender to close.
    void reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

async function command(store: Store, args: (string | number)[], fetcher: typeof fetch): Promise<unknown> {
  const response = await fetcher(store.url, {
    method: "POST", cache: "no-store", redirect: "error", signal: AbortSignal.timeout(IO_TIMEOUT_MS),
    headers: { Authorization: `Bearer ${store.token}`, "Content-Type": "application/json" },
    body: JSON.stringify(args),
  });
  if (!response.ok) throw new Error("Store unavailable");
  const data = await boundedJson(response, RESPONSE_LIMIT);
  if (!data || typeof data !== "object" || Array.isArray(data) || "error" in data || !("result" in data))
    throw new Error("Invalid store response");
  return data.result;
}

function readStored(value: unknown, store: Store): PaperStatus | null {
  if (!Array.isArray(value) || value.length !== 4) throw new Error("Invalid stored report");
  if (value.every(field => field === null)) return null;
  if (value.some(field => typeof field !== "string")) throw new Error("Incomplete stored report");
  const [observed, payload, protocol, registered] = value as string[];
  if (Buffer.byteLength(payload, "utf8") > BODY_LIMIT) throw new Error("Oversized stored report");
  const status = parsePaperStatus(JSON.parse(payload));
  if (status.run_id !== store.runId || String(Date.parse(status.observed_at)) !== observed || status.protocol_sha256 !== protocol || status.registered_at !== registered)
    throw new Error("Stored report identity mismatch");
  return status;
}

export async function getPaperServiceStatus(deps: Dependencies = {}) {
  const env = deps.env ?? process.env;
  const fetcher = deps.fetch ?? fetch;
  const now = deps.now ?? Date.now;
  try {
    const store = storeConfig(env);
    if (store) {
      const status = readStored(await command(store, ["HMGET", store.key, "observed_ms", "status", "protocol_sha256", "registered_at"], fetcher), store);
      return status ? json({ status, stale: isStale(status, now()) }) : notConnected();
    }
    // Preserve the private local proxy for a same-host development deployment.
    // A configured but failed relay never silently switches to another run.
    const source = env.TAJARI_PAPER_SERVICE_URL;
    const token = env.TAJARI_PAPER_LOCAL_TOKEN;
    if (!source || !token) return notConnected();
    const url = new URL(source);
    if (url.username || url.password || (url.protocol !== "https:" && !(url.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname))))
      throw new Error("Invalid worker endpoint");
    const response = await fetcher(url.href, { cache: "no-store", redirect: "error", signal: AbortSignal.timeout(IO_TIMEOUT_MS), headers: { Authorization: `Bearer ${token}` } });
    if (!response.ok) throw new Error("Worker unavailable");
    const status = parsePaperStatus(await boundedJson(response, RESPONSE_LIMIT));
    if (env.TAJARI_PAPER_RUN_ID && status.run_id !== expectedRun(env)) throw new Error("Wrong worker run");
    return json({ status, stale: isStale(status, now()) });
  } catch {
    return unavailable();
  }
}

export async function postPaperServiceStatus(request: Request, deps: Dependencies = {}) {
  const env = deps.env ?? process.env;
  const fetcher = deps.fetch ?? fetch;
  const now = deps.now ?? Date.now;
  const token = env.TAJARI_PAPER_STATUS_TOKEN;
  if (!token || token.length < 32 || token.length > 1024) return unavailable();
  if (!authorized(request, token)) return json({ error: "Unauthorized" }, 401);
  let store: Store | null;
  try { store = storeConfig(env); } catch { return unavailable(); }
  if (!store) return unavailable();
  if (request.headers.get("content-type")?.split(";")[0].trim().toLowerCase() !== "application/json")
    return json({ error: "A JSON report is required" }, 415);
  let status: PaperStatus;
  try {
    status = parsePaperStatus(await boundedJson(request, BODY_LIMIT));
  } catch (error) {
    return json({ error: "Invalid paper report" }, error instanceof BodyError ? error.status : 400);
  }
  if (status.run_id !== store.runId) return json({ error: "Report belongs to a different registered run" }, 409);
  if (isStale(status, now())) return json({ error: "Report timestamp is outside the accepted window" }, 422);
  try {
    const result = await command(store, ["EVAL", UPDATE_STATUS_SCRIPT, 1, store.key, String(Date.parse(status.observed_at)), JSON.stringify(status), status.protocol_sha256, status.registered_at], fetcher);
    if (result === 0 || result === -1) return json({ error: "Report conflicts with the stored run or a newer report" }, 409);
    if (result !== 1 && result !== 2) throw new Error("Unexpected write result");
    return json({ accepted: true, duplicate: result === 2 });
  } catch {
    return unavailable();
  }
}
