// Run: node --test tests/paper-relay.test.cjs
// Include the real Redis Lua/concurrency test by setting TAJARI_TEST_REDIS_BIN
// to a directory containing redis-server and redis-cli. It creates and removes
// its own Unix-socket-only server; no application ledger or remote store is used.
const assert = require('node:assert/strict');
const { test, after } = require('node:test');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn, execFile } = require('node:child_process');
const { promisify } = require('node:util');
const ts = require('typescript');

// Use the project's existing compiler, with no additional runner dependency.
const compiled = fs.mkdtempSync(path.join(os.tmpdir(), 'tajari-relay-code-'));
for (const name of ['paper-status', 'paper-relay']) {
  const source = fs.readFileSync(path.join(__dirname, '../src/lib', name + '.ts'), 'utf8');
  const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } });
  fs.writeFileSync(path.join(compiled, name + '.js'), output.outputText);
}
const { getPaperServiceStatus: get, postPaperServiceStatus: post } = require(path.join(compiled, 'paper-relay.js'));
after(() => fs.rmSync(compiled, { recursive: true, force: true }));

const now = Date.parse('2026-09-15T15:00:00.000Z');
const token = 'synthetic-publisher-token-for-tests-only';
const env = {
  TAJARI_PAPER_STATUS_TOKEN: token,
  TAJARI_PAPER_RUN_ID: 'synthetic-run',
  UPSTASH_REDIS_REST_URL: 'https://synthetic-test.upstash.io',
  UPSTASH_REDIS_REST_TOKEN: 'synthetic-redis-token',
};
function report(overrides = {}) {
  return {
    schema_version: 1, run_id: 'synthetic-run', observed_at: new Date(now).toISOString(),
    registered_at: '2026-09-15T14:00:00.000Z', protocol_sha256: 'a'.repeat(64),
    mode: 'streaming_internal_paper', connection: 'streaming', hard_halt: null,
    last_message_at: new Date(now).toISOString(), last_bar_received_at: new Date(now).toISOString(),
    last_reconciled_at: new Date(now).toISOString(), last_audit_attempt_at: new Date(now).toISOString(),
    contract: { symbol: 'MNQU6' }, receipts: 1, excluded_receipts: 0,
    complete_opening_opportunities: 0, observed_opening_dates: 0, engineering_review_due: false,
    scenarios: ['baseline', 'worse_costs'].map(name => ({ name,
      account: { position: 0, gross_pnl_cents: 0, fees_cents: 0, net_pnl_cents: 0, equity_cents: 5000000 },
      orders: 0, fills: 0, completed_contract_units: 0, halted_days: 0, risk_halted: false, reconciliation: 'pass' })),
    external_broker_connected: false, live_order_routing: false, profitability_established: false,
    initial_balance_cents: 5000000, ...overrides,
  };
}
function request(value = report(), authorization = `Bearer ${token}`, headers = {}) {
  return new Request('https://tajari.test/api/paper-service', { method: 'POST',
    headers: { Authorization: authorization, 'Content-Type': 'application/json', ...headers },
    body: typeof value === 'string' ? value : JSON.stringify(value) });
}
function deps(fetcher, other = {}) { return { env, fetch: fetcher, now: () => now, ...other }; }
function stored(status = report()) {
  return [String(Date.parse(status.observed_at)), JSON.stringify(status), status.protocol_sha256, status.registered_at];
}

test('publisher authentication fails before reading the body or contacting storage', async () => {
  let calls = 0;
  const settings = deps(async () => { calls++; throw new Error('must not run'); });
  for (const authorization of ['', 'Basic abc', 'Bearer wrong', `Bearer ${token}x`]) {
    const response = await post(request('{', authorization), settings);
    assert.equal(response.status, 401);
    assert.equal(response.headers.get('cache-control'), 'no-store');
  }
  assert.equal(calls, 0);
  assert.equal((await post(request(), { ...settings, env: { ...env, TAJARI_PAPER_STATUS_TOKEN: 'short' } })).status, 503);
});

test('publication stores only the public allowlist and keeps Redis credentials server-side', async () => {
  const source = report({ api_key: 'secret-provider-key', market_price: 12345, host: '/private/host' });
  source.scenarios[0].account.password = 'secret-account-value';
  let command;
  const response = await post(request(source), deps(async (url, init) => {
    assert.equal(url, 'https://synthetic-test.upstash.io/');
    assert.equal(init.redirect, 'error');
    assert.equal(init.headers.Authorization, 'Bearer synthetic-redis-token');
    assert.ok(init.signal instanceof AbortSignal);
    command = JSON.parse(init.body);
    return Response.json({ result: 1 });
  }));
  assert.equal(response.status, 200);
  assert.equal(command[0], 'EVAL');
  assert.equal(command[2], 1);
  assert.equal(command[3], 'tajari:paper-status:v1:synthetic-run');
  assert.equal(command[4], String(now));
  const saved = JSON.parse(command[5]);
  assert.equal(saved.api_key, undefined);
  assert.equal(saved.market_price, undefined);
  assert.equal(saved.host, undefined);
  assert.equal(saved.scenarios[0].account.password, undefined);
  assert.deepEqual(await response.json(), { accepted: true, duplicate: false });
});

test('rejects other runs, live mode, stale and future timestamps without storage access', async () => {
  let calls = 0;
  const settings = deps(async () => { calls++; throw new Error('must not run'); });
  for (const [changes, expected] of [
    [{ run_id: 'old-run' }, 409], [{ live_order_routing: true }, 400],
    [{ observed_at: new Date(now - 150001).toISOString() }, 422],
    [{ observed_at: new Date(now + 15001).toISOString() }, 422],
  ]) assert.equal((await post(request(report(changes)), settings)).status, expected);
  assert.equal(calls, 0);
});

test('requires bounded JSON input, including a stream without content-length', async () => {
  let calls = 0;
  const settings = deps(async () => { calls++; throw new Error('must not run'); });
  assert.equal((await post(request('{}', undefined, { 'content-type': 'text/plain' }), settings)).status, 415);
  assert.equal((await post(request('{'), settings)).status, 400);
  assert.equal((await post(request('{}', undefined, { 'content-length': '32769' }), settings)).status, 413);
  const stream = new ReadableStream({ start(controller) {
    controller.enqueue(new Uint8Array(20 * 1024));
    controller.enqueue(new Uint8Array(20 * 1024));
    controller.close();
  } });
  const streamed = new Request('https://tajari.test', { method: 'POST', duplex: 'half', body: stream,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } });
  assert.equal((await post(streamed, settings)).status, 413);
  assert.equal(calls, 0);
});

test('provider failures, malformed replies and unexpected write results fail closed', async () => {
  const sources = [
    async () => { throw new Error('private credential in provider failure'); },
    async () => { throw new DOMException('timed out', 'TimeoutError'); },
    async () => new Response('private outage details', { status: 503 }),
    async () => new Response('{'),
    async () => Response.json({ error: 'private Redis error' }),
    async () => Response.json({ result: 'OK' }),
    async () => Response.json({ result: 1, error: 'not actually accepted' }),
  ];
  for (const fetcher of sources) {
    const response = await post(request(), deps(fetcher));
    assert.equal(response.status, 503);
    assert.doesNotMatch(await response.text(), /private/);
  }
  assert.equal((await post(request(), deps(async () => Response.json({ result: 0 })))).status, 409);
  assert.deepEqual(await (await post(request(), deps(async () => Response.json({ result: 2 })))).json(), { accepted: true, duplicate: true });
});

test('read validates stored identity, strips unknown fields and reports staleness', async () => {
  const source = report({ observed_at: new Date(now - 151000).toISOString(), private_value: 'never-public' });
  const response = await get(deps(async () => Response.json({ result: stored(source) })));
  assert.equal(response.status, 200);
  const output = await response.json();
  assert.equal(output.stale, true);
  assert.equal(output.status.private_value, undefined);
  assert.equal(output.status.run_id, 'synthetic-run');
  const corrupt = [stored(report({ run_id: 'other-run' })), ['0', ...stored().slice(1)], [null, '{}', null, null], { result: '{}' }];
  for (const value of corrupt) assert.equal((await get(deps(async () => Response.json({ result: value })))).status, 503);
  const empty = await get(deps(async () => Response.json({ result: [null, null, null, null] })));
  assert.equal((await empty.json()).connection_status, 'not_connected');
});

test('missing configuration stays unavailable; local fallback and Marketplace names work', async () => {
  let calls = 0;
  const settings = deps(async () => { calls++; return Response.json(report()); }, { env: {} });
  assert.equal((await (await get(settings)).json()).connection_status, 'not_connected');
  assert.equal(calls, 0);
  const local = { TAJARI_PAPER_SERVICE_URL: 'http://127.0.0.1:8022/status', TAJARI_PAPER_LOCAL_TOKEN: token };
  assert.equal((await get({ ...settings, env: local })).status, 200);
  assert.equal((await get({ ...settings, env: { ...local, UPSTASH_REDIS_REST_URL: env.UPSTASH_REDIS_REST_URL } })).status, 503);
  assert.equal((await get({ ...settings, env: { ...local, TAJARI_PAPER_RUN_ID: 'wrong-run' } })).status, 503);
  assert.equal((await get({ ...settings, env: { ...env, TAJARI_PAPER_RUN_ID: undefined } })).status, 503);
  const marketplace = { TAJARI_PAPER_RUN_ID: env.TAJARI_PAPER_RUN_ID,
    KV_REST_API_URL: env.UPSTASH_REDIS_REST_URL, KV_REST_API_TOKEN: env.UPSTASH_REDIS_REST_TOKEN };
  assert.equal((await get(deps(async () => Response.json({ result: stored() }), { env: marketplace }))).status, 200);
});

test('GET rejects failed, oversized or unsafe local sources', async () => {
  const local = { TAJARI_PAPER_SERVICE_URL: 'http://127.0.0.1:8022/status', TAJARI_PAPER_LOCAL_TOKEN: token };
  for (const fetcher of [async () => new Response('', { status: 502 }), async () => Response.json({}),
    async () => new Response('x'.repeat(65537)), async () => { throw new DOMException('timeout', 'TimeoutError'); }])
    assert.equal((await get(deps(fetcher, { env: local }))).status, 503);
  let calls = 0;
  const response = await get(deps(async () => { calls++; return Response.json(report()); },
    { env: { ...local, TAJARI_PAPER_SERVICE_URL: 'http://external.example/status' } }));
  assert.equal(response.status, 503);
  assert.equal(calls, 0);
});

test('stalled request and provider bodies stop at the bounded read deadline', { timeout: 6000 }, async () => {
  let requestCancelled = false;
  let providerCancelled = false;
  const input = new ReadableStream({ cancel() { requestCancelled = true; } });
  const stalledRequest = new Request('https://tajari.test', { method: 'POST', duplex: 'half', body: input,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } });
  const provider = new ReadableStream({ cancel() { providerCancelled = true; } });
  const [write, read] = await Promise.all([
    post(stalledRequest, deps(async () => { throw new Error('must not contact store'); })),
    get(deps(async () => new Response(provider))),
  ]);
  assert.equal(write.status, 408);
  assert.equal(read.status, 503);
  assert.equal(requestCancelled, true);
  assert.equal(providerCancelled, true);
});

test('actual Redis Lua keeps the latest concurrent report and rejects changed identity',
  { skip: !process.env.TAJARI_TEST_REDIS_BIN }, async (t) => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'tajari-relay-redis-'));
  const socket = path.join(directory, 'redis.sock');
  const binaries = process.env.TAJARI_TEST_REDIS_BIN;
  const child = spawn(path.join(binaries, 'redis-server'), ['--port', '0', '--unixsocket', socket,
    '--unixsocketperm', '700', '--save', '', '--appendonly', 'no', '--dir', directory], { stdio: 'ignore' });
  const exit = new Promise(resolve => child.once('exit', resolve));
  t.after(async () => { child.kill('SIGTERM'); await exit; fs.rmSync(directory, { recursive: true, force: true }); });
  for (let attempt = 0; !fs.existsSync(socket) && attempt < 300; attempt++) await new Promise(resolve => setTimeout(resolve, 10));
  assert.ok(fs.existsSync(socket), 'isolated Redis did not start');
  const execute = async args => {
    const { stdout } = await promisify(execFile)(path.join(binaries, 'redis-cli'), ['-s', socket, '--json', ...args.map(String)]);
    return JSON.parse(stdout);
  };
  const settings = deps(async (_url, init) => Response.json({ result: await execute(JSON.parse(init.body)) }));
  const observations = [-1000, -500, 0, -900, -300, -100].map(delta => report({ observed_at: new Date(now + delta).toISOString() }));
  const responses = await Promise.all(observations.map(value => post(request(value), settings)));
  for (const response of responses) assert.ok([200, 409].includes(response.status));
  const current = await (await get(settings)).json();
  assert.equal(current.status.observed_at, report().observed_at);
  assert.equal((await post(request(observations[0]), settings)).status, 409);
  assert.deepEqual(await (await post(request(report()), settings)).json(), { accepted: true, duplicate: true });
  assert.equal((await post(request(report({ protocol_sha256: 'b'.repeat(64), observed_at: new Date(now + 1).toISOString() })), settings)).status, 409);
  assert.equal((await post(request(report({ registered_at: '2026-09-15T13:00:00Z', observed_at: new Date(now + 1).toISOString() })), settings)).status, 409);
  const changedAtSameTime = report({ receipts: 100 });
  assert.equal((await post(request(changedAtSameTime), settings)).status, 409);
  assert.equal(await execute(['TTL', 'tajari:paper-status:v1:synthetic-run']), -1);
  await execute(['HSET', 'tajari:paper-status:v1:synthetic-run', 'observed_ms', 'corrupt']);
  assert.equal((await get(settings)).status, 503);
  assert.equal((await post(request(report({ observed_at: new Date(now + 1).toISOString() })), settings)).status, 409);
});
