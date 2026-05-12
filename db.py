import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

DB_PATH = os.environ.get("DB_PATH", "newsreader.db")

DEFAULT_FEEDS = [
    {"name": "BBC News", "url": "http://feeds.bbci.co.uk/news/rss.xml", "category": "World"},
    {"name": "Reuters", "url": "https://feeds.reuters.com/reuters/topNews", "category": "World"},
    {"name": "Hacker News", "url": "https://hnrss.org/frontpage", "category": "Tech"},
    {"name": "The Verge", "url": "https://www.theverge.com/rss/index.xml", "category": "Tech"},
    {"name": "Ars Technica", "url": "http://feeds.arstechnica.com/arstechnica/index", "category": "Tech"},
    {"name": "NPR News", "url": "https://feeds.npr.org/1001/rss.xml", "category": "US"},
    {"name": "NASA", "url": "https://www.nasa.gov/rss/dyn/breaking_news.rss", "category": "Science"},
]


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Create tables and seed default feeds if the feeds table is empty."""
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS feeds (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                name     TEXT NOT NULL,
                url      TEXT NOT NULL UNIQUE,
                category TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS bookmarks (
                url        TEXT PRIMARY KEY,
                title      TEXT,
                source     TEXT,
                category   TEXT,
                summary    TEXT,
                published  TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
        """)

        if conn.execute("SELECT COUNT(*) FROM feeds").fetchone()[0] == 0:
            conn.executemany(
                "INSERT OR IGNORE INTO feeds (name, url, category) VALUES (:name, :url, :category)",
                DEFAULT_FEEDS,
            )


# ── Feeds ──────────────────────────────────────────────────────────────────────

def get_feeds() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT name, url, category FROM feeds ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def add_feed(name: str, url: str, category: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO feeds (name, url, category) VALUES (?, ?, ?)",
            (name, url, category),
        )


def remove_feed(url: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM feeds WHERE url = ?", (url,))


def update_feed(original_url: str, name: str, url: str, category: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE feeds SET name = ?, url = ?, category = ? WHERE url = ?",
            (name, url, category, original_url),
        )


# ── Bookmarks ──────────────────────────────────────────────────────────────────

def get_bookmarked_urls() -> set[str]:
    with get_conn() as conn:
        rows = conn.execute("SELECT url FROM bookmarks").fetchall()
    return {r["url"] for r in rows}


def add_bookmark(article) -> None:
    published_str = article.published.isoformat() if article.published else None
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO bookmarks (url, title, source, category, summary, published)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (article.url, article.title, article.source, article.category, article.summary, published_str),
        )


def remove_bookmark(url: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM bookmarks WHERE url = ?", (url,))
