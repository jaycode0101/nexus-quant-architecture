from trading_model.analysis.market_analyzer import MarketAnalyzer
from trading_model.analysis.news_analyzer import NewsAnalyzer
from trading_model.config.settings import NSE_SYMBOLS
import pandas as pd
from datetime import datetime
import plotly.io as pio
import os

def main():
    """
    Main function to demonstrate the trading system capabilities.
    """
    print("Initializing Trading System...")
    
    # Create charts directory if it doesn't exist
    os.makedirs('charts', exist_ok=True)
    
    # Initialize analyzers
    market_analyzer = MarketAnalyzer()
    news_analyzer = NewsAnalyzer()
    
    # Analyze each symbol
    for symbol in NSE_SYMBOLS:
        print(f"\nAnalyzing {symbol}...")
        
        # Get market analysis
        market_analysis = market_analyzer.analyze_market_trends(symbol)
        
        # Get news analysis
        news_analysis = news_analyzer.analyze_news(symbol)
        
        # Print results
        print("\nMarket Analysis:")
        print(f"Technical Analysis: {market_analysis['ai_analysis']}")
        
        print("\nNews Analysis:")
        print(f"Sentiment Trend: {news_analysis['sentiment_analysis']['sentiment_trend']}")
        print(f"Market Impact: {news_analysis['market_impact']['recommendation']}")
        
        # Save chart
        chart_path = f"charts/{symbol}_{datetime.now().strftime('%Y%m%d')}.html"
        pio.write_html(market_analysis['chart'], chart_path)
        print(f"\nChart saved to: {chart_path}")
        
        print("\n" + "="*50)

if __name__ == "__main__":
    main() 