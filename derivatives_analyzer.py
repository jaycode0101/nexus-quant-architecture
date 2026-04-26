import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from textblob import TextBlob
import requests
from bs4 import BeautifulSoup
from prophet import Prophet
import nsepy as nse
from nsepy.derivatives import get_expiry_date

# Constants
INDICES = {
    'NIFTY 50': '^NSEI',
    'BANK NIFTY': '^NSEBANK',
    'FINNIFTY': 'FINNIFTY.NS',
    'SENSEX': '^BSESN',
    'NIFTY IT': '^CNXIT',
    'NIFTY PHARMA': '^CNXPHARMA',
    'NIFTY AUTO': '^CNXAUTO',
    'NIFTY FMCG': '^CNXFMCG',
    'NIFTY METAL': '^CNXMETAL',
    'NIFTY REALTY': '^CNXREALTY'
}

def get_option_chain(symbol):
    """Fetch option chain data from NSE"""
    try:
        expiry = get_expiry_date(year=datetime.now().year, month=datetime.now().month)
        option_chain = nse.get_option_chain(symbol, expiry)
        return option_chain
    except Exception as e:
        st.error(f"Error fetching option chain: {str(e)}")
        return None

def calculate_technical_indicators(data):
    """Calculate technical indicators for prediction"""
    # RSI
    delta = data['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    data['RSI'] = 100 - (100 / (1 + rs))
    
    # MACD
    exp1 = data['Close'].ewm(span=12, adjust=False).mean()
    exp2 = data['Close'].ewm(span=26, adjust=False).mean()
    data['MACD'] = exp1 - exp2
    data['Signal'] = data['MACD'].ewm(span=9, adjust=False).mean()
    
    # Bollinger Bands
    data['MA20'] = data['Close'].rolling(window=20).mean()
    data['STD20'] = data['Close'].rolling(window=20).std()
    data['Upper'] = data['MA20'] + (data['STD20'] * 2)
    data['Lower'] = data['MA20'] - (data['STD20'] * 2)
    
    return data

def prepare_data_for_prediction(data, lookback=60):
    """Prepare data for LSTM model"""
    scaler = MinMaxScaler()
    scaled_data = scaler.fit_transform(data[['Close', 'Volume', 'RSI', 'MACD']].values)
    
    X, y = [], []
    for i in range(lookback, len(scaled_data)):
        X.append(scaled_data[i-lookback:i])
        y.append(scaled_data[i, 0])
    
    return np.array(X), np.array(y), scaler

def create_lstm_model(lookback):
    """Create LSTM model for prediction"""
    model = Sequential([
        LSTM(50, return_sequences=True, input_shape=(lookback, 4)),
        Dropout(0.2),
        LSTM(50, return_sequences=False),
        Dropout(0.2),
        Dense(1)
    ])
    model.compile(optimizer='adam', loss='mse')
    return model

def predict_price(data, timeframes=[5, 10, 15]):
    """Predict price for different timeframes"""
    # Calculate technical indicators
    data = calculate_technical_indicators(data)
    
    # Prepare data
    X, y, scaler = prepare_data_for_prediction(data)
    
    # Create and train model
    model = create_lstm_model(60)
    model.fit(X, y, epochs=50, batch_size=32, verbose=0)
    
    # Make predictions
    predictions = {}
    last_sequence = X[-1:]
    
    for minutes in timeframes:
        pred = model.predict(last_sequence)
        pred_price = scaler.inverse_transform([[pred[0][0], 0, 0, 0]])[0][0]
        predictions[minutes] = pred_price
    
    return predictions

def analyze_option_opportunities(option_chain, current_price, budget):
    """Analyze options for trading opportunities"""
    opportunities = []
    
    if option_chain is None:
        return opportunities
    
    # Analyze calls
    for _, row in option_chain.calls.iterrows():
        if row['strikePrice'] > current_price * 0.95 and row['strikePrice'] < current_price * 1.05:
            risk_reward = (row['strikePrice'] - current_price) / row['lastPrice']
            if risk_reward > 2 and row['lastPrice'] * 100 <= budget:
                opportunities.append({
                    'type': 'CALL',
                    'strike': row['strikePrice'],
                    'premium': row['lastPrice'],
                    'risk_reward': risk_reward,
                    'open_interest': row['openInterest'],
                    'volume': row['totalTradedVolume']
                })
    
    # Analyze puts
    for _, row in option_chain.puts.iterrows():
        if row['strikePrice'] < current_price * 1.05 and row['strikePrice'] > current_price * 0.95:
            risk_reward = (current_price - row['strikePrice']) / row['lastPrice']
            if risk_reward > 2 and row['lastPrice'] * 100 <= budget:
                opportunities.append({
                    'type': 'PUT',
                    'strike': row['strikePrice'],
                    'premium': row['lastPrice'],
                    'risk_reward': risk_reward,
                    'open_interest': row['openInterest'],
                    'volume': row['totalTradedVolume']
                })
    
    return sorted(opportunities, key=lambda x: x['risk_reward'], reverse=True)

def fetch_news(symbol):
    """Fetch and analyze news for the given symbol"""
    try:
        # Fetch news from MoneyControl
        url = f"https://www.moneycontrol.com/news/tags/{symbol.lower()}.html"
        response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        news_items = soup.find_all('li', class_='clearfix')
        
        news_data = []
        for item in news_items[:5]:  # Get top 5 news
            title = item.find('h2').text.strip()
            link = item.find('a')['href']
            date = item.find('span', class_='article_time').text.strip()
            
            # Analyze sentiment
            sentiment = TextBlob(title).sentiment.polarity
            
            news_data.append({
                'title': title,
                'link': link,
                'date': date,
                'sentiment': sentiment
            })
        
        return news_data
    except Exception as e:
        st.error(f"Error fetching news: {str(e)}")
        return []

def predict_prices(data, days=5):
    """Predict future prices using Prophet"""
    # Prepare data for Prophet
    df = data.reset_index()[['Date', 'Close']]
    df.columns = ['ds', 'y']
    
    # Create and fit model
    model = Prophet(
        daily_seasonality=True,
        weekly_seasonality=True,
        yearly_seasonality=True,
        changepoint_prior_scale=0.05
    )
    model.fit(df)
    
    # Make future predictions
    future = model.make_future_dataframe(periods=days)
    forecast = model.predict(future)
    
    # Get predictions
    predictions = forecast['yhat'].tail(days).values
    
    return predictions, forecast

def derivatives_analysis_page():
    """Main derivatives analysis page"""
    st.title("📊 Derivatives Analysis & Predictions")
    
    # Sidebar controls
    st.sidebar.header("Analysis Parameters")
    selected_index = st.sidebar.selectbox(
        "Select Index",
        list(INDICES.keys())
    )
    
    analysis_type = st.sidebar.radio(
        "Analysis Type",
        ["Options", "Futures"]
    )
    
    if analysis_type == "Options":
        option_type = st.sidebar.radio(
            "Option Type",
            ["CE", "PE"]
        )
        
        expiry_date = st.sidebar.date_input(
            "Expiry Date",
            datetime.now() + timedelta(days=7)
        )
    
    # Fetch data
    symbol = INDICES[selected_index]
    data = yf.download(symbol, period="1y")
    
    # Calculate technical indicators
    data = calculate_technical_indicators(data)
    
    # Predict future prices
    future_prices, forecast = predict_prices(data)
    
    # Fetch and analyze news
    news_data = fetch_news(selected_index)
    
    # Display current metrics
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric(
            "Current Price",
            f"₹{data['Close'].iloc[-1]:,.2f}",
            f"{((data['Close'].iloc[-1] - data['Close'].iloc[-2]) / data['Close'].iloc[-2] * 100):,.2f}%"
        )
    
    with col2:
        st.metric(
            "Predicted Price (5 days)",
            f"₹{future_prices[-1]:,.2f}",
            f"{((future_prices[-1] - data['Close'].iloc[-1]) / data['Close'].iloc[-1] * 100):,.2f}%"
        )
    
    with col3:
        sentiment_score = np.mean([news['sentiment'] for news in news_data]) if news_data else 0
        st.metric(
            "News Sentiment",
            f"{sentiment_score:.2f}",
            "Positive" if sentiment_score > 0 else "Negative"
        )
    
    # Display trading signals
    st.subheader("Trading Signals")
    
    # Calculate signals based on technical indicators and predictions
    current_price = data['Close'].iloc[-1]
    predicted_price = future_prices[-1]
    rsi = data['RSI'].iloc[-1]
    macd = data['MACD'].iloc[-1]
    signal = data['Signal'].iloc[-1]
    
    # Generate trading signal
    if rsi < 30 and predicted_price > current_price and macd > signal:
        signal = "BUY"
        signal_color = "signal-buy"
    elif rsi > 70 and predicted_price < current_price and macd < signal:
        signal = "SELL"
        signal_color = "signal-sell"
    else:
        signal = "HOLD"
        signal_color = "signal-hold"
    
    st.markdown(f"""
        <div class="{signal_color}">
            <h3>Signal: {signal}</h3>
            <p>Current Price: ₹{current_price:,.2f}</p>
            <p>Predicted Price: ₹{predicted_price:,.2f}</p>
            <p>RSI: {rsi:.2f}</p>
            <p>MACD: {macd:.2f}</p>
            <p>News Sentiment: {sentiment_score:.2f}</p>
        </div>
    """, unsafe_allow_html=True)
    
    # Display price chart with predictions
    fig = make_subplots(rows=3, cols=1, 
                       shared_xaxes=True,
                       vertical_spacing=0.05,
                       subplot_titles=('Price', 'Volume', 'Technical Indicators'),
                       row_heights=[0.5, 0.2, 0.3])
    
    # Add candlestick chart
    fig.add_trace(go.Candlestick(x=data.index,
                                open=data['Open'],
                                high=data['High'],
                                low=data['Low'],
                                close=data['Close'],
                                name='Price'),
                  row=1, col=1)
    
    # Add predicted prices
    future_dates = pd.date_range(start=data.index[-1], periods=6)[1:]
    fig.add_trace(go.Scatter(x=future_dates,
                            y=future_prices,
                            name='Predicted',
                            line=dict(color='green', dash='dash')),
                  row=1, col=1)
    
    # Add Bollinger Bands
    fig.add_trace(go.Scatter(x=data.index, y=data['Upper'],
                            name='Upper BB',
                            line=dict(color='rgba(250, 0, 0, 0.3)')),
                  row=1, col=1)
    fig.add_trace(go.Scatter(x=data.index, y=data['MA20'],
                            name='Middle BB',
                            line=dict(color='rgba(0, 0, 250, 0.3)')),
                  row=1, col=1)
    fig.add_trace(go.Scatter(x=data.index, y=data['Lower'],
                            name='Lower BB',
                            line=dict(color='rgba(0, 250, 0, 0.3)')),
                  row=1, col=1)
    
    # Add volume bars
    fig.add_trace(go.Bar(x=data.index, y=data['Volume'],
                        name='Volume'),
                  row=2, col=1)
    
    # Add technical indicators
    fig.add_trace(go.Scatter(x=data.index, y=data['RSI'],
                            name='RSI',
                            line=dict(color='purple')),
                  row=3, col=1)
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
        title=f'{selected_index} Analysis',
        yaxis_title='Price',
        yaxis2_title='Volume',
        yaxis3_title='Indicator Value',
        xaxis_rangeslider_visible=False,
        height=1000,
        template='plotly_dark'
    )
    
    st.plotly_chart(fig, use_container_width=True)
    
    # Display news analysis
    st.subheader("Latest News Analysis")
    for news in news_data:
        sentiment_color = "green" if news['sentiment'] > 0 else "red"
        st.markdown(f"""
            <div style='background-color: #2D2D2D; padding: 1rem; border-radius: 0.5rem; margin: 0.5rem 0;'>
                <h4>{news['title']}</h4>
                <p>Date: {news['date']}</p>
                <p>Sentiment: <span style='color: {sentiment_color}'>{news['sentiment']:.2f}</span></p>
                <a href='{news['link']}' target='_blank'>Read More</a>
            </div>
        """, unsafe_allow_html=True)

if __name__ == "__main__":
    derivatives_analysis_page() 