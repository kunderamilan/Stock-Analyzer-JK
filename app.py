
import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf
import pandas as pd
import numpy as np
import altair as alt
import html
from curl_cffi import requests
from io import BytesIO
import os
from pathlib import Path
from datetime import datetime
# -----------------------------
# Page setup
# -----------------------------
st.set_page_config(page_title="Stock analyzer", layout="wide")
# -----------------------------
# CSS (držím staré rozložení + tmavý panel + čitelné tickery)
# -----------------------------
st.markdown(
    """
    <style>
      .title-center { text-align: center; font-size: 34px; font-weight: 700; margin-top: 10px; margin-bottom: 10px; }
      .chart-space { height: 360px; margin-top: 10px; margin-bottom: 10px; } /* prázdný prostor, když nejsou data */
      .control-panel {
        background: #0b0f15;
        border-radius: 10px;
        padding: 14px 16px;
        width: 320px;
        color: #ffffff;
        box-shadow: 0 8px 18px rgba(0,0,0,0.25);
      }
      .control-panel h4 { margin: 0 0 8px 0; color:#ffffff; }
      .subtle { color:#93a3b8; font-size: 12px; }
      .active-box {
        background: #0b0f15;
        border-radius: 10px;
        padding: 10px 12px;
        border: 1px solid rgba(255,255,255,0.10);
      }
      .active-title { color:#cdd6e3; font-weight: 700; margin-bottom: 6px; }
      .ticker-line { font-size: 14px; font-weight: 700; margin: 3px 0; }
      /* ať inputy na tmavém nejsou "bílé na bílém" */
      div[data-baseweb="input"] input { color: #e8eef7 !important; }
      div[data-baseweb="select"] span { color: #e8eef7 !important; }
      /* smaller label for override checkboxes */
      label[data-testid="stCheckboxLabel"] p,
      [data-testid="stCheckbox"] p,
      [data-baseweb="checkbox"] span { font-size: 11px !important; color: #93a3b8 !important; }
    </style>
    """,
    unsafe_allow_html=True,
)
# -----------------------------
# Corporate SSL workaround session (cache)
# -----------------------------
@st.cache_resource
def get_yf_session():
    s = requests.Session(impersonate="chrome")
    # Cloud-safe default: SSL verification ON.
    # For restricted corporate networks set env YF_VERIFY_SSL=0.
    _verify_ssl = os.getenv("YF_VERIFY_SSL", "1").strip().lower() not in {"0", "false", "no"}
    s.verify = _verify_ssl
    return s

@st.cache_data(ttl=3600, show_spinner=False)
def get_yf_crumb() -> str:
    """
    Obtain a Yahoo Finance crumb token required for v10 quoteSummary API calls.
    Flow: GET fc.yahoo.com (sets cookie) → GET /v1/test/getcrumb (returns crumb).
    Returns empty string on failure (callers should handle gracefully).
    """
    try:
        s = get_yf_session()
        s.get("https://fc.yahoo.com", timeout=10)
        resp = s.get("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=10)
        crumb = resp.text.strip()
        return crumb if crumb else ""
    except Exception:
        return ""

def fetch_close_series(ticker: str, period_key: str, start=None, end=None) -> pd.Series:
    session = get_yf_session()
    t = yf.Ticker(ticker=ticker, session=session)
    today = pd.Timestamp.today().normalize()
    # --- 1️⃣ Vlastní období má PRIORITU ---
    if start or end:
        start_ts = pd.Timestamp(start) if start else None
        end_ts = (
            pd.Timestamp(end) + pd.Timedelta(days=1)
            if end
            else today + pd.Timedelta(days=1)
        )
        hist = t.history(start=start_ts, end=end_ts)
    # --- 2️⃣ Jinak použijeme předdefinované období ---
    else:
        if period_key == "1 day":
            hist = t.history(period="1d")
        elif period_key == "1 month":
            hist = t.history(period="1mo")
        elif period_key == "3 month":
            hist = t.history(period="3mo")
        elif period_key == "6 month":
            hist = t.history(period="6mo")
        elif period_key == "1 year":
            hist = t.history(period="1y")
        elif period_key == "3 years":
            start_ts = today - pd.Timedelta(days=365 * 3)
            hist = t.history(start=start_ts, end=today + pd.Timedelta(days=1))
        elif period_key == "5 years":
            hist = t.history(period="5y")
        elif period_key == "10 years":
            start_ts = today - pd.Timedelta(days=365 * 10)
            hist = t.history(start=start_ts, end=today + pd.Timedelta(days=1))
        elif period_key == "YTD":
            start_ts = pd.Timestamp(year=today.year, month=1, day=1)
            hist = t.history(start=start_ts, end=today + pd.Timedelta(days=1))
        else:
            hist = t.history(period="1y")
    # --- 3️⃣ Bezpečnostní pojistka ---
    if hist is None or hist.empty:
        return pd.Series(dtype="float64")
    s = hist["Close"].copy()
    s.name = ticker
    return s
# -----------------------------
# Quick metrics fetch (used in the top table)
# -----------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_quick_metrics(ticker: str) -> dict:
    """Return Forward P/E, PEG ratio, Market cap, Enterprise Value for a ticker."""
    def _fmt_large(val):
        if val is None:
            return "—"
        try:
            v = float(val)
            if not np.isfinite(v):
                return "—"
            if v >= 1e12:
                return f"{v/1e12:.2f} T"
            elif v >= 1e9:
                return f"{v/1e9:.2f} B"
            elif v >= 1e6:
                return f"{v/1e6:.2f} M"
            return f"{v:.2f}"
        except Exception:
            return "—"

    def _fmt_ratio(val):
        if val is None:
            return "—"
        try:
            v = float(val)
            return f"{v:.2f}" if np.isfinite(v) else "—"
        except Exception:
            return "—"

    def _get_key_stats_from_api(tkr: str) -> dict:
        """
        Fetch defaultKeyStatistics + summaryDetail directly from Yahoo Finance
        quoteSummary API. More reliable than t.info for values like enterpriseValue.
        Returns a dict with raw float values, or empty dict on failure.
        """
        try:
            session = get_yf_session()
            for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
                url = (
                    f"https://{host}/v10/finance/quoteSummary/{tkr}"
                    f"?modules=defaultKeyStatistics%2CsummaryDetail"
                )
                resp = session.get(url, timeout=10)
                data = resp.json()
                result = data["quoteSummary"]["result"][0]
                dks = result.get("defaultKeyStatistics", {})
                sd  = result.get("summaryDetail", {})

                def _raw(d, key):
                    try:
                        return float(d[key]["raw"])
                    except Exception:
                        return None

                return {
                    "pegRatio":        _raw(dks, "pegRatio") or _raw(dks, "trailingPegRatio"),
                    "enterpriseValue": _raw(dks, "enterpriseValue"),
                    "marketCap":       _raw(sd,  "marketCap"),
                    "trailingPE":      _raw(sd,  "trailingPE"),
                    "forwardPE":       _raw(sd,  "forwardPE"),
                }
        except Exception:
            return {}

    try:
        session = get_yf_session()
        t = yf.Ticker(ticker=ticker, session=session)
        info = t.info

        # Prefer values from the quoteSummary API – they are fresher and more
        # reliable than t.info (which can return stale / wrong numbers).
        ks = _get_key_stats_from_api(ticker)

        def _pick(api_key, info_key, *fallback_info_keys):
            v = ks.get(api_key)
            if v is None:
                v = info.get(info_key)
            if v is None:
                for fk in fallback_info_keys:
                    v = info.get(fk)
                    if v is not None:
                        break
            return v

        return {
            "Ticker": ticker,
            "Trailing P/E":         _fmt_ratio(_pick("trailingPE",      "trailingPE")),
            "Forward P/E":          _fmt_ratio(_pick("forwardPE",       "forwardPE")),
            "PEG ratio (5yr exp.)": _fmt_ratio(_pick("pegRatio",        "pegRatio", "trailingPegRatio")),
            "Market Cap":           _fmt_large(_pick("marketCap",       "marketCap")),
            "Enterprise Value":     _fmt_large(_pick("enterpriseValue", "enterpriseValue")),
        }
    except Exception:
        return {
            "Ticker": ticker,
            "Trailing P/E": "—",
            "Forward P/E": "—",
            "PEG ratio (5yr exp.)": "—",
            "Market Cap": "—",
            "Enterprise Value": "—",
        }


# ── Company info (for the firm-info expander) ─────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_company_info(ticker: str) -> dict:
    """
    Fetch all company-info data.
    Earnings/calendar/estimates are fetched via t._data.get_raw_json() which
    uses yfinance's own authenticated session (handles cookies/crumb internally),
    so it works on both corporate networks and Streamlit Cloud.
    Returns a dict with keys: info, income_stmt, major_holders,
    institutional_holders, calendar, news, earnings_estimate,
    revenue_estimate, earnings_history.
    All values are safe defaults on failure.
    """
    session = get_yf_session()
    t = yf.Ticker(ticker=ticker, session=session)

    def _safe(fn):
        try:
            result = fn()
            return result if result is not None else None
        except Exception:
            return None

    def _raw(d, key, default=None):
        try:
            return d[key]["raw"]
        except Exception:
            return default

    # ── Trigger yfinance auth setup ────────────────────────────────────────
    # fast_info initialises cookies/crumb inside t._data so that
    # t._data.get_raw_json() calls below are properly authenticated.
    _safe(lambda: t.fast_info)

    # ── Direct quoteSummary via yfinance's own authenticated request ───────
    # t._data.get_raw_json() handles crumb/cookie internally and works on
    # both corporate networks (CSRF cookie) and Streamlit Cloud (fc.yahoo.com).
    def _fetch_quote_summary(modules: list) -> dict:
        modules_str = "%2C".join(modules)
        url = (
            f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}"
            f"?modules={modules_str}"
        )
        try:
            data = t._data.get_raw_json(url)
            result = data.get("quoteSummary", {}).get("result")
            if result:
                return result[0]
        except Exception:
            pass
        return {}

    qs = _fetch_quote_summary([
        "assetProfile", "summaryDetail", "financialData", "quoteType",
        "earningsTrend", "earningsHistory", "calendarEvents",
    ])

    # ── info: yfinance first, always supplement missing fields from quoteSummary ──
    # t.info on Streamlit Cloud may return a non-empty but incomplete dict
    # (e.g. only {"symbol": "GOOGL"}) – so we always fill missing keys from the
    # quoteSummary modules fetched via the direct API above.
    info = _safe(lambda: t.info) or {}
    fd = qs.get("financialData", {})
    ap = qs.get("assetProfile", {})
    sd = qs.get("summaryDetail", {})
    qt = qs.get("quoteType", {})

    # Fields sourced from assetProfile / quoteType
    _ap_fallback = {
        "longName":               ap.get("longName") or qt.get("longName"),
        "sector":                 ap.get("sector"),
        "industry":               ap.get("industry"),
        "country":                ap.get("country"),
        "website":                ap.get("website"),
        "fullTimeEmployees":      ap.get("fullTimeEmployees"),
        "longBusinessSummary":    ap.get("longBusinessSummary"),
        "auditRisk":              ap.get("auditRisk"),
        "boardRisk":              ap.get("boardRisk"),
        "compensationRisk":       ap.get("compensationRisk"),
        "shareHolderRightsRisk":  ap.get("shareHolderRightsRisk"),
        "overallRisk":            ap.get("overallRisk"),
        "currentPrice":           _raw(fd, "currentPrice"),
        "regularMarketPrice":     _raw(sd, "regularMarketPrice"),
    }
    for _k, _v in _ap_fallback.items():
        if info.get(_k) is None and _v is not None:
            info[_k] = _v

    # Fields sourced from financialData (analyst targets / recommendation)
    if fd:
        for _k_info, _k_fd in [
            ("targetMeanPrice",        "targetMeanPrice"),
            ("targetHighPrice",        "targetHighPrice"),
            ("targetLowPrice",         "targetLowPrice"),
            ("recommendationMean",     "recommendationMean"),
            ("recommendationKey",      "recommendationKey"),
            ("numberOfAnalystOpinions","numberOfAnalystOpinions"),
            ("currentPrice",           "currentPrice"),
        ]:
            if info.get(_k_info) is None:
                _v = fd.get(_k_fd)
                info[_k_info] = _v.get("raw") if isinstance(_v, dict) else _v

    # ── calendar (calendarEvents module) ──────────────────────────────────
    calendar = None
    _ce = qs.get("calendarEvents", {})
    if _ce:
        _earn_node = _ce.get("earnings", {})
        if _earn_node:
            _earn_dates_raw = _earn_node.get("earningsDate", [])
            calendar = {
                "Earnings Date": [
                    pd.Timestamp(d["raw"], unit="s")
                    for d in _earn_dates_raw if isinstance(d, dict) and "raw" in d
                ],
                "Earnings Average": _raw(_earn_node, "earningsAverage"),
                "Earnings Low":     _raw(_earn_node, "earningsLow"),
                "Earnings High":    _raw(_earn_node, "earningsHigh"),
                "Revenue Average":  _raw(_earn_node, "revenueAverage"),
                "Revenue Low":      _raw(_earn_node, "revenueLow"),
                "Revenue High":     _raw(_earn_node, "revenueHigh"),
            }
    if calendar is None:
        calendar = _safe(lambda: t.calendar)

    # ── earnings_estimate & revenue_estimate (earningsTrend module) ───────
    earnings_estimate = None
    revenue_estimate  = None
    _et = qs.get("earningsTrend", {})
    _trend = _et.get("trend", []) if _et else []
    if _trend:
        _ee_rows, _re_rows, _periods = [], [], []
        for _item in _trend:
            _period = _item.get("period")
            _ee_node = _item.get("earningsEstimate", {})
            _re_node = _item.get("revenueEstimate", {})
            _ee_rows.append({
                "avg":              _raw(_ee_node, "avg"),
                "low":              _raw(_ee_node, "low"),
                "high":             _raw(_ee_node, "high"),
                "yearAgoEps":       _raw(_ee_node, "yearAgoEps"),
                "numberOfAnalysts": _raw(_ee_node, "numberOfAnalysts"),
                "growth":           _raw(_ee_node, "growth"),
            })
            _re_rows.append({
                "avg":              _raw(_re_node, "avg"),
                "low":              _raw(_re_node, "low"),
                "high":             _raw(_re_node, "high"),
                "yearAgoRevenue":   _raw(_re_node, "yearAgoRevenue"),
                "numberOfAnalysts": _raw(_re_node, "numberOfAnalysts"),
                "growth":           _raw(_re_node, "growth"),
            })
            _periods.append(_period)
        if _ee_rows:
            earnings_estimate = pd.DataFrame(_ee_rows, index=_periods)
        if _re_rows:
            revenue_estimate  = pd.DataFrame(_re_rows, index=_periods)
    if earnings_estimate is None:
        earnings_estimate = _safe(lambda: t.earnings_estimate)
    if revenue_estimate is None:
        revenue_estimate = _safe(lambda: t.revenue_estimate)

    # ── earnings_history (earningsHistory module) ──────────────────────────
    earnings_history = None
    _eh_node = qs.get("earningsHistory", {})
    _eh_list = _eh_node.get("history", []) if _eh_node else []
    if _eh_list:
        _eh_rows = []
        for _h in _eh_list:
            _q_raw = _h.get("quarter", {}).get("raw") if isinstance(_h.get("quarter"), dict) else None
            _eh_rows.append({
                "quarter":         pd.Timestamp(_q_raw, unit="s") if _q_raw else None,
                "epsActual":       _raw(_h, "epsActual"),
                "epsEstimate":     _raw(_h, "epsEstimate"),
                "epsDifference":   _raw(_h, "epsDifference"),
                "surprisePercent": _raw(_h, "surprisePercent"),
            })
        if _eh_rows:
            earnings_history = pd.DataFrame(_eh_rows).set_index("quarter")
    if earnings_history is None:
        earnings_history = _safe(lambda: t.earnings_history)

    # ── income_stmt (yfinance — uses v8 financial statements API) ─────────
    _inc_annual = _safe(lambda: t.income_stmt)
    _inc_qtr    = _safe(lambda: t.quarterly_income_stmt)
    if _inc_annual is not None and not getattr(_inc_annual, "empty", True):
        income_stmt = _inc_annual
    elif _inc_qtr is not None and not getattr(_inc_qtr, "empty", True):
        income_stmt = _inc_qtr
    else:
        income_stmt = None

    major_holders         = _safe(lambda: t.major_holders)
    institutional_holders = _safe(lambda: t.institutional_holders)
    news                  = _safe(lambda: t.news) or []

    return {
        "info":                  info,
        "income_stmt":           income_stmt,
        "major_holders":         major_holders,
        "institutional_holders": institutional_holders,
        "calendar":              calendar,
        "news":                  news,
        "earnings_estimate":     earnings_estimate,
        "revenue_estimate":      revenue_estimate,
        "earnings_history":      earnings_history,
    }


def _build_income_sankey(income_stmt: "pd.DataFrame | None", ticker: str):
    """
    Build a Plotly Sankey waterfall from the income statement.
    Uses TTM column if available, otherwise the most recent annual column.
    Returns (plotly.Figure, None) on success, or (None, error_str) on failure.
    """
    try:
        import plotly.graph_objects as go

        if income_stmt is None or income_stmt.empty:
            return None, "income_stmt je prázdný"

        col = income_stmt.columns[0]
        col_label = col.year if hasattr(col, "year") else str(col)
        idx_lower = {str(k).lower(): k for k in income_stmt.index}

        def _pick_first(keywords):
            """Return value of FIRST matching row (not sum) — exact match preferred."""
            for kw in keywords:
                kw_l = kw.lower()
                # 1) exact match
                if kw_l in idx_lower:
                    try:
                        v = float(income_stmt.loc[idx_lower[kw_l], col])
                        if np.isfinite(v):
                            return v / 1e9
                    except Exception:
                        pass
            for kw in keywords:
                kw_l = kw.lower()
                # 2) substring fallback
                for k_l, k_orig in idx_lower.items():
                    if kw_l in k_l:
                        try:
                            v = float(income_stmt.loc[k_orig, col])
                            if np.isfinite(v):
                                return v / 1e9
                        except Exception:
                            pass
            return 0.0

        rev      = _pick_first(["total revenue", "totalrevenue"])
        cogs     = _pick_first(["cost of revenue", "costofrevenue", "cost of goods"])
        gp       = _pick_first(["gross profit", "grossprofit"])
        opex     = _pick_first(["operating expense", "totaloperatingexpenses"])
        ebit     = _pick_first(["operating income", "operatingincome", "ebit"])
        interest = abs(_pick_first(["interest expense", "interestexpense"]))
        tax      = abs(_pick_first(["tax provision", "taxprovision", "income tax"]))
        ni       = _pick_first(["net income", "netincome"])

        # Exact match for net income to avoid double-counting variants
        ni_exact = 0.0
        for k_l, k_orig in idx_lower.items():
            if k_l in ("net income", "netincome"):
                try:
                    v = float(income_stmt.loc[k_orig, col])
                    if np.isfinite(v):
                        ni_exact = v / 1e9
                        break
                except Exception:
                    pass
        if ni_exact != 0.0:
            ni = ni_exact

        # Derive fallbacks
        if gp == 0 and rev > 0 and cogs > 0:
            gp = rev - cogs
        if ebit == 0 and gp > 0 and opex > 0:
            ebit = gp - opex

        if rev < 0.001:
            return None, f"Revenue = 0 (ticker: {ticker})"

        # ── Force Sankey balance ───────────────────────────────────────────
        # Node 0 (Revenue):  out = cogs + gp  → must sum to rev
        if cogs > 0 and gp > 0:
            if abs((cogs + gp) - rev) / max(rev, 0.001) > 0.05:
                cogs = rev - gp  # rebalance

        # Node 4 (EBIT): out = interest + tax + ni → must sum to ebit
        ebit_out = interest + tax + ni
        if ebit_out > 0 and abs(ebit_out - ebit) / max(abs(ebit), 0.001) > 0.05:
            ni = max(ebit - interest - tax, 0.001)

        labels = ["Revenue", "Cost of Revenue", "Gross Profit",
                  "Op. Expenses", "EBIT / Op. Income",
                  "Interest & Other", "Tax", "Net Income"]
        sources = [0,    0,   2,    2,    4,        4,   4]
        targets = [1,    2,   3,    4,    5,        6,   7]
        values  = [
            max(cogs, 0.001), max(gp, 0.001),
            max(opex, 0.001), max(ebit, 0.001),
            max(interest, 0.001), max(tax, 0.001), max(ni, 0.001),
        ]
        link_colors = ["rgba(255,112,67,0.5)", "rgba(102,187,106,0.5)",
                       "rgba(255,112,67,0.5)", "rgba(79,142,247,0.5)",
                       "rgba(255,112,67,0.5)", "rgba(255,112,67,0.5)", "rgba(102,187,106,0.5)"]
        node_colors = ["#4f8ef7", "#FF7043", "#66BB6A",
                       "#FF7043", "#4f8ef7",
                       "#FF7043", "#FF7043", "#66BB6A"]

        # Explicit node positions for clean vertical separation
        # Nodes: 0=Revenue, 1=CostOfRev, 2=GrossProfit, 3=OpEx, 4=EBIT,
        #        5=Interest, 6=Tax, 7=NetIncome
        node_x = [0.01, 0.99, 0.33, 0.99, 0.66, 0.99, 0.99, 0.99]
        node_y = [0.50, 0.12, 0.70, 0.48, 0.82, 0.97, 0.87, 0.74]

        fig = go.Figure(go.Sankey(
            arrangement="fixed",
            node=dict(
                label=labels, color=node_colors,
                x=node_x, y=node_y,
                pad=40, thickness=22,
            ),
            link=dict(source=sources, target=targets,
                      value=values, color=link_colors),
        ))
        fig.update_layout(
            title=dict(
                text=f"{ticker} — Income Waterfall ({col_label})",
                font=dict(color="#cdd6e3", size=13),
            ),
            height=500,
            margin=dict(l=10, r=10, t=40, b=10),
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#cdd6e3", size=11),
        )
        return fig, None
    except Exception as e:
        return None, str(e)


# -----------------------------
# Stable colors per ticker
# -----------------------------
PALETTE = [
    "#4FC3F7", "#66BB6A", "#FF7043", "#BA68C8", "#FFD54F",
    "#26A69A", "#EC407A", "#8D6E63", "#78909C", "#29B6F6"
]
def ensure_color_map(tickers):
    if "color_map" not in st.session_state:
        st.session_state.color_map = {}
    cm = st.session_state.color_map
    for t in tickers:
        if t not in cm:
            cm[t] = PALETTE[len(cm) % len(PALETTE)]
    st.session_state.color_map = cm
# -----------------------------
# Session init
# -----------------------------
if "ticker_main" not in st.session_state:
    st.session_state.ticker_main = "BRK-B"
if "period_label" not in st.session_state:
    st.session_state.period_label = "5 years"
if "mode" not in st.session_state:
    st.session_state.mode = "Absolutní cena (Close)"   # logická default hodnota
if "mode_widget" not in st.session_state:
    st.session_state.mode_widget = st.session_state.mode  # widget se inicializuje podle logiky
if "compare_list" not in st.session_state:
    st.session_state.compare_list = []
if "add_ticker" not in st.session_state:
    st.session_state.add_ticker = "^GSPC"
if "df_long" not in st.session_state:
    st.session_state.df_long = None
if "current_tickers" not in st.session_state:
    st.session_state.current_tickers = []
if "pending_mode_widget" not in st.session_state:
    st.session_state.pending_mode_widget = None
if "date_from" not in st.session_state:
    st.session_state.date_from = None
if "date_to" not in st.session_state:
    st.session_state.date_to = None

# -----------------------------
# Single source of truth: reload_data
# -----------------------------
def reload_data():
    main = st.session_state.ticker_main
    period_key = st.session_state.period_label
    # pokud uživatel zadal vlastní období, použijeme ho místo předdefinovaných period
    start = st.session_state.date_from
    end = st.session_state.date_to
    #-----------------
    added = st.session_state.compare_list
    tickers = [main] + [t for t in added if t and t != main]
    ensure_color_map(tickers)
    series_list = []
    failed = []
    for t in tickers:
        s = fetch_close_series(
            t,
            period_key,
            start=start,
            end=end
        )
        if s is None or s.empty:
            failed.append(t)
            continue
        series_list.append(s)
    if not series_list:
        st.session_state.df_long = None
        st.error("Nepodařilo se načíst data pro žádný ticker.")
        return
    if failed:
        st.warning(f"Nepodařilo se načíst data pro: {', '.join(failed)}")
    df = pd.concat(series_list, axis=1).dropna(how="any")
    if df.empty:
        st.session_state.df_long = None
        st.error("Tickery nemají žádný společný úsek dat v tomto období.")
        return
    if st.session_state.mode.startswith("Relativní"):
        base = df.iloc[0]
        df_plot = (df / base - 1.0) * 100.0  # 0% start, 100% = 2×
    else:
        df_plot = df
    df_long = (
        df_plot.reset_index()
        .rename(columns={"index": "Date"})
        .melt(id_vars=["Date"], var_name="Ticker", value_name="Value")
    )
    st.session_state.df_long = df_long
    st.session_state.current_tickers = tickers

@st.cache_data(ttl=60, show_spinner=False)
def fetch_current_price(ticker: str) -> str:
    """Return formatted current price string, e.g. '499.13 USD'. Cached 60 s."""
    try:
        session = get_yf_session()
        t = yf.Ticker(ticker=ticker, session=session)
        fi = t.fast_info
        price = getattr(fi, "last_price", None)
        currency = getattr(fi, "currency", "") or ""
        if price is None:
            info = t.info
            price = info.get("regularMarketPrice") or info.get("currentPrice")
            currency = info.get("currency", "")
        if price is None:
            return ""
        return f"{price:,.2f} {currency}".strip()
    except Exception:
        return ""

def on_period_change():
        # auto překreslení jen pokud už graf existuje (jinak by to zbytečně tahalo data)
        if st.session_state.df_long is not None:
            reload_data()
# -----------------------------
# Period definitions (GLOBAL)
# -----------------------------
period_keys = [
    "1 day", "1 month", "3 month", "6 month",
    "1 year", "3 years", "5 years", "10 years", "YTD"
]
period_labels = {
    "1 day": "1 den",
    "1 month": "1 měsíc",
    "3 month": "3 měsíce",
    "6 month": "6 měsíců",
    "1 year": "1 rok",
    "3 years": "3 roky",
    "5 years": "5 let",
    "10 years": "10 let",
    "YTD": "YTD",
}
# -----------------------------
# UI (staré rozložení)
# -----------------------------
st.markdown('<div class="title-center">Stock analyzer</div>', unsafe_allow_html=True)
# ===== HORNÍ ŘÁDEK: Ticker =====
top_left, top_right = st.columns([3, 4])
with top_left:
    st.write("Ticker:")
    tcol1, tcol2 = st.columns([4, 1.5], vertical_alignment="center")
    with tcol1:
        st.session_state.ticker_main = st.text_input(
            "Ticker",
            value=st.session_state.ticker_main,
            label_visibility="collapsed",
            placeholder="BRK-B",
        ).upper().strip()
    with tcol2:
        load_clicked = st.button("Načíst", help="Načíst / přepočítat graf", width="stretch")
with top_right:
    if st.session_state.ticker_main:
        _price_str = fetch_current_price(st.session_state.ticker_main)
        if _price_str:
            st.markdown(
                f"<div style='font-size:22px; font-weight:700; color:#4FC3F7; "
                f"text-align:right; padding-top:4px'>{_price_str}</div>",
                unsafe_allow_html=True,
            )
st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
# ===== DRUHÝ ŘÁDEK: OBDOBÍ + VLASTNÍ OBDOBÍ (CELÁ ŠÍŘKA) =====
col_period, col_spacer, col_from, col_to, col_btn = st.columns(
    [1.6, 3.5, 1.6, 1.6, 1.8],
    vertical_alignment="center"
)
with col_period:
    st.caption("Období")
    st.selectbox(
        "Období",
        options=period_keys,
        format_func=lambda k: period_labels[k],
        key="period_label",
        label_visibility="collapsed",
        on_change=on_period_change,
    )
with col_spacer:
    st.write("")  # velká mezera → vlastní období vpravo
with col_from:
    st.caption("Od")
    st.session_state.date_from = st.date_input(
        "Od",
        value=st.session_state.date_from,
        label_visibility="collapsed",
    )
with col_to:
    st.caption("Do")
    st.session_state.date_to = st.date_input(
        "Do",
        value=st.session_state.date_to,
        label_visibility="collapsed",
    )
with col_btn:
    st.caption(" ")
    custom_load = st.button(
        "Načíst",
        help="Načíst vlastní období",
        width="stretch"
    )
    
    #------------------------------------------------------------------
with top_right:
    st.write("")
long_period = st.session_state.period_label in ["3 years", "5 years", "10 years"]


# CHART AREA napříč (jako dřív)
if st.session_state.df_long is None:
    st.markdown('<div class="chart-space"></div>', unsafe_allow_html=True)
else:
    tickers = st.session_state.current_tickers
    ensure_color_map(tickers)
    colors = [st.session_state.color_map[t] for t in tickers]
    is_relative = st.session_state.mode.startswith("Relativní")
    if is_relative:
        y_axis_left  = alt.Axis(title="Výnos (%)", grid=True,  labelExpr="format(datum.value, '.0f') + '%'", orient="left")
        y_axis_right = alt.Axis(title=None,         grid=False, labelExpr="format(datum.value, '.0f') + '%'", orient="right")
    else:
        y_axis_left  = alt.Axis(title="Close", grid=True,  orient="left")
        y_axis_right = alt.Axis(title=None,    grid=False, orient="right")

    _x = alt.X("Date:T", axis=alt.Axis(title=None, format="%b %y" if long_period else "%d %b", grid=True, gridOpacity=0.5))
    _color = alt.Color("Ticker:N", scale=alt.Scale(domain=tickers, range=colors), legend=None)

    # Interactive nearest-date selection for crosshair tooltip
    _nearest = alt.selection_point(
        nearest=True, on="pointerover", fields=["Date"], empty=False,
    )

    _val_fmt = ".2f" if not is_relative else "+.2f"

    _y_enc = alt.Y("Value:Q", axis=y_axis_left)

    # Pre-pivot data in Python so the rule tooltip can show all tickers
    _df_wide = (
        st.session_state.df_long
        .pivot_table(index="Date", columns="Ticker", values="Value")
        .sort_index()
        .ffill()
        .reset_index()
    )

    # Base line chart (no tooltip on line itself)
    base = alt.Chart(st.session_state.df_long).mark_line().encode(x=_x, y=_y_enc, color=_color)

    # Tooltip definition (wide-format: one column per ticker)
    _pivot_tooltip = [alt.Tooltip("Date:T", format="%d.%m.%Y", title="Datum")] + [
        alt.Tooltip(f"{t}:Q", format=_val_fmt, title=t) for t in tickers
    ]

    # Selector layer on wide data — nearly invisible rules at every date.
    # opacity > 0 is required so the canvas renderer fires tooltip events.
    # Placed on TOP of the layer stack to always capture pointer events.
    selectors = (
        alt.Chart(_df_wide)
        .mark_rule(strokeWidth=1)
        .encode(x="Date:T", opacity=alt.value(0.01), tooltip=_pivot_tooltip)
        .add_params(_nearest)
    )

    # Points layer: show dots for ALL tickers at selected date
    points = (
        alt.Chart(st.session_state.df_long)
        .mark_point(size=60, filled=True)
        .encode(
            x=_x,
            y=_y_enc,
            color=_color,
            opacity=alt.condition(_nearest, alt.value(1), alt.value(0)),
        )
    )

    # Visible dashed vertical rule at selected date (no tooltip — selectors handles it)
    rule = (
        alt.Chart(_df_wide)
        .mark_rule(color="#888", strokeDash=[4, 4])
        .encode(x="Date:T")
        .transform_filter(_nearest)
    )

    # Ghost layer – invisible, only forces Vega-Lite to render the right Y-axis
    _y_enc_right = alt.Y("Value:Q", axis=y_axis_right)
    base_right = (
        alt.Chart(st.session_state.df_long)
        .mark_line(opacity=0)
        .encode(x=_x, y=_y_enc_right)
    )

    chart = (
        alt.layer(base, points, rule, selectors, base_right)
        .resolve_scale(y="shared")
        .resolve_axis(y="independent")
        .properties(height=420)
        .configure_view(strokeOpacity=0)
    )
    st.altair_chart(chart, width="stretch")
# ROW pod grafem: Přidat ticker | Aktivní tickery | Metrics table
row_left, row_mid, row_table = st.columns([2.5, 2, 5.5])

with row_left:
    st.write("Přidat ticker k porovnání:")
    st.session_state.add_ticker = st.text_input(
        "Přidat ticker",
        value=st.session_state.add_ticker,
        label_visibility="collapsed",
    ).upper().strip()
    add_clicked = st.button("Přidat")

    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

    # Zobrazení panel (přesunuto sem)
    st.markdown('<div class="control-panel">', unsafe_allow_html=True)
    st.markdown("<h4>Zobrazení:</h4>", unsafe_allow_html=True)
    if st.session_state.get("pending_mode_widget"):
        new_mode = st.session_state.pending_mode_widget
        st.session_state.mode = new_mode
        st.session_state.mode_widget = new_mode
        st.session_state.pending_mode_widget = None
    def on_mode_change():
        st.session_state.mode = st.session_state.mode_widget
        if st.session_state.df_long is not None:
            reload_data()
    st.radio(
        "Zobrazení",
        options=["Relativní vývoj (%)", "Absolutní cena (Close)"],
        key="mode_widget",
        label_visibility="collapsed",
        on_change=on_mode_change,
    )
    st.markdown('<div class="subtle">Relativní: 0% = start, 100% = dvojnásobek (2×).</div>', unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

with row_mid:
    st.markdown('<div class="active-title">Aktivní tickery:</div>', unsafe_allow_html=True)
    main = st.session_state.ticker_main
    tickers = [main] + st.session_state.compare_list
    ensure_color_map(tickers)
    # hlavní ticker
    col = st.session_state.color_map.get(main, "#ffffff")
    st.markdown(f"<div class='ticker-line' style='color:{col}'>{main}</div>", unsafe_allow_html=True)
    # přidané tickery + odebrání
    for t in list(st.session_state.compare_list):
        col = st.session_state.color_map.get(t, "#ffffff")
        c1, c2 = st.columns([6, 1])
        with c1:
            st.markdown(f"<div class='ticker-line' style='color:{col}'>{t}</div>", unsafe_allow_html=True)
        with c2:
            if st.button("✖", key=f"remove_{t}"):
                st.session_state.compare_list = [x for x in st.session_state.compare_list if x != t]
                if len(st.session_state.compare_list) == 0:
                    st.session_state.mode = "Absolutní cena (Close)"
                    st.session_state.pending_mode_widget = "Absolutní cena (Close)"
                reload_data()
                st.rerun()
    if st.session_state.compare_list:
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        if st.button("❌ Zrušit porovnání"):
            st.session_state.compare_list = []
            st.session_state.mode = "Absolutní cena (Close)"
            st.session_state.pending_mode_widget = "Absolutní cena (Close)"
            reload_data()
            st.rerun()

with row_table:
    # Quick metrics table for all active tickers
    main = st.session_state.ticker_main
    active_tickers = [main] + st.session_state.compare_list
    with st.spinner("Načítám metriky…"):
        metrics_rows = [fetch_quick_metrics(t) for t in active_tickers]
    metrics_df = pd.DataFrame(metrics_rows)
    st.dataframe(
        metrics_df,
        width="stretch",
        hide_index=True,
        column_config={
            "Ticker": st.column_config.TextColumn("Ticker"),
            "Trailing P/E": st.column_config.TextColumn("Trailing P/E"),
            "Forward P/E": st.column_config.TextColumn("Forward P/E"),
            "PEG ratio (5yr exp.)": st.column_config.TextColumn("PEG ratio (5yr exp.)"),
            "Market Cap": st.column_config.TextColumn("Market Cap"),
            "Enterprise Value": st.column_config.TextColumn("Enterprise Value"),
        },
    )
# -----------------------------
# Actions
# -----------------------------
# Načíst
if load_clicked:
    reload_data()
    st.rerun()
# Přidat ticker
if add_clicked:
    t = st.session_state.add_ticker
    main = st.session_state.ticker_main
    if not t:
        st.warning("Zadej ticker pro porovnání.")
    elif t == main:
        st.warning("Tento ticker už je hlavní ticker.")
    elif t in st.session_state.compare_list:
        st.info("Ticker už je v porovnání.")
    
    else:
        # přidáváme ticker
        st.session_state.compare_list.append(t)
        st.session_state.add_ticker = "^GSPC"
        # pokud tohle je PRVNÍ ticker v porovnání, přepni automaticky na relativní
        
        if len(st.session_state.compare_list) == 1:
            st.session_state.mode = "Relativní vývoj (%)"
            st.session_state.pending_mode_widget = "Relativní vývoj (%)"


        reload_data()
        st.rerun()
# Načíst vlastní období
if custom_load:
    start = st.session_state.date_from
    end = st.session_state.date_to
    if start and end and start > end:
        st.error("Datum „Od“ musí být menší než „Do“.")
    elif not start and not end:
        st.warning("Vyplň alespoň jedno datum (Od nebo Do).")
    else:
        reload_data()
        st.rerun()
# ============================================================
# VALUACE SECTION
# ============================================================

st.divider()
st.markdown("### Valuace")

# ── helpers ──────────────────────────────────────────────────────────────────

def _safe_float(val):
    """Convert a value to float, return NaN on failure."""
    try:
        f = float(val)
        return f if np.isfinite(f) else np.nan
    except Exception:
        return np.nan


def _fv_clr(fv, price):
    """Return colour for a fair-value cell based on comparison with current price.
    Green  → FV > price × 1.05  (stock undervalued)
    Yellow → FV within ±5% of price
    Red    → FV < price × 0.95  (stock overvalued)
    """
    try:
        fv, price = float(fv), float(price)
    except Exception:
        return "#93a3b8"
    if np.isnan(fv) or np.isnan(price) or price <= 0:
        return "#93a3b8"
    ratio = fv / price
    if ratio > 1.05:
        return "#66BB6A"
    if ratio < 0.95:
        return "#FF7043"
    return "#FFD54F"


def _cagr(start_val, end_val, n):
    """CAGR = (end/start)^(1/n) - 1.  Returns NaN on bad inputs."""
    try:
        s, e, n = float(start_val), float(end_val), float(n)
        if np.isnan(s) or np.isnan(e) or np.isnan(n):
            return np.nan
        if s <= 0 or n <= 0:
            return np.nan
        return (e / s) ** (1.0 / n) - 1.0
    except Exception:
        return np.nan


def _mean_valid(series):
    """Mean of non-NaN values, or NaN if none."""
    vals = [v for v in series if not np.isnan(v)]
    return float(np.mean(vals)) if vals else np.nan


def _sm_heatmap_style(df_num, price_fmt="${:.2f}", price=None, mid_row=None, mid_col=None):
    """Return a Styler with green=high / red=low heatmap colouring.

    Optional:
      price    – current stock price; cells where IV > price get bold white text
      mid_row  – index label of the Mid-scenario row (gets yellow border)
      mid_col  – column name of the Mid-scenario column (gets yellow border)
    """
    flat = df_num.values.flatten()
    flat = flat[~np.isnan(flat)]
    if len(flat) == 0:
        return df_num.style
    vmin, vmax = float(np.nanmin(flat)), float(np.nanmax(flat))

    def _bg(val):
        if pd.isna(val):
            return "background-color:#1a1d27;color:#ef4444"
        if price is not None and not np.isnan(price) and price > 0:
            ratio = val / price
            if ratio > 1.0:
                # green – intensity based on upside (0 % → faint, ≥ 50 % → saturated)
                intensity = min((ratio - 1.0) / 0.5, 1.0)
                g_c = int(80 + 120 * intensity)
                return f"background-color:rgba(50,{g_c},50,0.55);color:#ffffff;font-weight:700"
            else:
                # red – intensity based on downside (0 % → faint, ≥ 50 % → saturated)
                intensity = min((1.0 - ratio) / 0.5, 1.0)
                r_c = int(80 + 140 * intensity)
                return f"background-color:rgba({r_c},50,50,0.55);color:#e2e8f0;font-weight:600"
        # fallback when no price: relative gradient
        t = (val - vmin) / (vmax - vmin + 1e-9)
        r_c = int(255 * (1 - t)); g_c = int(200 * t)
        color = "#e2e8f0"
        weight = "600"
        return f"background-color:rgba({r_c},{g_c},60,0.4);color:{color};font-weight:{weight}"

    def _border(row_idx, col_name, val):
        styles = []
        if mid_row is not None and row_idx == mid_row:
            styles.append("border-top:2px solid #FFD54F;border-bottom:2px solid #FFD54F")
        if mid_col is not None and col_name == mid_col:
            styles.append("border-left:2px solid #FFD54F;border-right:2px solid #FFD54F")
        return ";".join(styles)

    styler = df_num.style.map(_bg).format(price_fmt, na_rep="N/A")
    if mid_row is not None or mid_col is not None:
        def _cell_border(df):
            result = pd.DataFrame("", index=df.index, columns=df.columns)
            if mid_row is not None and mid_row in result.index:
                result.loc[mid_row, :] = result.loc[mid_row, :].apply(
                    lambda x: x + ("border-top:2px solid #FFD54F;border-bottom:2px solid #FFD54F" if not x else ";border-top:2px solid #FFD54F;border-bottom:2px solid #FFD54F")
                )
            if mid_col is not None and mid_col in result.columns:
                result[mid_col] = result[mid_col].apply(
                    lambda x: x + ("border-left:2px solid #FFD54F;border-right:2px solid #FFD54F" if not x else ";border-left:2px solid #FFD54F;border-right:2px solid #FFD54F")
                )
            return result
        styler = styler.apply(_cell_border, axis=None)
    return styler


# ── API data fetcher ──────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_valuation_api_data(ticker: str, years: int) -> pd.DataFrame:
    """
        Return a DataFrame indexed by year string (e.g. '2023'), with columns:
            Revenue_M, NetIncome_M, TotalEquity_M, FCF_M, LongTermDebt_M,
            SharesOutstanding_M, DividendPerShare, DividendYield,
            EPS, BPS, ProfitMargin, FreeCashFlowMargin, FreeCashFlowPerShare,
            StockPrice, PE, PB, PS, PFCF, ROE, ROI
    Rows are sorted newest-first, with 'TTM' as the first row.
    """
    session = get_yf_session()
    t = yf.Ticker(ticker=ticker, session=session)

    rows: dict[str, dict] = {}

    # ── annual financials ──────────────────────────────────────────────────
    try:
        inc = t.income_stmt          # columns = fiscal-year end dates
        bal = t.balance_sheet
        cf  = t.cashflow
    except Exception:
        inc = bal = cf = pd.DataFrame()

    # helper: pick first matching row label
    def _pick(df, *labels):
        for lbl in labels:
            for idx in df.index:
                if str(idx).lower() == lbl.lower():
                    return df.loc[idx]
        return pd.Series(dtype="float64")

    inc_rev   = _pick(inc, "Total Revenue")
    inc_ni    = _pick(inc, "Net Income", "Net Income Common Stockholders")
    inc_eps   = _pick(inc, "Basic EPS", "Diluted EPS")
    bal_eq    = _pick(bal, "Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest")
    bal_ltd   = _pick(bal, "Long Term Debt", "Long-Term Debt")
    bal_sh    = _pick(bal, "Ordinary Shares Number", "Share Issued")
    bal_cash  = _pick(bal, "Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments", "Cash And Short Term Investments")
    cf_ocf    = _pick(cf, "Operating Cash Flow", "Cash Flow From Continuing Operations")
    cf_capex  = _pick(cf, "Capital Expenditure")

    # ── collect fiscal-year columns available from API ─────────────────
    annual_cols = []
    if not inc.empty:
        for col in inc.columns:
            try:
                annual_cols.append(col)
            except Exception:
                pass

    # ── historical closing prices keyed by year ───────────────────────────
    try:
        hist = t.history(period="max")
        hist.index = hist.index.tz_localize(None) if getattr(hist.index, "tz", None) is not None else hist.index
    except Exception:
        hist = pd.DataFrame()

    def _eoy_price(year: int):
        if hist.empty:
            return np.nan
        yr_data = hist[hist.index.year == year]
        if yr_data.empty:
            return np.nan
        return float(yr_data["Close"].iloc[-1])

    # ── dividends keyed by year ───────────────────────────────────────────
    try:
        divs = t.dividends
        if hasattr(divs.index, "tz") and divs.index.tz is not None:
            divs.index = divs.index.tz_localize(None)
        div_by_year = divs.groupby(divs.index.year).sum().to_dict()
    except Exception:
        div_by_year = {}

    # ── pre-populate ALL requested year rows with NaN ─────────────────────
    current_year = pd.Timestamp.today().year
    _empty_row: dict = {
        "Revenue [M]": np.nan, "Net Income [M]": np.nan, "Total Equity [M]": np.nan,
        "FCF [M]": np.nan, "Long term debt [M]": np.nan, "Shares Outstanding [M]": np.nan, "Cash [M]": np.nan,
        "Dividend per share": np.nan, "Dividend Yield": np.nan,
        "EPS $": np.nan, "BPS $": np.nan, "Profit Margin": np.nan,
        "Free Cash Flow Margin": np.nan, "Free Cash Flow per share": np.nan,
        "Stock Price": np.nan,
        "P/E": np.nan, "P/B": np.nan, "P/S": np.nan, "P/FCF": np.nan,
        "ROE": np.nan, "ROI": np.nan, "Enterprise Value [M]": np.nan,
    }
    for _yr in range(current_year - 1, current_year - years - 1, -1):
        rows[str(_yr)] = _empty_row.copy()
        # fill price + dividends even when financials are missing
        _p = _eoy_price(_yr)
        _d = float(div_by_year.get(_yr, np.nan))
        rows[str(_yr)]["Stock Price"] = _p
        rows[str(_yr)]["Dividend per share"] = _d
        if not np.isnan(_d) and not np.isnan(_p) and _p > 0:
            rows[str(_yr)]["Dividend Yield"] = _d / _p

    # ── build annual rows ─────────────────────────────────────────────────
    def _get_val(series, col):
        try:
            return _safe_float(series[col])
        except Exception:
            return np.nan

    for col in annual_cols:
        try:
            yr = pd.Timestamp(col).year
        except Exception:
            continue
        yr_str = str(yr)

        revenue     = _get_val(inc_rev,  col) / 1e6
        net_income  = _get_val(inc_ni,   col) / 1e6
        tot_equity  = _get_val(bal_eq,   col) / 1e6
        ltd         = _get_val(bal_ltd,  col) / 1e6
        cash_m      = _get_val(bal_cash, col) / 1e6
        ocf         = _get_val(cf_ocf,   col)
        capex       = _get_val(cf_capex, col)
        fcf         = (ocf - abs(capex)) / 1e6 if not np.isnan(ocf) and not np.isnan(capex) else np.nan
        shares_m    = _get_val(bal_sh,   col) / 1e6
        eps         = _get_val(inc_eps,  col)
        bps         = (tot_equity * 1e6 / (shares_m * 1e6)) if (shares_m and shares_m > 0 and not np.isnan(tot_equity)) else np.nan
        profit_margin = (net_income / revenue * 100) if (revenue and revenue != 0 and not np.isnan(net_income)) else np.nan
        fcf_margin    = (fcf / revenue * 100) if (revenue and revenue != 0 and not np.isnan(fcf)) else np.nan
        price       = _eoy_price(yr)
        div_ps      = float(div_by_year.get(yr, np.nan))
        div_yield   = (div_ps / price) if (price and price > 0 and not np.isnan(div_ps)) else np.nan
        pe          = (price / eps)    if (eps and abs(eps) > 0 and not np.isnan(price)) else np.nan
        pb          = (price / bps)    if (bps and abs(bps) > 0 and not np.isnan(price)) else np.nan
        rev_ps      = (revenue * 1e6 / (shares_m * 1e6)) if (shares_m and shares_m > 0 and not np.isnan(revenue)) else np.nan
        ps          = (price / rev_ps) if (rev_ps and abs(rev_ps) > 0 and not np.isnan(price)) else np.nan
        fcf_ps      = (fcf * 1e6 / (shares_m * 1e6)) if (shares_m and shares_m > 0 and not np.isnan(fcf)) else np.nan
        pfcf        = (price / fcf_ps) if (fcf_ps and abs(fcf_ps) > 0 and not np.isnan(price)) else np.nan
        roe         = (net_income / tot_equity * 100) if (tot_equity and tot_equity > 0 and not np.isnan(net_income)) else np.nan
        invested    = tot_equity + (ltd if not np.isnan(ltd) else 0.0)
        roic        = (net_income / invested * 100) if (invested and invested > 0 and not np.isnan(net_income)) else np.nan
        ev_m        = (price * shares_m + (ltd if not np.isnan(ltd) else 0.0) - (cash_m if not np.isnan(cash_m) else 0.0)) if (not np.isnan(price) and shares_m and shares_m > 0) else np.nan

        rows[yr_str] = {
            "Revenue [M]":            revenue,
            "Net Income [M]":         net_income,
            "Total Equity [M]":       tot_equity,
            "FCF [M]":                fcf,
            "Long term debt [M]":     ltd,
            "Cash [M]":               cash_m,
            "Shares Outstanding [M]": shares_m,
            "Dividend per share":     div_ps,
            "Dividend Yield":         div_yield,
            "EPS $":                  eps,
            "BPS $":                  bps,
            "Profit Margin":          profit_margin,
            "Free Cash Flow Margin":  fcf_margin,
            "Free Cash Flow per share": fcf_ps,
            "Stock Price":            price,
            "P/E":                    pe,
            "P/B":                    pb,
            "P/S":                    ps,
            "P/FCF":                  pfcf,
            "ROE":                    roe,
            "ROI":                    roic,
            "Enterprise Value [M]":   ev_m,
        }

    # ── TTM row ───────────────────────────────────────────────────────────
    try:
        q_inc = t.quarterly_income_stmt
        q_bal = t.quarterly_balance_sheet
        q_cf  = t.quarterly_cashflow
        ttm_cols_inc = list(q_inc.columns[:4]) if q_inc is not None and len(q_inc.columns) >= 4 else []
        ttm_cols_cf  = list(q_cf.columns[:4])  if q_cf  is not None and len(q_cf.columns)  >= 4 else []

        def _ttm_sum(df, *labels):
            s = _pick(df, *labels)
            try:
                return float(s[ttm_cols_inc[:len(s)]].sum())
            except Exception:
                return np.nan

        def _ttm_sum_cf(df, *labels):
            s = _pick(df, *labels)
            try:
                return float(s[ttm_cols_cf[:len(s)]].sum())
            except Exception:
                return np.nan

        def _latest_bal(df, *labels):
            s = _pick(df, *labels)
            try:
                return _safe_float(s.iloc[0])
            except Exception:
                return np.nan

        ttm_rev     = _ttm_sum(q_inc, "Total Revenue") / 1e6
        ttm_ni      = _ttm_sum(q_inc, "Net Income", "Net Income Common Stockholders") / 1e6
        ttm_eps     = _ttm_sum(q_inc, "Basic EPS", "Diluted EPS")
        ttm_eq      = _latest_bal(q_bal, "Stockholders Equity", "Common Stock Equity") / 1e6
        ttm_ltd     = _latest_bal(q_bal, "Long Term Debt", "Long-Term Debt") / 1e6
        ttm_cash    = _latest_bal(q_bal, "Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments", "Cash And Short Term Investments") / 1e6
        ttm_sh      = _latest_bal(q_bal, "Ordinary Shares Number", "Share Issued") / 1e6
        ttm_ocf     = _ttm_sum_cf(q_cf, "Operating Cash Flow", "Cash Flow From Continuing Operations")
        ttm_capex   = _ttm_sum_cf(q_cf, "Capital Expenditure")
        ttm_fcf     = (ttm_ocf - abs(ttm_capex)) / 1e6 if not np.isnan(ttm_ocf) and not np.isnan(ttm_capex) else np.nan
        ttm_bps     = (ttm_eq * 1e6 / (ttm_sh * 1e6)) if (ttm_sh and ttm_sh > 0 and not np.isnan(ttm_eq)) else np.nan
        ttm_profit_margin = (ttm_ni / ttm_rev * 100) if (ttm_rev and ttm_rev != 0 and not np.isnan(ttm_ni)) else np.nan
        ttm_fcf_margin = (ttm_fcf / ttm_rev * 100) if (ttm_rev and ttm_rev != 0 and not np.isnan(ttm_fcf)) else np.nan
        ttm_price   = float(hist["Close"].iloc[-1]) if not hist.empty else np.nan

        # TTM dividends: last 12 months
        try:
            one_yr_ago = pd.Timestamp.today() - pd.Timedelta(days=365)
            ttm_div_ps = float(divs[divs.index >= one_yr_ago].sum())
        except Exception:
            ttm_div_ps = np.nan

        ttm_dy      = (ttm_div_ps / ttm_price) if (ttm_price and ttm_price > 0 and not np.isnan(ttm_div_ps)) else np.nan
        ttm_pe      = (ttm_price / ttm_eps)    if (ttm_eps   and abs(ttm_eps)   > 0 and not np.isnan(ttm_price)) else np.nan
        ttm_pb      = (ttm_price / ttm_bps)    if (ttm_bps   and abs(ttm_bps) > 0 and not np.isnan(ttm_price)) else np.nan
        ttm_rev_ps  = (ttm_rev * 1e6 / (ttm_sh * 1e6)) if (ttm_sh and ttm_sh > 0 and not np.isnan(ttm_rev)) else np.nan
        ttm_ps      = (ttm_price / ttm_rev_ps) if (ttm_rev_ps and abs(ttm_rev_ps) > 0 and not np.isnan(ttm_price)) else np.nan
        ttm_fcf_ps  = (ttm_fcf * 1e6 / (ttm_sh * 1e6)) if (ttm_sh and ttm_sh > 0 and not np.isnan(ttm_fcf)) else np.nan
        ttm_pfcf    = (ttm_price / ttm_fcf_ps) if (ttm_fcf_ps and abs(ttm_fcf_ps) > 0 and not np.isnan(ttm_price)) else np.nan
        ttm_roe     = (ttm_ni / ttm_eq * 100)        if (ttm_eq and ttm_eq > 0 and not np.isnan(ttm_ni)) else np.nan
        ttm_inv     = ttm_eq + (ttm_ltd if not np.isnan(ttm_ltd) else 0.0)
        ttm_roic    = (ttm_ni / ttm_inv * 100)       if (ttm_inv and ttm_inv > 0 and not np.isnan(ttm_ni)) else np.nan
        ttm_ev      = (ttm_price * ttm_sh + (ttm_ltd if not np.isnan(ttm_ltd) else 0.0) - (ttm_cash if not np.isnan(ttm_cash) else 0.0)) if (not np.isnan(ttm_price) and ttm_sh and ttm_sh > 0) else np.nan

        rows["TTM"] = {
            "Revenue [M]":            ttm_rev,
            "Net Income [M]":         ttm_ni,
            "Total Equity [M]":       ttm_eq,
            "FCF [M]":                ttm_fcf,
            "Long term debt [M]":     ttm_ltd,
            "Cash [M]":               ttm_cash,
            "Shares Outstanding [M]": ttm_sh,
            "Dividend per share":     ttm_div_ps,
            "Dividend Yield":         ttm_dy,
            "EPS $":                  ttm_eps,
            "BPS $":                  ttm_bps,
            "Profit Margin":          ttm_profit_margin,
            "Free Cash Flow Margin":  ttm_fcf_margin,
            "Free Cash Flow per share": ttm_fcf_ps,
            "Stock Price":            ttm_price,
            "P/E":                    ttm_pe,
            "P/B":                    ttm_pb,
            "P/S":                    ttm_ps,
            "P/FCF":                  ttm_pfcf,
            "ROE":                    ttm_roe,
            "ROI":                    ttm_roic,
            "Enterprise Value [M]":   ttm_ev,
        }
    except Exception:
        pass

    if not rows:
        return pd.DataFrame()

    # sort: TTM first, then years descending
    year_keys  = sorted([k for k in rows if k != "TTM"], reverse=True)
    order      = (["TTM"] if "TTM" in rows else []) + year_keys
    df = pd.DataFrame([rows[k] for k in order], index=order)
    df.index.name = "Year"
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_ttm_quarter_info(ticker: str) -> dict:
    """
    Return latest reported quarter (from yfinance quarterly statements)
    and suggested TTM correction factor.
    Mapping: Q1->0.75, Q2->0.50, Q3->0.25, Q4->1.00
    """
    default = {
        "quarter_label": "N/A",
        "ttm_cf": 0.50,
        "quarter": None,
        "year": None,
        "asof": None,
    }
    try:
        session = get_yf_session()
        t = yf.Ticker(ticker=ticker, session=session)

        cols = []
        for q_df in [
            getattr(t, "quarterly_income_stmt", pd.DataFrame()),
            getattr(t, "quarterly_balance_sheet", pd.DataFrame()),
            getattr(t, "quarterly_cashflow", pd.DataFrame()),
        ]:
            try:
                if q_df is not None and not q_df.empty:
                    cols.extend(list(q_df.columns))
            except Exception:
                pass

        q_dates = []
        for c in cols:
            try:
                q_dates.append(pd.Timestamp(c).tz_localize(None))
            except Exception:
                continue

        if not q_dates:
            return default

        latest = max(q_dates)
        q = int(((latest.month - 1) // 3) + 1)
        _cf_map = {1: 0.75, 2: 0.50, 3: 0.25, 4: 1.00}
        cf = float(_cf_map.get(q, 0.50))
        return {
            "quarter_label": f"Q{q} {latest.year}",
            "ttm_cf": cf,
            "quarter": q,
            "year": int(latest.year),
            "asof": latest,
        }
    except Exception:
        return default


# ── merge + override mask ─────────────────────────────────────────────────────

def merge_api_and_manual(api_df: pd.DataFrame, manual_df: pd.DataFrame):
    """
    Returns:
      effective_df  – manual value where set, otherwise api value
      override_mask – bool DataFrame, True where manual overrides api
    """
    if api_df.empty:
        return api_df.copy(), pd.DataFrame(dtype=bool)

    effective = api_df.copy()
    mask      = pd.DataFrame(False, index=api_df.index, columns=api_df.columns)

    if manual_df is None or manual_df.empty:
        return effective, mask

    for col in api_df.columns:
        if col not in manual_df.columns:
            continue
        for idx in api_df.index:
            if idx not in manual_df.index:
                continue
            mv = manual_df.loc[idx, col]
            av = api_df.loc[idx, col]
            if not pd.isna(mv) and mv != av:
                effective.loc[idx, col] = mv
                mask.loc[idx, col] = True

    return effective, mask


# ── metrics computation ───────────────────────────────────────────────────────

def compute_metrics(eff: pd.DataFrame) -> pd.DataFrame:
    """
    Returns a metrics DataFrame with rows = metric names,
    columns = ['10 let', '5 let', '3 roky', '1 rok'].
    """
    horizons = {"10 let": 10, "5 let": 5, "3 roky": 3, "1 rok": 1}
    metric_keys = [
        "ROI", "Equity CAGR", "BPS CAGR", "EPS CAGR",
        "Revenue CAGR", "FCF CAGR", "ROE",
        "Dividend growth rate", "Dividend payout ratio", "P/E", "Profit Margin",
        "Free Cash Flow Margin", "Free Cash Flow per share",
    ]
    results = {h: {} for h in horizons}

    # Only annual rows (exclude TTM for CAGR calcs)
    annual = eff.drop(index=["TTM"], errors="ignore")
    # sort ascending by year
    annual = annual.sort_index()

    # TTM row for single-point averages
    ttm_row = eff.loc["TTM"] if "TTM" in eff.index else pd.Series(dtype=float)

    def _ttm(col):
        try:
            return _safe_float(ttm_row[col])
        except Exception:
            return np.nan

    def _series(col):
        if col not in annual.columns:
            return pd.Series(dtype=float)
        return annual[col].apply(_safe_float)

    rev  = _series("Revenue [M]")
    ni   = _series("Net Income [M]")
    eq   = _series("Total Equity [M]")
    fcf  = _series("FCF [M]")
    eps  = _series("EPS $")
    bps  = _series("BPS $")
    roe  = _series("ROE")
    roic = _series("ROI")
    div  = _series("Dividend per share")
    pe   = _series("P/E")
    pm   = _series("Profit Margin")
    fcfm = _series("Free Cash Flow Margin")
    fcfps = _series("Free Cash Flow per share")

    # dividend payout ratio = DPS / EPS
    dpr = pd.Series({idx: (div[idx] / eps[idx]) if not np.isnan(div[idx]) and not np.isnan(eps[idx]) and eps[idx] > 0 else np.nan
                      for idx in annual.index}, dtype=float)

    for h_label, n in horizons.items():
        # pick start & end rows by position from top/bottom of annual
        sorted_years = list(annual.index)
        if len(sorted_years) < 2:
            for mk in metric_keys:
                results[h_label][mk] = np.nan
            continue

        # "end" = most recent annual row, "start" = n years earlier
        end_idx   = sorted_years[-1]
        # try to find a row exactly n years before end
        try:
            end_yr   = int(end_idx)
            start_yr = end_yr - n
            start_idx = str(start_yr) if str(start_yr) in sorted_years else None
        except Exception:
            start_idx = None

        if start_idx is None:
            # fallback: use first available if within 2 year tolerance
            if len(sorted_years) >= n:
                start_idx = sorted_years[-(n + 1)] if (n + 1) <= len(sorted_years) else sorted_years[0]
            else:
                for mk in metric_keys:
                    results[h_label][mk] = np.nan
                continue

        try:
            actual_n = int(end_idx) - int(start_idx)
        except Exception:
            actual_n = n
        if actual_n <= 0:
            actual_n = n

        def _get(series, idx):
            return series[idx] if idx in series.index else np.nan

        results[h_label]["Revenue CAGR"]       = _cagr(_get(rev,  start_idx), _get(rev,  end_idx), actual_n)
        results[h_label]["Equity CAGR"]        = _cagr(_get(eq,   start_idx), _get(eq,   end_idx), actual_n)
        _eps_s = _get(eps, start_idx); _eps_e = _get(eps, end_idx)
        # EPS CAGR: only meaningful when both endpoints are positive; abs() can give false signal for neg→pos transitions
        results[h_label]["EPS CAGR"]           = _cagr(_eps_s, _eps_e, actual_n) if (not np.isnan(_eps_s) and _eps_s > 0 and not np.isnan(_eps_e) and _eps_e > 0) else np.nan
        results[h_label]["BPS CAGR"]           = _cagr(_get(bps,  start_idx), _get(bps,  end_idx), actual_n)
        results[h_label]["FCF CAGR"]           = _cagr(_get(fcf,  start_idx), _get(fcf,  end_idx), actual_n)
        results[h_label]["Dividend growth rate"] = _cagr(_get(div, start_idx), _get(div, end_idx), actual_n)

        # averages over the window (for "1 rok" use TTM as the latest available value)
        if n == 1:
            results[h_label]["ROI"]   = _ttm("ROI")
            results[h_label]["ROE"]   = _ttm("ROE")
            results[h_label]["Dividend payout ratio"] = (
                (_ttm("Dividend per share") / _ttm("EPS $"))
                if not np.isnan(_ttm("EPS $")) and _ttm("EPS $") > 0 and not np.isnan(_ttm("Dividend per share"))
                else np.nan
            )
            results[h_label]["P/E"]   = _ttm("P/E")
            results[h_label]["Profit Margin"] = _ttm("Profit Margin")
            results[h_label]["Free Cash Flow Margin"] = _ttm("Free Cash Flow Margin")
            results[h_label]["Free Cash Flow per share"] = _ttm("Free Cash Flow per share")
        else:
            window_idx  = [y for y in sorted_years if start_idx <= y <= end_idx]
            results[h_label]["ROI"]   = _mean_valid([_get(roic, y) for y in window_idx])
            results[h_label]["ROE"]   = _mean_valid([_get(roe,  y) for y in window_idx])
            results[h_label]["Dividend payout ratio"] = _mean_valid([_get(dpr, y) for y in window_idx])
            results[h_label]["P/E"]   = _mean_valid([_get(pe,   y) for y in window_idx])
            results[h_label]["Profit Margin"] = _mean_valid([_get(pm, y) for y in window_idx])
            results[h_label]["Free Cash Flow Margin"] = _mean_valid([_get(fcfm, y) for y in window_idx])
            results[h_label]["Free Cash Flow per share"] = _mean_valid([_get(fcfps, y) for y in window_idx])

    metrics_df = pd.DataFrame(results, index=metric_keys)
    return metrics_df


# ── styler ────────────────────────────────────────────────────────────────────

def style_effective_df(eff: pd.DataFrame, mask: pd.DataFrame) -> "pd.io.formats.style.Styler":
    """Return a Styler: overridden cells highlighted in amber."""

    def _highlight(val, flag):
        if flag:
            return "background-color: #7a5c00; color: #ffe082; font-weight: bold;"
        return ""

    def _fmt(v, col):
        if pd.isna(v):
            return ""
        if col == "Dividend Yield":
            return f"{v:.2%}"
        if col in ("ROE", "ROI", "Profit Margin", "Free Cash Flow Margin"):
            return f"{v:.2f}%"
        if col in ("P/E", "P/B", "P/S", "P/FCF"):
            return f"{v:.1f}×"
        if col in ("Revenue [M]", "Net Income [M]", "Total Equity [M]", "FCF [M]",
                   "Long term debt [M]", "Shares Outstanding [M]"):
            return f"{v:,.0f}"
        if col in ("EPS $", "BPS $", "Dividend per share", "Stock Price", "Free Cash Flow per share"):
            return f"{v:.2f}"
        return f"{v:.2f}"

    # build formatted string table
    fmt_df = eff.copy().astype(object)
    for col in eff.columns:
        for idx in eff.index:
            fmt_df.loc[idx, col] = _fmt(eff.loc[idx, col], col)

    # apply cell styles via Styler
    style = fmt_df.style

    if not mask.empty:
        aligned_mask = mask.reindex(index=eff.index, columns=eff.columns, fill_value=False)

        def _cell_style(row_label, col_label):
            try:
                return aligned_mask.loc[row_label, col_label]
            except Exception:
                return False

        def _apply_row(row):
            styles = []
            for col in row.index:
                flag = _cell_style(row.name, col)
                styles.append(_highlight(row[col], flag))
            return styles

        style = style.apply(_apply_row, axis=1)

    style = style.set_table_styles([
        {"selector": "th", "props": [("background-color", "#1e2030"), ("color", "#cdd6f4"), ("font-size", "12px"), ("padding", "4px 8px")]},
        {"selector": "td", "props": [("font-size", "12px"), ("padding", "3px 8px"), ("text-align", "right")]},
        {"selector": "tr:hover td", "props": [("background-color", "#2a2d3e")]},
    ])
    return style


def style_metrics_df(mdf: pd.DataFrame):
    """Style the metrics DataFrame with % formatting for CAGRs/ROE/ROI etc."""

    # percent rows
    pct_rows = {"Equity CAGR", "BPS CAGR", "EPS CAGR",
                "Revenue CAGR", "FCF CAGR", "Dividend growth rate",
                "Dividend payout ratio"}
    pct_plain_rows = {"ROE", "ROI"}

    def _fmt_metric(v, row_label):
        if pd.isna(v):
            return "N/A"
        if row_label in pct_plain_rows:
            return f"{v:.1f}%"
        if row_label in pct_rows:
            return f"{v:.1%}"
        if row_label == "P/E":
            return f"{v:.1f}×"
        if row_label == "Profit Margin":
            return f"{v:.1f}%"
        if row_label == "Free Cash Flow Margin":
            return f"{v:.1f}%"
        if row_label == "Free Cash Flow per share":
            return f"{v:.2f}"
        return f"{v:.2f}"

    fmt = mdf.copy().astype(object)
    for idx in mdf.index:
        for col in mdf.columns:
            fmt.loc[idx, col] = _fmt_metric(mdf.loc[idx, col], idx)

    def _color_row(row):
        styles = []
        for v in row:
            if v == "N/A":
                styles.append("color: #555; font-weight: normal;")
            else:
                styles.append("")
        return styles

    style = (
        fmt.style
        .apply(_color_row, axis=1)
        .set_table_styles([
            {"selector": "th", "props": [("background-color", "#1e2030"), ("color", "#cdd6f4"), ("font-size", "12px"), ("padding", "4px 8px")]},
            {"selector": "td", "props": [("font-size", "12px"), ("padding", "3px 8px"), ("text-align", "right")]},
        ])
    )
    return style


# ── Excel export ──────────────────────────────────────────────────────────────

def build_excel(eff: pd.DataFrame, metrics: pd.DataFrame) -> bytes:
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        eff.to_excel(writer, sheet_name="Inputs (effective)")
        metrics.to_excel(writer, sheet_name="Metrics")
    return buf.getvalue()


# ── Snapshot helpers ──────────────────────────────────────────────────────────

def get_snapshot_dir() -> Path:
    try:
        base = Path(__file__).parent
    except NameError:
        base = Path.cwd()
    return base / "snapshots"


def ensure_snapshot_dir() -> Path:
    d = get_snapshot_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def build_snapshot_excel_bytes(
    effective_df: pd.DataFrame,
    metrics_df: pd.DataFrame,
    manual_df: pd.DataFrame,
    override_mask: pd.DataFrame,
    scope: str,
    ticker: str = "",
    years: int = 0,
    current_price: float = np.nan,
    scenario_inputs_df: pd.DataFrame = None,
    scenario_outputs_df: pd.DataFrame = None,
    meta: dict = None,
) -> bytes:
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        effective_df.to_excel(writer, sheet_name="Inputs_effective")
        if not manual_df.empty:
            manual_df.to_excel(writer, sheet_name="Inputs_manual")
        else:
            pd.DataFrame().to_excel(writer, sheet_name="Inputs_manual")
        override_mask.astype(int).to_excel(writer, sheet_name="Override_mask")

        # Metrics sheet: write metrics_df, then append current price below
        metrics_df.to_excel(writer, sheet_name="Metrics")
        if not np.isnan(current_price):
            _price_info = pd.DataFrame(
                [[current_price]],
                index=["Aktuální cena ($)"],
                columns=["hodnota v době exportu"],
            )
            _price_info.to_excel(
                writer,
                sheet_name="Metrics",
                startrow=len(metrics_df) + 3,
            )

        # Meta sheet
        _meta = {
            "ticker": ticker,
            "years": years,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "format_version": 1,
            "scope": scope,
        }
        if meta:
            _meta.update(meta)
        pd.DataFrame([_meta]).to_excel(writer, sheet_name="Meta", index=False)

        if scope == "FULL" and scenario_inputs_df is not None:
            scenario_inputs_df.to_excel(writer, sheet_name="Scenario_inputs", index=False)
        if scope == "FULL" and scenario_outputs_df is not None:
            scenario_outputs_df.to_excel(writer, sheet_name="Scenario_outputs", index=False)

    return buf.getvalue()


def build_roe_excel_bytes(
    roe_params: dict,
    roe_proj: dict,
    roe_sc_labels: list,
    ticker: str = "",
    current_price: float = np.nan,
) -> bytes:
    """Export ROE model inputs, outputs and year-by-year projections to Excel."""
    buf = BytesIO()
    _param_keys = ["roe_1_3", "roe_4_5", "roe_6_10", "dg_1_3", "dg_4_5", "dg_6_10", "tax", "r", "pe", "ttm_cf"]
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        # Inputs per scenario
        _inp_rows = []
        for sn in roe_sc_labels:
            p = roe_params.get(sn, {})
            _inp_rows.append({"Scénář": sn, **{k: p.get(k, np.nan) for k in _param_keys}})
        pd.DataFrame(_inp_rows).to_excel(writer, sheet_name="ROE_inputs", index=False)

        # Outputs per scenario
        _out_rows = []
        for sn in roe_sc_labels:
            d = roe_proj.get(sn, {})
            _out_rows.append({
                "Scénář": sn,
                "Intrinsic Value ($)": d.get("iv", np.nan),
                "PV zdaněných dividend ($)": d.get("pv_div", np.nan),
                "PV terminální ($)": d.get("pv_term", np.nan),
                "Upside/Downside": d.get("mos", np.nan),
            })
        pd.DataFrame(_out_rows).to_excel(writer, sheet_name="ROE_outputs", index=False)

        # Year-by-year projection per scenario
        for sn in roe_sc_labels:
            rows = roe_proj.get(sn, {}).get("rows", [])
            if rows:
                pd.DataFrame(rows).to_excel(writer, sheet_name=f"ROE_proj_{sn}", index=False)

        # Meta
        pd.DataFrame([{
            "ticker": ticker,
            "current_price": current_price,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "format_version": 1,
            "scope": "ROE",
        }]).to_excel(writer, sheet_name="Meta", index=False)
    return buf.getvalue()


def build_all_excel_bytes(
    effective_df: pd.DataFrame,
    metrics_df: pd.DataFrame,
    manual_df: pd.DataFrame,
    override_mask: pd.DataFrame,
    ticker: str,
    years: int,
    current_price: float,
    scenario_inputs_df: pd.DataFrame = None,
    scenario_outputs_df: pd.DataFrame = None,
    roe_params: dict = None,
    roe_proj: dict = None,
    roe_sc_labels: list = None,
    current_price_roe: float = np.nan,
    simple_eps_params: dict = None,
    simple_rev_params: dict = None,
    damodaran_params: dict = None,
) -> bytes:
    """Combined export: all models + historical data in one workbook."""
    if roe_params    is None: roe_params    = {}
    if roe_proj      is None: roe_proj      = {}
    if roe_sc_labels is None: roe_sc_labels = []

    buf = BytesIO()
    _param_keys = ["roe_1_3", "roe_4_5", "roe_6_10", "dg_1_3", "dg_4_5", "dg_6_10", "tax", "r", "pe", "ttm_cf"]
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        # ── Historická data ───────────────────────────────────────────
        effective_df.to_excel(writer, sheet_name="Inputs_effective")
        if manual_df is not None and not manual_df.empty:
            manual_df.to_excel(writer, sheet_name="Inputs_manual")
        else:
            pd.DataFrame().to_excel(writer, sheet_name="Inputs_manual")
        override_mask.astype(int).to_excel(writer, sheet_name="Override_mask")
        metrics_df.to_excel(writer, sheet_name="Metrics")
        if not np.isnan(current_price):
            _price_info = pd.DataFrame(
                [[current_price]],
                index=["Aktuální cena ($)"],
                columns=["hodnota v době exportu"],
            )
            _price_info.to_excel(writer, sheet_name="Metrics", startrow=len(metrics_df) + 3)

        # ── Advanced Valuation ────────────────────────────────────────
        if scenario_inputs_df is not None and not scenario_inputs_df.empty:
            scenario_inputs_df.to_excel(writer, sheet_name="AdvVal_inputs", index=False)
            scenario_inputs_df.to_excel(writer, sheet_name="Scenario_inputs", index=False)
        if scenario_outputs_df is not None and not scenario_outputs_df.empty:
            scenario_outputs_df.to_excel(writer, sheet_name="AdvVal_outputs", index=False)
            scenario_outputs_df.to_excel(writer, sheet_name="Scenario_outputs", index=False)

        # ── ROE model Dan Gladiš ──────────────────────────────────────
        if roe_sc_labels:
            _inp_rows = []
            for sn in roe_sc_labels:
                p = roe_params.get(sn, {})
                _inp_rows.append({"Scénář": sn, **{k: p.get(k, np.nan) for k in _param_keys}})
            pd.DataFrame(_inp_rows).to_excel(writer, sheet_name="ROE_inputs", index=False)

            _out_rows = []
            for sn in roe_sc_labels:
                d = roe_proj.get(sn, {})
                _out_rows.append({
                    "Scénář": sn,
                    "Intrinsic Value ($)": d.get("iv", np.nan),
                    "PV zdaněných dividend ($)": d.get("pv_div", np.nan),
                    "PV terminální ($)": d.get("pv_term", np.nan),
                    "Upside/Downside": d.get("mos", np.nan),
                })
            pd.DataFrame(_out_rows).to_excel(writer, sheet_name="ROE_outputs", index=False)

            for sn in roe_sc_labels:
                rows = roe_proj.get(sn, {}).get("rows", [])
                if rows:
                    pd.DataFrame(rows).to_excel(writer, sheet_name=f"ROE_proj_{sn}", index=False)

        # ── Simple EPS / Revenue Growth ───────────────────────────────
        if simple_eps_params:
            _seps_rows = []
            for sn, p in simple_eps_params.items():
                _seps_rows.append({"Scénář": sn, "g_EPS [%]": p.get("g"), "Terminal P/E": p.get("pe"),
                                   "Discount rate [%]": p.get("r"), "Years": p.get("n")})
            pd.DataFrame(_seps_rows).to_excel(writer, sheet_name="SimpleEPS_inputs", index=False)
        if simple_rev_params:
            _srev_rows = []
            for sn, p in simple_rev_params.items():
                _srev_rows.append({"Scénář": sn, "g_Rev [%]": p.get("g"), "Net Margin [%]": p.get("nm"),
                                   "Terminal P/E": p.get("pe"), "Discount rate [%]": p.get("r"),
                                   "Years": p.get("n")})
            pd.DataFrame(_srev_rows).to_excel(writer, sheet_name="SimpleRev_inputs", index=False)

        # ── Simple Valuation – Damodaran ──────────────────────────────
        if damodaran_params:
            _dam_rows = []
            for sn, p in damodaran_params.get("scenarios", {}).items():
                _dam_rows.append({"Scénář": sn, "g_NOPAT [%]": p.get("g"), "ROIC proxy [%]": p.get("roic"),
                                  "WACC [%]": p.get("r"), "Years": p.get("n")})
            _dam_shared = {
                "Tax rate [%]": damodaran_params.get("tax"),
                "g_terminal [%]": damodaran_params.get("g_term"),
                "Cash [M$]": damodaran_params.get("cash_m"),
            }
            if _dam_rows:
                _dam_df_exp = pd.DataFrame(_dam_rows)
                for k, v in _dam_shared.items():
                    _dam_df_exp[k] = v
                _dam_df_exp.to_excel(writer, sheet_name="Damodaran_inputs", index=False)

        # ── Meta ─────────────────────────────────────────────────────
        pd.DataFrame([{
            "ticker": ticker,
            "years": years,
            "current_price": current_price,
            "current_price_roe": current_price_roe,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "format_version": 2,
            "scope": "ALL",
        }]).to_excel(writer, sheet_name="Meta", index=False)
    return buf.getvalue()


def list_snapshots_for_ticker(ticker: str) -> list:
    folder = get_snapshot_dir()
    if not folder.exists():
        return []
    prefix = f"{ticker}_"
    files = sorted(
        [f for f in folder.glob(f"{prefix}*.xlsx")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return files


def load_snapshot(path) -> dict:
    path = Path(path)
    result = {}
    xl = pd.ExcelFile(path, engine="openpyxl")
    sheets = xl.sheet_names

    if "Inputs_manual" in sheets:
        result["manual_df"] = xl.parse("Inputs_manual", index_col=0)
    if "Inputs_effective" in sheets:
        result["effective_df"] = xl.parse("Inputs_effective", index_col=0)
    if "Override_mask" in sheets:
        result["override_mask"] = xl.parse("Override_mask", index_col=0).astype(bool)
    if "Metrics" in sheets:
        result["metrics_df"] = xl.parse("Metrics", index_col=0)
    if "Meta" in sheets:
        result["meta"] = xl.parse("Meta").to_dict(orient="records")[0] if not xl.parse("Meta").empty else {}
    if "Scenario_inputs" in sheets:
        result["scenario_inputs_df"] = xl.parse("Scenario_inputs")
    if "Scenario_outputs" in sheets:
        result["scenario_outputs_df"] = xl.parse("Scenario_outputs")
    return result


# ── Model recommendation heuristics ──────────────────────────────────────────

def _trend_r2_loglinear(vals: list) -> float:
    """R² of log-linear fit: log(x) = a + b*t. For Revenue, BPS — always positive."""
    if len(vals) < 3 or any(v <= 0 for v in vals):
        return np.nan
    y = np.log(np.array(vals, dtype=float))
    x = np.arange(len(y), dtype=float) - np.mean(np.arange(len(y), dtype=float))
    b = np.dot(x, y) / np.dot(x, x)
    fitted = y.mean() + b * x
    ss_res = np.sum((y - fitted) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    return float(1 - ss_res / ss_tot) if ss_tot > 1e-12 else 1.0


def _trend_r2_linear(vals: list) -> float:
    """R² of linear fit: x = a + b*t. For EPS, NI, FCF — may be negative."""
    if len(vals) < 3:
        return np.nan
    y = np.array(vals, dtype=float)
    x = np.arange(len(y), dtype=float) - np.mean(np.arange(len(y), dtype=float))
    b = np.dot(x, y) / np.dot(x, x)
    fitted = y.mean() + b * x
    ss_res = np.sum((y - fitted) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    if ss_tot < 1e-12:
        return 1.0
    return float(1 - ss_res / ss_tot)


def _growth_cv(vals: list) -> float:
    """CV of YoY growth rates — only for always-positive series (Revenue, BPS)."""
    if len(vals) < 3 or any(v <= 0 for v in vals):
        return np.nan
    rates = [(vals[i + 1] - vals[i]) / vals[i] for i in range(len(vals) - 1)]
    mean_r = np.mean(rates)
    if abs(mean_r) < 1e-6:
        return np.nan
    return float(np.std(rates) / abs(mean_r))


def _std_pp(vals: list) -> float:
    """Std dev in percentage-point units — for margins and ROE (ratios, not quantities)."""
    if len(vals) < 3:
        return np.nan
    return float(np.std(vals))


def _eps_growth_std(vals: list) -> float:
    """Std dev of YoY EPS growth rates in pp. Only valid when all EPS values > 0.
    Hard-capped at 30 pp to avoid exploding σ from near-zero EPS transitions."""
    if len(vals) < 3 or any(v <= 0 for v in vals):
        return np.nan
    rates = [(vals[i + 1] - vals[i]) / abs(vals[i]) * 100 for i in range(len(vals) - 1)]
    return min(float(np.std(rates)), 30.0)


def run_monte_carlo(
    fv_fn,
    param_specs,
    n_sim: int = 10_000,
    current_price: float = None,
) -> dict:
    """
    Vectorized Monte Carlo simulation.

    param_specs is a list of dicts:
      {
        "name": str,      # parameter name, must match fv_fn kwarg
        "dist": str,      # "normal" | "uniform" | "fixed"
        "mean": float,    # for normal: mean
        "std": float,     # for normal: std
        "low": float,     # for uniform: lower bound
        "high": float,    # for uniform: upper bound
        "value": float,   # for fixed: exact value
      }
    Returns dict with percentiles, mean, std, prob_above_price, etc.
    """
    rng = np.random.default_rng(seed=42)
    samples = {}
    for p in param_specs:
        if p["dist"] == "normal":
            drawn = rng.normal(p["mean"], p["std"], n_sim)
        elif p["dist"] == "uniform":
            drawn = rng.uniform(p["low"], p["high"], n_sim)
        else:  # fixed
            drawn = np.full(n_sim, p["value"])
        samples[p["name"]] = drawn

    results = np.array([
        fv_fn(**{k: float(v[i]) for k, v in samples.items()})
        for i in range(n_sim)
    ])

    valid_mask = np.isfinite(results)
    valid = results[valid_mask]
    if len(valid) == 0:
        return None

    out = {
        "results": valid,
        "param_samples": {k: v[valid_mask] for k, v in samples.items()},
        "p10": float(np.percentile(valid, 10)),
        "p25": float(np.percentile(valid, 25)),
        "p50": float(np.percentile(valid, 50)),
        "p75": float(np.percentile(valid, 75)),
        "p90": float(np.percentile(valid, 90)),
        "mean": float(np.mean(valid)),
        "std_result": float(np.std(valid)),
        "n_valid": len(valid),
        "n_sim": n_sim,
    }
    if current_price and current_price > 0:
        out["prob_above_price"] = float(np.mean(valid > current_price))
    else:
        out["prob_above_price"] = None
    return out


def render_mc_chart(mc_result: dict, current_price, model_label: str, currency: str = "$"):
    """Render histogram + percentile lines using st.vega_lite_chart."""
    vals = mc_result["results"]

    # Clip to P1–P99 so extreme outliers don't compress the chart
    _clip_lo = float(np.percentile(vals, 1))
    _clip_hi = float(np.percentile(vals, 99))
    vals_clipped = vals[(vals >= _clip_lo) & (vals <= _clip_hi)]
    if len(vals_clipped) < 10:
        vals_clipped = vals  # fallback if clipping removes too much

    counts, edges = np.histogram(vals_clipped, bins=50)
    bin_centers = (edges[:-1] + edges[1:]) / 2

    # Color each bin: red = below current price, green = above
    _has_price = bool(current_price and current_price > 0)
    if _has_price:
        hist_data = [
            {"fv": float(c), "count": int(n),
             "zone": "Pod cenou" if float(c) < current_price else "Nad cenou"}
            for c, n in zip(bin_centers, counts)
        ]
    else:
        hist_data = [{"fv": float(c), "count": int(n), "zone": "FV"}
                     for c, n in zip(bin_centers, counts)]

    # Add a small padding to x-axis domain
    _pad = (_clip_hi - _clip_lo) * 0.04
    _x_domain = [_clip_lo - _pad, _clip_hi + _pad]

    price_line = [{"x": current_price, "label": "Aktuální cena"}] \
                 if _has_price else []

    _color_scale = (
        {"field": "zone", "type": "nominal",
         "scale": {
             "domain": ["Pod cenou", "Nad cenou", "FV"],
             "range":  ["#EF5350",   "#66BB6A",   "#4f8ef7"],
         },
         "legend": {"title": None}}
        if _has_price else {"value": "#4f8ef7"}
    )

    bar_layer = {
        "data": {"values": hist_data},
        "mark": {"type": "bar", "opacity": 0.72},
        "encoding": {
            "x": {"field": "fv", "type": "quantitative",
                  "title": f"Fair Value ({currency})",
                  "bin": False,
                  "scale": {"domain": _x_domain}},
            "y": {"field": "count", "type": "quantitative", "title": "Četnost"},
            "color": _color_scale,
            "tooltip": [
                {"field": "fv",    "title": f"Fair Value ({currency})"},
                {"field": "count", "title": "Počet simulací"},
                {"field": "zone",  "title": "Zóna"},
            ],
        },
    }

    # Percentile rules + inline text labels
    def _pct_rule(x_val, label, short, dash, width, color="#FFD54F"):
        rule = {
            "data": {"values": [{"x": x_val, "label": label, "short": short}]},
            "mark": {"type": "rule", "strokeDash": dash,
                     "color": color, "strokeWidth": width},
            "encoding": {
                "x": {"field": "x", "type": "quantitative",
                      "scale": {"domain": _x_domain}},
                "tooltip": [{"field": "label", "type": "nominal"},
                            {"field": "x", "title": f"Fair Value ({currency})"}],
            },
        }
        text = {
            "data": {"values": [{"x": x_val, "short": short}]},
            "mark": {"type": "text", "align": "left", "dx": 3, "dy": -6,
                     "color": color, "fontSize": 10, "fontWeight": "bold"},
            "encoding": {
                "x": {"field": "x", "type": "quantitative",
                      "scale": {"domain": _x_domain}},
                "y": {"value": 8},
                "text": {"field": "short", "type": "nominal"},
            },
        }
        return rule, text

    pct_layers = []
    for r, t in [
        _pct_rule(mc_result["p10"], "P10 (pesimistický)",  "P10", [2, 4], 1.0, "#FFD54F"),
        _pct_rule(mc_result["p25"], "P25",                  "P25", [6, 3], 1.3, "#FFD54F"),
        _pct_rule(mc_result["p50"], "P50 (medián)",         "P50", [],     2.2, "#FFEE58"),
        _pct_rule(mc_result["p75"], "P75",                  "P75", [6, 3], 1.3, "#FFD54F"),
        _pct_rule(mc_result["p90"], "P90 (optimistický)",  "P90", [2, 4], 1.0, "#FFD54F"),
    ]:
        pct_layers.append(r)
        pct_layers.append(t)

    price_layers = []
    if price_line:
        price_layers.append({
            "data": {"values": price_line},
            "mark": {"type": "rule", "color": "#FF7043", "strokeWidth": 2.5},
            "encoding": {
                "x": {"field": "x", "type": "quantitative",
                      "scale": {"domain": _x_domain}},
                "tooltip": [{"field": "label"},
                            {"field": "x", "title": f"Fair Value ({currency})"}],
            },
        })
        price_layers.append({
            "data": {"values": price_line},
            "mark": {"type": "text", "align": "left", "dx": 3, "dy": 22,
                     "color": "#FF7043", "fontSize": 10, "fontWeight": "bold"},
            "encoding": {
                "x": {"field": "x", "type": "quantitative",
                      "scale": {"domain": _x_domain}},
                "y": {"value": 8},
                "text": {"value": "Cena"},
            },
        })

    st.vega_lite_chart({
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "layer": [bar_layer] + pct_layers + price_layers,
        "resolve": {"scale": {"color": "independent"}},
        "height": 320,
        "config": {"view": {"strokeOpacity": 0}},
        "title": f"Monte Carlo — {model_label} (n = {mc_result['n_valid']:,})",
    }, use_container_width=True)

    pct_rows = [
        {"Percentil": "P10 (pesimistický)", "Fair Value": f"{currency}{mc_result['p10']:.2f}"},
        {"Percentil": "P25",                "Fair Value": f"{currency}{mc_result['p25']:.2f}"},
        {"Percentil": "P50 (medián)",        "Fair Value": f"{currency}{mc_result['p50']:.2f}"},
        {"Percentil": "P75",                "Fair Value": f"{currency}{mc_result['p75']:.2f}"},
        {"Percentil": "P90 (optimistický)", "Fair Value": f"{currency}{mc_result['p90']:.2f}"},
        {"Percentil": "Průměr",             "Fair Value": f"{currency}{mc_result['mean']:.2f}"},
        {"Percentil": "Std. odch. výsledků","Fair Value": f"{mc_result['std_result']:.2f}"},
    ]
    st.dataframe(pd.DataFrame(pct_rows), hide_index=True, use_container_width=True)

    prob = mc_result.get("prob_above_price")
    if prob is not None and current_price and current_price > 0:
        prob_pct = prob * 100
        color = "#66BB6A" if prob_pct >= 60 else ("#FFD54F" if prob_pct >= 40 else "#FF7043")
        st.markdown(
            f"<div style='padding:10px;border-radius:8px;"
            f"background:rgba(255,255,255,0.04);border-left:4px solid {color}'>"
            f"<span style='font-size:14px;font-weight:700;color:{color}'>"
            f"Pravděpodobnost FV &gt; aktuální ceny ({currency}{current_price:.2f}): "
            f"{prob_pct:.1f}%"
            f"</span><br>"
            f"<span style='font-size:11px;color:#93a3b8'>"
            f"Z {mc_result['n_valid']:,} platných simulací vyšla FV nad aktuální cenu "
            f"v {int(prob * mc_result['n_valid']):,} případech.</span></div>",
            unsafe_allow_html=True,
        )

    # ── Filtered simulations warning ──────────────────────────────────────
    n_filtered = mc_result["n_sim"] - mc_result["n_valid"]
    if n_filtered > mc_result["n_sim"] * 0.05:
        st.warning(
            f"⚠ {n_filtered:,} simulací ({n_filtered / mc_result['n_sim'] * 100:.0f} %) "
            f"bylo vyřazeno (nekonečné nebo záporné FV). "
            f"Model je citlivý na kombinace parametrů s extrémními hodnotami."
        )

    # ── Auto-generated interpretive text ─────────────────────────────────
    _p10 = mc_result["p10"]
    _p50 = mc_result["p50"]
    _p90 = mc_result["p90"]
    if _p50 > 0:
        _width_pct = (_p90 - _p10) / _p50 * 100
        if _width_pct < 30:
            _interp = "Úzká distribuce — ocenění je relativně stabilní vůči vstupním předpokladům."
        elif _width_pct < 70:
            _interp = "Středně široká distribuce — výsledky jsou citlivé na vstupní předpoklady."
        else:
            _interp = ("Velmi široká distribuce — ocenění je vysoce nejisté. "
                       "Zvažte vyšší margin of safety (MOS).")
        st.info(
            f"📊 {_interp}  "
            f"P10–P90 rozsah: {currency}{_p10:.2f} – {currency}{_p90:.2f} "
            f"({_width_pct:.0f} % šíře kolem mediánu P50 = {currency}{_p50:.2f})"
        )


def recommend_models(eff: pd.DataFrame, ci_info: dict = None) -> list:
    """
    Evaluates model suitability using TTM snapshot + multi-year historical metrics.
    Uses R² of trend regression (not CV) as primary predictability measure.
    Returns list of dicts: {model, rating, reasons, warnings}
    rating: "✅ Vhodný" | "⚠️ Podmíněně" | "❌ Nevhodný"
    """
    ci_info = ci_info or {}

    # ── TTM snapshot ──────────────────────────────────────────────────────
    ttm = eff.loc["TTM"] if "TTM" in eff.index else pd.Series(dtype=float)

    def _get(col, default=np.nan):
        try:
            return float(ttm[col])
        except Exception:
            return default

    eps_ttm = _get("EPS $")
    rev_ttm = _get("Revenue [M]")
    ni_ttm  = _get("Net Income [M]")
    bps_ttm = _get("BPS $")
    roe_ttm = _get("ROE")
    dps_ttm = _get("Dividend per share")
    fcf_ttm = _get("FCF [M]")
    ltd_ttm = _get("Long term debt [M]", 0)
    eq_ttm  = _get("Total Equity [M]")
    fcf_m   = _get("Free Cash Flow Margin")

    # ── Historical series (annual rows only) ──────────────────────────────
    annual = eff.drop(index=["TTM"], errors="ignore").sort_index()

    def _series(col):
        if col not in annual.columns:
            return []
        out = []
        for v in annual[col]:
            try:
                f = float(v)
                if np.isfinite(f):
                    out.append(f)
            except Exception:
                pass
        return out

    rev_h = _series("Revenue [M]")
    eps_h = _series("EPS $")
    ni_h  = _series("Net Income [M]")
    pm_h  = _series("Profit Margin")   # in %
    fcf_h = _series("FCF [M]")
    roe_h = _series("ROE")             # in %
    bps_h = _series("BPS $")

    # ── Predictability metrics ────────────────────────────────────────────
    rev_r2       = _trend_r2_loglinear(rev_h)   # Revenue: log-linear (exponential growth)
    rev_gcv      = _growth_cv(rev_h)             # CV of YoY revenue growth rates
    eps_r2       = _trend_r2_linear(eps_h)       # EPS: linear (can go negative)
    ni_r2        = _trend_r2_linear(ni_h)
    fcf_r2       = _trend_r2_linear(fcf_h)
    bps_r2       = _trend_r2_loglinear(bps_h)    # BPS: log-linear (should compound)
    pm_std       = _std_pp(pm_h)                 # Margin stability in pp (not CV!)
    roe_std      = _std_pp(roe_h)                # ROE stability in pp
    eps_pos_frac = (sum(1 for v in eps_h if v > 0) / len(eps_h)
                    if eps_h else np.nan)
    fcf_pos_frac = (sum(1 for v in fcf_h if v > 0) / len(fcf_h)
                    if fcf_h else np.nan)
    roe_pos_frac = (sum(1 for v in roe_h if v > 0) / len(roe_h)
                    if roe_h else np.nan)

    # ── Basic TTM flags ───────────────────────────────────────────────────
    has_pos_eps = not np.isnan(eps_ttm) and eps_ttm > 0
    has_pos_ni  = not np.isnan(ni_ttm)  and ni_ttm  > 0
    has_rev     = not np.isnan(rev_ttm) and rev_ttm > 0
    has_pos_bps = not np.isnan(bps_ttm) and bps_ttm > 0
    has_pos_roe = not np.isnan(roe_ttm) and roe_ttm > 0
    has_div     = not np.isnan(dps_ttm) and dps_ttm > 0
    has_pos_fcf = not np.isnan(fcf_ttm) and fcf_ttm > 0
    neg_eq      = not np.isnan(eq_ttm)  and eq_ttm  < 0
    high_debt   = (ltd_ttm / eq_ttm > 2.0) if (not np.isnan(ltd_ttm)
                   and not np.isnan(eq_ttm) and eq_ttm > 0) else False

    sector   = str(ci_info.get("sector",   "")).lower()
    industry = str(ci_info.get("industry", "")).lower()
    is_financial = (any(s in sector   for s in ["financial", "bank", "insurance"]) or
                    any(s in industry for s in ["bank", "insurance", "reit"]))

    results = []

    # ══════════════════════════════════════════════════════════════════════════
    # 1. Simple EPS Growth
    # Model projektuje EPS jako exponenciální křivku → klíčová je konzistence
    # trendu EPS. Měřeno R² lineárního trendu (log nelze — EPS může být záporné).
    # ══════════════════════════════════════════════════════════════════════════
    r = {"model": "Simple EPS Growth", "reasons": [], "warnings": []}
    score = 0

    if not has_pos_eps:
        r["warnings"].append("Záporné TTM EPS — terminální cena EPS×P/E bude záporná")
        r["rating"] = "❌ Nevhodný"
        results.append(r)
    else:
        r["reasons"].append("Kladné TTM EPS")
        score += 1

        # Klíčová metrika: R² lineárního trendu EPS
        if not np.isnan(eps_r2):
            if eps_r2 >= 0.85:
                r["reasons"].append(f"Silný trend EPS (R² = {eps_r2:.2f}) — spolehlivá extrapolace")
                score += 4
            elif eps_r2 >= 0.65:
                r["reasons"].append(f"Střední trend EPS (R² = {eps_r2:.2f})")
                score += 2
            elif eps_r2 >= 0.4:
                r["warnings"].append(f"Slabý trend EPS (R² = {eps_r2:.2f}) — extrapolace méně spolehlivá")
            else:
                r["warnings"].append(f"EPS bez jasného trendu (R² = {eps_r2:.2f}) — model předpokládá hladký růst!")
                score -= 2
        else:
            r["warnings"].append("Málo historických EPS dat (< 3 roky)")

        # Doplněk: % kladných let
        if not np.isnan(eps_pos_frac) and eps_pos_frac < 0.7:
            r["warnings"].append(f"EPS záporné v {(1 - eps_pos_frac) * 100:.0f} % historických let")
            score -= 1

        if is_financial:
            r["warnings"].append("Finanční sektor — EPS nestabilní kvůli regulaci a účetním specifikům")
            score -= 1

        r["rating"] = ("✅ Vhodný"    if score >= 4 else
                       "⚠️ Podmíněně" if score >= 1 else "❌ Nevhodný")
        results.append(r)

    # ══════════════════════════════════════════════════════════════════════════
    # 2. Simple Revenue Growth
    # Model = Revenue × stabilní marže → EPS → P/E výstup
    # Klíčové: (a) trend tržeb R², (b) STABILITA MARŽE v pp (ne CV — ratio!)
    # ══════════════════════════════════════════════════════════════════════════
    r = {"model": "Simple Revenue Growth", "reasons": [], "warnings": []}
    score = 0

    if not has_rev:
        r["warnings"].append("Chybí tržby")
        r["rating"] = "❌ Nevhodný"
    else:
        r["reasons"].append("Kladné TTM tržby")
        score += 1

        if not has_pos_eps:
            r["warnings"].append("Záporné EPS — terminální cena (EPS×P/E) bude záporná")
            score -= 2

        # Trend tržeb (log-linear — Revenue vždy kladné)
        if not np.isnan(rev_r2):
            if rev_r2 >= 0.85:
                r["reasons"].append(f"Silný trend tržeb (R² = {rev_r2:.2f})")
                score += 3
            elif rev_r2 >= 0.65:
                r["reasons"].append(f"Střední trend tržeb (R² = {rev_r2:.2f})")
                score += 1
            else:
                r["warnings"].append(f"Tržby bez jasného trendu (R² = {rev_r2:.2f}) — zpochybňuje předpoklad růstu")
                score -= 1
        else:
            r["warnings"].append("Málo historických dat pro trend tržeb (< 3 roky)")

        # Konzistence tempa růstu (CV YoY — jen pro kladné série)
        if not np.isnan(rev_gcv):
            if rev_gcv < 0.3:
                r["reasons"].append(f"Konzistentní tempo růstu tržeb (CV YoY = {rev_gcv:.2f})")
                score += 1
            elif rev_gcv > 0.7:
                r["warnings"].append(f"Velmi proměnlivé tempo růstu tržeb (CV YoY = {rev_gcv:.2f})")

        # ★ Klíčová podmínka: stabilita marže v procentních bodech
        if not np.isnan(pm_std):
            if pm_std < 2.0:
                r["reasons"].append(f"Stabilní čistá marže (±{pm_std:.1f} pp) — základ modelu")
                score += 3
            elif pm_std < 5.0:
                r["warnings"].append(f"Střední volatilita marže (±{pm_std:.1f} pp) — projekce EPS méně spolehlivá")
                score += 1
            else:
                r["warnings"].append(f"Vysoká volatilita marže (±{pm_std:.1f} pp) — model předpokládá stabilní marži!")
                score -= 2
        elif len(pm_h) < 3:
            r["warnings"].append("Málo historických dat pro posouzení stability marže")

        if is_financial:
            r["warnings"].append("Finanční sektor — tržby mají jiný charakter (úrokové výnosy)")
            score -= 1

        r["rating"] = ("✅ Vhodný"    if score >= 5 else
                       "⚠️ Podmíněně" if score >= 1 else "❌ Nevhodný")
    results.append(r)

    # ══════════════════════════════════════════════════════════════════════════
    # 3. Damodaran FCFF DCF
    # Klíčové: konzistentní kladné FCF, stabilní FCF trend (R² linear)
    # ══════════════════════════════════════════════════════════════════════════
    r = {"model": "Damodaran FCFF DCF", "reasons": [], "warnings": []}
    score = 0

    if is_financial:
        r["warnings"].append("Finanční sektor — FCFF model nevhodný (jiná reinvestiční logika)")
        r["rating"] = "❌ Nevhodný"
    else:
        if has_pos_ni:
            r["reasons"].append("Kladný Net Income (NOPAT proxy)")
            score += 2
        else:
            r["warnings"].append("Záporný NI — NOPAT proxy selže")
            score -= 2

        # FCF trend R² (linear — FCF může být záporné)
        if not np.isnan(fcf_r2):
            if fcf_r2 >= 0.75:
                r["reasons"].append(f"Konzistentní FCF trend (R² = {fcf_r2:.2f})")
                score += 3
            elif fcf_r2 >= 0.5:
                r["warnings"].append(f"Střední konzistence FCF (R² = {fcf_r2:.2f})")
                score += 1
            else:
                r["warnings"].append(f"FCF bez jasného trendu (R² = {fcf_r2:.2f}) — DCF citlivý na tento vstup")
                score -= 1

        # % let s kladným FCF
        if not np.isnan(fcf_pos_frac):
            if fcf_pos_frac >= 0.8:
                r["reasons"].append(f"FCF kladné v {fcf_pos_frac * 100:.0f} % let")
                score += 2
            elif fcf_pos_frac >= 0.6:
                r["warnings"].append(f"FCF záporné v {(1 - fcf_pos_frac) * 100:.0f} % let")
            else:
                r["warnings"].append("FCF historicky převážně záporné — DCF model nespolehlivý")
                score -= 2
        elif has_pos_fcf:
            r["reasons"].append("Kladné TTM FCF")
            score += 1
        else:
            r["warnings"].append("Záporné TTM FCF")
            score -= 1

        if not np.isnan(fcf_m) and fcf_m > 5:
            r["reasons"].append(f"Solidní FCF marže ({fcf_m:.1f} %)")
            score += 1

        if neg_eq:
            r["warnings"].append("Záporný vlastní kapitál — EV→Equity bridge nefunkční")
            score -= 1
        if high_debt:
            r["warnings"].append("Vysoký dluh (D/E > 2) — zvýšená citlivost na WACC")

        r["rating"] = ("✅ Vhodný"    if score >= 5 else
                       "⚠️ Podmíněně" if score >= 1 else "❌ Nevhodný")
    results.append(r)

    # ══════════════════════════════════════════════════════════════════════════
    # 4. ROE model (Gladiš)
    # Přímý vzorec: EPS_t = BPS_{t-1} × ROE_t
    # Klíčové: stabilní ROE (std pp), kladný BPS, konzistentní trend BPS (R²)
    # Dividenda: přispívá ale NENÍ prerekvizita
    # ══════════════════════════════════════════════════════════════════════════
    r = {"model": "ROE model (Gladiš)", "reasons": [], "warnings": []}
    score = 0

    if neg_eq or not has_pos_bps:
        r["warnings"].append("Záporný BPS / vlastní kapitál — model nefunguje (EPS = BPS × ROE)")
        r["rating"] = "❌ Nevhodný"
    elif not has_pos_roe:
        r["warnings"].append("Záporné ROE → záporné modelové EPS v každém roce projekce")
        r["rating"] = "❌ Nevhodný"
    else:
        r["reasons"].append("Kladné BPS a ROE (základní prerekvizity)")
        score += 2

        # ★ Klíčová metrika: stabilita ROE v procentních bodech
        if not np.isnan(roe_std):
            if roe_std < 3.0:
                r["reasons"].append(f"Stabilní ROE (±{roe_std:.1f} pp) — klíčový vstup modelu")
                score += 4
            elif roe_std < 7.0:
                r["warnings"].append(f"Střední volatilita ROE (±{roe_std:.1f} pp)")
                score += 2
            else:
                r["warnings"].append(f"Vysoká volatilita ROE (±{roe_std:.1f} pp) — model silně citlivý")
                score -= 1
        else:
            r["warnings"].append("Málo historických ROE dat (< 3 roky)")

        # Konzistentní trend BPS (log-linear — BPS by mělo kompoundovat)
        if not np.isnan(bps_r2):
            if bps_r2 >= 0.85:
                r["reasons"].append(f"Konzistentní růst BPS (R² = {bps_r2:.2f})")
                score += 2
            elif bps_r2 >= 0.6:
                r["reasons"].append(f"Střední konzistence BPS (R² = {bps_r2:.2f})")
                score += 1
            else:
                r["warnings"].append(f"BPS bez jasného trendu (R² = {bps_r2:.2f})")

        # Dividenda: bonus, ne prerekvizita (terminální cena tvoří ~60–80 % IV)
        if has_div:
            r["reasons"].append(f"Vyplácí dividendu ({dps_ttm:.3f} $/akcii) — PV dividend > 0")
            score += 1
        else:
            r["warnings"].append("Nevyplácí dividendu — IV závisí jen na terminální ceně (EPS₁₀×P/E)")

        r["rating"] = ("✅ Vhodný"    if score >= 6 else
                       "⚠️ Podmíněně" if score >= 3 else "❌ Nevhodný")
    results.append(r)

    # ══════════════════════════════════════════════════════════════════════════
    # 5. Advanced Valuation (P/E + DCF)
    # Nejflexibilnější — hodnotíme dostupnost obou větví + trend tržeb
    # ══════════════════════════════════════════════════════════════════════════
    r = {"model": "Advanced Valuation", "reasons": [], "warnings": []}
    score = 0

    if not has_rev:
        r["warnings"].append("Chybí tržby")
        r["rating"] = "❌ Nevhodný"
    else:
        r["reasons"].append("Kladné tržby")
        score += 1

        if has_pos_ni:
            r["reasons"].append("Kladné NI — P/E větev dostupná")
            score += 2
        else:
            r["warnings"].append("Záporné NI — P/E FV bude N/A, dostupná jen DCF větev")

        if has_pos_fcf:
            r["reasons"].append("Kladné FCF — DCF větev dostupná")
            score += 2
        else:
            r["warnings"].append("Záporná FCF marže — DCF větev bude N/A nebo zkreslená")

        if not np.isnan(pm_std) and pm_std < 5.0:
            r["reasons"].append(f"Dostatečně stabilní marže (±{pm_std:.1f} pp)")
            score += 1
        elif not np.isnan(pm_std):
            r["warnings"].append(f"Volatilní marže (±{pm_std:.1f} pp) — implied FCF marže nespolehlivá")

        if not np.isnan(rev_r2) and rev_r2 >= 0.7:
            r["reasons"].append(f"Konzistentní trend tržeb (R² = {rev_r2:.2f})")
            score += 1

        if is_financial:
            r["warnings"].append("Finanční sektor — FCF marže má jiný charakter")

        r["rating"] = ("✅ Vhodný"    if score >= 5 else
                       "⚠️ Podmíněně" if score >= 2 else "❌ Nevhodný")
    results.append(r)

    return results


# ── Session-state init ────────────────────────────────────────────────────────

for _k, _v in {
    "val_ticker":       "GOOGL",
    "val_years":        10,
    "val_api_df":       pd.DataFrame(),
    "val_manual_df":    pd.DataFrame(),
    "val_loaded":       False,
    "roe_manual_df":    pd.DataFrame(),
    "roe_params":       {},
}.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


# ── Import ze souboru ────────────────────────────────────────────────────────

with st.expander("📂 Import ze souboru", expanded=False):
    _up_file = st.file_uploader(
        "Vyberte snapshot (.xlsx)",
        type=["xlsx"],
        key="val_import_uploader",
        label_visibility="collapsed",
    )
    if _up_file is not None:
        if st.button("📥 Importovat ze souboru", key="val_import_file_btn"):
            try:
                _xl = pd.ExcelFile(BytesIO(_up_file.read()), engine="openpyxl")
                _sheets = _xl.sheet_names
                # read meta for ticker
                _imp_meta = {}
                if "Meta" in _sheets:
                    _meta_df = _xl.parse("Meta")
                    if not _meta_df.empty:
                        _imp_meta = _meta_df.to_dict(orient="records")[0]
                _imp_ticker = str(_imp_meta.get("ticker", st.session_state.val_ticker)).upper().strip()
                # load effective as api baseline (no API call needed)
                if "Inputs_effective" in _sheets:
                    _imp_eff = _xl.parse("Inputs_effective", index_col=0)
                    st.session_state.val_api_df   = _imp_eff
                    st.session_state.val_manual_df = pd.DataFrame()
                    st.session_state.val_ticker    = _imp_ticker
                    st.session_state.val_loaded    = True
                    # Sync widget key so ticker_changed = False on next render
                    st.session_state["val_ticker_input_widget"] = _imp_ticker
                # restore scenarios if available
                if "Scenario_inputs" in _sheets:
                    _si = _xl.parse("Scenario_inputs")
                    _new_sc = {}
                    for _, _row in _si.iterrows():
                        _sn = str(_row.get("scenario", ""))
                        if _sn in ["Low", "Mid", "High"]:
                            _new_sc[_sn] = {
                                "roic": float(_row.get("roic", 0)),
                                "g":    float(_row.get("g",    0)),
                                "op":   float(_row.get("op",   0)),
                                "r":    float(_row.get("r",    10)),
                                "pe":   float(_row.get("pe",   15)),
                                "pfcf": float(_row.get("pfcf", 12)),
                                "n":    int(_row.get("n",      10)),
                                "dg":   float(_row.get("dg",   0.0)),
                                "override": bool(_row.get("override", False)),
                                "fcf_ovr": float(_row.get("fcf_ovr", 0.0)),
                            }
                    if _new_sc:
                        st.session_state["scenarios"] = _new_sc
                    _tax_imp = _si["tax_rate"].iloc[0] if "tax_rate" in _si.columns else None
                    if _tax_imp is not None and not pd.isna(_tax_imp):
                        st.session_state["sc_tax_rate_pct"] = float(_tax_imp)
                    _div_tax_imp = _si["div_tax_rate"].iloc[0] if "div_tax_rate" in _si.columns else None
                    if _div_tax_imp is not None and not pd.isna(_div_tax_imp):
                        st.session_state["sc_div_tax_pct"] = float(_div_tax_imp)
                    _term_mode_imp = _si["terminal_mode"].iloc[0] if "terminal_mode" in _si.columns else None
                    if _term_mode_imp is not None and str(_term_mode_imp).strip() not in ("", "nan", "NaN"):
                        st.session_state["sc_terminal_mode"] = str(_term_mode_imp)
                    _g_term_imp = _si["g_terminal"].iloc[0] if "g_terminal" in _si.columns else None
                    if _g_term_imp is not None and not pd.isna(_g_term_imp):
                        st.session_state["sc_g_terminal_pct"] = float(_g_term_imp)
                st.success(f"Importováno: **{_up_file.name}** (ticker: {_imp_ticker})")
                st.rerun()
            except Exception as _exc:
                st.error(f"Import selhal: {_exc}")

# ── Controls ──────────────────────────────────────────────────────────────────

v_c1, v_c2, v_c3, v_c4 = st.columns([3, 2, 2, 2])
with v_c1:
    # Hodnotu řídíme výhradně přes session state key – nikoli přes value=, aby
    # nekonfliktovalo s přímým zápisem st.session_state["val_ticker_input_widget"]
    # při importu snapshotu (Streamlit warning: widget created with default value
    # but also set via Session State API).
    if "val_ticker_input_widget" not in st.session_state:
        st.session_state["val_ticker_input_widget"] = st.session_state.val_ticker
    val_ticker_input = st.text_input(
        "Ticker (Valuace)",
        label_visibility="collapsed",
        placeholder="GOOGL",
        key="val_ticker_input_widget",
    ).upper().strip()

with v_c2:
    val_years_input = st.selectbox(
        "Počet let",
        options=[5, 7, 10, 15],
        index=[5, 7, 10, 15].index(st.session_state.val_years) if st.session_state.val_years in [5, 7, 10, 15] else 2,
        label_visibility="collapsed",
        key="val_years_select",
    )

with v_c3:
    val_analyze_btn = st.button("Analyzovat", width="stretch", key="val_analyze_btn")

with v_c4:
    # Show "Doplnit z API" only when data is already loaded (e.g. after import)
    _has_existing_data = st.session_state.val_loaded and not st.session_state.val_api_df.empty
    val_fill_btn = st.button(
        "🔄 Doplnit z API",
        width="stretch",
        key="val_fill_api_btn",
        disabled=not _has_existing_data,
        help="Doplní chybějící roky z yfinance API. Existující data zůstanou nedotčena, TTM se vždy aktualizuje.",
    )

# ── Reload from API + ticker/years change detection ───────────────────────────

ticker_changed = val_ticker_input != st.session_state.val_ticker
years_changed  = val_years_input  != st.session_state.val_years

if (val_analyze_btn or ticker_changed or years_changed) and not val_fill_btn:
    st.session_state.val_ticker = val_ticker_input
    st.session_state.val_years  = val_years_input

    with st.spinner(f"Načítám data pro {val_ticker_input}…"):
        new_api = fetch_valuation_api_data(val_ticker_input, val_years_input)

    if ticker_changed:
        # reset manual overrides when ticker changes
        st.session_state.val_manual_df = pd.DataFrame()
        st.session_state["roe_manual_df"] = pd.DataFrame()
        st.session_state["roe_params"]   = {}

    st.session_state.val_api_df   = new_api
    st.session_state.val_loaded   = True

# ── "Doplnit z API" – merge fresh API data into existing table ────────────────

if val_fill_btn and _has_existing_data:
    st.session_state.val_ticker = val_ticker_input
    st.session_state.val_years  = val_years_input

    with st.spinner(f"Doplňuji chybějící data z API pro {val_ticker_input}…"):
        fetch_valuation_api_data.clear()
        fresh_api = fetch_valuation_api_data(val_ticker_input, val_years_input)

    existing = st.session_state.val_api_df.copy()

    if not fresh_api.empty:
        # 1) Always replace TTM with fresh data
        if "TTM" in fresh_api.index:
            existing.loc["TTM"] = fresh_api.loc["TTM"]

        # 2) For annual rows: only fill NaN cells, keep existing values
        filled_cells = 0
        added_years = []
        for yr in fresh_api.index:
            if yr == "TTM":
                continue
            if yr not in existing.index:
                # Entirely new year → add whole row
                existing.loc[yr] = fresh_api.loc[yr]
                added_years.append(yr)
            else:
                # Existing year → fill only NaN cells
                for col in fresh_api.columns:
                    if col in existing.columns:
                        existing_val = existing.loc[yr, col]
                        fresh_val = fresh_api.loc[yr, col]
                        if pd.isna(existing_val) and not pd.isna(fresh_val):
                            existing.loc[yr, col] = fresh_val
                            filled_cells += 1

        # 3) Re-sort: TTM first, then years descending
        year_keys = sorted([k for k in existing.index if k != "TTM"], reverse=True)
        order = (["TTM"] if "TTM" in existing.index else []) + year_keys
        existing = existing.loc[order]

        st.session_state.val_api_df = existing

        # Summary message
        parts = []
        if added_years:
            parts.append(f"přidáno {len(added_years)} {'rok' if len(added_years) == 1 else 'roků'}: {', '.join(sorted(added_years))}")
        if filled_cells > 0:
            parts.append(f"doplněno {filled_cells} chybějících buněk")
        parts.append("TTM aktualizován")
        st.success("🔄 " + "; ".join(parts) + ".")
    else:
        st.warning("API nevrátilo žádná data.")
    st.rerun()

# ── Main Valuace UI ───────────────────────────────────────────────────────────

if not st.session_state.val_loaded or st.session_state.val_api_df.empty:
    st.info("Zadej ticker a klikni **Analyzovat**.")
else:
    api_df    = st.session_state.val_api_df
    manual_df = st.session_state.val_manual_df

    effective_df, override_mask = merge_api_and_manual(api_df, manual_df)

    # ── Informace o firmě ──────────────────────────────────────────────────
    with st.expander("🏢 Informace o firmě", expanded=False):
        _ci_ticker = st.session_state.val_ticker
        with st.spinner("Načítám informace o firmě…"):
            _ci = fetch_company_info(_ci_ticker)
        _info = _ci["info"]

        _ci_tabs = st.tabs([
            "📋 O firmě",
            "🎯 Odhady analytiků",
            "📅 Earnings",
            "💧 Sankey",
            "📰 Zprávy",
            "🏦 Vlastnictví",
        ])

        # ── Tab 0: O firmě ────────────────────────────────────────────────
        with _ci_tabs[0]:
            _long_name = _info.get("longName", _ci_ticker)
            _sector    = _info.get("sector", "—")
            _industry  = _info.get("industry", "—")
            _country   = _info.get("country", "—")
            _website   = _info.get("website", "")
            _employees = _info.get("fullTimeEmployees")
            _summary   = _info.get("longBusinessSummary", "")

            _meta_col1, _meta_col2 = st.columns([2, 1])
            with _meta_col1:
                st.markdown(f"### {_long_name}")
                if _summary:
                    st.caption(_summary)
            with _meta_col2:
                st.markdown(
                    f"**Sektor:** {_sector}  \n"
                    f"**Odvětví:** {_industry}  \n"
                    f"**Země:** {_country}  \n"
                    + (f"**Zaměstnanci:** {_employees:,}  \n" if _employees else "")
                    + (f"**Web:** [{_website}]({_website})" if _website else ""),
                    unsafe_allow_html=False,
                )

            # Governance risk scores
            # yfinance scale: 1 = highest risk (worst), 10 = lowest risk (best)
            _audit   = _info.get("auditRisk")
            _board   = _info.get("boardRisk")
            _comp    = _info.get("compensationRisk")
            _shr     = _info.get("shareHolderRightsRisk")
            _overall = _info.get("overallRisk")
            _risk_vals = [x for x in [_audit, _board, _comp, _shr, _overall] if x is not None]
            if _risk_vals:
                st.markdown("**Governance rizika** *(skóre 1–10: vyšší = nižší riziko = lepší)*")
                _r_cols = st.columns(5)
                for _rc, (_rl, _rv) in zip(_r_cols, [
                    ("Audit", _audit), ("Board", _board),
                    ("Odměny", _comp), ("Práva akcionářů", _shr), ("Celkové", _overall),
                ]):
                    with _rc:
                        if _rv is not None:
                            # Higher score = lower risk = green
                            _rcolor = "#66BB6A" if _rv >= 7 else ("#FFD54F" if _rv >= 4 else "#FF7043")
                            st.markdown(
                                f"<div style='text-align:center'>"
                                f"<div style='font-size:11px;color:#93a3b8'>{_rl}</div>"
                                f"<div style='font-size:22px;font-weight:700;color:{_rcolor}'>{_rv}</div>"
                                f"</div>",
                                unsafe_allow_html=True,
                            )

        # ── Tab 1: Odhady analytiků ───────────────────────────────────────
        with _ci_tabs[1]:
            _target_mean = _info.get("targetMeanPrice")
            _target_high = _info.get("targetHighPrice")
            _target_low  = _info.get("targetLowPrice")
            _rec_mean    = _info.get("recommendationMean")
            _n_analysts  = _info.get("numberOfAnalystOpinions")
            _rec_key     = _info.get("recommendationKey", "")
            _curr_price  = _info.get("currentPrice") or _info.get("regularMarketPrice")

            _an_col1, _an_col2 = st.columns([1, 1])
            with _an_col1:
                st.markdown("**Price targety analytiků**")
                if _target_mean is not None:
                    _updown = ""
                    if _curr_price and _curr_price > 0:
                        _pct = (_target_mean / _curr_price - 1) * 100
                        _updown = f"  ({'+' if _pct >= 0 else ''}{_pct:.1f}% vs. aktuální cena)"
                    _th_str = f"${float(_target_high):.2f}" if _target_high is not None else "—"
                    _tl_str = f"${float(_target_low):.2f}"  if _target_low  is not None else "—"
                    _cp_str = f"${float(_curr_price):.2f}"  if _curr_price  is not None else ""
                    _lines  = (
                        f"- **Průměrný target (12 měs.):** ${float(_target_mean):.2f}{_updown}  \n"
                        f"- **Nejvyšší target:** {_th_str}  \n"
                        f"- **Nejnižší target:** {_tl_str}  \n"
                    )
                    if _cp_str:
                        _lines += f"- **Aktuální cena:** {_cp_str}  \n"
                    if _n_analysts:
                        _lines += f"- **Počet analytiků:** {_n_analysts}  \n"
                    if _rec_mean:
                        _lines += f"- **Konsensus:** {_rec_key.upper()}  ({float(_rec_mean):.1f}/5)  \n"
                    st.caption("Targety jsou 12měsíční konsensus odhady analytiků.")
                    st.markdown(_lines)
                else:
                    st.info("Odhady ceny nejsou dostupné.")

            with _an_col2:
                # Consensus gauge: 1=Strong Buy … 5=Strong Sell
                if _rec_mean is not None:
                    try:
                        import plotly.graph_objects as go
                        _gauge_labels = ["Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"]
                        _gauge_colors = ["#66BB6A", "#A5D6A7", "#FFD54F", "#FF8A65", "#FF7043"]
                        # Clamp to 1-5
                        _rm = max(1.0, min(5.0, float(_rec_mean)))
                        _gi = min(int(_rm) - 1, 4)
                        _gfig = go.Figure(go.Indicator(
                            mode="gauge+number",
                            value=_rm,
                            number={"font": {"color": "#cdd6e3"}, "valueformat": ".2f"},
                            gauge={
                                "axis": {"range": [1, 5], "tickvals": [1,2,3,4,5],
                                         "ticktext": _gauge_labels,
                                         "tickfont": {"size": 9, "color": "#93a3b8"}},
                                "bar": {"color": _gauge_colors[_gi]},
                                "bgcolor": "rgba(0,0,0,0)",
                                "borderwidth": 0,
                                "steps": [
                                    {"range": [1, 2], "color": "rgba(102,187,106,0.15)"},
                                    {"range": [2, 3], "color": "rgba(165,214,167,0.15)"},
                                    {"range": [3, 4], "color": "rgba(255,213,79,0.15)"},
                                    {"range": [4, 5], "color": "rgba(255,112,78,0.15)"},
                                ],
                            },
                            title={"text": "Konsensus analytiků", "font": {"color": "#cdd6e3", "size": 12}},
                        ))
                        _gfig.update_layout(
                            height=200,
                            margin=dict(l=20, r=20, t=40, b=10),
                            paper_bgcolor="rgba(0,0,0,0)",
                            font=dict(color="#cdd6e3"),
                        )
                        st.plotly_chart(_gfig, use_container_width=True)
                    except Exception:
                        st.write(f"Konsensus: {_rec_key.upper()} ({_rec_mean:.1f}/5)")

            # EPS & Revenue estimates
            _ee = _ci["earnings_estimate"]
            _re = _ci["revenue_estimate"]
            _eh = _ci["earnings_history"]

            # ── helper: translate period codes to Q1 2026 / Y2027 style ──
            import re as _re_mod, datetime as _dt
            def _period_label(code: str) -> str:
                today = _dt.date.today()
                cur_y = today.year
                cur_cal_q = (today.month - 1) // 3 + 1  # calendar Q (1-4)
                # Yahoo "0q" = most recently *completed* quarter = calendar Q - 1
                base_q = cur_cal_q - 1
                base_y = cur_y
                if base_q < 1:
                    base_q += 4
                    base_y -= 1
                m = _re_mod.match(r'^([+-]?\d*)([qy])$', str(code))
                if not m:
                    return str(code)
                raw, unit = m.group(1), m.group(2)
                offset = int(raw) if raw not in ('', '+') else 0
                if unit == 'q':
                    total_q = base_y * 4 + (base_q - 1) + offset
                    return f"Q{total_q % 4 + 1} {total_q // 4}"
                else:
                    return f"Y{cur_y + offset}"
            _EE_COLS = {
                "avg":             "Průměr EPS",
                "low":             "Minimum EPS",
                "high":            "Maximum EPS",
                "yearAgoEps":      "EPS loni",
                "numberOfAnalysts":"Počet analytiků",
                "growth":          "Odh. růst (%)",
            }
            _RE_COLS = {
                "avg":             "Průměr Revenue",
                "low":             "Minimum Revenue",
                "high":            "Maximum Revenue",
                "yearAgoRevenue":  "Revenue loni",
                "numberOfAnalysts":"Počet analytiků",
                "growth":          "Odh. růst (%)",
            }

            if _ee is not None and not getattr(_ee, "empty", True):
                st.markdown("**EPS odhady analytiků**")
                _ee_disp = _ee.copy()
                # Rename index (period codes) to Q2 2026 / Y2027 style
                _ee_disp.index = [_period_label(i) for i in _ee_disp.index]
                _ee_disp.index.name = "Období"
                # Rename columns
                _ee_disp.columns = [_EE_COLS.get(str(c), str(c)) for c in _ee_disp.columns]
                # Convert growth to %
                if "Odh. růst (%)" in _ee_disp.columns:
                    _ee_disp["Odh. růst (%)"] = pd.to_numeric(_ee_disp["Odh. růst (%)"], errors="coerce") * 100
                st.dataframe(_ee_disp.reset_index(), use_container_width=True, hide_index=True)

            if _re is not None and not getattr(_re, "empty", True):
                st.markdown("**Revenue odhady analytiků** *(v miliardách USD)*")
                _re_disp = _re.copy()
                _re_disp.index = [_period_label(i) for i in _re_disp.index]
                _re_disp.index.name = "Období"
                _re_disp.columns = [_RE_COLS.get(str(c), str(c)) for c in _re_disp.columns]
                # Scale revenue columns to billions
                for _rc2 in ["Průměr Revenue", "Minimum Revenue", "Maximum Revenue", "Revenue loni"]:
                    if _rc2 in _re_disp.columns:
                        _re_disp[_rc2] = pd.to_numeric(_re_disp[_rc2], errors="coerce") / 1e9
                if "Odh. růst (%)" in _re_disp.columns:
                    _re_disp["Odh. růst (%)"] = pd.to_numeric(_re_disp["Odh. růst (%)"], errors="coerce") * 100
                st.dataframe(_re_disp.reset_index(), use_container_width=True, hide_index=True)

            if _eh is not None and not getattr(_eh, "empty", True):
                st.markdown("**Historické EPS surprises**")
                _eh_disp = _eh.reset_index().copy()
                # Rename columns
                _EH_COLS = {
                    "quarter":         "Čtvrtletí",
                    "epsActual":        "EPS skutečný",
                    "epsEstimate":      "EPS odhad",
                    "epsDifference":    "Rozdíl EPS",
                    "surprisePercent":  "Překvapení (%)",
                }
                _eh_disp.columns = [_EH_COLS.get(str(c), str(c)) for c in _eh_disp.columns]
                # Convert date to QX YYYY label
                if "Čtvrtletí" in _eh_disp.columns:
                    def _date_to_q(d):
                        try:
                            dt = pd.to_datetime(d, errors="coerce")
                            if pd.isna(dt):
                                return str(d)
                            return f"Q{(dt.month - 1) // 3 + 1} {dt.year}"
                        except Exception:
                            return str(d)
                    _eh_disp["Čtvrtletí"] = _eh_disp["Čtvrtletí"].apply(_date_to_q)
                # Surprise to %
                if "Překvapení (%)" in _eh_disp.columns:
                    _eh_disp["Překvapení (%)"] = pd.to_numeric(_eh_disp["Překvapení (%)"], errors="coerce") * 100
                # Ensure Čtvrtletí is first column
                _eh_cols_ordered = (["Čtvrtletí"] if "Čtvrtletí" in _eh_disp.columns else []) + \
                                   [c for c in _eh_disp.columns if c != "Čtvrtletí"]
                st.dataframe(_eh_disp[_eh_cols_ordered], use_container_width=True, hide_index=True)

        # ── Tab 2: Earnings ───────────────────────────────────────────────
        with _ci_tabs[2]:
            _cal = _ci["calendar"]
            if _cal is not None:
                # calendar is a dict or DataFrame depending on yfinance version
                if isinstance(_cal, dict):
                    _earn_date = _cal.get("Earnings Date")
                    _earn_avg  = _cal.get("Earnings Average")
                    _earn_low  = _cal.get("Earnings Low")
                    _earn_high = _cal.get("Earnings High")
                    _rev_avg   = _cal.get("Revenue Average")
                    _rev_low   = _cal.get("Revenue Low")
                    _rev_high  = _cal.get("Revenue High")

                    if _earn_date:
                        _dates = _earn_date if isinstance(_earn_date, list) else [_earn_date]
                        _dates_str = " – ".join(str(d)[:10] for d in _dates)
                        st.markdown(f"**Příští Earnings:** {_dates_str}")
                    _e_col1, _e_col2 = st.columns(2)
                    with _e_col1:
                        if _earn_avg is not None:
                            st.metric("EPS odhad (průměr)", f"${float(_earn_avg):.2f}",
                                      delta=None)
                        if _earn_low is not None and _earn_high is not None:
                            st.caption(f"Rozsah EPS: ${float(_earn_low):.2f} – ${float(_earn_high):.2f}")
                    with _e_col2:
                        if _rev_avg is not None:
                            _rv_b = float(_rev_avg) / 1e9
                            st.metric("Revenue odhad (průměr)", f"${_rv_b:.2f} B")
                        if _rev_low is not None and _rev_high is not None:
                            st.caption(f"Rozsah Revenue: ${float(_rev_low)/1e9:.2f} B – ${float(_rev_high)/1e9:.2f} B")
                elif hasattr(_cal, "to_dict"):
                    # DataFrame format
                    st.dataframe(_cal, use_container_width=True)
                else:
                    st.write(_cal)
            else:
                st.info("Datum earnings není k dispozici.")

            # Last earnings surprises from history
            _eh2 = _ci["earnings_history"]
            if _eh2 is not None and not getattr(_eh2, "empty", True):
                st.markdown("**Poslední EPS surprises**")
                _eh2_disp = (_eh2.tail(4) if len(_eh2) > 4 else _eh2).copy()
                _EH_COLS2 = {
                    "quarter":        "Čtvrtletí",
                    "epsActual":      "EPS skutečný",
                    "epsEstimate":    "EPS odhad",
                    "epsDifference":  "Rozdíl EPS",
                    "surprisePercent":"Překvapení (%)",
                }
                _eh2_disp.columns = [_EH_COLS2.get(str(c), str(c)) for c in _eh2_disp.columns]
                if "Čtvrtletí" in _eh2_disp.columns:
                    _eh2_disp["Čtvrtletí"] = pd.to_datetime(_eh2_disp["Čtvrtletí"], errors="coerce").dt.strftime("%d.%m.%Y")
                if "Překvapení (%)" in _eh2_disp.columns:
                    _eh2_disp["Překvapení (%)"] = pd.to_numeric(_eh2_disp["Překvapení (%)"], errors="coerce") * 100
                st.dataframe(_eh2_disp, use_container_width=True, hide_index=True)

        # ── Tab 3: Sankey ─────────────────────────────────────────────────
        with _ci_tabs[3]:
            _sankey_fig, _sankey_err = _build_income_sankey(_ci["income_stmt"], _ci_ticker)
            if _sankey_fig is not None:
                st.plotly_chart(_sankey_fig, use_container_width=True)
                st.caption(
                    "Zdroj: yfinance income statement (nejnovější dostupný rok / TTM). "
                    "Hodnoty v miliardách USD. Segment breakdown není k dispozici přes yfinance."
                )
            else:
                st.info(f"Sankey diagram není dostupný. Příčina: {_sankey_err or 'neznámá'}")
                if _ci["income_stmt"] is not None and not _ci["income_stmt"].empty:
                    with st.expander("🔍 Diagnostika — dostupné řádky income_stmt"):
                        st.write(list(_ci["income_stmt"].index))

        # ── Tab 4: Zprávy ─────────────────────────────────────────────────
        with _ci_tabs[4]:
            _news = _ci["news"]
            if _news:
                _shown = 0
                for _n in _news:
                    if _shown >= 5:
                        break
                    try:
                        # yfinance news item structure
                        _content = _n.get("content", {}) if isinstance(_n, dict) else {}
                        _title = (
                            _content.get("title")
                            or (_n.get("title") if isinstance(_n, dict) else None)
                            or "Bez názvu"
                        )
                        # URL: try nested content.clickThroughUrl, then content.canonicalUrl, then direct
                        _url = (
                            (_content.get("clickThroughUrl") or {}).get("url")
                            or (_content.get("canonicalUrl") or {}).get("url")
                            or (_n.get("link") if isinstance(_n, dict) else None)
                            or (_n.get("url") if isinstance(_n, dict) else None)
                            or ""
                        )
                        # Publisher
                        _provider = (
                            (_content.get("provider") or {}).get("displayName")
                            or _n.get("publisher", "")
                            if isinstance(_n, dict) else ""
                        )
                        # Published time
                        _pub_time = (
                            _content.get("pubDate")
                            or _content.get("displayTime")
                            or (_n.get("providerPublishTime") if isinstance(_n, dict) else None)
                        )
                        _pub_str = ""
                        if _pub_time:
                            try:
                                if isinstance(_pub_time, (int, float)):
                                    _pub_str = datetime.fromtimestamp(int(_pub_time)).strftime("%d.%m.%Y")
                                else:
                                    _pub_str = str(_pub_time)[:10]
                            except Exception:
                                _pub_str = str(_pub_time)[:10]

                        _meta_parts = [x for x in [_provider, _pub_str] if x]
                        _meta_str   = "  ·  ".join(_meta_parts)

                        if _url:
                            st.markdown(f"**[{_title}]({_url})**")
                        else:
                            st.markdown(f"**{_title}**")
                        if _meta_str:
                            st.caption(_meta_str)
                        st.markdown("---")
                        _shown += 1
                    except Exception:
                        continue
                if _shown == 0:
                    st.info("Zprávy nejsou k dispozici.")
            else:
                st.info("Zprávy nejsou k dispozici.")

        # ── Tab 5: Vlastnictví ────────────────────────────────────────────
        with _ci_tabs[5]:
            _mh = _ci["major_holders"]
            _ih = _ci["institutional_holders"]

            _own_col1, _own_col2 = st.columns([1, 2])
            with _own_col1:
                st.markdown("**Přehled vlastnictví**")
                if _mh is not None and not getattr(_mh, "empty", True):
                    try:
                        # yfinance major_holders: either (Value, Breakdown) cols
                        # or description as index. Normalize to rows list.
                        _mh_rows = []
                        _mh_df = _mh.reset_index()
                        _mh_cols = list(_mh_df.columns)
                        # Find value col (numeric) and desc col (string)
                        _val_col, _desc_col = None, None
                        for _c in _mh_cols:
                            _sample = _mh_df[_c].dropna()
                            if len(_sample) == 0:
                                continue
                            try:
                                pd.to_numeric(_sample)
                                if _val_col is None:
                                    _val_col = _c
                            except (ValueError, TypeError):
                                if _desc_col is None:
                                    _desc_col = _c
                        if _val_col and _desc_col:
                            _MH_LABELS = {
                                "insidersPercentHeld":       "Insideři (% akcií)",
                                "institutionsPercentHeld":   "Instituce (% akcií)",
                                "institutionsFloatPercentHeld": "Instituce (% floatu)",
                                "institutionsCount":         "Počet institucí",
                                "insiderPercent":            "Insiderři (% akcií)",
                                "institutionPercent":        "Instituce (% akcií)",
                            }
                            for _, _row in _mh_df.iterrows():
                                _raw_val = _row[_val_col]
                                _raw_desc = str(_row[_desc_col])
                                _desc = _MH_LABELS.get(_raw_desc, _raw_desc)
                                try:
                                    _fval = float(_raw_val)
                                    _fmt  = f"{_fval*100:.2f}%" if _fval < 2 else f"{int(_fval):,}"
                                except Exception:
                                    _fmt = str(_raw_val)
                                _mh_rows.append({"Popis": _desc, "Hodnota": _fmt})
                            st.dataframe(pd.DataFrame(_mh_rows), use_container_width=True, hide_index=True)
                        else:
                            st.dataframe(_mh_df, use_container_width=True, hide_index=True)
                    except Exception:
                        st.dataframe(_mh, use_container_width=True)
                else:
                    _ins_pct  = _info.get("institutionsPercentHeld") or _info.get("institutionPercent")
                    _ins_pct2 = _info.get("insidersPercentHeld") or _info.get("insiderPercent")
                    _short_r  = _info.get("shortRatio")
                    _short_f  = _info.get("shortPercentOfFloat")
                    for _lbl, _val in [
                        ("Instituce", f"{float(_ins_pct)*100:.1f}%" if _ins_pct else "—"),
                        ("Insideři", f"{float(_ins_pct2)*100:.1f}%" if _ins_pct2 else "—"),
                        ("Short ratio", f"{float(_short_r):.2f}" if _short_r else "—"),
                        ("Short % float", f"{float(_short_f)*100:.1f}%" if _short_f else "—"),
                    ]:
                        st.markdown(f"**{_lbl}:** {_val}")

            with _own_col2:
                st.markdown("**Top institucionální akcionáři**")
                if _ih is not None and not getattr(_ih, "empty", True):
                    _ih_show = _ih.head(10).copy().reset_index(drop=True)
                    # Translate known column names
                    _IH_COLS = {
                        "Holder":        "Akcionář",
                        "Shares":        "Počet akcií",
                        "Date Reported": "Datum",
                        "% Out":         "Podíl (%)",
                        "Value":         "Hodnota (USD)",
                        "pctHeld":       "Podíl (%)",
                        "shares":        "Počet akcií",
                        "value":         "Hodnota (USD)",
                        "pctChange":     "Změna pozice",
                    }
                    _ih_show.columns = [_IH_COLS.get(str(c), str(c)) for c in _ih_show.columns]
                    # Format date column — keep only date part
                    if "Datum" in _ih_show.columns:
                        _ih_show["Datum"] = pd.to_datetime(_ih_show["Datum"], errors="coerce").dt.strftime("%d.%m.%Y")
                    # Format share count with thousands separator
                    if "Počet akcií" in _ih_show.columns:
                        _ih_show["Počet akcií"] = pd.to_numeric(_ih_show["Počet akcií"], errors="coerce").apply(
                            lambda x: f"{int(x):,}" if pd.notna(x) else "—"
                        )
                    # Podíl — if < 2 it's a fraction, multiply to %
                    if "Podíl (%)" in _ih_show.columns:
                        _ih_show["Podíl (%)"] = pd.to_numeric(_ih_show["Podíl (%)"], errors="coerce").apply(
                            lambda x: f"{x*100:.2f}%" if (pd.notna(x) and x < 2) else (f"{x:.2f}%" if pd.notna(x) else "—")
                        )
                    # Format monetary value
                    if "Hodnota (USD)" in _ih_show.columns:
                        _ih_show["Hodnota (USD)"] = pd.to_numeric(_ih_show["Hodnota (USD)"], errors="coerce").apply(
                            lambda x: f"${x/1e9:.2f} B" if (pd.notna(x) and x >= 1e9) else (f"${x/1e6:.1f} M" if pd.notna(x) else "—")
                        )
                    # Format pctChange as percentage
                    if "Změna pozice" in _ih_show.columns:
                        _ih_show["Změna pozice"] = pd.to_numeric(_ih_show["Změna pozice"], errors="coerce").apply(
                            lambda x: f"{x*100:+.2f}%" if (pd.notna(x) and abs(x) < 10) else (f"{x:+.2f}%" if pd.notna(x) else "—")
                        )
                    st.dataframe(_ih_show, use_container_width=True, hide_index=True)
                else:
                    st.info("Data o institucionálních akcionářích nejsou k dispozici.")

    # ── Upper table: st.data_editor ──────────────────────────────────────
    st.markdown("**Tabulka valuace (editovatelná):**")
    st.markdown(
        """
        <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:2px 0 8px 0;font-size:12px;color:#93a3b8;">
            <span style="font-weight:600;">Legenda vstupů:</span>
            <span style="display:inline-flex;align-items:center;gap:4px;"><svg width="12" height="12"><circle cx="6" cy="6" r="6" fill="#f5c518"/></svg> P/E fair value</span>
            <span style="display:inline-flex;align-items:center;gap:4px;"><svg width="12" height="12"><circle cx="6" cy="6" r="6" fill="#3b82f6"/></svg> Equity DCF Fair Value</span>
            <span style="display:inline-flex;align-items:center;gap:4px;"><svg width="12" height="12"><circle cx="6" cy="6" r="6" fill="#a855f7"/></svg> ROE model Dan Gladiš</span>
            <span style="display:inline-flex;align-items:center;gap:4px;"><svg width="12" height="12"><circle cx="6" cy="6" r="6" fill="#f97316"/></svg> Simple EPS / Revenue Growth</span>
            <span style="display:inline-flex;align-items:center;gap:4px;"><svg width="12" height="12"><circle cx="6" cy="6" r="6" fill="#ef4444"/></svg> Simple Valuation (Damodaran-style)</span>
            <span style="display:inline-flex;align-items:center;gap:4px;"><svg width="12" height="12"><circle cx="6" cy="6" r="6" fill="#22c55e"/></svg> Všechny modely</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Always feed api_df as the editor base — the data_editor key persists user edits.
    # Feeding effective_df would reset the editor state every rerun and cause flicker.
    editor_init = api_df.reset_index()  # 'Year' becomes a column
    # Dividend Yield is stored as decimal (0.02) but displayed as percent (2.00%)
    if "Dividend Yield" in editor_init.columns:
        editor_init["Dividend Yield"] = editor_init["Dividend Yield"] * 100

    # ── Column grouping with thin separator columns ───────────────────────
    _SEP_IS  = "╱is╱"
    _SEP_BS  = "╱bs╱"
    _SEP_CF  = "╱cf╱"
    _SEP_MKT = "╱mkt╱"
    _SEP_COLS = [_SEP_IS, _SEP_BS, _SEP_CF, _SEP_MKT]

    _GRP_IS  = ["Revenue [M]", "Net Income [M]", "EPS $",
                "Profit Margin", "Dividend per share", "Dividend Yield"]
    _GRP_BS  = ["Total Equity [M]", "BPS $", "Long term debt [M]",
                "Cash [M]", "Shares Outstanding [M]"]
    _GRP_CF  = ["FCF [M]", "Free Cash Flow Margin", "Free Cash Flow per share"]
    _GRP_MKT = ["Stock Price", "P/E", "P/B", "P/S", "P/FCF", "ROE", "ROI", "Enterprise Value [M]"]

    _ordered_cols = ["Year"]
    _ordered_cols.append(_SEP_IS)
    _ordered_cols.extend([c for c in _GRP_IS  if c in editor_init.columns])
    _ordered_cols.append(_SEP_BS)
    _ordered_cols.extend([c for c in _GRP_BS  if c in editor_init.columns])
    _ordered_cols.append(_SEP_CF)
    _ordered_cols.extend([c for c in _GRP_CF  if c in editor_init.columns])
    _ordered_cols.append(_SEP_MKT)
    _ordered_cols.extend([c for c in _GRP_MKT if c in editor_init.columns])
    # any columns not classified go at the end
    _classified = set(_GRP_IS + _GRP_BS + _GRP_CF + _GRP_MKT)
    _ordered_cols.extend([c for c in editor_init.columns
                          if c != "Year" and c not in _classified and c not in _SEP_COLS])

    for _sc in _SEP_COLS:
        editor_init[_sc] = ""
    editor_init = editor_init[[c for c in _ordered_cols if c in editor_init.columns]]

    _editor_height = (len(editor_init) + 1) * 35 + 4

    st.caption("📋 Income Statement  ·  🏦 Balance Sheet  ·  💸 Cash Flow  ·  📌 Market / Ratios")

    edited_raw = st.data_editor(
        editor_init,
        width="stretch",
        num_rows="fixed",
        hide_index=True,
        height=_editor_height,
        column_config={
            "Year": st.column_config.TextColumn("Year", disabled=True),

            # ── Separator columns ─────────────────────────────────────
            _SEP_IS:  st.column_config.TextColumn("📋 Income Statement",  disabled=True, width="small", help="Odděluje Year od Income Statement"),
            _SEP_BS:  st.column_config.TextColumn("🏦 Balance Sheet",     disabled=True, width="small"),
            _SEP_CF:  st.column_config.TextColumn("💸 Cash Flow",         disabled=True, width="small"),
            _SEP_MKT: st.column_config.TextColumn("📌 Market / Ratios",   disabled=True, width="small"),

            # ── Income Statement ──────────────────────────────────────
            "Revenue [M]":            st.column_config.NumberColumn("Revenue [M] 🟡🔵🟠",           format="%.0f",    help="Použito v: P/E fair value, DCF fair value, Simple EPS / Revenue Growth"),
            "Net Income [M]":         st.column_config.NumberColumn("Net Income [M] 🔴",           format="%.0f",    help="Použito v: Simple Valuation – Damodaran (jako proxy NOPAT)"),
            "EPS $":                  st.column_config.NumberColumn("EPS $ 🟣🟠",                  format="%.2f",    help="Použito v: ROE model Dan Gladiš, Simple EPS (EPS Growth sub-model)"),
            "Profit Margin":          st.column_config.NumberColumn("Profit Margin",              format="%.2f%%"),
            "Dividend per share":     st.column_config.NumberColumn("Dividend per share 🟣",      format="%.4f",    help="Použito v: ROE model Dan Gladiš"),
            "Dividend Yield":         st.column_config.NumberColumn("Dividend Yield",             format="%.2f%%",  help="Dividendový výnos = DPS / Stock Price. Automaticky vypočteno."),

            # ── Balance Sheet ─────────────────────────────────────────
            "Total Equity [M]":       st.column_config.NumberColumn("Total Equity [M]",           format="%.0f"),
            "BPS $":                  st.column_config.NumberColumn("BPS $ 🟣",                   format="%.2f",    help="Použito v: ROE model Dan Gladiš"),
            "Long term debt [M]":     st.column_config.NumberColumn("Long term debt [M] 🔴",      format="%.0f",    help="Použito v: Simple Valuation – Damodaran (equity bridge)"),
            "Cash [M]":               st.column_config.NumberColumn("Cash [M] 🔴",               format="%.0f",    help="Použito v: Simple Valuation – Damodaran (equity bridge)"),
            "Shares Outstanding [M]": st.column_config.NumberColumn("Shares Outstanding [M] 🟡🔵🟠🔴", format="%.2f", help="Použito v: P/E fair value, DCF fair value, Simple EPS / Revenue Growth, Simple Valuation – Damodaran"),
            "ROE":                    st.column_config.NumberColumn("ROE 🟣",                     format="%.2f%%",  help="Použito v: ROE model Dan Gladiš"),
            "ROI":                    st.column_config.NumberColumn("ROI (ROIC proxy)",           format="%.2f%%",  help="ROI = Net Income / (Equity + Long-term Debt). Proxy za ROIC – přesnější výpočet by zahrnoval NOPAT = EBIT × (1 − tax). Používáno jako 'ROIC' vstup v Damodaran modelu."),

            # ── Cash Flow ─────────────────────────────────────────────
            "FCF [M]":                st.column_config.NumberColumn("FCF [M]",                   format="%.0f"),
            "Free Cash Flow Margin":  st.column_config.NumberColumn("Free Cash Flow Margin",     format="%.2f%%"),
            "Free Cash Flow per share": st.column_config.NumberColumn("Free Cash Flow per share", format="%.2f"),

            # ── Market / Ratios ───────────────────────────────────────
            "Stock Price":            st.column_config.NumberColumn("Stock Price 🟢",             format="%.2f",    help="Použito ve všech modelech budoucího vývoje akcie"),
            "P/E":                    st.column_config.NumberColumn("P/E",                       format="%.1f"),
            "P/B":                    st.column_config.NumberColumn("P/B",                       format="%.1f"),
            "P/S":                    st.column_config.NumberColumn("P/S",                       format="%.1f"),
            "P/FCF":                  st.column_config.NumberColumn("P/FCF",                     format="%.1f"),
            "Enterprise Value [M]":   st.column_config.NumberColumn("Enterprise Value [M]",      format="%.0f",    help="Vypočteno: Tržní kapitalizace + Dluh – Cash. Referenční hodnota."),
        },
        key="val_data_editor",
    )

    # ── Enter → move focus one row down (Excel-like navigation) ─────────
    components.html("""
    <script>
    (function() {
        // Re-install on every render: remove old listener first
        if (window.parent._valEnterNavHandler) {
            window.parent.document.removeEventListener('keydown', window.parent._valEnterNavHandler, true);
        }

        var doc = window.parent.document;

        function _editingCellFromTarget(target) {
            if (target && target.closest) {
                var c = target.closest('.ag-cell-inline-editing');
                if (c) return c;
            }
            return doc.querySelector('.ag-cell-inline-editing');
        }

        function _startEdit(cell) {
            if (!cell) return;
            cell.click();
            setTimeout(function() {
                cell.dispatchEvent(new KeyboardEvent('keydown', {
                    key: 'Enter', keyCode: 13, which: 13,
                    bubbles: true, cancelable: true
                }));
                var inp = cell.querySelector('input, textarea, [contenteditable="true"]');
                if (inp) {
                    inp.focus();
                    if (inp.select) inp.select();
                }
            }, 30);
        }

        window.parent._valEnterNavHandler = function(e) {
            if (e.key !== 'Enter') return;
            if (e.shiftKey || e.ctrlKey || e.altKey || e.metaKey) return;

            // Find the cell currently in edit mode (prefer event target scope)
            var cell = _editingCellFromTarget(e.target);
            if (!cell) return;

            var rowEl = cell.closest('[row-index]');
            if (!rowEl) return;
            var currentRow = Number(rowEl.getAttribute('row-index'));
            if (!Number.isFinite(currentRow)) return;
            var colId = cell.getAttribute('col-id');

            // Prevent AG Grid default Enter behavior and apply Excel-like move down
            e.preventDefault();
            e.stopPropagation();

            var input = cell.querySelector('input, textarea, [contenteditable="true"]');
            if (input) {
                input.blur();
            }

            var targetRow = currentRow + 1;

            setTimeout(function() {
                var grid = cell.closest('.ag-root-wrapper') || doc;
                var nextRowEl = grid.querySelector('[row-index="' + targetRow + '"]');
                if (!nextRowEl) return;

                // Find target cell by iterating (avoids CSS selector issues
                // with special chars like [ ] in column names such as "Revenue [M]")
                var targetCell = null;
                if (colId) {
                    var allCells = nextRowEl.querySelectorAll('.ag-cell[col-id]');
                    for (var i = 0; i < allCells.length; i++) {
                        if (allCells[i].getAttribute('col-id') === colId) {
                            targetCell = allCells[i];
                            break;
                        }
                    }
                }

                if (!targetCell) {
                    // fallback: first non-Year cell
                    var cells = nextRowEl.querySelectorAll('.ag-cell[col-id]');
                    for (var i = 0; i < cells.length; i++) {
                        if (cells[i].getAttribute('col-id') !== 'Year') {
                            targetCell = cells[i];
                            break;
                        }
                    }
                }
                if (!targetCell) return;

                targetCell.scrollIntoView({ block: 'nearest', inline: 'nearest' });
                _startEdit(targetCell);
            }, 40);
        };

        doc.addEventListener('keydown', window.parent._valEnterNavHandler, true);
    })();
    </script>
    """, height=0)

    # Persist manual overrides (cells that differ from api_df)
    edited_raw = edited_raw.drop(columns=_SEP_COLS, errors="ignore")
    # Convert Dividend Yield back from display percent to decimal before comparing with api_df
    if "Dividend Yield" in edited_raw.columns:
        edited_raw["Dividend Yield"] = (edited_raw["Dividend Yield"] / 100).round(8)
    edited_df = edited_raw.set_index("Year")
    new_manual = pd.DataFrame(np.nan, index=api_df.index, columns=api_df.columns)

    for col in api_df.columns:
        if col not in edited_df.columns:
            continue
        for idx in api_df.index:
            if idx not in edited_df.index:
                continue
            ev = _safe_float(edited_df.loc[idx, col])
            av = _safe_float(api_df.loc[idx, col])
            # Dividend Yield: round both sides to 6 decimals to absorb
            # floating-point drift from the ×100/÷100 display conversion
            if col == "Dividend Yield":
                ev = round(ev, 6) if np.isfinite(ev) else ev
                av = round(av, 6) if np.isfinite(av) else av
            # if edited differs from API (accounting for both NaN)
            if not (np.isnan(ev) and np.isnan(av)) and ev != av:
                new_manual.loc[idx, col] = ev

    st.session_state.val_manual_df = new_manual
    effective_df, override_mask = merge_api_and_manual(api_df, new_manual)

    # ── Effective view with override highlighting ─────────────────────────
    # Re-order columns to match the group order used in the editor
    _eff_ordered = [c for c in _ordered_cols if c not in _SEP_COLS and c in effective_df.columns]
    # append any leftover columns not in _ordered_cols (shouldn't happen, but safe)
    _eff_ordered += [c for c in effective_df.columns if c not in _eff_ordered]
    _eff_to_show = effective_df[_eff_ordered]

    n_overrides = int(override_mask.sum().sum())
    if n_overrides > 0:
        with st.expander(f"📋 Effective view – {n_overrides} přepsaná {'buňka' if n_overrides == 1 else 'buňky'} (zvýrazněno)", expanded=True):
            st.markdown(
                style_effective_df(_eff_to_show, override_mask).to_html(),
                unsafe_allow_html=True,
            )
    else:
        with st.expander("📋 Effective view (žádné přepsané buňky)", expanded=False):
            st.markdown(
                style_effective_df(_eff_to_show, override_mask).to_html(),
                unsafe_allow_html=True,
            )

    # ── Metrics ───────────────────────────────────────────────────────────
    metrics_df = compute_metrics(effective_df)

    st.divider()

    # ── Lower section: Historical performance table + chart ──────────────
    st.markdown("**Historická výkonnost:**")

    _met_col, _chart_col = st.columns([1, 2], gap="large")

    with _met_col:
        if metrics_df.empty:
            st.warning("Nedostatek dat pro výpočet metrik.")
        else:
            st.markdown(
                style_metrics_df(metrics_df).to_html(),
                unsafe_allow_html=True,
            )

    with _chart_col:
        # Build chart data from annual rows (exclude TTM for cleaner view)
        _chart_annual = effective_df.drop(index=["TTM"], errors="ignore").copy()
        _chart_annual = _chart_annual.sort_index()
        _chart_cols_left  = ["Revenue [M]", "Net Income [M]", "FCF [M]"]
        _chart_cols_right = ["EPS $", "BPS $"]
        _all_chart_cols   = _chart_cols_left + _chart_cols_right

        _chart_rows = []
        for _yr in _chart_annual.index:
            for _col in _all_chart_cols:
                _v = _safe_float(_chart_annual.loc[_yr, _col]) if _col in _chart_annual.columns else np.nan
                if not np.isnan(_v):
                    _chart_rows.append({"Year": str(_yr), "Metric": _col, "Value": _v,
                                        "Axis": "right" if _col in _chart_cols_right else "left"})

        if _chart_rows:
            _cdf = pd.DataFrame(_chart_rows)

            _left_df  = _cdf[_cdf["Axis"] == "left"]
            _right_df = _cdf[_cdf["Axis"] == "right"]

            _color_map = {
                "Revenue [M]":    "#5B9BD5",
                "Net Income [M]": "#70AD47",
                "FCF [M]":        "#FFC000",
                "EPS $":          "#FF7043",
                "BPS $":          "#AB47BC",
            }
            _domain   = list(_color_map.keys())
            _range_c  = list(_color_map.values())

            _x = alt.X("Year:N", sort=list(_chart_annual.index), title="Rok")

            _left_base = (
                alt.Chart(_left_df)
                .mark_line(point=True, strokeWidth=2)
                .encode(
                    x=_x,
                    y=alt.Y("Value:Q", title="Revenue / Net Income / FCF [M $]", axis=alt.Axis(titleColor="#93a3b8")),
                    color=alt.Color("Metric:N", scale=alt.Scale(domain=_domain, range=_range_c), legend=alt.Legend(title="")),
                    tooltip=["Year:N", "Metric:N", alt.Tooltip("Value:Q", format=",.0f")],
                )
            )

            _right_base = (
                alt.Chart(_right_df)
                .mark_line(point=True, strokeWidth=2, strokeDash=[4, 2])
                .encode(
                    x=_x,
                    y=alt.Y(
                        "Value:Q",
                        title="EPS / BPS [$]",
                        axis=alt.Axis(
                            titleColor="#93a3b8",
                            titleAngle=-90,
                            grid=True,
                            gridColor="#3a3f5c",
                            gridDash=[2, 4],
                        ),
                    ),
                    color=alt.Color("Metric:N", scale=alt.Scale(domain=_domain, range=_range_c), legend=alt.Legend(title="")),
                    tooltip=["Year:N", "Metric:N", alt.Tooltip("Value:Q", format=".2f")],
                )
            )

            _hist_chart = (
                alt.layer(_left_base, _right_base)
                .resolve_scale(y="independent")
                .properties(height=560, title="Historický vývoj klíčových metrik")
                .configure_view(strokeWidth=0)
                .configure_axis(grid=True, gridColor="#2a2d3e", labelColor="#93a3b8", titleColor="#93a3b8")
                .configure_title(color="#cdd6f4")
                .configure_legend(labelColor="#cdd6f4", titleColor="#cdd6f4")
            )
            st.altair_chart(_hist_chart, width="stretch")
        else:
            st.info("Nejsou data pro graf.")

    # ── Výhled analytiků ─────────────────────────────────────────────
    try:
        _ee_out = _ci["earnings_estimate"]
        _re_out = _ci["revenue_estimate"]
        _info_out = _ci["info"]
    except Exception:
        _ee_out = None; _re_out = None; _info_out = {}

    # Resolve last actual EPS/Revenue from effective_df
    _annual_out = effective_df.drop(index=["TTM"], errors="ignore").sort_index()
    _last_yr_out = _annual_out.index[-1] if len(_annual_out) > 0 else None
    _base_eps_out = _safe_float(_annual_out.loc[_last_yr_out, "EPS $"]) if (_last_yr_out and "EPS $" in _annual_out.columns) else np.nan
    _base_rev_out = _safe_float(_annual_out.loc[_last_yr_out, "Revenue [M]"]) / 1e3 if (_last_yr_out and "Revenue [M]" in _annual_out.columns) else np.nan  # convert M→B

    # Parse estimates (0y = current FY = Y2026, +1y = next FY = Y2027)
    import datetime as _dt_out
    _cur_fy_out = _dt_out.date.today().year  # e.g. 2026

    def _get_est(df, period, col):
        """Safely get a value from an estimate DataFrame by period index."""
        if df is None or getattr(df, "empty", True):
            return np.nan
        try:
            if period in df.index:
                v = df.loc[period, col]
            else:
                return np.nan
            return float(v) if v is not None and not pd.isna(v) else np.nan
        except Exception:
            return np.nan

    _eps_y1 = _get_est(_ee_out, "0y", "avg")   # Y2026e EPS
    _eps_y2 = _get_est(_ee_out, "+1y", "avg")  # Y2027e EPS
    _nan_y1 = _get_est(_ee_out, "0y", "numberOfAnalysts")
    _nan_y2 = _get_est(_ee_out, "+1y", "numberOfAnalysts")

    _rev_y1_m = _get_est(_re_out, "0y", "avg")   # in raw units (USD)
    _rev_y2_m = _get_est(_re_out, "+1y", "avg")
    _rev_y1 = _rev_y1_m / 1e9 if not np.isnan(_rev_y1_m) else np.nan  # → billions
    _rev_y2 = _rev_y2_m / 1e9 if not np.isnan(_rev_y2_m) else np.nan

    # Current price for Forward P/E
    _cur_price_out = np.nan
    try:
        if "TTM" in effective_df.index and "Stock Price" in effective_df.columns:
            _cur_price_out = _safe_float(effective_df.loc["TTM", "Stock Price"])
        if np.isnan(_cur_price_out):
            _cur_price_out = float(_info_out.get("currentPrice") or _info_out.get("regularMarketPrice") or np.nan)
    except Exception:
        pass

    _fpe_y1 = (_cur_price_out / _eps_y1) if (not np.isnan(_cur_price_out) and not np.isnan(_eps_y1) and _eps_y1 > 0) else np.nan
    _fpe_y2 = (_cur_price_out / _eps_y2) if (not np.isnan(_cur_price_out) and not np.isnan(_eps_y2) and _eps_y2 > 0) else np.nan

    # Growth % — always YoY: Y2026e vs base, Y2027e vs Y2026e
    def _pct(new, old):
        if np.isnan(new) or np.isnan(old) or old == 0:
            return np.nan
        return (new - old) / abs(old) * 100

    _eps_g1  = _pct(_eps_y1, _base_eps_out)    # Y2026e vs last actual
    _eps_g2  = _pct(_eps_y2, _eps_y1)           # Y2027e vs Y2026e
    _rev_g1  = _pct(_rev_y1, _base_rev_out)     # Y2026e vs last actual
    _rev_g2  = _pct(_rev_y2, _rev_y1)           # Y2027e vs Y2026e

    _base_yr_lbl = str(_last_yr_out) if _last_yr_out else "—"
    _y1_lbl = f"Y{_cur_fy_out}e"
    _y2_lbl = f"Y{_cur_fy_out + 1}e"

    _has_outlook = not (np.isnan(_eps_y1) and np.isnan(_eps_y2) and np.isnan(_rev_y1) and np.isnan(_rev_y2))

    if _has_outlook:
        st.divider()
        st.markdown("**📈 Výhled analytiků:**")

        def _fmt_val(v, fmt=".2f"):
            return f"{v:{fmt}}" if not np.isnan(v) else "—"

        def _fmt_pct(v):
            if np.isnan(v):
                return "<span style='color:#555'>—</span>"
            color = "#4ade80" if v >= 0 else "#f87171"
            sign  = "+" if v >= 0 else ""
            return f"<span style='color:{color}; font-weight:600'>{sign}{v:.1f}%</span>"

        def _fmt_fpe(v):
            return f"{v:.1f}×" if not np.isnan(v) else "—"

        def _analysts(n):
            return f"({int(n)} anal.)" if not np.isnan(n) else ""

        _tbl_html = f"""
<style>
.outlook-table {{
    border-collapse: collapse;
    width: auto;
    font-size: 13px;
    border-left: 3px solid #5B9BD5;
    background: #1a1d2e;
    border-radius: 4px;
}}
.outlook-table th {{
    background: #1e2030;
    color: #cdd6f4;
    padding: 6px 14px;
    text-align: right;
    font-weight: 600;
    border-bottom: 1px solid #2a2d3e;
    white-space: nowrap;
}}
.outlook-table th:first-child {{ text-align: left; }}
.outlook-table th.base-col {{ color: #6b7280; }}
.outlook-table td {{
    padding: 5px 14px;
    text-align: right;
    border-bottom: 1px solid #1e2030;
    color: #cdd6f4;
    white-space: nowrap;
}}
.outlook-table td:first-child {{ text-align: left; font-weight: 500; color: #93a3b8; white-space: nowrap; }}
.outlook-table tr:last-child td {{ border-bottom: none; }}
.base-col {{ color: #6b7280 !important; }}
</style>
<table class="outlook-table">
<thead>
  <tr>
    <th>Metrika</th>
    <th class="base-col">{_base_yr_lbl} (skut.)</th>
    <th>{_y1_lbl}</th>
    <th>YoY</th>
    <th>{_y2_lbl}</th>
    <th>YoY</th>
  </tr>
</thead>
<tbody>
  <tr>
    <td>EPS ($)</td>
    <td class="base-col">{_fmt_val(_base_eps_out)}</td>
    <td>{_fmt_val(_eps_y1)} <small style='color:#6b7280'>{_analysts(_nan_y1)}</small></td>
    <td>{_fmt_pct(_eps_g1)}</td>
    <td>{_fmt_val(_eps_y2)} <small style='color:#6b7280'>{_analysts(_nan_y2)}</small></td>
    <td>{_fmt_pct(_eps_g2)}</td>
  </tr>
  <tr>
    <td>Revenue (mld. $)</td>
    <td class="base-col">{_fmt_val(_base_rev_out)}</td>
    <td>{_fmt_val(_rev_y1)}</td>
    <td>{_fmt_pct(_rev_g1)}</td>
    <td>{_fmt_val(_rev_y2)}</td>
    <td>{_fmt_pct(_rev_g2)}</td>
  </tr>
  <tr>
    <td>Forward P/E</td>
    <td class="base-col">—</td>
    <td>{_fmt_fpe(_fpe_y1)}</td>
    <td></td>
    <td>{_fmt_fpe(_fpe_y2)}</td>
    <td></td>
  </tr>
</tbody>
</table>
"""
        st.markdown(_tbl_html, unsafe_allow_html=True)

    # ── Uložit historická data ────────────────────────────────────────
    if not metrics_df.empty:
        try:
            _hist_price = np.nan
            try:
                if "TTM" in effective_df.index and "Stock Price" in effective_df.columns:
                    _hist_price = _safe_float(effective_df.loc["TTM", "Stock Price"])
            except Exception:
                pass
            _hist_bytes = build_snapshot_excel_bytes(
                effective_df=effective_df,
                metrics_df=metrics_df,
                manual_df=st.session_state.val_manual_df,
                override_mask=override_mask,
                scope="BASIC",
                ticker=st.session_state.val_ticker,
                years=st.session_state.val_years,
                current_price=_hist_price,
            )
            _hist_fname = f"{st.session_state.val_ticker}_hist_{datetime.now().strftime('%y_%m_%d')}.xlsx"
            _hist_col1, _hist_col2 = st.columns([1, 3])
            with _hist_col1:
                st.download_button(
                    "💾 Uložit historická data",
                    data=_hist_bytes,
                    file_name=_hist_fname,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="snap_hist_save_btn",
                    width="stretch",
                )
        except Exception as _exc:
            st.warning(f"Uložení selhalo: {_exc}")

    st.divider()
    # ── Výpočetní modely – tabs ─────────────────────────────────────────
    st.markdown("## Výpočet Intrinsic Value")

    # Shared helper – available for ALL tabs (also re-defined inside tab 3 for backwards compat)
    def _tooltip_attr(text):
        return html.escape(text, quote=True).replace("\n", "&#10;")

    # ── Model recommendation ──────────────────────────────────────────────
    with st.expander("🎯 Doporučení modelu pro tento ticker", expanded=True):
        st.caption("Automatické hodnocení vhodnosti každého modelu na základě TTM dat i historické stability (CV, pozitivní roky, trend).")
        _recs = recommend_models(effective_df, ci_info=_ci.get("info", {}) if _ci else {})
        _rating_color = {
            "✅ Vhodný":     "#66BB6A",
            "⚠️ Podmíněně": "#FFD54F",
            "❌ Nevhodný":   "#FF7043",
        }
        _rec_cols = st.columns(len(_recs))
        for _rc, _rec in zip(_rec_cols, _recs):
            with _rc:
                _clr = _rating_color.get(_rec["rating"], "#93a3b8")
                _body = (
                    f"<div style='border-left:4px solid {_clr};padding:8px 10px;"
                    f"border-radius:6px;background:rgba(255,255,255,0.04)'>"
                    f"<div style='font-weight:700;font-size:13px'>{_rec['model']}</div>"
                    f"<div style='color:{_clr};font-size:12px;margin:4px 0'>{_rec['rating']}</div>"
                    + "".join(
                        f"<div style='color:#93a3b8;font-size:11px'>✔ {x}</div>"
                        for x in _rec["reasons"]
                    )
                    + "".join(
                        f"<div style='color:#FF7043;font-size:11px'>⚠ {x}</div>"
                        for x in _rec["warnings"]
                    )
                    + "</div>"
                )
                st.markdown(_body, unsafe_allow_html=True)
        st.markdown(
            "<div style='margin-top:10px;padding:8px 12px;border-radius:6px;"
            "background:rgba(255,255,255,0.04);font-size:11px;color:#93a3b8'>"
            "<b style='color:#cdd5e0'>ℹ️ Legenda metrik:</b>&nbsp;&nbsp;"
            "<b>R²</b> = koeficient determinace trendu (0–1): měří, jak dobře hladký trend vysvětluje historická data. "
            "<b>R² ≥ 0.85</b> = silný trend, <b>0.65–0.85</b> = střední, <b>&lt; 0.4</b> = bez jasného trendu. "
            "Výpočet: log-lineární fit pro Revenue / BPS (exponenciální růst), lineární fit pro EPS / NI / FCF (mohou být záporné). "
            "&nbsp;·&nbsp;"
            "<b>±pp</b> = směrodatná odchylka v procentních bodech — používá se pro Profit Margin a ROE, "
            "kde CV (relativní míra) selhává kvůli nízké základně. "
            "<b>&lt; 2 pp</b> = stabilní, <b>2–5 pp</b> = střední, <b>&gt; 5 pp</b> = vysoká volatilita. "
            "&nbsp;·&nbsp;"
            "<b>CV YoY</b> = koeficient variace meziročních temp růstu — pro Revenue: jak konzistentní je tempo, ne objem."
            "</div>",
            unsafe_allow_html=True,
        )

    # ── Global discount rate (syncs to all models) ───────────────────────
    with st.expander("⚙️ Globální diskontní sazba (požadovaný výnos r)", expanded=False):
        _gcols = st.columns([3, 1, 1])
        with _gcols[0]:
            _global_r = st.number_input(
                "Požadovaný roční výnos r (%)",
                min_value=1.0, max_value=40.0,
                value=float(st.session_state.get("global_r_pct", 12.0)),
                step=0.5, format="%.1f",
                key="global_r_pct",
                help="Nastaví diskontní sazbu r ve všech modelech najednou. Klikni na tlačítko vpravo pro synchronizaci.",
            )
        with _gcols[1]:
            st.markdown("<div style='padding-top:28px'></div>", unsafe_allow_html=True)
            if st.button("↕️ Použít ve všech modelech", key="global_r_sync_btn"):
                # Update per-model r keys in session state so per-model widgets pick up the new value
                for _sn_g in ["Low", "Mid", "High"]:
                    # Simple EPS / Revenue Growth – fix actual session state key names
                    for _sk, _wk in [("simple_eps_params", "seps_r"), ("simple_rev_params", "srev_r")]:
                        if _sk in st.session_state and _sn_g in st.session_state[_sk]:
                            st.session_state[_sk][_sn_g]["r"] = _global_r
                        # also update the per-widget key so the number_input widget reflects the change
                        st.session_state[f"{_wk}_{_sn_g}"] = _global_r
                    if "damodaran_params" in st.session_state:
                        if "scenarios" in st.session_state["damodaran_params"] and _sn_g in st.session_state["damodaran_params"]["scenarios"]:
                            st.session_state["damodaran_params"]["scenarios"][_sn_g]["r"] = _global_r
                    if "scenarios" in st.session_state and _sn_g in st.session_state["scenarios"]:
                        st.session_state["scenarios"][_sn_g]["r"] = _global_r
                # ROE model (Gladiš) uses "Nominal"/"Worst"/"Best" labels – update both widget
                # keys and the params dict directly to avoid race condition on st.rerun()
                for _sn_roe in ["Nominal", "Worst", "Best"]:
                    st.session_state[f"roe_{_sn_roe}_r"] = _global_r
                    if "roe_params" in st.session_state and _sn_roe in st.session_state["roe_params"]:
                        st.session_state["roe_params"][_sn_roe]["r"] = _global_r
                st.success(f"r = {_global_r:.1f} % nastaveno ve všech modelech. Stránka se aktualizuje.")
                st.rerun()
        with _gcols[2]:
            st.markdown("<div style='padding-top:28px'></div>", unsafe_allow_html=True)
            if st.button("🔄 Reset všech scénářů na defaults", key="global_reset_defaults_btn",
                         help="Smaže všechny uložené hodnoty scénářů ve všech modelech. Defaulty se automaticky přepočítají z TTM dat po resetu."):
                for _reset_key in [
                    "simple_eps_params", "simple_rev_params",
                    "damodaran_params", "scenarios",
                    "sc_terminal_mode", "sc_tax_rate_pct", "sc_div_tax_pct", "sc_g_terminal_pct",
                    "roe_params",
                ]:
                    if _reset_key in st.session_state:
                        del st.session_state[_reset_key]
                # Also clear per-widget ROE keys
                for _sn_g in ["Nominal", "Worst", "Best", "Low", "Mid", "High"]:
                    for _pk in ["roe_1_3", "roe_4_5", "roe_6_10", "dg_1_3", "dg_4_5", "dg_6_10", "pe", "tax", "r", "ttm_cf"]:
                        _wk = f"roe_{_sn_g}_{_pk}"
                        if _wk in st.session_state:
                            del st.session_state[_wk]
                st.success("Scénáře resetovány na defaulty z TTM dat. Stránka se aktualizuje.")
                st.rerun()

    # ── Pre-compute historical volatility metrics for MC sigma defaults ──
    # (mirrors the logic inside recommend_models but exposed to app scope)
    try:
        _mc_annual = effective_df.drop(index=["TTM"], errors="ignore").sort_index().tail(7)
        def _mc_series(col):
            if col not in _mc_annual.columns:
                return []
            out = []
            for _v in _mc_annual[col]:
                try:
                    _f = float(_v)
                    if np.isfinite(_f):
                        out.append(_f)
                except Exception:
                    pass
            return out
        rev_gcv   = _growth_cv(_mc_series("Revenue [M]"))
        pm_std    = _std_pp(_mc_series("Profit Margin"))
        roe_std   = _std_pp(_mc_series("ROE"))
        eps_g_std = _eps_growth_std(_mc_series("EPS $"))
    except Exception:
        rev_gcv   = np.nan
        pm_std    = np.nan
        roe_std   = np.nan
        eps_g_std = np.nan

    _val_tabs = st.tabs([
        "Simple EPS / Revenue Growth",
        "Simple Valuation (Damodaran-style)",
        "ROE model Dan Gladiš",
        "Advanced Valuation",
    ])

    # ── Tab 1: Simple EPS / Revenue Growth ─────────────────────────────
    with _val_tabs[0]:
        _t0_tip = _tooltip_attr(
            "Popis: Projekce budoucích zisků nebo tržeb (earnings-based / revenue-based).\n"
            "Vhodné typy firem: Profitabilní firmy s predikovatelnou EPS nebo Revenue – tech, consumer staples, healthcare, quality growth.\n"
            "NEVHODNÉ pro: Banky, pojišťovny, ztrátové firmy nebo firmy s neodhadnutelnou marží.\n"
            "Výhody: Jednoduchost a intuitivnost. Rychlý screening. Dvě sub-varianty (EPS Growth / Revenue Growth).\n"
            "Na co si dát pozor: Extremální citlivost na předpoklad růstu g. Nereflektuje dluh, buybacks ani FCF konverzi. Exit P/E může být nerealistický."
        )
        st.markdown(
            f"<h3>Simple EPS / Revenue Growth "
            f"<span title='{_t0_tip}' style='cursor:help;color:#93a3b8;border-bottom:1px dotted #93a3b8;font-size:14px;'>ⓘ</span>"
            f"</h3>",
            unsafe_allow_html=True,
        )
        with st.expander("ℹ️ O tomto modelu", expanded=False):
            st.markdown("""
| | |
|---|---|
| **Popis** | Projekce EPS (nebo tržeb) + odvození terminální ceny přes Exit multiple (např. Exit P/E) a diskontování na současnost. |
| **Vhodné typy firem** | Profitabilní firmy s relativně predikovatelnou EPS nebo Revenue – tech, consumer staples, healthcare, quality growth firmy. |
| **NEVHODNÉ pro** | Banky, pojišťovny, firmy se záporným nebo nestabilním EPS, firmy s vysokou pákou. |
| **Výhody** | Jednoduchost, intuitivnost, rychlý screening. Dvě sub-varianty: EPS Growth nebo Revenue Growth. |
| **Na co si dát pozor** | Extremální citlivost na předpoklad růstu **g** – malá změna = velký dopad na Fair Value. Nereflektuje kapitálovou strukturu (dluh, buybacks, CAPEX). Exit P/E může být daleko od budoucí reality. Vhodný jen jako první orientace, ne jako jediné ocenění. |
            """)

        # ── Base values from effective_df ─────────────────────────────────
        def _seps_ttm(col, default=np.nan):
            try:
                v = _safe_float(effective_df.loc["TTM", col])
                return v if not np.isnan(v) else default
            except Exception:
                return default

        _seps_eps0   = _seps_ttm("EPS $")
        _seps_rev0_m = _seps_ttm("Revenue [M]")
        _seps_sh_m   = _seps_ttm("Shares Outstanding [M]")
        _seps_price  = _seps_ttm("Stock Price")
        _seps_pe_ttm = _seps_ttm("P/E")
        _seps_nm_ttm = _seps_ttm("Profit Margin")  # in %

        def _seps_metrics_cagr(row_label, col_label="5 let", default=8.0):
            try:
                v = _safe_float(metrics_df.loc[row_label, col_label])
                return (v * 100.0) if not np.isnan(v) else default
            except Exception:
                return default

        _d_eps_cagr = _seps_metrics_cagr("EPS CAGR", "5 let", 8.0)
        _d_rev_cagr = _seps_metrics_cagr("Revenue CAGR", "5 let", 8.0)
        _d_pe_seps  = _seps_pe_ttm if not np.isnan(_seps_pe_ttm) else 18.0
        _d_nm_seps  = _seps_nm_ttm if not np.isnan(_seps_nm_ttm) else 10.0

        # ── Session state init ────────────────────────────────────────────
        _SEPS_KEY = "simple_eps_params"
        _SREV_KEY = "simple_rev_params"

        if _SEPS_KEY not in st.session_state:
            st.session_state[_SEPS_KEY] = {
                "Low":  {"g": max(0.0, round(_d_eps_cagr * 0.5, 1)), "pe": max(5.0, round(_d_pe_seps * 0.7, 1)), "r": 12.0, "n": 10},
                "Mid":  {"g": round(_d_eps_cagr, 1),                  "pe": round(_d_pe_seps, 1),                  "r": 12.0, "n": 10},
                "High": {"g": min(50.0, round(_d_eps_cagr * 1.5, 1)), "pe": min(60.0, round(_d_pe_seps * 1.3, 1)), "r": 12.0, "n": 10},
            }
        if _SREV_KEY not in st.session_state:
            st.session_state[_SREV_KEY] = {
                "Low":  {"g": max(0.0, round(_d_rev_cagr * 0.5, 1)), "nm": max(1.0, round(_d_nm_seps * 0.8, 1)), "pe": max(5.0, round(_d_pe_seps * 0.7, 1)), "r": 12.0, "n": 10},
                "Mid":  {"g": round(_d_rev_cagr, 1),                  "nm": round(_d_nm_seps, 1),                  "pe": round(_d_pe_seps, 1),                 "r": 12.0, "n": 10},
                "High": {"g": min(50.0, round(_d_rev_cagr * 1.5, 1)), "nm": min(40.0, round(_d_nm_seps * 1.2, 1)), "pe": min(60.0, round(_d_pe_seps * 1.3, 1)), "r": 12.0, "n": 10},
            }

        _sep = st.session_state[_SEPS_KEY]
        _srv = st.session_state[_SREV_KEY]
        _SC_LABELS_S  = ["Low", "Mid", "High"]
        _SC_COLORS_S  = {"Low": "#FF7043", "Mid": "#FFD54F", "High": "#66BB6A"}

        # ── historical rows for charts ─────────────────────────────────────
        _seps_hist_years = sorted(
            [int(y) for y in effective_df.index if str(y) != "TTM" and str(y).isdigit()],
        )
        _seps_hist_price_rows: list = []
        _seps_hist_eps_rows:   list = []
        _seps_hist_rev_rows:   list = []
        for _yr in effective_df.index:
            _yr_s = str(_yr)
            if _yr_s == "TTM":
                continue  # TTM is used as forecast bridge, not in historical series
            for _col, _lst in [("Stock Price", _seps_hist_price_rows),
                                ("EPS $",        _seps_hist_eps_rows),
                                ("Revenue [M]",  _seps_hist_rev_rows)]:
                if _col in effective_df.columns:
                    _v = _safe_float(effective_df.loc[_yr, _col])
                    if not np.isnan(_v):
                        _lst.append({"Year": _yr_s, "Scenario": "Historická", "Value": _v})

        _seps_fby = max(_seps_hist_years) if _seps_hist_years else (pd.Timestamp.today().year - 1)

        # Anchor values: last historical year's actual data (so forecast connects to history endpoint)
        _fby_s = str(_seps_fby)
        _seps_price_anchor = next((r["Value"] for r in _seps_hist_price_rows if r["Year"] == _fby_s), _seps_price)
        _seps_eps_anchor   = next((r["Value"] for r in _seps_hist_eps_rows   if r["Year"] == _fby_s), _seps_eps0)
        _seps_rev_anchor   = next((r["Value"] for r in _seps_hist_rev_rows   if r["Year"] == _fby_s), _seps_rev0_m)

        # ── Sub-model radio switcher ───────────────────────────────────────
        st.markdown("---")
        _seps_submodel = st.radio(
            "Sub-model:",
            ["EPS Growth", "Revenue Growth"],
            horizontal=True,
            key="seps_submodel_radio",
        )

        # helper – ROE-style input row: label | Low | Mid | High
        def _seps_input_row(label, key_suffix, mn, mx, stp, fmt, sc_dict, dict_key):
            _cols = st.columns([2.5, 2, 2, 2])
            with _cols[0]:
                st.markdown(
                    f"<div style='font-size:14px;font-weight:700;padding-top:8px'>{label}</div>",
                    unsafe_allow_html=True,
                )
            for _i, _sn in enumerate(["Low", "Mid", "High"]):
                with _cols[_i + 1]:
                    if isinstance(stp, float):
                        sc_dict[_sn][dict_key] = st.number_input(
                            " ", min_value=float(mn), max_value=float(mx),
                            value=float(sc_dict[_sn][dict_key]),
                            step=stp, format=fmt,
                            key=f"{key_suffix}_{_sn}",
                            label_visibility="collapsed",
                        )
                    else:
                        sc_dict[_sn][dict_key] = st.number_input(
                            " ", min_value=int(mn), max_value=int(mx),
                            value=int(sc_dict[_sn][dict_key]),
                            step=int(stp),
                            key=f"{key_suffix}_{_sn}",
                            label_visibility="collapsed",
                        )

        # ── Column header row ─────────────────────────────────────────────
        _sh0, _sh_low, _sh_mid, _sh_high = st.columns([2.5, 2, 2, 2])
        with _sh_low:
            st.markdown("<div style='font-weight:700;color:#FF7043;text-align:center'>Low</div>", unsafe_allow_html=True)
        with _sh_mid:
            st.markdown("<div style='font-weight:700;color:#FFD54F;text-align:center'>Mid</div>", unsafe_allow_html=True)
        with _sh_high:
            st.markdown("<div style='font-weight:700;color:#66BB6A;text-align:center'>High</div>", unsafe_allow_html=True)

        # ─── empty fore-row lists (populated by active sub-model) ─────────
        _seps_fore_price_rows: list = []
        _seps_fore_eps_rows:   list = []
        _srev_fore_price_rows: list = []
        _srev_fore_rev_rows:   list = []
        _srev_fore_eps_rows_b: list = []
        _seps_res_a: dict = {}
        _srev_res_b: dict = {}

        # ═══════════════════ Sub-model A: EPS Growth ════════════════════════
        if _seps_submodel == "EPS Growth":
            st.markdown("#### EPS Growth → Future Price")
            _seps_input_row("EPS growth [%]",    "seps_g",  -50.0, 100.0, 0.5, "%.1f", _sep, "g")
            _seps_input_row("Terminal P/E",       "seps_pe",   1.0, 150.0, 0.5, "%.1f", _sep, "pe")
            _seps_input_row("Discount rate [%]",  "seps_r",    1.0,  50.0, 0.5, "%.1f", _sep, "r")
            _seps_input_row("Years",              "seps_n",    1,    30,   1,   "%d",   _sep, "n")

            # compute A
            for _sn in _SC_LABELS_S:
                _g_a  = _sep[_sn]["g"]  / 100.0
                _pe_a = _sep[_sn]["pe"]
                _r_a  = _sep[_sn]["r"]  / 100.0
                _n_a  = int(_sep[_sn]["n"])
                if np.isnan(_seps_eps0):
                    _seps_res_a[_sn] = None
                    continue
                if not np.isnan(_seps_price_anchor):
                    _seps_fore_price_rows.append({"Year": str(_seps_fby), "Scenario": _sn, "Value": _seps_price_anchor})
                if not np.isnan(_seps_eps_anchor):
                    _seps_fore_eps_rows.append({"Year": str(_seps_fby), "Scenario": _sn, "Value": _seps_eps_anchor})
                for _t in range(1, _n_a + 1):
                    _eps_t_a  = _seps_eps0 * (1.0 + _g_a) ** _t
                    _price_ta = _eps_t_a * _pe_a
                    _seps_fore_price_rows.append({"Year": str(_seps_fby + _t), "Scenario": _sn, "Value": _price_ta})
                    _seps_fore_eps_rows.append(  {"Year": str(_seps_fby + _t), "Scenario": _sn, "Value": _eps_t_a})
                _eps_n_a  = _seps_eps0 * (1.0 + _g_a) ** _n_a
                _fp_a     = _eps_n_a * _pe_a
                _fv_a     = _fp_a / (1.0 + _r_a) ** _n_a
                _cagr_a   = (_fp_a / _seps_price) ** (1.0 / _n_a) - 1.0 if (not np.isnan(_seps_price) and _seps_price > 0 and _n_a > 0 and _fp_a > 0) else np.nan
                _mos_a    = (_fv_a / _seps_price - 1.0) if (not np.isnan(_fv_a) and not np.isnan(_seps_price) and _seps_price > 0) else np.nan
                _seps_res_a[_sn] = {"eps_n": _eps_n_a, "future_price": _fp_a, "fair_value": _fv_a, "cagr": _cagr_a, "mos": _mos_a, "n": _n_a}

            # highlighted results A
            st.markdown("---")
            if any(_seps_res_a.get(_sn) for _sn in _SC_LABELS_S):
                _res_cols_a = st.columns(3)
                for _i_ra, _sn in enumerate(_SC_LABELS_S):
                    _ra = _seps_res_a.get(_sn)
                    with _res_cols_a[_i_ra]:
                        _clr = _SC_COLORS_S[_sn]
                        if _ra:
                            _fv_disp  = f"${_ra['fair_value']:.2f}"   if not np.isnan(_ra['fair_value'])  else "N/A"
                            _fp_disp  = f"${_ra['future_price']:.2f}" if not np.isnan(_ra['future_price']) else "N/A"
                            _cg_disp  = f"{_ra['cagr']*100:.1f}%"     if not np.isnan(_ra['cagr'])         else "N/A"
                            _mos_disp = f"{_ra['mos']*100:.1f}%"      if not np.isnan(_ra['mos'])          else "N/A"
                            _mos_clr  = "#66BB6A" if (not np.isnan(_ra['mos']) and _ra['mos'] > 0) else "#FF7043"
                            _fv_clr_a = _fv_clr(_ra['fair_value'], _seps_price)
                            st.markdown(
                                f"<div style='background:rgba(255,255,255,0.05);border-radius:10px;"
                                f"padding:14px 16px;border-left:4px solid {_clr}'>"
                                f"<div style='font-weight:700;color:{_clr};font-size:15px;margin-bottom:8px'>{_sn}</div>"
                                f"<table style='width:100%;font-size:13px;border-collapse:collapse'>"
                                f"<tr><td style='color:#93a3b8;padding:2px 0'>EPS<sub>0</sub></td>"
                                f"<td style='text-align:right;font-weight:600'>${_seps_eps0:.2f}</td></tr>"
                                f"<tr><td style='color:#93a3b8;padding:2px 0'>EPS<sub>{_ra['n']}</sub></td>"
                                f"<td style='text-align:right;font-weight:600'>${_ra['eps_n']:.2f}</td></tr>"
                                f"<tr><td style='color:#93a3b8;padding:2px 0'>Future Price</td>"
                                f"<td style='text-align:right;font-weight:600'>{_fp_disp}</td></tr>"
                                f"<tr><td style='color:#93a3b8;padding:2px 0'>Fair Value (PV)</td>"
                                f"<td style='text-align:right;font-weight:700;font-size:15px;color:{_fv_clr_a}'>{_fv_disp}</td></tr>"
                                f"<tr><td style='color:#93a3b8;padding:2px 0'>CAGR</td>"
                                f"<td style='text-align:right;font-weight:600'>{_cg_disp}</td></tr>"
                                f"<tr><td style='color:#93a3b8;padding:2px 0'><span title='Upside/Downside = FV/Price − 1. Kladné = potenciální výnos nad aktuální cenou.' style='cursor:help;border-bottom:1px dotted #93a3b8'>Upside/Downside ⓘ</span></td>"
                                f"<td style='text-align:right;font-weight:700;color:{_mos_clr}'>{_mos_disp}</td></tr>"
                                + (f"<tr><td style='color:#93a3b8;padding:2px 0;border-top:1px solid rgba(255,255,255,0.08)'>Aktuální cena</td>"
                                   f"<td style='text-align:right;font-weight:600;border-top:1px solid rgba(255,255,255,0.08)'>${_seps_price:.2f}</td></tr>"
                                   if not np.isnan(_seps_price) else "") +
                                f"</table></div>",
                                unsafe_allow_html=True,
                            )
                        else:
                            st.markdown(
                                f"<div style='background:rgba(255,255,255,0.05);border-radius:10px;"
                                f"padding:14px 16px;border-left:4px solid {_clr}'>"
                                f"<div style='font-weight:700;color:{_clr};font-size:15px;margin-bottom:8px'>{_sn}</div>"
                                f"<div style='color:#FF7043'>Chybí TTM EPS</div></div>",
                                unsafe_allow_html=True,
                            )
            else:
                st.warning("Chybí TTM EPS – nelze spočítat EPS Growth model.")

        # ═══════════════════ Sub-model B: Revenue Growth ════════════════════
        else:
            st.markdown("#### Revenue Growth → Future Price")
            _seps_input_row("Revenue growth [%]",       "srev_g",  -50.0, 100.0, 0.5, "%.1f", _srv, "g")
            _seps_input_row("Terminal Net Margin [%]",  "srev_nm", -50.0,  60.0, 0.5, "%.1f", _srv, "nm")
            _seps_input_row("Terminal P/E",             "srev_pe",   1.0, 150.0, 0.5, "%.1f", _srv, "pe")
            _seps_input_row("Discount rate [%]",        "srev_r",    1.0,  50.0, 0.5, "%.1f", _srv, "r")
            _seps_input_row("Years",                    "srev_n",    1,    30,   1,   "%d",   _srv, "n")

            # compute B
            for _sn in _SC_LABELS_S:
                _g_b  = _srv[_sn]["g"]  / 100.0
                _nm_b = _srv[_sn]["nm"] / 100.0
                _pe_b = _srv[_sn]["pe"]
                _r_b  = _srv[_sn]["r"]  / 100.0
                _n_b  = int(_srv[_sn]["n"])
                if np.isnan(_seps_rev0_m) or np.isnan(_seps_sh_m) or _seps_sh_m <= 0:
                    _srev_res_b[_sn] = None
                    continue
                if not np.isnan(_seps_price_anchor):
                    _srev_fore_price_rows.append({"Year": str(_seps_fby), "Scenario": _sn, "Value": _seps_price_anchor})
                if not np.isnan(_seps_rev_anchor):
                    _srev_fore_rev_rows.append({"Year": str(_seps_fby), "Scenario": _sn, "Value": _seps_rev_anchor})
                if not np.isnan(_seps_eps_anchor):
                    _srev_fore_eps_rows_b.append({"Year": str(_seps_fby), "Scenario": _sn, "Value": _seps_eps_anchor})
                for _t in range(1, _n_b + 1):
                    _rev_t_m_b = _seps_rev0_m * (1.0 + _g_b) ** _t
                    _eps_t_b   = _rev_t_m_b * 1e6 * _nm_b / (_seps_sh_m * 1e6)
                    _price_tb  = _eps_t_b * _pe_b
                    _srev_fore_price_rows.append({"Year": str(_seps_fby + _t), "Scenario": _sn, "Value": _price_tb})
                    _srev_fore_rev_rows.append(  {"Year": str(_seps_fby + _t), "Scenario": _sn, "Value": _rev_t_m_b})
                    _srev_fore_eps_rows_b.append({"Year": str(_seps_fby + _t), "Scenario": _sn, "Value": _eps_t_b})
                _rev_n_b  = _seps_rev0_m * (1.0 + _g_b) ** _n_b
                _eps_n_b  = _rev_n_b * 1e6 * _nm_b / (_seps_sh_m * 1e6)
                _fp_b     = _eps_n_b * _pe_b
                _fv_b     = _fp_b / (1.0 + _r_b) ** _n_b
                _cagr_b   = (_fp_b / _seps_price) ** (1.0 / _n_b) - 1.0 if (not np.isnan(_seps_price) and _seps_price > 0 and _n_b > 0 and _fp_b > 0) else np.nan
                _mos_b    = (_fv_b / _seps_price - 1.0) if (not np.isnan(_fv_b) and not np.isnan(_seps_price) and _seps_price > 0) else np.nan
                _srev_res_b[_sn] = {"rev_n": _rev_n_b, "eps_n": _eps_n_b, "future_price": _fp_b, "fair_value": _fv_b, "cagr": _cagr_b, "mos": _mos_b, "n": _n_b}

            # highlighted results B
            st.markdown("---")
            if any(_srev_res_b.get(_sn) for _sn in _SC_LABELS_S):
                _res_cols_b = st.columns(3)
                for _i_rb, _sn in enumerate(_SC_LABELS_S):
                    _rb = _srev_res_b.get(_sn)
                    with _res_cols_b[_i_rb]:
                        _clr = _SC_COLORS_S[_sn]
                        if _rb:
                            _fv_disp  = f"${_rb['fair_value']:.2f}"   if not np.isnan(_rb['fair_value'])  else "N/A"
                            _fp_disp  = f"${_rb['future_price']:.2f}" if not np.isnan(_rb['future_price']) else "N/A"
                            _cg_disp  = f"{_rb['cagr']*100:.1f}%"     if not np.isnan(_rb['cagr'])         else "N/A"
                            _mos_disp = f"{_rb['mos']*100:.1f}%"      if not np.isnan(_rb['mos'])          else "N/A"
                            _mos_clr  = "#66BB6A" if (not np.isnan(_rb['mos']) and _rb['mos'] > 0) else "#FF7043"
                            _fv_clr_b = _fv_clr(_rb['fair_value'], _seps_price)
                            st.markdown(
                                f"<div style='background:rgba(255,255,255,0.05);border-radius:10px;"
                                f"padding:14px 16px;border-left:4px solid {_clr}'>"
                                f"<div style='font-weight:700;color:{_clr};font-size:15px;margin-bottom:8px'>{_sn}</div>"
                                f"<table style='width:100%;font-size:13px;border-collapse:collapse'>"
                                f"<tr><td style='color:#93a3b8;padding:2px 0'>Revenue<sub>0</sub> [M$]</td>"
                                f"<td style='text-align:right;font-weight:600'>{_seps_rev0_m:,.0f}</td></tr>"
                                f"<tr><td style='color:#93a3b8;padding:2px 0'>Revenue<sub>{_rb['n']}</sub> [M$]</td>"
                                f"<td style='text-align:right;font-weight:600'>{_rb['rev_n']:,.0f}</td></tr>"
                                f"<tr><td style='color:#93a3b8;padding:2px 0'>EPS<sub>{_rb['n']}</sub></td>"
                                f"<td style='text-align:right;font-weight:600'>${_rb['eps_n']:.2f}</td></tr>"
                                f"<tr><td style='color:#93a3b8;padding:2px 0'>Future Price</td>"
                                f"<td style='text-align:right;font-weight:600'>{_fp_disp}</td></tr>"
                                f"<tr><td style='color:#93a3b8;padding:2px 0'>Fair Value (PV)</td>"
                                f"<td style='text-align:right;font-weight:700;font-size:15px;color:{_fv_clr_b}'>{_fv_disp}</td></tr>"
                                f"<tr><td style='color:#93a3b8;padding:2px 0'>CAGR</td>"
                                f"<td style='text-align:right;font-weight:600'>{_cg_disp}</td></tr>"
                                f"<tr><td style='color:#93a3b8;padding:2px 0'><span title='Upside/Downside = FV/Price − 1. Kladné = potenciální výnos nad aktuální cenou.' style='cursor:help;border-bottom:1px dotted #93a3b8'>Upside/Downside ⓘ</span></td>"
                                f"<td style='text-align:right;font-weight:700;color:{_mos_clr}'>{_mos_disp}</td></tr>"
                                + (f"<tr><td style='color:#93a3b8;padding:2px 0;border-top:1px solid rgba(255,255,255,0.08)'>Aktuální cena</td>"
                                   f"<td style='text-align:right;font-weight:600;border-top:1px solid rgba(255,255,255,0.08)'>${_seps_price:.2f}</td></tr>"
                                   if not np.isnan(_seps_price) else "") +
                                f"</table></div>",
                                unsafe_allow_html=True,
                            )
                        else:
                            st.markdown(
                                f"<div style='background:rgba(255,255,255,0.05);border-radius:10px;"
                                f"padding:14px 16px;border-left:4px solid {_clr}'>"
                                f"<div style='font-weight:700;color:{_clr};font-size:15px;margin-bottom:8px'>{_sn}</div>"
                                f"<div style='color:#FF7043'>Chybí TTM Revenue/Shares</div></div>",
                                unsafe_allow_html=True,
                            )
            else:
                st.warning("Chybí TTM Revenue nebo Shares – nelze spočítat Revenue Growth model.")

        # ═══════════════════ Charts ══════════════════════════════════════════
        st.markdown("---")
        _max_n_s = max(
            max(int(_sep[_sn]["n"]) for _sn in _SC_LABELS_S),
            max(int(_srv[_sn]["n"]) for _sn in _SC_LABELS_S),
        )
        _fore_yr_strs_s = [str(_seps_fby)] + [str(_seps_fby + _t) for _t in range(1, _max_n_s + 1)]
        _hist_yr_strs_s = [str(y) for y in sorted(_seps_hist_years)]
        _full_yr_order_s = _hist_yr_strs_s + _fore_yr_strs_s
        _domain_s = ["Historická", "Low", "Mid", "High"]
        _range_s  = ["#4f8ef7", "#FF7043", "#FFD54F", "#66BB6A"]
        _cscale_s = alt.Scale(domain=_domain_s, range=_range_s)

        # pick active fore rows
        _active_price_fore = _seps_fore_price_rows if _seps_submodel == "EPS Growth" else _srev_fore_price_rows
        _active_eps_fore   = _seps_fore_eps_rows   if _seps_submodel == "EPS Growth" else _srev_fore_eps_rows_b

        def _seps_make_chart(hist_rows, fore_rows, y_title, tt_fmt, chart_title, h=300):
            layers = []
            _years_s = {r["Year"] for r in hist_rows + fore_rows}
            _domain_s_chart = list(dict.fromkeys(y for y in _full_yr_order_s if y in _years_s))
            _x_enc_s = alt.X("Year:N", sort=_domain_s_chart, scale=alt.Scale(domain=_domain_s_chart), title="Rok")
            if hist_rows:
                layers.append(
                    alt.Chart(pd.DataFrame(hist_rows)).mark_line(strokeWidth=2, point=True)
                    .encode(x=_x_enc_s,
                            y=alt.Y("Value:Q", title=y_title),
                            color=alt.Color("Scenario:N", scale=_cscale_s, title=""),
                            tooltip=["Year", "Scenario", alt.Tooltip("Value:Q", format=tt_fmt)])
                )
            if fore_rows:
                layers.append(
                    alt.Chart(pd.DataFrame(fore_rows)).mark_line(strokeWidth=2, strokeDash=[4, 2], point=True)
                    .encode(x=_x_enc_s,
                            y=alt.Y("Value:Q"),
                            color=alt.Color("Scenario:N", scale=_cscale_s),
                            tooltip=["Year", "Scenario", alt.Tooltip("Value:Q", format=tt_fmt)])
                )
            if layers:
                st.altair_chart(
                    alt.layer(*layers)
                    .properties(title=chart_title, height=h)
                    .configure_view(strokeOpacity=0),
                    width="stretch",
                )

        # Chart 1: Price – always shown
        _seps_make_chart(
            _seps_hist_price_rows,
            _active_price_fore,
            "Cena [$]", ".2f",
            "Historická cena + Projekce ceny",
        )
        # Chart 2: EPS – only for EPS Growth sub-model
        if _seps_submodel == "EPS Growth":
            _seps_make_chart(
                _seps_hist_eps_rows,
                _active_eps_fore,
                "EPS [$]", ".2f",
                "Historické EPS + Projekce EPS",
            )
        # Chart 3: Revenue – only for Revenue Growth sub-model
        if _seps_submodel == "Revenue Growth":
            _seps_make_chart(
                _seps_hist_rev_rows,
                _srev_fore_rev_rows,
                "Revenue [M$]", ",.0f",
                "Historické Revenue + Projekce Revenue",
            )

        # ── Save ─────────────────────────────────────────────────────────────
        st.markdown("---")
        try:
            _seps_bytes = build_snapshot_excel_bytes(
                effective_df=effective_df, metrics_df=metrics_df,
                manual_df=st.session_state.val_manual_df, override_mask=override_mask,
                scope="BASIC", ticker=st.session_state.val_ticker,
                years=st.session_state.val_years,
                current_price=float(_seps_price) if not np.isnan(_seps_price) else np.nan,
            )
            _seps_fname = f"{st.session_state.val_ticker}_simple_eps_{datetime.now().strftime('%y_%m_%d')}.xlsx"
            _all_seps_bytes = build_all_excel_bytes(
                effective_df=effective_df, metrics_df=metrics_df,
                manual_df=st.session_state.val_manual_df, override_mask=override_mask,
                ticker=st.session_state.val_ticker, years=st.session_state.val_years,
                current_price=float(_seps_price) if not np.isnan(_seps_price) else np.nan,
                simple_eps_params=st.session_state.get(_SEPS_KEY, {}),
                simple_rev_params=st.session_state.get(_SREV_KEY, {}),
                damodaran_params=st.session_state.get("damodaran_params", {}),
            )
            _all_seps_fname = f"{st.session_state.val_ticker}_vse_{datetime.now().strftime('%y_%m_%d')}.xlsx"
            _seps_sc1, _seps_sc2 = st.columns([1, 1])
            with _seps_sc1:
                st.download_button(
                    "💾 Uložit tento model (včetně historických dat)",
                    data=_seps_bytes, file_name=_seps_fname,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="snap_seps_save_btn", width="stretch",
                )
            with _seps_sc2:
                st.download_button(
                    "💾 Uložit všechny modely (včetně historických dat)",
                    data=_all_seps_bytes, file_name=_all_seps_fname,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="snap_seps_all_btn", width="stretch",
                )
        except Exception as _exc_seps:
            st.warning(f"Uložení selhalo: {_exc_seps}")

        # -- Sensitivity matrix (g x r) ---------------------------------------------------
        with st.expander("🔲 Citlivost (g × r) – Mid scénář", expanded=False):
            try:
                if _seps_submodel == "EPS Growth":
                    if np.isnan(_seps_eps0):
                        st.info("Chybí EPS0 – citlivostní tabulka není dostupná.")
                    else:
                        _sm2_g_c = _sep["Mid"]["g"]
                        _sm2_pe  = _sep["Mid"]["pe"]
                        _sm2_n   = int(_sep["Mid"]["n"])
                        _sm2_r_c = _sep["Mid"]["r"]
                        _sm2_g_vals = [round(_sm2_g_c + d, 1) for d in range(-6, 7)]
                        _sm2_r_vals = [round(_sm2_r_c + d, 1) for d in range(-6, 7)]
                        _sm2_data = []
                        for _g_v in _sm2_g_vals:
                            _row2 = {"g (%)": f"{_g_v:.1f}%"}
                            for _r_v in _sm2_r_vals:
                                _fv2 = (_seps_eps0 * (1 + _g_v / 100) ** _sm2_n * _sm2_pe
                                        / (1 + _r_v / 100) ** _sm2_n) if _sm2_n > 0 else float("nan")
                                _row2[f"r {_r_v:.1f}%"] = round(_fv2, 2)
                            _sm2_data.append(_row2)
                        _sm2_df = pd.DataFrame(_sm2_data).set_index("g (%)")
                        _sm2_df_num = _sm2_df.apply(pd.to_numeric, errors="coerce")
                        _sm2_mid_row = f"{_sm2_g_c:.1f}%"
                        _sm2_mid_col = f"r {_sm2_r_c:.1f}%"
                        _sm2_styled = _sm_heatmap_style(
                            _sm2_df_num,
                            price=_seps_price if not np.isnan(_seps_price) else None,
                            mid_row=_sm2_mid_row,
                            mid_col=_sm2_mid_col,
                        )
                        st.caption(
                            f"EPS₀ = ${_seps_eps0:.2f}  |  P/E = {_sm2_pe:.1f}  |  n = {_sm2_n}  "
                            f"|  Řádky = g, sloupce = r (Mid ± 6 pp)  |  🟡 = Mid baseline"
                        )
                        st.dataframe(_sm2_styled, use_container_width=True)
                        if not np.isnan(_seps_price):
                            st.caption(f"Aktuální cena: ${_seps_price:.2f}")
                else:  # Revenue Growth
                    if np.isnan(_seps_rev0_m) or np.isnan(_seps_sh_m) or _seps_sh_m <= 0:
                        st.info("Chybí TTM Revenue/Shares – citlivostní tabulka není dostupná.")
                    else:
                        _smr_g_c = _srv["Mid"]["g"]
                        _smr_nm  = _srv["Mid"]["nm"]
                        _smr_pe  = _srv["Mid"]["pe"]
                        _smr_n   = int(_srv["Mid"]["n"])
                        _smr_r_c = _srv["Mid"]["r"]
                        _smr_g_vals = [round(_smr_g_c + d, 1) for d in range(-6, 7)]
                        _smr_r_vals = [round(_smr_r_c + d, 1) for d in range(-6, 7)]
                        _smr_data = []
                        for _g_v in _smr_g_vals:
                            _rowr = {"g (%)": f"{_g_v:.1f}%"}
                            for _r_v in _smr_r_vals:
                                _rev_n2 = _seps_rev0_m * (1 + _g_v / 100) ** _smr_n
                                _eps_n2 = _rev_n2 * 1e6 * _smr_nm / 100 / (_seps_sh_m * 1e6)
                                _fvr = (_eps_n2 * _smr_pe / (1 + _r_v / 100) ** _smr_n
                                        if _smr_n > 0 else float("nan"))
                                _rowr[f"r {_r_v:.1f}%"] = round(_fvr, 2)
                            _smr_data.append(_rowr)
                        _smr_df = pd.DataFrame(_smr_data).set_index("g (%)")
                        _smr_df_num = _smr_df.apply(pd.to_numeric, errors="coerce")
                        _smr_mid_row = f"{_smr_g_c:.1f}%"
                        _smr_mid_col = f"r {_smr_r_c:.1f}%"
                        _smr_styled = _sm_heatmap_style(
                            _smr_df_num,
                            price=_seps_price if not np.isnan(_seps_price) else None,
                            mid_row=_smr_mid_row,
                            mid_col=_smr_mid_col,
                        )
                        st.caption(
                            f"Rev₀ = {_seps_rev0_m:,.0f} M$  |  Net Margin = {_smr_nm:.1f}%  "
                            f"|  P/E = {_smr_pe:.1f}  |  n = {_smr_n}  "
                            f"|  Řádky = g, sloupce = r (Mid ± 6 pp)  |  🟡 = Mid baseline"
                        )
                        st.dataframe(_smr_styled, use_container_width=True)
                        if not np.isnan(_seps_price):
                            st.caption(f"Aktuální cena: ${_seps_price:.2f}")
            except Exception as _sm2_exc:
                st.warning(f"Citlivostní matice se nepodařila: {_sm2_exc}")

        # ── Monte Carlo — EPS Growth ───────────────────────────────────────────
        if _seps_submodel == "EPS Growth":
          with st.expander("🎲 Monte Carlo simulace — Simple EPS Growth", expanded=False):
            st.caption(
                "Simultánní náhodná variace g a Terminal P/E. "
                "Diskontní sazba r je fixní. "
                "σ předvyplněno z historické volatility (lze přepsat). "
                "🟡 = percentily  |  ━ = P50  |  🔴 = aktuální cena"
            )
            if np.isnan(_seps_eps0):
                st.info("Chybí TTM EPS₀ — simulace není dostupná.")
            else:
                _mc_mid = _sep["Mid"]
                _mc_g_sigma_default = round(
                    eps_g_std if not np.isnan(eps_g_std)
                    else float(_seps_metrics_cagr("EPS CAGR", "5 let", 8.0)) * 0.4, 1
                )
                if not np.isnan(eps_g_std):
                    _mc_g_sigma_help = (
                        "Co je σ (sigma)?\n"
                        "Odhadovaná nepřesnost tvoé projekce růstu EPS.\n"
                        "Vyšší σ = v simulaci vyšší šance extrémních výsledků.\n"
                        "\n"
                        "Z čeho se počítá:\n"
                        "Historická směrodatná odchylka YoY tempa růstu EPS.\n"
                        f"Předvyplněna: {_mc_g_sigma_default:.1f} pp (z ročních dat EPS, max 7 let, cap 30 pp).\n"
                        "\n"
                        "Tahak pro ruční úpravu:\n"
                        "  2–5 pp • konzistentní EPS růst (Apple, MSFT)\n"
                        "  5–15 pp • průměrná firma\n"
                        "  15+ pp • volatilní EPS (cyklické firmy)"
                    )
                else:
                    _mc_g_sigma_help = (
                        "Co je σ (sigma)?\n"
                        "Odhadovaná nepřesnost tvoé projekce růstu EPS.\n"
                        "\n"
                        "Použita záložní metoda (EPS obsahuje \u2264 0 nebo málo dat):\n"
                        f"Předvyplněna: {_mc_g_sigma_default:.1f} pp (= 5letý EPS CAGR \u00d7 0,4, max 7 let dat).\n"
                        "\n"
                        "Tahak pro ruční úpravu:\n"
                        "  2–5 pp • konzistentní EPS růst (Apple, MSFT)\n"
                        "  5–15 pp • průměrná firma\n"
                        "  15+ pp • volatilní EPS (cyklické firmy)"
                    )
                _mc_pe_range = max(5.0, _mc_mid["pe"] * 0.3)

                _mc1_c1, _mc1_c2, _mc1_c3 = st.columns(3)
                with _mc1_c1:
                    st.markdown("**EPS growth g (%)**")
                    _mc1_g_mu  = st.number_input("Průměr g", value=float(_mc_mid["g"]),
                                                  key="mc_seps_g_mu", format="%.1f")
                    _mc1_g_sig = st.number_input("Std. odch. σ",
                                                  value=max(0.1, _mc_g_sigma_default),
                                                  min_value=0.1, key="mc_seps_g_sig",
                                                  format="%.1f",
                                                  help=_mc_g_sigma_help)
                    st.caption(f"💡 90 % simulací: {_mc1_g_mu - 1.645 * _mc1_g_sig:.1f}\u2013{_mc1_g_mu + 1.645 * _mc1_g_sig:.1f} %")
                with _mc1_c2:
                    st.markdown("**Terminal P/E**")
                    _mc1_pe_lo = st.number_input("Min P/E", value=max(5.0, _mc_mid["pe"] - _mc_pe_range),
                                                  key="mc_seps_pe_lo", format="%.1f")
                    _mc1_pe_hi = st.number_input("Max P/E", value=min(80.0, _mc_mid["pe"] + _mc_pe_range),
                                                  key="mc_seps_pe_hi", format="%.1f")
                    st.caption("Rovnoměrné rozdělení (uniform)")
                with _mc1_c3:
                    st.markdown("**Diskontní sazba r (%) — fixní**")
                    _mc1_r_fixed = st.number_input("r (fixní)", value=float(_mc_mid["r"]),
                                                    key="mc_seps_r_fixed", format="%.1f",
                                                    help=(
                                                        "🔒 Diskontní sazba je záměrně fixní.\n"
                                                        "Důvod: r ovlivňuje FV přes (1+r)^n — i malá\n"
                                                        "variace r produkuje extrémně asymetrické\n"
                                                        "rozdělení FV, obtížně interpretovatelné.\n"
                                                        "Vliv r na FV zobrazuje Tornado graf výše."
                                                    ))

                _mc1_n    = int(_mc_mid["n"])
                _mc1_nsim = st.select_slider("Počet simulací", [1_000, 5_000, 10_000, 25_000],
                                              value=10_000, key="mc_seps_nsim")

                if st.button("▶ Spustit simulaci", key="mc_seps_run"):
                    def _mc_seps_fv(g, pe, r):
                        if np.isnan(_seps_eps0) or _mc1_n <= 0 or r <= -100:
                            return np.nan
                        try:
                            ep_n = _seps_eps0 * (1.0 + g / 100.0) ** _mc1_n
                            fv   = (ep_n * pe) / (1.0 + r / 100.0) ** _mc1_n
                            return fv if np.isfinite(fv) else np.nan
                        except Exception:
                            return np.nan

                    _mc1_specs = [
                        {"name": "g",  "dist": "normal",  "mean": _mc1_g_mu, "std": _mc1_g_sig},
                        {"name": "pe", "dist": "uniform", "low": _mc1_pe_lo, "high": _mc1_pe_hi},
                        {"name": "r",  "dist": "fixed",   "value": _mc1_r_fixed},
                    ]
                    with st.spinner(f"Probíhá {_mc1_nsim:,} simulací..."):
                        _mc1_res = run_monte_carlo(_mc_seps_fv, _mc1_specs,
                                                   n_sim=_mc1_nsim,
                                                   current_price=_seps_price)
                    if _mc1_res:
                        render_mc_chart(_mc1_res, _seps_price, "EPS Growth")
                    else:
                        st.warning("Simulace nevygenerovala platné výsledky.")

        # ── Monte Carlo — Revenue Growth ───────────────────────────────────────
        if _seps_submodel == "Revenue Growth":
          with st.expander("🎲 Monte Carlo simulace — Revenue Growth", expanded=False):
            st.caption(
                "Simultánní náhodná variace g, čisté marže a Terminal P/E. "
                "Diskontní sazba r je fixní. "
                "σ předvyplněno z historické volatility (lze přepsat). "
                "🟡 = percentily  |  ━ = P50  |  🔴 = aktuální cena"
            )
            if np.isnan(_seps_rev0_m) or np.isnan(_seps_sh_m) or _seps_sh_m <= 0:
                st.info("Chybí TTM Revenue nebo Shares.")
            else:
                _mcr_mid = _srv["Mid"]
                _mcr_g_sigma  = max(2.0, round(float(_mcr_mid["g"] * rev_gcv) if (
                    not np.isnan(rev_gcv) and rev_gcv > 0) else 3.0, 1))
                _mcr_nm_sigma = round(float(pm_std) if not np.isnan(pm_std) else 2.0, 1)
                _mcr_pe_rng   = max(5.0, _mcr_mid["pe"] * 0.3)

                _mcrc1, _mcrc2, _mcrc3, _mcrc4 = st.columns(4)
                with _mcrc1:
                    st.markdown("**Revenue growth g (%)**")
                    _mcr_g_mu  = st.number_input("Průměr g", value=float(_mcr_mid["g"]),
                                                  key="mc_srev_g_mu", format="%.1f")
                    _mcr_g_sig = st.number_input("σ g", value=max(0.1, _mcr_g_sigma),
                                                  min_value=0.1, key="mc_srev_g_sig",
                                                  format="%.1f",
                                                  help=(
                                                      "Co je σ (sigma)?\n"
                                                      "Odhadovaná nepřesnost tvoé projekce růstu.\n"
                                                      "Vyšší σ = v simulaci vyšší šance extrémních výsledků.\n"
                                                      "\n"
                                                      "Z čeho se počítá:\n"
                                                      "Historická kolisavost tržeb (koeficient variace).\n"
                                                      f"Předvyplněna: {_mcr_g_sigma:.1f} pp z dat Revenue (max 7 let).\n"
                                                      "Minimální podlaha: 2 pp (i stabilní firma má riziko).\n"
                                                      "\n"
                                                      "Tahak pro ruční úpravu:\n"
                                                      "  1–3 pp • stabilní (utility, spotrební zboží)\n"
                                                      "  3–7 pp • běžné firmy (tech, průmysl)\n"
                                                      "  7–15+ pp • cyklické / rychle rostouci startups"
                                                  ))
                    st.caption(f"💡 90 % simulací: {_mcr_g_mu - 1.645 * _mcr_g_sig:.1f}–{_mcr_g_mu + 1.645 * _mcr_g_sig:.1f} %")
                with _mcrc2:
                    st.markdown("**Čistá marže (%)**")
                    _mcr_nm_mu  = st.number_input("Průměr marže", value=float(_mcr_mid["nm"]),
                                                   key="mc_srev_nm_mu", format="%.1f")
                    _mcr_nm_sig = st.number_input("σ marže", value=max(0.1, _mcr_nm_sigma),
                                                   min_value=0.1, key="mc_srev_nm_sig",
                                                   format="%.1f",
                                                   help=(
                                                       "Co je σ (sigma)?\n"
                                                       "Nepřesnost tvoé projekce čisté marže.\n"
                                                       "Vyšší σ = větší kolebání marže v simulaci.\n"
                                                       "\n"
                                                       "Z čeho se počítá:\n"
                                                       "Historická směrodatná odchylka Profit Margin.\n"
                                                       f"Předvyplněna: {_mcr_nm_sigma:.1f} pp z dat (max 7 let).\n"
                                                       "\n"
                                                       "Tahak pro ruční úpravu:\n"
                                                       "  1–2 pp • extrémně stabilní marže\n"
                                                       "  2–5 pp • běžná firma\n"
                                                       "  5–10+ pp • cyklická / nestabilní marže"
                                                   ))
                    st.caption(f"💡 90 % simulací: {_mcr_nm_mu - 1.645 * _mcr_nm_sig:.1f}–{_mcr_nm_mu + 1.645 * _mcr_nm_sig:.1f} %")
                with _mcrc3:
                    st.markdown("**Terminal P/E**")
                    _mcr_pe_lo  = st.number_input("Min P/E", value=max(5.0, _mcr_mid["pe"] - _mcr_pe_rng),
                                                   key="mc_srev_pe_lo", format="%.1f")
                    _mcr_pe_hi  = st.number_input("Max P/E", value=min(80.0, _mcr_mid["pe"] + _mcr_pe_rng),
                                                   key="mc_srev_pe_hi", format="%.1f")
                    st.caption("Rovnoměrné rozdělení (uniform)")
                with _mcrc4:
                    st.markdown("**Diskontní sazba r (%) — fixní**")
                    _mcr_r_fixed = st.number_input("r (fixní)", value=float(_mcr_mid["r"]),
                                                    key="mc_srev_r_fixed", format="%.1f",
                                                    help=(
                                                        "🔒 Diskontní sazba je záměrně fixní.\n"
                                                        "Důvod: r ovlivňuje FV přes (1+r)^n — i malá\n"
                                                        "variace r produkuje extrémně asymetrické\n"
                                                        "rozdělení FV, obtížně interpretovatelné.\n"
                                                        "Vliv r na FV zobrazuje Tornado graf výše."
                                                    ))

                _mcr_n    = int(_mcr_mid["n"])
                _mcr_nsim = st.select_slider("Počet simulací", [1_000, 5_000, 10_000, 25_000],
                                              value=10_000, key="mc_srev_nsim")

                if st.button("▶ Spustit simulaci", key="mc_srev_run"):
                    _mcr_rev0 = _seps_rev0_m
                    _mcr_sh_m = _seps_sh_m

                    def _mc_srev_fv(g, nm, pe, r):
                        try:
                            if _mcr_n <= 0 or _mcr_sh_m <= 0:
                                return np.nan
                            rev_n = _mcr_rev0 * (1.0 + g / 100.0) ** _mcr_n
                            eps_n = rev_n * 1e6 * (nm / 100.0) / (_mcr_sh_m * 1e6)
                            fv    = (eps_n * pe) / (1.0 + r / 100.0) ** _mcr_n
                            return fv if np.isfinite(fv) else np.nan
                        except Exception:
                            return np.nan

                    _mcr_specs = [
                        {"name": "g",  "dist": "normal",  "mean": _mcr_g_mu,  "std": _mcr_g_sig},
                        {"name": "nm", "dist": "normal",  "mean": _mcr_nm_mu, "std": _mcr_nm_sig},
                        {"name": "pe", "dist": "uniform", "low": _mcr_pe_lo,  "high": _mcr_pe_hi},
                        {"name": "r",  "dist": "fixed",   "value": _mcr_r_fixed},
                    ]
                    with st.spinner(f"Probíhá {_mcr_nsim:,} simulací..."):
                        _mcr_res = run_monte_carlo(_mc_srev_fv, _mcr_specs,
                                                   n_sim=_mcr_nsim,
                                                   current_price=_seps_price)
                    if _mcr_res:
                        render_mc_chart(_mcr_res, _seps_price, "Revenue Growth")
                    else:
                        st.warning("Simulace nevygenerovala platné výsledky.")

        # ── Tornado sensitivity ────────────────────────────────────────────────
        with st.expander("🌪️ Analýza citlivosti (Tornado)", expanded=False):
            st.caption(
                "🌪️ Tornado = citlivost one-at-a-time. Žlutá čára = baseline FV zvoleného scénáře. "
                "🟥 Červená = nižší FV výsledek  |  🟩 Zelená = vyšší FV výsledek. "
                "Delší pruh = větší citlivost. "
                "Δ pp (absolutně): r, Net Margin, g — posun o pevný počet % bodů. "
                "Δ % (relativně): Terminal P/E — násobení hodnoty. "
                "Tornado mění vždy jen 1 parametr — neukazuje kombinace."
            )
            _t_sub = st.radio(
                "Sub-model pro tornado:",
                ["EPS Growth", "Revenue Growth"],
                horizontal=True,
                key="tornado_seps_submodel",
            )
            _t_sn_seps = st.selectbox(
                "Základní scénář:", ["Low", "Mid", "High"],
                index=1, key="tornado_seps_scenario",
            )
            _t_delta_pp   = st.number_input("Δ sazeb / marží – ± pp (r, Net Margin, absolutně)", value=1.0, min_value=0.1, max_value=10.0, step=0.1, format="%.1f", key="tornado_seps_delta_pp")
            _t_delta_g_pp = st.number_input("Δg – ± pp (EPS/Revenue growth g, absolutně v % bodech)", value=1.0, min_value=0.5, max_value=20.0, step=0.5, format="%.1f", key="tornado_seps_delta_g")
            _t_delta_rel  = st.number_input("Δ PE – absolutní delta násobku (Terminal P/E)", value=5.0, min_value=0.5, max_value=50.0, step=0.5, format="%.1f", key="tornado_seps_delta_rel")

            try:
                if _t_sub == "EPS Growth":
                    _tb_g   = _sep[_t_sn_seps]["g"]
                    _tb_pe  = _sep[_t_sn_seps]["pe"]
                    _tb_r   = _sep[_t_sn_seps]["r"]
                    _tb_n   = int(_sep[_t_sn_seps]["n"])
                    st.caption(f"Scénář {_t_sn_seps}: g = {_tb_g:.1f} %  |  P/E = {_tb_pe:.1f}  |  r = {_tb_r:.1f} %  |  n = {_tb_n} let")
                    def _seps_fv(g_pct, pe, r_pct, n):
                        if np.isnan(_seps_eps0) or n <= 0: return np.nan
                        _ep_n = _seps_eps0 * (1.0 + g_pct / 100.0) ** n
                        return (_ep_n * pe) / (1.0 + r_pct / 100.0) ** n
                    _t_base_fv = _seps_fv(_tb_g, _tb_pe, _tb_r, _tb_n)
                    if not np.isnan(_t_base_fv):
                        _t_impacts = []
                        for _pname, _lo_v, _hi_v in [
                            (f"EPS growth g (±{_t_delta_g_pp:.1f}pp)",   _seps_fv(_tb_g - _t_delta_g_pp, _tb_pe,  _tb_r,          _tb_n),
                                                   _seps_fv(_tb_g + _t_delta_g_pp, _tb_pe,  _tb_r,          _tb_n)),
                            (f"Terminal P/E (±{_t_delta_rel:.1f})",       _seps_fv(_tb_g, max(0.5, _tb_pe - _t_delta_rel), _tb_r, _tb_n),
                                                   _seps_fv(_tb_g, _tb_pe + _t_delta_rel, _tb_r, _tb_n)),
                            (f"Discount rate r (±{_t_delta_pp:.1f}pp)", _seps_fv(_tb_g, _tb_pe, _tb_r + _t_delta_pp,  _tb_n),
                                                   _seps_fv(_tb_g, _tb_pe, _tb_r - _t_delta_pp,  _tb_n)),
                            ("Years n (±1)",            _seps_fv(_tb_g, _tb_pe, _tb_r, max(1, _tb_n - 1)),
                                                   _seps_fv(_tb_g, _tb_pe, _tb_r, _tb_n + 1)),
                        ]:
                            if not (np.isnan(_lo_v) or np.isnan(_hi_v)):
                                _t_impacts.append({"Parametr": _pname, "Nízká": _lo_v, "Vysoká": _hi_v,
                                                   "RozsahAbs": abs(_hi_v - _lo_v)})
                        if _t_impacts:
                            _t_df = pd.DataFrame(_t_impacts).sort_values("RozsahAbs", ascending=False)
                            _t_df["Baseline"] = _t_base_fv
                            _t_df["FV_nizka"] = _t_df["Nízká"]
                            _t_df["FV_vysoka"] = _t_df["Vysoká"]
                            _t_df["DiffLo"] = _t_df["Nízká"] - _t_base_fv
                            _t_df["DiffHi"] = _t_df["Vysoká"] - _t_base_fv
                            _t_long_rows = []
                            for _, _r in _t_df.iterrows():
                                _bl = float(_r["Baseline"])
                                _dl = float(_r["DiffLo"]); _dh = float(_r["DiffHi"])
                                _dlp = (_dl / _bl * 100) if _bl else 0.0
                                _dhp = (_dh / _bl * 100) if _bl else 0.0
                                _range_dollar = f"{_dl:+.2f}$ / {_dh:+.2f}$"
                                _range_pct    = f"{_dlp:+.1f}% / {_dhp:+.1f}%"
                                for _dc, _fc, _lbl in [("DiffLo","FV_nizka","Nižší FV"),("DiffHi","FV_vysoka","Vyšší FV")]:
                                    _da = float(_r[_dc])
                                    _t_long_rows.append({"Parametr": str(_r["Parametr"]), "DiffAbs": _da,
                                        "DiffPct": round(_da / _bl * 100, 2) if _bl else 0.0,
                                        "Baseline": _bl, "FV_nizka": float(_r["FV_nizka"]),
                                        "FV_vysoka": float(_r["FV_vysoka"]), "StranaCZ": _lbl,
                                        "BarColor": "#66BB6A" if _da >= 0 else "#FF7043",
                                        "RangeDollar": _range_dollar, "RangePct": _range_pct})
                            _t_sort = list(_t_df["Parametr"])
                            _t_h = max(150, len(_t_impacts) * 50)
                            _t_sort_tt = [
                                {"field": "Parametr", "type": "nominal"},
                                {"field": "StranaCZ", "type": "nominal", "title": "Výsledek"},
                                {"field": "Baseline", "type": "quantitative", "format": "$.2f", "title": "Baseline FV ($)"},
                                {"field": "FV_nizka", "type": "quantitative", "format": "$.2f", "title": "FV nižší ($)"},
                                {"field": "FV_vysoka", "type": "quantitative", "format": "$.2f", "title": "FV vysoká ($)"},
                                {"field": "RangeDollar", "type": "nominal", "title": "Δ nízká / vysoká ($)"},
                                {"field": "RangePct", "type": "nominal", "title": "Δ nízká / vysoká (%)"},
                            ]
                            st.vega_lite_chart({
                                "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
                                "height": _t_h,
                                "title": f"Tornado: EPS Growth — {_t_sn_seps} scénář",
                                "config": {"view": {"strokeOpacity": 0}},
                                "layer": [
                                    {"data": {"values": [r for r in _t_long_rows if r["DiffAbs"] >= 0]}, "mark": {"type": "bar", "opacity": 0.75, "color": "#66BB6A"}, "encoding": {"y": {"field": "Parametr", "type": "nominal", "sort": _t_sort, "title": None, "axis": {"labelOverlap": False, "labelLimit": 300}}, "x": {"field": "DiffAbs", "type": "quantitative", "title": "Δ Fair Value vs baseline ($)", "axis": {"grid": True}}, "tooltip": _t_sort_tt}},
                                    {"data": {"values": [r for r in _t_long_rows if r["DiffAbs"] < 0]}, "mark": {"type": "bar", "opacity": 0.75, "color": "#FF7043"}, "encoding": {"y": {"field": "Parametr", "type": "nominal", "sort": _t_sort}, "x": {"field": "DiffAbs", "type": "quantitative"}, "tooltip": _t_sort_tt}},
                                    {"data": {"values": _t_long_rows}, "transform": [{"calculate": "format(datum.DiffPct, '+.1f') + '%'", "as": "_dp_label"}], "mark": {"type": "text", "fontSize": 10, "align": {"expr": "datum.DiffAbs >= 0 ? 'left' : 'right'"}, "dx": {"expr": "datum.DiffAbs >= 0 ? 4 : -4"}}, "encoding": {"y": {"field": "Parametr", "type": "nominal", "sort": _t_sort}, "x": {"field": "DiffAbs", "type": "quantitative"}, "text": {"field": "_dp_label", "type": "nominal"}, "color": {"value": "#93a3b8"}, "tooltip": _t_sort_tt}},
                                    {"data": {"values": [{"x": 0}]}, "mark": {"type": "rule", "color": "#FFD54F", "strokeDash": [4, 2]}, "encoding": {"x": {"field": "x", "type": "quantitative"}}},
                                ],
                            }, width='stretch')
                            _t_price_txt = f"  |  Aktuální cena: ${_seps_price:.2f}" if not np.isnan(_seps_price) else ""
                            st.caption(f"Baseline FV = ${_t_base_fv:.2f}{_t_price_txt}. Pruhy = Δ vs baseline. Žlutá čára = 0.")
                        else:
                            st.info("Nelze vypočítat tornado (chybí data).")
                    else:
                        st.info("Základní FV není dostupné (chybí EPS0).")
                else:  # Revenue Growth
                    _tb_g_rv  = _srv[_t_sn_seps]["g"]
                    _tb_nm    = _srv[_t_sn_seps]["nm"]
                    _tb_pe_rv = _srv[_t_sn_seps]["pe"]
                    _tb_r_rv  = _srv[_t_sn_seps]["r"]
                    _tb_n_rv  = int(_srv[_t_sn_seps]["n"])
                    st.caption(f"Scénář {_t_sn_seps}: g = {_tb_g_rv:.1f} %  |  Net Margin = {_tb_nm:.1f} %  |  P/E = {_tb_pe_rv:.1f}  |  r = {_tb_r_rv:.1f} %  |  n = {_tb_n_rv} let")
                    def _srev_fv(g_pct, nm_pct, pe, r_pct, n):
                        if np.isnan(_seps_rev0_m) or np.isnan(_seps_sh_m) or _seps_sh_m <= 0 or n <= 0: return np.nan
                        _rn = _seps_rev0_m * (1.0 + g_pct / 100.0) ** n
                        _ep_n = _rn * 1e6 * (nm_pct / 100.0) / (_seps_sh_m * 1e6)
                        return (_ep_n * pe) / (1.0 + r_pct / 100.0) ** n
                    _t_base_fv = _srev_fv(_tb_g_rv, _tb_nm, _tb_pe_rv, _tb_r_rv, _tb_n_rv)
                    if not np.isnan(_t_base_fv):
                        _t_impacts = []
                        for _pname, _lo_v, _hi_v in [
                            (f"Revenue growth g (±{_t_delta_g_pp:.1f}pp)", _srev_fv(_tb_g_rv - _t_delta_g_pp, _tb_nm, _tb_pe_rv, _tb_r_rv, _tb_n_rv),
                                                     _srev_fv(_tb_g_rv + _t_delta_g_pp, _tb_nm, _tb_pe_rv, _tb_r_rv, _tb_n_rv)),
                            (f"Net Margin (±{_t_delta_pp:.1f}pp)",        _srev_fv(_tb_g_rv, _tb_nm - _t_delta_pp, _tb_pe_rv, _tb_r_rv, _tb_n_rv),
                                                     _srev_fv(_tb_g_rv, _tb_nm + _t_delta_pp, _tb_pe_rv, _tb_r_rv, _tb_n_rv)),
                            (f"Terminal P/E (±{_t_delta_rel:.1f})",          _srev_fv(_tb_g_rv, _tb_nm, max(0.5, _tb_pe_rv - _t_delta_rel), _tb_r_rv, _tb_n_rv),
                                                     _srev_fv(_tb_g_rv, _tb_nm, _tb_pe_rv + _t_delta_rel, _tb_r_rv, _tb_n_rv)),
                            (f"Discount rate r (±{_t_delta_pp:.1f}pp)",   _srev_fv(_tb_g_rv, _tb_nm, _tb_pe_rv, _tb_r_rv + _t_delta_pp, _tb_n_rv),
                                                     _srev_fv(_tb_g_rv, _tb_nm, _tb_pe_rv, _tb_r_rv - _t_delta_pp, _tb_n_rv)),
                        ]:
                            if not (np.isnan(_lo_v) or np.isnan(_hi_v)):
                                _t_impacts.append({"Parametr": _pname, "Nízká": _lo_v, "Vysoká": _hi_v,
                                                   "RozsahAbs": abs(_hi_v - _lo_v)})
                        if _t_impacts:
                            _t_df = pd.DataFrame(_t_impacts).sort_values("RozsahAbs", ascending=False)
                            _t_df["Baseline"] = _t_base_fv
                            _t_df["FV_nizka"] = _t_df["Nízká"]
                            _t_df["FV_vysoka"] = _t_df["Vysoká"]
                            _t_df["DiffLo"] = _t_df["Nízká"] - _t_base_fv
                            _t_df["DiffHi"] = _t_df["Vysoká"] - _t_base_fv
                            _t_long_rows = []
                            for _, _r in _t_df.iterrows():
                                _bl = float(_r["Baseline"])
                                _dl = float(_r["DiffLo"]); _dh = float(_r["DiffHi"])
                                _dlp = (_dl / _bl * 100) if _bl else 0.0
                                _dhp = (_dh / _bl * 100) if _bl else 0.0
                                _range_dollar = f"{_dl:+.2f}$ / {_dh:+.2f}$"
                                _range_pct    = f"{_dlp:+.1f}% / {_dhp:+.1f}%"
                                for _dc, _fc, _lbl in [("DiffLo","FV_nizka","Nižší FV"),("DiffHi","FV_vysoka","Vyšší FV")]:
                                    _da = float(_r[_dc])
                                    _t_long_rows.append({"Parametr": str(_r["Parametr"]), "DiffAbs": _da,
                                        "DiffPct": round(_da / _bl * 100, 2) if _bl else 0.0,
                                        "Baseline": _bl, "FV_nizka": float(_r["FV_nizka"]),
                                        "FV_vysoka": float(_r["FV_vysoka"]), "StranaCZ": _lbl,
                                        "BarColor": "#66BB6A" if _da >= 0 else "#FF7043",
                                        "RangeDollar": _range_dollar, "RangePct": _range_pct})
                            _t_sort = list(_t_df["Parametr"])
                            _t_h = max(150, len(_t_impacts) * 50)
                            _t_sort_tt = [
                                {"field": "Parametr", "type": "nominal"},
                                {"field": "StranaCZ", "type": "nominal", "title": "Výsledek"},
                                {"field": "Baseline", "type": "quantitative", "format": "$.2f", "title": "Baseline FV ($)"},
                                {"field": "FV_nizka", "type": "quantitative", "format": "$.2f", "title": "FV nižší ($)"},
                                {"field": "FV_vysoka", "type": "quantitative", "format": "$.2f", "title": "FV vysoká ($)"},
                                {"field": "RangeDollar", "type": "nominal", "title": "Δ nízká / vysoká ($)"},
                                {"field": "RangePct", "type": "nominal", "title": "Δ nízká / vysoká (%)"},
                            ]
                            st.vega_lite_chart({
                                "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
                                "height": _t_h,
                                "title": f"Tornado: Revenue Growth — {_t_sn_seps} scénář",
                                "config": {"view": {"strokeOpacity": 0}},
                                "layer": [
                                    {"data": {"values": [r for r in _t_long_rows if r["DiffAbs"] >= 0]}, "mark": {"type": "bar", "opacity": 0.75, "color": "#66BB6A"}, "encoding": {"y": {"field": "Parametr", "type": "nominal", "sort": _t_sort, "title": None, "axis": {"labelOverlap": False, "labelLimit": 300}}, "x": {"field": "DiffAbs", "type": "quantitative", "title": "Δ Fair Value vs baseline ($)", "axis": {"grid": True}}, "tooltip": _t_sort_tt}},
                                    {"data": {"values": [r for r in _t_long_rows if r["DiffAbs"] < 0]}, "mark": {"type": "bar", "opacity": 0.75, "color": "#FF7043"}, "encoding": {"y": {"field": "Parametr", "type": "nominal", "sort": _t_sort}, "x": {"field": "DiffAbs", "type": "quantitative"}, "tooltip": _t_sort_tt}},
                                    {"data": {"values": _t_long_rows}, "transform": [{"calculate": "format(datum.DiffPct, '+.1f') + '%'", "as": "_dp_label"}], "mark": {"type": "text", "fontSize": 10, "align": {"expr": "datum.DiffAbs >= 0 ? 'left' : 'right'"}, "dx": {"expr": "datum.DiffAbs >= 0 ? 4 : -4"}}, "encoding": {"y": {"field": "Parametr", "type": "nominal", "sort": _t_sort}, "x": {"field": "DiffAbs", "type": "quantitative"}, "text": {"field": "_dp_label", "type": "nominal"}, "color": {"value": "#93a3b8"}, "tooltip": _t_sort_tt}},
                                    {"data": {"values": [{"x": 0}]}, "mark": {"type": "rule", "color": "#FFD54F", "strokeDash": [4, 2]}, "encoding": {"x": {"field": "x", "type": "quantitative"}}},
                                ],
                            }, width='stretch')
                            _t_price_txt = f"  |  Aktuální cena: ${_seps_price:.2f}" if not np.isnan(_seps_price) else ""
                            st.caption(f"Baseline FV = ${_t_base_fv:.2f}{_t_price_txt}. Pruhy = Δ vs baseline. Žlutá čára = 0.")
                        else:
                            st.info("Nelze vypočítat tornado (chybí data).")
                    else:
                        st.info("Základní FV není dostupné (chybí Revenue/Shares).")
            except Exception as _t_exc_seps:
                st.warning(f"Tornado nelze zobrazit: {_t_exc_seps}")

        # ── Equations ─────────────────────────────────────────────────────────
        with st.expander("📐 Equations – Simple EPS / Revenue Growth (click to expand)"):
            st.markdown(r"""
**Sub-model A – EPS Growth:**

$$
EPS_t = EPS_0 \times (1 + g_{EPS})^t
$$

$$
\text{Future Price}_n = EPS_n \times P/E_{terminal}
$$

$$
\text{Fair Value} = \frac{\text{Future Price}_n}{(1 + r)^n}
$$

$$
\text{CAGR} = \left(\frac{\text{Future Price}_n}{\text{Current Price}}\right)^{1/n} - 1
$$

$$
\text{Upside/Downside} = \frac{\text{Fair Value}}{\text{Current Price}} - 1
$$

---

**Sub-model B – Revenue Growth:**

$$
Revenue_t = Revenue_0 \times (1 + g_{Rev})^t
$$

$$
EPS_t = \frac{Revenue_t \times \text{Net Margin}}{\text{Shares Outstanding}}
$$

$$
\text{Future Price}_n = EPS_n \times P/E_{terminal}
$$

$$
\text{Fair Value} = \frac{\text{Future Price}_n}{(1 + r)^n}
$$

---

*$g$, $r$ jsou zadávány v procentech a před výpočtem děleny 100.*
*$EPS_0$ a $Revenue_0$ jsou TTM hodnoty z tabulky Valuace.*
            """)

    # ── Tab 2: Simple Valuation – Damodaran-style (STEP 3) ───────────
    with _val_tabs[1]:
        _t1_tip = _tooltip_attr(
            "Popis: 2-stage FCFF DCF model (Free Cash Flow to Firm).\n"
            "Vhodné typy firem: Průmyslové firmy, zralé tech firmy, firmy s pozitivním a predikovatelbným NOPAT/FCF.\n"
            "NEVHODNÉ pro: Banky, pojišťovny, firmy se záporným operating income.\n"
            "Výhody: Zahrnuje WACC, reinvestiční sazbu (g/ROIC), terminální hodnotu (Gordon). Explicitní EV → Equity bridge.\n"
            "Na co si dát pozor: Net Income TTM použit jako NOPAT proxy. Podmínka WACC > g_terminal musí platit. Vysoká citlivost na WACC."
        )
        st.markdown(
            f"<h3>Simple Valuation (Damodaran-style) "
            f"<span title='{_t1_tip}' style='cursor:help;color:#93a3b8;border-bottom:1px dotted #93a3b8;font-size:14px;'>ⓘ</span>"
            f"</h3>",
            unsafe_allow_html=True,
        )
        with st.expander("ℹ️ O tomto modelu", expanded=False):
            st.markdown("""
| | |
|---|---|
| **Popis** | 2-stage FCFF model. Explicitní horizont + Gordon terminální hodnota. |
| **Vhodné typy firem** | Průmyslové firmy, reálná ekonomika, zralé tech firmy. Firmy s měřitelným NOPAT a jasným reinvestičním profilem. |
| **NEVHODNÉ pro** | Banky a pojišťovny (jiné reinvestiční logiky). Firmy se záporným Net Income / NOPAT. |
| **Výhody** | Zahrnuje ROIC a reinvestiční sazbu (RR = g/ROIC) – růst tvoří nebo ničí hodnotu. EV → Equity bridge (Dluh – Cash). |
| **Na co si dát pozor** | Net Income TTM je zjednodušení pro NOPAT. WACC > g_terminal je nutná podmínka. Vysoká citlivost na oba vstupy. |
            """)

        # ── Base values from effective_df ─────────────────────────────────
        def _dam_ttm(col, default=np.nan):
            try:
                v = _safe_float(effective_df.loc["TTM", col])
                return v if not np.isnan(v) else default
            except Exception:
                return default

        _dam_ni_m   = _dam_ttm("Net Income [M]", np.nan)   # NOPAT₀ proxy
        _dam_debt_m = _dam_ttm("Long term debt [M]", 0.0)
        _dam_cash_ttm = _dam_ttm("Cash [M]", 0.0)
        _dam_sh_m   = _dam_ttm("Shares Outstanding [M]", np.nan)
        _dam_price  = _dam_ttm("Stock Price", np.nan)
        _dam_roic_d = _dam_ttm("ROI", np.nan)

        _dam_def_roic = _dam_roic_d
        if np.isnan(_dam_def_roic):
            try:
                _rv2 = [_safe_float(metrics_df.loc["ROI", c]) for c in metrics_df.columns
                        if "ROI" in metrics_df.index]
                _rv2 = [v for v in _rv2 if not np.isnan(v)]
                _dam_def_roic = float(np.mean(_rv2)) if _rv2 else 15.0
            except Exception:
                _dam_def_roic = 15.0
        _dam_def_roic = max(1.0, _dam_def_roic)

        def _dam_metrics_cagr(row_label, col_label="5 let", default=8.0):
            try:
                v = _safe_float(metrics_df.loc[row_label, col_label])
                return (v * 100.0) if not np.isnan(v) else default
            except Exception:
                return default

        _dam_def_g = _dam_metrics_cagr("Revenue CAGR", "5 let", 8.0)

        # ── Session state init ─────────────────────────────────────────────
        _DAM_KEY = "damodaran_params"
        if _DAM_KEY not in st.session_state:
            st.session_state[_DAM_KEY] = {
                "scenarios": {
                    "Low":  {"g": max(0.0, round(_dam_def_g * 0.5, 1)),
                             "roic": round(max(1.0, _dam_def_roic * 0.7), 1),
                             "r": 12.0, "n": 10},
                    "Mid":  {"g": round(_dam_def_g, 1),
                             "roic": round(_dam_def_roic, 1),
                             "r": 12.0, "n": 10},
                    "High": {"g": min(40.0, round(_dam_def_g * 1.5, 1)),
                             "roic": min(60.0, round(_dam_def_roic * 1.3, 1)),
                             "r": 12.0, "n": 10},
                },
                "tax":    21.0,
                "g_term": 2.5,
                "cash_m": _dam_cash_ttm if not np.isnan(_dam_cash_ttm) else 0.0,
            }

        _dp     = st.session_state[_DAM_KEY]
        _dp_sc  = _dp["scenarios"]
        _SC_LABELS_D = ["Low", "Mid", "High"]
        _SC_COLORS_D = {"Low": "#FF7043", "Mid": "#FFD54F", "High": "#66BB6A"}

        # ── Base values info ───────────────────────────────────────────────
        _dam_debt_m_used = _dam_debt_m if not np.isnan(_dam_debt_m) else 0.0

        st.markdown(
            "<div style='font-size:12px;color:#93a3b8;margin-bottom:8px;'>"
            "Vstupy automaticky doplněny z tabulky Valuace (TTM) — všechny hodnoty lze ručně přepsat."
            "</div>",
            unsafe_allow_html=True,
        )

        _bv_c1, _bv_c2, _bv_c3, _bv_c4 = st.columns(4)
        with _bv_c1:
            _dam_ni_m = st.number_input(
                "NOPAT₀ (Net Income TTM) [M$]",
                value=float(_dam_ni_m) if not np.isnan(_dam_ni_m) else 0.0,
                min_value=0.0, step=100.0, format="%.1f", key="dam_nopat_m")
        with _bv_c2:
            _dam_debt_m_used = st.number_input(
                "Debt [M$]",
                value=float(_dam_debt_m_used),
                min_value=0.0, step=100.0, format="%.1f", key="dam_debt_m_inp")
        with _bv_c3:
            _dam_sh_m = st.number_input(
                "Shares [M]",
                value=float(_dam_sh_m) if not np.isnan(_dam_sh_m) else 0.0,
                min_value=0.01, step=10.0, format="%.2f", key="dam_shares_m")
        with _bv_c4:
            _dam_price = st.number_input(
                "Current Price [$]",
                value=float(_dam_price) if not np.isnan(_dam_price) else 0.0,
                min_value=0.0, step=1.0, format="%.2f", key="dam_price_inp")

        # ── Shared inputs ─────────────────────────────────────────────────
        _sh2, _sh3 = st.columns(2)
        st.caption(
            "ℹ️ **Tax rate** se v tomto modelu nepoužívá – vstupní základnou je Net Income TTM, "
            "který je již po zdanění. Reinvestiční sazba (RR = g / ROI) proto vychází přímo z čistého zisku."
        )
        with _sh2:
            _dp["g_term"] = st.number_input(
                "Terminal growth g_term [%]", min_value=0.0, max_value=10.0,
                value=float(_dp["g_term"]), step=0.1, format="%.1f", key="dam_g_term")
        with _sh3:
            _dp["cash_m"] = st.number_input(
                "Cash [M$]", min_value=0.0,
                value=float(_dp["cash_m"]), step=10.0, format="%.0f", key="dam_cash")

        _dam_cash_m  = _dp["cash_m"]
        _dam_g_term  = _dp["g_term"] / 100.0

        # ── Per-scenario inputs (row-based layout) ──────────────────────────
        st.markdown("---")

        def _dam_input_row(label, key_suffix, mn, mx, stp, fmt, dict_key):
            _cols = st.columns([2.5, 2, 2, 2])
            with _cols[0]:
                st.markdown(
                    f"<div style='font-size:14px;font-weight:700;padding-top:8px'>{label}</div>",
                    unsafe_allow_html=True,
                )
            for _i, _sn in enumerate(["Low", "Mid", "High"]):
                with _cols[_i + 1]:
                    if isinstance(stp, float):
                        _clamped_val = min(max(float(_dp_sc[_sn][dict_key]), float(mn)), float(mx))
                        _dp_sc[_sn][dict_key] = st.number_input(
                            " ", min_value=float(mn), max_value=float(mx),
                            value=_clamped_val,
                            step=stp, format=fmt,
                            key=f"{key_suffix}_{_sn}",
                            label_visibility="collapsed",
                        )
                    else:
                        _dp_sc[_sn][dict_key] = st.number_input(
                            " ", min_value=int(mn), max_value=int(mx),
                            value=int(_dp_sc[_sn][dict_key]),
                            step=int(stp),
                            key=f"{key_suffix}_{_sn}",
                            label_visibility="collapsed",
                        )

        _dh0, _dh_low, _dh_mid, _dh_high = st.columns([2.5, 2, 2, 2])
        with _dh_low:
            st.markdown("<div style='font-weight:700;color:#FF7043;text-align:center'>Low</div>", unsafe_allow_html=True)
        with _dh_mid:
            st.markdown("<div style='font-weight:700;color:#FFD54F;text-align:center'>Mid</div>", unsafe_allow_html=True)
        with _dh_high:
            st.markdown("<div style='font-weight:700;color:#66BB6A;text-align:center'>High</div>", unsafe_allow_html=True)

        _dam_input_row("NOPAT growth g [%]", "dam_g",    -20.0, 60.0,  0.5, "%.1f", "g")
        _dam_input_row("ROIC proxy [%]",     "dam_roic",   1.0, 300.0, 0.5, "%.1f", "roic")
        _dam_input_row("WACC [%]",           "dam_r",      1.0,  50.0, 0.5, "%.1f", "r")
        _dam_input_row("Years n",            "dam_n",      1,    30,   1,   "%d",   "n")

        # ── Derived base year for charts ───────────────────────────────────
        _dam_hist_years = sorted(
            [int(y) for y in effective_df.index
             if str(y) != "TTM" and str(y).isdigit()]
        )
        _dam_fby = max(_dam_hist_years) if _dam_hist_years else (pd.Timestamp.today().year - 1)
        # Price anchor: last historical year's actual price (connects forecast to history endpoint visually)
        _dam_price_anchor = _dam_price
        if "Stock Price" in effective_df.columns:
            for _k in [_dam_fby, str(_dam_fby)]:
                try:
                    _v = _safe_float(effective_df.loc[_k, "Stock Price"])
                    if not np.isnan(_v):
                        _dam_price_anchor = _v
                        break
                except Exception:
                    pass

        # ── Compute ────────────────────────────────────────────────────────
        st.markdown("---")
        _dam_res: dict   = {}
        _dam_fcff_rows   = []
        _dam_price_fore  = []

        for _sn_d in _SC_LABELS_D:
            _g_d    = _dp_sc[_sn_d]["g"]    / 100.0
            _roic_d = _dp_sc[_sn_d]["roic"] / 100.0
            _r_d    = _dp_sc[_sn_d]["r"]    / 100.0
            _n_d    = int(_dp_sc[_sn_d]["n"])

            if any(np.isnan(x) for x in [_dam_ni_m, _dam_sh_m]) or _dam_sh_m <= 0:
                _dam_res[_sn_d] = None
                continue
            if _r_d <= _dam_g_term:
                _dam_res[_sn_d] = {"error": "WACC musí být > g_terminal"}
                continue

            _reinv_rate_d = min(1.0, max(0.0, _g_d / _roic_d))
            _dam_fcff_rows.append({"Year": str(_dam_fby), "Scenario": _sn_d, "fcff_m": _dam_ni_m * (1.0 - _reinv_rate_d)})

            _pv_fcff = 0.0
            for _t in range(1, _n_d + 1):
                _nopat_t = _dam_ni_m * (1.0 + _g_d) ** _t
                _fcff_t  = _nopat_t * (1.0 - _reinv_rate_d)
                _pv_fcff += _fcff_t / (1.0 + _r_d) ** _t
                _dam_fcff_rows.append({
                    "Year": str(_dam_fby + _t),
                    "Scenario": _sn_d,
                    "fcff_m": _fcff_t,
                })

            # Terminal value (Gordon)
            _nopat_n1     = _dam_ni_m * (1.0 + _g_d) ** _n_d * (1.0 + _dam_g_term)
            _rr_term      = min(1.0, max(0.0, _dam_g_term / _roic_d))
            _fcff_terminal = _nopat_n1 * (1.0 - _rr_term)
            _tv_m         = _fcff_terminal / (_r_d - _dam_g_term)
            _pv_tv        = _tv_m / (1.0 + _r_d) ** _n_d

            _ev_m     = _pv_fcff + _pv_tv
            _equity_m = _ev_m - _dam_debt_m_used + _dam_cash_m
            _iv_ps    = _equity_m / _dam_sh_m  # both in [M$] / [M shares] = $/share

            _mos_d  = (_iv_ps / _dam_price - 1.0) if (not np.isnan(_dam_price) and _dam_price > 0) else np.nan
            _cagr_d = (
                (_iv_ps / _dam_price) ** (1.0 / _n_d) - 1.0
                if (not np.isnan(_dam_price) and _dam_price > 0 and _n_d > 0 and _iv_ps > 0)
                else np.nan
            )

            _dam_res[_sn_d] = {
                "pv_fcff": _pv_fcff, "pv_tv": _pv_tv, "ev": _ev_m,
                "equity": _equity_m, "iv_ps": _iv_ps,
                "reinv_rate": _reinv_rate_d, "mos": _mos_d, "cagr": _cagr_d,
                "n": _n_d,
            }
            # price trajectory: TTM current price → year-n IV per share
            if not np.isnan(_dam_price):
                _dam_price_fore.append({"Year": str(_dam_fby), "Scenario": _sn_d, "Value": _dam_price_anchor})
            _dam_price_fore.append({"Year": str(_dam_fby + _n_d), "Scenario": _sn_d, "Value": _iv_ps})

        # ── Results cards ─────────────────────────────────────────────────
        _dam_has_res = any(
            _dam_res.get(_sn_d) and "error" not in _dam_res[_sn_d]
            for _sn_d in _SC_LABELS_D
        )
        for _sn_d in _SC_LABELS_D:
            _rd = _dam_res.get(_sn_d)
            if _rd and "error" in _rd:
                st.warning(f"Scénář {_sn_d}: {_rd['error']}")

        st.markdown("---")
        if _dam_has_res:
            _res_cols_d = st.columns(3)
            for _i_rd, _sn_d in enumerate(_SC_LABELS_D):
                _rd = _dam_res.get(_sn_d)
                with _res_cols_d[_i_rd]:
                    _clr_d = _SC_COLORS_D[_sn_d]
                    if _rd and "error" not in _rd:
                        _iv_disp   = f"${_rd['iv_ps']:.2f}"
                        _mos_disp  = f"{_rd['mos']*100:.1f}%"  if not np.isnan(_rd['mos'])  else "N/A"
                        _cagr_disp = f"{_rd['cagr']*100:.1f}%" if not np.isnan(_rd['cagr']) else "N/A"
                        _mos_clr   = "#66BB6A" if (not np.isnan(_rd['mos']) and _rd['mos'] > 0) else "#FF7043"
                        _iv_clr_d  = _fv_clr(_rd['iv_ps'], _dam_price)
                        st.markdown(
                            f"<div style='background:rgba(255,255,255,0.05);border-radius:10px;"
                            f"padding:14px 16px;border-left:4px solid {_clr_d}'>"
                            f"<div style='font-weight:700;color:{_clr_d};font-size:15px;margin-bottom:8px'>{_sn_d}</div>"
                            f"<table style='width:100%;font-size:13px;border-collapse:collapse'>"
                            f"<tr><td style='color:#93a3b8;padding:2px 0'>Reinv. Rate</td>"
                            f"<td style='text-align:right;font-weight:600'>{_rd['reinv_rate']*100:.1f}%</td></tr>"
                            f"<tr><td style='color:#93a3b8;padding:2px 0'>PV FCFF [M$]</td>"
                            f"<td style='text-align:right;font-weight:600'>{_rd['pv_fcff']:,.1f}</td></tr>"
                            f"<tr><td style='color:#93a3b8;padding:2px 0'>PV Terminal [M$]</td>"
                            f"<td style='text-align:right;font-weight:600'>{_rd['pv_tv']:,.1f}</td></tr>"
                            f"<tr><td style='color:#93a3b8;padding:2px 0'>EV [M$]</td>"
                            f"<td style='text-align:right;font-weight:600'>{_rd['ev']:,.1f}</td></tr>"
                            f"<tr><td style='color:#93a3b8;padding:2px 0'>Equity [M$]</td>"
                            f"<td style='text-align:right;font-weight:600'>{_rd['equity']:,.1f}</td></tr>"
                            f"<tr><td style='color:#93a3b8;padding:2px 0'>Intrinsic Value</td>"
                            f"<td style='text-align:right;font-weight:700;font-size:15px;color:{_iv_clr_d}'>{_iv_disp}</td></tr>"
                            f"<tr><td style='color:#93a3b8;padding:2px 0'>Implied roční výnos (IV vs. P₀)</td>"
                            f"<td style='text-align:right;font-weight:600'>{_cagr_disp}</td></tr>"
                            f"<tr><td style='color:#93a3b8;padding:2px 0'><span title='Upside/Downside = IV/Price − 1. Kladné = IV nad aktuální cenou.' style='cursor:help;border-bottom:1px dotted #93a3b8'>Upside/Downside ⓘ</span></td>"
                            f"<td style='text-align:right;font-weight:700;color:{_mos_clr}'>{_mos_disp}</td></tr>"
                            + (f"<tr><td style='color:#93a3b8;padding:2px 0;border-top:1px solid rgba(255,255,255,0.08)'>Aktuální cena</td>"
                               f"<td style='text-align:right;font-weight:600;border-top:1px solid rgba(255,255,255,0.08)'>${_dam_price:.2f}</td></tr>"
                               if not np.isnan(_dam_price) else "") +
                            f"</table></div>",
                            unsafe_allow_html=True,
                        )
                    elif _rd and "error" in _rd:
                        st.markdown(
                            f"<div style='background:rgba(255,255,255,0.05);border-radius:10px;"
                            f"padding:14px 16px;border-left:4px solid {_clr_d}'>"
                            f"<div style='font-weight:700;color:{_clr_d};font-size:15px;margin-bottom:8px'>{_sn_d}</div>"
                            f"<div style='color:#FF7043'>{_rd['error']}</div></div>",
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown(
                            f"<div style='background:rgba(255,255,255,0.05);border-radius:10px;"
                            f"padding:14px 16px;border-left:4px solid {_clr_d}'>"
                            f"<div style='font-weight:700;color:{_clr_d};font-size:15px;margin-bottom:8px'>{_sn_d}</div>"
                            f"<div style='color:#FF7043'>Chybí TTM Net Income nebo Shares Outstanding</div></div>",
                            unsafe_allow_html=True,
                        )
        else:
            st.warning("Chybí TTM Net Income nebo Shares Outstanding – nelze spočítat.")

        # ── Charts ─────────────────────────────────────────────────────────
        st.markdown("---")

        _dam_hist_yr_strs = [str(y) for y in sorted(_dam_hist_years)]
        _dam_max_n = max(int(_dp_sc[_sn_d]["n"]) for _sn_d in _SC_LABELS_D)
        _dam_fore_yr_strs = [str(_dam_fby)] + [str(_dam_fby + t) for t in range(1, _dam_max_n + 1)]
        _dam_full_yr_order = _dam_hist_yr_strs + _dam_fore_yr_strs
        _dam_cscale = alt.Scale(
            domain=["Historická"] + _SC_LABELS_D,
            range=["#4f8ef7", "#FF7043", "#FFD54F", "#66BB6A"],
        )

        # Chart 1: historical price + IV per scenario (last hist year → year n)
        _dam_hist_px = []
        for _yr_d in effective_df.index:
            if str(_yr_d) == "TTM":
                continue  # TTM used as forecast bridge, not in historical series
            if "Stock Price" in effective_df.columns:
                _vv = _safe_float(effective_df.loc[_yr_d, "Stock Price"])
                if not np.isnan(_vv):
                    _dam_hist_px.append({"Year": str(_yr_d), "Scenario": "Historická", "Value": _vv})

        # Build x domain from actual data rows only
        _dam_ch1_years = {r["Year"] for r in _dam_hist_px + _dam_price_fore}
        _dam_ch1_domain = list(dict.fromkeys(y for y in _dam_full_yr_order if y in _dam_ch1_years))
        _x_enc_d = alt.X("Year:N", sort=_dam_ch1_domain, scale=alt.Scale(domain=_dam_ch1_domain), title="Rok")

        _ch1_layers = []
        if _dam_hist_px:
            _ch1_layers.append(
                alt.Chart(pd.DataFrame(_dam_hist_px))
                .mark_line(strokeWidth=2, point=True)
                .encode(
                    x=_x_enc_d,
                    y=alt.Y("Value:Q", title="Cena [$]"),
                    color=alt.Color("Scenario:N", scale=_dam_cscale, title=""),
                    tooltip=["Year", "Scenario", alt.Tooltip("Value:Q", format=".2f")],
                )
            )
        if _dam_price_fore:
            _ch1_layers.append(
                alt.Chart(pd.DataFrame(_dam_price_fore))
                .mark_line(strokeWidth=2, strokeDash=[4, 2], point=True)
                .encode(
                    x=_x_enc_d,
                    y=alt.Y("Value:Q"),
                    color=alt.Color("Scenario:N", scale=_dam_cscale),
                    tooltip=["Year", "Scenario", alt.Tooltip("Value:Q", format=".2f")],
                )
            )
        if _ch1_layers:
            st.altair_chart(
                alt.layer(*_ch1_layers)
                .properties(
                    title="Historická cena + Intrinsic Value per share (Damodaran)",
                    height=300,
                )
                .configure_view(strokeOpacity=0),
                width="stretch",
            )

        # Chart 2: projected FCFF per year (line, same style as historical price projection)
        if _dam_fcff_rows:
            st.vega_lite_chart({
                "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
                "height": 280,
                "title": "Projektovaný FCFF [M$]",
                "config": {"view": {"strokeOpacity": 0}},
                "data": {"values": _dam_fcff_rows},
                "mark": {"type": "line", "strokeDash": [4, 2], "point": True},
                "encoding": {
                    "x": {"field": "Year", "type": "nominal", "sort": _dam_fore_yr_strs, "scale": {"domain": _dam_fore_yr_strs}, "title": "Rok"},
                    "y": {"field": "fcff_m", "type": "quantitative", "title": "FCFF [M$]"},
                    "color": {
                        "field": "Scenario", "type": "nominal", "title": "Scénář",
                        "scale": {"domain": _SC_LABELS_D, "range": ["#FF7043", "#FFD54F", "#66BB6A"]},
                    },
                    "tooltip": [
                        {"field": "Year", "type": "nominal"},
                        {"field": "Scenario", "type": "nominal"},
                        {"field": "fcff_m", "type": "quantitative", "format": ",.1f", "title": "FCFF [M$]"},
                    ],
                },
            }, width='stretch')

        # ── Save ──────────────────────────────────────────────────────────
        st.markdown("---")
        try:
            _dam_bytes = build_snapshot_excel_bytes(
                effective_df=effective_df, metrics_df=metrics_df,
                manual_df=st.session_state.val_manual_df,
                override_mask=override_mask,
                scope="BASIC",
                ticker=st.session_state.val_ticker,
                years=st.session_state.val_years,
                current_price=float(_dam_price) if not np.isnan(_dam_price) else np.nan,
            )
            _dam_all_bytes = build_all_excel_bytes(
                effective_df=effective_df, metrics_df=metrics_df,
                manual_df=st.session_state.val_manual_df, override_mask=override_mask,
                ticker=st.session_state.val_ticker, years=st.session_state.val_years,
                current_price=float(_dam_price) if not np.isnan(_dam_price) else np.nan,
                simple_eps_params=st.session_state.get("simple_eps_params", {}),
                simple_rev_params=st.session_state.get("simple_rev_params", {}),
                damodaran_params=st.session_state.get(_DAM_KEY, {}),
            )
            _dam_all_fname = f"{st.session_state.val_ticker}_vse_{datetime.now().strftime('%y_%m_%d')}.xlsx"
            _dam_sc1, _dam_sc2 = st.columns([1, 1])
            with _dam_sc1:
                st.download_button(
                    "💾 Uložit tento model (včetně historických dat)",
                    data=_dam_bytes,
                    file_name=(
                        f"{st.session_state.val_ticker}_damodaran_"
                        f"{datetime.now().strftime('%y_%m_%d')}.xlsx"
                    ),
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="snap_dam_save_btn",
                    width="stretch",
                )
            with _dam_sc2:
                st.download_button(
                    "💾 Uložit všechny modely (včetně historických dat)",
                    data=_dam_all_bytes,
                    file_name=_dam_all_fname,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="snap_dam_all_btn",
                    width="stretch",
                )
        except Exception as _exc_dam:
            st.warning(f"Uložení selhalo: {_exc_dam}")

        # ── Sensitivity matrix WACC × g ─────────────────────────────────
        with st.expander("🔲 Citlivost (WACC × g) – Mid scénář", expanded=False):
            st.caption("Intrinsic Value per share ($) při různých kombinacích WACC a g – ostatní vstupy fixovány na Mid scénáři.")
            _sm_c1, _sm_c2, _sm_c3, _sm_c4 = st.columns(4)
            with _sm_c1:
                _sm_wacc_min = st.number_input("WACC min (%)", value=6.0, min_value=1.0, max_value=30.0, step=1.0, key="dam_sm_wacc_min")
            with _sm_c2:
                _sm_wacc_max = st.number_input("WACC max (%)", value=16.0, min_value=2.0, max_value=40.0, step=1.0, key="dam_sm_wacc_max")
            with _sm_c3:
                _sm_g_min = st.number_input("g min (%)", value=0.0, min_value=-5.0, max_value=20.0, step=1.0, key="dam_sm_g_min")
            with _sm_c4:
                _sm_g_max = st.number_input("g max (%)", value=20.0, min_value=1.0, max_value=50.0, step=1.0, key="dam_sm_g_max")

            try:
                _sm_wacc_vals = [round(_sm_wacc_min + i * 2.0, 1) for i in range(int((_sm_wacc_max - _sm_wacc_min) / 2.0) + 1)]
                _sm_g_vals    = [round(_sm_g_min   + i * 2.0, 1) for i in range(int((_sm_g_max   - _sm_g_min)   / 2.0) + 1)]
                _sm_mid = _dp_sc.get("Mid", _dp_sc.get(list(_dp_sc.keys())[0]))
                _sm_n    = int(_sm_mid.get("n", 10))
                _sm_roic = _sm_mid.get("roic", 15.0) / 100.0
                _sm_ni   = _dam_ni_m
                _sm_gterm = _dp.get("g_term", 2.5) / 100.0
                _sm_debt = _dam_debt_m_used
                _sm_cash = _dam_cash_m
                _sm_sh   = _dam_sh_m

                def _dam_iv(g_pct, wacc_pct):
                    _g = g_pct / 100.0; _r = wacc_pct / 100.0
                    if _r <= _sm_gterm or _sm_ni <= 0 or _sm_sh <= 0:
                        return np.nan
                    _rr = min(1.0, max(0.0, _g / _sm_roic)) if _sm_roic > 0 else 1.0
                    _pv = sum(_sm_ni * (1+_g)**t * (1-_rr) / (1+_r)**t for t in range(1, _sm_n+1))
                    _nopat_n1 = _sm_ni * (1+_g)**_sm_n * (1+_sm_gterm)
                    _rr_t = min(1.0, max(0.0, _sm_gterm / _sm_roic)) if _sm_roic > 0 else 1.0
                    _tv = _nopat_n1 * (1-_rr_t) / (_r - _sm_gterm)
                    _pv_tv = _tv / (1+_r)**_sm_n
                    _eq = (_pv + _pv_tv) - _sm_debt + _sm_cash
                    return _eq / _sm_sh

                _sm_data = []
                for _g_v in _sm_g_vals:
                    _row_sm = {"g (%)": f"{_g_v:.0f}%"}
                    for _w_v in _sm_wacc_vals:
                        _iv_cell = _dam_iv(_g_v, _w_v)
                        _row_sm[f"WACC {_w_v:.0f}%"] = round(_iv_cell, 2) if not np.isnan(_iv_cell) else None
                    _sm_data.append(_row_sm)

                _sm_df = pd.DataFrame(_sm_data).set_index("g (%)")
                # Styled display: green = high IV, red = low IV
                _sm_df_num = _sm_df.apply(pd.to_numeric, errors="coerce")
                _sm_vals_flat = _sm_df_num.values.flatten()
                _sm_vals_flat = _sm_vals_flat[~np.isnan(_sm_vals_flat)]
                if len(_sm_vals_flat) > 0:
                    _sm_styled = _sm_heatmap_style(
                        _sm_df_num,
                        price=_dam_price if not np.isnan(_dam_price) else None,
                        mid_row=f"{_sm_mid.get('g', 0):.0f}%",
                        mid_col=f"WACC {_sm_mid.get('r', 12):.0f}%",
                    )
                    st.dataframe(_sm_styled, width="stretch")
                    if not np.isnan(_dam_price):
                        st.caption(f"Aktuální cena: ${_dam_price:.2f}. Mid scénář: g={_sm_mid.get('g',0):.1f}%, WACC={_sm_mid.get('r',12):.1f}%.  |  🟡 = Mid baseline")
                else:
                    st.warning("Žádné platné hodnoty – zkontroluj rozsahy WACC/g.")
            except Exception as _sm_exc:
                st.warning(f"Citlivostní matice se nepodařila: {_sm_exc}")

        # ── Monte Carlo — Damodaran FCFF ───────────────────────────────────────
        with st.expander("🎲 Monte Carlo simulace — Damodaran FCFF", expanded=False):
            st.caption(
                "Simultánní náhodná variace g, WACC a ROIC. "
                "g_terminal je fixní (variace by narušila podmínku WACC > g_terminal). "
                "σ lze přepsat. "
                "🟡 = percentily | 🔴 = aktuální cena"
            )
            if np.isnan(_dam_ni_m) or np.isnan(_dam_sh_m) or _dam_sh_m <= 0:
                st.info("Chybí TTM Net Income nebo Shares.")
            else:
                _mcd_mid   = _dp_sc["Mid"]
                _mcd_g_mu  = float(_mcd_mid["g"])
                _mcd_r_mu  = float(_mcd_mid["r"])
                _mcd_ri_mu = float(_mcd_mid["roic"])
                _mcd_n     = int(_mcd_mid["n"])
                _mcd_gt    = float(_dam_g_term)

                _mcdc1, _mcdc2, _mcdc3 = st.columns(3)
                with _mcdc1:
                    st.markdown("**NOPAT growth g (%)**")
                    _mcd_g_mu_in  = st.number_input("Průměr g", value=_mcd_g_mu,
                                                     key="mc_dam_g_mu", format="%.1f")
                    _mcd_g_sig_in = st.number_input("σ g", value=3.0, min_value=0.5,
                                                     key="mc_dam_g_sig", format="%.1f",
                                                     help=(
                                                         "Co je σ (sigma)?\n"
                                                         "Nepřesnost tvoé projekce růstu zisku (NOPAT/NI).\n"
                                                         "Vyšší σ = v simulaci větší prostor pro růst i pokles.\n"
                                                         "\n"
                                                         "Není předvyplněna automaticky — zadej sám.\n"
                                                         "Tip: podívej se do sekce Net Income v tabulce dat.\n"
                                                         "\n"
                                                         "Tahak:\n"
                                                         "  2–5 pp • stabilní firma (Apple, J&J)\n"
                                                         "  5–12 pp • průměrná růstová firma\n"
                                                         "  12+ pp • cyklická nebo disruptivní firma"
                                                     ))
                    st.caption(f"💡 90 % simulací: {_mcd_g_mu_in - 1.645 * _mcd_g_sig_in:.1f}–{_mcd_g_mu_in + 1.645 * _mcd_g_sig_in:.1f} %")
                with _mcdc2:
                    st.markdown("**WACC / r (%) — fixní**")
                    _mcd_r_fixed = st.number_input("WACC (fixní)", value=_mcd_r_mu,
                                                    key="mc_dam_r_fixed", format="%.1f",
                                                    help=(
                                                        "🔒 WACC je záměrně fixní.\n"
                                                        "Důvod 1: WACC ovlivňuje FV přes (1+WACC)^n —\n"
                                                        "variace by produkovala extrémně asymetrické\n"
                                                        "rozdělení FV, obtížně interpretovatelné.\n"
                                                        "Důvod 2: WACC musí být > g_terminal — variace\n"
                                                        "by mohla tuto podmínku porušit (→ NaN/∞ FV).\n"
                                                        "Vliv WACC zobrazuje Tornado graf výše."
                                                    ))
                with _mcdc3:
                    st.markdown("**ROIC (%)**")
                    _mcd_ri_mu_in  = st.number_input("Průměr ROIC", value=_mcd_ri_mu,
                                                      key="mc_dam_ri_mu", format="%.1f")
                    _mcd_ri_sig_in = st.number_input("σ ROIC", value=2.0, min_value=0.1,
                                                      key="mc_dam_ri_sig", format="%.1f",
                                                      help=(
                                                          "Co je σ (sigma)?\n"
                                                          "Nepřesnost projekce návratnosti investovaného kapitálu.\n"
                                                          "\n"
                                                          "Není předvyplněna automaticky — zadej sám.\n"
                                                          "Tip: podívej se na řádek ROI v tabulce dat.\n"
                                                          "\n"
                                                          "Tahak:\n"
                                                          "  1–3 pp • stabilní ROIC (konzistentní firma)\n"
                                                          "  3–8 pp • průměrná firma\n"
                                                          "  8+ pp • vysoká kolisavost (cyklická / agresivní)"
                                                      ))
                    st.caption(f"💡 90 % simulací: {_mcd_ri_mu_in - 1.645 * _mcd_ri_sig_in:.1f}–{_mcd_ri_mu_in + 1.645 * _mcd_ri_sig_in:.1f} %")

                st.caption(f"g_terminal = {_mcd_gt:.1f}% (fixní — variace by narušila podmínku WACC > g_terminal)")
                _mcd_nsim = st.select_slider("Počet simulací", [1_000, 5_000, 10_000, 25_000],
                                              value=10_000, key="mc_dam_nsim")

                if st.button("▶ Spustit simulaci", key="mc_dam_run"):
                    _mcd_ni   = _dam_ni_m
                    _mcd_sh   = _dam_sh_m
                    _mcd_debt = _dam_debt_m_used
                    _mcd_cash = _dam_cash_m
                    _mcd_gt_f = _mcd_gt / 100.0
                    _mcd_n_f  = _mcd_n

                    def _mc_dam_fv(g, r, roic):
                        try:
                            _g = g / 100.0
                            _r = r / 100.0
                            _ri = max(roic, 0.1) / 100.0
                            if _r <= _mcd_gt_f or _ri <= 0:
                                return np.nan
                            _rr = min(1.0, max(0.0, _g / _ri))
                            _pv = sum(_mcd_ni * (1 + _g) ** t * (1 - _rr) / (1 + _r) ** t
                                      for t in range(1, _mcd_n_f + 1))
                            _nop_n1 = _mcd_ni * (1 + _g) ** _mcd_n_f * (1 + _mcd_gt_f)
                            _rr_t   = min(1.0, max(0.0, _mcd_gt_f / _ri))
                            _tv     = _nop_n1 * (1 - _rr_t) / (_r - _mcd_gt_f) / (1 + _r) ** _mcd_n_f
                            _eq     = (_pv + _tv) - _mcd_debt + _mcd_cash
                            return _eq / _mcd_sh
                        except Exception:
                            return np.nan

                    _mcd_specs = [
                        {"name": "g",    "dist": "normal", "mean": _mcd_g_mu_in,  "std": _mcd_g_sig_in},
                        {"name": "r",    "dist": "fixed",  "value": _mcd_r_fixed},
                        {"name": "roic", "dist": "normal", "mean": _mcd_ri_mu_in, "std": _mcd_ri_sig_in},
                    ]
                    with st.spinner(f"Probíhá {_mcd_nsim:,} simulací..."):
                        _mcd_res = run_monte_carlo(_mc_dam_fv, _mcd_specs,
                                                   n_sim=_mcd_nsim,
                                                   current_price=_dam_price)
                    if _mcd_res:
                        render_mc_chart(_mcd_res, _dam_price, "Damodaran FCFF")
                    else:
                        st.warning("Simulace nevygenerovala platné výsledky. Zkontroluj WACC > g_terminal.")

        # ── Tornado sensitivity ────────────────────────────────────────────
        with st.expander("🌪️ Analýza citlivosti (Tornado) – Damodaran", expanded=False):
            st.caption(
                "🌪️ Tornado = citlivost one-at-a-time. Žlutá čára = 0 (baseline rozdíl). "
                "🟥 Červená = nižší IV výsledek  |  🟩 Zelená = vyšší IV výsledek. "
                "Delší pruh = větší citlivost. "
                "Δ pp (absolutně): všechny vstupy (g, WACC, ROIC, g_terminal) — posun o pevný počet % bodů. "
                "⚠️ WACC > g_terminal musí platit — pokud perturbace poruší tuto podmínku, pruh se nezobrazí. "
                "Tornado mění vždy jen 1 parametr — neukazuje kombinace."
            )
            _td_sn = st.selectbox(
                "Základní scénář:", _SC_LABELS_D,
                index=min(1, len(_SC_LABELS_D) - 1), key="tornado_dam_scenario",
            )
            _td_sn_params = _dp_sc.get(_td_sn, {})
            st.caption(f"Scénář {_td_sn}: g = {_td_sn_params.get('g', float('nan')):.1f} %  |  ROIC = {_td_sn_params.get('roic', float('nan')):.1f} %  |  WACC = {_td_sn_params.get('r', float('nan')):.1f} %  |  n = {int(_td_sn_params.get('n', 0))} let")
            _td_delta_pp   = st.number_input("Δ sazeb – ± pp (WACC, ROIC, g_terminal, absolutně)", value=1.0, min_value=0.1, max_value=10.0, step=0.1, format="%.1f", key="tornado_dam_delta_pp")
            _td_delta_g_pp = st.number_input("Δg – ± pp (NOPAT growth g, absolutně v % bodech)", value=1.0, min_value=0.5, max_value=20.0, step=0.5, format="%.1f", key="tornado_dam_delta_g")

            def _dam_iv_fn(g_pct, roic_pct, wacc_pct, n_yrs, g_term_pct):
                """Damodaran 2-stage FCFF → IV per share. Returns nan on invalid inputs."""
                try:
                    if any(np.isnan(x) for x in [_dam_ni_m, _dam_sh_m]) or _dam_sh_m <= 0: return np.nan
                    _r = wacc_pct / 100.0; _g = g_pct / 100.0; _roic = roic_pct / 100.0
                    _gt = g_term_pct / 100.0; _n = int(n_yrs)
                    if _r <= _gt or _roic <= 0: return np.nan
                    _rr = min(1.0, max(0.0, _g / _roic))
                    _pv = sum(_dam_ni_m * (1 + _g) ** t * (1 - _rr) / (1 + _r) ** t for t in range(1, _n + 1))
                    _nopat_n1 = _dam_ni_m * (1 + _g) ** _n * (1 + _gt)
                    _rr_t = min(1.0, max(0.0, _gt / _roic))
                    _tv = (_nopat_n1 * (1 - _rr_t)) / (_r - _gt) / (1 + _r) ** _n
                    _eq = (_pv + _tv) - _dam_debt_m_used + _dam_cash_m
                    return _eq / _dam_sh_m
                except Exception:
                    return np.nan

            try:
                _td_g    = _dp_sc[_td_sn]["g"]
                _td_roic = _dp_sc[_td_sn]["roic"]
                _td_wacc = _dp_sc[_td_sn]["r"]
                _td_n    = int(_dp_sc[_td_sn]["n"])
                _td_gt   = _dam_g_term
                _td_base = _dam_iv_fn(_td_g, _td_roic, _td_wacc, _td_n, _td_gt)
                if not np.isnan(_td_base):
                    _td_impacts = []
                    for _pname, _lo_v, _hi_v in [
                        (f"NOPAT growth g (±{_td_delta_g_pp:.1f}pp)",   _dam_iv_fn(_td_g - _td_delta_g_pp, _td_roic, _td_wacc, _td_n, _td_gt),
                                                 _dam_iv_fn(_td_g + _td_delta_g_pp, _td_roic, _td_wacc, _td_n, _td_gt)),
                        (f"ROIC (±{_td_delta_pp:.1f}pp)",              _dam_iv_fn(_td_g, max(0.01, _td_roic - _td_delta_pp), _td_wacc, _td_n, _td_gt),
                                                 _dam_iv_fn(_td_g, _td_roic + _td_delta_pp, _td_wacc, _td_n, _td_gt)),
                        (f"WACC / r (±{_td_delta_pp:.1f}pp)",          _dam_iv_fn(_td_g, _td_roic, _td_wacc + _td_delta_pp, _td_n, _td_gt),
                                                 _dam_iv_fn(_td_g, _td_roic, max(0.01, _td_wacc - _td_delta_pp), _td_n, _td_gt)),
                        (f"Terminal growth g_t (±{_td_delta_pp:.1f}pp)", _dam_iv_fn(_td_g, _td_roic, _td_wacc, _td_n, max(0.0, _td_gt - _td_delta_pp)),
                                                 _dam_iv_fn(_td_g, _td_roic, _td_wacc, _td_n, _td_gt + _td_delta_pp)),
                        ("Years n (±1)",               _dam_iv_fn(_td_g, _td_roic, _td_wacc, max(1, _td_n - 1), _td_gt),
                                                 _dam_iv_fn(_td_g, _td_roic, _td_wacc, _td_n + 1, _td_gt)),
                    ]:
                        if not (np.isnan(_lo_v) or np.isnan(_hi_v)):
                            _td_impacts.append({"Parametr": _pname, "Nízká": _lo_v, "Vysoká": _hi_v,
                                                "RozsahAbs": abs(_hi_v - _lo_v)})
                    if _td_impacts:
                        _td_df = pd.DataFrame(_td_impacts).sort_values("RozsahAbs", ascending=False)
                        _td_df["Baseline"] = _td_base
                        _td_df["IV_nizka"] = _td_df["Nízká"]
                        _td_df["IV_vysoka"] = _td_df["Vysoká"]
                        _td_df["DiffLo"] = _td_df["Nízká"] - _td_base
                        _td_df["DiffHi"] = _td_df["Vysoká"] - _td_base
                        _td_long_rows = []
                        for _, _r in _td_df.iterrows():
                            _bl = float(_r["Baseline"])
                            _dl = float(_r["DiffLo"]); _dh = float(_r["DiffHi"])
                            _dlp = (_dl / _bl * 100) if _bl else 0.0
                            _dhp = (_dh / _bl * 100) if _bl else 0.0
                            _range_dollar = f"{_dl:+.2f}$ / {_dh:+.2f}$"
                            _range_pct    = f"{_dlp:+.1f}% / {_dhp:+.1f}%"
                            for _dc, _ic, _lbl in [("DiffLo","IV_nizka","Nižší IV"),("DiffHi","IV_vysoka","Vyšší IV")]:
                                _da = float(_r[_dc])
                                _td_long_rows.append({"Parametr": str(_r["Parametr"]), "DiffAbs": _da,
                                    "DiffPct": round(_da / _bl * 100, 2) if _bl else 0.0,
                                    "Baseline": _bl, "IV_nizka": float(_r["IV_nizka"]),
                                    "IV_vysoka": float(_r["IV_vysoka"]), "StranaCZ": _lbl,
                                    "BarColor": "#66BB6A" if _da >= 0 else "#FF7043",
                                    "RangeDollar": _range_dollar, "RangePct": _range_pct})
                        _td_sort = list(_td_df["Parametr"])
                        _td_h = max(150, len(_td_impacts) * 50)
                        _td_sort_tt = [
                            {"field": "Parametr", "type": "nominal"},
                            {"field": "StranaCZ", "type": "nominal", "title": "Výsledek"},
                            {"field": "Baseline", "type": "quantitative", "format": "$.2f", "title": "Baseline IV ($)"},
                            {"field": "IV_nizka", "type": "quantitative", "format": "$.2f", "title": "IV nižší ($)"},
                            {"field": "IV_vysoka", "type": "quantitative", "format": "$.2f", "title": "IV vysoká ($)"},
                            {"field": "RangeDollar", "type": "nominal", "title": "Δ nízká / vysoká ($)"},
                            {"field": "RangePct", "type": "nominal", "title": "Δ nízká / vysoká (%)"},
                        ]
                        st.vega_lite_chart({
                            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
                            "height": _td_h,
                            "title": f"Tornado: Damodaran FCFF — {_td_sn} scénář",
                            "config": {"view": {"strokeOpacity": 0}},
                            "layer": [
                                {"data": {"values": [r for r in _td_long_rows if r["DiffAbs"] >= 0]}, "mark": {"type": "bar", "opacity": 0.75, "color": "#66BB6A"}, "encoding": {"y": {"field": "Parametr", "type": "nominal", "sort": _td_sort, "title": None, "axis": {"labelOverlap": False, "labelLimit": 300}}, "x": {"field": "DiffAbs", "type": "quantitative", "title": "Δ Intrinsic Value vs baseline ($)", "axis": {"grid": True}}, "tooltip": _td_sort_tt}},
                                {"data": {"values": [r for r in _td_long_rows if r["DiffAbs"] < 0]}, "mark": {"type": "bar", "opacity": 0.75, "color": "#FF7043"}, "encoding": {"y": {"field": "Parametr", "type": "nominal", "sort": _td_sort}, "x": {"field": "DiffAbs", "type": "quantitative"}, "tooltip": _td_sort_tt}},
                                {"data": {"values": _td_long_rows}, "transform": [{"calculate": "format(datum.DiffPct, '+.1f') + '%'", "as": "_dp_label"}], "mark": {"type": "text", "fontSize": 10, "align": {"expr": "datum.DiffAbs >= 0 ? 'left' : 'right'"}, "dx": {"expr": "datum.DiffAbs >= 0 ? 4 : -4"}}, "encoding": {"y": {"field": "Parametr", "type": "nominal", "sort": _td_sort}, "x": {"field": "DiffAbs", "type": "quantitative"}, "text": {"field": "_dp_label", "type": "nominal"}, "color": {"value": "#93a3b8"}, "tooltip": _td_sort_tt}},
                                {"data": {"values": [{"x": 0}]}, "mark": {"type": "rule", "color": "#FFD54F", "strokeDash": [4, 2]}, "encoding": {"x": {"field": "x", "type": "quantitative"}}},
                            ],
                        }, width='stretch')
                        _td_price_txt = f"  |  Aktuální cena: ${_dam_price:.2f}" if not np.isnan(_dam_price) else ""
                        st.caption(f"Baseline IV = ${_td_base:.2f}{_td_price_txt}. Pruhy = Δ vs baseline. Žlutá čára = 0.")
                    else:
                        st.info("Nelze vypočítat tornado (chybí data).")
                else:
                    st.info("Základní IV není dostupné – zkontroluj WACC > g_terminal a platná data.")
            except Exception as _t_exc_dam:
                st.warning(f"Tornado nelze zobrazit: {_t_exc_dam}")

        # ── Equations ─────────────────────────────────────────────────────
        with st.expander("📐 Equations – Simple Valuation (Damodaran-style) (click to expand)"):
            st.markdown(r"""
**2-stage FCFF Damodaran model**

Vstupní veličiny na scénář: $g$ (NOPAT growth), $ROIC$ (proxy), $WACC$ (discount rate), $n$ (roky)  
Sdílené: $g_{term}$ (terminal growth), Cash, Debt  
Z tabulky (TTM): $NOPAT_0 = \text{Net Income}_{TTM}$ **(after-tax, tax rate se zde nepoužívá)**, Shares, Stock Price

---

**Reinvestment rate:**

$$
RR = \frac{g}{ROIC}
$$

**NOPAT a FCFF v roce $t$:**

$$
NOPAT_t = NOPAT_0 \times (1 + g)^t
$$

$$
FCFF_t = NOPAT_t \times (1 - RR)
$$

**Present value FCFF fáze 1:**

$$
PV_{FCFF} = \sum_{t=1}^{n} \frac{FCFF_t}{(1 + WACC)^t}
$$

**Terminální hodnota (Gordon Growth):**

$$
RR_{term} = \frac{g_{term}}{ROIC}
$$

$$
FCFF_{n+1} = NOPAT_0 \times (1+g)^n \times (1+g_{term}) \times (1 - RR_{term})
$$

$$
TV_n = \frac{FCFF_{n+1}}{WACC - g_{term}}
$$

$$
PV_{TV} = \frac{TV_n}{(1 + WACC)^n}
$$

**Enterprise Value a Equity:**

$$
EV = PV_{FCFF} + PV_{TV}
$$

$$
Equity = EV - Debt + Cash
$$

$$
\text{Intrinsic Value per share} = \frac{Equity \;[\$M]}{Shares \;[M]}
$$

$$
\text{Upside/Downside} = \frac{IV}{P_0} - 1 \qquad CAGR = \left(\frac{IV}{P_0}\right)^{1/n} - 1
$$

*Podmínka: $WACC > g_{term}$. Pokud $g > ROIC$, model capuje RR na 100 %.*
            """)

    # ── Tab 4: Advanced Valuation ─────────────────────────────────────
    with _val_tabs[3]:
        _t3_tip = _tooltip_attr(
            "Popis: Scénářová P/E i DCF analýza – simultánní dual-method ocenění.\n"
            "Vhodné typy firem: Jakákoliv profitabilní firma s Revenue a marží, kde lze odvodit FCF (tech, consumer, industrial, healthcare).\n"
            "Výhody: Kombinace P/E i DCF dává dvě nezávislá čísla pro cross-check. Total return CAGR vč. dividend. Implied FCF margin z ROIC/g/margin vztahu. Volbná Gordon nebo Exit Multiple TV.\n"
            "Na co si dát pozor: Mnoho vstupních parametrů = vyšší riziko chyb (garbage in, garbage out). Implied FCF margin závisí na konzistenci ROIC, g a Op.Margin. Záporná FCF margin dává nesmyslný DCF výstup."
        )
        st.markdown(
            f"<h3>Advanced Valuation "
            f"<span title='{_t3_tip}' style='cursor:help;color:#93a3b8;border-bottom:1px dotted #93a3b8;font-size:14px;'>ⓘ</span>"
            f"</h3>",
            unsafe_allow_html=True,
        )
        with st.expander("ℹ️ O tomto modelu", expanded=False):
            st.markdown("""
| | |
|---|---|
| **Popis** | Scénářová analýza kombinující P/E-based fair value a Equity DCF Fair Value – ideální pro cross-check výsledků. |
| **Vhodné typy firem** | Jakákoliv profitabilní firma s Revenue a op. marží – tech, consumer, industrial, healthcare. Při záporné FCF margi je DCF nesmyslný. |
| **NEVHODNÉ pro** | Banky/pojišťovny (jiná struktura FCF). Firmy s extremálně nestabilní marginí – implied FCF bude nespolehlivý. |
| **Výhody** | Dual-method cross-check (P/E + DCF). Total return CAGR včetně dividend. Implied FCF margin z konzistentního ROIC/g/margin vztahu. Volba terminality (Exit P/FCF nebo Gordon). |
| **Na co si dát pozor** | Mnoho vstupů → vyšší riziko chybých vstupů. Implied FCF musí být konzistentní s ROIC a g. Záporná FCF margin => DCF bude N/A. Při Gordonovi WACC > g_terminal je podmínka. |
            """)
        st.markdown(
            """
            <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:2px 0 10px 0;font-size:12px;color:#93a3b8;">
              <span style="font-weight:600;">Legenda výpočtů:</span>
              <span>🟡 P/E fair value</span>
              <span>🔵 Equity DCF fair value</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # ── local helper functions ────────────────────────────────────────

        def _info_label(label, help_text, subtext=None, top_pad=6, size=13, weight=400, badges=None):
            icon = ""
            if help_text:
                icon = (
                    f" <span title=\"{_tooltip_attr(help_text)}\" "
                    "style='cursor:help;color:#93a3b8;border-bottom:1px dotted #93a3b8;font-size:11px;'>ⓘ</span>"
                )
            badge_html = ""
            if badges:
                _BADGE_EMOJI = {"PE": "🟡", "DCF": "🔵"}
                for b in badges:
                    badge_html += " " + _BADGE_EMOJI.get(b, b)
            sub = ""
            if subtext:
                sub = f"<br><span style='color:#93a3b8;font-size:11px'>{html.escape(subtext)}</span>"
            return (
                f"<div style='padding-top:{top_pad}px;font-size:{size}px;font-weight:{weight}'>"
                f"{html.escape(label)}{badge_html}{icon}{sub}</div>"
            )

        def _sc_implied_fcf(roic_pct, g_pct, op_margin_pct, tax_rate_pct):
            """
            FCF_margin = OpMargin*(1-TaxRate) * (1 - g/ROIC)
            Inputs are in PERCENT (e.g. 15 for 15%).
            Returns implied FCF margin as PERCENT, or NaN on invalid inputs.
            """
            try:
                roic = float(roic_pct) / 100.0
                g    = float(g_pct)    / 100.0
                op   = float(op_margin_pct) / 100.0
                tax  = float(tax_rate_pct)  / 100.0
                if any(np.isnan(x) for x in [roic, g, op, tax]):
                    return np.nan
                if roic <= 0:
                    return np.nan
                nopat = op * (1.0 - tax)
                reinv = g / roic
                return nopat * (1.0 - reinv) * 100.0
            except Exception:
                return np.nan

        # ── pull defaults from effective_df / metrics_df ─────────────────

        def _sc_get_ttm(col, default=np.nan):
            try:
                v = _safe_float(effective_df.loc["TTM", col])
                return v if not np.isnan(v) else default
            except Exception:
                return default

        def _sc_metrics_val(row_label, col_label="5 let", default=np.nan):
            try:
                v = _safe_float(metrics_df.loc[row_label, col_label])
                return v if not np.isnan(v) else default
            except Exception:
                return default

        _d_roic_pct = _sc_get_ttm("ROI", np.nan)
        if np.isnan(_d_roic_pct):
            _cols_available = [c for c in metrics_df.columns] if not metrics_df.empty else []
            _roic_vals = [_safe_float(metrics_df.loc["ROI", c]) for c in _cols_available
                          if not metrics_df.empty and "ROI" in metrics_df.index]
            _roic_vals = [v for v in _roic_vals if not np.isnan(v)]
            _d_roic_pct = float(np.mean(_roic_vals)) if _roic_vals else 15.0
        _d_roic_pct = max(1.0, _d_roic_pct) if not np.isnan(_d_roic_pct) else 15.0

        _d_g_dec = _sc_metrics_val("Revenue CAGR", "5 let", 0.08)
        _d_g_pct = float(_d_g_dec) * 100.0
        if np.isnan(_d_g_pct):
            _d_g_pct = 8.0
        _d_g_pct = max(0.0, _d_g_pct)

        _d_ni  = _sc_get_ttm("Net Income [M]", np.nan)
        _d_rev = _sc_get_ttm("Revenue [M]", np.nan)
        # Default op = pre-tax operating margin (EBIT/Revenue).
        # Net margin is post-tax, so we back-calculate: op ≈ net_margin / (1 - tax).
        # This avoids double-taxation in formulas that apply × (1 - tax) explicitly.
        _tax_for_op = st.session_state.get("sc_tax_rate_pct", 21.0) / 100.0
        if not np.isnan(_d_ni) and not np.isnan(_d_rev) and _d_rev > 0:
            _net_margin = _d_ni / _d_rev
            _d_op_pct = (_net_margin / max(0.01, 1.0 - _tax_for_op)) * 100.0
        else:
            _d_op_pct = 10.0
        _d_op_pct = max(0.0, _d_op_pct)

        _d_price  = _sc_get_ttm("Stock Price", np.nan)
        _d_sh_m   = _sc_get_ttm("Shares Outstanding [M]", np.nan)
        _d_shares = _d_sh_m * 1e6 if not np.isnan(_d_sh_m) else np.nan
        _d_rev0   = _d_rev * 1e6  if not np.isnan(_d_rev)  else np.nan

        # ── session-state init ────────────────────────────────────────────

        _SC_KEY       = "scenarios"
        _TAX_KEY      = "sc_tax_rate_pct"
        _DIVTAX_KEY   = "sc_div_tax_pct"
        _TERMMODE_KEY = "sc_terminal_mode"
        _GTERM_KEY    = "sc_g_terminal_pct"

        if _TAX_KEY not in st.session_state:
            st.session_state[_TAX_KEY] = 21.0
        if _DIVTAX_KEY not in st.session_state:
            st.session_state[_DIVTAX_KEY] = 15.0
        if _TERMMODE_KEY not in st.session_state:
            st.session_state[_TERMMODE_KEY] = "Exit multiple (P/FCF)"
        if _GTERM_KEY not in st.session_state:
            st.session_state[_GTERM_KEY] = 2.5

        _sc_init = {
            "Low": {
                "roic": round(max(1.0, _d_roic_pct * 0.7), 1),
                "g":    round(max(0.0, _d_g_pct    * 0.5), 1),
                "op":   round(max(0.0, _d_op_pct   * 0.85), 1),
                "r":    12.0, "pe": 15.0, "pfcf": 12.0, "n": 10,
                "dg":   2.0,
                "override": False, "fcf_ovr": 0.0,
            },
            "Mid": {
                "roic": round(_d_roic_pct, 1),
                "g":    round(_d_g_pct,    1),
                "op":   round(_d_op_pct,   1),
                "r":    10.0, "pe": 20.0, "pfcf": 18.0, "n": 10,
                "dg":   5.0,
                "override": False, "fcf_ovr": 0.0,
            },
            "High": {
                "roic": round(min(99.0, _d_roic_pct * 1.3), 1),
                "g":    round(min(99.0, _d_g_pct    * 1.5), 1),
                "op":   round(min(99.0, _d_op_pct   * 1.15), 1),
                "r":    8.0, "pe": 28.0, "pfcf": 25.0, "n": 10,
                "dg":   8.0,
                "override": False, "fcf_ovr": 0.0,
            },
        }

        if _SC_KEY not in st.session_state:
            st.session_state[_SC_KEY] = _sc_init

        _sc = st.session_state[_SC_KEY]
        _SC_LABELS = ["Low", "Mid", "High"]
        _SC_COLORS = {"Low": "#FF7043", "Mid": "#FFD54F", "High": "#66BB6A"}
        _SC_HELP = {
            "tax": "Použito v P/E i DCF. Po zdanění se marže počítá jako op × (1 - tax). Vyšší daň snižuje výslednou férovou hodnotu. Používej dlouhodobě udržitelnou korporátní sazbu, ne jednorázově nízký efektivní rok.",
            "div_tax": "Použito v Total return CAGR. After-tax dividendy se počítají jako DPS_t × (1 - div_tax). Nemění P/E fair value ani DCF fair value, ale snižuje celkový výnos investora.",
            "terminal_mode": "Určuje, jak DCF ocení období po explicitní projekci n. Exit multiple používá TV_n = FCF_n × P/FCF. Gordon používá TV_n = FCF_(n+1) / (r - g_terminal). Gordon je citlivější na malé změny vstupů.",
            "g_terminal": "Použito jen při Gordonově perpetuitě. Musí být nižší než r, jinak terminální hodnota nedává smysl. Obvykle drž konzervativně kolem dlouhodobého nominálního růstu ekonomiky.",
            "roic": "Použito hlavně v DCF přes implied FCF margin. Reinvestice = g / ROIC, takže vyšší ROIC umožní vyšší růst s menším tlakem na reinvestice. Pozor na cyklické peak hodnoty a jednorázově nafouknutý kapitálový výnos.",
            "g": "Použito v P/E i DCF: Revenue_n = Revenue_0 × (1 + g)^n. Současně vstupuje do implied FCF margin přes člen g / ROIC. Příliš vysoké g při nízkém ROIC může hodnotu ničit místo tvořit.",
            "op": "Provozní marže PŘED daní (EBIT/Revenue). Použito v P/E i DCF: NOPAT = Revenue × op × (1−tax). Default se dopočítává z Net Margin / (1−tax), aby nedocházelo k dvojímu zdanění. Nastavuj normalizovanou marži, ne nejlepší rok v cyklu.",
            "r": "Diskontní míra v P/E i DCF. Budoucí hodnota se převádí na dnešek dělením (1 + r)^n. Vyšší r prudce snižuje fair value. Nastavuj podle požadovaného výnosu investora, ne automaticky podle trhu.",
            "pe": "Použito jen v P/E fair value a CAGR via P/E exit. Na konci horizontu se equity value aproximuje jako zisk v roce n × exit P/E. Drž multiple realisticky vzhledem ke kvalitě, růstu a sazbám.",
            "pfcf": "Použito jen v DCF, pokud je zvolen terminal mode Exit multiple. Terminální hodnota je FCF_n × P/FCF. Pokud je vybraný Gordon, tento parametr se ignoruje.",
            "n": "Délka explicitní projekce. Ovlivňuje diskontování, terminální rok i velikost prostoru pro růst. Delší horizont může zvýšit hodnotu, ale dělá model citlivější na terminální předpoklady.",
            "dg": "Použito pro Total return CAGR přes růst dividend: DPS_t = DPS_0 × (1 + dg)^t. Nemění přímo P/E fair value ani DCF fair value. Dlouhodobě by nemělo být systematicky vyšší než růst zisků.",
            "fcf": "Použito v DCF. Bez override se FCF margin dopočítá z ROIC, růstu, marže a daně: FCF_margin = op × (1 - tax) × (1 - g / ROIC). Manual override umožní tento odhad nahradit vlastním číslem.",
            "fcf_override": "Zapni jen pokud implied FCF margin zjevně neodpovídá realitě firmy. Override přepíše automatický výpočet a jde přímo do DCF. Pozor, ať optimismus nezapočítáš dvakrát současně v marži, růstu i override.",
        }

        # ── global tax rate input ─────────────────────────────────────────

        _tax_col_w, _ = st.columns([2, 8])
        with _tax_col_w:
            st.markdown(_info_label("Global Tax Rate (%)", _SC_HELP["tax"], top_pad=0, size=12, badges=["PE", "DCF"]), unsafe_allow_html=True)
            _tax_pct = st.number_input(
                "Tax rate (%)", min_value=0.0, max_value=60.0,
                value=float(st.session_state[_TAX_KEY]),
                step=0.5, format="%.1f",
                key="sc_tax_rate_widget",
                label_visibility="collapsed",
            )
        st.session_state[_TAX_KEY] = _tax_pct

        # ── dividend tax + terminal value global settings ─────────────────
        _glob_c1, _glob_c2, _glob_c3 = st.columns([2, 3, 2])
        with _glob_c1:
            st.markdown(_info_label("Dividend tax rate (%)", _SC_HELP["div_tax"], top_pad=0, size=12), unsafe_allow_html=True)  # total return only – no PE/DCF badge
            _div_tax_pct = st.number_input(
                "Dividend tax rate (%)", min_value=0.0, max_value=60.0,
                value=float(st.session_state[_DIVTAX_KEY]),
                step=0.5, format="%.1f",
                key="sc_div_tax_widget",
                label_visibility="collapsed",
            )
        st.session_state[_DIVTAX_KEY] = _div_tax_pct

        with _glob_c2:
            st.markdown(_info_label("Terminal value method", _SC_HELP["terminal_mode"], top_pad=0, size=12, badges=["DCF"]), unsafe_allow_html=True)
            _terminal_mode = st.radio(
                "Terminal value method",
                options=["Exit multiple (P/FCF)", "Perpetual growth (Gordon)"],
                index=0 if st.session_state[_TERMMODE_KEY] == "Exit multiple (P/FCF)" else 1,
                key="sc_terminal_mode_widget",
                label_visibility="collapsed",
            )
        st.session_state[_TERMMODE_KEY] = _terminal_mode

        with _glob_c3:
            if _terminal_mode == "Perpetual growth (Gordon)":
                st.markdown(_info_label("Terminal growth g_terminal (%)", _SC_HELP["g_terminal"], top_pad=0, size=12, badges=["DCF"]), unsafe_allow_html=True)
                _g_terminal_pct = st.number_input(
                    "Terminal growth g_terminal (%)", min_value=0.0, max_value=10.0,
                    value=float(st.session_state[_GTERM_KEY]),
                    step=0.1, format="%.1f",
                    key="sc_g_terminal_widget",
                    label_visibility="collapsed",
                )
                st.session_state[_GTERM_KEY] = _g_terminal_pct
            else:
                _g_terminal_pct = float(st.session_state[_GTERM_KEY])

        # ── header row ────────────────────────────────────────────────────

        _c_lbl, _c_low, _c_mid, _c_high = st.columns([2.5, 2, 2, 2])
        with _c_lbl:
            st.markdown("**Parameter**")
        for _cw, _sn in zip([_c_low, _c_mid, _c_high], _SC_LABELS):
            with _cw:
                _col = _SC_COLORS[_sn]
                st.markdown(
                    f"<div style='font-weight:700;color:{_col};padding-bottom:4px'>{_sn}</div>",
                    unsafe_allow_html=True,
                )

        # ── input rows (float) ─────────────────────────────────────────────

        def _sc_float_row(label, key, min_v, max_v, step, fmt="%.1f", help_text=None, badges=None):
            """Render one parameter row; return {sc_name: float_value} in percent."""
            rl, rlo, rmi, rhi = st.columns([2.5, 2, 2, 2])
            with rl:
                st.markdown(_info_label(label, help_text, top_pad=6, size=13, badges=badges), unsafe_allow_html=True)
            out = {}
            for cw, sn in zip([rlo, rmi, rhi], _SC_LABELS):
                wk = f"sc_{sn}_{key}"
                existing = st.session_state.get(wk, None)
                init_val = float(_sc[sn].get(key, 0.0)) if existing is None else float(existing)
                with cw:
                    val = st.number_input(
                        label, value=init_val,
                        min_value=float(min_v), max_value=float(max_v),
                        step=float(step), format=fmt,
                        key=wk, label_visibility="collapsed",
                    )
                out[sn] = val
            return out

        def _sc_int_row(label, key, min_v, max_v, step=1, help_text=None, badges=None):
            """Render one integer parameter row."""
            rl, rlo, rmi, rhi = st.columns([2.5, 2, 2, 2])
            with rl:
                st.markdown(_info_label(label, help_text, top_pad=6, size=13, badges=badges), unsafe_allow_html=True)
            out = {}
            for cw, sn in zip([rlo, rmi, rhi], _SC_LABELS):
                wk = f"sc_{sn}_{key}"
                existing = st.session_state.get(wk, None)
                init_val = int(_sc[sn].get(key, min_v)) if existing is None else int(existing)
                with cw:
                    val = st.number_input(
                        label, value=init_val,
                        min_value=int(min_v), max_value=int(max_v),
                        step=int(step),
                        key=wk, label_visibility="collapsed",
                    )
                out[sn] = int(val)
            return out

        _roic_vals  = _sc_float_row("ROI (%)",                     "roic", 0.1,  200.0, 0.5, help_text=_SC_HELP["roic"], badges=["DCF"])
        _g_vals     = _sc_float_row("Revenue Growth g (%)",        "g",    0.0,  100.0, 0.5, help_text=_SC_HELP["g"],    badges=["PE", "DCF"])
        _op_vals    = _sc_float_row("Operating Margin – pre-tax (%)", "op",   0.0,  100.0, 0.5, help_text=_SC_HELP["op"],   badges=["PE", "DCF"])
        _r_vals     = _sc_float_row("Desired Annual Return r (%)", "r",    0.0,  100.0, 0.5, help_text=_SC_HELP["r"],    badges=["PE", "DCF"])
        _pe_vals    = _sc_float_row("Exit P/E multiple",           "pe",   1.0,  300.0, 1.0, help_text=_SC_HELP["pe"],   badges=["PE"])
        _pfcf_vals  = _sc_float_row("Exit P/FCF multiple",         "pfcf", 1.0,  300.0, 1.0, help_text=_SC_HELP["pfcf"], badges=["DCF"])
        _n_vals     = _sc_int_row("Projection horizon n (years)",  "n",    1,    50,         help_text=_SC_HELP["n"],    badges=["PE", "DCF"])
        _dg_vals    = _sc_float_row("Dividend growth dg (%)",      "dg",   0.0,   50.0, 0.5, help_text=_SC_HELP["dg"])

        # update session state dict from widgets
        for _sn in _SC_LABELS:
            _sc[_sn]["roic"] = _roic_vals[_sn]
            _sc[_sn]["g"]    = _g_vals[_sn]
            _sc[_sn]["op"]   = _op_vals[_sn]
            _sc[_sn]["r"]    = _r_vals[_sn]
            _sc[_sn]["pe"]   = _pe_vals[_sn]
            _sc[_sn]["pfcf"] = _pfcf_vals[_sn]
            _sc[_sn]["n"]    = _n_vals[_sn]
            _sc[_sn]["dg"]   = _dg_vals[_sn]

        # ── FCF margin row (implied + optional override) ───────────────────

        st.markdown(
            "<div style='height:8px'></div>",
            unsafe_allow_html=True,
        )

        _fcf_lbl, _fcf_lo, _fcf_mi, _fcf_hi = st.columns([2.5, 2, 2, 2])
        with _fcf_lbl:
            st.markdown(
                _info_label("FCF margin (%)", _SC_HELP["fcf"], subtext="auto-implied or manual override", top_pad=0, size=13, weight=700, badges=["DCF"]),
                unsafe_allow_html=True,
            )

        _effective_fcf_dec = {}  # decimal values used in computations

        for _cw, _sn in zip([_fcf_lo, _fcf_mi, _fcf_hi], _SC_LABELS):
            with _cw:
                _impl_pct = _sc_implied_fcf(
                    _roic_vals[_sn], _g_vals[_sn], _op_vals[_sn], _tax_pct
                )
                _roic_d = _roic_vals[_sn] / 100.0
                _g_d    = _g_vals[_sn]    / 100.0

                # ── validation warnings ──
                if _roic_d <= 0:
                    st.warning("ROIC ≤ 0 → implied N/A")
                elif _g_d >= _roic_d and _g_d > 0:
                    st.warning("⚠️ Growth ≥ ROIC → value-destructive growth / implied reinvestment ≥ 100%")
                elif not np.isnan(_impl_pct) and (_impl_pct > 60.0 or _impl_pct < -20.0):
                    st.caption("⚠️ Check assumptions — implied FCF margin extreme")

                _impl_str = f"{_impl_pct:.1f}%" if not np.isnan(_impl_pct) else "N/A"
                st.caption(f"Implied: **{_impl_str}**")

                # ── override toggle ──
                _ovr_wk = f"sc_{_sn}_override"
                _ovr_on = st.checkbox(
                    "Manual override",
                    value=bool(_sc[_sn].get("override", False)),
                    help=_SC_HELP["fcf_override"],
                    key=_ovr_wk,
                )
                _sc[_sn]["override"] = _ovr_on

                if _ovr_on:
                    _def_ovr = float(_sc[_sn].get("fcf_ovr", 0.0))
                    if np.isnan(_def_ovr):
                        _def_ovr = 0.0
                    _ovr_v = st.number_input(
                        "FCF margin override (%)",
                        value=_def_ovr,
                        min_value=-100.0, max_value=100.0,
                        step=0.5, format="%.1f",
                        key=f"sc_{_sn}_fcf_ovr_input",
                        label_visibility="collapsed",
                    )
                    _sc[_sn]["fcf_ovr"] = _ovr_v
                    st.caption(f"✅ Using: **{_ovr_v:.1f}%**")
                    _effective_fcf_dec[_sn] = _ovr_v / 100.0
                else:
                    if not np.isnan(_impl_pct):
                        # clamp to [-100%, +100%]
                        _clamped = max(-100.0, min(100.0, _impl_pct))
                        _effective_fcf_dec[_sn] = _clamped / 100.0
                        st.caption(f"Using implied: **{_clamped:.1f}%**")
                    else:
                        _effective_fcf_dec[_sn] = np.nan
                        st.caption("Using implied: **N/A**")

        st.session_state[_SC_KEY] = _sc

        # ── DPS_0: base dividend per share for all scenarios ─────────────
        _dps_0    = np.nan
        _dps_warn = False
        try:
            _dps_0 = _safe_float(effective_df.loc["TTM", "Dividend per share"])
        except Exception:
            pass
        if np.isnan(_dps_0):
            try:
                _dy = _safe_float(effective_df.loc["TTM", "Dividend Yield"])
                if not np.isnan(_dy) and not np.isnan(_d_price) and _d_price > 0:
                    _dps_0 = _dy * _d_price
            except Exception:
                pass
        if np.isnan(_dps_0):
            _dps_0    = 0.0
            _dps_warn = True

        # ══════════════════════════════════════════════════════════════════
        # OUTPUTS
        # ══════════════════════════════════════════════════════════════════

        st.markdown("---")
        with st.container(border=True):
            st.markdown(
                "<span style='font-size:18px;font-weight:700;color:#4f8ef7;letter-spacing:0.5px;'>"
                "Scenario Outputs (per share):"
                "</span>",
                unsafe_allow_html=True,
            )

            _sc_outputs = {}  # capture for FULL snapshot
            # ── compute all three scenarios, then render cards ──
            for _sn_c in _SC_LABELS:
                _g_d   = _sc[_sn_c]["g"]    / 100.0
                _op_d  = _sc[_sn_c]["op"]   / 100.0
                _r_d   = _sc[_sn_c]["r"]    / 100.0
                _pe    = float(_sc[_sn_c]["pe"])
                _pfcf  = float(_sc[_sn_c]["pfcf"])
                _n     = int(_sc[_sn_c]["n"])
                _fcm   = _effective_fcf_dec[_sn_c]
                _tax_d = _tax_pct / 100.0
                _rev0  = _d_rev0
                _sh    = _d_shares
                _p0    = _d_price

                _fv_pe      = np.nan
                _price_n_pe = np.nan
                try:
                    if not (np.isnan(_rev0) or np.isnan(_sh) or _sh <= 0 or _n <= 0):
                        _rev_n      = _rev0 * (1.0 + _g_d) ** _n
                        _ni_n       = _rev_n * _op_d * (1.0 - _tax_d)
                        _price_n_pe = _ni_n * _pe / _sh
                        _fv_pe      = _price_n_pe / (1.0 + _r_d) ** _n
                except Exception:
                    pass

                _fv_dcf      = np.nan
                _gordon_warn = False
                try:
                    if not (np.isnan(_rev0) or np.isnan(_sh) or _sh <= 0
                            or np.isnan(_fcm) or _n <= 0):
                        _pv_sum = sum(
                            _rev0 * (1.0 + _g_d) ** _t * _fcm / (1.0 + _r_d) ** _t
                            for _t in range(1, _n + 1)
                        )
                        _fcf_n = _rev0 * (1.0 + _g_d) ** _n * _fcm
                        if _terminal_mode == "Perpetual growth (Gordon)":
                            _g_term_d = _g_terminal_pct / 100.0
                            if _r_d <= _g_term_d:
                                _gordon_warn = True
                                _term_pv     = np.nan
                            else:
                                _tv_n    = _fcf_n * (1.0 + _g_term_d) / (_r_d - _g_term_d)
                                _term_pv = _tv_n / (1.0 + _r_d) ** _n
                        else:
                            _term_pv = (_fcf_n * _pfcf) / (1.0 + _r_d) ** _n
                        if not np.isnan(_term_pv):
                            _fv_dcf = (_pv_sum + _term_pv) / _sh
                except Exception:
                    pass

                _cagr_pe = np.nan
                try:
                    if not (np.isnan(_p0) or _p0 <= 0
                            or np.isnan(_price_n_pe) or _price_n_pe <= 0 or _n <= 0):
                        _cagr_pe = (_price_n_pe / _p0) ** (1.0 / _n) - 1.0
                except Exception:
                    pass

                _dg_d_sc   = _sc[_sn_c].get("dg", 0.0) / 100.0
                _div_tax_d = _div_tax_pct / 100.0
                _cum_div   = sum(
                    _dps_0 * (1.0 + _dg_d_sc) ** _t * (1.0 - _div_tax_d)
                    for _t in range(1, _n + 1)
                )
                _cagr_total = np.nan
                try:
                    if not (np.isnan(_p0) or _p0 <= 0
                            or np.isnan(_price_n_pe) or _price_n_pe <= 0 or _n <= 0):
                        _cagr_total = ((_price_n_pe + _cum_div) / _p0) ** (1.0 / _n) - 1.0
                except Exception:
                    pass

                _cagr_dcf = np.nan
                try:
                    if (not np.isnan(_fv_dcf) and _fv_dcf > 0
                            and not np.isnan(_p0) and _p0 > 0 and _n > 0):
                        _cagr_dcf = (_fv_dcf / _p0) ** (1.0 / _n) - 1.0
                except Exception:
                    pass

                _sc_outputs[_sn_c] = {
                    "scenario":          _sn_c,
                    "pe_fair_value":     _fv_pe,
                    "dcf_fair_value":    _fv_dcf,
                    "cagr_via_pe_exit":  _cagr_pe,
                    "cagr_via_dcf_exit": _cagr_dcf,
                    "cagr_total_return": _cagr_total,
                    "cum_div_after_tax": _cum_div,
                }
                if _gordon_warn:
                    st.warning(f"⚠️ {_sn_c}: r ≤ g_terminal → Gordon TV undefined")

            if _dps_warn:
                st.caption(
                    "⚠️ Dividend per share not found – dividends set to $0 "
                    "(Total return CAGR ≈ Price CAGR)"
                )

            # ── render scenario cards ──
            def _adv_td(val, fmt="currency", weight="700", price=float("nan")):
                if val != val:  # isnan
                    return f"<td style='text-align:right;font-weight:{weight};color:#93a3b8'>N/A</td>"
                if fmt == "pct":
                    _c = "#66BB6A" if val >= 0 else "#FF7043"
                    return f"<td style='text-align:right;font-weight:{weight};color:{_c}'>{val:.1%}</td>"
                _c = _fv_clr(val, price)
                _col_style = f";color:{_c}" if _c != "#93a3b8" else ""
                return f"<td style='text-align:right;font-weight:{weight}{_col_style}'>${val:,.2f}</td>"

            _adv_card_cols = st.columns(3)
            for _cw, _sn in zip(_adv_card_cols, _SC_LABELS):
                with _cw:
                    _cc       = _SC_COLORS[_sn]
                    _sv       = _sc_outputs.get(_sn, {})
                    _fv_pe_c  = _sv.get("pe_fair_value",     float("nan"))
                    _fv_dcf_c = _sv.get("dcf_fair_value",    float("nan"))
                    _cpe_c    = _sv.get("cagr_via_pe_exit",  float("nan"))
                    _cdcf_c   = _sv.get("cagr_via_dcf_exit", float("nan"))
                    _ctot_c   = _sv.get("cagr_total_return", float("nan"))
                    _p0_c     = _d_price
                    _pe_sec = (
                        "<tr><td colspan='2' style='font-size:11px;font-weight:700;"
                        "color:#93a3b8;padding:4px 0 2px;letter-spacing:0.5px'>"
                        "── P/E MODEL ──</td></tr>"
                        f"<tr><td style='color:#93a3b8;padding:2px 0;font-size:13px'>Fair Value (P/E)</td>"
                        f"{_adv_td(_fv_pe_c, price=_p0_c)}</tr>"
                        f"<tr><td style='color:#93a3b8;padding:2px 0;font-size:13px'>CAGR (P/E exit)</td>"
                        f"{_adv_td(_cpe_c, 'pct')}</tr>"
                        f"<tr><td style='color:#93a3b8;padding:2px 0;font-size:13px'>CAGR (celkový výnos)</td>"
                        f"{_adv_td(_ctot_c, 'pct')}</tr>"
                    )
                    _dcf_sec = (
                        "<tr><td colspan='2' style='font-size:11px;font-weight:700;"
                        "color:#93a3b8;padding:6px 0 2px;letter-spacing:0.5px'>"
                        "── DCF MODEL ──</td></tr>"
                        f"<tr><td style='color:#93a3b8;padding:2px 0;font-size:13px'>Fair Value (DCF)</td>"
                        f"{_adv_td(_fv_dcf_c, price=_p0_c)}</tr>"
                        f"<tr><td style='color:#93a3b8;padding:2px 0;font-size:13px'>CAGR (DCF exit)</td>"
                        f"{_adv_td(_cdcf_c, 'pct')}</tr>"
                    )
                    _cur_row = ""
                    if not np.isnan(_p0_c):
                        _cur_row = (
                            "<tr style='border-top:1px solid rgba(255,255,255,0.1)'>"
                            f"<td style='color:#93a3b8;padding:4px 0 2px;font-size:13px'>Aktuální cena</td>"
                            f"<td style='text-align:right;font-weight:400'>${_p0_c:,.2f}</td></tr>"
                        )
                    st.markdown(
                        f"<div style='background:rgba(255,255,255,0.05);border-radius:10px;"
                        f"padding:14px 16px;border-left:4px solid {_cc}'>"
                        f"<div style='font-weight:700;color:{_cc};font-size:15px;margin-bottom:8px'>{_sn}</div>"
                        f"<table style='width:100%;font-size:13px;border-collapse:collapse'>"
                        f"{_pe_sec}{_dcf_sec}{_cur_row}</table></div>",
                        unsafe_allow_html=True,
                    )
        # ── Build scenario DataFrames for snapshot ────────────────────────
        _snap_scenario_inputs_df = pd.DataFrame([
            {
                "scenario": _sn,
                "roic": _sc[_sn]["roic"],
                "g": _sc[_sn]["g"],
                "op": _sc[_sn]["op"],
                "r": _sc[_sn]["r"],
                "pe": _sc[_sn]["pe"],
                "pfcf": _sc[_sn]["pfcf"],
                "n": _sc[_sn]["n"],
                "dg": _sc[_sn].get("dg", 0.0),
                "override": _sc[_sn].get("override", False),
                "fcf_ovr": _sc[_sn].get("fcf_ovr", 0.0),
                "tax_rate": _tax_pct,
                "div_tax_rate": _div_tax_pct,
                "terminal_mode": _terminal_mode,
                "g_terminal": _g_terminal_pct,
            }
            for _sn in _SC_LABELS
        ])
        _snap_scenario_outputs_df = pd.DataFrame(list(_sc_outputs.values())) if _sc_outputs else pd.DataFrame()

        # ── Charts: historical stock price + scenario projections ─────────
        _hist_price_rows = []
        if "Stock Price" in effective_df.columns:
            for _yr in effective_df.index:
                if str(_yr) == "TTM":
                    continue  # TTM used as forecast bridge, not in historical series
                _pv = _safe_float(effective_df.loc[_yr, "Stock Price"])
                if not np.isnan(_pv):
                    _hist_price_rows.append({"Year": str(_yr), "Scenario": "Historická", "Value": _pv})

        _hist_years_num_for_fc = []
        for _yr in effective_df.index:
            _ys = str(_yr)
            if _ys == "TTM":
                continue
            try:
                _hist_years_num_for_fc.append(int(_ys))
            except Exception:
                continue
        _forecast_base_year = max(_hist_years_num_for_fc) if _hist_years_num_for_fc else (pd.Timestamp.today().year - 1)

        # Price anchor: last historical year's actual price
        _fby_s_ch = str(_forecast_base_year)
        _d_price_anchor = next((r["Value"] for r in _hist_price_rows if r["Year"] == _fby_s_ch), _d_price)

        _fore_pe_rows  = []
        _fore_dcf_rows = []

        for _sn in _SC_LABELS:
            if np.isnan(_d_rev0) or np.isnan(_d_shares) or _d_shares <= 0:
                continue
            _g_d2   = _sc[_sn]["g"]    / 100.0
            _op_d2  = _sc[_sn]["op"]   / 100.0
            _r_d2   = _sc[_sn]["r"]    / 100.0
            _pe2    = float(_sc[_sn]["pe"])
            _pfcf2  = float(_sc[_sn]["pfcf"])
            _n2     = int(_sc[_sn]["n"])
            _fcm2   = _effective_fcf_dec.get(_sn, np.nan)
            _tax_d2 = _tax_pct / 100.0

            # Anchor forecast at last historical year actual price
            if not np.isnan(_d_price_anchor):
                _fore_pe_rows.append( {"Year": str(_forecast_base_year), "Scenario": _sn, "Value": _d_price_anchor})
                _fore_dcf_rows.append({"Year": str(_forecast_base_year), "Scenario": _sn, "Value": _d_price_anchor})

            for _t in range(1, _n2 + 1):
                try:
                    _rev_t2     = _d_rev0 * (1.0 + _g_d2) ** _t
                    _price_t_pe = _rev_t2 * _op_d2 * (1.0 - _tax_d2) * _pe2 / _d_shares
                    _fore_pe_rows.append({"Year": str(_forecast_base_year + _t), "Scenario": _sn, "Value": _price_t_pe})
                except Exception:
                    pass
            # DCF graf: pouze finální-rok hodnota z output sekce (rolling terminal value na každý rok byl zavádějící –
            # každý intermediate bod měl jiný TV ze svého FCF, nikoliv terminální hodnotu na konci horizonta).
            _dcf_fv_final = _sc_outputs.get(_sn, {}).get("dcf_fair_value", np.nan)
            if not np.isnan(_dcf_fv_final):
                _fore_dcf_rows.append({"Year": str(_forecast_base_year + _n2), "Scenario": _sn, "Value": _dcf_fv_final})

        _sc_domain_ch = ["Historická"] + _SC_LABELS
        _sc_range_ch  = ["#4f8ef7", "#FF7043", "#FFD54F", "#66BB6A"]
        _sc_cscale_ch = alt.Scale(domain=_sc_domain_ch, range=_sc_range_ch)

        _hist_yrs_num_ch = []
        if not effective_df.empty:
            for y in effective_df.index:
                y_str = str(y)
                if y_str == "TTM":
                    continue
                try:
                    _hist_yrs_num_ch.append(int(y_str))
                except Exception:
                    continue
        _hist_yr_strs_ch = [str(y) for y in sorted(set(_hist_yrs_num_ch))]
        _max_n_ch = max((int(_sc[_sn]["n"]) for _sn in _SC_LABELS), default=10)
        _fore_yr_strs_ch = [str(_forecast_base_year)] + [str(_forecast_base_year + _t) for _t in range(1, _max_n_ch + 1)]
        _full_yr_order_ch = _hist_yr_strs_ch + _fore_yr_strs_ch

        _hist_price_cdf = pd.DataFrame(_hist_price_rows) if _hist_price_rows else pd.DataFrame()

        if not _hist_price_cdf.empty or _fore_pe_rows or _fore_dcf_rows:
            # P/E chart domain: hist price + P/E forecast rows
            _pe_years = {r["Year"] for r in _hist_price_rows + _fore_pe_rows}
            _pe_domain_ch = list(dict.fromkeys(y for y in _full_yr_order_ch if y in _pe_years))
            _x_enc_ch = alt.X("Year:N", sort=_pe_domain_ch, scale=alt.Scale(domain=_pe_domain_ch), title="Rok")

            def _sc_hist_layer(title_y):
                return alt.Chart(_hist_price_cdf).mark_line(strokeWidth=2, point=True).encode(
                    x=_x_enc_ch,
                    y=alt.Y("Value:Q", title=title_y),
                    color=alt.Color("Scenario:N", scale=_sc_cscale_ch, title="Scénář"),
                    tooltip=["Year", "Scenario", alt.Tooltip("Value:Q", format=".2f", title="Cena $")],
                )

            # ── P/E chart ──────────────────────────────────────────────────
            _pe_layers = []
            if not _hist_price_cdf.empty:
                _pe_layers.append(_sc_hist_layer("Cena / P/E FV ($)"))
            if _fore_pe_rows:
                _fore_pe_cdf = pd.DataFrame(_fore_pe_rows)
                _pe_layers.append(
                    alt.Chart(_fore_pe_cdf).mark_line(strokeWidth=2, strokeDash=[4, 2], point=True).encode(
                        x=_x_enc_ch,
                        y=alt.Y("Value:Q"),
                        color=alt.Color("Scenario:N", scale=_sc_cscale_ch),
                        tooltip=["Year", "Scenario", alt.Tooltip("Value:Q", format=".2f", title="P/E FV $")],
                    )
                )
            if _pe_layers:
                st.altair_chart(
                    alt.layer(*_pe_layers)
                    .properties(title="P/E Fair Value — Historická cena + Projekce", height=300)
                    .configure_view(strokeOpacity=0),
                    width="stretch",
                )

            # ── DCF chart ─────────────────────────────────────────────────
            _dcf_layers = []
            _dcf_years = {r["Year"] for r in _hist_price_rows + _fore_dcf_rows}
            _dcf_domain_ch = list(dict.fromkeys(y for y in _full_yr_order_ch if y in _dcf_years))
            _x_enc_dcf = alt.X("Year:N", sort=_dcf_domain_ch, scale=alt.Scale(domain=_dcf_domain_ch), title="Rok")
            if not _hist_price_cdf.empty:
                _dcf_layers.append(
                    alt.Chart(_hist_price_cdf).mark_line(strokeWidth=2, point=True).encode(
                        x=_x_enc_dcf,
                        y=alt.Y("Value:Q", title="Cena / DCF FV ($)"),
                        color=alt.Color("Scenario:N", scale=_sc_cscale_ch, title="Scénář"),
                        tooltip=["Year", "Scenario", alt.Tooltip("Value:Q", format=".2f", title="Cena $")],
                    )
                )
            if _fore_dcf_rows:
                _fore_dcf_cdf = pd.DataFrame(_fore_dcf_rows)
                _dcf_layers.append(
                    alt.Chart(_fore_dcf_cdf).mark_line(strokeWidth=2, strokeDash=[4, 2], point=True).encode(
                        x=_x_enc_dcf,
                        y=alt.Y("Value:Q"),
                        color=alt.Color("Scenario:N", scale=_sc_cscale_ch),
                        tooltip=["Year", "Scenario", alt.Tooltip("Value:Q", format=".2f", title="DCF FV $")],
                    )
                )
            if _dcf_layers:
                st.altair_chart(
                    alt.layer(*_dcf_layers)
                    .properties(title="Equity DCF Fair Value — Historická cena + Projekce", height=300)
                    .configure_view(strokeOpacity=0),
                    width="stretch",
                )

        # ── Uložit analýzu ───────────────────────────────────────────────
        try:
            _full_bytes = build_snapshot_excel_bytes(
                effective_df=effective_df,
                metrics_df=metrics_df,
                manual_df=st.session_state.val_manual_df,
                override_mask=override_mask,
                scope="FULL",
                ticker=st.session_state.val_ticker,
                years=st.session_state.val_years,
                current_price=float(_d_price) if not np.isnan(_d_price) else np.nan,
                scenario_inputs_df=_snap_scenario_inputs_df,
                scenario_outputs_df=_snap_scenario_outputs_df,
            )
            _adv_all_bytes = build_all_excel_bytes(
                effective_df=effective_df,
                metrics_df=metrics_df,
                manual_df=st.session_state.val_manual_df,
                override_mask=override_mask,
                ticker=st.session_state.val_ticker,
                years=st.session_state.val_years,
                current_price=float(_d_price) if not np.isnan(_d_price) else np.nan,
                scenario_inputs_df=_snap_scenario_inputs_df,
                scenario_outputs_df=_snap_scenario_outputs_df,
                simple_eps_params=st.session_state.get("simple_eps_params", {}),
                simple_rev_params=st.session_state.get("simple_rev_params", {}),
                damodaran_params=st.session_state.get("damodaran_params", {}),
            )
            _full_fname     = f"{st.session_state.val_ticker}_{datetime.now().strftime('%y_%m_%d')}.xlsx"
            _adv_all_fname  = f"{st.session_state.val_ticker}_vse_{datetime.now().strftime('%y_%m_%d')}.xlsx"
            _full_col1, _full_col2 = st.columns([1, 1])
            with _full_col1:
                st.download_button(
                    "💾 Uložit tento model (včetně historických dat)",
                    data=_full_bytes,
                    file_name=_full_fname,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="snap_full_save_btn",
                    width="stretch",
                )
            with _full_col2:
                st.download_button(
                    "💾 Uložit všechny modely (včetně historických dat)",
                    data=_adv_all_bytes,
                    file_name=_adv_all_fname,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="snap_adv_all_btn",
                    width="stretch",
                )
        except Exception as _exc:
            st.warning(f"Uložení selhalo: {_exc}")

        # ── Current price reference ────────────────────────────────────────
        if not np.isnan(_d_price):
            st.caption(
                f"Current price (TTM): **${_d_price:.2f}**  |  "
                f"Shares (TTM): **{_d_shares:,.0f}**  |  "
                f"Revenue₀ (TTM): **${_d_rev0:,.0f}**"
                if not np.isnan(_d_shares) and not np.isnan(_d_rev0)
                else f"Current price (TTM): **${_d_price:.2f}**"
            )

        # -- Sensitivity matrix Advanced P/E (g x r) ---------------------------------------
        with st.expander("🔲 Citlivost P/E (g × r) – Mid scénář", expanded=False):
            try:
                _adv_mid = _sc["Mid"]
                _adv_g_c = _adv_mid["g"]
                _adv_op  = _adv_mid["op"]
                _adv_pe  = _adv_mid["pe"]
                _adv_n   = int(_adv_mid["n"])
                _adv_r_c = _adv_mid["r"]
                _adv_tax = float(st.session_state.get("sc_tax_rate_pct", 21.0))
                if np.isnan(_d_rev0) or np.isnan(_d_shares) or _d_shares <= 0:
                    st.info("Chybí TTM Revenue nebo Shares.")
                else:
                    _adv_g_vals = [round(_adv_g_c + d, 1) for d in range(-6, 7)]
                    _adv_r_vals = [round(_adv_r_c + d, 1) for d in range(-6, 7)]
                    _adv_data = []
                    for _g_v in _adv_g_vals:
                        _rowa = {"g (%)": f"{_g_v:.1f}%"}
                        for _r_v in _adv_r_vals:
                            _rev_n_a = _d_rev0 * (1 + _g_v / 100) ** _adv_n
                            _ep_a    = _rev_n_a * _adv_op / 100 * (1 - _adv_tax / 100)
                            _fp_a    = _ep_a * _adv_pe / _d_shares if _d_shares > 0 else float("nan")
                            _fva     = (_fp_a / (1 + _r_v / 100) ** _adv_n
                                        if (_adv_n > 0 and not np.isnan(_fp_a)) else float("nan"))
                            _rowa[f"r {_r_v:.1f}%"] = round(_fva, 2)
                        _adv_data.append(_rowa)
                    _adv_sm_df = pd.DataFrame(_adv_data).set_index("g (%)")
                    _adv_sm_df_num = _adv_sm_df.apply(pd.to_numeric, errors="coerce")
                    _adv_mid_row = f"{_adv_g_c:.1f}%"
                    _adv_mid_col = f"r {_adv_r_c:.1f}%"
                    _adv_sm_styled = _sm_heatmap_style(
                        _adv_sm_df_num,
                        price=_d_price if not np.isnan(_d_price) else None,
                        mid_row=_adv_mid_row,
                        mid_col=_adv_mid_col,
                    )
                    st.caption(
                        f"Rev₀ = ${_d_rev0:,.0f}  |  Op.Margin = {_adv_op:.1f}%  "
                        f"|  Tax = {_adv_tax:.1f}%  |  Exit P/E = {_adv_pe:.1f}  |  n = {_adv_n}  "
                        f"|  Řádky = g, sloupce = r (Mid ± 6 pp)  |  🟡 = Mid baseline"
                    )
                    st.dataframe(_adv_sm_styled, use_container_width=True)
                    if not np.isnan(_d_price):
                        st.caption(f"Aktuální cena: ${_d_price:.2f}")
            except Exception as _adv_sm_exc:
                st.warning(f"Citlivostní matice se nepodařila: {_adv_sm_exc}")

        # -- Sensitivity matrix Advanced DCF (g x r) ----------------------------------------
        with st.expander("🔲 Citlivost DCF (g × r) – Mid scénář", expanded=False):
            try:
                _adv_dcf_mid  = _sc["Mid"]
                _adv_dcf_g_c  = _adv_dcf_mid["g"]
                _adv_dcf_r_c  = _adv_dcf_mid["r"]
                _adv_dcf_pfcf = float(_adv_dcf_mid["pfcf"])
                _adv_dcf_n    = int(_adv_dcf_mid["n"])
                _adv_dcf_fcm  = _effective_fcf_dec.get("Mid", np.nan)
                if np.isnan(_d_rev0) or np.isnan(_d_shares) or _d_shares <= 0:
                    st.info("Chybí TTM Revenue nebo Shares.")
                elif np.isnan(_adv_dcf_fcm):
                    st.info("FCF margin (Mid) není dostupná – zkontroluj ROIC / override.")
                else:
                    _adv_dcf_g_vals = [round(_adv_dcf_g_c + d, 1) for d in range(-6, 7)]
                    _adv_dcf_r_vals = [round(_adv_dcf_r_c + d, 1) for d in range(-6, 7)]
                    _adv_dcf_data   = []
                    for _gv in _adv_dcf_g_vals:
                        _row_dcf = {"g (%)": f"{_gv:.1f}%"}
                        for _rv in _adv_dcf_r_vals:
                            _g = _gv / 100.0; _r = _rv / 100.0
                            try:
                                _pv_dcf = sum(
                                    _d_rev0 * (1 + _g) ** t * _adv_dcf_fcm / (1 + _r) ** t
                                    for t in range(1, _adv_dcf_n + 1)
                                )
                                _fcf_n_dcf = _d_rev0 * (1 + _g) ** _adv_dcf_n * _adv_dcf_fcm
                                if _terminal_mode == "Perpetual growth (Gordon)":
                                    _gt_d = _g_terminal_pct / 100.0
                                    _tv_dcf = (
                                        _fcf_n_dcf * (1 + _gt_d) / (_r - _gt_d) / (1 + _r) ** _adv_dcf_n
                                        if _r > _gt_d else np.nan
                                    )
                                else:
                                    _tv_dcf = _fcf_n_dcf * _adv_dcf_pfcf / (1 + _r) ** _adv_dcf_n
                                _iv_dcf = ((_pv_dcf + _tv_dcf) / _d_shares
                                           if not np.isnan(_tv_dcf) else np.nan)
                            except Exception:
                                _iv_dcf = np.nan
                            _row_dcf[f"r {_rv:.1f}%"] = (round(_iv_dcf, 2)
                                                          if not np.isnan(_iv_dcf) else None)
                        _adv_dcf_data.append(_row_dcf)
                    _adv_dcf_df     = pd.DataFrame(_adv_dcf_data).set_index("g (%)")
                    _adv_dcf_df_num = _adv_dcf_df.apply(pd.to_numeric, errors="coerce")
                    _adv_dcf_mid_row = f"{_adv_dcf_g_c:.1f}%"
                    _adv_dcf_mid_col = f"r {_adv_dcf_r_c:.1f}%"
                    _adv_dcf_tv_lbl  = (
                        f"g_term = {_g_terminal_pct:.1f}%"
                        if _terminal_mode == "Perpetual growth (Gordon)"
                        else f"Exit P/FCF = {_adv_dcf_pfcf:.1f}"
                    )
                    _adv_dcf_styled = _sm_heatmap_style(
                        _adv_dcf_df_num,
                        price=_d_price if not np.isnan(_d_price) else None,
                        mid_row=_adv_dcf_mid_row,
                        mid_col=_adv_dcf_mid_col,
                    )
                    st.caption(
                        f"Rev₀ = ${_d_rev0:,.0f}  |  FCF margin = {_adv_dcf_fcm * 100:.1f}%  "
                        f"|  TV: {_adv_dcf_tv_lbl}  |  n = {_adv_dcf_n}  "
                        f"|  Řádky = g, sloupce = r (Mid ± 6 pp)  |  🟡 = Mid baseline"
                    )
                    st.dataframe(_adv_dcf_styled, use_container_width=True)
                    if not np.isnan(_d_price):
                        st.caption(f"Aktuální cena: ${_d_price:.2f}")
            except Exception as _adv_dcf_sm_exc:
                st.warning(f"Citlivostní matice DCF se nepodařila: {_adv_dcf_sm_exc}")

        # ── Monte Carlo — Advanced Valuation ──────────────────────────────────
        with st.expander("🎲 Monte Carlo simulace — Advanced Valuation", expanded=False):
            st.caption(
                "Simultánní náhodná variace g, Op. Margin a r. "
                "Zvol větev (P/E nebo DCF). σ lze přepsat. "
                "🟡 = percentily | 🔴 = aktuální cena"
            )
            if np.isnan(_d_rev0) or np.isnan(_d_shares) or _d_shares <= 0:
                st.info("Chybí TTM Revenue nebo Shares.")
            else:
                _mcadv_mid   = _sc["Mid"]
                _mcadv_g_mu  = float(_mcadv_mid["g"])
                _mcadv_op_mu = float(_mcadv_mid["op"])
                _mcadv_r_mu  = float(_mcadv_mid["r"])
                _mcadv_pe_mu = float(_mcadv_mid["pe"])
                _mcadv_pf_mu = float(_mcadv_mid["pfcf"])
                _mcadv_n     = int(_mcadv_mid["n"])
                _mcadv_tax   = _tax_pct / 100.0

                _mcadv_g_sigma  = max(2.0, round(float(_mcadv_g_mu * rev_gcv) if (
                    not np.isnan(rev_gcv) and rev_gcv > 0) else 3.0, 1))
                _mcadv_op_sigma = round(float(pm_std) if not np.isnan(pm_std) else 2.5, 1)

                _mcadv_sub = st.radio("Větev simulace:", ["P/E Fair Value", "DCF Fair Value"],
                                       horizontal=True, key="mc_adv_branch")
                _mcadv_nsim = st.select_slider("Počet simulací", [1_000, 5_000, 10_000, 25_000],
                                                value=10_000, key="mc_adv_nsim")

                _mcadvc1, _mcadvc2, _mcadvc3, _mcadvc4 = st.columns(4)
                with _mcadvc1:
                    st.markdown("**Revenue growth g (%)**")
                    _mcadv_g_mu_in  = st.number_input("Průměr g", value=_mcadv_g_mu,
                                                       key="mc_adv_g_mu", format="%.1f")
                    _mcadv_g_sig_in = st.number_input("σ g", value=max(0.1, _mcadv_g_sigma),
                                                       min_value=0.1, key="mc_adv_g_sig",
                                                       format="%.1f",
                                                       help=(
                                                           "Co je σ (sigma)?\n"
                                                           "Odhadovaná nepřesnost tvoé projekce růstu.\n"
                                                           "Vyšší σ = v simulaci vyšší šance extrémních výsledků.\n"
                                                           "\n"
                                                           "Z čeho se počítá:\n"
                                                           "Historická kolisavost tržeb (koeficient variace).\n"
                                                           f"Předvyplněna: {_mcadv_g_sigma:.1f} pp z dat Revenue (max 7 let).\n"
                                                           "Minimální podlaha: 2 pp (i stabilní firma má riziko).\n"
                                                           "\n"
                                                           "Tahak pro ruční úpravu:\n"
                                                           "  1–3 pp • stabilní (utility, spotrební zboží)\n"
                                                           "  3–7 pp • běžné firmy (tech, průmysl)\n"
                                                           "  7–15+ pp • cyklické / rychle rostouci"
                                                       ))
                    st.caption(f"💡 90 % simulací: {_mcadv_g_mu_in - 1.645 * _mcadv_g_sig_in:.1f}–{_mcadv_g_mu_in + 1.645 * _mcadv_g_sig_in:.1f} %")
                with _mcadvc2:
                    st.markdown("**Op. Margin (%)**")
                    _mcadv_op_mu_in  = st.number_input("Průměr Op.M.", value=_mcadv_op_mu,
                                                        key="mc_adv_op_mu", format="%.1f")
                    _mcadv_op_sig_in = st.number_input("σ Op.M.", value=max(0.1, _mcadv_op_sigma),
                                                        min_value=0.1, key="mc_adv_op_sig",
                                                        format="%.1f",
                                                        help=(
                                                            "Co je σ (sigma)?\n"
                                                            "Nepřesnost tvoé projekce operační marže.\n"
                                                            "Vyšší σ = větší kolebání marže v simulaci.\n"
                                                            "\n"
                                                            "Z čeho se počítá:\n"
                                                            "Historická std dev Profit Margin (proxy pro Op.M.).\n"
                                                            f"Předvyplněna: {_mcadv_op_sigma:.1f} pp z dat (max 7 let).\n"
                                                            "\n"
                                                            "Tahak pro ruční úpravu:\n"
                                                            "  1–2 pp • extrémně stabilní marže\n"
                                                            "  2–5 pp • běžná firma\n"
                                                            "  5–10+ pp • cyklická / nestabilní marže"
                                                        ))
                    st.caption(f"💡 90 % simulací: {_mcadv_op_mu_in - 1.645 * _mcadv_op_sig_in:.1f}–{_mcadv_op_mu_in + 1.645 * _mcadv_op_sig_in:.1f} %")
                with _mcadvc3:
                    if _mcadv_sub == "P/E Fair Value":
                        st.markdown("**Exit P/E (uniform)**")
                        _mcadv_pe_lo = st.number_input("Min P/E",
                                                        value=max(5.0, round(_mcadv_pe_mu * 0.7, 1)),
                                                        key="mc_adv_pe_lo", format="%.1f")
                        _mcadv_pe_hi = st.number_input("Max P/E",
                                                        value=min(80.0, round(_mcadv_pe_mu * 1.3, 1)),
                                                        key="mc_adv_pe_hi", format="%.1f")
                    else:
                        st.markdown("**Exit P/FCF (uniform)**")
                        _mcadv_pf_lo = st.number_input("Min P/FCF",
                                                        value=max(5.0, round(_mcadv_pf_mu * 0.7, 1)),
                                                        key="mc_adv_pf_lo", format="%.1f")
                        _mcadv_pf_hi = st.number_input("Max P/FCF",
                                                        value=min(80.0, round(_mcadv_pf_mu * 1.3, 1)),
                                                        key="mc_adv_pf_hi", format="%.1f")
                with _mcadvc4:
                    st.markdown("**Diskontní sazba r (%) — fixní**")
                    _mcadv_r_fixed = st.number_input("r (fixní)", value=_mcadv_r_mu,
                                                      key="mc_adv_r_fixed", format="%.1f",
                                                      help=(
                                                          "🔒 Diskontní sazba je záměrně fixní.\n"
                                                          "Důvod: r ovlivňuje FV přes (1+r)^n — i malá\n"
                                                          "variace r produkuje extrémně asymetrické\n"
                                                          "rozdělení FV, obtížně interpretovatelné.\n"
                                                          "Vliv r na FV zobrazuje Tornado graf výše."
                                                      ))

                if st.button("▶ Spustit simulaci", key="mc_adv_run"):
                    _macrev0 = _d_rev0
                    _macsh   = _d_shares
                    _mactax  = _mcadv_tax
                    _macn    = _mcadv_n

                    if _mcadv_sub == "P/E Fair Value":
                        def _mc_adv_fv(g, op, pe, r):
                            try:
                                rn   = _macrev0 * (1 + g / 100) ** _macn
                                ni_n = rn * (op / 100) * (1 - _mactax)
                                fp   = ni_n * pe / _macsh
                                fv   = fp / (1 + r / 100) ** _macn
                                return fv if np.isfinite(fv) else np.nan
                            except Exception:
                                return np.nan
                        _mcadv_specs = [
                            {"name": "g",  "dist": "normal",  "mean": _mcadv_g_mu_in,  "std": _mcadv_g_sig_in},
                            {"name": "op", "dist": "normal",  "mean": _mcadv_op_mu_in, "std": _mcadv_op_sig_in},
                            {"name": "pe", "dist": "uniform", "low": _mcadv_pe_lo,     "high": _mcadv_pe_hi},
                            {"name": "r",  "dist": "fixed",   "value": _mcadv_r_fixed},
                        ]
                        _lbl = "Advanced P/E FV"
                    else:
                        _fcm_mc = _effective_fcf_dec.get("Mid", np.nan)
                        def _mc_adv_fv(g, pf, r):  # noqa: F811
                            try:
                                if np.isnan(_fcm_mc):
                                    return np.nan
                                _g = g / 100; _r = r / 100
                                pv = sum(_macrev0 * (1 + _g) ** t * _fcm_mc / (1 + _r) ** t
                                          for t in range(1, _macn + 1))
                                fcf_n = _macrev0 * (1 + _g) ** _macn * _fcm_mc
                                tv = fcf_n * pf / (1 + _r) ** _macn
                                return (pv + tv) / _macsh if np.isfinite(pv + tv) else np.nan
                            except Exception:
                                return np.nan
                        _mcadv_specs = [
                            {"name": "g",  "dist": "normal",  "mean": _mcadv_g_mu_in,  "std": _mcadv_g_sig_in},
                            {"name": "pf", "dist": "uniform", "low": _mcadv_pf_lo,     "high": _mcadv_pf_hi},
                            {"name": "r",  "dist": "fixed",   "value": _mcadv_r_fixed},
                        ]
                        _lbl = "Advanced DCF FV"

                    with st.spinner(f"Probíhá {_mcadv_nsim:,} simulací..."):
                        _mcadv_res = run_monte_carlo(_mc_adv_fv, _mcadv_specs,
                                                      n_sim=_mcadv_nsim,
                                                      current_price=_d_price)
                    if _mcadv_res:
                        render_mc_chart(_mcadv_res, _d_price, _lbl)
                    else:
                        st.warning("Simulace nevygenerovala platné výsledky.")

        with st.expander("🌪️ Analýza citlivosti (Tornado) – Advanced Valuation", expanded=False):
            st.caption(
                "🌪️ Tornado = citlivost one-at-a-time. Žlutá čára = baseline FV zvoleného scénáře (P/E FV; není-li dostupné, DCF FV). "
                "🟥 Červená = nižší FV výsledek  |  🟩 Zelená = vyšší FV výsledek. "
                "Delší pruh = větší citlivost. "
                "Δ pp (absolutně): r, Op. Margin, g. Δ % (relativně): Exit P/E, Exit P/FCF. "
                "⚠️ Gordon terminal vyžaduje r > g_terminal. Tornado mění vždy jen 1 parametr."
            )
            _ta_sn = st.selectbox(
                "Základní scénář:", _SC_LABELS,
                index=min(1, len(_SC_LABELS) - 1), key="tornado_adv_scenario",
            )
            _ta_sn_params = _sc.get(_ta_sn, {})
            st.caption(f"Scénář {_ta_sn}: g = {_ta_sn_params.get('g', float('nan')):.1f} %  |  Op.Margin = {_ta_sn_params.get('op', float('nan')):.1f} %  |  r = {_ta_sn_params.get('r', float('nan')):.1f} %  |  P/E = {_ta_sn_params.get('pe', float('nan')):.1f}  |  n = {int(_ta_sn_params.get('n', 0))} let")
            _ta_delta_pp   = st.number_input("Δ sazeb / marží – ± pp (r, Op. Margin, absolutně)", value=1.0, min_value=0.1, max_value=10.0, step=0.1, format="%.1f", key="tornado_adv_delta_pp")
            _ta_delta_g_pp = st.number_input("Δg – ± pp (Revenue growth g, absolutně v % bodech)", value=1.0, min_value=0.5, max_value=20.0, step=0.5, format="%.1f", key="tornado_adv_delta_g")
            _ta_delta_rel  = st.number_input("Δ PE / P/FCF – absolutní delta násobku", value=5.0, min_value=0.5, max_value=50.0, step=0.5, format="%.1f", key="tornado_adv_delta_rel")

            def _adv_fv_pe(g_pct, op_pct, r_pct, pe_val, n_yrs):
                try:
                    if np.isnan(_d_rev0) or np.isnan(_d_shares) or _d_shares <= 0 or n_yrs <= 0: return np.nan
                    _tax = _tax_pct / 100.0
                    _rn = _d_rev0 * (1.0 + g_pct / 100.0) ** n_yrs
                    _ni_n = _rn * (op_pct / 100.0) * (1.0 - _tax)
                    return (_ni_n * pe_val / _d_shares) / (1.0 + r_pct / 100.0) ** n_yrs
                except Exception:
                    return np.nan

            def _adv_fv_dcf(g_pct, r_pct, pfcf_val, n_yrs):
                try:
                    _fcm_v = _effective_fcf_dec[_ta_sn]
                    if np.isnan(_d_rev0) or np.isnan(_d_shares) or _d_shares <= 0 or np.isnan(_fcm_v) or n_yrs <= 0: return np.nan
                    _r = r_pct / 100.0; _g = g_pct / 100.0
                    _pv = sum(_d_rev0 * (1 + _g) ** t * _fcm_v / (1 + _r) ** t for t in range(1, n_yrs + 1))
                    _fcf_n = _d_rev0 * (1 + _g) ** n_yrs * _fcm_v
                    if _terminal_mode == "Perpetual growth (Gordon)":
                        _gt = _g_terminal_pct / 100.0
                        if _r <= _gt: return np.nan
                        _tv = _fcf_n * (1 + _gt) / (_r - _gt) / (1 + _r) ** n_yrs
                    else:
                        _tv = (_fcf_n * pfcf_val) / (1 + _r) ** n_yrs
                    return (_pv + _tv) / _d_shares
                except Exception:
                    return np.nan

            try:
                _ta_g    = _sc[_ta_sn]["g"]
                _ta_op   = _sc[_ta_sn]["op"]
                _ta_r    = _sc[_ta_sn]["r"]
                _ta_pe   = float(_sc[_ta_sn]["pe"])
                _ta_pfcf = float(_sc[_ta_sn]["pfcf"])
                _ta_n    = int(_sc[_ta_sn]["n"])
                _ta_base_pe  = _adv_fv_pe(_ta_g, _ta_op, _ta_r, _ta_pe, _ta_n)
                _ta_base_dcf = _adv_fv_dcf(_ta_g, _ta_r, _ta_pfcf, _ta_n)
                # ── helper: build and render one tornado chart ────────────
                def _render_ta_chart(impacts, baseline, model_lbl):
                    _df2 = pd.DataFrame(impacts).sort_values("RozsahAbs", ascending=False)
                    _df2["Baseline"]  = baseline
                    _df2["FV_nizka"]  = _df2["Nízká"]
                    _df2["FV_vysoka"] = _df2["Vysoká"]
                    _df2["DiffLo"]    = _df2["Nízká"]  - baseline
                    _df2["DiffHi"]    = _df2["Vysoká"] - baseline
                    _long2_rows = []
                    for _, _r in _df2.iterrows():
                        _bl = float(_r["Baseline"])
                        for _dc, _fc, _lbl in [("DiffLo","FV_nizka","Nižší FV"),("DiffHi","FV_vysoka","Vyšší FV")]:
                            _da = float(_r[_dc])
                            _long2_rows.append({"Parametr": str(_r["Parametr"]), "DiffAbs": _da,
                                "DiffPct": round(_da / _bl * 100, 2) if _bl else 0.0,
                                "Baseline": _bl, "FV_nizka": float(_r["FV_nizka"]),
                                "FV_vysoka": float(_r["FV_vysoka"]), "StranaCZ": _lbl,
                                "BarColor": "#66BB6A" if _da >= 0 else "#FF7043"})
                    _sort2 = list(_df2["Parametr"])
                    _h2   = max(150, len(impacts) * 50)
                    _ptxt = f"  |  Aktuální cena: ${_d_price:.2f}" if not np.isnan(_d_price) else ""
                    _sort2_tt = [
                        {"field": "Parametr", "type": "nominal"},
                        {"field": "StranaCZ", "type": "nominal", "title": "Výsledek"},
                        {"field": "Baseline", "type": "quantitative", "format": "$.2f", "title": "Baseline FV ($)"},
                        {"field": "FV_nizka", "type": "quantitative", "format": "$.2f", "title": "FV nižší ($)"},
                        {"field": "FV_vysoka", "type": "quantitative", "format": "$.2f", "title": "FV vysoká ($)"},
                        {"field": "DiffAbs", "type": "quantitative", "format": "+$.2f", "title": "Δ vs baseline ($)"},
                        {"field": "DiffPct", "type": "quantitative", "format": "+.1f", "title": "Δ vs baseline (%)"},
                    ]
                    st.vega_lite_chart({
                        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
                        "height": _h2,
                        "title": f"Tornado: Advanced ({model_lbl}) — {_ta_sn} scénář",
                        "config": {"view": {"strokeOpacity": 0}},
                        "layer": [
                            {"data": {"values": [r for r in _long2_rows if r["DiffAbs"] >= 0]}, "mark": {"type": "bar", "opacity": 0.75, "color": "#66BB6A"}, "encoding": {"y": {"field": "Parametr", "type": "nominal", "sort": _sort2, "title": None, "axis": {"labelOverlap": False, "labelLimit": 300}}, "x": {"field": "DiffAbs", "type": "quantitative", "title": "Δ Fair Value vs baseline ($)", "axis": {"grid": True}}, "tooltip": _sort2_tt}},
                            {"data": {"values": [r for r in _long2_rows if r["DiffAbs"] < 0]}, "mark": {"type": "bar", "opacity": 0.75, "color": "#FF7043"}, "encoding": {"y": {"field": "Parametr", "type": "nominal", "sort": _sort2}, "x": {"field": "DiffAbs", "type": "quantitative"}, "tooltip": _sort2_tt}},
                            {"data": {"values": _long2_rows}, "transform": [{"calculate": "format(datum.DiffPct, '+.1f') + '%'", "as": "_dp_label"}], "mark": {"type": "text", "fontSize": 10, "align": {"expr": "datum.DiffAbs >= 0 ? 'left' : 'right'"}, "dx": {"expr": "datum.DiffAbs >= 0 ? 4 : -4"}}, "encoding": {"y": {"field": "Parametr", "type": "nominal", "sort": _sort2}, "x": {"field": "DiffAbs", "type": "quantitative"}, "text": {"field": "_dp_label", "type": "nominal"}, "color": {"value": "#93a3b8"}}},
                            {"data": {"values": [{"x": 0}]}, "mark": {"type": "rule", "color": "#FFD54F", "strokeDash": [4, 2]}, "encoding": {"x": {"field": "x", "type": "quantitative"}}},
                        ],
                    }, width='stretch')
                    st.caption(f"Baseline {model_lbl} = ${baseline:.2f}{_ptxt}. Pruhy = Δ vs baseline. Žlutá čára = 0.")

                _any_ta_chart = False

                # ── P/E Tornado (parametry: g, Op. Margin, r, Exit P/E, n) ──
                if not np.isnan(_ta_base_pe):
                    _ta_pe_impacts = []
                    for _pname, _lo_v, _hi_v in [
                        (f"Revenue growth g (±{_ta_delta_g_pp:.1f}pp)", _adv_fv_pe(_ta_g - _ta_delta_g_pp, _ta_op, _ta_r, _ta_pe, _ta_n),
                                                 _adv_fv_pe(_ta_g + _ta_delta_g_pp, _ta_op, _ta_r, _ta_pe, _ta_n)),
                        (f"Op. Margin (±{_ta_delta_pp:.1f}pp)",        _adv_fv_pe(_ta_g, _ta_op - _ta_delta_pp, _ta_r, _ta_pe, _ta_n),
                                                 _adv_fv_pe(_ta_g, _ta_op + _ta_delta_pp, _ta_r, _ta_pe, _ta_n)),
                        (f"Discount rate r (±{_ta_delta_pp:.1f}pp)",   _adv_fv_pe(_ta_g, _ta_op, _ta_r + _ta_delta_pp, _ta_pe, _ta_n),
                                                 _adv_fv_pe(_ta_g, _ta_op, max(0.01, _ta_r - _ta_delta_pp), _ta_pe, _ta_n)),
                        (f"Exit P/E (±{_ta_delta_rel:.1f})",              _adv_fv_pe(_ta_g, _ta_op, _ta_r, max(0.5, _ta_pe - _ta_delta_rel), _ta_n),
                                                 _adv_fv_pe(_ta_g, _ta_op, _ta_r, _ta_pe + _ta_delta_rel, _ta_n)),
                        ("Years n (±1)",               _adv_fv_pe(_ta_g, _ta_op, _ta_r, _ta_pe, max(1, _ta_n - 1)),
                                                 _adv_fv_pe(_ta_g, _ta_op, _ta_r, _ta_pe, _ta_n + 1)),
                    ]:
                        if not (np.isnan(_lo_v) or np.isnan(_hi_v)):
                            _ta_pe_impacts.append({"Parametr": _pname, "Nízká": _lo_v, "Vysoká": _hi_v,
                                                   "RozsahAbs": abs(_hi_v - _lo_v)})
                    if _ta_pe_impacts:
                        _render_ta_chart(_ta_pe_impacts, _ta_base_pe, "P/E FV")
                        _any_ta_chart = True

                # ── DCF Tornado (parametry: g, r, Exit P/FCF, n) ─────────
                # Op. Margin is NOT a DCF parameter – FCF margin is fixed per scenario
                # in _effective_fcf_dec. Exit P/FCF is irrelevant in Gordon mode
                # (bar will be 0-width = informative).
                if not np.isnan(_ta_base_dcf):
                    _ta_dcf_impacts = []
                    _dcf_lbl = "DCF FV (Gordon)" if _terminal_mode == "Perpetual growth (Gordon)" else "DCF FV"
                    for _pname, _lo_v, _hi_v in [
                        (f"Revenue growth g (±{_ta_delta_g_pp:.1f}pp)", _adv_fv_dcf(_ta_g - _ta_delta_g_pp, _ta_r, _ta_pfcf, _ta_n),
                                                 _adv_fv_dcf(_ta_g + _ta_delta_g_pp, _ta_r, _ta_pfcf, _ta_n)),
                        (f"Discount rate r (±{_ta_delta_pp:.1f}pp)",   _adv_fv_dcf(_ta_g, _ta_r + _ta_delta_pp, _ta_pfcf, _ta_n),
                                                 _adv_fv_dcf(_ta_g, max(0.01, _ta_r - _ta_delta_pp), _ta_pfcf, _ta_n)),
                        (f"Exit P/FCF (±{_ta_delta_rel:.1f})",            _adv_fv_dcf(_ta_g, _ta_r, max(0.5, _ta_pfcf - _ta_delta_rel), _ta_n),
                                                 _adv_fv_dcf(_ta_g, _ta_r, _ta_pfcf + _ta_delta_rel, _ta_n)),
                        ("Years n (±1)",               _adv_fv_dcf(_ta_g, _ta_r, _ta_pfcf, max(1, _ta_n - 1)),
                                                 _adv_fv_dcf(_ta_g, _ta_r, _ta_pfcf, _ta_n + 1)),
                    ]:
                        if not (np.isnan(_lo_v) or np.isnan(_hi_v)):
                            _ta_dcf_impacts.append({"Parametr": _pname, "Nízká": _lo_v, "Vysoká": _hi_v,
                                                    "RozsahAbs": abs(_hi_v - _lo_v)})
                    if _ta_dcf_impacts:
                        _render_ta_chart(_ta_dcf_impacts, _ta_base_dcf, _dcf_lbl)
                        _any_ta_chart = True

                if not _any_ta_chart:
                    st.info("Základní FV není dostupné – zkontroluj vstupní data.")
            except Exception as _t_exc_adv:
                st.warning(f"Tornado nelze zobrazit: {_t_exc_adv}")

        with st.expander("📐 Equations – Advanced Valuation (click to expand)"):
            st.markdown(r"""
    **Scenario Outputs (per share)**

    $$
    \text{P/E Fair Value} = \frac{\text{Price}_n^{PE}}{(1+r)^n}
    \qquad
    \text{Price}_n^{PE} = \frac{\text{Revenue}_n \times \text{NOPAT margin} \times P/E}{\text{Shares}}
    $$

    $$
    \text{Equity DCF Fair Value} = \frac{PV_{\text{FCF}} + PV_{\text{terminal}}}{\text{Shares}}
    $$

    $$
    \text{CAGR}_{\text{price}} = \left(\frac{\text{Price}_n^{PE}}{\text{CurrentPrice}}\right)^{1/n} - 1
    $$

    $$
    \text{CAGR}_{\text{total}} = \left(\frac{\text{Price}_n^{PE} + \text{CumDiv}}{\text{CurrentPrice}}\right)^{1/n} - 1
    $$

    ---

    **Dividend projection:**

    $$
    DPS_0 = \text{DividendPerShare}_{\text{TTM}}
    \qquad
    DPS_t = DPS_0 \,(1 + dg)^t
    \qquad
    DPS_t^{\text{net}} = DPS_t \,(1 - \text{div\_tax})
    $$

    $$
    \text{CumDiv} = \sum_{t=1}^{n} DPS_t^{\text{net}}
    $$

    ---

    **Terminal value – Exit multiple (P/FCF):**

    $$
    PV_{\text{terminal}} = \frac{\text{FCF}_n \times P/\text{FCF}}{(1+r)^n}
    \qquad
    \text{FCF}_n = \text{Revenue}_0 \cdot (1+g)^n \cdot \text{FCF margin}
    $$

    ---

    **Terminal value – Perpetual growth (Gordon):**

    $$
    \text{FCF}_{n+1} = \text{FCF}_n \,(1 + g_{\text{terminal}})
    \qquad
    TV_n = \frac{\text{FCF}_{n+1}}{r - g_{\text{terminal}}}
    \qquad
    PV_{\text{terminal}} = \frac{TV_n}{(1+r)^n}
    $$

    *Valid only when $r > g_{\text{terminal}}$; otherwise Equity DCF Fair Value = N/A.*

    ---

    **Implied FCF margin** (from ROIC–Growth–Margin relationship):

    $$
    \text{NOPAT margin} = \text{OpMargin} \times (1 - \text{TaxRate})
    $$

    $$
    \text{ReinvestmentRate} = \frac{g}{\text{ROIC}}
    $$

    $$
    \text{FCF margin}_{\text{implied}} = \text{NOPAT margin} \times \left(1 - \frac{g}{\text{ROIC}}\right)
    $$

    ---

    **Revenue at horizon n:**

    $$
    \text{Revenue}_n = \text{Revenue}_0 \times (1 + g)^n
    $$

    ---

    **P/E-based fair value today** (detail):

    $$
    \text{NOPAT}_n = \text{Revenue}_n \times \text{NOPAT margin}
    \qquad
    \text{EquityValue}_n = \text{NOPAT}_n \times P/E
    $$

    $$
    \text{Price}_n^{PE} = \frac{\text{EquityValue}_n}{\text{Shares}}
    \qquad
    \text{FairValue}_{PE} = \frac{\text{Price}_n^{PE}}{(1+r)^n}
    $$

    ---

    **Equity DCF Fair Value today** (detail):

    $$
    PV_{\text{FCF}} = \sum_{t=1}^{n} \frac{\text{Revenue}_0 \cdot (1+g)^t \cdot \text{FCF margin}}{(1+r)^t}
    $$

    $$
    \text{Equity FairValue}_{DCF} = \frac{PV_{\text{FCF}} + PV_{\text{terminal}}}{\text{Shares}}
    $$

    ---

    *All rates are decimals inside calculations (e.g. r = 0.10 for 10 %, dg = 0.05 for 5 %).
    Revenue₀ = TTM Revenue [M] × 1 000 000.*
            """)


    # ── Tab 3: ROE model Dan Gladiš ────────────────────────────────
    with _val_tabs[2]:
        _t2_tip = _tooltip_attr(
            "Popis: Dividendový model – IV = PV zdatněných dividend + PV terminální ceny (EPS×Exit P/E).\n"
            "Vhodné typy firem: Dividendové firmy s predikovatelbným ROE – banky, pojišťovny, consumer staples, dividendoví aristokraté.\n"
            "NEVHODNÉ pro: Growth firmy bez dividend, firmy se záporným BPS nebo nestabilním ROE.\n"
            "Výhody: BPS-grounded, explicitní piecewise dividendové modelování (1-3 / 4-5 / 6-10 let), TTM correction factor.\n"
            "Na co si dát pozor: Nezohledňuje buybacks. Terminální hodnota silně závisí na Exit P/E. Nepřesné pro fi. s akvižičním růstem. Je třeba pohlídat payout ratio (DPS/EPS) – dividendový růst musí být konzistentní s EPS, jinak payout může přelézt 100 %."
        )
        st.markdown(
            f"<h3>ROE model Dan Gladiš "
            f"<span title='{_t2_tip}' style='cursor:help;color:#93a3b8;border-bottom:1px dotted #93a3b8;font-size:14px;'>ⓘ</span>"
            f"</h3>",
            unsafe_allow_html=True,
        )
        with st.expander("ℹ️ O tomto modelu", expanded=False):
            st.markdown("""
| | |
|---|---|
| **Popis** | Dividendový model – IV = PV zdatněných dividend (10 let) + PV terminální ceny (EPS₁₀ × Exit P/E). |
| **Vhodné typy firem** | Dividendové firmy s predikovatelbným ROE – banky, pojišťovny, consumer staples, dividendoví aristokraté. |
| **NEVHODNÉ pro** | Growth firmy bez dividend. Firmy se záporným nebo nepředvídatelným BPS. |
| **Výhody** | BPS-grounded (BPS_t = BPS + EPS − DPS). Explicitní piecewise projekce dividendy. TTM correction factor. |
| **Na co si dát pozor** | Nezohledňuje buybacks – u firem s vysokou repurchase aktivitou je podhodnocený. Terminální hodnota silně závisí na Exit P/E. Je třeba pohlídat payout ratio (DPS/EPS) – dividendový růst musí být konzistentní s EPS, jinak payout může přelézt 100 %. |
            """)
        st.caption(
            "Model dle Dana Gladiše: historický ROE + piecewise projekce BPS/EPS/DPS na 10 let. "
            "Intrinsic value = PV po-daňových dividend + PV terminální ceny."
        )

        _ROE_MANUAL_KEY = "roe_manual_df"
        _ROE_PARAMS_KEY = "roe_params"

        # ── Build base DataFrame from effective_df ───────────────────────
        _roe_src_map = {
            "BPS": "BPS $",
            "ROE": "ROE",
            "EPS": "EPS $",
            "DPS": "Dividend per share",
        }
        _roe_edit_cols = list(_roe_src_map.keys())

        roe_base_df = pd.DataFrame(
            {_dst: [_safe_float(effective_df.loc[r, _src]) if _src in effective_df.columns else np.nan
                    for r in effective_df.index]
             for _dst, _src in _roe_src_map.items()},
            index=effective_df.index,
        )
        roe_base_df.index.name = "Year"

        def _roe_add_payout(df):
            df = df.copy()
            eps_s = pd.to_numeric(df["EPS"], errors="coerce")
            dps_s = pd.to_numeric(df["DPS"], errors="coerce")
            df["Payout"] = np.where((eps_s > 0) & eps_s.notna() & dps_s.notna(), dps_s / eps_s, np.nan)
            return df

        # First merge (display only – overrides may not exist yet)
        _roe_man0 = st.session_state.get(_ROE_MANUAL_KEY, pd.DataFrame())
        roe_effective_df, _roe_ov_mask = merge_api_and_manual(roe_base_df, _roe_man0)
        roe_effective_df = _roe_add_payout(roe_effective_df)

        # ── Data editor ──────────────────────────────────────────────────
        st.markdown("**Historická data ROE modelu (editovatelná):**")
        _roe_editor_base = _roe_add_payout(roe_base_df).reset_index()
        # Convert percentage columns to % display (Payout is still decimal, ROE already in %)
        _roe_editor_base["Payout"] = _roe_editor_base["Payout"] * 100
        _roe_editor_h = (len(_roe_editor_base) + 1) * 35 + 4

        _roe_edited_raw = st.data_editor(
            _roe_editor_base,
            width="stretch",
            num_rows="fixed",
            hide_index=True,
            height=_roe_editor_h,
            column_config={
                "Year":   st.column_config.TextColumn("Year",      disabled=True),
                "BPS":    st.column_config.NumberColumn("BPS $",    format="%.2f"),
                "ROE":    st.column_config.NumberColumn("ROE (%)",  format="%.2f"),
                "EPS":    st.column_config.NumberColumn("EPS $",    format="%.2f"),
                "DPS":    st.column_config.NumberColumn("DPS $",    format="%.4f"),
                "Payout": st.column_config.NumberColumn("Payout (%)", format="%.1f", disabled=True),
            },
            key="roe_data_editor",
        )

        # Persist manual overrides (cells that differ from roe_base_df)
        _roe_edited_df   = _roe_edited_raw.set_index("Year")
        _roe_new_manual  = pd.DataFrame(np.nan, index=roe_base_df.index, columns=_roe_edit_cols)
        for _col in _roe_edit_cols:
            if _col not in _roe_edited_df.columns:
                continue
            for _yr in roe_base_df.index:
                if _yr not in _roe_edited_df.index:
                    continue
                _ev = _safe_float(_roe_edited_df.loc[_yr, _col])
                _av = _safe_float(roe_base_df.loc[_yr, _col])
                if not (np.isnan(_ev) and np.isnan(_av)) and _ev != _av:
                    _roe_new_manual.loc[_yr, _col] = _ev

        st.session_state[_ROE_MANUAL_KEY] = _roe_new_manual
        roe_effective_df, _roe_ov_mask = merge_api_and_manual(roe_base_df, _roe_new_manual)
        roe_effective_df = _roe_add_payout(roe_effective_df)

        _roe_n_ov = int(_roe_ov_mask.sum().sum())
        _roe_expander_label = (
            f"📋 Effective view – {_roe_n_ov} přepsaná {'buňka' if _roe_n_ov == 1 else 'buňky'} (zvýrazněno)"
            if _roe_n_ov > 0 else "📋 Effective view (žádné přepsané buňky)"
        )
        with st.expander(_roe_expander_label, expanded=_roe_n_ov > 0):
            _roe_disp = _roe_add_payout(roe_effective_df).copy()
            _roe_disp["Payout"] = _roe_disp["Payout"] * 100
            st.dataframe(
                _roe_disp,
                width="stretch",
                column_config={
                    "ROE":    st.column_config.NumberColumn("ROE (%)",    format="%.2f"),
                    "Payout": st.column_config.NumberColumn("Payout (%)", format="%.1f"),
                },
            )

        st.divider()

        # ══════════════════════════════════════════════════════════════════
        # SCENARIO PARAMETERS
        # ══════════════════════════════════════════════════════════════════
        st.markdown("**Parametry scénářů (10letá projekce):**")

        _ROE_SC_LABELS = ["Worst", "Nominal", "Best"]
        _ROE_SC_COLORS = {"Nominal": "#FFD54F", "Worst": "#FF7043", "Best": "#66BB6A"}
        _ROE_PARAM_HELP = {
            "roe": (
                "Jak se používá: Určuje modelové EPS přes vztah EPS_t(model) = BPS_t × ROE_t, "
                "kde BPS_t = BPS_{t-1} + EPS_{t-1} − DPS_{t-1}.\n"
                "Co vyjadřuje: Výnosnost vlastního kapitálu v jednotlivých obdobích.\n"
                "Kdy použít: Klíčový vstup pro kvalitu businessu; nastav konzervativně pro delší horizont."
            ),
            "dg": (
                "Jak se používá: DPS_t = DPS_{t-1} × (1 + dg_t), následně se počítá PV zdaněných dividend.\n"
                "Co vyjadřuje: Tempo růstu dividendy v čase.\n"
                "Kdy použít: Důležité u dividendových firem; u volatilních výplat raději nižší hodnoty."
            ),
            "pe": (
                "Jak se používá: Terminální cena v roce 10 = EPS_10 × Exit P/E, pak se diskontuje na současnou hodnotu.\n"
                "Co vyjadřuje: Očekávané tržní ocenění na konci projekce.\n"
                "Kdy použít: Citlivý parametr; drž se historického pásma a kvality firmy."
            ),
            "tax": (
                "Jak se používá: Každá dividenda je upravena na DPS_t × (1 − daň), až pak se diskontuje.\n"
                "Co vyjadřuje: Efektivní zdanění dividend investora.\n"
                "Kdy použít: Nastav dle tvé jurisdikce a daňového režimu brokera."
            ),
            "r": (
                "Jak se používá: Diskontní sazba pro PV dividend i PV terminální hodnoty.\n"
                "Co vyjadřuje: Požadovaný roční výnos / alternativní náklad kapitálu.\n"
                "Kdy použít: Pro konzervativnější valuaci použij vyšší r."
            ),
            "ttm_cf": (
                "Jak se používá: Pouze v roce 1 míchá TTM EPS a modelové EPS z BPS×ROE: "
                "EPS_1 = EPS_0×(1−cf) + (BPS_1×ROE_1)×cf.\n"
                "Automatický default z yfinance (podle posledního zveřejněného kvartálu v TTM): Q1→0.75, Q2→0.50, Q3→0.25, Q4→1.00.\n"
                "Co vyjadřuje: Jak velkou část roku 1 přebírá model (vyšší cf) vs. TTM EPS (nižší cf)."
            ),
        }

        _ttm_q_info = fetch_ttm_quarter_info(st.session_state.val_ticker)
        _auto_ttm_cf = float(np.clip(_safe_float(_ttm_q_info.get("ttm_cf", 0.5)), 0.0, 1.0))
        _auto_ttm_q_lbl = str(_ttm_q_info.get("quarter_label", "N/A"))

        def _rttm(col):
            try:
                if "TTM" in roe_effective_df.index:
                    v = _safe_float(roe_effective_df.loc["TTM", col])
                    return v if not np.isnan(v) else np.nan
            except Exception:
                pass
            return np.nan

        # ── Historical data for smart defaults ────────────────────────────
        _roe_annual_sorted = roe_effective_df.drop(index=["TTM"], errors="ignore").sort_index()

        # Annual ROE values (%)
        _hist_roe_s = pd.to_numeric(_roe_annual_sorted["ROE"], errors="coerce").dropna()

        # Annual DPS year-over-year growth rates (%)
        _hist_dps_s = pd.to_numeric(_roe_annual_sorted["DPS"], errors="coerce").dropna()
        _hist_dps_s = _hist_dps_s[_hist_dps_s > 0]
        _hist_dg_rates: list[float] = []
        if len(_hist_dps_s) >= 2:
            for _i_dg in range(1, len(_hist_dps_s)):
                _prev_dps = _hist_dps_s.iloc[_i_dg - 1]
                _curr_dps = _hist_dps_s.iloc[_i_dg]
                if _prev_dps > 0:
                    _hist_dg_rates.append((_curr_dps / _prev_dps - 1.0) * 100.0)

        # Annual P/E values
        _pe_annual_sorted = effective_df.drop(index=["TTM"], errors="ignore").sort_index()
        _hist_pe_s = pd.to_numeric(_pe_annual_sorted["P/E"], errors="coerce").dropna() if "P/E" in _pe_annual_sorted.columns else pd.Series(dtype=float)

        def _last_n_s(series, n):
            """Last n values from a sorted-ascending Series."""
            return series.iloc[-n:] if len(series) >= n else series

        def _last_n_l(lst, n):
            """Last n values from a list."""
            return lst[-n:] if len(lst) >= n else lst

        # ── ROE defaults (%) ──
        _roe_3y = _last_n_s(_hist_roe_s, 3)
        _roe_5y = _last_n_s(_hist_roe_s, 5)
        _roe_nom  = float(_roe_3y.mean()) if len(_roe_3y) > 0 else 15.0
        _roe_worst = float(_roe_5y.min()) if len(_roe_5y) > 0 else round(_roe_nom * 0.7, 2)
        _roe_best  = float(_roe_3y.max()) if len(_roe_3y) > 0 else round(min(_roe_nom * 1.15, 200.0), 2)

        # ── Dividend growth defaults (%) ──
        _dg_3y = _last_n_l(_hist_dg_rates, 3)
        _dg_5y = _last_n_l(_hist_dg_rates, 5)
        _dg_nom  = float(np.mean(_dg_3y))  if _dg_3y else 5.0
        _dg_worst = float(min(_dg_5y))     if _dg_5y else max(0.0, _dg_nom * 0.5)
        _dg_best  = float(max(_dg_3y))     if _dg_3y else min(_dg_nom * 1.3, 100.0)

        # ── P/E defaults ──
        _pe_10y = _last_n_s(_hist_pe_s, 10)
        _pe_3y  = _last_n_s(_hist_pe_s, 3)
        _pe_nom  = float(_pe_10y.mean()) if len(_pe_10y) > 0 else 15.0
        _pe_worst = float(_pe_10y.min()) if len(_pe_10y) > 0 else 12.0
        _pe_best  = float(_pe_3y.mean()) if len(_pe_3y)  > 0 else 20.0

        # Backward-compat fallbacks
        _r0_raw = _rttm("ROE")
        _r0     = _r0_raw if not np.isnan(_r0_raw) else 15.0
        _hist_dg_def = _dg_nom / 100.0 if _dg_nom != 0 else 0.05

        def _rdft(sn, key):
            """Default value for a scenario/key based on historical data."""
            sc_def = {
                "Nominal": dict(
                    roe_1_3=round(_roe_nom, 2), roe_4_5=round(_roe_nom, 2), roe_6_10=round(_roe_nom, 2),
                    dg_1_3=round(_dg_nom, 2), dg_4_5=round(_dg_nom, 2), dg_6_10=round(_dg_nom, 2),
                    pe=round(_pe_nom, 1), tax=15.0, r=12.0, ttm_cf=_auto_ttm_cf,
                ),
                "Worst": dict(
                    roe_1_3=round(_roe_worst, 2), roe_4_5=round(_roe_worst, 2), roe_6_10=round(_roe_worst, 2),
                    dg_1_3=round(_dg_worst, 2), dg_4_5=round(_dg_worst, 2), dg_6_10=round(_dg_worst, 2),
                    pe=round(_pe_worst, 1), tax=15.0, r=12.0, ttm_cf=_auto_ttm_cf,
                ),
                "Best": dict(
                    roe_1_3=round(_roe_best, 2), roe_4_5=round(_roe_best, 2), roe_6_10=round(_roe_best, 2),
                    dg_1_3=round(_dg_best, 2), dg_4_5=round(_dg_best, 2), dg_6_10=round(_dg_best, 2),
                    pe=round(_pe_best, 1), tax=15.0, r=12.0, ttm_cf=_auto_ttm_cf,
                ),
            }
            return float(sc_def[sn].get(key, 0.0))

        # One-time migration: if stored params use old decimal format (tax < 1.0), reset to % format
        _stored_roe_p = st.session_state.get(_ROE_PARAMS_KEY, {})
        if _stored_roe_p and float(_stored_roe_p.get("Nominal", {}).get("tax", 1.0)) < 1.0:
            st.session_state[_ROE_PARAMS_KEY] = {}

        # Init scenario params only once (or if cleared on ticker change)
        if not st.session_state.get(_ROE_PARAMS_KEY):
            st.session_state[_ROE_PARAMS_KEY] = {
                sn: {k: _rdft(sn, k) for k in ["roe_1_3", "roe_4_5", "roe_6_10",
                                                 "dg_1_3", "dg_4_5", "dg_6_10",
                                                 "pe", "tax", "r", "ttm_cf"]}
                for sn in _ROE_SC_LABELS
            }
        _roe_p = st.session_state[_ROE_PARAMS_KEY]

        # ── Column proportions: [param_label, period_label, Nominal, Worst, Best] ──
        _C = [2.2, 1.4, 2, 2, 2]

        # Header row – scenario names only
        _h0, _h1, _h_nom, _h_wor, _h_bes = st.columns(_C)
        for _hcw, _hsn in zip([_h_nom, _h_wor, _h_bes], _ROE_SC_LABELS):
            with _hcw:
                st.markdown(
                    f"<div style='font-weight:700;color:{_ROE_SC_COLORS[_hsn]};text-align:center'>{_hsn}</div>",
                    unsafe_allow_html=True,
                )

        def _roe_3period_group(param_label, key_1_3, key_4_5, key_6_10, mn, mx, stp, fmt="%.1f", help_key=None):
            """
            3 sub-rows; param label on middle row.
            Rows 4-5Y and 6-10Y have an override checkbox – when unchecked they
            mirror the 1-3Y value (shown as a greyed-out read-only block).
            """
            result = {key_1_3: {}, key_4_5: {}, key_6_10: {}}
            _period_keys   = [key_1_3,   key_4_5,   key_6_10]
            _period_labels = ["1-3 roky", "4-5 let",  "6-10 let"]

            for _pi, (_pk, _pl) in enumerate(zip(_period_keys, _period_labels)):
                _lbl_c, _per_c, _c_nom, _c_wor, _c_bes = st.columns(_C)

                with _lbl_c:
                    if _pi == 1:  # centred label on middle row
                        _title = _tooltip_attr(_ROE_PARAM_HELP.get(help_key, "")) if help_key else ""
                        _label_html = (
                            f"{param_label} <span title='{_title}' "
                            "style='cursor:help;color:#93a3b8;font-weight:700'>ⓘ</span>"
                            if _title else param_label
                        )
                        st.markdown(
                            f"<div style='font-size:14px;font-weight:700;padding-top:6px'>{_label_html}</div>",
                            unsafe_allow_html=True,
                        )

                with _per_c:
                    st.markdown(
                        f"<div style='font-size:14px;font-weight:600;color:#e8eef7;margin-bottom:0'>{_pl}</div>",
                        unsafe_allow_html=True,
                    )
                    if _pi > 0:
                        _ovr_key = f"ovr_{_pk}"  # e.g. "ovr_roe_4_5" / "ovr_dg_4_5"
                        _ovr = st.checkbox("přepsat", key=_ovr_key)
                    else:
                        _ovr = True  # 1-3Y is always editable

                for _cw, _sn in zip([_c_nom, _c_wor, _c_bes], _ROE_SC_LABELS):
                    _wk = f"roe_{_sn}_{_pk}"
                    with _cw:
                        if _ovr:
                            if _pi == 0:
                                _iv = float(_roe_p.get(_sn, {}).get(_pk, _rdft(_sn, _pk)))
                            else:
                                _iv = float(_roe_p.get(_sn, {}).get(_pk, result[key_1_3].get(_sn, _rdft(_sn, key_1_3))))
                            result[_pk][_sn] = st.number_input(
                                param_label, value=_iv,
                                min_value=float(mn), max_value=float(mx),
                                step=float(stp), format=fmt,
                                key=_wk, label_visibility="collapsed",
                            )
                        else:
                            # Mirror 1-3Y – show read-only styled block, no widget key
                            _mirror = result[key_1_3].get(_sn, _rdft(_sn, key_1_3))
                            result[_pk][_sn] = _mirror
                            st.markdown(
                                f"<div style='background:#1a1d27;border:1px solid #2a2d3e;"
                                f"border-radius:6px;padding:7px 12px;color:#4a5568;"
                                f"font-size:14px;margin-top:4px'>{fmt % _mirror}</div>",
                                unsafe_allow_html=True,
                            )
            return result

        _SEP = "<hr style='border:none;border-top:1px solid #2a2d3e;margin:6px 0 4px 0'/>"

        _rrv_roe = _roe_3period_group("ROE (%)",                  "roe_1_3", "roe_4_5", "roe_6_10", -100.0, 500.0, 0.1, help_key="roe")
        st.markdown(_SEP, unsafe_allow_html=True)
        _rrv_dg  = _roe_3period_group("Dividend growth rate (%)", "dg_1_3",  "dg_4_5",  "dg_6_10",  -100.0, 500.0, 0.1, help_key="dg")
        st.markdown(_SEP, unsafe_allow_html=True)

        # Future P/E – single row, one input per scenario
        _fp_lbl, _fp_per, _fp_nom, _fp_wor, _fp_bes = st.columns(_C)
        with _fp_lbl:
            _pe_title = _tooltip_attr(_ROE_PARAM_HELP.get("pe", ""))
            st.markdown(
                f"<div style='font-size:14px;font-weight:700;padding-top:6px'>Future P/E <span title='{_pe_title}' style='cursor:help;color:#93a3b8;font-weight:700'>ⓘ</span></div>",
                unsafe_allow_html=True,
            )
        _rrv_pe_vals = {}
        for _cw, _sn in zip([_fp_nom, _fp_wor, _fp_bes], _ROE_SC_LABELS):
            _wk_pe = f"roe_{_sn}_pe"
            _iv_pe = float(_roe_p.get(_sn, {}).get("pe", _rdft(_sn, "pe")))
            with _cw:
                _rrv_pe_vals[_sn] = st.number_input(
                    "Future P/E", value=_iv_pe,
                    min_value=1.0, max_value=300.0,
                    step=0.5, format="%.1f",
                    key=_wk_pe, label_visibility="collapsed",
                )

        def _roe_single_row(label, pkey, mn, mx, stp, fmt="%.1f", help_key=None):
            """Single-value per scenario – same 5-column grid as the group rows."""
            _rl2, _per2, _rn3, _rw3, _rb3 = st.columns(_C)
            with _rl2:
                _title = _tooltip_attr(_ROE_PARAM_HELP.get(help_key, "")) if help_key else ""
                _label_html = (
                    f"{label} <span title='{_title}' style='cursor:help;color:#93a3b8;font-weight:700'>ⓘ</span>"
                    if _title else label
                )
                st.markdown(f"<div style='padding-top:6px;font-size:13px;font-weight:700'>{_label_html}</div>", unsafe_allow_html=True)
            out = {}
            for _cw3, _sn3 in zip([_rn3, _rw3, _rb3], _ROE_SC_LABELS):
                _wk3 = f"roe_{_sn3}_{pkey}"
                _iv3 = float(_roe_p.get(_sn3, {}).get(pkey, _rdft(_sn3, pkey)))
                with _cw3:
                    out[_sn3] = st.number_input(
                        label, value=_iv3,
                        min_value=float(mn), max_value=float(mx),
                        step=float(stp), format=fmt,
                        key=_wk3, label_visibility="collapsed",
                    )
            return out

        st.markdown(_SEP, unsafe_allow_html=True)
        _rrv_tax    = _roe_single_row("Dividend tax (%)",     "tax",    0.0, 100.0, 0.5,  "%.1f", help_key="tax")
        _rrv_r      = _roe_single_row("Discount rate r (%)",  "r",      0.0, 100.0, 0.5,  "%.1f", help_key="r")
        _rrv_ttm_cf = _roe_single_row("TTM correction factor","ttm_cf", 0.0, 1.0,  0.05, "%.2f", help_key="ttm_cf")
        st.markdown(
            (
                "<div style='margin:6px 0 2px 0;padding:8px 12px;background:#0f1420;"
                "border:1px solid #2a2d3e;border-radius:8px;font-size:13px;color:#cdd6e3'>"
                "Poslední zveřejněné výsledky zahrnuté v TTM: "
                f"<span style='font-weight:700'>{_auto_ttm_q_lbl}</span> "
                "-&gt; TTM correction factor = "
                f"<span style='font-weight:700'>{_auto_ttm_cf:.2f}</span>"
                "</div>"
            ),
            unsafe_allow_html=True,
        )

        for _sn in _ROE_SC_LABELS:
            _roe_p[_sn]["roe_1_3"]  = _rrv_roe["roe_1_3"][_sn]
            _roe_p[_sn]["roe_4_5"]  = _rrv_roe["roe_4_5"][_sn]
            _roe_p[_sn]["roe_6_10"] = _rrv_roe["roe_6_10"][_sn]
            _roe_p[_sn]["dg_1_3"]   = _rrv_dg["dg_1_3"][_sn]
            _roe_p[_sn]["dg_4_5"]   = _rrv_dg["dg_4_5"][_sn]
            _roe_p[_sn]["dg_6_10"]  = _rrv_dg["dg_6_10"][_sn]
            _roe_p[_sn]["pe"]       = _rrv_pe_vals[_sn]
            _roe_p[_sn]["tax"]      = _rrv_tax[_sn]
            _roe_p[_sn]["r"]        = _rrv_r[_sn]
            _roe_p[_sn]["ttm_cf"]   = _rrv_ttm_cf[_sn]
        st.session_state[_ROE_PARAMS_KEY] = _roe_p

        # ══════════════════════════════════════════════════════════════════
        # PROJECTION COMPUTATION
        # ══════════════════════════════════════════════════════════════════

        def _compute_roe_proj(bps0, eps0, dps0, params):
            """10-year piecewise ROE projection; returns (rows, iv, pv_div, pv_term, payout_warn, future_price, cum_div).
            Expects roe_*, dg_*, tax, r stored in % (e.g. 15.0 for 15%).
            Algorithm: EPS_t = BPS_{t-1} * ROE_t  →  DPS_t = DPS_{t-1}*(1+dg_t)
                       BPS_t = BPS_{t-1} + EPS_t - DPS_t  (correct order)."""
            rows = []
            bps_p, eps_p, dps_p = bps0, eps0, dps0
            pv_div   = 0.0
            cum_div  = 0.0  # undiscounted after-tax dividends (for CAGR)
            r_d   = params["r"]   / 100.0
            tax_d = params["tax"] / 100.0
            cf    = float(np.clip(_safe_float(params.get("ttm_cf", 0.5)), 0.0, 1.0))
            payout_warn = False
            for t in range(1, 11):
                if   t <= 3: roe_t = params["roe_1_3"]  / 100.0; gt = params["dg_1_3"]  / 100.0
                elif t <= 5: roe_t = params["roe_4_5"]  / 100.0; gt = params["dg_4_5"]  / 100.0
                else:        roe_t = params["roe_6_10"] / 100.0; gt = params["dg_6_10"] / 100.0

                # Correct order: EPS first (uses previous BPS), then DPS, then update BPS
                eps_model_t = bps_p * roe_t
                eps_t = (eps_p * (1.0 - cf) + eps_model_t * cf) if t == 1 else eps_model_t
                dps_t = dps_p * (1.0 + gt)
                bps_t = bps_p + eps_t - dps_t
                pout  = (dps_t / eps_t) if eps_t > 0 else np.nan
                if not np.isnan(pout) and pout > 1.0:
                    payout_warn = True
                after_tax_dps = dps_t * (1.0 - tax_d)
                pv_div  += after_tax_dps / (1.0 + r_d) ** t
                cum_div += after_tax_dps  # undiscounted sum
                rows.append({"t": t, "ROE": roe_t, "EPS": eps_t, "DPS": dps_t, "BPS": bps_t, "Payout": pout})
                bps_p, eps_p, dps_p = bps_t, eps_t, dps_t

            future_price = rows[-1]["EPS"] * params["pe"]
            pv_term      = future_price / (1.0 + r_d) ** 10
            iv           = pv_div + pv_term
            return rows, iv, pv_div, pv_term, payout_warn, future_price, cum_div

        _bps0_v = _rttm("BPS"); _bps0_v = _bps0_v if not np.isnan(_bps0_v) else 0.0
        _eps0_v = _rttm("EPS"); _eps0_v = _eps0_v if not np.isnan(_eps0_v) else 0.0
        _dps0_v = _rttm("DPS"); _dps0_v = _dps0_v if not np.isnan(_dps0_v) else 0.0
        _roe0_v = _r0

        _cur_price_roe = np.nan
        try:
            if "TTM" in effective_df.index and "Stock Price" in effective_df.columns:
                _cur_price_roe = _safe_float(effective_df.loc["TTM", "Stock Price"])
        except Exception:
            pass

        _roe_proj = {}
        for _sn in _ROE_SC_LABELS:
            try:
                _rows, _iv, _pvd, _pvt, _payout_warn, _fpr, _cdiv = _compute_roe_proj(_bps0_v, _eps0_v, _dps0_v, _roe_p[_sn])
                _mos_v = (_iv / _cur_price_roe - 1.0) if (not np.isnan(_cur_price_roe) and _cur_price_roe > 0) else np.nan
                _cagr_roe_v = (
                    ((_fpr + _cdiv) / _cur_price_roe) ** (1.0 / 10.0) - 1.0
                    if (not np.isnan(_fpr) and (_fpr + _cdiv) > 0 and not np.isnan(_cur_price_roe) and _cur_price_roe > 0)
                    else np.nan
                )
                _roe_proj[_sn] = {
                    "rows": _rows, "iv": _iv, "pv_div": _pvd, "pv_term": _pvt,
                    "mos": _mos_v, "cagr": _cagr_roe_v, "payout_warn": _payout_warn,
                    "future_price": _fpr, "future_price_div": _fpr + _cdiv,
                }
            except Exception as _exc_roe:
                _roe_proj[_sn] = {
                    "rows": [], "iv": np.nan, "pv_div": np.nan, "pv_term": np.nan,
                    "mos": np.nan, "cagr": np.nan, "payout_warn": False,
                    "future_price": np.nan, "future_price_div": np.nan, "error": str(_exc_roe),
                }

        # ══════════════════════════════════════════════════════════════════
        # OUTPUTS
        # ══════════════════════════════════════════════════════════════════
        st.divider()
        # Payout ratio warnings
        for _sn_pw in _ROE_SC_LABELS:
            if _roe_proj.get(_sn_pw, {}).get("payout_warn"):
                st.warning(
                    f"⚠️ Scénář **{_sn_pw}**: V některém roce je výplatní poměr DPS/EPS > 100 %. "
                    "Firma by vyplácela více, než vydělává – model může být nespolehlivý. "
                    "Zkontroluj DPS₀, DPS growth a EPS₀."
                )
        _ROE_OUT_HELP = {
            "Total present value (terminal + dividends) ($)": (
                "Jak se počítá: Total present value = PV zdaněných dividend + PV terminální hodnoty.\n"
                "Co vyjadřuje: Odhad vnitřní hodnoty akcie na akcii.\n"
                "Kdy použít: Hlavní výstup pro porovnání s aktuální cenou."
            ),
            "PV zdaněných dividend ($)": (
                "Jak se počítá: Σ [ DPS_t × (1−daň) / (1+r)^t ] pro t=1..10.\n"
                "Co vyjadřuje: Současná hodnota očekávaných dividend po zdanění.\n"
                "Kdy použít: Důležité hlavně u dividendových titulů."
            ),
            "PV terminální ($)": (
                "Jak se počítá: (EPS_10 × Exit P/E) / (1+r)^10.\n"
                "Co vyjadřuje: Současná hodnota prodejní ceny na konci horizontu.\n"
                "Kdy použít: U většiny titulů tvoří významnou část valuace, kontroluj citlivost na Exit P/E."
            ),
            "MOS (%)": (
                "Jak se počítá: MOS = Intrinsic Value / Current Price − 1.\n"
                "Co vyjadřuje: Bezpečnostní polštář vůči aktuální tržní ceně.\n"
                "Kdy použít: Pro rychlé rozhodnutí, zda je cena pod nebo nad odhadovanou hodnotou."
            ),
        }
        with st.container(border=True):
            def _roe_td(key, val):
                if val != val:  # isnan
                    return "<td style='text-align:right;font-weight:700;color:#93a3b8'>N/A</td>"
                if key in ("mos", "cagr"):
                    _c = "#66BB6A" if val >= 0 else "#FF7043"
                    return f"<td style='text-align:right;font-weight:700;color:{_c}'>{val:.1%}</td>"
                if key in ("pv_div", "pv_term"):
                    return f"<td style='text-align:right;font-weight:400'>${val:,.2f}</td>"
                if key == "iv":
                    _c = _fv_clr(val, _cur_price_roe)
                    return f"<td style='text-align:right;font-weight:700;color:{_c}'>${val:,.2f}</td>"
                if key == "future_price_div":
                    _c = _fv_clr(val, _cur_price_roe)
                    return f"<td style='text-align:right;font-weight:600;color:{_c}'>${val:,.2f}</td>"
                return f"<td style='text-align:right;font-weight:600'>${val:,.2f}</td>"

            _roe_row_defs = [
                ("Future Price (EPS₁₀ × P/E)",          "future_price"),
                ("Future Price + Dividends",            "future_price_div"),
                ("Fair Value (PV)",                     "pv_term"),
                ("Fair Value + Dividends (PV)",         "iv"),
                ("CAGR (10 let)",                       "cagr"),
                ("Upside/Downside (%)",                 "mos"),
            ]
            _roe_card_cols = st.columns(3)
            for _cw, _sn in zip(_roe_card_cols, _ROE_SC_LABELS):
                with _cw:
                    _cc = _ROE_SC_COLORS[_sn]
                    _d  = _roe_proj.get(_sn, {})
                    if _d.get("error"):
                        st.markdown(
                            f"<div style='background:rgba(255,255,255,0.05);border-radius:10px;"
                            f"padding:14px 16px;border-left:4px solid {_cc}'>"
                            f"<div style='font-weight:700;color:{_cc};font-size:15px;margin-bottom:8px'>{_sn}</div>"
                            f"<div style='color:#FF7043;font-size:13px'>⚠️ Chyba: "
                            f"{html.escape(str(_d['error']))}</div></div>",
                            unsafe_allow_html=True,
                        )
                        continue
                    _rows = "".join(
                        f"<tr><td style='color:#93a3b8;padding:2px 0;font-size:13px'>{_lbl}</td>"
                        f"{_roe_td(_key, _d.get(_key, float('nan')))}</tr>"
                        for _lbl, _key in _roe_row_defs
                    )
                    if not np.isnan(_cur_price_roe):
                        _rows += (
                            "<tr style='border-top:1px solid rgba(255,255,255,0.1)'>"
                            f"<td style='color:#93a3b8;padding:4px 0 2px;font-size:13px'>Aktuální cena</td>"
                            f"<td style='text-align:right;font-weight:400'>${_cur_price_roe:,.2f}</td></tr>"
                        )
                    st.markdown(
                        f"<div style='background:rgba(255,255,255,0.05);border-radius:10px;"
                        f"padding:14px 16px;border-left:4px solid {_cc}'>"
                        f"<div style='font-weight:700;color:{_cc};font-size:15px;margin-bottom:8px'>{_sn}</div>"
                        f"<table style='width:100%;font-size:13px;border-collapse:collapse'>"
                        f"{_rows}</table></div>",
                        unsafe_allow_html=True,
                    )

        # ══════════════════════════════════════════════════════════════════
        # CHARTS
        # ══════════════════════════════════════════════════════════════════
        st.divider()

        def _yr_sort_key_roe(y):
            try: return (0, int(str(y)))
            except: return (1, str(y))

        def _roe_chart_decimal(v):
            v = _safe_float(v)
            if np.isnan(v):
                return np.nan
            return v / 100.0 if abs(v) > 1.5 else v

        _hist_yrs_sorted = sorted(roe_effective_df.index.tolist(), key=_yr_sort_key_roe)
        _hist_years_num_roe = []
        for yr in _hist_yrs_sorted:
            yr_s = str(yr)
            if yr_s == "TTM":
                continue
            try:
                _hist_years_num_roe.append(int(yr_s))
            except Exception:
                continue
        _forecast_base_year_roe = max(_hist_years_num_roe) if _hist_years_num_roe else (pd.Timestamp.today().year - 1)

        _chart_hist_rows = [
            {"Year": str(yr), "Scenario": "Historická",
             "EPS": _safe_float(roe_effective_df.loc[yr, "EPS"]),
             "ROE": _roe_chart_decimal(roe_effective_df.loc[yr, "ROE"])}
            for yr in _hist_yrs_sorted
            if str(yr) != "TTM"  # TTM used as forecast bridge, not in historical series
            and not (np.isnan(_safe_float(roe_effective_df.loc[yr, "EPS"])) and
                    np.isnan(_safe_float(roe_effective_df.loc[yr, "ROE"])))
        ]

        _chart_fore_rows = []
        for _sn in _ROE_SC_LABELS:
            _pd2 = _roe_proj.get(_sn, {})
            if not _pd2.get("rows"):
                continue
            _chart_fore_rows.append({"Year": str(_forecast_base_year_roe), "Scenario": _sn,
                                      "EPS": next((r["EPS"] for r in _chart_hist_rows if r["Year"] == str(_forecast_base_year_roe)), _eps0_v),
                                      "ROE": next((r["ROE"] for r in _chart_hist_rows if r["Year"] == str(_forecast_base_year_roe)), _roe_chart_decimal(_roe0_v))})
            for _rw in _pd2["rows"]:
                _chart_fore_rows.append({"Year": str(_forecast_base_year_roe + int(_rw["t"])), "Scenario": _sn,
                                          "EPS": _rw["EPS"], "ROE": _rw["ROE"]})

        _hist_yr_strs = [str(y) for y in _hist_yrs_sorted]
        _fore_yr_strs = [str(_forecast_base_year_roe)] + [str(_forecast_base_year_roe + t) for t in range(1, 11)]
        _full_yr_order = [y for y in _hist_yr_strs if y != "TTM"] + _fore_yr_strs

        _hist_cdf = pd.DataFrame(_chart_hist_rows)
        _fore_cdf = pd.DataFrame(_chart_fore_rows) if _chart_fore_rows else pd.DataFrame()

        # Only keep years that actually have data points (avoids empty columns for missing history)
        _years_with_data = set()
        for _row in _chart_hist_rows + _chart_fore_rows:
            _years_with_data.add(_row["Year"])
        _all_yr_order = list(dict.fromkeys(y for y in _full_yr_order if y in _years_with_data))

        _sc_domain = ["Historická"] + _ROE_SC_LABELS
        _sc_range2 = ["#4f8ef7", "#FF7043", "#FFD54F", "#66BB6A"]
        _sc_cscale = alt.Scale(domain=_sc_domain, range=_sc_range2)

        if not _hist_cdf.empty:
            _x_enc_roe = alt.X("Year:N", sort=_all_yr_order, scale=alt.Scale(domain=_all_yr_order), title="Rok")

            # ── EPS chart ──────────────────────────────────────────────────
            _eps_h = alt.Chart(_hist_cdf).mark_line(strokeWidth=2, point=True).encode(
                x=_x_enc_roe,
                y=alt.Y("EPS:Q", title="EPS ($)"),
                color=alt.Color("Scenario:N", scale=_sc_cscale, title="Scénář"),
                tooltip=["Year", "Scenario", alt.Tooltip("EPS:Q", format=".2f", title="EPS $")],
            )
            _eps_layers_roe = [_eps_h]
            if not _fore_cdf.empty:
                _eps_layers_roe.append(
                    alt.Chart(_fore_cdf).mark_line(strokeWidth=2, strokeDash=[4, 2], point=True).encode(
                        x=_x_enc_roe,
                        y=alt.Y("EPS:Q"),
                        color=alt.Color("Scenario:N", scale=_sc_cscale),
                        tooltip=["Year", "Scenario", alt.Tooltip("EPS:Q", format=".2f", title="EPS $")],
                    )
                )
            _eps_chart_roe = (
                alt.layer(*_eps_layers_roe)
                .properties(title="EPS ($) — Historický vývoj + Projekce", height=300)
                .configure_view(strokeOpacity=0)
            )

            # ── ROE chart ──────────────────────────────────────────────────
            _roe_h = alt.Chart(_hist_cdf).mark_line(strokeWidth=2, point=True).encode(
                x=_x_enc_roe,
                y=alt.Y("ROE:Q", title="ROE", axis=alt.Axis(format=".0%")),
                color=alt.Color("Scenario:N", scale=_sc_cscale, title="Scénář"),
                tooltip=["Year", "Scenario", alt.Tooltip("ROE:Q", format=".2%", title="ROE")],
            )
            _roe_layers_roe = [_roe_h]
            if not _fore_cdf.empty:
                _roe_layers_roe.append(
                    alt.Chart(_fore_cdf).mark_line(strokeWidth=2, strokeDash=[4, 2], point=True).encode(
                        x=_x_enc_roe,
                        y=alt.Y("ROE:Q", axis=alt.Axis(format=".0%")),
                        color=alt.Color("Scenario:N", scale=_sc_cscale),
                        tooltip=["Year", "Scenario", alt.Tooltip("ROE:Q", format=".2%", title="ROE")],
                    )
                )
            _roe_chart_roe = (
                alt.layer(*_roe_layers_roe)
                .properties(title="ROE — Historický vývoj + Projekce", height=300)
                .configure_view(strokeOpacity=0)
            )

            st.altair_chart(_eps_chart_roe, width="stretch")
            st.altair_chart(_roe_chart_roe, width="stretch")

        # ── Tornado sensitivity ────────────────────────────────────────────
        # -- Sensitivity matrix ROE (ROE x r) ----------------------------------------------
        with st.expander("🔲 Citlivost ROE (ROE × r) – Mid scénář", expanded=False):
            try:
                if _bps0_v <= 0:
                    st.info("Chybí BPS0 – citlivostní tabulka není dostupná.")
                else:
                    _roe_mid = _roe_p.get("Nominal", _roe_p.get("Mid", {}))
                    if not _roe_mid or "roe_1_3" not in _roe_mid or "r" not in _roe_mid:
                        st.info("Spusťte ROE model pro zobrazení citlivostní matice.")
                    else:
                        _roe_c      = _roe_mid["roe_1_3"]
                        _roe_r_c    = _roe_mid["r"]
                        _roe_vals_v = [round(_roe_c + d, 1) for d in range(-6, 7)]
                        _roe_r_vals = [round(_roe_r_c + d, 1) for d in range(-6, 7)]
                        _roe_sm_data = []
                        for _roe_v in _roe_vals_v:
                            _row_roe = {"ROE (%)": f"{_roe_v:.1f}%"}
                            for _r_v in _roe_r_vals:
                                _params_ov = dict(_roe_mid)
                                _params_ov["roe_1_3"]  = _roe_v
                                _params_ov["roe_4_5"]  = _roe_v
                                _params_ov["roe_6_10"] = _roe_v
                                _params_ov["r"]        = _r_v
                                _, _iv_ov, _, _, _, _, _ = _compute_roe_proj(
                                    _bps0_v, _eps0_v, _dps0_v, _params_ov
                                )
                                _row_roe[f"r {_r_v:.1f}%"] = (round(_iv_ov, 2)
                                                               if not np.isnan(_iv_ov) else None)
                            _roe_sm_data.append(_row_roe)
                        _roe_sm_df = pd.DataFrame(_roe_sm_data).set_index("ROE (%)")
                        _roe_sm_df_num = _roe_sm_df.apply(pd.to_numeric, errors="coerce")
                        _roe_mid_row = f"{_roe_c:.1f}%"
                        _roe_mid_col = f"r {_roe_r_c:.1f}%"
                        _roe_sm_styled = _sm_heatmap_style(
                            _roe_sm_df_num,
                            price=_cur_price_roe if not np.isnan(_cur_price_roe) else None,
                            mid_row=_roe_mid_row,
                            mid_col=_roe_mid_col,
                        )
                        st.caption(
                            f"BPS₀ = ${_bps0_v:.2f}  |  EPS₀ = ${_eps0_v:.2f}  "
                            f"|  Řádky = ROE (fáze 1–10), sloupce = r (Mid ± 6 pp)  |  🟡 = Mid baseline"
                        )
                        st.dataframe(_roe_sm_styled, use_container_width=True)
                        _roe_iv_mid = _compute_roe_proj(_bps0_v, _eps0_v, _dps0_v, _roe_p.get("Nominal", _roe_p.get("Mid", {})))[1]
                        if not np.isnan(_roe_iv_mid):
                            _roe_pr_v = _cur_price_roe
                            _pr_txt = f"  |  Aktuální cena: ${_roe_pr_v:.2f}" if not np.isnan(_roe_pr_v) else ""
                            st.caption(f"Mid IV = ${_roe_iv_mid:.2f}{_pr_txt}")
            except Exception as _roe_sm_exc:
                st.warning(f"Citlivostní matice se nepodařila: {_roe_sm_exc}")

        # ── Monte Carlo — ROE Gladiš ───────────────────────────────────────────
        with st.expander("🎲 Monte Carlo simulace — ROE Gladiš", expanded=False):
            st.caption(
                "Simultánní náhodná variace ROE, dividendového růstu dg, Exit P/E a r. "
                "σ předvyplněno z historické volatility ROE (lze přepsat). "
                "⚠️ Výchozí počet simulací = 5 000 (model je pomalejší). "
                "🟡 = percentily | 🔴 = aktuální cena"
            )
            if _bps0_v <= 0 or np.isnan(_eps0_v):
                st.info("Chybí BPS₀ nebo EPS₀.")
            else:
                _mcroe_nom    = _roe_p.get("Nominal", {})
                _mcroe_r_mu   = float(_mcroe_nom.get("r", 12.0))
                _mcroe_roe_mu = float(_mcroe_nom.get("roe_1_3", 15.0))
                _mcroe_dg_mu  = float(_mcroe_nom.get("dg_1_3", 3.0))
                _mcroe_pe_mu  = float(_mcroe_nom.get("pe", 15.0))
                _mcroe_pe_rng = max(3.0, _mcroe_pe_mu * 0.25)
                _mcroe_roe_sigma = round(float(roe_std) if not np.isnan(roe_std) else 3.0, 1)

                _mcroec1, _mcroec2, _mcroec3, _mcroec4 = st.columns(4)
                with _mcroec1:
                    st.markdown("**ROE (všechny fáze) (%)**")
                    _mcroe_roe_mu_in  = st.number_input("Průměr ROE", value=_mcroe_roe_mu,
                                                         key="mc_roe_roe_mu", format="%.1f")
                    _mcroe_roe_sig_in = st.number_input("σ ROE", value=max(0.1, _mcroe_roe_sigma),
                                                         min_value=0.1, key="mc_roe_roe_sig",
                                                         format="%.1f",
                                                         help=(
                                                             "Co je σ (sigma)?\n"
                                                             "Nepřesnost tvoé projekce návratnosti vlastního kapitálu.\n"
                                                             "Vyšší σ = ROE v simulaci více kolebá.\n"
                                                             "\n"
                                                             "Z čeho se počítá:\n"
                                                             "Historická std dev ROE z ročních dat.\n"
                                                             f"Předvyplněna: {_mcroe_roe_sigma:.1f} pp z dat (max 7 let).\n"
                                                             "\n"
                                                             "Tahak:\n"
                                                             "  1–3 pp • konzistentní ROE (vysokojakostní firma)\n"
                                                             "  3–8 pp • průměrná firma\n"
                                                             "  8+ pp • nestabilní ROE (re-investice, změny leverage)"
                                                         ))
                    st.caption(f"💡 90 % simulací: {_mcroe_roe_mu_in - 1.645 * _mcroe_roe_sig_in:.1f}–{_mcroe_roe_mu_in + 1.645 * _mcroe_roe_sig_in:.1f} %")
                with _mcroec2:
                    st.markdown("**Dividendový růst dg (%)**")
                    _mcroe_dg_mu_in  = st.number_input("Průměr dg", value=_mcroe_dg_mu,
                                                        key="mc_roe_dg_mu", format="%.1f")
                    _mcroe_dg_sig_in = st.number_input("σ dg", value=2.0, min_value=0.1,
                                                        key="mc_roe_dg_sig", format="%.1f",
                                                        help=(
                                                            "Co je σ (sigma)?\n"
                                                            "Nepřesnost tvoé projekce tempa růstu dividendy.\n"
                                                            "\n"
                                                            "Historická data pro dg nejsou přímo dostupná.\n"
                                                            "Výchozí 2 pp = mírná konzervativní nejistota.\n"
                                                            "\n"
                                                            "Tahak:\n"
                                                            "  1–2 pp • stabilní dividendová politika\n"
                                                            "  2–4 pp • běžná dividendová firma\n"
                                                            "  4+ pp • volatilní nebo rostoucí dividendy"
                                                        ))
                    st.caption(f"💡 90 % simulací: {_mcroe_dg_mu_in - 1.645 * _mcroe_dg_sig_in:.1f}–{_mcroe_dg_mu_in + 1.645 * _mcroe_dg_sig_in:.1f} %")
                with _mcroec3:
                    st.markdown("**Exit P/E (uniform)**")
                    _mcroe_pe_lo = st.number_input("Min P/E",
                                                    value=max(5.0, round(_mcroe_pe_mu - _mcroe_pe_rng, 1)),
                                                    key="mc_roe_pe_lo", format="%.1f")
                    _mcroe_pe_hi = st.number_input("Max P/E",
                                                    value=min(60.0, round(_mcroe_pe_mu + _mcroe_pe_rng, 1)),
                                                    key="mc_roe_pe_hi", format="%.1f")
                with _mcroec4:
                    st.markdown("**Diskontní sazba r (%) — fixní**")
                    _mcroe_r_fixed = st.number_input("r (fixní)", value=_mcroe_r_mu,
                                                      key="mc_roe_r_fixed", format="%.1f",
                                                      help=(
                                                          "🔒 Diskontní sazba je záměrně fixní.\n"
                                                          "Důvod: r ovlivňuje FV přes (1+r)^n — i malá\n"
                                                          "variace r produkuje extrémně asymetrické\n"
                                                          "rozdělení FV, obtížně interpretovatelné.\n"
                                                          "Vliv r na FV zobrazuje Tornado graf výše."
                                                      ))

                _mcroe_nsim = st.select_slider("Počet simulací", [1_000, 5_000, 10_000, 25_000],
                                                value=5_000, key="mc_roe_nsim")

                if st.button("▶ Spustit simulaci", key="mc_roe_run"):
                    _bps0_mc = _bps0_v
                    _eps0_mc = _eps0_v
                    _dps0_mc = _dps0_v
                    _mcroe_nom_snap = dict(_mcroe_nom)

                    def _mc_roe_fv(roe, dg, pe, r):
                        try:
                            params_sim = dict(_mcroe_nom_snap)
                            params_sim.update({
                                "roe_1_3": roe, "roe_4_5": roe, "roe_6_10": roe,
                                "dg_1_3": dg,  "dg_4_5": dg,  "dg_6_10": dg,
                                "pe": pe, "r": r,
                            })
                            _, iv, _, _, _ = _compute_roe_proj(_bps0_mc, _eps0_mc, _dps0_mc, params_sim)
                            return iv if np.isfinite(iv) else np.nan
                        except Exception:
                            return np.nan

                    _mcroe_specs = [
                        {"name": "roe", "dist": "normal",  "mean": _mcroe_roe_mu_in, "std": _mcroe_roe_sig_in},
                        {"name": "dg",  "dist": "normal",  "mean": _mcroe_dg_mu_in,  "std": _mcroe_dg_sig_in},
                        {"name": "pe",  "dist": "uniform", "low": _mcroe_pe_lo,       "high": _mcroe_pe_hi},
                        {"name": "r",   "dist": "fixed",   "value": _mcroe_r_fixed},
                    ]
                    with st.spinner(f"Probíhá {_mcroe_nsim:,} simulací..."):
                        _mcroe_res = run_monte_carlo(_mc_roe_fv, _mcroe_specs,
                                                      n_sim=_mcroe_nsim,
                                                      current_price=_cur_price_roe)
                    if _mcroe_res:
                        render_mc_chart(_mcroe_res, _cur_price_roe, "ROE Gladiš")
                    else:
                        st.warning("Simulace nevygenerovala platné výsledky.")

        with st.expander("🌪️ Analýza citlivosti (Tornado) – ROE Gladiš", expanded=False):
            st.caption(
                "🌪️ Tornado = citlivost one-at-a-time. Žlutá čára = baseline IV (PV dividend + PV termin. ceny) zvoleného scénáře. "
                "🟥 Červená = nižší IV výsledek  |  🟩 Zelená = vyšší IV výsledek. "
                "Delší pruh = větší citlivost. "
                "Δ pp (absolutně): ROE, dg, r. Δ % (relativně): Future P/E. "
                "⚠️ Payout ratio: pokud DPS > EPS v některém roce, IV může být nerealisticky vysoké. "
                "Tornado mění vždy jen 1 parametr."
            )
            _tr_sn = st.selectbox(
                "Základní scénář:", _ROE_SC_LABELS,
                index=min(1, len(_ROE_SC_LABELS) - 1), key="tornado_roe_scenario",
            )
            _tr_sn_params = _roe_p.get(_tr_sn, {})
            st.caption(f"Scénář {_tr_sn}: ROE 1–3 = {_tr_sn_params.get('roe_1_3', float('nan')):.1f} %  |  dg 1–3 = {_tr_sn_params.get('dg_1_3', float('nan')):.1f} %  |  r = {_tr_sn_params.get('r', float('nan')):.1f} %  |  P/E = {_tr_sn_params.get('pe', float('nan')):.1f}")
            _tr_delta_pp  = st.number_input("Δ sazeb – ± pp (ROE, dg, r — absolutně v % bodech)", value=1.0, min_value=0.1, max_value=10.0, step=0.1, format="%.1f", key="tornado_roe_delta_pp")
            _tr_delta_rel = st.number_input("Δ PE – absolutní delta násobku (Future P/E)", value=5.0, min_value=0.5, max_value=50.0, step=0.5, format="%.1f", key="tornado_roe_delta_rel")

            def _roe_iv_fn(params_override):
                try:
                    _, _iv_r, _, _, _, _, _ = _compute_roe_proj(_bps0_v, _eps0_v, _dps0_v, params_override)
                    return _iv_r
                except Exception:
                    return np.nan

            try:
                _tr_p = dict(_roe_p[_tr_sn])  # shallow copy of base params
                _tr_base = _roe_iv_fn(_tr_p)
                if not np.isnan(_tr_base):
                    _tr_impacts = []
                    for _pname, _key, _delta, _is_rel in [
                        (f"ROE roky 1–3 (±{_tr_delta_pp:.1f}pp)",   "roe_1_3",  _tr_delta_pp, False),
                        (f"ROE roky 4–5 (±{_tr_delta_pp:.1f}pp)",   "roe_4_5",  _tr_delta_pp, False),
                        (f"ROE roky 6–10 (±{_tr_delta_pp:.1f}pp)",  "roe_6_10", _tr_delta_pp, False),
                        (f"Růst DPS 1–3 (±{_tr_delta_pp:.1f}pp)",  "dg_1_3",   _tr_delta_pp, False),
                        (f"Růst DPS 4–5 (±{_tr_delta_pp:.1f}pp)",  "dg_4_5",   _tr_delta_pp, False),
                        (f"Růst DPS 6–10 (±{_tr_delta_pp:.1f}pp)", "dg_6_10",  _tr_delta_pp, False),
                        (f"Discount rate r (±{_tr_delta_pp:.1f}pp)", "r",        _tr_delta_pp,  False),
                        (f"Future P/E (±{_tr_delta_rel:.1f})",           "pe",       _tr_delta_rel, False),
                    ]:
                        _p_lo = dict(_tr_p); _p_hi = dict(_tr_p)
                        if _is_rel:
                            _p_lo[_key] = _tr_p[_key] * (1 - _delta / 100)
                            _p_hi[_key] = _tr_p[_key] * (1 + _delta / 100)
                        else:
                            _p_lo[_key] = _tr_p[_key] - _delta
                            _p_hi[_key] = _tr_p[_key] + _delta
                        _lo_v = _roe_iv_fn(_p_lo)
                        _hi_v = _roe_iv_fn(_p_hi)
                        if not (np.isnan(_lo_v) or np.isnan(_hi_v)):
                            _tr_impacts.append({"Parametr": _pname, "Nízká": _lo_v, "Vysoká": _hi_v,
                                                "RozsahAbs": abs(_hi_v - _lo_v)})
                    if _tr_impacts:
                        _tr_df = pd.DataFrame(_tr_impacts).sort_values("RozsahAbs", ascending=False)
                        _tr_df["Baseline"] = _tr_base
                        _tr_df["IV_nizka"] = _tr_df["Nízká"]
                        _tr_df["IV_vysoka"] = _tr_df["Vysoká"]
                        _tr_df["DiffLo"] = _tr_df["Nízká"] - _tr_base
                        _tr_df["DiffHi"] = _tr_df["Vysoká"] - _tr_base
                        _tr_long_rows = []
                        for _, _r in _tr_df.iterrows():
                            _bl = float(_r["Baseline"])
                            for _dc, _ic, _lbl in [("DiffLo","IV_nizka","Nižší IV"),("DiffHi","IV_vysoka","Vyšší IV")]:
                                _da = float(_r[_dc])
                                _tr_long_rows.append({"Parametr": str(_r["Parametr"]), "DiffAbs": _da,
                                    "DiffPct": round(_da / _bl * 100, 2) if _bl else 0.0,
                                    "Baseline": _bl, "IV_nizka": float(_r["IV_nizka"]),
                                    "IV_vysoka": float(_r["IV_vysoka"]), "StranaCZ": _lbl,
                                    "BarColor": "#66BB6A" if _da >= 0 else "#FF7043"})
                        _tr_sort = list(_tr_df["Parametr"])
                        _tr_h = max(150, len(_tr_impacts) * 50)
                        _tr_sort_tt = [
                            {"field": "Parametr", "type": "nominal"},
                            {"field": "StranaCZ", "type": "nominal", "title": "Výsledek"},
                            {"field": "Baseline", "type": "quantitative", "format": "$.2f", "title": "Baseline IV ($)"},
                            {"field": "IV_nizka", "type": "quantitative", "format": "$.2f", "title": "IV nižší ($)"},
                            {"field": "IV_vysoka", "type": "quantitative", "format": "$.2f", "title": "IV vysoká ($)"},
                            {"field": "DiffAbs", "type": "quantitative", "format": "+$.2f", "title": "Δ vs baseline ($)"},
                            {"field": "DiffPct", "type": "quantitative", "format": "+.1f", "title": "Δ vs baseline (%)"},
                        ]
                        st.vega_lite_chart({
                            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
                            "height": _tr_h,
                            "title": f"Tornado: ROE Gladiš — {_tr_sn} scénář",
                            "config": {"view": {"strokeOpacity": 0}},
                            "layer": [
                                {"data": {"values": [r for r in _tr_long_rows if r["DiffAbs"] >= 0]}, "mark": {"type": "bar", "opacity": 0.75, "color": "#66BB6A"}, "encoding": {"y": {"field": "Parametr", "type": "nominal", "sort": _tr_sort, "title": None, "axis": {"labelOverlap": False, "labelLimit": 300}}, "x": {"field": "DiffAbs", "type": "quantitative", "title": "Δ Intrinsic Value vs baseline ($)", "axis": {"grid": True}}, "tooltip": _tr_sort_tt}},
                                {"data": {"values": [r for r in _tr_long_rows if r["DiffAbs"] < 0]}, "mark": {"type": "bar", "opacity": 0.75, "color": "#FF7043"}, "encoding": {"y": {"field": "Parametr", "type": "nominal", "sort": _tr_sort}, "x": {"field": "DiffAbs", "type": "quantitative"}, "tooltip": _tr_sort_tt}},
                                {"data": {"values": _tr_long_rows}, "transform": [{"calculate": "format(datum.DiffPct, '+.1f') + '%'", "as": "_dp_label"}], "mark": {"type": "text", "fontSize": 10, "align": {"expr": "datum.DiffAbs >= 0 ? 'left' : 'right'"}, "dx": {"expr": "datum.DiffAbs >= 0 ? 4 : -4"}}, "encoding": {"y": {"field": "Parametr", "type": "nominal", "sort": _tr_sort}, "x": {"field": "DiffAbs", "type": "quantitative"}, "text": {"field": "_dp_label", "type": "nominal"}, "color": {"value": "#93a3b8"}}},
                                {"data": {"values": [{"x": 0}]}, "mark": {"type": "rule", "color": "#FFD54F", "strokeDash": [4, 2]}, "encoding": {"x": {"field": "x", "type": "quantitative"}}},
                            ],
                        }, width='stretch')
                        _tr_price_txt = f"  |  Aktuální cena: ${_cur_price_roe:.2f}" if not np.isnan(_cur_price_roe) else ""
                        st.caption(f"Baseline IV = ${_tr_base:.2f}{_tr_price_txt}. Pruhy = Δ vs baseline. Žlutá čára = 0.")
                    else:
                        st.info("Nelze vypočítat tornado (chybí data).")
                else:
                    st.info("Základní IV není dostupné – zkontroluj BPS/EPS data.")
            except Exception as _t_exc_roe:
                st.warning(f"Tornado nelze zobrazit: {_t_exc_roe}")

        with st.expander("📐 Equations – ROE model (click to expand)"):
            st.markdown(r"""
    **Projekce EPS, DPS, BPS** (piecewise, roky 1–3 / 4–5 / 6–10):

    **Pořadí výpočtu v každém roce $t$:**

    **1) EPS** — odvozeno z *počáteční* účetní hodnoty (BPS z konce roku $t-1$):

    $$
    EPS_t^{model} = BPS_{t-1} \cdot ROE_t
    $$

    $$
    EPS_t = \begin{cases}
    EPS_0 \cdot (1-cf) + EPS_1^{model} \cdot cf & t=1 \\
    EPS_t^{model} & t>1
    \end{cases}
    $$

    **2) DPS** — dividenda roste geometricky:

    $$
    DPS_t = DPS_{t-1} \cdot (1 + g_{div,t})
    $$

    **3) BPS** — aktualizace účetní hodnoty pomocí *aktuálního* EPS a DPS:

    $$
    BPS_t = BPS_{t-1} + EPS_t - DPS_t
    $$

    $\text{ROE}_t$ a $g_{div,t}$ jsou zadané piecewise hodnoty pro daný horizont.
    $cf$ = TTM correction factor (mix TTM EPS vs. modelového EPS v roce 1).

    ---

    **Payout ratio:**

    $$
    \text{Payout}_t = \frac{\text{DPS}_t}{\text{EPS}_t}
    $$

    ---

    **PV po-daňových dividend:**

    $$
    PV_{div} = \sum_{t=1}^{10} \frac{\text{DPS}_t \cdot (1 - \text{TaxRate})}{(1 + r)^t}
    $$

    ---

    **Terminální cena a její PV:**

    $$
    \text{Price}_{10} = \text{EPS}_{10} \times P/E_{exit}
    \qquad
    PV_{term} = \frac{\text{Price}_{10}}{(1 + r)^{10}}
    $$

    ---

    **Intrinsic Value (fair value):**

    $$
    \text{IV} = PV_{div} + PV_{term}
    $$

    ---

    **Upside/Downside:**

    $$
    \text{Upside/Downside} = \frac{\text{IV}}{\text{CurrentPrice}} - 1
    $$

    ---

    *Vstupy ROE, $g_{div}$, Tax a $r$ jsou zadávány v procentech a před výpočtem děleny 100.*
            """)

        # ── Kompletní přehled (detailní tabulka) ────────────────────────
        if st.checkbox("Kompletní přehled", key="roe_complete_overview_chk"):
            _tabs = st.tabs(_ROE_SC_LABELS)

            for _tab, _sn in zip(_tabs, _ROE_SC_LABELS):
                with _tab:
                    _p_sc = _roe_p.get(_sn, {})
                    _rows_sc = _roe_proj.get(_sn, {}).get("rows", [])
                    if not _rows_sc:
                        st.info("Pro tento scénář nejsou dostupná projekční data.")
                        continue

                    _tax_d_sc = _safe_float(_p_sc.get("tax", np.nan)) / 100.0
                    _r_d_sc   = _safe_float(_p_sc.get("r", np.nan)) / 100.0
                    _pe_sc    = _safe_float(_p_sc.get("pe", np.nan))
                    _p0_sc    = _safe_float(_cur_price_roe)

                    _col_labels = ["TTM"] + [str(_forecast_base_year_roe + int(_rw.get("t", 0))) for _rw in _rows_sc]

                    _bps_row = [_safe_float(_bps0_v)]
                    _roe_row = [_safe_float(_roe0_v)]
                    _eps_row = [_safe_float(_eps0_v)]
                    _dps_row = [_safe_float(_dps0_v)]
                    _payout_row = [(_safe_float(_dps0_v) / _safe_float(_eps0_v) * 100.0) if (_safe_float(_eps0_v) > 0) else np.nan]

                    _future_pe_row = [np.nan]
                    _price_row = [np.nan]
                    _cum_div_row = [np.nan]
                    _cum_div_net_row = [np.nan]
                    _price_plus_div_row = [np.nan]
                    _gain_abs_row = [np.nan]
                    _gain_pct_row = [np.nan]
                    _years_row = [np.nan]
                    _gain_pa_row = [np.nan]
                    _pv_row = [np.nan]
                    _mos_row = [np.nan]

                    _cum_div = 0.0
                    _cum_div_net = 0.0

                    for _rw in _rows_sc:
                        _t = int(_rw.get("t", 0))
                        _eps_t = _safe_float(_rw.get("EPS", np.nan))
                        _dps_t = _safe_float(_rw.get("DPS", np.nan))
                        _bps_t = _safe_float(_rw.get("BPS", np.nan))
                        _roe_t = _safe_float(_rw.get("ROE", np.nan))
                        _payout_t = _safe_float(_rw.get("Payout", np.nan))

                        _price_t = _eps_t * _pe_sc if (not np.isnan(_eps_t) and not np.isnan(_pe_sc)) else np.nan
                        if not np.isnan(_dps_t):
                            _cum_div += _dps_t
                            if not np.isnan(_tax_d_sc):
                                _cum_div_net += _dps_t * (1.0 - _tax_d_sc)

                        _price_plus_div_t = _price_t + _cum_div_net if (not np.isnan(_price_t)) else np.nan
                        _gain_abs_t = _price_plus_div_t - _p0_sc if (not np.isnan(_price_plus_div_t) and not np.isnan(_p0_sc)) else np.nan
                        _gain_pct_t = (_gain_abs_t / _p0_sc) if (not np.isnan(_gain_abs_t) and _p0_sc > 0) else np.nan
                        _gain_pa_t = ((_price_plus_div_t / _p0_sc) ** (1.0 / _t) - 1.0) if (
                            not np.isnan(_price_plus_div_t) and _price_plus_div_t > 0 and not np.isnan(_p0_sc) and _p0_sc > 0 and _t > 0
                        ) else np.nan
                        _pv_t = (_price_plus_div_t / ((1.0 + _r_d_sc) ** _t)) if (
                            not np.isnan(_price_plus_div_t) and not np.isnan(_r_d_sc) and _t > 0
                        ) else np.nan
                        _mos_t = (_pv_t / _p0_sc - 1.0) if (not np.isnan(_pv_t) and not np.isnan(_p0_sc) and _p0_sc > 0) else np.nan

                        _bps_row.append(_bps_t)
                        _roe_row.append(_roe_t * 100.0 if not np.isnan(_roe_t) else np.nan)
                        _eps_row.append(_eps_t)
                        _dps_row.append(_dps_t)
                        _payout_row.append(_payout_t * 100.0 if not np.isnan(_payout_t) else np.nan)

                        _future_pe_row.append(_pe_sc)
                        _price_row.append(_price_t)
                        _cum_div_row.append(_cum_div)
                        _cum_div_net_row.append(_cum_div_net)
                        _price_plus_div_row.append(_price_plus_div_t)
                        _gain_abs_row.append(_gain_abs_t)
                        _gain_pct_row.append(_gain_pct_t * 100.0 if not np.isnan(_gain_pct_t) else np.nan)
                        _years_row.append(float(_t))
                        _gain_pa_row.append(_gain_pa_t * 100.0 if not np.isnan(_gain_pa_t) else np.nan)
                        _pv_row.append(_pv_t)
                        _mos_row.append(_mos_t * 100.0 if not np.isnan(_mos_t) else np.nan)

                    _overview_df = pd.DataFrame(
                        {
                            "BPS [$]": _bps_row,
                            "ROE [%]": _roe_row,
                            "EPS [$]": _eps_row,
                            "Dividend Per Share [$]": _dps_row,
                            "Dividend payout ratio [%]": _payout_row,
                            "Future PE": _future_pe_row,
                            "Price [$]": _price_row,
                            "Cumulative dividends [$]": _cum_div_row,
                            "Cum. dividends without tax [$]": _cum_div_net_row,
                            "Price + dividends [$]": _price_plus_div_row,
                            "Gain [$]": _gain_abs_row,
                            "Gain [%]": _gain_pct_row,
                            "No. of years": _years_row,
                            "Gain [%] p.a.": _gain_pa_row,
                            "Present value [$]": _pv_row,
                            "MOS [%]": _mos_row,
                        },
                        index=_col_labels,
                    ).T

                    _row_cfg = {
                        "BPS [$]": "%.2f",
                        "ROE [%]": "%.1f%%",
                        "EPS [$]": "%.2f",
                        "Dividend Per Share [$]": "%.2f",
                        "Dividend payout ratio [%]": "%.1f%%",
                        "Future PE": "%.2f",
                        "Price [$]": "%.2f",
                        "Cumulative dividends [$]": "%.2f",
                        "Cum. dividends without tax [$]": "%.2f",
                        "Price + dividends [$]": "%.2f",
                        "Gain [$]": "%.2f",
                        "Gain [%]": "%.0f%%",
                        "No. of years": "%.2f",
                        "Gain [%] p.a.": "%.0f%%",
                        "Present value [$]": "%.2f",
                        "MOS [%]": "%.0f%%",
                    }

                    _col_cfg = {"index": st.column_config.TextColumn("Year")}
                    for _cl in _overview_df.columns:
                        _col_cfg[_cl] = st.column_config.NumberColumn(str(_cl), format=_row_cfg.get(_overview_df.index[0], "%.2f"))

                    _overview_h = (len(_overview_df) + 1) * 35 + 4
                    st.dataframe(_overview_df, width="stretch", height=_overview_h)

        # ── Uložit analýzu ROE ────────────────────────────────────────────
        try:
            _roe_bytes = build_roe_excel_bytes(
                roe_params=_roe_p,
                roe_proj=_roe_proj,
                roe_sc_labels=_ROE_SC_LABELS,
                ticker=st.session_state.val_ticker,
                current_price=_cur_price_roe,
            )
            _all_bytes = build_all_excel_bytes(
                effective_df=effective_df,
                metrics_df=metrics_df,
                manual_df=st.session_state.val_manual_df,
                override_mask=override_mask,
                ticker=st.session_state.val_ticker,
                years=st.session_state.val_years,
                current_price=float(_d_price) if not np.isnan(_d_price) else np.nan,
                scenario_inputs_df=_snap_scenario_inputs_df,
                scenario_outputs_df=_snap_scenario_outputs_df,
                roe_params=_roe_p,
                roe_proj=_roe_proj,
                roe_sc_labels=_ROE_SC_LABELS,
                current_price_roe=_cur_price_roe,
                simple_eps_params=st.session_state.get("simple_eps_params", {}),
                simple_rev_params=st.session_state.get("simple_rev_params", {}),
                damodaran_params=st.session_state.get("damodaran_params", {}),
            )
            _roe_fname = f"{st.session_state.val_ticker}_roe_{datetime.now().strftime('%y_%m_%d')}.xlsx"
            _all_fname = f"{st.session_state.val_ticker}_vse_{datetime.now().strftime('%y_%m_%d')}.xlsx"
            _roe_sc1, _roe_sc2 = st.columns([1, 1])
            with _roe_sc1:
                st.download_button(
                    "💾 Uložit tento model (včetně historických dat)",
                    data=_roe_bytes,
                    file_name=_roe_fname,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="snap_roe_save_btn",
                    width="stretch",
                )
            with _roe_sc2:
                st.download_button(
                    "💾 Uložit všechny modely (včetně historických dat)",
                    data=_all_bytes,
                    file_name=_all_fname,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="snap_all_save_btn",
                    width="stretch",
                )
        except Exception as _exc_roe_save:
            st.warning(f"Uložení selhalo: {_exc_roe_save}")

    # ── Summary Table – all models ────────────────────────────────────────
    st.divider()
    st.markdown("### 📊 Souhrn ocenění – všechny modely")
    try:
        _sum_sc_labels = ["Low", "Mid", "High"]
        # ROE model uses different scenario names – map Low→Worst, Mid→Nominal, High→Best
        _ROE_SUM_MAP = {"Low": "Worst", "Mid": "Nominal", "High": "Best"}
        _sum_rows = []

        # Current price for upside calculation
        try:
            _sum_cur_p = _safe_float(effective_df.loc["TTM", "Stock Price"])
            if np.isnan(_sum_cur_p):
                _sum_cur_p = float(_d_price)  # fallback na Advanced
        except Exception:
            _sum_cur_p = None

        def _upside(fv):
            """Return formatted upside string or 'N/A'."""
            try:
                if _sum_cur_p and _sum_cur_p > 0 and fv == fv:  # fv not NaN
                    pct = (float(fv) / _sum_cur_p - 1) * 100
                    return f"{pct:+.1f} %"
            except Exception:
                pass
            return "N/A"

        def _cagr_fmt(cagr_dec):
            """Format a CAGR decimal (e.g. 0.085) as '+8.5 %'."""
            try:
                if cagr_dec == cagr_dec:  # not NaN
                    return f"{float(cagr_dec) * 100:+.1f} %"
            except Exception:
                pass
            return "N/A"

        # Simple EPS model
        try:
            _sep_row  = {"Model": "Simple EPS – Fair Value (PV) $"}
            _sep_cagr = {"Model": "  ↳ CAGR (EPS exit)"}
            for _sn_s in _sum_sc_labels:
                _rv = _seps_res_a.get(_sn_s)
                _fv = _rv['fair_value'] if _rv and not np.isnan(_rv.get("fair_value", np.nan)) else np.nan
                _sep_row[_sn_s]  = f"${_fv:.2f}" if not np.isnan(_fv) else "N/A"
                _sep_cagr[_sn_s] = _cagr_fmt(_rv.get("cagr", np.nan)) if _rv else "N/A"
            _sum_rows.append(_sep_row)
            _sum_rows.append(_sep_cagr)
        except Exception:
            pass

        # Simple Revenue model
        try:
            _srev_row  = {"Model": "Simple Revenue – Fair Value (PV) $"}
            _srev_cagr = {"Model": "  ↳ CAGR (Revenue exit)"}
            for _sn_s in _sum_sc_labels:
                _rv = _srev_res_b.get(_sn_s)
                _fv = _rv['fair_value'] if _rv and not np.isnan(_rv.get("fair_value", np.nan)) else np.nan
                _srev_row[_sn_s]  = f"${_fv:.2f}" if not np.isnan(_fv) else "N/A"
                _srev_cagr[_sn_s] = _cagr_fmt(_rv.get("cagr", np.nan)) if _rv else "N/A"
            _sum_rows.append(_srev_row)
            _sum_rows.append(_srev_cagr)
        except Exception:
            pass

        # Damodaran model
        try:
            _dam_row  = {"Model": "Damodaran FCFF – IV per share $"}
            _dam_cagr = {"Model": "  ↳ CAGR"}
            for _sn_s in _sum_sc_labels:
                _rv = _dam_res.get(_sn_s)
                _fv = _rv['iv_ps'] if _rv and "error" not in _rv and not np.isnan(_rv.get("iv_ps", np.nan)) else np.nan
                _dam_row[_sn_s]  = f"${_fv:.2f}" if not np.isnan(_fv) else "N/A"
                _dam_cagr[_sn_s] = _cagr_fmt(_rv.get("cagr", np.nan)) if _rv and "error" not in _rv else "N/A"
            _sum_rows.append(_dam_row)
            _sum_rows.append(_dam_cagr)
        except Exception:
            pass

        # ROE model – uses Nominal/Worst/Best → map to Low/Mid/High columns
        try:
            _roe_r    = {"Model": "ROE (Gladiš) – IV per share $"}
            _roe_cagr = {"Model": "  ↳ CAGR (10 let)"}
            for _sn_s in _sum_sc_labels:
                _roe_sn = _ROE_SUM_MAP[_sn_s]
                _rv = _roe_proj.get(_roe_sn)
                _fv = _rv['iv'] if _rv and "error" not in _rv and not np.isnan(_rv.get("iv", np.nan)) else np.nan
                _roe_r[_sn_s]    = f"${_fv:.2f}" if not np.isnan(_fv) else "N/A"
                _roe_cagr[_sn_s] = _cagr_fmt(_rv.get("cagr", np.nan)) if _rv and "error" not in _rv else "N/A"
            _sum_rows.append(_roe_r)
            _sum_rows.append(_roe_cagr)
        except Exception:
            pass

        # Advanced – P/E Fair Value
        try:
            _adv_pe   = {"Model": "Advanced – P/E Fair Value $"}
            _adv_pe_c = {"Model": "  ↳ CAGR (P/E exit)"}
            for _sn_s in _sum_sc_labels:
                _rv = _sc_outputs.get(_sn_s, {})
                _fv = _rv.get("pe_fair_value", np.nan)
                _adv_pe[_sn_s]   = f"${_fv:.2f}" if not np.isnan(_fv) else "N/A"
                _adv_pe_c[_sn_s] = _cagr_fmt(_rv.get("cagr_via_pe_exit", np.nan))
            _sum_rows.append(_adv_pe)
            _sum_rows.append(_adv_pe_c)
        except Exception:
            pass

        # Advanced – Equity DCF Fair Value
        try:
            _adv_dcf  = {"Model": "Advanced – Equity DCF Fair Value $"}
            _adv_dcf_c = {"Model": "  ↳ CAGR (DCF exit)"}
            for _sn_s in _sum_sc_labels:
                _rv = _sc_outputs.get(_sn_s, {})
                _fv = _rv.get("dcf_fair_value", np.nan)
                _adv_dcf[_sn_s]   = f"${_fv:.2f}" if not np.isnan(_fv) else "N/A"
                _adv_dcf_c[_sn_s] = _cagr_fmt(_rv.get("cagr_via_dcf_exit", np.nan))
            _sum_rows.append(_adv_dcf)
            _sum_rows.append(_adv_dcf_c)
        except Exception:
            pass

        if _sum_rows:
            _sum_df = pd.DataFrame(_sum_rows).set_index("Model")
            # Current price row
            try:
                _cur_p_str = f"${float(_d_price):.2f}" if not np.isnan(_d_price) else "N/A"
            except Exception:
                _cur_p_str = "N/A"
            _price_row = pd.DataFrame([{"Low": _cur_p_str, "Mid": _cur_p_str, "High": _cur_p_str}], index=["── Aktuální cena ──"])
            _sum_df = pd.concat([_sum_df, _price_row])
            _sc_colors_sum = {"Low": "#FF7043", "Mid": "#FFD54F", "High": "#66BB6A"}
            _hdr_html = "".join([
                f"<th style='text-align:center;color:{_sc_colors_sum[c]};padding:8px 14px;font-size:13px'>{c}</th>" if c in _sc_colors_sum
                else f"<th style='text-align:left;padding:8px 14px;font-size:13px'>{c}</th>"
                for c in ["Model"] + _sum_sc_labels
            ])
            # Alternating background colours per model block
            _ALT_BG = [
                "rgba(255,255,255,0.00)",   # model 0 – transparent
                "rgba(79,142,247,0.07)",    # model 1 – faint blue
                "rgba(255,255,255,0.00)",
                "rgba(79,142,247,0.07)",
                "rgba(255,255,255,0.00)",
                "rgba(79,142,247,0.07)",
            ]
            _rows_html = ""
            _model_idx = -1  # increments on every main (non-sub) row
            for _idx, _row in _sum_df.iterrows():
                _is_price  = "Aktuální cena" in str(_idx)
                _is_sub    = str(_idx).startswith("  ↳")
                if not _is_sub and not _is_price:
                    _model_idx += 1
                _bg = _ALT_BG[_model_idx % len(_ALT_BG)] if not _is_price else "transparent"
                _sep = "border-top:2px solid #3a3d4e;" if (not _is_sub and not _is_price) else ""
                _pt_sep = "border-top:2px solid #4a4d5e;" if _is_price else ""
                _rows_html += f"<tr style='background:{_bg};{_sep}{_pt_sep}'>"
                _lbl_color = "#93a3b8" if _is_sub else ("#e0e6f0" if not _is_price else "#cdd6f4")
                _lbl_size  = "11px"    if _is_sub else "13px"
                _lbl_weight = "400"   if _is_sub else ("600" if not _is_price else "700")
                _lbl_pad   = "2px 12px 3px 24px" if _is_sub else ("6px 14px" if not _is_price else "8px 14px")
                _rows_html += f"<td style='color:{_lbl_color};padding:{_lbl_pad};font-size:{_lbl_size};font-weight:{_lbl_weight}'>{_idx}</td>"
                for _c in _sum_sc_labels:
                    _v = _row.get(_c, "N/A")
                    if _is_price:
                        _clr = _sc_colors_sum.get(_c, "#cdd6f4")
                        _fw  = "700"
                        _fs  = "13px"
                        _pad = "8px 14px"
                    elif _is_sub:
                        _v_str = str(_v)
                        if _v_str.startswith("+"):
                            _clr = "#66BB6A"
                        elif _v_str.startswith("-") or _v_str.startswith("−"):
                            _clr = "#FF7043"
                        else:
                            _clr = "#93a3b8"
                        _fw  = "400"
                        _fs  = "11px"
                        _pad = "2px 14px 3px 14px"
                    else:
                        try:
                            _fv_f = float(str(_v).replace("$", "").replace(",", ""))
                            if _sum_cur_p and _sum_cur_p > 0:
                                _ratio = _fv_f / _sum_cur_p
                                _clr = "#66BB6A" if _ratio > 1.05 else ("#FF7043" if _ratio < 0.95 else "#FFD54F")
                            else:
                                _clr = "#e2e8f0"
                        except Exception:
                            _clr = "#e2e8f0"
                        _fw  = "700"
                        _fs  = "13px"
                        _pad = "6px 14px"
                    _rows_html += f"<td style='text-align:right;padding:{_pad};font-size:{_fs};font-weight:{_fw};color:{_clr}'>{_v}</td>"
                _rows_html += "</tr>"
            st.markdown(
                f"<table style='width:100%;border-collapse:collapse;border-radius:8px;overflow:hidden'>"
                f"<thead><tr style='background:rgba(42,45,62,0.9);border-bottom:2px solid #4a4d5e'>{_hdr_html}</tr></thead>"
                f"<tbody>{_rows_html}</tbody></table>",
                unsafe_allow_html=True,
            )
            st.caption("Low/Mid/High = scénáře modelu. ↳ CAGR = roční výnos z tržní ceny na FV. ROE sloupce: Low=Worst, Mid=Nominal, High=Best. Barva FV: 🟢 > cena+5 % | 🟡 ±5 % | 🔴 < cena−5 %.")
        else:
            st.info("Vypočítejte libovolný model, aby se zde zobrazil souhrn.")
    except Exception as _sum_exc:
        st.caption(f"Souhrn není k dispozici: {_sum_exc}")

st.markdown(
        """
        <div style="margin-top:18px;font-size:11px;color:#6b7280;opacity:0.8;line-height:1.4;">
            Jan Kindermann<br/>
            coax.sacra.5m@icloud.com
        </div>
        """,
        unsafe_allow_html=True,
)

