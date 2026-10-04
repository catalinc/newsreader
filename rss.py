import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html import unescape

import feedparser

logger = logging.getLogger(__name__)

SUMMARY_LIMIT = 300  # visible characters, not counting URLs

URL_RE = re.compile(r"(https?://[^\s<>\"']+)", re.IGNORECASE)
_BLOCK_BREAK_RE = re.compile(r"<br\s*/?>|</(?:p|div|li|h[1-6]|tr|blockquote)>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


def clean_summary(html: str) -> str:
    """Strip HTML from a feed summary, keeping paragraphs and line breaks as lines."""
    text = _TAG_RE.sub("", _BLOCK_BREAK_RE.sub("\n", html))
    lines = (" ".join(unescape(line).split()) for line in text.splitlines())
    return truncate_summary("\n".join(line for line in lines if line))


def truncate_summary(text: str, limit: int = SUMMARY_LIMIT) -> str:
    """Cut text to `limit` visible characters, never splitting a URL.

    URLs don't count towards the limit: the UI shortens them to one line each.
    """
    out: list[str] = []
    used = 0
    for i, part in enumerate(URL_RE.split(text)):
        if i % 2 == 1:
            out.append(part)
            continue
        if used + len(part) > limit:
            out.append(part[: limit - used].rstrip() + "…")
            break
        out.append(part)
        used += len(part)
    return "".join(out)


@dataclass
class Article:
    title: str
    url: str
    source: str
    category: str
    summary: str = ""
    published: datetime | None = None
    bookmarked: bool = False
    logo_url: str | None = None

    @property
    def published_str(self) -> str:
        if self.published:
            return self.published.strftime("%b %d, %Y")
        return ""


class FeedUnreachableError(Exception):
    """The feed could not be downloaded or did not contain a feed."""


@dataclass
class FetchResult:
    articles: list[Article]
    # feed url -> why it was unreachable, or None if it was fetched fine
    errors: dict[str, str | None]


async def fetch_feed(feed_info: dict) -> list[Article]:
    """Fetch and parse a single RSS feed asynchronously.

    Raises FeedUnreachableError when the feed can't be fetched or parsed.
    """
    loop = asyncio.get_event_loop()
    try:
        parsed = await loop.run_in_executor(None, feedparser.parse, feed_info["url"])
    except Exception as e:
        logger.warning("Failed to fetch feed %s", feed_info["url"], exc_info=True)
        raise FeedUnreachableError(str(e) or type(e).__name__) from e

    # feedparser reports network and parse failures instead of raising them
    status = parsed.get("status")
    if status is not None and status >= 400:
        raise FeedUnreachableError(f"HTTP {status}")
    if parsed.get("bozo") and not parsed.entries:
        error = parsed.get("bozo_exception")
        raise FeedUnreachableError(str(error) if error else "Not a valid feed")

    articles = []
    for entry in parsed.entries[:20]:  # cap at 20 per feed
        published = None
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                published = datetime(*entry.published_parsed[:6], tzinfo=UTC)
            except Exception:
                logger.warning("Failed to parse published date for %s", feed_info["url"], exc_info=True)

        summary = clean_summary(getattr(entry, "summary", "") or "")

        articles.append(Article(
            title=unescape(getattr(entry, "title", "No title")),
            url=getattr(entry, "link", ""),
            source=feed_info["name"],
            category=feed_info["category"],
            summary=summary,
            published=published,
            logo_url=feed_info.get("logo_url"),
        ))

    return articles


async def fetch_all_feeds(feeds: list[dict]) -> FetchResult:
    """Fetch all feeds concurrently, noting which ones were unreachable."""
    results = await asyncio.gather(*[fetch_feed(f) for f in feeds], return_exceptions=True)
    articles: list[Article] = []
    errors: dict[str, str | None] = {}
    for feed, result in zip(feeds, results, strict=True):
        if isinstance(result, FeedUnreachableError):
            errors[feed["url"]] = str(result)
        elif isinstance(result, BaseException):
            raise result
        else:
            articles += result
            errors[feed["url"]] = None
    # sort by published date, newest first
    articles.sort(key=lambda a: a.published or datetime.min.replace(tzinfo=UTC), reverse=True)
    return FetchResult(articles, errors)
