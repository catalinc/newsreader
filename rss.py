import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html import unescape

import feedparser

logger = logging.getLogger(__name__)


@dataclass
class Article:
    title: str
    url: str
    source: str
    category: str
    summary: str = ""
    published: datetime | None = None
    bookmarked: bool = False

    @property
    def published_str(self) -> str:
        if self.published:
            return self.published.strftime("%b %d, %Y")
        return ""


async def fetch_feed(feed_info: dict) -> list[Article]:
    """Fetch and parse a single RSS feed asynchronously."""
    loop = asyncio.get_event_loop()
    try:
        parsed = await loop.run_in_executor(None, feedparser.parse, feed_info["url"])
    except Exception:
        logger.warning("Failed to fetch feed %s", feed_info["url"], exc_info=True)
        return []

    articles = []
    for entry in parsed.entries[:20]:  # cap at 20 per feed
        published = None
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                published = datetime(*entry.published_parsed[:6], tzinfo=UTC)
            except Exception:
                logger.warning("Failed to parse published date for %s", feed_info["url"], exc_info=True)

        summary = getattr(entry, "summary", "") or ""
        # strip basic html tags from summary
        summary = unescape(re.sub(r"<[^>]+>", "", summary).strip())
        summary = summary[:300] + "…" if len(summary) > 300 else summary

        articles.append(Article(
            title=unescape(getattr(entry, "title", "No title")),
            url=getattr(entry, "link", ""),
            source=feed_info["name"],
            category=feed_info["category"],
            summary=summary,
            published=published,
        ))

    return articles


async def fetch_all_feeds(feeds: list[dict]) -> list[Article]:
    """Fetch all feeds concurrently."""
    results = await asyncio.gather(*[fetch_feed(f) for f in feeds])
    articles = [a for feed_articles in results for a in feed_articles]
    # sort by published date, newest first
    articles.sort(key=lambda a: a.published or datetime.min.replace(tzinfo=UTC), reverse=True)
    return articles
