from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import Body, Depends, FastAPI, HTTPException, Query, status
from pydantic import BaseModel, Field

from config import get_settings
from errors import ScraperError, UpstreamError
from getro import parse_payload
from getro_client import GetroClient
from schemas import Job, JobPage
from scraper import JobScraper, ScrapeResult
from store import JobStore


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with GetroClient(get_settings()) as client:
        app.state.client = client
        app.state.store = JobStore()
        yield


app = FastAPI(
    title="phx-scraper",
    version="0.1.0",
    description="Scrapes the Getro job collection behind jobs.phxfwd.org into one consistent shape.",
    lifespan=lifespan,
)


def get_scraper() -> JobScraper:
    return JobScraper(app.state.client, get_settings())


def get_store() -> JobStore:
    return app.state.store


class ScrapeRequest(BaseModel):
    query: str = Field("", examples=["software engineer"])
    max_pages: int | None = Field(None, ge=1, le=500)
    store: bool = True


class ScrapeReport(BaseModel):
    query: str
    total: int
    reported_total: int
    scraped: int
    pages_fetched: int
    failed_pages: list[int]
    partial: bool
    jobs: list[Job]

    @classmethod
    def of(cls, result: ScrapeResult) -> "ScrapeReport":
        return cls(
            query=result.query,
            total=result.total,
            reported_total=result.reported_total,
            scraped=len(result.jobs),
            pages_fetched=result.pages_fetched,
            failed_pages=[failure.page for failure in result.failures],
            partial=result.is_partial,
            jobs=result.jobs,
        )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/scrape", summary="Scrape the upstream collection in batched pages")
async def scrape(
    request: ScrapeRequest,
    scraper: JobScraper = Depends(get_scraper),
    store: JobStore = Depends(get_store),
) -> ScrapeReport:
    try:
        result = await scraper.scrape(request.query, max_pages=request.max_pages)
    except UpstreamError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    except ScraperError as exc:
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, str(exc)) from exc

    if request.store:
        store.upsert_many(result.jobs)
    return ScrapeReport.of(result)


@app.post("/normalize", summary="Normalize a raw payload without fetching or storing")
def normalize(payload: dict[str, Any] = Body(...)) -> JobPage:
    jobs, total = parse_payload(payload)
    return JobPage.of(jobs, total=total, per_page=max(len(jobs), 1))


@app.get("/jobs")
def list_jobs(
    q: str | None = Query(None, description="Case-insensitive match on title, company, or skill."),
    company: str | None = Query(None, description="Company slug or name."),
    work_mode: str | None = None,
    seniority: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    store: JobStore = Depends(get_store),
) -> JobPage:
    return store.search(
        q=q,
        company=company,
        work_mode=work_mode,
        seniority=seniority,
        page=page,
        per_page=per_page,
    )


@app.get("/jobs/{job_id}")
def get_job(job_id: int, store: JobStore = Depends(get_store)) -> Job:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return job


@app.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(job_id: int, store: JobStore = Depends(get_store)) -> None:
    if not store.delete(job_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
