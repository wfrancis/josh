"""
Generate a professional bid PDF using reportlab.
US Letter size, Standard Interiors branding.
"""

import os
from datetime import date
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
            f"Tax ({bid_data['tax_rate'] * 100:.1f}%):",
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
