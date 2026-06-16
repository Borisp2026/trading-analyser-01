"""
build_dashboard.py
Reads reports/latest.json and writes index.html for GitHub Pages.
Run automatically after analyser.py completes.
"""

import json
from pathlib import Path
from datetime import datetime

ROOT       = Path(__file__).parent.parent
JSON_PATH  = ROOT / "reports" / "latest.json"
BACKTEST_PATH = ROOT / "reports" / "backtest_results.json"
HTML_PATH  = ROOT / "index.html"


def load_backtest_section():
    """Build an HTML section summarising backtest accuracy, if results exist."""
    if not BACKTEST_PATH.exists():
        return ""

    with open(BACKTEST_PATH) as f:
        bt = json.load(f)

    generated = bt.get("generated", "")[:16].replace("T", " ")
    results = bt.get("results", [])
    if not results:
        return ""

    # Aggregate across all tickers per signal type
    agg = {}
    for stock in results:
        for group_key in ["cycle_signals", "composite_technical_signals"]:
            for sig_name, sig in stock.get(group_key, {}).items():
                d10 = sig.get("10d", {})
                if not d10.get("count"):
                    continue
                key = (group_key, sig_name, sig.get("description", ""))
                agg.setdefault(key, {"count": 0, "wins_weighted": 0, "returns": []})
                agg[key]["count"] += d10["count"]
                agg[key]["wins_weighted"] += (d10["win_rate"] or 0) * d10["count"]
                agg[key]["returns"].append(d10["avg_return"] or 0)

    rows = ""
    for (group_key, sig_name, desc), data in sorted(agg.items(), key=lambda x: -x[1]["count"]):
        if data["count"] == 0:
            continue
        avg_win_rate = data["wins_weighted"] / data["count"]
        avg_return = sum(data["returns"]) / len(data["returns"]) if data["returns"] else 0
        group_label = "🔄 Cycle" if group_key == "cycle_signals" else "📊 Technical"
        win_color = "#16a34a" if avg_win_rate >= 55 else "#ca8a04" if avg_win_rate >= 45 else "#dc2626"
        rows += f"""
        <tr>
          <td>{group_label}</td>
          <td>{sig_name.replace('_',' ').title()}</td>
          <td style="font-size:11px;color:#64748b">{desc}</td>
          <td>{data['count']}</td>
          <td style="color:{win_color};font-weight:bold">{avg_win_rate:.0f}%</td>
          <td style="color:{'#16a34a' if avg_return>=0 else '#dc2626'}">{avg_return:+.2f}%</td>
        </tr>"""

    if not rows:
        return ""

    return f"""
  <div class="section-header">Signal Accuracy — Historical Backtest (10-day forward window)</div>
  <p style="font-size:12px;color:#64748b;margin-bottom:10px">Last run: {generated} AWST &nbsp;|&nbsp; Across {len(results)} stocks in watchlist &nbsp;|&nbsp; Win rate = % of occurrences where price moved in the expected direction</p>
  <table>
    <thead><tr>
      <th>Source</th><th>Signal</th><th>Description</th><th>Occurrences</th><th>Win Rate</th><th>Avg Return</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>
  """


def rec_css(action_color):
    return {
        "buy_strong":  ("#15803d", "#dcfce7"),
        "buy":         ("#166534", "#bbf7d0"),
        "hold":        ("#854d0e", "#fef9c3"),
        "sell":        ("#9a3412", "#ffedd5"),
        "sell_strong": ("#991b1b", "#fee2e2"),
    }.get(action_color, ("#374151", "#f3f4f6"))


def fmt_pct(v):
    if v is None:
        return "N/A"
    sign = "+" if v >= 0 else ""
    color = "#16a34a" if v >= 0 else "#dc2626"
    return f'<span style="color:{color}">{sign}{v:.1f}%</span>'


def build():
    if not JSON_PATH.exists():
        print("No latest.json found — skipping dashboard build.")
        return

    with open(JSON_PATH) as f:
        data = json.load(f)

    results      = data.get("results", [])
    correlations = data.get("correlations", [])
    generated    = data.get("generated", "")[:16].replace("T", " ")

    # Sort by blended score descending
    results.sort(key=lambda x: x.get("blended_score", x.get("score", 0)), reverse=True)

    buys  = [r for r in results if r.get("blended_score", r.get("score", 0)) >= 2]
    holds = [r for r in results if -2 < r.get("blended_score", r.get("score", 0)) < 2]
    sells = [r for r in results if r.get("blended_score", r.get("score", 0)) <= -2]

    # ── Build stock cards ──────────────────────────────────────────
    cards_html = ""
    for r in results:
        fg, bg = rec_css(r.get("action_color", "hold"))
        signals_html  = "".join(f'<li style="color:#166534">✓ {s}</li>' for s in r.get("signals", []))
        cautions_html = "".join(f'<li style="color:#dc2626">▲ {s}</li>' for s in r.get("cautions", []))
        buy_html      = "".join(f'<li>{b}</li>' for b in r.get("buy_when", []))
        sell_html     = "".join(f'<li>{s}</li>' for s in r.get("sell_when", []))
        news_html     = "".join(
            f'<div class="news-item">📰 {n["title"][:100]} <span class="news-date">{n.get("date","")}</span></div>'
            for n in r.get("news", []) if n.get("title")
        )
        ma_txt = ""
        if r.get("ma20"):
            ma_txt += f'MA20: ${r["ma20"]:.2f}'
        if r.get("ma50"):
            ma_txt += f'  |  MA50: ${r["ma50"]:.2f}'
        if r.get("ma200"):
            ma_txt += f'  |  MA200: ${r["ma200"]:.2f}'

        div_html = ""
        if r.get("div_yield"):
            div_html = f'<span class="badge" style="background:#ede9fe;color:#6d28d9">Div {r["div_yield"]*100:.2f}%</span>'

        # Cycle Trading Analysis block
        cycle_block = ""
        cyc = r.get("cycle")
        if cyc and cyc.get("status") != "insufficient_data":
            cfg, cbg = rec_css(cyc.get("action_color", "hold"))
            translation_txt = "Right-translated (bullish)" if cyc.get("translation") == "right" else "Left-translated (bearish)"
            cyc_signals_html  = "".join(f'<li style="color:#166534">✓ {s}</li>' for s in cyc.get("signals", []))
            cyc_cautions_html = "".join(f'<li style="color:#dc2626">▲ {s}</li>' for s in cyc.get("cautions", []))
            cycle_block = f"""
            <div class="cycle-section" style="margin-top:14px;border-top:2px dashed #e2e8f0;padding-top:12px">
              <div class="section-title" style="display:flex;justify-content:space-between;align-items:center">
                <span>🔄 Cycle Trading Analysis</span>
                <span style="background:{cfg};color:white;padding:2px 10px;border-radius:10px;font-size:11px">{cyc.get('recommendation','—')}</span>
              </div>
              <div class="ma-row">
                Cycle day {cyc.get('days_since_dcl0','?')} of ~{cyc.get('cycle_len_detected','?')}d &nbsp;|&nbsp;
                Daily Cycle {cyc.get('current_cycle_number_in_ic','?')} of 4 in Intermediate Cycle &nbsp;|&nbsp;
                {translation_txt}
              </div>
              <div class="two-col" style="margin-top:8px">
                <div>
                  <ul class="sig-list">{cyc_signals_html if cyc_signals_html else '<li style="color:#94a3b8">None</li>'}</ul>
                </div>
                <div>
                  <ul class="sig-list">{cyc_cautions_html if cyc_cautions_html else '<li style="color:#94a3b8">None</li>'}</ul>
                </div>
              </div>
            </div>
            """

        blended_fg, blended_bg = rec_css(r.get("blended_action_color", r.get("action_color", "hold")))
        tech_score = r.get("technical_score", r.get("score", 0))
        cycle_score = r.get("cycle_score", 0)
        blended_score = r.get("blended_score", r.get("score", 0))

        cards_html += f"""
        <div class="card" id="{r['ticker'].replace('.','_')}" data-tech="{tech_score}" data-cycle="{cycle_score}" data-blended="{blended_score}">
          <div class="card-header" style="background:{blended_fg};color:white">
            <div>
              <span class="ticker">{r['ticker']}</span>
              <span class="company">{r['name']}</span>
            </div>
            <span class="rec-badge">{r.get('blended_recommendation', r.get('recommendation','—'))}</span>
          </div>
          <div class="card-body">
            <div class="metrics">
              <div class="metric"><div class="m-val">${r.get('price',0):.3f}</div><div class="m-lbl">Price</div></div>
              <div class="metric"><div class="m-val">{r.get('rsi',0):.0f}</div><div class="m-lbl">RSI</div></div>
              <div class="metric"><div class="m-val">{fmt_pct(r.get('week_chg'))}</div><div class="m-lbl">1 Week</div></div>
              <div class="metric"><div class="m-val">{fmt_pct(r.get('month_chg'))}</div><div class="m-lbl">1 Month</div></div>
              <div class="metric"><div class="m-val" style="color:{blended_fg}">{blended_score:+d}</div><div class="m-lbl">Blended</div></div>
              <div class="metric"><div class="m-val" style="font-size:13px">{r.get('sector','N/A')}</div><div class="m-lbl">Sector</div></div>
            </div>

            <div class="score-breakdown">
              <span>Technical: <b>{tech_score:+d}</b></span>
              <span>+</span>
              <span>Cycle: <b>{cycle_score:+d}</b></span>
              <span>=</span>
              <span style="color:{blended_fg}">Blended: <b>{blended_score:+d}</b></span>
            </div>

            {f'<div class="ma-row">📈 {ma_txt}</div>' if ma_txt else ''}
            {div_html}

            <div class="two-col">
              <div>
                <div class="section-title" style="color:#166534">Technical Bullish Signals</div>
                <ul class="sig-list">{signals_html if signals_html else '<li style="color:#94a3b8">None detected</li>'}</ul>
              </div>
              <div>
                <div class="section-title" style="color:#dc2626">Technical Cautions</div>
                <ul class="sig-list">{cautions_html if cautions_html else '<li style="color:#94a3b8">None detected</li>'}</ul>
              </div>
            </div>

            {cycle_block}

            <div class="two-col" style="margin-top:12px">
              <div style="background:#f0fdf4;border-radius:6px;padding:10px">
                <div class="section-title" style="color:#166534">🟢 Buy When</div>
                <ul class="sig-list">{buy_html}</ul>
              </div>
              <div style="background:#fff1f2;border-radius:6px;padding:10px">
                <div class="section-title" style="color:#dc2626">🔴 Sell / Take Profit When</div>
                <ul class="sig-list">{sell_html}</ul>
              </div>
            </div>

            {f'<div class="news-section"><div class="section-title">Recent News</div>{news_html}</div>' if news_html else ''}
          </div>
        </div>
        """

    # ── Correlation table ──────────────────────────────────────────
    corr_rows = ""
    for c in correlations:
        corr_val = c.get("corr", 0)
        corr_bar = int(abs(corr_val) * 80)
        corr_col = "#16a34a" if corr_val > 0.5 else "#eab308" if corr_val > 0.2 else "#dc2626"
        corr_rows += f"""
        <tr>
          <td>{c['index']}</td>
          <td>{fmt_pct(c.get('chg_1d'))}</td>
          <td>{fmt_pct(c.get('chg_1mo'))}</td>
          <td>
            <div style="display:flex;align-items:center;gap:8px">
              <div style="width:{corr_bar}px;height:10px;background:{corr_col};border-radius:3px"></div>
              <span>{corr_val:.2f}</span>
            </div>
          </td>
        </tr>"""

    # ── Summary table ──────────────────────────────────────────────
    summary_rows = ""
    for r in results:
        blended_fg, _ = rec_css(r.get("blended_action_color", r.get("action_color", "hold")))
        ticker_link = r['ticker'].replace('.','_')
        tech_score = r.get("technical_score", r.get("score", 0))
        cycle_score = r.get("cycle_score", 0)
        blended_score = r.get("blended_score", r.get("score", 0))
        summary_rows += f"""
        <tr onclick="document.getElementById('{ticker_link}').scrollIntoView({{behavior:'smooth'}})" style="cursor:pointer">
          <td><b>{r['ticker']}</b></td>
          <td>{r['name']}</td>
          <td>${r.get('price',0):.3f}</td>
          <td>{r.get('rsi',0):.0f}</td>
          <td>{fmt_pct(r.get('week_chg'))}</td>
          <td>{tech_score:+d}</td>
          <td>{cycle_score:+d}</td>
          <td><span style="background:{blended_fg};color:white;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:bold">{r.get('blended_recommendation', r.get('recommendation','—'))}</span></td>
          <td style="color:{blended_fg};font-weight:bold">{blended_score:+d}</td>
        </tr>"""

    # ── Full HTML ──────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Trading Analyser Dashboard</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f1f5f9; color: #1e293b; }}

    .topbar {{ background: #0f172a; color: white; padding: 14px 24px; display: flex; justify-content: space-between; align-items: center; position: sticky; top: 0; z-index: 100; box-shadow: 0 2px 8px rgba(0,0,0,0.3); }}
    .topbar h1 {{ font-size: 18px; }}
    .topbar .updated {{ font-size: 12px; opacity: 0.6; }}

    .container {{ max-width: 1200px; margin: 0 auto; padding: 24px 16px; }}

    .summary-boxes {{ display: grid; grid-template-columns: repeat(3,1fr); gap: 16px; margin-bottom: 24px; }}
    .box {{ border-radius: 10px; padding: 20px; text-align: center; color: white; }}
    .box .count {{ font-size: 42px; font-weight: 700; }}
    .box .label {{ font-size: 13px; opacity: 0.85; margin-top: 4px; }}

    .section-header {{ font-size: 17px; font-weight: 700; color: #0f172a; margin: 24px 0 12px; padding-bottom: 6px; border-bottom: 2px solid #e2e8f0; }}

    table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 10px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }}
    th {{ background: #0f172a; color: white; padding: 10px 12px; text-align: left; font-size: 13px; }}
    td {{ padding: 9px 12px; font-size: 13px; border-bottom: 1px solid #f1f5f9; }}
    tr:last-child td {{ border-bottom: none; }}
    tr:hover td {{ background: #f8fafc; }}

    .card {{ background: white; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); margin-bottom: 20px; overflow: hidden; }}
    .card-header {{ padding: 14px 18px; display: flex; justify-content: space-between; align-items: center; }}
    .ticker {{ font-size: 20px; font-weight: 800; margin-right: 10px; }}
    .company {{ font-size: 14px; opacity: 0.85; }}
    .rec-badge {{ background: rgba(255,255,255,0.2); border: 1px solid rgba(255,255,255,0.4); padding: 4px 12px; border-radius: 20px; font-weight: 700; font-size: 13px; }}
    .card-body {{ padding: 18px; }}

    .metrics {{ display: grid; grid-template-columns: repeat(6,1fr); gap: 10px; margin-bottom: 14px; }}
    .metric {{ background: #f8fafc; border-radius: 8px; padding: 10px 6px; text-align: center; }}
    .m-val {{ font-size: 17px; font-weight: 700; }}
    .m-lbl {{ font-size: 11px; color: #64748b; margin-top: 3px; }}

    .ma-row {{ font-size: 12px; color: #475569; background: #f1f5f9; padding: 6px 10px; border-radius: 6px; margin-bottom: 10px; }}

    .score-breakdown {{ display: flex; gap: 8px; align-items: center; font-size: 12px; color: #64748b; background: #f8fafc; padding: 8px 12px; border-radius: 8px; margin-bottom: 12px; flex-wrap: wrap; }}
    .score-breakdown b {{ color: #0f172a; }}

    .cycle-section .section-title {{ color: #0369a1; }}

    .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }}
    .section-title {{ font-weight: 700; font-size: 13px; margin-bottom: 6px; }}
    .sig-list {{ padding-left: 16px; font-size: 12px; line-height: 1.7; color: #374151; }}

    .badge {{ display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; margin-bottom: 8px; }}

    .news-section {{ margin-top: 12px; padding-top: 10px; border-top: 1px solid #f1f5f9; }}
    .news-item {{ font-size: 12px; color: #475569; padding: 4px 0; }}
    .news-date {{ color: #94a3b8; margin-left: 6px; }}

    .filter-bar {{ display: flex; gap: 10px; margin-bottom: 18px; flex-wrap: wrap; }}
    .filter-btn {{ padding: 6px 16px; border-radius: 20px; border: 1.5px solid #cbd5e1; background: white; cursor: pointer; font-size: 13px; font-weight: 500; transition: all 0.15s; }}
    .filter-btn:hover, .filter-btn.active {{ background: #0f172a; color: white; border-color: #0f172a; }}

    .disclaimer {{ font-size: 11px; color: #94a3b8; margin-top: 32px; padding: 14px; background: #f8fafc; border-radius: 8px; line-height: 1.6; }}

    @media (max-width:700px) {{
      .metrics {{ grid-template-columns: repeat(3,1fr); }}
      .two-col {{ grid-template-columns: 1fr; }}
      .summary-boxes {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>

<div class="topbar">
  <h1>📈 Trading Analyser Dashboard</h1>
  <span class="updated">Updated: {generated} AWST</span>
</div>

<div class="container">

  <!-- Summary boxes -->
  <div class="summary-boxes">
    <div class="box" style="background:#16a34a">
      <div class="count">{len(buys)}</div>
      <div class="label">BUY / STRONG BUY</div>
    </div>
    <div class="box" style="background:#ca8a04">
      <div class="count">{len(holds)}</div>
      <div class="label">HOLD / WATCH</div>
    </div>
    <div class="box" style="background:#dc2626">
      <div class="count">{len(sells)}</div>
      <div class="label">SELL / AVOID</div>
    </div>
  </div>

  <!-- Quick summary table -->
  <div class="section-header">Today's Signals — Click a row to jump to full analysis</div>
  <div class="filter-bar" id="lens-bar">
    <span style="font-size:13px;color:#64748b;align-self:center;margin-right:4px">Signal lens:</span>
    <button class="filter-btn active" onclick="setLens('blended', this)">Blended</button>
    <button class="filter-btn" onclick="setLens('tech', this)">Technical Only</button>
    <button class="filter-btn" onclick="setLens('cycle', this)">Cycle Only</button>
  </div>
  <table>
    <thead><tr>
      <th>Ticker</th><th>Company</th><th>Price</th><th>RSI</th>
      <th>1 Week</th><th>Tech</th><th>Cycle</th><th>Signal</th><th>Score</th>
    </tr></thead>
    <tbody>{summary_rows}</tbody>
  </table>

  <!-- Global indices correlation -->
  <div class="section-header">Global Index Correlation with ASX 200</div>
  <table>
    <thead><tr>
      <th>Index</th><th>1-Day Change</th><th>1-Month Change</th><th>Correlation vs ASX 200</th>
    </tr></thead>
    <tbody>{corr_rows}</tbody>
  </table>

  <!-- Backtest accuracy section -->
  {load_backtest_section()}

  <!-- Filter buttons -->
  <div class="section-header">Detailed Analysis</div>
  <div class="filter-bar" id="rec-filter-bar">
    <button class="filter-btn active" onclick="filterCards('all', this)">All ({len(results)})</button>
    <button class="filter-btn" onclick="filterCards('buy', this)">Buy ({len(buys)})</button>
    <button class="filter-btn" onclick="filterCards('hold', this)">Hold ({len(holds)})</button>
    <button class="filter-btn" onclick="filterCards('sell', this)">Sell ({len(sells)})</button>
  </div>

  <!-- Individual stock cards -->
  <div id="cards-container">
    {cards_html}
  </div>

  <div class="disclaimer">
    ⚠ <strong>Disclaimer:</strong> This dashboard is generated automatically using publicly available market data and
    technical analysis algorithms. It is for informational purposes only and does not constitute financial advice.
    Past performance is not indicative of future results. Always consult a qualified financial adviser before
    making investment decisions.
  </div>

</div>

<script>
function filterCards(type, btn) {{
  document.getElementById('rec-filter-bar').querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('.card').forEach(card => {{
    const header = card.querySelector('.card-header');
    const rec    = header ? header.querySelector('.rec-badge').textContent.toLowerCase() : '';
    if (type === 'all') {{
      card.style.display = '';
    }} else if (type === 'buy') {{
      card.style.display = rec.includes('buy') ? '' : 'none';
    }} else if (type === 'hold') {{
      card.style.display = rec.includes('hold') || rec.includes('watch') ? '' : 'none';
    }} else if (type === 'sell') {{
      card.style.display = rec.includes('sell') || rec.includes('avoid') ? '' : 'none';
    }}
  }});
}}

function setLens(lens, btn) {{
  document.getElementById('lens-bar').querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');

  const container = document.getElementById('cards-container');
  const cards = Array.from(container.querySelectorAll('.card'));

  cards.sort((a, b) => {{
    const key = lens === 'tech' ? 'data-tech' : lens === 'cycle' ? 'data-cycle' : 'data-blended';
    return parseFloat(b.getAttribute(key)) - parseFloat(a.getAttribute(key));
  }});
  cards.forEach(c => container.appendChild(c));

  // Also re-sort the summary table to match
  const tbody = document.querySelector('table tbody');
  if (tbody) {{
    const rows = Array.from(tbody.querySelectorAll('tr'));
    const colIdx = lens === 'tech' ? 5 : lens === 'cycle' ? 6 : 8;
    rows.sort((a, b) => {{
      const av = parseFloat(a.children[colIdx].textContent) || 0;
      const bv = parseFloat(b.children[colIdx].textContent) || 0;
      return bv - av;
    }});
    rows.forEach(r => tbody.appendChild(r));
  }}
}}
</script>
</body>
</html>"""

    HTML_PATH.write_text(html, encoding="utf-8")
    print(f"✅ Dashboard built → {HTML_PATH}")


if __name__ == "__main__":
    build()
