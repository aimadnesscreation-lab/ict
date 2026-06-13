import httpx
import feedparser
from typing import List, Dict, Optional
from datetime import datetime
from loguru import logger


class NewsEngine:
    def __init__(self, sources: Optional[List[str]] = None):
        self.sources = sources or [
            "https://news.google.com/rss/search?q=forex+market+finance&hl=en-US&gl=US&ceid=US:en",
            "https://news.google.com/rss/search?q=cryptocurrency+trading&hl=en-US&gl=US&ceid=US:en",
        ]

    async def fetch_news(self) -> List[Dict]:
        """
        Fetch real news from RSS sources using feedparser.
        """
        all_articles = []
        async with httpx.AsyncClient() as client:
            for source in self.sources:
                try:
                    response = await client.get(source, timeout=15)
                    response.raise_for_status()
                    feed = feedparser.parse(response.text)

                    for entry in feed.entries[:10]:  # max 10 per source
                        title = entry.get("title", "")
                        summary = entry.get("summary", entry.get("description", ""))
                        published = entry.get("published_parsed") or entry.get("updated_parsed")

                        published_dt = datetime(*published[:6]) if published else datetime.utcnow()

                        # Analyze sentiment from the title + summary
                        sentiment = self._analyze_sentiment(f"{title} {summary}")

                        all_articles.append({
                            "title": title,
                            "source": source,
                            "published_at": published_dt,
                            "content": summary,
                            "sentiment": sentiment,
                        })

                    logger.info(f"Fetched {len(feed.entries)} articles from {source}")

                except Exception as e:
                    logger.warning(f"Failed to fetch news from {source}: {e}")

        return all_articles

    def analyze_sentiment(self, text: str) -> float:
        """Public wrapper for sentiment analysis."""
        return self._analyze_sentiment(text)

    def _analyze_sentiment(self, text: str) -> float:
        """
        Analyze sentiment of news text using keyword scoring.
        Scale: -1.0 to 1.0
        """
        positive_words = [
            "bullish", "growth", "strong", "upward", "gain", "higher", "positive",
            "surge", "rally", "rise", "rising", "increase", "gains", "breakthrough",
            "recovery", "optimistic", "momentum", "outperform", "upgrade",
        ]
        negative_words = [
            "bearish", "recession", "weak", "downward", "loss", "lower", "negative",
            "decline", "fall", "falling", "drop", "slump", "crash", "plunge",
            "inflation", "recession", "downturn", "selloff", "volatile",
            "uncertainty", "risk", "downgrade", "debt", "crisis",
        ]

        text_lower = text.lower()
        pos_count = sum(1 for word in positive_words if word in text_lower)
        neg_count = sum(1 for word in negative_words if word in text_lower)

        total = pos_count + neg_count
        if total == 0:
            return 0.0

        return round((pos_count - neg_count) / max(total, 1), 4)
