# RSS Reader

A web-based RSS reader built with [NiceGUI](https://nicegui.io) and Python.

## Features

- Fetches multiple RSS feeds concurrently
- Filters articles by category or keyword search
- Bookmarks persist across restarts (SQLite)
- Feed list is stored in SQLite and can be managed directly in the database
- Background job refreshes feeds every 15 minutes automatically
- Shows each feed's site favicon as its logo, with a newspaper icon when none is available

## Running locally

Requires Python 3.14+ and [uv](https://docs.astral.sh/uv/).

```bash
uv run main.py
```

Open [http://localhost:8080](http://localhost:8080).

## Running with Docker

```bash
# Build
docker build -t newsreader .

# Run (database persisted in a named volume)
docker run -p 8080:8080 -v newsreader-data:/data newsreader
```

The SQLite database is stored at `/data/newsreader.db` inside the container. Mount a volume there to keep feeds and bookmarks across container restarts.

## Managing feeds

Feeds are seeded from defaults on first run and stored in the `feeds` table of the SQLite database. You can add, edit, or remove feeds directly:

```bash
sqlite3 newsreader.db

INSERT INTO feeds (name, url, category) VALUES ('My Blog', 'https://example.com/feed.xml', 'Tech');
DELETE FROM feeds WHERE name = 'Reuters';
```

Feed logos are fetched when a feed is added from the UI or its URL is changed. On startup, the app also looks up a logo for any feed that has never been checked (including the seeded defaults and feeds inserted with `sqlite3`). To refetch a logo, clear its check timestamp and restart:

```sql
UPDATE feeds SET logo_fetched_at = NULL WHERE name = 'BBC News';
```

## Project structure

| File | Purpose |
|------|---------|
| `main.py` | NiceGUI app, UI layout, page logic |
| `rss.py` | Feed fetching and article parsing |
| `favicon.py` | Feed logo (site favicon) discovery and download |
| `db.py` | SQLite schema, feeds and bookmarks CRUD |
