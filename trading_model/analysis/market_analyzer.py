import google.generativeai as genai
import pandas as pd
import pandas_ta as ta
import numpy as np
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from ..config.settings import GEMINI_API_KEY, TECHNICAL_INDICATORS
from ..utils.data_fetcher import DataFetcher
import plotly.graph_objects as go
from plotly.subplots import make_subplots

class MarketAnalyzer:
    """
    Market analysis class that uses Gemini AI for market insights and technical analysis.
    """
    
    def __init__(self):
        """Initialize the market analyzer with Gemini AI configuration."""
        genai.configure(api_key=GEMINI_API_KEY)
        self.model = genai.GenerativeModel('gemini-pro')
        self.data_fetcher = DataFetcher()
        
    def analyze_market_trends(self, symbol: str, timeframe: str = '1d') -> Dict:
        """
        Analyze market trends using Gemini AI and technical indicators.
        
        Args:
            symbol: Stock or index symbol
            timeframe: Data timeframe
            
        Returns:
            Dictionary containing market analysis
        """
        # Fetch historical data
        data = self.data_fetcher.fetch_yahoo_data(symbol, interval=timeframe)
        
        # Calculate technical indicators
        technical_analysis = self._calculate_technical_indicators(data)
        
        # Generate AI analysis
        prompt = self._create_analysis_prompt(data, technical_analysis)
        ai_analysis = self._get_ai_analysis(prompt)
        
        return {
            'symbol': symbol,
            'timestamp': datetime.now(),
            'technical_analysis': technical_analysis,
            'ai_analysis': ai_analysis,
            'chart': self._create_interactive_chart(data, technical_analysis)
        }
    
    def _calculate_technical_indicators(self, data: pd.DataFrame) -> Dict:
        """Calculate technical indicators for the given data."""
        indicators = {}
        
        # RSI
        indicators['RSI'] = data.ta.rsi(length=TECHNICAL_INDICATORS['RSI']['period'])
        
        # MACD
        macd = data.ta.macd(
            fast=TECHNICAL_INDICATORS['MACD']['fast'],
            slow=TECHNICAL_INDICATORS['MACD']['slow'],
            signal=TECHNICAL_INDICATORS['MACD']['signal']
        )
        indicators['MACD'] = macd['MACD_12_26_9']
        indicators['Signal'] = macd['MACDs_12_26_9']
        
        # Bollinger Bands
        bollinger = data.ta.bbands(
            length=TECHNICAL_INDICATORS['Bollinger']['period'],
            std=TECHNICAL_INDICATORS['Bollinger']['std_dev']
        )
        indicators['SMA'] = bollinger['BBM_20_2.0']
        indicators['Upper_Band'] = bollinger['BBU_20_2.0']
        indicators['Lower_Band'] = bollinger['BBL_20_2.0']
        
        # Additional indicators
        indicators['ATR'] = data.ta.atr(length=TECHNICAL_INDICATORS['ATR']['period'])
        indicators['Stochastic'] = data.ta.stoch()
        
        return indicators
    
    def _create_analysis_prompt(self, data: pd.DataFrame, technical_analysis: Dict) -> str:
        """Create a prompt for Gemini AI analysis."""
        latest_price = data['close'].iloc[-1]
        price_change = ((latest_price - data['close'].iloc[-2]) / data['close'].iloc[-2]) * 100
        
        prompt = f"""
        Analyze the following market data for {data.index[-1].strftime('%Y-%m-%d')}:
        
        Current Price: {latest_price:.2f}
        Price Change: {price_change:.2f}%
        
        Technical Indicators:
        RSI: {technical_analysis['RSI'].iloc[-1]:.2f}
        MACD: {technical_analysis['MACD'].iloc[-1]:.2f}
        Signal: {technical_analysis['Signal'].iloc[-1]:.2f}
        ATR: {technical_analysis['ATR'].iloc[-1]:.2f}
        
        Please provide:
        1. Market trend analysis
        2. Key support and resistance levels
        3. Trading recommendations
        4. Risk assessment
        """
        
        return prompt
    
    def _get_ai_analysis(self, prompt: str) -> str:
        """Get analysis from Gemini AI."""
        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            return f"Error getting AI analysis: {str(e)}"
    
    def _create_interactive_chart(self, data: pd.DataFrame, technical_analysis: Dict) -> go.Figure:
        """Create an interactive chart with technical indicators."""
        fig = make_subplots(rows=3, cols=1, 
                           shared_xaxes=True,
                           vertical_spacing=0.05,
                           subplot_titles=('Price', 'RSI', 'MACD'),
                           row_heights=[0.5, 0.25, 0.25])

        # Candlestick chart
        fig.add_trace(go.Candlestick(x=data.index,
                                    open=data['open'],
                                    high=data['high'],
                                    low=data['low'],
                                    close=data['close'],
                                    name='OHLC'),
                     row=1, col=1)

        # Bollinger Bands
        fig.add_trace(go.Scatter(x=data.index, y=technical_analysis['Upper_Band'],
                                name='Upper Band', line=dict(color='gray', dash='dash')),
                     row=1, col=1)
        fig.add_trace(go.Scatter(x=data.index, y=technical_analysis['Lower_Band'],
                                name='Lower Band', line=dict(color='gray', dash='dash')),
                     row=1, col=1)

        # RSI
        fig.add_trace(go.Scatter(x=data.index, y=technical_analysis['RSI'],
                                name='RSI', line=dict(color='purple')),
                     row=2, col=1)

        # MACD
        fig.add_trace(go.Scatter(x=data.index, y=technical_analysis['MACD'],
                                name='MACD', line=dict(color='blue')),
                     row=3, col=1)
        fig.add_trace(go.Scatter(x=data.index, y=technical_analysis['Signal'],
                                name='Signal', line=dict(color='orange')),
                     row=3, col=1)

        # Add overbought/oversold lines for RSI
        fig.add_hline(y=70, line_dash="dash", line_color="red", row=2, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="green", row=2, col=1)

        fig.update_layout(
            title='Technical Analysis Chart',
            yaxis_title='Price',
            yaxis2_title='RSI',
            yaxis3_title='MACD',
            xaxis_rangeslider_visible=False,
            height=800
        )

        return fig 