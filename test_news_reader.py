from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from db import DEFAULT_FEEDS
from rss import Article, fetch_all_feeds, fetch_feed

# ── Article ────────────────────────────────────────────────────────────────────

def make_article(**kwargs) -> Article:
    defaults = {"title": "Test", "url": "https://example.com", "source": "TestFeed", "category": "Tech"}
    return Article(**{**defaults, **kwargs})


def test_article_published_str_with_date():
    a = make_article(published=datetime(2024, 3, 15, tzinfo=UTC))
    assert a.published_str == "Mar 15, 2024"


def test_article_published_str_without_date():
    a = make_article()
    assert a.published_str == ""


def test_article_defaults():
    a = make_article()
    assert a.bookmarked is False
    assert a.summary == ""


# ── fetch_feed ─────────────────────────────────────────────────────────────────

MOCK_FEED = {
    "entries": [
        {
            "title": "Article One",
            "link": "https://example.com/1",
            "summary": "Short summary",
            "published_parsed": (2024, 3, 15, 10, 0, 0, 0, 0, 0),
        },
        {
            "title": "Article Two",
            "link": "https://example.com/2",
            "summary": "<p>HTML <b>summary</b> here</p>",
            "published_parsed": None,
        },
    ]
}


def _make_mock_parsed(entries):
    mock = MagicMock()
    mock.entries = []
    for e in entries:
        entry = MagicMock(spec=list(e.keys()))
        for k, v in e.items():
            setattr(entry, k, v)
        mock.entries.append(entry)
    return mock


@pytest.mark.asyncio
async def test_fetch_feed_parses_articles():
    mock_parsed = _make_mock_parsed(MOCK_FEED["entries"])
    with patch("rss.feedparser.parse", return_value=mock_parsed):
        articles = await fetch_feed({"name": "Test", "url": "http://fake", "category": "Tech"})
    assert len(articles) == 2
    assert articles[0].title == "Article One"
    assert articles[0].published == datetime(2024, 3, 15, 10, 0, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_fetch_feed_strips_html_from_summary():
    mock_parsed = _make_mock_parsed(MOCK_FEED["entries"])
    with patch("rss.feedparser.parse", return_value=mock_parsed):
        articles = await fetch_feed({"name": "Test", "url": "http://fake", "category": "Tech"})
    assert "<" not in articles[1].summary
    assert "HTML summary here" in articles[1].summary


@pytest.mark.asyncio
async def test_fetch_feed_truncates_long_summary():
    long_entry = {
        "title": "Long",
        "link": "https://x.com",
        "summary": "x" * 400,
        "published_parsed": None,
    }
    mock_parsed = _make_mock_parsed([long_entry])
    with patch("rss.feedparser.parse", return_value=mock_parsed):
        articles = await fetch_feed({"name": "T", "url": "http://fake", "category": "Tech"})
    assert len(articles[0].summary) <= 303  # 300 + "…"
    assert articles[0].summary.endswith("…")


@pytest.mark.asyncio
async def test_fetch_feed_returns_empty_on_error():
    with patch("rss.feedparser.parse", side_effect=Exception("network error")):
        articles = await fetch_feed({"name": "T", "url": "http://fake", "category": "Tech"})
    assert articles == []


@pytest.mark.asyncio
async def test_fetch_all_feeds_sorted_newest_first():
    a1 = make_article(url="u1", published=datetime(2024, 1, 1, tzinfo=UTC))
    a2 = make_article(url="u2", published=datetime(2024, 3, 1, tzinfo=UTC))
    a3 = make_article(url="u3", published=None)

    async def fake_fetch(feed):
        return [a1, a2, a3]

    with patch("rss.fetch_feed", side_effect=fake_fetch):
        articles = await fetch_all_feeds([{"name": "T", "url": "", "category": "X"}])

    dated = [a for a in articles if a.published]
    assert dated[0].published > dated[1].published


# ── Default feeds ──────────────────────────────────────────────────────────────

def test_default_feeds_have_required_keys():
    for feed in DEFAULT_FEEDS:
        assert "name" in feed
        assert "url" in feed
        assert "category" in feed


def test_default_feeds_urls_are_http():
    for feed in DEFAULT_FEEDS:
        assert feed["url"].startswith("http")
