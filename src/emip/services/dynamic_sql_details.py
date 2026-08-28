"""Stable query representation for persisted dynamic SQL evidence."""

from __future__ import annotations

import json

from emip.domain import MetadataObject


def dynamic_sql_details(item: MetadataObject) -> dict[str, object] | None:
    """Decode additive properties without trusting their serialized shape."""

    properties = {prop.property_name: prop.property_value for prop in item.properties}
    classification = properties.get("dynamic_sql.classification")
    if classification is None:
        return None
    evidence: list[dict[str, object]] = []
    serialized = properties.get("dynamic_sql.evidence")
    if serialized:
        try:
            decoded = json.loads(serialized)
        except (TypeError, ValueError):
            decoded = []
        if isinstance(decoded, list):
            evidence = [value for value in decoded if isinstance(value, dict)]
    return {
        "classification": classification,
        "unresolved_reason": properties.get("dynamic_sql.unresolved_reason"),
        "evidence": evidence,
    }
