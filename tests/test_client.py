import httpx
import pytest

from errors import PayloadError, RateLimitError, TransientError, UpstreamError
from getro_client import GetroClient


def _page(jobs: int, count: int = 100) -> dict:
    return {"results": {"count": count, "jobs": [{"id": i, "title": f"job {i}"} for i in range(jobs)]}}


async def _run(settings, handler):
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        client = GetroClient(settings, client=http)
        return await client.search_jobs("q", page=1)


async def test_returns_parsed_page(settings):
    page = await _run(settings, lambda request: httpx.Response(200, json=_page(3, count=42)))
    assert page.page == 1
    assert page.total == 42
    assert len(page.jobs) == 3


async def test_sends_expected_body(settings):
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(__import__("json").loads(request.content))
        return httpx.Response(200, json=_page(1))

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        await GetroClient(settings, client=http).search_jobs("software engineer", page=3)

    assert seen == [{"query": "software engineer", "page": 3, "hitsPerPage": 20}]


async def test_retries_then_succeeds(settings):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_page(1)) if calls > 2 else httpx.Response(503)

    page = await _run(settings, handler)
    assert calls == 3
    assert len(page.jobs) == 1


async def test_exhausts_retries(settings):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    with pytest.raises(TransientError):
        await _run(settings, handler)
    assert calls == settings.max_retries + 1


async def test_honours_retry_after(settings):
    seen: list[float] = []

    async def fake_sleep(delay: float) -> None:
        seen.append(delay)

    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"retry-after": "0.01"})
        return httpx.Response(200, json=_page(1))

    import asyncio

    original, asyncio.sleep = asyncio.sleep, fake_sleep
    try:
        await _run(settings, handler)
    finally:
        asyncio.sleep = original

    assert seen == [0.01]


async def test_rate_limit_surfaces_after_retries(settings):
    with pytest.raises(TransientError) as excinfo:
        await _run(settings, lambda request: httpx.Response(429))
    assert isinstance(excinfo.value.__cause__, RateLimitError)


async def test_client_error_is_not_retried(settings):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, text="bad query")

    with pytest.raises(UpstreamError) as excinfo:
        await _run(settings, handler)
    assert calls == 1
    assert excinfo.value.status_code == 400


async def test_retries_transport_errors(settings):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectTimeout("boom", request=request)
        return httpx.Response(200, json=_page(2))

    page = await _run(settings, handler)
    assert calls == 2
    assert len(page.jobs) == 2


async def test_malformed_payload(settings):
    with pytest.raises(PayloadError):
        await _run(settings, lambda request: httpx.Response(200, json={"nope": True}))


async def test_requires_context_manager(settings):
    with pytest.raises(RuntimeError):
        await GetroClient(settings).search_jobs("q", page=1)
