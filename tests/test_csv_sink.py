import csv
import json
from datetime import datetime, timezone

import httpx

from getro_client import GetroClient
from schemas import Job
from scraper import JobScraper
from sinks import CSV_COLUMNS, CsvJobSink
from tests.test_scraper import _job, paged_handler


async def test_writes_header_for_empty_run(tmp_path):
    path = tmp_path / "jobs.csv"
    async with CsvJobSink(path):
        pass
    assert path.read_text(encoding="utf-8").strip() == ",".join(CSV_COLUMNS)


async def test_flattens_a_job(tmp_path):
    path = tmp_path / "jobs.csv"
    job = Job.model_validate(
        {
            "id": 7,
            "title": "Engineer",
            "company": {"name": "Acme", "slug": "acme", "industries": ["Fintech", "SaaS"]},
            "locations": [{"name": "Phoenix, AZ, USA", "latitude": 33.4, "longitude": -112.0}],
            "work_mode": "remote",
            "seniority": "director",
            "skills": ["Python", "Async"],
            "compensation": {"min_amount": 170000, "max_amount": 190000, "period": "year", "offers_equity": True},
            "posted_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
        }
    )
    async with CsvJobSink(path) as sink:
        await sink.write([job])

    row = next(iter(csv.DictReader(path.open(newline="", encoding="utf-8"))))
    assert row["company"] == "Acme"
    assert row["industries"] == "Fintech | SaaS"
    assert row["skills"] == "Python | Async"
    assert row["compensation_text"] == "$170,000 - $190,000/yr + equity"
    assert row["seniority_label"] == "Director"
    assert row["latitude"] == "33.4"
    assert row["posted_at"] == "2026-01-02T00:00:00+00:00"


async def test_quotes_commas_and_unicode(tmp_path):
    path = tmp_path / "jobs.csv"
    job = Job.model_validate(
        {
            "id": 1,
            "title": 'Engineer, "Platform" — Café',
            "company": {"name": "A, B & C"},
            "locations": [{"name": "Montréal, QC, Canada"}],
        }
    )
    async with CsvJobSink(path) as sink:
        await sink.write([job])

    row = next(iter(csv.DictReader(path.open(newline="", encoding="utf-8"))))
    assert row["title"] == 'Engineer, "Platform" — Café'
    assert row["company"] == "A, B & C"
    assert row["location"] == "Montréal, QC, Canada"


async def test_rows_land_during_the_scrape(settings, tmp_path):
    settings.batch_size = 2
    path = tmp_path / "jobs.csv"
    pages = {p: [_job(p * 100 + i) for i in range(20)] for p in range(1, 8)}
    pages[7] = [_job(700)]
    base = paged_handler(pages, count=10_000)
    row_counts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content)["page"] > 1:
            row_counts.append(sum(1 for _ in path.open(encoding="utf-8")) - 1)
        return base(request)

    transport = httpx.MockTransport(handler)
    async with CsvJobSink(path) as sink, httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        scraper = JobScraper(GetroClient(settings, client=http), settings)
        result = await scraper.scrape("", sink=sink)

    assert row_counts[0] == 20
    assert max(row_counts) < result.total
    assert sink.rows_written == result.total


async def test_partial_run_keeps_written_rows(settings, tmp_path):
    path = tmp_path / "jobs.csv"
    pages = {p: [_job(p * 100 + i) for i in range(20)] for p in range(1, 4)}
    base = paged_handler(pages, count=60)

    def handler(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content)["page"] == 2:
            return httpx.Response(500)
        return base(request)

    transport = httpx.MockTransport(handler)
    async with CsvJobSink(path) as sink, httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        result = await JobScraper(GetroClient(settings, client=http), settings).scrape("", sink=sink)

    rows = list(csv.DictReader(path.open(newline="", encoding="utf-8")))
    assert result.is_partial
    assert len(rows) == 40


async def test_requires_context_manager(tmp_path):
    import pytest

    with pytest.raises(RuntimeError):
        await CsvJobSink(tmp_path / "jobs.csv").write([Job.model_validate({"id": 1, "title": "x", "company": {"name": "y"}})])
