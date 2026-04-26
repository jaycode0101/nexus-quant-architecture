import yfinance as yf
import pandas as pd
from typing import Optional, List, Union, Dict
from datetime import datetime, timedelta

class DataFetcher:
    """
    Utility class for fetching market data from various sources.
    """
    
    def __init__(self):
        """Initialize the data fetcher."""
        pass
    
    def fetch_yahoo_data(
        self,
        symbol: str,
        start_date: Optional[Union[str, datetime]] = None,
        end_date: Optional[Union[str, datetime]] = None,
        interval: str = '1d'
    ) -> pd.DataFrame:
        """
        Fetch historical data from Yahoo Finance.
        
        Args:
            symbol: Stock symbol (e.g., 'AAPL')
            start_date: Start date for historical data
            end_date: End date for historical data
            interval: Data interval ('1d', '1h', '1m', etc.)
            
        Returns:
            DataFrame containing historical price data
        """
        if start_date is None:
            start_date = datetime.now() - timedelta(days=365)
        if end_date is None:
            end_date = datetime.now()
            
        ticker = yf.Ticker(symbol)
        df = ticker.history(start=start_date, end=end_date, interval=interval)
        
        # Clean and prepare the data
        df = df.rename(columns={
            'Open': 'open',
            'High': 'high',
            'Low': 'low',
            'Close': 'close',
            'Volume': 'volume'
        })
        
        return df
    
    def fetch_multiple_symbols(
        self,
        symbols: List[str],
        start_date: Optional[Union[str, datetime]] = None,
        end_date: Optional[Union[str, datetime]] = None,
        interval: str = '1d'
    ) -> Dict[str, pd.DataFrame]:
        """
        Fetch historical data for multiple symbols.
        
        Args:
            symbols: List of stock symbols
            start_date: Start date for historical data
            end_date: End date for historical data
            interval: Data interval
            
        Returns:
            Dictionary mapping symbols to their respective DataFrames
        """
        return {
            symbol: self.fetch_yahoo_data(symbol, start_date, end_date, interval)
            for symbol in symbols
        } 