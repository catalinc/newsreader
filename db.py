import os
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime

DB_PATH = os.environ.get("DB_PATH", "newsreader.db")

DEFAULT_FEEDS = [
    {"name": "BBC News", "url": "http://feeds.bbci.co.uk/news/rss.xml", "category": "World"},
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
                category TEXT NOT NULL,
                logo     BLOB,
                logo_type TEXT,
                logo_fetched_at TEXT,
                last_checked_at TEXT,
                last_ok_at TEXT,
                last_error TEXT
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

        # migrate databases created before feed logos and reachability tracking existed
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(feeds)")}
        for column, sql_type in (
            ("logo", "BLOB"),
            ("logo_type", "TEXT"),
            ("logo_fetched_at", "TEXT"),
            ("last_checked_at", "TEXT"),
            ("last_ok_at", "TEXT"),
            ("last_error", "TEXT"),
        ):
            if column not in columns:
                conn.execute(f"ALTER TABLE feeds ADD COLUMN {column} {sql_type}")

        if conn.execute("SELECT COUNT(*) FROM feeds").fetchone()[0] == 0:
            conn.executemany(
                "INSERT OR IGNORE INTO feeds (name, url, category) VALUES (:name, :url, :category)",
                DEFAULT_FEEDS,
            )


# ── Feeds ──────────────────────────────────────────────────────────────────────

def get_feeds() -> list[dict]:
    """All feeds; logo_url is None when the feed has no logo (show the default).

    last_error is set when the latest fetch failed; last_ok_at (a UTC datetime,
    or None if never) is when the feed was last fetched successfully.
    """
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, name, url, category, last_ok_at, last_error,
                      CASE WHEN logo IS NOT NULL THEN strftime('%s', logo_fetched_at) END AS logo_version
               FROM feeds ORDER BY id"""
        ).fetchall()
    feeds = []
    for r in rows:
        feed = {k: r[k] for k in ("id", "name", "url", "category", "last_error")}
        feed["last_ok_at"] = datetime.fromisoformat(r["last_ok_at"]) if r["last_ok_at"] else None
        # the version query param busts browser caches when the logo is refetched
        feed["logo_url"] = f"/feed-logo/{r['id']}?v={r['logo_version']}" if r["logo_version"] else None
        feeds.append(feed)
    return feeds


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
        if url != original_url:
            # the logo and reachability belonged to the old URL; start over
            conn.execute(
                """UPDATE feeds SET logo = NULL, logo_type = NULL, logo_fetched_at = NULL,
                                    last_checked_at = NULL, last_ok_at = NULL, last_error = NULL
                   WHERE url = ?""",
                (url,),
            )


def record_feed_statuses(errors: dict[str, str | None]) -> None:
    """Store fetch outcomes: feed url -> error message, or None if it was reachable."""
    now = datetime.now(UTC).isoformat()
    with get_conn() as conn:
        for url, error in errors.items():
            if error is None:
                conn.execute(
                    "UPDATE feeds SET last_checked_at = ?, last_ok_at = ?, last_error = NULL WHERE url = ?",
                    (now, now, url),
                )
            else:
                conn.execute(
                    "UPDATE feeds SET last_checked_at = ?, last_error = ? WHERE url = ?",
                    (now, error, url),
                )


def get_feed_logo(feed_id: int) -> tuple[bytes, str] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT logo, logo_type FROM feeds WHERE id = ? AND logo IS NOT NULL", (feed_id,)
        ).fetchone()
    return (row["logo"], row["logo_type"]) if row else None


def set_feed_logo(url: str, logo: tuple[bytes, str] | None) -> None:
    """Store a fetched logo; None records that the site has no usable favicon."""
    data, mime = logo if logo else (None, None)
    with get_conn() as conn:
        conn.execute(
            "UPDATE feeds SET logo = ?, logo_type = ?, logo_fetched_at = CURRENT_TIMESTAMP WHERE url = ?",
            (data, mime, url),
        )


def get_feed_urls_without_logo_check() -> list[str]:
    """Feeds whose favicon has never been looked up (e.g. freshly seeded defaults)."""
    with get_conn() as conn:
        rows = conn.execute("SELECT url FROM feeds WHERE logo_fetched_at IS NULL").fetchall()
    return [r["url"] for r in rows]


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
