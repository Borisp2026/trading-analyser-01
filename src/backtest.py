"""
backtest.py
Walks backward through a stock's price history, replaying the Cycle Trading
Analysis signals as if running the scanner each day in the past, then checks
what actually happened next — to report a real accuracy/win-rate for each
signal type. Also supports backtesting the existing RSI/MACD/Bollinger
composite score the same way, so all signal types are comparably scored.

Usage (standalone):
    python backtest.py EOS.AX
    python backtest.py --all          # backtest every ticker in watchlist.json

Output: prints + saves reports/backtest_results.json
"""

import sys
import json
import warnings
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent))
from cycle_analysis import detect_daily_cycles, check_trendline_break, check_confirmation_signal
from analyser import calc_indicators, generate_signals, load_watchlist

warnings.filterwarnings("ignore")

REPORTS_DIR = Path(__file__).parent.parent / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

FORWARD_WINDOWS = [5, 10, 20]   # trading days forward to measure outcome


# ─────────────────────────────────────────────
# OUTCOME MEASUREMENT
# ─────────────────────────────────────────────
def forward_return(close, idx, days):
    """Return % change `days` trading days after index `idx`, or None if out of range."""
    if idx + days >= len(close):
        return None
    p0 = float(close.iloc[idx])
    p1 = float(close.iloc[idx + days])
    return (p1 - p0) / p0 * 100


# ─────────────────────────────────────────────
# BACKTEST: CYCLE CONFIRMATION SIGNAL
# ─────────────────────────────────────────────
def backtest_cycle_signals(df, ticker, min_history=80):
    """
    Walk forward day-by-day through history. On each day, re-run cycle
    detection using ONLY data up to that day (no lookahead), check if the
    '90% confirmation' signal or a 'trendline break' fired, and record what
    happened over the next 5/10/20 days.
    """
    close = df["Close"].squeeze()
    results = {
        "confirmation_signal": [],
        "trendline_break":     [],
        "right_translated":    [],
        "left_translated":     [],
    }

    step = 3  # check every 3 trading days to keep runtime reasonable
    for i in range(min_history, len(close) - max(FORWARD_WINDOWS), step):
        window_df = df.iloc[: i + 1]
        window_close = window_df["Close"].squeeze()

        try:
            cycles, _ = detect_daily_cycles(window_df)
        except Exception:
            continue
        if not cycles:
            continue

        current_cycle = cycles[-1]

        # Confirmation signal check
        try:
            confirmed = check_confirmation_signal(window_df, current_cycle)
        except Exception:
            confirmed = False

        if confirmed:
            outcomes = {f"{d}d": forward_return(close, i, d) for d in FORWARD_WINDOWS}
            results["confirmation_signal"].append({"date": str(close.index[i].date()), **outcomes})

        # Trendline break check
        try:
            tl = check_trendline_break(window_df, current_cycle)
        except Exception:
            tl = None

        if tl and tl["broken"]:
            outcomes = {f"{d}d": forward_return(close, i, d) for d in FORWARD_WINDOWS}
            results["trendline_break"].append({"date": str(close.index[i].date()), **outcomes})

        # Translation outcomes (measured at point of detection)
        key = "right_translated" if current_cycle["translation"] == "right" else "left_translated"
        outcomes = {f"{d}d": forward_return(close, i, d) for d in FORWARD_WINDOWS}
        results[key].append({"date": str(close.index[i].date()), **outcomes})

    return results


# ─────────────────────────────────────────────
# BACKTEST: COMPOSITE TECHNICAL SCORE (RSI/MACD/BB/MA)
# ─────────────────────────────────────────────
def backtest_composite_signals(df, ticker, name, min_history=60):
    """
    Same walk-forward approach for the existing composite scoring system,
    so cycle signals and technical signals can be compared on equal footing.
    """
    close = df["Close"].squeeze()
    results = {"buy_signal": [], "sell_signal": []}

    step = 3
    for i in range(min_history, len(close) - max(FORWARD_WINDOWS), step):
        window_df = calc_indicators(df.iloc[: i + 1])
        try:
            sig = generate_signals(window_df, ticker, name)
        except Exception:
            continue

        outcomes = {f"{d}d": forward_return(close, i, d) for d in FORWARD_WINDOWS}
        entry = {"date": str(close.index[i].date()), "score": sig["score"], **outcomes}

        if sig["score"] >= 2:
            results["buy_signal"].append(entry)
        elif sig["score"] <= -2:
            results["sell_signal"].append(entry)

    return results


# ─────────────────────────────────────────────
# SUMMARISE ACCURACY
# ─────────────────────────────────────────────
def summarise(signal_events, expect_positive=True):
    """
    For a list of {date, 5d, 10d, 20d} events, compute win rate (did the
    move go the expected direction) and average return for each horizon.
    """
    summary = {}
    for horizon in [f"{d}d" for d in FORWARD_WINDOWS]:
        rets = [e[horizon] for e in signal_events if e.get(horizon) is not None]
        if not rets:
            summary[horizon] = {"count": 0, "win_rate": None, "avg_return": None}
            continue

        if expect_positive:
            wins = sum(1 for r in rets if r > 0)
        else:
            wins = sum(1 for r in rets if r < 0)

        summary[horizon] = {
            "count":      len(rets),
            "win_rate":   round(wins / len(rets) * 100, 1),
            "avg_return": round(float(np.mean(rets)), 2),
            "best":       round(float(np.max(rets)), 2),
            "worst":      round(float(np.min(rets)), 2),
        }
    return summary


# ─────────────────────────────────────────────
# RUN BACKTEST FOR ONE TICKER
# ─────────────────────────────────────────────
def run_backtest(ticker, name, period="3y"):
    print(f"\n🔬 Backtesting {ticker} ({name})  —  {period} history")
    df = yf.Ticker(ticker).history(period=period)
    if df.empty or len(df) < 100:
        print(f"  ⚠ Not enough data for {ticker}")
        return None

    cycle_events     = backtest_cycle_signals(df, ticker)
    composite_events = backtest_composite_signals(df, ticker, name)

    report = {
        "ticker": ticker,
        "name": name,
        "history_period": period,
        "bars_tested": len(df),
        "cycle_signals": {
            "confirmation_signal_90pct": {
                "description": "Close above trendline + above 10D SMA (expect price to rise)",
                **summarise(cycle_events["confirmation_signal"], expect_positive=True),
            },
            "trendline_break": {
                "description": "Close breaks below Daily Cycle Trendline (expect further decline)",
                **summarise(cycle_events["trendline_break"], expect_positive=False),
            },
            "right_translated_cycle": {
                "description": "Daily Cycle is right-translated (expect bullish continuation)",
                **summarise(cycle_events["right_translated"], expect_positive=True),
            },
            "left_translated_cycle": {
                "description": "Daily Cycle is left-translated (expect bearish / failed cycle)",
                **summarise(cycle_events["left_translated"], expect_positive=False),
            },
        },
        "composite_technical_signals": {
            "buy_signal": {
                "description": "Composite score >= +2 (RSI/MACD/BB/MA blend)",
                **summarise(composite_events["buy_signal"], expect_positive=True),
            },
            "sell_signal": {
                "description": "Composite score <= -2 (RSI/MACD/BB/MA blend)",
                **summarise(composite_events["sell_signal"], expect_positive=False),
            },
        },
    }

    # Console summary
    for group_name, group in [("CYCLE", report["cycle_signals"]), ("COMPOSITE", report["composite_technical_signals"])]:
        print(f"  ── {group_name} signals ──")
        for sig_name, sig in group.items():
            d10 = sig.get("10d", {})
            if d10.get("count"):
                print(f"    {sig_name:28s}  n={d10['count']:3d}  10d win-rate={d10['win_rate']}%  avg={d10['avg_return']:+.2f}%")
            else:
                print(f"    {sig_name:28s}  no occurrences found")

    return report


def run_all(period="3y"):
    config = load_watchlist()
    all_reports = []
    for stock in config["stocks"]:
        result = run_backtest(stock["ticker"], stock["name"], period=period)
        if result:
            all_reports.append(result)

    out_path = REPORTS_DIR / "backtest_results.json"
    with open(out_path, "w") as f:
        json.dump({"generated": datetime.now().isoformat(), "results": all_reports}, f, indent=2)
    print(f"\n✅ Backtest results saved → {out_path}")
    return all_reports


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--all":
        run_all()
    elif len(sys.argv) > 1:
        ticker = sys.argv[1]
        run_backtest(ticker, ticker)
    else:
        print("Usage: python backtest.py <TICKER>   OR   python backtest.py --all")
