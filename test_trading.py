import os

from trading_model.analysis.market_analyzer import MarketAnalyzer


def main() -> None:
    os.makedirs("charts", exist_ok=True)
    analyzer = MarketAnalyzer()

    symbol = os.getenv("SMOKE_SYMBOL", "SPY")
    print(f"\nAnalyzing {symbol}...")

    try:
        analysis = analyzer.analyze_market_trends(symbol)
    except (KeyError, ValueError, RuntimeError) as exc:
        print(f"Error analyzing {symbol}: {exc}")
        return

    print("\nMarket Analysis:")
    print(f"Technical Analysis: {analysis['ai_analysis']}")

    chart_path = f"charts/{symbol.replace('/', '-')}_{analysis['timestamp'].strftime('%Y%m%d')}.html"
    analysis["chart"].write_html(chart_path)
    print(f"\nChart saved to: {chart_path}")


if __name__ == "__main__":
    main()
