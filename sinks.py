import asyncio
import csv
from collections.abc import Sequence
from pathlib import Path
from types import TracebackType
from typing import Protocol, Self, TextIO

from schemas import Job

CSV_COLUMNS = (
    "id",
    "title",
    "url",
    "company",
    "company_slug",
    "company_stage",
    "company_head_count",
    "industries",
    "location",
    "locations",
    "latitude",
    "longitude",
    "work_mode",
    "work_mode_label",
    "seniority",
    "seniority_label",
    "skills",
    "compensation_min",
    "compensation_max",
    "compensation_currency",
    "compensation_period",
    "compensation_equity",
    "compensation_text",
    "posted_at",
    "source",
    "featured",
    "has_description",
    "slug",
)

_MULTI_VALUE_SEPARATOR = " | "


class JobSink(Protocol):
    async def write(self, jobs: Sequence[Job]) -> None: ...


def job_to_row(job: Job) -> dict[str, object]:
    primary = job.locations[0] if job.locations else None
    comp = job.compensation
    return {
        "id": job.id,
        "title": job.title,
        "url": job.url or "",
        "company": job.company.name,
        "company_slug": job.company.slug or "",
        "company_stage": job.company.stage or "",
        "company_head_count": job.company.head_count if job.company.head_count is not None else "",
        "industries": _MULTI_VALUE_SEPARATOR.join(job.company.industries),
        "location": job.location_text,
        "locations": _MULTI_VALUE_SEPARATOR.join(loc.name for loc in job.locations),
        "latitude": primary.latitude if primary and primary.latitude is not None else "",
        "longitude": primary.longitude if primary and primary.longitude is not None else "",
        "work_mode": job.work_mode.value,
        "work_mode_label": job.work_mode_label,
        "seniority": job.seniority.value,
        "seniority_label": job.seniority_label,
        "skills": _MULTI_VALUE_SEPARATOR.join(job.skills),
        "compensation_min": comp.min_amount if comp and comp.min_amount is not None else "",
        "compensation_max": comp.max_amount if comp and comp.max_amount is not None else "",
        "compensation_currency": comp.currency if comp else "",
        "compensation_period": comp.period if comp and comp.period else "",
        "compensation_equity": comp.offers_equity if comp else "",
        "compensation_text": comp.text if comp and comp.text else "",
        "posted_at": job.posted_at.isoformat() if job.posted_at else "",
        "source": job.source or "",
        "featured": job.featured,
        "has_description": job.has_description,
        "slug": job.slug or "",
    }


class CsvJobSink:
    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._handle: TextIO | None = None
        self._writer: csv.DictWriter | None = None
        self._lock = asyncio.Lock()
        self.rows_written = 0

    async def __aenter__(self) -> Self:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = await asyncio.to_thread(self._path.open, "w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._handle, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        await asyncio.to_thread(self._writer.writeheader)
        await asyncio.to_thread(self._handle.flush)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._handle is not None:
            await asyncio.to_thread(self._handle.close)
            self._handle = None
            self._writer = None

    async def write(self, jobs: Sequence[Job]) -> None:
        if not jobs:
            return
        if self._writer is None or self._handle is None:
            raise RuntimeError("CsvJobSink must be used as an async context manager")

        rows = [job_to_row(job) for job in jobs]
        async with self._lock:
            await asyncio.to_thread(self._flush_rows, rows)
        self.rows_written += len(rows)

    def _flush_rows(self, rows: list[dict[str, object]]) -> None:
        assert self._writer is not None and self._handle is not None
        self._writer.writerows(rows)
        self._handle.flush()


def read_rows(path: Path | str) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))
