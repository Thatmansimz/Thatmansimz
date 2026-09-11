"""Deterministic OHLC broker simulator with its OWN database and order lifecycle.

This is an engineering test double, not a real broker adapter. Integer ticks
and cents avoid rounding drift. No network or real-account code is imported.
"""
from __future__ import annotations

import json
from .storage import bind, canonical, connect, record


class Simulator:
    def __init__(self, path, spec, *, fill_cap=None, reject=None):
        if spec.get("purpose") != "engineering_replay_only":
            raise ValueError("This simulator only accepts engineering replays")
        self.spec, self.fill_cap, self.reject = spec, fill_cap, reject
        self.db = connect(path)
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY, request TEXT NOT NULL,
            state TEXT NOT NULL, filled INTEGER NOT NULL DEFAULT 0);
          CREATE TABLE IF NOT EXISTS bars(ts INTEGER PRIMARY KEY, payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS fills(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS lots(id TEXT PRIMARY KEY, parent TEXT NOT NULL,
            side INTEGER NOT NULL, qty INTEGER NOT NULL, price INTEGER NOT NULL, stop INTEGER NOT NULL);
        """)
        bind(self.db, spec)

    def close(self):
        self.db.close()

    def submit(self, request):
        encoded = canonical(request)
        old = self.db.execute("SELECT * FROM orders WHERE id=?", (request["id"],)).fetchone()
        if old:
            if old["request"] != encoded:
                raise ValueError("Idempotency key reused for a different order")
            return dict(old)
        if request["side"] not in (-1, 1) or type(request["qty"]) is not int or not 0 < request["qty"] <= self.spec["max_quantity"]:
            raise ValueError("Invalid side or quantity")
        if request["kind"] not in ("entry", "exit") or request["eligible_at"] <= request["submitted_at"]:
            raise ValueError("Invalid order eligibility")
        latest = self.db.execute("SELECT MAX(ts) FROM bars").fetchone()[0]
        state = "accepted"
        reason = None
        if latest is not None and request["expires_at"] <= latest:
            state, reason = "rejected", "stale_intent"
        elif request["kind"] == "entry" and self.reject:
            state, reason = "rejected", self.reject
        with self.db:
            self.db.execute("INSERT INTO orders VALUES(?,?,?,0)", (request["id"], encoded, state))
            record(self.db, "order_" + state, {"request": request, "reason": reason,
                                                "protection": "atomic_simulated_bracket" if request["kind"] == "entry" and state == "accepted" else None})
        return dict(self.db.execute("SELECT * FROM orders WHERE id=?", (request["id"],)).fetchone())

    def _fill(self, order_id, side, qty, price, bar, reason, *, lot_id=None):
        number = self.db.execute("SELECT COUNT(*) FROM fills").fetchone()[0] + 1
        fill = {"id": f"fill-{number:06d}", "order_id": order_id, "side": side, "qty": qty,
                "price_ticks": price, "fee_cents": self.spec["commission_per_side_cents"] * qty,
                "market_ts": bar["ts"], "reason": reason, "lot_id": lot_id}
        self.db.execute("INSERT INTO fills VALUES(?,?)", (fill["id"], canonical(fill)))
        record(self.db, "fill", fill)
        return fill

    def advance(self, bar):
        if not all(type(bar[k]) is int for k in ("ts", "open", "high", "low", "close", "volume")):
            raise ValueError("Market events require integer ticks, timestamps and volume")
        if min(bar[k] for k in ("open", "high", "low", "close")) <= 0 or bar["volume"] < 0 or bar["low"] > min(bar["open"], bar["close"]) or bar["high"] < max(bar["open"], bar["close"]):
            raise ValueError("Invalid market event")
        encoded = canonical(bar)
        old = self.db.execute("SELECT payload FROM bars WHERE ts=?", (bar["ts"],)).fetchone()
        if old:
            if old[0] != encoded:
                raise ValueError("Conflicting duplicate market event")
            return
        latest = self.db.execute("SELECT MAX(ts) FROM bars").fetchone()[0]
        if latest is not None and bar["ts"] <= latest:
            raise ValueError("Out-of-order market event")
        with self.db:
            self.db.execute("INSERT INTO bars VALUES(?,?)", (bar["ts"], encoded))
            record(self.db, "market_event", bar)
            for row in list(self.db.execute("SELECT * FROM orders WHERE state IN ('accepted','partially_filled') ORDER BY rowid")):
                req = json.loads(row["request"])
                if bar["ts"] >= req["expires_at"]:
                    self.db.execute("UPDATE orders SET state='expired' WHERE id=?", (row["id"],))
                    record(self.db, "order_expired", {"id": row["id"], "market_ts": bar["ts"]})
                    continue
                if bar["ts"] < req["eligible_at"] or not bar["volume"]:
                    continue
                qty = min(req["qty"] - row["filled"], self.fill_cap or req["qty"])
                if req["kind"] == "exit":
                    available = self.db.execute("SELECT COALESCE(SUM(qty),0) FROM lots WHERE side=?", (-req["side"],)).fetchone()[0]
                    qty = min(qty, available)
                    if not qty:
                        self.db.execute("UPDATE orders SET state='cancelled' WHERE id=?", (row["id"],))
                        record(self.db, "order_cancelled", {"id": row["id"], "reason": "reduce_only_no_position"})
                        continue
                price = bar["open"] + req["side"] * self.spec["slippage_ticks"]
                fill = self._fill(row["id"], req["side"], qty, price, bar, req["kind"])
                if req["kind"] == "entry":
                    stop = price - req["side"] * self.spec["stop_ticks"]
                    self.db.execute("INSERT INTO lots VALUES(?,?,?,?,?,?)", (fill["id"], row["id"], req["side"], qty, price, stop))
                    record(self.db, "protection_acknowledged", {"lot_id": fill["id"], "stop_ticks": stop, "qty": qty})
                else:
                    remaining = qty
                    for lot in list(self.db.execute("SELECT * FROM lots WHERE side=? ORDER BY rowid", (-req["side"],))):
                        take = min(remaining, lot["qty"])
                        self.db.execute("UPDATE lots SET qty=qty-? WHERE id=?", (take, lot["id"]))
                        remaining -= take
                        if not remaining:
                            break
                    self.db.execute("DELETE FROM lots WHERE qty=0")
                total = row["filled"] + qty
                state = "filled" if total == req["qty"] else "partially_filled"
                self.db.execute("UPDATE orders SET filled=?,state=? WHERE id=?", (total, state, row["id"]))
                record(self.db, "order_" + state, {"id": row["id"], "filled": total})
            # Stops survive a disconnected worker. Same-bar execution is
            # explicitly conservative and remains an OHLC assumption.
            if bar["volume"]:
                for lot in list(self.db.execute("SELECT * FROM lots ORDER BY rowid")):
                    touched = bar["low"] <= lot["stop"] if lot["side"] == 1 else bar["high"] >= lot["stop"]
                    if touched:
                        base = min(bar["open"], lot["stop"]) if lot["side"] == 1 else max(bar["open"], lot["stop"])
                        price = base - lot["side"] * self.spec["slippage_ticks"]
                        self._fill(lot["parent"], -lot["side"], lot["qty"], price, bar, "stop", lot_id=lot["id"])
                        self.db.execute("DELETE FROM lots WHERE id=?", (lot["id"],))
                        # Cancel remaining entry quantity after its stop fires.
                        self.db.execute("UPDATE orders SET state='cancelled' WHERE id=? AND state='partially_filled'", (lot["parent"],))
                        if self.db.execute("SELECT changes()").fetchone()[0]:
                            record(self.db, "order_cancelled", {"id": lot["parent"], "reason": "protective_stop_filled"})

    def snapshot(self):
        return {"orders": [dict(r) for r in self.db.execute("SELECT * FROM orders ORDER BY rowid")],
                "fills": [json.loads(r[0]) for r in self.db.execute("SELECT payload FROM fills ORDER BY rowid")],
                "position": self.db.execute("SELECT COALESCE(SUM(side*qty),0) FROM lots").fetchone()[0]}
