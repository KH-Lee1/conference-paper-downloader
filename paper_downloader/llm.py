from __future__ import annotations

import os

from .http_client import HttpClient


def parse_yes_no(value: str) -> bool | None:
    cleaned = (value or "").strip().strip("\"'`").strip().lower()
    if cleaned == "yes":
        return True
    if cleaned == "no":
        return False
    return None


class OpenAICompatibleClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        http_client: HttpClient | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.model = model or os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"
        self.http_client = http_client or HttpClient(timeout=60, retries=2)
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is required for LLM calls")

    def matches(
        self,
        *,
        direction: str,
        title: str,
        abstract: str,
        definition: str | None = None,
    ) -> bool:
        response = self._complete(direction=direction, title=title, abstract=abstract, definition=definition)
        return parse_yes_no(response) is True

    def complete_prompt(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 800,
        temperature: float = 0,
    ) -> str:
        payload = {
            "model": self.model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        data = self._post_chat(payload)
        return data["choices"][0]["message"]["content"]

    def _complete(
        self,
        *,
        direction: str,
        title: str,
        abstract: str,
        definition: str | None = None,
    ) -> str:
        definition_block = ""
        if definition:
            definition_block = (
                "Definition extracted from the review paper:\n"
                f"{definition.strip()}\n\n"
            )
        payload = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": 3,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You classify research papers."
                        "Reply with exactly one token: yes or no."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Research direction: {direction}\n\n"
                        f"{definition_block}"
                        f"Paper title: {title}\n\n"
                        f"Paper abstract: {abstract}\n\n"
                        "Does this paper primarily match the research direction?"
                        "Reply exactly yes or no. Do not output anything else."
                    ),
                },
            ],
        }
        data = self._post_chat(payload)
        return data["choices"][0]["message"]["content"]

    def _post_chat(self, payload: dict) -> dict:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        return self.http_client.post_json(f"{self.base_url}/chat/completions", payload, headers=headers)
