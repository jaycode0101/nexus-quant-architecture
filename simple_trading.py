import os

import matplotlib.pyplot as plt
import yfinance as yf


def configured_watchlist() -> list[str]:
    raw = os.getenv("WATCHLIST", "SPY,QQQ,BTC-USD")
    return [symbol.strip() for symbol in raw.split(",") if symbol.strip()]


def get_market_data(symbol: str, period: str = "1y"):
    ticker = yf.Ticker(symbol)
    return ticker.history(period=period)


def calculate_signals(data):
    data["SMA20"] = data["Close"].rolling(window=20).mean()
    data["SMA50"] = data["Close"].rolling(window=50).mean()

    data["Signal"] = 0
    data.loc[data["SMA20"] > data["SMA50"], "Signal"] = 1
    data.loc[data["SMA20"] < data["SMA50"], "Signal"] = -1
    return data


def plot_analysis(data, symbol: str) -> None:
    plt.figure(figsize=(12, 6))
    plt.plot(data.index, data["Close"], label="Price", color="blue")
    plt.plot(data.index, data["SMA20"], label="20-bar MA", color="red")
    plt.plot(data.index, data["SMA50"], label="50-bar MA", color="green")

    buy_signals = data[data["Signal"] == 1]
    plt.scatter(
        buy_signals.index,
        buy_signals["Close"],
        marker="^",
        color="green",
        label="Buy Signal",
    )

    sell_signals = data[data["Signal"] == -1]
    plt.scatter(
        sell_signals.index,
        sell_signals["Close"],
        marker="v",
        color="red",
        label="Sell Signal",
    )

    plt.title(f"{symbol} Moving-Average Signal")
    plt.xlabel("Date")
    plt.ylabel("Price")
    plt.legend()
    plt.grid(True)
    plt.savefig(f"{symbol.replace('/', '-')}_analysis.png")
    plt.close()


def analyze_symbol(symbol: str) -> None:
    print(f"\nAnalyzing {symbol}...")

    try:
        data = calculate_signals(get_market_data(symbol))
        latest_price = data["Close"].iloc[-1]
        latest_signal = data["Signal"].iloc[-1]

        print(f"\nCurrent price: {latest_price:.2f}")
        print(f"20-bar MA: {data['SMA20'].iloc[-1]:.2f}")
        print(f"50-bar MA: {data['SMA50'].iloc[-1]:.2f}")

        if latest_signal == 1:
            print("\nSignal: BUY")
            print("Reason: 20-bar moving average is above the 50-bar average")
        elif latest_signal == -1:
            print("\nSignal: SELL")
            print("Reason: 20-bar moving average is below the 50-bar average")
        else:
            print("\nSignal: HOLD")
            print("Reason: moving averages are not giving a directional signal")

        plot_analysis(data, symbol)
        print(f"\nChart saved as {symbol.replace('/', '-')}_analysis.png")
    except (KeyError, IndexError, ValueError) as exc:
        print(f"Could not analyze {symbol}: {exc}")


def main() -> None:
    for symbol in configured_watchlist():
        analyze_symbol(symbol)
        print("\n" + "=" * 50)


if __name__ == "__main__":
    main()
