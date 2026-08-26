import argparse
import sys
from pathlib import Path

from pdf_reports import build_jobs_pdf, build_metrics_pdf
from sinks import read_rows
from stale_jobs import DEFAULT_MAX_AGE_DAYS, analyze


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render the scraped CSV as human-readable PDFs.")
    parser.add_argument("csv_path", nargs="?", type=Path, default=Path("jobs.csv"))
    parser.add_argument("--jobs-pdf", type=Path, default=Path("jobs.pdf"))
    parser.add_argument("--metrics-pdf", type=Path, default=Path("metrics.pdf"))
    parser.add_argument("-d", "--days", type=int, default=DEFAULT_MAX_AGE_DAYS)
    parser.add_argument("--jobs-only", action="store_true")
    parser.add_argument("--metrics-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.jobs_only and args.metrics_only:
        print("--jobs-only and --metrics-only are mutually exclusive", file=sys.stderr)
        return 2
    if not args.csv_path.is_file():
        print(f"no such file: {args.csv_path}", file=sys.stderr)
        return 1

    if not args.metrics_only:
        rows = read_rows(args.csv_path)
        build_jobs_pdf(rows, args.jobs_pdf, max_age_days=args.days)
        print(f"wrote {len(rows)} postings to {args.jobs_pdf}")

    if not args.jobs_only:
        report = analyze(args.csv_path, args.days)
        build_metrics_pdf(report, args.metrics_pdf, source=args.csv_path)
        print(f"wrote {args.metrics_pdf}")
        print(f"jobs older than {report.max_age_days} days: {report.stale} of {report.total} ({report.percentage}%)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
