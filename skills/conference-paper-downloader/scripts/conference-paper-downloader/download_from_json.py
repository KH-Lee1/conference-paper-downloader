from __future__ import annotations

import argparse
import json
from pathlib import Path

from paper_downloader.downloader import download_selected_papers
from paper_downloader.http_client import HttpClient
from paper_downloader.models import Paper


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download PDFs from a selected paper JSON list.")
    parser.add_argument("--selected-json", required=True, type=Path)
    parser.add_argument("--pdf-dir", required=True, type=Path)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--timeout", type=int, default=60)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    data = json.loads(args.selected_json.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("--selected-json must contain a JSON list")
    papers = [Paper.from_json(item) for item in data if isinstance(item, dict)]
    download_selected_papers(
        papers,
        pdf_dir=args.pdf_dir,
        force=args.force,
        http_client=HttpClient(timeout=args.timeout, retries=2),
    )
    print(f"Downloaded {len(papers)} selected paper records to {args.pdf_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
