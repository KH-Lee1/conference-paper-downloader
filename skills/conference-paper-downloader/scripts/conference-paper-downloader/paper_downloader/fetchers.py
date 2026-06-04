from __future__ import annotations

import concurrent.futures
import re
import sys
import time
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from .http_client import HttpClient
from .models import Paper


OPENREVIEW_BASE = "https://openreview.net"
OPENREVIEW_API = "https://api2.openreview.net/notes"
PMLR_VOLUMES = {("icml", 2025): "v267"}


class ProgressBar:
    def __init__(self, label: str, total: int) -> None:
        self.label = label
        self.total = max(0, int(total))
        self.current = 0
        self.started_at = time.monotonic()
        self.last_rendered_at = 0.0
        self.enabled = self.total > 1
        if self.enabled:
            self.render(force=True)

    def update(self, step: int = 1) -> None:
        if not self.enabled:
            return
        self.current = min(self.total, self.current + step)
        now = time.monotonic()
        if self.current >= self.total or now - self.last_rendered_at >= 0.1:
            self.render(force=True)

    def close(self) -> None:
        if not self.enabled:
            return
        self.current = min(self.total, self.current)
        if self.current < self.total:
            self.render(force=True)
        sys.stderr.write("\n")
        sys.stderr.flush()

    def render(self, *, force: bool = False) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        if not force and now - self.last_rendered_at < 0.1:
            return
        self.last_rendered_at = now
        percent = (self.current / self.total) if self.total else 1.0
        width = 30
        filled = int(width * percent)
        bar = "#" * filled + "-" * (width - filled)
        elapsed = now - self.started_at
        sys.stderr.write(
            f"\r{self.label}: |{bar}| {self.current}/{self.total} "
            f"{percent * 100:5.1f}% elapsed {elapsed:0.1f}s"
        )
        sys.stderr.flush()


def absolute_url(base_url: str, href: str) -> str:
    return urljoin(base_url, href or "")


def fetch_papers(
    conference: str,
    year: int,
    *,
    limit: int | None = None,
    http_client: HttpClient | None = None,
    max_workers: int = 8,
) -> list[Paper]:
    client = http_client or HttpClient()
    conference = conference.lower()
    if conference == "iclr":
        return fetch_iclr_openreview(year, client=client, limit=limit)
    if conference == "icml":
        return fetch_icml(year, client=client, limit=limit, max_workers=max_workers)
    if conference == "neurips":
        return fetch_neurips(year, client=client, limit=limit, max_workers=max_workers)
    raise ValueError(f"Unsupported conference: {conference}")


def fetch_iclr_openreview(
    year: int,
    *,
    client: HttpClient,
    limit: int | None = None,
) -> list[Paper]:
    papers: list[Paper] = []
    seen: set[tuple[str, str]] = set()
    venue_kinds = ("Oral", "Spotlight", "Poster")
    progress = ProgressBar(f"ICLR {year} venue groups", len(venue_kinds))
    try:
        for venue_kind in venue_kinds:
            venue = f"ICLR {year} {venue_kind}"
            for note in _fetch_openreview_notes("ICLR", year, venue, client=client):
                paper = _paper_from_openreview_note(note, "iclr", year)
                key = (paper.title, paper.download_url)
                if paper.title and key not in seen:
                    papers.append(paper)
                    seen.add(key)
                    if limit and len(papers) >= limit:
                        return papers
            progress.update()
    finally:
        progress.close()
    return papers


def fetch_icml(
    year: int,
    *,
    client: HttpClient,
    limit: int | None = None,
    max_workers: int = 8,
) -> list[Paper]:
    volume = PMLR_VOLUMES.get(("icml", year))
    if volume:
        return fetch_pmlr_volume("icml", year, volume, client=client, limit=limit, max_workers=max_workers)
    return fetch_virtual_json("icml", year, client=client, limit=limit)


def fetch_neurips(
    year: int,
    *,
    client: HttpClient,
    limit: int | None = None,
    max_workers: int = 8,
) -> list[Paper]:
    if year == 2025:
        return fetch_neurips_proceedings(year, client=client, limit=limit, max_workers=max_workers)
    return fetch_virtual_json("neurips", year, client=client, limit=limit)


def _fetch_openreview_notes(
    conference: str,
    year: int,
    venue: str,
    *,
    client: HttpClient,
    page_size: int = 1000,
) -> list[dict]:
    notes: list[dict] = []
    offset = 0
    invitation = f"{conference}.cc/{year}/Conference/-/Submission"
    while True:
        params = {
            "invitation": invitation,
            "content.venue": venue,
            "limit": page_size,
            "offset": offset,
        }
        url = f"{OPENREVIEW_API}?{urlencode(params)}"
        data = client.get_json(url)
        page = data.get("notes", [])
        notes.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    return notes


def _content_value(content: dict, key: str, default=""):
    value = content.get(key, default)
    if isinstance(value, dict) and "value" in value:
        return value.get("value", default)
    return value


def _as_keywords(value) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        parts = re.split(r"[;,]", value)
        return [item.strip() for item in parts if item.strip()]
    return []


def _paper_from_openreview_note(note: dict, conference: str, year: int) -> Paper:
    content = note.get("content", {})
    title = str(_content_value(content, "title", "") or "")
    abstract = str(_content_value(content, "abstract", "") or "")
    keywords = _as_keywords(_content_value(content, "keywords", []))
    primary_area = str(_content_value(content, "primary_area", "") or "").strip()
    if primary_area:
        keywords.append(primary_area)
    pdf = str(_content_value(content, "pdf", "") or "")
    download_url = absolute_url(OPENREVIEW_BASE, pdf) if pdf else ""
    return Paper(
        conference=conference,
        year=year,
        title=title,
        abstract=abstract,
        keywords=keywords,
        download_url=download_url,
    )


def fetch_virtual_json(
    conference: str,
    year: int,
    *,
    client: HttpClient,
    limit: int | None = None,
) -> list[Paper]:
    base_url = f"https://{conference}.cc"
    papers_url = f"{base_url}/static/virtual/data/{conference}-{year}-orals-posters.json"
    abstracts_url = f"{base_url}/static/virtual/data/{conference}-{year}-abstracts.json"
    papers_data = client.get_json(papers_url)
    abstracts_data = client.get_json(abstracts_url)
    return _papers_from_virtual_data(
        conference,
        year,
        papers_data,
        abstracts_data,
        base_url=base_url,
        limit=limit,
    )


def _papers_from_virtual_data(
    conference: str,
    year: int,
    papers_data: dict,
    abstracts_data: dict,
    *,
    base_url: str,
    limit: int | None = None,
) -> list[Paper]:
    results = papers_data.get("results", [])
    if limit:
        results = results[:limit]
    papers: list[Paper] = []
    progress = ProgressBar(f"{conference.upper()} {year} records", len(results))
    try:
        for item in results:
            item_id = str(item.get("id", ""))
            title = str(item.get("name", "") or "")
            abstract = str(item.get("abstract") or abstracts_data.get(item_id, "") or "")
            keywords = _as_keywords(item.get("keywords", []))
            topic = str(item.get("topic") or "").strip()
            if topic:
                keywords.append(topic)
            download_url = _virtual_download_url(item, base_url)
            papers.append(
                Paper(
                    conference=conference,
                    year=year,
                    title=title,
                    abstract=abstract,
                    keywords=keywords,
                    download_url=download_url,
                )
            )
            progress.update()
    finally:
        progress.close()
    return papers


def _virtual_download_url(item: dict, base_url: str) -> str:
    pdf_url = str(item.get("paper_pdf_url") or "").strip()
    if pdf_url:
        return absolute_url(base_url, pdf_url)
    paper_url = str(item.get("paper_url") or "").strip()
    if paper_url.endswith(".pdf"):
        return absolute_url(base_url, paper_url)
    parsed = urlparse(paper_url)
    if parsed.netloc.endswith("openreview.net"):
        forum_id = parse_qs(parsed.query).get("id", [""])[0]
        if forum_id:
            return f"{OPENREVIEW_BASE}/pdf?id={forum_id}"
    return ""


def fetch_pmlr_volume(
    conference: str,
    year: int,
    volume: str,
    *,
    client: HttpClient,
    limit: int | None = None,
    max_workers: int = 8,
) -> list[Paper]:
    base_url = f"https://proceedings.mlr.press/{volume}/"
    index_html = client.get_text(base_url)
    entries = _parse_pmlr_index(index_html, base_url)
    if limit:
        entries = entries[:limit]

    def build(entry: dict) -> Paper:
        abstract = ""
        if entry.get("abstract_url"):
            try:
                abstract = _parse_pmlr_abstract(client.get_text(entry["abstract_url"]))
            except Exception:
                abstract = ""
        return Paper(
            conference=conference,
            year=year,
            title=entry.get("title", ""),
            abstract=abstract,
            keywords=[],
            download_url=entry.get("download_url", ""),
        )

    return _parallel_map(
        build,
        entries,
        max_workers=max_workers,
        progress_label=f"{conference.upper()} {year} abstracts",
    )


class _PmlrIndexParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.entries: list[dict] = []
        self._in_paper = False
        self._paper_depth = 0
        self._capture_title = False
        self._current: dict = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        classes = set((attr.get("class") or "").split())
        if tag == "div" and "paper" in classes:
            self._in_paper = True
            self._paper_depth = 1
            self._current = {"title": "", "abstract_url": "", "download_url": ""}
            return
        if self._in_paper and tag == "div":
            self._paper_depth += 1
        if self._in_paper and tag == "p" and "title" in classes:
            self._capture_title = True
        if self._in_paper and tag == "a":
            href = attr.get("href") or ""
            text_href = absolute_url(self.base_url, href)
            if href.endswith(".pdf"):
                self._current["download_url"] = text_href
            elif href.endswith(".html") and not self._current.get("abstract_url"):
                self._current["abstract_url"] = text_href

    def handle_endtag(self, tag: str) -> None:
        if self._capture_title and tag == "p":
            self._capture_title = False
        if self._in_paper and tag == "div":
            self._paper_depth -= 1
            if self._paper_depth <= 0:
                if self._current.get("title"):
                    self.entries.append(self._current)
                self._in_paper = False

    def handle_data(self, data: str) -> None:
        if self._capture_title:
            self._current["title"] = (self._current.get("title", "") + data).strip()


class _AbstractDivParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.text_parts: list[str] = []
        self._capture = False
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        classes = set((attr.get("class") or "").split())
        if tag in {"div", "p"} and (attr.get("id") == "abstract" or "abstract" in classes):
            self._capture = True
            self._depth = 1
            return
        if self._capture:
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._capture:
            self._depth -= 1
            if self._depth <= 0:
                self._capture = False

    def handle_data(self, data: str) -> None:
        if self._capture:
            self.text_parts.append(data)


def _parse_pmlr_index(html: str, base_url: str) -> list[dict]:
    parser = _PmlrIndexParser(base_url)
    parser.feed(html)
    return parser.entries


def _parse_pmlr_abstract(html: str) -> str:
    parser = _AbstractDivParser()
    parser.feed(html)
    text = " ".join(part.strip() for part in parser.text_parts if part.strip())
    text = re.sub(r"\s+", " ", unescape(text)).strip()
    return re.sub(r"^Abstract\s*", "", text, flags=re.IGNORECASE).strip()


def fetch_neurips_proceedings(
    year: int,
    *,
    client: HttpClient,
    limit: int | None = None,
    max_workers: int = 8,
) -> list[Paper]:
    base_url = "https://proceedings.neurips.cc"
    index_url = f"{base_url}/paper_files/paper/{year}"
    index_html = client.get_text(index_url)
    entries = _parse_neurips_index(index_html, base_url)
    if limit:
        entries = entries[:limit]

    def build(entry: dict) -> Paper:
        abstract = ""
        download_url = _neurips_pdf_from_abstract_url(entry.get("abstract_url", ""))
        try:
            detail = _parse_neurips_abstract(client.get_text(entry["abstract_url"]), entry["abstract_url"])
            abstract = detail.get("abstract", "")
            download_url = detail.get("download_url") or download_url
        except Exception:
            pass
        return Paper(
            conference="neurips",
            year=year,
            title=entry.get("title", ""),
            abstract=abstract,
            keywords=[],
            download_url=download_url,
        )

    return _parallel_map(
        build,
        entries,
        max_workers=max_workers,
        progress_label=f"NeurIPS {year} abstracts",
    )


class _NeuripsIndexParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.entries: list[dict] = []
        self._capture_href = ""
        self._capture_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attr = dict(attrs)
        href = attr.get("href") or ""
        if "-Abstract-" in href and "/paper_files/paper/" in href:
            self._capture_href = absolute_url(self.base_url, href)
            self._capture_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._capture_href:
            title = " ".join(part.strip() for part in self._capture_text if part.strip())
            if title:
                self.entries.append({"title": unescape(title), "abstract_url": self._capture_href})
            self._capture_href = ""
            self._capture_text = []

    def handle_data(self, data: str) -> None:
        if self._capture_href:
            self._capture_text.append(data)


class _NeuripsAbstractParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.abstract = ""
        self.download_url = ""
        self._capture_h4 = False
        self._h4_text: list[str] = []
        self._capture_next_p = False
        self._capture_p = False
        self._p_depth = 0
        self._p_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        classes = set((attr.get("class") or "").split())
        if self._capture_p:
            self._p_depth += 1
            return
        if tag in {"h2", "h4"}:
            self._capture_h4 = True
            self._h4_text = []
        elif tag == "p" and ("paper-abstract" in classes or self._capture_next_p) and not self.abstract:
            self._capture_p = True
            self._p_depth = 1
            self._p_parts = []
        elif tag == "a":
            href = attr.get("href") or ""
            if href.endswith(".pdf") and ("-Paper-" in href or not self.download_url):
                self.download_url = absolute_url(self.base_url, href)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"h2", "h4"} and self._capture_h4:
            text = normalize_space(" ".join(self._h4_text))
            self._capture_next_p = text.lower() == "abstract"
            self._capture_h4 = False
        elif self._capture_p:
            self._p_depth -= 1
            if self._p_depth <= 0:
                self.abstract = normalize_space(" ".join(self._p_parts))
                self._capture_p = False
                self._capture_next_p = False

    def handle_data(self, data: str) -> None:
        if self._capture_h4:
            self._h4_text.append(data)
        elif self._capture_p:
            self._p_parts.append(data)


def _parse_neurips_index(html: str, base_url: str) -> list[dict]:
    parser = _NeuripsIndexParser(base_url)
    parser.feed(html)
    return parser.entries


def _parse_neurips_abstract(html: str, abstract_url: str) -> dict:
    parser = _NeuripsAbstractParser(abstract_url)
    parser.feed(html)
    return {
        "abstract": parser.abstract,
        "download_url": parser.download_url or _neurips_pdf_from_abstract_url(abstract_url),
    }


def _neurips_pdf_from_abstract_url(abstract_url: str) -> str:
    if "-Abstract-" not in abstract_url:
        return ""
    return abstract_url.replace("-Abstract-", "-Paper-").removesuffix(".html") + ".pdf"


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value or "")).strip()


def _parallel_map(func, items: list, *, max_workers: int, progress_label: str | None = None) -> list:
    if not items:
        return []
    workers = max(1, min(max_workers, len(items)))
    progress = ProgressBar(progress_label, len(items)) if progress_label else None
    results = [None] * len(items)
    if workers == 1:
        try:
            for index, item in enumerate(items):
                results[index] = func(item)
                if progress:
                    progress.update()
        finally:
            if progress:
                progress.close()
        return results

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(func, item): index
                for index, item in enumerate(items)
            }
            for future in concurrent.futures.as_completed(futures):
                results[futures[future]] = future.result()
                if progress:
                    progress.update()
    finally:
        if progress:
            progress.close()
    return results
