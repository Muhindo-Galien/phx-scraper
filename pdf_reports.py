from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from pdf_styles import ACCENT, FRESH, INK, MUTED, PAGE_MARGIN, RULE, STALE, UNDATED, build_styles
from stale_jobs import StaleReport

PAGE_SIZE = A4
CONTENT_WIDTH = PAGE_SIZE[0] - 2 * PAGE_MARGIN


class ProportionBar(Flowable):
    def __init__(self, segments: Sequence[tuple[float, colors.Color]], width: float, height: float = 9 * mm) -> None:
        super().__init__()
        self.segments = [(value, color) for value, color in segments if value > 0]
        self.width = width
        self.height = height

    def draw(self) -> None:
        total = sum(value for value, _ in self.segments)
        if total <= 0:
            self.canv.setFillColor(RULE)
            self.canv.roundRect(0, 0, self.width, self.height, 2, stroke=0, fill=1)
            return

        offset = 0.0
        for value, color in self.segments:
            span = self.width * value / total
            self.canv.setFillColor(color)
            self.canv.rect(offset, 0, span, self.height, stroke=0, fill=1)
            offset += span


class Rule(Flowable):
    def __init__(self, width: float, color: colors.Color = RULE) -> None:
        super().__init__()
        self.width = width
        self.height = 0.6
        self.color = color

    def draw(self) -> None:
        self.canv.setStrokeColor(self.color)
        self.canv.setLineWidth(0.6)
        self.canv.line(0, 0, self.width, 0)


def _escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _age_days(row: dict[str, str], now: datetime) -> int | None:
    posted = _parse_timestamp((row.get("posted_at") or "").strip())
    return (now - posted).days if posted else None


def _footer(canvas, doc, label: str) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(PAGE_MARGIN, PAGE_MARGIN * 0.55, label)
    canvas.drawRightString(PAGE_SIZE[0] - PAGE_MARGIN, PAGE_MARGIN * 0.55, f"Page {canvas.getPageNumber()}")
    canvas.restoreState()


def _document(path: Path, title: str, footer_label: str) -> BaseDocTemplate:
    doc = BaseDocTemplate(
        str(path),
        pagesize=PAGE_SIZE,
        leftMargin=PAGE_MARGIN,
        rightMargin=PAGE_MARGIN,
        topMargin=PAGE_MARGIN,
        bottomMargin=PAGE_MARGIN,
        title=title,
        author="phx-scraper",
    )
    frame = Frame(PAGE_MARGIN, PAGE_MARGIN, CONTENT_WIDTH, PAGE_SIZE[1] - 2 * PAGE_MARGIN, id="body")
    doc.addPageTemplates(
        PageTemplate(id="main", frames=[frame], onPage=lambda canvas, d: _footer(canvas, d, footer_label))
    )
    return doc


def _metric_cards(entries: Sequence[tuple[str, str]], styles: dict) -> Table:
    cells = [
        [
            Paragraph(value, styles["metric_value"]),
        ]
        for value, _ in entries
    ]
    table = Table(
        [[Paragraph(value, styles["metric_value"]) for value, _ in entries],
         [Paragraph(label.upper(), styles["metric_label"]) for _, label in entries]],
        colWidths=[CONTENT_WIDTH / len(entries)] * len(entries),
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                ("TOPPADDING", (0, 0), (-1, 0), 0),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 1),
                ("TOPPADDING", (0, 1), (-1, 1), 0),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("LINEABOVE", (0, 0), (-1, 0), 0.6, RULE),
                ("TOPPADDING", (0, 0), (-1, 0), 8),
            ]
        )
    )
    return table


def build_metrics_pdf(
    report: StaleReport,
    path: Path | str,
    source: Path | str | None = None,
    now: datetime | None = None,
) -> Path:
    path = Path(path)
    generated = now or datetime.now(timezone.utc)
    styles = build_styles()
    cutoff = generated - timedelta(days=report.max_age_days)
    fresh = report.total - report.stale - report.undated

    story: list = [
        Paragraph(f"{report.max_age_days}-Day Staleness Report", styles["title"]),
        Spacer(1, 3),
        Paragraph(
            f"Generated {generated:%d %b %Y %H:%M} UTC"
            + (f" &middot; source {_escape(Path(source).name)}" if source else ""),
            styles["subtitle"],
        ),
        Spacer(1, 22),
        Paragraph(f"{report.percentage}%", styles["headline"]),
        Paragraph(
            f"of postings are older than {report.max_age_days} days "
            f"(posted before {cutoff:%d %b %Y})",
            styles["subtitle"],
        ),
        Spacer(1, 20),
        ProportionBar([(report.stale, STALE), (fresh, FRESH), (report.undated, UNDATED)], CONTENT_WIDTH),
        Spacer(1, 8),
        Paragraph(
            f'<font color="#b45309">&#9632;</font> Older than {report.max_age_days} days &nbsp;&nbsp;'
            f'<font color="#0f766e">&#9632;</font> Within {report.max_age_days} days'
            + (f' &nbsp;&nbsp;<font color="#9ca3af">&#9632;</font> Undated' if report.undated else ""),
            styles["meta"],
        ),
        Spacer(1, 26),
        _metric_cards(
            [
                (str(report.total), "Total jobs"),
                (str(report.stale), f"Older than {report.max_age_days}d"),
                (str(fresh), f"Within {report.max_age_days}d"),
                (f"{report.percentage}%", "Stale share"),
            ],
            styles,
        ),
    ]

    if report.undated:
        story += [
            Spacer(1, 16),
            Paragraph(
                f"{report.undated} row(s) carry no posting date and are excluded from the stale count.",
                styles["meta"],
            ),
        ]

    _document(path, f"{report.max_age_days}-day staleness report", "phx-scraper staleness report").build(story)
    return path


def _job_block(row: dict[str, str], now: datetime, max_age_days: int, styles: dict) -> KeepTogether:
    age = _age_days(row, now)
    is_stale = age is not None and age > max_age_days

    facts = [row.get("company", ""), row.get("location", ""), row.get("work_mode_label", "")]
    seniority = row.get("seniority_label", "")
    if seniority and seniority != "Not specified":
        facts.append(seniority)

    if age is None:
        age_text = "date unknown"
    elif age == 0:
        age_text = "posted today"
    else:
        age_text = f"{age}d ago"

    header = Table(
        [
            [
                Paragraph(_escape(row.get("title", "Untitled")), styles["job_title"]),
                Paragraph(
                    f'<font color="{"#b45309" if is_stale else "#6b7280"}">{age_text}</font>',
                    styles["stale_flag"],
                ),
            ]
        ],
        colWidths=[CONTENT_WIDTH * 0.8, CONTENT_WIDTH * 0.2],
    )
    header.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )

    parts: list = [header, Paragraph(" &middot; ".join(_escape(f) for f in facts if f), styles["meta"])]

    pay = row.get("compensation_text", "")
    if pay:
        parts.append(Paragraph(_escape(pay), styles["pay"]))

    skills = row.get("skills", "")
    if skills:
        trimmed = skills.split(" | ")[:8]
        parts.append(Paragraph("Skills: " + _escape(", ".join(trimmed)), styles["body"]))

    url = row.get("url", "")
    if url:
        parts.append(Paragraph(f'<link href="{_escape(url)}"><font color="#6b7280">{_escape(url[:96])}</font></link>', styles["meta"]))

    parts += [Spacer(1, 7), Rule(CONTENT_WIDTH), Spacer(1, 9)]
    return KeepTogether(parts)


def build_jobs_pdf(
    rows: Sequence[dict[str, str]],
    path: Path | str,
    max_age_days: int = 90,
    now: datetime | None = None,
) -> Path:
    path = Path(path)
    generated = now or datetime.now(timezone.utc)
    styles = build_styles()

    ordered = sorted(rows, key=lambda row: (row.get("posted_at") or "", row.get("title", "")), reverse=True)
    companies = {row.get("company", "") for row in ordered if row.get("company")}
    stale = sum(1 for row in ordered if (age := _age_days(row, generated)) is not None and age > max_age_days)

    story: list = [
        Paragraph("Job Board", styles["title"]),
        Spacer(1, 3),
        Paragraph(
            f"{len(ordered)} postings from {len(companies)} companies &middot; "
            f"newest first &middot; generated {generated:%d %b %Y %H:%M} UTC",
            styles["subtitle"],
        ),
        Spacer(1, 14),
        _metric_cards(
            [
                (str(len(ordered)), "Postings"),
                (str(len(companies)), "Companies"),
                (str(stale), f"Older than {max_age_days}d"),
            ],
            styles,
        ),
        Spacer(1, 22),
        Paragraph("LISTINGS", styles["section"]),
        Rule(CONTENT_WIDTH, INK),
        Spacer(1, 9),
    ]

    if not ordered:
        story.append(Paragraph("No postings.", styles["body"]))
    else:
        story += [_job_block(row, generated, max_age_days, styles) for row in ordered]

    _document(path, "Job board", "phx-scraper job board").build(story)
    return path
