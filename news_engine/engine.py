import httpx
from typing import List, Dict, Optional
from datetime import datetime
from loguru import logger

class NewsEngine:
    def __init__(self, sources: Optional[List[str]] = None):
        self.sources = sources or ["https://news.google.com/rss/search?q=forex+market"]

    async def fetch_news(self) -> List[Dict]:
        """
        Fetch news from various sources.
        """
        all_articles = []
        async with httpx.AsyncClient() as client:
            for source in self.sources:
                try:
                    # In a real scenario, we'd parse XML/RSS here
                    # For now, we mock the result
                    logger.info(f"Fetching news from {source}")
                    articles = self._mock_news()
                    all_articles.extend(articles)
                except Exception as e:
                    logger.error(f"Failed to fetch news from {source}: {e}")
        return all_articles

    def analyze_sentiment(self, text: str) -> float:
        """
        Analyze sentiment of news text.
        Scale: -1.0 to 1.0
        """
        # Simplified keyword-based sentiment for demonstration
        positive_words = ["bullish", "growth", "strong", "upward", "gain", "higher", "positive"]
        negative_words = ["bearish", "recession", "weak", "downward", "loss", "lower", "negative"]
        
        text_lower = text.lower()
        pos_count = sum(1 for word in positive_words if word in text_lower)
        neg_count = sum(1 for word in negative_words if word in text_lower)
        
        total = pos_count + neg_count
        if total == 0:
            return 0.0
            
        return (pos_count - neg_count) / total

    def _mock_news(self) -> List[Dict]:
        return [
            {
                "title": "US Dollar remains strong amid inflation data",
                "source": "Mock Finance",
                "published_at": datetime.utcnow(),
                "content": "The US Dollar index showed bullish momentum today as inflation data suggests higher interest rates for longer."
            },
            {
                "title": "Euro falls as ECB signals potential pause",
                "source": "Mock News",
                "published_at": datetime.utcnow(),
                "content": "The Euro is under pressure today after the ECB hinted at a potential pause in rate hikes, leading to bearish sentiment."
            }
        ]
