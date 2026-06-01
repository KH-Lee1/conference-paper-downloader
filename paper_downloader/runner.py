from __future__ import annotations

import argparse
import concurrent.futures
import json
from datetime import datetime
from pathlib import Path

from .definitions import direction_slug, extract_definition_from_review, load_definition_file
from .downloader import download_pdf
from .fetchers import fetch_papers
from .http_client import HttpClient
from .llm import OpenAICompatibleClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download ICLR, ICML, and NeurIPS papers by direction.")
    parser.add_argument("--conference", required=True, choices=["iclr", "icml", "neurips"])
    parser.add_argument("--year", required=True, type=int, choices=[2025, 2026])
    parser.add_argument("--direction", required=True)
    parser.add_argument(
        "--review-paper",
        help="Required for v1. Absolute PDF path, or a file name/path relative to review_papers.",
    )
    parser.add_argument(
        "--version",
        choices=["v1", "v2"],
        default="v1",
        help="v1 extracts JSON, derives a review definition, then downloads matches; v2 extracts JSON only.",
    )
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "downloads")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=30)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be greater than 0")
    if args.max_workers <= 0:
        parser.error("--max-workers must be greater than 0")
    if args.version == "v1" and not args.review_paper:
        parser.error("--review-paper is required for v1")

    run(args)
    return 0


def run(args: argparse.Namespace) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d")
    run_dir = (
        args.output_dir
        / f"{args.conference}-{args.year}"
        / f"{direction_slug(args.direction)}-{timestamp}"
    )
    run_dir.mkdir(parents=True, exist_ok=True)

    papers = extract_json(args, run_dir)
    if args.version == "v2":
        write_json(run_dir / "run_status.json", _run_status(args, run_dir, papers, [], stage="json_only"))
        print(f"Run directory: {run_dir}")
        print(f"Total papers: {len(papers)}")
        print("Selected papers: 0")
        print("Mode: v2 JSON extraction only")
        return run_dir

    selected = process_papers(args, run_dir, papers)
    print(f"Run directory: {run_dir}")
    print(f"Total papers: {len(papers)}")
    print(f"Selected papers: {len(selected)}")
    return run_dir


def extract_json(args: argparse.Namespace, run_dir: Path):
    http_client = HttpClient(timeout=args.timeout)
    papers = fetch_papers(
        args.conference,
        args.year,
        limit=args.limit,
        http_client=http_client,
        max_workers=args.max_workers,
    )
    write_json(run_dir / "all_papers.json", [paper.to_json() for paper in papers])
    return papers


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def process_papers(args: argparse.Namespace, run_dir: Path, papers):
    llm_client = OpenAICompatibleClient(http_client=HttpClient(timeout=max(args.timeout, 60)))
    definitions_root = getattr(args, "definitions_root", None)
    if definitions_root is None:
        definition_file = extract_definition_from_review(
            direction=args.direction,
            review_paper=args.review_paper,
            llm_client=llm_client,
        )
    else:
        definition_file = extract_definition_from_review(
            direction=args.direction,
            review_paper=args.review_paper,
            output_root=definitions_root,
            llm_client=llm_client,
        )
    definition = load_definition_file(definition_file)
    args.definition_file = str(definition_file)
    selected = process_exact_parallel(args, run_dir, papers, llm_client=llm_client, definition=definition)

    write_json(run_dir / "selected_papers.json", [paper.to_json() for paper in selected])
    write_json(run_dir / "run_status.json", _run_status(args, run_dir, papers, selected, stage="processed"))
    return selected


def process_exact_parallel(
    args: argparse.Namespace,
    run_dir: Path,
    papers: list,
    *,
    llm_client,
    definition: str | None = None,
    download_func=download_pdf,
) -> list:
    pdf_dir = run_dir / "pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    workers = max(1, int(args.max_workers))
    download_client = HttpClient(timeout=max(args.timeout, 60))
    selected_by_index = {}

    def classify(index: int, paper):
        try:
            match_args = {
                "direction": args.direction,
                "title": paper.title,
                "abstract": paper.abstract,
            }
            if definition:
                match_args["definition"] = definition
            matched = llm_client.matches(**match_args)
            return index, paper, matched, None
        except Exception as exc:
            return index, paper, False, exc

    with (
        concurrent.futures.ThreadPoolExecutor(max_workers=workers) as llm_executor,
        concurrent.futures.ThreadPoolExecutor(max_workers=workers) as download_executor,
    ):
        llm_futures = [
            llm_executor.submit(classify, index, paper)
            for index, paper in enumerate(papers, start=1)
        ]
        download_futures = {}

        for future in concurrent.futures.as_completed(llm_futures):
            index, paper, matched, error = future.result()
            if error is not None:
                continue
            if not matched:
                continue

            selected_by_index[index] = paper
            download_future = download_executor.submit(
                download_func,
                paper,
                pdf_dir=pdf_dir,
                force=args.force,
                http_client=download_client,
            )
            download_futures[download_future] = paper

        for future in concurrent.futures.as_completed(download_futures):
            try:
                future.result()
            except Exception:
                pass

    return [selected_by_index[index] for index in sorted(selected_by_index)]


def _run_status(
    args: argparse.Namespace,
    run_dir: Path,
    papers,
    selected,
    *,
    stage: str,
) -> dict:
    return {
        "conference": args.conference,
        "year": args.year,
        "direction": args.direction,
        "version": args.version,
        "stage": stage,
        "review_paper": getattr(args, "review_paper", None),
        "definition_file": getattr(args, "definition_file", None),
        "definition_used": bool(getattr(args, "definition_file", None)),
        "force": bool(args.force),
        "limit": args.limit,
        "run_dir": str(run_dir),
        "total_papers": len(papers),
        "selected_papers": len(selected),
    }
