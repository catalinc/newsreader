import sqlite3
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

import db
from db import DEFAULT_FEEDS
from favicon import fetch_favicon, sniff_image_type
from rss import Article, clean_summary, fetch_all_feeds, fetch_feed, truncate_summary

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

    dates = [a.published for a in articles if a.published is not None]
    assert dates[0] > dates[1]


# ── Summary cleanup ────────────────────────────────────────────────────────────

HN_SUMMARY = (
    '<p>Article URL: <a href="https://github.com/allenv0/SCM">https://github.com/allenv0/SCM</a></p>\n'
    '<p>Comments URL: <a href="https://news.ycombinator.com/item?id=49952111">'
    "https://news.ycombinator.com/item?id=49952111</a></p>\n"
    "<p>Points: 20</p>\n<p># Comments: 8</p>"
)


def test_clean_summary_keeps_hacker_news_items_on_separate_lines():
    assert clean_summary(HN_SUMMARY).splitlines() == [
        "Article URL: https://github.com/allenv0/SCM",
        "Comments URL: https://news.ycombinator.com/item?id=49952111",
        "Points: 20",
        "# Comments: 8",
    ]


def test_clean_summary_handles_br_and_collapses_whitespace():
    assert clean_summary("one<br>two <b>  bold </b><br/>\n\n<p></p>three &amp; four") == "one\ntwo bold\nthree & four"


def test_truncate_summary_keeps_long_urls_whole():
    long_url = "https://example.com/" + "a" * 400
    text = f"Article URL: {long_url}\nPoints: 20\n# Comments: 8"
    assert truncate_summary(text) == text


def test_truncate_summary_cuts_text_but_never_a_url():
    url = "https://example.com/" + "a" * 50
    result = truncate_summary("x" * 295 + " " + url + " and then some more text")
    assert result == "x" * 295 + " " + url + " and…"

    result = truncate_summary("x" * 310 + " " + url)
    assert result == "x" * 300 + "…"


# ── Default feeds ──────────────────────────────────────────────────────────────

def test_default_feeds_have_required_keys():
    for feed in DEFAULT_FEEDS:
        assert "name" in feed
        assert "url" in feed
        assert "category" in feed


def test_default_feeds_urls_are_http():
    for feed in DEFAULT_FEEDS:
        assert feed["url"].startswith("http")


# ── Favicons ───────────────────────────────────────────────────────────────────

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
ICO = b"\x00\x00\x01\x00" + b"\x00" * 16


def test_sniff_image_type():
    assert sniff_image_type(PNG) == "image/png"
    assert sniff_image_type(ICO) == "image/x-icon"
    assert sniff_image_type(b'<?xml version="1.0"?><svg xmlns="...">') == "image/svg+xml"
    assert sniff_image_type(b"<!doctype html><html>") is None


def _fake_site(pages: dict[str, bytes]):
    def fake_get(url):
        if url not in pages:
            raise OSError("404")
        return pages[url], url
    return fake_get


def test_fetch_favicon_prefers_largest_declared_icon():
    html = b"""<html><head>
        <link rel="icon" href="/small.png" sizes="16x16">
        <link rel="shortcut icon" href="/big.png" sizes="32x32 64x64">
        <link rel="apple-touch-icon" href="/touch.png" sizes="180x180">
    </head></html>"""
    pages = {"https://site.test/": html, "https://site.test/big.png": PNG, "https://site.test/small.png": ICO}
    with (
        patch("favicon._site_url", return_value="https://site.test/"),
        patch("favicon._get", side_effect=_fake_site(pages)),
    ):
        assert fetch_favicon("https://feeds.site.test/rss") == (PNG, "image/png")


def test_fetch_favicon_falls_back_to_favicon_ico():
    pages = {"https://site.test/": b"<html></html>", "https://site.test/favicon.ico": ICO}
    with (
        patch("favicon._site_url", return_value="https://site.test/"),
        patch("favicon._get", side_effect=_fake_site(pages)),
    ):
        assert fetch_favicon("https://feeds.site.test/rss") == (ICO, "image/x-icon")


def test_fetch_favicon_returns_none_when_nothing_is_an_image():
    pages = {"https://site.test/": b"<html></html>", "https://site.test/favicon.ico": b"<html>not found</html>"}
    with (
        patch("favicon._site_url", return_value="https://site.test/"),
        patch("favicon._get", side_effect=_fake_site(pages)),
    ):
        assert fetch_favicon("https://feeds.site.test/rss") is None


# ── Feed logos in the database ─────────────────────────────────────────────────

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    db.init_db()


def test_seeded_feeds_need_logo_lookup(temp_db):
    assert db.get_feed_urls_without_logo_check() == [f["url"] for f in DEFAULT_FEEDS]
    assert all(f["logo_url"] is None for f in db.get_feeds())


def test_set_feed_logo_exposes_logo_url(temp_db):
    url = DEFAULT_FEEDS[0]["url"]
    db.set_feed_logo(url, (PNG, "image/png"))
    feed = next(f for f in db.get_feeds() if f["url"] == url)
    assert feed["logo_url"].startswith(f"/feed-logo/{feed['id']}?v=")
    assert db.get_feed_logo(feed["id"]) == (PNG, "image/png")
    assert url not in db.get_feed_urls_without_logo_check()


def test_missing_favicon_is_recorded_and_not_retried(temp_db):
    url = DEFAULT_FEEDS[0]["url"]
    db.set_feed_logo(url, None)
    assert url not in db.get_feed_urls_without_logo_check()
    assert next(f for f in db.get_feeds() if f["url"] == url)["logo_url"] is None


def test_changing_feed_url_clears_logo(temp_db):
    old = DEFAULT_FEEDS[0]["url"]
    db.set_feed_logo(old, (PNG, "image/png"))
    db.update_feed(old, "Renamed", "https://new.test/rss", "World")
    assert "https://new.test/rss" in db.get_feed_urls_without_logo_check()


def test_init_db_migrates_old_feeds_table(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    monkeypatch.setattr(db, "DB_PATH", str(path))
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE feeds (id INTEGER PRIMARY KEY, name TEXT, url TEXT UNIQUE, category TEXT)")
    conn.execute("INSERT INTO feeds (name, url, category) VALUES ('Old', 'https://old.test/rss', 'X')")
    conn.commit()
    conn.close()

    db.init_db()

    assert db.get_feed_urls_without_logo_check() == ["https://old.test/rss"]
