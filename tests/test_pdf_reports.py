from datetime import datetime, timedelta, timezone

from pypdf import PdfReader

from pdf_reports import build_jobs_pdf, build_metrics_pdf
from stale_jobs import StaleReport

NOW = datetime(2026, 8, 25, tzinfo=timezone.utc)


def _text(path) -> str:
    return "".join(page.extract_text() for page in PdfReader(str(path)).pages)


def _row(**overrides) -> dict[str, str]:
    row = {
        "id": "1",
        "title": "Staff Engineer",
        "company": "Acme",
        "location": "Phoenix, AZ, USA",
        "work_mode_label": "Remote",
        "seniority_label": "Director",
        "skills": "Python | Async",
        "compensation_text": "$170,000 - $190,000/yr",
        "posted_at": (NOW - timedelta(days=5)).isoformat(),
        "url": "https://example.com/job/1",
    }
    row.update(overrides)
    return row


def test_metrics_pdf_reports_only_the_requested_window(tmp_path):
    path = build_metrics_pdf(StaleReport(total=136, stale=71, undated=0, max_age_days=90), tmp_path / "m.pdf", now=NOW)
    text = _text(path)
    assert "90-Day Staleness Report" in text
    assert "52.21%" in text
    assert "136" in text and "71" in text and "65" in text
    assert "30-day" not in text and "180" not in text


def test_metrics_pdf_notes_undated_rows(tmp_path):
    path = build_metrics_pdf(StaleReport(total=10, stale=4, undated=3, max_age_days=90), tmp_path / "m.pdf", now=NOW)
    assert "3 row(s) carry no posting date" in _text(path)


def test_metrics_pdf_handles_empty_dataset(tmp_path):
    path = build_metrics_pdf(StaleReport(total=0, stale=0, undated=0, max_age_days=90), tmp_path / "m.pdf", now=NOW)
    assert "0.0%" in _text(path)


def test_jobs_pdf_contains_each_posting(tmp_path):
    rows = [_row(id=str(i), title=f"Engineer {i}") for i in range(30)]
    text = _text(build_jobs_pdf(rows, tmp_path / "j.pdf", now=NOW))
    for i in range(30):
        assert f"Engineer {i}" in text


def test_jobs_pdf_renders_separators_not_entities(tmp_path):
    text = _text(build_jobs_pdf([_row()], tmp_path / "j.pdf", now=NOW))
    assert "&middot;" not in text
    assert "&amp;" not in text
    assert "·" in text


def test_jobs_pdf_escapes_markup_characters(tmp_path):
    rows = [_row(title="R&D <Lead>", company="A & B")]
    text = _text(build_jobs_pdf(rows, tmp_path / "j.pdf", now=NOW))
    assert "R&D <Lead>" in text
    assert "A & B" in text


def test_jobs_pdf_shows_age_and_summary(tmp_path):
    rows = [
        _row(id="1", posted_at=(NOW - timedelta(days=200)).isoformat()),
        _row(id="2", posted_at=(NOW - timedelta(days=3)).isoformat()),
        _row(id="3", posted_at=""),
    ]
    text = _text(build_jobs_pdf(rows, tmp_path / "j.pdf", now=NOW))
    assert "200d ago" in text
    assert "3d ago" in text
    assert "date unknown" in text
    assert "OLDER THAN 90D" in text


def test_jobs_pdf_sorted_newest_first(tmp_path):
    rows = [
        _row(id="1", title="Older", posted_at=(NOW - timedelta(days=100)).isoformat()),
        _row(id="2", title="Newer", posted_at=(NOW - timedelta(days=1)).isoformat()),
    ]
    text = _text(build_jobs_pdf(rows, tmp_path / "j.pdf", now=NOW))
    assert text.index("Newer") < text.index("Older")


def test_jobs_pdf_handles_empty_and_sparse_rows(tmp_path):
    assert "No postings." in _text(build_jobs_pdf([], tmp_path / "empty.pdf", now=NOW))
    sparse = [{"id": "1", "title": "Bare"}]
    assert "Bare" in _text(build_jobs_pdf(sparse, tmp_path / "sparse.pdf", now=NOW))


def test_jobs_pdf_paginates(tmp_path):
    rows = [_row(id=str(i), title=f"Engineer {i}") for i in range(120)]
    assert len(PdfReader(str(build_jobs_pdf(rows, tmp_path / "j.pdf", now=NOW))).pages) > 1
