import asyncio
import random
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Self

import httpx

from config import Settings, get_settings
from errors import PayloadError, RateLimitError, TransientError, UpstreamError

RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


@dataclass(frozen=True, slots=True)
class SearchPage:
    page: int
    jobs: list[dict[str, Any]]
    total: int

    @property
    def is_empty(self) -> bool:
        return not self.jobs


class GetroClient:
    def __init__(self, settings: Settings | None = None, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = client
        self._owns_client = client is None
        self._semaphore = asyncio.Semaphore(self._settings.max_concurrency)

    async def __aenter__(self) -> Self:
        if self._client is None:
            limits = httpx.Limits(
                max_connections=self._settings.max_concurrency,
                max_keepalive_connections=self._settings.max_concurrency,
            )
            timeout = httpx.Timeout(self._settings.read_timeout, connect=self._settings.connect_timeout)
            self._client = httpx.AsyncClient(
                base_url=self._settings.getro_base_url,
                timeout=timeout,
                limits=limits,
                headers={
                    "content-type": "application/json",
                    "accept": "application/json",
                    "user-agent": self._settings.user_agent,
                },
            )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def search_jobs(self, query: str, page: int, hits_per_page: int | None = None) -> SearchPage:
        body = {
            "query": query,
            "page": page,
            "hitsPerPage": hits_per_page or self._settings.hits_per_page,
        }
        path = f"/collections/{self._settings.collection_id}/search/jobs"
        payload = await self._post_with_retry(path, body)
        return _to_search_page(payload, page)

    async def _post_with_retry(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None

        for attempt in range(self._settings.max_retries + 1):
            try:
                return await self._post(path, body)
            except RateLimitError as exc:
                last_error = exc
                delay = exc.retry_after if exc.retry_after is not None else self._backoff(attempt)
            except (TransientError, httpx.TransportError) as exc:
                last_error = exc
                delay = self._backoff(attempt)

            if attempt == self._settings.max_retries:
                break
            await asyncio.sleep(delay)

        raise TransientError(f"exhausted retries for {path}") from last_error

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        if self._client is None:
            raise RuntimeError("GetroClient must be used as an async context manager")

        async with self._semaphore:
            response = await self._client.post(path, json=body)

        if response.status_code in RETRYABLE_STATUS:
            if response.status_code == 429:
                raise RateLimitError(_retry_after_seconds(response))
            raise TransientError(f"upstream returned {response.status_code}")
        if response.is_error:
            raise UpstreamError(response.status_code, response.text[:200])

        try:
            return response.json()
        except ValueError as exc:
            raise PayloadError("upstream returned a non-JSON body") from exc

    def _backoff(self, attempt: int) -> float:
        capped = min(self._settings.backoff_base * 2**attempt, self._settings.backoff_max)
        return capped * (0.5 + random.random() / 2)


def _retry_after_seconds(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


def _to_search_page(payload: dict[str, Any], page: int) -> SearchPage:
    results = payload.get("results")
    if not isinstance(results, dict):
        raise PayloadError("upstream response is missing `results`")

    jobs = results.get("jobs")
    if not isinstance(jobs, list):
        raise PayloadError("upstream response is missing `results.jobs`")

    total = results.get("count")
    return SearchPage(
        page=page,
        jobs=[job for job in jobs if isinstance(job, dict)],
        total=total if isinstance(total, int) else len(jobs),
    )
