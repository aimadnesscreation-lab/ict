"""
Discord webhook notification bot.
Sends formatted trading signals to a Discord channel via webhook.
No VPN/proxy needed — Discord uses standard HTTPS.
"""

import httpx
from loguru import logger
from typing import Dict, Optional


class DiscordBot:
    """Send formatted trading signals to Discord via webhook."""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    async def send_signal(self, signal: Dict):
        """Format and send a signal to Discord as an embedded message."""
        embed = self._build_embed(signal)
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.webhook_url,
                    json={
                        "username": "ICT Signal Bot",
                        "embeds": [embed],
                    },
                )
                # Discord returns 204 No Content on success
                if response.status_code not in (200, 204):
                    logger.warning(
                        f"Discord webhook returned {response.status_code}: "
                        f"{response.text[:200]}"
                    )
                else:
                    logger.info(
                        f"Signal sent to Discord: {signal.get('symbol', '?')} "
                        f"{signal.get('signal_type', '?')} "
                        f"(Score: {signal.get('score', 0)})"
                    )
        except Exception as e:
            logger.error(f"Failed to send Discord message: {e}")

    def _build_embed(self, signal: Dict) -> Dict:
        """Build a rich Discord embed for the signal."""
        symbol = signal.get("symbol", "UNKNOWN")
        stype = signal.get("signal_type", "NEUTRAL")
        score = signal.get("score", 0)
        price = signal.get("price", 0)
        timeframe = signal.get("timeframe", "?")
        bias = signal.get("bias", "neutral")
        confidence = signal.get("confidence", 0.5)
        details = signal.get("details", {})

        # Determine embed color based on signal type
        if "STRONG_BUY" in stype or "BUY" in stype:
            color = 0x22c55e  # emerald green
        elif "STRONG_SELL" in stype or "SELL" in stype:
            color = 0xf43f5e  # rose red
        else:
            color = 0x64748b  # slate gray

        # Build confluence fields
        fields = [
            {
                "name": "Score",
                "value": f"**{score}/100**",
                "inline": True,
            },
            {
                "name": "Confidence",
                "value": f"**{round(confidence * 100)}%**",
                "inline": True,
            },
            {
                "name": "Timeframe",
                "value": f"**{timeframe}**",
                "inline": True,
            },
            {
                "name": "Trend Bias",
                "value": {
                    "bullish": "📈 **BULLISH**",
                    "bearish": "📉 **BEARISH**",
                    "neutral": "➖ **NEUTRAL**",
                }.get(bias, bias),
                "inline": True,
            },
            {
                "name": "Price",
                "value": f"`{price:,.4f}`",
                "inline": True,
            },
        ]

        # Confluence flags
        flags = []
        if details.get("mss"):
            flags.append("✅ MSS (+20)")
        if details.get("sweep"):
            flags.append("✅ Sweep (+20)")
        if details.get("fvg"):
            flags.append("✅ FVG (+15)")
        if details.get("ob"):
            flags.append("✅ OB (+15)")
        if details.get("discount"):
            flags.append("✅ Discount (+10)")
        if details.get("ote"):
            flags.append("✅ OTE (+10)")

        if flags:
            fields.append({
                "name": "Confluences",
                "value": "\n".join(flags),
                "inline": False,
            })

        # News sentiment
        news = details.get("news_sentiment", 0.0)
        if abs(news) > 0.1:
            sentiment_icon = "📰🟢" if news > 0 else "📰🔴"
            fields.append({
                "name": "News Sentiment",
                "value": f"{sentiment_icon} `{news:+.2f}`",
                "inline": False,
            })

        emoji = "🚀" if "BUY" in stype else "🔻" if "SELL" in stype else "➖"

        return {
            "title": f"{emoji} {symbol} — {stype.replace('_', ' ')}",
            "color": color,
            "fields": fields,
            "footer": {
                "text": "ICT Signal Engine",
            },
            "timestamp": (
                signal.get("timestamp")
                if isinstance(signal.get("timestamp"), str)
                else None
            ),
        }
