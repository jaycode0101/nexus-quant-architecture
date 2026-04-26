import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta

def load_portfolio():
    """Load portfolio from session state or create new one"""
    if 'portfolio' not in st.session_state:
        st.session_state.portfolio = pd.DataFrame(columns=[
            'Symbol', 'Quantity', 'Buy Price', 'Buy Date', 'Current Price', 
            'Market Value', 'Profit/Loss', 'Profit/Loss %'
        ])
    return st.session_state.portfolio

def add_stock_to_portfolio(symbol, quantity, buy_price, buy_date):
    """Add a new stock to the portfolio"""
    portfolio = load_portfolio()
    
    # Get current price
    stock = yf.Ticker(symbol)
    current_price = stock.history(period='1d')['Close'].iloc[-1]
    
    # Calculate market value and profit/loss
    market_value = quantity * current_price
    cost_basis = quantity * buy_price
    profit_loss = market_value - cost_basis
    profit_loss_pct = (profit_loss / cost_basis) * 100
    
    # Add new row to portfolio
    new_row = pd.DataFrame({
        'Symbol': [symbol],
        'Quantity': [quantity],
        'Buy Price': [buy_price],
        'Buy Date': [buy_date],
        'Current Price': [current_price],
        'Market Value': [market_value],
        'Profit/Loss': [profit_loss],
        'Profit/Loss %': [profit_loss_pct]
    })
    
    st.session_state.portfolio = pd.concat([portfolio, new_row], ignore_index=True)

def remove_stock_from_portfolio(index):
    """Remove a stock from the portfolio"""
    portfolio = load_portfolio()
    st.session_state.portfolio = portfolio.drop(index)

def update_portfolio_values():
    """Update current prices and profit/loss calculations"""
    portfolio = load_portfolio()
    
    for idx, row in portfolio.iterrows():
        stock = yf.Ticker(row['Symbol'])
        current_price = stock.history(period='1d')['Close'].iloc[-1]
        
        market_value = row['Quantity'] * current_price
        cost_basis = row['Quantity'] * row['Buy Price']
        profit_loss = market_value - cost_basis
        profit_loss_pct = (profit_loss / cost_basis) * 100
        
        portfolio.at[idx, 'Current Price'] = current_price
        portfolio.at[idx, 'Market Value'] = market_value
        portfolio.at[idx, 'Profit/Loss'] = profit_loss
        portfolio.at[idx, 'Profit/Loss %'] = profit_loss_pct
    
    st.session_state.portfolio = portfolio

def create_portfolio_chart(portfolio):
    """Create portfolio performance chart"""
    fig = go.Figure()
    
    # Add each stock's performance
    for _, row in portfolio.iterrows():
        stock = yf.Ticker(row['Symbol'])
        start_date = row['Buy Date']
        end_date = datetime.now()
        
        # Get historical data
        hist = stock.history(start=start_date, end=end_date)
        
        # Calculate investment value over time
        investment_value = hist['Close'] * row['Quantity']
        
        fig.add_trace(go.Scatter(
            x=hist.index,
            y=investment_value,
            name=row['Symbol'],
            mode='lines'
        ))
    
    # Add total portfolio value
    total_value = portfolio['Market Value'].sum()
    fig.add_hline(y=total_value, line_dash="dash", line_color="red",
                 annotation_text=f"Total Value: ₹{total_value:,.2f}")
    
    fig.update_layout(
        title="Portfolio Performance",
        xaxis_title="Date",
        yaxis_title="Value (₹)",
        height=500
    )
    
    return fig

def portfolio_page():
    """Main portfolio tracking page"""
    st.title("📊 Portfolio Tracker")
    
    # Sidebar for adding stocks
    with st.sidebar:
        st.header("Add Stock")
        
        symbol = st.text_input("Stock Symbol (e.g., RELIANCE.NS)")
        quantity = st.number_input("Quantity", min_value=1, value=1)
        buy_price = st.number_input("Buy Price (₹)", min_value=0.0)
        buy_date = st.date_input("Buy Date")
        
        if st.button("Add to Portfolio"):
            if symbol:
                add_stock_to_portfolio(symbol, quantity, buy_price, buy_date)
                st.success(f"Added {symbol} to portfolio!")
            else:
                st.error("Please enter a stock symbol")
    
    # Main content
    portfolio = load_portfolio()
    
    if not portfolio.empty:
        # Update portfolio values
        update_portfolio_values()
        
        # Display portfolio summary
        total_investment = (portfolio['Quantity'] * portfolio['Buy Price']).sum()
        total_value = portfolio['Market Value'].sum()
        total_profit_loss = portfolio['Profit/Loss'].sum()
        total_profit_loss_pct = (total_profit_loss / total_investment) * 100
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Investment", f"₹{total_investment:,.2f}")
        with col2:
            st.metric("Current Value", f"₹{total_value:,.2f}")
        with col3:
            st.metric("Profit/Loss", f"₹{total_profit_loss:,.2f}")
        with col4:
            st.metric("Profit/Loss %", f"{total_profit_loss_pct:.2f}%")
        
        # Display portfolio chart
        st.plotly_chart(create_portfolio_chart(portfolio), use_container_width=True)
        
        # Display portfolio table
        st.header("Portfolio Holdings")
        
        # Format the dataframe for display
        display_df = portfolio.copy()
        display_df['Buy Price'] = display_df['Buy Price'].map('₹{:,.2f}'.format)
        display_df['Current Price'] = display_df['Current Price'].map('₹{:,.2f}'.format)
        display_df['Market Value'] = display_df['Market Value'].map('₹{:,.2f}'.format)
        display_df['Profit/Loss'] = display_df['Profit/Loss'].map('₹{:,.2f}'.format)
        display_df['Profit/Loss %'] = display_df['Profit/Loss %'].map('{:.2f}%'.format)
        
        st.dataframe(display_df)
        
        # Add delete buttons for each stock
        for idx, row in portfolio.iterrows():
            if st.button(f"Remove {row['Symbol']}", key=f"remove_{idx}"):
                remove_stock_from_portfolio(idx)
                st.experimental_rerun()
    else:
        st.info("Your portfolio is empty. Add stocks using the sidebar.")

if __name__ == "__main__":
    portfolio_page() 