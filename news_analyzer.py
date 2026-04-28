import os
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf
from textblob import TextBlob


def configured_symbols() -> list[str]:
    raw = os.getenv("WATCHLIST", "SPY,QQQ,BTC-USD,AAPL,MSFT")
    return [symbol.strip() for symbol in raw.split(",") if symbol.strip()]


def fetch_provider_news(symbol: str) -> list[dict[str, str]]:
    articles: list[dict[str, str]] = []
    ticker = yf.Ticker(symbol)

    try:
        raw_news = ticker.news or []
    except (AttributeError, RuntimeError, ValueError):
        raw_news = []

    for item in raw_news[:20]:
        content = item.get("content", item)
        title = content.get("title", "") if isinstance(content, dict) else item.get("title", "")
        provider = content.get("provider", {}) if isinstance(content, dict) else {}
        source = provider.get("displayName", "provider") if isinstance(provider, dict) else "provider"
        published = content.get("pubDate", "") if isinstance(content, dict) else ""

        if title:
            articles.append(
                {
                    "title": title,
                    "source": source,
                    "published": str(published),
                    "sentiment": TextBlob(title).sentiment.polarity,
                }
            )

    return articles


def fetch_market_data(symbol: str) -> pd.DataFrame:
    return yf.download(symbol, period="5d", interval="1h", progress=False).dropna()


def detect_market_stress(data: pd.DataFrame, articles: list[dict[str, str]]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []

    if not data.empty:
        returns = data["Close"].pct_change().dropna()
        recent_return = returns.iloc[-1] if len(returns) else 0.0
        realized_vol = returns.std() * np.sqrt(252)
        current_volume = float(data["Volume"].iloc[-1])
        avg_volume = float(data["Volume"].rolling(20).mean().iloc[-1])

        if abs(recent_return) > 0.03:
            findings.append(
                {
                    "type": "Large price move",
                    "description": f"Recent return is {recent_return * 100:.2f}%",
                    "severity": "Medium",
                }
            )

        if avg_volume and current_volume > avg_volume * 2:
            findings.append(
                {
                    "type": "Volume spike",
                    "description": f"Latest volume is {current_volume / avg_volume:.1f}x its 20-bar average",
                    "severity": "Medium",
                }
            )

        if realized_vol > 0.8:
            findings.append(
                {
                    "type": "High realized volatility",
                    "description": f"Annualized realized volatility is {realized_vol:.2f}",
                    "severity": "High",
                }
            )

    if articles:
        avg_sentiment = float(np.mean([item["sentiment"] for item in articles]))
        if abs(avg_sentiment) > 0.35:
            direction = "positive" if avg_sentiment > 0 else "negative"
            findings.append(
                {
                    "type": "News sentiment skew",
                    "description": f"Headline sentiment is strongly {direction}",
                    "severity": "Low",
                }
            )

    return findings


def sentiment_chart(articles: list[dict[str, str]]) -> go.Figure:
    frame = pd.DataFrame(articles)
    fig = go.Figure()
    if not frame.empty:
        fig.add_trace(
            go.Bar(
                x=frame["title"].str.slice(0, 48),
                y=frame["sentiment"],
                text=frame["source"],
                name="Sentiment",
            )
        )
    fig.update_layout(
        title="Headline sentiment",
        xaxis_title="Headline",
        yaxis_title="Polarity",
        height=420,
        margin={"l": 20, "r": 20, "t": 50, "b": 120},
    )
    return fig


def news_analysis_page() -> None:
    st.title("Market News Analysis")

    symbol = st.selectbox("Symbol", configured_symbols())
    st.caption(f"Last refresh: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")

    data = fetch_market_data(symbol)
    articles = fetch_provider_news(symbol)
    findings = detect_market_stress(data, articles)

    col1, col2, col3 = st.columns(3)
    col1.metric("Headlines", len(articles))
    col2.metric(
        "Average sentiment",
        f"{np.mean([item['sentiment'] for item in articles]):.2f}" if articles else "0.00",
    )
    col3.metric("Stress findings", len(findings))

    if articles:
        st.plotly_chart(sentiment_chart(articles), use_container_width=True)
        st.dataframe(pd.DataFrame(articles), use_container_width=True)
    else:
        st.info("No headlines returned by the configured data provider.")

    st.subheader("Market Stress Checks")
    if findings:
        st.dataframe(pd.DataFrame(findings), use_container_width=True)
    else:
        st.write("No stress checks fired.")


if __name__ == "__main__":
    news_analysis_page()
