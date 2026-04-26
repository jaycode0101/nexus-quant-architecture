from abc import ABC, abstractmethod
import pandas as pd
from typing import Dict, Any, Optional

class BaseStrategy(ABC):
    """
    Base class for all trading strategies.
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the strategy with optional configuration.
        
        Args:
            config: Dictionary containing strategy configuration parameters
        """
        self.config = config or {}
        self.position = 0
        self.trades = []
        
    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Generate trading signals based on the input data.
        
        Args:
            data: DataFrame containing price and indicator data
            
        Returns:
            DataFrame with trading signals
        """
        pass
    
    @abstractmethod
    def calculate_position_size(self, signal: float, price: float) -> float:
        """
        Calculate the position size based on the signal and current price.
        
        Args:
            signal: Trading signal (-1 to 1)
            price: Current price of the asset
            
        Returns:
            Position size to take
        """
        pass
    
    def update_position(self, signal: float, price: float):
        """
        Update the current position based on the signal.
        
        Args:
            signal: Trading signal (-1 to 1)
            price: Current price of the asset
        """
        position_size = self.calculate_position_size(signal, price)
        self.position += position_size
        self.trades.append({
            'timestamp': pd.Timestamp.now(),
            'price': price,
            'size': position_size,
            'signal': signal
        })
    
    def get_performance_metrics(self) -> Dict[str, float]:
        """
        Calculate and return performance metrics.
        
        Returns:
            Dictionary containing performance metrics
        """
        if not self.trades:
            return {}
            
        trades_df = pd.DataFrame(self.trades)
        return {
            'total_trades': len(self.trades),
            'avg_price': trades_df['price'].mean(),
            'total_position': self.position
        } 