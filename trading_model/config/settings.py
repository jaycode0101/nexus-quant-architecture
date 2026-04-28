import os

from dotenv import load_dotenv

load_dotenv()


def _csv_env(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


# Provider keys. Fill only the services used by your local setup.
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")

# Market configuration. Replace these with any instruments your data provider
# and broker adapter understand.
MARKET = os.getenv("MARKET", "equities")
WATCHLIST = _csv_env("WATCHLIST", "SPY,QQQ,BTC-USD,AAPL,MSFT")
SESSION_OPEN = os.getenv("SESSION_OPEN", "09:30")
SESSION_CLOSE = os.getenv("SESSION_CLOSE", "16:00")
SESSION_TZ = os.getenv("SESSION_TZ", "UTC")

# Cost model. Keep these boring and explicit; strategy results are useless when
# costs are hidden in prose.
COMMISSION_BPS = float(os.getenv("COMMISSION_BPS", "5"))
SLIPPAGE_BPS = float(os.getenv("SLIPPAGE_BPS", "2"))

TECHNICAL_INDICATORS = {
    "RSI": {"period": 14},
    "MACD": {"fast": 12, "slow": 26, "signal": 9},
    "Bollinger": {"period": 20, "std_dev": 2},
    "ATR": {"period": 14},
}

NEWS_SOURCES = _csv_env("NEWS_SOURCES", "rss,provider_search")

SENTIMENT_THRESHOLD = float(os.getenv("SENTIMENT_THRESHOLD", "0.2"))

MAX_POSITION_SIZE = float(os.getenv("MAX_POSITION_SIZE", "0.1"))
STOP_LOSS_PERCENTAGE = float(os.getenv("STOP_LOSS_PERCENTAGE", "0.02"))
TAKE_PROFIT_PERCENTAGE = float(os.getenv("TAKE_PROFIT_PERCENTAGE", "0.04"))
