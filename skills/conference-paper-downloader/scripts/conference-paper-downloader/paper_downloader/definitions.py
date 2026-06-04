from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from .llm import OpenAICompatibleClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REVIEW_PAPERS_DIR = PROJECT_ROOT / "review_papers"
DEFINITIONS_DIR = PROJECT_ROOT / "definitions"


def normalize_for_slug(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").lower()
    value = re.sub(r"[\-_/:]+", " ", value)
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def slugify(value: str, fallback: str = "item") -> str:
    normalized = normalize_for_slug(value)
    slug = re.sub(r"[^\w]+", "-", normalized, flags=re.UNICODE).strip("-")
    return (slug or fallback)[:80]


def direction_slug(direction: str, fallback: str = "direction") -> str:
    return slugify(direction, fallback=fallback)


def resolve_review_paper(review_paper: str | Path, review_dir: Path = REVIEW_PAPERS_DIR) -> Path:
    path = Path(review_paper).expanduser()
    if path.is_absolute():
        resolved = path
    else:
        resolved = review_dir / path
        if not resolved.exists() and path.exists():
            resolved = path
    if not resolved.exists():
        raise FileNotFoundError(f"Review paper not found: {resolved}")
    if not resolved.is_file():
        raise FileNotFoundError(f"Review paper is not a file: {resolved}")
    return resolved


def extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("pypdf is required. Run: pip install -r requirements.txt") from exc

    reader = PdfReader(str(path))
    pages: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            pages.append(text)
    text = clean_review_text("\n\n".join(pages))
    if not text:
        raise ValueError(f"No extractable text found in review paper: {path}")
    return text


def clean_review_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text(text: str, max_chars: int = 12000, overlap: int = 800) -> list[str]:
    text = clean_review_text(text)
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            boundary = text.rfind("\n\n", start, end)
            if boundary > start + max_chars // 2:
                end = boundary
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return [chunk for chunk in chunks if chunk]


def extract_definition_from_text(
    *,
    direction: str,
    review_text: str,
    llm_client,
    max_chunk_chars: int = 12000,
) -> str:
    chunks = chunk_text(review_text, max_chars=max_chunk_chars)
    if not chunks:
        raise ValueError("Review text is empty; cannot extract definition")

    if len(chunks) == 1:
        definition = _extract_final_definition(direction=direction, review_material=chunks[0], llm_client=llm_client)
    else:
        candidates = [
            _extract_candidate_definition(direction=direction, chunk=chunk, llm_client=llm_client)
            for chunk in chunks
        ]
        review_material = "\n\n".join(
            candidate.strip()
            for candidate in candidates
            if candidate and candidate.strip()
        )
        if not review_material:
            raise ValueError("No direction definition candidates were extracted from the review paper")
        definition = _extract_final_definition(
            direction=direction,
            review_material=review_material,
            llm_client=llm_client,
        )

    definition = (definition or "").strip()
    if not definition:
        raise ValueError("LLM returned an empty direction definition")
    return definition


def save_definition(
    *,
    direction: str,
    review_paper: Path,
    definition: str,
    model: str,
    output_root: Path = DEFINITIONS_DIR,
    created_at: str | None = None,
) -> Path:
    created_at = created_at or datetime.now().strftime("%Y%m%d")
    output_dir = output_root / direction_slug(direction)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{slugify(review_paper.stem, fallback='review')}-{created_at}.json"
    data = {
        "direction": direction,
        "review_paper": str(review_paper),
        "definition": definition,
        "model": model,
        "created_at": created_at,
    }
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def extract_definition_from_review(
    *,
    direction: str,
    review_paper: str | Path,
    output_root: Path = DEFINITIONS_DIR,
    review_dir: Path = REVIEW_PAPERS_DIR,
    llm_client=None,
) -> Path:
    resolved_review = resolve_review_paper(review_paper, review_dir=review_dir)
    client = llm_client or OpenAICompatibleClient()
    review_text = extract_pdf_text(resolved_review)
    definition = extract_definition_from_text(direction=direction, review_text=review_text, llm_client=client)
    return save_definition(
        direction=direction,
        review_paper=resolved_review,
        definition=definition,
        model=getattr(client, "model", ""),
        output_root=output_root,
    )


def latest_definition_file(direction: str, definitions_root: Path = DEFINITIONS_DIR) -> Path:
    definition_dir = definitions_root / direction_slug(direction)
    candidates = sorted(definition_dir.glob("*.json"), key=lambda path: (path.stat().st_mtime, path.name))
    if not candidates:
        raise FileNotFoundError(
            f"No definition JSON found for direction '{direction}' under {definition_dir}. "
            "Run main.py with --review-paper to extract a definition."
        )
    return candidates[-1]


def load_latest_definition(direction: str, definitions_root: Path = DEFINITIONS_DIR) -> tuple[Path, str]:
    path = latest_definition_file(direction, definitions_root=definitions_root)
    return path, load_definition_file(path)


def load_definition_file(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    definition = (data.get("definition") or "").strip()
    if not definition:
        raise ValueError(f"Definition file has an empty 'definition' field: {path}")
    return definition


def _extract_candidate_definition(*, direction: str, chunk: str, llm_client) -> str:
    return llm_client.complete_prompt(
        system_prompt="You extract research-direction definitions from survey papers.",
        user_prompt=(
            f"Research direction: {direction}\n\n"
            "Review paper excerpt:\n"
            f"{chunk}\n\n"
            "Extract only the parts that define this research direction, including inclusion criteria, "
            "exclusion criteria, key attributes, and boundary cases if present. "
            "If the excerpt has no relevant definition, reply with an empty string."
        ),
        max_tokens=900,
        temperature=0,
    )


def _extract_final_definition(*, direction: str, review_material: str, llm_client) -> str:
    return llm_client.complete_prompt(
        system_prompt="You write concise definitions for research paper screening.",
        user_prompt=(
            f"Research direction: {direction}\n\n"
            "Review material:\n"
            f"{review_material}\n\n"
            "Write a concise screening definition for this research direction. "
            "Include what should be counted as relevant, what should be excluded, and important borderline cases. "
            "Do not summarize the whole review paper."
        ),
        max_tokens=900,
        temperature=0,
    )
