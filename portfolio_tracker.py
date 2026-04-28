import os
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf


ACCOUNT_CURRENCY = os.getenv("ACCOUNT_CURRENCY", "ACCT")


def money(value: float) -> str:
    return f"{value:,.2f} {ACCOUNT_CURRENCY}"


def load_portfolio() -> pd.DataFrame:
    if "portfolio" not in st.session_state:
        st.session_state.portfolio = pd.DataFrame(
            columns=[
                "Symbol",
                "Quantity",
                "Entry Price",
                "Entry Date",
                "Current Price",
                "Market Value",
                "Profit/Loss",
                "Profit/Loss %",
            ]
        )
    return st.session_state.portfolio


def add_position(symbol: str, quantity: int, entry_price: float, entry_date) -> None:
    portfolio = load_portfolio()
    current_price = yf.Ticker(symbol).history(period="1d")["Close"].iloc[-1]

    market_value = quantity * current_price
    cost_basis = quantity * entry_price
    profit_loss = market_value - cost_basis
    profit_loss_pct = (profit_loss / cost_basis) * 100 if cost_basis else 0.0

    new_row = pd.DataFrame(
        {
            "Symbol": [symbol],
            "Quantity": [quantity],
            "Entry Price": [entry_price],
            "Entry Date": [entry_date],
            "Current Price": [current_price],
            "Market Value": [market_value],
            "Profit/Loss": [profit_loss],
            "Profit/Loss %": [profit_loss_pct],
        }
    )

    st.session_state.portfolio = pd.concat([portfolio, new_row], ignore_index=True)


def remove_position(index: int) -> None:
    portfolio = load_portfolio()
    st.session_state.portfolio = portfolio.drop(index)


def update_portfolio_values() -> None:
    portfolio = load_portfolio()

    for idx, row in portfolio.iterrows():
        current_price = yf.Ticker(row["Symbol"]).history(period="1d")["Close"].iloc[-1]

        market_value = row["Quantity"] * current_price
        cost_basis = row["Quantity"] * row["Entry Price"]
        profit_loss = market_value - cost_basis
        profit_loss_pct = (profit_loss / cost_basis) * 100 if cost_basis else 0.0

        portfolio.at[idx, "Current Price"] = current_price
        portfolio.at[idx, "Market Value"] = market_value
        portfolio.at[idx, "Profit/Loss"] = profit_loss
        portfolio.at[idx, "Profit/Loss %"] = profit_loss_pct

    st.session_state.portfolio = portfolio


def create_portfolio_chart(portfolio: pd.DataFrame) -> go.Figure:
    fig = go.Figure()

    for _, row in portfolio.iterrows():
        hist = yf.Ticker(row["Symbol"]).history(
            start=row["Entry Date"],
            end=datetime.now(),
        )
        value = hist["Close"] * row["Quantity"]
        fig.add_trace(go.Scatter(x=hist.index, y=value, name=row["Symbol"], mode="lines"))

    total_value = portfolio["Market Value"].sum()
    fig.add_hline(
        y=total_value,
        line_dash="dash",
        line_color="red",
        annotation_text=f"Total Value: {money(total_value)}",
    )

    fig.update_layout(
        title="Portfolio Performance",
        xaxis_title="Date",
        yaxis_title=f"Value ({ACCOUNT_CURRENCY})",
        height=500,
    )
    return fig


def portfolio_page() -> None:
    st.title("Portfolio Tracker")

    with st.sidebar:
        st.header("Add Position")

        symbol = st.text_input("Symbol", value="SPY")
        quantity = st.number_input("Quantity", min_value=1, value=1)
        entry_price = st.number_input("Entry Price", min_value=0.0)
        entry_date = st.date_input("Entry Date")

        if st.button("Add Position"):
            if symbol:
                add_position(symbol, quantity, entry_price, entry_date)
                st.success(f"Added {symbol}")
            else:
                st.error("Enter a symbol")

    portfolio = load_portfolio()

    if portfolio.empty:
        st.info("Portfolio is empty. Add a position from the sidebar.")
        return

    update_portfolio_values()

    total_investment = (portfolio["Quantity"] * portfolio["Entry Price"]).sum()
    total_value = portfolio["Market Value"].sum()
    total_profit_loss = portfolio["Profit/Loss"].sum()
    total_profit_loss_pct = (
        (total_profit_loss / total_investment) * 100 if total_investment else 0.0
    )

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total Investment", money(total_investment))
    with col2:
        st.metric("Current Value", money(total_value))
    with col3:
        st.metric("Profit/Loss", money(total_profit_loss))
    with col4:
        st.metric("Profit/Loss %", f"{total_profit_loss_pct:.2f}%")

    st.plotly_chart(create_portfolio_chart(portfolio), use_container_width=True)

    st.header("Portfolio Holdings")
    display_df = portfolio.copy()
    for col in ["Entry Price", "Current Price", "Market Value", "Profit/Loss"]:
        display_df[col] = display_df[col].map(money)
    display_df["Profit/Loss %"] = display_df["Profit/Loss %"].map("{:.2f}%".format)

    st.dataframe(display_df)

    for idx, row in portfolio.iterrows():
        if st.button(f"Remove {row['Symbol']}", key=f"remove_{idx}"):
            remove_position(idx)
            st.experimental_rerun()


if __name__ == "__main__":
    portfolio_page()
