import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

from config import get_settings
from errors import ScraperError
from getro_client import GetroClient
from scraper import JobScraper, PageFailure
from sinks import CsvJobSink

logger = logging.getLogger("phx.scrape")


@dataclass(slots=True)
class RunSummary:
    written: int = 0
    reported_total: int = 0
    pages_fetched: int = 0
    failures: list[PageFailure] = field(default_factory=list)

    @property
    def is_partial(self) -> bool:
        return bool(self.failures)


async def scrape_to_csv(queries: list[str], out: Path, max_pages: int | None = None) -> RunSummary:
    settings = get_settings()
    summary = RunSummary()
    seen: set[int] = set()

    async with CsvJobSink(out) as sink, GetroClient(settings) as client:
        scraper = JobScraper(client, settings)
        for query in queries:
            result = await scraper.scrape(query, max_pages=max_pages, sink=sink, seen=seen)
            summary.reported_total = max(summary.reported_total, result.reported_total)
            summary.pages_fetched += result.pages_fetched
            summary.failures.extend(result.failures)
            logger.info(
                "query %r -> %d new jobs across %d pages",
                query or "<all jobs>",
                result.total,
                result.pages_fetched,
            )
        summary.written = sink.rows_written

    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape the Getro collection into a CSV file.")
    parser.add_argument(
        "-q",
        "--query",
        dest="queries",
        action="append",
        default=None,
        help="Repeatable. Omit to scrape every job in the collection.",
    )
    parser.add_argument("-o", "--out", type=Path, default=Path("jobs.csv"))
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    queries = args.queries or [""]

    try:
        summary = asyncio.run(scrape_to_csv(queries, args.out, args.max_pages))
    except KeyboardInterrupt:
        print("interrupted; partial CSV kept", file=sys.stderr)
        return 130
    except ScraperError as exc:
        print(f"scrape failed: {exc}", file=sys.stderr)
        return 1

    print(f"wrote {summary.written} jobs to {args.out}")
    print(f"pages fetched: {summary.pages_fetched}  upstream reported: {summary.reported_total}")
    if summary.is_partial:
        print(f"partial run, {len(summary.failures)} page(s) failed: {[f.page for f in summary.failures]}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
