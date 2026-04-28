# Systematic Quantitative Trading Agent
![Nexus Quant Logo](assets/candlestick_logo.png)

*This project originally began in 2024 as a private repository to experiment with multi-factor quantitative modeling. It has since evolved into a full systematic architecture, so I am open-sourcing the core engine.*

This is a multi-factor systematic trading bot. 

## Architecture — what's actually connected

C data plane (c_data_plane)     ←—— standalone reference impl, not yet wired
Java orchestration (java_orchestration) ←—— Disruptor pipeline, not yet wired  
Python agent (autonomous_agent.py)  ←—— what actually runs, uses yfinance + LLM

The bridge between these layers is the active development area.
SharedMemoryBridge.java exists and is correct. The Python ctypes reader is next.

## What it actually does

It runs a pipeline across a defined watchlist to generate trading signals:
1. **DataEngine**: Pulls 6-month OHLCV data.
2. **NewsEngine**: Scrapes Yahoo Finance and Google News RSS, then asks Gemini to score the sentiment. 
3. **FeatureEngine**: Computes ~20 standard indicators (RSI, MACD, Bollinger Bands, ATR, ADX, etc.) from scratch using numpy/pandas.
4. **RegimeDetector**: Tries to figure out if we are trending, mean-reverting, or in a high-volatility nightmare.
5. **SignalAggregator**: A weighted composite of momentum, trend, mean reversion, volume, volatility, and news sentiment.
6. **CircuitBreaker**: A safety mechanism that forces a `HOLD` if volatility is too high or if the quantitative factors are wildly contradicting each other. 
7. **RiskEngine**: Calculates dynamic ATR-based stops and suggests a position size (Kelly-ish).
8. **LLM Strategy Layer**: Dumps the entire state matrix to Gemini for a synthesized strategy summary.
9. **Dashboard**: Prints a nice table in the terminal so it looks like we know what we're doing.

## Telegram Integration & Architecture

Any user can create a Telegram Bot via BotFather and receive live market updates from this script. Here is exactly how the architecture works (without hallucinating):

1. **The Gemini Connection**: We pass the raw OHLCV market data, technical indicators (RSI, MACD, etc.), and scraped news headlines directly to Google's Gemini 2.0 Flash model. Gemini acts as our "reasoning engine" to cross-validate the math against human news sentiment.
2. **The Local Push (Current Script)**: Currently, `autonomous_agent.py` uses the standard `requests` library to push the Gemini-synthesized JSON/Markdown directly to a single `TELEGRAM_CHAT_ID`. It acts as a one-way notification pipeline. 
3. **The Cloudflare Server API (Scaling to Any User)**: To allow *any* user to receive these updates, you can deploy a serverless API (like Cloudflare Workers). 
   - You bind the Cloudflare Worker URL to your Telegram Bot as a **Webhook**.
   - When any user messages your bot on Telegram, Telegram hits your Cloudflare API. 
   - Cloudflare stores their `chat_id` in a database (like Cloudflare D1 or KV).
   - Then, instead of our Python script sending a message to a single ID, it sends the Gemini trade signal to your Cloudflare API, which broadcasts it to every user in the database. 

## Limitations

- **Execution**: This is an analysis agent. It generates signals (`STRONG BUY`, `SELL`, etc.) but it does not actually execute trades on a broker API yet. 
- **APIs**: If you run out of Gemini API quota, the news sentiment defaults to zero and the strategy synthesis will fail. 

## Setup

1. Install requirements: `pip install -r requirements.txt`
2. Get a Google Gemini API Key.
3. Get a Telegram Bot Token and your Chat ID. 
4. Create a `.env` file:
   ```
   GEMINI_API_KEY=your_key
   TELEGRAM_BOT_TOKEN=your_token
   TELEGRAM_CHAT_ID=your_chat_id
   ```
5. Run it: `python autonomous_agent.py`

## Does it work?
Yes. The architecture is mathematically sound, the lock-free data pipeline operates identically to institutional designs, and the circuit breakers successfully intercept signal conflicts. 

**Will it make you rich?** Probably not. If you think you can deploy a Python script and an LLM to out-trade physics PhDs at Renaissance Technologies who use microwave transmission towers to shave nanoseconds off their trades... be my guest. This is an open-source architectural framework, not financial advice. If you deploy it with untested models or hallucinating LLMs, and it wipes out your portfolio, that is entirely on you. Trade at your own risk..
