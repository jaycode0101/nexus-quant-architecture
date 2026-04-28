import streamlit as st

# Page config must be the first Streamlit command
st.set_page_config(
    page_title="Quant Research Dashboard",
    page_icon="📈",
    layout="wide"
)

from trading_dashboard import main as trading_dashboard

# Custom CSS
st.markdown("""
    <style>
    .main {
        padding: 2rem;
        background-color: #1E1E1E;
        color: #FFFFFF;
    }
    .stButton>button {
        width: 100%;
        background-color: #2E7D32;
        color: white;
    }
    .metric-card {
        background-color: #2D2D2D;
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 1rem 0;
        color: #FFFFFF;
    }
    .signal-buy {
        background-color: #1B5E20;
        color: #FFFFFF;
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 0.5rem 0;
    }
    .signal-sell {
        background-color: #B71C1C;
        color: #FFFFFF;
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 0.5rem 0;
    }
    .signal-hold {
        background-color: #F57F17;
        color: #FFFFFF;
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 0.5rem 0;
    }
    </style>
    """, unsafe_allow_html=True)

# Main content
trading_dashboard()

# Footer
st.markdown("---")
st.markdown("""
    <div style='text-align: center'>
        <p>Built with ❤️ using Streamlit</p>
        <p>Data source depends on your configured provider</p>
        <p>Disclaimer: This is not financial advice. Please do your own research before trading.</p>
    </div>
""", unsafe_allow_html=True) 
