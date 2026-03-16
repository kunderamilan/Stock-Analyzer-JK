
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
    
    """Close série pro ticker + vybrané období."""
    session = get_yf_session()
    t = yf.Ticker(ticker=ticker, session=session)
    today = pd.Timestamp.today().normalize()
    
    
    if start or end:
        # ✅ doplnění chybějící hranice
        start_ts = pd.Timestamp(start) if start else None
        end_ts = (
            pd.Timestamp(end) + pd.Timedelta(days=1)
            if end
            else pd.Timestamp.today() + pd.Timedelta(days=1)
        )
        hist = t.history(
            start=start_ts,
            end=end_ts,
        )
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
            start = today - pd.Timedelta(days=365 * 3)
            hist = t.history(start=start.to_pydatetime(), end=(today + pd.Timedelta(days=1)).to_pydatetime())
        elif period_key == "5 years":
            hist = t.history(period="5y")
        elif period_key == "10 years":
            start = today - pd.Timedelta(days=365 * 10)
            hist = t.history(start=start.to_pydatetime(), end=(today + pd.Timedelta(days=1)).to_pydatetime())
        elif period_key == "YTD":
            start = pd.Timestamp(year=today.year, month=1, day=1)
            hist = t.history(start=start.to_pydatetime(), end=(today + pd.Timedelta(days=1)).to_pydatetime())
        else:
            hist = t.history(period="1y")
        if start or end:
            start_ts = pd.Timestamp(start) if start else None
            end_ts = pd.Timestamp(end) + pd.Timedelta(days=1) if end else None
            hist = t.history(
                start=start_ts,
                end=end_ts,
            )
        else:
            # původní period_key logika
            ...
        # DŮLEŽITÁ POJISTKA
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
                    "pegRatio":        _raw(dks, "pegRatio"),
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

        def _pick(api_key, info_key):
            v = ks.get(api_key)
            if v is None:
                v = info.get(info_key)
            return v

        return {
            "Ticker": ticker,
            "Trailing P/E":         _fmt_ratio(_pick("trailingPE",      "trailingPE")),
            "Forward P/E":          _fmt_ratio(_pick("forwardPE",       "forwardPE")),
            "PEG ratio (5yr exp.)": _fmt_ratio(_pick("pegRatio",        "pegRatio")),
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

def on_mode_change():
    # přepočítat jen pokud už graf existuje (aby to netahalo data hned po startu)
    if st.session_state.df_long is not None:
        reload_data()

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
    _tooltip = [
        alt.Tooltip("Ticker:N"),
        alt.Tooltip("Date:T"),
        alt.Tooltip("Value:Q", format=".2f"),
    ]

    base = alt.Chart(st.session_state.df_long).mark_line().encode(x=_x, color=_color, tooltip=_tooltip)

    chart = (
        alt.layer(
            base.encode(y=alt.Y("Value:Q", axis=y_axis_left)),
            base.encode(y=alt.Y("Value:Q", axis=y_axis_right)),
        )
        .properties(height=420)
        .resolve_scale(y="shared")
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


# ── API data fetcher ──────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_valuation_api_data(ticker: str, years: int) -> pd.DataFrame:
    """
    Return a DataFrame indexed by year string (e.g. '2023'), with columns:
      Revenue_M, NetIncome_M, TotalEquity_M, FCF_M, LongTermDebt_M,
      SharesOutstanding_M, DividendPerShare, DividendYield,
      EPS, BPS, StockPrice, PE, PB, PS, PFCF, ROE, ROIC
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
        hist.index = hist.index.tz_localize(None) if hist.index.tzinfo else hist.index
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
        "FCF [M]": np.nan, "Long term debt [M]": np.nan, "Shares Outstanding [M]": np.nan,
        "Dividend per share": np.nan, "Dividend Yield": np.nan,
        "EPS $": np.nan, "BPS $": np.nan, "Profit Margin": np.nan, "Stock Price": np.nan,
        "P/E": np.nan, "P/B": np.nan, "P/S": np.nan, "P/FCF": np.nan,
        "ROE": np.nan, "ROIC": np.nan,
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
        ocf         = _get_val(cf_ocf,   col)
        capex       = _get_val(cf_capex, col)
        fcf         = (ocf + capex) / 1e6 if not np.isnan(ocf) and not np.isnan(capex) else np.nan
        shares_m    = _get_val(bal_sh,   col) / 1e6
        eps         = _get_val(inc_eps,  col)
        bps         = (tot_equity * 1e6 / (shares_m * 1e6)) if (shares_m and shares_m > 0 and not np.isnan(tot_equity)) else np.nan
        profit_margin = (net_income / revenue * 100) if (revenue and revenue != 0 and not np.isnan(net_income)) else np.nan
        price       = _eoy_price(yr)
        div_ps      = float(div_by_year.get(yr, np.nan))
        div_yield   = (div_ps / price) if (price and price > 0 and not np.isnan(div_ps)) else np.nan
        pe          = (price / eps)    if (eps   and eps   > 0 and not np.isnan(price)) else np.nan
        pb          = (price / bps)    if (bps   and bps   > 0 and not np.isnan(price)) else np.nan
        rev_ps      = (revenue * 1e6 / (shares_m * 1e6)) if (shares_m and shares_m > 0 and not np.isnan(revenue)) else np.nan
        ps          = (price / rev_ps) if (rev_ps and rev_ps > 0 and not np.isnan(price)) else np.nan
        fcf_ps      = (fcf * 1e6 / (shares_m * 1e6)) if (shares_m and shares_m > 0 and not np.isnan(fcf)) else np.nan
        pfcf        = (price / fcf_ps) if (fcf_ps and fcf_ps > 0 and not np.isnan(price)) else np.nan
        roe         = (net_income / tot_equity * 100) if (tot_equity and tot_equity > 0 and not np.isnan(net_income)) else np.nan
        invested    = tot_equity + (ltd if not np.isnan(ltd) else 0.0)
        roic        = (net_income / invested * 100) if (invested and invested > 0 and not np.isnan(net_income)) else np.nan

        rows[yr_str] = {
            "Revenue [M]":            revenue,
            "Net Income [M]":         net_income,
            "Total Equity [M]":       tot_equity,
            "FCF [M]":                fcf,
            "Long term debt [M]":     ltd,
            "Shares Outstanding [M]": shares_m,
            "Dividend per share":     div_ps,
            "Dividend Yield":         div_yield,
            "EPS $":                  eps,
            "BPS $":                  bps,
            "Profit Margin":          profit_margin,
            "Stock Price":            price,
            "P/E":                    pe,
            "P/B":                    pb,
            "P/S":                    ps,
            "P/FCF":                  pfcf,
            "ROE":                    roe,
            "ROIC":                   roic,
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
        ttm_sh      = _latest_bal(q_bal, "Ordinary Shares Number", "Share Issued") / 1e6
        ttm_ocf     = _ttm_sum_cf(q_cf, "Operating Cash Flow", "Cash Flow From Continuing Operations")
        ttm_capex   = _ttm_sum_cf(q_cf, "Capital Expenditure")
        ttm_fcf     = (ttm_ocf + ttm_capex) / 1e6 if not np.isnan(ttm_ocf) and not np.isnan(ttm_capex) else np.nan
        ttm_bps     = (ttm_eq * 1e6 / (ttm_sh * 1e6)) if (ttm_sh and ttm_sh > 0 and not np.isnan(ttm_eq)) else np.nan
        ttm_profit_margin = (ttm_ni / ttm_rev * 100) if (ttm_rev and ttm_rev != 0 and not np.isnan(ttm_ni)) else np.nan
        ttm_price   = float(hist["Close"].iloc[-1]) if not hist.empty else np.nan

        # TTM dividends: last 12 months
        try:
            one_yr_ago = pd.Timestamp.today() - pd.Timedelta(days=365)
            ttm_div_ps = float(divs[divs.index >= one_yr_ago].sum())
        except Exception:
            ttm_div_ps = np.nan

        ttm_dy      = (ttm_div_ps / ttm_price) if (ttm_price and ttm_price > 0 and not np.isnan(ttm_div_ps)) else np.nan
        ttm_pe      = (ttm_price / ttm_eps)    if (ttm_eps   and abs(ttm_eps)   > 0 and not np.isnan(ttm_price)) else np.nan
        ttm_pb      = (ttm_price / ttm_bps)    if (ttm_bps   and ttm_bps   > 0 and not np.isnan(ttm_price)) else np.nan
        ttm_rev_ps  = (ttm_rev * 1e6 / (ttm_sh * 1e6)) if (ttm_sh and ttm_sh > 0 and not np.isnan(ttm_rev)) else np.nan
        ttm_ps      = (ttm_price / ttm_rev_ps) if (ttm_rev_ps and ttm_rev_ps > 0 and not np.isnan(ttm_price)) else np.nan
        ttm_fcf_ps  = (ttm_fcf * 1e6 / (ttm_sh * 1e6)) if (ttm_sh and ttm_sh > 0 and not np.isnan(ttm_fcf)) else np.nan
        ttm_pfcf    = (ttm_price / ttm_fcf_ps) if (ttm_fcf_ps and ttm_fcf_ps > 0 and not np.isnan(ttm_price)) else np.nan
        ttm_roe     = (ttm_ni / ttm_eq * 100)        if (ttm_eq and ttm_eq > 0 and not np.isnan(ttm_ni)) else np.nan
        ttm_inv     = ttm_eq + (ttm_ltd if not np.isnan(ttm_ltd) else 0.0)
        ttm_roic    = (ttm_ni / ttm_inv * 100)       if (ttm_inv and ttm_inv > 0 and not np.isnan(ttm_ni)) else np.nan

        rows["TTM"] = {
            "Revenue [M]":            ttm_rev,
            "Net Income [M]":         ttm_ni,
            "Total Equity [M]":       ttm_eq,
            "FCF [M]":                ttm_fcf,
            "Long term debt [M]":     ttm_ltd,
            "Shares Outstanding [M]": ttm_sh,
            "Dividend per share":     ttm_div_ps,
            "Dividend Yield":         ttm_dy,
            "EPS $":                  ttm_eps,
            "BPS $":                  ttm_bps,
            "Profit Margin":          ttm_profit_margin,
            "Stock Price":            ttm_price,
            "P/E":                    ttm_pe,
            "P/B":                    ttm_pb,
            "P/S":                    ttm_ps,
            "P/FCF":                  ttm_pfcf,
            "ROE":                    ttm_roe,
            "ROIC":                   ttm_roic,
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
        "ROIC", "Equity CAGR", "BPS CAGR", "EPS CAGR",
        "Revenue CAGR", "FCF CAGR", "ROE",
        "Dividend growth rate", "Dividend payout ratio", "P/E", "Profit Margin",
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
    roic = _series("ROIC")
    div  = _series("Dividend per share")
    pe   = _series("P/E")
    pm   = _series("Profit Margin")

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
        results[h_label]["EPS CAGR"]           = _cagr(abs(_get(eps, start_idx)), abs(_get(eps, end_idx)), actual_n)
        results[h_label]["BPS CAGR"]           = _cagr(_get(bps,  start_idx), _get(bps,  end_idx), actual_n)
        results[h_label]["FCF CAGR"]           = _cagr(_get(fcf,  start_idx), _get(fcf,  end_idx), actual_n)
        results[h_label]["Dividend growth rate"] = _cagr(_get(div, start_idx), _get(div, end_idx), actual_n)

        # averages over the window (for "1 rok" use TTM as the latest available value)
        if n == 1:
            results[h_label]["ROIC"]  = _ttm("ROIC")
            results[h_label]["ROE"]   = _ttm("ROE")
            results[h_label]["Dividend payout ratio"] = (
                (_ttm("Dividend per share") / _ttm("EPS $"))
                if not np.isnan(_ttm("EPS $")) and _ttm("EPS $") > 0 and not np.isnan(_ttm("Dividend per share"))
                else np.nan
            )
            results[h_label]["P/E"]   = _ttm("P/E")
            results[h_label]["Profit Margin"] = _ttm("Profit Margin")
        else:
            window_idx  = [y for y in sorted_years if start_idx <= y <= end_idx]
            results[h_label]["ROIC"]  = _mean_valid([_get(roic, y) for y in window_idx])
            results[h_label]["ROE"]   = _mean_valid([_get(roe,  y) for y in window_idx])
            results[h_label]["Dividend payout ratio"] = _mean_valid([_get(dpr, y) for y in window_idx])
            results[h_label]["P/E"]   = _mean_valid([_get(pe,   y) for y in window_idx])
            results[h_label]["Profit Margin"] = _mean_valid([_get(pm, y) for y in window_idx])

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
        if col in ("ROE", "ROIC", "Profit Margin"):
            return f"{v:.2f}%"
        if col in ("P/E", "P/B", "P/S", "P/FCF"):
            return f"{v:.1f}×"
        if col in ("Revenue [M]", "Net Income [M]", "Total Equity [M]", "FCF [M]",
                   "Long term debt [M]", "Shares Outstanding [M]"):
            return f"{v:,.0f}"
        if col in ("EPS $", "BPS $", "Dividend per share", "Stock Price"):
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
    """Style the metrics DataFrame with % formatting for CAGRs/ROE/ROIC etc."""

    # percent rows
    pct_rows = {"Equity CAGR", "BPS CAGR", "EPS CAGR",
                "Revenue CAGR", "FCF CAGR", "Dividend growth rate",
                "Dividend payout ratio"}
    pct_plain_rows = {"ROE", "ROIC"}

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
                "MOS": d.get("mos", np.nan),
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
    scenario_inputs_df: pd.DataFrame,
    scenario_outputs_df: pd.DataFrame,
    roe_params: dict,
    roe_proj: dict,
    roe_sc_labels: list,
    current_price_roe: float = np.nan,
) -> bytes:
    """Combined export: Valuace + Budoucí vývoj + ROE model in one workbook."""
    buf = BytesIO()
    _param_keys = ["roe_1_3", "roe_4_5", "roe_6_10", "dg_1_3", "dg_4_5", "dg_6_10", "tax", "r", "pe", "ttm_cf"]
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        # ── Valuace ──────────────────────────────────────────────────
        effective_df.to_excel(writer, sheet_name="Inputs_effective")
        if not manual_df.empty:
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

        # ── Budoucí vývoj – 3 scénáře ────────────────────────────────
        if scenario_inputs_df is not None and not scenario_inputs_df.empty:
            scenario_inputs_df.to_excel(writer, sheet_name="Scenario_inputs", index=False)
        if scenario_outputs_df is not None and not scenario_outputs_df.empty:
            scenario_outputs_df.to_excel(writer, sheet_name="Scenario_outputs", index=False)

        # ── ROE model ────────────────────────────────────────────────
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
                "MOS": d.get("mos", np.nan),
            })
        pd.DataFrame(_out_rows).to_excel(writer, sheet_name="ROE_outputs", index=False)

        for sn in roe_sc_labels:
            rows = roe_proj.get(sn, {}).get("rows", [])
            if rows:
                pd.DataFrame(rows).to_excel(writer, sheet_name=f"ROE_proj_{sn}", index=False)

        # ── Meta ─────────────────────────────────────────────────────
        pd.DataFrame([{
            "ticker": ticker,
            "years": years,
            "current_price": current_price,
            "current_price_roe": current_price_roe,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "format_version": 1,
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
                                "override": bool(_row.get("override", False)),
                                "fcf_ovr": float(_row.get("fcf_ovr", 0.0)),
                            }
                    if _new_sc:
                        st.session_state["scenarios"] = _new_sc
                    _tax_imp = _si["tax_rate"].iloc[0] if "tax_rate" in _si.columns else None
                    if _tax_imp is not None and not pd.isna(_tax_imp):
                        st.session_state["sc_tax_rate_pct"] = float(_tax_imp)
                st.success(f"Importováno: **{_up_file.name}** (ticker: {_imp_ticker})")
                st.rerun()
            except Exception as _exc:
                st.error(f"Import selhal: {_exc}")

# ── Controls ──────────────────────────────────────────────────────────────────

v_c1, v_c2, v_c3 = st.columns([3, 2, 2])
with v_c1:
    val_ticker_input = st.text_input(
        "Ticker (Valuace)",
        value=st.session_state.val_ticker,
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

# ── Reload from API + ticker/years change detection ───────────────────────────

ticker_changed = val_ticker_input != st.session_state.val_ticker
years_changed  = val_years_input  != st.session_state.val_years

if val_analyze_btn or ticker_changed or years_changed:
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

# ── Main Valuace UI ───────────────────────────────────────────────────────────

if not st.session_state.val_loaded or st.session_state.val_api_df.empty:
    st.info("Zadej ticker a klikni **Analyzovat**.")
else:
    api_df    = st.session_state.val_api_df
    manual_df = st.session_state.val_manual_df

    effective_df, override_mask = merge_api_and_manual(api_df, manual_df)

    # ── Upper table: st.data_editor ──────────────────────────────────────
    st.markdown("**Tabulka valuace (editovatelná):**")
    st.markdown(
        """
        <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:2px 0 8px 0;font-size:12px;color:#93a3b8;">
            <span style="font-weight:600;">Legenda vstupů:</span>
            <span style="display:inline-flex;align-items:center;gap:6px;">🟡 P/E fair value</span>
            <span style="display:inline-flex;align-items:center;gap:6px;">🔵 DCF fair value</span>
            <span style="display:inline-flex;align-items:center;gap:6px;">🟣 ROE model Dan Gladiš</span>
            <span style="display:inline-flex;align-items:center;gap:6px;">🟢 Všechny modely</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Always feed api_df as the editor base — the data_editor key persists user edits.
    # Feeding effective_df would reset the editor state every rerun and cause flicker.
    editor_init = api_df.reset_index()  # 'Year' becomes a column

    _editor_height = (len(editor_init) + 1) * 35 + 4

    edited_raw = st.data_editor(
        editor_init,
        width="stretch",
        num_rows="fixed",
        hide_index=True,
        height=_editor_height,
        column_config={
            "Year":                    st.column_config.TextColumn("Year",    disabled=True),
            "Revenue [M]":             st.column_config.NumberColumn("Revenue [M] 🟡🔵",             format="%.0f", help="Použito v: P/E fair value, DCF fair value"),
            "Net Income [M]":          st.column_config.NumberColumn("Net Income [M]",          format="%.0f"),
            "Total Equity [M]":        st.column_config.NumberColumn("Total Equity [M]",        format="%.0f"),
            "FCF [M]":                 st.column_config.NumberColumn("FCF [M]",                 format="%.0f"),
            "Long term debt [M]":      st.column_config.NumberColumn("Long term debt [M]",      format="%.0f"),
            "Shares Outstanding [M]":  st.column_config.NumberColumn("Shares Outstanding [M] 🟡🔵",  format="%.2f", help="Použito v: P/E fair value, DCF fair value"),
            "Dividend per share":      st.column_config.NumberColumn("Dividend per share 🟣",      format="%.4f", help="Použito v: ROE model Dan Gladiš"),
            "Dividend Yield":          st.column_config.NumberColumn("Dividend Yield",          format="%.4f"),
            "EPS $":                   st.column_config.NumberColumn("EPS $ 🟣",                   format="%.2f", help="Použito v: ROE model Dan Gladiš"),
            "BPS $":                   st.column_config.NumberColumn("BPS $ 🟣",                   format="%.2f", help="Použito v: ROE model Dan Gladiš"),
            "Profit Margin":           st.column_config.NumberColumn("Profit Margin",           format="%.2f%%"),
            "Stock Price":             st.column_config.NumberColumn("Stock Price 🟢",             format="%.2f", help="Použito ve všech modelech budoucího vývoje akcie"),
            "P/E":                     st.column_config.NumberColumn("P/E",                     format="%.1f"),
            "P/B":                     st.column_config.NumberColumn("P/B",                     format="%.1f"),
            "P/S":                     st.column_config.NumberColumn("P/S",                     format="%.1f"),
            "P/FCF":                   st.column_config.NumberColumn("P/FCF",                   format="%.1f"),
            "ROE":                     st.column_config.NumberColumn("ROE 🟣",                     format="%.2f%%", help="Použito v: ROE model Dan Gladiš"),
            "ROIC":                    st.column_config.NumberColumn("ROIC",                    format="%.2f%%"),
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

                var targetCell = colId
                    ? nextRowEl.querySelector('[col-id="' + colId + '"]')
                    : null;

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
            # if edited differs from API (accounting for both NaN)
            if not (np.isnan(ev) and np.isnan(av)) and ev != av:
                new_manual.loc[idx, col] = ev

    st.session_state.val_manual_df = new_manual
    effective_df, override_mask = merge_api_and_manual(api_df, new_manual)

    # ── Effective view with override highlighting ─────────────────────────
    n_overrides = int(override_mask.sum().sum())
    if n_overrides > 0:
        with st.expander(f"📋 Effective view – {n_overrides} přepsaná {'buňka' if n_overrides == 1 else 'buňky'} (zvýrazněno)", expanded=True):
            st.markdown(
                style_effective_df(effective_df, override_mask).to_html(),
                unsafe_allow_html=True,
            )
    else:
        with st.expander("📋 Effective view (žádné přepsané buňky)", expanded=False):
            st.markdown(
                style_effective_df(effective_df, override_mask).to_html(),
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

    # ══════════════════════════════════════════════════════════════════
    # BUDOUCÍ VÝVOJ AKCIE - 3 SCÉNÁŘE
    # ══════════════════════════════════════════════════════════════════
    st.divider()
    st.markdown("### Budoucí vývoj akcie - 3 scénáře")
    st.markdown(
        """
        <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:2px 0 10px 0;font-size:12px;color:#93a3b8;">
          <span style="font-weight:600;">Legenda výpočtů:</span>
          <span>🟡 P/E fair value</span>
          <span>🔵 DCF fair value</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── local helper functions ────────────────────────────────────────

    def _tooltip_attr(text):
        return html.escape(text, quote=True).replace("\n", "&#10;")

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

    _d_roic_pct = _sc_get_ttm("ROIC", np.nan)
    if np.isnan(_d_roic_pct):
        _cols_available = [c for c in metrics_df.columns] if not metrics_df.empty else []
        _roic_vals = [_safe_float(metrics_df.loc["ROIC", c]) for c in _cols_available
                      if not metrics_df.empty and "ROIC" in metrics_df.index]
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
    if not np.isnan(_d_ni) and not np.isnan(_d_rev) and _d_rev > 0:
        _d_op_pct = (_d_ni / _d_rev) * 100.0
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
        "op": "Použito v P/E i DCF jako provozní / profit marže. V P/E přibližuje ziskovost po zdanění, v DCF vstupuje do implied FCF margin. Nastavuj normalizovanou marži, ne nejlepší rok v cyklu.",
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

    _roic_vals  = _sc_float_row("ROIC (%)",                    "roic", 0.1,  200.0, 0.5, help_text=_SC_HELP["roic"], badges=["DCF"])
    _g_vals     = _sc_float_row("Revenue Growth g (%)",        "g",    0.0,  100.0, 0.5, help_text=_SC_HELP["g"],    badges=["PE", "DCF"])
    _op_vals    = _sc_float_row("Operating/Profit margin (%)", "op",   0.0,  100.0, 0.5, help_text=_SC_HELP["op"],   badges=["PE", "DCF"])
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

        _out_metrics = ["P/E Fair Value ($)", "DCF Fair Value ($)", "CAGR via P/E exit", "Total return CAGR (price + dividends)", "Current price"]
        _OUT_HELP = {
            "P/E Fair Value ($)": (
                "Jak se počítá: Revenue_0 × (1+g)^n × op_margin × (1−tax) × Exit P/E ÷ Shares, diskontováno zpět rázem 1/(1+r)^n.\n"
                "Co vyjadřuje: Současnou hodnotu akcie za předpokladu, že trh ocení firmu zvolenou P/E násobkem po n letech.\n"
                "Kdy použít: Vhodné pro získové firmy s relativně predikovatelnou marží. Méně vhodné pro firmy s nulovým nebo nestabilním ziskem."
            ),
            "DCF Fair Value ($)": (
                "Jak se počítá: PV diskontovaných FCF_t (t=1..n) + PV terminální hodnoty (Exit P/FCF nebo Gordon), vše děleno počtem akcií.\n"
                "FCF_t = Revenue_0 × (1+g)^t × FCF_margin.\n"
                "Co vyjadřuje: Vnitřní hodnotu akcie na základě skutečně generovaných volných peněžních toků, nezávislo na účetních zisích.\n"
                "Kdy použít: Základní metrika pro ocenění. Preferuj ji pro firmy s predikovatelným FCF. Citlivá na FCF margin a terminální hodnotu."
            ),
            "CAGR via P/E exit": (
                "Jak se počítá: (Price_n / P_0)^(1/n) − 1, kde Price_n = cena akcie v roce n odvozená z P/E fair value (bez diskontování).\n"
                "Co vyjadřuje: Roční výnos z kursovního růstu, pokud koupíš za současnou cenu a firma dospěje k P/E ocenění.\n"
                "Kdy použít: Porovnej s požadovaným výnosem r. Pokud CAGR > r, akcie je potenciálně levná. Ignoruje dividendy – viz Total return CAGR."
            ),
            "Total return CAGR (price + dividends)": (
                "Jak se počítá: (Price_n + kumulativní DPS po dani) / (P_0)^(1/n) − 1.\n"
                "Dividendy: DPS_t = DPS_0 × (1+dg)^t × (1−div_tax), sčítány za všech n let.\n"
                "Co vyjadřuje: Skutečný celkový roční výnos investora včetně dividend. Důležité zejména u dividendových akcí.\n"
                "Kdy použít: Primární metrika pro posouzení, zda se investice vyplatí. Vždy srovnej s Alternativním výnosem (dluhopisy, index)."
            ),
            "Current price": (
                "Jak se počítá: Bere se aktuální tržní cena akcie P_0 (TTM Stock Price) použitá ve výpočtu CAGR.\n"
                "Co vyjadřuje: Vstupní kupní cenu investora, vůči které se porovnává Price_n i Price_n + dividendy.\n"
                "Kdy použít: Pro kontrolu, z jaké přesné ceny jsou spočítané metriky CAGR via P/E exit a Total return CAGR."
            ),
        }
        _sc_outputs = {}  # capture for FULL snapshot
        _out_lbl, _out_lo, _out_mi, _out_hi = st.columns([2.5, 2, 2, 2])
        with _out_lbl:
            st.markdown("<div style='font-size:16px;font-weight:700'>Metric</div>", unsafe_allow_html=True)
            for _m in _out_metrics:
                _tip = _tooltip_attr(_OUT_HELP.get(_m, ""))
                _w = "400" if _m == "Current price" else "700"
                st.markdown(
                    f"<div style='padding:4px 0;font-size:16px;font-weight:{_w}'>{html.escape(_m)}"
                    f" <span title=\"{_tip}\" style='cursor:help;color:#93a3b8;border-bottom:1px dotted #93a3b8;font-size:11px;'>ⓘ</span></div>",
                    unsafe_allow_html=True,
                )

        if _dps_warn:
            st.caption("⚠️ Dividend per share not found – dividends set to $0 (Total return CAGR ≈ Price CAGR)")

        for _cw, _sn in zip([_out_lo, _out_mi, _out_hi], _SC_LABELS):
            with _cw:
                _col = _SC_COLORS[_sn]
                st.markdown(
                    f"<div style='font-size:16px;font-weight:700;color:{_col}'>{_sn}</div>",
                    unsafe_allow_html=True,
                )

                _g_d   = _sc[_sn]["g"]    / 100.0
                _op_d  = _sc[_sn]["op"]   / 100.0
                _r_d   = _sc[_sn]["r"]    / 100.0
                _pe    = float(_sc[_sn]["pe"])
                _pfcf  = float(_sc[_sn]["pfcf"])
                _n     = int(_sc[_sn]["n"])
                _fcm   = _effective_fcf_dec[_sn]
                _tax_d = _tax_pct / 100.0

                _rev0 = _d_rev0
                _sh   = _d_shares
                _p0   = _d_price

                # ── 1) P/E Fair Value ──
                _fv_pe     = np.nan
                _price_n_pe = np.nan
                try:
                    if not (np.isnan(_rev0) or np.isnan(_sh) or _sh <= 0 or _n <= 0):
                        _rev_n    = _rev0 * (1.0 + _g_d) ** _n
                        _nopat_m  = _op_d * (1.0 - _tax_d)
                        _ni_n     = _rev_n * _nopat_m
                        _eq_n     = _ni_n * _pe
                        _price_n_pe = _eq_n / _sh
                        _fv_pe    = _price_n_pe / (1.0 + _r_d) ** _n
                except Exception:
                    pass

                if not np.isnan(_fv_pe):
                    st.markdown(
                        f"<div style='padding:4px 0;font-size:16px;font-weight:700'>${_fv_pe:,.2f}</div>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        "<div style='padding:4px 0;font-size:16px;font-weight:700;color:#93a3b8'>N/A</div>",
                        unsafe_allow_html=True,
                    )

                # ── 2) DCF Fair Value ──
                _fv_dcf = np.nan
                try:
                    if not (np.isnan(_rev0) or np.isnan(_sh) or _sh <= 0
                            or np.isnan(_fcm) or _n <= 0):
                        _pv_sum = 0.0
                        for _t in range(1, _n + 1):
                            _fcf_t = _rev0 * (1.0 + _g_d) ** _t * _fcm
                            _pv_sum += _fcf_t / (1.0 + _r_d) ** _t
                        _fcf_n  = _rev0 * (1.0 + _g_d) ** _n * _fcm
                        if _terminal_mode == "Perpetual growth (Gordon)":
                            _g_term_d = _g_terminal_pct / 100.0
                            if _r_d <= _g_term_d:
                                st.warning("r ≤ g_terminal → Gordon TV undefined")
                                _term_pv = np.nan
                            else:
                                _fcf_n1  = _fcf_n * (1.0 + _g_term_d)
                                _tv_n    = _fcf_n1 / (_r_d - _g_term_d)
                                _term_pv = _tv_n / (1.0 + _r_d) ** _n
                        else:
                            _term_pv = (_fcf_n * _pfcf) / (1.0 + _r_d) ** _n
                        if not np.isnan(_term_pv):
                            _fv_dcf = (_pv_sum + _term_pv) / _sh
                except Exception:
                    pass

                if not np.isnan(_fv_dcf):
                    st.markdown(
                        f"<div style='padding:4px 0;font-size:16px;font-weight:700'>${_fv_dcf:,.2f}</div>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        "<div style='padding:4px 0;font-size:16px;font-weight:700;color:#93a3b8'>N/A</div>",
                        unsafe_allow_html=True,
                    )

                # ── 3) CAGR @ current price (P/E exit) ──
                _cagr_pe = np.nan
                try:
                    if not (np.isnan(_p0) or _p0 <= 0
                            or np.isnan(_price_n_pe) or _price_n_pe <= 0 or _n <= 0):
                        _cagr_pe = (_price_n_pe / _p0) ** (1.0 / _n) - 1.0
                except Exception:
                    pass

                # ── 4) Total return CAGR (price + after-tax dividends) ──
                _dg_d_sc   = _sc[_sn].get("dg", 0.0) / 100.0
                _div_tax_d = _div_tax_pct / 100.0
                _cum_div   = 0.0
                for _t in range(1, _n + 1):
                    _cum_div += _dps_0 * (1.0 + _dg_d_sc) ** _t * (1.0 - _div_tax_d)
                _cagr_total = np.nan
                try:
                    if not (np.isnan(_p0) or _p0 <= 0
                            or np.isnan(_price_n_pe) or _price_n_pe <= 0 or _n <= 0):
                        _tr = (_price_n_pe + _cum_div) / _p0
                        _cagr_total = _tr ** (1.0 / _n) - 1.0
                except Exception:
                    pass

                # ── capture for snapshot ──
                _sc_outputs[_sn] = {
                    "scenario": _sn,
                    "pe_fair_value": _fv_pe,
                    "dcf_fair_value": _fv_dcf,
                    "cagr_via_pe_exit": _cagr_pe,
                    "cagr_total_return": _cagr_total,
                    "cum_div_after_tax": _cum_div,
                }

                if not np.isnan(_cagr_pe):
                    st.markdown(
                        f"<div style='padding:4px 0;font-size:16px;font-weight:700'>{_cagr_pe:.1%}</div>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        "<div style='padding:4px 0;font-size:16px;font-weight:700;color:#93a3b8'>N/A</div>",
                        unsafe_allow_html=True,
                    )

                if not np.isnan(_cagr_total):
                    st.markdown(
                        f"<div style='padding:4px 0;font-size:16px;font-weight:700'>{_cagr_total:.1%}</div>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        "<div style='padding:4px 0;font-size:16px;font-weight:700;color:#93a3b8'>N/A</div>",
                        unsafe_allow_html=True,
                    )

                if not np.isnan(_p0):
                    st.markdown(
                        f"<div style='padding:4px 0;font-size:16px;font-weight:400'>${_p0:,.2f}</div>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        "<div style='padding:4px 0;font-size:16px;font-weight:400;color:#93a3b8'>N/A</div>",
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

        # Anchor forecast at TTM actual price
        if not np.isnan(_d_price):
            _fore_pe_rows.append( {"Year": "TTM", "Scenario": _sn, "Value": _d_price})
            _fore_dcf_rows.append({"Year": "TTM", "Scenario": _sn, "Value": _d_price})

        _pv_sum2 = 0.0
        for _t in range(1, _n2 + 1):
            try:
                _rev_t2     = _d_rev0 * (1.0 + _g_d2) ** _t
                _price_t_pe = _rev_t2 * _op_d2 * (1.0 - _tax_d2) * _pe2 / _d_shares
                _fore_pe_rows.append({"Year": str(_forecast_base_year + _t), "Scenario": _sn, "Value": _price_t_pe})
            except Exception:
                pass
            try:
                if not np.isnan(_fcm2):
                    _fcf_t2   = _d_rev0 * (1.0 + _g_d2) ** _t * _fcm2
                    _pv_sum2 += _fcf_t2 / (1.0 + _r_d2) ** _t
                    _term_pv2 = (_fcf_t2 * _pfcf2) / (1.0 + _r_d2) ** _t
                    _dcf_fv_t = (_pv_sum2 + _term_pv2) / _d_shares
                    _fore_dcf_rows.append({"Year": str(_forecast_base_year + _t), "Scenario": _sn, "Value": _dcf_fv_t})
            except Exception:
                pass

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
    _fore_yr_strs_ch = ["TTM"] + [str(_forecast_base_year + _t) for _t in range(1, _max_n_ch + 1)]
    _all_yr_order_ch = _hist_yr_strs_ch + _fore_yr_strs_ch

    _hist_price_cdf = pd.DataFrame(_hist_price_rows) if _hist_price_rows else pd.DataFrame()

    if not _hist_price_cdf.empty or _fore_pe_rows or _fore_dcf_rows:
        _x_enc_ch = alt.X("Year:N", sort=_all_yr_order_ch, title="Rok")

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
        if not _hist_price_cdf.empty:
            _dcf_layers.append(_sc_hist_layer("Cena / DCF FV ($)"))
        if _fore_dcf_rows:
            _fore_dcf_cdf = pd.DataFrame(_fore_dcf_rows)
            _dcf_layers.append(
                alt.Chart(_fore_dcf_cdf).mark_line(strokeWidth=2, strokeDash=[4, 2], point=True).encode(
                    x=_x_enc_ch,
                    y=alt.Y("Value:Q"),
                    color=alt.Color("Scenario:N", scale=_sc_cscale_ch),
                    tooltip=["Year", "Scenario", alt.Tooltip("Value:Q", format=".2f", title="DCF FV $")],
                )
            )
        if _dcf_layers:
            st.altair_chart(
                alt.layer(*_dcf_layers)
                .properties(title="DCF Fair Value — Historická cena + Projekce", height=300)
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
        _full_fname = f"{st.session_state.val_ticker}_{datetime.now().strftime('%y_%m_%d')}.xlsx"
        _full_col1, _full_col2 = st.columns([1, 3])
        with _full_col1:
            st.download_button(
                "💾 Uložit analýzu",
                data=_full_bytes,
                file_name=_full_fname,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="snap_full_save_btn",
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

    with st.expander("📐 Equations – Budoucí vývoj akcie (click to expand)"):
        st.markdown(r"""
**Scenario Outputs (per share)**

$$
\text{P/E Fair Value} = \frac{\text{Price}_n^{PE}}{(1+r)^n}
\qquad
\text{Price}_n^{PE} = \frac{\text{Revenue}_n \times \text{NOPAT margin} \times P/E}{\text{Shares}}
$$

$$
\text{DCF Fair Value} = \frac{PV_{\text{FCF}} + PV_{\text{terminal}}}{\text{Shares}}
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

*Valid only when $r > g_{\text{terminal}}$; otherwise DCF Fair Value = N/A.*

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

**DCF fair value today** (detail):

$$
PV_{\text{FCF}} = \sum_{t=1}^{n} \frac{\text{Revenue}_0 \cdot (1+g)^t \cdot \text{FCF margin}}{(1+r)^t}
$$

$$
\text{FairValue}_{DCF} = \frac{PV_{\text{FCF}} + PV_{\text{terminal}}}{\text{Shares}}
$$

---

*All rates are decimals inside calculations (e.g. r = 0.10 for 10 %, dg = 0.05 for 5 %).
Revenue₀ = TTM Revenue [M] × 1 000 000.*
        """)

    # ══════════════════════════════════════════════════════════════════
    # ROE MODEL DAN GLADIŠ
    # ══════════════════════════════════════════════════════════════════
    st.divider()
    st.markdown("### ROE model Dan Gladiš")
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

    _ROE_SC_LABELS = ["Nominal", "Worst", "Best"]
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

    _r0_raw = _rttm("ROE")
    _r0     = _r0_raw if not np.isnan(_r0_raw) else 15.0

    # Historical dividend CAGR for default dg
    _hist_dg_def = 0.05
    try:
        _dps_s2 = roe_effective_df["DPS"].dropna()
        _dps_s2 = _dps_s2[_dps_s2 > 0]
        if len(_dps_s2) >= 2:
            _n_d2 = len(_dps_s2) - 1
            _hist_dg_def = float(np.clip(
                (_dps_s2.iloc[-1] / _dps_s2.iloc[0]) ** (1.0 / _n_d2) - 1.0, -0.5, 1.0
            ))
    except Exception:
        pass

    def _rdft(sn, key):
        """Default value for a scenario/key. All periods start equal (user unlocks to diverge)."""
        sc_def = {
            "Nominal": dict(
                roe_1_3=round(_r0, 2), roe_4_5=round(_r0, 2), roe_6_10=round(_r0, 2),
                dg_1_3=round(_hist_dg_def * 100, 2), dg_4_5=round(_hist_dg_def * 100, 2), dg_6_10=round(_hist_dg_def * 100, 2),
                pe=15.0, tax=15.0, r=12.0, ttm_cf=_auto_ttm_cf,
            ),
            "Worst": dict(
                roe_1_3=round(_r0 * 0.70, 2), roe_4_5=round(_r0 * 0.70, 2), roe_6_10=round(_r0 * 0.70, 2),
                dg_1_3=round(max(0.0, _hist_dg_def * 100 * 0.5), 2), dg_4_5=round(max(0.0, _hist_dg_def * 100 * 0.5), 2),
                dg_6_10=round(max(0.0, _hist_dg_def * 100 * 0.5), 2),
                pe=12.0, tax=15.0, r=12.0, ttm_cf=_auto_ttm_cf,
            ),
            "Best": dict(
                roe_1_3=round(min(_r0 * 1.15, 200.0), 2), roe_4_5=round(min(_r0 * 1.15, 200.0), 2),
                roe_6_10=round(min(_r0 * 1.15, 200.0), 2),
                dg_1_3=round(min(_hist_dg_def * 100 * 1.3, 100.0), 2), dg_4_5=round(min(_hist_dg_def * 100 * 1.3, 100.0), 2),
                dg_6_10=round(min(_hist_dg_def * 100 * 1.3, 100.0), 2),
                pe=20.0, tax=15.0, r=12.0, ttm_cf=_auto_ttm_cf,
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
        """10-year piecewise ROE projection; returns (rows, iv, pv_div, pv_term).
        Expects roe_*, dg_*, tax, r stored in % (e.g. 15.0 for 15%)."""
        rows = []
        bps_p, eps_p, dps_p = bps0, eps0, dps0
        pv_div = 0.0
        r_d   = params["r"]   / 100.0
        tax_d = params["tax"] / 100.0
        cf    = float(np.clip(_safe_float(params.get("ttm_cf", 0.5)), 0.0, 1.0))
        for t in range(1, 11):
            if   t <= 3: roe_t = params["roe_1_3"]  / 100.0; gt = params["dg_1_3"]  / 100.0
            elif t <= 5: roe_t = params["roe_4_5"]  / 100.0; gt = params["dg_4_5"]  / 100.0
            else:        roe_t = params["roe_6_10"] / 100.0; gt = params["dg_6_10"] / 100.0

            dps_t = dps_p * (1.0 + gt)
            bps_t = bps_p + eps_p - dps_p
            eps_model_t = bps_t * roe_t
            eps_t = (eps_p * (1.0 - cf) + eps_model_t * cf) if t == 1 else eps_model_t
            pout  = (dps_t / eps_t) if eps_t > 0 else np.nan
            pv_div += dps_t * (1.0 - tax_d) / (1.0 + r_d) ** t
            rows.append({"t": t, "ROE": roe_t, "EPS": eps_t, "DPS": dps_t, "BPS": bps_t, "Payout": pout})
            bps_p, eps_p, dps_p = bps_t, eps_t, dps_t

        price_10  = rows[-1]["EPS"] * params["pe"]
        pv_term   = price_10 / (1.0 + r_d) ** 10
        iv        = pv_div + pv_term
        return rows, iv, pv_div, pv_term

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
            _rows, _iv, _pvd, _pvt = _compute_roe_proj(_bps0_v, _eps0_v, _dps0_v, _roe_p[_sn])
            _mos_v = (_iv / _cur_price_roe - 1.0) if (not np.isnan(_cur_price_roe) and _cur_price_roe > 0) else np.nan
            _roe_proj[_sn] = {"rows": _rows, "iv": _iv, "pv_div": _pvd, "pv_term": _pvt, "mos": _mos_v}
        except Exception as _exc_roe:
            _roe_proj[_sn] = {"rows": [], "iv": np.nan, "pv_div": np.nan, "pv_term": np.nan, "mos": np.nan, "error": str(_exc_roe)}

    # ══════════════════════════════════════════════════════════════════
    # OUTPUTS
    # ══════════════════════════════════════════════════════════════════
    st.divider()
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
        _ro_lbl, _ro_n, _ro_w, _ro_b = st.columns([3, 2, 2, 2])
        with _ro_lbl:
            st.markdown("<div style='font-size:15px;font-weight:700'>Výsledky</div>", unsafe_allow_html=True)
        for _cw, _sn in zip([_ro_n, _ro_w, _ro_b], _ROE_SC_LABELS):
            with _cw:
                st.markdown(
                    f"<div style='font-size:15px;font-weight:700;color:{_ROE_SC_COLORS[_sn]}'>{_sn}</div>",
                    unsafe_allow_html=True,
                )

        _out_defs_roe = [
            ("Total present value (terminal + dividends) ($)", "iv"),
            ("MOS (%)",             "mos"),
            ("PV zdaněných dividend ($)",    "pv_div"),
            ("PV terminální ($)",   "pv_term"),
        ]
        with _ro_lbl:
            for _ml, _ in _out_defs_roe:
                _out_title = _tooltip_attr(_ROE_OUT_HELP.get(_ml, ""))
                _label_w = "400" if _ml in ["PV zdaněných dividend ($)", "PV terminální ($)"] else "600"
                st.markdown(
                    f"<div style='padding:4px 0;font-size:14px;font-weight:{_label_w}'>{_ml} <span title='{_out_title}' style='cursor:help;color:#93a3b8;font-weight:700'>ⓘ</span></div>",
                    unsafe_allow_html=True,
                )

        for _cw, _sn in zip([_ro_n, _ro_w, _ro_b], _ROE_SC_LABELS):
            with _cw:
                _d = _roe_proj.get(_sn, {})
                if _d.get("error"):
                    st.caption(f"⚠️ Chyba: {_d['error']}")
                    continue
                for _, _key in _out_defs_roe:
                    _v = _d.get(_key, np.nan)
                    if _key == "mos":
                        if not np.isnan(_v):
                            _mc = "#66BB6A" if _v >= 0 else "#FF7043"
                            st.markdown(
                                f"<div style='padding:4px 0;font-size:14px;font-weight:700;color:{_mc}'>{_v:.1%}</div>",
                                unsafe_allow_html=True,
                            )
                        else:
                            st.markdown("<div style='padding:4px 0;font-size:14px;color:#93a3b8'>N/A</div>", unsafe_allow_html=True)
                    elif not np.isnan(_v):
                        _val_w = "400" if _key in ["pv_div", "pv_term"] else "700"
                        st.markdown(
                            f"<div style='padding:4px 0;font-size:14px;font-weight:{_val_w}'>${_v:,.2f}</div>",
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown("<div style='padding:4px 0;font-size:14px;color:#93a3b8'>N/A</div>", unsafe_allow_html=True)

        if not np.isnan(_cur_price_roe):
            st.caption(f"Current price (TTM): **${_cur_price_roe:.2f}**")

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
    ]

    _chart_fore_rows = []
    for _sn in _ROE_SC_LABELS:
        _pd2 = _roe_proj.get(_sn, {})
        if not _pd2.get("rows"):
            continue
        _chart_fore_rows.append({"Year": "TTM", "Scenario": _sn, "EPS": _eps0_v, "ROE": _roe_chart_decimal(_roe0_v)})
        for _rw in _pd2["rows"]:
            _chart_fore_rows.append({"Year": str(_forecast_base_year_roe + int(_rw["t"])), "Scenario": _sn,
                                      "EPS": _rw["EPS"], "ROE": _rw["ROE"]})

    _hist_yr_strs = [str(y) for y in _hist_yrs_sorted]
    _fore_yr_strs = ["TTM"] + [str(_forecast_base_year_roe + t) for t in range(1, 11)]
    _all_yr_order = [y for y in _hist_yr_strs if y != "TTM"] + _fore_yr_strs

    _hist_cdf = pd.DataFrame(_chart_hist_rows)
    _fore_cdf = pd.DataFrame(_chart_fore_rows) if _chart_fore_rows else pd.DataFrame()

    _sc_domain = ["Historická"] + _ROE_SC_LABELS
    _sc_range2 = ["#4f8ef7", "#FFD54F", "#FF7043", "#66BB6A"]
    _sc_cscale = alt.Scale(domain=_sc_domain, range=_sc_range2)

    if not _hist_cdf.empty:
        _x_enc_roe = alt.X("Year:N", sort=_all_yr_order, title="Rok")

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

    with st.expander("📐 Equations – ROE model (click to expand)"):
        st.markdown(r"""
**Projekce EPS, DPS, BPS** (piecewise, roky 1–3 / 4–5 / 6–10):

$$
BPS_t = BPS_{t-1} + EPS_{t-1} - DPS_{t-1}
$$

$$
EPS_t^{model} = BPS_t \cdot ROE_t
$$

$$
EPS_t = \begin{cases}
EPS_0 \cdot (1-cf) + EPS_1^{model} \cdot cf & t=1 \\
EPS_t^{model} & t>1
\end{cases}
$$

$$
DPS_t = DPS_{t-1} \cdot (1 + g_{div,t})
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

**Margin of Safety (MOS):**

$$
\text{MOS} = \frac{\text{IV}}{\text{CurrentPrice}} - 1
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
        )
        _roe_fname = f"{st.session_state.val_ticker}_roe_{datetime.now().strftime('%y_%m_%d')}.xlsx"
        _all_fname = f"{st.session_state.val_ticker}_vse_{datetime.now().strftime('%y_%m_%d')}.xlsx"
        _roe_sc1, _roe_sc2 = st.columns([1, 3])
        with _roe_sc1:
            st.download_button(
                "💾 Uložit analýzu",
                data=_roe_bytes,
                file_name=_roe_fname,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="snap_roe_save_btn",
                width="stretch",
            )
        _all_sc1, _all_sc2 = st.columns([1, 3])
        with _all_sc1:
            st.download_button(
                "💾 Uložit vše",
                data=_all_bytes,
                file_name=_all_fname,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="snap_all_save_btn",
                width="stretch",
            )
    except Exception as _exc_roe_save:
        st.warning(f"Uložení selhalo: {_exc_roe_save}")

st.markdown(
        """
        <div style="margin-top:18px;font-size:11px;color:#6b7280;opacity:0.8;line-height:1.4;">
            Jan Kindermann<br/>
            coax.sacra.5m@icloud.com
        </div>
        """,
        unsafe_allow_html=True,
)

