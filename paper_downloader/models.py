from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Paper:
    conference: str
    year: int
    title: str
    abstract: str = ""
    keywords: list[str] = field(default_factory=list)
    download_url: str = ""

    def __post_init__(self) -> None:
        self.conference = self.conference.lower()
        self.title = (self.title or "").strip()
        self.abstract = (self.abstract or "").strip()
        self.download_url = (self.download_url or "").strip()
        self.keywords = [str(item).strip() for item in (self.keywords or []) if str(item).strip()]

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict) -> "Paper":
        allowed = {
            "conference",
            "year",
            "title",
            "abstract",
            "keywords",
            "download_url",
        }
        return cls(**{key: data.get(key) for key in allowed if key in data})
