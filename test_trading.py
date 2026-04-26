from trading_model.analysis.market_analyzer import MarketAnalyzer
import os

def main():
    # Create charts directory
    os.makedirs('charts', exist_ok=True)
    
    # Initialize analyzer
    analyzer = MarketAnalyzer()
    
    # Test with a single symbol
    symbol = 'RELIANCE.NS'  # Using .NS suffix for NSE stocks
    print(f"\nAnalyzing {symbol}...")
    
    try:
        # Get market analysis
        analysis = analyzer.analyze_market_trends(symbol)
        
        # Print results
        print("\nMarket Analysis:")
        print(f"Technical Analysis: {analysis['ai_analysis']}")
        
        # Save chart
        chart_path = f"charts/{symbol.replace('.NS', '')}_{analysis['timestamp'].strftime('%Y%m%d')}.html"
        analysis['chart'].write_html(chart_path)
        print(f"\nChart saved to: {chart_path}")
        
    except Exception as e:
        print(f"Error analyzing {symbol}: {str(e)}")

if __name__ == "__main__":
    main() 