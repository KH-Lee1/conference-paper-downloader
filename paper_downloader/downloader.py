from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from urllib.error import HTTPError, URLError

from .http_client import HttpClient
from .models import Paper


WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
}

CONFERENCE_DISPLAY = {
    "iclr": "ICLR",
    "icml": "ICML",
    "neurips": "NeurIPS",
}


def sanitize_filename(value: str, fallback: str = "paper") -> str:
    value = unicodedata.normalize("NFKC", value or "").strip()
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    if not value:
        value = fallback
    if value.upper() in WINDOWS_RESERVED_NAMES:
        value = f"{value}_"
    return value[:180].rstrip(" .") or fallback


def conference_display(conference: str) -> str:
    return CONFERENCE_DISPLAY.get((conference or "").lower(), (conference or "").upper() or "CONF")


def paper_pdf_name(paper: Paper) -> str:
    base_name = f"{paper.year} {conference_display(paper.conference)} {paper.title}"
    return f"{sanitize_filename(base_name)}.pdf"


def ensure_unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 2
    while True:
        candidate = parent / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def download_selected_papers(
    papers: list[Paper],
    *,
    pdf_dir: Path,
    force: bool,
    http_client: HttpClient | None = None,
) -> list[Paper]:
    client = http_client or HttpClient(timeout=60, retries=2)
    pdf_dir.mkdir(parents=True, exist_ok=True)
    for paper in papers:
        download_pdf(
            paper,
            pdf_dir=pdf_dir,
            force=force,
            http_client=client,
        )
    return papers


def download_pdf(
    paper: Paper,
    *,
    pdf_dir: Path,
    force: bool,
    http_client: HttpClient,
) -> Path | None:
    if not paper.download_url:
        return None

    pdf_dir.mkdir(parents=True, exist_ok=True)
    target = pdf_dir / paper_pdf_name(paper)
    if target.exists() and not force:
        return target
    if target.exists() and force:
        target.unlink()
    else:
        target = ensure_unique_path(target)

    try:
        content = http_client.get_bytes(paper.download_url, headers={"Accept": "application/pdf,*/*"})
        if not content:
            return None
        target.write_bytes(content)
        return target
    except HTTPError:
        return None
    except (OSError, URLError):
        return None
