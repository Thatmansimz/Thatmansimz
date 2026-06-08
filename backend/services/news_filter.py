"""
Red-Folder News Filter
======================

High-impact ("red folder" on ForexFactory) economic releases — CPI, NFP, FOMC,
PPI, retail sales, ISM, etc. — cause violent, gap-through-your-stop moves. The
edge in any breakout system evaporates in those seconds. The professional move
is simple: DO NOT hold or open a position inside a blackout window around them.

This filter blocks new entries within `pre_minutes` before and `post_minutes`
after any high-impact event. Two sources of events:

  1. RECURRING time-of-day windows (ET) that are almost always high-impact:
       • 08:30  — CPI / NFP / PPI / GDP / retail sales (pre-open, volatile open)
       • 10:00  — ISM / JOLTS / consumer confidence  (inside our trading window)
       • 14:00  — FOMC statement / minutes            (after our cutoff)
     08:30 and 14:00 sit outside the 09:45–12:00 entry window, so in practice
     the 10:00 window is the one that gates trades — exactly the red-folder slot.

  2. An EXPLICIT calendar file (data/news_calendar.json) you populate from
     ForexFactory's weekly high-impact events for pinpoint accuracy:

       [
         {"datetime": "2026-06-11T08:30:00", "impact": "High", "title": "CPI m/m"},
         {"datetime": "2026-06-18T14:00:00", "impact": "High", "title": "FOMC Rate"}
       ]
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

HIGH_IMPACT_TOKENS = {"high", "red", "3", "high impact"}

# (hour, minute, label) — recurring ET windows that are reliably high-impact
DEFAULT_RECURRING = [
    (8, 30, "08:30 data release"),
    (10, 0, "10:00 data release"),
    (14, 0, "14:00 FOMC"),
]


class NewsFilter:
    def __init__(
        self,
        enabled: bool = True,
        pre_minutes: int = 15,
        post_minutes: int = 15,
        calendar_path: str | None = "data/news_calendar.json",
        use_recurring: bool = True,
    ):
        self.enabled = enabled
        self.pre = int(pre_minutes)
        self.post = int(post_minutes)
        self.use_recurring = use_recurring
        self.recurring = DEFAULT_RECURRING if use_recurring else []
        self.events: list[dict] = []  # {"date": date, "mod": int, "title": str}
        if calendar_path:
            self._load_calendar(calendar_path)

    def _load_calendar(self, path: str) -> None:
        if not os.path.exists(path):
            logger.info("News calendar not found at %s — using recurring windows only", path)
            return
        try:
            with open(path, "r") as fh:
                data = json.load(fh)
        except Exception as exc:
            logger.warning("Could not parse news calendar %s: %s", path, exc)
            return

        items = data if isinstance(data, list) else data.get("events", [])
        loaded = 0
        for item in items:
            if not isinstance(item, dict) or "datetime" not in item:
                continue
            impact = str(item.get("impact", "high")).strip().lower()
            if impact not in HIGH_IMPACT_TOKENS:
                continue
            try:
                dt = datetime.fromisoformat(item["datetime"])
            except ValueError:
                continue
            self.events.append({
                "date": dt.date(),
                "mod": dt.hour * 60 + dt.minute,
                "title": item.get("title", "high-impact event"),
            })
            loaded += 1
        if loaded:
            logger.info("Loaded %d high-impact news events from %s", loaded, path)

    def in_blackout(self, ts) -> tuple[bool, str]:
        """
        ts: a timestamp with .hour/.minute/.date() in US/Eastern.
        Returns (is_blackout, reason).
        """
        if not self.enabled:
            return False, ""

        mod = ts.hour * 60 + ts.minute

        # Recurring windows
        for h, m, label in self.recurring:
            center = h * 60 + m
            if center - self.pre <= mod <= center + self.post:
                return True, label

        # Explicit calendar events on the same date
        try:
            d = ts.date()
        except Exception:
            return False, ""
        for ev in self.events:
            if ev["date"] == d and (ev["mod"] - self.pre <= mod <= ev["mod"] + self.post):
                return True, ev["title"]

        return False, ""
