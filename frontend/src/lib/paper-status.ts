export type PaperScenario = {
  name: "baseline" | "worse_costs";
  account: {
    position: number;
    gross_pnl_cents: number;
    fees_cents: number;
    net_pnl_cents: number;
    equity_cents: number;
  };
  orders: number;
  fills: number;
  completed_contract_units: number;
  halted_days: number;
  risk_halted: boolean;
  reconciliation: "pass" | "pending" | "fail";
};
export type PaperStatus = {
  schema_version: 1;
  run_id: string;
  observed_at: string;
  registered_at: string;
  protocol_sha256: string;
  mode: "streaming_internal_paper";
  connection: string;
  hard_halt: string | null;
  last_message_at: string | null;
  last_bar_received_at: string | null;
  last_reconciled_at: string | null;
  contract: { symbol: string } | null;
  receipts: number;
  excluded_receipts: number;
  complete_opening_opportunities: number;
  observed_opening_dates: number;
  engineering_review_due: boolean;
  scenarios: PaperScenario[];
  external_broker_connected: false;
  live_order_routing: false;
  profitability_established: false;
  initial_balance_cents: number;
};

// Strip every unrecognized field. Raw prices, credentials and private
// identifiers do not belong in the public observation endpoint.
export function parsePaperStatus(value: unknown): PaperStatus {
  if (!value || typeof value !== "object") throw new Error("Invalid status");
  const v = value as Record<string, unknown>;
  const str = (x: unknown, pattern?: RegExp): string => {
    if (typeof x !== "string" || x.length > 160 || (pattern && !pattern.test(x)))
      throw new Error("Invalid text field");
    return x;
  };
  const num = (x: unknown): number => {
    if (typeof x !== "number" || !Number.isSafeInteger(x) || Math.abs(x) > 1e12)
      throw new Error("Invalid numeric field");
    return x;
  };
  const stamp = (x: unknown): string => {
    const s = str(x);
    if (!Number.isFinite(Date.parse(s))) throw new Error("Invalid timestamp");
    return s;
  };
  const optionalStamp = (x: unknown) => x === null ? null : stamp(x);
  const states = new Set(["starting", "connecting", "connected_waiting_for_bar", "streaming", "data_review", "disconnected", "halted", "stopped"]);
  if (v.schema_version !== 1 || v.mode !== "streaming_internal_paper" || v.live_order_routing !== false || v.external_broker_connected !== false || v.profitability_established !== false || !states.has(String(v.connection)))
    throw new Error("Unsupported paper mode");
  if (!Array.isArray(v.scenarios) || v.scenarios.length !== 2) throw new Error("Missing scenarios");
  const scenarios = v.scenarios.map((row: Record<string, unknown>) => {
    if (!row || typeof row !== "object" || !["baseline", "worse_costs"].includes(String(row.name))) throw new Error("Invalid scenario");
    const a = row.account as Record<string, unknown>;
    if (!a || typeof a !== "object") throw new Error("Missing account");
    if (!["pass", "pending", "fail"].includes(String(row.reconciliation)) || typeof row.risk_halted !== "boolean") throw new Error("Invalid reconciliation state");
    return { name: row.name as PaperScenario["name"], account: {
      position: num(a.position), gross_pnl_cents: num(a.gross_pnl_cents), fees_cents: num(a.fees_cents),
      net_pnl_cents: num(a.net_pnl_cents), equity_cents: num(a.equity_cents),
    }, orders: num(row.orders), fills: num(row.fills), completed_contract_units: num(row.completed_contract_units),
    halted_days: num(row.halted_days), risk_halted: row.risk_halted,
    reconciliation: row.reconciliation as PaperScenario["reconciliation"] };
  });
  if (new Set(scenarios.map(s => s.name)).size !== 2) throw new Error("Duplicate scenarios");
  return {
    schema_version: 1, run_id: str(v.run_id, /^[a-zA-Z0-9_-]+$/), observed_at: stamp(v.observed_at), registered_at: stamp(v.registered_at),
    protocol_sha256: str(v.protocol_sha256, /^[a-f0-9]{64}$/), mode: "streaming_internal_paper", connection: str(v.connection),
    hard_halt: v.hard_halt === null ? null : str(v.hard_halt, /^[a-z_]+$/),
    last_message_at: optionalStamp(v.last_message_at), last_bar_received_at: optionalStamp(v.last_bar_received_at),
    last_reconciled_at: optionalStamp(v.last_reconciled_at),
    contract: v.contract ? { symbol: str((v.contract as Record<string, unknown>).symbol, /^MNQ[HMUZ][0-9]{1,2}$/) } : null,
    receipts: num(v.receipts), excluded_receipts: num(v.excluded_receipts), complete_opening_opportunities: num(v.complete_opening_opportunities),
    observed_opening_dates: num(v.observed_opening_dates), engineering_review_due: v.engineering_review_due === true,
    scenarios, external_broker_connected: false, live_order_routing: false, profitability_established: false,
    initial_balance_cents: num(v.initial_balance_cents),
  };
}

export function isStale(status: PaperStatus, now = Date.now()) {
  const age = now - Date.parse(status.observed_at);
  return age > 150_000 || age < -15_000;
}
