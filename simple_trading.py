import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta

def get_stock_data(symbol, period='1y'):
    """Fetch stock data from Yahoo Finance"""
    stock = yf.Ticker(symbol)
    data = stock.history(period=period)
    return data

def calculate_signals(data):
    """Calculate simple moving averages and trading signals"""
    # Calculate 20-day and 50-day moving averages
    data['SMA20'] = data['Close'].rolling(window=20).mean()
    data['SMA50'] = data['Close'].rolling(window=50).mean()
    
    # Generate signals
    data['Signal'] = 0
    data.loc[data['SMA20'] > data['SMA50'], 'Signal'] = 1  # Buy signal
    data.loc[data['SMA20'] < data['SMA50'], 'Signal'] = -1  # Sell signal
    
    return data

def plot_stock_analysis(data, symbol):
    """Plot stock price and moving averages"""
    plt.figure(figsize=(12, 6))
    plt.plot(data.index, data['Close'], label='Price', color='blue')
    plt.plot(data.index, data['SMA20'], label='20-day MA', color='red')
    plt.plot(data.index, data['SMA50'], label='50-day MA', color='green')
    
    # Plot buy signals
    buy_signals = data[data['Signal'] == 1]
    plt.scatter(buy_signals.index, buy_signals['Close'], 
                marker='^', color='green', label='Buy Signal')
    
    # Plot sell signals
    sell_signals = data[data['Signal'] == -1]
    plt.scatter(sell_signals.index, sell_signals['Close'], 
                marker='v', color='red', label='Sell Signal')
    
    plt.title(f'{symbol} Stock Analysis')
    plt.xlabel('Date')
    plt.ylabel('Price')
    plt.legend()
    plt.grid(True)
    
    # Save the plot
    plt.savefig(f'{symbol}_analysis.png')
    plt.close()

def analyze_stock(symbol):
    """Analyze a stock and generate trading signals"""
    print(f"\nAnalyzing {symbol}...")
    
    try:
        # Get stock data
        data = get_stock_data(symbol)
        
        # Calculate signals
        data = calculate_signals(data)
        
        # Get latest signals
        latest_price = data['Close'].iloc[-1]
        latest_signal = data['Signal'].iloc[-1]
        
        # Print analysis
        print(f"\nCurrent Price: {latest_price:.2f}")
        print(f"20-day MA: {data['SMA20'].iloc[-1]:.2f}")
        print(f"50-day MA: {data['SMA50'].iloc[-1]:.2f}")
        
        if latest_signal == 1:
            print("\nTrading Signal: BUY")
            print("Reason: 20-day moving average is above 50-day moving average")
        elif latest_signal == -1:
            print("\nTrading Signal: SELL")
            print("Reason: 20-day moving average is below 50-day moving average")
        else:
            print("\nTrading Signal: HOLD")
            print("Reason: No clear trend in moving averages")
        
        # Plot the analysis
        plot_stock_analysis(data, symbol)
        print(f"\nAnalysis chart saved as {symbol}_analysis.png")
        
    except Exception as e:
        print(f"Error analyzing {symbol}: {str(e)}")

def main():
    # List of stocks to analyze
    stocks = ['RELIANCE.NS', 'TCS.NS', 'HDFCBANK.NS']
    
    for stock in stocks:
        analyze_stock(stock)
        print("\n" + "="*50)

if __name__ == "__main__":
    main() 