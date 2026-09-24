"""
Generate bid and proposal PDFs using reportlab.

The customer proposal PDF follows Standard Interiors' JobRunner "Estimate"
layout (logo, boxed quote fields, blue bars, priced text blocks, Grand Total
and Deposit boxes, then the 5/16/2023 Terms and Conditions).
"""

import os
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    HRFlowable,
    PageBreak,
    KeepTogether,
    BaseDocTemplate,
    Flowable,
    Frame,
    PageTemplate,
)
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER

from proposal_totals import effective_bundle_total, money, number
from proposal_terms import (
    DEFAULT_PROPOSAL_TERMS,
    LEGACY_PROPOSAL_TERMS,
    SI_TERMS,
    SI_TERMS_PREAMBLE,
    SI_TERMS_TITLE,
)


COMPANY_NAME = "STANDARD INTERIORS"
COMPANY_ADDRESS = "1050 W HAMPDEN AVE, STE 300 ENGLEWOOD, CO 80110"

TERMS_TEXT = (
    "Payment terms: Net 30 from invoice date. "
    "Pricing is valid for 30 days from quote date. "
    "Material pricing subject to change based on vendor availability. "
    "Change orders will be priced separately. "
    "Standard Interiors is not responsible for pre-existing substrate conditions."
)

# ─────────────────────────────────────────────────────────────────────────────
# Bid PDF (original)
# ─────────────────────────────────────────────────────────────────────────────

def _build_styles() -> dict:
    """Create custom paragraph styles."""
    base = getSampleStyleSheet()
    styles = {}
    styles["title"] = ParagraphStyle(
        "BidTitle",
        parent=base["Title"],
        fontSize=18,
        spaceAfter=4,
        textColor=colors.HexColor("#1a1a2e"),
    )
    styles["subtitle"] = ParagraphStyle(
        "BidSubtitle",
        parent=base["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#555555"),
        spaceAfter=12,
    )
    styles["heading"] = ParagraphStyle(
        "BidHeading",
        parent=base["Heading2"],
        fontSize=12,
        spaceBefore=12,
        spaceAfter=6,
        textColor=colors.HexColor("#1a1a2e"),
    )
    styles["body"] = ParagraphStyle(
        "BidBody",
        parent=base["Normal"],
        fontSize=10,
        leading=14,
    )
    styles["small"] = ParagraphStyle(
        "BidSmall",
        parent=base["Normal"],
        fontSize=8,
        textColor=colors.HexColor("#666666"),
    )
    styles["price"] = ParagraphStyle(
        "BidPrice",
        parent=base["Normal"],
        fontSize=11,
        alignment=2,  # Right-aligned
        fontName="Helvetica-Bold",
    )
    styles["total"] = ParagraphStyle(
        "BidTotal",
        parent=base["Normal"],
        fontSize=14,
        alignment=2,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#1a1a2e"),
    )
    return styles


def _header_footer(canvas, doc):
    """Draw page number in footer."""
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#999999"))
    page_num = canvas.getPageNumber()
    canvas.drawCentredString(
        letter[0] / 2, 0.5 * inch,
        f"Page {page_num}"
    )
    canvas.restoreState()


def generate_bid_pdf(
    bid_data: dict,
    output_path: str,
    quote_number: Optional[str] = None,
) -> str:
    """
    Generate a bid PDF document.

    Args:
        bid_data: output from bid_assembler.assemble_bid()
        output_path: where to save the PDF
        quote_number: optional quote reference number

    Returns:
        The output file path.
    """
    styles = _build_styles()

    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
    )

    story = []
    job_info = bid_data.get("job_info", {})

    # ── Header ────────────────────────────────────────────────────────────
    story.append(Paragraph(COMPANY_NAME, styles["title"]))
    story.append(Paragraph(COMPANY_ADDRESS, styles["subtitle"]))
    story.append(HRFlowable(
        width="100%", thickness=2,
        color=colors.HexColor("#1a1a2e"), spaceAfter=12
    ))

    # ── Quote metadata ────────────────────────────────────────────────────
    today = date.today().strftime("%B %d, %Y")
    q_num = quote_number or f"Q-{job_info.get('id', '000')}"
    meta_data = [
        ["Quote #:", q_num, "Date:", today],
        ["Salesperson:", job_info.get("salesperson", ""), "", ""],
    ]
    meta_table = Table(meta_data, colWidths=[1.2 * inch, 2.5 * inch, 0.8 * inch, 2.5 * inch])
    meta_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 12))

    # ── Customer / Job Site info ──────────────────────────────────────────
    address_line = ", ".join(filter(None, [
        job_info.get("address"),
        job_info.get("city"),
        job_info.get("state"),
        job_info.get("zip"),
    ]))
    info_data = [
        ["Project:", job_info.get("project_name", ""), "GC:", job_info.get("gc_name", "")],
        ["Job Site:", address_line, "", ""],
    ]
    info_table = Table(info_data, colWidths=[1.0 * inch, 3.0 * inch, 0.5 * inch, 2.5 * inch])
    info_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 16))
    story.append(HRFlowable(
        width="100%", thickness=1,
        color=colors.HexColor("#cccccc"), spaceAfter=12
    ))

    # ── Bundle line items ─────────────────────────────────────────────────
    bundles = bid_data.get("bundles", [])
    for i, bundle in enumerate(bundles):
        # Bundle header
        story.append(Paragraph(
            f"<b>{bundle['bundle_name']}</b>",
            styles["heading"],
        ))

        # Description and price side by side
        desc_text = bundle.get("description_text", "").replace("\n", "<br/>")
        price_text = f"${bundle['total_price']:,.2f}"

        row_data = [[
            Paragraph(desc_text, styles["body"]),
            Paragraph(price_text, styles["price"]),
        ]]
        row_table = Table(row_data, colWidths=[5.0 * inch, 2.0 * inch])
        row_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(row_table)

        # Separator between bundles
        if i < len(bundles) - 1:
            story.append(HRFlowable(
                width="100%", thickness=0.5,
                color=colors.HexColor("#dddddd"), spaceAfter=8, spaceBefore=4
            ))

    # ── Totals ────────────────────────────────────────────────────────────
    story.append(Spacer(1, 16))
    story.append(HRFlowable(
        width="100%", thickness=2,
        color=colors.HexColor("#1a1a2e"), spaceAfter=8
    ))

    totals_data = [
        ["Subtotal:", f"${bid_data['subtotal']:,.2f}"],
    ]
    if bid_data.get("tax_rate", 0) > 0:
        totals_data.append([
            f"Tax ({bid_data['tax_rate'] * 100:.2f}%):",
            f"${bid_data['tax_amount']:,.2f}",
        ])
    totals_data.append(["Grand Total:", f"${bid_data['grand_total']:,.2f}"])

    totals_table = Table(totals_data, colWidths=[5.0 * inch, 2.0 * inch])
    totals_styles = [
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    # Bold the grand total row
    last_row = len(totals_data) - 1
    totals_styles.append(("FONTNAME", (0, last_row), (-1, last_row), "Helvetica-Bold"))
    totals_styles.append(("FONTSIZE", (0, last_row), (-1, last_row), 14))
    totals_table.setStyle(TableStyle(totals_styles))
    story.append(totals_table)

    # ── Exclusions ────────────────────────────────────────────────────────
    exclusions = bid_data.get("exclusions", [])
    if exclusions:
        story.append(Spacer(1, 20))
        story.append(Paragraph("<b>Exclusions:</b>", styles["heading"]))
        for exc in exclusions:
            story.append(Paragraph(f"&bull; {exc}", styles["body"]))

    # ── Terms & Conditions ────────────────────────────────────────────────
    story.append(Spacer(1, 20))
    story.append(Paragraph("<b>Terms &amp; Conditions:</b>", styles["heading"]))
    story.append(Paragraph(TERMS_TEXT, styles["small"]))

    # ── Signature block ───────────────────────────────────────────────────
    story.append(Spacer(1, 40))
    sig_data = [
        ["Accepted By:", "_" * 40, "Date:", "_" * 20],
        ["Print Name:", "_" * 40, "Title:", "_" * 20],
    ]
    sig_table = Table(sig_data, colWidths=[1.2 * inch, 2.8 * inch, 0.8 * inch, 2.2 * inch])
    sig_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
    ]))
    story.append(sig_table)

    # ── Build PDF ─────────────────────────────────────────────────────────
    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    return output_path


# ─────────────────────────────────────────────────────────────────────────────
# Proposal PDF: Standard Interiors "Estimate" (JobRunner quote layout)
#
# Page geometry, fonts and colors are measured from Josh's JobRunner estimate
# for Sun Valley Block 2 (quote 293113). All positions below are in points
# measured from the TOP of a US Letter page, then flipped for ReportLab.
# ─────────────────────────────────────────────────────────────────────────────

_PAGE_W, _PAGE_H = letter

_SI_BLUE = colors.HexColor("#0000AA")
_SI_RED = colors.HexColor("#AA0000")
_SI_RULE_GRAY = colors.HexColor("#7F7F7F")
_SI_TOTAL_GRAY = colors.HexColor("#CCCCCC")
_SI_DEPOSIT_GRAY = colors.HexColor("#DDDDDD")

_LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "si_logo.png")

# Content frame: 20pt left edge to 594pt right edge, as in the JobRunner print.
_FRAME_X = 20.0
_FRAME_W = 574.0
_FRAME_BOTTOM = 36.0
_FIRST_BAR_BOTTOM = 244.1   # page 1 column bar bottom (from top)
_LATER_BAR_BOTTOM = 64.1    # pages 2+ column bar bottom (from top)
_FRAME_TOP_OVERLAP = 2.65   # first price baseline sits 10.9pt under the bar
_FIRST_FRAME_H = _PAGE_H - (_FIRST_BAR_BOTTOM - _FRAME_TOP_OVERLAP) - _FRAME_BOTTOM
_LATER_FRAME_H = _PAGE_H - (_LATER_BAR_BOTTOM - _FRAME_TOP_OVERLAP) - _FRAME_BOTTOM
# Text wraps inside the 'General Information / Description' column (20pt to
# ~536pt); the Total column to its right only carries prices.
_TEXT_WRAP_W = 512.0

# Title, preamble and clauses 1-16 live in proposal_terms (shared with the
# proposal editor's default Terms list).

SI_FLOOR_PREP_BOLD = "Floor prep can be expensive and very time consuming."
SI_FLOOR_PREP_RATES: list[str] = [
    "**Mechanic (performed on T&M basis) $75.26/hr",
    "**Grinding prep (performed on T&M basis)  $115.38/hr",
    "**Floor Prep Patch $69.23/bag",
    "**Floor Prep Leveling $96.67/bag",
]

SI_EXCLUSIONS: list[str] = [
    "Waterproofing",
    "Sound underlayment",
    "All flooring and tile substrates",
    "Demo, Hoisting, Forklift, and/or Elevator for transport to work area provided by customer",
    "Grounding and Testing of Static Dissipative Flooring/ESD flooring is by qualified "
    "electrician provided by customer",
    "Waxing & Sealing of all materials as this is part of the customers maintenance program",
    "Countertops, wood base, solid surface products, elevator cab finishes, FRP, Sealing or "
    "Staining of Concrete Exterior and/or landscaping tile or flooring products",
    "Caulking to material installed by other trades, including base, trim, cabinets, "
    "toilets, bathtubs, shower pans, windows, doors, etc.",
    "Floor protection, protection of other trades finished materials",
    "Touchup or repairs required to wall base installed prior to flooring for primer, "
    "adhesive and scratches from lvt and carpet installation",
    "Bonding",
    "Prevailing Wage, Davis Bacon, or other related programs",
    "Credits for participation in OCIP/CCIP programs",
    "Door modification & cut down",
    "Clean-up program participation",
    "Temporary HVAC and/or weather protection",
    "Price increases due to tariffs or trade disputes",
    "Extended project durations may incur additional supervision and material storage fees",
]

SI_WARRANTY: list[str] = [
    "Standard Interiors warrants all labor for a period of one year along with "
    "manufacturer’s warranty on all materials.",
    "To provide a fully warranted system, the GC/Owner is required to provide all "
    "requirements per manufactures recommendations for the entire duration of the "
    "warranty period.",
]


def _norm_clause(text) -> str:
    value = str(text or "").lower()
    value = (value.replace("’", "'").replace("‘", "'")
             .replace("“", '"').replace("”", '"').replace("&", " and "))
    value = re.sub(r"\s+", " ", value).strip()
    return value.rstrip(". ")


_PREAMBLE_KEY = _norm_clause(SI_TERMS_PREAMBLE)
_SI_CLAUSE_INDEX = {_norm_clause(text): index for index, text in enumerate(SI_TERMS)}
_LEGACY_TERM_KEYS = [_norm_clause(text) for text in LEGACY_PROPOSAL_TERMS]


def _printed_terms(terms) -> list[tuple[str, str]]:
    """The job's saved Terms as ('preamble' | 'clause', markup) items, in order.

    The saved list prints as-is, so the PDF matches the proposal editor. A list
    that is empty or exactly the tool's earlier default set (never edited)
    prints the 5/16/2023 terms instead. A saved clause that matches a 5/16/2023
    clause prints in its standard wording (clause 7 with its bold sentence and
    T&M rate lines); any other text prints as typed.
    """
    saved = [str(term).strip() for term in (terms or []) if str(term or "").strip()]
    if not saved or [_norm_clause(text) for text in saved] == _LEGACY_TERM_KEYS:
        saved = list(DEFAULT_PROPOSAL_TERMS)
    items = []
    for text in saved:
        key = _norm_clause(text)
        if key == _PREAMBLE_KEY:
            items.append(("preamble", escape(SI_TERMS_PREAMBLE)))
        elif key in _SI_CLAUSE_INDEX:
            index = _SI_CLAUSE_INDEX[key]
            items.append(("clause", _si_terms_markup(index, SI_TERMS[index])))
        else:
            items.append(("clause", _clause_markup(text)))
    return items


def _to_denver(moment: datetime) -> datetime:
    """Denver (Mountain) wall-clock time for an aware datetime, without relying on tzdata."""
    try:
        from zoneinfo import ZoneInfo
        return moment.astimezone(ZoneInfo("America/Denver")).replace(tzinfo=None)
    except Exception:
        utc = moment.astimezone(timezone.utc).replace(tzinfo=None)
        year = utc.year
        march1 = datetime(year, 3, 1)
        nov1 = datetime(year, 11, 1)
        # DST: 2:00 MST on the second Sunday of March to 2:00 MDT on the first
        # Sunday of November.
        dst_start = march1 + timedelta(days=(6 - march1.weekday()) % 7 + 7, hours=2 + 7)
        dst_end = nov1 + timedelta(days=(6 - nov1.weekday()) % 7, hours=2 + 6)
        offset = -6 if dst_start <= utc < dst_end else -7
        return utc + timedelta(hours=offset)


def _denver_now() -> datetime:
    """Current wall-clock time in Denver (Mountain)."""
    return _to_denver(datetime.now(timezone.utc))


def _us_date(value: datetime) -> str:
    return f"{value.month}/{value.day}/{value.year}"


def _quote_date_text(value, fallback: datetime) -> str:
    """The header 'Date' box: the quote's own date, not the print date.

    Accepts a date/datetime, an ISO timestamp (naive stamps are the server's
    local time, as written by datetime.now()) or a date the estimator typed
    ('1/30/2026'). Falls back to the print date only when nothing is set.
    """
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, date):
        return _us_date(value)
    else:
        text = _clean(value)
        if not text:
            return _us_date(fallback)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            try:
                return _us_date(date.fromisoformat(text))
            except ValueError:
                return text
        try:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            for pattern in ("%m/%d/%Y", "%m/%d/%y"):
                try:
                    return _us_date(datetime.strptime(text, pattern))
                except ValueError:
                    continue
            return text
    try:
        if moment.tzinfo is None:
            moment = moment.astimezone()  # server-local naive stamp
        return _us_date(_to_denver(moment))
    except (OverflowError, OSError, ValueError):
        return _us_date(moment)


def _us_time(value: datetime) -> str:
    return value.strftime("%I:%M:%S %p").lstrip("0")


def _money_text(value) -> str:
    amount = money(value)
    return f"-${abs(amount):,.2f}" if amount < 0 else f"${amount:,.2f}"


def _clean(value) -> str:
    return "" if value is None else str(value).replace("\t", " ").strip()


def _city_line(city, state, zip_code) -> str:
    """JobRunner prints 'Denver,  CO  80223' (two spaces between parts)."""
    city, state, zip_code = _clean(city), _clean(state), _clean(zip_code)
    tail = "  ".join(part for part in (state, zip_code) if part)
    if city and tail:
        return f"{city},  {tail}"
    return city or tail


_QTY_LINE_RE = re.compile(r"^\s*installed\s+qty\s*:?\s*(-?[\d,]*\.?\d+)\s*(.*?)\s*$", re.IGNORECASE)
# The derived waterproofing / crack isolation bundles state their area as
# 'Net Area: 8915.29 SF'; on the customer PDF it reads like every other block.
_NET_AREA_LINE_RE = re.compile(r"^\s*net\s+area\s*:?\s*(-?[\d,]*\.?\d+)\s*(.*?)\s*$", re.IGNORECASE)
# Internal pail math ('Coverage: 275 SF/pail, 33 pails needed') is not printed.
_PAIL_COVERAGE_LINE_RE = re.compile(r"^\s*coverage\s*:.*\bpails?\s+needed\s*\.?\s*$", re.IGNORECASE)


def _quantity_line(line: str) -> Optional[str]:
    """Turn 'Installed QTY 7007.54 SF' (or 'Net Area: 7007.54 SF') into
    JobRunner's '7,008 SF Installed'."""
    match = _QTY_LINE_RE.match(line or "") or _NET_AREA_LINE_RE.match(line or "")
    if not match:
        return None
    try:
        qty = Decimal(match.group(1).replace(",", ""))
    except Exception:
        return None
    unit = match.group(2).strip()
    if qty != 0 and abs(qty) < 1:
        qty_text = f"{qty:,.2f}".rstrip("0").rstrip(".")
    else:
        qty_text = f"{int(qty.quantize(Decimal('1'), rounding=ROUND_HALF_UP)):,}"
    return " ".join(part for part in (qty_text, unit, "Installed") if part)


def _bundle_lines(bundle: dict) -> list[str]:
    """Name line, the bundle's own text lines, then the quantity line."""
    lines: list[str] = []
    name = _clean(bundle.get("bundle_name"))
    if name:
        lines.append(name)
    raw = str(bundle.get("description_text") or "").replace("\r\n", "\n").replace("\r", "\n")
    desc = [line.replace("\t", " ").rstrip() for line in raw.split("\n")]
    while desc and not desc[0].strip():
        desc.pop(0)
    while desc and not desc[-1].strip():
        desc.pop()
    for line in desc:
        if _PAIL_COVERAGE_LINE_RE.match(line):
            continue
        qty_line = _quantity_line(line)
        if qty_line:
            if lines and lines[-1].strip():
                lines.append("")
            lines.append(qty_line)
        elif not line.strip():
            if lines and lines[-1].strip():
                lines.append("")
        else:
            lines.append(line.strip())
    return lines


def _fit_text(text: str, font: str, size: float, max_width: float, min_size: float = 6.5):
    """Shrink (then trim) a single line so it fits a fixed-width header slot."""
    text = _clean(text)
    while size > min_size and stringWidth(text, font, size) > max_width:
        size -= 0.5
    if stringWidth(text, font, size) > max_width:
        while text and stringWidth(text + "…", font, size) > max_width:
            text = text[:-1]
        text = text.rstrip() + "…"
    return text, size


class _LinesBlock(Flowable):
    """Free-text lines at fixed JobRunner metrics, with an optional price above.

    A priced block is one flowable, so it never splits across pages (a block
    that does not fit moves whole to the next page). Only a block taller than
    a whole page, or a block marked splittable (the notes), is ever split.
    """

    def __init__(self, paragraphs=None, price: Optional[str] = None, *, font="Helvetica",
                 size=10.0, leading=13.0, para_gap=0.0, first_gap=13.55, price_gap=13.75,
                 rule=True, rule_gap=6.45, splittable=False, max_height=None, lines=None):
        super().__init__()
        self.paragraphs = list(paragraphs or [])
        self.price = price
        self.font = font
        self.size = size
        self.leading = leading
        self.para_gap = para_gap
        self.first_gap = first_gap
        self.price_gap = price_gap
        self.rule = rule
        self.rule_gap = rule_gap
        self.splittable = splittable
        self.max_height = max_height
        self._fixed_lines = lines  # pre-wrapped [(text, gap_before, starts_paragraph)]

    def _copy(self, lines, *, price, rule, first_gap):
        return _LinesBlock(
            price=price, font=self.font, size=self.size, leading=self.leading,
            para_gap=self.para_gap, first_gap=first_gap, price_gap=self.price_gap,
            rule=rule, rule_gap=self.rule_gap, splittable=self.splittable,
            max_height=self.max_height, lines=lines,
        )

    def _layout(self, width):
        if self._fixed_lines is not None:
            return list(self._fixed_lines)
        text_width = _TEXT_WRAP_W
        lines = []
        for index, paragraph in enumerate(self.paragraphs):
            text = str(paragraph or "")
            wrapped = simpleSplit(text, self.font, self.size, text_width) if text.strip() else [""]
            for sub, piece in enumerate(wrapped or [""]):
                gap = self.para_gap if (index > 0 and sub == 0) else 0.0
                lines.append((piece, gap, sub == 0))
        return lines

    def wrap(self, availWidth, availHeight):
        self._lines = self._layout(availWidth)
        baselines = []
        y = self.first_gap + (self.price_gap if self.price is not None else 0.0)
        for index, (_, gap, _) in enumerate(self._lines):
            if index:
                y += self.leading + gap
            baselines.append(y)
        self._baselines = baselines
        last = baselines[-1] if baselines else self.first_gap
        self.width = availWidth
        self.height = last + (self.rule_gap if self.rule else 4.0)
        return self.width, self.height

    def split(self, availWidth, availHeight):
        self.wrap(availWidth, availHeight)
        if not self.splittable and (self.max_height is None or self.height <= self.max_height):
            return []
        fit = sum(1 for baseline in self._baselines if baseline + 4.0 <= availHeight)
        if fit <= 0 or fit >= len(self._lines):
            return []
        cut = fit
        if self.splittable:
            # Prefer to break between paragraphs.
            starts = [i for i in range(1, fit + 1) if i < len(self._lines) and self._lines[i][2]]
            if starts:
                cut = starts[-1]
        head = self._lines[:cut]
        tail = [(text, 0.0 if i == 0 else gap, start)
                for i, (text, gap, start) in enumerate(self._lines[cut:])]
        return [
            self._copy(head, price=self.price, rule=False, first_gap=self.first_gap),
            self._copy(tail, price=None, rule=self.rule, first_gap=13.55),
        ]

    def draw(self):
        canv = self.canv
        top = self.height
        if self.price is not None:
            canv.setFillColor(colors.black)
            canv.setFont("Helvetica", 9)
            canv.drawRightString(573.0, top - self.first_gap, self.price)
        canv.setFillColor(colors.black)
        canv.setFont(self.font, self.size)
        for (text, _, _), baseline in zip(self._lines, self._baselines):
            if text:
                canv.drawString(1.8, top - baseline, text)
        if self.rule:
            canv.setStrokeColor(_SI_RULE_GRAY)
            canv.setLineWidth(0.75)
            canv.line(-0.2, 0.15, 573.0, 0.15)


class _TotalsBlock(Flowable):
    """Red 'Totals' heading, gray Grand Total box and the Deposit box.

    Offsets below are measured from the column bar's bottom edge. The frame
    starts _FRAME_TOP_OVERLAP above that edge, so every offset is shifted down
    by it; at the top of a page this leaves JobRunner's thin white gap between
    the bar and the blue rule (page 10 of quote 293113).
    """

    SHIFT = _FRAME_TOP_OVERLAP
    HEIGHT = 80.0 + SHIFT

    def __init__(self, grand_total_text: str):
        super().__init__()
        self.grand_total_text = grand_total_text

    def wrap(self, availWidth, availHeight):
        self.width = availWidth
        self.height = self.HEIGHT
        return self.width, self.height

    def draw(self):
        canv = self.canv
        top = self.height
        x0 = -_FRAME_X  # draw in page x coordinates

        def y(offset):
            return top - (offset + self.SHIFT)

        canv.saveState()
        canv.translate(x0, 0)
        # Blue rule (about 2pt, as in JobRunner) that opens the totals section.
        canv.setStrokeColor(_SI_BLUE)
        canv.setLineWidth(2.0)
        canv.line(20.0, y(1.9), 594.0, y(1.9))
        # 'Totals' heading, centered over the boxes.
        canv.setFillColor(_SI_RED)
        canv.setFont("Helvetica-Oblique", 10)
        canv.drawCentredString(485.5, y(16.8), "Totals")
        canv.setLineWidth(0.5)
        canv.setStrokeColor(colors.black)
        # Grand Total box with the inset amount box.
        canv.setFillColor(_SI_TOTAL_GRAY)
        canv.rect(380.3, y(44.7), 210.5, 19.5, stroke=1, fill=1)
        canv.setFillColor(colors.white)
        canv.rect(494.3, y(42.6), 94.5, 15.4, stroke=1, fill=1)
        canv.setFillColor(colors.black)
        canv.setFont("Helvetica", 12)
        canv.drawString(382.9, y(39.8), "Grand Total")
        amount, amount_size = _fit_text(self.grand_total_text, "Helvetica", 12, 90.0, 8.0)
        canv.setFont("Helvetica", amount_size)
        canv.drawRightString(586.8, y(39.8), amount)
        # Deposit box.
        canv.setFillColor(_SI_DEPOSIT_GRAY)
        canv.rect(380.3, y(77.7), 210.5, 29.6, stroke=1, fill=1)
        canv.setFillColor(colors.white)
        canv.rect(494.3, y(74.7), 94.5, 13.5, stroke=1, fill=1)
        canv.setFillColor(colors.black)
        canv.setFont("Helvetica", 9)
        canv.drawString(430.0, y(59.9), "Date")
        canv.drawString(468.5, y(59.9), "Ck #")
        canv.line(424.0, y(72.5), 453.2, y(72.5))
        canv.line(460.9, y(72.5), 490.1, y(72.5))
        canv.setFont("Helvetica", 10)
        canv.drawString(382.0, y(73.9), "Deposit")
        canv.restoreState()


class _AcceptanceBlock(Flowable):
    """'Date:' line, purchaser acceptance, signature line and Buyer/Seller line."""

    TOP = 26.9  # 'Date:' baseline below the top of the block

    def wrap(self, availWidth, availHeight):
        self.width = availWidth
        self.height = self.TOP + 118.0
        return self.width, self.height

    def draw(self):
        canv = self.canv
        top = self.height - self.TOP
        canv.setFillColor(colors.black)
        canv.setFont("Times-Italic", 10)
        canv.drawString(1.8, top, "Date:")
        canv.drawString(36.6, top, "_" * 43)
        canv.drawString(1.8, top - 24.0, "Purchasers Acceptance to this agreement:")
        canv.drawString(1.8, top - 48.0, "_" * 41)
        canv.drawString(1.8, top - 60.1, "Customer Signature")
        canv.setFont("Helvetica-Oblique", 8)
        canv.drawString(
            2.0, top - 114.1,
            "Buyer" + "_" * 39 + "Date" + "_" * 13 + "Seller" + "_" * 39 + "Date" + "_" * 12,
        )


class _EstimateDocTemplate(BaseDocTemplate):
    """Doc template carrying the header/footer data for every page."""

    def __init__(self, filename, header: dict, **kwargs):
        self.header = header
        super().__init__(filename, **kwargs)


def _draw_footer(canv, doc):
    header = doc.header
    canv.setFillColor(colors.black)
    canv.setFont("Helvetica", 9)
    baseline = _PAGE_H - 773.1
    canv.drawString(25.0, baseline, f"Page {canv.getPageNumber()}")
    canv.drawString(187.0, baseline, f"Quote # {header['quote_number']}")
    canv.drawRightString(520.0, baseline, header["print_date"])
    canv.drawRightString(586.1, baseline, header["print_time"])


def _draw_column_bar(canv, bar_top: float, total_offset: float):
    canv.setFillColor(_SI_BLUE)
    canv.rect(20.0, _PAGE_H - (bar_top + 25.1), 574.0, 25.1, stroke=0, fill=1)
    canv.setFillColor(colors.white)
    canv.setFont("Helvetica", 10)
    canv.drawCentredString(278.35, _PAGE_H - (bar_top + 16.4), "General Information / Description")
    canv.drawRightString(593.0, _PAGE_H - (bar_top + total_offset), "Total")


def _draw_first_page(canv, doc):
    header = doc.header
    canv.saveState()

    def y(top):
        return _PAGE_H - top

    # Logo (includes the AZ/NV license line) top-left.
    if os.path.exists(_LOGO_PATH):
        canv.drawImage(_LOGO_PATH, 32.04, y(125.04), width=216.0, height=108.0,
                       preserveAspectRatio=True, anchor="nw")
    else:
        canv.setFillColor(colors.black)
        canv.setFont("Helvetica-Bold", 22)
        canv.drawString(32.0, y(70.0), "STANDARD INTERIORS")

    # 'Estimate' title top-right.
    canv.setFillColor(_SI_BLUE)
    canv.setFont("Helvetica-Oblique", 20)
    canv.drawRightString(586.4, y(39.0), "Estimate")

    # Right-side stack of boxed fields.
    fields = [
        ("Quote #", header["quote_number"]),
        ("Customer PO", header["customer_po"]),
        ("Contract #", header["contract_number"]),
        ("Date", header["quote_date"]),
        ("Sales Person1", header["salesperson"]),
        ("Sales Person2", header["salesperson2"]),
    ]
    canv.setStrokeColor(colors.black)
    canv.setLineWidth(0.75)
    for index, (label, value) in enumerate(fields):
        step = 23.0 * index
        canv.setFillColor(colors.black)
        canv.setFont("Helvetica", 9)
        canv.drawString(520.0, y(86.9 + step), label)
        canv.rect(520.2, y(100.9 + step), 71.8, 12.7, stroke=1, fill=0)
        if value:
            text, size = _fit_text(value, "Helvetica", 9, 69.0)
            canv.setFillColor(_SI_BLUE)
            canv.setFont("Helvetica", size)
            canv.drawString(521.5, y(98.0 + step), text)

    # 'For:' bar (account #, customer phone and fax).
    canv.setFillColor(_SI_BLUE)
    canv.rect(20.0, y(153.0), 236.1, 25.0, stroke=0, fill=1)
    canv.rect(303.0, y(153.0), 205.1, 25.0, stroke=0, fill=1)
    canv.setFillColor(colors.white)
    acct, size = _fit_text(f"Acct # {header['customer_account']}".strip(), "Helvetica-Bold", 10, 196.0)
    canv.setFont("Helvetica-Bold", size)
    canv.drawString(55.9, y(137.65), acct)
    canv.setFont("Helvetica", 10)
    canv.drawString(21.8, y(149.85), "For:")
    phone_fax = "  ".join(part for part in (header["customer_phone"], "Fax", header["customer_fax"]) if part)
    phone_fax, size = _fit_text(phone_fax, "Helvetica-Bold", 10, 196.0)
    canv.setFont("Helvetica-Bold", size)
    canv.drawString(55.9, y(149.55), phone_fax)

    # 'Job Site:' bar (site phone).
    canv.setFont("Helvetica", 10)
    canv.drawString(304.9, y(148.75), "Job Site:")
    if header["site_phone"]:
        site_phone, size = _fit_text(header["site_phone"], "Helvetica-Bold", 10, 150.0)
        canv.setFont("Helvetica-Bold", size)
        canv.drawString(348.8, y(149.15), site_phone)

    # Customer block under the For: bar.
    canv.setFillColor(colors.black)
    for text, top in zip(header["customer_lines"], (175.05, 187.15, 199.05)):
        if text:
            fitted, size = _fit_text(text, "Helvetica-Bold", 10, 198.0)
            canv.setFont("Helvetica-Bold", size)
            canv.drawString(56.9, y(top), fitted)

    # Job site block under the Job Site bar.
    for text, top in zip(header["site_lines"], (177.25, 189.15, 201.15, 213.25)):
        if text:
            fitted, size = _fit_text(text, "Helvetica-Bold", 10, 212.0)
            canv.setFont("Helvetica-Bold", size)
            canv.drawString(304.0, y(top), fitted)

    _draw_column_bar(canv, _FIRST_BAR_BOTTOM - 25.1, 16.8)
    _draw_footer(canv, doc)
    canv.restoreState()


def _draw_later_page(canv, doc):
    header = doc.header
    canv.saveState()
    canv.setFillColor(colors.black)
    text, size = _fit_text(
        f"Continuation For:  {header['customer_name']},   Quote #  {header['quote_number']}",
        "Helvetica-Bold", 12, 572.0,
    )
    canv.setFont("Helvetica-Bold", size)
    canv.drawString(19.0, _PAGE_H - 30.2, text)
    _draw_column_bar(canv, _LATER_BAR_BOTTOM - 25.1, 17.9)
    _draw_footer(canv, doc)
    canv.restoreState()


class _TopPadded(Flowable):
    """A flowable with fixed space above it that is kept at the top of a page.

    ReportLab drops spaceBefore at the top of a frame, which would push legal
    text right against the blue bar; JobRunner keeps a gap there.
    """

    def __init__(self, inner, top: float):
        super().__init__()
        self.inner = inner
        self.top = top

    def wrap(self, availWidth, availHeight):
        _, inner_height = self.inner.wrap(availWidth, max(availHeight - self.top, 0))
        self.width = availWidth
        self.height = inner_height + self.top
        return self.width, self.height

    def split(self, availWidth, availHeight):
        parts = self.inner.split(availWidth, availHeight - self.top)
        if not parts:
            return []
        return [_TopPadded(part, self.top) for part in parts]

    def draw(self):
        self.inner.drawOn(self.canv, 0, 0)


def _legal_styles() -> dict:
    base = getSampleStyleSheet()["Normal"]
    return {
        "title": ParagraphStyle(
            "SITermsTitle", parent=base, fontName="Times-BoldItalic", fontSize=11,
            leading=13, leftIndent=2.0,
        ),
        "preamble": ParagraphStyle(
            "SITermsPreamble", parent=base, fontName="Times-BoldItalic", fontSize=10,
            leading=11, leftIndent=1.8, rightIndent=7.5,
        ),
        "clause": ParagraphStyle(
            "SITermsClause", parent=base, fontName="Times-Italic", fontSize=9, leading=10,
            leftIndent=1.8, rightIndent=5.0, firstLineIndent=35.0, bulletIndent=1.8,
            bulletFontName="Times-Italic", bulletFontSize=9,
        ),
        "heading": ParagraphStyle(
            "SISectionHeading", parent=base, fontName="Times-BoldItalic", fontSize=9,
            leading=10, leftIndent=1.8,
        ),
        "body": ParagraphStyle(
            "SIWarrantyBody", parent=base, fontName="Times-Italic", fontSize=9, leading=10,
            leftIndent=1.8, rightIndent=5.0,
        ),
    }


def _clause_markup(text: str) -> str:
    return escape(str(text or "")).replace("\n", "<br/>")


def _si_terms_markup(index: int, text: str) -> str:
    markup = _clause_markup(text)
    if index == 6:  # clause 7: bold sentence plus the T&M rate lines
        bold = escape(SI_FLOOR_PREP_BOLD)
        markup = markup.replace(bold, f"<font name='Times-BoldItalic'>{bold}</font>")
        markup += "<br/>" + "<br/>".join(escape(rate) for rate in SI_FLOOR_PREP_RATES)
    return markup


def _header_context(proposal_data: dict, quote_number: Optional[str], printed_at: datetime) -> dict:
    job_info = proposal_data.get("job_info") or {}

    def field(key):
        return _clean(job_info.get(key))

    quote = _clean(quote_number) or field("quote_number") or field("id")
    project_name = field("project_name")
    customer_name = field("gc_name") or project_name
    site_contact = field("site_contact")
    return {
        "quote_number": quote,
        "customer_po": field("customer_po"),
        "contract_number": field("contract_number"),
        "quote_date": _quote_date_text(job_info.get("quote_date"), printed_at),
        "salesperson": field("salesperson"),
        "salesperson2": field("salesperson2"),
        "customer_account": field("customer_account"),
        "customer_phone": field("customer_phone"),
        "customer_fax": field("customer_fax"),
        "site_phone": field("site_phone"),
        "customer_name": customer_name,
        "customer_lines": [
            customer_name,
            field("customer_address"),
            _city_line(job_info.get("customer_city"), job_info.get("customer_state"),
                       job_info.get("customer_zip")),
        ],
        "site_lines": [
            project_name,
            field("address"),
            _city_line(job_info.get("city"), job_info.get("state"), job_info.get("zip")),
            f"Contact: {site_contact}".strip(),
        ],
        "print_date": _us_date(printed_at),
        "print_time": _us_time(printed_at),
    }


def _tax_rate_sentence(tax_rate) -> str:
    rate = number(tax_rate)
    if rate <= 0:
        return ""
    pct = rate * 100 if rate < 1 else rate
    text = f"{pct:.3f}".rstrip("0")
    if len(text.split(".")[1]) < 2:
        text = f"{pct:.2f}"
    return f"Tax Rate is figured as {text}%"


def _clarification_lines(proposal_data: dict) -> list[str]:
    """Unheaded notes printed after the last line item and before the totals."""
    notes = [_clean(note) for note in (proposal_data.get("notes") or []) if _clean(note)]
    tax_sentence = _tax_rate_sentence(proposal_data.get("tax_rate"))
    if tax_sentence and not any("tax rate" in note.lower() for note in notes):
        notes.append(tax_sentence)
    job_info = proposal_data.get("job_info") or {}
    for line in job_info.get("excluded_at_this_time") or []:
        text = _clean(line)
        if not text:
            continue
        if text[-1] not in ".!?":
            text += "."
        if _norm_clause(text) not in {_norm_clause(note) for note in notes}:
            notes.append(text)
    return notes


def generate_proposal_pdf(
    proposal_data: dict,
    output_path: str,
    quote_number: str = None,
    generated_at: Optional[datetime] = None,
) -> str:
    """
    Generate the customer Estimate PDF in Standard Interiors' JobRunner layout.

    Args:
        proposal_data: dict with job_info, bundles, grand_total, tax_rate,
                       textura_amount, notes, terms, exclusions
        output_path: where to save the PDF
        quote_number: quote number override (defaults to job_info quote_number,
                      then the job id)
        generated_at: Denver wall-clock time to stamp (defaults to now)

    Returns:
        The output file path.
    """
    printed_at = generated_at or _denver_now()
    header = _header_context(proposal_data, quote_number, printed_at)

    doc = _EstimateDocTemplate(
        output_path,
        header=header,
        pagesize=letter,
        leftMargin=_FRAME_X,
        rightMargin=_PAGE_W - _FRAME_X - _FRAME_W,
        topMargin=_LATER_BAR_BOTTOM - _FRAME_TOP_OVERLAP,
        bottomMargin=_FRAME_BOTTOM,
        title=f"Estimate {header['quote_number']}".strip(),
        author="Standard Interiors",
        subject=header["site_lines"][0],
        creator="SI Bid Tool",
    )

    def frame(height, frame_id):
        return Frame(
            _FRAME_X, _FRAME_BOTTOM, _FRAME_W, height, id=frame_id,
            leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
        )

    doc.addPageTemplates([
        PageTemplate(id="first", frames=[frame(_FIRST_FRAME_H, "first")],
                     onPage=_draw_first_page, autoNextPageTemplate="later"),
        PageTemplate(id="later", frames=[frame(_LATER_FRAME_H, "later")],
                     onPage=_draw_later_page),
    ])

    story = []

    # ── Line items: price above each block, gray rule under it ──────────
    for bundle in proposal_data.get("bundles") or []:
        if not isinstance(bundle, dict):
            continue
        amount = effective_bundle_total(bundle)
        is_header = bool(bundle.get("is_header")) and amount == 0
        story.append(_LinesBlock(
            _bundle_lines(bundle) or [""],
            price=None if is_header else _money_text(amount),
            max_height=_LATER_FRAME_H,
        ))

    textura_amount = money(proposal_data.get("textura_amount"))
    if textura_amount:
        story.append(_LinesBlock(["Textura Fee"], price=_money_text(textura_amount),
                                 max_height=_LATER_FRAME_H))

    # ── Clarifications (unheaded) just before the totals ───────────────
    clarifications = _clarification_lines(proposal_data)
    if clarifications:
        story.append(_LinesBlock(
            clarifications, size=9.0, leading=12.0, para_gap=12.0,
            rule_gap=6.3, splittable=True, max_height=_LATER_FRAME_H,
        ))

    # ── Totals: Grand Total and Deposit boxes ────────────────────────────
    story.append(_TotalsBlock(_money_text(proposal_data.get("grand_total"))))

    # ── Terms and Conditions (the job's saved Terms list) ────────────────
    # Gaps (points of space above each item) follow the JobRunner print.
    styles = _legal_styles()
    story.append(_TopPadded(Paragraph(escape(SI_TERMS_TITLE), styles["title"]), 10.0))
    clause_number = 0
    for kind, markup in _printed_terms(proposal_data.get("terms")):
        if kind == "preamble":
            story.append(_TopPadded(Paragraph(markup, styles["preamble"]), 16.0))
            continue
        clause_number += 1
        story.append(_TopPadded(
            Paragraph(markup, styles["clause"], bulletText=f"{clause_number}."),
            12.0 if clause_number == 1 else 10.0,
        ))

    # ── Specific Exclusions (the job's list; standard list if never set) ─
    exclusions = proposal_data.get("exclusions")
    if exclusions is None:
        exclusions = SI_EXCLUSIONS
    exclusions = [_clean(item) for item in exclusions if _clean(item)]
    if exclusions:
        story.append(_TopPadded(Paragraph("Specific Exclusions", styles["heading"]), 21.0))
        for number_, item in enumerate(exclusions, 1):
            story.append(_TopPadded(
                Paragraph(_clause_markup(item), styles["clause"], bulletText=f"{number_}."),
                10.0,
            ))

    # ── Warranty and acceptance (kept on one page) ──────────────────────
    closing = [_TopPadded(Paragraph("Warranty", styles["heading"]), 21.0)]
    closing += [
        _TopPadded(Paragraph(escape(paragraph), styles["body"]), 22.0 if index == 0 else 10.0)
        for index, paragraph in enumerate(SI_WARRANTY)
    ]
    closing.append(_AcceptanceBlock())
    story.append(KeepTogether(closing))

    doc.build(story)
    return output_path
