import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sinks import CSV_COLUMNS
from stale_jobs import analyze, main

NOW = datetime(2026, 8, 25, tzinfo=timezone.utc)


def _write(path: Path, ages: list[int | None]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for index, days in enumerate(ages):
            posted = "" if days is None else (NOW - timedelta(days=days)).isoformat()
            writer.writerow({"id": index, "title": f"job {index}", "posted_at": posted})


def test_counts_and_percentage(tmp_path):
    path = tmp_path / "jobs.csv"
    _write(path, [10, 30, 91, 200, 365])
    report = analyze(path, now=NOW)
    assert report.total == 5
    assert report.stale == 3
    assert report.percentage == 60.0


def test_boundary_is_exclusive(tmp_path):
    path = tmp_path / "jobs.csv"
    _write(path, [90, 91])
    report = analyze(path, now=NOW)
    assert report.stale == 1


def test_undated_rows_are_reported_not_counted(tmp_path):
    path = tmp_path / "jobs.csv"
    _write(path, [200, None, None, 5])
    report = analyze(path, now=NOW)
    assert report.total == 4
    assert report.stale == 1
    assert report.undated == 2
    assert report.percentage == 25.0


def test_custom_window(tmp_path):
    path = tmp_path / "jobs.csv"
    _write(path, [10, 40, 100])
    assert analyze(path, max_age_days=30, now=NOW).stale == 2


def test_empty_file_does_not_divide_by_zero(tmp_path):
    path = tmp_path / "jobs.csv"
    _write(path, [])
    report = analyze(path, now=NOW)
    assert report.total == 0
    assert report.percentage == 0.0


def test_missing_file_exits_nonzero(tmp_path, capsys):
    assert main([str(tmp_path / "nope.csv")]) == 1


def test_cli_output(tmp_path, capsys):
    path = tmp_path / "jobs.csv"
    _write(path, [10, 200])
    assert main([str(path)]) == 0
    assert "of 2" in capsys.readouterr().out
