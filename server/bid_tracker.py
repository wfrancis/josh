"""
Bid tracker rules: the bid statuses, input checks, and the due-date and
follow-up flags shown on the Bid Tracker page.

Pure functions only. The database work is in models.py and the endpoints are
in main.py. Dates are plain calendar dates (YYYY-MM-DD); "today" comes from
the person's browser so "overdue" matches their own calendar, not the
server's time zone.
"""

import re
from datetime import date, timedelta

BID_STATUSES: tuple[str, ...] = (
    "Not started",
    "Estimating",
    "Ready to send",
    "Sent",
    "Won",
    "Lost",
    "No bid",
)
OPEN_BID_STATUSES = frozenset({"Not started", "Estimating", "Ready to send"})
DECIDED_BID_STATUSES = frozenset({"Won", "Lost"})
CLOSED_BID_STATUSES = frozenset({"Won", "Lost", "No bid"})

# Events people add by hand; status_change is written by the tracker itself.
BID_EVENT_TYPES: tuple[str, ...] = ("status_change", "sent", "follow_up", "note", "won", "lost")
POSTABLE_BID_EVENT_TYPES: tuple[str, ...] = ("sent", "follow_up", "note", "won", "lost")

DUE_SOON_DAYS = 2          # amber when the due date is today or within this many days
MAX_FUTURE_SENT_DAYS = 1   # allow one day of time-zone slack on "sent on"

MAX_NOTE_LENGTH = 2000
MAX_SHORT_TEXT_LENGTH = 200
MAX_REASON_LENGTH = 500
MAX_SENT_TO_LENGTH = 500

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)(:[0-5]\d)?$")

_STATUS_BY_KEY = {status.lower(): status for status in BID_STATUSES}

FIELD_LABELS = {
    "bid_status": "Status",
    "bid_due_date": "Due date",
    "bid_due_time": "Due time",
    "estimator": "Estimator",
    "next_follow_up_date": "Next follow-up",
    "won_lost_reason": "Reason",
    "awarded_amount": "Awarded amount",
}


def effective_bid_status(stored: str | None, material_count: int | None) -> tuple[str, bool]:
    """Return (status, is_default). Untracked jobs show "Estimating" once they have materials."""
    if stored in BID_STATUSES:
        return stored, False
    return ("Estimating" if (material_count or 0) > 0 else "Not started"), True


def parse_status(value) -> str:
    key = str(value or "").strip().lower()
    if key not in _STATUS_BY_KEY:
        raise ValueError(f"Status must be one of: {', '.join(BID_STATUSES)}.")
    return _STATUS_BY_KEY[key]


def parse_date(value, label: str) -> str | None:
    """Blank clears the date; otherwise it must be a real YYYY-MM-DD date."""
    text = str(value or "").strip()
    if not text:
        return None
    if _DATE_RE.match(text):
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError:
            pass
    raise ValueError(f"{label} must be a date like 2026-10-01.")


def parse_time(value, label: str) -> str | None:
    """Blank clears the time; otherwise 24-hour HH:MM (what a time picker sends)."""
    text = str(value or "").strip()
    if not text:
        return None
    match = _TIME_RE.match(text)
    if not match:
        raise ValueError(f"{label} must be a time like 14:00.")
    return f"{match.group(1)}:{match.group(2)}"


def parse_money(value, label: str) -> float | None:
    """Blank clears the amount; accepts 125000, "125,000" or "$125,000.50"."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a dollar amount.")
    if isinstance(value, (int, float)):
        amount = float(value)
    else:
        text = str(value).strip().replace("$", "").replace(",", "")
        if not text:
            return None
        try:
            amount = float(text)
        except ValueError:
            raise ValueError(f"{label} must be a dollar amount.") from None
    if amount != amount or amount < 0 or amount > 1e10:  # NaN, negative, absurd
        raise ValueError(f"{label} must be a dollar amount of zero or more.")
    return round(amount, 2)


def clean_text(value, max_length: int, label: str) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) > max_length:
        raise ValueError(f"{label} is too long (keep it under {max_length} characters).")
    return text


def clean_sent_to(value) -> str | None:
    """Names or emails the bid went to, as one comma-separated line."""
    if isinstance(value, (list, tuple)):
        value = ", ".join(str(part).strip() for part in value if str(part or "").strip())
    return clean_text(value, MAX_SENT_TO_LENGTH, "Sent to")


def resolve_today(value) -> date:
    """The person's local date if their browser sent one, else the server's date."""
    try:
        parsed = parse_date(value, "Today")
    except ValueError:
        parsed = None
    if parsed:
        candidate = date.fromisoformat(parsed)
        # Ignore a clock that is wildly off rather than trusting it.
        if abs((candidate - date.today()).days) <= 2:
            return candidate
    return date.today()


def clean_tracking_fields(values: dict) -> dict:
    """Check the editable tracking fields that were sent; returns column -> clean value."""
    cleaned: dict = {}
    if "bid_status" in values:
        cleaned["bid_status"] = parse_status(values["bid_status"])
    if "bid_due_date" in values:
        cleaned["bid_due_date"] = parse_date(values["bid_due_date"], FIELD_LABELS["bid_due_date"])
    if "bid_due_time" in values:
        cleaned["bid_due_time"] = parse_time(values["bid_due_time"], FIELD_LABELS["bid_due_time"])
    if "estimator" in values:
        cleaned["estimator"] = clean_text(values["estimator"], MAX_SHORT_TEXT_LENGTH, FIELD_LABELS["estimator"])
    if "next_follow_up_date" in values:
        cleaned["next_follow_up_date"] = parse_date(values["next_follow_up_date"], FIELD_LABELS["next_follow_up_date"])
    if "won_lost_reason" in values:
        cleaned["won_lost_reason"] = clean_text(values["won_lost_reason"], MAX_REASON_LENGTH, FIELD_LABELS["won_lost_reason"])
    if "awarded_amount" in values:
        cleaned["awarded_amount"] = parse_money(values["awarded_amount"], FIELD_LABELS["awarded_amount"])
    return cleaned


def status_change_updates(old_status: str, new_status: str, today: date, explicit: dict) -> dict:
    """Fields that follow from a status change. Values the person typed (explicit) win.

    - Won/Lost stamps won_lost_at with today; switching between them clears
      the old reason and amount.
    - Moving out of Won/Lost clears won_lost_at, reason and amount.
    - A closed bid (Won/Lost/No bid) needs no follow-up, so that date clears.
    """
    updates: dict = {}
    if new_status == old_status:
        return updates
    if new_status in DECIDED_BID_STATUSES:
        updates["won_lost_at"] = today.isoformat()
        if old_status in DECIDED_BID_STATUSES:
            updates["won_lost_reason"] = None
            updates["awarded_amount"] = None
    elif old_status in DECIDED_BID_STATUSES:
        updates.update(won_lost_at=None, won_lost_reason=None, awarded_amount=None)
    if new_status in CLOSED_BID_STATUSES:
        updates["next_follow_up_date"] = None
    return {key: value for key, value in updates.items() if key not in explicit}


def _as_date(value) -> date | None:
    text = str(value or "").strip()[:10]
    if not _DATE_RE.match(text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def decorate_bid_row(row: dict, today: date) -> dict:
    """Add the effective status and the overdue / due-soon / follow-up flags to a tracker row."""
    status, is_default = effective_bid_status(row.get("bid_status"), row.get("material_count"))
    due = _as_date(row.get("bid_due_date"))
    follow_up = _as_date(row.get("next_follow_up_date"))
    sent = _as_date(row.get("last_sent_date"))
    is_open = status in OPEN_BID_STATUSES
    days_until_due = (due - today).days if due else None
    follow_up_active = bool(follow_up) and status not in CLOSED_BID_STATUSES

    item = dict(row)
    item.update({
        "bid_status": status,
        "bid_status_is_default": is_default,
        "is_open": is_open,
        "days_until_due": days_until_due,
        "due_overdue": bool(is_open and due and due < today),
        "due_soon": bool(is_open and due and 0 <= days_until_due <= DUE_SOON_DAYS),
        "follow_up_overdue": bool(follow_up_active and follow_up < today),
        "follow_up_due_today": bool(follow_up_active and follow_up == today),
        "days_since_sent": max(0, (today - sent).days) if sent else None,
    })
    return item


def summarize_bids(rows: list[dict], today: date) -> dict:
    """Numbers for the tiles at the top of the Bid Tracker page (rows already decorated)."""
    week_end = today + timedelta(days=6)
    month = today.strftime("%Y-%m")

    open_rows = [row for row in rows if row["bid_status"] in OPEN_BID_STATUSES]
    due_this_week = 0
    for row in open_rows:
        due = _as_date(row.get("bid_due_date"))
        if due and today <= due <= week_end:
            due_this_week += 1
    sent_rows = [row for row in rows if row["bid_status"] == "Sent"]

    def decided_this_month(status: str) -> int:
        return sum(
            1 for row in rows
            if row["bid_status"] == status and str(row.get("won_lost_at") or "").startswith(month)
        )

    won_month = decided_this_month("Won")
    lost_month = decided_this_month("Lost")
    won_all = sum(1 for row in rows if row["bid_status"] == "Won")
    lost_all = sum(1 for row in rows if row["bid_status"] == "Lost")

    def rate(won: int, lost: int) -> float | None:
        return round(won / (won + lost), 4) if (won + lost) else None

    return {
        "open": len(open_rows),
        "overdue": sum(1 for row in open_rows if row["due_overdue"]),
        "due_this_week": due_this_week,
        "sent_awaiting": len(sent_rows),
        "follow_ups_due": sum(1 for row in sent_rows if row["follow_up_overdue"] or row["follow_up_due_today"]),
        "won_this_month": won_month,
        "lost_this_month": lost_month,
        "win_rate_this_month": rate(won_month, lost_month),
        "won_all_time": won_all,
        "lost_all_time": lost_all,
        "win_rate_all_time": rate(won_all, lost_all),
    }
