import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import time
import requests
from bs4 import BeautifulSoup
import json
import pytz
from textblob import TextBlob
import nltk
from nltk.sentiment import SentimentIntensityAnalyzer
import os
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
import asyncio
from playwright.async_api import async_playwright
from playwright.sync_api import sync_playwright
import google.generativeai as genai

# Set page config first
st.set_page_config(layout="wide", page_title="Trading Dashboard")

# Download required NLTK data
nltk.download('vader_lexicon')

# Initialize Gemini API
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-pro')

# Add custom CSS for smooth number transitions and timestamp
st.markdown("""
    <style>
    .price-change {
        transition: all 0.5s ease;
    }
    .price-up {
        color: #00ff00;
        animation: fadeIn 0.5s;
    }
    .price-down {
        color: #ff0000;
        animation: fadeIn 0.5s;
    }
    .timestamp {
        font-size: 0.8em;
        color: #666;
        text-align: right;
        margin-top: 5px;
    }
    @keyframes fadeIn {
        from { opacity: 0; }
        to { opacity: 1; }
    }
    @keyframes rollNumber {
        0% { transform: translateY(20px); opacity: 0; }
        100% { transform: translateY(0); opacity: 1; }
    }
    .price-change span {
        display: inline-block;
        animation: rollNumber 0.5s ease-out;
    }
    </style>
    """, unsafe_allow_html=True)

# Title
st.title("📈 Indian Stock Market Analysis Dashboard")
st.markdown("---")

# Define stocks dictionary first
stocks = {
    'SENSEX': '^BSESN',  # Sensex Index
    'NIFTY 50': '^NSEI',  # Nifty 50 Index
    'GOLD': 'GC=F',  # Gold Futures
    'BITCOIN': 'BTC-USD',  # Bitcoin
    'USD/INR': 'INR=X',  # USD/INR Forex
    'RELIANCE': 'RELIANCE.NS',
    'TCS': 'TCS.NS',
    'HDFC Bank': 'HDFCBANK.NS',
    'Infosys': 'INFY.NS',
    'ICICI Bank': 'ICICIBANK.NS',
    'Wipro': 'WIPRO.NS',
    'Tata Motors': 'TATAMOTORS.NS',
    'Bharti Airtel': 'BHARTIARTL.NS',
    'Axis Bank': 'AXISBANK.NS',
    'Kotak Bank': 'KOTAKBANK.NS',
    'Larsen & Toubro': 'LT.NS',
    'ITC': 'ITC.NS',
    'Asian Paints': 'ASIANPAINT.NS',
    'Maruti Suzuki': 'MARUTI.NS',
    'Sun Pharma': 'SUNPHARMA.NS',
    'Titan': 'TITAN.NS',
    'Nestle': 'NESTLEIND.NS',
    'ONGC': 'ONGC.NS',
    'Power Grid': 'POWERGRID.NS',
    'NTPC': 'NTPC.NS'
}

# Create two columns for layout
main_col, ticker_col = st.columns([3, 1])

with ticker_col:
    st.markdown("### 📊 Live Prices")
    st.markdown("---")
    
    # Only keep Sensex for live updates
    live_stocks = {
        'SENSEX': '^BSESN'
    }
    
    # Initialize session state for prices if it doesn't exist
    if 'prices' not in st.session_state:
        st.session_state.prices = {}
    if 'last_update' not in st.session_state:
        st.session_state.last_update = 0
    
    def get_live_price(symbol):
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            
            # Get the most recent data
            price = info.get('regularMarketPrice')
            prev_close = info.get('regularMarketPreviousClose')
            
            # Calculate percentage change safely
            if price and prev_close and prev_close != 0:
                change = ((price - prev_close) / prev_close) * 100
            else:
                change = 0
            
            return price or 0, change
        except Exception as e:
            st.error(f"Error fetching price: {str(e)}")
            return 0, 0
    
    # Create a placeholder for live prices
    price_container = st.empty()
    
    def update_prices():
        new_prices = {}
        for name, symbol in live_stocks.items():
            price, change = get_live_price(symbol)
            if price > 0:  # Only update if we got a valid price
                new_prices[name] = (price, change)
        return new_prices
    
    # Function to format price display
    def format_price_display(name, price, change):
        if price <= 0:  # Don't display invalid prices
            return ""
        
        color_class = "price-up" if change >= 0 else "price-down"
        return f"""
            <div class="price-change {color_class}" style="margin-bottom: 10px;">
                <b>{name}</b><br>
                <span>₹{price:,.2f} ({change:+.2f}%)</span>
            </div>
        """
    
    # Auto-refresh logic using JavaScript
    st.markdown("""
        <script>
            function updatePrice() {
                const priceContainer = document.getElementById('price-container');
                fetch('/update_price')
                    .then(response => response.json())
                    .then(data => {
                        priceContainer.innerHTML = data.html;
                    });
            }
            setInterval(updatePrice, 5000);
        </script>
    """, unsafe_allow_html=True)
    
    # Display prices
    price_text = ""
    for name, (price, change) in st.session_state.prices.items():
        if price > 0:  # Only display if we have a valid price
            price_text += format_price_display(name, price, change)
    
    # Add timestamp
    ist = pytz.timezone('Asia/Kolkata')
    current_time_ist = datetime.now(ist).strftime('%H:%M:%S')
    price_text += f'<div class="timestamp">Last updated: {current_time_ist} IST</div>'
    
    # Render the markdown within the container
    price_container.markdown(price_text, unsafe_allow_html=True)
    
    # Update prices every 5 seconds without refreshing the page
    if time.time() - st.session_state.last_update > 5:
        try:
            new_prices = update_prices()
            if new_prices:  # Only update if we got valid prices
                st.session_state.prices = new_prices
                st.session_state.last_update = time.time()
        except Exception as e:
            st.error(f"Error updating prices: {e}")

with main_col:
    # Sidebar
    st.sidebar.title("Settings")

    selected_stock = st.sidebar.selectbox(
        "Select Stock",
        list(stocks.keys())
    )

    # Time period selection
    period = st.sidebar.selectbox(
        "Select Time Period",
        ['1mo', '3mo', '6mo', '1y', '2y', '5y']
    )

    # Analysis type
    analysis_type = st.sidebar.multiselect(
        "Select Analysis Types",
        ['Moving Averages', 'Volume Analysis', 'Price Trends', 'Support/Resistance',
         'RSI', 'MACD', 'Bollinger Bands', 'Stochastic Oscillator', 'ATR'],
        default=['Moving Averages', 'Volume Analysis']
    )

    def calculate_rsi(data, period=14):
        """Calculate RSI technical indicator"""
        delta = data['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    def calculate_macd(data, fast=12, slow=26, signal=9):
        """Calculate MACD technical indicator"""
        exp1 = data['Close'].ewm(span=fast, adjust=False).mean()
        exp2 = data['Close'].ewm(span=slow, adjust=False).mean()
        macd = exp1 - exp2
        signal_line = macd.ewm(span=signal, adjust=False).mean()
        return macd, signal_line

    def calculate_bollinger_bands(data, period=20, std_dev=2):
        """Calculate Bollinger Bands"""
        sma = data['Close'].rolling(window=period).mean()
        std = data['Close'].rolling(window=period).std()
        upper_band = sma + (std * std_dev)
        lower_band = sma - (std * std_dev)
        return upper_band, sma, lower_band

    def calculate_atr(data, period=14):
        """Calculate Average True Range"""
        high = data['High']
        low = data['Low']
        close = data['Close']
        
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(window=period).mean()

    def calculate_moving_averages(data):
        """Calculate moving averages"""
        data['SMA20'] = data['Close'].rolling(window=20).mean()
        data['SMA50'] = data['Close'].rolling(window=50).mean()
        data['SMA200'] = data['Close'].rolling(window=200).mean()
        return data

    def detect_manipulation(data):
        """Detect potential market manipulation patterns"""
        patterns = []
        
        # Volume analysis
        avg_volume = data['Volume'].mean()
        recent_volume = data['Volume'].iloc[-1]
        volume_ratio = recent_volume / avg_volume
        
        if volume_ratio > 3:
            patterns.append({
                'type': 'Volume Spike',
                'description': f'Unusual volume spike: {volume_ratio:.1f}x average',
                'severity': 'High'
            })
        
        # Price analysis
        price_change = (data['Close'].iloc[-1] - data['Open'].iloc[-1]) / data['Open'].iloc[-1] * 100
        if abs(price_change) > 5:
            patterns.append({
                'type': 'Price Gap',
                'description': f'Significant price gap: {price_change:.2f}%',
                'severity': 'Medium'
            })
        
        # Volatility analysis
        atr = calculate_atr(data)
        current_atr = atr.iloc[-1]
        avg_atr = atr.mean()
        if current_atr > avg_atr * 2:
            patterns.append({
                'type': 'Volatility Spike',
                'description': f'Unusual volatility: {current_atr:.2f} vs avg {avg_atr:.2f}',
                'severity': 'Medium'
            })
        
        return patterns

    # Add Nifty 50 specific analysis
    def analyze_nifty(data):
        """Analyze Nifty 50 specific patterns and indicators"""
        analysis = {}
        
        # Calculate daily returns
        data['Returns'] = data['Close'].pct_change()
        
        # Volatility analysis
        analysis['Volatility'] = data['Returns'].std() * np.sqrt(252)  # Annualized volatility
        
        # Trend analysis
        analysis['Trend'] = 'Bullish' if data['Close'].iloc[-1] > data['Close'].iloc[-20] else 'Bearish'
        
        # Support and Resistance levels
        analysis['Support'] = data['Low'].rolling(window=20).min().iloc[-1]
        analysis['Resistance'] = data['High'].rolling(window=20).max().iloc[-1]
        
        # Market breadth (if available)
        if 'Volume' in data.columns:
            analysis['Volume_Trend'] = 'Increasing' if data['Volume'].iloc[-1] > data['Volume'].iloc[-5:].mean() else 'Decreasing'
        
        return analysis

    # Add Sensex specific analysis
    def analyze_sensex(data):
        """Analyze Sensex specific patterns and indicators"""
        analysis = {}
        
        # Calculate daily returns
        data['Returns'] = data['Close'].pct_change()
        
        # Volatility analysis
        analysis['Volatility'] = data['Returns'].std() * np.sqrt(252)  # Annualized volatility
        
        # Trend analysis
        analysis['Trend'] = 'Bullish' if data['Close'].iloc[-1] > data['Close'].iloc[-20] else 'Bearish'
        
        # Support and Resistance levels
        analysis['Support'] = data['Low'].rolling(window=20).min().iloc[-1]
        analysis['Resistance'] = data['High'].rolling(window=20).max().iloc[-1]
        
        # Market breadth (if available)
        if 'Volume' in data.columns:
            analysis['Volume_Trend'] = 'Increasing' if data['Volume'].iloc[-1] > data['Volume'].iloc[-5:].mean() else 'Decreasing'
        
        return analysis

    # Add commodity and crypto analysis
    def analyze_commodity_crypto(data, asset_type):
        """Analyze commodity and crypto specific patterns and indicators"""
        analysis = {}
        
        # Calculate daily returns
        data['Returns'] = data['Close'].pct_change()
        
        # Volatility analysis
        analysis['Volatility'] = data['Returns'].std() * np.sqrt(252)  # Annualized volatility
        
        # Trend analysis
        analysis['Trend'] = 'Bullish' if data['Close'].iloc[-1] > data['Close'].iloc[-20] else 'Bearish'
        
        # Support and Resistance levels
        analysis['Support'] = data['Low'].rolling(window=20).min().iloc[-1]
        analysis['Resistance'] = data['High'].rolling(window=20).max().iloc[-1]
        
        # Asset specific analysis
        if asset_type == 'GOLD':
            # Gold specific metrics
            analysis['Safe_Haven'] = 'Yes' if data['Returns'].std() < 0.015 else 'No'
            analysis['Correlation'] = 'Negative' if data['Returns'].corr(data['Close'].pct_change()) < 0 else 'Positive'
        elif asset_type == 'BITCOIN':
            # Bitcoin specific metrics
            analysis['Market_Cap'] = 'High' if data['Volume'].iloc[-1] > data['Volume'].mean() * 1.5 else 'Normal'
            analysis['Volatility_Status'] = 'High' if analysis['Volatility'] > 0.5 else 'Normal'
        elif asset_type == 'USD/INR':
            # Forex specific metrics
            analysis['Exchange_Rate_Trend'] = 'Appreciating' if data['Close'].iloc[-1] > data['Close'].iloc[-5:].mean() else 'Depreciating'
            analysis['Volatility_Status'] = 'High' if analysis['Volatility'] > 0.02 else 'Normal'
        
        return analysis

    def detect_sideways_market(data, threshold=0.02):  # 2% threshold for sideways movement
        """Detect how long the market has been moving sideways"""
        try:
            # Calculate the range of prices
            high = data['High'].iloc[-20:]  # Last 20 days
            low = data['Low'].iloc[-20:]
            
            # Calculate the percentage range
            price_range = (high.max() - low.min()) / low.min()
            
            # If range is less than threshold, market is sideways
            if price_range <= threshold:
                # Count consecutive days in sideways movement
                sideways_days = 0
                for i in range(len(data)-1, 0, -1):
                    day_range = (data['High'].iloc[i] - data['Low'].iloc[i]) / data['Low'].iloc[i]
                    if day_range <= threshold:
                        sideways_days += 1
                    else:
                        break
                
                return True, sideways_days
            return False, 0
        except:
            return False, 0

    def analyze_stock(data):
        """Comprehensive stock analysis with recommendations"""
        analysis = {}
        
        # Calculate key metrics
        current_price = data['Close'].iloc[-1]
        sma20 = data['SMA20'].iloc[-1]
        sma50 = data['SMA50'].iloc[-1]
        rsi = data['RSI'].iloc[-1]
        macd = data['MACD'].iloc[-1]
        signal_line = data['Signal'].iloc[-1]
        bb_upper = data['BB_Upper'].iloc[-1]
        bb_lower = data['BB_Lower'].iloc[-1]
        volume = data['Volume'].iloc[-1]
        avg_volume = data['Volume'].rolling(window=20).mean().iloc[-1]
        
        # Check for sideways market
        is_sideways, sideways_days = detect_sideways_market(data)
        
        # Trend Analysis
        short_trend = "Bullish" if current_price > sma20 else "Bearish"
        long_trend = "Bullish" if current_price > sma50 else "Bearish"
        
        # Volume Analysis
        volume_trend = "High" if volume > avg_volume * 1.5 else "Normal" if volume > avg_volume else "Low"
        
        # Technical Indicators Analysis
        rsi_signal = "Oversold" if rsi < 30 else "Overbought" if rsi > 70 else "Neutral"
        macd_signal = "Bullish" if macd > signal_line else "Bearish"
        bb_signal = "Overbought" if current_price > bb_upper else "Oversold" if current_price < bb_lower else "Neutral"
        
        # Calculate Support and Resistance
        support = data['Low'].rolling(window=20).min().iloc[-1]
        resistance = data['High'].rolling(window=20).max().iloc[-1]
        
        # Determine Trading Signal
        signal_score = 0
        
        # Trend Score
        if short_trend == "Bullish" and long_trend == "Bullish":
            signal_score += 2
        elif short_trend == "Bearish" and long_trend == "Bearish":
            signal_score -= 2
        
        # RSI Score
        if rsi_signal == "Oversold":
            signal_score += 1
        elif rsi_signal == "Overbought":
            signal_score -= 1
        
        # MACD Score
        if macd_signal == "Bullish":
            signal_score += 1
        else:
            signal_score -= 1
        
        # Bollinger Bands Score
        if bb_signal == "Oversold":
            signal_score += 1
        elif bb_signal == "Overbought":
            signal_score -= 1
        
        # Volume Score
        if volume_trend == "High" and short_trend == "Bullish":
            signal_score += 1
        elif volume_trend == "High" and short_trend == "Bearish":
            signal_score -= 1
        
        # Calculate target prices and exit strategy
        atr = data['ATR'].iloc[-1]
        
        # Calculate target prices based on ATR
        target_1 = current_price + (atr * 1.5)  # First target
        target_2 = current_price + (atr * 3)    # Second target
        stop_loss = current_price - (atr * 1.5)  # Stop loss
        
        # Determine exit strategy based on signal
        if signal_score >= 3:  # Strong Buy
            exit_strategy = f"Hold until ₹{target_2:,.2f} or if price drops below ₹{stop_loss:,.2f}"
        elif signal_score == 2:  # Buy
            exit_strategy = f"Take partial profits at ₹{target_1:,.2f}, hold rest until ₹{target_2:,.2f}"
        elif signal_score == 1:  # Weak Buy
            exit_strategy = f"Take profits at ₹{target_1:,.2f}, stop loss at ₹{stop_loss:,.2f}"
        elif signal_score == 0:  # Hold
            exit_strategy = "Wait for better entry point, no position recommended"
        elif signal_score == -1:  # Weak Sell
            exit_strategy = f"Consider reducing position, stop loss at ₹{stop_loss:,.2f}"
        elif signal_score == -2:  # Sell
            exit_strategy = "Consider exiting position, market showing weakness"
        else:  # Strong Sell
            exit_strategy = "Immediate exit recommended, market showing strong bearish signals"
        
        # Determine Final Signal
        if signal_score >= 3:
            signal = "STRONG BUY"
            hold_duration = "Short-term (1-2 weeks)"
        elif signal_score == 2:
            signal = "BUY"
            hold_duration = "Medium-term (2-4 weeks)"
        elif signal_score == 1:
            signal = "WEAK BUY"
            hold_duration = "Short-term (1 week)"
        elif signal_score == 0:
            signal = "HOLD"
            hold_duration = "Wait for better entry"
        elif signal_score == -1:
            signal = "WEAK SELL"
            hold_duration = "Consider reducing position"
        elif signal_score == -2:
            signal = "SELL"
            hold_duration = "Medium-term (2-4 weeks)"
        else:
            signal = "STRONG SELL"
            hold_duration = "Immediate action recommended"
        
        # Compile Analysis
        analysis = {
            'Signal': signal,
            'Hold Duration': hold_duration,
            'Current Price': current_price,
            'Trend': {
                'Short Term': short_trend,
                'Long Term': long_trend,
                'Sideways': is_sideways,
                'Sideways Days': sideways_days
            },
            'Technical Indicators': {
                'RSI': f"{rsi:.2f} ({rsi_signal})",
                'MACD': macd_signal,
                'Bollinger Bands': bb_signal
            },
            'Volume': volume_trend,
            'Support': support,
            'Resistance': resistance,
            'Signal Score': signal_score,
            'Exit Strategy': exit_strategy,
            'Target Prices': {
                'First Target': target_1,
                'Second Target': target_2,
                'Stop Loss': stop_loss
            }
        }
        
        return analysis

    def fetch_news(symbol, days=7):
        """Fetch and analyze news using Gemini API"""
        try:
            # Get company name and clean it
            company_name = symbol.split('.')[0] if '.' in symbol else symbol
            company_name = company_name.replace('^', '')  # Remove ^ from indices
            
            # Create search query
            query = f"Latest news about {company_name} stock market performance and trading in the last {days} days"
            
            # Get response from Gemini
            response = model.generate_content(query)
            
            if not response or not response.text:
                st.warning("No news data available from Gemini API")
                return []
            
            # Process the response into structured news articles
            articles = []
            news_text = response.text
            
            # Split the response into individual news items
            news_items = news_text.split('\n\n')
            
            for item in news_items:
                if len(item.strip()) > 50:  # Only process substantial news items
                    try:
                        # Extract date if present
                        date = None
                        if ' - ' in item:
                            text, date_str = item.split(' - ', 1)
                        else:
                            text = item
                        
                        articles.append({
                            'title': text.split('\n')[0] if '\n' in text else text[:100],
                            'description': text,
                            'publishedAt': date if date else datetime.now().strftime("%Y-%m-%d"),
                            'source': {'name': 'Gemini AI'},
                            'url': '#',  # No direct URL available
                            'relevance_score': 1.0  # Default relevance score
                        })
                    except Exception as e:
                        continue
            
            return articles[:10]  # Return top 10 news items
            
        except Exception as e:
            st.error(f"Error fetching news from Gemini: {str(e)}")
            return []

    def analyze_news_sentiment(articles):
        """Analyze sentiment of news articles using NLTK"""
        sia = SentimentIntensityAnalyzer()
        sentiments = []
        
        for article in articles:
            try:
                # Combine title and description for analysis
                text = f"{article['title']} {article['description']}"
                
                # Basic text validation
                if not text or len(text.strip()) < 10:
                    continue
                    
                # Get sentiment scores
                sentiment = sia.polarity_scores(text)
                
                # Validate sentiment scores
                if not all(key in sentiment for key in ['neg', 'neu', 'pos', 'compound']):
                    continue
                    
                # Calculate confidence score
                confidence = abs(sentiment['compound'])
                
                # Only include articles with meaningful sentiment
                if confidence > 0.1:  # Minimum sentiment threshold
                    sentiments.append({
                        'title': article['title'],
                        'description': article['description'],
                        'url': article['url'],
                        'publishedAt': article['publishedAt'],
                        'sentiment': sentiment,
                        'source': article['source']['name'],
                        'relevance_score': article.get('relevance_score', 0),
                        'confidence': confidence
                    })
            except Exception as e:
                continue  # Skip articles with processing errors
        
        return sentiments

    def calculate_news_score(sentiments):
        """Calculate weighted news sentiment score"""
        if not sentiments:
            return 0
        
        # Calculate weighted average based on relevance and confidence
        total_weight = 0
        weighted_score = 0
        
        for sentiment in sentiments:
            weight = sentiment['relevance_score'] * sentiment['confidence']
            weighted_score += sentiment['sentiment']['compound'] * weight
            total_weight += weight
        
        if total_weight == 0:
            return 0
        
        return weighted_score / total_weight

    def get_news_recommendation(news_score):
        """Get trading recommendation based on news sentiment with confidence levels"""
        if news_score >= 0.5:
            return "STRONG BUY", "Very positive news sentiment with high confidence"
        elif news_score >= 0.2:
            return "BUY", "Positive news sentiment"
        elif news_score >= -0.2:
            return "HOLD", "Neutral news sentiment"
        elif news_score >= -0.5:
            return "SELL", "Negative news sentiment"
        else:
            return "STRONG SELL", "Very negative news sentiment with high confidence"

    def fetch_nse_oi_data(symbol):
        """Fixed NSE Nifty 50 OI Data Scraper with proper error handling"""
        try:
            if symbol != '^NSEI':
                st.warning("Open Interest analysis is currently only available for Nifty 50")
                return None

            # First try the API approach (more reliable)
            st.info("Attempting to fetch data via NSE API...")
            api_data = fetch_nse_api_data()
            
            if api_data:
                return process_api_data(api_data)
            
            # Fallback to browser scraping
            st.info("API approach failed, trying browser scraping...")
            browser_data = fetch_via_browser()
            
            if browser_data:
                return process_api_data(browser_data)
                
            # If both methods fail, try one last time with a different approach
            st.info("Trying alternative approach...")
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    page = browser.new_page()
                    
                    # Set headers
                    page.set_extra_http_headers({
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                        'Accept': 'application/json, text/plain, */*',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Accept-Encoding': 'gzip, deflate, br',
                        'Connection': 'keep-alive'
                    })
                    
                    # Visit NSE website first
                    page.goto('https://www.nseindia.com/', wait_until='networkidle')
                    page.wait_for_timeout(5000)  # Wait for 5 seconds
                    
                    # Navigate to option chain
                    page.goto('https://www.nseindia.com/option-chain', wait_until='networkidle')
                    page.wait_for_timeout(5000)  # Wait for 5 seconds
                    
                    # Try to intercept the API response
                    response = page.wait_for_response(
                        lambda response: 'option-chain' in response.url and response.status == 200,
                        timeout=30000
                    )
                    
                    if response:
                        data = response.json()
                        browser.close()
                        return process_api_data(data)
                    
                    browser.close()
                    return None
                    
            except Exception as e:
                st.error(f"Alternative approach failed: {str(e)}")
                return None
                
        except Exception as e:
            st.error(f"Error in main function: {str(e)}")
            return None

    def fetch_nse_api_data():
        """Try to fetch data directly from NSE API with improved headers and session handling"""
        try:
            session = requests.Session()
            
            # Essential headers to mimic browser
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Cache-Control': 'max-age=0',
                'sec-ch-ua': '"Not A(Brand";v="99", "Google Chrome";v="131", "Chromium";v="131"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"'
            }
            
            session.headers.update(headers)
            
            # Step 1: Visit main page to get cookies
            st.info("Establishing session with NSE...")
            response = session.get('https://www.nseindia.com/', timeout=30)
            if response.status_code != 200:
                st.warning("Failed to establish session with NSE")
                return None
                
            time.sleep(5)  # Increased wait time
            
            # Step 2: Visit option chain page to get more cookies
            session.headers.update({
                'Referer': 'https://www.nseindia.com/',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            })
            
            response = session.get('https://www.nseindia.com/option-chain', timeout=30)
            time.sleep(5)  # Increased wait time
            
            # Step 3: Try to fetch option chain data
            session.headers.update({
                'Accept': 'application/json, text/plain, */*',
                'Referer': 'https://www.nseindia.com/option-chain',
                'X-Requested-With': 'XMLHttpRequest',
                'sec-ch-ua': '"Not A(Brand";v="99", "Google Chrome";v="131", "Chromium";v="131"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"'
            })
            
            # Known NSE API endpoints for Nifty option chain
            api_urls = [
                'https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY',
                'https://www.nseindia.com/api/option-chain-equities?symbol=NIFTY',
                'https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY&expiryDate=',
                'https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY&date='
            ]
            
            for url in api_urls:
                try:
                    st.info(f"Trying API endpoint: {url}")
                    response = session.get(url, timeout=30)
                    
                    if response.status_code == 200:
                        try:
                            data = response.json()
                            if data and 'records' in data and data['records']:
                                st.success("Successfully fetched data from NSE API!")
                                return data
                            else:
                                st.warning("API returned empty data")
                        except json.JSONDecodeError as e:
                            st.warning(f"Failed to parse JSON response: {str(e)}")
                            # Save response for debugging
                            st.text("Response content:")
                            st.text(response.text[:500])  # Show first 500 chars
                    else:
                        st.warning(f"API returned status code: {response.status_code}")
                        
                except Exception as e:
                    st.warning(f"Failed to fetch from {url}: {str(e)}")
                    continue
            
            return None
            
        except Exception as e:
            st.error(f"Error in API fetch: {str(e)}")
            return None

    def process_api_data(data):
        """Process the API data and return structured OI data"""
        try:
            if not data or 'records' not in data:
                st.error("Invalid API data structure")
                return None
                
            records = data['records']
            
            # Get current price and other metadata
            current_price = None
            if 'underlyingValue' in records:
                current_price = float(records['underlyingValue'])
            
            # Get expiry date
            expiry_date = records.get('expiryDates', [None])[0] if records.get('expiryDates') else None
            
            # Process option chain data
            option_data = records.get('data', [])
            
            if not option_data:
                st.error("No option chain data found in API response")
                return None
            
            calls_data = []
            puts_data = []
            
            for item in option_data:
                strike_price = item.get('strikePrice', 0)
                
                # Process Call options
                if 'CE' in item:
                    ce_data = item['CE']
                    calls_data.append({
                        'strike': strike_price,
                        'oi': ce_data.get('openInterest', 0),
                        'change_oi': ce_data.get('changeinOpenInterest', 0),
                        'volume': ce_data.get('totalTradedVolume', 0),
                        'last_price': ce_data.get('lastPrice', 0),
                        'bid': ce_data.get('bidprice', 0),
                        'ask': ce_data.get('askPrice', 0),
                        'iv': ce_data.get('impliedVolatility', 0)
                    })
                
                # Process Put options
                if 'PE' in item:
                    pe_data = item['PE']
                    puts_data.append({
                        'strike': strike_price,
                        'oi': pe_data.get('openInterest', 0),
                        'change_oi': pe_data.get('changeinOpenInterest', 0),
                        'volume': pe_data.get('totalTradedVolume', 0),
                        'last_price': pe_data.get('lastPrice', 0),
                        'bid': pe_data.get('bidprice', 0),
                        'ask': pe_data.get('askPrice', 0),
                        'iv': pe_data.get('impliedVolatility', 0)
                    })
            
            # Create DataFrames
            calls_df = pd.DataFrame(calls_data) if calls_data else pd.DataFrame()
            puts_df = pd.DataFrame(puts_data) if puts_data else pd.DataFrame()
            
            # Validate DataFrames
            if calls_df.empty or puts_df.empty:
                st.error("No valid call or put options data found")
                return None
            
            # Display the data
            display_option_chain_data(calls_df, puts_df, current_price, expiry_date)
            
            # Calculate analysis metrics safely
            return calculate_oi_analysis(calls_df, puts_df, current_price, expiry_date)
            
        except Exception as e:
            st.error(f"Error processing API data: {str(e)}")
            return None

    def fetch_via_browser():
        """Fallback browser-based scraping method with improved security handling"""
        try:
            st.info("Initializing browser...")
            
            options = uc.ChromeOptions()
            options.add_argument('--headless')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            options.add_argument('--window-size=1920,1080')
            options.add_argument('--disable-blink-features=AutomationControlled')
            options.add_argument('--disable-notifications')
            options.add_argument('--disable-popup-blocking')
            options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')
            
            # Add additional preferences to make browser more stealthy
            options.add_experimental_option('excludeSwitches', ['enable-automation'])
            options.add_experimental_option('useAutomationExtension', False)
            
            driver = uc.Chrome(version_main=131, options=options)
            driver.set_page_load_timeout(120)
            
            try:
                # Visit NSE website
                st.info("Accessing NSE website...")
                driver.get("https://www.nseindia.com")
                time.sleep(10)  # Increased wait time
                
                # Execute JavaScript to modify navigator properties
                driver.execute_script("""
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                """)
                
                # Navigate to option chain
                st.info("Loading option chain page...")
                driver.get("https://www.nseindia.com/option-chain")
                
                # Wait for page to load
                wait = WebDriverWait(driver, 120)
                wait.until(lambda d: d.execute_script('return document.readyState') == 'complete')
                time.sleep(25)  # Increased wait time
                
                # Try to get data from browser's network/memory
                browser_data = driver.execute_script("""
                    // Try to find option chain data in various locations
                    function findOptionData() {
                        // Check window object for data
                        if (window.optionChainData) return window.optionChainData;
                        if (window.nseData) return window.nseData;
                        
                        // Check for NEXT_DATA (if it's a Next.js app)
                        if (window.__NEXT_DATA__) {
                            const nextData = window.__NEXT_DATA__;
                            if (nextData.props && nextData.props.pageProps) {
                                return nextData.props.pageProps;
                            }
                        }
                        
                        // Try to find data in script tags
                        const scripts = document.querySelectorAll('script');
                        for (let script of scripts) {
                            const content = script.textContent;
                            if (content.includes('optionChain') || content.includes('NIFTY')) {
                                try {
                                    const jsonMatch = content.match(/({.*})/);
                                    if (jsonMatch) {
                                        const data = JSON.parse(jsonMatch[1]);
                                        if (data.records || data.data) {
                                            return data;
                                        }
                                    }
                                } catch (e) {
                                    // Continue searching
                                }
                            }
                        }
                        
                        // Try to intercept fetch requests
                        const responses = window._fetchResponses || [];
                        for (let response of responses) {
                            if (response.url.includes('option-chain') && response.data) {
                                return response.data;
                            }
                        }
                        
                        return null;
                    }
                    
                    return findOptionData();
                """)
                
                if browser_data and 'records' in browser_data:
                    return process_api_data(browser_data)
                else:
                    st.error("Could not extract option chain data from browser")
                    # Save page source for debugging
                    page_source = driver.page_source
                    st.download_button(
                        label="Download page source for debugging",
                        data=page_source,
                        file_name="nse_page_source.html",
                        mime="text/html"
                    )
                    return None
                    
            finally:
                driver.quit()
                
        except Exception as e:
            st.error(f"Browser scraping failed: {str(e)}")
            return None

    def display_option_chain_data(calls_df, puts_df, current_price, expiry_date):
        """Display the option chain data in a user-friendly format"""
        st.markdown("### 📊 Nifty 50 Option Chain Data")
        st.write(f"**Current Price:** ₹{current_price:,.2f}" if current_price else "Current price not available")
        st.write(f"**Expiry Date:** {expiry_date}" if expiry_date else "Expiry date not available")
        
        # Create tabs for different views
        tab1, tab2, tab3 = st.tabs(["📈 Calls", "📉 Puts", "🔄 Combined"])
        
        with tab1:
            st.markdown("#### Call Options")
            if not calls_df.empty:
                # Sort by strike price
                calls_display = calls_df.sort_values('strike').reset_index(drop=True)
                st.dataframe(calls_display.style.format({
                    'strike': '{:,.0f}',
                    'oi': '{:,.0f}',
                    'change_oi': '{:+,.0f}',
                    'volume': '{:,.0f}',
                    'last_price': '{:.2f}',
                    'bid': '{:.2f}',
                    'ask': '{:.2f}',
                    'iv': '{:.2f}%' if 'iv' in calls_df.columns else '{:.2f}'
                }), use_container_width=True)
            else:
                st.warning("No call options data available")
        
        with tab2:
            st.markdown("#### Put Options")
            if not puts_df.empty:
                # Sort by strike price
                puts_display = puts_df.sort_values('strike').reset_index(drop=True)
                st.dataframe(puts_display.style.format({
                    'strike': '{:,.0f}',
                    'oi': '{:,.0f}',
                    'change_oi': '{:+,.0f}',
                    'volume': '{:,.0f}',
                    'last_price': '{:.2f}',
                    'bid': '{:.2f}',
                    'ask': '{:.2f}',
                    'iv': '{:.2f}%' if 'iv' in puts_df.columns else '{:.2f}'
                }), use_container_width=True)
            else:
                st.warning("No put options data available")
        
        with tab3:
            st.markdown("#### Combined Analysis")
            if not calls_df.empty and not puts_df.empty:
                # Merge data on strike price
                combined = pd.merge(
                    calls_df[['strike', 'oi', 'volume']],
                    puts_df[['strike', 'oi', 'volume']],
                    on='strike', suffixes=('_call', '_put'), how='outer'
                ).fillna(0)
                
                # Calculate PCR for each strike
                combined['pcr'] = combined.apply(
                    lambda row: row['oi_put'] / row['oi_call'] if row['oi_call'] > 0 else 0, 
                    axis=1
                )
                
                # Sort by strike
                combined = combined.sort_values('strike').reset_index(drop=True)
                
                st.dataframe(combined.style.format({
                    'strike': '{:,.0f}',
                    'oi_call': '{:,.0f}',
                    'volume_call': '{:,.0f}',
                    'oi_put': '{:,.0f}',
                    'volume_put': '{:,.0f}',
                    'pcr': '{:.2f}'
                }), use_container_width=True)
            else:
                st.warning("Insufficient data for combined analysis")

    def calculate_oi_analysis(calls_df, puts_df, current_price, expiry_date):
        """Calculate OI analysis metrics with proper error handling"""
        try:
            # Ensure DataFrames are not empty and have required columns
            if calls_df.empty or puts_df.empty:
                st.error("Empty dataframes - cannot calculate analysis")
                return None
                
            required_columns = ['oi', 'strike']
            for col in required_columns:
                if col not in calls_df.columns or col not in puts_df.columns:
                    st.error(f"Missing required column: {col}")
                    return None
                
            # Calculate basic metrics with error handling
            total_call_oi = calls_df['oi'].sum() if 'oi' in calls_df.columns else 0
            total_put_oi = puts_df['oi'].sum() if 'oi' in puts_df.columns else 0
            
            # Safely calculate put-call ratio
            if total_call_oi > 0:
                put_call_ratio = total_put_oi / total_call_oi
            else:
                put_call_ratio = 0
                st.warning("Total call OI is zero, cannot calculate meaningful PCR")
            
            # Find max OI strikes
            max_call_oi_strike = calls_df.loc[calls_df['oi'].idxmax(), 'strike'] if not calls_df.empty else 0
            max_put_oi_strike = puts_df.loc[puts_df['oi'].idxmax(), 'strike'] if not puts_df.empty else 0
            
            # Display metrics
            st.markdown("### 📈 Option Chain Analysis")
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.metric("Put-Call Ratio", f"{put_call_ratio:.3f}")
            
            with col2:
                st.metric("Total Call OI", f"{total_call_oi:,.0f}")
            
            with col3:
                st.metric("Total Put OI", f"{total_put_oi:,.0f}")
            
            with col4:
                st.metric("Max Call OI Strike", f"₹{max_call_oi_strike:,.0f}")
            
            # Additional analysis
            st.markdown("#### Key Levels")
            col1, col2 = st.columns(2)
            
            with col1:
                st.metric("Max Put OI Strike", f"₹{max_put_oi_strike:,.0f}")
            
            with col2:
                if current_price:
                    resistance = max_call_oi_strike if max_call_oi_strike > current_price else "Above current price"
                    support = max_put_oi_strike if max_put_oi_strike < current_price else "Below current price"
                    st.write(f"**Potential Resistance:** {resistance}")
                    st.write(f"**Potential Support:** {support}")
            
            # Return structured data
            return {
                'current_price': current_price,
                'expiry': expiry_date,
                'put_call_ratio': put_call_ratio,
                'total_call_oi': total_call_oi,
                'total_put_oi': total_put_oi,
                'max_call_oi_strike': max_call_oi_strike,
                'max_put_oi_strike': max_put_oi_strike,
                'calls_df': calls_df,
                'puts_df': puts_df
            }
            
        except Exception as e:
            st.error(f"Error in analysis calculation: {str(e)}")
            return None

    def analyze_intraday(data):
        """Analyze intraday trading patterns and generate signals"""
        try:
            # Get today's data
            today_data = data.iloc[-1]
            yesterday_data = data.iloc[-2]
            
            # Calculate key intraday metrics
            open_price = today_data['Open']
            current_price = today_data['Close']
            high_price = today_data['High']
            low_price = today_data['Low']
            volume = today_data['Volume']
            prev_close = yesterday_data['Close']
            
            # Calculate price changes
            price_change = current_price - open_price
            price_change_pct = (price_change / open_price) * 100
            day_range = high_price - low_price
            day_range_pct = (day_range / open_price) * 100
            
            # Volume analysis
            avg_volume = data['Volume'].rolling(window=20).mean().iloc[-1]
            volume_ratio = volume / avg_volume
            
            # Volatility analysis
            atr = calculate_atr(data).iloc[-1]
            volatility_ratio = day_range / atr
            
            # Support and Resistance levels
            support_levels = [
                low_price,
                data['Low'].rolling(window=5).min().iloc[-1],
                data['Low'].rolling(window=20).min().iloc[-1]
            ]
            
            resistance_levels = [
                high_price,
                data['High'].rolling(window=5).max().iloc[-1],
                data['High'].rolling(window=20).max().iloc[-1]
            ]
            
            # Intraday patterns
            patterns = []
            
            # Gap analysis
            gap = open_price - prev_close
            gap_pct = (gap / prev_close) * 100
            if abs(gap_pct) > 1:
                patterns.append(f"{'Bullish' if gap > 0 else 'Bearish'} gap of {abs(gap_pct):.2f}%")
            
            # Volume pattern
            if volume_ratio > 1.5:
                patterns.append(f"High volume ({volume_ratio:.1f}x average)")
            elif volume_ratio < 0.5:
                patterns.append(f"Low volume ({volume_ratio:.1f}x average)")
            
            # Volatility pattern
            if volatility_ratio > 1.5:
                patterns.append(f"High volatility ({volatility_ratio:.1f}x ATR)")
            
            # Price action patterns
            if current_price > open_price and current_price > prev_close:
                patterns.append("Price above both open and previous close")
            elif current_price < open_price and current_price < prev_close:
                patterns.append("Price below both open and previous close")
            
            # Generate intraday signal
            signal_score = 0
            
            # Price momentum
            if price_change_pct > 1:
                signal_score += 2
            elif price_change_pct > 0.5:
                signal_score += 1
            elif price_change_pct < -1:
                signal_score -= 2
            elif price_change_pct < -0.5:
                signal_score -= 1
            
            # Volume confirmation
            if volume_ratio > 1.2:
                if price_change_pct > 0:
                    signal_score += 1
                else:
                    signal_score -= 1
            
            # Volatility consideration
            if volatility_ratio > 1.5:
                signal_score = signal_score * 0.8  # Reduce confidence in high volatility
            
            # Determine intraday signal
            if signal_score >= 2:
                signal = "STRONG BUY"
                confidence = "High"
            elif signal_score == 1:
                signal = "BUY"
                confidence = "Moderate"
            elif signal_score == 0:
                signal = "HOLD"
                confidence = "Low"
            elif signal_score == -1:
                signal = "SELL"
                confidence = "Moderate"
            else:
                signal = "STRONG SELL"
                confidence = "High"
            
            # Calculate risk levels
            risk_level = "High" if volatility_ratio > 1.5 else "Moderate" if volatility_ratio > 1 else "Low"
            
            # Generate intraday targets
            if signal in ["STRONG BUY", "BUY"]:
                target_1 = current_price + (atr * 0.5)
                target_2 = current_price + (atr * 1)
                stop_loss = current_price - (atr * 0.5)
            elif signal in ["STRONG SELL", "SELL"]:
                target_1 = current_price - (atr * 0.5)
                target_2 = current_price - (atr * 1)
                stop_loss = current_price + (atr * 0.5)
            else:
                target_1 = target_2 = stop_loss = current_price
            
            return {
                'signal': signal,
                'confidence': confidence,
                'risk_level': risk_level,
                'current_price': current_price,
                'price_change': price_change,
                'price_change_pct': price_change_pct,
                'volume_ratio': volume_ratio,
                'volatility_ratio': volatility_ratio,
                'patterns': patterns,
                'support_levels': support_levels,
                'resistance_levels': resistance_levels,
                'target_1': target_1,
                'target_2': target_2,
                'stop_loss': stop_loss,
                'signal_score': signal_score
            }
        except Exception as e:
            st.error(f"Error in intraday analysis: {str(e)}")
            return None

    def main():
        try:
            # Get data
            data = yf.Ticker(stocks[selected_stock]).history(period=period)
            
            if data.empty:
                st.warning(f"No data available for {selected_stock}")
                return
            
            # Calculate technical indicators
            data = calculate_moving_averages(data)
            data['RSI'] = calculate_rsi(data)
            macd, signal = calculate_macd(data)
            data['MACD'] = macd
            data['Signal'] = signal
            upper_band, middle_band, lower_band = calculate_bollinger_bands(data)
            data['BB_Upper'] = upper_band
            data['BB_Middle'] = middle_band
            data['BB_Lower'] = lower_band
            data['ATR'] = calculate_atr(data)
            
            # Get comprehensive analysis
            analysis = analyze_stock(data)
            
            # Create three columns for metrics
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric(
                    "Current Price",
                    f"₹{data['Close'].iloc[-1]:.2f}",
                    f"{(data['Close'].iloc[-1] - data['Close'].iloc[-2])/data['Close'].iloc[-2]*100:.2f}%"
                )
            
            with col2:
                st.metric(
                    "20-day MA",
                    f"₹{data['SMA20'].iloc[-1]:.2f}",
                    f"{(data['SMA20'].iloc[-1] - data['Close'].iloc[-1])/data['Close'].iloc[-1]*100:.2f}%"
                )
            
            with col3:
                st.metric(
                    "50-day MA",
                    f"₹{data['SMA50'].iloc[-1]:.2f}",
                    f"{(data['SMA50'].iloc[-1] - data['Close'].iloc[-1])/data['Close'].iloc[-1]*100:.2f}%"
                )
            
            # Technical Indicators
            st.markdown("### Technical Indicators")
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric("RSI", f"{data['RSI'].iloc[-1]:.2f}")
                st.metric("MACD", f"{data['MACD'].iloc[-1]:.2f}")
            
            with col2:
                st.metric("BB Upper", f"₹{data['BB_Upper'].iloc[-1]:.2f}")
                st.metric("BB Lower", f"₹{data['BB_Lower'].iloc[-1]:.2f}")
            
            with col3:
                st.metric("ATR", f"₹{data['ATR'].iloc[-1]:.2f}")
            
            # Price chart
            fig = make_subplots(rows=3, cols=1,
                               shared_xaxes=True,
                               vertical_spacing=0.05,
                               subplot_titles=('Price', 'RSI', 'MACD'),
                               row_heights=[0.6, 0.2, 0.2])
            
            # Add candlestick chart
            fig.add_trace(go.Candlestick(x=data.index,
                                        open=data['Open'],
                                        high=data['High'],
                                        low=data['Low'],
                                        close=data['Close'],
                                        name='Price'),
                         row=1, col=1)
            
            # Add Bollinger Bands
            fig.add_trace(go.Scatter(x=data.index, y=data['BB_Upper'],
                                    name='BB Upper',
                                    line=dict(color='rgba(250, 0, 0, 0.3)')),
                         row=1, col=1)
            fig.add_trace(go.Scatter(x=data.index, y=data['BB_Lower'],
                                    name='BB Lower',
                                    line=dict(color='rgba(0, 250, 0, 0.3)')),
                         row=1, col=1)
            
            # Add RSI
            fig.add_trace(go.Scatter(x=data.index, y=data['RSI'],
                                    name='RSI',
                                    line=dict(color='purple')),
                         row=2, col=1)
            
            # Add MACD
            fig.add_trace(go.Scatter(x=data.index, y=data['MACD'],
                                    name='MACD',
                                    line=dict(color='blue')),
                         row=3, col=1)
            fig.add_trace(go.Scatter(x=data.index, y=data['Signal'],
                                    name='Signal',
                                    line=dict(color='orange')),
                         row=3, col=1)
            
            # Update layout
            fig.update_layout(
                title=f'{selected_stock} Technical Analysis',
                yaxis_title='Price',
                yaxis2_title='RSI',
                yaxis3_title='MACD',
                xaxis_rangeslider_visible=False,
                height=800,
                template='plotly_dark'
            )
            
            st.plotly_chart(fig, use_container_width=True)
            
            # Trading Analysis Section (New)
            st.markdown("### 📊 Trading Analysis")
            st.markdown("---")
            
            # Create two columns for analysis
            col1, col2 = st.columns(2)
            
            with col1:
                # Signal and Hold Duration - Simplified
                signal_color = {
                    'STRONG BUY': '#00C853',  # Green
                    'BUY': '#69F0AE',         # Light Green
                    'WEAK BUY': '#FFD600',    # Yellow
                    'HOLD': '#FF9100',        # Orange
                    'WEAK SELL': '#FF4081',   # Pink
                    'SELL': '#FF1744',        # Red
                    'STRONG SELL': '#D50000'  # Dark Red
                }[analysis['Signal']]
                
                st.markdown(f"""
                    <div style='margin-bottom: 20px;'>
                        <span style='font-size: 24px; font-weight: bold; color: {signal_color};'>{analysis['Signal']}</span>
                        <p style='margin-top: 5px;'><strong>Hold Duration:</strong> {analysis['Hold Duration']}</p>
                        <p style='margin-top: 5px;'><strong>Exit Strategy:</strong> {analysis['Exit Strategy']}</p>
                    </div>
                """, unsafe_allow_html=True)
                
                # Support and Resistance
                st.markdown("#### Support and Resistance")
                st.write(f"Support: ₹{analysis['Support']:,.2f}")
                st.write(f"Resistance: ₹{analysis['Resistance']:,.2f}")
                st.write(f"First Target: ₹{analysis['Target Prices']['First Target']:,.2f}")
                st.write(f"Second Target: ₹{analysis['Target Prices']['Second Target']:,.2f}")
                st.write(f"Stop Loss: ₹{analysis['Target Prices']['Stop Loss']:,.2f}")
            
            with col2:
                # Technical Analysis
                st.markdown("#### Technical Analysis")
                st.write(f"Short Term Trend: {analysis['Trend']['Short Term']}")
                st.write(f"Long Term Trend: {analysis['Trend']['Long Term']}")
                if analysis['Trend']['Sideways']:
                    st.write(f"Market is sideways for {analysis['Trend']['Sideways Days']} days")
                st.write(f"Volume: {analysis['Volume']}")
                st.write(f"RSI: {analysis['Technical Indicators']['RSI']}")
                st.write(f"MACD: {analysis['Technical Indicators']['MACD']}")
                st.write(f"Bollinger Bands: {analysis['Technical Indicators']['Bollinger Bands']}")
            
            # Signal Strength
            st.markdown("#### Signal Strength")
            st.progress((analysis['Signal Score'] + 4) / 8)  # Normalize score to 0-1 range
            st.write(f"Signal Score: {analysis['Signal Score']}/4 (Range: -4 to +4)")
            
            # Add explanation of score
            st.markdown("""
            **Signal Score Breakdown:**
            - Strong Buy: +3 to +4
            - Buy: +2
            - Weak Buy: +1
            - Hold: 0
            - Weak Sell: -1
            - Sell: -2
            - Strong Sell: -3 to -4
            """)
            
            # Detect manipulation patterns
            patterns = detect_manipulation(data)
            
            # Display manipulation patterns
            if patterns:
                st.subheader("⚠️ Market Manipulation Detection")
                for pattern in patterns:
                    severity_color = {
                        'High': '#B71C1C',
                        'Medium': '#F57F17',
                        'Low': '#1B5E20'
                    }[pattern['severity']]
                    
                    st.markdown(f"""
                        <div class="manipulation-pattern">
                            <h4 style='color: {severity_color}'>{pattern['type']} ({pattern['severity']})</h4>
                            <p>{pattern['description']}</p>
                        </div>
                    """, unsafe_allow_html=True)
            
            # Analysis explanation
            st.markdown("### Analysis Explanation")
            st.markdown("""
            #### Technical Indicators
            - **RSI (Relative Strength Index)**: Measures momentum and identifies overbought/oversold conditions
            - **MACD (Moving Average Convergence Divergence)**: Identifies trend changes and momentum
            - **Bollinger Bands**: Shows price volatility and potential reversal points
            - **ATR (Average True Range)**: Measures market volatility
            
            #### Trading Signals
            - Moving Average Crossover: 20-day MA crossing 50-day MA
            - RSI: Above 70 (overbought), Below 30 (oversold)
            - MACD: Bullish when MACD line crosses above signal line
            - Bollinger Bands: Price touching upper/lower bands indicates potential reversals
            """)

            # Add News Analysis Section
            st.markdown("### 📰 News Analysis")
            st.markdown("---")
            
            # Fetch and analyze news
            news_articles = fetch_news(stocks[selected_stock])
            news_sentiments = analyze_news_sentiment(news_articles)
            news_score = calculate_news_score(news_sentiments)
            news_signal, news_reason = get_news_recommendation(news_score)
            
            # Create columns for news analysis
            news_col1, news_col2 = st.columns(2)
            
            with news_col1:
                st.markdown("#### News Sentiment Analysis")
                st.metric("News Sentiment Score", f"{news_score:.2f}")
                st.markdown(f"**Recommendation:** {news_signal}")
                st.markdown(f"**Reason:** {news_reason}")
                
                # Display sentiment distribution
                sentiment_dist = {
                    'Positive': len([s for s in news_sentiments if s['sentiment']['compound'] > 0.2]),
                    'Neutral': len([s for s in news_sentiments if -0.2 <= s['sentiment']['compound'] <= 0.2]),
                    'Negative': len([s for s in news_sentiments if s['sentiment']['compound'] < -0.2])
                }
                
                fig = go.Figure(data=[go.Pie(
                    labels=list(sentiment_dist.keys()),
                    values=list(sentiment_dist.values()),
                    hole=.3
                )])
                fig.update_layout(title="News Sentiment Distribution")
                st.plotly_chart(fig, use_container_width=True)
            
            with news_col2:
                st.markdown("#### Recent News Articles")
                for article in news_sentiments[:5]:  # Show top 5 articles
                    sentiment_color = {
                        'compound': 'green' if article['sentiment']['compound'] > 0 else 'red'
                    }
                    
                    st.markdown(f"""
                        <div style='margin-bottom: 15px; padding: 10px; border: 1px solid #ddd; border-radius: 5px;'>
                            <h4 style='margin: 0;'>{article['title']}</h4>
                            <p style='margin: 5px 0;'>{article['description']}</p>
                            <p style='margin: 5px 0;'>
                                <span style='color: {sentiment_color["compound"]};'>
                                    Sentiment: {article['sentiment']['compound']:.2f}
                                </span>
                            </p>
                            <p style='margin: 5px 0;'>
                                <a href='{article['url']}' target='_blank'>Read more</a> | 
                                Source: {article['source']} | 
                                {article['publishedAt']}
                            </p>
                        </div>
                    """, unsafe_allow_html=True)
            
            # Combined Analysis Section
            st.markdown("### 🔄 Combined Analysis")
            st.markdown("---")
            
            # Calculate combined score (weighted average of technical and news analysis)
            technical_score = analysis['Signal Score'] / 4  # Normalize to -1 to 1
            combined_score = (technical_score * 0.6) + (news_score * 0.4)  # 60% technical, 40% news
            
            # Get combined recommendation
            if combined_score >= 0.5:
                combined_signal = "STRONG BUY"
            elif combined_score >= 0.2:
                combined_signal = "BUY"
            elif combined_score >= -0.2:
                combined_signal = "HOLD"
            elif combined_score >= -0.5:
                combined_signal = "SELL"
            else:
                combined_signal = "STRONG SELL"
            
            # Display combined analysis
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric("Technical Analysis", analysis['Signal'])
                st.metric("Technical Score", f"{technical_score:.2f}")
            
            with col2:
                st.metric("News Analysis", news_signal)
                st.metric("News Score", f"{news_score:.2f}")
            
            with col3:
                st.metric("Combined Signal", combined_signal)
                st.metric("Combined Score", f"{combined_score:.2f}")
            
            # Display confidence level
            confidence = abs(combined_score) * 100
            st.progress(confidence / 100)
            st.markdown(f"**Confidence Level:** {confidence:.1f}%")
            
            # Display analysis explanation
            st.markdown("""
            #### Analysis Explanation
            - **Technical Analysis**: Based on price action, volume, and technical indicators
            - **News Analysis**: Based on sentiment analysis of recent news articles
            - **Combined Analysis**: Weighted average of technical (60%) and news (40%) analysis
            """)

            # Add Open Interest Analysis Section for Nifty 50
            if selected_stock == 'NIFTY 50':
                st.markdown("### 📊 Open Interest Analysis")
                st.markdown("---")
                
                with st.spinner('Fetching Open Interest data from NSE...'):
                    oi_analysis = fetch_nse_oi_data(stocks[selected_stock])
                
                if oi_analysis:
                    # Create columns for OI metrics
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        st.metric(
                            "Put-Call Ratio",
                            f"{oi_analysis['put_call_ratio']:.2f}",
                            f"Sentiment: {oi_analysis['oi_sentiment']}"
                        )
                    
                    with col2:
                        st.metric(
                            "Total Call OI",
                            f"{oi_analysis['total_call_oi']:,.0f}",
                            f"Change: {oi_analysis['call_oi_change']:,.0f}"
                        )
                    
                    with col3:
                        st.metric(
                            "Total Put OI",
                            f"{oi_analysis['total_put_oi']:,.0f}",
                            f"Change: {oi_analysis['put_oi_change']:,.0f}"
                        )
                    
                    # Display nearest strikes
                    st.markdown("#### Nearest Strike Analysis")
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.markdown("**Calls**")
                        for call in oi_analysis['nearest_calls']:
                            st.markdown(f"""
                                Strike: ₹{call['strike']:,.0f}  
                                OI: {call['oi']:,.0f}  
                                Change in OI: {call['change_oi']:,.0f}
                                Volume: {call['volume']:,.0f}
                                Last Price: ₹{call['last_price']:.2f}
                                ---
                            """)
                    
                    with col2:
                        st.markdown("**Puts**")
                        for put in oi_analysis['nearest_puts']:
                            st.markdown(f"""
                                Strike: ₹{put['strike']:,.0f}  
                                OI: {put['oi']:,.0f}  
                                Change in OI: {put['change_oi']:,.0f}
                                Volume: {put['volume']:,.0f}
                                Last Price: ₹{put['last_price']:.2f}
                                ---
                            """)
                    
                    # Add OI analysis explanation
                    st.markdown("""
                    #### Open Interest Analysis Explanation
                    - **Put-Call Ratio**: 
                      - > 1.2: Bearish sentiment
                      - < 0.8: Bullish sentiment
                      - 0.8-1.2: Neutral sentiment
                    - **OI Changes**: 
                      - Positive change with price movement confirms the trend
                      - Negative change with price movement suggests trend reversal
                    - **Volume**: High volume at strikes indicates strong support/resistance
                    - **Nearest Strikes**: Shows where most options activity is concentrated
                    """)

            # Add Intraday Analysis Section
            st.markdown("### 📊 Intraday Trading Analysis")
            st.markdown("---")
            
            # Get intraday analysis
            intraday_analysis = analyze_intraday(data)
            
            if intraday_analysis:
                # Create columns for intraday metrics
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.metric(
                        "Intraday Signal",
                        intraday_analysis['signal'],
                        f"Confidence: {intraday_analysis['confidence']}"
                    )
                    st.metric(
                        "Risk Level",
                        intraday_analysis['risk_level']
                    )
                
                with col2:
                    st.metric(
                        "Price Change",
                        f"₹{intraday_analysis['price_change']:.2f}",
                        f"{intraday_analysis['price_change_pct']:.2f}%"
                    )
                    st.metric(
                        "Volume Ratio",
                        f"{intraday_analysis['volume_ratio']:.1f}x"
                    )
                
                with col3:
                    st.metric(
                        "Volatility",
                        f"{intraday_analysis['volatility_ratio']:.1f}x ATR"
                    )
                
                # Display patterns
                st.markdown("#### Intraday Patterns")
                for pattern in intraday_analysis['patterns']:
                    st.markdown(f"- {pattern}")
                
                # Display targets and levels
                st.markdown("#### Trading Levels")
                col1, col2 = st.columns(2)
                
                with col1:
                    st.markdown("**Support Levels**")
                    for i, level in enumerate(intraday_analysis['support_levels']):
                        st.markdown(f"Level {i+1}: ₹{level:.2f}")
                
                with col2:
                    st.markdown("**Resistance Levels**")
                    for i, level in enumerate(intraday_analysis['resistance_levels']):
                        st.markdown(f"Level {i+1}: ₹{level:.2f}")
                
                # Display targets and stop loss
                st.markdown("#### Trading Targets")
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.metric("Target 1", f"₹{intraday_analysis['target_1']:.2f}")
                with col2:
                    st.metric("Target 2", f"₹{intraday_analysis['target_2']:.2f}")
                with col3:
                    st.metric("Stop Loss", f"₹{intraday_analysis['stop_loss']:.2f}")
                
                # Display signal strength
                st.markdown("#### Signal Strength")
                signal_strength = (intraday_analysis['signal_score'] + 2) / 4  # Normalize to 0-1
                st.progress(signal_strength)
                
                # Add disclaimer
                st.markdown("""
                ---
                **Disclaimer**: Intraday trading signals are based on technical analysis and market patterns. 
                These signals should not be the sole basis for trading decisions. Always consider market conditions, 
                news, and your risk tolerance before trading.
                """)

            # Add Trading Recommendations Section
            st.markdown("### 📈 Trading Recommendations")
            st.markdown("---")

            # Create columns for different analysis aspects
            col1, col2 = st.columns(2)

            with col1:
                st.markdown("#### Market Analysis")
                
                # Calculate key levels
                current_price = float(price_info['price'])
                support_levels = [
                    current_price * 0.98,  # 2% below current price
                    current_price * 0.95,  # 5% below current price
                    current_price * 0.92   # 8% below current price
                ]
                
                resistance_levels = [
                    current_price * 1.02,  # 2% above current price
                    current_price * 1.05,  # 5% above current price
                    current_price * 1.08   # 8% above current price
                ]

                st.markdown("##### Key Levels")
                st.write(f"Current Price: ₹{current_price:,.2f}")
                
                st.markdown("**Support Levels:**")
                for i, level in enumerate(support_levels):
                    st.write(f"Level {i+1}: ₹{level:,.2f}")
                
                st.markdown("**Resistance Levels:**")
                for i, level in enumerate(resistance_levels):
                    st.write(f"Level {i+1}: ₹{level:,.2f}")

            with col2:
                st.markdown("#### Trading Strategy")
                
                # Determine market sentiment
                rsi = data['RSI'].iloc[-1]
                macd = data['MACD'].iloc[-1]
                signal = data['Signal'].iloc[-1]
                
                # Calculate trend
                sma20 = data['SMA20'].iloc[-1]
                sma50 = data['SMA50'].iloc[-1]
                
                # Determine trading signals
                if rsi < 30 and macd > signal and current_price > sma20:
                    signal = "STRONG BUY"
                    reason = "Oversold conditions with positive momentum"
                elif rsi < 40 and current_price > sma20:
                    signal = "BUY"
                    reason = "Moderate oversold conditions with uptrend"
                elif rsi > 70 and macd < signal and current_price < sma20:
                    signal = "STRONG SELL"
                    reason = "Overbought conditions with negative momentum"
                elif rsi > 60 and current_price < sma20:
                    signal = "SELL"
                    reason = "Moderate overbought conditions with downtrend"
                else:
                    signal = "HOLD"
                    reason = "Neutral market conditions"

                st.markdown(f"**Trading Signal:** {signal}")
                st.markdown(f"**Reason:** {reason}")
                
                # Add trading recommendations
                st.markdown("##### Trading Recommendations")
                
                if signal in ["STRONG BUY", "BUY"]:
                    st.markdown("""
                    **Entry Strategy:**
                    - Enter in small lots
                    - Use limit orders near support levels
                    - Set stop loss 2% below entry
                    
                    **Exit Strategy:**
                    - Take partial profits at first resistance
                    - Trail stop loss for remaining position
                    - Book full profits at second resistance
                    """)
                elif signal in ["STRONG SELL", "SELL"]:
                    st.markdown("""
                    **Entry Strategy:**
                    - Enter in small lots
                    - Use limit orders near resistance levels
                    - Set stop loss 2% above entry
                    
                    **Exit Strategy:**
                    - Take partial profits at first support
                    - Trail stop loss for remaining position
                    - Book full profits at second support
                    """)
                else:
                    st.markdown("""
                    **Current Strategy:**
                    - Wait for better entry points
                    - Monitor support/resistance levels
                    - Look for breakout/breakdown signals
                    """)

            # Add Market Insights
            st.markdown("### 📊 Market Insights")
            st.markdown("---")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.markdown("#### Technical Indicators")
                st.write(f"RSI: {rsi:.2f}")
                st.write(f"MACD: {macd:.2f}")
                st.write(f"Signal Line: {signal:.2f}")
                st.write(f"20-day MA: ₹{sma20:,.2f}")
                st.write(f"50-day MA: ₹{sma50:,.2f}")
            
            with col2:
                st.markdown("#### Volume Analysis")
                avg_volume = data['Volume'].mean()
                current_volume = data['Volume'].iloc[-1]
                volume_ratio = current_volume / avg_volume
                
                st.write(f"Current Volume: {current_volume:,.0f}")
                st.write(f"Average Volume: {avg_volume:,.0f}")
                st.write(f"Volume Ratio: {volume_ratio:.2f}x")
                
                if volume_ratio > 1.5:
                    st.write("High volume - Strong trend")
                elif volume_ratio < 0.5:
                    st.write("Low volume - Weak trend")
                else:
                    st.write("Normal volume - Neutral trend")
            
            with col3:
                st.markdown("#### Risk Analysis")
                atr = data['ATR'].iloc[-1]
                volatility = (atr / current_price) * 100
                
                st.write(f"ATR: ₹{atr:.2f}")
                st.write(f"Volatility: {volatility:.2f}%")
                
                if volatility > 2:
                    st.write("High volatility - Use tight stops")
                elif volatility < 1:
                    st.write("Low volatility - Normal stops")
                else:
                    st.write("Moderate volatility - Standard stops")

            # Add Trading Tips
            st.markdown("### 💡 Trading Tips")
            st.markdown("""
            #### Best Practices for Indian Markets:
            1. **Entry Timing:**
               - Best entry times: 9:15 AM - 10:00 AM and 2:30 PM - 3:30 PM
               - Avoid trading during lunch hours (12:00 PM - 1:00 PM)
            
            2. **Position Sizing:**
               - Never risk more than 1-2% of capital per trade
               - Use proper position sizing based on stop loss
            
            3. **Risk Management:**
               - Always use stop losses
               - Trail your stops in trending markets
               - Take partial profits at key levels
            
            4. **Market Hours:**
               - Pre-market: 9:00 AM - 9:15 AM
               - Regular market: 9:15 AM - 3:30 PM
               - Post-market: 3:30 PM - 4:00 PM
            
            5. **Important Levels:**
               - Watch for FII/DII data
               - Monitor global markets (especially US futures)
               - Track currency movements (USD/INR)
            """)

            # Add Disclaimer
            st.markdown("""
            ---
            **Disclaimer:** This analysis is for educational purposes only. Trading in financial markets involves risk. 
            Always do your own research and consult with a financial advisor before making any investment decisions.
            """)
        
        except Exception as e:
            st.error(f"An error occurred: {str(e)}")
            st.info("Please try refreshing the page or selecting a different stock.")

    if __name__ == "__main__":
        main() 