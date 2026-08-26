import asyncio
import json

import httpx
import pytest

from getro_client import GetroClient
from scraper import JobScraper


def _job(job_id: int) -> dict:
    return {
        "id": job_id,
        "title": f"Engineer {job_id}",
        "created_at": 1785839127 + job_id,
        "organization": {"name": "Acme", "slug": "acme"},
        "work_mode": "remote",
        "compensation_public": True,
        "compensation_amount_min_cents": 10000000,
        "compensation_currency": "USD",
        "compensation_period": "year",
    }


def paged_handler(pages: dict[int, list[dict]], count: int, concurrency: list[int] | None = None):
    inflight = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal inflight
        page = json.loads(request.content)["page"]
        if concurrency is not None:
            inflight += 1
            concurrency.append(inflight)
            inflight -= 1
        return httpx.Response(200, json={"results": {"count": count, "jobs": pages.get(page, [])}})

    return handler


async def _scrape(settings, handler, query: str = "q", max_pages: int | None = None):
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        scraper = JobScraper(GetroClient(settings, client=http), settings)
        return await scraper.scrape(query, max_pages=max_pages)


async def test_walks_all_pages(settings):
    pages = {p: [_job(p * 100 + i) for i in range(20)] for p in range(1, 5)}
    pages[5] = [_job(500)]
    result = await _scrape(settings, paged_handler(pages, count=81))
    assert result.total == 81
    assert result.pages_fetched == 5


async def test_stops_after_batch_containing_short_page(settings):
    settings.batch_size = 2
    pages = {p: [_job(p * 100 + i) for i in range(20)] for p in range(1, 10)}
    pages[2] = [_job(200)]
    result = await _scrape(settings, paged_handler(pages, count=10_000))
    assert result.pages_fetched == 3
    assert result.total == 41


async def test_never_exceeds_batch_size(settings):
    settings.batch_size = 5
    settings.max_concurrency = 5
    pages = {p: [_job(p * 100 + i) for i in range(20)] for p in range(1, 30)}
    seen: list[int] = []
    await _scrape(settings, paged_handler(pages, count=10_000, concurrency=seen), max_pages=25)
    assert max(seen) <= 5


async def test_respects_max_pages(settings):
    pages = {p: [_job(p * 100 + i) for i in range(20)] for p in range(1, 50)}
    result = await _scrape(settings, paged_handler(pages, count=10_000), max_pages=3)
    assert result.pages_fetched == 3
    assert result.total == 60


async def test_deduplicates_across_pages(settings):
    repeated = [_job(i) for i in range(20)]
    result = await _scrape(settings, paged_handler({1: repeated, 2: repeated, 3: repeated}, count=60))
    assert result.total == 20


async def test_isolates_failing_pages(settings):
    pages = {p: [_job(p * 100 + i) for i in range(20)] for p in range(1, 4)}
    base = paged_handler(pages, count=60)

    def handler(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content)["page"] == 2:
            return httpx.Response(500)
        return base(request)

    result = await _scrape(settings, handler)
    assert result.is_partial
    assert [f.page for f in result.failures] == [2]
    assert result.total == 40


async def test_empty_result_set(settings):
    result = await _scrape(settings, paged_handler({}, count=0))
    assert result.total == 0
    assert result.pages_fetched == 1
    assert not result.is_partial


async def test_sorted_newest_first(settings):
    result = await _scrape(settings, paged_handler({1: [_job(i) for i in range(5)]}, count=5))
    dates = [job.posted_at for job in result.jobs]
    assert dates == sorted(dates, reverse=True)


async def test_cancellation_propagates(settings):
    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(200, json={"results": {"count": 0, "jobs": []}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        scraper = JobScraper(GetroClient(settings, client=http), settings)
        task = asyncio.create_task(scraper.scrape("q"))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
