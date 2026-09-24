"""
Pricing of material lines, shared by every path that changes them.

- ``normalize_material_row(base, incoming)``: a saved line (``base``; {} for
  a new line) with changes applied (``incoming``), its order quantity and
  extended cost worked out the way the materials table's save always has
  (PUT /api/jobs/{id}/materials).
- Compare-and-swap patches for slow steps (AI quote matching, vendor
  detection, AI price estimates). The step reads the lines and works without
  holding the bid; then, inside ``job_write``, ``apply_material_patches``
  saves only what it changed, and only on lines that still have the values it
  read. A line someone changed (or removed) in the meantime keeps their
  change and is reported as a conflict, in the response and in the history.
"""

from __future__ import annotations

import math

import audit
import models
from material_pricing import order_qty_is_lf, transition_pieces
from stable_ids import ROW_META_COLUMNS

VENDOR_EVIDENCE_SOURCES = frozenset({"vendor_quote", "vendor_quote_override"})


def as_number(value):
    """A finite number rounded to 4 places, or None (same as main._as_number)."""
    try:
        if value is None or value == "":
            return None
        number = float(value)
        if not math.isfinite(number):
            return None
        return round(number, 4)
    except (TypeError, ValueError):
        return None


def normalize_material_row(base: dict | None, incoming: dict, *, recounted: list | None = None) -> dict:
    """The line ``base`` with ``incoming`` applied and priced.

    Fields in ``incoming`` that are None keep the saved value (price_source
    can be cleared). A new material type marks the line as classified by a
    person. Quote evidence is dropped unless the price comes from a vendor
    quote. A typed price clears a "needs price / quote" marker. order_qty
    defaults to installed_qty x (1 + waste_pct); extended cost is
    order_qty x unit_price, except a typed extended cost on a manual price and
    stick-priced transitions (price book / transition rule), which bill whole
    sticks.

    When a stored stick line's count or total changes without the estimator
    editing that line, a note is appended to ``recounted`` (if given).
    """
    base = base or {}
    material = incoming or {}
    merged = {**base, **{key: value for key, value in material.items() if value is not None}}
    if "price_source" in material:
        merged["price_source"] = material.get("price_source")
    if material.get("material_type") and base.get("material_type") != material.get("material_type"):
        merged["ai_confidence"] = 1.0
    if str(merged.get("price_source") or "").strip().lower() not in VENDOR_EVIDENCE_SOURCES:
        merged["quote_source_hash"] = None
        merged["quote_file_name"] = None

    waste_pct = merged.get("waste_pct", 0)
    installed_qty = merged.get("installed_qty", 0)
    unit_price = merged.get("unit_price", 0)
    if not merged.get("price_source") and (as_number(unit_price) or 0) <= 0:
        merged["quote_status"] = None
    # A typed price replaces the "needs price/quote" marker on the edited line.
    if (
        str(merged.get("price_source") or "").strip().lower() == "manual"
        and (as_number(unit_price) or 0) > 0
        and merged.get("quote_status") in ("needs_quote", "needs_price")
        and (
            str(base.get("price_source") or "").strip().lower() != "manual"
            or abs((as_number(base.get("unit_price")) or 0) - (as_number(unit_price) or 0)) > 0.005
        )
    ):
        merged["quote_status"] = "manual"
    order_qty_given = "order_qty" in material and material["order_qty"] is not None
    order_qty = (
        material["order_qty"]
        if order_qty_given
        else installed_qty * (1 + waste_pct)
    )

    if material.get("price_source") == "manual" and material.get("extended_cost") is not None:
        extended_cost = material["extended_cost"]
    elif (
        merged.get("price_source") in ("price_book", "default_rule")
        and (merged.get("material_type") or "").lower() == "transitions"
    ):
        # EA lines (Schluter sticks priced at RFMS upload) already store
        # order_qty in pieces; dividing by the stick length again would
        # under-price the line. Same rule as the EA skip in api_generate_proposal.
        # An EA row whose order_qty equals its LF figure was saved in LF by
        # the old editor, so its sticks are recounted from that LF. Storage is
        # judged on the saved row, as the editor does (a new LF can equal the
        # old stick count). An incoming order_qty equal to the incoming row's
        # own LF figure is still LF: every reader (bid assembler, PDF gate,
        # editor) reads it back as LF, and a client that saved from a stale
        # copy (autosave re-send after this handler converted a legacy row)
        # sends exactly that.
        piece_qty = str(merged.get("unit") or "").strip().upper() == "EA"
        stored_row = base or merged
        if (
            piece_qty
            and order_qty_given
            and not order_qty_is_lf(stored_row, stored_row.get("order_qty"))
            and not order_qty_is_lf(merged, order_qty)
        ):
            pieces = order_qty
        else:
            pieces = transition_pieces(order_qty, merged.get("vendor"), merged.get("fixture_count", 0))
            if piece_qty:
                # order_qty was in LF; store the stick count for an EA line
                order_qty = pieces
        extended_cost = pieces * unit_price
        # Note stored EA rows whose sticks/total the server changed without
        # the estimator editing that line, so repriced jobs can be reviewed.
        if (
            recounted is not None
            and piece_qty
            and base
            and abs((as_number(material.get("order_qty")) or 0) - (as_number(base.get("order_qty")) or 0)) <= 0.005
            and abs((as_number(unit_price) or 0) - (as_number(base.get("unit_price")) or 0)) <= 0.005
            and (
                abs(round(order_qty, 2) - (as_number(base.get("order_qty")) or 0)) > 0.005
                or abs(round(extended_cost, 2) - (as_number(base.get("extended_cost")) or 0)) > 0.005
            )
        ):
            recounted.append({
                "item_code": merged.get("item_code"),
                "description": merged.get("description"),
                "order_qty_before": base.get("order_qty"),
                "order_qty_after": round(order_qty, 2),
                "extended_cost_before": base.get("extended_cost"),
                "extended_cost_after": round(extended_cost, 2),
            })
    else:
        extended_cost = order_qty * unit_price

    merged["order_qty"] = round(order_qty, 2)
    merged["extended_cost"] = round(extended_cost, 2)
    return merged


# ── Compare-and-swap patches ─────────────────────────────────────────────────
# What a quote match or a price estimate reads to price a line. If any of
# these changed while it was working, its answer for that line is stale.
PRICE_INPUT_FIELDS = (
    "item_code", "description", "material_type", "unit", "installed_qty", "waste_pct",
    "order_qty", "unit_price", "price_source", "quote_status", "vendor", "fixture_count",
)
# Never patched: who the line is and its bookkeeping.
_UNPATCHABLE = frozenset({"id", "job_id", "uid", *ROW_META_COLUMNS})


def _line_label(row: dict) -> str:
    return str(row.get("item_code") or row.get("description") or f"line {row.get('id')}")


def material_patch(row: dict, changes: dict, *, depends_on=PRICE_INPUT_FIELDS,
                   normalize: bool = False) -> dict:
    """A patch for one line as it was read (``row``): set ``changes`` only if
    the line still has the values ``row`` had for the changed fields and for
    ``depends_on``. With ``normalize``, the line is re-priced with
    normalize_material_row after the change (order qty, extended cost)."""
    changes = {key: value for key, value in changes.items() if key not in _UNPATCHABLE}
    fields = list(dict.fromkeys([*changes, *depends_on]))
    return {
        "material_id": row.get("id"),
        "uid": row.get("uid"),
        "label": _line_label(row),
        "base": {field: row.get(field) for field in fields},
        "set": changes,
        "normalize": bool(normalize),
    }


def patches_from_rows(before_rows: list[dict], after_rows: list[dict], *,
                      depends_on=PRICE_INPUT_FIELDS) -> list[dict]:
    """One patch per line a slow step changed, from the copy it read
    (``before_rows``) and its result (``after_rows``), matched by id. Only
    stored fields (keys of the row as read) are patched, never transient extras."""
    before_by_id = {}
    for row in before_rows or []:
        try:
            before_by_id[int(row.get("id"))] = row
        except (TypeError, ValueError):
            continue
    patches = []
    for row in after_rows or []:
        try:
            base = before_by_id.get(int(row.get("id")))
        except (TypeError, ValueError):
            continue
        if base is None:
            continue
        changes = {
            key: row.get(key)
            for key in base
            if key not in _UNPATCHABLE and key in row and not audit.values_equal(base.get(key), row.get(key))
        }
        if changes:
            patches.append(material_patch(base, changes, depends_on=depends_on))
    return patches


def _field_names(fields) -> str:
    names = [str(field).replace("_", " ") for field in fields]
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


def apply_material_patches(tx, patches) -> dict:
    """Apply compare-and-swap patches to the bid's lines, inside
    ``job_write`` (uses tx.conn and tx.job_id).

    A patch applies only if its line still exists and still has every value
    in the patch's ``base``; otherwise it is a conflict and the line is left
    as it is. Conflicts go into the history entry (extra.conflicts, and the
    entry is written even if nothing else changed).

    Returns {"applied": [{material_id, uid, item_code, fields}],
             "conflicts": [{material_id, uid, item_code, reason, fields, message}]}.
    """
    conn, job_id = tx.conn, tx.job_id
    current = [
        dict(row)
        for row in conn.execute("SELECT * FROM job_materials WHERE job_id=? ORDER BY id", (job_id,)).fetchall()
    ]
    by_id = {int(row["id"]): row for row in current}
    by_uid = {row["uid"]: row for row in current if row.get("uid")}
    applied: list[dict] = []
    conflicts: list[dict] = []
    touched = False
    for patch in patches or []:
        try:
            row = by_id.get(int(patch.get("material_id")))
        except (TypeError, ValueError):
            row = None
        if row is None and patch.get("uid"):
            row = by_uid.get(patch["uid"])
        label = patch.get("label") or "A line"
        if row is None:
            conflicts.append({
                "material_id": patch.get("material_id"),
                "uid": patch.get("uid"),
                "item_code": label,
                "reason": "removed",
                "fields": [],
                "message": f"{label} was removed while this was running, so it was left out.",
            })
            continue
        stale = [
            field for field, value in (patch.get("base") or {}).items()
            if not audit.values_equal(row.get(field), value)
        ]
        if stale:
            conflicts.append({
                "material_id": row["id"],
                "uid": row.get("uid"),
                "item_code": label,
                "reason": "changed",
                "fields": stale,
                "current": {field: row.get(field) for field in stale},
                "not_saved": dict(patch.get("set") or {}),
                "message": (
                    f"Someone changed the {_field_names(stale)} on {label} while this was running, "
                    "so their change was kept and this one was not saved."
                ),
            })
            continue
        changes = {key: value for key, value in (patch.get("set") or {}).items() if key not in _UNPATCHABLE}
        updated = normalize_material_row(row, changes) if patch.get("normalize") else {**row, **changes}
        fields = sorted(
            key for key, value in updated.items()
            if key not in _UNPATCHABLE and not audit.values_equal(row.get(key), value)
        )
        if fields:
            row.update({key: updated[key] for key in fields})
            touched = True
        applied.append({"material_id": row["id"], "uid": row.get("uid"), "item_code": label, "fields": fields})
    if touched:
        models.save_materials(job_id, current, conn=conn)
    if conflicts:
        tx.extra.setdefault("conflicts", []).extend(conflicts)
        tx.force_record()
    return {"applied": applied, "conflicts": conflicts}


def conflict_note(conflicts: list[dict]) -> str:
    """" (1 line skipped: someone changed it meanwhile)" for history summaries."""
    if not conflicts:
        return ""
    count = len(conflicts)
    return f" ({count} line{'' if count == 1 else 's'} skipped: someone changed {'it' if count == 1 else 'them'} meanwhile)"
