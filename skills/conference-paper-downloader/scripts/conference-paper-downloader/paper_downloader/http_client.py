from __future__ import annotations

import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class HttpClient:
    def __init__(self, timeout: int = 30, retries: int = 2) -> None:
        self.timeout = timeout
        self.retries = retries
        self.user_agent = (
            "Mozilla/5.0 (compatible; paper-downloader/0.1; "
            "+https://github.com/openai/codex)"
        )

    def get_bytes(self, url: str, headers: dict[str, str] | None = None) -> bytes:
        request_headers = {"User-Agent": self.user_agent}
        request_headers.update(headers or {})
        return self._open(Request(url, headers=request_headers)).read()

    def get_text(self, url: str, headers: dict[str, str] | None = None) -> str:
        content = self.get_bytes(url, headers=headers)
        return content.decode("utf-8", errors="replace")

    def get_json(self, url: str, headers: dict[str, str] | None = None) -> Any:
        return json.loads(self.get_text(url, headers=headers))

    def post_json(
        self,
        url: str,
        payload: dict,
        headers: dict[str, str] | None = None,
    ) -> Any:
        body = json.dumps(payload).encode("utf-8")
        request_headers = {
            "Content-Type": "application/json",
            "User-Agent": self.user_agent,
        }
        request_headers.update(headers or {})
        request = Request(url, data=body, method="POST", headers=request_headers)
        response = self._open(request)
        return json.loads(response.read().decode("utf-8", errors="replace"))

    def _open(self, request: Request):
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                return urlopen(request, timeout=self.timeout)
            except HTTPError as exc:
                if exc.code < 500 or attempt >= self.retries:
                    raise
                last_error = exc
            except URLError as exc:
                if attempt >= self.retries:
                    raise
                last_error = exc
            time.sleep(0.5 * (attempt + 1))
        if last_error:
            raise last_error
        raise RuntimeError("HTTP request failed without an exception")
