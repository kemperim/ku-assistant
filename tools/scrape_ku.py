#!/usr/bin/env python3
"""
Collect public text pages from ku.edu.kz and apply.ku.edu.kz into one RAG-ready TXT.

The script intentionally uses only the Python standard library so it can run
before optional project dependencies are installed.
"""

from __future__ import annotations

import argparse
import html
import re
import time
from collections import deque
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.request import Request, urlopen


ALLOWED_HOSTS = {"ku.edu.kz", "www.ku.edu.kz", "apply.ku.edu.kz"}
SKIP_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico",
    ".css", ".js", ".zip", ".rar", ".7z", ".mp4", ".mp3", ".avi",
}

START_URLS = [
    "https://ku.edu.kz/site/index?lang=ru",
    "https://ku.edu.kz/page?lang=ru",
    "https://ku.edu.kz/page/view?id=523&lang=ru",
    "https://ku.edu.kz/page/view?id=1588&lang=ru",
    "https://ku.edu.kz/DocDb/doc/index?lang=ru",
    "https://apply.ku.edu.kz/ru",
    "https://apply.ku.edu.kz/ru/1/main/info?step=1&type=school",
    "https://apply.ku.edu.kz/ru/1/main/info?step=1&type=college",
]


class TextExtractor(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.links: list[str] = []
        self.text_parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
            return

        attrs_dict = dict(attrs)
        href = attrs_dict.get("href")
        if tag == "a" and href:
            self.links.append(urljoin(self.base_url, href))

        if tag in {"p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str):
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag in {"p", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.text_parts.append("\n")

    def handle_data(self, data: str):
        if self._skip_depth == 0:
            cleaned = data.strip()
            if cleaned:
                self.text_parts.append(cleaned)
                self.text_parts.append(" ")

    def text(self) -> str:
        text = html.unescape("".join(self.text_parts))
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        lines = [line.strip() for line in text.splitlines()]
        return "\n".join(line for line in lines if line)


def normalize_url(url: str) -> str | None:
    url = urldefrag(url)[0]
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return None
    host = parsed.netloc.lower()
    if host not in ALLOWED_HOSTS:
        return None
    if any(parsed.path.lower().endswith(ext) for ext in SKIP_EXTENSIONS):
        return None
    return url


def looks_useful(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    query = parsed.query.lower()
    if "lang=en" in query or "lang=kz" in query:
        return False
    if any(part in path for part in ["/login", "/user", "/admin"]):
        return False
    return True


def fetch(url: str, timeout: int) -> tuple[str, str]:
    request = Request(
        url,
        headers={
            "User-Agent": "RAG-Abitur-Agent/1.0 (+https://ku.edu.kz/)",
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        content_type = response.headers.get("content-type", "")
        raw = response.read()
    if "text/html" not in content_type and "text/plain" not in content_type:
        return content_type, ""
    return content_type, raw.decode("utf-8", errors="ignore")


def crawl(start_urls: Iterable[str], max_pages: int, delay: float, timeout: int):
    queue = deque(start_urls)
    seen: set[str] = set()
    pages: list[tuple[str, str]] = []

    while queue and len(pages) < max_pages:
        raw_url = queue.popleft()
        url = normalize_url(raw_url)
        if not url or url in seen or not looks_useful(url):
            continue

        seen.add(url)
        print(f"[{len(pages) + 1}/{max_pages}] {url}", flush=True)
        try:
            _, body = fetch(url, timeout)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            print(f"  skip: {exc}", flush=True)
            continue

        extractor = TextExtractor(url)
        extractor.feed(body)
        text = extractor.text()
        if len(text) >= 300:
            pages.append((url, text))

        for link in extractor.links:
            normalized = normalize_url(link)
            if normalized and normalized not in seen and looks_useful(normalized):
                queue.append(normalized)

        if delay:
            time.sleep(delay)

    return pages


def write_output(path: Path, pages: list[tuple[str, str]]):
    path.parent.mkdir(parents=True, exist_ok=True)
    blocks = [
        "Официальная выгрузка страниц Kozybayev University для RAG-базы",
        "",
        "Домены: ku.edu.kz, www.ku.edu.kz, apply.ku.edu.kz",
        f"Количество страниц: {len(pages)}",
        "",
    ]
    for idx, (url, text) in enumerate(pages, start=1):
        blocks.append(f"\n===== СТРАНИЦА {idx}: {url} =====\n")
        blocks.append(text)
        blocks.append("\n")
    path.write_text("\n".join(blocks), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="docs/ku_site_crawl.txt")
    parser.add_argument("--max-pages", type=int, default=120)
    parser.add_argument("--delay", type=float, default=0.2)
    parser.add_argument("--timeout", type=int, default=8)
    args = parser.parse_args()

    pages = crawl(START_URLS, args.max_pages, args.delay, args.timeout)
    if not pages:
        raise SystemExit("No pages were downloaded. Check internet access or site availability.")
    write_output(Path(args.output), pages)
    print(f"\nSaved {len(pages)} pages to {args.output}")


if __name__ == "__main__":
    main()
