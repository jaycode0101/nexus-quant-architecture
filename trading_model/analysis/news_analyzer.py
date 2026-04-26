import requests
from bs4 import BeautifulSoup
from textblob import TextBlob
import pandas as pd
from typing import List, Dict
from datetime import datetime, timedelta
from ..config.settings import NEWS_SOURCES, SENTIMENT_THRESHOLD
import nltk
from nltk.tokenize import word_tokenize
from nltk.corpus import stopwords

class NewsAnalyzer:
    """
    News analysis class for sentiment analysis and market impact assessment.
    """
    
    def __init__(self):
        """Initialize the news analyzer with NLTK downloads."""
        nltk.download('punkt')
        nltk.download('stopwords')
        self.stop_words = set(stopwords.words('english'))
        
    def analyze_news(self, symbol: str) -> Dict:
        """
        Analyze news articles related to the given symbol.
        
        Args:
            symbol: Stock or index symbol
            
        Returns:
            Dictionary containing news analysis results
        """
        articles = self._fetch_news(symbol)
        sentiments = self._analyze_sentiments(articles)
        
        return {
            'symbol': symbol,
            'timestamp': datetime.now(),
            'articles': articles,
            'sentiment_analysis': sentiments,
            'market_impact': self._assess_market_impact(sentiments)
        }
    
    def _fetch_news(self, symbol: str) -> List[Dict]:
        """Fetch news articles from various sources."""
        articles = []
        
        for source in NEWS_SOURCES:
            try:
                # Example URL construction (you'll need to implement specific scraping for each source)
                url = f"https://{source}/search?q={symbol}"
                response = requests.get(url)
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Extract articles (implementation will vary by source)
                article_elements = soup.find_all('article')  # Adjust based on source structure
                
                for article in article_elements[:5]:  # Limit to 5 articles per source
                    title = article.find('h2').text.strip()
                    content = article.find('div', class_='content').text.strip()
                    date = article.find('time').text.strip()
                    
                    articles.append({
                        'title': title,
                        'content': content,
                        'date': date,
                        'source': source
                    })
            except Exception as e:
                print(f"Error fetching news from {source}: {str(e)}")
                
        return articles
    
    def _analyze_sentiments(self, articles: List[Dict]) -> Dict:
        """Analyze sentiment of news articles."""
        sentiments = []
        
        for article in articles:
            # Combine title and content for analysis
            text = f"{article['title']} {article['content']}"
            
            # Tokenize and remove stop words
            tokens = word_tokenize(text.lower())
            tokens = [t for t in tokens if t not in self.stop_words]
            
            # Calculate sentiment
            blob = TextBlob(text)
            sentiment_score = blob.sentiment.polarity
            
            sentiments.append({
                'title': article['title'],
                'sentiment_score': sentiment_score,
                'date': article['date'],
                'source': article['source']
            })
        
        # Calculate aggregate sentiment
        avg_sentiment = sum(s['sentiment_score'] for s in sentiments) / len(sentiments) if sentiments else 0
        
        return {
            'articles': sentiments,
            'average_sentiment': avg_sentiment,
            'sentiment_trend': 'positive' if avg_sentiment > SENTIMENT_THRESHOLD else 'negative' if avg_sentiment < -SENTIMENT_THRESHOLD else 'neutral'
        }
    
    def _assess_market_impact(self, sentiments: Dict) -> Dict:
        """Assess potential market impact based on news sentiment."""
        avg_sentiment = sentiments['average_sentiment']
        
        impact = {
            'level': 'high' if abs(avg_sentiment) > 0.5 else 'medium' if abs(avg_sentiment) > 0.2 else 'low',
            'direction': 'positive' if avg_sentiment > 0 else 'negative',
            'confidence': min(abs(avg_sentiment) * 2, 1.0),  # Scale to 0-1
            'recommendation': self._generate_recommendation(avg_sentiment)
        }
        
        return impact
    
    def _generate_recommendation(self, sentiment: float) -> str:
        """Generate trading recommendation based on sentiment."""
        if sentiment > 0.5:
            return "Strong buy signal based on positive news sentiment"
        elif sentiment > 0.2:
            return "Moderate buy signal based on positive news sentiment"
        elif sentiment < -0.5:
            return "Strong sell signal based on negative news sentiment"
        elif sentiment < -0.2:
            return "Moderate sell signal based on negative news sentiment"
        else:
            return "Neutral position recommended based on mixed news sentiment" 