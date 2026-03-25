"""
Fuzzy-match job project names to Dropbox bid folder names.

The actual file reading happens in the browser via the File System Access API.
This module only handles the folder name matching logic server-side.
"""

import difflib
import re


def _normalize_for_match(name: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace for fuzzy matching."""
    return re.sub(r'[^a-z0-9 ]', '', name.lower()).strip()


def match_folder(project_name: str, gc_name: str, folder_names: list[str]) -> dict | None:
    """
    Fuzzy-match a job's project_name (and optionally gc_name) against
    a list of folder names from the bid folder.

    Folder convention: "GC Name - Project Name"
    e.g. "Brinkmann - Hanger at Central Park"

    Returns: {folder_name, score} or None
    """
    if not folder_names:
        return None

    project_norm = _normalize_for_match(project_name)
    gc_norm = _normalize_for_match(gc_name) if gc_name else ""

    best = None
    best_score = 0.0

    for folder_name in folder_names:
        folder_norm = _normalize_for_match(folder_name)

        # Split on " - " to get GC and project parts
        parts = folder_name.split(" - ", 1)
        folder_gc_norm = _normalize_for_match(parts[0]) if len(parts) > 1 else ""
        folder_project_norm = _normalize_for_match(parts[1]) if len(parts) > 1 else folder_norm

        # Score 1: project_name vs full folder name
        s1 = difflib.SequenceMatcher(None, project_norm, folder_norm).ratio()

        # Score 2: project_name vs project part (after the dash)
        s2 = difflib.SequenceMatcher(None, project_norm, folder_project_norm).ratio()

        # Score 3: combined GC + project match
        s3 = 0.0
        if gc_norm and folder_gc_norm:
            gc_score = difflib.SequenceMatcher(None, gc_norm, folder_gc_norm).ratio()
            proj_score = difflib.SequenceMatcher(None, project_norm, folder_project_norm).ratio()
            s3 = (gc_score * 0.3) + (proj_score * 0.7)

        # Score 4: substring containment bonus
        s4 = 0.0
        if project_norm in folder_project_norm or folder_project_norm in project_norm:
            s4 = 0.85
        if project_norm in folder_norm or folder_norm in project_norm:
            s4 = max(s4, 0.80)

        score = max(s1, s2, s3, s4)

        if score > best_score:
            best_score = score
            best = {
                "folder_name": folder_name,
                "score": round(score, 3),
            }

    if best and best_score >= 0.6:
        return best
    return None
