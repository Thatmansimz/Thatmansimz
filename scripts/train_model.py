#!/usr/bin/env python3
"""
Model Training Script
Downloads 2 years of historical data for each configured symbol, engineers
all technical features, trains the GradientBoosting + RandomForest ensemble,
and saves the models to backend/models/trained/.

Usage:
    python scripts/train_model.py
    python scripts/train_model.py --symbols MES MNQ --period 60d
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time

# Make sure project root is on the path when running as a script
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("train_model")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train AI trading models")
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=["MES", "MNQ"],
        help="List of symbols to train (default: MES MNQ)",
    )
    parser.add_argument(
        "--period",
        default="60d",
        help="Data period for yfinance (e.g. 60d, 1y, 2y). Note: 5m interval is limited to 60 days.",
    )
    parser.add_argument(
        "--interval",
        default="5m",
        help="Bar interval (default: 5m)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.65,
        help="Confidence threshold (default: 0.65)",
    )
    return parser.parse_args()


def print_section(title: str):
    width = 60
    print("\n" + "=" * width)
    print(f"  {title}")
    print("=" * width)


def train_symbol(symbol: str, period: str, interval: str) -> dict:
    from backend.services.market_data import MarketDataService
    from backend.services.ai_engine import AIEngine

    md = MarketDataService()
    engine = AIEngine(confidence_threshold=0.0)

    print(f"\n[{symbol}] Downloading data: period={period} interval={interval}")
    t0 = time.time()
    df = md.get_historical(symbol, period=period, interval=interval)
    if df.empty:
        print(f"[{symbol}] ERROR: No data returned.")
        return {"symbol": symbol, "error": "No data"}

    print(f"[{symbol}] {len(df)} bars downloaded in {time.time()-t0:.1f}s")

    print(f"[{symbol}] Computing technical indicators ...")
    t1 = time.time()
    df = md.add_indicators(df)
    print(f"[{symbol}] Indicators computed: {df.shape[1]} columns in {time.time()-t1:.1f}s")

    print(f"[{symbol}] Training ML ensemble ...")
    t2 = time.time()
    metrics = engine.train(df, symbol)
    elapsed = time.time() - t2

    if not metrics:
        print(f"[{symbol}] Training failed — insufficient data or signals.")
        return {"symbol": symbol, "error": "Training failed"}

    print(f"[{symbol}] Training complete in {elapsed:.1f}s")
    return metrics


def print_metrics(metrics: dict):
    symbol = metrics.get("symbol", "?")
    print(f"\n  Symbol      : {symbol}")
    print(f"  Train bars  : {metrics.get('train_bars', 'N/A')}")
    print(f"  Test bars   : {metrics.get('test_bars', 'N/A')}")
    print(f"  Accuracy    : {metrics.get('accuracy', 0)*100:.1f}%")
    print(f"  Precision   : {metrics.get('precision', 0)*100:.1f}%")
    print(f"  Recall      : {metrics.get('recall', 0)*100:.1f}%")
    print(f"  F1 Score    : {metrics.get('f1', 0)*100:.1f}%")
    print(f"  Long prec.  : {metrics.get('long_precision', 0)*100:.1f}%")
    print(f"  Short prec. : {metrics.get('short_precision', 0)*100:.1f}%")


def main():
    args = parse_args()

    print_section("AI Day Trading Platform — Model Trainer")
    print(f"  Symbols  : {args.symbols}")
    print(f"  Period   : {args.period}")
    print(f"  Interval : {args.interval}")

    all_metrics = []
    for symbol in args.symbols:
        print_section(f"Training: {symbol}")
        metrics = train_symbol(symbol, args.period, args.interval)
        all_metrics.append(metrics)

    print_section("Training Summary")
    for m in all_metrics:
        if "error" in m:
            print(f"\n  [{m['symbol']}] FAILED: {m['error']}")
        else:
            print_metrics(m)

    # Model file locations
    model_dir = os.path.join(os.path.dirname(__file__), "..", "backend", "models", "trained")
    model_dir = os.path.abspath(model_dir)
    print(f"\n  Models saved to: {model_dir}")
    if os.path.exists(model_dir):
        for f in sorted(os.listdir(model_dir)):
            path = os.path.join(model_dir, f)
            size_kb = os.path.getsize(path) / 1024
            print(f"    {f}  ({size_kb:.0f} KB)")

    print_section("Done")
    print("  Run the backend to use trained models:")
    print("    uvicorn backend.main:app --host 0.0.0.0 --port 8000")
    print()


if __name__ == "__main__":
    main()
