# grabber.py - Recursive Site Grabber / Web Spider for CIDM
from __future__ import annotations

import os
import re
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Callable, Dict, List, Optional, Set

import requests

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

PRESET_EXTENSIONS = {
    "images": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".ico", ".tiff"},
    "videos": {".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".wmv", ".m4v", ".m3u8", ".mpd"},
    "audio": {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma", ".opus"},
    "documents": {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".rtf", ".odt"},
    "archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso", ".exe", ".msi", ".dmg"},
}

_ALL_BINARY_EXTENSIONS: Set[str] = {
    ext for exts in PRESET_EXTENSIONS.values() for ext in exts
} | {".bin", ".deb", ".rpm", ".apk", ".pkg", ".dll", ".so", ".css", ".js", ".json", ".xml", ".woff", ".woff2", ".ttf"}

MAX_HTML_BYTES = 2 * 1024 * 1024
_CSS_URL_RE = re.compile(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)", re.IGNORECASE)

# Attributes that commonly hold a single media URL (lazy-loaders included).
_SRC_ATTRS = ("src", "data-src", "data-original", "data-lazy-src",
              "data-url", "poster", "data")
_META_MEDIA_KEYS = {
    "og:image", "og:image:url", "og:video", "og:video:url", "og:video:secure_url",
    "og:audio", "twitter:image", "twitter:player:stream",
}


def _normalize(url: str) -> str:
    """Strip fragment/whitespace and lowercase scheme + host so duplicates collapse."""
    url = (url or "").split("#")[0].strip()
    try:
        p = urllib.parse.urlsplit(url)
    except ValueError:
        return url
    if not p.scheme:
        return url
    return urllib.parse.urlunsplit(
        (p.scheme.lower(), p.netloc.lower(), p.path or "/", p.query, ""))


class _LinkExtractor(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.page_links: Set[str] = set()
        self.media_links: Set[str] = set()

    def _add(self, target: Set[str], raw: Optional[str]) -> None:
        if not raw:
            return
        raw = raw.strip()
        if not raw or raw.startswith(("data:", "javascript:", "mailto:", "tel:", "#")):
            return
        try:
            url = urllib.parse.urljoin(self.base_url, raw)
        except ValueError:
            return
        if url.startswith(("http://", "https://")):
            target.add(url)

    def _add_srcset(self, value: Optional[str]) -> None:
        if not value:
            return
        for part in value.split(","):
            tokens = part.strip().split()
            if tokens:
                self._add(self.media_links, tokens[0])

    def handle_starttag(self, tag: str, attrs: list):
        tag = tag.lower()
        a = {k.lower(): v for k, v in attrs if v}

        if tag in ("a", "area") and "href" in a:
            self._add(self.page_links, a["href"])
            if "download" in a:           # explicit download link
                self._add(self.media_links, a["href"])

        if tag in ("img", "script", "embed", "video", "audio", "source",
                   "iframe", "track", "object", "input"):
            for key in _SRC_ATTRS:
                if key in a:
                    self._add(self.media_links, a[key])
        if tag in ("img", "source"):
            self._add_srcset(a.get("srcset") or a.get("data-srcset"))
        if tag == "video" and "poster" in a:
            self._add(self.media_links, a["poster"])
        if tag == "link" and "href" in a:
            self._add(self.media_links, a["href"])
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key in _META_MEDIA_KEYS:
                self._add(self.media_links, a.get("content"))

        # Background images etc. in inline style attributes
        style = a.get("style")
        if style:
            for m in _CSS_URL_RE.finditer(style):
                self._add(self.media_links, m.group(1))


@dataclass
class GrabbedItem:
    url: str
    filename: str
    ext: str
    category: str
    found_on_page: str
    size: int = 0
    checked: bool = True


class SiteGrabber:
    """Recursively crawls web pages and collects matching downloadable media/files.

    Pages are fetched concurrently (``workers`` threads), level by level, so the
    crawl stays breadth-first while being several times faster than a serial loop.
    """

    def __init__(
        self,
        start_url: str,
        max_depth: int = 2,
        stay_on_domain: bool = True,
        categories: Optional[Set[str]] = None,
        custom_extensions: Optional[Set[str]] = None,
        max_pages: int = 100,
        timeout: int = 10,
        user_agent: Optional[str] = None,
        workers: int = 6,
    ):
        self.start_url = start_url.strip()
        if "://" not in self.start_url:
            self.start_url = "https://" + self.start_url
        self.max_depth = max(1, min(5, max_depth))
        self.stay_on_domain = stay_on_domain
        self.max_pages = max(1, max_pages)
        self.timeout = timeout
        self.user_agent = user_agent or DEFAULT_USER_AGENT
        self.workers = max(1, min(16, workers))

        self.target_extensions: Set[str] = set()
        cat_set = categories or {"images", "videos",
                                 "audio", "documents", "archives"}
        for c in cat_set:
            if c in PRESET_EXTENSIONS:
                self.target_extensions.update(PRESET_EXTENSIONS[c])
        if custom_extensions:
            for ext in custom_extensions:
                clean_ext = ext.strip().lower()
                if clean_ext:
                    if not clean_ext.startswith("."):
                        clean_ext = "." + clean_ext
                    self.target_extensions.add(clean_ext)

        parsed = urllib.parse.urlparse(self.start_url)
        host = (parsed.hostname or "").lower()
        # Treat example.com and www.example.com as the same site.
        self.base_domain = host[4:] if host.startswith("www.") else host

        self._cancel_flag = threading.Event()
        self._items: Dict[str, GrabbedItem] = {}
        self._crawled_urls: Set[str] = set()
        self._lock = threading.Lock()
        self._local = threading.local()
        self._sessions: List[requests.Session] = []

        self.on_item_found: Optional[Callable[[GrabbedItem], None]] = None
        self.on_progress: Optional[Callable[[int, int, str], None]] = None
        self.on_finished: Optional[Callable[[List[GrabbedItem]], None]] = None

    # ----- control ---------------------------------------------------------- #
    def cancel(self):
        self._cancel_flag.set()

    def is_cancelled(self) -> bool:
        return self._cancel_flag.is_set()

    # ----- url helpers ------------------------------------------------------ #
    def _get_extension(self, url: str) -> str:
        path = urllib.parse.urlparse(url).path
        return os.path.splitext(path)[1].lower()

    def _get_filename(self, url: str) -> str:
        name = urllib.parse.unquote(
            os.path.basename(urllib.parse.urlparse(url).path))
        return name or "file"

    def _get_category(self, ext: str) -> str:
        for cat, exts in PRESET_EXTENSIONS.items():
            if ext in exts:
                return cat.capitalize()
        return "Custom"

    def _is_same_domain(self, url: str) -> bool:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        return host == self.base_domain or host.endswith("." + self.base_domain)

    def _session(self) -> requests.Session:
        """One Session per worker thread (requests.Session isn't fully thread-safe)."""
        s = getattr(self._local, "session", None)
        if s is None:
            s = requests.Session()
            s.headers.update({"User-Agent": self.user_agent})
            self._local.session = s
            with self._lock:
                self._sessions.append(s)
        return s

    # ----- crawl ------------------------------------------------------------ #
    def crawl(self) -> List[GrabbedItem]:
        """Breadth-first crawl; each depth level is fetched in parallel."""
        level: List[str] = [_normalize(self.start_url)]
        depth = 1
        pages_visited = 0

        try:
            with ThreadPoolExecutor(max_workers=self.workers,
                                    thread_name_prefix="cidm-grab") as pool:
                while level and not self._cancel_flag.is_set():
                    # Enforce the page budget *before* fetching.
                    budget = self.max_pages - pages_visited
                    if budget <= 0:
                        break
                    batch: List[str] = []
                    for u in level:
                        if u in self._crawled_urls:
                            continue
                        self._crawled_urls.add(u)
                        batch.append(u)
                        if len(batch) >= budget:
                            break

                    next_level: List[str] = []
                    queued: Set[str] = set()
                    futures = [(u, pool.submit(self._fetch_page, u, depth))
                               for u in batch]
                    for idx, (url, fut) in enumerate(futures):
                        if self._cancel_flag.is_set():
                            break
                        pages_visited += 1
                        if self.on_progress:
                            self.on_progress(pages_visited,
                                             len(futures) - idx - 1 + len(next_level), url)
                        try:
                            links = fut.result()
                        except Exception:
                            continue
                        if depth >= self.max_depth:
                            continue
                        for link in links:
                            if link in self._crawled_urls or link in queued:
                                continue
                            if self.stay_on_domain and not self._is_same_domain(link):
                                continue
                            queued.add(link)
                            next_level.append(link)

                    if self._cancel_flag.is_set():
                        for _, f in futures:
                            f.cancel()
                    level = next_level
                    depth += 1
        finally:
            for s in getattr(self, "_sessions", []):
                try:
                    s.close()
                except Exception:
                    pass

        results = list(self._items.values())
        if self.on_finished:
            self.on_finished(results)
        return results

    def _fetch_page(self, url: str, depth: int) -> List[str]:
        """Fetch one page, record media found on it, return page links to crawl next."""
        if self._cancel_flag.is_set():
            return []
        try:
            with self._session().get(url, timeout=self.timeout, stream=True) as resp:
                if resp.status_code >= 400:
                    return []
                ctype = resp.headers.get("Content-Type", "").lower()
                if "text/html" not in ctype and "application/xhtml" not in ctype:
                    if self._get_extension(url) in self.target_extensions:
                        self._record_item(url, url)
                    return []

                data = bytearray()
                for chunk in resp.iter_content(chunk_size=32768):
                    if self._cancel_flag.is_set():
                        return []
                    data.extend(chunk)
                    if len(data) > MAX_HTML_BYTES:
                        break
                html_text = self._decode(bytes(data), resp.encoding)
                base = _normalize(resp.url or url)
        except requests.RequestException:
            return []

        parser = _LinkExtractor(base)
        try:
            parser.feed(html_text)
            parser.close()
        except Exception:
            pass

        follow: List[str] = []
        for link in parser.page_links | parser.media_links:
            clean = _normalize(link)
            ext = self._get_extension(clean)
            if ext in self.target_extensions:
                self._record_item(clean, base)
            elif link in parser.page_links and ext not in _ALL_BINARY_EXTENSIONS:
                follow.append(clean)
        return follow

    @staticmethod
    def _decode(data: bytes, header_encoding: Optional[str]) -> str:
        # Prefer a <meta charset> hint, then the header, then UTF-8.
        head = data[:4096].decode("ascii", errors="ignore")
        m = re.search(r"charset=['\"]?([\w-]+)", head, re.IGNORECASE)
        for enc in (m.group(1) if m else None, header_encoding, "utf-8"):
            if not enc:
                continue
            try:
                return data.decode(enc, errors="replace")
            except LookupError:
                continue
        return data.decode("utf-8", errors="replace")

    def _record_item(self, url: str, found_on_page: str):
        with self._lock:
            if url in self._items:
                return
            ext = self._get_extension(url)
            item = GrabbedItem(
                url=url,
                filename=self._get_filename(url),
                ext=ext,
                category=self._get_category(ext),
                found_on_page=found_on_page,
            )
            self._items[url] = item
        # Fire the callback outside the lock so a slow UI handler can't stall workers.
        if self.on_item_found:
            self.on_item_found(item)
