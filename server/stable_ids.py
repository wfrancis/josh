"""
Stable identities for rows that used to be found by position or content.

- **Material lines** keep ``job_materials.uid`` for life: "m12" for lines
  that existed before uids (their id), "m" + 8 random hex characters for new
  ones. A uid the browser sends back is kept.
- **Sundry and labor lines** are matched by ``line_key``: the material line
  they belong to plus their name ("m12|thinset"), with "#2", "#3", ... for
  repeats in the order the calculator lists them. A save updates the lines
  whose key is still there, adds the new ones and removes the rest, so the
  history shows what really changed instead of "everything removed and added".
- **Proposal bundles** carry a ``uid`` ("b_" + random) that survives
  renames, saves and regenerate. Proposals saved before uids get a
  deterministic one: "b_" + sha1("<job id>|<position>|<bundle name>")[:10].

Nothing here touches the database; models.py and main.py call these.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections import Counter

# Bookkeeping columns on job_materials / job_sundries / job_labor. They say
# when and by whom a row last changed; they are never part of the row's
# content (history, fingerprints and saved proposals leave them out).
ROW_META_COLUMNS = ("row_version", "updated_at", "updated_by")
# Identity keys: who a row is, not what it says.
IDENTITY_KEYS = ("uid", "line_key")

_UID_RE = re.compile(r"[A-Za-z0-9_.:-]{1,64}")


def clean_uid(value) -> str | None:
    """A usable uid from a client or stored row, else None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text if _UID_RE.fullmatch(text) else None


def new_uid(prefix: str, taken=()) -> str:
    """prefix + 8 random hex characters, not in ``taken``. Never all digits,
    so it can't clash with a backfilled "m<id>"."""
    taken = taken if isinstance(taken, (set, frozenset, dict)) else set(taken)
    while True:
        tail = uuid.uuid4().hex[:8]
        candidate = prefix + tail
        if not tail.isdigit() and candidate not in taken:
            return candidate


def new_material_uid(taken=()) -> str:
    return new_uid("m", taken)


def new_bundle_uid(taken=()) -> str:
    return new_uid("b_", taken)


def without_row_meta(row: dict) -> dict:
    """The row without its bookkeeping columns (row_version, updated_at, updated_by)."""
    return {key: value for key, value in row.items() if key not in ROW_META_COLUMNS}


def without_identity(value):
    """A copy with uids, line keys and row bookkeeping removed at any depth
    (for fingerprints that must not change when only identities do)."""
    if isinstance(value, dict):
        return {
            key: without_identity(item)
            for key, item in value.items()
            if key not in IDENTITY_KEYS and key not in ROW_META_COLUMNS
        }
    if isinstance(value, list):
        return [without_identity(item) for item in value]
    return value


# ── Sundry and labor line keys ────────────────────────────────────────────────
def _name_part(text) -> str:
    # Same identity as reproducibility._sundry_key / _labor_identity (trimmed,
    # lower case), with runs of spaces treated as one.
    return " ".join(str(text or "").split()).lower()


def material_ref(material_id, uid_by_material_id: dict) -> str:
    """How a line key names its material line: the material's uid, "#<id>"
    for an id this bid doesn't have, or "job" for bid-wide lines."""
    if material_id in (None, ""):
        return "job"
    try:
        number = int(material_id)
    except (TypeError, ValueError):
        return f"#{material_id}"
    return uid_by_material_id.get(number) or f"#{number}"


def line_key_base(material_id, name, uid_by_material_id: dict) -> str:
    return f"{material_ref(material_id, uid_by_material_id)}|{_name_part(name)}"


def assign_line_keys(rows, name_field: str, uid_by_material_id: dict, taken=()) -> list[str]:
    """One line key per row, in order: "<material>|<name>", then "#2", "#3"
    for repeats. Keys in ``taken`` are skipped (used when filling in keys
    next to rows that already have one)."""
    counts: Counter = Counter()
    used = set(taken)
    keys = []
    for row in rows:
        base = line_key_base(row.get("material_id"), row.get(name_field), uid_by_material_id)
        counts[base] += 1
        number = counts[base]
        key = base if number == 1 else f"{base}#{number}"
        while key in used:
            number += 1
            counts[base] = number
            key = f"{base}#{number}"
        used.add(key)
        keys.append(key)
    return keys


# ── Proposal bundle uids ──────────────────────────────────────────────────────
def backfill_bundle_uid(job_id, index: int, bundle_name) -> str:
    """The uid a bundle saved before uids gets (the same every time)."""
    digest = hashlib.sha1(f"{job_id}|{index}|{bundle_name or ''}".encode("utf-8")).hexdigest()[:10]
    return f"b_{digest}"


def backfill_proposal_bundle_uids(job_id, proposal) -> bool:
    """Give every bundle of a saved proposal that has no uid its deterministic
    one. Running it again changes nothing. True when something changed."""
    if not isinstance(proposal, dict) or not isinstance(proposal.get("bundles"), list):
        return False
    bundles = proposal["bundles"]
    taken = set()
    missing = []
    for index, bundle in enumerate(bundles):
        if not isinstance(bundle, dict):
            continue
        uid = clean_uid(bundle.get("uid"))
        if uid and uid not in taken:
            taken.add(uid)
        else:
            missing.append(index)
    for index in missing:
        bundle = bundles[index]
        base = backfill_bundle_uid(job_id, index, bundle.get("bundle_name"))
        uid, number = base, 2
        while uid in taken:
            uid, number = f"{base}-{number}", number + 1
        bundle["uid"] = uid
        taken.add(uid)
    return bool(missing)


def _material_key(item: dict) -> str:
    # Same as reproducibility._material_key.
    return str(item.get("item_code") or item.get("id") or item.get("material_id") or "")


def bundle_signature(bundle: dict) -> tuple[str, ...]:
    """The bundle's material codes, sorted (same as reproducibility._bundle_signature)."""
    return tuple(sorted(
        code for code in (
            _material_key(item) for item in (bundle.get("materials") or []) if isinstance(item, dict)
        ) if code
    ))


def carry_bundle_uids(previous_bundles, bundles) -> dict:
    """Give every bundle in ``bundles`` (changed in place) a uid.

    A uid the client sent back is kept (the first bundle using it keeps it;
    a copy made from another bundle gets its own). A bundle without one takes
    the uid of the previous bundle it matches, tried in this order: same
    materials and name, same materials, same name (bundles with no material
    codes), same place with the same materials. Anything left gets a new uid.

    Returns {"kept": n, "matched": n, "new": n}.
    """
    counts = {"kept": 0, "matched": 0, "new": 0}
    bundles = bundles if isinstance(bundles, list) else []
    previous = [bundle for bundle in (previous_bundles or []) if isinstance(bundle, dict)]
    claimed: set[str] = set()
    pending: list[int] = []
    for index, bundle in enumerate(bundles):
        if not isinstance(bundle, dict):
            continue
        uid = clean_uid(bundle.get("uid"))
        if uid and uid not in claimed:
            bundle["uid"] = uid
            claimed.add(uid)
            counts["kept"] += 1
        else:
            bundle.pop("uid", None)
            pending.append(index)

    def available():
        return [
            (position, candidate) for position, candidate in enumerate(previous)
            if clean_uid(candidate.get("uid")) and candidate["uid"] not in claimed
        ]

    def same_materials_and_name(bundle, _index, _position, candidate):
        signature = bundle_signature(bundle)
        return bool(signature) and bundle_signature(candidate) == signature \
            and candidate.get("bundle_name") == bundle.get("bundle_name")

    def same_materials(bundle, _index, _position, candidate):
        signature = bundle_signature(bundle)
        return bool(signature) and bundle_signature(candidate) == signature

    def same_name(bundle, _index, _position, candidate):
        return (
            not bundle_signature(bundle) and not bundle_signature(candidate)
            and bool(str(bundle.get("bundle_name") or "").strip())
            and candidate.get("bundle_name") == bundle.get("bundle_name")
        )

    def same_place(bundle, index, position, candidate):
        return index == position and bundle_signature(candidate) == bundle_signature(bundle)

    for rule in (same_materials_and_name, same_materials, same_name, same_place):
        still_pending = []
        for index in pending:
            bundle = bundles[index]
            found = [candidate for position, candidate in available() if rule(bundle, index, position, candidate)]
            if len(found) == 1:
                bundle["uid"] = found[0]["uid"]
                claimed.add(found[0]["uid"])
                counts["matched"] += 1
            else:
                still_pending.append(index)
        pending = still_pending

    for index in pending:
        uid = new_bundle_uid(claimed)
        bundles[index]["uid"] = uid
        claimed.add(uid)
        counts["new"] += 1
    return counts
