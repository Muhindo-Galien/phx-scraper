from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm

INK = colors.HexColor("#1a1a1a")
MUTED = colors.HexColor("#6b7280")
RULE = colors.HexColor("#e5e7eb")
ACCENT = colors.HexColor("#b45309")
FRESH = colors.HexColor("#0f766e")
STALE = colors.HexColor("#b45309")
UNDATED = colors.HexColor("#9ca3af")

PAGE_MARGIN = 16 * mm


def build_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["BodyText"]
    return {
        "title": ParagraphStyle("title", parent=base, fontName="Helvetica-Bold", fontSize=22, leading=26, textColor=INK),
        "subtitle": ParagraphStyle("subtitle", parent=base, fontSize=9.5, leading=13, textColor=MUTED),
        "section": ParagraphStyle(
            "section", parent=base, fontName="Helvetica-Bold", fontSize=8, leading=11,
            textColor=MUTED, spaceBefore=6, spaceAfter=4,
        ),
        "job_title": ParagraphStyle("job_title", parent=base, fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=INK),
        "meta": ParagraphStyle("meta", parent=base, fontSize=8.5, leading=12, textColor=MUTED),
        "body": ParagraphStyle("body", parent=base, fontSize=9, leading=12.5, textColor=INK),
        "pay": ParagraphStyle("pay", parent=base, fontName="Helvetica-Bold", fontSize=9, leading=12, textColor=ACCENT),
        "stale_flag": ParagraphStyle("stale_flag", parent=base, fontSize=8, leading=11, textColor=STALE, alignment=TA_RIGHT),
        "metric_value": ParagraphStyle("metric_value", parent=base, fontName="Helvetica-Bold", fontSize=30, leading=34, textColor=INK),
        "metric_label": ParagraphStyle("metric_label", parent=base, fontSize=8, leading=11, textColor=MUTED),
        "headline": ParagraphStyle("headline", parent=base, fontName="Helvetica-Bold", fontSize=54, leading=58, textColor=STALE),
    }
