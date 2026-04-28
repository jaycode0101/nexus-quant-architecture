import os

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

from trading_model.llm.provider import get_llm_response


def _watchlist() -> list[str]:
    raw = os.getenv("WATCHLIST", "SPY,QQQ,BTC-USD,AAPL,MSFT")
    return [symbol.strip() for symbol in raw.split(",") if symbol.strip()]


def _account_currency() -> str:
    return os.getenv("ACCOUNT_CURRENCY", "ACCT")


def money(value: float) -> str:
    return f"{value:,.2f} {_account_currency()}"


@st.cache_data(ttl=300)
def load_ohlcv(symbol: str, period: str, interval: str) -> pd.DataFrame:
    data = yf.Ticker(symbol).history(period=period, interval=interval)
    if data.empty:
        return data
    return data.dropna()


def compute_features(data: pd.DataFrame) -> dict[str, float]:
    close = data["Close"]
    high = data["High"]
    low = data["Low"]

    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    returns = close.pct_change()

    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = -delta.clip(upper=0).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    macd_signal = macd.ewm(span=9, adjust=False).mean()
    macd_hist = macd - macd_signal

    tr = pd.concat(
        [
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = tr.rolling(14).mean()
    vol = returns.rolling(20).std() * np.sqrt(252)

    latest = close.iloc[-1]
    previous = close.iloc[-2] if len(close) > 1 else latest
    change_pct = ((latest - previous) / previous) * 100 if previous else 0.0

    return {
        "price": float(latest),
        "change_pct": float(change_pct),
        "sma20": float(sma20.iloc[-1]),
        "sma50": float(sma50.iloc[-1]),
        "rsi": float(rsi.iloc[-1]) if not np.isnan(rsi.iloc[-1]) else 50.0,
        "macd_hist": float(macd_hist.iloc[-1]),
        "atr": float(atr.iloc[-1]) if not np.isnan(atr.iloc[-1]) else 0.0,
        "vol": float(vol.iloc[-1]) if not np.isnan(vol.iloc[-1]) else 0.0,
    }


def signal_from_features(features: dict[str, float]) -> tuple[str, str]:
    score = 0

    if features["price"] > features["sma20"] > features["sma50"]:
        score += 2
    elif features["price"] < features["sma20"] < features["sma50"]:
        score -= 2

    if features["rsi"] < 35:
        score += 1
    elif features["rsi"] > 65:
        score -= 1

    if features["macd_hist"] > 0:
        score += 1
    elif features["macd_hist"] < 0:
        score -= 1

    if features["vol"] > 0.6:
        return "HOLD", "volatility filter"
    if score >= 3:
        return "BUY", "trend and momentum agree"
    if score <= -3:
        return "SELL", "trend and momentum agree"
    return "HOLD", "mixed evidence"


def price_chart(symbol: str, data: pd.DataFrame) -> go.Figure:
    close = data["Close"]
    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()

    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=data.index,
            open=data["Open"],
            high=data["High"],
            low=data["Low"],
            close=data["Close"],
            name="OHLC",
        )
    )
    fig.add_trace(go.Scatter(x=data.index, y=sma20, name="SMA 20"))
    fig.add_trace(go.Scatter(x=data.index, y=sma50, name="SMA 50"))
    fig.update_layout(
        title=f"{symbol} price",
        xaxis_rangeslider_visible=False,
        height=520,
        margin={"l": 20, "r": 20, "t": 50, "b": 20},
    )
    return fig


def llm_note(symbol: str, features: dict[str, float], signal: str, reason: str) -> str:
    prompt = f"""
Review this quantitative snapshot for {symbol}.

Price: {features['price']:.4f}
Change percent: {features['change_pct']:.2f}
SMA20: {features['sma20']:.4f}
SMA50: {features['sma50']:.4f}
RSI14: {features['rsi']:.2f}
MACD histogram: {features['macd_hist']:.4f}
ATR14: {features['atr']:.4f}
Annualized volatility: {features['vol']:.4f}
System signal: {signal}
Reason: {reason}

Explain the main conflict or confirmation in three sentences. Do not give
financial advice.
"""
    return get_llm_response(prompt).strip()


def main() -> None:
    st.title("Quant Research Dashboard")

    with st.sidebar:
        st.header("Inputs")
        symbols = st.multiselect("Symbols", _watchlist(), default=_watchlist()[:3])
        period = st.selectbox("Lookback", ["1mo", "3mo", "6mo", "1y", "2y"], index=2)
        interval = st.selectbox("Interval", ["1d", "1h", "30m", "15m"], index=0)
        use_llm = st.checkbox("Generate LLM notes", value=False)

    if not symbols:
        st.info("Choose at least one symbol.")
        return

    rows = []
    loaded: dict[str, tuple[pd.DataFrame, dict[str, float], str, str]] = {}

    for symbol in symbols:
        data = load_ohlcv(symbol, period, interval)
        if data.empty or len(data) < 50:
            st.warning(f"Not enough data for {symbol}")
            continue

        features = compute_features(data)
        signal, reason = signal_from_features(features)
        loaded[symbol] = (data, features, signal, reason)
        rows.append(
            {
                "Symbol": symbol,
                "Price": money(features["price"]),
                "Change %": f"{features['change_pct']:.2f}",
                "RSI": f"{features['rsi']:.2f}",
                "Vol": f"{features['vol']:.2f}",
                "Signal": signal,
                "Reason": reason,
            }
        )

    if not rows:
        st.error("No symbols had enough data for analysis.")
        return

    st.dataframe(pd.DataFrame(rows), use_container_width=True)

    selected = st.selectbox("Chart", list(loaded.keys()))
    data, features, signal, reason = loaded[selected]

    st.plotly_chart(price_chart(selected, data), use_container_width=True)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Signal", signal)
    col2.metric("RSI", f"{features['rsi']:.2f}")
    col3.metric("ATR", money(features["atr"]))
    col4.metric("Volatility", f"{features['vol']:.2f}")

    if use_llm:
        try:
            st.subheader("LLM Note")
            st.write(llm_note(selected, features, signal, reason))
        except (RuntimeError, ValueError, KeyError) as exc:
            st.warning(f"LLM note unavailable: {exc}")


if __name__ == "__main__":
    main()
