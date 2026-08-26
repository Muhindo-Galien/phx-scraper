import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_MAX_AGE_DAYS = 90


@dataclass(frozen=True, slots=True)
class StaleReport:
    total: int
    stale: int
    undated: int
    max_age_days: int

    @property
    def percentage(self) -> float:
        return round(self.stale / self.total * 100, 2) if self.total else 0.0


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def analyze(path: Path, max_age_days: int = DEFAULT_MAX_AGE_DAYS, now: datetime | None = None) -> StaleReport:
    reference = now or datetime.now(timezone.utc)
    cutoff = reference - timedelta(days=max_age_days)

    total = stale = undated = 0
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            total += 1
            posted_at = _parse_timestamp((row.get("posted_at") or "").strip())
            if posted_at is None:
                undated += 1
            elif posted_at < cutoff:
                stale += 1

    return StaleReport(total=total, stale=stale, undated=undated, max_age_days=max_age_days)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report how many scraped jobs are older than N days.")
    parser.add_argument("csv_path", nargs="?", type=Path, default=Path("jobs.csv"))
    parser.add_argument("-d", "--days", type=int, default=DEFAULT_MAX_AGE_DAYS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.csv_path.is_file():
        print(f"no such file: {args.csv_path}", file=sys.stderr)
        return 1

    report = analyze(args.csv_path, args.days)
    print(f"jobs older than {report.max_age_days} days: {report.stale} of {report.total} ({report.percentage}%)")
    if report.undated:
        print(f"undated rows excluded from the stale count: {report.undated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
