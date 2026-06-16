"""
cycle_analysis.py
Implements the "Cycle Trading Analysis" methodology (DJRTrading style):

  Daily Cycle structure:  DCL(start) -> HCH -> HCL -> DCH -> decline -> next DCL
  Intermediate Cycle:     ~4 Daily Cycles, ICL = lowest DCL in the group

  Key concepts coded here:
    - Auto-detect DCL/DCH (swing low/high) pivots using a rolling window
    - HCH = first significant high before cycle midpoint
    - HCL = first significant low after HCH, before cycle midpoint -> used for trendline
    - Right-translated  = DCH occurs AFTER cycle midpoint (bullish)
    - Left-translated   = DCH occurs BEFORE cycle midpoint (bearish / failed-cycle risk)
    - Failed Cycle      = price breaks below DCL0 (cycle start) before next DCL forms
    - Daily Cycle Trendline = line from DCL0 through HCL; a close below it = decline confirmed
    - Confirmation       = close above trendline + above 10-day SMA after a DCL (90% per the source material)

This module is intentionally self-contained so it can be:
  (a) called standalone for a "Cycle View" signal, and
  (b) blended into the main composite score in analyser.py
"""

import numpy as np
import pandas as pd


# ─────────────────────────────────────────────
# PIVOT / SWING DETECTION
# ─────────────────────────────────────────────
def find_swing_points(close, window=5):
    """
    Returns boolean masks for swing highs and swing lows.
    A swing high/low is a local extreme over `window` bars on each side.
    """
    highs = pd.Series(False, index=close.index)
    lows  = pd.Series(False, index=close.index)

    for i in range(window, len(close) - window):
        seg = close.iloc[i - window: i + window + 1]
        if close.iloc[i] == seg.max():
            highs.iloc[i] = True
        if close.iloc[i] == seg.min():
            lows.iloc[i] = True

    return highs, lows


def estimate_cycle_length(close, min_len=20, max_len=70):
    """
    Auto-detect dominant Daily Cycle length using autocorrelation of returns.
    Searches lag range [min_len, max_len] trading days, returns the lag with
    the strongest positive autocorrelation peak (the repeating cycle rhythm).
    """
    rets = close.pct_change().dropna()
    if len(rets) < max_len + 10 or rets.std() == 0:
        return 35  # fallback default

    best_lag, best_corr = 35, -1
    for lag in range(min_len, max_len + 1):
        if lag >= len(rets):
            break
        c = rets.autocorr(lag=lag)
        if pd.notna(c) and c > best_corr:
            best_corr = c
            best_lag = lag

    return best_lag


# ─────────────────────────────────────────────
# CYCLE DETECTION (DCL -> HCH -> HCL -> DCH -> DCL)
# ─────────────────────────────────────────────
def filter_major_lows(close, low_idx, min_spacing_days):
    """
    Swing-low detection often flags minor dips alongside true cycle lows.
    Keep only 'major' lows: a low is major if no lower low exists within
    min_spacing_days on either side of it (i.e. it's the deepest point in
    its local neighbourhood, not just a local pivot inside a bigger move).
    """
    if not low_idx:
        return []

    major = []
    for d in low_idx:
        window_start = d - pd.Timedelta(days=min_spacing_days)
        window_end   = d + pd.Timedelta(days=min_spacing_days)
        local_slice  = close.loc[window_start:window_end]
        if len(local_slice) == 0:
            continue
        if close.loc[d] <= local_slice.min() + 1e-9:
            major.append(d)

    # Deduplicate consecutive majors that are within a few days of each other
    # (flat-bottom dips can register multiple adjacent points) — keep the lowest.
    deduped = []
    for d in major:
        if deduped and (d - deduped[-1]).days <= max(3, min_spacing_days * 0.15):
            if close.loc[d] < close.loc[deduped[-1]]:
                deduped[-1] = d
        else:
            deduped.append(d)

    return deduped


def detect_daily_cycles(df, cycle_len=None):
    """
    Walk through price history and segment it into Daily Cycles.
    Returns a list of cycle dicts with DCL0, HCH, HCL, DCH, DCL1 indices/dates/prices,
    translation type, and whether it failed.
    """
    close = df["Close"].squeeze()

    if cycle_len is None:
        cycle_len = estimate_cycle_length(close)

    # Pivot window for raw swing detection — small, so we catch every local
    # extreme (including minor ones); major-low filtering below removes noise.
    window = max(2, cycle_len // 10)
    swing_highs, swing_lows = find_swing_points(close, window=window)

    raw_low_idx  = list(close.index[swing_lows])
    high_idx     = list(close.index[swing_highs])

    # Only keep lows that are the deepest point within roughly half a cycle
    # on either side — these are the genuine Daily Cycle Lows (DCL), filtering
    # out minor dips that would otherwise be mistaken for cycle boundaries.
    min_spacing = max(10, int(cycle_len * 0.5))
    low_idx = filter_major_lows(close, raw_low_idx, min_spacing)

    cycles = []
    if len(low_idx) < 2:
        return cycles, cycle_len

    for i in range(len(low_idx) - 1):
        dcl0_date = low_idx[i]
        dcl1_date = low_idx[i + 1]
        dcl0_price = float(close.loc[dcl0_date])
        dcl1_price = float(close.loc[dcl1_date])

        duration_days = (dcl1_date - dcl0_date).days
        # Skip implausible micro-segments (noise) or huge multi-cycle spans
        if duration_days < cycle_len * 0.4 or duration_days > cycle_len * 2.5:
            continue

        midpoint_date = dcl0_date + (dcl1_date - dcl0_date) / 2

        # Highs strictly between DCL0 and DCL1
        highs_in_range = [h for h in high_idx if dcl0_date < h < dcl1_date]
        if not highs_in_range:
            continue

        # DCH = highest high in the segment
        dch_date  = max(highs_in_range, key=lambda d: close.loc[d])
        dch_price = float(close.loc[dch_date])

        # HCH = highest high strictly before DCH (a genuine secondary peak,
        # not just "first high" which can equal DCH itself)
        highs_before_dch = [h for h in highs_in_range if h < dch_date]
        if highs_before_dch:
            hch_date  = max(highs_before_dch, key=lambda d: close.loc[d])
            hch_price = float(close.loc[hch_date])
        else:
            hch_date, hch_price = dch_date, dch_price  # no distinct secondary peak found

        # HCL = lowest point strictly between HCH and DCH (the pullback that
        # forms the Daily Cycle Trendline together with DCL0)
        if hch_date != dch_date:
            span = close.loc[hch_date:dch_date]
            interior = span.iloc[1:-1]
            if len(interior) > 0:
                hcl_date  = interior.idxmin()
                hcl_price = float(close.loc[hcl_date])
            else:
                hcl_date, hcl_price = None, None
        else:
            hcl_date, hcl_price = None, None

        # Translation: right (bullish) if DCH after midpoint, left (bearish) if before
        translation = "right" if dch_date > midpoint_date else "left"

        # Failed cycle: DCL1 prints LOWER than DCL0 (lower low)
        failed = dcl1_price < dcl0_price

        cycles.append({
            "dcl0_date": dcl0_date, "dcl0_price": dcl0_price,
            "hch_date":  hch_date,  "hch_price":  hch_price,
            "hcl_date":  hcl_date,  "hcl_price":  hcl_price,
            "dch_date":  dch_date,  "dch_price":  dch_price,
            "dcl1_date": dcl1_date, "dcl1_price": dcl1_price,
            "midpoint_date": midpoint_date,
            "duration_days": duration_days,
            "translation": translation,
            "failed_cycle": failed,
        })

    return cycles, cycle_len


def group_intermediate_cycles(daily_cycles, group_size=4):
    """
    Group consecutive Daily Cycles into an Intermediate Cycle.
    ICL = the DCL0 of the group with the lowest price (typically the first
    Daily Cycle low of the group, but we confirm by lowest price).
    """
    intermediates = []
    for i in range(0, len(daily_cycles), group_size):
        group = daily_cycles[i: i + group_size]
        if not group:
            continue
        icl_cycle = min(group, key=lambda c: c["dcl0_price"])
        intermediates.append({
            "daily_cycles": group,
            "icl_date":  icl_cycle["dcl0_date"],
            "icl_price": icl_cycle["dcl0_price"],
            "start_date": group[0]["dcl0_date"],
            "end_date":   group[-1]["dcl1_date"],
            "num_daily_cycles": len(group),
        })
    return intermediates


# ─────────────────────────────────────────────
# TRENDLINE FROM DCL0 -> HCL (Daily Cycle Trendline)
# ─────────────────────────────────────────────
def trendline_value_at(cycle, date, df):
    """
    Linear interpolation of the Daily Cycle Trendline (DCL0 -> HCL) at a given date.
    Returns None if HCL not available or date is before DCL0.
    """
    if cycle["hcl_date"] is None:
        return None

    x0 = cycle["dcl0_date"].toordinal()
    x1 = cycle["hcl_date"].toordinal()
    y0 = cycle["dcl0_price"]
    y1 = cycle["hcl_price"]

    if x1 == x0:
        return None

    slope = (y1 - y0) / (x1 - x0)
    x = date.toordinal()
    return y0 + slope * (x - x0)


def check_trendline_break(df, cycle):
    """
    Check whether the most recent close has broken below the Daily Cycle Trendline,
    which per the methodology confirms the cycle has topped and is in decline.
    """
    close = df["Close"].squeeze()
    last_date  = close.index[-1]
    last_price = float(close.iloc[-1])

    tl_value = trendline_value_at(cycle, last_date, df)
    if tl_value is None:
        return None

    broken = last_price < tl_value
    pct_from_line = (last_price - tl_value) / tl_value * 100
    return {
        "trendline_value": tl_value,
        "broken": broken,
        "pct_from_line": pct_from_line,
    }


def check_confirmation_signal(df, cycle):
    """
    'Close above trendline resistance AND above 10-day SMA' = ~90% confirmation
    of a new Daily Cycle Low having printed (per the source material).
    """
    close = df["Close"].squeeze()
    sma10 = close.rolling(10).mean()

    last_price = float(close.iloc[-1])
    last_sma10 = float(sma10.iloc[-1]) if not pd.isna(sma10.iloc[-1]) else None

    tl_check = check_trendline_break(df, cycle)
    if tl_check is None or last_sma10 is None:
        return False

    above_trendline = last_price > tl_check["trendline_value"]
    above_sma10      = last_price > last_sma10
    return above_trendline and above_sma10


# ─────────────────────────────────────────────
# MAIN: CYCLE SIGNAL FOR A STOCK
# ─────────────────────────────────────────────
def analyse_cycle(df, ticker, name):
    """
    Run full cycle analysis on a stock's price history and return a
    structured signal dict (mirrors the shape used by generate_signals()
    in analyser.py so it can plug into the same report/dashboard).
    """
    close = df["Close"].squeeze()
    if len(close) < 60:
        return None

    daily_cycles, cycle_len = detect_daily_cycles(df)
    if not daily_cycles:
        return {
            "ticker": ticker, "name": name, "cycle_len_detected": cycle_len,
            "status": "insufficient_data",
            "signals": [], "cautions": ["Not enough price history to detect a reliable cycle"],
            "score": 0, "recommendation": "HOLD / WATCH", "action_color": "hold",
            "current_cycle": None, "intermediates": [],
        }

    intermediates = group_intermediate_cycles(daily_cycles)
    current_cycle = daily_cycles[-1]
    current_position_in_ic = len(daily_cycles) % 4 or 4  # which Daily Cycle # within current IC (1-4)

    signals, cautions = [], []
    score = 0

    last_date  = close.index[-1]
    last_price = float(close.iloc[-1])
    days_since_dcl0 = (last_date - current_cycle["dcl0_date"]).days
    days_into_cycle_pct = days_since_dcl0 / current_cycle["duration_days"] * 100 if current_cycle["duration_days"] else 0

    # ── Translation read ──
    if current_cycle["translation"] == "right":
        signals.append(
            f"Right-translated Daily Cycle (DCH printed after midpoint) — bullish structure, "
            f"trend continuation favoured"
        )
        score += 2
    else:
        cautions.append(
            f"Left-translated Daily Cycle (DCH printed before midpoint) — bearish structure, "
            f"raises risk of a Failed Cycle"
        )
        score -= 2

    # ── Failed cycle check ──
    if current_cycle["failed_cycle"]:
        cautions.append(
            f"Failed Cycle detected — most recent low (${current_cycle['dcl1_price']:.2f}) "
            f"printed BELOW cycle start (${current_cycle['dcl0_price']:.2f}). Often marks a deeper low "
            f"or trend change."
        )
        score -= 3

    # ── Trendline break check ──
    tl = check_trendline_break(df, current_cycle)
    if tl:
        if tl["broken"]:
            cautions.append(
                f"Price has broken below the Daily Cycle Trendline ({tl['pct_from_line']:.1f}% below) "
                f"— decline phase confirmed, cycle searching for a bottom (DCL)"
            )
            score -= 2
        else:
            signals.append(
                f"Price holding above the Daily Cycle Trendline ({tl['pct_from_line']:.1f}% above) "
                f"— advancing phase intact"
            )
            score += 1

    # ── Confirmation signal (90% per methodology) ──
    confirmed = check_confirmation_signal(df, current_cycle)
    if confirmed:
        signals.append(
            "Close above trendline resistance AND above 10-day SMA — ~90% confirmation per "
            "cycle methodology that a new Daily Cycle Low has printed"
        )
        score += 3

    # ── High-risk zone warning (Daily Cycle 3 or 4 within the Intermediate Cycle) ──
    if current_position_in_ic >= 3:
        cautions.append(
            f"Currently in Daily Cycle {current_position_in_ic} of the Intermediate Cycle — "
            f"\"High Risk Entry Area\" per methodology. New long entries are higher risk; "
            f"existing positions should be managed toward exit on rallies."
        )
        score -= 1
    elif current_position_in_ic == 1:
        signals.append(
            "Currently in Daily Cycle 1 of a new Intermediate Cycle — \"Lower Risk Entry Area\" "
            "per methodology, most favourable point in the cycle structure for new long entries"
        )
        score += 1

    # ── Where are we in the cycle right now? ──
    if days_into_cycle_pct < 50 and current_cycle["dch_date"] is None:
        signals.append(f"Day {days_since_dcl0} of an estimated {current_cycle['duration_days']}-day cycle — still in advancing phase")
    elif last_date >= current_cycle["dch_date"]:
        cautions.append(f"Cycle has already made its high (DCH ${current_cycle['dch_price']:.2f}) — now in declining phase, searching for next DCL")

    # ── Entry/exit guidance per methodology ──
    buy_when = [
        "Close above Daily Cycle Trendline resistance AND above 10-day SMA (90% DCL confirmation)",
        "Half Cycle Low (HCL) forms and price recovers — early continuation entry",
        "1st Daily Cycle Low and recovery within a new Intermediate Cycle",
    ]
    sell_when = [
        f"Stop below DCL0 (${current_cycle['dcl0_price']:.2f}) or below most recent HCL"
        + (f" (${current_cycle['hcl_price']:.2f})" if current_cycle["hcl_price"] else ""),
        "By Day 25 of Daily Cycle 3, or anywhere in Daily Cycle 4 — sell into a rally to limit risk",
        "Daily Cycle Trendline breaks with a confirmed close below it",
    ]

    # ── Final recommendation ──
    if score >= 4:
        recommendation, action_color = "STRONG BUY", "buy_strong"
    elif score >= 1:
        recommendation, action_color = "BUY", "buy"
    elif score <= -4:
        recommendation, action_color = "STRONG SELL", "sell_strong"
    elif score <= -1:
        recommendation, action_color = "SELL / AVOID", "sell"
    else:
        recommendation, action_color = "HOLD / WATCH", "hold"

    return {
        "ticker": ticker, "name": name,
        "cycle_len_detected": cycle_len,
        "current_cycle_number_in_ic": current_position_in_ic,
        "translation": current_cycle["translation"],
        "failed_cycle": current_cycle["failed_cycle"],
        "days_since_dcl0": days_since_dcl0,
        "days_into_cycle_pct": round(days_into_cycle_pct, 1),
        "dcl0_price": current_cycle["dcl0_price"],
        "dcl0_date": str(current_cycle["dcl0_date"].date()),
        "dch_price": current_cycle["dch_price"],
        "dch_date": str(current_cycle["dch_date"].date()) if current_cycle["dch_date"] is not None else None,
        "hcl_price": current_cycle["hcl_price"],
        "trendline_broken": tl["broken"] if tl else None,
        "confirmed_new_dcl": confirmed,
        "signals": signals,
        "cautions": cautions,
        "buy_when": buy_when,
        "sell_when": sell_when,
        "score": score,
        "recommendation": recommendation,
        "action_color": action_color,
        "total_cycles_detected": len(daily_cycles),
        "total_intermediate_cycles": len(intermediates),
    }
