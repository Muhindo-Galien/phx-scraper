import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

from make_pdf import main
from sinks import CSV_COLUMNS

NOW = datetime.now(timezone.utc)


def _csv(path: Path, ages: list[int]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for index, days in enumerate(ages):
            writer.writerow(
                {
                    "id": index,
                    "title": f"job {index}",
                    "company": "Acme",
                    "posted_at": (NOW - timedelta(days=days)).isoformat(),
                }
            )
    return path


def test_writes_both_pdfs(tmp_path, capsys):
    source = _csv(tmp_path / "jobs.csv", [10, 200])
    jobs_pdf, metrics_pdf = tmp_path / "j.pdf", tmp_path / "m.pdf"
    code = main([str(source), "--jobs-pdf", str(jobs_pdf), "--metrics-pdf", str(metrics_pdf)])
    assert code == 0
    assert jobs_pdf.is_file() and metrics_pdf.is_file()
    assert "of 2 (50.0%)" in capsys.readouterr().out


def test_jobs_only(tmp_path):
    source = _csv(tmp_path / "jobs.csv", [10])
    jobs_pdf, metrics_pdf = tmp_path / "j.pdf", tmp_path / "m.pdf"
    main([str(source), "--jobs-only", "--jobs-pdf", str(jobs_pdf), "--metrics-pdf", str(metrics_pdf)])
    assert jobs_pdf.is_file() and not metrics_pdf.exists()


def test_metrics_only(tmp_path):
    source = _csv(tmp_path / "jobs.csv", [10])
    jobs_pdf, metrics_pdf = tmp_path / "j.pdf", tmp_path / "m.pdf"
    main([str(source), "--metrics-only", "--jobs-pdf", str(jobs_pdf), "--metrics-pdf", str(metrics_pdf)])
    assert metrics_pdf.is_file() and not jobs_pdf.exists()


def test_conflicting_flags(tmp_path):
    assert main([str(tmp_path / "x.csv"), "--jobs-only", "--metrics-only"]) == 2


def test_missing_source(tmp_path):
    assert main([str(tmp_path / "nope.csv")]) == 1
