"""
AI-powered email agent for composing and sending vendor quote requests.
Uses existing OpenAI integration from quote_parser.py.
"""

import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

from ai_client import chat_complete


def compose_quote_request(
    job: dict,
    materials: list[dict],
    openai_config: dict,
    sender_name: str = "",
    sender_signature: str = ""
) -> str:
    """Use OpenAI to compose a professional quote request email.

    Args:
        job: Job dict with project_name, gc_name, architect, designer, address, city, state, zip
        materials: List of material dicts needing quotes (item_code, description, installed_qty, unit)
        openai_config: Dict with api_key, model
        sender_name: Estimator's name
        sender_signature: Company signature block

    Returns:
        Formatted email body text
    """
    # Build material list for the prompt
    material_lines = []
    for m in materials:
        item = m.get("item_code", "")
        desc = m.get("description", "")
        qty = m.get("installed_qty", 0) or m.get("order_qty", 0)
        unit = m.get("unit", "")
        parts = [p for p in [item, desc] if p]
        line = " - ".join(parts)
        if qty:
            line += f" ({qty} {unit})"
        material_lines.append(line)

    material_text = "\n".join(f"  - {line}" for line in material_lines)

    # Build project context
    project_details = [f"Project: {job.get('project_name', 'Unknown')}"]
    if job.get("gc_name"):
        project_details.append(f"General Contractor: {job['gc_name']}")
    if job.get("architect"):
        project_details.append(f"Architect: {job['architect']}")
    if job.get("designer"):
        project_details.append(f"Designer: {job['designer']}")
    location_parts = [
        p for p in [job.get("address"), job.get("city"), job.get("state"), job.get("zip")] if p
    ]
    if location_parts:
        project_details.append(f"Location: {', '.join(location_parts)}")

    project_text = "\n".join(project_details)

    system_prompt = (
        "You are a professional flooring estimator composing a quote request email to a vendor/supplier. "
        "Write a concise, professional email requesting pricing on the listed materials. "
        "The tone should be businesslike but friendly — this is a routine industry email. "
        "Include all project details and the full materials list with quantities. "
        "Ask for unit pricing, freight/shipping costs, and lead times. "
        "Do NOT include a subject line — just the email body. "
        "Do NOT include placeholder brackets like [Your Name] — if sender info is provided, use it. "
        "If no sender name is provided, end with a simple 'Thank you' without a name. "
        "Keep it under 200 words. Return ONLY the email body text, no JSON wrapping."
    )

    user_prompt = (
        f"Compose a quote request email with the following details:\n\n"
        f"Project Details:\n{project_text}\n\n"
        f"Materials Needed:\n{material_text}\n"
    )
    if sender_name:
        user_prompt += f"\nSender Name: {sender_name}"

    api_key = openai_config.get("api_key")
    model = openai_config.get("model", "gpt-5-mini")

    body = chat_complete(
        system=system_prompt,
        user=user_prompt,
        api_key=api_key,
        model=model,
    ).strip()

    # Append signature if provided
    if sender_signature:
        body += f"\n\n{sender_signature}"

    return body


def send_email(
    to_email: str,
    subject: str,
    body: str,
    smtp_config: dict,
    from_email: str = None,
    from_name: str = None,
) -> bool:
    """Send an email via SMTP.

    Args:
        to_email: Recipient email
        subject: Email subject line
        body: Email body (plain text)
        smtp_config: Dict with host, port, username, password, use_tls
        from_email: Sender email (defaults to smtp_config username)
        from_name: Sender display name

    Returns:
        True if sent successfully

    Raises:
        Exception on SMTP errors
    """
    sender = from_email or smtp_config.get("username", "")
    if not sender:
        raise ValueError("No sender email: provide from_email or smtp_config.username")

    msg = MIMEMultipart()
    if from_name:
        msg["From"] = f"{from_name} <{sender}>"
    else:
        msg["From"] = sender
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    host = smtp_config.get("host", "")
    port = int(smtp_config.get("port", 587))
    username = smtp_config.get("username", "")
    password = smtp_config.get("password", "")
    use_tls = smtp_config.get("use_tls", True)

    if not host:
        raise ValueError("SMTP host is required")

    if port == 465:
        # SSL from the start
        server = smtplib.SMTP_SSL(host, port, timeout=30)
    else:
        server = smtplib.SMTP(host, port, timeout=30)
        server.ehlo()
        if use_tls:
            server.starttls()
            server.ehlo()

    try:
        if username and password:
            server.login(username, password)
        server.sendmail(sender, [to_email], msg.as_string())
    finally:
        server.quit()

    return True


def generate_quote_request_text(job: dict, materials: list[dict]) -> str:
    """Generate a simple formatted quote request text (no AI needed).
    Used as fallback or for copy-to-clipboard mode.

    Returns plain text that estimator can copy/paste into email.
    """
    lines = []
    lines.append(f"Project: {job.get('project_name', '')}")
    if job.get("architect"):
        lines.append(f"Architect: {job['architect']}")
    if job.get("designer"):
        lines.append(f"Designer: {job['designer']}")
    location_parts = [
        p for p in [job.get("address"), job.get("city"), job.get("state"), job.get("zip")] if p
    ]
    if location_parts:
        lines.append(f"Location: {', '.join(location_parts)}")
    if job.get("gc_name"):
        lines.append(f"GC: {job['gc_name']}")

    lines.append("")
    lines.append("We are bidding the above project and need pricing on the following materials:")
    lines.append("")

    for m in materials:
        item = m.get("item_code", "")
        desc = m.get("description", "")
        qty = m.get("installed_qty", 0) or m.get("order_qty", 0)
        unit = m.get("unit", "")
        parts = [p for p in [item, desc] if p]
        line = " - ".join(parts)
        if qty:
            line += f" — {round(qty, 2)} {unit}"
        lines.append(f"• {line}")

    lines.append("")
    lines.append("Please include unit pricing, freight, and lead times.")
    lines.append("Thank you!")

    return "\n".join(lines)
