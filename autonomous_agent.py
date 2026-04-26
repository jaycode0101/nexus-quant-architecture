"""
Autonomous Trading Agent
A multi-factor systematic trading agent.
Architecture: Data -> Features -> Regime -> Signals -> Risk -> LLM

Components:
    1. DataEngine       — Market data pipeline (yfinance, 6-month OHLCV)
    2. NewsEngine       — Multi-source news + LLM sentiment scoring
    3. FeatureEngine    — Quantitative indicators
    4. RegimeDetector   — Market state classification
    5. SignalAggregator — Weighted composite
    6. CircuitBreaker   — Safety layer
    7. RiskEngine       — Sizing, stops, signal classification
    8. LLM Strategy     — Gemini reasoning overlay
    9. Dashboard        — Terminal UI
"""

import os
import sys
import time

# Fix Windows terminal encoding — force UTF-8
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
import math
import warnings
import requests
import numpy as np
import pandas as pd
import yfinance as yf
import feedparser
from urllib.parse import quote as url_quote
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
import google.generativeai as genai
from dotenv import load_dotenv

# Rich terminal display
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text
from rich.live import Live
from rich import box

warnings.filterwarnings("ignore")
load_dotenv()

# --- Configuration -----------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

console = Console(force_terminal=True)


# 1. QUANTITATIVE STATE
@dataclass
class QuantState:
    """Complete quantitative state for a single instrument. ~40 fields."""
    # Identity
    symbol: str
    timestamp: str
    # Price
    current_price: float = 0.0
    prev_close: float = 0.0
    daily_return_pct: float = 0.0
    # Trend
    ema_9: float = 0.0
    ema_21: float = 0.0
    ema_50: float = 0.0
    ema_200: float = 0.0
    golden_cross: bool = False
    death_cross: bool = False
    # Momentum
    rsi_7: float = 50.0
    rsi_14: float = 50.0
    rsi_21: float = 50.0
    macd: float = 0.0
    macd_signal: float = 0.0
    macd_histogram: float = 0.0
    stochastic_k: float = 50.0
    stochastic_d: float = 50.0
    roc_10: float = 0.0
    # Volatility
    atr_14: float = 0.0
    bollinger_upper: float = 0.0
    bollinger_lower: float = 0.0
    bollinger_pct_b: float = 0.5
    historical_vol_20: float = 0.0
    # Volume
    volume_ratio: float = 1.0
    obv_slope: float = 0.0
    # Trend Strength
    adx: float = 0.0
    # Statistical
    z_score_20: float = 0.0
    hurst_exponent: float = 0.5
    # Support/Resistance
    fib_levels: Dict[str, float] = field(default_factory=dict)
    # Regression
    linear_reg_slope: float = 0.0
    # News
    news_sentiment: float = 0.0  # -1.0 to +1.0
    news_headlines: List[str] = field(default_factory=list)
    news_count: int = 0
    # System output
    composite_score: float = 0.0   # -100 to +100
    regime: str = "UNKNOWN"
    confidence: float = 0.0        # 0.0 to 1.0
    signal_label: str = "HOLD"
    circuit_breaker: str = "CLEAR"  # CLEAR or reason for trip
    # Risk
    stop_loss: float = 0.0
    target_price: float = 0.0
    position_size_pct: float = 0.0


# 2. DATA ENGINE
class DataEngine:
    """Fetches and validates market data."""

    @staticmethod
    def fetch(symbol: str, period: str = "6mo") -> Optional[pd.DataFrame]:
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period=period)
            if hist.empty or len(hist) < 50:
                console.print(f"[red][DataEngine] Insufficient data for {symbol} ({len(hist) if not hist.empty else 0} bars)[/red]")
                return None
            return hist
        except Exception as e:
            console.print(f"[red][DataEngine] Error fetching {symbol}: {e}[/red]")
            return None


# 3. NEWS ENGINE
class NewsEngine:
    """
    Fetches news from multiple sources and scores sentiment via Gemini LLM.
    Sources (in priority order):
        1. yfinance ticker.news — direct Yahoo Finance news feed
        2. Google News RSS — free, no API key, broad coverage
    Sentiment: Gemini LLM scores each headline (-1 to +1) with financial context.
    """

    @staticmethod
    def _fetch_yfinance_news(symbol: str) -> List[Dict]:
        """Fetch news directly from yfinance ticker object."""
        articles = []
        try:
            ticker = yf.Ticker(symbol)
            news = ticker.news
            if news:
                for item in news[:10]:
                    content = item.get("content", item)
                    title = content.get("title", "") if isinstance(content, dict) else item.get("title", "")
                    pub_date = ""
                    if isinstance(content, dict):
                        pub_date = content.get("pubDate", content.get("provider_publish_time", ""))
                    elif "providerPublishTime" in item:
                        pub_date = datetime.fromtimestamp(item["providerPublishTime"]).strftime("%Y-%m-%d %H:%M")
                    link = ""
                    if isinstance(content, dict):
                        ctu = content.get("clickThroughUrl", {})
                        link = ctu.get("url", "") if isinstance(ctu, dict) else str(ctu)
                    else:
                        link = item.get("link", "")

                    if title:
                        articles.append({
                            "title": title,
                            "date": str(pub_date),
                            "source": "Yahoo Finance",
                            "link": link
                        })
        except Exception as e:
            console.print(f"[yellow][NewsEngine] yfinance news warning: {e}[/yellow]")
        return articles

    @staticmethod
    def _fetch_google_news_rss(query: str) -> List[Dict]:
        """Fetch news from Google News RSS feed. Free, no API key required."""
        articles = []
        try:
            # Clean the symbol for search (RELIANCE.NS → RELIANCE stock NSE)
            clean_query = query.replace(".NS", "").replace(".BO", "")
            search_term = url_quote(f"{clean_query} stock NSE India")
            url = f"https://news.google.com/rss/search?q={search_term}&hl=en-IN&gl=IN&ceid=IN:en"

            feed = feedparser.parse(url)
            if feed.entries:
                for entry in feed.entries[:10]:
                    articles.append({
                        "title": entry.get("title", ""),
                        "date": entry.get("published", ""),
                        "source": "Google News",
                        "link": entry.get("link", "")
                    })
        except Exception as e:
            console.print(f"[yellow][NewsEngine] Google News RSS warning: {e}[/yellow]")
        return articles

    @staticmethod
    def _score_sentiment_llm(headlines: List[str], symbol: str) -> float:
        """
        Use Gemini LLM to score financial sentiment of headlines.
        Returns: float between -1.0 (extremely bearish) and +1.0 (extremely bullish).
        """
        if not headlines or not GEMINI_API_KEY:
            return 0.0

        try:
            model = genai.GenerativeModel('gemini-2.0-flash')
            headlines_text = "\n".join([f"- {h}" for h in headlines[:15]])

            prompt = f"""You are a quantitative financial sentiment analyzer.
Score the overall sentiment of these news headlines for {symbol} on a scale from -1.0 (extremely bearish/negative for the stock price) to +1.0 (extremely bullish/positive for the stock price).

Headlines:
{headlines_text}

Rules:
- Consider the FINANCIAL IMPACT on the stock price, not general sentiment
- Regulatory actions, lawsuits, downgrades = negative
- Earnings beats, upgrades, expansions, partnerships = positive
- Generic market news with no direct impact = near 0.0
- Return ONLY a single float number, nothing else

Score:"""

            response = model.generate_content(prompt)
            score_text = response.text.strip()
            # Extract float from response
            score = float(score_text.replace(",", "").strip())
            return max(-1.0, min(1.0, score))
        except Exception as e:
            console.print(f"[yellow][NewsEngine] LLM sentiment warning: {e}[/yellow]")
            return 0.0

    @classmethod
    def fetch_and_score(cls, symbol: str) -> Tuple[float, List[str], int]:
        """
        Complete news pipeline: fetch from all sources → deduplicate → LLM sentiment.
        Returns: (sentiment_score, headline_list, total_count)
        """
        console.print(f"  [dim]→ Fetching news for {symbol}...[/dim]")

        # Fetch from both sources
        yf_news = cls._fetch_yfinance_news(symbol)
        gn_news = cls._fetch_google_news_rss(symbol)

        # Combine and deduplicate by title similarity
        all_articles = yf_news + gn_news
        seen_titles = set()
        unique_articles = []
        for article in all_articles:
            title_key = article["title"].lower()[:50]
            if title_key not in seen_titles and article["title"]:
                seen_titles.add(title_key)
                unique_articles.append(article)

        headlines = [a["title"] for a in unique_articles]
        total_count = len(headlines)

        if total_count == 0:
            console.print(f"  [yellow]→ No news found for {symbol}[/yellow]")
            return 0.0, [], 0

        console.print(f"  [green]→ Found {total_count} articles, scoring sentiment...[/green]")

        # Score via LLM
        sentiment = cls._score_sentiment_llm(headlines, symbol)

        return sentiment, headlines[:8], total_count


# 4. FEATURE ENGINE
class FeatureEngine:
    """Computes the full quantitative feature matrix from raw OHLCV."""

    @staticmethod
    def compute_rsi(series: pd.Series, period: int) -> float:
        delta = series.diff()
        gain = delta.where(delta > 0, 0).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        val = rsi.iloc[-1]
        return round(val, 2) if not np.isnan(val) else 50.0

    @staticmethod
    def compute_ema(series: pd.Series, span: int) -> pd.Series:
        return series.ewm(span=span, adjust=False).mean()

    @staticmethod
    def compute_macd(series: pd.Series) -> Tuple[float, float, float]:
        exp12 = series.ewm(span=12, adjust=False).mean()
        exp26 = series.ewm(span=26, adjust=False).mean()
        macd_line = exp12 - exp26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        histogram = macd_line - signal_line
        return (
            round(macd_line.iloc[-1], 4),
            round(signal_line.iloc[-1], 4),
            round(histogram.iloc[-1], 4)
        )

    @staticmethod
    def compute_bollinger(series: pd.Series, period: int = 20, std_dev: float = 2.0) -> Tuple[float, float, float]:
        sma = series.rolling(window=period).mean()
        std = series.rolling(window=period).std()
        upper = sma + (std * std_dev)
        lower = sma - (std * std_dev)
        band_width = upper.iloc[-1] - lower.iloc[-1]
        if band_width != 0:
            pct_b = (series.iloc[-1] - lower.iloc[-1]) / band_width
        else:
            pct_b = 0.5
        return round(upper.iloc[-1], 2), round(lower.iloc[-1], 2), round(pct_b, 4)

    @staticmethod
    def compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float:
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        val = atr.iloc[-1]
        return round(val, 4) if not np.isnan(val) else 0.0

    @staticmethod
    def compute_stochastic(high: pd.Series, low: pd.Series, close: pd.Series,
                           k_period: int = 14, d_period: int = 3) -> Tuple[float, float]:
        lowest_low = low.rolling(window=k_period).min()
        highest_high = high.rolling(window=k_period).max()
        denom = highest_high - lowest_low
        denom = denom.replace(0, np.nan)
        k = 100 * ((close - lowest_low) / denom)
        d = k.rolling(window=d_period).mean()
        k_val = k.iloc[-1] if not np.isnan(k.iloc[-1]) else 50.0
        d_val = d.iloc[-1] if not np.isnan(d.iloc[-1]) else 50.0
        return round(k_val, 2), round(d_val, 2)

    @staticmethod
    def compute_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float:
        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)

        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        atr = tr.rolling(window=period).mean()
        atr = atr.replace(0, np.nan)

        plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr)
        minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr)

        di_sum = plus_di + minus_di
        di_sum = di_sum.replace(0, np.nan)
        dx = 100 * abs(plus_di - minus_di) / di_sum
        adx = dx.rolling(window=period).mean()
        val = adx.iloc[-1]
        return round(val, 2) if not np.isnan(val) else 0.0

    @staticmethod
    def compute_obv_slope(close: pd.Series, volume: pd.Series, lookback: int = 10) -> float:
        direction = np.sign(close.diff())
        obv = (volume * direction).cumsum()
        if len(obv) < lookback:
            return 0.0
        x = np.arange(lookback)
        y = obv.iloc[-lookback:].values.astype(float)
        if np.any(np.isnan(y)):
            return 0.0
        slope = np.polyfit(x, y, 1)[0]
        return round(slope, 2)

    @staticmethod
    def compute_historical_volatility(close: pd.Series, period: int = 20) -> float:
        log_returns = np.log(close / close.shift(1))
        vol = log_returns.rolling(window=period).std() * np.sqrt(252)
        val = vol.iloc[-1]
        return round(val, 4) if not np.isnan(val) else 0.0

    @staticmethod
    def compute_z_score(close: pd.Series, period: int = 20) -> float:
        mean = close.rolling(window=period).mean().iloc[-1]
        std = close.rolling(window=period).std().iloc[-1]
        if std == 0 or np.isnan(std):
            return 0.0
        return round((close.iloc[-1] - mean) / std, 4)

    @staticmethod
    def compute_hurst_exponent(series, max_lag: int = 20) -> float:
        """Simplified R/S analysis for Hurst exponent estimation."""
        if isinstance(series, pd.Series):
            series = series.values.astype(float)
        series = series[~np.isnan(series)]
        if len(series) < 40:
            return 0.5

        lags = range(2, min(max_lag + 1, len(series) // 4))
        tau = []
        for lag in lags:
            chunks = [series[i:i + lag] for i in range(0, len(series) - lag, lag)]
            rs_values = []
            for chunk in chunks:
                if len(chunk) < lag:
                    continue
                mean_c = np.mean(chunk)
                deviations = chunk - mean_c
                cumulative = np.cumsum(deviations)
                R = np.max(cumulative) - np.min(cumulative)
                S = np.std(chunk, ddof=1)
                if S > 0 and R > 0:
                    rs_values.append(R / S)
            if rs_values:
                tau.append((lag, np.mean(rs_values)))

        if len(tau) < 3:
            return 0.5

        lags_arr = np.log([t[0] for t in tau])
        rs_arr = np.log([t[1] for t in tau])
        hurst = np.polyfit(lags_arr, rs_arr, 1)[0]
        return round(max(0, min(1, hurst)), 4)

    @staticmethod
    def compute_fibonacci_levels(high: pd.Series, low: pd.Series, lookback: int = 60) -> Dict[str, float]:
        actual_lookback = min(lookback, len(high))
        recent_high = high.iloc[-actual_lookback:].max()
        recent_low = low.iloc[-actual_lookback:].min()
        diff = recent_high - recent_low
        return {
            "0.0%": round(recent_high, 2),
            "23.6%": round(recent_high - 0.236 * diff, 2),
            "38.2%": round(recent_high - 0.382 * diff, 2),
            "50.0%": round(recent_high - 0.500 * diff, 2),
            "61.8%": round(recent_high - 0.618 * diff, 2),
            "100.0%": round(recent_low, 2),
        }

    @staticmethod
    def compute_linear_regression_slope(close: pd.Series, period: int = 20) -> float:
        actual_period = min(period, len(close))
        if actual_period < 5:
            return 0.0
        y = close.iloc[-actual_period:].values.astype(float)
        if np.any(np.isnan(y)):
            return 0.0
        x = np.arange(actual_period)
        slope = np.polyfit(x, y, 1)[0]
        price = close.iloc[-1]
        if price == 0:
            return 0.0
        return round(slope / price * 100, 4)


# 5. REGIME DETECTOR
class RegimeDetector:
    """
    Classifies market into one of 4 regimes:
        HIGH_VOLATILITY  — hist vol > 40% annualized
        TRENDING_UP      — ADX > 25, price > EMA50 > EMA200
        TRENDING_DOWN    — ADX > 25, price < EMA50 < EMA200
        MEAN_REVERTING   — Hurst < 0.45 or ADX < 20
    """

    @staticmethod
    def detect(adx: float, hurst: float, vol: float,
               ema_50: float, ema_200: float, current_price: float) -> str:
        # High volatility overrides everything
        if vol > 0.40:
            return "HIGH_VOLATILITY"

        # Strong trend
        if adx > 25:
            if current_price > ema_50 and ema_50 > ema_200:
                return "TRENDING_UP"
            elif current_price < ema_50 and ema_50 < ema_200:
                return "TRENDING_DOWN"

        # Mean reversion
        if hurst < 0.45 or adx < 20:
            return "MEAN_REVERTING"

        # Weak directional bias
        if current_price > ema_200:
            return "TRENDING_UP"
        return "TRENDING_DOWN"


# 6. SIGNAL AGGREGATOR
class SignalAggregator:
    """
    6-factor weighted composite scoring with regime-adaptive weights.
    Factors: Momentum, Trend, Mean Reversion, Volume, Volatility, News Sentiment.
    """

    WEIGHTS = {
        "momentum": 0.20,
        "trend": 0.22,
        "mean_reversion": 0.15,
        "volume": 0.13,
        "volatility": 0.10,
        "news": 0.20,
    }

    @staticmethod
    def compute_composite(state: QuantState) -> Tuple[float, float]:
        """Returns (composite_score [-100, 100], confidence [0, 1])."""
        scores = {}
        confidences = {}

        # -- Momentum --
        momentum = 0
        if state.rsi_14 < 30:
            momentum += 40
        elif state.rsi_14 > 70:
            momentum -= 40
        else:
            momentum += (50 - state.rsi_14) * 1.2

        if state.macd_histogram > 0:
            momentum += 25
        else:
            momentum -= 25

        if state.stochastic_k < 20:
            momentum += 20
        elif state.stochastic_k > 80:
            momentum -= 20

        if state.roc_10 > 0:
            momentum += 15
        else:
            momentum -= 15

        scores["momentum"] = max(-100, min(100, momentum))
        confidences["momentum"] = min(1.0, abs(momentum) / 60)

        # -- Trend --
        trend = 0
        if state.golden_cross:
            trend += 35
        elif state.death_cross:
            trend -= 35

        if state.current_price > state.ema_9:
            trend += 12
        else:
            trend -= 12

        if state.current_price > state.ema_21:
            trend += 12
        else:
            trend -= 12

        adx_multiplier = 1.3 if state.adx > 25 else 0.7
        trend = trend * adx_multiplier
        trend += state.linear_reg_slope * 10

        scores["trend"] = max(-100, min(100, trend))
        confidences["trend"] = min(1.0, state.adx / 40)

        # -- Mean Reversion --
        mr = 0
        if state.bollinger_pct_b < 0.1:
            mr += 50
        elif state.bollinger_pct_b > 0.9:
            mr -= 50
        else:
            mr += (0.5 - state.bollinger_pct_b) * 60

        if state.z_score_20 < -2:
            mr += 40
        elif state.z_score_20 > 2:
            mr -= 40
        else:
            mr -= state.z_score_20 * 15

        scores["mean_reversion"] = max(-100, min(100, mr))
        confidences["mean_reversion"] = min(1.0, abs(state.z_score_20) / 2.5)

        # -- Volume --
        vol_score = 0
        if state.volume_ratio > 1.5 and state.daily_return_pct > 0:
            vol_score += 40
        elif state.volume_ratio > 1.5 and state.daily_return_pct < 0:
            vol_score -= 40

        if state.obv_slope > 0:
            vol_score += 30
        else:
            vol_score -= 30

        scores["volume"] = max(-100, min(100, vol_score))
        confidences["volume"] = min(1.0, state.volume_ratio / 2.0)

        # -- Volatility --
        vol_adj = 0
        if state.historical_vol_20 > 0.35:
            vol_adj = -20
        elif state.historical_vol_20 < 0.15:
            vol_adj = 10

        scores["volatility"] = vol_adj
        confidences["volatility"] = 0.5

        # -- News Sentiment --
        news_score = state.news_sentiment * 80  # Scale -1..+1 to -80..+80
        if state.news_count == 0:
            news_score = 0
            confidences["news"] = 0.1
        else:
            confidences["news"] = min(1.0, state.news_count / 8)

        scores["news"] = max(-100, min(100, news_score))

        # -- Weighted Composite --
        composite = sum(
            scores[factor] * SignalAggregator.WEIGHTS[factor]
            for factor in scores
        )

        # Regime adaptation
        if state.regime == "MEAN_REVERTING":
            composite = composite * 0.7 + scores["mean_reversion"] * 0.3
        elif "TRENDING" in state.regime:
            composite = composite * 0.7 + scores["trend"] * 0.3

        # Overall confidence
        confidence = sum(
            confidences[factor] * SignalAggregator.WEIGHTS[factor]
            for factor in confidences
        )

        return round(max(-100, min(100, composite)), 2), round(confidence, 4)


# 7. CIRCUIT BREAKER
class CircuitBreaker:
    """
    4 kill switches:
        1. Volatility Kill    — hist vol > 60% annualized
        2. Low Confidence     — confidence < 0.15
        3. Signal Conflict    — composite near 0 (±5) with high factor disagreement
        4. Data Staleness     — last data point > 3 days old
    """

    @staticmethod
    def check(state: QuantState, df: pd.DataFrame) -> str:
        """Returns 'CLEAR' or a reason string for the circuit trip."""

        # 1. Volatility kill switch
        if state.historical_vol_20 > 0.60:
            return "VOL_KILL: Historical volatility > 60% — too dangerous"

        # 2. Low confidence filter
        if state.confidence < 0.15:
            return "LOW_CONFIDENCE: Insufficient signal conviction"

        # 3. Conflicting signals — composite near zero means factors are fighting
        if abs(state.composite_score) < 5 and state.confidence > 0.3:
            return "SIGNAL_CONFLICT: Factors contradicting — forced HOLD"

        # 4. Data staleness
        if df is not None and len(df) > 0:
            last_date = df.index[-1]
            if hasattr(last_date, 'tz_localize'):
                last_date = last_date.tz_localize(None) if last_date.tzinfo else last_date
            days_old = (datetime.now() - last_date).days
            if days_old > 3:
                return f"STALE_DATA: Last data point is {days_old} days old"

        return "CLEAR"


# 8. RISK ENGINE
class RiskEngine:
    """Half-Kelly position sizing, ATR-based stops, signal classification."""

    @staticmethod
    def signal_label(composite: float, circuit: str) -> str:
        if circuit != "CLEAR":
            return "HOLD [!]"
        if composite >= 50:
            return "STRONG BUY"
        elif composite >= 20:
            return "BUY"
        elif composite >= -20:
            return "HOLD"
        elif composite >= -50:
            return "SELL"
        else:
            return "STRONG SELL"

    @staticmethod
    def position_size_pct(composite: float, confidence: float, vol: float) -> float:
        """Returns suggested position size as % of portfolio (max 10%)."""
        base = abs(composite) / 100 * 10
        vol_adj = base * (1 - min(vol, 0.5))
        conf_adj = vol_adj * confidence
        return round(min(conf_adj, 10.0), 2)

    @staticmethod
    def compute_stops(price: float, atr: float, is_long: bool) -> Tuple[float, float]:
        """ATR-based dynamic stop-loss and target price."""
        if atr == 0:
            return round(price * 0.97, 2), round(price * 1.05, 2)

        if is_long:
            stop = price - (2.0 * atr)
            target = price + (3.0 * atr)
        else:
            stop = price + (2.0 * atr)
            target = price - (3.0 * atr)

        return round(stop, 2), round(target, 2)


# 9. TERMINAL DASHBOARD
class Dashboard:
    """Professional terminal display using Rich."""

    @staticmethod
    def build_header() -> Panel:
        header_text = Text()
        header_text.append("  Systematic Trading Agent\n", style="bold white")
        header_text.append("  Quant Matrix + News + LLM\n", style="dim")
        header_text.append(f"  Cycle: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", style="cyan")
        return Panel(header_text, border_style="bright_blue", box=box.ASCII)

    @staticmethod
    def build_summary_table(states: List[QuantState]) -> Table:
        table = Table(
            title="QUANTITATIVE ANALYSIS MATRIX",
            box=box.ASCII,
            header_style="bold magenta",
            border_style="bright_blue",
            show_lines=True,
            pad_edge=True,
        )

        table.add_column("Symbol", style="bold cyan", width=14)
        table.add_column("Price", justify="right", width=10)
        table.add_column("Chg%", justify="right", width=8)
        table.add_column("RSI", justify="right", width=7)
        table.add_column("MACD-H", justify="right", width=9)
        table.add_column("ADX", justify="right", width=7)
        table.add_column("Regime", width=16)
        table.add_column("News", justify="right", width=7)
        table.add_column("Comp.", justify="right", width=8)
        table.add_column("Conf.", justify="right", width=7)
        table.add_column("Signal", width=14)
        table.add_column("CB", width=6)

        for s in states:
            # Color coding
            chg_color = "green" if s.daily_return_pct >= 0 else "red"
            rsi_color = "red" if s.rsi_14 > 70 else "green" if s.rsi_14 < 30 else "white"
            macd_color = "green" if s.macd_histogram > 0 else "red"
            regime_color = {"TRENDING_UP": "green", "TRENDING_DOWN": "red",
                            "MEAN_REVERTING": "yellow", "HIGH_VOLATILITY": "bright_red"}.get(s.regime, "white")
            news_color = "green" if s.news_sentiment > 0.1 else "red" if s.news_sentiment < -0.1 else "yellow"
            comp_color = "green" if s.composite_score > 20 else "red" if s.composite_score < -20 else "yellow"

            signal_styles = {
                "STRONG BUY": "bold bright_green",
                "BUY": "green",
                "HOLD": "yellow",
                "HOLD [!]": "bright_yellow",
                "SELL": "red",
                "STRONG SELL": "bold bright_red",
            }
            signal_style = signal_styles.get(s.signal_label, "white")

            cb_text = "OK" if s.circuit_breaker == "CLEAR" else "!!"

            table.add_row(
                s.symbol,
                f"Rs{s.current_price:,.1f}",
                f"[{chg_color}]{s.daily_return_pct:+.2f}%[/{chg_color}]",
                f"[{rsi_color}]{s.rsi_14}[/{rsi_color}]",
                f"[{macd_color}]{s.macd_histogram:+.4f}[/{macd_color}]",
                f"{s.adx}",
                f"[{regime_color}]{s.regime}[/{regime_color}]",
                f"[{news_color}]{s.news_sentiment:+.2f}[/{news_color}]",
                f"[{comp_color}]{s.composite_score:+.1f}[/{comp_color}]",
                f"{s.confidence:.2f}",
                f"[{signal_style}]{s.signal_label}[/{signal_style}]",
                cb_text,
            )

        return table

    @staticmethod
    def build_news_panel(states: List[QuantState]) -> Panel:
        text = Text()
        for s in states:
            if s.news_headlines:
                color = "green" if s.news_sentiment > 0 else "red" if s.news_sentiment < 0 else "yellow"
                text.append(f"\n  {s.symbol}", style="bold cyan")
                text.append(f" (Sentiment: ", style="dim")
                text.append(f"{s.news_sentiment:+.2f}", style=color)
                text.append(f", {s.news_count} articles)\n", style="dim")
                for i, headline in enumerate(s.news_headlines[:3]):
                    text.append(f"    - {headline[:80]}\n", style="dim white")
        if not text.plain.strip():
            text.append("  No news data available.", style="dim yellow")
        return Panel(text, title="NEWS INTELLIGENCE", border_style="yellow", box=box.ASCII)

    @staticmethod
    def build_circuit_panel(states: List[QuantState]) -> Panel:
        text = Text()
        any_tripped = False
        for s in states:
            if s.circuit_breaker != "CLEAR":
                any_tripped = True
                text.append(f"  [!!] {s.symbol}: ", style="bold red")
                text.append(f"{s.circuit_breaker}\n", style="yellow")
        if not any_tripped:
            text.append("  [OK] All circuit breakers CLEAR", style="bold green")
        return Panel(text, title="CIRCUIT BREAKERS", border_style="red", box=box.ASCII)

    @staticmethod
    def render_full(states: List[QuantState], llm_outputs: Dict[str, str]):
        console.print()
        console.print(Dashboard.build_header())
        console.print(Dashboard.build_summary_table(states))
        console.print(Dashboard.build_circuit_panel(states))
        console.print(Dashboard.build_news_panel(states))

        # LLM Reasoning panels
        for symbol, reasoning in llm_outputs.items():
            text = Text(reasoning[:600], style="white")
            console.print(Panel(text, title=f"LLM STRATEGY -- {symbol}",
                                border_style="bright_blue", box=box.ASCII))


# MAIN AGENT
class TradingAgent:
    """
    Orchestrates the pipeline: Data -> News -> Features -> Regime -> Signals -> Circuit -> Risk -> LLM -> Output
    """

    def __init__(self, symbols: List[str]):
        self.symbols = symbols
        self.model = genai.GenerativeModel('gemini-2.0-flash') if GEMINI_API_KEY else None

    def build_quant_state(self, symbol: str) -> Optional[Tuple[QuantState, pd.DataFrame]]:
        """Build the complete quantitative state for a symbol."""
        # -- Data --
        df = DataEngine.fetch(symbol, period="6mo")
        if df is None:
            return None

        close = df['Close']
        high = df['High']
        low = df['Low']
        volume = df['Volume']
        fe = FeatureEngine

        # -- Price --
        current_price = round(float(close.iloc[-1]), 2)
        prev_close = round(float(close.iloc[-2]), 2)
        daily_return = round((current_price - prev_close) / prev_close * 100, 4) if prev_close != 0 else 0

        # -- EMAs --
        ema_9 = round(float(fe.compute_ema(close, 9).iloc[-1]), 2)
        ema_21 = round(float(fe.compute_ema(close, 21).iloc[-1]), 2)
        ema_50 = round(float(fe.compute_ema(close, 50).iloc[-1]), 2)
        ema_200_val = fe.compute_ema(close, min(200, len(close)))
        ema_200 = round(float(ema_200_val.iloc[-1]), 2)

        # -- Momentum --
        rsi_7 = fe.compute_rsi(close, 7)
        rsi_14 = fe.compute_rsi(close, 14)
        rsi_21 = fe.compute_rsi(close, 21)
        macd_val, macd_sig, macd_hist = fe.compute_macd(close)
        stoch_k, stoch_d = fe.compute_stochastic(high, low, close)
        roc_10 = 0.0
        if len(close) > 11:
            prev_price = float(close.iloc[-11])
            roc_10 = round(((current_price - prev_price) / prev_price) * 100, 4) if prev_price != 0 else 0

        # -- Volatility --
        atr = fe.compute_atr(high, low, close)
        bb_upper, bb_lower, bb_pct_b = fe.compute_bollinger(close)
        hist_vol = fe.compute_historical_volatility(close)

        # -- Volume --
        vol_avg_20 = float(volume.rolling(window=20).mean().iloc[-1])
        vol_current = float(volume.iloc[-1])
        vol_ratio = round(vol_current / vol_avg_20, 4) if vol_avg_20 > 0 else 1.0
        obv_slope = fe.compute_obv_slope(close, volume)

        # -- Trend Strength --
        adx = fe.compute_adx(high, low, close)

        # -- Statistical --
        z_score = fe.compute_z_score(close)
        hurst = fe.compute_hurst_exponent(close)

        # -- Fibonacci --
        fibs = fe.compute_fibonacci_levels(high, low)

        # -- Regression --
        reg_slope = fe.compute_linear_regression_slope(close)

        # -- News --
        news_sentiment, news_headlines, news_count = NewsEngine.fetch_and_score(symbol)

        # -- Regime --
        regime = RegimeDetector.detect(adx, hurst, hist_vol, ema_50, ema_200, current_price)

        # -- Build State --
        state = QuantState(
            symbol=symbol,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            current_price=current_price,
            prev_close=prev_close,
            daily_return_pct=daily_return,
            ema_9=ema_9, ema_21=ema_21, ema_50=ema_50, ema_200=ema_200,
            golden_cross=(ema_50 > ema_200),
            death_cross=(ema_50 < ema_200),
            rsi_7=rsi_7, rsi_14=rsi_14, rsi_21=rsi_21,
            macd=macd_val, macd_signal=macd_sig, macd_histogram=macd_hist,
            stochastic_k=stoch_k, stochastic_d=stoch_d,
            roc_10=roc_10,
            atr_14=atr,
            bollinger_upper=bb_upper, bollinger_lower=bb_lower, bollinger_pct_b=bb_pct_b,
            historical_vol_20=hist_vol,
            volume_ratio=vol_ratio, obv_slope=obv_slope,
            adx=adx,
            z_score_20=z_score, hurst_exponent=hurst,
            fib_levels=fibs,
            linear_reg_slope=reg_slope,
            news_sentiment=news_sentiment,
            news_headlines=news_headlines,
            news_count=news_count,
            regime=regime,
        )

        # -- Composite Score --
        composite, confidence = SignalAggregator.compute_composite(state)
        state.composite_score = composite
        state.confidence = confidence

        # -- Circuit Breaker --
        state.circuit_breaker = CircuitBreaker.check(state, df)

        # -- Signal & Risk --
        state.signal_label = RiskEngine.signal_label(composite, state.circuit_breaker)
        state.position_size_pct = RiskEngine.position_size_pct(composite, confidence, hist_vol)
        is_long = composite >= 0
        state.stop_loss, state.target_price = RiskEngine.compute_stops(current_price, atr, is_long)

        return state, df

    def llm_strategy(self, state: QuantState) -> str:
        """Feed the full quantitative matrix + news to the LLM for synthesis."""
        if not self.model:
            return "[LLM Unavailable] No Gemini API key configured."

        # Build headline block
        news_block = ""
        if state.news_headlines:
            news_block = "\n## NEWS INTELLIGENCE\n"
            news_block += f"Sentiment Score: {state.news_sentiment:+.2f} ({state.news_count} articles)\n"
            news_block += "Key Headlines:\n"
            for h in state.news_headlines[:5]:
                news_block += f"  • {h}\n"

        prompt = f"""You are a quantitative trading strategist at a top-tier proprietary trading firm.
Analyze the complete quantitative state for {state.symbol} as of {state.timestamp}.

## PRICE
Current: ₹{state.current_price} | Prev Close: ₹{state.prev_close} | Daily: {state.daily_return_pct:+.2f}%

## TREND
EMA 9/21/50/200: {state.ema_9}/{state.ema_21}/{state.ema_50}/{state.ema_200}
Golden Cross: {state.golden_cross} | ADX: {state.adx} | Reg Slope: {state.linear_reg_slope}

## MOMENTUM
RSI (7/14/21): {state.rsi_7}/{state.rsi_14}/{state.rsi_21}
MACD: {state.macd} | Signal: {state.macd_signal} | Histogram: {state.macd_histogram}
Stochastic %K/%D: {state.stochastic_k}/{state.stochastic_d} | ROC-10: {state.roc_10}%

## VOLATILITY
ATR-14: {state.atr_14} | Hist Vol (20d ann.): {state.historical_vol_20}
Bollinger: Upper={state.bollinger_upper} Lower={state.bollinger_lower} %B={state.bollinger_pct_b}

## VOLUME
Vol Ratio (vs 20d avg): {state.volume_ratio} | OBV Slope: {state.obv_slope}

## STATISTICAL
Z-Score (20d): {state.z_score_20} | Hurst: {state.hurst_exponent}

## FIBONACCI
{chr(10).join(f'{k}: ₹{v}' for k, v in state.fib_levels.items())}
{news_block}
## SYSTEM OUTPUT
Regime: {state.regime} | Composite: {state.composite_score}/100 | Confidence: {state.confidence}
Signal: {state.signal_label} | Circuit: {state.circuit_breaker}
Stop-Loss: ₹{state.stop_loss} | Target: ₹{state.target_price} | Position: {state.position_size_pct}%

---
INSTRUCTIONS:
1. Cross-validate quantitative signals AND news sentiment. Identify conflicts.
2. State the dominant narrative in 1 sentence.
3. Identify the single highest-risk factor.
4. FINAL VERDICT with conviction (LOW/MEDIUM/HIGH): [STRONG BUY|BUY|HOLD|SELL|STRONG SELL]
5. Specific stop-loss and target based on ATR + Fibonacci.
Keep response under 8 sentences. No fluff."""

        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            return f"[LLM Error] {str(e)}"

    def send_telegram(self, message: str):
        """Push alert via Telegram API."""
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            return

        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        # Telegram has a 4096 char limit per message
        msg = message[:4000]
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}
        try:
            r = requests.post(url, json=payload, timeout=15)
            if r.status_code == 200:
                console.print(f"  [green]→ Telegram alert sent[/green]")
            else:
                console.print(f"  [red]→ Telegram error {r.status_code}[/red]")
        except Exception as e:
            console.print(f"  [red]→ Telegram failed: {e}[/red]")

    def format_telegram_alert(self, state: QuantState, llm_text: str) -> str:
        """Format the full analysis for Telegram push."""
        alert = f"*AUTONOMOUS AGENT — {state.symbol}*\n"
        alert += f"📅 {state.timestamp}\n\n"

        chg_sign = "+" if state.daily_return_pct > 0 else ""
        alert += f"💰 *Price:* ₹{state.current_price} ({chg_sign}{state.daily_return_pct}%)\n"
        alert += f"📊 *Regime:* `{state.regime}`\n\n"

        alert += f"*— Quant Matrix —*\n"
        alert += f"RSI(14): {state.rsi_14} | MACD-H: {state.macd_histogram}\n"
        alert += f"ADX: {state.adx} | Hurst: {state.hurst_exponent}\n"
        alert += f"BB%B: {state.bollinger_pct_b} | Z: {state.z_score_20}\n"
        alert += f"Vol Ratio: {state.volume_ratio} | HistVol: {state.historical_vol_20}\n\n"

        if state.news_count > 0:
            alert += f"*— News —*\n"
            alert += f"Sentiment: {state.news_sentiment:+.2f} ({state.news_count} articles)\n"
            for h in state.news_headlines[:2]:
                alert += f"• {h[:60]}\n"
            alert += "\n"

        alert += f"*— Decision —*\n"
        alert += f"Composite: *{state.composite_score}*/100 | Conf: *{state.confidence}*\n"
        alert += f"Signal: *{state.signal_label}*\n"
        alert += f"Position: *{state.position_size_pct}%* | SL: ₹{state.stop_loss} | TP: ₹{state.target_price}\n"

        if state.circuit_breaker != "CLEAR":
            alert += f"\n⚠️ *Circuit Break:* {state.circuit_breaker}\n"

        alert += f"\n*— LLM Strategy —*\n{llm_text[:500]}"

        return alert

    def run_cycle(self):
        """Execute one full analysis cycle across all symbols."""
        console.print(f"\n{'=' * 60}")
        console.print(f"  [bold cyan]CYCLE START: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/bold cyan]")
        console.print(f"  [dim]Watchlist: {', '.join(self.symbols)}[/dim]")
        console.print(f"{'=' * 60}\n")

        all_states: List[QuantState] = []
        llm_outputs: Dict[str, str] = {}

        for symbol in self.symbols:
            console.print(f"[bold white]> {symbol}[/bold white] -- Building quantitative state...")

            result = self.build_quant_state(symbol)
            if result is None:
                console.print(f"  [red]x SKIPPED -- No data[/red]\n")
                continue

            state, df = result

            console.print(f"  [green]OK Composite: {state.composite_score:+.1f} | "
                          f"Signal: {state.signal_label} | "
                          f"Regime: {state.regime}[/green]")

            # LLM reasoning
            console.print(f"  [dim]-> Querying LLM for strategy synthesis...[/dim]")
            llm_text = self.llm_strategy(state)
            llm_outputs[symbol] = llm_text

            # Telegram push
            alert_msg = self.format_telegram_alert(state, llm_text)
            self.send_telegram(alert_msg)

            all_states.append(state)
            time.sleep(2)  # Rate limiting between symbols
            console.print()

        # -- Render Dashboard --
        if all_states:
            console.print(f"\n{'=' * 60}")
            console.print(f"  [bold cyan]DASHBOARD[/bold cyan]")
            console.print(f"{'=' * 60}")
            Dashboard.render_full(all_states, llm_outputs)

        console.print(f"\n{'=' * 60}")
        console.print(f"  [bold green]CYCLE COMPLETE -- {len(all_states)}/{len(self.symbols)} symbols analyzed[/bold green]")
        console.print(f"{'=' * 60}\n")


# ENTRY POINT
if __name__ == "__main__":
    # Watchlist — Blue-chip NSE
    WATCHLIST = ['RELIANCE.NS', 'TCS.NS', 'HDFCBANK.NS', 'INFY.NS', 'ICICIBANK.NS']

    agent = TradingAgent(WATCHLIST)

    console.print(Panel(
        Text.from_markup(
            "[bold bright_white]  Systematic Trading Agent[/bold bright_white]\n"
            "[dim]  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/dim]"
        ),
        border_style="bright_blue",
        box=box.ASCII,
    ))

    # Run single demo cycle
    agent.run_cycle()

    # -- For production: hourly cycles --
    # while True:
    #     agent.run_cycle()
    #     console.print("[dim]Sleeping 60 minutes until next cycle...[/dim]")
    #     time.sleep(3600)
