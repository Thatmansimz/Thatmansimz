"""Independent ledger reconciliation. Does not import Worker or Simulator.

Recalculates eligibility, prices, FIFO P&L and fees from raw simulator evidence.
Passing proves internal accounting consistency under declared assumptions only.
"""
from __future__ import annotations

import json
import sqlite3
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo

from .storage import canonical, digest, verify_journal


def audit(simulator_path, worker_path, spec, input_bars, reported_account):
    sim = sqlite3.connect(f"file:{simulator_path}?mode=ro", uri=True)
    worker = sqlite3.connect(f"file:{worker_path}?mode=ro", uri=True)
    sim.row_factory = worker.row_factory = sqlite3.Row
    errors = []
    def require(condition, message):
        if not condition: errors.append(message)
    try:
        roots = {}
        for name, db in [("simulator", sim), ("worker", worker)]:
            try: roots[name] = verify_journal(db)
            except ValueError as exc: errors.append(f"{name}: {exc}")
            require(db.execute("SELECT value FROM meta WHERE key='protocol'").fetchone()[0] == canonical(spec), f"{name}: protocol mismatch")
        bars = {b["ts"]: b for b in input_bars}
        actual_bars = {r[0]: json.loads(r[1]) for r in sim.execute("SELECT ts,payload FROM bars")}
        require(actual_bars == bars, "Simulator market record differs from registered input")
        intents = {r[0]: json.loads(r[1]) for r in worker.execute("SELECT id,request FROM intents")}
        orders = {r["id"]: dict(r) for r in sim.execute("SELECT * FROM orders")}
        require(set(intents) == set(orders), "Intent/order identity mismatch")
        for key, order in orders.items():
            require(key in intents and json.loads(order["request"]) == intents[key], f"{key}: broker request differs")
        fills = [json.loads(r[0]) for r in sim.execute("SELECT payload FROM fills ORDER BY rowid")]
        worker_fills = [json.loads(r[0]) for r in worker.execute("SELECT payload FROM fills ORDER BY rowid")]
        require(fills == worker_fills, "Fill identity/content/order differs between ledgers")
        for db, event_name, expected in [(sim, "fill", fills), (worker, "fill_observed", worker_fills)]:
            recorded = [json.loads(r[0]) for r in db.execute("SELECT payload FROM journal WHERE kind=? ORDER BY seq", (event_name,))]
            require(recorded == expected, f"{event_name}: journal/table mismatch")
        protections = {json.loads(r[0])["lot_id"]: json.loads(r[0]) for r in sim.execute("SELECT payload FROM journal WHERE kind='protection_acknowledged'")}
        queue, gross, fees, position, peak_position = deque(), 0, 0, 0, 0
        entry_fills, executed_quantities, completed_units = {}, {}, 0
        last_ts = -1
        for f in fills:
            req = intents.get(f["order_id"])
            b = bars.get(f["market_ts"])
            require(req is not None and b is not None, f"{f['id']}: missing intent or eligible market event")
            if req is None or b is None: continue
            require(f["market_ts"] >= last_ts, "Fill time moved backwards")
            last_ts = f["market_ts"]
            require(type(f["qty"]) is int and f["qty"] > 0 and f["side"] in (-1, 1), "Invalid fill quantity/side")
            require(b["volume"] > 0, "Fill on a zero-volume event")
            expected_fee = f["qty"] * spec["commission_per_side_cents"]
            require(f["fee_cents"] == expected_fee, f"{f['id']}: wrong fee")
            if f["reason"] in ("entry", "exit"):
                require(req["eligible_at"] <= b["ts"] < req["expires_at"], f"{f['id']}: fill outside eligibility window")
                require(req["eligible_at"] == req["submitted_at"] + spec["latency_bars"] * 60, "Latency differs from frozen protocol")
                require(f["side"] == req["side"] and f["reason"] == req["kind"], "Fill side/kind differs from order")
                price = b["open"] + f["side"] * spec["slippage_ticks"]
                executed_quantities[f["order_id"]] = executed_quantities.get(f["order_id"], 0) + f["qty"]
                require(executed_quantities[f["order_id"]] <= req["qty"], "Order overfilled")
                if f["reason"] == "entry":
                    entry_fills[f["id"]] = f
                    protect = protections.get(f["id"])
                    require(protect == {"lot_id": f["id"], "stop_ticks": price - f["side"] * spec["stop_ticks"], "qty": f["qty"]}, "Missing or incorrect simulated protection")
                else:
                    require(position * f["side"] < 0 and f["qty"] <= abs(position), "Exit was not reduce-only")
            elif f["reason"] == "stop":
                parent = entry_fills.get(f["lot_id"])
                require(parent is not None, "Stop without earlier entry fill")
                if parent is None: continue
                stop = parent["price_ticks"] - parent["side"] * spec["stop_ticks"]
                require(f["side"] == -parent["side"] and b["ts"] >= parent["market_ts"], "Pre-entry or reversed protective fill")
                require(b["low"] <= stop if parent["side"] > 0 else b["high"] >= stop, "Stop was not crossed")
                base = min(b["open"], stop) if parent["side"] > 0 else max(b["open"], stop)
                price = base - parent["side"] * spec["slippage_ticks"]
                require(position * f["side"] < 0 and f["qty"] <= abs(position), "Protective fill reverses inventory")
            else:
                errors.append("Unknown fill reason"); continue
            require(f["price_ticks"] == price, f"{f['id']}: fill price differs from registered model")
            remaining = f["qty"]
            while remaining and queue and queue[0]["side"] != f["side"]:
                lot = queue[0]; count = min(remaining, lot["qty"])
                gross += (price - lot["price"]) * lot["side"] * count * spec["tick_value_cents"]
                completed_units += count
                remaining -= count; lot["qty"] -= count
                if not lot["qty"]: queue.popleft()
            if remaining: queue.append({"side": f["side"], "qty": remaining, "price": price})
            fees += expected_fee; position += f["side"] * f["qty"]
            peak_position = max(peak_position, abs(position))
            require(abs(position) <= spec["quantity"], "Exposure exceeds frozen quantity")
        broker_position = sim.execute("SELECT COALESCE(SUM(side*qty),0) FROM lots").fetchone()[0]
        require(position == broker_position == reported_account["position"], "Position reconciliation failed")
        require(position == 0, "End-of-test inventory remains open")
        observed_states = dict(worker.execute("SELECT id,state FROM intents"))
        for key, order in orders.items():
            require(observed_states.get(key) == order["state"], f"{key}: order state not reconciled")
            require(order["filled"] == executed_quantities.get(key, 0), f"{key}: acknowledged fill quantity differs")
            if order["state"] == "filled": require(order["filled"] == intents[key]["qty"], "Incomplete order marked filled")
            if order["state"] == "rejected": require(order["filled"] == 0, "Rejected order has market fills")
        require(all(o["state"] in ("filled", "cancelled", "rejected", "expired") for o in orders.values()), "Pending order remains at end of test")
        calculated = {"position": position, "gross_pnl_cents": gross, "fees_cents": fees,
                      "net_pnl_cents": gross - fees, "equity_cents": spec["initial_balance_cents"] + gross - fees}
        require(calculated == reported_account, "Independent cents-level accounting differs from worker")
        # Check the frozen directional rule using broker market evidence,
        # independently of the worker's strategy implementation.
        for req in intents.values():
            if req["kind"] != "entry": continue
            decision = datetime.fromtimestamp(req["submitted_at"], ZoneInfo("America/New_York"))
            require((decision.hour, decision.minute) == (9, 45), "Entry decision outside frozen time")
            first_ts = int(decision.replace(hour=9, minute=30).timestamp())
            opening = [bars.get(first_ts + 60 * i) for i in range(15)]
            require(all(b and b["volume"] > 0 for b in opening), "Entry lacks 15 valid opening minutes")
            if all(opening):
                delta = opening[-1]["close"] - opening[0]["open"]
                require(delta != 0 and req["side"] == (1 if delta > 0 else -1), "Entry side differs from frozen rule")
        counts = {r[0]: r[1] for r in worker.execute("SELECT kind,COUNT(*) FROM journal GROUP BY kind")}
        return {"status": "pass" if not errors else "fail", "errors": errors, "account": calculated,
                "orders": len(orders), "fills": len(fills), "completed_contract_units": completed_units,
                "maximum_position": peak_position, "journal_roots": roots, "protocol_sha256": digest(spec),
                "worker_events": counts, "order_states": {state: sum(o["state"] == state for o in orders.values()) for state in sorted({o["state"] for o in orders.values()})},
                "scope": "Internal simulator reconciliation only; not independent broker confirmation or strategy validation"}
    finally:
        sim.close(); worker.close()
