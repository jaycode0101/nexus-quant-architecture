import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# API Keys
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
NEWS_API_KEY = os.getenv('NEWS_API_KEY')

# Market Settings
NSE_SYMBOLS = [
    'NIFTY', 'BANKNIFTY', 'FINNIFTY', 'RELIANCE', 'TCS', 'HDFCBANK',
    'INFY', 'ICICIBANK', 'HINDUNILVR', 'SBIN'
]

# Technical Analysis Settings
TECHNICAL_INDICATORS = {
    'RSI': {'period': 14},
    'MACD': {'fast': 12, 'slow': 26, 'signal': 9},
    'Bollinger': {'period': 20, 'std_dev': 2},
    'ATR': {'period': 14}
}

# News Analysis Settings
NEWS_SOURCES = [
    'moneycontrol.com',
    'economictimes.indiatimes.com',
    'livemint.com',
    'ndtv.com/business'
]

# Sentiment Analysis Settings
SENTIMENT_THRESHOLD = 0.2  # Threshold for considering sentiment significant

# Risk Management Settings
MAX_POSITION_SIZE = 0.1  # Maximum position size as fraction of portfolio
STOP_LOSS_PERCENTAGE = 0.02  # 2% stop loss
TAKE_PROFIT_PERCENTAGE = 0.04  # 4% take profit 