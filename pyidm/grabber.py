# grabber.py - Recursive Site Grabber / Web Spider for CIDM
from __future__ import annotations

import os
import threading
import urllib.parse
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
    "videos": {".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".wmv", ".m4v", ".ts", ".m3u8", ".mpd"},
    "audio": {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma", ".opus"},
    "documents": {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".rtf", ".odt"},
    "archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso", ".exe", ".msi", ".dmg"},
}

_ALL_BINARY_EXTENSIONS: Set[str] = {
    ext for exts in PRESET_EXTENSIONS.values() for ext in exts
} | {".bin", ".deb", ".rpm", ".apk", ".pkg", ".dll", ".so"}


class _LinkExtractor(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.page_links: Set[str] = set()
        self.media_links: Set[str] = set()

    def handle_starttag(self, tag: str, attrs: list):
        tag_lower = tag.lower()
        attr_dict = {k.lower(): v for k, v in attrs if v}

        # Links to other pages or files
        if tag_lower == "a" and "href" in attr_dict:
            url = urllib.parse.urljoin(
                self.base_url, attr_dict["href"].strip())
            if url.startswith(("http://", "https://")):
                self.page_links.add(url)

        # Embedded media
        media_attr = None
        if tag_lower in ("img", "script", "embed") and "src" in attr_dict:
            media_attr = attr_dict["src"]
        elif tag_lower in ("video", "audio", "source") and "src" in attr_dict:
            media_attr = attr_dict["src"]
        elif tag_lower == "link" and "href" in attr_dict:
            media_attr = attr_dict["href"]

        if media_attr:
            url = urllib.parse.urljoin(self.base_url, media_attr.strip())
            if url.startswith(("http://", "https://")):
                self.media_links.add(url)


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
    """Recursively crawls web pages and collects matching downloadable media/files."""

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
    ):
        self.start_url = start_url.strip()
        self.max_depth = max(1, min(5, max_depth))
        self.stay_on_domain = stay_on_domain
        self.max_pages = max_pages
        self.timeout = timeout
        self.user_agent = user_agent or DEFAULT_USER_AGENT

        # Build extension set
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
        self.base_domain = parsed.netloc.lower()

        self._cancel_flag = threading.Event()
        self._items: Dict[str, GrabbedItem] = {}
        self._crawled_urls: Set[str] = set()
        self._lock = threading.Lock()

        # Callbacks
        self.on_item_found: Optional[Callable[[GrabbedItem], None]] = None
        self.on_progress: Optional[Callable[[int, int, str], None]] = None
        self.on_finished: Optional[Callable[[List[GrabbedItem]], None]] = None

    def cancel(self):
        self._cancel_flag.set()

    def is_cancelled(self) -> bool:
        return self._cancel_flag.is_set()

    def _get_extension(self, url: str) -> str:
        path = urllib.parse.urlparse(url).path
        _, ext = os.path.splitext(path)
        return ext.lower()

    def _get_filename(self, url: str) -> str:
        path = urllib.parse.urlparse(url).path
        name = os.path.basename(path)
        name = urllib.parse.unquote(name)
        return name or "file"

    def _get_category(self, ext: str) -> str:
        for cat, exts in PRESET_EXTENSIONS.items():
            if ext in exts:
                return cat.capitalize()
        return "Custom"

    def _is_same_domain(self, url: str) -> bool:
        netloc = urllib.parse.urlparse(url).netloc.lower()
        return netloc == self.base_domain or netloc.endswith("." + self.base_domain)

    def crawl(self) -> List[GrabbedItem]:
        """Breadth-first search crawler with depth tracking."""
        session = requests.Session()
        session.headers.update({"User-Agent": self.user_agent})

        queue: List[tuple[str, int]] = [(self.start_url, 1)]
        pages_visited = 0

        try:
            while queue and not self._cancel_flag.is_set():
                current_url, depth = queue.pop(0)

                clean_current = current_url.split("#")[0].strip()
                if clean_current in self._crawled_urls:
                    continue

                self._crawled_urls.add(clean_current)
                pages_visited += 1

                if self.on_progress:
                    self.on_progress(pages_visited, len(queue), clean_current)

                try:
                    with session.get(clean_current, timeout=self.timeout, stream=True) as resp:
                        content_type = resp.headers.get(
                            "Content-Type", "").lower()

                        # If this is not HTML, check if it's a media/document file
                        if "text/html" not in content_type and "application/xhtml" not in content_type:
                            ext = self._get_extension(clean_current)
                            if ext in self.target_extensions:
                                self._record_item(clean_current, clean_current)
                            continue

                        # Read HTML (up to 2MB to prevent memory exhaustion)
                        chunks = []
                        total_bytes = 0
                        for chunk in resp.iter_content(chunk_size=32768, decode_unicode=True):
                            if self._cancel_flag.is_set():
                                break
                            if isinstance(chunk, str):
                                chunks.append(chunk)
                                total_bytes += len(chunk.encode("utf-8"))
                                if total_bytes > 2 * 1024 * 1024:
                                    break
                        html_text = "".join(chunks)
                except Exception:
                    continue

                if self._cancel_flag.is_set():
                    break

                # Parse HTML for links
                parser = _LinkExtractor(clean_current)
                try:
                    parser.feed(html_text)
                except Exception:
                    pass

                # Inspect extracted links
                all_discovered = parser.page_links | parser.media_links
                for link in all_discovered:
                    link_clean = link.split("#")[0].strip()
                    ext = self._get_extension(link_clean)

                    if ext in self.target_extensions:
                        self._record_item(link_clean, clean_current)
                    elif depth < self.max_depth and pages_visited < self.max_pages:
                        # Enqueue HTML page for deeper crawling
                        if not self.stay_on_domain or self._is_same_domain(link_clean):
                            if link_clean not in self._crawled_urls and not any(q[0] == link_clean for q in queue):
                                if ext not in _ALL_BINARY_EXTENSIONS:
                                    queue.append((link_clean, depth + 1))
        finally:
            session.close()

        results = list(self._items.values())
        if self.on_finished:
            self.on_finished(results)
        return results

    def _record_item(self, url: str, found_on_page: str):
        with self._lock:
            if url in self._items:
                return
            ext = self._get_extension(url)
            filename = self._get_filename(url)
            cat = self._get_category(ext)
            item = GrabbedItem(
                url=url,
                filename=filename,
                ext=ext,
                category=cat,
                found_on_page=found_on_page,
            )
            self._items[url] = item
            if self.on_item_found:
                self.on_item_found(item)
