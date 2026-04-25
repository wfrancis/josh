"""
Audit trace helpers for deterministic calculation receipts.

Calculators can accept an AuditTraceBuilder and call ``record`` at the point
where they produce a value. The builder stays in memory until the API handler
persists the run, which keeps existing calculation code easy to call.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any


def _jsonable(value: Any) -> Any:
    """Return a JSON-safe value without surprising callers."""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


class AuditTraceBuilder:
    """Collect calculation trace rows for one calculation run."""

    def __init__(self, job_id: int, run_id: int | None = None, default_source: str = "rule_engine"):
        self.job_id = job_id
        self.run_id = run_id
        self.default_source = default_source
        self._records: list[dict] = []
        self.created_at = datetime.now().isoformat()

    @property
    def records(self) -> list[dict]:
        return list(self._records)

    def record(
        self,
        *,
        entity_type: str,
        output_field: str,
        formula: str,
        inputs: dict | None = None,
        result: Any = None,
        entity_id: Any = None,
        entity_key: str | None = None,
        rule_id: str | None = None,
        source: str | None = None,
        warnings: list[str] | str | None = None,
    ) -> dict:
        if warnings is None:
            warning_list: list[str] = []
        elif isinstance(warnings, str):
            warning_list = [warnings]
        else:
            warning_list = [str(w) for w in warnings if w is not None]

        result_value = None
        if isinstance(result, (int, float)) and not isinstance(result, bool):
            result_value = float(result)

        record = {
            "job_id": self.job_id,
            "run_id": self.run_id,
            "entity_type": entity_type,
            "entity_id": None if entity_id is None else str(entity_id),
            "entity_key": entity_key,
            "output_field": output_field,
            "formula": formula,
            "inputs": _jsonable(inputs or {}),
            "result": _jsonable(result),
            "result_value": result_value,
            "rule_id": rule_id,
            "source": source or self.default_source,
            "warnings": warning_list,
            "created_at": datetime.now().isoformat(),
        }
        self._records.append(record)
        return record

    def manual_override(
        self,
        *,
        entity_type: str,
        output_field: str,
        value: Any,
        entity_id: Any = None,
        entity_key: str | None = None,
        prior_value: Any = None,
        note: str | None = None,
    ) -> dict:
        inputs = {"prior_value": prior_value}
        if note:
            inputs["note"] = note
        return self.record(
            entity_type=entity_type,
            entity_id=entity_id,
            entity_key=entity_key,
            output_field=output_field,
            formula="manual override",
            inputs=inputs,
            result=value,
            source="manual_override",
        )

    def summary(self) -> dict:
        by_entity: dict[str, int] = {}
        by_source: dict[str, int] = {}
        warning_count = 0
        for record in self._records:
            entity_type = record.get("entity_type") or "unknown"
            source = record.get("source") or "unknown"
            by_entity[entity_type] = by_entity.get(entity_type, 0) + 1
            by_source[source] = by_source.get(source, 0) + 1
            warning_count += len(record.get("warnings") or [])
        return {
            "trace_count": len(self._records),
            "by_entity_type": by_entity,
            "by_source": by_source,
            "warning_count": warning_count,
        }


def trace_summary(records: list[dict]) -> dict:
    builder = AuditTraceBuilder(job_id=0)
    builder._records = list(records)
    return builder.summary()
