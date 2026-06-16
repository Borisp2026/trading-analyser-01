# 📈 Trading Analyser

Automated nightly stock analysis system for ASX shares.
Runs every weekday at **6:00 PM AWST** via GitHub Actions.

## What it does
- Analyses your watchlist using RSI, MACD, Bollinger Bands, Moving Averages & volume
- Runs **Cycle Trading Analysis** (DJRTrading-style Daily/Intermediate Cycle methodology) — auto-detects cycle length, DCL/HCH/HCL/DCH structure, translation, trendline breaks, and failed cycles
- Generates **buy / hold / sell signals** with reasoning and timing guidance — shown separately per method AND blended into one combined score
- Tracks **global index correlations** (ASX vs NASDAQ, FTSE, Nikkei, etc.)
- **Backtests** every signal type against historical data to report real win-rate and average return
- Emails a **PDF report** to your Gmail
- Publishes a **live web dashboard** on GitHub Pages with a toggle to view Technical-only, Cycle-only, or Blended signals

## 🌐 Dashboard
**[View Live Dashboard](https://borisp2026.github.io/trading-analyser-01/)**

## Setup

### 1. Add GitHub Secrets
Go to **Settings → Secrets and variables → Actions → New repository secret**

| Secret Name | Value |
|---|---|
| `GMAIL_ADDRESS` | Your Gmail address |
| `GMAIL_APP_PASSWORD` | Your 16-char Gmail App Password |
| `REPORT_EMAIL` | Email address to receive reports |

### 2. Edit your watchlist
Edit `data/watchlist.json` to add or remove stocks.
Set `price_max` to filter stocks by maximum price.

### 3. Run manually
Go to **Actions → Nightly Trading Report → Run workflow**

### 4. Run a backtest (optional, on demand)
Go to **Actions → Backtest Cycle & Technical Signals → Run workflow**
This measures historical accuracy of every signal type (Cycle confirmation, trendline breaks, RSI/MACD/BB composite) across your whole watchlist and publishes the results to the dashboard. Runs automatically every Sunday too.

## Project Structure
```
trading-analyser/
├── .github/workflows/
│   ├── nightly.yml                 # 6pm scanner + report
│   └── backtest.yml                # On-demand / weekly accuracy backtest
├── src/
│   ├── analyser.py                 # Main analysis engine (technical + blending)
│   ├── cycle_analysis.py           # Cycle Trading Analysis (DJRTrading methodology)
│   ├── backtest.py                 # Historical signal accuracy testing
│   └── build_dashboard.py          # HTML dashboard builder
├── data/
│   └── watchlist.json              # Your stock watchlist
├── reports/
│   ├── latest.json                 # Latest data (auto-generated)
│   ├── backtest_results.json       # Latest backtest stats (auto-generated)
│   └── report_YYYY-MM-DD.pdf       # PDF reports (auto-generated)
├── index.html                      # Dashboard (auto-generated)
└── requirements.txt
```

## Technical Indicators Used
| Indicator | Purpose |
|---|---|
| RSI (14) | Overbought / oversold detection |
| MACD (12/26/9) | Momentum and trend direction |
| Bollinger Bands (20,2) | Volatility and price extremes |
| MA20 / MA50 / MA200 | Short, medium, long-term trends |
| Volume spike (1.5x avg) | Confirm breakouts and sell-offs |
| Golden / Death Cross | Major trend change signals |

## Cycle Trading Analysis
Implements the Daily Cycle / Intermediate Cycle framework (DJRTrading-style):
- **Daily Cycle length is auto-detected per stock** using return autocorrelation (typically 25-50 trading days)
- Identifies **DCL (Daily Cycle Low) → HCH (Half Cycle High) → HCL (Half Cycle Low) → DCH (Daily Cycle High)** structure
- Flags **right-translated** (bullish, DCH after midpoint) vs **left-translated** (bearish, DCH before midpoint) cycles
- Detects **Daily Cycle Trendline breaks** (DCL0→HCL line) — the key decline-confirmation signal
- Flags the **"90% confirmation"** signal: close above trendline resistance + above 10-day SMA
- Warns when a stock is in **Daily Cycle 3 or 4 of its Intermediate Cycle** (the "High Risk Entry Area" per the methodology)
- Detects **Failed Cycles** (a new low printing below the cycle's starting low)
- Groups Daily Cycles into **Intermediate Cycles** (~4 Daily Cycles) and tracks the Intermediate Cycle Low (ICL)

This is shown as its own signal lens on the dashboard, and its score is also blended with the technical score for one combined recommendation per stock.

## Backtesting
`backtest.py` walks back through each stock's price history day-by-day (using only data available up to that point — no lookahead bias), replays both the Cycle signals and the Technical composite signals, and checks what actually happened over the next 5/10/20 trading days. This produces a real win-rate and average return for each signal type, shown on the dashboard under "Signal Accuracy".

## ⚠ Disclaimer
This tool is for **informational purposes only** and does not constitute financial advice.
Always do your own research and consult a financial adviser before investing.
