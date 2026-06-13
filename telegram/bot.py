import httpx
from loguru import logger
from typing import Dict, Optional

class TelegramBot:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{self.token}/sendMessage"

    async def send_signal(self, signal: Dict):
        """
        Format and send a signal to Telegram.
        """
        text = self._format_signal(signal)
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(self.api_url, json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "Markdown"
                })
                response.raise_for_status()
                logger.info(f"Signal sent to Telegram: {signal['signal_type']}")
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")

    def _format_signal(self, signal: Dict) -> str:
        symbol = signal.get("symbol", "UNKNOWN")
        stype = signal["signal_type"]
        score = signal["score"]
        price = signal["price"]
        details = signal["details"]
        
        emoji = "🚀" if "BUY" in stype else "🔻" if "SELL" in stype else "➖"
        
        msg = [
            f"{emoji} *{symbol} {stype}*",
            f"Score: `{score}/100`",
            f"Price: `{price}`",
            "",
            "*Confluences:*",
            f"- MSS: {'✅' if details['mss'] else '❌'}",
            f"- Sweep: {'✅' if details['sweep'] else '❌'}",
            f"- FVG: {'✅' if details['fvg'] else '❌'}",
            f"- Order Block: {'✅' if details['ob'] else '❌'}",
            f"- News Sentiment: `{details['news_sentiment']}`"
        ]
        
        return "\n".join(msg)
