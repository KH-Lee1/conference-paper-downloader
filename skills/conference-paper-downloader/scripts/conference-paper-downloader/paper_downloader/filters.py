from __future__ import annotations

from collections.abc import Iterable
import re
import unicodedata

from .models import Paper


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").lower()
    value = re.sub(r"[\-_/:]+", " ", value)
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def select_by_llm(papers: Iterable[Paper], direction: str, llm_client) -> list[Paper]:
    selected: list[Paper] = []
    for paper in papers:
        if llm_client.matches(direction=direction, title=paper.title, abstract=paper.abstract):
            selected.append(paper)
    return selected
