import os

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf


ACCOUNT_CURRENCY = os.getenv("ACCOUNT_CURRENCY", "ACCT")


def money(value: float) -> str:
    return f"{value:,.2f} {ACCOUNT_CURRENCY}"


def configured_symbols() -> list[str]:
    raw = os.getenv("DERIVATIVES_WATCHLIST", "SPY,QQQ,AAPL,MSFT")
    return [symbol.strip() for symbol in raw.split(",") if symbol.strip()]


def load_history(symbol: str, period: str = "1y") -> pd.DataFrame:
    return yf.Ticker(symbol).history(period=period).dropna()


def realized_volatility(data: pd.DataFrame, window: int = 20) -> pd.Series:
    returns = np.log(data["Close"] / data["Close"].shift(1))
    return returns.rolling(window).std() * np.sqrt(252)


def option_expiries(symbol: str) -> list[str]:
    try:
        return list(yf.Ticker(symbol).options)
    except (AttributeError, ValueError, RuntimeError):
        return []


def option_chain(symbol: str, expiry: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    chain = yf.Ticker(symbol).option_chain(expiry)
    calls = chain.calls.copy()
    puts = chain.puts.copy()
    return calls, puts


def summarize_chain(calls: pd.DataFrame, puts: pd.DataFrame) -> dict[str, float]:
    call_volume = float(calls.get("volume", pd.Series(dtype=float)).fillna(0).sum())
    put_volume = float(puts.get("volume", pd.Series(dtype=float)).fillna(0).sum())
    call_oi = float(calls.get("openInterest", pd.Series(dtype=float)).fillna(0).sum())
    put_oi = float(puts.get("openInterest", pd.Series(dtype=float)).fillna(0).sum())
    total_volume = call_volume + put_volume
    total_oi = call_oi + put_oi

    return {
        "call_volume": call_volume,
        "put_volume": put_volume,
        "put_call_volume": put_volume / call_volume if call_volume else 0.0,
        "call_oi": call_oi,
        "put_oi": put_oi,
        "put_call_oi": put_oi / call_oi if call_oi else 0.0,
        "total_volume": total_volume,
        "total_oi": total_oi,
    }


def price_chart(symbol: str, data: pd.DataFrame) -> go.Figure:
    vol = realized_volatility(data)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=data.index, y=data["Close"], name="Close"))
    fig.add_trace(go.Scatter(x=data.index, y=vol, name="Realized vol", yaxis="y2"))
    fig.update_layout(
        title=f"{symbol} price and realized volatility",
        yaxis={"title": "Price"},
        yaxis2={"title": "Volatility", "overlaying": "y", "side": "right"},
        height=520,
        margin={"l": 20, "r": 20, "t": 50, "b": 20},
    )
    return fig


def chain_table(chain: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "contractSymbol",
        "strike",
        "lastPrice",
        "bid",
        "ask",
        "volume",
        "openInterest",
        "impliedVolatility",
    ]
    available = [col for col in columns if col in chain.columns]
    table = chain[available].copy()
    return table.sort_values("strike") if "strike" in table.columns else table


def derivatives_page() -> None:
    st.title("Derivatives Analyzer")

    with st.sidebar:
        symbols = configured_symbols()
        symbol = st.selectbox("Underlying", symbols, index=0)
        period = st.selectbox("Lookback", ["3mo", "6mo", "1y", "2y"], index=2)

    data = load_history(symbol, period)
    if data.empty:
        st.warning(f"No price history available for {symbol}")
        return

    current_price = float(data["Close"].iloc[-1])
    current_vol = realized_volatility(data).iloc[-1]

    col1, col2, col3 = st.columns(3)
    col1.metric("Underlying", symbol)
    col2.metric("Last Price", money(current_price))
    col3.metric("20-bar Realized Vol", f"{current_vol:.2f}")

    st.plotly_chart(price_chart(symbol, data), use_container_width=True)

    expiries = option_expiries(symbol)
    if not expiries:
        st.info("No option expiries available from the configured data provider.")
        return

    expiry = st.selectbox("Expiry", expiries)
    try:
        calls, puts = option_chain(symbol, expiry)
    except (ValueError, RuntimeError) as exc:
        st.warning(f"Could not load option chain: {exc}")
        return

    summary = summarize_chain(calls, puts)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Call Volume", f"{summary['call_volume']:,.0f}")
    c2.metric("Put Volume", f"{summary['put_volume']:,.0f}")
    c3.metric("Put/Call Volume", f"{summary['put_call_volume']:.2f}")
    c4.metric("Put/Call OI", f"{summary['put_call_oi']:.2f}")

    tab_calls, tab_puts = st.tabs(["Calls", "Puts"])
    with tab_calls:
        st.dataframe(chain_table(calls), use_container_width=True)
    with tab_puts:
        st.dataframe(chain_table(puts), use_container_width=True)


if __name__ == "__main__":
    derivatives_page()
