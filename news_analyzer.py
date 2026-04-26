import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
from textblob import TextBlob
import tweepy
import praw
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# News sources
NEWS_SOURCES = {
    'MoneyControl': 'https://www.moneycontrol.com/news/tags/{symbol}.html',
    'Economic Times': 'https://economictimes.indiatimes.com/markets/stocks/news',
    'Business Standard': 'https://www.business-standard.com/markets',
    'NDTV Profit': 'https://www.ndtv.com/business/market',
    'Livemint': 'https://www.livemint.com/market'
}

# Market manipulation patterns
MANIPULATION_PATTERNS = {
    'Pump and Dump': {
        'description': 'Sudden price increase followed by rapid selling',
        'indicators': ['Unusual volume spike', 'Price gap up', 'Social media hype']
    },
    'Bear Raid': {
        'description': 'Coordinated selling to drive price down',
        'indicators': ['Large sell orders', 'Negative news spread', 'Price gap down']
    },
    'Spoofing': {
        'description': 'Large fake orders to manipulate price',
        'indicators': ['Order book imbalance', 'Quick order cancellation', 'Price reversal']
    },
    'Wash Trading': {
        'description': 'Artificial volume through self-trading',
        'indicators': ['Unusual volume patterns', 'Same buyer/seller', 'No price impact']
    },
    'Front Running': {
        'description': 'Trading ahead of large orders',
        'indicators': ['Price movement before news', 'Unusual pre-market activity', 'Order flow analysis']
    }
}

# Symbol mapping for Indian indices
SYMBOL_MAPPING = {
    "NIFTY 50": "^NSEI",
    "BANK NIFTY": "^NSEBANK",
    "RELIANCE": "RELIANCE.NS",
    "TCS": "TCS.NS",
    "HDFC BANK": "HDFCBANK.NS"
}

def fetch_news_from_source(source, symbol):
    """Fetch news from a specific source"""
    try:
        url = NEWS_SOURCES[source].format(symbol=symbol.lower())
        response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        news_items = []
        if source == 'MoneyControl':
            items = soup.find_all('li', class_='clearfix')
            for item in items[:5]:
                title = item.find('h2').text.strip()
                link = item.find('a')['href']
                date = item.find('span', class_='article_time').text.strip()
                news_items.append({
                    'title': title,
                    'link': link,
                    'date': date,
                    'source': source
                })
        # Add more source-specific parsing here
        
        return news_items
    except Exception as e:
        st.error(f"Error fetching news from {source}: {str(e)}")
        return []

def analyze_sentiment(text):
    """Analyze sentiment of text"""
    return TextBlob(text).sentiment.polarity

def detect_manipulation_patterns(data, news_data):
    """Detect potential market manipulation patterns"""
    patterns = []
    
    # Analyze price and volume patterns
    if len(data) > 0:
        # Volume spike detection
        avg_volume = data['Volume'].mean()
        recent_volume = data['Volume'].iloc[-1]
        if recent_volume > avg_volume * 2:
            patterns.append({
                'type': 'Volume Spike',
                'description': f'Unusual volume spike: {recent_volume:,.0f} vs avg {avg_volume:,.0f}',
                'severity': 'High'
            })
        
        # Price gap detection
        price_change = (data['Close'].iloc[-1] - data['Open'].iloc[-1]) / data['Open'].iloc[-1] * 100
        if abs(price_change) > 5:
            patterns.append({
                'type': 'Price Gap',
                'description': f'Significant price gap: {price_change:.2f}%',
                'severity': 'Medium'
            })
    
    # Analyze news sentiment patterns
    if news_data:
        sentiments = [analyze_sentiment(news['title']) for news in news_data]
        avg_sentiment = np.mean(sentiments)
        if abs(avg_sentiment) > 0.5:
            patterns.append({
                'type': 'News Sentiment',
                'description': f'Strong {("positive" if avg_sentiment > 0 else "negative")} news sentiment',
                'severity': 'Medium'
            })
    
    return patterns

def fetch_market_data(symbol):
    """Fetch market data with proper error handling"""
    try:
        mapped_symbol = SYMBOL_MAPPING.get(symbol, symbol)
        data = yf.download(mapped_symbol, period="1d", interval="1m")
        if data.empty:
            st.warning(f"No data available for {symbol}. Please try a different symbol.")
            return None
        return data
    except Exception as e:
        st.error(f"Error fetching data for {symbol}: {str(e)}")
        return None

def news_analysis_page():
    """Main news analysis page"""
    st.title("📰 Market News & Manipulation Analysis")
    
    # Sidebar controls
    st.sidebar.header("Analysis Parameters")
    selected_index = st.sidebar.selectbox(
        "Select Index/Stock",
        list(SYMBOL_MAPPING.keys())
    )
    
    analysis_type = st.sidebar.multiselect(
        "Analysis Type",
        ["News Analysis", "Manipulation Detection", "Social Media Sentiment", "Trading Signals"],
        default=["News Analysis", "Manipulation Detection"]
    )
    
    # Fetch data
    data = fetch_market_data(selected_index)
    
    # Fetch news from all sources
    all_news = []
    for source in NEWS_SOURCES.keys():
        news_items = fetch_news_from_source(source, selected_index)
        all_news.extend(news_items)
    
    # Sort news by date
    all_news.sort(key=lambda x: x['date'], reverse=True)
    
    # Display news analysis
    if "News Analysis" in analysis_type:
        st.subheader("Latest News Analysis")
        
        if not all_news:
            st.info("No news articles found. Please try a different symbol or check your internet connection.")
        else:
            for news in all_news:
                sentiment = analyze_sentiment(news['title'])
                sentiment_color = "green" if sentiment > 0 else "red" if sentiment < 0 else "gray"
                
                st.markdown(f"""
                    <div class="news-card">
                        <p class="news-source">{news['source']}</p>
                        <h4>{news['title']}</h4>
                        <p>Date: {news['date']}</p>
                        <p>Sentiment: <span style='color: {sentiment_color}'>{sentiment:.2f}</span></p>
                        <a href='{news['link']}' target='_blank'>Read More</a>
                    </div>
                """, unsafe_allow_html=True)
    
    # Display manipulation patterns
    if "Manipulation Detection" in analysis_type and data is not None:
        st.subheader("Market Manipulation Analysis")
        
        # Detect patterns
        patterns = detect_manipulation_patterns(data, all_news)
        
        if patterns:
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
        else:
            st.info("No significant manipulation patterns detected.")
    
    # Display trading signals
    if "Trading Signals" in analysis_type and data is not None:
        st.subheader("Trading Signals")
        
        # Calculate signals based on news and patterns
        patterns = detect_manipulation_patterns(data, all_news) if data is not None else []
        if patterns:
            signal = "SELL" if any(p['severity'] == 'High' for p in patterns) else "HOLD"
            signal_color = "signal-sell" if signal == "SELL" else "signal-hold"
        else:
            signal = "BUY"
            signal_color = "signal-buy"
        
        st.markdown(f"""
            <div class="{signal_color}">
                <h3>Signal: {signal}</h3>
                <p>Based on news analysis and manipulation detection</p>
                <p>Number of patterns detected: {len(patterns)}</p>
                <p>Latest news sentiment: {np.mean([analyze_sentiment(n['title']) for n in all_news]):.2f if all_news else 0:.2f}</p>
            </div>
        """, unsafe_allow_html=True)
    
    # Display price chart
    if data is not None and len(data) > 0:
        fig = make_subplots(rows=2, cols=1, 
                           shared_xaxes=True,
                           vertical_spacing=0.03,
                           subplot_titles=('Price', 'Volume'),
                           row_heights=[0.7, 0.3])
        
        # Add candlestick chart
        fig.add_trace(go.Candlestick(x=data.index,
                                    open=data['Open'],
                                    high=data['High'],
                                    low=data['Low'],
                                    close=data['Close'],
                                    name='Price'),
                      row=1, col=1)
        
        # Add volume bars
        fig.add_trace(go.Bar(x=data.index, y=data['Volume'],
                            name='Volume'),
                      row=2, col=1)
        
        # Update layout
        fig.update_layout(
            title=f'{selected_index} Intraday Analysis',
            yaxis_title='Price',
            yaxis2_title='Volume',
            xaxis_rangeslider_visible=False,
            height=800,
            template='plotly_dark'
        )
        
        st.plotly_chart(fig, use_container_width=True)

if __name__ == "__main__":
    news_analysis_page() 