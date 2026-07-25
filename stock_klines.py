import json
import numpy as np
import pandas as pd
import yfinance as yf
import streamlit as st
import streamlit.components.v1 as components
import plotly.graph_objects as go
from plotly.subplots import make_subplots


# ── 股票代號轉換 & 資料抓取 ─────────────────────────────────────────

MARKET_OPTIONS = {
    "美股 (US)": "US",
    "台股上市 (TW)": "TW",
    "台股上櫃 (TWO)": "TWO",
    "港股 (HK)": "HK",
    "陸股-滬市 (SS)": "SS",
    "陸股-深市 (SZ)": "SZ",
    "自行輸入完整代碼": None,
}


def to_yahoo_symbol(symbol: str, market: str | None) -> str:
    """依市場別把使用者輸入的代號轉成 yfinance 需要的完整代號。"""
    symbol = symbol.strip().upper()
    if market is None:
        return symbol  # 使用者已自行提供完整代號，例如 "2330.TW"

    market = market.strip().upper()
    if market == "US":
        return symbol
    elif market == "TW":       # 台股上市
        return f"{symbol}.TW"
    elif market == "TWO":      # 台股上櫃
        return f"{symbol}.TWO"
    elif market == "HK":       # 港股：Yahoo 需要 4 碼補零，例如 700 -> 0700.HK
        return f"{symbol.zfill(4)}.HK"
    elif market == "SS":       # 陸股上海
        return f"{symbol}.SS"
    elif market == "SZ":       # 陸股深圳
        return f"{symbol}.SZ"
    else:
        raise ValueError(f"不支援的市場別：{market}")


@st.cache_data(ttl=300, show_spinner=False)
def fetch_stock_data(symbol: str, market: str | None,
                      period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    """透過 yfinance 抓取指定股票的歷史 K 線資料，回傳標準化欄位的 DataFrame。"""
    yahoo_symbol = to_yahoo_symbol(symbol, market)
    ticker = yf.Ticker(yahoo_symbol)
    raw = ticker.history(period=period, interval=interval, auto_adjust=False)

    if raw.empty:
        raise ValueError(
            f"抓不到資料：代號「{yahoo_symbol}」，請確認代號、市場別是否正確，"
            f"或該股票在 Yahoo Finance 上是否存在。"
        )

    raw = raw.reset_index()
    date_col = "Date" if "Date" in raw.columns else "Datetime"

    df = pd.DataFrame({
        "date": pd.to_datetime(raw[date_col]).dt.tz_localize(None),
        "open": raw["Open"],
        "high": raw["High"],
        "low": raw["Low"],
        "close": raw["Close"],
        "volume": raw["Volume"],
    }).dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)

    try:
        info = ticker.info
        display_name = info.get("longName") or info.get("shortName") or yahoo_symbol
    except Exception:
        display_name = yahoo_symbol

    df.attrs["symbol"] = yahoo_symbol
    df.attrs["display_name"] = display_name
    return df


# ── K 線圖表產生（保留原本 4-row + 動態 y 軸縮放 JS）──────────────────

def build_kline_html(df: pd.DataFrame, title: str) -> str:
    ma_periods = [1, 5, 20, 60]
    ma_colors = {1: "#888888", 5: "#e6a23c", 20: "#409eff", 60: "#a259d9"}
    for p in ma_periods:
        df[f"ma{p}"] = df["close"].rolling(window=p, min_periods=1).mean()

    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["dif"] = ema12 - ema26
    df["dea"] = df["dif"].ewm(span=9, adjust=False).mean()
    df["macd"] = (df["dif"] - df["dea"]) * 2

    delta = df["close"].diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs = gain / loss
    df["rsi"] = 100 - 100 / (1 + rs)

    x_min, x_max = df["date"].min(), df["date"].max()
    span = x_max - x_min
    left_pad, right_pad = span * 0.02, span * 0.05

    fig = make_subplots(
        rows=4, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.30, 0.20, 0.25, 0.25],
    )

    fig.add_trace(go.Candlestick(
        x=df["date"], open=df["open"], high=df["high"],
        low=df["low"], close=df["close"],
        name="K 線",
        increasing_line_color="red", decreasing_line_color="green",
    ), row=1, col=1)

    for p in ma_periods:
        fig.add_trace(go.Scatter(
            x=df["date"], y=df[f"ma{p}"],
            mode="lines", name=f"MA{p}",
            line=dict(color=ma_colors[p], width=1.2),
            hovertemplate=f"MA{p}: %{{y:.2f}}<extra></extra>",
        ), row=1, col=1)

    vol_colors = ["red" if c >= o else "green"
                  for c, o in zip(df["close"], df["open"])]
    fig.add_trace(go.Bar(
        x=df["date"], y=df["volume"],
        name="成交量", marker_color=vol_colors,
        showlegend=False,
        hovertemplate="量: %{y:,.0f}<extra></extra>",
    ), row=2, col=1)

    macd_colors = ["red" if v >= 0 else "green" for v in df["macd"]]
    fig.add_trace(go.Bar(
        x=df["date"], y=df["macd"],
        name="MACD 柱", marker_color=macd_colors,
        showlegend=False,
        hovertemplate="MACD: %{y:.3f}<extra></extra>",
    ), row=3, col=1)
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["dif"], mode="lines", name="DIF",
        line=dict(color="#e6a23c", width=1.2),
        hovertemplate="DIF: %{y:.3f}<extra></extra>",
    ), row=3, col=1)
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["dea"], mode="lines", name="DEA",
        line=dict(color="#409eff", width=1.2),
        hovertemplate="DEA: %{y:.3f}<extra></extra>",
    ), row=3, col=1)

    fig.add_trace(go.Scatter(
        x=df["date"], y=df["rsi"], mode="lines", name="RSI",
        line=dict(color="#a259d9", width=1.2),
        hovertemplate="RSI: %{y:.2f}<extra></extra>",
    ), row=4, col=1)
    fig.add_hline(y=70, line=dict(color="#999", width=0.8, dash="dash"), row=4, col=1)
    fig.add_hline(y=30, line=dict(color="#999", width=0.8, dash="dash"), row=4, col=1)

    fig.update_layout(
        title=dict(text=title, x=0.01, xanchor="left", y=0.995, yanchor="top", font=dict(size=16)),
        dragmode="pan",
        height=940,
        margin=dict(l=50, r=40, t=70, b=60),
        legend=dict(orientation="h", yanchor="top", y=-0.04, xanchor="center", x=0.5),
        hovermode="x unified",
        bargap=0.2,
    )

    def add_row_title(text, yref):
        fig.add_annotation(
            text=text, xref="paper", yref=yref,
            x=0.005, y=0.97, xanchor="left", yanchor="top",
            showarrow=False, font=dict(size=12, color="#666"),
            bgcolor="rgba(255,255,255,0.7)",
        )

    add_row_title("K 線 + MA", "y domain")
    add_row_title("成交量", "y2 domain")
    add_row_title("MACD", "y3 domain")
    add_row_title("RSI(14)", "y4 domain")

    fig.update_xaxes(
        fixedrange=False,
        minallowed=x_min - left_pad,
        maxallowed=x_max + right_pad,
        range=[x_min - left_pad, x_max + right_pad],
        rangebreaks=[dict(bounds=["sat", "mon"])],
        rangeslider_visible=False,
    )

    y_lo, y_hi = df["low"].min(), df["high"].max()
    y_pad = (y_hi - y_lo) * 0.05
    fig.update_yaxes(fixedrange=True, range=[y_lo - y_pad, y_hi + y_pad], row=1, col=1)

    vol_max = df["volume"].max() * 1.1
    fig.update_yaxes(fixedrange=True, range=[0, vol_max], row=2, col=1)

    macd_abs = max(abs(df["macd"].min()), abs(df["macd"].max()),
                   abs(df["dif"].min()), abs(df["dif"].max())) * 1.1
    fig.update_yaxes(fixedrange=True, range=[-macd_abs, macd_abs], row=3, col=1)

    fig.update_yaxes(fixedrange=True, range=[0, 100], row=4, col=1)

    payload = {
        "x": df["date"].dt.strftime("%Y-%m-%d").tolist(),
        "ohlc": {"high": df["high"].tolist(), "low": df["low"].tolist()},
        "ma": {f"ma{p}": df[f"ma{p}"].tolist() for p in ma_periods},
        "volume": df["volume"].tolist(),
        "macd": df["macd"].tolist(),
        "dif": df["dif"].tolist(),
        "dea": df["dea"].tolist(),
    }
    payload_json = json.dumps(payload)

    ma_trace_idx = {f"ma{p}": i + 1 for i, p in enumerate(ma_periods)}
    ma_trace_idx_json = json.dumps(ma_trace_idx)

    post_script = f"""
var d = {payload_json};
var maIdx = {ma_trace_idx_json};
var gd = document.getElementById('{{plot_id}}');

function visible(traceIdx) {{
    var v = gd.data[traceIdx].visible;
    return !(v === false || v === 'legendonly');
}}

function visibleRange(xr0, xr1) {{
    var t0 = new Date(xr0).getTime();
    var t1 = new Date(xr1).getTime();
    var idx = [];
    for (var i = 0; i < d.x.length; i++) {{
        var t = new Date(d.x[i]).getTime();
        if (t >= t0 && t <= t1) idx.push(i);
    }}
    return idx;
}}

function rescaleAll(xr0, xr1) {{
    var idx = visibleRange(xr0, xr1);
    if (idx.length === 0) return;

    var update = {{}};

    if (visible(0)) {{
        var hi = -Infinity, lo = Infinity;
        for (var k = 0; k < idx.length; k++) {{
            var i = idx[k];
            if (d.ohlc.high[i] > hi) hi = d.ohlc.high[i];
            if (d.ohlc.low[i]  < lo) lo = d.ohlc.low[i];
        }}
        Object.keys(maIdx).forEach(function(name) {{
            if (!visible(maIdx[name])) return;
            var arr = d.ma[name];
            for (var k = 0; k < idx.length; k++) {{
                var v = arr[idx[k]];
                if (v == null) continue;
                if (v > hi) hi = v;
                if (v < lo) lo = v;
            }}
        }});
        if (hi > -Infinity) {{
            var pad = (hi - lo) * 0.05;
            update['yaxis.range'] = [lo - pad, hi + pad];
        }}
    }}

    if (visible(5)) {{
        var vmax = 0;
        for (var k = 0; k < idx.length; k++) {{
            var v = d.volume[idx[k]];
            if (v > vmax) vmax = v;
        }}
        update['yaxis2.range'] = [0, vmax * 1.1];
    }}

    var anyMacd = visible(6) || visible(7) || visible(8);
    if (anyMacd) {{
        var maxAbs = 0;
        var pools = [];
        if (visible(6)) pools.push(d.macd);
        if (visible(7)) pools.push(d.dif);
        if (visible(8)) pools.push(d.dea);
        for (var p = 0; p < pools.length; p++) {{
            for (var k = 0; k < idx.length; k++) {{
                var v = pools[p][idx[k]];
                if (v == null) continue;
                if (Math.abs(v) > maxAbs) maxAbs = Math.abs(v);
            }}
        }}
        if (maxAbs > 0) update['yaxis3.range'] = [-maxAbs * 1.1, maxAbs * 1.1];
    }}

    if (Object.keys(update).length > 0) Plotly.relayout(gd, update);
}}

function currentXRange() {{
    var xr = gd.layout.xaxis.range;
    return xr ? [xr[0], xr[1]] : null;
}}

gd.on('plotly_relayout', function(ev) {{
    var xr0 = ev['xaxis.range[0]'] || (ev['xaxis.range'] && ev['xaxis.range'][0]);
    var xr1 = ev['xaxis.range[1]'] || (ev['xaxis.range'] && ev['xaxis.range'][1]);
    if (xr0 && xr1) {{ rescaleAll(xr0, xr1); return; }}
    if (ev['xaxis.autorange']) {{
        var xr = currentXRange();
        if (xr) rescaleAll(xr[0], xr[1]);
    }}
}});

gd.on('plotly_restyle', function() {{
    var xr = currentXRange();
    if (xr) rescaleAll(xr[0], xr[1]);
}});

var xrInit = currentXRange();
if (xrInit) rescaleAll(xrInit[0], xrInit[1]);
"""

    return fig.to_html(
        config={"scrollZoom": True, "displayModeBar": False, "displaylogo": False},
        include_plotlyjs="cdn",
        post_script=post_script,
        full_html=True,
    )


# ── Streamlit 介面 ────────────────────────────────────────────────────

def main():
    st.set_page_config(page_title="股票 K 線圖", layout="wide")

    if "kline_result" not in st.session_state:
        st.session_state.kline_result = None
    if "kline_error" not in st.session_state:
        st.session_state.kline_error = None

    st.markdown("""
        <style>
        .block-container {
            padding-top: 3.5rem !important;
            padding-bottom: 0rem !important;
        }
        iframe {
            margin-top: 8px !important;
        }
        </style>
    """, unsafe_allow_html=True)

    col_v, col_c = st.columns([3, 1], gap="large")

    with col_c:
        st.markdown("### 📈 股票 K 線圖")
        st.markdown(
            "輸入股票代號並選擇市場，即可繪製包含 <b>K線 + MA</b>、"
            "<b>成交量</b>、<b>MACD</b>、<b>RSI</b> 的四合一互動圖表。<br><br>"
            "支援 <b>美股 / 台股上市 / 台股上櫃 / 港股 / 陸股(滬、深)</b>。",
            unsafe_allow_html=True,
        )

        market_label = st.selectbox("市場", list(MARKET_OPTIONS.keys()), index=1)
        market = MARKET_OPTIONS[market_label]

        placeholder = "2330" if market == "TW" else (
            "AAPL" if market == "US" else
            "6488" if market == "TWO" else
            "700" if market == "HK" else
            "600519" if market == "SS" else
            "000001" if market == "SZ" else
            "2330.TW"
        )
        symbol = st.text_input("股票代號", placeholder=placeholder)

        col_p1, col_p2 = st.columns(2)
        with col_p1:
            period = st.selectbox(
                "區間", ["1mo", "3mo", "6mo", "1y", "2y", "5y", "ytd", "max"], index=3
            )
        with col_p2:
            interval = st.selectbox("K棒週期", ["1d", "1wk", "1mo"], index=0)

        if st.button("🚀 繪製圖表", use_container_width=True):
            if not symbol.strip():
                st.session_state.kline_error = "請輸入股票代號。"
                st.session_state.kline_result = None
            else:
                with st.spinner("抓取股價資料中..."):
                    try:
                        df = fetch_stock_data(symbol, market, period=period, interval=interval)
                        title = f"{df.attrs['display_name']} ({df.attrs['symbol']})"
                        html = build_kline_html(df, title)
                        st.session_state.kline_result = {"html": html, "title": title}
                        st.session_state.kline_error = None
                    except Exception as e:
                        st.session_state.kline_result = None
                        st.session_state.kline_error = str(e)

        if st.session_state.kline_error:
            st.error(st.session_state.kline_error)
        elif st.session_state.kline_result:
            st.success(f"已繪製：{st.session_state.kline_result['title']}")

        st.caption("資料來源：Yahoo Finance（yfinance），僅供參考，不構成投資建議。")

        st.markdown("<br><hr style='margin: 1em 0;'>", unsafe_allow_html=True)

        st.markdown("""
            <div style="font-size: 0.9em; line-height: 1.6; color: #555;">
                <b>👨‍💻 Author:</b> Yen-Hung Chen<br>
                <b>🐙 GitHub:</b> <a href="https://github.com/pplongChen"> https://github.com/pplongChen </a> <br>
                <b>📁 Repository:</b> <a href="https://github.com/pplongChen/tools_agent"> https://github.com/pplongChen/tools_agent </a> <br>
                <b>🌐 Website:</b> <a href="https://network-affairs.github.io/"> https://network-affairs.github.io/ </a>
            </div>
        """, unsafe_allow_html=True)

    with col_v:
        if st.session_state.kline_result:
            components.html(st.session_state.kline_result["html"], height=950, scrolling=True)
        else:
            st.info("👈 請在右側輸入股票代號並選擇市場，再點擊「繪製圖表」。")


if __name__ == "__main__":
    main()
