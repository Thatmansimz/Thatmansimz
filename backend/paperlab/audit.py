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


def _journal_orders(sim, worker, require):
    """Rebuild materialized orders independently of both order tables.

    Worker observations may skip intermediate broker states after a disconnect,
    so their own journal defines the last state they actually acknowledged.
    Simulator lifecycle events must follow creation and its durable fills.
    """
    intents, observed, orders = {}, {}, {}
    states = {"accepted", "partially_filled", "filled", "cancelled", "rejected", "expired"}
    for row in worker.execute("SELECT kind,payload FROM journal ORDER BY seq"):
        kind, payload = row[0], json.loads(row[1])
        if kind == "intent_committed":
            key = payload["id"]
            require(key not in intents, f"{key}: duplicate journal intent")
            intents[key], observed[key] = payload, "pending"
        elif kind in ("order_acknowledged", "order_observed"):
            key = payload["id"]
            require(key in intents, f"{key}: observation precedes journal intent")
            require(payload["state"] in states, f"{key}: invalid observed journal state")
            observed[key] = payload["state"]
    for row in sim.execute("SELECT kind,payload FROM journal ORDER BY seq"):
        kind, payload = row[0], json.loads(row[1])
        if kind in ("order_accepted", "order_rejected"):
            req = payload["request"]; key = req["id"]
            require(key not in orders, f"{key}: duplicate journal order creation")
            orders[key] = {"id": key, "request": canonical(req), "state": kind[6:], "filled": 0}
        elif kind == "fill" and payload["reason"] in ("entry", "exit"):
            key = payload["order_id"]; order = orders.get(key)
            require(order is not None, f"{key}: fill precedes journal order")
            if order is None: continue
            require(order["state"] in ("accepted", "partially_filled"), f"{key}: journal fill after terminal state")
            order["filled"] += payload["qty"]
        elif kind in ("order_partially_filled", "order_filled", "order_cancelled", "order_expired"):
            key = payload["id"]; order = orders.get(key)
            require(order is not None, f"{key}: lifecycle precedes journal order")
            if order is None: continue
            require(order["state"] in ("accepted", "partially_filled"), f"{key}: invalid terminal journal transition")
            if kind in ("order_partially_filled", "order_filled"):
                require(payload["filled"] == order["filled"], f"{key}: journal state/fill quantity mismatch")
            order["state"] = kind[6:]
    for key, order in orders.items():
        qty = json.loads(order["request"])["qty"]
        state, filled = order["state"], order["filled"]
        valid = (state in ("accepted", "rejected") and filled == 0
                 or state == "partially_filled" and 0 < filled < qty
                 or state == "filled" and filled == qty
                 or state in ("cancelled", "expired") and 0 <= filled < qty)
        require(valid, f"{key}: invalid final journal order state/quantity")
    return intents, observed, orders


def audit(simulator_path, worker_path, spec, input_bars, reported_account, *, allow_open=False):
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
        observed_states = dict(worker.execute("SELECT id,state FROM intents"))
        journal_intents, journal_observed, journal_orders = _journal_orders(sim, worker, require)
        require(intents == journal_intents, "Intent journal/table mismatch")
        require(observed_states == journal_observed, "Worker order state journal/table mismatch")
        require(orders == journal_orders, "Simulator order lifecycle journal/table mismatch")
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
        # Physical protective lots are separate from FIFO accounting lots:
        # a stop targets its specific entry lot, while exits consume oldest lots.
        active_lots = {}
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
                earliest = req["submitted_at"] + spec["latency_bars"] * 60
                if spec.get("purpose") == "engineering_forward_paper":
                    decision_ns = req.get("decision_received_at_ns", 0)
                    earliest = max(earliest, ((decision_ns + 60_000_000_000 - 1) // 60_000_000_000) * 60)
                    require(decision_ns > 0 and f["market_ts"] * 1_000_000_000 >= decision_ns, "Retrospective forward fill")
                    require(req.get("symbol") == b.get("symbol") and req.get("instrument_id") == b.get("instrument_id"), "Fill crosses actual contract mapping")
                require(req["eligible_at"] == earliest, "Latency differs from frozen protocol")
                require(f["side"] == req["side"] and f["reason"] == req["kind"], "Fill side/kind differs from order")
                price = b["open"] + f["side"] * spec["slippage_ticks"]
                executed_quantities[f["order_id"]] = executed_quantities.get(f["order_id"], 0) + f["qty"]
                require(executed_quantities[f["order_id"]] <= req["qty"], "Order overfilled")
                if f["reason"] == "entry":
                    entry_fills[f["id"]] = f
                    protect = protections.get(f["id"])
                    require(protect == {"lot_id": f["id"], "stop_ticks": price - f["side"] * spec["stop_ticks"], "qty": f["qty"]}, "Missing or incorrect simulated protection")
                    require(f["id"] not in active_lots, "Duplicate live lot identity")
                    active_lots[f["id"]] = {"id": f["id"], "parent": f["order_id"], "side": f["side"],
                                             "qty": f["qty"], "price": price,
                                             "stop": price - f["side"] * spec["stop_ticks"]}
                else:
                    require(position * f["side"] < 0 and f["qty"] <= abs(position), "Exit was not reduce-only")
                    remaining_exit = f["qty"]
                    for key, lot in list(active_lots.items()):
                        if lot["side"] != -f["side"]: continue
                        take = min(remaining_exit, lot["qty"])
                        lot["qty"] -= take; remaining_exit -= take
                        if not lot["qty"]: del active_lots[key]
                        if not remaining_exit: break
                    require(remaining_exit == 0, "Exit exceeds physical lot inventory")
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
                lot = active_lots.get(f["lot_id"])
                require(lot is not None, "Stop has no remaining protected lot")
                if lot is not None:
                    require(f["order_id"] == lot["parent"] and f["qty"] == lot["qty"]
                            and f["side"] == -lot["side"], "Stop differs from its remaining protected lot")
                    del active_lots[f["lot_id"]]
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
        actual_lots = [dict(row) for row in sim.execute("SELECT * FROM lots ORDER BY rowid")]
        require(actual_lots == list(active_lots.values()), "Current protective lot journal/table mismatch")
        require(position == broker_position == reported_account["position"], "Position reconciliation failed")
        if not allow_open:
            require(position == 0, "End-of-test inventory remains open")
        for key, order in orders.items():
            require(observed_states.get(key) == order["state"], f"{key}: order state not reconciled")
            require(order["filled"] == executed_quantities.get(key, 0), f"{key}: acknowledged fill quantity differs")
            if order["state"] == "filled": require(key in intents and order["filled"] == intents[key]["qty"], "Incomplete order marked filled")
            if order["state"] == "rejected": require(order["filled"] == 0, "Rejected order has market fills")
        if not allow_open:
            require(all(o["state"] in ("filled", "cancelled", "rejected", "expired") for o in orders.values()), "Pending order remains at end of test")
        mark = input_bars[-1]["close"] if allow_open and input_bars else None
        unrealized = sum((mark - lot["price"]) * lot["side"] * lot["qty"] * spec["tick_value_cents"] for lot in queue) if mark is not None else 0
        calculated = {"position": position, "gross_pnl_cents": gross, "fees_cents": fees,
                      "net_pnl_cents": gross - fees, "equity_cents": spec["initial_balance_cents"] + gross - fees + unrealized}
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
