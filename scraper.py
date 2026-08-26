import asyncio
import logging
from dataclasses import dataclass, field
from math import ceil

from config import Settings, get_settings
from getro import parse_job
from getro_client import GetroClient, SearchPage
from schemas import Job
from sinks import JobSink

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PageFailure:
    page: int
    reason: str


@dataclass(slots=True)
class ScrapeResult:
    query: str
    jobs: list[Job] = field(default_factory=list)
    reported_total: int = 0
    pages_fetched: int = 0
    failures: list[PageFailure] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.jobs)

    @property
    def is_partial(self) -> bool:
        return bool(self.failures)


@dataclass(frozen=True, slots=True)
class _BatchOutcome:
    added: bool
    exhausted: bool


class JobScraper:
    def __init__(self, client: GetroClient, settings: Settings | None = None) -> None:
        self._client = client
        self._settings = settings or get_settings()

    async def scrape(
        self,
        query: str = "",
        max_pages: int | None = None,
        sink: JobSink | None = None,
        seen: set[int] | None = None,
    ) -> ScrapeResult:
        result = ScrapeResult(query=query)
        seen = seen if seen is not None else set()

        first = await self._client.search_jobs(query, page=1)
        result.reported_total = first.total
        result.pages_fetched = 1
        await self._emit(self._collect(first, result, seen), sink)

        page_size = len(first.jobs)
        if page_size == 0:
            return result

        hard_cap = min(max_pages or self._settings.max_pages, self._settings.max_pages)
        estimated = ceil(first.total / page_size)
        page = 2

        while page <= hard_cap:
            window = self._next_window(page, estimated, hard_cap)
            outcome = await self._run_batch(query, window, page_size, result, seen, sink)
            if outcome.exhausted or not outcome.added:
                break
            page = window[-1] + 1

        result.jobs.sort(key=lambda job: (job.posted_at is None, job.posted_at), reverse=True)
        return result

    def _next_window(self, page: int, estimated: int, hard_cap: int) -> tuple[int, ...]:
        end = min(page + self._settings.batch_size - 1, hard_cap)
        if estimated >= page:
            end = min(end, estimated)
        return tuple(range(page, end + 1))

    async def _run_batch(
        self,
        query: str,
        pages: tuple[int, ...],
        page_size: int,
        result: ScrapeResult,
        seen: set[int],
        sink: JobSink | None,
    ) -> _BatchOutcome:
        logger.info("fetching pages %d-%d for %r", pages[0], pages[-1], query or "<all jobs>")
        outcomes = await asyncio.gather(
            *(self._client.search_jobs(query, page=page) for page in pages),
            return_exceptions=True,
        )

        batch: list[Job] = []
        exhausted = False
        for page, outcome in zip(pages, outcomes, strict=True):
            if isinstance(outcome, BaseException):
                if isinstance(outcome, asyncio.CancelledError):
                    raise outcome
                logger.warning("page %d failed: %s", page, outcome)
                result.failures.append(PageFailure(page=page, reason=str(outcome)))
                continue

            result.pages_fetched += 1
            batch.extend(self._collect(outcome, result, seen))
            exhausted |= len(outcome.jobs) < page_size

        await self._emit(batch, sink)
        return _BatchOutcome(added=bool(batch), exhausted=exhausted)

    def _collect(self, page: SearchPage, result: ScrapeResult, seen: set[int]) -> list[Job]:
        fresh: list[Job] = []
        for raw in page.jobs:
            job = parse_job(raw)
            if job is None or job.id in seen:
                continue
            seen.add(job.id)
            result.jobs.append(job)
            fresh.append(job)
        return fresh

    @staticmethod
    async def _emit(jobs: list[Job], sink: JobSink | None) -> None:
        if sink is not None and jobs:
            await sink.write(jobs)


async def scrape_jobs(
    query: str = "",
    max_pages: int | None = None,
    sink: JobSink | None = None,
) -> ScrapeResult:
    async with GetroClient() as client:
        return await JobScraper(client).scrape(query, max_pages=max_pages, sink=sink)
