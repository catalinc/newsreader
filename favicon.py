"""Discover and download the favicon of the site behind an RSS feed."""

import logging
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

import feedparser

logger = logging.getLogger(__name__)

TIMEOUT = 10  # seconds
MAX_BYTES = 512 * 1024
USER_AGENT = "Mozilla/5.0 (compatible; newsreader/0.1)"


class _IconLinkParser(HTMLParser):
    """Collect <link rel="icon"> style hrefs, ranked best first."""

    def __init__(self) -> None:
        super().__init__()
        self._found: list[tuple[int, int, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "link":
            return
        a = dict(attrs)
        href = a.get("href")
        rels = (a.get("rel") or "").lower().split()
        if not href:
            return
        if "icon" in rels:
            priority = 0
        elif "apple-touch-icon" in rels:
            priority = 1
        else:
            return
        self._found.append((priority, -_icon_size(a.get("sizes")), href))

    @property
    def hrefs(self) -> list[str]:
        return [href for *_, href in sorted(self._found)]


def _icon_size(sizes: str | None) -> int:
    """Largest dimension declared in a sizes attribute ("any" counts as huge)."""
    if not sizes:
        return 0
    if "any" in sizes.lower():
        return 10_000
    return max((int(n) for n in re.findall(r"(\d+)x\d+", sizes)), default=0)


def sniff_image_type(data: bytes) -> str | None:
    """Return the image MIME type for known magic bytes, or None."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\x00\x00\x01\x00"):
        return "image/x-icon"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if b"<svg" in data[:1024].lower():
        return "image/svg+xml"
    return None


def _get(url: str) -> tuple[bytes, str]:
    """Fetch url, returning (body, final url after redirects)."""
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read(MAX_BYTES + 1), resp.geturl()


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}/"


def _site_url(feed_url: str) -> str:
    """The homepage the feed belongs to, falling back to the feed's own origin."""
    link = feedparser.parse(feed_url).feed.get("link")
    if isinstance(link, str) and link.startswith(("http://", "https://")):
        return link
    return _origin(feed_url)


def _candidates(feed_url: str) -> list[str]:
    site = _site_url(feed_url)
    urls: list[str] = []
    try:
        html, final_url = _get(site)
        parser = _IconLinkParser()
        parser.feed(html.decode("utf-8", errors="replace"))
        urls += [urljoin(final_url, href) for href in parser.hrefs]
        site = final_url
    except Exception:
        logger.info("Could not load site page %s", site, exc_info=True)
    urls += [urljoin(site, "/favicon.ico"), urljoin(_origin(feed_url), "/favicon.ico")]
    return list(dict.fromkeys(u for u in urls if u.startswith(("http://", "https://"))))


def fetch_favicon(feed_url: str) -> tuple[bytes, str] | None:
    """Return (image bytes, MIME type) for the feed's site favicon, or None.

    Blocking; never raises.
    """
    try:
        candidates = _candidates(feed_url)
    except Exception:
        logger.warning("Favicon discovery failed for %s", feed_url, exc_info=True)
        return None

    for url in candidates:
        try:
            data, _ = _get(url)
        except Exception:
            logger.debug("Could not fetch favicon candidate %s", url, exc_info=True)
            continue
        if len(data) > MAX_BYTES:
            continue
        mime = sniff_image_type(data)
        if mime:
            return data, mime
    logger.info("No favicon found for %s", feed_url)
    return None
