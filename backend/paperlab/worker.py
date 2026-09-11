"""Durable intents, asynchronous fills and recovery for an isolated paper lab."""
from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from .storage import bind, canonical, connect, record, verify_journal

ET = ZoneInfo("America/New_York")


class Worker:
    def __init__(self, path, spec, transport, *, after_accept=None, after_fill=None):
        self.spec, self.transport = spec, transport
        self.after_accept, self.after_fill = after_accept, after_fill
        self.db = connect(path)
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS intents(id TEXT PRIMARY KEY, request TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending');
          CREATE TABLE IF NOT EXISTS fills(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS bars(ts INTEGER PRIMARY KEY, payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS halted_days(day TEXT PRIMARY KEY, reason TEXT NOT NULL);
        """)
        bind(self.db, spec)
        verify_journal(self.db)

    def close(self):
        self.db.close()

    def account(self, mark=None):
        lots, realized, fees = [], 0, 0
        for row in self.db.execute("SELECT payload FROM fills ORDER BY rowid"):
            f = json.loads(row[0]); fees += f["fee_cents"]
            left = f["qty"]
            while left and lots and lots[0][0] != f["side"]:
                side, size, entry = lots[0]; take = min(size, left)
                realized += (f["price_ticks"] - entry) * side * take * self.spec["tick_value_cents"]
                left -= take; size -= take
                if size: lots[0][1] = size
                else: lots.pop(0)
            if left: lots.append([f["side"], left, f["price_ticks"]])
        unrealized = sum((mark - price) * side * qty * self.spec["tick_value_cents"] for side, qty, price in lots) if mark is not None else 0
        return {"position": sum(side * qty for side, qty, _ in lots), "gross_pnl_cents": realized,
                "fees_cents": fees, "net_pnl_cents": realized - fees,
                "equity_cents": self.spec["initial_balance_cents"] + realized - fees + unrealized}

    def reconcile(self):
        snapshot = self.transport.snapshot()
        known = {r[0]: r[1] for r in self.db.execute("SELECT id,request FROM intents")}
        remote = {r["id"]: r for r in snapshot["orders"]}
        if set(remote) - set(known):
            raise ValueError("Unexplained simulator order; entries blocked")
        for order_id, remote_order in remote.items():
            if remote_order["request"] != known[order_id]:
                raise ValueError("Simulator order differs from durable intent")
        for row in self.db.execute("SELECT id,state FROM intents"):
            if row["state"] != "pending" and row["id"] not in remote:
                raise ValueError("Acknowledged order disappeared from simulator")
        with self.db:
            for f in snapshot["fills"]:
                if f["order_id"] not in known:
                    raise ValueError("Fill has no known intent")
                old = self.db.execute("SELECT payload FROM fills WHERE id=?", (f["id"],)).fetchone()
                encoded = canonical(f)
                if old and old[0] != encoded:
                    raise ValueError("Conflicting duplicate fill")
                if not old:
                    if self.after_fill: self.after_fill()
                    self.db.execute("INSERT INTO fills VALUES(?,?)", (f["id"], encoded))
                    record(self.db, "fill_observed", f)
            if self.account()["position"] != snapshot["position"]:
                raise ValueError("Position mismatch after fill reconciliation")
            for order_id, item in remote.items():
                old = self.db.execute("SELECT state FROM intents WHERE id=?", (order_id,)).fetchone()[0]
                if old != item["state"]:
                    self.db.execute("UPDATE intents SET state=? WHERE id=?", (item["state"], order_id))
                    record(self.db, "order_observed", {"id": order_id, "state": item["state"]})
        return snapshot

    def dispatch(self):
        for row in list(self.db.execute("SELECT request FROM intents WHERE state='pending' ORDER BY rowid")):
            req = json.loads(row[0])
            result = self.transport.submit(req)
            if self.after_accept: self.after_accept()
            with self.db:
                self.db.execute("UPDATE intents SET state=? WHERE id=?", (result["state"], req["id"]))
                record(self.db, "order_acknowledged", {"id": req["id"], "state": result["state"]})

    def recover(self):
        self.reconcile()
        self.dispatch()
        with self.db: record(self.db, "recovery_completed", {"position": self.account()["position"]})

    def processed(self, bar):
        old = self.db.execute("SELECT payload FROM bars WHERE ts=?", (bar["ts"],)).fetchone()
        if old and old[0] != canonical(bar):
            raise ValueError("Conflicting duplicate worker market event")
        return old is not None

    def _intent(self, day, kind, side, qty, bar):
        key = f"{day}/{kind}"
        if self.db.execute("SELECT 1 FROM intents WHERE id=?", (key,)).fetchone(): return
        submitted = bar["ts"] + 60
        eligible = submitted + self.spec["latency_bars"] * 60
        req = {"id": key, "kind": kind, "side": side, "qty": qty,
               "submitted_at": submitted, "eligible_at": eligible,
               "expires_at": eligible + (180 if kind == "entry" else 1800),
               "symbol": self.spec["symbol"]}
        self.db.execute("INSERT INTO intents(id,request) VALUES(?,?)", (key, canonical(req)))
        record(self.db, "intent_committed", req)

    def step(self, bar):
        if self.processed(bar): return
        try:
            self.reconcile()
        except ConnectionError:
            with self.db: record(self.db, "transport_disconnected", {"market_ts": bar["ts"]})
            return
        now = datetime.fromtimestamp(bar["ts"], ET)
        day, minute = now.date().isoformat(), now.hour * 60 + now.minute
        previous = self.db.execute("SELECT MAX(ts) FROM bars").fetchone()[0]
        if previous is not None and bar["ts"] <= previous:
            raise ValueError("Worker market time moved backwards")
        with self.db:
            if previous is not None and datetime.fromtimestamp(previous, ET).date() == now.date() and bar["ts"] - previous != 60:
                self.db.execute("INSERT OR IGNORE INTO halted_days VALUES(?,?)", (day, "missing_market_event"))
                record(self.db, "market_gap", {"from": previous, "to": bar["ts"], "day": day})
            self.db.execute("INSERT INTO bars VALUES(?,?)", (bar["ts"], canonical(bar)))
            record(self.db, "market_observed", bar)
            account = self.account(bar["close"])
            day_start = now.replace(hour=9, minute=30, second=0, microsecond=0).timestamp()
            prior = self.db.execute("SELECT value FROM meta WHERE key=?", (f"equity/{day}",)).fetchone()
            if prior is None:
                self.db.execute("INSERT INTO meta VALUES(?,?)", (f"equity/{day}", str(account["equity_cents"])))
                prior_equity = account["equity_cents"]
            else: prior_equity = int(prior[0])
            peak_row = self.db.execute("SELECT value FROM meta WHERE key='peak_equity'").fetchone()
            peak = max(int(peak_row[0]) if peak_row else self.spec["initial_balance_cents"], account["equity_cents"])
            self.db.execute("INSERT OR REPLACE INTO meta VALUES('peak_equity',?)", (str(peak),))
            loss_limit = prior_equity - account["equity_cents"] >= self.spec["daily_loss_limit_cents"]
            drawdown_limit = peak - account["equity_cents"] >= self.spec["drawdown_limit_cents"]
            if loss_limit or drawdown_limit:
                self.db.execute("INSERT OR IGNORE INTO halted_days VALUES(?,?)", (day, "risk_limit"))
                if drawdown_limit: self.db.execute("INSERT OR REPLACE INTO meta VALUES('risk_halted','true')")
            halted = self.db.execute("SELECT 1 FROM halted_days WHERE day=?", (day,)).fetchone() or self.db.execute("SELECT 1 FROM meta WHERE key='risk_halted'").fetchone()
            if minute == 9 * 60 + 44 and not halted:
                opening = [json.loads(r[0]) for r in self.db.execute("SELECT payload FROM bars WHERE ts>=? AND ts<=? ORDER BY ts", (day_start, bar["ts"]))]
                valid = len(opening) == 15 and all(b["ts"] == day_start + i * 60 and b["volume"] > 0 for i, b in enumerate(opening))
                qty = self.spec["quantity"]
                risk = qty * ((self.spec["stop_ticks"] + 2 * self.spec["slippage_ticks"]) * self.spec["tick_value_cents"] + 2 * self.spec["commission_per_side_cents"])
                if valid and not account["position"] and risk <= self.spec["max_planned_risk_cents"] and qty <= self.spec["max_quantity"]:
                    delta = bar["close"] - opening[0]["open"]
                    if delta: self._intent(day, "entry", 1 if delta > 0 else -1, qty, bar)
                else:
                    record(self.db, "entry_suppressed", {"day": day, "reason": "opening_data_or_risk"})
            if account["position"] and (minute >= 10 * 60 + 14 or loss_limit or drawdown_limit):
                self._intent(day, "exit", -1 if account["position"] > 0 else 1, abs(account["position"]), bar)
        try:
            self.dispatch()
        except ConnectionError:
            with self.db: record(self.db, "acknowledgment_unknown", {"market_ts": bar["ts"]})
