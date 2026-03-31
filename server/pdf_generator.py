"""
Generate professional bid and proposal PDFs using reportlab.
US Letter size, Standard Interiors branding.
"""

import os
from datetime import date, datetime
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
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
    Frame,
    PageTemplate,
)
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER


COMPANY_NAME = "STANDARD INTERIORS"
COMPANY_ADDRESS = "1050 W HAMPDEN AVE, STE 300 ENGLEWOOD, CO 80110"

TERMS_TEXT = (
    "Payment terms: Net 30 from invoice date. "
    "Pricing is valid for 30 days from quote date. "
    "Material pricing subject to change based on vendor availability. "
    "Change orders will be priced separately. "
    "Standard Interiors is not responsible for pre-existing substrate conditions."
)

# Colors used across proposal PDF
_DARK_BLUE = colors.HexColor("#1a1a2e")
_HEADER_BG = colors.HexColor("#2c3e6b")
_LIGHT_GRAY = colors.HexColor("#f5f5f5")
_MED_GRAY = colors.HexColor("#cccccc")
_TEXT_GRAY = colors.HexColor("#555555")
_WHITE = colors.white


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
# Proposal PDF (Standard Interiors reference format)
# ─────────────────────────────────────────────────────────────────────────────

def _proposal_styles() -> dict:
    """Build paragraph styles for the proposal PDF."""
    base = getSampleStyleSheet()
    s = {}

    s["company_name"] = ParagraphStyle(
        "PropCompanyName",
        parent=base["Normal"],
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=16,
        textColor=_DARK_BLUE,
    )
    s["header_bar_text"] = ParagraphStyle(
        "PropHeaderBar",
        parent=base["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=12,
        textColor=_WHITE,
    )
    s["header_bar_total"] = ParagraphStyle(
        "PropHeaderBarTotal",
        parent=base["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=12,
        textColor=_WHITE,
        alignment=TA_RIGHT,
    )
    s["label"] = ParagraphStyle(
        "PropLabel",
        parent=base["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=colors.black,
    )
    s["value"] = ParagraphStyle(
        "PropValue",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        textColor=colors.black,
    )
    s["bundle_name"] = ParagraphStyle(
        "PropBundleName",
        parent=base["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        textColor=colors.black,
    )
    s["bundle_desc"] = ParagraphStyle(
        "PropBundleDesc",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=11,
        textColor=colors.black,
    )
    s["bundle_price"] = ParagraphStyle(
        "PropBundlePrice",
        parent=base["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        alignment=TA_RIGHT,
        textColor=colors.black,
    )
    s["total_label"] = ParagraphStyle(
        "PropTotalLabel",
        parent=base["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=14,
        alignment=TA_RIGHT,
    )
    s["total_value"] = ParagraphStyle(
        "PropTotalValue",
        parent=base["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=14,
        alignment=TA_RIGHT,
    )
    s["section_heading"] = ParagraphStyle(
        "PropSectionHeading",
        parent=base["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=14,
        spaceBefore=8,
        spaceAfter=4,
        textColor=_DARK_BLUE,
    )
    s["notes_body"] = ParagraphStyle(
        "PropNotesBody",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=11,
        textColor=colors.black,
    )
    s["notes_bold"] = ParagraphStyle(
        "PropNotesBold",
        parent=base["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=11,
        textColor=colors.black,
    )
    s["continuation_text"] = ParagraphStyle(
        "PropContinuation",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        textColor=colors.black,
    )
    s["sig_label"] = ParagraphStyle(
        "PropSigLabel",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
    )
    s["sig_bold"] = ParagraphStyle(
        "PropSigBold",
        parent=base["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=14,
    )
    s["footer_text"] = ParagraphStyle(
        "PropFooter",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=7,
        leading=9,
        textColor=_TEXT_GRAY,
    )
    return s


class _ProposalDocTemplate(BaseDocTemplate):
    """Custom doc template that tracks proposal metadata for headers/footers."""

    def __init__(self, filename, quote_number, project_name, **kwargs):
        self.quote_number = quote_number
        self.project_name = project_name
        self._is_first_page = True
        super().__init__(filename, **kwargs)

    def afterPage(self):
        """Called after each page is rendered."""
        self._is_first_page = False


def _proposal_footer(canvas, doc):
    """Draw the footer on every page of the proposal."""
    canvas.saveState()
    page_w, page_h = letter
    y = 0.4 * inch

    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(_TEXT_GRAY)

    now = datetime.now()
    date_str = now.strftime("%m/%d/%Y %I:%M %p")

    # Left: Quote #
    canvas.drawString(0.6 * inch, y, f"Quote # {doc.quote_number}")

    # Center: Date/time
    canvas.drawCentredString(page_w / 2, y, date_str)

    # Right: Page number
    page_num = canvas.getPageNumber()
    canvas.drawRightString(page_w - 0.6 * inch, y, f"Page {page_num}")

    # Thin line above footer
    canvas.setStrokeColor(_MED_GRAY)
    canvas.setLineWidth(0.5)
    canvas.line(0.6 * inch, y + 10, page_w - 0.6 * inch, y + 10)

    canvas.restoreState()


def _build_header_bar(styles, page_width):
    """Build the dark 'General Information / Description ... Total' header bar."""
    left_text = Paragraph("General Information / Description", styles["header_bar_text"])
    right_text = Paragraph("Total", styles["header_bar_total"])

    usable = page_width - 1.2 * inch  # account for margins
    bar_table = Table(
        [[left_text, right_text]],
        colWidths=[usable - 1.2 * inch, 1.2 * inch],
        rowHeights=[20],
    )
    bar_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _HEADER_BG),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 6),
        ("RIGHTPADDING", (-1, -1), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return bar_table


def _build_continuation_header(styles, project_name, quote_number, page_width):
    """Build the smaller continuation header for pages 2+."""
    usable = page_width - 1.2 * inch
    bar = _build_header_bar(styles, page_width)

    cont_text = Paragraph(
        f"Continuation For: {project_name}, Quote # {quote_number}",
        styles["continuation_text"],
    )
    return [bar, Spacer(1, 2), cont_text, Spacer(1, 6)]


def generate_proposal_pdf(
    proposal_data: dict,
    output_path: str,
    quote_number: str = None,
) -> str:
    """
    Generate a proposal PDF in the Standard Interiors reference format.

    Args:
        proposal_data: dict with job_info, bundles, subtotal, tax_rate,
                       tax_amount, grand_total, notes, terms, exclusions
        output_path: where to save the PDF
        quote_number: quote reference number

    Returns:
        The output file path.
    """
    styles = _proposal_styles()
    job_info = proposal_data.get("job_info", {})
    page_w, page_h = letter

    q_num = quote_number or "Q-000"
    project_name = job_info.get("project_name", "")
    today_str = date.today().strftime("%m/%d/%Y")

    doc = _ProposalDocTemplate(
        output_path,
        quote_number=q_num,
        project_name=project_name,
        pagesize=letter,
        topMargin=0.6 * inch,
        bottomMargin=0.65 * inch,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
    )

    frame = Frame(
        0.6 * inch, 0.65 * inch,
        page_w - 1.2 * inch, page_h - 1.25 * inch,
        id="main",
    )
    doc.addPageTemplates([
        PageTemplate(id="all_pages", frames=[frame], onPage=_proposal_footer),
    ])

    story = []
    usable_width = page_w - 1.2 * inch

    # ── Page 1: Company header ────────────────────────────────────────────
    story.append(Paragraph(COMPANY_NAME, styles["company_name"]))
    story.append(Spacer(1, 2))
    story.append(HRFlowable(
        width="100%", thickness=1.5,
        color=_DARK_BLUE, spaceAfter=8,
    ))

    # ── Header bar ────────────────────────────────────────────────────────
    story.append(_build_header_bar(styles, page_w))
    story.append(Spacer(1, 6))

    # ── GC info (left) + Quote metadata (right) ──────────────────────────
    gc_name = job_info.get("gc_name", "")
    gc_address = job_info.get("gc_address", "")
    gc_city_state_zip = job_info.get("gc_city_state_zip", "")
    gc_phone = job_info.get("gc_phone", "")
    gc_contact = job_info.get("gc_contact", "")

    # Build job site address
    site_parts = [
        job_info.get("address", ""),
    ]
    city_state_zip = ", ".join(filter(None, [
        job_info.get("city", ""),
        job_info.get("state", ""),
    ]))
    if job_info.get("zip"):
        city_state_zip += f" {job_info['zip']}"
    site_parts.append(city_state_zip)

    # Left column: GC info block + Job site block
    left_rows = []

    # GC block
    if gc_name:
        left_rows.append(
            [Paragraph("<b>GC:</b>", styles["label"]),
             Paragraph(gc_name, styles["value"])]
        )
    if gc_address:
        left_rows.append(
            [Paragraph("", styles["label"]),
             Paragraph(gc_address, styles["value"])]
        )
    if gc_city_state_zip:
        left_rows.append(
            [Paragraph("", styles["label"]),
             Paragraph(gc_city_state_zip, styles["value"])]
        )
    if gc_phone:
        left_rows.append(
            [Paragraph("<b>Phone:</b>", styles["label"]),
             Paragraph(gc_phone, styles["value"])]
        )
    if gc_contact:
        left_rows.append(
            [Paragraph("<b>Contact:</b>", styles["label"]),
             Paragraph(gc_contact, styles["value"])]
        )

    # Spacer row between GC and job site
    left_rows.append([Paragraph("", styles["label"]), Paragraph("", styles["value"])])

    # Job site block
    left_rows.append(
        [Paragraph("<b>Job Site:</b>", styles["label"]),
         Paragraph(project_name, styles["value"])]
    )
    if job_info.get("address"):
        left_rows.append(
            [Paragraph("", styles["label"]),
             Paragraph(job_info["address"], styles["value"])]
        )
    if city_state_zip.strip():
        left_rows.append(
            [Paragraph("", styles["label"]),
             Paragraph(city_state_zip.strip(), styles["value"])]
        )

    left_table = Table(
        left_rows,
        colWidths=[0.6 * inch, 2.8 * inch],
    )
    left_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
    ]))

    # Right column: Quote metadata
    salesperson = job_info.get("salesperson", "")
    right_rows = [
        [Paragraph("<b>Quote #:</b>", styles["label"]),
         Paragraph(q_num, styles["value"])],
        [Paragraph("<b>Date:</b>", styles["label"]),
         Paragraph(today_str, styles["value"])],
        [Paragraph("<b>Sales Person:</b>", styles["label"]),
         Paragraph(salesperson, styles["value"])],
    ]

    right_table = Table(
        right_rows,
        colWidths=[0.9 * inch, 1.8 * inch],
    )
    right_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
    ]))

    # Combine left and right into a two-column layout
    info_row = Table(
        [[left_table, right_table]],
        colWidths=[usable_width * 0.55, usable_width * 0.45],
    )
    info_row.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(info_row)
    story.append(Spacer(1, 8))
    story.append(HRFlowable(
        width="100%", thickness=0.5,
        color=_MED_GRAY, spaceAfter=8,
    ))

    # ── Bundle line items ─────────────────────────────────────────────────
    bundles = proposal_data.get("bundles", [])
    desc_col_width = usable_width - 1.3 * inch
    price_col_width = 1.3 * inch

    for i, bundle in enumerate(bundles):
        bundle_name = bundle.get("bundle_name", "")
        desc_text = bundle.get("description_text", "")
        total_price = bundle.get("total_price", 0)

        # Format description: each line on its own line
        desc_lines = desc_text.strip().split("\n")
        desc_html = "<br/>".join(line.strip() for line in desc_lines if line.strip())

        # Bundle name + price row
        name_para = Paragraph(f"<b>{bundle_name}</b>", styles["bundle_name"])
        price_para = Paragraph(f"${total_price:,.2f}", styles["bundle_price"])

        # Description below the name
        desc_para = Paragraph(desc_html, styles["bundle_desc"])

        # Build a mini-table: row 1 = name + price, row 2 = description spanning
        bundle_table = Table(
            [
                [name_para, price_para],
                [desc_para, ""],
            ],
            colWidths=[desc_col_width, price_col_width],
        )
        bundle_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("SPAN", (0, 1), (1, 1)),
            ("TOPPADDING", (0, 0), (-1, 0), 4),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 1),
            ("TOPPADDING", (0, 1), (-1, 1), 1),
            ("BOTTOMPADDING", (0, 1), (-1, 1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))

        story.append(bundle_table)

        # Light separator between bundles
        if i < len(bundles) - 1:
            story.append(HRFlowable(
                width="100%", thickness=0.3,
                color=_MED_GRAY, spaceAfter=2, spaceBefore=2,
            ))

    # ── Totals section ────────────────────────────────────────────────────
    story.append(Spacer(1, 6))
    story.append(HRFlowable(
        width="100%", thickness=1,
        color=_DARK_BLUE, spaceAfter=6,
    ))

    subtotal = proposal_data.get("subtotal", 0)
    tax_rate = proposal_data.get("tax_rate", 0)
    tax_amount = proposal_data.get("tax_amount", 0)
    grand_total = proposal_data.get("grand_total", 0)

    totals_rows = [
        [Paragraph("<b>Subtotal:</b>", styles["total_label"]),
         Paragraph(f"${subtotal:,.2f}", styles["total_value"])],
    ]

    if tax_rate and tax_rate > 0:
        tax_pct = tax_rate * 100 if tax_rate < 1 else tax_rate
        totals_rows.append([
            Paragraph(f"<b>Tax ({tax_pct:.2f}%):</b>", styles["total_label"]),
            Paragraph(f"${tax_amount:,.2f}", styles["total_value"]),
        ])

    textura_fee = proposal_data.get("textura_fee", 0)
    textura_amount = proposal_data.get("textura_amount", 0)
    if textura_fee and textura_amount:
        totals_rows.append([
            Paragraph("<b>Textura Fee (0.22%):</b>", styles["total_label"]),
            Paragraph(f"${textura_amount:,.2f}", styles["total_value"]),
        ])

    totals_rows.append([
        Paragraph("<b>Grand Total:</b>", styles["total_label"]),
        Paragraph(f"<b>${grand_total:,.2f}</b>", styles["total_value"]),
    ])

    totals_table = Table(
        totals_rows,
        colWidths=[usable_width - 1.5 * inch, 1.5 * inch],
    )
    totals_style_cmds = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    # Highlight grand total row
    last_idx = len(totals_rows) - 1
    totals_style_cmds.append(
        ("LINEABOVE", (0, last_idx), (-1, last_idx), 0.5, _DARK_BLUE)
    )
    totals_table.setStyle(TableStyle(totals_style_cmds))
    story.append(totals_table)

    # ── Notes / Qualifications page ───────────────────────────────────────
    notes = proposal_data.get("notes", [])
    terms = proposal_data.get("terms", [])
    exclusions = proposal_data.get("exclusions", [])

    if notes or terms or exclusions:
        story.append(PageBreak())

        # Continuation header
        for elem in _build_continuation_header(styles, project_name, q_num, page_w):
            story.append(elem)

        # Notes
        if notes:
            story.append(Paragraph("<b>Notes / Qualifications:</b>", styles["section_heading"]))
            for note in notes:
                story.append(Paragraph(f"&bull; {note}", styles["notes_body"]))
                story.append(Spacer(1, 2))
            story.append(Spacer(1, 8))

        # Terms & Conditions
        if terms:
            story.append(Paragraph("<b>Terms &amp; Conditions:</b>", styles["section_heading"]))
            for idx, term in enumerate(terms, 1):
                story.append(Paragraph(f"{idx}. {term}", styles["notes_body"]))
                story.append(Spacer(1, 1))
            story.append(Spacer(1, 8))

        # Exclusions
        if exclusions:
            story.append(Paragraph("<b>Specific Exclusions:</b>", styles["section_heading"]))
            for idx, exc in enumerate(exclusions, 1):
                story.append(Paragraph(f"{idx}. {exc}", styles["notes_body"]))
                story.append(Spacer(1, 1))
            story.append(Spacer(1, 8))

        # Warranty section
        story.append(Paragraph("<b>Warranty:</b>", styles["section_heading"]))
        story.append(Paragraph(
            "Standard Interiors warrants all workmanship for a period of one (1) year "
            "from the date of substantial completion. Manufacturer warranties on materials "
            "are passed through to the purchaser per manufacturer terms. Standard Interiors "
            "makes no warranty, express or implied, beyond the manufacturer's warranty on "
            "materials furnished under this agreement.",
            styles["notes_body"],
        ))

    # ── Signature page ────────────────────────────────────────────────────
    story.append(PageBreak())

    # Continuation header on signature page
    for elem in _build_continuation_header(styles, project_name, q_num, page_w):
        story.append(elem)

    story.append(Spacer(1, 24))
    story.append(Paragraph(
        "<b>Purchasers Acceptance to this agreement:</b>",
        styles["sig_bold"],
    ))
    story.append(Spacer(1, 30))

    # Signature lines
    line_width = usable_width * 0.42
    sig_spacer = usable_width * 0.08
    date_width = usable_width * 0.25

    # Customer Signature line
    story.append(Paragraph("Customer Signature:", styles["sig_label"]))
    story.append(Spacer(1, 4))
    story.append(HRFlowable(
        width="60%", thickness=0.5,
        color=colors.black, spaceAfter=20,
    ))

    # Buyer / Date row
    buyer_date_data = [
        [
            Paragraph("Buyer:", styles["sig_label"]),
            Paragraph("_" * 50, styles["sig_label"]),
            Paragraph("Date:", styles["sig_label"]),
            Paragraph("_" * 25, styles["sig_label"]),
        ],
    ]
    buyer_date_table = Table(
        buyer_date_data,
        colWidths=[0.6 * inch, 3.0 * inch, 0.5 * inch, 2.0 * inch],
    )
    buyer_date_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(buyer_date_table)
    story.append(Spacer(1, 16))

    # Seller / Date row
    seller_date_data = [
        [
            Paragraph("Seller:", styles["sig_label"]),
            Paragraph("_" * 50, styles["sig_label"]),
            Paragraph("Date:", styles["sig_label"]),
            Paragraph("_" * 25, styles["sig_label"]),
        ],
    ]
    seller_date_table = Table(
        seller_date_data,
        colWidths=[0.6 * inch, 3.0 * inch, 0.5 * inch, 2.0 * inch],
    )
    seller_date_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(seller_date_table)

    story.append(Spacer(1, 40))
    story.append(Paragraph(
        f"<b>{COMPANY_NAME}</b>",
        styles["company_name"],
    ))
    story.append(Paragraph(COMPANY_ADDRESS, styles["notes_body"]))

    # ── Build PDF ─────────────────────────────────────────────────────────
    doc.build(story)
    return output_path
